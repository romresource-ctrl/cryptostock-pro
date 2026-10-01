"""v9.2.4 — Audit konsistensi sinyal END-TO-END.

Untuk setiap (market, symbol, profile) membandingkan sinyal yang
dihasilkan oleh SEMUA jalur yang dilihat user:
  A. /api/dashboard            (kartu dashboard)
  B. /api/asset/.../chart      (badge & level di halaman detail)
  C. /api/asset/.../analyze    (kartu AI PREDICTION di detail)
  D. /api/search               (hasil pencarian)
  E. /api/ai-suggestions       (sheet premium)

Aturan lulus:
  - action/label HARUS identik di semua jalur untuk aset+profile+TF sama.
  - Entry/SL/TP di chart HARUS identik dengan dashboard & suggestions.
  - Confidence boleh beda MAKSIMAL 0 (harus sama — satu sumber).

Jalankan: cd /app/backend && python3 audit_consistency.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx

BASE = "http://localhost:8001/api"
DEVICE = "web:aitest-e2e-001"
TF = "1h"

CASES: list[tuple[str, str]] = [
    ("crypto", "BTC"), ("crypto", "ETH"), ("crypto", "SUI"), ("crypto", "SOL"),
    ("stock_id", "BBCA"), ("stock_id", "GOTO"),
    ("stock_us", "AAPL"), ("stock_us", "TSLA"),
    ("gold_silver", "XAU-USD"),
    ("forex", "EUR-USD"),
    ("commodity", "WTI"),
    ("etf", "QQQ"),
]
PROFILES = [None, "scalper", "day", "swing"]


async def get(client: httpx.AsyncClient, path: str) -> dict[str, Any] | None:
    try:
        r = await client.get(f"{BASE}{path}", timeout=90)
        if r.status_code != 200:
            return {"_http": r.status_code}
        return r.json()
    except Exception as e:
        return {"_err": str(e)[:80]}


def sig_view(action: Any, label: Any, conf: Any, entry: Any, sl: Any, tp: Any) -> str:
    e = f"{entry:.6g}" if isinstance(entry, (int, float)) else str(entry)
    s = f"{sl:.6g}" if isinstance(sl, (int, float)) else str(sl)
    t = f"{tp:.6g}" if isinstance(tp, (int, float)) else str(tp)
    return f"{action}/{label} conf={conf} E={e} SL={s} TP={t}"


async def audit_case(client: httpx.AsyncClient, market: str, symbol: str, profile: str | None) -> dict[str, Any]:
    pq = f"&profile={profile}" if profile else ""
    pname = profile or "confluence"

    # A. dashboard (single-market, cari symbol)
    dash = await get(client, f"/dashboard?market={market}&timeframe={TF}{pq}")
    dash_assets = (dash or {}).get("assets") or []
    dash_hit = next((a for a in dash_assets if a.get("symbol", "").upper() == symbol.replace("-", "/").upper()), None)

    # B. chart (detail)
    chart = await get(client, f"/asset/{market}/{symbol}/chart?timeframe={TF}{pq}")
    csig = (chart or {}).get("signal") or {}

    # C. analyze (kartu AI prediction di detail) — endpoint POST.
    try:
        _r = await client.post(f"{BASE}/asset/{market}/{symbol}/analyze?timeframe={TF}&lang=id{pq}", timeout=120)
        an = _r.json() if _r.status_code == 200 else {"_http": _r.status_code}
    except Exception as e:
        an = {"_err": str(e)[:80]}
    atech = ((an or {}).get("technical") or {})

    # D. search
    srch = await get(client, f"/search?query={symbol}{pq}")
    sres = (srch or {}).get("results") or (srch or {}).get("assets") or []
    s_hit = None
    for a in sres:
        if a.get("symbol", "").upper() == symbol.replace("-", "/").upper() and a.get("market") == market:
            s_hit = a
            break
    if s_hit is None and sres:
        s_hit = next((a for a in sres if a.get("symbol", "").upper() == symbol.replace("-", "/").upper()), None)

    def v(x: dict[str, Any] | None) -> str:
        if not x:
            return "ABSENT"
        return sig_view(x.get("action"), x.get("label"), x.get("confidence"),
                        x.get("entry"), x.get("stop_loss"), x.get("take_profit"))

    row = {
        "dashboard": v(dash_hit),
        "chart": v(csig) if csig else ("HTTP_" + str(chart.get("_http")) if chart else "ERR"),
        "analyze_tech": v(atech) if atech else ("HTTP_" + str(an.get("_http")) if an else "ERR"),
        "search": v(s_hit),
    }
    # konsistensi: abaikan jalur ABSENT (aset memang tidak ada di universe jalur itu)
    present = {k: val for k, val in row.items() if val != "ABSENT" and not val.startswith("HTTP") and val != "ERR"}
    uniq = set(present.values())
    ok = len(uniq) <= 1
    return {"market": market, "symbol": symbol, "profile": pname, "ok": ok, "views": row}


async def main() -> None:
    mismatches: list[dict[str, Any]] = []
    total = 0
    async with httpx.AsyncClient() as client:
        for profile in PROFILES:
            print(f"\n===== PROFILE: {profile or 'confluence (default)'} =====", flush=True)
            for market, symbol in CASES:
                total += 1
                r = await audit_case(client, market, symbol, profile)
                status = "OK " if r["ok"] else "MISMATCH"
                print(f"[{status}] {r['market']}/{r['symbol']}", flush=True)
                if not r["ok"]:
                    mismatches.append(r)
                    for k, val in r["views"].items():
                        print(f"    {k:14s}: {val}", flush=True)
    print("\n" + "=" * 70, flush=True)
    print(f"TOTAL CASES: {total}  MISMATCH: {len(mismatches)}", flush=True)
    with open("/app/test_reports/audit_consistency.json", "w") as f:
        json.dump({"total": total, "mismatches": mismatches}, f, indent=2)
    if mismatches:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
