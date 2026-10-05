"""ASI-Bot — Top-100 crypto futures (default scan universe).

Daftar perpetual futures USDT-margined paling liquid di 4 exchange.

v9.8.2 — PERAN BERUBAH: daftar ini BUKAN LAGI batasan eksekusi. Preview
dan execute memvalidasi simbol secara dinamis terhadap daftar pasar asli
exchange (engine._ensure_tradable) sehingga SEMUA perpetual USDT yang
listed (mis. STX, dll di luar daftar ini) boleh ditradingkan.

Daftar ini hanya dipakai sebagai default SCAN UNIVERSE untuk Full-Auto
background scanner (scheduler) ketika user belum mengatur whitelist sendiri
— supaya scanner tidak perlu memindai 400+ pair tiap siklus.
"""
TOP_100_FUTURES: list[str] = [
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "TRX", "LINK",
    "MATIC", "DOT", "LTC", "SHIB", "BCH", "NEAR", "UNI", "ATOM", "APT", "ICP",
    "ETC", "FIL", "HBAR", "XLM", "ARB", "VET", "OP", "IMX", "INJ", "RNDR",
    "TIA", "GRT", "MKR", "SUI", "AAVE", "ALGO", "LDO", "FTM", "QNT", "XTZ",
    "RUNE", "EGLD", "SAND", "AXS", "APE", "FLOW", "THETA", "KAS", "MANA", "CHZ",
    "NEO", "EOS", "PEPE", "WIF", "BONK", "FLOKI", "ORDI", "SEI", "STRK", "JUP",
    "DYDX", "PYTH", "MINA", "FET", "RSR", "ENS", "GALA", "AR", "KAVA", "ROSE",
    "ZEC", "DASH", "SNX", "CRV", "COMP", "YFI", "1INCH", "BAT", "ZIL", "CELO",
    "IOTA", "KSM", "GMX", "CFX", "BLUR", "ILV", "LRC", "ANKR", "WLD", "JTO",
    "ONDO", "MANTA", "ALT", "BOME", "W", "ENA", "TNSR", "AEVO", "PIXEL", "PYR",
]

def is_allowed(symbol: str) -> bool:
    """DEPRECATED v9.8.2 — hanya dipakai scheduler untuk scan-universe check.
    Eksekusi trade kini memakai engine._ensure_tradable (dinamis)."""
    base = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
    return base in TOP_100_FUTURES


# ---------------------------------------------------------------------------
# v9.8.3 — Daftar simbol perpetual USDT yang TRADING di Binance (public API).
# Dipakai untuk menandai sinyal AI yang BENAR-BENAR bisa dieksekusi di
# Binance Futures (mis. OCEAN sudah delist → futures_tradable=False di UI,
# tombol EXECUTE diganti note abu-abu, tidak ada lagi kegagalan setelah tap).
# ---------------------------------------------------------------------------
import os as _os
import time as _time

_PERPS_CACHE: tuple[float, set[str] | None] = (0.0, None)
_PERPS_TTL = 600.0  # 10 menit


async def binance_perp_tradable() -> set[str] | None:
    """Return set base-symbols (BTC, STX, …) yang statusnya TRADING di
    Binance USDT-M Futures. None bila fetch gagal (caller jangan filter)."""
    global _PERPS_CACHE
    now = _time.monotonic()
    cached_at, cached = _PERPS_CACHE
    if cached is not None and (now - cached_at) < _PERPS_TTL:
        return cached
    try:
        import httpx  # noqa: PLC0415 — local import keeps startup light
        proxy = _os.environ.get("ASI_PROXY_URL") or _os.environ.get("HTTPS_PROXY")
        async with httpx.AsyncClient(proxy=proxy, timeout=15) as c:
            r = await c.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
            r.raise_for_status()
            data = r.json()
        out: set[str] = set()
        for s in data.get("symbols", []):
            if (
                s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
            ):
                base = (s.get("baseAsset") or "").upper()
                if base:
                    out.add(base)
        if out:
            _PERPS_CACHE = (now, out)
            return out
    except Exception:
        pass
    # Jangan timpa cache sukses dengan kegagalan; pakai cache lama bila ada.
    return cached
