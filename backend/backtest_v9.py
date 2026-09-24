"""v9.0.0 — Backtest sederhana untuk formula "Confluence".

Walk-forward 30 hari terakhir (candle 1h):
  • Setiap titik evaluasi memanggil compute_signal() pada data historis
    hingga titik itu (tanpa look-ahead).
  • Sinyal BUY/SELL → simulasi LIMIT order di entry_deep:
      - Fill jika harga menyentuh entry dalam 6 candle berikutnya.
      - Setelah fill: menang jika TP1 (1.5R) tersentuh sebelum SL dalam
        24 candle; kalah jika SL duluan; open jika dua-duanya tidak kena.
  • HOLD tidak dihitung.

Jalankan:  cd /app/backend && python backtest_v9.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

from indicators import compute_signal

WARMUP = 210          # candle minimum untuk EMA200
FILL_WINDOW = 6       # candle menunggu limit entry tersentuh
TRADE_WINDOW = 24     # candle maksimal menunggu TP1/SL

CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
STOCKS = {"AAPL": "stock_us", "TSLA": "stock_us", "NVDA": "stock_us", "BBCA.JK": "stock_id"}

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


async def fetch_binance(symbol: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1h", "limit": 1000},
        )
        r.raise_for_status()
        raw = r.json()
    return [
        {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
         "close": float(k[4]), "volume": float(k[5]), "time": k[0]}
        for k in raw
    ]


async def fetch_bitget(symbol: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            "https://api.bitget.com/api/v2/spot/market/candles",
            params={"symbol": symbol, "granularity": "1h", "limit": 1000},
        )
        r.raise_for_status()
        raw = r.json()["data"]
    out = [
        {"open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
         "close": float(k[4]), "volume": float(k[5]), "time": int(k[0])}
        for k in raw
    ]
    out.sort(key=lambda x: x["time"])
    return out


async def fetch_yahoo(symbol: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30, headers=UA) as c:
        r = await c.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1h", "range": "3mo"},
        )
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    closes = q["close"]
    out = []
    for i, ts in enumerate(res["timestamp"]):
        if closes[i] is None:
            continue
        out.append({
            "open": q["open"][i] or closes[i], "high": q["high"][i] or closes[i],
            "low": q["low"][i] or closes[i], "close": closes[i],
            "volume": q["volume"][i] or 0, "time": ts,
        })
    return out


def simulate(candles: list[dict[str, Any]], market: str,
             min_score: int = 4, trade_window: int = 24,
             htf_gate: bool = True, zone_cap: float = 0.8,
             macd_required: bool = False, rsi_momentum: bool = False,
             vol_required: bool = False, hlhh_required: bool = False) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    last_trade_exit = 0
    for i in range(WARMUP, len(candles) - trade_window - FILL_WINDOW):
        if i < last_trade_exit:
            continue  # satu posisi pada satu waktu
        sig = compute_signal(candles[: i + 1], market, min_score=min_score, htf_gate=htf_gate, zone_cap=zone_cap, macd_required=macd_required, rsi_momentum=rsi_momentum, vol_required=vol_required, hlhh_required=hlhh_required)
        if sig["action"] not in ("BUY", "SELL") or sig.get("entry") is None:
            continue
        side = sig["action"]
        entry, sl, tp1 = sig["entry"], sig["stop_loss"], sig["take_profit"]
        if entry is None or sl is None or tp1 is None:
            continue
        # Tunggu fill (limit order di entry_deep)
        fill_idx = None
        for j in range(i + 1, i + 1 + FILL_WINDOW):
            lo, hi = candles[j]["low"], candles[j]["high"]
            if (side == "BUY" and lo <= entry) or (side == "SELL" and hi >= entry):
                fill_idx = j
                break
        if fill_idx is None:
            continue
        outcome = "open"
        exit_idx = fill_idx
        for j in range(fill_idx, fill_idx + trade_window):
            lo, hi = candles[j]["low"], candles[j]["high"]
            if side == "BUY":
                hit_sl, hit_tp = lo <= sl, hi >= tp1
            else:
                hit_sl, hit_tp = hi >= sl, lo <= tp1
            if hit_sl and hit_tp:
                outcome = "loss"  # konservatif: anggap SL duluan
                exit_idx = j
                break
            if hit_sl:
                outcome = "loss"
                exit_idx = j
                break
            if hit_tp:
                outcome = "win"
                exit_idx = j
                break
        last_trade_exit = exit_idx
        trades.append({"i": i, "side": side, "conf": sig["confidence"], "outcome": outcome})
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    opens = sum(1 for t in trades if t["outcome"] == "open")
    decided = wins + losses
    wr = (wins / decided * 100.0) if decided else 0.0
    # Expectancy in R: win = +1.5R (TP1), loss = -1R, open = 0
    exp_r = ((wins * 1.5) - losses) / len(trades) if trades else 0.0
    return {"trades": len(trades), "wins": wins, "losses": losses,
            "open": opens, "wr_decided": round(wr, 1), "expectancy_r": round(exp_r, 2)}


async def main() -> None:
    print("=" * 72)
    print("BACKTEST v9.0 'Confluence' — 30 hari terakhir, candle 1h, TP1=1.5R")
    print("=" * 72)
    # Fetch semua data dulu
    data: list[tuple[str, str, list[dict[str, Any]]]] = []
    for sym in CRYPTO:
        try:
            candles = await fetch_binance(sym)
        except Exception:
            try:
                candles = await fetch_bitget(sym)
            except Exception as e2:
                print(f"{sym}: SKIP ({e2})")
                continue
        data.append((sym, "crypto", candles))
    for sym, mkt in STOCKS.items():
        try:
            candles = await fetch_yahoo(sym)
        except Exception as e:
            print(f"{sym}: SKIP ({e})")
            continue
        data.append((sym, mkt, candles))

    # Sensitivity sweep: varian filter konfluens
    VARIANTS = [
        ("A: base",                   dict(htf_gate=False, zone_cap=1.5)),
        ("F: base+rsiMom",            dict(htf_gate=False, zone_cap=1.5, rsi_momentum=True)),
        ("G: base+hlhh",              dict(htf_gate=False, zone_cap=1.5, hlhh_required=True)),
        ("H: htf+rsiMom",             dict(htf_gate=True,  zone_cap=1.5, rsi_momentum=True)),
        ("I: htf+rsiMom+hlhh",        dict(htf_gate=True,  zone_cap=1.5, rsi_momentum=True, hlhh_required=True)),
        ("J: htf+rsiMom+hlhh+vol",    dict(htf_gate=True,  zone_cap=1.5, rsi_momentum=True, hlhh_required=True, vol_required=True)),
    ]
    for min_score in (4,):
        for tw in (24,):
            for vname, vkw in VARIANTS:
                tot = {"trades": 0, "wins": 0, "losses": 0, "open": 0}
                print(f"\n--- {vname} ---")
                for sym, mkt, candles in data:
                    res = simulate(candles, mkt, min_score=min_score, trade_window=tw, **vkw)
                    print(f"  {sym:10s} {mkt:9s} trades={res['trades']:3d}  W={res['wins']:3d}  L={res['losses']:3d}  "
                          f"open={res['open']:2d}  WR={res['wr_decided']:5.1f}%  exp={res['expectancy_r']:+.2f}R")
                    tot["trades"] += res["trades"]; tot["wins"] += res["wins"]
                    tot["losses"] += res["losses"]; tot["open"] += res["open"]
                decided = tot["wins"] + tot["losses"]
                wr = tot["wins"] / decided * 100.0 if decided else 0.0
                exp = ((tot["wins"] * 1.5) - tot["losses"]) / tot["trades"] if tot["trades"] else 0.0
                print(f"  TOTAL     trades={tot['trades']}  W={tot['wins']}  L={tot['losses']}  "
                      f"open={tot['open']}  WR={wr:.1f}%  expectancy={exp:+.2f}R/trade")


if __name__ == "__main__":
    asyncio.run(main())
