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
