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
    # Memecoins & narratives — only symbols actually listed on Binance
    # spot; for the rest we hit CoinGecko as an on-demand fallback.
    "WIF": "WIFUSDT", "BONK": "BONKUSDT", "FLOKI": "FLOKIUSDT",
    "TRUMP": "TRUMPUSDT", "MEME": "MEMEUSDT",
    "BOME": "BOMEUSDT", "PENGU": "PENGUUSDT", "TURBO": "TURBOUSDT",
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
    # v8.1.2 — Batch add per user request. All IDX tickers use ".JK"
    # Yahoo Finance suffix. Duplicates below are silently ignored by
    # Python dict-literal (later value wins) — kept explicit so this
    # extension list is easy to diff against the user's raw list.
    "AADI": "AADI.JK", "DSSA": "DSSA.JK", "TAPG": "TAPG.JK",
    "CUAN": "CUAN.JK", "MAPI": "MAPI.JK", "POLY": "POLY.JK",
    "BFIN": "BFIN.JK", "BIPI": "BIPI.JK", "OASA": "OASA.JK",
    "INKP": "INKP.JK", "INDF": "INDF.JK", "GOTO": "GOTO.JK",
    "TINS": "TINS.JK", "BUVA": "BUVA.JK", "BRPT": "BRPT.JK",
    "RATU": "RATU.JK", "BREN": "BREN.JK", "ADHI": "ADHI.JK",
    "PGAS": "PGAS.JK", "BNBR": "BNBR.JK", "GTSI": "GTSI.JK",
    "PRDL": "PRDL.JK", "JELI": "JELI.JK", "ARCI": "ARCI.JK",
    "BUMI": "BUMI.JK", "BULL": "BULL.JK", "SGER": "SGER.JK",
    "NCKL": "NCKL.JK", "FORE": "FORE.JK", "BIRD": "BIRD.JK",
    "JSMR": "JSMR.JK", "CMPP": "CMPP.JK", "MYOR": "MYOR.JK",
    "RANS": "RANS.JK", "EMMI": "EMMI.JK", "BACH": "BACH.JK",
    "JECX": "JECX.JK", "MDIA": "MDIA.JK", "ENRG": "ENRG.JK",
    "AKRA": "AKRA.JK", "HRUM": "HRUM.JK", "INCO": "INCO.JK",
    "SGRO": "SGRO.JK", "BBYB": "BBYB.JK", "INET": "INET.JK",
    "SSMS": "SSMS.JK", "MBSS": "MBSS.JK", "TOBA": "TOBA.JK",
    "MINA": "MINA.JK", "CDIA": "CDIA.JK", "CBRE": "CBRE.JK",
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
    # v8.1.3 — Low-caps batch per user request
    "COCO": "COCO.JK", "DOOH": "DOOH.JK", "EMAS": "EMAS.JK",
    "ERAA": "ERAA.JK", "IMPC": "IMPC.JK", "KETR": "KETR.JK",
    "KOTA": "KOTA.JK", "MSIN": "MSIN.JK", "SCMA": "SCMA.JK",
    "SINI": "SINI.JK", "SOCI": "SOCI.JK", "VKTR": "VKTR.JK",
    "WBSA": "WBSA.JK",
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

    # ============================================================
    # v8.1.3 — S&P 500 extension (~120 more names beyond above)
    # ============================================================
    # More Financials / Insurance
    "ALL": "ALL", "AIG": "AIG", "MET": "MET", "PRU": "PRU",
    "TRV": "TRV", "PGR": "PGR", "CB": "CB", "AFL": "AFL",
    "USB": "USB", "PNC": "PNC", "TFC": "TFC", "COF": "COF",
    "MTB": "MTB", "RF": "RF", "FITB": "FITB", "KEY": "KEY",
    "SPGI": "SPGI", "MCO": "MCO", "MSCI": "MSCI", "ICE": "ICE",
    "CME": "CME", "NDAQ": "NDAQ", "CBOE": "CBOE", "AMP": "AMP",
    "TROW": "TROW", "STT": "STT", "BEN": "BEN", "IVZ": "IVZ",
    # More Healthcare / Biotech / Med Devices
    "CI": "CI", "CVS": "CVS", "HUM": "HUM", "ELV": "ELV",
    "CNC": "CNC", "MOH": "MOH", "HCA": "HCA", "UHS": "UHS",
    "ISRG": "ISRG", "MDT": "MDT", "SYK": "SYK", "BSX": "BSX",
    "EW": "EW", "ZBH": "ZBH", "BDX": "BDX", "BAX": "BAX",
    "IDXX": "IDXX", "IQV": "IQV", "A": "A", "ILMN": "ILMN",
    "BIIB": "BIIB", "INCY": "INCY", "ALNY": "ALNY", "BMRN": "BMRN",
    "TECH": "TECH",
    # More Consumer / Staples / Restaurants
    "PM": "PM", "MO": "MO", "STZ": "STZ", "TAP": "TAP",
    "KHC": "KHC", "MDLZ": "MDLZ", "GIS": "GIS", "K": "K",
    "HSY": "HSY", "CPB": "CPB", "SJM": "SJM", "CAG": "CAG",
    "TSN": "TSN", "HRL": "HRL", "MKC": "MKC", "CLX": "CLX",
    "CHD": "CHD", "KMB": "KMB", "KDP": "KDP", "MNST": "MNST",
    "YUM": "YUM", "CMG": "CMG", "QSR": "QSR", "DPZ": "DPZ",
    "DRI": "DRI", "TXRH": "TXRH", "EAT": "EAT",
    # More Consumer Discretionary / Apparel / Leisure
    "LULU": "LULU", "TJX": "TJX", "ROST": "ROST", "BURL": "BURL",
    "ULTA": "ULTA", "TPR": "TPR", "RL": "RL", "LEVI": "LEVI",
    "PVH": "PVH", "ETSY": "ETSY", "W": "W", "CHWY": "CHWY",
    "DASH": "DASH", "BKNG": "BKNG", "EXPE": "EXPE", "MAR": "MAR",
    "HLT": "HLT", "H": "H", "RCL": "RCL", "CCL": "CCL",
    "NCLH": "NCLH", "MGM": "MGM", "WYNN": "WYNN", "LVS": "LVS",
    "CZR": "CZR", "PENN": "PENN", "F1": "FWONA",
    # More Industrials / Transportation
    "UPS": "UPS", "FDX": "FDX", "UNP": "UNP", "CSX": "CSX",
    "NSC": "NSC", "DAL": "DAL", "UAL": "UAL", "AAL": "AAL",
    "LUV": "LUV", "JBLU": "JBLU", "ALK": "ALK", "SKYW": "SKYW",
    "SAVE": "SAVE", "CHRW": "CHRW", "XPO": "XPO", "JBHT": "JBHT",
    "ODFL": "ODFL", "SAIA": "SAIA", "ARCB": "ARCB", "R": "R",
    "WM": "WM", "RSG": "RSG", "WCN": "WCN", "SRCL": "SRCL",
    "GNRC": "GNRC", "IR": "IR", "ETN": "ETN", "EMR": "EMR",
    "ROK": "ROK", "PH": "PH", "CMI": "CMI", "PCAR": "PCAR",
    "WAB": "WAB", "URI": "URI", "FAST": "FAST", "GWW": "GWW",
    "MMC": "MMC", "AON": "AON", "AJG": "AJG", "WTW": "WTW",
    # More REITs
    "PLD": "PLD", "AMT": "AMT", "CCI": "CCI", "EQIX": "EQIX",
    "DLR": "DLR", "PSA": "PSA", "O": "O", "SPG": "SPG",
    "WELL": "WELL", "AVB": "AVB", "EQR": "EQR", "MAA": "MAA",
    "EXR": "EXR", "VTR": "VTR", "ARE": "ARE", "SBAC": "SBAC",
    # More Utilities / Renewables
    "SO": "SO", "D": "D", "AEP": "AEP", "EXC": "EXC",
    "XEL": "XEL", "SRE": "SRE", "PEG": "PEG", "ED": "ED",
    "PCG": "PCG", "AWK": "AWK", "ENPH": "ENPH", "FSLR": "FSLR",
    "RUN": "RUN", "SEDG": "SEDG", "PLUG": "PLUG",
    # More Materials / Chemicals
    "LIN": "LIN", "APD": "APD", "SHW": "SHW", "ECL": "ECL",
    "DD": "DD", "DOW": "DOW", "PPG": "PPG", "NEM": "NEM",
    "FCX": "FCX", "NUE": "NUE", "STLD": "STLD", "CLF": "CLF",
    "X": "X", "AA": "AA", "CENX": "CENX", "MP": "MP",
    "LAC": "LAC", "ALB": "ALB", "SQM": "SQM",
    # More Tech / Growth
    "CDW": "CDW", "ANSS": "ANSS", "CDNS": "CDNS", "SNPS": "SNPS",
    "KEYS": "KEYS", "FISV": "FISV", "FIS": "FIS", "PAYX": "PAYX",
    "ADP": "ADP", "GEHC": "GEHC", "ROP": "ROP", "TDG": "TDG",
    "TDY": "TDY", "TRMB": "TRMB",

    # ============================================================
    # v8.1.3 — 🇯🇵 JAPAN (Nikkei 225 top ~55)
    # ============================================================
    "TOYOTA": "7203.T", "SONYG": "6758.T", "SOFTBANK": "9984.T",
    "KEYENCE": "6861.T", "MITSUBISHI": "8058.T", "SUMITOMO": "8316.T",
    "MUFG": "8306.T", "SMFG": "8316.T", "HITACHI": "6501.T",
    "NINTENDO": "7974.T", "TOKYO_ELECTRON": "8035.T", "FANUC": "6954.T",
    "SHIN_ETSU": "4063.T", "TAKEDA": "4502.T", "ASTELLAS": "4503.T",
    "DAIICHI": "4568.T", "HONDA": "7267.T", "NISSAN": "7201.T",
    "MAZDA": "7261.T", "SUBARU": "7270.T", "SUZUKI": "7269.T",
    "PANASONIC": "6752.T", "SHARP": "6753.T", "CANON": "7751.T",
    "NIKON": "7731.T", "FUJIFILM": "4901.T", "OLYMPUS": "7733.T",
    "KOMATSU": "6301.T", "MURATA": "6981.T", "KYOCERA": "6971.T",
    "TDK": "6762.T", "ROHM": "6963.T", "ADVANTEST": "6857.T",
    "RENESAS": "6723.T", "NEC": "6701.T", "FUJITSU": "6702.T",
    "MITSUI": "8031.T", "MARUBENI": "8002.T", "ITOCHU": "8001.T",
    "KDDI": "9433.T", "NTT": "9432.T", "DOCOMO": "9437.T",
    "JR_EAST": "9020.T", "JR_CENTRAL": "9022.T", "ANA": "9202.T",
    "JAL": "9201.T", "SEVEN_I": "3382.T", "FAST_RETAILING": "9983.T",
    "MITSUBISHI_ELE": "6503.T", "DENSO": "6902.T", "BRIDGESTONE": "5108.T",
    "ORIX": "8591.T", "SEGA": "6460.T", "BANDAI": "7832.T",
    "SQUARE_ENIX": "9684.T", "KIRIN": "2503.T", "ASAHI_BEER": "2502.T",

    # ============================================================
    # v8.1.3 — 🇨🇳 CHINA A-shares (Shanghai .SS, Shenzhen .SZ) ~40
    # ============================================================
    "MOUTAI": "600519.SS", "WULIANGYE": "000858.SZ", "ICBC": "601398.SS",
    "CCB": "601939.SS", "AGBANK": "601288.SS", "BOC": "601988.SS",
    "PETROCHINA": "601857.SS", "SINOPEC": "600028.SS", "CNOOC_A": "600938.SS",
    "PING_AN": "601318.SS", "CHINA_LIFE": "601628.SS", "CITIC": "601066.SS",
    "MERCHANTS_BANK": "600036.SS", "MINSHENG": "600016.SS", "PUFA": "600000.SS",
    "GREE": "000651.SZ", "MIDEA": "000333.SZ", "HAIER": "600690.SS",
    "TCL": "000100.SZ", "BYD_A": "002594.SZ", "CATL": "300750.SZ",
    "GOTION": "002074.SZ", "EVE": "300014.SZ", "SUNGROW": "300274.SZ",
    "LONGI": "601012.SS", "TRINA": "688599.SS", "JA_SOLAR": "002459.SZ",
    "TONGWEI": "600438.SS", "ZTE_A": "000063.SZ", "HIKVISION": "002415.SZ",
    "DAHUA": "002236.SZ", "WOODY": "603288.SS", "YILI": "600887.SS",
    "MENGNIU_A": "600887.SS", "GOERTEK": "002241.SZ", "LUXSHARE": "002475.SZ",
    "SMIC": "688981.SS", "AMEC": "688012.SS", "NAURA": "002371.SZ",
    "CAMBRICON": "688256.SS", "IFLYTEK": "002230.SZ",

    # ============================================================
    # v8.1.3 — 🇭🇰 HONG KONG (.HK) ~35 top constituents
    # ============================================================
    "TENCENT": "0700.HK", "ALIBABA_HK": "9988.HK", "MEITUAN": "3690.HK",
    "JD_HK": "9618.HK", "BAIDU_HK": "9888.HK", "NETEASE_HK": "9999.HK",
    "XIAOMI": "1810.HK", "LENOVO": "0992.HK", "BYD_HK": "1211.HK",
    "GEELY": "0175.HK", "GREATWALL": "2333.HK", "NIO_HK": "9866.HK",
    "LI_AUTO_HK": "2015.HK", "XPENG_HK": "9868.HK", "HSBC": "0005.HK",
    "STANCHART_HK": "2888.HK", "BOC_HK": "2388.HK", "ICBC_HK": "1398.HK",
    "CCB_HK": "0939.HK", "PING_AN_HK": "2318.HK", "AIA": "1299.HK",
    "CK_HUTCHISON": "0001.HK", "CK_ASSET": "1113.HK", "SUN_HUNG_KAI": "0016.HK",
    "HKEX": "0388.HK", "GALAXY_ENT": "0027.HK", "SANDS_CHINA": "1928.HK",
    "MGM_CHINA": "2282.HK", "WYNN_MACAU": "1128.HK", "CATHAY_PACIFIC": "0293.HK",
    "CHINA_MOBILE": "0941.HK", "CHINA_UNICOM": "0762.HK", "CHINA_TELECOM_HK": "0728.HK",
    "SINOPEC_HK": "0386.HK", "CNOOC": "0883.HK", "PETROCHINA_HK": "0857.HK",
    "TSINGTAO": "0168.HK",

    # ============================================================
    # v8.1.3 — 🇹🇼 TAIWAN (.TW) ~20 top
    # ============================================================
    "TSMC_TW": "2330.TW", "FOXCONN": "2317.TW", "MEDIATEK": "2454.TW",
    "UNITED_MICRO": "2303.TW", "LARGAN": "3008.TW", "DELTA_TW": "2308.TW",
    "CATCHER": "2474.TW", "PEGATRON": "4938.TW", "QUANTA": "2382.TW",
    "COMPAL": "2324.TW", "WISTRON": "3231.TW", "ASUS": "2357.TW",
    "ACER": "2353.TW", "CATL_TW": "1216.TW", "CHT": "2412.TW",
    "FORMOSA_PLASTICS": "1301.TW", "NAN_YA": "1303.TW", "CTBC_FIN": "2891.TW",
    "CATHAY_FIN": "2882.TW", "FUBON_FIN": "2881.TW",

    # ============================================================
    # v8.1.3 — 🇲🇾 MALAYSIA (.KL) ~20 top
    # ============================================================
    "MAYBANK": "1155.KL", "CIMB": "1023.KL", "PBBANK": "1295.KL",
    "TENAGA": "5347.KL", "PCHEM": "5183.KL", "PETRONAS_GAS": "6033.KL",
    "PETRONAS_CHEM": "5183.KL", "IHH": "5225.KL", "GENTING": "3182.KL",
    "GENM": "4715.KL", "SIME": "4197.KL", "AXIATA": "6888.KL",
    "MAXIS": "6012.KL", "DIGI": "6947.KL", "TM": "4863.KL",
    "AMBANK": "1015.KL", "HLBANK": "5819.KL", "RHB": "1066.KL",
    "IOI": "1961.KL", "KLK": "2445.KL",

    # ============================================================
    # v8.1.3 — 🇸🇬 SINGAPORE (.SI) ~20 top
    # ============================================================
    "DBS": "D05.SI", "OCBC": "O39.SI", "UOB": "U11.SI",
    "SGX": "S68.SI", "SINGTEL": "Z74.SI", "STARHUB": "CC3.SI",
    "SIA": "C6L.SI", "SATS": "S58.SI", "COMFORTDELGRO": "C52.SI",
    "SEMBCORP": "U96.SI", "KEPPEL": "BN4.SI", "CAPITALAND": "9CI.SI",
    "CAPITALAND_INTG": "C38U.SI", "MAPLETREE": "M44U.SI", "WILMAR": "F34.SI",
    "OLAM": "VC2.SI", "GENTING_SG": "G13.SI", "JARDINE_MATHESON": "J36.SI",
    "SIA_ENG": "S59.SI", "THAI_BEV": "Y92.SI",

    # ============================================================
    # v8.1.3 — 🇷🇺 RUSSIA (.ME) ~10 (limited data due to sanctions)
    # ============================================================
    "SBER": "SBER.ME", "GAZP": "GAZP.ME", "LKOH": "LKOH.ME",
    "GMKN": "GMKN.ME", "ROSN": "ROSN.ME", "NVTK": "NVTK.ME",
    "TATN": "TATN.ME", "MTSS": "MTSS.ME", "MGNT": "MGNT.ME",
    "YDEX": "YDEX.ME",  # v8.3.4 — Yandex renamed from YNDX after 2024 restructuring
    "YNDX": "YDEX.ME",  # legacy alias so old bookmarks/links still resolve

    # ============================================================
    # v8.1.3 — 🇰🇷 KOREA (.KS/.KQ) top ~15 bonus
    # ============================================================
    "SAMSUNG": "005930.KS", "SK_HYNIX": "000660.KS", "LG_ENERGY": "373220.KS",
    "SAMSUNG_BIOLOGICS": "207940.KS", "HYUNDAI_MOTOR": "005380.KS",
    "KIA": "000270.KS", "POSCO": "005490.KS", "NAVER": "035420.KS",
    "KAKAO": "035720.KS", "LG_CHEM": "051910.KS", "CELLTRION": "068270.KS",
    "SK_INNOVATION": "096770.KS", "KB_FIN": "105560.KS", "SHINHAN_FIN": "055550.KS",
    "HANA_FIN": "086790.KS",

    # ============================================================
    # v8.1.3 — 🇬🇧 UK LONDON (.L) ~20 blue chips
    # ============================================================
    "HSBC_L": "HSBA.L", "SHELL": "SHEL.L", "BP": "BP.L",
    "ASTRA_ZENECA": "AZN.L", "GLAXO": "GSK.L", "UNILEVER": "ULVR.L",
    "DIAGEO": "DGE.L", "RIO_TINTO": "RIO.L", "GLENCORE": "GLEN.L",
    "ANGLO_AMERICAN": "AAL.L", "BARCLAYS": "BARC.L", "LLOYDS": "LLOY.L",
    "NATWEST": "NWG.L", "STANDARD_CHARTERED": "STAN.L", "PRUDENTIAL": "PRU.L",
    "TESCO": "TSCO.L", "SAINSBURYS": "SBRY.L", "M_S": "MKS.L",
    "VODAFONE": "VOD.L", "BT_GROUP": "BT-A.L", "ROLLS_ROYCE": "RR.L",
    "BAE_SYSTEMS": "BA.L", "IAG": "IAG.L",

    # ============================================================
    # v8.1.3 — 🇪🇺 EUROPE Continental (.PA/.DE/.MI/.AS/.MC/.SW) ~30
    # ============================================================
    "LVMH": "MC.PA", "TOTAL": "TTE.PA", "SANOFI": "SAN.PA",
    "AIRBUS": "AIR.PA", "LOREAL": "OR.PA", "HERMES": "RMS.PA",
    "SCHNEIDER": "SU.PA", "AXA": "CS.PA", "BNP": "BNP.PA",
    "SOCIETE_GENERALE": "GLE.PA", "STELLANTIS_PA": "STLA.PA", "DANONE": "BN.PA",
    "PERNOD": "RI.PA", "MICHELIN_PA": "ML.PA", "CARREFOUR": "CA.PA",
    "SAP": "SAP.DE", "SIEMENS": "SIE.DE", "ALLIANZ": "ALV.DE",
    "VW": "VOW3.DE", "BMW": "BMW.DE", "MERCEDES": "MBG.DE",
    "PORSCHE": "P911.DE", "DEUTSCHE_BANK": "DBK.DE", "DEUTSCHE_POST": "DPW.DE",
    "BASF": "BAS.DE", "BAYER": "BAYN.DE", "ADIDAS": "ADS.DE",
    "PUMA": "PUM.DE", "INFINEON": "IFX.DE", "MUNICH_RE": "MUV2.DE",
    "NESTLE": "NESN.SW", "NOVARTIS": "NOVN.SW", "ROCHE": "ROG.SW",
    "UBS": "UBSG.SW", "ABB": "ABBN.SW", "RICHEMONT": "CFR.SW",
    "NOVO_NORDISK": "NOVO-B.CO", "MAERSK": "MAERSK-B.CO", "ORSTED": "ORSTED.CO",
    "ASML_EU": "ASML.AS", "ING": "INGA.AS", "PHILIPS": "PHIA.AS",
    "HEINEKEN": "HEIA.AS", "STELLANTIS": "STLAM.MI", "FERRARI": "RACE.MI",
    "ENI": "ENI.MI", "ENEL": "ENEL.MI", "INTESA": "ISP.MI", "UNICREDIT": "UCG.MI",
    "SANTANDER": "SAN.MC", "BBVA": "BBVA.MC", "IBERDROLA": "IBE.MC",
    "INDITEX": "ITX.MC", "TELEFONICA": "TEF.MC",

    # ============================================================
    # v8.1.3 — 🇮🇳 INDIA NSE (.NS) ~30 top
    # ============================================================
    "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "INFOSYS": "INFY.NS",
    "HDFC_BANK": "HDFCBANK.NS", "ICICI_BANK": "ICICIBANK.NS", "SBI": "SBIN.NS",
    "AXIS_BANK": "AXISBANK.NS", "KOTAK_BANK": "KOTAKBANK.NS", "INDUSIND": "INDUSINDBK.NS",
    "BAJAJ_FIN": "BAJFINANCE.NS", "WIPRO": "WIPRO.NS", "HCL_TECH": "HCLTECH.NS",
    "TECH_MAHINDRA": "TECHM.NS", "LT": "LT.NS", "MARUTI": "MARUTI.NS",
    "M_M": "M&M.NS", "TATA_MOTORS": "TATAMOTORS.NS", "TATA_STEEL": "TATASTEEL.NS",
    "HINDALCO": "HINDALCO.NS", "JSW_STEEL": "JSWSTEEL.NS", "ONGC": "ONGC.NS",
    "IOC": "IOC.NS", "COAL_INDIA": "COALINDIA.NS", "NTPC": "NTPC.NS",
    "POWERGRID": "POWERGRID.NS", "ADANI_ENT": "ADANIENT.NS", "ADANI_PORTS": "ADANIPORTS.NS",
    "ADANI_GREEN": "ADANIGREEN.NS", "ITC": "ITC.NS", "HINDUSTAN_UNILEVER": "HINDUNILVR.NS",
    "NESTLE_INDIA": "NESTLEIND.NS", "SUN_PHARMA": "SUNPHARMA.NS", "DR_REDDY": "DRREDDY.NS",
    "CIPLA": "CIPLA.NS", "APOLLO_HOSP": "APOLLOHOSP.NS", "ZOMATO": "ZOMATO.NS",
    "NYKAA": "NYKAA.NS", "PAYTM": "PAYTM.NS", "IRCTC": "IRCTC.NS",

    # ============================================================
    # v8.1.3 — 🇨🇦 CANADA TSX (.TO) ~15 top
    # ============================================================
    "SHOPIFY_CA": "SHOP.TO", "RBC": "RY.TO", "TD_BANK": "TD.TO",
    "BMO": "BMO.TO", "BNS": "BNS.TO", "CIBC": "CM.TO",
    "ENBRIDGE": "ENB.TO", "TC_ENERGY": "TRP.TO", "CNRL": "CNQ.TO",
    "SUNCOR": "SU.TO", "CNR_RAIL": "CNR.TO", "CP_RAIL": "CP.TO",
    "BROOKFIELD": "BN.TO", "NUTRIEN": "NTR.TO", "BARRICK": "ABX.TO",
    "MANULIFE": "MFC.TO", "BCE": "BCE.TO", "TELUS": "T.TO",
    "LOBLAW": "L.TO", "COSTCO_CA": "COST.TO",

    # ============================================================
    # v8.1.3 — 🇦🇺 AUSTRALIA ASX (.AX) ~15 top
    # ============================================================
    "BHP_AX": "BHP.AX", "CBA": "CBA.AX", "WESTPAC": "WBC.AX",
    "ANZ": "ANZ.AX", "NAB": "NAB.AX", "MACQUARIE": "MQG.AX",
    "TELSTRA": "TLS.AX", "WOOLWORTHS": "WOW.AX", "COLES": "COL.AX",
    "WESFARMERS": "WES.AX", "FORTESCUE": "FMG.AX", "RIO_AX": "RIO.AX",
    "SOUTH32": "S32.AX", "NEWCREST": "NCM.AX", "QANTAS": "QAN.AX",
    "TRANSURBAN": "TCL.AX", "GOODMAN": "GMG.AX", "CSL": "CSL.AX",

    # ============================================================
    # v8.1.3 — 🛢️ GULF (.SR Saudi / .DFM UAE / .QA Qatar) ~15 top
    # ============================================================
    "ARAMCO": "2222.SR", "SAUDI_TELECOM": "7010.SR", "ALINMA": "1150.SR",
    "SNB": "1180.SR", "AL_RAJHI": "1120.SR", "SABIC": "2010.SR",
    "MAADEN": "1211.SR", "EMAAR": "EMAAR.DU", "DUBAI_ISLAMIC": "DIB.DU",
    "EMIRATES_NBD": "EMIRATESNBD.DU", "FIRST_ABU_DHABI": "FAB.AD",
    "IHC": "IHC.AD", "ADNOC_GAS": "ADNOCGAS.AD", "ADCB": "ADCB.AD",
    "QATAR_NATIONAL_BANK": "QNBK.QA", "INDUSTRIES_QATAR": "IQCD.QA",
    "OOREDOO": "ORDS.QA",

    # ============================================================
    # v8.1.3 — 🌎 LATAM (.SA Brazil / .MX Mexico / .SN Chile) ~15
    # ============================================================
    "PETROBRAS": "PETR4.SA", "VALE_BR": "VALE3.SA", "ITAU": "ITUB4.SA",
    "BRADESCO": "BBDC4.SA", "SANTANDER_BR": "SANB11.SA", "BANCO_BRASIL": "BBAS3.SA",
    "AMBEV": "ABEV3.SA", "JBS": "JBSS3.SA", "MAGAZINE_LUIZA": "MGLU3.SA",
    "WEG": "WEGE3.SA", "LOCALIZA": "RENT3.SA", "SUZANO": "SUZB3.SA",
    "AMERICA_MOVIL": "AMXB.MX", "WALMEX": "WALMEX.MX", "FEMSA": "FEMSAUBD.MX",
    "CEMEX": "CEMEXCPO.MX", "GRUPO_BIMBO": "BIMBOA.MX",
    "SQM_CL": "SQM-B.SN", "FALABELLA": "FALABELLA.SN",

    # ============================================================
    # v8.1.3 — 🇿🇦 SOUTH AFRICA JSE (.JO) ~10 top
    # ============================================================
    "NASPERS": "NPN.JO", "PROSUS": "PRX.JO", "MTN": "MTN.JO",
    "VODACOM": "VOD.JO", "STANDARD_BANK_SA": "SBK.JO", "FIRSTRAND": "FSR.JO",
    "ABSA": "ABG.JO", "SASOL": "SOL.JO", "ANGLO_AMERICAN_SA": "AGL.JO",
    "SHOPRITE": "SHP.JO", "WOOLWORTHS_SA": "WHL.JO", "DISCOVERY": "DSY.JO",

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
# v8.1.1 — Fallback for coins that aren't on Binance/OKX spot (Solana
# DEX-only memes like MOODENG, POPCAT, BRETT, MEW, etc.). CoinGecko's
# free API covers 10k+ tokens; we resolve symbol → coin_id via /search
# then pull OHLC via /coins/{id}/market_chart.
COINGECKO_BASE = "https://api.coingecko.com/api/v3"


# v8.1.3 — Regional filter for World Stocks (derived from Yahoo suffix).
# Used by /api/dashboard?region=X and frontend filter chips.
# Order matters: check most-specific suffix first (e.g. .KS before .K).
_YAHOO_SUFFIX_REGION: list[tuple[str, str]] = [
    (".JK", "indonesia"),
    (".T", "japan"),
    (".SS", "china"),
    (".SZ", "china"),
    (".HK", "hongkong"),
    (".TW", "taiwan"),
    (".KL", "malaysia"),
    (".SI", "singapore"),
    (".KS", "korea"),
    (".KQ", "korea"),
    (".ME", "russia"),
    (".NS", "india"),
    (".BO", "india"),
    (".L", "europe"),      # UK LSE
    (".PA", "europe"),     # Paris
    (".DE", "europe"),     # Xetra
    (".F", "europe"),      # Frankfurt
    (".MI", "europe"),     # Milan
    (".AS", "europe"),     # Amsterdam
    (".MC", "europe"),     # Madrid
    (".SW", "europe"),     # Zurich
    (".CO", "europe"),     # Copenhagen
    (".HE", "europe"),     # Helsinki
    (".ST", "europe"),     # Stockholm
    (".OL", "europe"),     # Oslo
    (".BR", "europe"),     # Brussels
    (".VI", "europe"),     # Vienna
    (".LS", "europe"),     # Lisbon
    (".WA", "europe"),     # Warsaw
    (".PR", "europe"),     # Prague
    (".BD", "europe"),     # Budapest
    (".TO", "canada"),
    (".V", "canada"),      # TSXV
    (".AX", "australia"),
    (".NZ", "australia"),  # bundle NZ with AU
    (".SR", "gulf"),       # Saudi
    (".DU", "gulf"),       # Dubai
    (".AD", "gulf"),       # Abu Dhabi
    (".QA", "gulf"),       # Qatar
    (".KW", "gulf"),       # Kuwait
    (".SA", "latam"),      # Brazil
    (".MX", "latam"),      # Mexico
    (".SN", "latam"),      # Santiago
    (".BA", "latam"),      # Buenos Aires
    (".JO", "africa"),     # South Africa JSE
]


def region_from_yahoo_ticker(yahoo_ticker: str) -> str:
    """Return region key from Yahoo suffix. Returns 'us' if no suffix
    (or index tickers like ^GSPC/^N225 which we tag under 'index')."""
    if not yahoo_ticker:
        return "us"
    if yahoo_ticker.startswith("^") or yahoo_ticker.endswith("=F") or yahoo_ticker.endswith("=X"):
        return "index"
    tk = yahoo_ticker.upper()
    for suffix, region in _YAHOO_SUFFIX_REGION:
        if tk.endswith(suffix.upper()):
            return region
    return "us"


def region_for_symbol(market: str, symbol: str) -> str | None:
    """Return region key for a given (market, symbol) tuple. Only
    meaningful for stock_us / stock_id — other markets return None."""
    if market == "stock_id":
        return "indonesia"
    if market != "stock_us":
        return None
    yh = STOCK_US_YAHOO_MAP.get(symbol.upper())
    if not yh:
        return None
    return region_from_yahoo_ticker(yh)

# Symbols that should be fetched from OKX instead of Binance
# (e.g. HYPE / Hyperliquid is not listed on Binance spot API).
CRYPTO_OKX_MAP: dict[str, str] = {
    "HYPE": "HYPE-USDT",
}

# v8.1.3 — Auto-loaded full Binance USDT universe.
# Populated on backend startup via `_load_binance_universe()` (background
# task) — one call to `/api/v3/exchangeInfo` gives us ~2000 symbols.
# Refreshed every 6 hours. Used by /api/search to find ANY currently
# listed Binance spot pair (MOODENG, POPCAT, BRETT, CAT, etc.) without
# manual map updates.
# Structure: base_asset_upper -> "BASE" (canonical crypto symbol).
BINANCE_UNIVERSE: dict[str, str] = {}
BINANCE_UNIVERSE_READY = asyncio.Event()
_BINANCE_UNIVERSE_LOCK = asyncio.Lock()
_BINANCE_UNIVERSE_LAST_LOAD = 0.0
BINANCE_UNIVERSE_TTL = 6 * 3600  # 6 hours


async def _load_binance_universe(force: bool = False) -> int:
    """Load / refresh the full Binance spot USDT universe into memory.

    Non-blocking: caller schedules this as an asyncio task from server
    startup. Failures are swallowed (search silently falls back to the
    static maps). Returns the number of symbols loaded (0 on failure).
    """
    global _BINANCE_UNIVERSE_LAST_LOAD
    async with _BINANCE_UNIVERSE_LOCK:
        now = time.time()
        if not force and BINANCE_UNIVERSE and (now - _BINANCE_UNIVERSE_LAST_LOAD) < BINANCE_UNIVERSE_TTL:
            return len(BINANCE_UNIVERSE)
        try:
            client = await _http()
            r = await client.get(
                "https://api.binance.com/api/v3/exchangeInfo",
                timeout=20.0,
            )
            r.raise_for_status()
            data = r.json()
            fresh: dict[str, str] = {}
            for sym in data.get("symbols", []):
                if sym.get("quoteAsset") != "USDT":
                    continue
                if sym.get("status") != "TRADING":
                    continue
                # Only include real spot pairs (skip margin-only / leveraged tokens).
                # isSpotTradingAllowed is present on modern Binance API; if
                # missing we fall back to `permissions` containing "SPOT".
                is_spot = sym.get("isSpotTradingAllowed")
                if is_spot is False:
                    continue
                if is_spot is None:
                    perms = sym.get("permissions") or []
                    if perms and "SPOT" not in perms:
                        continue
                base = (sym.get("baseAsset") or "").upper()
                if not base:
                    continue
                # Skip leveraged token bases (UP/DOWN/BULL/BEAR variants).
                if any(base.endswith(suf) for suf in ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")):
                    continue
                fresh[base] = base
            if fresh:
                BINANCE_UNIVERSE.clear()
                BINANCE_UNIVERSE.update(fresh)
                _BINANCE_UNIVERSE_LAST_LOAD = now
                BINANCE_UNIVERSE_READY.set()
            return len(BINANCE_UNIVERSE)
        except Exception:
            # Do not clear on failure — keep stale-but-usable data.
            return len(BINANCE_UNIVERSE)


async def get_binance_universe() -> dict[str, str]:
    """Public accessor for the search endpoint. Never blocks — returns
    whatever universe is currently loaded (may be empty during first
    30s of startup)."""
    return BINANCE_UNIVERSE


# v8.1.3 — Bitget spot fallback (used when Binance says "no such pair").
# Public endpoint: https://api.bitget.com/api/v2/spot/market/candles
BITGET_BASE = "https://api.bitget.com"
BITGET_UNIVERSE: dict[str, str] = {}  # base_upper -> pair (e.g. "MOODENG" -> "MOODENGUSDT")
BITGET_UNIVERSE_READY = asyncio.Event()
_BITGET_UNIVERSE_LOCK = asyncio.Lock()
_BITGET_UNIVERSE_LAST_LOAD = 0.0

# Bitget uses different granularity strings: 1min/5min/15min/30min/1h/4h/6h/12h/1day/1week
BITGET_GRANULARITY_MAP: dict[str, str] = {
    "15m": "15min", "30m": "30min", "1h": "1h", "2h": "4h",
    "6h": "6h", "12h": "12h", "1d": "1day",
}


async def _load_bitget_universe(force: bool = False) -> int:
    """Load Bitget spot USDT universe. Same lifecycle as Binance."""
    global _BITGET_UNIVERSE_LAST_LOAD
    async with _BITGET_UNIVERSE_LOCK:
        now = time.time()
        if not force and BITGET_UNIVERSE and (now - _BITGET_UNIVERSE_LAST_LOAD) < BINANCE_UNIVERSE_TTL:
            return len(BITGET_UNIVERSE)
        try:
            client = await _http()
            r = await client.get(
                f"{BITGET_BASE}/api/v2/spot/public/symbols",
                timeout=20.0,
            )
            r.raise_for_status()
            data = r.json()
            fresh: dict[str, str] = {}
            for sym in (data.get("data") or []):
                if sym.get("status") != "online":
                    continue
                quote = (sym.get("quoteCoin") or "").upper()
                if quote != "USDT":
                    continue
                base = (sym.get("baseCoin") or "").upper()
                pair = sym.get("symbol") or f"{base}USDT"
                if base:
                    fresh[base] = pair
            if fresh:
                BITGET_UNIVERSE.clear()
                BITGET_UNIVERSE.update(fresh)
                _BITGET_UNIVERSE_LAST_LOAD = now
                BITGET_UNIVERSE_READY.set()
            return len(BITGET_UNIVERSE)
        except Exception:
            return len(BITGET_UNIVERSE)


async def _fetch_bitget_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    pair = BITGET_UNIVERSE.get(symbol.upper()) or f"{symbol.upper()}USDT"
    granularity = BITGET_GRANULARITY_MAP.get(interval, "1h")
    try:
        r = await client.get(
            f"{BITGET_BASE}/api/v2/spot/market/candles",
            params={"symbol": pair, "granularity": granularity, "limit": str(min(limit, 200))},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") or []
        # Bitget returns oldest-first arrays: [ts, open, high, low, close, baseVol, quoteVol]
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


async def _fetch_bitget_ticker(client: httpx.AsyncClient, symbol: str) -> dict[str, float] | None:
    pair = BITGET_UNIVERSE.get(symbol.upper()) or f"{symbol.upper()}USDT"
    try:
        r = await client.get(
            f"{BITGET_BASE}/api/v2/spot/market/tickers",
            params={"symbol": pair},
            timeout=8.0,
        )
        r.raise_for_status()
        rows = (r.json().get("data") or [])
        if not rows:
            return None
        d = rows[0]
        last = float(d.get("lastPr") or 0.0)
        open_utc0 = float(d.get("openUtc") or last or 0.0) or last
        change_pct = ((last - open_utc0) / open_utc0 * 100.0) if open_utc0 else 0.0
        return {
            "price": last,
            "change_pct_24h": change_pct,
            "volume_24h": float(d.get("quoteVolume") or 0.0),
            "high_24h": float(d.get("high24h") or 0.0),
            "low_24h": float(d.get("low24h") or 0.0),
        }
    except Exception:
        return None

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
    # v8.1.1 — On-demand lookup: if the symbol isn't in our curated map,
    # try the naive `${SYMBOL}USDT` pair name. Binance's public API is
    # perfectly happy to serve any listed pair, so this lets users find
    # brand-new listings (MOODENG, POPCAT, etc.) without a code update.
    pair = CRYPTO_BINANCE_MAP.get(symbol) or f"{symbol.upper()}USDT"
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
    pair = CRYPTO_BINANCE_MAP.get(symbol) or f"{symbol.upper()}USDT"
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
    if ticker and klines:
        return {"symbol": symbol, "market": "crypto", "ticker": ticker, "candles": klines}
    # v8.1.3 — Binance said "no such pair" or returned partial data —
    # try Bitget spot next (broader listing incl. brand-new tokens).
    bg_ticker, bg_klines = await asyncio.gather(
        _fetch_bitget_ticker(client, symbol),
        _fetch_bitget_klines(client, symbol, tf["binance"], tf["limit"]),
    )
    if bg_ticker and bg_klines:
        return {"symbol": symbol, "market": "crypto", "ticker": bg_ticker, "candles": bg_klines}
    # If we got partial Binance data (ticker OR klines but not both),
    # combine with Bitget to prefer completeness.
    combined_ticker = ticker or bg_ticker
    combined_klines = klines or bg_klines
    if combined_ticker and combined_klines:
        return {"symbol": symbol, "market": "crypto", "ticker": combined_ticker, "candles": combined_klines}
    # v8.1.1 — Final fallback: CoinGecko for Solana DEX memes and
    # long-tail alts that never touched a CEX.
    return await _fetch_coingecko_snapshot(client, symbol, tf)


# ── CoinGecko fallback ────────────────────────────────────────────────

_CG_ID_CACHE: dict[str, str | None] = {}  # symbol → coingecko coin_id
_CG_ID_LOCK = asyncio.Lock()
# v8.1.2 — Snapshot response cache (5 min TTL). CoinGecko free tier is
# ~30 req/min; without this we get HTTP 429 the moment two users search
# for popular meme tokens in a row.
_CG_SNAP_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CG_SNAP_TTL_SEC = 300.0


async def _resolve_coingecko_id(client: httpx.AsyncClient, symbol: str) -> str | None:
    """Symbol → CoinGecko coin_id resolution with per-process cache.

    Uses `/search?query=` and prefers the top result whose `symbol` field
    matches EXACTLY (case-insensitive). Returns None if nothing matches;
    callers should treat that as "unknown asset".
    """
    key = symbol.upper()
    if key in _CG_ID_CACHE:
        return _CG_ID_CACHE[key]
    async with _CG_ID_LOCK:
        if key in _CG_ID_CACHE:
            return _CG_ID_CACHE[key]
        try:
            r = await client.get(
                f"{COINGECKO_BASE}/search",
                params={"query": symbol},
                timeout=8.0,
            )
            r.raise_for_status()
            data = r.json()
            coins = data.get("coins") or []
            # Prefer exact symbol match (case-insensitive), else first hit.
            exact = next((c for c in coins if (c.get("symbol") or "").upper() == key), None)
            picked = exact or (coins[0] if coins else None)
            coin_id = picked.get("id") if picked else None
        except Exception:
            coin_id = None
        _CG_ID_CACHE[key] = coin_id
        return coin_id


# v8.1.3 — CoinGecko multi-match search for disambiguation (e.g. "CAT").
# Returns top-N candidates sorted by market cap rank.
_CG_MULTI_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CG_MULTI_TTL_SEC = 900.0  # 15 min


async def coingecko_multi_search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return up to `limit` CoinGecko coin candidates matching the query,
    sorted by market cap rank (best first). Each entry has:
      {id, symbol, name, market_cap_rank, thumb}

    Silently returns [] on failure or rate-limit — caller must handle
    empty case gracefully.
    """
    key = f"{query.upper()}:{limit}"
    now = time.time()
    hit = _CG_MULTI_CACHE.get(key)
    if hit and (now - hit[0]) < _CG_MULTI_TTL_SEC:
        return hit[1]
    try:
        client = await _http()
        r = await client.get(
            f"{COINGECKO_BASE}/search",
            params={"query": query},
            timeout=8.0,
        )
        r.raise_for_status()
        coins = (r.json().get("coins") or [])[:20]
        q_upper = query.upper()
        # Rank: exact symbol match (0) < exact name (1) < prefix (2) < contains (3)
        def rank(c: dict[str, Any]) -> tuple[int, int]:
            sym = (c.get("symbol") or "").upper()
            name = (c.get("name") or "").upper()
            mcap = c.get("market_cap_rank") or 999999
            if sym == q_upper:
                return (0, mcap)
            if name == q_upper:
                return (1, mcap)
            if sym.startswith(q_upper) or name.startswith(q_upper):
                return (2, mcap)
            return (3, mcap)
        coins.sort(key=rank)
        out = [
            {
                "id": c.get("id"),
                "symbol": (c.get("symbol") or "").upper(),
                "name": c.get("name") or "",
                "market_cap_rank": c.get("market_cap_rank"),
                "thumb": c.get("thumb") or c.get("large"),
            }
            for c in coins[:limit]
            if c.get("id")
        ]
        _CG_MULTI_CACHE[key] = (now, out)
        return out
    except Exception:
        return []


def _cg_days_for_tf(tf: dict[str, Any]) -> tuple[int, str]:
    """Map internal timeframe → (days, interval) for CoinGecko market_chart.

    v8.1.2 — CoinGecko dropped the `interval` param from the free tier;
    granularity is auto-picked based on the `days` value:
      days=1     → 5-minute candles
      days=2-90  → hourly
      days=91+   → daily
    """
    binance = tf.get("binance", "1h")
    if binance in ("15m", "30m"):
        return (1, "")
    if binance in ("1h", "2h", "4h"):
        return (7, "")
    if binance in ("6h", "12h", "1d"):
        return (90, "")
    return (7, "")


async def _fetch_coingecko_snapshot(
    client: httpx.AsyncClient, symbol: str, tf: dict[str, Any]
) -> dict[str, Any] | None:
    # Try cache first — vital because CoinGecko free tier rate-limits
    # us at ~30 req/min. Repeated searches within TTL cost 0 upstream.
    cache_key = f"{symbol.upper()}:{tf.get('binance', '1h')}"
    hit = _CG_SNAP_CACHE.get(cache_key)
    if hit and (time.monotonic() - hit[0]) < _CG_SNAP_TTL_SEC:
        return hit[1]

    coin_id = await _resolve_coingecko_id(client, symbol)
    if not coin_id:
        return None
    days, _interval = _cg_days_for_tf(tf)
    try:
        r = await client.get(
            f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=12.0,
        )
        if r.status_code == 429:
            # Rate-limited: return stale cache if we have one, else None.
            if hit:
                return hit[1]
            return None
        r.raise_for_status()
        data = r.json()
        prices = data.get("prices") or []       # [[t_ms, price], ...]
        volumes = data.get("total_volumes") or []
        if not prices:
            return None
        # Synthesise minimal OHLCV from the close series. CoinGecko free
        # tier only exposes closes here; the "ohlc" endpoint gives real
        # candles but with tighter rate limits. For obscure meme tokens
        # this trade-off is acceptable — dashboard already only shows
        # these via search, not the main columns.
        candles: list[dict[str, float]] = []
        vol_map = {int(v[0]): float(v[1] or 0.0) for v in volumes}
        for i, (t, p) in enumerate(prices):
            fp = float(p)
            candles.append({
                "t": int(t),
                "open": fp, "high": fp, "low": fp, "close": fp,
                "volume": vol_map.get(int(t), 0.0),
            })
        last = candles[-1]
        prev = candles[max(0, len(candles) - 25)]["close"]  # ~24h ago (hourly)
        price = last["close"]
        change_pct = ((price - prev) / prev * 100.0) if prev else 0.0
        highs = [c["close"] for c in candles[-25:]]
        result = {
            "symbol": symbol,
            "market": "crypto",
            "ticker": {
                "price": price,
                "change_pct_24h": change_pct,
                "volume_24h": sum(c["volume"] for c in candles[-25:]),
                "high_24h": max(highs) if highs else price,
                "low_24h": min(highs) if highs else price,
            },
            "candles": candles,
        }
        _CG_SNAP_CACHE[cache_key] = (time.monotonic(), result)
        return result
    except Exception:
        return None


# --------------------------- MOEX (Russia) --------------------------------
# v8.3.4 — Moscow Exchange public API fallback for `.ME` (Russian) stocks.
# Yahoo Finance stopped serving historical candles for Russian tickers after
# sanctions restrictions, so the detail-page chart and technical indicators
# came up blank. MOEX ISS is free and unauthenticated, still returns full
# OHLC candles, and matches Yahoo's ticker set 1:1 for our SBER/GAZP/LKOH/
# GMKN/ROSN/etc. universe. See `_MOEX_INTERVAL_MAP` for the interval bridge.

MOEX_BASE = "https://iss.moex.com/iss"

# App timeframe → MOEX interval (in minutes). MOEX supports:
#   1, 10, 60 (minutes), 24 (day), 7 (week), 31 (month), 4 (quarter).
# We collapse very-short timeframes to what MOEX exposes without exploding
# rate limits — the resulting candles are still accurate for indicators.
_MOEX_INTERVAL_MAP: dict[str, int] = {
    "1m": 1, "3m": 10, "5m": 10, "15m": 10, "30m": 10,
    "1h": 60, "3h": 60, "6h": 60, "12h": 60,
    "18h": 24, "24h": 24, "7d": 7, "14d": 7, "30d": 31,
}

# How many days back to request per timeframe so we still land ~100 candles.
_MOEX_LOOKBACK_DAYS: dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 3, "15m": 5, "30m": 10,
    "1h": 30, "3h": 60, "6h": 90, "12h": 120,
    "18h": 180, "24h": 180, "7d": 730, "14d": 730, "30d": 1825,
}


def _moex_symbol(symbol: str) -> str:
    """Strip the trailing `.ME` used inside Yahoo mappings so we hand MOEX
    a bare board ticker (SBER.ME → SBER).
    """
    up = symbol.upper()
    return up[:-3] if up.endswith(".ME") else up


async def _fetch_moex_candles(
    client: httpx.AsyncClient, symbol: str, timeframe: str,
) -> dict[str, Any] | None:
    """Fetch OHLC candles from MOEX ISS. Returns the same shape as our
    Yahoo helpers so `get_stock_snapshot` can substitute it drop-in.
    """
    interval = _MOEX_INTERVAL_MAP.get(timeframe, 60)
    lookback = _MOEX_LOOKBACK_DAYS.get(timeframe, 30)
    from datetime import datetime, timedelta, timezone
    frm = (datetime.now(timezone.utc) - timedelta(days=lookback)).strftime("%Y-%m-%d")

    moex_sym = _moex_symbol(symbol)
    url = f"{MOEX_BASE}/engines/stock/markets/shares/securities/{moex_sym}/candles.json"
    params = {"interval": str(interval), "from": frm}

    try:
        r = await client.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    c = data.get("candles", {}) or {}
    cols = c.get("columns") or []
    rows = c.get("data") or []
    if not rows or not cols:
        return None

    idx = {name: i for i, name in enumerate(cols)}
    for k in ("open", "close", "high", "low", "volume", "begin"):
        if k not in idx:
            return None

    from datetime import datetime  # noqa: reimport to avoid closure edge
    candles: list[dict[str, Any]] = []
    for row in rows:
        try:
            begin = row[idx["begin"]]
            # MOEX timestamps are naive UTC ("YYYY-MM-DD HH:MM:SS").
            dt = datetime.strptime(begin, "%Y-%m-%d %H:%M:%S")
            ts_ms = int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
            candles.append({
                "t": ts_ms,
                "open": float(row[idx["open"]]),
                "high": float(row[idx["high"]]),
                "low":  float(row[idx["low"]]),
                "close": float(row[idx["close"]]),
                "volume": float(row[idx["volume"]] or 0),
            })
        except Exception:
            continue

    if not candles:
        return None

    # Trim to 100 latest so downstream indicators match Yahoo's shape.
    candles = candles[-100:]
    latest = candles[-1]
    first = candles[0]
    price = latest["close"]
    open_first = first["open"] or price
    change_pct = ((price - open_first) / open_first) * 100 if open_first else 0.0
    highs_24 = [c["high"] for c in candles[-25:]]
    lows_24 = [c["low"] for c in candles[-25:]]
    return {
        "symbol": symbol,
        "ticker": {
            "price": price,
            "change_pct_24h": change_pct,
            "volume_24h": sum(c["volume"] for c in candles[-25:]),
            "high_24h": max(highs_24) if highs_24 else price,
            "low_24h": min(lows_24) if lows_24 else price,
        },
        "candles": candles,
    }


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
    # v8.3.4 — For `.ME` (Russian) tickers, Yahoo returns quote metadata but
    # zero candles due to post-sanction restrictions. Route to MOEX ISS
    # instead so the detail-page chart and technical indicators keep
    # working. Yahoo still handles every other market.
    if yahoo_sym.upper().endswith(".ME"):
        moex_payload = await _fetch_moex_candles(client, yahoo_sym, timeframe)
        if moex_payload and moex_payload.get("candles"):
            return {
                "symbol": symbol,
                "market": market,
                "ticker": moex_payload["ticker"],
                "candles": moex_payload["candles"],
            }
        # If MOEX is unreachable, fall through to Yahoo so we at least
        # return whatever quote data Yahoo still exposes.

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

    v8.1.1 — REVERTED to full OHLCV chart endpoint per symbol. The spark
    batch endpoint (v8.0.5) was faster on cold start but only returned
    close prices, forcing us to synthesise `open=high=low=close` — that
    broke ATR (volatility) and any signal reason that depends on the
    intraday range (high/low breakouts, wick rejects). Signal quality
    now matches v2.1.8 exactly. Cold-start latency is offset by the
    300s cache + stale-while-revalidate layer in server.py, so warm hits
    are still sub-100ms.

    Batch spark helper `get_batch_yahoo_spark` is kept below in case it
    is useful for lightweight preview views in the future.
    """
    if market == "crypto":
        # Binance's public API tolerates our load; no need to throttle.
        results = await asyncio.gather(
            *[get_crypto_snapshot(s, timeframe) for s in symbols],
            return_exceptions=True,
        )
    else:
        # Real OHLCV from /v8/finance/chart (throttled to avoid Yahoo
        # rate-limiting). Uses the pooled httpx.AsyncClient + 60s TTL
        # cache inside `_fetch_yahoo_chart_by_symbol`, so repeat calls
        # cost effectively nothing.
        results = await asyncio.gather(
            *[
                _yahoo_throttled(get_stock_snapshot(s, timeframe, market))
                for s in symbols
            ],
            return_exceptions=True,
        )
    out: list[dict[str, Any]] = [r for r in results if isinstance(r, dict)]
    return out
