"""Final MAINNET hard-bracket test via Singapore proxy (balance-aware sizing)."""
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
    placed = []
    sym = "BTC/USDT:USDT"
    try:
        bal = await ex.fetch_balance()
        free = float((bal.get("USDT") or {}).get("free") or 0)
        print(f"1 · USDT free: {free}")

        tk = await ex.fapiPublicGetTickerPrice({"symbol": "BTCUSDT"})
        mark = float(tk.get("price"))
        print(f"2 · BTC mark: {mark}")

        # Binance USDM min notional = 100 USDT. Use qty slightly above.
        qty = round((105 / mark), 4)  # e.g. 105/85000 = 0.00123 -> 0.0012
        qty = max(qty, 0.0012)
        notional = qty * mark
        # leverage: margin = notional/leverage should be <= 60% of balance
        lev = 1
        for L in (20, 10, 5, 3, 1):
            if notional / L <= free * 0.6:
                lev = L
                break
        margin_needed = notional / lev
        print(f"3 · qty={qty} notional=${notional:.2f} lev={lev}x margin≈${margin_needed:.2f}")

        try:
            await ex.fapiPrivatePostLeverage({"symbol": "BTCUSDT", "leverage": lev})
            print(f"4 · leverage={lev} set ✅")
        except Exception as e:
            print(f"4 · leverage warn: {e}")

        print("5 · MARKET BUY entry…")
        entry = await ex.create_order(sym, "market", "buy", qty, None,
                                      params={"reduceOnly": False})
        eid = entry.get("id")
        eavg = float(entry.get("average") or mark)
        print(f"   ✅ entry id={eid} avg={eavg}")

        sl_px = round(eavg * 0.99, 1)   # -1%
        tp_px = round(eavg * 1.01, 1)   # +1%

        print(f"6 · HARD STOP_MARKET @ {sl_px} (closePosition=true)…")
        try:
            o = await ex.create_order(sym, "STOP_MARKET", "sell", None, None,
                params={"stopPrice": sl_px, "closePosition": True,
                        "workingType": "MARK_PRICE", "timeInForce": "GTE_GTC"})
            placed.append(o.get("id"))
            print(f"   ✅ HARD SL ACCEPTED id={o.get('id')}")
        except Exception as e:
            print(f"   ❌ SL rejected: {str(e)[:250]}")

        print(f"7 · HARD TAKE_PROFIT_MARKET @ {tp_px} (closePosition=true)…")
        try:
            o = await ex.create_order(sym, "TAKE_PROFIT_MARKET", "sell", None, None,
                params={"stopPrice": tp_px, "closePosition": True,
                        "workingType": "MARK_PRICE", "timeInForce": "GTE_GTC"})
            placed.append(o.get("id"))
            print(f"   ✅ HARD TP ACCEPTED id={o.get('id')}")
        except Exception as e:
            print(f"   ❌ TP rejected: {str(e)[:250]}")

        print("8 · Open orders on Binance now:")
        for o in await ex.fetch_open_orders(sym):
            info = o.get("info") or {}
            print(f"   {o.get('id')} {o.get('type')} stopPx={info.get('stopPrice')} closePos={info.get('closePosition')}")

        await asyncio.sleep(4)

        print("9 · CLEANUP: cancel brackets + close position…")
        for pid in placed:
            try:
                await ex.cancel_order(pid, sym)
                print(f"   cancelled {pid}")
            except Exception as e:
                print(f"   cancel warn: {str(e)[:80]}")
        for p in await ex.fetch_positions([sym]):
            q = float(p.get("contracts") or 0)
            if q > 0:
                s = "sell" if p.get("side") == "long" else "buy"
                r = await ex.create_order(sym, "market", s, q, None, params={"reduceOnly": True})
                print(f"   ✅ position closed id={r.get('id')} avg={r.get('average')}")

        bal2 = await ex.fetch_balance()
        print(f"10 · Final USDT free: {float((bal2.get('USDT') or {}).get('free') or 0)}")

        print("\n" + "=" * 64)
        if len(placed) >= 2:
            print("🎉 HARD-BRACKET NATIVE SL/TP BEKERJA DI BINANCE MAINNET!")
        elif len(placed) == 1:
            print("⚠️  Hanya 1 bracket diterima — perlu investigasi.")
        else:
            print("❌ Hard-bracket ditolak — engine fallback ke soft-bracket.")
        print("=" * 64)
    finally:
        # Safety net: ensure nothing left open
        try:
            for p in await ex.fetch_positions([sym]):
                q = float(p.get("contracts") or 0)
                if q > 0:
                    s = "sell" if p.get("side") == "long" else "buy"
                    await ex.create_order(sym, "market", s, q, None, params={"reduceOnly": True})
                    print("safety close executed")
        except Exception:
            pass
        await ex.close()


asyncio.run(main())
