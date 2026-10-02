"""ASI-Bot — Top-100 crypto futures whitelist.

Daftar perpetual futures USDT-margined paling liquid di 4 exchange.
Dipakai sebagai whitelist Semi/Full-Auto ASI-Bot. User BISA mengurangi,
TIDAK bisa menambah di luar daftar ini (demi perlindungan terhadap koin
rug-pull / likuiditas tipis).
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
    base = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
    return base in TOP_100_FUTURES
