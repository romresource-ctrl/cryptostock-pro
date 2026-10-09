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

# v10.0.6 — Universe BIG-CAPS (Top-50 by market cap/liquidity) khusus untuk
# mode FULL-AUTO. Scheduler full-auto HANYA scan daftar ini supaya bot tidak
# otomatis eksekusi di low-caps yang slippage-nya besar. Semi-Auto tetap
# memakai TOP_100_FUTURES / exchange_info dinamis.
TOP_50_FUTURES: list[str] = TOP_100_FUTURES[:50]

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


# ---------------------------------------------------------------------------
# v9.9.0 — Symbol filters (tickSize / stepSize) untuk format harga & qty
# yang sah secara presisi Binance. Tanpa ini triggerPrice mentah (mis.
# 0.1051625 padahal tick 0.0001) ditolak Algo API → SL/TP native gagal
# terpasang. Cache 10 menit, public endpoint (no auth).
# ---------------------------------------------------------------------------
_FILTERS_CACHE: dict[bool, tuple[float, dict[str, dict[str, float]] | None]] = {
    False: (0.0, None), True: (0.0, None),
}


async def binance_symbol_filters(testnet: bool = False) -> dict[str, dict[str, float]] | None:
    """Return { "MANA": {"tick": 0.0001, "step": 1.0}, ... } utk semua
    USDT perpetual TRADING. None bila fetch gagal.

    v10.1.2 — NETWORK-AWARE: filter di-cache TERPISAH untuk mainnet vs
    testnet. Bug lama: cache mainnet dipakai untuk eksekusi testnet padahal
    stepSize berbeda (mis. ONDO mainnet 0.1 vs testnet 1) → Binance menolak
    order dengan -4023 "Qty not increased by step size" dan sinyal valid
    tidak pernah tereksekusi."""
    now = _time.monotonic()
    cached_at, cached = _FILTERS_CACHE[testnet]
    if cached is not None and (now - cached_at) < _PERPS_TTL:
        return cached
    base_url = ("https://testnet.binancefuture.com" if testnet
                else "https://fapi.binance.com")
    try:
        import httpx  # noqa: PLC0415
        proxy = _os.environ.get("ASI_PROXY_URL") or _os.environ.get("HTTPS_PROXY")
        async with httpx.AsyncClient(proxy=proxy, timeout=15) as c:
            r = await c.get(f"{base_url}/fapi/v1/exchangeInfo")
            r.raise_for_status()
            data = r.json()
        out: dict[str, dict[str, float]] = {}
        for s in data.get("symbols", []):
            if (
                s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
            ):
                tick = step = None
                for f in s.get("filters", []):
                    if f.get("filterType") == "PRICE_FILTER":
                        tick = float(f.get("tickSize") or 0)
                    elif f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize") or 0)
                base = (s.get("baseAsset") or "").upper()
                if base:
                    out[base] = {"tick": tick or 0.0, "step": step or 0.0}
        if out:
            _FILTERS_CACHE[testnet] = (now, out)
            return out
    except Exception:
        pass
    return cached


def round_to_tick(price: float, tick: float) -> float:
    """Bulatkan harga ke tick size (floor ke tick terdekat, lalu rapikan
    floating point). tick<=0 → kembalikan apa adanya."""
    if tick <= 0:
        return price
    import math
    steps = math.floor(price / tick + 1e-9)
    # Hindari floating error: hitung ulang dari integer steps.
    from decimal import Decimal
    d = Decimal(steps) * Decimal(str(tick))
    return float(d.normalize())


def round_to_step(qty: float, step: float) -> float:
    """Floor qty ke stepSize (LOT_SIZE Binance). step<=0 → qty apa adanya."""
    if step <= 0:
        return qty
    import math
    units = math.floor(qty / step + 1e-9)
    from decimal import Decimal
    d = Decimal(units) * Decimal(str(step))
    return float(d.normalize())


def fmt_decimal(x: float) -> str:
    """Format float → string desimal polos (tanpa notasi ilmiah) agar
    diterima Binance (mis. 5.9e-05 → '0.000059')."""
    from decimal import Decimal
    return format(Decimal(str(x)).normalize(), "f")
