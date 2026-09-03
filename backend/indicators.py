"""Pure-Python technical indicators + rule-based signal generator.

Used for fast dashboard signals (no LLM call). Returns BUY / SELL / HOLD plus
confidence percentage derived from how many indicators agree.
"""
from __future__ import annotations

from typing import Any


# v8.12.57 — Trader Profile presets (BTC Trading Formula v2 upgrade).
# Applied ONLY for volatile continuous-market instruments (crypto, forex,
# gold/silver). Stocks/commodity keep the market-neutral defaults because
# they trade in sessions and exhibit different volatility patterns.
#
# Each preset tunes:
#   ema_fast / ema_slow    — trend detection window
#   min_confidence         — signal quality gate (higher = fewer but stronger signals)
#   sl_atr_mult            — Stop-Loss distance as multiple of ATR
#   htf_required           — must higher-timeframe agree (v2 MTF filter)
#   description            — shown in the picker modal
TRADER_PROFILES: dict[str, dict[str, Any]] = {
    "scalper": {
        "ema_fast": 5,
        "ema_slow": 13,
        "min_confidence": 55,
        "sl_atr_mult": 1.0,
        "htf_required": False,
        "description": "5m–15m intraday moves",
    },
    "day": {  # default — matches legacy v8.x behaviour
        "ema_fast": 20,
        "ema_slow": 50,
        "min_confidence": 65,
        "sl_atr_mult": 1.5,
        "htf_required": False,
        "description": "1h–4h day trading",
    },
    "swing": {
        "ema_fast": 20,
        "ema_slow": 50,
        "min_confidence": 75,
        "sl_atr_mult": 2.0,
        "htf_required": True,
        "description": "4h–24h multi-day",
    },
    "longterm": {
        "ema_fast": 50,
        "ema_slow": 200,
        "min_confidence": 80,
        "sl_atr_mult": 3.0,
        "htf_required": True,
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


# v8.7.23 — Regime → parameter preset (buffer × ATR for entry band,
# SL multiplier × ATR for stop distance). BEAR gets tighter entry (avoid
# chasing lower highs) and wider SL (survive volatility). BEAR_CAPITULATION
# is even more defensive.
REGIME_PRESETS: dict[str, dict[str, float]] = {
    "BULL":              {"entry_buffer_mult": 0.25, "sl_atr_mult": 1.5},
    "SIDEWAYS":          {"entry_buffer_mult": 0.25, "sl_atr_mult": 1.5},
    "BEAR":              {"entry_buffer_mult": 0.20, "sl_atr_mult": 2.0},
    "BEAR_CAPITULATION": {"entry_buffer_mult": 0.15, "sl_atr_mult": 2.5},
    "UNKNOWN":           {"entry_buffer_mult": 0.25, "sl_atr_mult": 1.5},
}


def _compute_deep_levels(
    action: str,
    price: float,
    atr: float,
    peaks: list[float],
    valleys: list[float],
    market: str = "crypto",
    regime: str = "UNKNOWN",
) -> dict[str, float]:
    """Return entry/SL/TP using tier-based deep-entry formula.

    v8.2.1 — Split formula per market class:
      - Crypto: swing-based deep entry (unchanged)
      - Non-crypto (stock/ETF/gold/commodity/forex): percentage-based
        because these markets are much less volatile than crypto and
        entries should be close to current price.
        For BUY: entry range 0.1%-0.5% below price; TP +3%; SL -2%
        For SELL: entry range 0.1%-0.5% above price; TP -3%; SL +2%
    """
    recent_peaks = peaks[-5:] if len(peaks) >= 5 else peaks
    recent_valleys = valleys[-5:] if len(valleys) >= 5 else valleys
    last3_peaks = recent_peaks[-3:] if len(recent_peaks) >= 3 else recent_peaks
    last3_valleys = recent_valleys[-3:] if len(recent_valleys) >= 3 else recent_valleys

    def _safe_avg(xs: list[float], fallback: float) -> float:
        return (sum(xs) / len(xs)) if xs else fallback

    avg_peak = _safe_avg(last3_peaks, price * 1.05)
    avg_valley = _safe_avg(last3_valleys, price * 0.95)
    lowest_valley = min(recent_valleys) if recent_valleys else price * 0.93
    highest_peak = max(recent_peaks) if recent_peaks else price * 1.07

    # v8.2.1 — Non-crypto markets use percentage formula (stocks are
    # much less volatile than crypto, so swing-based entries would be
    # unrealistically far from current price).
    is_stocklike = market in ("stock_id", "stock_us", "world_stocks", "etf",
                              "gold_silver", "commodity", "forex")
    if is_stocklike and action in ("BUY", "SELL"):
        # R:R = 1:1.5 per user spec — 2% risk, 3% reward.
        if action == "BUY":
            entry_deep = price * 0.995        # 0.5% below (safest wait)
            entry_moderate = price * 0.997    # 0.3% below (balanced)
            entry_aggressive = price * 0.999  # 0.1% below (aggressive)
            take_profit = price * 1.030       # +3%
            stop_loss = entry_deep * 0.980    # -2% from entry
            sl_deep = entry_deep * 0.980
            sl_moderate = entry_moderate * 0.980
            sl_aggressive = entry_aggressive * 0.980
        else:  # SELL
            entry_deep = price * 1.005        # 0.5% above
            entry_moderate = price * 1.003
            entry_aggressive = price * 1.001
            take_profit = price * 0.970       # -3%
            stop_loss = entry_deep * 1.020    # +2% from entry
            sl_deep = entry_deep * 1.020
            sl_moderate = entry_moderate * 1.020
            sl_aggressive = entry_aggressive * 1.020
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
            "stop_loss": stop_loss,
            "stop_loss_moderate": sl_moderate,
            "stop_loss_aggressive": sl_aggressive,
            "take_profit": take_profit,
            # v8.7.23 — stocklike doesn't use the regime R:R ladder; frontend
            # falls back to its own derived tp2/tp3 when these are None.
            "take_profit_2": None,
            "take_profit_3": None,
            "avg_peak": avg_peak,
            "avg_valley": avg_valley,
        }

    if action == "BUY":
        # v8.7.23 — Regime-aware crypto BUY (per user's btc_trading_formula).
        # entry_deep = price − buffer×ATR, SL = entry − sl_mult×ATR,
        # risk = entry − SL, TP1/2/3 = 1×/2×/3× risk (R:R 1:1, 1:2, 1:3).
        # Preset buffer/sl_mult varies by regime (BEAR gets tighter buffer
        # + wider SL). Falls back to swing anchors if ATR is degenerate.
        preset = REGIME_PRESETS.get(regime, REGIME_PRESETS["UNKNOWN"])
        buf = atr * preset["entry_buffer_mult"]
        sl_dist = atr * preset["sl_atr_mult"]
        entry_deep = price - buf
        entry_moderate = price
        entry_aggressive = price + buf * 0.5
        band = buf
        stop_loss = entry_deep - sl_dist
        risk = max(entry_deep - stop_loss, price * 0.005)
        take_profit = entry_deep + risk * 1.0    # TP-1 = 1R
        take_profit_2 = entry_deep + risk * 2.0  # TP-2 = 2R
        take_profit_3 = entry_deep + risk * 3.0  # TP-3 = 3R
        sl_deep = stop_loss
        sl_moderate = entry_moderate - sl_dist
        sl_aggressive = entry_aggressive - sl_dist
    elif action == "SELL":
        # v8.7.23 — Regime-aware crypto SELL (mirror of BUY).
        preset = REGIME_PRESETS.get(regime, REGIME_PRESETS["UNKNOWN"])
        buf = atr * preset["entry_buffer_mult"]
        sl_dist = atr * preset["sl_atr_mult"]
        entry_deep = price + buf
        entry_moderate = price
        entry_aggressive = price - buf * 0.5
        band = buf
        stop_loss = entry_deep + sl_dist
        risk = max(stop_loss - entry_deep, price * 0.005)
        take_profit = entry_deep - risk * 1.0
        take_profit_2 = entry_deep - risk * 2.0
        take_profit_3 = entry_deep - risk * 3.0
        sl_deep = stop_loss
        sl_moderate = entry_moderate + sl_dist
        sl_aggressive = entry_aggressive + sl_dist
    else:  # HOLD
        # v8.12.28 — HOLD signals no longer emit entry/SL/TP levels.
        # Reason: users reported that the previous "informational dip-buy
        # zone" (entry below price + TP above + SL below entry) LOOKED
        # exactly like a BUY LONG suggestion — so they placed the trade
        # anyway. Now HOLD returns null for every level and the frontend
        # can render a clean "No entry — market indecisive, tunggu
        # konfirmasi" state instead of a fake ladder.
        entry_deep = None
        entry_moderate = None
        entry_aggressive = None
        band = 0.0
        take_profit = None
        take_profit_2 = None
        take_profit_3 = None
        stop_loss = None
        sl_deep = sl_moderate = sl_aggressive = None

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
        "stop_loss": stop_loss,
        "stop_loss_moderate": sl_moderate,
        "stop_loss_aggressive": sl_aggressive,
        "take_profit": take_profit,
        "take_profit_2": take_profit_2,
        "take_profit_3": take_profit_3,
        "avg_peak": avg_peak,
        "avg_valley": avg_valley,
    }


def compute_signal(
    candles: list[dict[str, Any]],
    market: str,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return signal dict: action, confidence, indicators, entry/sl/tp suggestions.

    Action: BUY / SELL / HOLD. For crypto we also surface LONG/SHORT in label.

    v8.12.57 — When `profile` is provided AND market is in
    PROFILE_APPLICABLE_MARKETS (crypto/forex/gold_silver), the EMA windows,
    minimum confidence gate, and SL/ATR multiplier are swapped for the
    profile-tuned preset from TRADER_PROFILES. All other markets (stocks,
    commodity, ETFs) keep the market-neutral defaults so their behaviour
    is unchanged.
    """
    if not candles or len(candles) < 20:
        return {
            "action": "HOLD",
            "label": "HOLD",
            "confidence": 0,
            "indicators": {},
            "reasons": [],
            "entry": None, "stop_loss": None, "take_profit": None,
        }

    # Resolve trader-profile presets. Only apply on eligible markets so that
    # stocks / commodity / etf keep the current v8.x day-trader defaults.
    _prof = get_trader_profile(profile) if market in PROFILE_APPLICABLE_MARKETS else get_trader_profile("day")
    _ema_fast_n = int(_prof["ema_fast"])
    _ema_slow_n = int(_prof["ema_slow"])
    _min_conf_gate = int(_prof["min_confidence"])
    _sl_atr_mult = float(_prof["sl_atr_mult"])

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1]

    rsi = _rsi(closes, 14)
    ema20 = _ema(closes, _ema_fast_n)[-1]
    ema50 = _ema(closes, _ema_slow_n)[-1] if len(closes) >= _ema_slow_n else ema20
    macd = _macd(closes)

    # Vote per indicator
    votes: list[int] = []  # +1 bullish, -1 bearish, 0 neutral
    reasons: list[str] = []

    def _vote(v: int, reason: str) -> None:
        votes.append(v)
        reasons.append(reason)

    # v8.7.0 — Restored strict v1.0.x-style scoring (target Win Rate >70%).
    # Rationale: The old v8.x formula (baseline 55, score>=2) let mediocre
    # 2-of-5 signals into the Premium bucket → WR degraded to ~50%. We now
    # require STRONG multi-indicator confirmation (score>=3, RSI-directional
    # confirmation, MACD alignment) and drop the confidence baseline.

    # --- Trend strength (used to weight EMA vs mean-reversion RSI) ---
    ema_spread_pct = abs(ema20 - ema50) / ema50 * 100 if ema50 else 0
    strong_trend = ema_spread_pct > 0.5  # trend is dominant → suppress mean-rev RSI

    # --- RSI (14) --- mean-reversion vote, but SUPPRESSED in strong trends.
    #     In choppy/ranging market: RSI < 30 = BUY, > 70 = SELL.
    #     In strong trend: extreme RSI is a momentum signal, not a reversal —
    #     so we vote WITH the trend (softer weight) instead of against.
    #     v8.12.22 — But cap the "momentum continuation" vote at RSI 78
    #     for uptrend and RSI 22 for downtrend so we don't help users
    #     enter parabolic tops / capitulation bottoms.
    if rsi is not None:
        if strong_trend:
            trend_sign_ema = 1 if ema20 > ema50 else -1
            if trend_sign_ema > 0 and 55 < rsi < 78:
                _vote(1, f"RSI {rsi:.1f} momentum-up (strong trend)")
            elif trend_sign_ema < 0 and 22 < rsi < 45:
                _vote(-1, f"RSI {rsi:.1f} momentum-down (strong trend)")
            elif trend_sign_ema > 0 and rsi >= 78:
                # Uptrend but RSI extreme — DO NOT vote BUY; flag caution.
                _vote(0, f"RSI {rsi:.1f} extreme — avoid FOMO")
            elif trend_sign_ema < 0 and rsi <= 22:
                # Downtrend but RSI extreme — DO NOT vote SELL; flag caution.
                _vote(0, f"RSI {rsi:.1f} extreme — avoid panic sell")
            else:
                _vote(0, f"RSI {rsi:.1f} (trend-suppressed)")
        else:
            if rsi < 30:
                _vote(1, f"RSI {rsi:.1f} strong oversold")
            elif rsi < 40:
                _vote(1, f"RSI {rsi:.1f} oversold")
            elif rsi > 70:
                _vote(-1, f"RSI {rsi:.1f} strong overbought")
            elif rsi > 60:
                _vote(-1, f"RSI {rsi:.1f} overbought")
            else:
                _vote(0, f"RSI {rsi:.1f} netral")

    # --- EMA crossover / trend (weighted 2x when spread > 0.3%) ---
    if ema20 > ema50:
        v = 2 if ema_spread_pct > 0.3 else 1
        _vote(v, f"EMA20>EMA50 (uptrend, spread {ema_spread_pct:.2f}%)")
    elif ema20 < ema50:
        v = -2 if ema_spread_pct > 0.3 else -1
        _vote(v, f"EMA20<EMA50 (downtrend, spread {ema_spread_pct:.2f}%)")

    # --- Price vs EMA20 (tighter band 0.3% instead of 0.2%) ---
    if price > ema20 * 1.003:
        _vote(1, "Price above EMA20 (+0.3%)")
    elif price < ema20 * 0.997:
        _vote(-1, "Price below EMA20 (-0.3%)")

    # --- MACD histogram + direction ---
    if macd:
        _m, _s, hist = macd
        # Require histogram to be meaningful — tiny hist near zero = noise.
        hist_abs = abs(hist)
        threshold = max(price * 0.0005, 1e-9)  # 0.05% of price as noise floor
        if hist > threshold:
            _vote(1, "MACD histogram positif")
        elif hist < -threshold:
            _vote(-1, "MACD histogram negatif")

    # --- Momentum: last 5 candles (raised bar to 2% for stronger conviction) ---
    if len(closes) >= 6:
        mom = (closes[-1] - closes[-6]) / closes[-6] * 100
        if mom > 2.0:
            _vote(1, f"Momentum 5-bar +{mom:.2f}%")
        elif mom < -2.0:
            _vote(-1, f"Momentum 5-bar {mom:.2f}%")

    # --- Volume expansion: last 3 candles avg > previous 10 avg by 20% ---
    volumes: list[float] = [c.get("volume", 0) or 0 for c in candles]
    if len(volumes) >= 13:
        recent_vol = sum(volumes[-3:]) / 3
        prior_vol = sum(volumes[-13:-3]) / 10
        if prior_vol > 0 and recent_vol / prior_vol > 1.2:
            # Volume expansion confirms direction — add vote in trend direction
            trend_sign = 1 if (ema20 > ema50 and price > ema20) else (-1 if (ema20 < ema50 and price < ema20) else 0)
            if trend_sign != 0:
                _vote(trend_sign, f"Volume expansion x{recent_vol/prior_vol:.2f}")

    score = sum(votes)
    total = len(votes) or 1
    # v8.7.0 — Real confidence: |score|/total * scale, NO artificial baseline.
    # Requires broad + strong agreement to hit Premium threshold (85+).
    max_possible = sum(abs(v) for v in votes) or 1
    agreement = abs(score) / max_possible * 100.0
    # Strong-agreement bonus (score>=4 or score>=5)
    boost = 0
    if abs(score) >= 5:
        boost = 12
    elif abs(score) >= 4:
        boost = 8
    elif abs(score) >= 3:
        boost = 4
    confidence = round(min(98.0, max(35.0, agreement * 0.80 + boost)))

    # v8.7.0 — Directional confirmation gate:
    # Only issue BUY/SELL when:
    #   • score >= 3 (was 2) → at least 3-net-indicator agreement
    #   • Price vs EMA20 aligns with signal side (trend confirmation)
    ema_align_buy = price > ema20 * 0.997
    ema_align_sell = price < ema20 * 1.003

    # v8.12.22 — Anti-FOMO / anti-panic overextension guard.
    # v8.12.23 — Tightened + added "near recent high/low" veto.
    # v8.12.24 — Per-market threshold tuning.
    # v8.12.26 — Multi-timeframe extreme detection + rally-exhaustion:
    #             DSSA rallied +28.8 % from its 120-day low but the 30-day
    #             window said "not near a high" so the old guard missed it.
    #             Now check 30 / 60 / 120-candle horizons AND a
    #             "rally-exhaustion" trigger that fires when price has
    #             surged >20 % from the multi-week low with elevated RSI.
    #
    # v8.12.27 — Tightened for crypto blue-chips (BTC/ETH) which move
    # in smaller % than small-caps. The old crypto ext_cap 12% and
    # rally-exhaustion 30% never fired for ETH pumping 3-5% into a
    # local top → user still saw LONG at the peak and got stopped out.
    # New crypto row: ext 6% (was 12), RSI near 62 (was 68), rally
    # exhaustion 12% (was 30). Same-day intraday spike also handled.
    _GUARDS: dict[str, tuple[float, float, float, float, float]] = {
        "crypto":       (0.06, 78.0, 22.0, 62.0, 38.0),
        "stock_id":     (0.05, 76.0, 24.0, 60.0, 40.0),
        "stock_us":     (0.05, 76.0, 24.0, 60.0, 40.0),
        "world_stocks": (0.05, 76.0, 24.0, 60.0, 40.0),
        "etf":          (0.04, 74.0, 26.0, 58.0, 42.0),
        "gold_silver":  (0.05, 76.0, 24.0, 60.0, 40.0),
        "commodity":    (0.06, 76.0, 24.0, 60.0, 40.0),
        "forex":        (0.03, 72.0, 28.0, 58.0, 42.0),
    }
    ext_cap, rsi_hi_x, rsi_lo_x, rsi_hi_near, rsi_lo_near = _GUARDS.get(
        market, (0.05, 76.0, 24.0, 60.0, 40.0)
    )
    extension = ((price - ema50) / ema50) if ema50 else 0.0
    overextended_up = extension > ext_cap
    overextended_dn = extension < -ext_cap
    rsi_extreme_up = rsi is not None and rsi >= rsi_hi_x
    rsi_extreme_dn = rsi is not None and rsi <= rsi_lo_x

    # Multi-timeframe recent-extreme veto: check 30 / 60 / 120-candle
    # horizons. Wider horizons catch multi-week rallies (like DSSA
    # rallying +28 % from a 4-month low).
    def _near_extreme(window_size: int) -> tuple[bool, bool]:
        w = closes[-window_size:] if len(closes) >= window_size else closes
        if not w:
            return False, False
        hi = max(w)
        lo = min(w)
        at_top_local = (price / hi) >= 0.98 if hi else False
        at_bot_local = (price / lo) <= 1.02 if lo else False
        return at_top_local, at_bot_local

    at_top_30, at_bot_30 = _near_extreme(30)
    at_top_60, at_bot_60 = _near_extreme(60)
    at_top_120, at_bot_120 = _near_extreme(120)
    at_any_top = at_top_30 or at_top_60 or at_top_120
    at_any_bot = at_bot_30 or at_bot_60 or at_bot_120

    near_top_hot = at_any_top and rsi is not None and rsi >= rsi_hi_near
    near_bot_cold = at_any_bot and rsi is not None and rsi <= rsi_lo_near

    # Rally / capitulation exhaustion: how far did the asset move from
    # its longer-term extreme? A +20 % surge from the 60/120-day low is
    # a classic euphoria zone even if the 4-hour RSI looks calm.
    rally_pct_60 = ((price / min(closes[-60:])) - 1.0) * 100 if len(closes) >= 60 else 0.0
    rally_pct_120 = ((price / min(closes[-120:])) - 1.0) * 100 if len(closes) >= 120 else 0.0
    max_rally = max(rally_pct_60, rally_pct_120)
    drop_pct_60 = (1.0 - (price / max(closes[-60:]))) * 100 if len(closes) >= 60 else 0.0
    drop_pct_120 = (1.0 - (price / max(closes[-120:]))) * 100 if len(closes) >= 120 else 0.0
    max_drop = max(drop_pct_60, drop_pct_120)

    # Rally exhaustion trigger — different threshold per market.
    # v8.12.27 — crypto lowered 30 % → 12 % because BTC/ETH pump into
    # tops in smaller percentages than small-cap alts, so a 30 % rally
    # from a 60-day low was near-never triggered on blue-chips.
    exhaust_up_pct = 12.0 if market == "crypto" else 20.0
    exhaust_dn_pct = 12.0 if market == "crypto" else 20.0
    rally_exhausted = (
        max_rally >= exhaust_up_pct
        and at_any_top
        and rsi is not None and rsi >= (rsi_hi_near - 5)  # e.g. 55+ for stocks
    )
    capitulation_exhausted = (
        max_drop >= exhaust_dn_pct
        and at_any_bot
        and rsi is not None and rsi <= (rsi_lo_near + 5)
    )

    veto_buy = (
        overextended_up or rsi_extreme_up or near_top_hot or rally_exhausted
    )
    veto_sell = (
        overextended_dn or rsi_extreme_dn or near_bot_cold or capitulation_exhausted
    )

    # v8.12.27 — Short-term pump/dump veto. Catches ETH-style intraday
    # spikes (2-5 % move in the last few candles into a local top) that
    # the longer-window checks above miss. Threshold scaled per market.
    short_pump_pct = 3.5 if market == "crypto" else 2.5
    short_dump_pct = 3.5 if market == "crypto" else 2.5
    if len(closes) >= 6:
        mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100
        if mom5 >= short_pump_pct and rsi is not None and rsi >= (rsi_hi_near - 3):
            veto_buy = True
            # Attach descriptive reason if flip happens.
            if score >= 3:
                reasons.append(f"Short-term pump +{mom5:.1f}% dalam 5-bar — jangan chase.")
        elif mom5 <= -short_dump_pct and rsi is not None and rsi <= (rsi_lo_near + 3):
            veto_sell = True
            if score <= -3:
                reasons.append(f"Short-term dump {mom5:.1f}% dalam 5-bar — tunggu stabil.")

    # v8.12.24 — FLIP to mean-reversion action instead of demoting to HOLD.
    if score >= 3 and ema_align_buy and not veto_buy:
        action = "BUY"
        label = "LONG" if market == "crypto" else "BUY"
    elif score <= -3 and ema_align_sell and not veto_sell:
        action = "SELL"
        label = "SHORT" if market == "crypto" else "SELL"
    elif score >= 3 and veto_buy:
        # Trend-up + veto → take profit
        action = "SELL"
        label = "TP" if market == "crypto" else "SELL"
        parts = []
        if overextended_up:
            parts.append(f"harga {extension * 100:+.1f}% dari EMA50")
        if rsi_extreme_up:
            parts.append(f"RSI {rsi:.0f} sangat overbought")
        if near_top_hot:
            horizon = "30d" if at_top_30 else ("60d" if at_top_60 else "120d")
            parts.append(f"harga di puncak {horizon}")
        if rally_exhausted:
            parts.append(f"rally +{max_rally:.0f}% dari low — sudah kepanjangan")
        reasons.append(
            "TAKE PROFIT — " + ", ".join(parts) + ". Jangan kejar harga."
        )
        tp_boost = (18 if overextended_up else 0) + (12 if rsi_extreme_up else 0) + (8 if near_top_hot else 0) + (15 if rally_exhausted else 0)
        confidence = min(95, max(70, 60 + tp_boost))
    elif score <= -3 and veto_sell:
        # Trend-down + veto → buy the dip
        action = "BUY"
        label = "DIP" if market == "crypto" else "BUY"
        parts = []
        if overextended_dn:
            parts.append(f"harga {extension * 100:+.1f}% dari EMA50")
        if rsi_extreme_dn:
            parts.append(f"RSI {rsi:.0f} sangat oversold")
        if near_bot_cold:
            horizon = "30d" if at_bot_30 else ("60d" if at_bot_60 else "120d")
            parts.append(f"harga di dasar {horizon}")
        if capitulation_exhausted:
            parts.append(f"turun {max_drop:.0f}% dari high — capitulasi")
        reasons.append(
            "BUY THE DIP — " + ", ".join(parts) + ". Accumulate bertahap."
        )
        dip_boost = (18 if overextended_dn else 0) + (12 if rsi_extreme_dn else 0) + (8 if near_bot_cold else 0) + (15 if capitulation_exhausted else 0)
        confidence = min(95, max(70, 60 + dip_boost))
    else:
        action = "HOLD"
        label = "HOLD"
        confidence = max(40, min(70, confidence))

    # v8.12.57 — BTC Trading Formula v3: Trader-Profile confidence gate.
    # After the primary BUY/SELL/HOLD decision, downgrade to HOLD if the
    # confidence falls below the trader-profile threshold. This enforces
    # the "signal frequency" personality per profile:
    #   Scalper (55%)  → sees more signals, small wins
    #   Day (65%)      → balanced
    #   Swing (75%)    → fewer but stronger signals
    #   Long-term (80%) → rare, high-conviction only
    # Only applied to eligible markets (crypto / forex / gold_silver).
    if market in PROFILE_APPLICABLE_MARKETS and action in ("BUY", "SELL"):
        if confidence < _min_conf_gate:
            reasons.append(
                f"Downgraded to HOLD — confidence {confidence}% below "
                f"{profile or 'day'} profile threshold {_min_conf_gate}%."
            )
            action = "HOLD"
            label = "HOLD"

    # Compute simple ATR for SL/TP
    if len(highs) >= 14:
        trs = []
        for i in range(1, 14):
            tr = max(
                highs[-i] - lows[-i],
                abs(highs[-i] - closes[-i - 1]),
                abs(lows[-i] - closes[-i - 1]),
            )
            trs.append(tr)
        atr = sum(trs) / len(trs)
    else:
        atr = price * 0.02

    # v8.1.6 — Deep-entry formula (swing-based). Detect peaks/valleys
    # from the full candle history (window=10 mid-swings) and place
    # entry BELOW recent structure so users don't buy tops or short
    # bottoms. Falls back to ATR-based default if not enough swings.
    peaks, valleys = _find_swings(highs, lows, window=10)
    # v8.7.23 — Detect market regime (BULL / BEAR / BEAR_CAPITULATION / …)
    # once per compute so all three level tiers (deep / moderate / aggr)
    # share the SAME regime preset. Crypto only — other markets ignore it.
    regime_info = _detect_regime(closes, highs, lows) if market == "crypto" else {"regime": "UNKNOWN"}
    regime = regime_info.get("regime", "UNKNOWN")
    levels = _compute_deep_levels(action, price, atr, peaks, valleys, market=market, regime=regime)
    entry = levels["entry"]
    stop_loss = levels["stop_loss"]
    take_profit = levels["take_profit"]

    # v8.1.6 — Also pre-compute levels for both BUY and SELL sides so
    # the AI ensemble can pick either direction with the same swing
    # structure — even if the AI action disagrees with the technical
    # rule vote.
    buy_levels = _compute_deep_levels("BUY", price, atr, peaks, valleys, market=market, regime=regime)
    sell_levels = _compute_deep_levels("SELL", price, atr, peaks, valleys, market=market, regime=regime)

    return {
        "action": action,
        "label": label,
        "confidence": int(confidence),
        "indicators": {
            "rsi": round(rsi, 2) if rsi is not None else None,
            "ema20": round(ema20, 6),
            "ema50": round(ema50, 6),
            "macd_hist": round(macd[2], 6) if macd else None,
            "price": round(price, 8),
            "atr": round(atr, 6),
            # v8.1.6 — swing metrics exposed so the frontend can render
            # a full "Entry Levels" card (deep / moderate / aggressive).
            "avg_peak": round(levels["avg_peak"], 8),
            "avg_valley": round(levels["avg_valley"], 8),
            "peaks_found": len(peaks),
            "valleys_found": len(valleys),
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
