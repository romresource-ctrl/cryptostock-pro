"""Final MAINNET test via Singapore proxy."""
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import ccxt.async_support as ccxt_async

KEY = "YrbxFxqQLpUv7qVdiVvSfurdggHZ20sUNh97y78VnNTplFiI5d6deHrvmksPFGsx"
SEC = "jmlagUuA6FtAPG128Sv5s8c7zchIif4il88yju5g3vBTkIvnSVguObX1sBf3qPAu"
PROXY = "http://143.198.197.107:8888"


async def main():
    ex = ccxt_async.binanceusdm({
        "apiKey": KEY, "secret": SEC,
        "enableRateLimit": True,
        "httpsProxy": PROXY,
        "options": {"defaultType": "swap", "portfolioMargin": False},
    })
    try:
        print("=" * 64)
        print("1 · Account balance via Singapore proxy")
        print("=" * 64)
        acc = await ex.fapiPrivateV2GetAccount()
        print(f"  canTrade={acc.get('canTrade')}  canWithdraw={acc.get('canWithdraw')}")
        print(f"  totalWalletBalance={acc.get('totalWalletBalance')} USDT")
        print(f"  availableBalance={acc.get('availableBalance')} USDT")

        bal = await ex.fetch_balance()
        free = float((bal.get("USDT") or {}).get("free") or 0)
        print(f"  USDT free: {free}")
        if free < 50:
            print("⚠️  Low balance. Use minimum qty.")

        sym = "BTC/USDT:USDT"
        tk = await ex.fapiPublicGetTickerPrice({"symbol": "BTCUSDT"})
        mark = float(tk.get("price"))
        print(f"\nBTC mark price: {mark}")

        # Min qty = 0.001 BTC (~$85 notional)
        qty = 0.001
        print(f"Test qty: {qty} BTC (notional ≈ ${qty * mark:.2f})")

        print("\n2 · Set leverage=1")
        try:
            await ex.fapiPrivatePostLeverage({"symbol": "BTCUSDT", "leverage": 1})
            print("  ✅ leverage=1")
        except Exception as e:
            print(f"  warn: {e}")

        print("\n3 · MARKET BUY entry")
        entry = await ex.create_order(sym, "market", "buy", qty, None,
                                      params={"reduceOnly": False})
        eid = entry.get("id")
        eavg = float(entry.get("average") or mark)
        efill = float(entry.get("filled") or qty)
        print(f"  ✅ entry id={eid} avg={eavg} filled={efill}")

        placed = []
        sl_px = round(eavg * 0.985, 1)
        print(f"\n4 · HARD STOP_MARKET @ {sl_px} (closePosition=true)")
        try:
            o = await ex.create_order(sym, "STOP_MARKET", "sell", None, None,
                params={"stopPrice": sl_px, "closePosition": True,
                        "workingType": "MARK_PRICE", "timeInForce": "GTE_GTC"})
            placed.append(o.get("id"))
            print(f"  ✅ HARD SL ACCEPTED id={o.get('id')}")
        except Exception as e:
            print(f"  ❌ SL rejected: {str(e)[:300]}")

        tp_px = round(eavg * 1.015, 1)
        print(f"\n5 · HARD TAKE_PROFIT_MARKET @ {tp_px} (closePosition=true)")
        try:
            o = await ex.create_order(sym, "TAKE_PROFIT_MARKET", "sell", None, None,
                params={"stopPrice": tp_px, "closePosition": True,
                        "workingType": "MARK_PRICE", "timeInForce": "GTE_GTC"})
            placed.append(o.get("id"))
            print(f"  ✅ HARD TP ACCEPTED id={o.get('id')}")
        except Exception as e:
            print(f"  ❌ TP rejected: {str(e)[:300]}")

        print("\n6 · Open orders")
        opens = await ex.fetch_open_orders(sym)
        for o in opens:
            info = o.get("info") or {}
            print(f"  id={o.get('id')} type={o.get('type')} stopPx={info.get('stopPrice')} closePos={info.get('closePosition')}")

        print("\n7 · Wait 3s...")
        await asyncio.sleep(3)

        print("\n8 · Cleanup (cancel + close)")
        for pid in placed:
            try:
                await ex.cancel_order(pid, sym)
                print(f"  cancelled {pid}")
            except Exception as e:
                print(f"  cancel warn: {str(e)[:80]}")
        for p in await ex.fetch_positions([sym]):
            q = float(p.get("contracts") or 0)
            if q > 0:
                s = "sell" if p.get("side") == "long" else "buy"
                r = await ex.create_order(sym, "market", s, q, None, params={"reduceOnly": True})
                print(f"  ✅ position closed id={r.get('id')} avg={r.get('average')}")

        print("\n" + "=" * 64)
        print("🎉 RESULT:", "HARD-BRACKET WORKS VIA SINGAPORE PROXY" if len(placed) >= 2 else "Fallback to soft-bracket")
        print("=" * 64)
    finally:
        await ex.close()


asyncio.run(main())
