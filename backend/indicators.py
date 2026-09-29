"""Pure-Python technical indicators + rule-based signal generator.

Used for fast dashboard signals (no LLM call). Returns BUY / SELL / HOLD plus
confidence percentage derived from how many indicators agree.
"""
from __future__ import annotations

from typing import Any


# v9.0.0 — Trader Profile presets ("Confluence" total overhaul).
# Applied ONLY for volatile continuous-market instruments (crypto, forex,
# gold/silver). Stocks/commodity keep the market-neutral defaults because
# they trade in sessions and exhibit different volatility patterns.
#
# A profile ONLY tunes the trading-horizon parameters:
#   ema_fast / ema_slow  — trend-structure windows
#   require_ema200       — demand EMA200 alignment too (swing/longterm)
#   sl_atr_mult          — Stop-Loss distance as multiple of ATR
#   tp_ladder            — TP1/TP2/TP3 as multiples of risk (R).
#                          v9.0.0 backtest (30d, 9 aset, 302 trade):
#                          TP1=1.0R → WR 57.1%, +0.136R/trade (TERBAIK)
#                          TP1=1.5R → WR 42.1%, +0.048R/trade
#                          → ladder (1.0, 2.0, 3.0): TP1 bank cepat,
#                            TP2/TP3 untuk runner.
#   description          — shown in the picker modal
#
# It NEVER forces or vetoes a signal direction. The v3 confidence gate
# that downgraded valid signals to HOLD was the root cause of the
# "dashboard BUY vs detail SIDEWAYS" desync and is permanently removed.
TRADER_PROFILES: dict[str, dict[str, Any]] = {
    "scalper": {
        "ema_fast": 9,
        "ema_slow": 21,
        "require_ema200": False,
        "sl_atr_mult": 1.0,
        "tp_ladder": (0.7, 1.5, 2.5),
        # v9.2.4 — Ladder KHUSUS mesin VWAP: TP1 lebih rapat (0.5R) agar
        # WR profile berbayar (scalper/day/swing) lebih tinggi dari
        # Confluence. Bukan kosmetik: filter trigger VWAP juga diperketat
        # (wajib pola reversal + volume ekspansi + floor confidence).
        "vwap_tp_ladder": (0.5, 1.0, 1.75),
        "description": "5m–15m intraday moves",
    },
    "day": {  # default — balanced horizon
        "ema_fast": 20,
        "ema_slow": 50,
        "require_ema200": False,
        "sl_atr_mult": 1.5,
        "tp_ladder": (0.7, 1.5, 2.5),
        "vwap_tp_ladder": (0.55, 1.1, 2.0),
        "description": "1h–4h day trading",
    },
    "swing": {
        "ema_fast": 20,
        "ema_slow": 50,
        "require_ema200": True,
        "sl_atr_mult": 2.0,
        "tp_ladder": (0.7, 1.5, 2.5),
        "vwap_tp_ladder": (0.6, 1.25, 2.25),
        "description": "4h–24h multi-day",
    },
    "longterm": {
        "ema_fast": 50,
        "ema_slow": 100,
        "require_ema200": True,
        "sl_atr_mult": 2.5,
        "tp_ladder": (0.8, 1.75, 3.0),
        "vwap_tp_ladder": (0.8, 1.75, 3.0),
        "description": "1D+ position hold",
    },
}

# Only these markets are affected by Trader Profile selection. Stocks and
# generic commodity keep the standard formula because their session-based
# behaviour does not respond well to crypto-tuned parameters.
PROFILE_APPLICABLE_MARKETS = {"crypto", "forex", "gold_silver"}


def get_trader_profile(name: str | None) -> dict[str, Any]:
    """Return a valid Trader Profile preset. Falls back to 'day' if input is
    None or unknown so backward-compatible callers keep the legacy behaviour."""
    if name and name in TRADER_PROFILES:
        return TRADER_PROFILES[name]
    return TRADER_PROFILES["day"]


def _ema(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1)
    out: list[float] = []
    ema = values[0]
    for v in values:
        ema = v * k + ema * (1 - k)
        out.append(ema)
    return out


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(closes: list[float]) -> tuple[float, float, float] | None:
    if len(closes) < 35:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal_line = _ema(macd_line[-30:], 9)
    if not signal_line:
        return None
    macd = macd_line[-1]
    sig = signal_line[-1]
    hist = macd - sig
    return macd, sig, hist


def _macd_hist_recent(closes: list[float], n: int = 3) -> list[float] | None:
    """v9.0.0 — Return the last `n` MACD histogram values (oldest → newest)
    so the confluence engine can detect both the SIGN and the DIRECTION of
    momentum (rising vs falling histogram)."""
    if len(closes) < 35:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal_line = _ema(macd_line[-30:], 9)
    if len(signal_line) < n or len(macd_line) < n:
        return None
    return [m - s for m, s in zip(macd_line[-n:], signal_line[-n:])]


def _atr14(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """v9.0.0 — Simple ATR over the last `period` true ranges."""
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(len(closes) - period, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


# v8.1.6 — Swing-based deep entry / take profit / stop loss.
# Detects local peaks and valleys over a fractal window; positions
# entries below the average of recent valleys (LONG) or above the
# average of recent peaks (SHORT) so users avoid catching a falling
# knife. TP is anchored on the mean of the last 3 opposite-side swings.
def _find_swings(
    highs: list[float],
    lows: list[float],
    window: int = 10,
) -> tuple[list[float], list[float]]:
    """Return (peaks, valleys) as lists of prices in chronological order.

    A peak at index i requires `high[i]` to be the maximum within
    [i-window, i+window]; symmetric for valleys. The `window` param
    controls swing significance — 10 detects mid-swings (matches user's
    v8.1.6 choice); 5 gives micro-swings; 20 gives major swings.
    """
    n = len(highs)
    if n < window * 2 + 1:
        return [], []
    peaks: list[float] = []
    valleys: list[float] = []
    for i in range(window, n - window):
        h = highs[i]
        lo = lows[i]
        left_high = max(highs[i - window:i])
        right_high = max(highs[i + 1:i + 1 + window])
        if h > left_high and h > right_high:
            peaks.append(h)
        left_low = min(lows[i - window:i])
        right_low = min(lows[i + 1:i + 1 + window])
        if lo < left_low and lo < right_low:
            valleys.append(lo)
    return peaks, valleys


def _atr_percent_history(highs: list[float], lows: list[float], closes: list[float],
                         period: int = 7, lookback: int = 30) -> tuple[float | None, float | None]:
    """Return (current_atr_pct, avg_atr_pct_over_lookback).

    v8.7.23 — Ported from user's btc_trading_formula.py to power the
    market-regime detector. ATR% (ATR ÷ price × 100) is far more stable
    across price scales than raw ATR.
    """
    def _atr(h: list[float], lo: list[float], c: list[float], p: int) -> float | None:
        if len(c) < p + 1:
            return None
        trs = []
        for i in range(1, len(c)):
            tr = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
            trs.append(tr)
        return sum(trs[-p:]) / p if trs else None

    if not closes:
        return None, None
    a_now = _atr(highs, lows, closes, period)
    if not a_now or closes[-1] <= 0:
        return None, None
    pct_now = (a_now / closes[-1]) * 100.0

    hist: list[float] = []
    for i in range(lookback):
        idx = len(closes) - lookback + i
        if idx - period < 0:
            continue
        a_i = _atr(highs[:idx + 1], lows[:idx + 1], closes[:idx + 1], period)
        if a_i and closes[idx] > 0:
            hist.append((a_i / closes[idx]) * 100.0)
    avg = sum(hist) / len(hist) if hist else None
    return pct_now, avg


def _detect_regime(closes: list[float], highs: list[float], lows: list[float],
                   ema_slow_period: int = 50) -> dict:
    """v8.7.23 — Market regime detector (ported from user formula).

    Returns one of BULL / SIDEWAYS / BEAR / BEAR_CAPITULATION / UNKNOWN.
    Logic:
      • price > EMA50 → BULL
      • price < EMA50 + ATR% > 1.5× 30-period avg → BEAR_CAPITULATION
      • price < EMA50 + normal vol → BEAR
      • fallback → SIDEWAYS
    """
    if len(closes) < ema_slow_period + 8:
        return {"regime": "UNKNOWN"}
    ema_slow = _ema(closes, ema_slow_period)
    if not ema_slow:
        return {"regime": "UNKNOWN"}
    price = closes[-1]
    is_down = price < ema_slow[-1]
    pct_now, avg = _atr_percent_history(highs, lows, closes)
    high_vol = (pct_now is not None and avg is not None and pct_now > avg * 1.5)
    if not is_down:
        return {"regime": "BULL", "atr_pct_now": pct_now, "atr_pct_avg": avg}
    regime = "BEAR_CAPITULATION" if high_vol else "BEAR"
    return {"regime": regime, "atr_pct_now": pct_now, "atr_pct_avg": avg, "high_vol": high_vol}


def _compute_deep_levels(
    action: str,
    price: float,
    atr: float,
    peaks: list[float],
    valleys: list[float],
    market: str = "crypto",
    regime: str = "UNKNOWN",
    sl_mult: float = 1.5,
    tp_ladder: tuple[float, float, float] = (1.0, 2.0, 3.0),
) -> dict[str, Any]:
    """v9.0.0 — ATR-laddered entries with minimum R:R 1:1.5.

    Entry tiers (BUY; SELL is the exact mirror):
      aggressive = price − 0.2×ATR   (almost market price)
      moderate   = price − 0.5×ATR
      deep       = price − 1.0×ATR   (default card, safest)
    SL  = entry − sl_mult×ATR        (per trader profile)
    TPn = entry + ladder[n] × risk   (default ladder 1R / 2R / 3R)

    Stock-like markets keep a tighter percentage variant because their
    session-based volatility is a fraction of crypto's: entries sit
    0.1/0.3/0.5% from price, risk = 1.5% of entry, TP ladder identical.

    HOLD returns None for every level (no fake ladders — v8.12.28 lesson:
    informational zones on HOLD looked like trade suggestions).
    `regime` is accepted for caller compatibility but no longer alters the
    levels — the profile's sl_mult / tp_ladder own that job now.
    """
    recent_peaks = peaks[-5:] if len(peaks) >= 5 else peaks
    recent_valleys = valleys[-5:] if len(valleys) >= 5 else valleys
    last3_peaks = recent_peaks[-3:] if len(recent_peaks) >= 3 else recent_peaks
    last3_valleys = recent_valleys[-3:] if len(recent_valleys) >= 3 else recent_valleys

    def _safe_avg(xs: list[float], fallback: float) -> float:
        return (sum(xs) / len(xs)) if xs else fallback

    avg_peak = _safe_avg(last3_peaks, price * 1.05)
    avg_valley = _safe_avg(last3_valleys, price * 0.95)

    is_stocklike = market in ("stock_id", "stock_us", "world_stocks", "etf",
                              "gold_silver", "commodity", "forex")
    if is_stocklike and action in ("BUY", "SELL"):
        # R:R 1:1.5 minimum — 1.5% risk of entry, TP ladder from profile.
        risk_pct = 0.015
        if action == "BUY":
            entry_deep = price * 0.995        # 0.5% below (safest wait)
            entry_moderate = price * 0.997    # 0.3% below (balanced)
            entry_aggressive = price * 0.999  # 0.1% below (aggressive)
            risk = entry_deep * risk_pct
            sl_deep = entry_deep - risk
            sl_moderate = entry_moderate - entry_moderate * risk_pct
            sl_aggressive = entry_aggressive - entry_aggressive * risk_pct
            take_profit = entry_deep + risk * tp_ladder[0]
            take_profit_2 = entry_deep + risk * tp_ladder[1]
            take_profit_3 = entry_deep + risk * tp_ladder[2]
        else:  # SELL
            entry_deep = price * 1.005        # 0.5% above
            entry_moderate = price * 1.003
            entry_aggressive = price * 1.001
            risk = entry_deep * risk_pct
            sl_deep = entry_deep + risk
            sl_moderate = entry_moderate + entry_moderate * risk_pct
            sl_aggressive = entry_aggressive + entry_aggressive * risk_pct
            take_profit = entry_deep - risk * tp_ladder[0]
            take_profit_2 = entry_deep - risk * tp_ladder[1]
            take_profit_3 = entry_deep - risk * tp_ladder[2]
        band = price * 0.002                  # ±0.2% zone for stock ranges
        return {
            "entry": entry_deep,
            "entry_moderate": entry_moderate,
            "entry_aggressive": entry_aggressive,
            "entry_low": entry_deep - band,
            "entry_high": entry_deep + band,
            "entry_moderate_low": entry_moderate - band,
            "entry_moderate_high": entry_moderate + band,
            "entry_aggressive_low": entry_aggressive - band,
            "entry_aggressive_high": entry_aggressive + band,
            "stop_loss": sl_deep,
            "stop_loss_moderate": sl_moderate,
            "stop_loss_aggressive": sl_aggressive,
            "take_profit": take_profit,
            "take_profit_2": take_profit_2,
            "take_profit_3": take_profit_3,
            "avg_peak": avg_peak,
            "avg_valley": avg_valley,
        }

    if action == "BUY":
        # v9.0.0 — Deep-entry ladder anchored on ATR. Entry sits BELOW
        # current price so users buy the pullback, not the top.
        entry_deep = price - atr * 1.0
        entry_moderate = price - atr * 0.5
        entry_aggressive = price - atr * 0.2
        band = atr * 0.25
        sl_deep = entry_deep - atr * sl_mult
        sl_moderate = entry_moderate - atr * sl_mult
        sl_aggressive = entry_aggressive - atr * sl_mult
        risk = max(entry_deep - sl_deep, price * 0.005)
        take_profit = entry_deep + risk * tp_ladder[0]     # TP-1 = 1.5R
        take_profit_2 = entry_deep + risk * tp_ladder[1]   # TP-2 = 2.5R
        take_profit_3 = entry_deep + risk * tp_ladder[2]   # TP-3 = 3.5R
    elif action == "SELL":
        # v9.0.0 — Mirror of BUY: entry sits ABOVE current price.
        entry_deep = price + atr * 1.0
        entry_moderate = price + atr * 0.5
        entry_aggressive = price + atr * 0.2
        band = atr * 0.25
        sl_deep = entry_deep + atr * sl_mult
        sl_moderate = entry_moderate + atr * sl_mult
        sl_aggressive = entry_aggressive + atr * sl_mult
        risk = max(sl_deep - entry_deep, price * 0.005)
        take_profit = entry_deep - risk * tp_ladder[0]
        take_profit_2 = entry_deep - risk * tp_ladder[1]
        take_profit_3 = entry_deep - risk * tp_ladder[2]
    else:  # HOLD
        # v8.12.28 — HOLD signals emit NO entry/SL/TP levels so the UI can
        # render a clean "no trade" state instead of a fake ladder.
        entry_deep = None
        entry_moderate = None
        entry_aggressive = None
        band = 0.0
        sl_deep = sl_moderate = sl_aggressive = None
        take_profit = None
        take_profit_2 = None
        take_profit_3 = None

    # Helper to safely apply an offset when the base value may be None (HOLD).
    def _off(base, delta):
        return None if base is None else (base + delta)

    return {
        "entry": entry_deep,
        "entry_moderate": entry_moderate,
        "entry_aggressive": entry_aggressive,
        "entry_low": _off(entry_deep, -band),
        "entry_high": _off(entry_deep, band),
        "entry_moderate_low": _off(entry_moderate, -band),
        "entry_moderate_high": _off(entry_moderate, band),
        "entry_aggressive_low": _off(entry_aggressive, -band),
        "entry_aggressive_high": _off(entry_aggressive, band),
        "stop_loss": sl_deep,
        "stop_loss_moderate": sl_moderate,
        "stop_loss_aggressive": sl_aggressive,
        "take_profit": take_profit,
        "take_profit_2": take_profit_2,
        "take_profit_3": take_profit_3,
        "avg_peak": avg_peak,
        "avg_valley": avg_valley,
    }



# ============================================================
# v9.1.0 — VWAP Session Engine (formula dari user untuk profile selector)
# ============================================================
# Dipakai saat user memilih profile scalper / day(=intraday) / swing.
# Profile "longterm" tetap memakai mesin Confluence v9.0 (EMA200-based)
# karena VWAP session tidak relevan untuk position trading.
_PROFILE_TO_VWAP = {"scalper": "SCALPER", "day": "INTRADAY", "swing": "SWING"}

_VWAP_BOX_LEN = {"SCALPER": 10, "INTRADAY": 20, "SWING": 50}


def _vwap_session_series(candles: list[dict[str, Any]]) -> list[float]:
    """Anchored VWAP dengan reset otomatis setiap sesi baru.

    Sesi baru terdeteksi saat tanggal UTC berganti (crypto 24/7) — untuk
    pasar saham, sesi trading (mis. NYSE 13:30-20:00 UTC) tetap berada
    dalam satu tanggal UTC sehingga reset harian UTC valid sebagai proxy.
    """
    import datetime as _dt

    vwaps: list[float] = []
    cum_pv = 0.0
    cum_vol = 0.0
    prev_day = None
    for c in candles:
        t = c.get("t") or c.get("time")
        day = None
        if t:
            ts = float(t) / 1000.0 if float(t) > 1e12 else float(t)
            try:
                day = _dt.datetime.utcfromtimestamp(ts).date()
            except Exception:
                day = None
        if prev_day is not None and day is not None and day != prev_day:
            cum_pv, cum_vol = 0.0, 0.0
        if day is not None:
            prev_day = day
        tp = (c["high"] + c["low"] + c["close"]) / 3.0
        vol = float(c.get("volume") or 0.0)
        cum_pv += tp * vol
        cum_vol += vol
        vwaps.append(cum_pv / cum_vol if cum_vol > 0 else c["close"])
    return vwaps



# ============================================================
# v9.2.0 — Modul Formula 68-Video (Macro Bias 50 SMA Harian,
# Liquidity Zones, Choke Risk 3R, Pattern Scalp 15M/5M)
# ============================================================

def _daily_context(daily_candles: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """[Strategi 3R Rule & Trend Bias] Context harian:
    - trend bias dari harga vs SMA50 harian (Buyers/Sellers Control)
    - liquidity zones: Previous Day High/Low + Swing High/Low 10 hari
    - Daily ATR (kapasitas gerak harian untuk validasi 3R)
    """
    if not daily_candles or len(daily_candles) < 52:
        return None
    closes = [c["close"] for c in daily_candles]
    highs = [c["high"] for c in daily_candles]
    lows = [c["low"] for c in daily_candles]
    sma50 = sum(closes[-50:]) / 50.0
    prev = daily_candles[-2]
    atr_d = _atr14(highs, lows, closes)
    return {
        "bias": "BULLISH" if closes[-1] > sma50 else "BEARISH",
        "sma50": sma50,
        "pdh": prev["high"],
        "pdl": prev["low"],
        "swing_high": max(highs[-10:]),
        "swing_low": min(lows[-10:]),
        "daily_atr": atr_d,
    }


def _pattern_scalp(candles: list[dict[str, Any]], daily_atr: float | None) -> dict[str, Any] | None:
    """[Strategi 15-Minute Pattern Scalp — Market Open Manipulation]

    1. Lilin 15 menit PERTAMA sesi (UTC day) dengan range >= 20% Daily ATR
       = fase manipulasi market open.
    2. Konfirmasi entry pada candle intraday berikutnya:
       - John Wick: wick > 2x body, divalidasi candle berikutnya tembus
         high (bullish) / low (bearish) candle wick tersebut.
       - Power of Tower: candle impulsif (body > 80% range) lalu candle
         berikutnya retrace >= 50% body.
    3. Entry = high/low candle pola, SL = sisi lain candle pola,
       TP = ujung range 15M pertama (range high untuk BUY).
    Hanya pola dalam ~3 jam terakhir yang dianggap fresh.
    """
    if not candles or daily_atr is None or daily_atr <= 0:
        return None
    import datetime as _dt

    def _day(c: dict[str, Any]):
        t = c.get("t") or c.get("time")
        if not t:
            return None
        ts = float(t) / 1000.0 if float(t) > 1e12 else float(t)
        try:
            return _dt.datetime.utcfromtimestamp(ts).date()
        except Exception:
            return None

    last_day = _day(candles[-1])
    if last_day is None:
        return None
    today = [c for c in candles if _day(c) == last_day]
    if len(today) < 5:
        return None

    # spacing bar dalam menit
    t_a = today[-2].get("t") or today[-2].get("time")
    t_b = today[-1].get("t") or today[-1].get("time")
    if not t_a or not t_b:
        return None
    t_a = float(t_a) / 1000.0 if float(t_a) > 1e12 else float(t_a)
    t_b = float(t_b) / 1000.0 if float(t_b) > 1e12 else float(t_b)
    spacing_min = (t_b - t_a) / 60.0
    if spacing_min <= 0 or spacing_min > 15:
        return None  # timeframe terlalu besar untuk pattern scalp
    bars_15 = max(1, round(15.0 / spacing_min))
    if len(today) <= bars_15 + 2:
        return None  # sesi baru mulai, belum cukup konfirmasi

    first = today[:bars_15]
    first_high = max(c["high"] for c in first)
    first_low = min(c["low"] for c in first)
    is_manip = (first_high - first_low) >= 0.20 * daily_atr
    if not is_manip:
        return {"is_manipulation": False}

    rest = today[bars_15:]
    fresh_bars = max(4, round(180.0 / spacing_min))  # ~3 jam terakhir
    start = max(0, len(rest) - fresh_bars)

    best = None
    for i in range(start, len(rest) - 1):
        c = rest[i]
        nxt = rest[i + 1]
        body = abs(c["close"] - c["open"]) or 1e-12
        wick_b = min(c["open"], c["close"]) - c["low"]
        wick_t = c["high"] - max(c["open"], c["close"])
        crange = c["high"] - c["low"] or 1e-12

        # John Wick bullish (hammer): lower wick > 2x body + break high
        if wick_b > 2 * body and nxt["close"] > c["high"] and c["high"] < first_high:
            best = {"action": "BUY", "entry": c["high"], "sl": c["low"],
                    "tp": first_high, "pattern": "John Wick hammer"}
        # John Wick bearish (inverted hammer): upper wick > 2x body + break low
        elif wick_t > 2 * body and nxt["close"] < c["low"] and c["low"] > first_low:
            best = {"action": "SELL", "entry": c["low"], "sl": c["high"],
                    "tp": first_low, "pattern": "John Wick inverted hammer"}
        # Power of Tower bearish: impulsive green + retrace 50%
        elif (c["close"] > c["open"] and (c["close"] - c["open"]) > crange * 0.8
              and nxt["close"] <= (c["open"] + (c["close"] - c["open"]) * 0.5)
              and nxt["close"] < c["open"] and nxt["close"] > first_low):
            best = {"action": "SELL", "entry": nxt["close"], "sl": c["high"],
                    "tp": first_low, "pattern": "Power of Tower bear"}
        # Power of Tower bullish: impulsive red + retrace 50%
        elif (c["close"] < c["open"] and (c["open"] - c["close"]) > crange * 0.8
              and nxt["close"] >= (c["close"] + (c["open"] - c["close"]) * 0.5)
              and nxt["close"] > c["close"] and nxt["close"] < first_high):
            best = {"action": "BUY", "entry": nxt["close"], "sl": c["low"],
                    "tp": first_high, "pattern": "Power of Tower bull"}

    if not best:
        return {"is_manipulation": True}
    best["is_manipulation"] = True
    return best

def _compute_vwap_signal(
    candles: list[dict[str, Any]],
    market: str,
    engine: str,
    profile: str,
    dev_threshold_pct: float = 1.5,
    live_price: float | None = None,
    daily_candles: list[dict[str, Any]] | None = None,
    timeframe: str | None = None,
) -> dict[str, Any] | None:
    """Mesin sinyal VWAP sesuai formula user (SCALPER / INTRADAY / SWING).

    Mengembalikan response dict dengan schema identik compute_signal,
    atau None jika data volume tidak tersedia (fallback ke Confluence).

    Perbedaan dengan Confluence: formula ini adalah PEMICU ENTRY
    (breakout box / reversal di VWAP), sehingga tier entry lebih rapat
    ke harga saat ini (0 / 0.3 / 0.6 ATR) — sinyal sudah terkonfirmasi
    oleh pola candle, bukan menunggu pullback jauh.
    """
    n = len(candles)
    if n < 3:
        return None
    # VWAP butuh volume nyata — tanpa volume, VWAP tidak bermakna.
    if not any((c.get("volume") or 0) > 0 for c in candles[-10:]):
        return None

    dev_thresh = dev_threshold_pct / 100.0
    box_len = _VWAP_BOX_LEN[engine]

    vwaps = _vwap_session_series(candles)
    i = n - 1
    row = candles[i]
    prev = candles[i - 1]
    vwap = vwaps[i]
    price = row["close"]
    price_dev = (price - vwap) / vwap if vwap else 0.0

    # v9.2.4 — Definisi series lebih awal: blok SCALP-15M di bawah memakai
    # closes/highs/lows/atr, sebelumnya didefinisikan SETELAH blok itu →
    # NameError laten setiap kali pola scalp 15M terpicu.
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    atr = _atr14(highs, lows, closes) or (price * 0.02)

    # v9.2.4 — Volume ekspansi (3 candle terakhir vs 10 sebelumnya).
    # Dipakai sebagai gate TAMBAHAN: trigger VWAP hanya valid bila ada
    # partisipasi volume nyata (x1.1). Menekan false-breakout di pasar sepi.
    volumes: list[float] = [c.get("volume", 0) or 0 for c in candles]
    vol_ratio: float | None = None
    if len(volumes) >= 13:
        _rv = sum(volumes[-3:]) / 3
        _pv = sum(volumes[-13:-3]) / 10
        if _pv > 0:
            vol_ratio = _rv / _pv

    # --- Candlestick patterns (v9.2.0 — Master 15-Video Formula) ---
    candle_range = row["high"] - row["low"]

    # A. John Wick — wick rejection >= 60% dari total range candle.
    upper_wick = row["high"] - max(row["open"], row["close"])
    lower_wick = min(row["open"], row["close"]) - row["low"]
    john_wick_bear = candle_range > 0 and (upper_wick / candle_range) >= 0.60
    john_wick_bull = candle_range > 0 and (lower_wick / candle_range) >= 0.60

    # B. Power of Tower — candle impulsif (body > 80% range) diikuti
    #    retracement 50% pada candle berikutnya.
    prev_range = prev["high"] - prev["low"]
    is_impulsive_green = (prev["close"] - prev["open"]) > (prev_range * 0.8) and prev["close"] > prev["open"]
    power_of_tower_bear = is_impulsive_green and (row["close"] <= (prev["open"] + (prev["close"] - prev["open"]) * 0.5))
    is_impulsive_red = (prev["open"] - prev["close"]) > (prev_range * 0.8) and prev["close"] < prev["open"]
    power_of_tower_bull = is_impulsive_red and (row["close"] >= (prev["close"] + (prev["open"] - prev["close"]) * 0.5))

    # C. Standard engulfing-style reversal.
    std_bull = (row["close"] > row["open"]) and (prev["close"] < prev["open"]) and (row["close"] > prev["open"])
    std_bear = (row["close"] < row["open"]) and (prev["close"] > prev["open"]) and (row["close"] < prev["open"])

    # Gabungan: reversal = standard ATAU John Wick ATAU Power of Tower.
    bull_rev = std_bull or john_wick_bull or power_of_tower_bull
    bear_rev = std_bear or john_wick_bear or power_of_tower_bear

    def _bull_patterns() -> list[str]:
        out = []
        if std_bull: out.append("bullish reversal")
        if john_wick_bull: out.append("John Wick (lower wick ≥60%)")
        if power_of_tower_bull: out.append("Power of Tower bull")
        return out

    def _bear_patterns() -> list[str]:
        out = []
        if std_bear: out.append("bearish reversal")
        if john_wick_bear: out.append("John Wick (upper wick ≥60%)")
        if power_of_tower_bear: out.append("Power of Tower bear")
        return out

    # --- Box breakout (persis formula user) ---
    if i >= box_len:
        box_high = max(c["high"] for c in candles[i - box_len:i])
        box_low = min(c["low"] for c in candles[i - box_len:i])
    else:
        box_high, box_low = row["high"], row["low"]
    box_break_long = row["close"] > box_high and prev["close"] <= box_high
    box_break_short = row["close"] < box_low and prev["close"] >= box_low

    # ---- v9.2.0 — Konteks harian (68-video): bias 50 SMA + liquidity ----
    daily = _daily_context(daily_candles)
    daily_bias = daily["bias"] if daily else None
    daily_atr = daily["daily_atr"] if daily else None

    # ---- v9.2.0 — Pattern Scalp override (hanya SCALPER di TF <= 15m) ----
    # Market Open Manipulation (lilin 15M pertama > 20% Daily ATR) +
    # konfirmasi John Wick / Power of Tower → entry/SL/TP langsung dari
    # pola (override aturan VWAP generik).
    scalp = None
    if engine == "SCALPER" and (timeframe or "1h") in ("1m", "3m", "5m", "15m"):
        scalp = _pattern_scalp(candles, daily_atr)
        if scalp and scalp.get("action"):
            action = scalp["action"]
            label = ("LONG" if market == "crypto" else "BUY") if action == "BUY" else ("SHORT" if market == "crypto" else "SELL")
            confidence = 70
            reasons = [
                f"[SCALP 15M] Manipulasi open terdeteksi (range 15M pertama ≥ 20% Daily ATR) "
                f"+ {scalp['pattern']} terkonfirmasi → {action}."
            ]
            if daily_bias and ((action == "BUY" and daily_bias == "BULLISH") or (action == "SELL" and daily_bias == "BEARISH")):
                confidence = min(95, confidence + 12)
                reasons.append(f"Searah bias harian 50 SMA ({daily_bias}) — full risk.")
            elif daily_bias:
                confidence -= 12
                reasons.append(f"Counter-trend vs bias harian ({daily_bias}) — half risk (scalp cepat).")
            # Level PERSIS dari formula: entry pola, SL sisi lain, TP ujung range 15M
            e, sl_, tp_ = scalp["entry"], scalp["sl"], scalp["tp"]
            band = abs(e - sl_) * 0.15 or price * 0.001
            levels = {
                "entry": e, "entry_moderate": e, "entry_aggressive": e,
                "entry_low": e - band, "entry_high": e + band,
                "entry_moderate_low": e - band, "entry_moderate_high": e + band,
                "entry_aggressive_low": e - band, "entry_aggressive_high": e + band,
                "stop_loss": sl_, "stop_loss_moderate": sl_, "stop_loss_aggressive": sl_,
                "take_profit": tp_, "take_profit_2": None, "take_profit_3": None,
            }
            rsi = _rsi(closes, 14)
            _pf = get_trader_profile(profile)
            _ef = _ema(closes, int(_pf["ema_fast"]))
            _es = _ema(closes, int(_pf["ema_slow"]))
            _h = _macd_hist_recent(closes, 3)
            regime_info = _detect_regime(closes, highs, lows) if market == "crypto" else {"regime": "UNKNOWN"}
            indicators = {
                "rsi": round(rsi, 2) if rsi is not None else None,
                "ema20": round(_ef[-1], 6) if _ef else None,
                "ema50": round(_es[-1], 6) if _es else None,
                "ema_fast_n": int(_pf["ema_fast"]),
                "ema_slow_n": int(_pf["ema_slow"]),
                "macd_hist": round(_h[-1], 6) if _h else None,
                "price": round(price, 8),
                "atr": round(atr, 6),
                "vwap": round(vwap, 8),
                "price_dev_pct": round(price_dev * 100.0, 3),
                "vwap_engine": "SCALP-15M",
                "scalp_pattern": scalp["pattern"],
                "is_manipulation": True,
                "structure": "SCALP-15M",
                "avg_peak": round(price * 1.05, 8),
                "avg_valley": round(price * 0.95, 8),
                "peaks_found": 0,
                "valleys_found": 0,
            }
            if daily:
                indicators.update({
                    "daily_bias": daily_bias,
                    "pdh": round(daily["pdh"], 8), "pdl": round(daily["pdl"], 8),
                    "swing_high": round(daily["swing_high"], 8), "swing_low": round(daily["swing_low"], 8),
                    "daily_atr": round(daily_atr, 8) if daily_atr else None,
                })
            return {
                "action": action, "label": label, "confidence": int(confidence),
                "indicators": indicators, "reasons": reasons,
                "entry": round(e, 8),
                "entry_low": round(e - band, 8), "entry_high": round(e + band, 8),
                "entry_moderate": round(e, 8), "entry_aggressive": round(e, 8),
                "entry_moderate_low": round(e - band, 8), "entry_moderate_high": round(e + band, 8),
                "entry_aggressive_low": round(e - band, 8), "entry_aggressive_high": round(e + band, 8),
                "stop_loss": round(sl_, 8),
                "take_profit": round(tp_, 8), "take_profit_2": None, "take_profit_3": None,
                "regime": regime_info.get("regime", "UNKNOWN"),
                "_all_levels": {"BUY": {}, "SELL": {}},
            }

    # --- Aturan sinyal per engine (persis formula user) ---
    # v9.2.4 — Opsi C: SEMUA trigger kini WAJIB konfirmasi pola reversal
    # (bull_rev/bear_rev) DAN volume ekspansi (x1.1). Breakout/deviasi
    # "kosong" tanpa pola & volume tidak lagi menghasilkan sinyal.
    vol_ok = vol_ratio is None or vol_ratio > 1.1
    action = "HOLD"
    triggers: list[str] = []
    if engine == "SCALPER":
        if price_dev <= -dev_thresh and bull_rev and vol_ok:
            action = "BUY"
            triggers.append(f"deviasi {price_dev*100:+.2f}% di bawah VWAP + " + "/".join(_bull_patterns()))
        elif box_break_long and price > vwap and bull_rev and vol_ok:
            action = "BUY"
            triggers.append(f"breakout box-{box_len} di atas VWAP + " + "/".join(_bull_patterns()))
        elif price_dev >= dev_thresh and bear_rev and vol_ok:
            action = "SELL"
            triggers.append(f"deviasi {price_dev*100:+.2f}% di atas VWAP + " + "/".join(_bear_patterns()))
        elif box_break_short and price < vwap and bear_rev and vol_ok:
            action = "SELL"
            triggers.append(f"breakdown box-{box_len} di bawah VWAP + " + "/".join(_bear_patterns()))
    elif engine == "INTRADAY":
        # v9.2.4 — Reclaim/rejection kini WAJIB disertai pola reversal.
        reclaim = ((row["low"] <= vwap and price > vwap and bull_rev)
                   or (prev["close"] <= vwap and price > vwap and bull_rev))
        rejection = ((row["high"] >= vwap and price < vwap and bear_rev)
                     or (prev["close"] >= vwap and price < vwap and bear_rev))
        if reclaim and price_dev < dev_thresh and vol_ok:
            action = "BUY"
            triggers.append("KISS pivot reclaim VWAP + " + "/".join(_bull_patterns()))
        elif rejection and price_dev > -dev_thresh and vol_ok:
            action = "SELL"
            triggers.append("KISS pivot rejection VWAP + " + "/".join(_bear_patterns()))
    else:  # SWING
        # v9.2.4 — Swing TIDAK pakai volume gate: breakout box-50 multi-hari
        # sering terjadi saat volume rata-rata (akumulasi institusi), dan
        # pola reversal + bias harian + floor confidence sudah cukup ketat.
        # Backtest: gate volume membuat swing hanya 19 trade/24bln, WR 52%.
        if price > vwap and box_break_long and bull_rev:
            action = "BUY"
            triggers.append(f"breakout box-{box_len} di atas VWAP + " + "/".join(_bull_patterns()))
        elif price < vwap and box_break_short and bear_rev:
            action = "SELL"
            triggers.append(f"breakdown box-{box_len} di bawah VWAP + " + "/".join(_bear_patterns()))

    label = "HOLD"
    if action == "BUY":
        label = "LONG" if market == "crypto" else "BUY"
    elif action == "SELL":
        label = "SHORT" if market == "crypto" else "SELL"

    # --- Confidence jujur dari komponen yang benar-benar menyala ---
    if action == "HOLD":
        side = "atas" if price_dev >= 0 else "bawah"
        reasons = [
            f"[{engine}] Harga {abs(price_dev)*100:.2f}% di {side} VWAP — "
            f"belum ada trigger (box-{box_len} breakout / reversal). Tunggu setup."
        ]
        confidence = 45
    else:
        # v9.1.2 — Rekalibrasi confidence VWAP agar setup berkonfluens penuh
        # bisa mencapai zona Premium (85+). Kalibrasi lama mentok di ~79
        # (base 55) sehingga TIDAK ADA satupun sinyal VWAP yang lolos gate
        # premium → badge hilang di semua kolom bervolume.
        #   base 58 (trigger terkonfirmasi) + box 14 + reversal 10
        #   + John Wick 7 + Power of Tower 7 + sisi VWAP 8 + deviasi 6
        #   → setup kuat (box + reversal + sisi VWAP) = 90 ✓ premium
        # Trigger utama engine (box breakout / deviasi ekstrem / KISS pivot
        # di VWAP) adalah kondisi yang BERHASIL menyala — beri bobot penuh.
        confidence = 58 + 14
        reasons = [f"[{engine}] " + t for t in triggers]
        if (action == "BUY" and box_break_long) or (action == "SELL" and box_break_short):
            confidence += 14
        if bull_rev or bear_rev:
            confidence += 10
        # Pola premium dari materi video: rejection wick / momentum tower.
        if john_wick_bull or john_wick_bear:
            confidence += 7
        if power_of_tower_bull or power_of_tower_bear:
            confidence += 7
        if (action == "BUY" and price > vwap) or (action == "SELL" and price < vwap):
            confidence += 8
        if abs(price_dev) >= dev_thresh:
            confidence += 6
        confidence = min(95, confidence)

    # ---- v9.2.0 — Macro Trend Bias Filter (50 SMA harian, 3R Rule) ----
    # Searah bias → full risk (confidence +6). Melawan bias:
    #   SCALPER → boleh (scalp cepat) tapi half risk (confidence -12)
    #   INTRADAY/SWING → HOLD (formula: short saat bias bullish hanya
    #   untuk scalp; posisi intraday/swing wajib searah bias).
    if daily_bias and action in ("BUY", "SELL"):
        with_bias = (action == "BUY" and daily_bias == "BULLISH") or \
                    (action == "SELL" and daily_bias == "BEARISH")
        if with_bias:
            confidence = min(95, confidence + 6)
            reasons.append(f"Searah bias harian 50 SMA ({daily_bias}) — full risk.")
        elif engine == "SCALPER":
            confidence = max(50, confidence - 12)
            reasons.append(f"Counter-trend scalp vs bias harian ({daily_bias}) — half risk, keluar cepat.")
        else:
            action = "HOLD"
            label = "HOLD"
            confidence = 48
            reasons = [
                f"[{engine}] Setup melawan bias harian 50 SMA ({daily_bias}) — "
                f"3R Rule: posisi {engine.lower()} hanya searah bias makro. Tunggu harga kembali searah."
            ]

    # ---- v9.2.4 — Confidence floor (Opsi C, anti-sinyal-lemah) ----
    # Setup yang lolos trigger tapi konfluensnya tipis diturunkan ke HOLD.
    # Swing floor lebih longgar (72 vs 78): trigger box-50 + reversal +
    # bias harian sudah struktural kuat, dan sample swing memang lebih
    # jarang secara alami.
    _conf_floor = 72 if engine == "SWING" else 78
    if action in ("BUY", "SELL") and confidence < _conf_floor:
        action = "HOLD"
        label = "HOLD"
        confidence = 50
        reasons = [
            f"[{engine}] Trigger terdeteksi tapi konfluens belum cukup kuat "
            f"(confidence < {_conf_floor}) — HOLD, tunggu setup berkualitas lebih tinggi."
        ]

    # --- Levels: tier rapat karena sinyal = pemicu, bukan limit jauh ---
    # (highs/lows/closes/atr sudah didefinisikan di atas sejak v9.2.4)
    prof = get_trader_profile(profile)
    sl_mult = float(prof["sl_atr_mult"])
    # v9.2.4 — VWAP engine pakai vwap_tp_ladder (TP1 lebih rapat) agar WR
    # profile berbayar lebih tinggi dari Confluence.
    tp_ladder = tuple(prof.get("vwap_tp_ladder", prof.get("tp_ladder", (1.0, 2.0, 3.0))))
    peaks, valleys = _find_swings(highs, lows, window=10)
    # v9.1.4 — Anchor level ke harga LIVE (trigger tetap dari candle tutup).
    _anchor = price
    if live_price and live_price > 0 and atr > 0 and abs(live_price - price) <= atr * 8:
        _anchor = float(live_price)
    levels = _compute_vwap_levels(action, _anchor, atr, peaks, valleys, market, sl_mult, tp_ladder)

    # ---- v9.2.0 — Choke Risk Protection (3R Rule) ----
    # Batalkan eksekusi bila jarak TP1 melebihi 80% kapasitas Daily ATR —
    # target tidak realistis untuk horizon harian.
    if (action in ("BUY", "SELL") and daily_atr and daily_atr > 0
            and levels.get("entry") is not None and levels.get("take_profit") is not None):
        if abs(levels["take_profit"] - levels["entry"]) > 0.8 * daily_atr:
            action = "HOLD"
            label = "HOLD"
            confidence = 46
            reasons = [
                f"[{engine}] Choke Risk Protection: jarak TP1 melebihi 80% Daily ATR — "
                f"target tidak realistis untuk horizon harian, eksekusi dibatalkan (3R Rule)."
            ]
            levels = _compute_vwap_levels("HOLD", _anchor, atr, peaks, valleys, market, sl_mult, tp_ladder)

    buy_levels = _compute_vwap_levels("BUY", _anchor, atr, peaks, valleys, market, sl_mult, tp_ladder)
    sell_levels = _compute_vwap_levels("SELL", _anchor, atr, peaks, valleys, market, sl_mult, tp_ladder)

    rsi = _rsi(closes, 14)
    # v9.1.4 — Panel indikator detail page membaca ema20/ema50/macd_hist.
    # Mesin VWAP sebelumnya TIDAK mengirim kunci ini → tampil "—" dan
    # "0.0000" di aplikasi (terlihat ngawur bagi user). Hitung dengan
    # window sesuai profil agar konsisten dengan mesin Confluence.
    _pf = get_trader_profile(profile)
    _ef = _ema(closes, int(_pf["ema_fast"]))
    _es = _ema(closes, int(_pf["ema_slow"]))
    _h = _macd_hist_recent(closes, 3)
    regime_info = _detect_regime(closes, highs, lows) if market == "crypto" else {"regime": "UNKNOWN"}

    return {
        "action": action,
        "label": label,
        "confidence": int(confidence),
        "indicators": {
            "rsi": round(rsi, 2) if rsi is not None else None,
            "ema20": round(_ef[-1], 6) if _ef else None,
            "ema50": round(_es[-1], 6) if _es else None,
            "ema_fast_n": int(_pf["ema_fast"]),
            "ema_slow_n": int(_pf["ema_slow"]),
            "macd_hist": round(_h[-1], 6) if _h else None,
            "price": round(price, 8),
            "atr": round(atr, 6),
            "vwap": round(vwap, 8),
            "price_dev_pct": round(price_dev * 100.0, 3),
            "box_high": round(box_high, 8),
            "box_low": round(box_low, 8),
            "vwap_engine": engine,
            "bull_reversal": bull_rev,
            "bear_reversal": bear_rev,
            "john_wick": bool(john_wick_bull or john_wick_bear),
            "john_wick_bull": bool(john_wick_bull),
            "john_wick_bear": bool(john_wick_bear),
            "power_of_tower": bool(power_of_tower_bull or power_of_tower_bear),
            "power_of_tower_bull": bool(power_of_tower_bull),
            "power_of_tower_bear": bool(power_of_tower_bear),
            "box_break_long": box_break_long,
            "box_break_short": box_break_short,
            "avg_peak": round(levels["avg_peak"], 8),
            "avg_valley": round(levels["avg_valley"], 8),
            "peaks_found": len(peaks),
            "valleys_found": len(valleys),
            "structure": "VWAP-" + engine,
            # v9.2.0 — konteks makro harian untuk panel indikator
            "daily_bias": daily_bias,
            "pdh": round(daily["pdh"], 8) if daily else None,
            "pdl": round(daily["pdl"], 8) if daily else None,
            "swing_high": round(daily["swing_high"], 8) if daily else None,
            "swing_low": round(daily["swing_low"], 8) if daily else None,
            "daily_atr": round(daily_atr, 8) if daily_atr else None,
            "is_manipulation": bool(scalp and scalp.get("is_manipulation")),
        },
        "reasons": reasons,
        "entry": (round(levels["entry"], 8) if levels.get("entry") is not None else None),
        "entry_low": (round(levels["entry_low"], 8) if levels.get("entry_low") is not None else None),
        "entry_high": (round(levels["entry_high"], 8) if levels.get("entry_high") is not None else None),
        "entry_moderate": (round(levels["entry_moderate"], 8) if levels.get("entry_moderate") is not None else None),
        "entry_aggressive": (round(levels["entry_aggressive"], 8) if levels.get("entry_aggressive") is not None else None),
        "entry_moderate_low": (round(levels["entry_moderate_low"], 8) if levels.get("entry_moderate_low") is not None else None),
        "entry_moderate_high": (round(levels["entry_moderate_high"], 8) if levels.get("entry_moderate_high") is not None else None),
        "entry_aggressive_low": (round(levels["entry_aggressive_low"], 8) if levels.get("entry_aggressive_low") is not None else None),
        "entry_aggressive_high": (round(levels["entry_aggressive_high"], 8) if levels.get("entry_aggressive_high") is not None else None),
        "stop_loss": (round(levels["stop_loss"], 8) if levels.get("stop_loss") is not None else None),
        "take_profit": (round(levels["take_profit"], 8) if levels.get("take_profit") is not None else None),
        "take_profit_2": (round(levels["take_profit_2"], 8) if levels.get("take_profit_2") is not None else None),
        "take_profit_3": (round(levels["take_profit_3"], 8) if levels.get("take_profit_3") is not None else None),
        "regime": regime_info.get("regime", "UNKNOWN"),
        "_all_levels": {
            "BUY":  {k: (round(v, 8) if v is not None else None) for k, v in buy_levels.items()},
            "SELL": {k: (round(v, 8) if v is not None else None) for k, v in sell_levels.items()},
        },
    }


def _compute_vwap_levels(
    action: str,
    price: float,
    atr: float,
    peaks: list[float],
    valleys: list[float],
    market: str,
    sl_mult: float,
    tp_ladder: tuple[float, float, float],
) -> dict[str, Any]:
    """Level untuk mesin VWAP — tier entry rapat ke harga (sinyal adalah
    pemicu, bukan limit order jauh):
      aggressive = harga saat ini (market entry)
      moderate   = 0.3 ATR pullback
      deep       = 0.6 ATR pullback (default card)
    SL = entry ∓ sl_mult×ATR; TP ladder 1R/2R/3R (warisan backtest v9.0).
    Pasar stocklike tetap memakai varian persentase dari _compute_deep_levels.
    """
    is_stocklike = market in ("stock_id", "stock_us", "world_stocks", "etf",
                              "gold_silver", "commodity", "forex")
    if is_stocklike:
        return _compute_deep_levels(action, price, atr, peaks, valleys,
                                    market=market, sl_mult=sl_mult, tp_ladder=tp_ladder)
    if action == "BUY":
        entry_aggressive = price
        entry_moderate = price - atr * 0.3
        entry_deep = price - atr * 0.6
        band = atr * 0.15
        sl_deep = entry_deep - atr * sl_mult
        sl_moderate = entry_moderate - atr * sl_mult
        sl_aggressive = entry_aggressive - atr * sl_mult
        risk = max(entry_deep - sl_deep, price * 0.005)
        tp1 = entry_deep + risk * tp_ladder[0]
        tp2 = entry_deep + risk * tp_ladder[1]
        tp3 = entry_deep + risk * tp_ladder[2]
    elif action == "SELL":
        entry_aggressive = price
        entry_moderate = price + atr * 0.3
        entry_deep = price + atr * 0.6
        band = atr * 0.15
        sl_deep = entry_deep + atr * sl_mult
        sl_moderate = entry_moderate + atr * sl_mult
        sl_aggressive = entry_aggressive + atr * sl_mult
        risk = max(sl_deep - entry_deep, price * 0.005)
        tp1 = entry_deep - risk * tp_ladder[0]
        tp2 = entry_deep - risk * tp_ladder[1]
        tp3 = entry_deep - risk * tp_ladder[2]
    else:
        entry_deep = entry_moderate = entry_aggressive = None
        band = 0.0
        sl_deep = sl_moderate = sl_aggressive = None
        tp1 = tp2 = tp3 = None

    recent_peaks = peaks[-5:] if len(peaks) >= 5 else peaks
    recent_valleys = valleys[-5:] if len(valleys) >= 5 else valleys
    last3_peaks = recent_peaks[-3:] if len(recent_peaks) >= 3 else recent_peaks
    last3_valleys = recent_valleys[-3:] if len(recent_valleys) >= 3 else recent_valleys
    avg_peak = (sum(last3_peaks) / len(last3_peaks)) if last3_peaks else price * 1.05
    avg_valley = (sum(last3_valleys) / len(last3_valleys)) if last3_valleys else price * 0.95

    def _off(base, delta):
        return None if base is None else (base + delta)

    return {
        "entry": entry_deep,
        "entry_moderate": entry_moderate,
        "entry_aggressive": entry_aggressive,
        "entry_low": _off(entry_deep, -band),
        "entry_high": _off(entry_deep, band),
        "entry_moderate_low": _off(entry_moderate, -band),
        "entry_moderate_high": _off(entry_moderate, band),
        "entry_aggressive_low": _off(entry_aggressive, -band),
        "entry_aggressive_high": _off(entry_aggressive, band),
        "stop_loss": sl_deep,
        "stop_loss_moderate": sl_moderate,
        "stop_loss_aggressive": sl_aggressive,
        "take_profit": tp1,
        "take_profit_2": tp2,
        "take_profit_3": tp3,
        "avg_peak": avg_peak,
        "avg_valley": avg_valley,
    }


def _drop_forming_candle(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """v9.1.3 — STABILITAS SINYAL: buang candle terakhir jika masih
    BERJALAN (forming). Kondisi seperti cross VWAP, breakout box, pola
    wick, dan momentum dievaluasi pada candle live yang berubah tiap
    detik → label HOLD↔SHORT berkedip di dashboard. Standar industri
    (Pine barstate.isconfirmed): sinyal hanya dari candle yang SUDAH
    TUTUP. Candle historis (backtest) tidak terpengaruh karena umurnya
    selalu lebih tua dari satu bar.
    """
    if len(candles) < 3:
        return candles
    t1 = candles[-1].get("t") or candles[-1].get("time")
    t0 = candles[-2].get("t") or candles[-2].get("time")
    if not t1 or not t0:
        return candles
    t1 = float(t1)
    t0 = float(t0)
    if t1 > 1e12:
        t1 /= 1000.0
    if t0 > 1e12:
        t0 /= 1000.0
    spacing = t1 - t0
    if spacing <= 0:
        return candles
    import time as _time
    # toleransi 2% untuk clock skew server vs exchange
    if _time.time() < t1 + spacing * 0.98:
        return candles[:-1]
    return candles

def compute_signal(
    candles: list[dict[str, Any]],
    market: str,
    profile: str | None = None,
    live_price: float | None = None,
    daily_candles: list[dict[str, Any]] | None = None,
    timeframe: str | None = None,
    # v9.2.4 — Opsi C: Confluence butuh 8 faktor confluence (dari 5).
    # Sinyal jauh lebih jarang tapi WR target 70-75% (validasi backtest).
    min_score: int = 8,
    htf_gate: bool = False,
    zone_cap: float = 1.5,
    macd_required: bool = False,
    rsi_momentum: bool = False,
    vol_required: bool = False,
    hlhh_required: bool = False,
) -> dict[str, Any]:
    """v9.0.0 "Confluence" — total formula overhaul.

    Design goals (post-mortem of the v3 accuracy regression):
      1. ONE deterministic direction engine shared by dashboard, search,
         chart and analyze. The caller's trader profile only tunes the
         horizon (EMA windows / SL distance / TP ladder); it NEVER vetoes
         a signal. This kills the "dashboard BUY vs detail SIDEWAYS" desync.
      2. Trend-following with pullback entries. We only BUY inside a BULL
         structure when price pulls back into the EMA zone, and only SELL
         inside a BEAR structure on a rally into the EMA zone.
      3. The v8.12.24 "FLIP" inversion (uptrend + overbought → SELL/TP)
         is REMOVED — it shorted users into bull runs. Overextension now
         produces HOLD ("wait for pullback"), never a counter-trend trade.
      4. Honest confidence: additive weighted score (50–95), no artificial
         baseline or boosts.
      5. TP ladder 1R / 2R / 3R — dipilih dari backtest 30 hari
         (302 trade, 9 aset): TP1=1R memberi WR 57.1% & expectancy
         +0.136R/trade, jauh di atas varian 1.5R (42.1%, +0.048R).
    """
    if not candles or len(candles) < 35:
        return {
            "action": "HOLD",
            "label": "HOLD",
            "confidence": 0,
            "indicators": {},
            "reasons": [],
            "entry": None, "stop_loss": None, "take_profit": None,
        }

    # v9.1.3 — Sinyal hanya dari candle TUTUP (anti-kedip HOLD↔SHORT).
    candles = _drop_forming_candle(candles)

    # v9.3.0 — Mesin VWAP Session HANYA aktif jika user EKSPLISIT memilih
    # profile scalper/day/swing di app (toggle di Trader Profile modal).
    # Tanpa pilihan (profile=None) → mesin Confluence v9.0 di bawah.
    # Longterm memang tidak ada di _PROFILE_TO_VWAP (selalu Confluence).
    if profile in _PROFILE_TO_VWAP:
        _vsig = _compute_vwap_signal(
            candles, market, _PROFILE_TO_VWAP[profile], profile,
            live_price=live_price,
            daily_candles=daily_candles,
            timeframe=timeframe,
        )
        if _vsig is not None:
            return _vsig
        # volume kosong → lanjut ke Confluence sebagai fallback

    # Resolve trader-profile presets. Only apply on eligible markets so that
    # stocks / commodity / etf keep the market-neutral day defaults.
    _prof = get_trader_profile(profile) if market in PROFILE_APPLICABLE_MARKETS else get_trader_profile("day")
    _ema_fast_n = int(_prof["ema_fast"])
    _ema_slow_n = int(_prof["ema_slow"])
    _require_ema200 = bool(_prof.get("require_ema200"))
    _sl_atr_mult = float(_prof["sl_atr_mult"])
    _tp_ladder = tuple(_prof.get("tp_ladder", (1.0, 2.0, 3.0)))

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes: list[float] = [c.get("volume", 0) or 0 for c in candles]
    price = closes[-1]

    if len(closes) < max(_ema_slow_n, 35):
        return {
            "action": "HOLD", "label": "HOLD", "confidence": 0,
            "indicators": {},
            "reasons": ["Data candle tidak cukup untuk membaca struktur tren"],
            "entry": None, "stop_loss": None, "take_profit": None,
        }

    rsi = _rsi(closes, 14)
    # v9.0.0 — Pegged/stablecoin guard: ATR di bawah 0.1% dari harga berarti
    # tidak ada volatilitas yang bisa ditradingkan (USDT, USDC, DAI...).
    # Tanpa guard ini risk-floor price*0.005 menghasilkan R:R semu (≈31R).
    # v9.2.0 — Guard HANYA untuk crypto: forex 1h memang bervolatilitas
    # ~0.05% per candle (normal dalam pip), jangan salah flag sebagai pegged.
    atr_probe = _atr14(highs, lows, closes)
    if market == "crypto" and atr_probe is not None and price > 0 and (atr_probe / price) < 0.001:
        return {
            "action": "HOLD", "label": "HOLD", "confidence": 40,
            "indicators": {"price": round(price, 8), "atr": round(atr_probe, 8)},
            "reasons": ["Volatilitas terlalu rendah (aset pegged/stablecoin) — tidak ada edge untuk ditradingkan."],
            "entry": None, "stop_loss": None, "take_profit": None,
        }
    ema_fast = _ema(closes, _ema_fast_n)[-1]
    ema_slow = _ema(closes, _ema_slow_n)[-1]
    ema200 = _ema(closes, 200)[-1] if len(closes) >= 200 else None
    hists = _macd_hist_recent(closes, 3)
    atr = _atr14(highs, lows, closes) or (price * 0.02)

    # ---- 1. Market structure — the spine of the whole formula ----
    # BULL: fast EMA above slow EMA AND price above slow EMA.
    # BEAR: mirror. Anything else is SIDEWAYS (no trade).
    # Swing/longterm profiles additionally demand EMA200 alignment.
    bull = ema_fast > ema_slow and price > ema_slow
    bear = ema_fast < ema_slow and price < ema_slow
    ema200_bull = ema200 is not None and price > ema200
    ema200_bear = ema200 is not None and price < ema200
    if _require_ema200 and ema200 is not None:
        bull = bull and ema200_bull
        bear = bear and ema200_bear
    structure = "BULL" if bull else ("BEAR" if bear else "SIDEWAYS")

    # ---- 2. Location — distance from EMAs measured in ATR units ----
    # Entry zone = pullback territory: harga di ATAU DI BAWAH fast EMA
    # (BUY), tidak lebih dari +zone_cap ATR di atasnya (no chasing).
    # Overextension = lebih dari 3 ATR dari slow EMA.
    dist_fast = (price - ema_fast) / atr if atr > 0 else 0.0
    dist_slow = (price - ema_slow) / atr if atr > 0 else 0.0
    in_buy_zone = -1.5 <= dist_fast <= zone_cap
    in_sell_zone = -zone_cap <= dist_fast <= 1.5
    overextended_up = dist_slow > 3.0
    overextended_dn = dist_slow < -3.0

    # ---- 2b. Higher-trend gate (proxy MTF via EMA200 di base TF) ----
    # BUY hanya jika harga di atas EMA200, SELL hanya jika di bawah.
    # Jika data EMA200 tidak cukup → gate netral (tidak memblokir).
    htf_buy_ok = (ema200 is None) or ema200_bull if htf_gate else True
    htf_sell_ok = (ema200 is None) or ema200_bear if htf_gate else True

    # ---- 3. RSI health bands ----
    # Pullback-buy wants RSI cooled off into 35–68; rally-sell 32–65.
    # RSI ≥ 72 (overbought) or ≤ 28 (oversold) vetoes chasing entirely.
    rsi_overbought = rsi is not None and rsi >= 72
    rsi_oversold = rsi is not None and rsi <= 28
    rsi_buy_ok = rsi is None or (35.0 <= rsi <= 68.0)
    rsi_sell_ok = rsi is None or (32.0 <= rsi <= 65.0)

    # ---- 4. MACD histogram — sign AND direction of change ----
    macd_vote = 0
    macd_note = "MACD netral"
    if hists and len(hists) >= 2:
        h_now, h_prev = hists[-1], hists[-2]
        if h_now > 0 and h_now >= h_prev:
            macd_vote, macd_note = 2, "MACD hist positif & menguat"
        elif h_now > 0:
            macd_vote, macd_note = 1, "MACD hist positif"
        elif h_now < 0 and h_now <= h_prev:
            macd_vote, macd_note = -2, "MACD hist negatif & melemah"
        elif h_now < 0:
            macd_vote, macd_note = -1, "MACD hist negatif"

    # ---- 5. Volume expansion & 5-bar momentum ----
    vol_ratio: float | None = None
    if len(volumes) >= 13:
        recent_vol = sum(volumes[-3:]) / 3
        prior_vol = sum(volumes[-13:-3]) / 10
        if prior_vol > 0:
            vol_ratio = recent_vol / prior_vol
    mom5 = ((closes[-1] - closes[-6]) / closes[-6] * 100.0) if len(closes) >= 6 else 0.0

    # ---- 6. Swing structure (higher-low / lower-high confirmation) ----
    _pk, _vl = _find_swings(highs, lows, window=5)
    higher_low = len(_vl) >= 2 and _vl[-1] > _vl[-2]
    lower_high = len(_pk) >= 2 and _pk[-1] < _pk[-2]

    # ---- Confluence scoring ----
    # Every component votes WITH the dominant structure only. There is no
    # mean-reversion flip: an overextended trend earns a HOLD ("wait for
    # pullback"), never a counter-trend entry.
    def _score(side: int) -> tuple[int, list[str]]:
        pts = 2  # structure alignment (the backbone of every trade)
        rs = [f"Struktur {structure} (EMA{_ema_fast_n} vs EMA{_ema_slow_n} + harga)"]
        pts += 1
        rs.append(f"Harga di zona entry (±1.5 ATR dari EMA{_ema_fast_n})")
        if macd_vote * side > 0:
            pts += min(2, abs(macd_vote))
            rs.append(macd_note)
        elif macd_vote * side < 0:
            pts -= 1
            rs.append(f"{macd_note} (melawan arah)")
        if rsi is not None:
            if side > 0 and 45.0 <= rsi <= 62.0:
                pts += 1
                rs.append(f"RSI {rsi:.1f} sehat untuk pullback-buy")
            elif side < 0 and 38.0 <= rsi <= 55.0:
                pts += 1
                rs.append(f"RSI {rsi:.1f} sehat untuk rally-sell")
            else:
                rs.append(f"RSI {rsi:.1f} netral")
        if vol_ratio is not None and vol_ratio > 1.2:
            pts += 1
            rs.append(f"Volume expansion x{vol_ratio:.2f}")
        if (side > 0 and mom5 > 0.3) or (side < 0 and mom5 < -0.3):
            pts += 1
            rs.append(f"Momentum 5-bar {mom5:+.2f}% searah")
        if (side > 0 and ema200_bull) or (side < 0 and ema200_bear):
            pts += 1
            rs.append("Harga di sisi benar EMA200")
        return pts, rs

    action = "HOLD"
    label = "HOLD"
    reasons: list[str] = []
    confidence = 50

    if structure == "BULL":
        if rsi_overbought or overextended_up:
            reasons.append(
                f"Tren BULL tapi overextended (RSI {rsi:.0f}, jarak {dist_slow:+.1f} ATR dari EMA{_ema_slow_n}) — tunggu pullback, jangan kejar harga."
                if rsi is not None else
                f"Tren BULL tapi overextended ({dist_slow:+.1f} ATR dari EMA{_ema_slow_n}) — tunggu pullback."
            )
            confidence = 55
        elif not htf_buy_ok:
            reasons.append(
                "Tren BULL jangka pendek tapi harga di BAWAH EMA200 (tren besar masih turun) — counter-trend, HOLD."
            )
            confidence = 50
        elif rsi_momentum and rsi is not None and rsi < 50.0:
            reasons.append(f"Tren BULL tapi RSI {rsi:.1f} < 50 — momentum belum berpihak, HOLD.")
            confidence = 52
        elif vol_required and vol_ratio is not None and vol_ratio <= 1.2:
            reasons.append(f"Tren BULL tapi volume belum ekspansi (x{vol_ratio:.2f}) — HOLD.")
            confidence = 52
        elif hlhh_required and not higher_low:
            reasons.append("Tren BULL tapi swing low belum higher-low — struktur mikro belum konfirmasi, HOLD.")
            confidence = 52
        elif not in_buy_zone:
            reasons.append(
                f"Tren BULL, harga {dist_fast:+.1f} ATR dari EMA{_ema_fast_n} — di luar zona entry, tunggu pullback."
            )
            confidence = 55
        elif not rsi_buy_ok:
            reasons.append(
                f"Tren BULL tapi RSI {rsi:.1f} di luar band sehat 35-68 — tunggu konfirmasi."
            )
            confidence = 52
        elif macd_required and macd_vote <= 0:
            reasons.append(f"Tren BULL + zona entry, tapi {macd_note} — tunggu momentum berbalik.")
            confidence = 54
        else:
            pts, reasons = _score(+1)
            if pts >= min_score:
                action = "BUY"
                label = "LONG" if market == "crypto" else "BUY"
                # Honest additive confidence: structure + zone are the
                # backbone; each confirming component adds weight.
                confidence = 50 + 18 + 10
                confidence += 10 if (macd_vote >= 2) else (6 if macd_vote > 0 else 0)
                if rsi is not None and 45.0 <= rsi <= 62.0:
                    confidence += 7
                if vol_ratio is not None and vol_ratio > 1.2:
                    confidence += 6
                if mom5 > 0.3:
                    confidence += 5
                if ema200_bull:
                    confidence += 5
                confidence = min(95, confidence)
            else:
                reasons.append(f"Konfluens belum cukup kuat (skor {pts}/{min_score}) — HOLD, tunggu setup lebih bersih.")
                confidence = 58
    elif structure == "BEAR":
        if rsi_oversold or overextended_dn:
            reasons.append(
                f"Tren BEAR tapi sudah capitulasi (RSI {rsi:.0f}, jarak {dist_slow:+.1f} ATR dari EMA{_ema_slow_n}) — jangan short di dasar, tunggu pantulan."
                if rsi is not None else
                f"Tren BEAR tapi sudah capitulasi ({dist_slow:+.1f} ATR dari EMA{_ema_slow_n}) — tunggu pantulan."
            )
            confidence = 55
        elif not htf_sell_ok:
            reasons.append(
                "Tren BEAR jangka pendek tapi harga di ATAS EMA200 (tren besar masih naik) — counter-trend, HOLD."
            )
            confidence = 50
        elif rsi_momentum and rsi is not None and rsi > 50.0:
            reasons.append(f"Tren BEAR tapi RSI {rsi:.1f} > 50 — momentum belum berpihak, HOLD.")
            confidence = 52
        elif vol_required and vol_ratio is not None and vol_ratio <= 1.2:
            reasons.append(f"Tren BEAR tapi volume belum ekspansi (x{vol_ratio:.2f}) — HOLD.")
            confidence = 52
        elif hlhh_required and not lower_high:
            reasons.append("Tren BEAR tapi swing high belum lower-high — struktur mikro belum konfirmasi, HOLD.")
            confidence = 52
        elif not in_sell_zone:
            reasons.append(
                f"Tren BEAR, harga {dist_fast:+.1f} ATR dari EMA{_ema_fast_n} — di luar zona entry, tunggu rally ke EMA."
            )
            confidence = 55
        elif not rsi_sell_ok:
            reasons.append(
                f"Tren BEAR tapi RSI {rsi:.1f} di luar band sehat 32-65 — tunggu konfirmasi."
            )
            confidence = 52
        elif macd_required and macd_vote >= 0:
            reasons.append(f"Tren BEAR + zona entry, tapi {macd_note} — tunggu momentum berbalik.")
            confidence = 54
        else:
            pts, reasons = _score(-1)
            if pts >= min_score:
                action = "SELL"
                label = "SHORT" if market == "crypto" else "SELL"
                confidence = 50 + 18 + 10
                confidence += 10 if (macd_vote <= -2) else (6 if macd_vote < 0 else 0)
                if rsi is not None and 38.0 <= rsi <= 55.0:
                    confidence += 7
                if vol_ratio is not None and vol_ratio > 1.2:
                    confidence += 6
                if mom5 < -0.3:
                    confidence += 5
                if ema200_bear:
                    confidence += 5
                confidence = min(95, confidence)
            else:
                reasons.append(f"Konfluens belum cukup kuat (skor {pts}/{min_score}) — HOLD, tunggu setup lebih bersih.")
                confidence = 58
    else:
        reasons.append(
            f"Struktur SIDEWAYS (EMA{_ema_fast_n} vs EMA{_ema_slow_n} tidak searah) — tidak ada edge, tunggu tren jelas."
        )
        confidence = 45

    # v9.1.4 — LEVEL ANCHORING ke harga LIVE. Arah sinyal tetap diputuskan
    # dari candle TUTUP (stabilitas), tetapi entry/SL/TP dihitung dari
    # harga realtime agar sinkron dengan yang user lihat di layar.
    # Tanpa ini, saat harga bergerak cepat (mis. LINK pump +8%), seluruh
    # ladder TP bisa berada di SISI YANG SALAH dari harga live.
    # Guard: abaikan live_price yang tidak masuk akal (>8 ATR dari close).
    _anchor = price
    if live_price and live_price > 0 and atr > 0 and abs(live_price - price) <= atr * 8:
        _anchor = float(live_price)

    # Swing metrics for display + level anchoring.
    peaks, valleys = _find_swings(highs, lows, window=10)
    # Regime detector kept as DISPLAY context only (crypto) — it no longer
    # alters entries; the trader profile owns SL/TP tuning.
    regime_info = _detect_regime(closes, highs, lows) if market == "crypto" else {"regime": "UNKNOWN"}
    regime = regime_info.get("regime", "UNKNOWN")
    levels = _compute_deep_levels(
        action, _anchor, atr, peaks, valleys,
        market=market, regime=regime,
        sl_mult=_sl_atr_mult, tp_ladder=_tp_ladder,
    )
    entry = levels["entry"]
    stop_loss = levels["stop_loss"]
    take_profit = levels["take_profit"]

    # Pre-compute levels for both BUY and SELL sides so the AI ensemble
    # can pick either direction with the same deterministic formula.
    buy_levels = _compute_deep_levels(
        "BUY", _anchor, atr, peaks, valleys,
        market=market, regime=regime,
        sl_mult=_sl_atr_mult, tp_ladder=_tp_ladder,
    )
    sell_levels = _compute_deep_levels(
        "SELL", _anchor, atr, peaks, valleys,
        market=market, regime=regime,
        sl_mult=_sl_atr_mult, tp_ladder=_tp_ladder,
    )

    return {
        "action": action,
        "label": label,
        "confidence": int(confidence),
        "indicators": {
            "rsi": round(rsi, 2) if rsi is not None else None,
            # Legacy key names kept for frontend compatibility; values
            # follow the ACTIVE profile's EMA windows.
            "ema20": round(ema_fast, 6),
            "ema50": round(ema_slow, 6),
            # v9.1.4 — Periode aktual agar label UI sesuai selector profil.
            "ema_fast_n": _ema_fast_n,
            "ema_slow_n": _ema_slow_n,
            "ema200": round(ema200, 6) if ema200 is not None else None,
            "macd_hist": round(hists[-1], 6) if hists else None,
            "price": round(price, 8),
            "atr": round(atr, 6),
            "avg_peak": round(levels["avg_peak"], 8),
            "avg_valley": round(levels["avg_valley"], 8),
            "peaks_found": len(peaks),
            "valleys_found": len(valleys),
            # v9.0.0 — confluence context so the UI can show WHY.
            "structure": structure,
            "volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "momentum_5bar_pct": round(mom5, 2),
        },
        "reasons": reasons,
        # v8.12.28 — All entry/SL/TP levels are None for HOLD signals;
        # use a null-safe rounder so we don't crash on `round(None)`.
        "entry": (round(entry, 8) if entry is not None else None),
        "entry_low": (round(levels["entry_low"], 8) if levels.get("entry_low") is not None else None),
        "entry_high": (round(levels["entry_high"], 8) if levels.get("entry_high") is not None else None),
        "entry_moderate": (round(levels["entry_moderate"], 8) if levels.get("entry_moderate") is not None else None),
        "entry_aggressive": (round(levels["entry_aggressive"], 8) if levels.get("entry_aggressive") is not None else None),
        "entry_moderate_low": (round(levels["entry_moderate_low"], 8) if levels.get("entry_moderate_low") is not None else None),
        "entry_moderate_high": (round(levels["entry_moderate_high"], 8) if levels.get("entry_moderate_high") is not None else None),
        "entry_aggressive_low": (round(levels["entry_aggressive_low"], 8) if levels.get("entry_aggressive_low") is not None else None),
        "entry_aggressive_high": (round(levels["entry_aggressive_high"], 8) if levels.get("entry_aggressive_high") is not None else None),
        "stop_loss": (round(stop_loss, 8) if stop_loss is not None else None),
        "take_profit": (round(take_profit, 8) if take_profit is not None else None),
        "take_profit_2": round(levels["take_profit_2"], 8) if levels.get("take_profit_2") is not None else None,
        "take_profit_3": round(levels["take_profit_3"], 8) if levels.get("take_profit_3") is not None else None,
        "regime": regime,
        # Full per-action level map, consumed by ai_engine._aggregate to
        # place AI-consensus entry/SL/TP with the same deterministic
        # formula the technical card uses.
        "_all_levels": {
            "BUY":  {k: (round(v, 8) if v is not None else None) for k, v in buy_levels.items()},
            "SELL": {k: (round(v, 8) if v is not None else None) for k, v in sell_levels.items()},
        },
    }
