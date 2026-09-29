"""v9.2.3 — Backtest 24 bulan untuk 4 mode strategi.

Modes:
  1. Confluence  (profile=None) — mesin default v9.0
  2. Scalper     (profile='scalper')  — VWAP-SCALPER + Master Pattern 15M
  3. Day Trader  (profile='day')      — VWAP-INTRADAY
  4. Swing       (profile='swing')    — VWAP-SWING

Asset: BTC, ETH, SOL, XRP, BNB (crypto liquid).
Data:  candle 1h dari Binance, 24 bulan terakhir (~17,280 candle/aset).
Eval:  walk-forward, sample setiap 12 candle (12 jam) — cukup untuk WR yang
       stabil tanpa harus compute_signal 17k kali.
Trade: LIMIT order entry_deep, fill dalam 6 candle. TP1 vs SL dalam 24 candle.

Jalankan: cd /app/backend && python backtest_24mo.py
Output:  /app/test_reports/backtest_24mo.json + log stdout.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from indicators import compute_signal

BASE = os.path.dirname(__file__)
OUT_JSON = "/app/test_reports/backtest_24mo.json"

WARMUP = 210
FILL_WINDOW = 6
TRADE_WINDOW = 24
SAMPLE_EVERY = 12  # 12 jam antar eval untuk kecepatan
MONTHS = 24
MS_PER_HOUR = 60 * 60 * 1000

CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]

PROFILES: list[tuple[str, str | None]] = [
    ("Confluence", None),
    ("Scalper",    "scalper"),
    ("DayTrader",  "day"),
    ("Swing",      "swing"),
]


async def fetch_bitget_chunk(client: httpx.AsyncClient, symbol: str, end_ms: int) -> list[list]:
    r = await client.get(
        "https://api.bitget.com/api/v2/spot/market/history-candles",
        params={"symbol": symbol, "granularity": "1h", "limit": 200, "endTime": end_ms},
    )
    r.raise_for_status()
    js = r.json()
    return js.get("data") or []


async def fetch_24mo_1h(client: httpx.AsyncClient, symbol: str) -> list[dict[str, Any]]:
    """Fetch ~17,520 candle 1h (24 bulan) via chunk pagination mundur."""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - MONTHS * 30 * 24 * MS_PER_HOUR
    end_ms = now_ms
    all_rows: dict[int, list] = {}
    empty_streak = 0
    while end_ms > start_ms and empty_streak < 3:
        try:
            batch = await fetch_bitget_chunk(client, symbol, end_ms)
        except Exception as e:
            print(f"  {symbol}: fetch chunk fail: {e}", flush=True)
            break
        if not batch:
            empty_streak += 1
            end_ms -= 1000 * MS_PER_HOUR  # skip 1000 jam ke belakang
            await asyncio.sleep(0.15)
            continue
        empty_streak = 0
        for k in batch:
            all_rows[int(k[0])] = k
        oldest = min(int(k[0]) for k in batch)
        if oldest <= start_ms:
            break
        end_ms = oldest - 1
        await asyncio.sleep(0.15)
    sorted_keys = sorted(all_rows.keys())
    keep = [k for k in sorted_keys if k >= start_ms]
    return [
        {
            "open": float(all_rows[k][1]),
            "high": float(all_rows[k][2]),
            "low": float(all_rows[k][3]),
            "close": float(all_rows[k][4]),
            "volume": float(all_rows[k][5]),
            "time": k,
        }
        for k in keep
    ]


def resample_daily(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resample candle 1h → 1D (UTC) untuk _daily_context (bias 50 SMA)."""
    if not candles:
        return []
    out: list[dict[str, Any]] = []
    cur_day: str | None = None
    o = h = l = c = v = 0.0
    for row in candles:
        d = datetime.fromtimestamp(row["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d != cur_day:
            if cur_day is not None:
                out.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
            cur_day = d
            o = row["open"]; h = row["high"]; l = row["low"]; c = row["close"]; v = row["volume"]
        else:
            h = max(h, row["high"]); l = min(l, row["low"]); c = row["close"]; v += row["volume"]
    if cur_day is not None:
        out.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return out


def simulate(candles: list[dict[str, Any]], profile: str | None) -> dict[str, Any]:
    """Walk-forward backtest. Return trade counts + WR + expectancy_R."""
    # v9.2.4 — Jendela per mode: swing butuh horizon multi-hari (96 candle
    # 1h = 4 hari) agar TP1 0.6R×2ATR sempat tersentuh; jendela 24 candle
    # memotong trade swing secara artifisial.
    if profile == "swing":
        trade_window, fill_window = 96, 12
    elif profile == "day":
        trade_window, fill_window = 36, 6
    else:
        trade_window, fill_window = TRADE_WINDOW, FILL_WINDOW
    trades: list[dict[str, Any]] = []
    last_trade_exit = 0
    n = len(candles)
    max_i = n - trade_window - fill_window - 1
    # Resample daily untuk daily_context (bias 50 SMA). Slice on the fly.
    daily_all = resample_daily(candles)
    # Peta hari terakhir yang selesai per index candle 1h (untuk look-ahead safe)
    day_end_index: list[int] = []
    cur_day: str | None = None
    day_count = 0
    for row in candles:
        d = datetime.fromtimestamp(row["time"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        if d != cur_day:
            cur_day = d
            day_count += 1
        # daily bar untuk hari berjalan belum selesai → gunakan yang selesai (day_count - 1).
        day_end_index.append(max(0, day_count - 1))

    i = WARMUP
    while i < max_i:
        if i < last_trade_exit:
            i += 1
            continue
        # Only eval every SAMPLE_EVERY candles (kecepatan)
        if (i - WARMUP) % SAMPLE_EVERY != 0:
            i += 1
            continue
        daily_slice = daily_all[: day_end_index[i]] if daily_all else None
        sig = compute_signal(
            candles[: i + 1],
            "crypto",
            profile=profile,
            daily_candles=daily_slice,
            timeframe="1h",
        )
        if sig["action"] not in ("BUY", "SELL") or sig.get("entry") is None:
            i += 1
            continue
        side = sig["action"]
        entry = sig["entry"]; sl = sig["stop_loss"]; tp1 = sig["take_profit"]
        if entry is None or sl is None or tp1 is None:
            i += 1; continue
        # Fill LIMIT
        fill_idx = None
        for j in range(i + 1, min(i + 1 + fill_window, n)):
            lo, hi = candles[j]["low"], candles[j]["high"]
            if (side == "BUY" and lo <= entry) or (side == "SELL" and hi >= entry):
                fill_idx = j; break
        if fill_idx is None:
            i += 1; continue
        outcome = "open"
        exit_idx = fill_idx
        for j in range(fill_idx, min(fill_idx + trade_window, n)):
            lo, hi = candles[j]["low"], candles[j]["high"]
            if side == "BUY":
                hit_sl, hit_tp = lo <= sl, hi >= tp1
            else:
                hit_sl, hit_tp = hi >= sl, lo <= tp1
            if hit_sl and hit_tp:
                outcome = "loss"; exit_idx = j; break  # konservatif: SL menang
            if hit_sl:
                outcome = "loss"; exit_idx = j; break
            if hit_tp:
                outcome = "win"; exit_idx = j; break
        last_trade_exit = exit_idx
        # Estimasi R multiplier dari level backend
        risk = abs(entry - sl) if sl else 0.0
        reward_r = (abs(tp1 - entry) / risk) if risk > 0 else 1.0
        trades.append({
            "side": side, "conf": sig["confidence"],
            "outcome": outcome, "reward_r": round(reward_r, 2),
        })
        i += 1

    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    opens = sum(1 for t in trades if t["outcome"] == "open")
    decisive = wins + losses
    wr = round(wins / decisive * 100.0, 1) if decisive else None
    avg_rr = round(sum(t["reward_r"] for t in trades) / len(trades), 2) if trades else 0
    # Expectancy: win = +reward_r rata2, loss = -1R, open = 0
    exp_r = round(((wins * avg_rr) - losses) / len(trades), 2) if trades else 0
    return {
        "trades": len(trades), "wins": wins, "losses": losses, "open": opens,
        "wr_decisive": wr, "avg_rr": avg_rr, "expectancy_r": exp_r,
    }


async def main() -> None:
    print("=" * 76, flush=True)
    print(f"BACKTEST 24 BULAN — 4 mode (Confluence, Scalper, Day, Swing) · TF 1h", flush=True)
    print(f"Sample every {SAMPLE_EVERY} candle · warm-up {WARMUP} · TP1 vs SL windows", flush=True)
    print("=" * 76, flush=True)

    t0 = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        data: list[tuple[str, list[dict[str, Any]]]] = []
        for sym in CRYPTO:
            print(f"[fetch] {sym} 24mo 1h ...", flush=True)
            candles = await fetch_24mo_1h(client, sym)
            if len(candles) < WARMUP + TRADE_WINDOW:
                print(f"  {sym}: SKIP (only {len(candles)} candles)", flush=True)
                continue
            span_days = (candles[-1]["time"] - candles[0]["time"]) / (24 * MS_PER_HOUR)
            print(f"  {sym}: {len(candles)} candle · {span_days:.0f} hari", flush=True)
            data.append((sym, candles))

    print(f"\nFetch total: {time.time() - t0:.1f}s", flush=True)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "months": MONTHS, "timeframe": "1h",
            "sample_every": SAMPLE_EVERY, "warmup": WARMUP,
            "fill_window": FILL_WINDOW, "trade_window": TRADE_WINDOW,
        },
        "modes": {},
    }

    for pname, prof in PROFILES:
        print(f"\n--- MODE: {pname} (profile={prof}) ---", flush=True)
        mode_tot = {"trades": 0, "wins": 0, "losses": 0, "open": 0, "rr_sum": 0.0}
        per_symbol = {}
        for sym, candles in data:
            t1 = time.time()
            res = simulate(candles, prof)
            dt = time.time() - t1
            print(
                f"  {sym:10s} trades={res['trades']:4d}  W={res['wins']:3d}  L={res['losses']:3d}  "
                f"open={res['open']:3d}  WR={res['wr_decisive']}%  "
                f"avgRR={res['avg_rr']}  exp={res['expectancy_r']:+.2f}R  ({dt:.1f}s)",
                flush=True,
            )
            per_symbol[sym] = res
            mode_tot["trades"] += res["trades"]
            mode_tot["wins"] += res["wins"]
            mode_tot["losses"] += res["losses"]
            mode_tot["open"] += res["open"]
            mode_tot["rr_sum"] += res["avg_rr"] * res["trades"]
        dec = mode_tot["wins"] + mode_tot["losses"]
        wr = round(mode_tot["wins"] / dec * 100.0, 1) if dec else None
        avg_rr = round(mode_tot["rr_sum"] / mode_tot["trades"], 2) if mode_tot["trades"] else 0
        exp_r = round(((mode_tot["wins"] * avg_rr) - mode_tot["losses"]) / mode_tot["trades"], 2) if mode_tot["trades"] else 0
        print(
            f"  TOTAL      trades={mode_tot['trades']}  W={mode_tot['wins']}  "
            f"L={mode_tot['losses']}  open={mode_tot['open']}  WR={wr}%  "
            f"avgRR={avg_rr}  expectancy={exp_r:+.2f}R/trade",
            flush=True,
        )
        report["modes"][pname] = {
            "profile": prof,
            "total": {**mode_tot, "wr_decisive": wr, "avg_rr": avg_rr, "expectancy_r": exp_r},
            "per_symbol": per_symbol,
        }

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report → {OUT_JSON}", flush=True)
    print(f"Total time: {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
