"""
v8.12.57 — Backtest 3 versi formula pada 2000 candle BTC dari Binance.

Formula:
- v1: /tmp/backtest/v1.py (btc_trading_formula_v1.py)
- v2: /tmp/backtest/v2.py (btc_trading_formula_v2.py)
- v3: backend/indicators.py (compute_signal with profile)

Untuk v3 kita test 4 profile: scalper, day, swing, longterm.

Metode simulasi (walk-forward):
1. Ambil 2000 candle 1h BTCUSDT.
2. Pada setiap bar i (i >= 200 supaya indikator siap), jalankan formula.
3. Kalau signal BUY:
   - entry = close[i]
   - SL = entry - sl_dist  (dari formula)
   - TP = entry + risk*2   (fixed 1:2 R:R untuk fairness)
   - forward-scan hingga max_hold bar atau sampai SL / TP terpicu
4. Kalau signal SELL: cermin (short).
5. Skip signal HOLD.
6. Cool-down: setelah 1 trade close, tunggu 3 bar sebelum entry baru.

Output:
- total_trades, wins, losses, win_rate
- total_pnl_pct (buy-hold baseline juga)
- avg_win_pct, avg_loss_pct
- max_drawdown
- profit_factor

Rank hasil: mana formula paling profitable + untuk profile mana v3 optimal.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import urllib.request

# Fix import paths
sys.path.insert(0, "/tmp/backtest")
sys.path.insert(0, "/app/backend")


def fetch_binance_klines(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 1000) -> list[dict]:
    """Fetch klines. Binance max limit=1000, so we chain 2 calls for 2000."""
    all_klines = []
    end_time = int(time.time() * 1000)
    for _ in range(2):
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}&endTime={end_time}"
        req = urllib.request.Request(url, headers={"User-Agent": "backtest/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        all_klines = batch + all_klines
        # earliest open_time of this batch becomes next endTime
        end_time = batch[0][0] - 1
        time.sleep(0.2)
    # De-dupe
    seen = set()
    uniq = []
    for k in all_klines:
        if k[0] in seen:
            continue
        seen.add(k[0])
        uniq.append(k)
    uniq.sort(key=lambda k: k[0])
    return [
        {
            "ts": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
        for k in uniq
    ]


# ---------------------------------------------------------------------------
# Import formula modules
# ---------------------------------------------------------------------------
import v1 as fv1  # noqa: E402
import v2 as fv2  # noqa: E402
from indicators import compute_signal as fv3_compute  # noqa: E402


def signal_v1(candles_slice: list[dict]) -> dict | None:
    """v1 signal from btc_trading_formula_v1.py."""
    if len(candles_slice) < 60:
        return None
    closes = [c["close"] for c in candles_slice]
    highs = [c["high"] for c in candles_slice]
    lows = [c["low"] for c in candles_slice]
    price = closes[-1]
    result = fv1.get_btc_signal(closes, highs, lows)
    sig = result.get("signal", "NEUTRAL")
    if sig == "NEUTRAL":
        return None
    atr_val = fv1.atr(highs, lows, closes, period=14)
    if atr_val is None or atr_val <= 0:
        return None
    levels = fv1.calculate_trade_levels(price, atr_val, sig)
    return {
        "action": "BUY" if sig == "LONG" else "SELL",
        "entry": price,
        "sl": levels["stop_loss"],
        "tp": levels["take_profit_2"],
    }


def signal_v2(candles_slice: list[dict]) -> dict | None:
    """v2 signal from btc_trading_formula_v2.py."""
    if len(candles_slice) < 60:
        return None
    closes = [c["close"] for c in candles_slice]
    highs = [c["high"] for c in candles_slice]
    lows = [c["low"] for c in candles_slice]
    price = closes[-1]
    result = fv2.get_btc_signal(closes, highs, lows)
    sig = result.get("signal", "NEUTRAL")
    if sig == "NEUTRAL":
        return None
    atr_val = fv2.atr(highs, lows, closes, period=14)
    if atr_val is None or atr_val <= 0:
        return None
    regime = fv2.detect_market_regime(closes, highs, lows)
    preset = fv2.get_preset(regime.get("regime", "SIDEWAYS"))
    levels = fv2.calculate_trade_levels(
        price, atr_val, sig,
        sl_atr_mult=preset.get("sl_atr_mult", 1.5),
    )
    return {
        "action": "BUY" if sig == "LONG" else "SELL",
        "entry": price,
        "sl": levels["stop_loss"],
        "tp": levels["take_profit_2"],
    }


def signal_v3(candles_slice: list[dict], profile: str) -> dict | None:
    """v3 signal from backend/indicators.py compute_signal."""
    if len(candles_slice) < 60:
        return None
    res = fv3_compute(candles_slice, "crypto", profile=profile)
    if res["action"] == "HOLD" or not res.get("entry") or not res.get("stop_loss") or not res.get("take_profit"):
        return None
    return {
        "action": res["action"],
        "entry": res["entry"],
        "sl": res["stop_loss"],
        "tp": res["take_profit"],
    }


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
def simulate(candles: list[dict], signal_fn, name: str, warmup: int = 200, max_hold: int = 48, cooldown: int = 3) -> dict:
    trades: list[dict] = []
    equity: list[float] = [1.0]
    peak = 1.0
    max_dd = 0.0
    i = warmup
    while i < len(candles) - 1:
        window = candles[: i + 1]
        s = signal_fn(window)
        if not s:
            i += 1
            continue
        # Enter at close of bar i
        entry = s["entry"]
        sl = s["sl"]
        tp = s["tp"]
        # Sanity: ensure SL/TP are on the right side
        if s["action"] == "BUY" and (sl >= entry or tp <= entry):
            i += 1
            continue
        if s["action"] == "SELL" and (sl <= entry or tp >= entry):
            i += 1
            continue
        # Forward scan
        outcome = None
        exit_price = entry
        exit_bar = i
        for j in range(1, max_hold + 1):
            if i + j >= len(candles):
                break
            hi = candles[i + j]["high"]
            lo = candles[i + j]["low"]
            if s["action"] == "BUY":
                if lo <= sl:
                    outcome = "loss"
                    exit_price = sl
                    exit_bar = i + j
                    break
                if hi >= tp:
                    outcome = "win"
                    exit_price = tp
                    exit_bar = i + j
                    break
            else:  # SELL
                if hi >= sl:
                    outcome = "loss"
                    exit_price = sl
                    exit_bar = i + j
                    break
                if lo <= tp:
                    outcome = "win"
                    exit_price = tp
                    exit_bar = i + j
                    break
        if outcome is None:
            # time-based close at bar i+max_hold
            j = min(max_hold, len(candles) - 1 - i)
            exit_price = candles[i + j]["close"]
            exit_bar = i + j
            outcome = "win" if (
                (s["action"] == "BUY" and exit_price > entry)
                or (s["action"] == "SELL" and exit_price < entry)
            ) else "loss"
        # PnL
        pnl = (exit_price - entry) / entry if s["action"] == "BUY" else (entry - exit_price) / entry
        trades.append({
            "bar": i, "outcome": outcome, "pnl": pnl,
            "action": s["action"], "entry": entry, "exit": exit_price,
        })
        cur_equity = equity[-1] * (1 + pnl)
        equity.append(cur_equity)
        if cur_equity > peak:
            peak = cur_equity
        dd = (peak - cur_equity) / peak
        if dd > max_dd:
            max_dd = dd
        # Advance past exit + cooldown
        i = exit_bar + cooldown

    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    total_pnl_pct = (equity[-1] - 1.0) * 100 if equity else 0.0
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    avg_win = (sum(t["pnl"] for t in wins) / len(wins) * 100) if wins else 0.0
    avg_loss = (sum(t["pnl"] for t in losses) / len(losses) * 100) if losses else 0.0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    return {
        "formula": name,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
    }


def buy_hold(candles: list[dict], warmup: int = 200) -> dict:
    entry = candles[warmup]["close"]
    exit_p = candles[-1]["close"]
    return {
        "formula": "buy_hold",
        "total_pnl_pct": round((exit_p - entry) / entry * 100, 2),
        "trades": 1,
        "wins": 1 if exit_p > entry else 0,
        "losses": 0 if exit_p > entry else 1,
    }


def main() -> None:
    print("Fetching 2000 x 1h BTCUSDT candles from Binance…")
    candles = fetch_binance_klines(symbol="BTCUSDT", interval="1h", limit=1000)
    print(f"Total candles: {len(candles)}")
    if len(candles) < 500:
        print("Not enough data; aborting.")
        return

    results: list[dict] = []
    print("\n=== Running v1 (btc_trading_formula_v1) ===")
    results.append(simulate(candles, signal_v1, "v1"))
    print("=== Running v2 (btc_trading_formula_v2) ===")
    results.append(simulate(candles, signal_v2, "v2"))
    print("=== Running v3 x 4 profiles ===")
    for p in ("scalper", "day", "swing", "longterm"):
        results.append(simulate(candles, lambda w, _p=p: signal_v3(w, _p), f"v3-{p}"))

    bh = buy_hold(candles)

    print("\n" + "=" * 92)
    print(f"{'Formula':<15} {'Trades':>7} {'WinRate':>9} {'TotalPnL%':>11} {'AvgWin%':>9} {'AvgLoss%':>10} {'MaxDD%':>8} {'PF':>6}")
    print("=" * 92)
    for r in results:
        print(f"{r['formula']:<15} {r['trades']:>7} {r['win_rate']:>8.1f}% {r['total_pnl_pct']:>10.2f}% {r['avg_win_pct']:>8.2f}% {r['avg_loss_pct']:>9.2f}% {r['max_drawdown_pct']:>7.2f}% {str(r['profit_factor']):>6}")
    print("-" * 92)
    print(f"{'buy_hold':<15} {bh['trades']:>7} {'—':>9} {bh['total_pnl_pct']:>10.2f}%")
    print("=" * 92)

    print("\nRanked by TotalPnL (best profitable):")
    for r in sorted(results, key=lambda x: x["total_pnl_pct"], reverse=True):
        print(f"  {r['formula']:<15}  {r['total_pnl_pct']:>7.2f}%  WR {r['win_rate']:>4.1f}%  PF {r['profit_factor']}")

    print("\nRanked by WinRate:")
    for r in sorted(results, key=lambda x: x["win_rate"], reverse=True):
        print(f"  {r['formula']:<15}  WR {r['win_rate']:>4.1f}%  ({r['trades']} trades)  PnL {r['total_pnl_pct']}%")

    # Save JSON for future comparison
    out = Path("/app/backend/backtest_results.json")
    out.write_text(json.dumps({"candles": len(candles), "results": results, "buy_hold": bh}, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
