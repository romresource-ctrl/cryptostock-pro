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
        _vote(1, "Harga di atas EMA20")
    elif price < ema20 * 0.998:
        _vote(-1, "Harga di bawah EMA20")

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

    if action == "BUY":
        entry = price
        stop_loss = price - atr * 1.5
        take_profit = price + atr * 2.5
    elif action == "SELL":
        entry = price
        stop_loss = price + atr * 1.5
        take_profit = price - atr * 2.5
    else:
        entry = price
        stop_loss = price - atr * 1.0
        take_profit = price + atr * 1.0

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
        },
        "reasons": reasons,
        "entry": round(entry, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),
    }
