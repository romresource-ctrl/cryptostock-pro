"""Market data adapters for crypto (Binance) and Indonesian stocks (Yahoo Finance).

All functions return native Python types; no MongoDB.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

# Crypto symbol -> Binance trading pair (USDT-quoted spot)
CRYPTO_BINANCE_MAP: dict[str, str] = {
    # Top 30 by market cap
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "HYPE": "HYPEUSDT",
    "AVAX": "AVAXUSDT", "USDT": "USDCUSDT",
    "ASTER": "ASTERUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT",
    "SOL": "SOLUSDT", "DOGE": "DOGEUSDT", "PEPE": "PEPEUSDT",
    "SUI": "SUIUSDT", "ADA": "ADAUSDT", "TRX": "TRXUSDT",
    "LTC": "LTCUSDT", "LINK": "LINKUSDT", "HBAR": "HBARUSDT",
    "SHIB": "SHIBUSDT", "DOT": "DOTUSDT", "BCH": "BCHUSDT",
    "SAND": "SANDUSDT", "ALGO": "ALGOUSDT", "XAUT": "PAXGUSDT",
    # Layer-1/Layer-2 & DeFi
    "MATIC": "MATICUSDT", "ATOM": "ATOMUSDT", "NEAR": "NEARUSDT",
    "FIL": "FILUSDT", "APT": "APTUSDT", "ARB": "ARBUSDT",
    "OP": "OPUSDT", "INJ": "INJUSDT", "STX": "STXUSDT",
    "TIA": "TIAUSDT", "SEI": "SEIUSDT", "IMX": "IMXUSDT",
    "MNT": "MNTUSDT", "TON": "TONUSDT", "GRT": "GRTUSDT",
    "AAVE": "AAVEUSDT", "MKR": "MKRUSDT", "UNI": "UNIUSDT",
    "LDO": "LDOUSDT", "CRV": "CRVUSDT", "COMP": "COMPUSDT",
    "SNX": "SNXUSDT", "SUSHI": "SUSHIUSDT",
    # Memecoins & narratives
    "WIF": "WIFUSDT", "BONK": "BONKUSDT", "FLOKI": "FLOKIUSDT",
    "TRUMP": "TRUMPUSDT", "MEME": "MEMEUSDT",
    # AI/Compute
    "RENDER": "RENDERUSDT", "FET": "FETUSDT", "TAO": "TAOUSDT",
    "WLD": "WLDUSDT", "AGIX": "AGIXUSDT",
    # Gaming/Metaverse
    "AXS": "AXSUSDT", "GALA": "GALAUSDT", "APE": "APEUSDT",
    "ENJ": "ENJUSDT", "MANA": "MANAUSDT",
    # Storage & Infrastructure
    "ICP": "ICPUSDT", "AR": "ARUSDT", "RUNE": "RUNEUSDT",
    "KAS": "KASUSDT", "FLOW": "FLOWUSDT", "EOS": "EOSUSDT",
    "XLM": "XLMUSDT", "VET": "VETUSDT", "XTZ": "XTZUSDT",
    "EGLD": "EGLDUSDT", "THETA": "THETAUSDT", "CHZ": "CHZUSDT",
    "QNT": "QNTUSDT", "KAVA": "KAVAUSDT", "CFX": "CFXUSDT",
    "PYTH": "PYTHUSDT", "JUP": "JUPUSDT", "STRK": "STRKUSDT",
    "ONDO": "ONDOUSDT", "ENA": "ENAUSDT", "W": "WUSDT",
    "ETHFI": "ETHFIUSDT", "AI16Z": "AI16ZUSDT", "VIRTUAL": "VIRTUALUSDT",
    "MOVE": "MOVEUSDT", "JASMY": "JASMYUSDT", "1INCH": "1INCHUSDT",
    "BAT": "BATUSDT", "ZIL": "ZILUSDT", "ZEC": "ZECUSDT",
    "DASH": "DASHUSDT", "GMT": "GMTUSDT", "DYDX": "DYDXUSDT",
    "OCEAN": "OCEANUSDT",
    # Additional 15 for wider coverage → total ~110
    "ORDI": "ORDIUSDT", "SATS": "1000SATSUSDT", "PEOPLE": "PEOPLEUSDT",
    "ANKR": "ANKRUSDT", "ROSE": "ROSEUSDT", "CAKE": "CAKEUSDT",
    "MASK": "MASKUSDT", "YFI": "YFIUSDT", "C98": "C98USDT",
    "ILV": "ILVUSDT", "ARKM": "ARKMUSDT", "TRB": "TRBUSDT",
    "PENDLE": "PENDLEUSDT", "BLUR": "BLURUSDT", "GMX": "GMXUSDT",
}

# IDX (Indonesia) stocks -> Yahoo Finance with .JK suffix
STOCK_YAHOO_MAP: dict[str, str] = {
    # Big 4 banks & top financials
    "BBCA": "BBCA.JK", "BBRI": "BBRI.JK", "BMRI": "BMRI.JK",
    "BBNI": "BBNI.JK", "BRIS": "BRIS.JK", "BTPS": "BTPS.JK",
    "BJBR": "BJBR.JK", "BJTM": "BJTM.JK",
    # Coal, mining, energy
    "TPIA": "TPIA.JK", "ADRO": "ADRO.JK", "DEWA": "DEWA.JK",
    "ADMR": "ADMR.JK", "BRMS": "BRMS.JK", "PTRO": "PTRO.JK",
    "ANTM": "ANTM.JK", "MBMA": "MBMA.JK", "MDKA": "MDKA.JK",
    "AMMN": "AMMN.JK", "PGEO": "PGEO.JK", "PTBA": "PTBA.JK",
    "ITMG": "ITMG.JK", "MEDC": "MEDC.JK", "ELSA": "ELSA.JK",
    "INCO": "INCO.JK", "HRUM": "HRUM.JK", "AKRA": "AKRA.JK",
    "PGAS": "PGAS.JK", "ENRG": "ENRG.JK", "RAJA": "RAJA.JK",
    # Conglomerates & industrials
    "ASII": "ASII.JK", "EMTK": "EMTK.JK", "PANI": "PANI.JK",
    "CBRE": "CBRE.JK", "INET": "INET.JK", "TLKM": "TLKM.JK",
    "ISAT": "ISAT.JK", "EXCL": "EXCL.JK", "TOWR": "TOWR.JK",
    "MTEL": "MTEL.JK", "MAPA": "MAPA.JK", "MAPI": "MAPI.JK",
    "ACES": "ACES.JK", "MIDI": "MIDI.JK", "AMRT": "AMRT.JK",
    # Consumer & retail
    "SIDO": "SIDO.JK", "UNVR": "UNVR.JK", "INDF": "INDF.JK",
    "ICBP": "ICBP.JK", "MYOR": "MYOR.JK", "KLBF": "KLBF.JK",
    "GGRM": "GGRM.JK", "HMSP": "HMSP.JK", "GOTO": "GOTO.JK",
    "BUKA": "BUKA.JK", "ARTO": "ARTO.JK", "BBHI": "BBHI.JK",
    # Property, construction & infra
    "BSDE": "BSDE.JK", "CTRA": "CTRA.JK", "PWON": "PWON.JK",
    "SMRA": "SMRA.JK", "PTPP": "PTPP.JK", "WIKA": "WIKA.JK",
    "WSKT": "WSKT.JK", "JSMR": "JSMR.JK", "SMGR": "SMGR.JK",
    "INTP": "INTP.JK", "SMCB": "SMCB.JK",
    # Palm oil, plantations
    "AALI": "AALI.JK", "LSIP": "LSIP.JK", "SIMP": "SIMP.JK",
    "SGRO": "SGRO.JK", "TBLA": "TBLA.JK", "DSNG": "DSNG.JK",
    # Automotive & transportation
    "IMAS": "IMAS.JK", "GJTL": "GJTL.JK", "GIAA": "GIAA.JK",
    # Healthcare
    "MIKA": "MIKA.JK", "HEAL": "HEAL.JK", "SILO": "SILO.JK",
    "TSPC": "TSPC.JK",
    # Additional 30 IDX tickers → total ~110
    # Energy / coal / oil / heavy equipment
    "UNTR": "UNTR.JK", "BYAN": "BYAN.JK", "BUMI": "BUMI.JK",
    "INDY": "INDY.JK", "HEXA": "HEXA.JK", "TINS": "TINS.JK",
    # Banks (secondary)
    "BBTN": "BBTN.JK", "MEGA": "MEGA.JK", "BFIN": "BFIN.JK",
    # Consumer / F&B / retail
    "CPIN": "CPIN.JK", "JPFA": "JPFA.JK", "MAIN": "MAIN.JK",
    "ULTJ": "ULTJ.JK", "ROTI": "ROTI.JK",
    # Pharma / healthcare
    "KAEF": "KAEF.JK", "INAF": "INAF.JK",
    # Property (extended)
    "LPKR": "LPKR.JK",
    # Construction & infra
    "ADHI": "ADHI.JK", "WSBP": "WSBP.JK",
    # Steel / basic materials
    "KRAS": "KRAS.JK", "ISSP": "ISSP.JK", "ARNA": "ARNA.JK",
    # Auto & industrials
    "SMSM": "SMSM.JK", "MPMX": "MPMX.JK",
    # Telco / IT
    "LINK": "LINK.JK",
    # Paper & textiles
    "TKIM": "TKIM.JK", "FASW": "FASW.JK", "SRIL": "SRIL.JK",
    # Shipping
    "SMDR": "SMDR.JK", "PSSI": "PSSI.JK",
    # Additional 34 IDX tickers requested (v6.0.10)
    "AADI": "AADI.JK", "DSSA": "DSSA.JK", "TAPG": "TAPG.JK",
    "CUAN": "CUAN.JK", "POLY": "POLY.JK", "BIPI": "BIPI.JK",
    "OASA": "OASA.JK", "INKP": "INKP.JK", "BUVA": "BUVA.JK",
    "BRPT": "BRPT.JK", "RATU": "RATU.JK", "BREN": "BREN.JK",
    "BNBR": "BNBR.JK", "GTSI": "GTSI.JK", "PRDL": "PRDL.JK",
    "JELI": "JELI.JK", "ARCI": "ARCI.JK", "BULL": "BULL.JK",
    "SGER": "SGER.JK", "NCKL": "NCKL.JK", "FORE": "FORE.JK",
    "BIRD": "BIRD.JK", "CMPP": "CMPP.JK", "RANS": "RANS.JK",
    "EMMI": "EMMI.JK", "BACH": "BACH.JK", "JECX": "JECX.JK",
    "MDIA": "MDIA.JK", "BBYB": "BBYB.JK", "SSMS": "SSMS.JK",
    "MBSS": "MBSS.JK", "TOBA": "TOBA.JK", "MINA": "MINA.JK",
    "CDIA": "CDIA.JK",
}

# ETFs -> Yahoo Finance (no suffix, listed in USD)
ETF_YAHOO_MAP: dict[str, str] = {
    # Broad market
    "QQQ": "QQQ", "VOO": "VOO", "VTI": "VTI", "SPY": "SPY",
    "IVV": "IVV", "VXUS": "VXUS", "VEA": "VEA", "VWO": "VWO",
    # Thematic / growth
    "ARKK": "ARKK", "ARKG": "ARKG", "ARKF": "ARKF", "ARKW": "ARKW",
    "SMH": "SMH", "SOXX": "SOXX", "IGV": "IGV",
    # Fixed income
    "TLT": "TLT", "IEF": "IEF", "SHY": "SHY", "BND": "BND",
    "LQD": "LQD", "HYG": "HYG", "AGG": "AGG",
    # Crypto ETFs
    "IBIT": "IBIT", "FBTC": "FBTC", "ARKB": "ARKB", "BITO": "BITO",
    "ETHE": "ETHE", "ETHA": "ETHA", "GBTC": "GBTC",
    # Dividend / income
    "SCHD": "SCHD", "VYM": "VYM", "DVY": "DVY", "VIG": "VIG",
    # International & country
    "INDA": "INDA", "EWJ": "EWJ", "EIDO": "EIDO", "EWH": "EWH",
    "FXI": "FXI", "ASHR": "ASHR", "EWZ": "EWZ", "EWG": "EWG",
    "EWU": "EWU",
    # Sector
    "XLF": "XLF", "XLE": "XLE", "XBI": "XBI", "XLK": "XLK",
    "XLV": "XLV", "XLI": "XLI", "XLY": "XLY", "XLP": "XLP",
    "XLU": "XLU", "XLC": "XLC", "XLB": "XLB", "XLRE": "XLRE",
    # Commodities & alternatives
    "GLD": "GLD", "SLV": "SLV", "USO": "USO", "UNG": "UNG",
    "DBC": "DBC", "PDBC": "PDBC",
    # Leverage & inverse
    "TQQQ": "TQQQ", "SQQQ": "SQQQ", "SOXL": "SOXL", "SOXS": "SOXS",
    "UPRO": "UPRO", "SPXL": "SPXL",
}

# US stocks -> Yahoo Finance (renamed to "world_stocks" market — kept map name for backward compat)
STOCK_US_YAHOO_MAP: dict[str, str] = {
    # Magnificent 7
    "AAPL": "AAPL", "MSFT": "MSFT", "NVDA": "NVDA", "GOOGL": "GOOGL",
    "GOOG": "GOOG", "AMZN": "AMZN", "TSLA": "TSLA", "META": "META",
    # Semiconductor / AI
    "AMD": "AMD", "ASML": "ASML", "TSM": "TSM", "TSMC": "TSM",
    "ARM": "ARM", "AVGO": "AVGO", "MU": "MU", "QCOM": "QCOM",
    "TXN": "TXN", "AMAT": "AMAT", "LRCX": "LRCX", "KLAC": "KLAC",
    "MRVL": "MRVL", "SMCI": "SMCI", "ANET": "ANET", "MCHP": "MCHP",
    "NXPI": "NXPI", "ADI": "ADI", "ON": "ON", "INTC": "INTC",
    "WOLF": "WOLF", "VRT": "VRT",
    # Software / SaaS
    "PLTR": "PLTR", "SNOW": "SNOW", "CRWD": "CRWD", "ADBE": "ADBE",
    "NOW": "NOW", "CRM": "CRM", "ORCL": "ORCL", "IBM": "IBM",
    "INTU": "INTU", "PANW": "PANW", "FTNT": "FTNT", "ZS": "ZS",
    "DDOG": "DDOG", "NET": "NET", "MDB": "MDB", "TEAM": "TEAM",
    "WDAY": "WDAY", "OKTA": "OKTA", "SPLK": "SPLK",
    # China / International
    "BABA": "BABA", "TCEHY": "TCEHY", "PDD": "PDD", "BIDU": "BIDU",
    "JD": "JD", "SHOP": "SHOP", "NU": "NU", "AZN": "AZN",
    "MELI": "MELI", "SPOT": "SPOT", "SE": "SE", "TCOM": "TCOM",
    "SONY": "SONY", "NVO": "NVO", "LLY": "LLY", "RIO": "RIO",
    "BHP": "BHP",
    # Consumer & retail
    "WMT": "WMT", "COST": "COST", "HD": "HD", "TGT": "TGT",
    "LOW": "LOW", "NKE": "NKE", "SBUX": "SBUX", "MCD": "MCD",
    "KO": "KO", "PEP": "PEP", "PG": "PG", "CL": "CL",
    "EL": "EL", "DIS": "DIS", "NFLX": "NFLX", "SPCX": "SPCX",
    # Financials
    "JPM": "JPM", "BAC": "BAC", "WFC": "WFC", "GS": "GS",
    "MS": "MS", "C": "C", "BLK": "BLK", "SCHW": "SCHW",
    "AXP": "AXP", "V": "V", "MA": "MA", "PYPL": "PYPL",
    "BRK-B": "BRK-B", "BRK-A": "BRK-A", "HOOD": "HOOD", "COIN": "COIN",
    "SOFI": "SOFI", "SQ": "SQ", "BX": "BX",
    # Healthcare / Pharma
    "JNJ": "JNJ", "UNH": "UNH", "PFE": "PFE", "MRK": "MRK",
    "ABBV": "ABBV", "ABT": "ABT", "TMO": "TMO", "DHR": "DHR",
    "AMGN": "AMGN", "GILD": "GILD", "BMY": "BMY", "MRNA": "MRNA",
    "BNTX": "BNTX", "REGN": "REGN", "VRTX": "VRTX",
    # Industrials / Auto / Aerospace
    "BA": "BA", "CAT": "CAT", "GE": "GE", "LMT": "LMT",
    "RTX": "RTX", "HON": "HON", "MMM": "MMM", "DE": "DE",
    "F": "F", "GM": "GM", "RIVN": "RIVN", "LCID": "LCID",
    "NIO": "NIO", "LI": "LI", "XPEV": "XPEV", "RKLB": "RKLB",
    "UBER": "UBER", "LYFT": "LYFT", "ABNB": "ABNB",
    # Energy / Utilities
    "XOM": "XOM", "CVX": "CVX", "COP": "COP", "EOG": "EOG",
    "SLB": "SLB", "OXY": "OXY", "NEE": "NEE", "DUK": "DUK",
    # Comms / Telecom
    "T": "T", "VZ": "VZ", "TMUS": "TMUS", "CSCO": "CSCO",
    "CMCSA": "CMCSA",
    # Retail / Other
    "EBAY": "EBAY", "ZM": "ZM", "DKNG": "DKNG", "GME": "GME",
    "AMC": "AMC", "MSTR": "MSTR", "DELL": "DELL", "HPQ": "HPQ",
    "HPE": "HPE",
    # ETFs commonly traded like stocks (leveraged)
    "TQQQ": "TQQQ", "SQQQ": "SQQQ", "SOXL": "SOXL",
    # Global indices
    "US30": "^DJI", "NAS100": "^IXIC", "SPX500": "^GSPC",
    "JP225": "^N225", "HK50": "^HSI", "GER40": "^GDAXI",
    "UK100": "^FTSE", "IDX30": "^JKSE", "AUS200": "^AXJO",
    "FR40": "^FCHI", "EU50": "^STOXX50E", "IN50": "^NSEI",
    "KR200": "^KS11", "TW50": "^TWII",
    "VIX": "^VIX", "DXY": "DX-Y.NYB",
}

# Gold / Silver / Precious metals -> Yahoo Finance FX/commodity symbols
GOLD_SILVER_YAHOO_MAP: dict[str, str] = {
    "XAU/USD": "GC=F",   # Gold futures (proxy for spot)
    "XAG/USD": "SI=F",   # Silver futures
    "XPT/USD": "PL=F",   # Platinum
    "XPD/USD": "PA=F",   # Palladium
}

# Commodities -> Yahoo Finance futures symbols
COMMODITY_YAHOO_MAP: dict[str, str] = {
    "WTI":     "CL=F",   # WTI Crude Oil
    "BRENT":   "BZ=F",   # Brent Crude Oil
    "NATGAS":  "NG=F",   # Natural Gas
    "GASOLINE": "RB=F",  # RBOB Gasoline
    "HEATOIL": "HO=F",   # Heating Oil
    "CORN":    "ZC=F",   # Corn
    "COFFEE":  "KC=F",   # Coffee Beans
    "SUGAR":   "SB=F",   # Sugar
    "COPPER":  "HG=F",   # Copper
    "WHEAT":   "ZW=F",   # Wheat
    "SOYBEAN": "ZS=F",   # Soybean
    "COCOA":   "CC=F",   # Cocoa
    "COTTON":  "CT=F",   # Cotton
    "OJ":      "OJ=F",   # Orange Juice
    "LUMBER":  "LBS=F",  # Lumber
    "OATS":    "ZO=F",   # Oats
    "RICE":    "ZR=F",   # Rough Rice
    "CATTLE":  "LE=F",   # Live Cattle
    "HOGS":    "HE=F",   # Lean Hogs
    "URANIUM": "URA",    # URA ETF proxy
}

# Forex -> Yahoo Finance FX symbols (XXX=X or XXXYYY=X)
FOREX_YAHOO_MAP: dict[str, str] = {
    # Majors
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X",
    "NZD/USD": "NZDUSD=X",
    "USD/CHF": "CHF=X",
    "USD/CAD": "CAD=X",
    # Cross rates (EUR)
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/CHF": "EURCHF=X",
    "EUR/AUD": "EURAUD=X",
    # Cross rates (GBP)
    "GBP/JPY": "GBPJPY=X",
    "GBP/CHF": "GBPCHF=X",
    "GBP/AUD": "GBPAUD=X",
    # Cross rates (AUD/NZD)
    "AUD/JPY": "AUDJPY=X",
    "AUD/NZD": "AUDNZD=X",
    "NZD/JPY": "NZDJPY=X",
    # Emerging markets vs USD
    "USD/IDR": "IDR=X",
    "USD/TRY": "TRY=X",
    "USD/ZAR": "ZAR=X",
    "USD/CNY": "CNY=X",
    "USD/RUB": "RUB=X",
    "USD/INR": "INR=X",
    "USD/BRL": "BRL=X",
    "USD/MXN": "MXN=X",
    "USD/SGD": "SGD=X",
    "USD/HKD": "HKD=X",
    "USD/KRW": "KRW=X",
    "USD/THB": "THB=X",
    "USD/MYR": "MYR=X",
    "USD/PHP": "PHP=X",
    "USD/VND": "VND=X",
    # Precious metal FX pairs
    "XAU/USD": "XAUUSD=X",
    "XAG/USD": "XAGUSD=X",
}

# Map app timeframe -> (binance_interval, yahoo_range, yahoo_interval, candles_needed)
TIMEFRAME_MAP: dict[str, dict[str, Any]] = {
    "1m":  {"binance": "1m",  "yahoo_range": "1d",  "yahoo_interval": "1m",  "limit": 100},
    "3m":  {"binance": "3m",  "yahoo_range": "1d",  "yahoo_interval": "5m",  "limit": 100},
    "5m":  {"binance": "5m",  "yahoo_range": "1d",  "yahoo_interval": "5m",  "limit": 100},
    "15m": {"binance": "15m", "yahoo_range": "5d",  "yahoo_interval": "15m", "limit": 100},
    "30m": {"binance": "30m", "yahoo_range": "5d",  "yahoo_interval": "30m", "limit": 100},
    "1h":  {"binance": "1h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 100},
    "3h":  {"binance": "2h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 100},
    "6h":  {"binance": "6h",  "yahoo_range": "3mo", "yahoo_interval": "1d",  "limit": 100},
    "12h": {"binance": "12h", "yahoo_range": "3mo", "yahoo_interval": "1d",  "limit": 100},
    "18h": {"binance": "12h", "yahoo_range": "6mo", "yahoo_interval": "1d",  "limit": 100},
    "24h": {"binance": "1d",  "yahoo_range": "6mo", "yahoo_interval": "1d",  "limit": 100},
    "7d":  {"binance": "1d",  "yahoo_range": "1y",  "yahoo_interval": "1wk", "limit": 100},
    "14d": {"binance": "1d",  "yahoo_range": "2y",  "yahoo_interval": "1wk", "limit": 100},
    "30d": {"binance": "1d",  "yahoo_range": "5y",  "yahoo_interval": "1mo", "limit": 100},
}

BINANCE_BASE = "https://data-api.binance.vision"
YAHOO_BASE = "https://query1.finance.yahoo.com"
OKX_BASE = "https://www.okx.com"

# Symbols that should be fetched from OKX instead of Binance
# (e.g. HYPE / Hyperliquid is not listed on Binance spot API).
CRYPTO_OKX_MAP: dict[str, str] = {
    "HYPE": "HYPE-USDT",
}

# OKX timeframe mapping (OKX uses uppercase H/D, lowercase m for minutes)
OKX_BAR_MAP: dict[str, str] = {
    "15m": "15m", "30m": "30m", "1h": "1H", "2h": "2H", "6h": "6H",
    "12h": "12H", "1d": "1D",
}


async def _fetch_okx_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    pair = CRYPTO_OKX_MAP.get(symbol)
    if not pair:
        return []
    bar = OKX_BAR_MAP.get(interval, "1H")
    try:
        r = await client.get(
            f"{OKX_BASE}/api/v5/market/candles",
            params={"instId": pair, "bar": bar, "limit": str(min(limit, 300))},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") or []
        # OKX returns newest-first; reverse to oldest-first for charting parity with Binance.
        rows = list(reversed(rows))
        return [
            {
                "t": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in rows
        ]
    except Exception:
        return []


async def _fetch_okx_ticker(client: httpx.AsyncClient, symbol: str) -> dict[str, float] | None:
    pair = CRYPTO_OKX_MAP.get(symbol)
    if not pair:
        return None
    try:
        r = await client.get(
            f"{OKX_BASE}/api/v5/market/ticker",
            params={"instId": pair},
            timeout=8.0,
        )
        r.raise_for_status()
        d = (r.json().get("data") or [None])[0]
        if not d:
            return None
        last = float(d["last"])
        open24 = float(d.get("open24h") or last)
        change_pct = ((last - open24) / open24 * 100.0) if open24 else 0.0
        return {
            "price": last,
            "change_pct_24h": change_pct,
            "volume_24h": float(d.get("volCcy24h") or 0.0),
            "high_24h": float(d.get("high24h") or 0.0),
            "low_24h": float(d.get("low24h") or 0.0),
        }
    except Exception:
        return None


async def _fetch_binance_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    pair = CRYPTO_BINANCE_MAP.get(symbol)
    if not pair:
        return []
    try:
        r = await client.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": pair, "interval": interval, "limit": limit},
            timeout=10.0,
        )
        r.raise_for_status()
        raw = r.json()
        return [
            {
                "t": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in raw
        ]
    except Exception:
        return []


async def _fetch_binance_ticker(client: httpx.AsyncClient, symbol: str) -> dict[str, float] | None:
    pair = CRYPTO_BINANCE_MAP.get(symbol)
    if not pair:
        return None
    try:
        r = await client.get(
            f"{BINANCE_BASE}/api/v3/ticker/24hr",
            params={"symbol": pair},
            timeout=8.0,
        )
        r.raise_for_status()
        d = r.json()
        return {
            "price": float(d["lastPrice"]),
            "change_pct_24h": float(d["priceChangePercent"]),
            "volume_24h": float(d["quoteVolume"]),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
        }
    except Exception:
        return None


async def _fetch_yahoo_chart(client: httpx.AsyncClient, symbol: str, range_: str, interval: str) -> dict[str, Any] | None:
    """Legacy wrapper — delegates to `_fetch_yahoo_chart_by_symbol` so this
    path also benefits from the 60s TTL cache + retry. Symbol here is the
    canonical UI symbol (e.g. "BBCA"), mapped through STOCK_YAHOO_MAP.
    Kept for backwards-compat with any external caller that might still
    import it; current server.py routes go through `get_stock_snapshot`.
    """
    yahoo_sym = STOCK_YAHOO_MAP.get(symbol)
    if not yahoo_sym:
        return None
    return await _fetch_yahoo_chart_by_symbol(client, yahoo_sym, range_, interval)


# v8.0.4 — Pooled httpx.AsyncClient. Creating a fresh AsyncClient per
# call is expensive: each one has to open its own TCP + TLS session, and
# there is no HTTP/2 connection reuse across the pool. On cold dashboard
# load that added ~30-80 ms per upstream request. A single module-level
# client (lazily initialised, closed at shutdown) reuses connections and
# gives us built-in HTTP/2 multiplexing on Yahoo/Binance/OKX.
_HTTP_CLIENT: httpx.AsyncClient | None = None
_HTTP_CLIENT_LOCK = asyncio.Lock()


async def _http() -> httpx.AsyncClient:
    """Lazy singleton client. Safe to call concurrently."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
        return _HTTP_CLIENT
    async with _HTTP_CLIENT_LOCK:
        if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
            _HTTP_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(
                    max_keepalive_connections=32,
                    max_connections=64,
                    keepalive_expiry=30.0,
                ),
                http2=True,
                headers={"User-Agent": "Mozilla/5.0 AITradePro/8"},
            )
    return _HTTP_CLIENT


async def close_http_client() -> None:
    """Called from server shutdown to release the pool cleanly."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
        try:
            await _HTTP_CLIENT.aclose()
        finally:
            _HTTP_CLIENT = None


async def get_crypto_snapshot(symbol: str, timeframe: str) -> dict[str, Any] | None:
    tf = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])
    client = await _http()
    # Route to OKX for symbols not listed on Binance public API
    if symbol in CRYPTO_OKX_MAP:
        ticker, klines = await asyncio.gather(
            _fetch_okx_ticker(client, symbol),
            _fetch_okx_klines(client, symbol, tf["binance"], tf["limit"]),
        )
        if not ticker and not klines:
            return None
        return {"symbol": symbol, "market": "crypto", "ticker": ticker or {}, "candles": klines}
    ticker, klines = await asyncio.gather(
        _fetch_binance_ticker(client, symbol),
        _fetch_binance_klines(client, symbol, tf["binance"], tf["limit"]),
    )
    if not ticker and not klines:
        return None
    return {"symbol": symbol, "market": "crypto", "ticker": ticker or {}, "candles": klines}


async def get_stock_snapshot(symbol: str, timeframe: str, market: str = "stock_id") -> dict[str, Any] | None:
    tf = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])
    if market == "stock_id":
        sym_map = STOCK_YAHOO_MAP
    elif market == "etf":
        sym_map = ETF_YAHOO_MAP
    elif market in ("stock_us", "world_stocks"):
        sym_map = STOCK_US_YAHOO_MAP
    elif market == "gold_silver":
        sym_map = GOLD_SILVER_YAHOO_MAP
    elif market == "commodity":
        sym_map = COMMODITY_YAHOO_MAP
    elif market == "forex":
        sym_map = FOREX_YAHOO_MAP
    else:
        sym_map = STOCK_YAHOO_MAP
    yahoo_sym = sym_map.get(symbol)
    if not yahoo_sym:
        return None
    client = await _http()
    data = await _fetch_yahoo_chart_by_symbol(client, yahoo_sym, tf["yahoo_range"], tf["yahoo_interval"])
    if not data:
        return None
    return {"symbol": symbol, "market": market, "ticker": data["ticker"], "candles": data["candles"]}


async def _fetch_yahoo_chart_by_symbol(client: httpx.AsyncClient, yahoo_sym: str, range_: str, interval: str) -> dict[str, Any] | None:
    # v7.0.8 — In-memory TTL cache (~60s) keyed by (symbol, range, interval).
    # Yahoo Finance rate-limits + times out under load, causing the previous
    # Gold/Silver/Commodity/Forex detail pages to 404 after ~10s. A short
    # cache absorbs bursty polling from the detail screen (chart + analyze
    # trigger back-to-back fetches for the same symbol) and also gives a
    # near-instant response on repeated visits during the same minute.
    #
    # We also do ONE retry with a shorter (5s) timeout before returning None
    # so a single Yahoo hiccup no longer nukes the whole request.
    cache_key = (yahoo_sym, range_, interval)
    now = time.monotonic()
    cached = _YAHOO_CHART_CACHE.get(cache_key)
    if cached is not None:
        ts, payload = cached
        if now - ts < _YAHOO_CHART_TTL_SEC:
            return payload

    async def _do_fetch(timeout: float) -> dict[str, Any] | None:
        try:
            r = await client.get(
                f"{YAHOO_BASE}/v8/finance/chart/{yahoo_sym}",
                params={"range": range_, "interval": interval, "includePrePost": "false"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            result = data["chart"]["result"][0]
            meta = result.get("meta", {})
            ts_list = result.get("timestamp", []) or []
            quote = (result.get("indicators", {}).get("quote") or [{}])[0]
            opens = quote.get("open") or []
            highs = quote.get("high") or []
            lows = quote.get("low") or []
            closes = quote.get("close") or []
            volumes = quote.get("volume") or []
            candles: list[dict[str, float]] = []
            for i, t in enumerate(ts_list):
                o, hi, lo, c, v = opens[i], highs[i], lows[i], closes[i], volumes[i]
                if None in (o, hi, lo, c):
                    continue
                candles.append({
                    "t": int(t) * 1000, "open": float(o), "high": float(hi),
                    "low": float(lo), "close": float(c), "volume": float(v or 0),
                })
            last = candles[-1] if candles else None
            prev_close = float(meta.get("chartPreviousClose") or (candles[-2]["close"] if len(candles) >= 2 else (last["close"] if last else 0)))
            price = float(meta.get("regularMarketPrice") or (last["close"] if last else 0))
            change_pct = ((price - prev_close) / prev_close * 100.0) if prev_close else 0.0
            return {
                "candles": candles,
                "ticker": {
                    "price": price, "change_pct_24h": change_pct,
                    "volume_24h": float(meta.get("regularMarketVolume") or 0),
                    "high_24h": float(meta.get("regularMarketDayHigh") or (last["high"] if last else 0)),
                    "low_24h": float(meta.get("regularMarketDayLow") or (last["low"] if last else 0)),
                },
            }
        except Exception:
            return None

    # First attempt: normal 10s timeout.
    payload = await _do_fetch(10.0)
    if payload is None:
        # Single retry with a shorter timeout — Yahoo either responds fast
        # on the second try or it's truly down; either way we don't want
        # the client sitting on this for another 10s.
        payload = await _do_fetch(5.0)

    if payload is not None:
        _YAHOO_CHART_CACHE[cache_key] = (now, payload)
        # Opportunistic cache eviction — keep the dict from growing unbounded.
        if len(_YAHOO_CHART_CACHE) > _YAHOO_CHART_CACHE_MAX:
            _yahoo_cache_evict(now)
    return payload


# v7.0.8 — module-level cache (bounded, opportunistic eviction).
_YAHOO_CHART_TTL_SEC = 60.0
_YAHOO_CHART_CACHE_MAX = 512
_YAHOO_CHART_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}


def _yahoo_cache_evict(now: float) -> None:
    """Drop entries older than TTL; if still too large, drop the oldest half."""
    dead = [k for k, (ts, _p) in _YAHOO_CHART_CACHE.items() if now - ts >= _YAHOO_CHART_TTL_SEC]
    for k in dead:
        _YAHOO_CHART_CACHE.pop(k, None)
    if len(_YAHOO_CHART_CACHE) > _YAHOO_CHART_CACHE_MAX:
        # Drop the oldest half by timestamp
        items = sorted(_YAHOO_CHART_CACHE.items(), key=lambda kv: kv[1][0])
        for k, _v in items[: len(items) // 2]:
            _YAHOO_CHART_CACHE.pop(k, None)


# Yahoo Finance throttles/blocks bursts of concurrent requests from a single
# egress IP. Capping to ~30 in-flight Yahoo calls keeps us well below their
# soft-limit while still delivering a 100-150 asset column in ~4-6 seconds
# on a warm Emergent production pod.
_YAHOO_SEM = asyncio.Semaphore(30)


async def _yahoo_throttled(coro):
    async with _YAHOO_SEM:
        return await coro


async def get_batch_yahoo_spark(
    client: httpx.AsyncClient,
    symbols: list[str],
    market: str,
    range_: str,
    interval: str,
) -> dict[str, dict[str, Any]]:
    """v8.0.5 — Batched Yahoo lookup using /v7/finance/spark.

    Yahoo accepts a comma-separated `symbols` query and returns
    timestamps + close prices for ALL of them in ONE HTTP round-trip.
    On the dashboard we don't need full OHLCV per row — a close-price
    series is enough to compute the sparkline, 24h change % and the
    rule-based RSI/EMA/MACD signal. Cuts network cost from N per-symbol
    requests to 1 batched request.

    Falls back gracefully: any symbol that Yahoo omits from the
    response is filtered out here and re-fetched via the per-symbol
    chart endpoint by the caller.
    """
    if not symbols:
        return {}
    if market == "stock_id":
        sym_map = STOCK_YAHOO_MAP
    elif market == "etf":
        sym_map = ETF_YAHOO_MAP
    elif market in ("stock_us", "world_stocks"):
        sym_map = STOCK_US_YAHOO_MAP
    elif market == "gold_silver":
        sym_map = GOLD_SILVER_YAHOO_MAP
    elif market == "commodity":
        sym_map = COMMODITY_YAHOO_MAP
    elif market == "forex":
        sym_map = FOREX_YAHOO_MAP
    else:
        sym_map = STOCK_YAHOO_MAP
    # Resolve UI ↔ Yahoo tickers (skip anything without a mapping).
    pairs: list[tuple[str, str]] = [(s, sym_map[s]) for s in symbols if s in sym_map]
    if not pairs:
        return {}
    ys = ",".join(y for _, y in pairs)
    rev = {y: ui for ui, y in pairs}
    try:
        r = await client.get(
            f"{YAHOO_BASE}/v7/finance/spark",
            params={"symbols": ys, "range": range_, "interval": interval},
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return {}

    results = (data.get("spark") or {}).get("result", []) or []
    out: dict[str, dict[str, Any]] = {}
    for item in results:
        ysym = item.get("symbol")
        ui_sym = rev.get(ysym)
        if not ui_sym:
            continue
        resp = (item.get("response") or [{}])[0]
        meta = resp.get("meta") or {}
        ts_list = resp.get("timestamp") or []
        quote = ((resp.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        candles: list[dict[str, float]] = []
        for i, t in enumerate(ts_list):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            fc = float(c)
            candles.append({
                "t": int(t) * 1000,
                "open": fc, "high": fc, "low": fc, "close": fc,
                "volume": 0.0,
            })
        if not candles:
            continue
        last = candles[-1]
        prev_close = float(
            meta.get("chartPreviousClose")
            or (candles[-2]["close"] if len(candles) >= 2 else last["close"])
        )
        price = float(meta.get("regularMarketPrice") or last["close"])
        change = ((price - prev_close) / prev_close * 100.0) if prev_close else 0.0
        out[ui_sym] = {
            "symbol": ui_sym,
            "market": market,
            "ticker": {
                "price": price,
                "change_pct_24h": change,
                "volume_24h": 0.0,
                "high_24h": float(meta.get("regularMarketDayHigh") or price),
                "low_24h": float(meta.get("regularMarketDayLow") or price),
            },
            "candles": candles,
        }
    return out


async def get_batch(market: str, symbols: list[str], timeframe: str) -> list[dict[str, Any]]:
    """Fetch many symbols concurrently. Returns only successful results.

    v8.0.5 — For non-crypto markets we first try the batched Yahoo spark
    endpoint (1 HTTP call). Any symbol Yahoo omits (mismatched region,
    delisted, etc.) is re-fetched with the per-symbol chart endpoint so
    the dashboard column doesn't lose rows. In the happy path this
    reduces N HTTP calls to 1, which is where the previous "heavy" feel
    was coming from.
    """
    if market == "crypto":
        # Binance's public API tolerates our load; no need to throttle.
        results = await asyncio.gather(
            *[get_crypto_snapshot(s, timeframe) for s in symbols],
            return_exceptions=True,
        )
        out: list[dict[str, Any]] = [r for r in results if isinstance(r, dict)]
        return out

    tf = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])
    client = await _http()
    batch = await get_batch_yahoo_spark(
        client, symbols, market,
        range_=tf["yahoo_range"], interval=tf["yahoo_interval"],
    )

    # Anything the batch endpoint didn't return: fall back to per-symbol
    # chart endpoint (still throttled). This is rare in practice.
    missing = [s for s in symbols if s not in batch]
    if missing:
        fallback = await asyncio.gather(
            *[_yahoo_throttled(get_stock_snapshot(s, timeframe, market)) for s in missing],
            return_exceptions=True,
        )
        for r in fallback:
            if isinstance(r, dict):
                batch[r["symbol"]] = r
    # Preserve input order so the dashboard is stable across polls.
    return [batch[s] for s in symbols if s in batch]
