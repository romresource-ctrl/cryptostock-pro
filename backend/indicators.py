"""Pure-Python technical indicators + rule-based signal generator.

Used for fast dashboard signals (no LLM call). Returns BUY / SELL / HOLD plus
confidence percentage derived from how many indicators agree.
"""
from __future__ import annotations

from typing import Any


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


def _compute_deep_levels(
    action: str,
    price: float,
    atr: float,
    peaks: list[float],
    valleys: list[float],
    market: str = "crypto",
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
            "avg_peak": avg_peak,
            "avg_valley": avg_valley,
        }

    if action == "BUY":
        # v8.1.8 — Three tiers + entry ZONE (v8.1.9). User trades a
        # range not a point, so we return low/high bounds around each
        # tier at ±0.4 ATR (typical band width ≈ user's expected
        # 1915-1925 range for ETH).
        entry_deep = ((avg_valley + lowest_valley) / 2.0) - atr * 0.5
        entry_moderate = ((price + avg_valley) / 2.0) + atr * 0.3
        entry_aggressive = price - atr * 0.3
        # v8.3.6 — Enforce a MEANINGFUL take-profit distance. On short
        # crypto timeframes (3m/5m) both `avg_peak` and `atr` can be
        # tiny, so the old `max(avg_peak, entry + atr*1.0)` returned a
        # TP only ~$3 above entry — pointless for a LONG trade. We now
        # require the TP to sit at least the greater of:
        #   • 1.0% above the deep entry           (min reward vs entry)
        #   • 0.5% above the current market price (min reward vs spot)
        #   • the average of recent peaks         (structural target)
        #   • entry_deep + 3× ATR                 (volatility target)
        # so both R:R and absolute profit stay realistic even in dead
        # markets.
        min_tp_pct_entry = entry_deep * 1.010
        min_tp_pct_price = price * 1.005
        take_profit = max(
            avg_peak,
            entry_deep + atr * 3.0,
            min_tp_pct_entry,
            min_tp_pct_price,
        )
        sl_deep = entry_deep - atr * 0.5
        sl_moderate = entry_moderate - atr * 0.5
        sl_aggressive = entry_aggressive - atr * 0.5
        stop_loss = sl_deep
        band = atr * 0.4
    elif action == "SELL":
        entry_deep = ((avg_peak + highest_peak) / 2.0) + atr * 0.5
        entry_moderate = ((price + avg_peak) / 2.0) - atr * 0.3
        entry_aggressive = price + atr * 0.3
        # v8.3.6 — Mirror of the BUY fix: enforce a meaningful TP below
        # entry / current price so SHORT trades are worth taking even
        # on quiet 3m/5m timeframes.
        min_tp_pct_entry = entry_deep * 0.990
        min_tp_pct_price = price * 0.995
        take_profit = min(
            avg_valley,
            entry_deep - atr * 3.0,
            min_tp_pct_entry,
            min_tp_pct_price,
        )
        sl_deep = entry_deep + atr * 0.5
        sl_moderate = entry_moderate + atr * 0.5
        sl_aggressive = entry_aggressive + atr * 0.5
        stop_loss = sl_deep
        band = atr * 0.4
    else:  # HOLD
        entry_deep = price
        entry_moderate = price
        entry_aggressive = price
        # v8.3.6 — HOLD is informational (no active trade recommended)
        # but the numbers still surface in the UI. Widen the projection
        # so users see realistic "if the market breaks upward" targets.
        take_profit = max(price + atr * 2.5, price * 1.008)
        stop_loss = min(price - atr * 2.5, price * 0.992)
        sl_deep = sl_moderate = sl_aggressive = stop_loss
        band = atr * 0.4

    return {
        "entry": entry_deep,
        "entry_moderate": entry_moderate,
        "entry_aggressive": entry_aggressive,
        # v8.1.9 — Entry zone (range) around the DEEP default so the
        # frontend can display "$1915-$1925" instead of a single point.
        # Range is ±0.4 ATR wide.
        "entry_low": entry_deep - band,
        "entry_high": entry_deep + band,
        # Also expose zones for the other two tiers so the frontend
        # "Entry Levels" card can render all three ranges.
        "entry_moderate_low": entry_moderate - band,
        "entry_moderate_high": entry_moderate + band,
        "entry_aggressive_low": entry_aggressive - band,
        "entry_aggressive_high": entry_aggressive + band,
        "stop_loss": stop_loss,
        "stop_loss_moderate": sl_moderate,
        "stop_loss_aggressive": sl_aggressive,
        "take_profit": take_profit,
        "avg_peak": avg_peak,
        "avg_valley": avg_valley,
    }


def compute_signal(candles: list[dict[str, Any]], market: str) -> dict[str, Any]:
    """Return signal dict: action, confidence, indicators, entry/sl/tp suggestions.

    Action: BUY / SELL / HOLD. For crypto we also surface LONG/SHORT in label.
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
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    price = closes[-1]

    rsi = _rsi(closes, 14)
    ema20 = _ema(closes, 20)[-1]
    ema50 = _ema(closes, 50)[-1] if len(closes) >= 50 else ema20
    macd = _macd(closes)

    # Vote per indicator
    votes: list[int] = []  # +1 bullish, -1 bearish, 0 neutral
    reasons: list[str] = []

    def _vote(v: int, reason: str) -> None:
        votes.append(v)
        reasons.append(reason)

    # RSI
    if rsi is not None:
        if rsi < 35:
            _vote(1, f"RSI {rsi:.1f} oversold (bullish)")
        elif rsi > 65:
            _vote(-1, f"RSI {rsi:.1f} overbought (bearish)")
        else:
            _vote(0, f"RSI {rsi:.1f} netral")

    # EMA crossover / trend
    if ema20 > ema50:
        _vote(1, "EMA20 > EMA50 (uptrend)")
    elif ema20 < ema50:
        _vote(-1, "EMA20 < EMA50 (downtrend)")

    # Price vs EMA20
    if price > ema20 * 1.002:
        _vote(1, "Price above EMA20")
    elif price < ema20 * 0.998:
        _vote(-1, "Price below EMA20")

    # MACD histogram
    if macd:
        _m, _s, hist = macd
        if hist > 0:
            _vote(1, "MACD histogram positif")
        elif hist < 0:
            _vote(-1, "MACD histogram negatif")

    # Momentum: last 5 candles
    if len(closes) >= 6:
        mom = (closes[-1] - closes[-6]) / closes[-6] * 100
        if mom > 1.5:
            _vote(1, f"Momentum 5-bar +{mom:.2f}%")
        elif mom < -1.5:
            _vote(-1, f"Momentum 5-bar {mom:.2f}%")

    score = sum(votes)
    total = len(votes) or 1
    confidence_raw = abs(score) / total * 100.0
    # Boost confidence with strong agreement
    confidence = round(min(98.0, 55.0 + confidence_raw * 0.45 + (abs(score) >= 4) * 8))

    if score >= 2:
        action = "BUY"
        label = "LONG" if market == "crypto" else "BUY"
    elif score <= -2:
        action = "SELL"
        label = "SHORT" if market == "crypto" else "SELL"
    else:
        action = "HOLD"
        label = "HOLD"
        confidence = max(45, min(65, confidence))

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
    levels = _compute_deep_levels(action, price, atr, peaks, valleys, market=market)
    entry = levels["entry"]
    stop_loss = levels["stop_loss"]
    take_profit = levels["take_profit"]

    # v8.1.6 — Also pre-compute levels for both BUY and SELL sides so
    # the AI ensemble can pick either direction with the same swing
    # structure — even if the AI action disagrees with the technical
    # rule vote.
    buy_levels = _compute_deep_levels("BUY", price, atr, peaks, valleys, market=market)
    sell_levels = _compute_deep_levels("SELL", price, atr, peaks, valleys, market=market)

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
        "entry": round(entry, 8),
        "entry_low": round(levels["entry_low"], 8),
        "entry_high": round(levels["entry_high"], 8),
        "entry_moderate": round(levels["entry_moderate"], 8),
        "entry_aggressive": round(levels["entry_aggressive"], 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),
        # Full per-action level map, consumed by ai_engine._aggregate to
        # place AI-consensus entry/SL/TP with the same deterministic
        # formula the technical card uses.
        "_all_levels": {
            "BUY":  {k: round(v, 8) for k, v in buy_levels.items()},
            "SELL": {k: round(v, 8) for k, v in sell_levels.items()},
        },
    }
