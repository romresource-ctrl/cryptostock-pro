"""Market data adapters for crypto (Binance) and Indonesian stocks (Yahoo Finance).

All functions return native Python types; no MongoDB.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

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
    "RAJA": "RAJA.JK",
    # Conglomerates & industrials
    "ASII": "ASII.JK", "EMTK": "EMTK.JK", "PANI": "PANI.JK",
    "TLKM": "TLKM.JK",
    "ISAT": "ISAT.JK", "EXCL": "EXCL.JK", "TOWR": "TOWR.JK",
    "MTEL": "MTEL.JK", "MAPA": "MAPA.JK",
    "ACES": "ACES.JK", "MIDI": "MIDI.JK", "AMRT": "AMRT.JK",
    # Consumer & retail
    "SIDO": "SIDO.JK", "UNVR": "UNVR.JK",
    "ICBP": "ICBP.JK", "KLBF": "KLBF.JK",
    "GGRM": "GGRM.JK", "HMSP": "HMSP.JK",
    "BUKA": "BUKA.JK", "ARTO": "ARTO.JK", "BBHI": "BBHI.JK",
    # Property, construction & infra
    "BSDE": "BSDE.JK", "CTRA": "CTRA.JK", "PWON": "PWON.JK",
    "SMRA": "SMRA.JK", "PTPP": "PTPP.JK", "WIKA": "WIKA.JK",
    "WSKT": "WSKT.JK", "SMGR": "SMGR.JK",
    "INTP": "INTP.JK", "SMCB": "SMCB.JK",
    # Palm oil, plantations
    "AALI": "AALI.JK", "LSIP": "LSIP.JK", "SIMP": "SIMP.JK",
    "TBLA": "TBLA.JK", "DSNG": "DSNG.JK",
    # Automotive & transportation
    "IMAS": "IMAS.JK", "GJTL": "GJTL.JK", "GIAA": "GIAA.JK",
    # Healthcare
    "MIKA": "MIKA.JK", "HEAL": "HEAL.JK", "SILO": "SILO.JK",
    "TSPC": "TSPC.JK",
    # Additional 30 IDX tickers → total ~110
    # Energy / coal / oil / heavy equipment
    "UNTR": "UNTR.JK", "BYAN": "BYAN.JK",
    "INDY": "INDY.JK", "HEXA": "HEXA.JK",
    # Banks (secondary)
    "BBTN": "BBTN.JK", "MEGA": "MEGA.JK",
    # Consumer / F&B / retail
    "CPIN": "CPIN.JK", "JPFA": "JPFA.JK", "MAIN": "MAIN.JK",
    "ULTJ": "ULTJ.JK", "ROTI": "ROTI.JK",
    # Pharma / healthcare
    "KAEF": "KAEF.JK", "INAF": "INAF.JK",
    # Property (extended)
    "LPKR": "LPKR.JK",
    # Construction & infra
    "WSBP": "WSBP.JK",
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
    # v8.1.3 — Low-caps batch per user request
    "COCO": "COCO.JK", "DOOH": "DOOH.JK", "EMAS": "EMAS.JK",
    "ERAA": "ERAA.JK", "IMPC": "IMPC.JK", "KETR": "KETR.JK",
    "KOTA": "KOTA.JK", "MSIN": "MSIN.JK", "SCMA": "SCMA.JK",
    "SINI": "SINI.JK", "SOCI": "SOCI.JK", "VKTR": "VKTR.JK",
    "WBSA": "WBSA.JK",
    # v8.12.63 — Medium/low-cap IDX expansion per user request (PACK,
    # KICI, dsb). Semua ticker memakai suffix Yahoo ".JK". Ticker yang
    # tidak valid/delisted otomatis ter-drop dari hasil search karena
    # snapshot Yahoo-nya None — aman untuk daftar besar.
    # --- Perbankan & multifinance kecil/menengah ---
    "AMAR": "AMAR.JK", "BABP": "BABP.JK", "BACA": "BACA.JK",
    "BANK": "BANK.JK", "BBSI": "BBSI.JK", "BCAP": "BCAP.JK",
    "BDMN": "BDMN.JK", "BEKS": "BEKS.JK", "BGTM": "BGTM.JK",
    "BINA": "BINA.JK", "BKSW": "BKSW.JK", "BMAS": "BMAS.JK",
    "BNBA": "BNBA.JK", "BNGA": "BNGA.JK", "BNLI": "BNLI.JK",
    "BSIM": "BSIM.JK", "BTPN": "BTPN.JK", "MAYA": "MAYA.JK",
    "MCOR": "MCOR.JK", "MFIN": "MFIN.JK", "NOBU": "NOBU.JK",
    "PNBN": "PNBN.JK", "PADI": "PADI.JK", "SDRA": "SDRA.JK",
    "TRIM": "TRIM.JK", "VRNA": "VRNA.JK", "WOMF": "WOMF.JK",
    "TIFA": "TIFA.JK", "BBLD": "BBLD.JK", "HDFA": "HDFA.JK",
    "AGRS": "AGRS.JK", "INPC": "INPC.JK",
    # --- Konsumer, ritel, F&B ---
    "AISA": "AISA.JK", "ALTO": "ALTO.JK", "AMFG": "AMFG.JK",
    "BLTZ": "BLTZ.JK", "CAMP": "CAMP.JK", "CEKA": "CEKA.JK",
    "CLEO": "CLEO.JK", "DAYA": "DAYA.JK", "DLTA": "DLTA.JK",
    "FAST": "FAST.JK", "FOOD": "FOOD.JK", "GOOD": "GOOD.JK",
    "HOKI": "HOKI.JK", "IKAN": "IKAN.JK", "KEJU": "KEJU.JK",
    "KINO": "KINO.JK", "MLBI": "MLBI.JK", "MPPA": "MPPA.JK",
    "PCAR": "PCAR.JK", "PZZA": "PZZA.JK", "SKBM": "SKBM.JK",
    "STTP": "STTP.JK", "TCID": "TCID.JK", "WIIM": "WIIM.JK",
    "WINE": "WINE.JK", "CINT": "CINT.JK", "CRSN": "CRSN.JK",
    "DMND": "DMND.JK", "SKLT": "SKLT.JK",
    # --- Teknologi & digital ---
    "DCII": "DCII.JK", "DMMX": "DMMX.JK", "EDGE": "EDGE.JK",
    "ENVY": "ENVY.JK", "GLVA": "GLVA.JK", "LUCK": "LUCK.JK",
    "MLPT": "MLPT.JK", "MTDL": "MTDL.JK", "NFCX": "NFCX.JK",
    "UVCR": "UVCR.JK", "WIFI": "WIFI.JK", "WIRG": "WIRG.JK",
    "ZATA": "ZATA.JK", "BELI": "BELI.JK", "BEBS": "BEBS.JK",
    "CASH": "CASH.JK", "DIVA": "DIVA.JK", "DWGL": "DWGL.JK",
    "HADE": "HADE.JK", "IRSX": "IRSX.JK", "KREN": "KREN.JK",
    "MCAS": "MCAS.JK", "PTPS": "PTPS.JK", "TECH": "TECH.JK",
    "TOSK": "TOSK.JK", "TRUS": "TRUS.JK", "VISI": "VISI.JK",
    "WINS": "WINS.JK", "ELIT": "ELIT.JK",
    "MMIX": "MMIX.JK", "SKRN": "SKRN.JK", "TFAS": "TFAS.JK",
    # --- Properti, konstruksi, kawasan ---
    "ASRI": "ASRI.JK", "BCIP": "BCIP.JK", "BEST": "BEST.JK",
    "BIKA": "BIKA.JK", "BKDP": "BKDP.JK", "BKSL": "BKSL.JK",
    "CITY": "CITY.JK", "DILD": "DILD.JK", "DUTI": "DUTI.JK",
    "EKAD": "EKAD.JK", "ELTY": "ELTY.JK", "GMTD": "GMTD.JK",
    "GPRA": "GPRA.JK", "HOMI": "HOMI.JK", "JIHD": "JIHD.JK",
    "JKON": "JKON.JK", "KIJA": "KIJA.JK", "KPIG": "KPIG.JK",
    "LAMI": "LAMI.JK", "MBAP": "MBAP.JK", "MDRN": "MDRN.JK",
    "MKPI": "MKPI.JK", "MPRO": "MPRO.JK", "MTMH": "MTMH.JK",
    "NIRO": "NIRO.JK", "NRCA": "NRCA.JK", "OMRE": "OMRE.JK",
    "POLL": "POLL.JK", "POSA": "POSA.JK", "PPRO": "PPRO.JK",
    "RBMS": "RBMS.JK", "RDTX": "RDTX.JK", "REAL": "REAL.JK",
    "RIMO": "RIMO.JK", "RISE": "RISE.JK", "SMDM": "SMDM.JK",
    "TARA": "TARA.JK", "TOTL": "TOTL.JK", "TRUE": "TRUE.JK",
    "UANG": "UANG.JK", "WINR": "WINR.JK", "CBDK": "CBDK.JK",
    "CSIS": "CSIS.JK", "LCGP": "LCGP.JK", "PLIN": "PLIN.JK",
    # --- Manufaktur, industri, semen, baja ---
    "ALMI": "ALMI.JK", "ASGR": "ASGR.JK",
    "CTBN": "CTBN.JK", "DPNS": "DPNS.JK", "ETWA": "ETWA.JK",
    "HRTA": "HRTA.JK", "IKAI": "IKAI.JK", "INDR": "INDR.JK",
    "INRU": "INRU.JK", "JTPE": "JTPE.JK", "KBLM": "KBLM.JK",
    "KBLI": "KBLI.JK", "KOIN": "KOIN.JK", "KONI": "KONI.JK",
    "LION": "LION.JK", "LMAS": "LMAS.JK", "LPIN": "LPIN.JK",
    "MARK": "MARK.JK", "MDLN": "MDLN.JK", "NAJA": "NAJA.JK",
    "PANR": "PANR.JK", "PBRX": "PBRX.JK", "POLU": "POLU.JK",
    "SIMA": "SIMA.JK", "SIPD": "SIPD.JK", "SPMA": "SPMA.JK",
    "STAR": "STAR.JK", "TALF": "TALF.JK", "TIRA": "TIRA.JK",
    "TRST": "TRST.JK", "UNIC": "UNIC.JK", "UNIT": "UNIT.JK",
    "VOKS": "VOKS.JK", "WTON": "WTON.JK", "YPAS": "YPAS.JK",
    "PACK": "PACK.JK", "KICI": "KICI.JK", "CAKK": "CAKK.JK",
    "IGAR": "IGAR.JK", "JECC": "JECC.JK", "KIAS": "KIAS.JK",
    "LMPI": "LMPI.JK", "PICO": "PICO.JK", "SWID": "SWID.JK",
    # --- Kesehatan & farmasi ---
    "DVLA": "DVLA.JK", "IRRA": "IRRA.JK", "KLIN": "KLIN.JK",
    "MERK": "MERK.JK", "PRDA": "PRDA.JK", "PYFA": "PYFA.JK",
    "SCPI": "SCPI.JK", "SOHO": "SOHO.JK", "SRAJ": "SRAJ.JK",
    "SAME": "SAME.JK", "CARE": "CARE.JK",
    # --- Media, hiburan, periklanan ---
    "MNCN": "MNCN.JK", "BMTR": "BMTR.JK", "VIVA": "VIVA.JK",
    "FILM": "FILM.JK", "NETV": "NETV.JK", "KBLV": "KBLV.JK",
    "RAAM": "RAAM.JK", "FUTR": "FUTR.JK",
    # --- Distribusi, logistik, transportasi ---
    "ASSA": "ASSA.JK", "CARS": "CARS.JK",
    "CSAP": "CSAP.JK", "DEPO": "DEPO.JK", "GLOB": "GLOB.JK",
    "HERO": "HERO.JK", "LPPF": "LPPF.JK", "MICE": "MICE.JK",
    "RALS": "RALS.JK", "SONA": "SONA.JK", "TELE": "TELE.JK",
    "TRIO": "TRIO.JK", "VERA": "VERA.JK", "ZYRX": "ZYRX.JK",
    "AKPI": "AKPI.JK", "BLTA": "BLTA.JK", "HITS": "HITS.JK",
    "KARW": "KARW.JK", "LAJU": "LAJU.JK", "MIRA": "MIRA.JK",
    "NELY": "NELY.JK", "SAFE": "SAFE.JK", "SAPX": "SAPX.JK",
    "SHIP": "SHIP.JK", "TMAS": "TMAS.JK", "WEHA": "WEHA.JK",
    "CABS": "CABS.JK", "HAIS": "HAIS.JK", "TRJA": "TRJA.JK",
    # --- Tambang kecil/menengah ---
    "ABMM": "ABMM.JK", "AIMS": "AIMS.JK", "ARII": "ARII.JK",
    "ARTI": "ARTI.JK", "BSSR": "BSSR.JK", "CITA": "CITA.JK",
    "DOID": "DOID.JK", "FIRE": "FIRE.JK", "GEMS": "GEMS.JK",
    "GTBO": "GTBO.JK", "HILL": "HILL.JK", "IATA": "IATA.JK",
    "KKGI": "KKGI.JK", "MYOH": "MYOH.JK", "PKPK": "PKPK.JK",
    "SMMT": "SMMT.JK", "TEBE": "TEBE.JK", "ZINC": "ZINC.JK",
    "APEX": "APEX.JK", "BICO": "BICO.JK", "CNKO": "CNKO.JK",
    "ESSA": "ESSA.JK", "HUMI": "HUMI.JK", "LEAD": "LEAD.JK",
    "RIGS": "RIGS.JK", "RUIS": "RUIS.JK", "SURE": "SURE.JK",
    "DYAN": "DYAN.JK", "NICK": "NICK.JK", "PSAB": "PSAB.JK",
    # --- Perkebunan & agri ---
    "ANDI": "ANDI.JK", "ANJT": "ANJT.JK", "BWPT": "BWPT.JK",
    "CSRA": "CSRA.JK", "GOLL": "GOLL.JK", "GZCO": "GZCO.JK",
    "JAWA": "JAWA.JK", "MAGP": "MAGP.JK", "PALM": "PALM.JK",
    "UNSP": "UNSP.JK", "WMPP": "WMPP.JK", "BISI": "BISI.JK",
    "FISH": "FISH.JK", "STAA": "STAA.JK", "TUGU": "TUGU.JK",
    "CPRO": "CPRO.JK", "WMUU": "WMUU.JK",
    # --- Infrastruktur, utilitas, jalan tol ---
    "CMNP": "CMNP.JK", "IPCC": "IPCC.JK", "IPCM": "IPCM.JK",
    "META": "META.JK", "PBID": "PBID.JK", "POWR": "POWR.JK",
    "PPRE": "PPRE.JK", "WEGE": "WEGE.JK", "TBIG": "TBIG.JK",
    "GOLD": "GOLD.JK", "CENT": "CENT.JK",
    "BALI": "BALI.JK", "BTON": "BTON.JK", "NUSA": "NUSA.JK",
    "PORT": "PORT.JK", "TAMA": "TAMA.JK", "HGII": "HGII.JK",
    # --- Jasa, perdagangan, lainnya ---
    "APII": "APII.JK", "ASHA": "ASHA.JK", "BRAM": "BRAM.JK",
    "CASA": "CASA.JK", "CCSI": "CCSI.JK", "CLAY": "CLAY.JK",
    "CMRY": "CMRY.JK", "CPRI": "CPRI.JK", "CTTH": "CTTH.JK",
    "DADA": "DADA.JK", "DGNS": "DGNS.JK", "DPUM": "DPUM.JK",
    "EAST": "EAST.JK", "ENZO": "ENZO.JK", "ESIP": "ESIP.JK",
    "ESTI": "ESTI.JK", "FITT": "FITT.JK", "FMII": "FMII.JK",
    "FORU": "FORU.JK", "GEMA": "GEMA.JK", "GDYR": "GDYR.JK",
    "GOLF": "GOLF.JK", "GULA": "GULA.JK", "HATM": "HATM.JK",
    "ICON": "ICON.JK", "IKBI": "IKBI.JK", "INAI": "INAI.JK",
    "JAST": "JAST.JK", "JAYA": "JAYA.JK", "JGLE": "JGLE.JK",
    "KEEN": "KEEN.JK", "KIDS": "KIDS.JK", "KLAS": "KLAS.JK",
    "KMTR": "KMTR.JK", "KOKA": "KOKA.JK", "KPAS": "KPAS.JK",
    "LABS": "LABS.JK", "LAND": "LAND.JK", "LIFE": "LIFE.JK",
    "LPGI": "LPGI.JK", "MABA": "MABA.JK", "MAMI": "MAMI.JK",
    "MAPB": "MAPB.JK", "MASA": "MASA.JK", "MFMI": "MFMI.JK",
    "MGRO": "MGRO.JK", "MKNT": "MKNT.JK", "MLIA": "MLIA.JK",
    "MMLP": "MMLP.JK", "MOLI": "MOLI.JK", "MORA": "MORA.JK",
    "MPOW": "MPOW.JK", "MSKY": "MSKY.JK", "MTRA": "MTRA.JK",
    "MTSM": "MTSM.JK", "MUTU": "MUTU.JK", "MYRX": "MYRX.JK",
    "NATO": "NATO.JK", "NINE": "NINE.JK", "NPGF": "NPGF.JK",
    "NZIA": "NZIA.JK", "OBMD": "OBMD.JK", "OKAS": "OKAS.JK",
    "OLIV": "OLIV.JK", "OMED": "OMED.JK", "OPMS": "OPMS.JK",
    "PARK": "PARK.JK", "PDES": "PDES.JK", "PEGE": "PEGE.JK",
    "PEHA": "PEHA.JK", "PEMG": "PEMG.JK", "PGJO": "PGJO.JK",
    "PGLI": "PGLI.JK", "PJAA": "PJAA.JK", "PLAN": "PLAN.JK",
    "PMJS": "PMJS.JK", "PMMP": "PMMP.JK", "PNBS": "PNBS.JK",
    "PNSE": "PNSE.JK", "POLA": "POLA.JK", "PRAY": "PRAY.JK",
    "PRIM": "PRIM.JK", "PSDN": "PSDN.JK", "PSKT": "PSKT.JK",
    "PTSP": "PTSP.JK", "PURA": "PURA.JK", "PUTI": "PUTI.JK",
    "RAFI": "RAFI.JK", "RANC": "RANC.JK", "RELI": "RELI.JK",
    "RICY": "RICY.JK", "RMKE": "RMKE.JK", "ROCK": "ROCK.JK",
    "ROSS": "ROSS.JK", "RSCH": "RSCH.JK", "RUNS": "RUNS.JK",
    "SATU": "SATU.JK", "SBAT": "SBAT.JK", "SBMA": "SBMA.JK",
    "SCNP": "SCNP.JK", "SDMU": "SDMU.JK", "SDPC": "SDPC.JK",
    "SFAN": "SFAN.JK", "SHID": "SHID.JK", "SICO": "SICO.JK",
    "SIKL": "SIKL.JK", "SLIS": "SLIS.JK", "SMAR": "SMAR.JK",
    "SMGA": "SMGA.JK", "SMIL": "SMIL.JK", "SMKM": "SMKM.JK",
    "SMLE": "SMLE.JK", "SOLA": "SOLA.JK", "SQBB": "SQBB.JK",
    "SRTG": "SRTG.JK", "STRK": "STRK.JK", "SUPR": "SUPR.JK",
    "SWAT": "SWAT.JK", "TAMU": "TAMU.JK", "TBMS": "TBMS.JK",
    "TGKA": "TGKA.JK", "TNCA": "TNCA.JK", "TOYS": "TOYS.JK",
    "TRIL": "TRIL.JK", "TRIN": "TRIN.JK", "TRIS": "TRIS.JK",
    "TYRE": "TYRE.JK", "UCID": "UCID.JK", "UFOE": "UFOE.JK",
    "UNIQ": "UNIQ.JK", "VAST": "VAST.JK", "VICI": "VICI.JK",
    "WAPO": "WAPO.JK", "WGSH": "WGSH.JK", "WICO": "WICO.JK",
    "WOWS": "WOWS.JK", "YELO": "YELO.JK", "YULE": "YULE.JK",
    "BOBA": "BOBA.JK", "RMUI": "RMUI.JK", "MGLN": "MGLN.JK",
    "TFCO": "TFCO.JK", "ASPI": "ASPI.JK",
    # v8.12.64 — Full-board IDX: sisa emiten BEI (micro-cap dll)
    # dari daftar resmi IDX (957 emiten). Invalid/delisted ter-drop
    # otomatis karena snapshot Yahoo-nya None.
    "ABBA": "ABBA.JK", "ABDA": "ABDA.JK", "ACRO": "ACRO.JK",
    "ACST": "ACST.JK", "ADCP": "ADCP.JK", "ADES": "ADES.JK",
    "ADMF": "ADMF.JK", "ADMG": "ADMG.JK", "AEGS": "AEGS.JK",
    "AGAR": "AGAR.JK", "AGII": "AGII.JK", "AGRO": "AGRO.JK",
    "AHAP": "AHAP.JK", "AKKU": "AKKU.JK", "AKSI": "AKSI.JK",
    "ALDO": "ALDO.JK", "ALII": "ALII.JK", "ALKA": "ALKA.JK",
    "AMAG": "AMAG.JK", "AMAN": "AMAN.JK", "AMIN": "AMIN.JK",
    "AMMS": "AMMS.JK", "AMOR": "AMOR.JK", "APIC": "APIC.JK",
    "APLI": "APLI.JK", "APLN": "APLN.JK", "AREA": "AREA.JK",
    "ARGO": "ARGO.JK", "ARKA": "ARKA.JK", "ARKO": "ARKO.JK",
    "ARMY": "ARMY.JK", "ARTA": "ARTA.JK", "ASBI": "ASBI.JK",
    "ASDM": "ASDM.JK", "ASJT": "ASJT.JK", "ASLC": "ASLC.JK",
    "ASLI": "ASLI.JK", "ASMI": "ASMI.JK", "ASPR": "ASPR.JK",
    "ASRM": "ASRM.JK", "ATAP": "ATAP.JK", "ATIC": "ATIC.JK",
    "ATLA": "ATLA.JK", "AUTO": "AUTO.JK", "AVIA": "AVIA.JK",
    "AWAN": "AWAN.JK", "AXIO": "AXIO.JK", "AYAM": "AYAM.JK",
    "AYLS": "AYLS.JK", "BABY": "BABY.JK", "BAIK": "BAIK.JK",
    "BAJA": "BAJA.JK", "BAPA": "BAPA.JK", "BAPI": "BAPI.JK",
    "BATA": "BATA.JK", "BATR": "BATR.JK", "BAUT": "BAUT.JK",
    "BAYU": "BAYU.JK", "BBKP": "BBKP.JK", "BBMD": "BBMD.JK",
    "BBRM": "BBRM.JK", "BBSS": "BBSS.JK", "BCIC": "BCIC.JK",
    "BDKR": "BDKR.JK", "BEEF": "BEEF.JK", "BEER": "BEER.JK",
    "BELL": "BELL.JK", "BESS": "BESS.JK", "BGTG": "BGTG.JK",
    "BHAT": "BHAT.JK", "BHIT": "BHIT.JK", "BIKE": "BIKE.JK",
    "BIMA": "BIMA.JK", "BINO": "BINO.JK", "BIPP": "BIPP.JK",
    "BLES": "BLES.JK", "BLOG": "BLOG.JK", "BLUE": "BLUE.JK",
    "BMBL": "BMBL.JK", "BMHS": "BMHS.JK", "BMSR": "BMSR.JK",
    "BNII": "BNII.JK", "BOAT": "BOAT.JK", "BOGA": "BOGA.JK",
    "BOLA": "BOLA.JK", "BOLT": "BOLT.JK", "BOSS": "BOSS.JK",
    "BPFI": "BPFI.JK", "BPII": "BPII.JK", "BPTR": "BPTR.JK",
    "BRNA": "BRNA.JK", "BRRC": "BRRC.JK", "BSBK": "BSBK.JK",
    "BSML": "BSML.JK", "BSWD": "BSWD.JK", "BTEK": "BTEK.JK",
    "BTEL": "BTEL.JK", "BUAH": "BUAH.JK", "BUDI": "BUDI.JK",
    "BUKK": "BUKK.JK", "BVIC": "BVIC.JK", "CANI": "CANI.JK",
    "CASS": "CASS.JK", "CBMF": "CBMF.JK", "CBPE": "CBPE.JK",
    "CBUT": "CBUT.JK", "CFIN": "CFIN.JK", "CGAS": "CGAS.JK",
    "CHEK": "CHEK.JK", "CHEM": "CHEM.JK", "CHIP": "CHIP.JK",
    "CLPI": "CLPI.JK", "CMNT": "CMNT.JK", "CNMA": "CNMA.JK",
    "CNTX": "CNTX.JK", "COAL": "COAL.JK", "COIN": "COIN.JK",
    "COWL": "COWL.JK", "CRAB": "CRAB.JK", "CSMI": "CSMI.JK",
    "CYBR": "CYBR.JK", "DAAZ": "DAAZ.JK", "DART": "DART.JK",
    "DATA": "DATA.JK", "DEAL": "DEAL.JK", "DEFI": "DEFI.JK",
    "DEWI": "DEWI.JK", "DFAM": "DFAM.JK", "DGIK": "DGIK.JK",
    "DGWG": "DGWG.JK", "DIGI": "DIGI.JK", "DKFT": "DKFT.JK",
    "DKHH": "DKHH.JK", "DMAS": "DMAS.JK", "DNAR": "DNAR.JK",
    "DNET": "DNET.JK", "DOSS": "DOSS.JK", "DRMA": "DRMA.JK",
    "DSFI": "DSFI.JK", "DUCK": "DUCK.JK", "ECII": "ECII.JK",
    "ELPI": "ELPI.JK", "EMDE": "EMDE.JK", "ENAK": "ENAK.JK",
    "EPAC": "EPAC.JK", "EPMT": "EPMT.JK", "ERAL": "ERAL.JK",
    "ERTX": "ERTX.JK", "ESTA": "ESTA.JK", "EURO": "EURO.JK",
    "FAPA": "FAPA.JK", "FIMP": "FIMP.JK", "FLMC": "FLMC.JK",
    "FOLK": "FOLK.JK", "FPNI": "FPNI.JK", "FUJI": "FUJI.JK",
    "FWCT": "FWCT.JK", "GAMA": "GAMA.JK", "GDST": "GDST.JK",
    "GGRP": "GGRP.JK", "GHON": "GHON.JK", "GMFI": "GMFI.JK",
    "GPSO": "GPSO.JK", "GRIA": "GRIA.JK", "GRPH": "GRPH.JK",
    "GRPM": "GRPM.JK", "GSMF": "GSMF.JK", "GTRA": "GTRA.JK",
    "GUNA": "GUNA.JK", "GWSA": "GWSA.JK", "HAJJ": "HAJJ.JK",
    "HALO": "HALO.JK", "HBAT": "HBAT.JK", "HDIT": "HDIT.JK",
    "HELI": "HELI.JK", "HKMU": "HKMU.JK", "HOME": "HOME.JK",
    "HOPE": "HOPE.JK", "HOTL": "HOTL.JK", "HRME": "HRME.JK",
    "HYGN": "HYGN.JK", "IBFN": "IBFN.JK", "IBOS": "IBOS.JK",
    "IBST": "IBST.JK", "IDEA": "IDEA.JK", "IDPR": "IDPR.JK",
    "IFII": "IFII.JK", "IFSH": "IFSH.JK", "IIKP": "IIKP.JK",
    "IKPM": "IKPM.JK", "IMJS": "IMJS.JK", "INCF": "INCF.JK",
    "INCI": "INCI.JK", "INDO": "INDO.JK", "INDS": "INDS.JK",
    "INDX": "INDX.JK", "INOV": "INOV.JK", "INPP": "INPP.JK",
    "INPS": "INPS.JK", "INTA": "INTA.JK", "INTD": "INTD.JK",
    "IOTF": "IOTF.JK", "IPAC": "IPAC.JK", "IPOL": "IPOL.JK",
    "IPPE": "IPPE.JK", "IPTV": "IPTV.JK", "ISAP": "ISAP.JK",
    "ISEA": "ISEA.JK", "ITIC": "ITIC.JK", "ITMA": "ITMA.JK",
    "JARR": "JARR.JK", "JATI": "JATI.JK", "JMAS": "JMAS.JK",
    "JRPT": "JRPT.JK", "JSKY": "JSKY.JK", "JSPT": "JSPT.JK",
    "KAQI": "KAQI.JK", "KAYU": "KAYU.JK", "KBAG": "KBAG.JK",
    "KBRI": "KBRI.JK", "KDSI": "KDSI.JK", "KDTN": "KDTN.JK",
    "KING": "KING.JK", "KIOS": "KIOS.JK", "KJEN": "KJEN.JK",
    "KKES": "KKES.JK", "KMDS": "KMDS.JK", "KOBX": "KOBX.JK",
    "KOCI": "KOCI.JK", "KOPI": "KOPI.JK", "KRYA": "KRYA.JK",
    "KSIX": "KSIX.JK", "KUAS": "KUAS.JK", "LABA": "LABA.JK",
    "LAPD": "LAPD.JK", "LCKM": "LCKM.JK", "LFLO": "LFLO.JK",
    "LIVE": "LIVE.JK", "LMAX": "LMAX.JK", "LMSH": "LMSH.JK",
    "LOPI": "LOPI.JK", "LPCK": "LPCK.JK", "LPLI": "LPLI.JK",
    "LPPS": "LPPS.JK", "LRNA": "LRNA.JK", "LTLS": "LTLS.JK",
    "LUCY": "LUCY.JK", "MAHA": "MAHA.JK", "MANG": "MANG.JK",
    "MARI": "MARI.JK", "MASB": "MASB.JK", "MAXI": "MAXI.JK",
    "MBTO": "MBTO.JK", "MCOL": "MCOL.JK", "MDIY": "MDIY.JK",
    "MDKI": "MDKI.JK", "MDLA": "MDLA.JK", "MEDS": "MEDS.JK",
    "MEJA": "MEJA.JK", "MENN": "MENN.JK", "MERI": "MERI.JK",
    "MGLV": "MGLV.JK", "MGNA": "MGNA.JK", "MHKI": "MHKI.JK",
    "MINE": "MINE.JK", "MITI": "MITI.JK", "MKAP": "MKAP.JK",
    "MKTR": "MKTR.JK", "MLPL": "MLPL.JK", "MPIX": "MPIX.JK",
    "MPXL": "MPXL.JK", "MRAT": "MRAT.JK", "MREI": "MREI.JK",
    "MSIE": "MSIE.JK", "MSJA": "MSJA.JK", "MSTI": "MSTI.JK",
    "MTFN": "MTFN.JK", "MTLA": "MTLA.JK", "MTPS": "MTPS.JK",
    "MTWI": "MTWI.JK", "MYTX": "MYTX.JK", "NAIK": "NAIK.JK",
    "NANO": "NANO.JK", "NASA": "NASA.JK", "NASI": "NASI.JK",
    "NAYZ": "NAYZ.JK", "NEST": "NEST.JK", "NICE": "NICE.JK",
    "NICL": "NICL.JK", "NIKL": "NIKL.JK", "NISP": "NISP.JK",
    "NSSS": "NSSS.JK", "NTBK": "NTBK.JK", "OBAT": "OBAT.JK",
    "OCAP": "OCAP.JK", "OILS": "OILS.JK", "PADA": "PADA.JK",
    "PAMG": "PAMG.JK", "PANS": "PANS.JK", "PART": "PART.JK",
    "PBSA": "PBSA.JK", "PDPP": "PDPP.JK", "PEVE": "PEVE.JK",
    "PGUN": "PGUN.JK", "PIPA": "PIPA.JK", "PJHB": "PJHB.JK",
    "PLAS": "PLAS.JK", "PMUI": "PMUI.JK", "PNGO": "PNGO.JK",
    "PNIN": "PNIN.JK", "PNLF": "PNLF.JK", "POLI": "POLI.JK",
    "POOL": "POOL.JK", "PPGL": "PPGL.JK", "PPRI": "PPRI.JK",
    "PSAT": "PSAT.JK", "PSGO": "PSGO.JK", "PTDU": "PTDU.JK",
    "PTIS": "PTIS.JK", "PTMP": "PTMP.JK", "PTMR": "PTMR.JK",
    "PTPW": "PTPW.JK", "PTSN": "PTSN.JK", "PUDP": "PUDP.JK",
    "PURE": "PURE.JK", "PURI": "PURI.JK", "RCCC": "RCCC.JK",
    "RELF": "RELF.JK", "RGAS": "RGAS.JK", "RLCO": "RLCO.JK",
    "RMKO": "RMKO.JK", "RODA": "RODA.JK", "RONY": "RONY.JK",
    "RSGK": "RSGK.JK", "SAGE": "SAGE.JK", "SAMF": "SAMF.JK",
    "SCCO": "SCCO.JK", "SEMA": "SEMA.JK", "SKYB": "SKYB.JK",
    "SMBR": "SMBR.JK", "SMKL": "SMKL.JK", "SMMA": "SMMA.JK",
    "SMRU": "SMRU.JK", "SNLK": "SNLK.JK", "SOFA": "SOFA.JK",
    "SOSS": "SOSS.JK", "SOTS": "SOTS.JK", "SOUL": "SOUL.JK",
    "SPRE": "SPRE.JK", "SPTO": "SPTO.JK", "SQMI": "SQMI.JK",
    "SRSN": "SRSN.JK", "SSIA": "SSIA.JK", "SSTM": "SSTM.JK",
    "SUGI": "SUGI.JK", "SULI": "SULI.JK", "SUNI": "SUNI.JK",
    "SUPA": "SUPA.JK", "SURI": "SURI.JK", "TAXI": "TAXI.JK",
    "TAYS": "TAYS.JK", "TCPI": "TCPI.JK", "TDPM": "TDPM.JK",
    "TGRA": "TGRA.JK", "TGUK": "TGUK.JK", "TIRT": "TIRT.JK",
    "TLDN": "TLDN.JK", "TMPO": "TMPO.JK", "TOOL": "TOOL.JK",
    "TOPS": "TOPS.JK", "TOTO": "TOTO.JK", "TPMA": "TPMA.JK",
    "TRAM": "TRAM.JK", "TRGU": "TRGU.JK", "TRON": "TRON.JK",
    "TRUK": "TRUK.JK", "UDNG": "UDNG.JK", "UNTD": "UNTD.JK",
    "URBN": "URBN.JK", "VERN": "VERN.JK", "VICO": "VICO.JK",
    "VINS": "VINS.JK", "VTNY": "VTNY.JK", "WIDI": "WIDI.JK",
    "WOOD": "WOOD.JK", "YOII": "YOII.JK", "YUPI": "YUPI.JK",
    "ZBRA": "ZBRA.JK", "ZONE": "ZONE.JK",

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
    "1m":  {"binance": "1m",  "yahoo_range": "1d",  "yahoo_interval": "1m",  "limit": 250},
    "3m":  {"binance": "3m",  "yahoo_range": "1d",  "yahoo_interval": "5m",  "limit": 250},
    "5m":  {"binance": "5m",  "yahoo_range": "1d",  "yahoo_interval": "5m",  "limit": 250},
    "15m": {"binance": "15m", "yahoo_range": "5d",  "yahoo_interval": "15m", "limit": 250},
    "30m": {"binance": "30m", "yahoo_range": "5d",  "yahoo_interval": "30m", "limit": 250},
    "1h":  {"binance": "1h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 250},
    "3h":  {"binance": "2h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 250},
    "6h":  {"binance": "6h",  "yahoo_range": "3mo", "yahoo_interval": "1d",  "limit": 250},
    "12h": {"binance": "12h", "yahoo_range": "3mo", "yahoo_interval": "1d",  "limit": 250},
    "18h": {"binance": "12h", "yahoo_range": "6mo", "yahoo_interval": "1d",  "limit": 250},
    "24h": {"binance": "1d",  "yahoo_range": "6mo", "yahoo_interval": "1d",  "limit": 250},
    "7d":  {"binance": "1d",  "yahoo_range": "1y",  "yahoo_interval": "1wk", "limit": 250},
    "14d": {"binance": "1d",  "yahoo_range": "2y",  "yahoo_interval": "1wk", "limit": 250},
    "30d": {"binance": "1d",  "yahoo_range": "5y",  "yahoo_interval": "1mo", "limit": 250},
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
    yh = STOCK_US_YAHOO_MAP.get(symbol.upper()) or STOCK_US_YAHOO_MAP_EXTRA.get(symbol.upper())
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
            params={"symbol": pair, "granularity": granularity, "limit": str(min(limit, 250))},
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


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 10.0,
    attempts: int = 3,
) -> httpx.Response:
    """v10.2.13 — GET dengan retry/backoff khusus throttle Binance.

    418 = IP ban sementara (response membawa header Retry-After);
    429 = rate limit weight. Keduanya transient → coba ulang dengan
    backoff 0.5s → 1.5s (atau Retry-After, maks 2s). Kegagalan akhir
    tetap melempar HTTPStatusError sehingga pemanggil jatuh ke fallback
    provider yang sudah ada (Bitget/OKX) — perilaku lama terjaga.
    """
    delay = 0.5
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            r = await client.get(url, params=params, timeout=timeout)
            if r.status_code in (418, 429):
                if attempt < attempts - 1:
                    wait = delay
                    try:
                        ra = r.headers.get("Retry-After")
                        if ra:
                            wait = min(float(ra), 2.0)
                    except Exception:
                        pass
                    logger.warning("binance throttle %s (attempt %d/%d) — retry dalam %.1fs",
                                   r.status_code, attempt + 1, attempts, wait)
                    await asyncio.sleep(wait)
                    delay *= 3
                    continue
                # Percobaan terakhir tetap throttle → lempar supaya
                # fallback provider mengambil alih.
                r.raise_for_status()
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError:
            raise
        except Exception as e:  # jaringan/DNS/dll — langsung ke fallback
            last_exc = e
            raise
    assert last_exc is not None
    raise last_exc


async def _fetch_binance_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    # v8.1.1 — On-demand lookup: if the symbol isn't in our curated map,
    # try the naive `${SYMBOL}USDT` pair name. Binance's public API is
    # perfectly happy to serve any listed pair, so this lets users find
    # brand-new listings (MOODENG, POPCAT, etc.) without a code update.
    pair = CRYPTO_BINANCE_MAP.get(symbol) or f"{symbol.upper()}USDT"
    try:
        r = await _get_with_retry(
            client,
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": pair, "interval": interval, "limit": limit},
            timeout=10.0,
        )
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
        r = await _get_with_retry(
            client,
            f"{BINANCE_BASE}/api/v3/ticker/24hr",
            params={"symbol": pair},
            timeout=8.0,
        )
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
            # v10.2.13 — Route traffic upstream lewat ASI_PROXY_URL (relay
            # IP keluar yang sama seperti asi_bot/exchanges.py & server.py).
            # Tanpa ini, IP server langsung kena 418/451 Binance saat
            # beban scanner+panic-guard naik → dashboard/grafik kehilangan
            # data. Bila env tidak diset → None → koneksi langsung
            # (perilaku lama, tidak berubah).
            proxy = os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY") or None
            _HTTP_CLIENT = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(
                    max_keepalive_connections=32,
                    max_connections=64,
                    keepalive_expiry=30.0,
                ),
                http2=True,
                proxy=proxy,
                headers={"User-Agent": "Mozilla/5.0 AITradePro/8"},
            )
            if proxy:
                logger.info("market_data: pooled http client via ASI_PROXY_URL relay")
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
    # v9.1.6 — Search-only US universe (NASDAQ Trader resmi + S&P
    # 500/400/600 superset) tersedia untuk fetch on-demand.
    if not yahoo_sym and market in ("stock_us", "world_stocks"):
        yahoo_sym = STOCK_US_YAHOO_MAP_EXTRA.get(symbol)
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
    # v9.2.4 — Boundary-aware: cache dibatalkan begitu candle interval
    # saat ini berganti (mirror fix dashboard di server.py). Sinyal
    # dihitung dari candle tutup, jadi menyajikan candle set lama setelah
    # penutupan candle = desync dashboard vs detail.
    _INTERVAL_SEC = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800,
                     "60m": 3600, "90m": 5400, "1h": 3600, "1d": 86400,
                     "5d": 432000, "1wk": 604800, "1mo": 2592000}
    _sec = _INTERVAL_SEC.get(interval, 3600)
    _boundary = int(time.time()) // _sec * _sec
    cache_key = (yahoo_sym, range_, interval)
    now = time.monotonic()
    cached = _YAHOO_CHART_CACHE.get(cache_key)
    if cached is not None:
        ts, payload, cb = cached
        if cb == _boundary and now - ts < _YAHOO_CHART_TTL_SEC:
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
        _YAHOO_CHART_CACHE[cache_key] = (now, payload, _boundary)
        # Opportunistic cache eviction — keep the dict from growing unbounded.
        if len(_YAHOO_CHART_CACHE) > _YAHOO_CHART_CACHE_MAX:
            _yahoo_cache_evict(now)
    return payload


# v7.0.8 — module-level cache (bounded, opportunistic eviction).
# v9.2.4 — entri: (monotonic_ts, payload, candle_boundary_epoch)
_YAHOO_CHART_TTL_SEC = 60.0
_YAHOO_CHART_CACHE_MAX = 512
_YAHOO_CHART_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any], int]] = {}


def _yahoo_cache_evict(now: float) -> None:
    """Drop entries older than TTL; if still too large, drop the oldest half."""
    dead = [k for k, (ts, _p, _b) in _YAHOO_CHART_CACHE.items() if now - ts >= _YAHOO_CHART_TTL_SEC]
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


# ============================================================
# v9.1.6 — US search-only universe (NASDAQ Trader resmi +
# S&P 500/400/600 superset). Search-only: TIDAK ikut dashboard
# full=true agar tidak membebani Yahoo batch fetch.
# ============================================================
STOCK_US_YAHOO_MAP_EXTRA: dict[str, str] = {
    "AAC": "AAC", "AACG": "AACG", "AACI": "AACI", "AACO": "AACO", "AACP": "AACP", "AADX": "AADX",
    "AAME": "AAME", "AAMI": "AAMI", "AAOI": "AAOI", "AAON": "AAON", "AAP": "AAP", "AAPG": "AAPG",
    "AARD": "AARD", "AAT": "AAT", "AAUC": "AAUC", "ABAT": "ABAT", "ABCB": "ABCB", "ABCL": "ABCL",
    "ABEO": "ABEO", "ABEV": "ABEV", "ABG": "ABG", "ABLV": "ABLV", "ABM": "ABM", "ABOS": "ABOS",
    "ABR": "ABR", "ABSI": "ABSI", "ABTC": "ABTC", "ABTS": "ABTS", "ABUS": "ABUS", "ABVC": "ABVC",
    "ABVX": "ABVX", "ABX": "ABX", "ACA": "ACA", "ACAA": "ACAA", "ACAD": "ACAD", "ACB": "ACB",
    "ACCL": "ACCL", "ACCO": "ACCO", "ACCS": "ACCS", "ACDC": "ACDC", "ACEL": "ACEL", "ACET": "ACET",
    "ACFN": "ACFN", "ACGC": "ACGC", "ACGL": "ACGL", "ACH": "ACH", "ACHC": "ACHC", "ACHR": "ACHR",
    "ACHV": "ACHV", "ACI": "ACI", "ACIC": "ACIC", "ACIU": "ACIU", "ACIW": "ACIW", "ACLS": "ACLS",
    "ACM": "ACM", "ACMR": "ACMR", "ACN": "ACN", "ACNB": "ACNB", "ACNT": "ACNT", "ACOG": "ACOG",
    "ACON": "ACON", "ACR": "ACR", "ACRE": "ACRE", "ACRS": "ACRS", "ACRV": "ACRV", "ACT": "ACT",
    "ACTG": "ACTG", "ACTU": "ACTU", "ACU": "ACU", "ACVA": "ACVA", "ACXP": "ACXP", "AD": "AD",
    "ADAC": "ADAC", "ADAG": "ADAG", "ADAM": "ADAM", "ADBT": "ADBT", "ADC": "ADC", "ADCT": "ADCT",
    "ADEA": "ADEA", "ADGM": "ADGM", "ADIG": "ADIG", "ADIL": "ADIL", "ADM": "ADM", "ADMA": "ADMA",
    "ADNT": "ADNT", "ADPT": "ADPT", "ADSE": "ADSE", "ADSK": "ADSK", "ADT": "ADT", "ADTN": "ADTN",
    "ADUR": "ADUR", "ADUS": "ADUS", "ADV": "ADV", "ADVB": "ADVB", "ADXN": "ADXN", "AEAQ": "AEAQ",
    "AEBI": "AEBI", "AEC": "AEC", "AEE": "AEE", "AEG": "AEG", "AEHL": "AEHL", "AEHR": "AEHR",
    "AEI": "AEI", "AEIS": "AEIS", "AEM": "AEM", "AEMD": "AEMD", "AENT": "AENT", "AEO": "AEO",
    "AEON": "AEON", "AER": "AER", "AERO": "AERO", "AERT": "AERT", "AES": "AES", "AESI": "AESI",
    "AESP": "AESP", "AEVA": "AEVA", "AEXA": "AEXA", "AEYE": "AEYE", "AFCG": "AFCG", "AFG": "AFG",
    "AFJK": "AFJK", "AFRI": "AFRI", "AFRM": "AFRM", "AFYA": "AFYA", "AG": "AG", "AGBK": "AGBK",
    "AGCC": "AGCC", "AGCO": "AGCO", "AGEN": "AGEN", "AGI": "AGI", "AGIG": "AGIG", "AGIO": "AGIO",
    "AGL": "AGL", "AGM": "AGM", "AGM-A": "AGM-A", "AGMB": "AGMB", "AGMH": "AGMH", "AGNC": "AGNC",
    "AGNT": "AGNT", "AGO": "AGO", "AGPU": "AGPU", "AGRO": "AGRO", "AGRZ": "AGRZ", "AGX": "AGX",
    "AGYS": "AGYS", "AHCO": "AHCO", "AHG": "AHG", "AHMA": "AHMA", "AHR": "AHR", "AHRT": "AHRT",
    "AHT": "AHT", "AI": "AI", "AIAI": "AIAI", "AIB": "AIB", "AIBZ": "AIBZ", "AIDX": "AIDX",
    "AIFA": "AIFA", "AIFC": "AIFC", "AIFF": "AIFF", "AIFU": "AIFU", "AII": "AII", "AIIA": "AIIA",
    "AIIO": "AIIO", "AIIR": "AIIR", "AIM": "AIM", "AIMD": "AIMD", "AIN": "AIN", "AIOS": "AIOS",
    "AIOT": "AIOT", "AIP": "AIP", "AIR": "AIR", "AIRE": "AIRE", "AIRG": "AIRG", "AIRI": "AIRI",
    "AIRJ": "AIRJ", "AIRO": "AIRO", "AIRS": "AIRS", "AIRT": "AIRT", "AISP": "AISP", "AIT": "AIT",
    "AIV": "AIV", "AIXC": "AIXC", "AIXI": "AIXI", "AIZ": "AIZ", "AKA": "AKA", "AKAM": "AKAM",
    "AKAN": "AKAN", "AKBA": "AKBA", "AKO-A": "AKO-A", "AKO-B": "AKO-B", "AKR": "AKR", "AKTS": "AKTS",
    "AKTX": "AKTX", "ALAB": "ALAB", "ALAR": "ALAR", "ALC": "ALC", "ALCO": "ALCO", "ALDF": "ALDF",
    "ALDX": "ALDX", "ALEC": "ALEC", "ALF": "ALF", "ALG": "ALG", "ALGM": "ALGM", "ALGN": "ALGN",
    "ALGS": "ALGS", "ALGT": "ALGT", "ALH": "ALH", "ALHC": "ALHC", "ALIS": "ALIS", "ALIT": "ALIT",
    "ALKS": "ALKS", "ALKT": "ALKT", "ALLE": "ALLE", "ALLO": "ALLO", "ALLR": "ALLR", "ALLT": "ALLT",
    "ALLY": "ALLY", "ALM": "ALM", "ALMR": "ALMR", "ALMS": "ALMS", "ALMU": "ALMU", "ALNT": "ALNT",
    "ALOV": "ALOV", "ALOY": "ALOY", "ALP": "ALP", "ALPS": "ALPS", "ALPX": "ALPX", "ALRM": "ALRM",
    "ALRS": "ALRS", "ALSN": "ALSN", "ALT": "ALT", "ALTG": "ALTG", "ALTI": "ALTI", "ALTO": "ALTO",
    "ALUB": "ALUB", "ALV": "ALV", "ALVO": "ALVO", "ALX": "ALX", "ALXO": "ALXO", "ALZN": "ALZN",
    "AM": "AM", "AMAC": "AMAC", "AMAL": "AMAL", "AMAN": "AMAN", "AMBA": "AMBA", "AMBO": "AMBO",
    "AMBP": "AMBP", "AMBQ": "AMBQ", "AMBR": "AMBR", "AMCI": "AMCI", "AMCR": "AMCR", "AMCX": "AMCX",
    "AME": "AME", "AMG": "AMG", "AMH": "AMH", "AMIX": "AMIX", "AMKR": "AMKR", "AMLX": "AMLX",
    "AMN": "AMN", "AMOD": "AMOD", "AMPG": "AMPG", "AMPH": "AMPH", "AMPL": "AMPL", "AMPX": "AMPX",
    "AMPY": "AMPY", "AMR": "AMR", "AMRC": "AMRC", "AMRN": "AMRN", "AMRX": "AMRX", "AMRZ": "AMRZ",
    "AMS": "AMS", "AMSC": "AMSC", "AMSF": "AMSF", "AMSS": "AMSS", "AMST": "AMST", "AMTB": "AMTB",
    "AMTD": "AMTD", "AMTM": "AMTM", "AMTX": "AMTX", "AMWL": "AMWL", "AMZE": "AMZE", "AN": "AN",
    "ANAB": "ANAB", "ANDE": "ANDE", "ANDG": "ANDG", "ANF": "ANF", "ANGH": "ANGH", "ANGI": "ANGI",
    "ANGO": "ANGO", "ANGX": "ANGX", "ANIK": "ANIK", "ANIP": "ANIP", "ANIX": "ANIX", "ANL": "ANL",
    "ANNA": "ANNA", "ANNX": "ANNX", "ANPA": "ANPA", "ANRO": "ANRO", "ANTA": "ANTA", "ANTX": "ANTX",
    "ANVS": "ANVS", "AOMR": "AOMR", "AORT": "AORT", "AOS": "AOS", "AOSL": "AOSL", "AOUT": "AOUT",
    "AP": "AP", "APA": "APA", "APAC": "APAC", "APAM": "APAM", "APC": "APC", "APEI": "APEI",
    "APG": "APG", "APH": "APH", "API": "API", "APLD": "APLD", "APLE": "APLE", "APLM": "APLM",
    "APMC": "APMC", "APMD": "APMD", "APO": "APO", "APOG": "APOG", "APP": "APP", "APPF": "APPF",
    "APPN": "APPN", "APPS": "APPS", "APRE": "APRE", "APT": "APT", "APTV": "APTV", "APUR": "APUR",
    "APUS": "APUS", "APVO": "APVO", "APWC": "APWC", "APXT": "APXT", "APYX": "APYX", "AQB": "AQB",
    "AQMS": "AQMS", "AQN": "AQN", "AQST": "AQST", "AR": "AR", "ARAI": "ARAI", "ARAY": "ARAY",
    "ARBB": "ARBB", "ARBE": "ARBE", "ARBK": "ARBK", "ARCI": "ARCI", "ARCL": "ARCL", "ARCO": "ARCO",
    "ARCT": "ARCT", "ARDT": "ARDT", "ARDX": "ARDX", "AREC": "AREC", "ARES": "ARES", "ARGX": "ARGX",
    "ARHS": "ARHS", "ARI": "ARI", "ARIS": "ARIS", "ARKO": "ARKO", "ARKR": "ARKR", "ARL": "ARL",
    "ARLO": "ARLO", "ARMK": "ARMK", "ARMP": "ARMP", "AROC": "AROC", "AROW": "AROW", "ARQ": "ARQ",
    "ARQQ": "ARQQ", "ARQT": "ARQT", "ARR": "ARR", "ARRY": "ARRY", "ARTC": "ARTC", "ARTL": "ARTL",
    "ARTNA": "ARTNA", "ARTV": "ARTV", "ARTW": "ARTW", "ARVN": "ARVN", "ARW": "ARW", "ARWR": "ARWR",
    "ARX": "ARX", "ARXS": "ARXS", "AS": "AS", "ASA": "ASA", "ASAN": "ASAN", "ASB": "ASB",
    "ASBH": "ASBH", "ASBP": "ASBP", "ASC": "ASC", "ASH": "ASH", "ASIC": "ASIC", "ASIX": "ASIX",
    "ASLE": "ASLE", "ASM": "ASM", "ASMB": "ASMB", "ASND": "ASND", "ASO": "ASO", "ASPC": "ASPC",
    "ASPI": "ASPI", "ASPN": "ASPN", "ASPS": "ASPS", "ASR": "ASR", "ASRV": "ASRV", "ASST": "ASST",
    "ASTC": "ASTC", "ASTE": "ASTE", "ASTH": "ASTH", "ASTI": "ASTI", "ASTL": "ASTL", "ASTS": "ASTS",
    "ASUR": "ASUR", "ASX": "ASX", "ASYS": "ASYS", "ATAT": "ATAT", "ATCH": "ATCH", "ATCX": "ATCX",
    "ATEC": "ATEC", "ATEN": "ATEN", "ATER": "ATER", "ATEX": "ATEX", "ATGL": "ATGL", "ATHE": "ATHE",
    "ATHM": "ATHM", "ATHR": "ATHR", "ATI": "ATI", "ATII": "ATII", "ATKR": "ATKR", "ATLC": "ATLC",
    "ATLO": "ATLO", "ATLQ": "ATLQ", "ATLX": "ATLX", "ATMU": "ATMU", "ATNI": "ATNI", "ATNM": "ATNM",
    "ATO": "ATO", "ATOM": "ATOM", "ATOS": "ATOS", "ATPC": "ATPC", "ATR": "ATR", "ATRA": "ATRA",
    "ATRC": "ATRC", "ATRO": "ATRO", "ATS": "ATS", "ATTO": "ATTO", "ATTT": "ATTT", "ATXG": "ATXG",
    "ATYR": "ATYR", "AU": "AU", "AUB": "AUB", "AUBN": "AUBN", "AUC": "AUC", "AUDC": "AUDC",
    "AUGO": "AUGO", "AUID": "AUID", "AUNA": "AUNA", "AUPH": "AUPH", "AUR": "AUR", "AURA": "AURA",
    "AURE": "AURE", "AUST": "AUST", "AUTL": "AUTL", "AUUD": "AUUD", "AUXX": "AUXX", "AVA": "AVA",
    "AVAH": "AVAH", "AVAT": "AVAT", "AVAV": "AVAV", "AVBC": "AVBC", "AVBH": "AVBH", "AVBP": "AVBP",
    "AVD": "AVD", "AVEX": "AVEX", "AVIR": "AVIR", "AVLN": "AVLN", "AVNT": "AVNT", "AVNW": "AVNW",
    "AVO": "AVO", "AVPT": "AVPT", "AVR": "AVR", "AVT": "AVT", "AVTR": "AVTR", "AVTX": "AVTX",
    "AVX": "AVX", "AVXL": "AVXL", "AVY": "AVY", "AWI": "AWI", "AWR": "AWR", "AWRE": "AWRE",
    "AWX": "AWX", "AX": "AX", "AXG": "AXG", "AXGN": "AXGN", "AXIL": "AXIL", "AXIN": "AXIN",
    "AXON": "AXON", "AXR": "AXR", "AXS": "AXS", "AXSM": "AXSM", "AXTA": "AXTA", "AXTI": "AXTI",
    "AYA": "AYA", "AYI": "AYI", "AYTU": "AYTU", "AZ": "AZ", "AZI": "AZI", "AZIO": "AZIO",
    "AZO": "AZO", "AZTA": "AZTA", "AZTR": "AZTR", "AZUL": "AZUL", "AZZ": "AZZ", "B": "B",
    "BAC-E": "BAC-E", "BAC-L": "BAC-L", "BACC": "BACC", "BAER": "BAER", "BAFN": "BAFN", "BAH": "BAH",
    "BAK": "BAK", "BALL": "BALL", "BALY": "BALY", "BAM": "BAM", "BANC": "BANC", "BAND": "BAND",
    "BANF": "BANF", "BANL": "BANL", "BANR": "BANR", "BAOS": "BAOS", "BAP": "BAP", "BAR": "BAR",
    "BARK": "BARK", "BATL": "BATL", "BATRA": "BATRA", "BATRK": "BATRK", "BB": "BB", "BBAI": "BBAI",
    "BBAR": "BBAR", "BBCP": "BBCP", "BBD": "BBD", "BBDC": "BBDC", "BBDO": "BBDO", "BBGI": "BBGI",
    "BBIO": "BBIO", "BBLG": "BBLG", "BBN": "BBN", "BBNX": "BBNX", "BBOT": "BBOT", "BBSI": "BBSI",
    "BBT": "BBT", "BBUC": "BBUC", "BBW": "BBW", "BBWI": "BBWI", "BBY": "BBY", "BC": "BC",
    "BCAL": "BCAL", "BCAT": "BCAT", "BCAX": "BCAX", "BCBP": "BCBP", "BCC": "BCC", "BCCQ": "BCCQ",
    "BCDA": "BCDA", "BCG": "BCG", "BCH": "BCH", "BCHT": "BCHT", "BCML": "BCML", "BCO": "BCO",
    "BCPC": "BCPC", "BCRX": "BCRX", "BCS": "BCS", "BCSF": "BCSF", "BCSS": "BCSS", "BCTX": "BCTX",
    "BCX": "BCX", "BCYC": "BCYC", "BDC": "BDC", "BDCI": "BDCI", "BDJ": "BDJ", "BDL": "BDL",
    "BDMD": "BDMD", "BDN": "BDN", "BDRX": "BDRX", "BDSX": "BDSX", "BDTX": "BDTX", "BE": "BE",
    "BEAG": "BEAG", "BEAM": "BEAM", "BEAT": "BEAT", "BEBE": "BEBE", "BEEM": "BEEM", "BEEP": "BEEP",
    "BEKE": "BEKE", "BELFA": "BELFA", "BELFB": "BELFB", "BENF": "BENF", "BEPC": "BEPC", "BESS": "BESS",
    "BETA": "BETA", "BETR": "BETR", "BF-A": "BF-A", "BF-B": "BF-B", "BFC": "BFC", "BFH": "BFH",
    "BFLY": "BFLY", "BFRG": "BFRG", "BFRI": "BFRI", "BFS": "BFS", "BFST": "BFST", "BG": "BG",
    "BGC": "BGC", "BGDE": "BGDE", "BGIN": "BGIN", "BGL": "BGL", "BGLC": "BGLC", "BGM": "BGM",
    "BGMS": "BGMS", "BGR": "BGR", "BGS": "BGS", "BGSF": "BGSF", "BGSI": "BGSI", "BGT": "BGT",
    "BGY": "BGY", "BH": "BH", "BH-A": "BH-A", "BHAV": "BHAV", "BHB": "BHB", "BHC": "BHC",
    "BHE": "BHE", "BHF": "BHF", "BHK": "BHK", "BHM": "BHM", "BHR": "BHR", "BHRB": "BHRB",
    "BHST": "BHST", "BHV": "BHV", "BHVN": "BHVN", "BIAF": "BIAF", "BID": "BID", "BIII": "BIII",
    "BILI": "BILI", "BILL": "BILL", "BIO": "BIO", "BIO-B": "BIO-B", "BIOA": "BIOA", "BIOT": "BIOT",
    "BIOX": "BIOX", "BIPC": "BIPC", "BIRD": "BIRD", "BIRK": "BIRK", "BIT": "BIT", "BIVI": "BIVI",
    "BIXI": "BIXI", "BIYA": "BIYA", "BJ": "BJ", "BJDX": "BJDX", "BJRI": "BJRI", "BKD": "BKD",
    "BKE": "BKE", "BKH": "BKH", "BKHA": "BKHA", "BKKT": "BKKT", "BKR": "BKR", "BKSY": "BKSY",
    "BKT": "BKT", "BKTI": "BKTI", "BKU": "BKU", "BKV": "BKV", "BKYI": "BKYI", "BL": "BL",
    "BLBD": "BLBD", "BLCO": "BLCO", "BLDP": "BLDP", "BLDR": "BLDR", "BLFS": "BLFS", "BLIN": "BLIN",
    "BLIV": "BLIV", "BLKB": "BLKB", "BLLN": "BLLN", "BLMN": "BLMN", "BLND": "BLND", "BLNE": "BLNE",
    "BLNK": "BLNK", "BLRK": "BLRK", "BLRX": "BLRX", "BLSH": "BLSH", "BLSM": "BLSM", "BLTE": "BLTE",
    "BLUW": "BLUW", "BLW": "BLW", "BLX": "BLX", "BLZE": "BLZE", "BLZR": "BLZR", "BMA": "BMA",
    "BMBL": "BMBL", "BME": "BME", "BMEA": "BMEA", "BMEZ": "BMEZ", "BMGL": "BMGL", "BMHL": "BMHL",
    "BMI": "BMI", "BMM": "BMM", "BMN": "BMN", "BMNR": "BMNR", "BMR": "BMR", "BMRA": "BMRA",
    "BMRC": "BMRC", "BN": "BN", "BNAI": "BNAI", "BNC": "BNC", "BNED": "BNED", "BNGO": "BNGO",
    "BNKK": "BNKK", "BNL": "BNL", "BNR": "BNR", "BNT": "BNT", "BNTC": "BNTC", "BNY": "BNY",
    "BOBS": "BOBS", "BODI": "BODI", "BOE": "BOE", "BOF": "BOF", "BOH": "BOH", "BOKF": "BOKF",
    "BOLD": "BOLD", "BOLT": "BOLT", "BON": "BON", "BOOM": "BOOM", "BOOT": "BOOT", "BORR": "BORR",
    "BOSC": "BOSC", "BOT": "BOT", "BOTJ": "BOTJ", "BOW": "BOW", "BOX": "BOX", "BOXL": "BOXL",
    "BPAC": "BPAC", "BPOP": "BPOP", "BPRN": "BPRN", "BQ": "BQ", "BR": "BR", "BRAG": "BRAG",
    "BRAI": "BRAI", "BRBI": "BRBI", "BRBR": "BRBR", "BRBS": "BRBS", "BRC": "BRC", "BRCB": "BRCB",
    "BRCC": "BRCC", "BREZ": "BREZ", "BRFH": "BRFH", "BRIA": "BRIA", "BRID": "BRID", "BRKH": "BRKH",
    "BRKR": "BRKR", "BRLS": "BRLS", "BRLT": "BRLT", "BRN": "BRN", "BRNX": "BRNX", "BRO": "BRO",
    "BROS": "BROS", "BRSL": "BRSL", "BRSP": "BRSP", "BRT": "BRT", "BRTM": "BRTM", "BRTX": "BRTX",
    "BRUN": "BRUN", "BRVE": "BRVE", "BRX": "BRX", "BRZE": "BRZE", "BSAA": "BSAA", "BSAC": "BSAC",
    "BSBK": "BSBK", "BSEM": "BSEM", "BSET": "BSET", "BSIN": "BSIN", "BSP": "BSP", "BSRR": "BSRR",
    "BST": "BST", "BSTZ": "BSTZ", "BSVN": "BSVN", "BSY": "BSY", "BTBD": "BTBD", "BTBT": "BTBT",
    "BTCS": "BTCS", "BTCT": "BTCT", "BTDR": "BTDR", "BTE": "BTE", "BTG": "BTG", "BTGO": "BTGO",
    "BTI": "BTI", "BTLN": "BTLN", "BTMD": "BTMD", "BTOC": "BTOC", "BTQ": "BTQ", "BTSG": "BTSG",
    "BTT": "BTT", "BTTC": "BTTC", "BTU": "BTU", "BTX": "BTX", "BTZ": "BTZ", "BUD": "BUD",
    "BUDA": "BUDA", "BUI": "BUI", "BULL": "BULL", "BUR": "BUR", "BURU": "BURU", "BUSE": "BUSE",
    "BUUU": "BUUU", "BV": "BV", "BVC": "BVC", "BVFL": "BVFL", "BVN": "BVN", "BVS": "BVS",
    "BW": "BW", "BWA": "BWA", "BWAY": "BWAY", "BWB": "BWB", "BWEN": "BWEN", "BWFG": "BWFG",
    "BWIN": "BWIN", "BWIV": "BWIV", "BWLP": "BWLP", "BWMN": "BWMN", "BWMX": "BWMX", "BWXT": "BWXT",
    "BXBL": "BXBL", "BXC": "BXC", "BXDC": "BXDC", "BXMT": "BXMT", "BXP": "BXP", "BY": "BY",
    "BYAH": "BYAH", "BYD": "BYD", "BYFC": "BYFC", "BYND": "BYND", "BYRN": "BYRN", "BYSI": "BYSI",
    "BZ": "BZ", "BZAI": "BZAI", "BZFD": "BZFD", "BZH": "BZH", "BZUN": "BZUN", "CAAP": "CAAP",
    "CAAS": "CAAS", "CABA": "CABA", "CABO": "CABO", "CABR": "CABR", "CAC": "CAC", "CACC": "CACC",
    "CACI": "CACI", "CADL": "CADL", "CAE": "CAE", "CAES": "CAES", "CAH": "CAH", "CAI": "CAI",
    "CAII": "CAII", "CAKE": "CAKE", "CAL": "CAL", "CALC": "CALC", "CALM": "CALM", "CALX": "CALX",
    "CALY": "CALY", "CAMP": "CAMP", "CAMT": "CAMT", "CAN": "CAN", "CANF": "CANF", "CANG": "CANG",
    "CAPN": "CAPN", "CAPR": "CAPR", "CAPS": "CAPS", "CAQ": "CAQ", "CAR": "CAR", "CARE": "CARE",
    "CARG": "CARG", "CARL": "CARL", "CARR": "CARR", "CARS": "CARS", "CART": "CART", "CASH": "CASH",
    "CASS": "CASS", "CAST": "CAST", "CASY": "CASY", "CATO": "CATO", "CATX": "CATX", "CATY": "CATY",
    "CAVA": "CAVA", "CBAN": "CBAN", "CBAT": "CBAT", "CBC": "CBC", "CBFV": "CBFV", "CBIO": "CBIO",
    "CBK": "CBK", "CBL": "CBL", "CBLL": "CBLL", "CBNA": "CBNA", "CBNK": "CBNK", "CBRE": "CBRE",
    "CBRL": "CBRL", "CBRS": "CBRS", "CBSH": "CBSH", "CBT": "CBT", "CBU": "CBU", "CBUS": "CBUS",
    "CBZ": "CBZ", "CC": "CC", "CCAP": "CCAP", "CCAQ": "CCAQ", "CCBG": "CCBG", "CCC": "CCC",
    "CCCC": "CCCC", "CCCT": "CCCT", "CCEC": "CCEC", "CCEL": "CCEL", "CCEP": "CCEP", "CCG": "CCG",
    "CCHH": "CCHH", "CCII": "CCII", "CCJ": "CCJ", "CCK": "CCK", "CCLD": "CCLD", "CCM": "CCM",
    "CCNE": "CCNE", "CCO": "CCO", "CCOI": "CCOI", "CCS": "CCS", "CCSI": "CCSI", "CCTG": "CCTG",
    "CCU": "CCU", "CCXI": "CCXI", "CCZ": "CCZ", "CD": "CD", "CDE": "CDE", "CDIO": "CDIO",
    "CDLR": "CDLR", "CDLX": "CDLX", "CDNA": "CDNA", "CDNL": "CDNL", "CDP": "CDP", "CDRE": "CDRE",
    "CDRO": "CDRO", "CDT": "CDT", "CDTG": "CDTG", "CDXS": "CDXS", "CDZI": "CDZI", "CDZIP": "CDZIP",
    "CE": "CE", "CECO": "CECO", "CEG": "CEG", "CELC": "CELC", "CELH": "CELH", "CELU": "CELU",
    "CELZ": "CELZ", "CENN": "CENN", "CENT": "CENT", "CENTA": "CENTA", "CEPF": "CEPF", "CEPL": "CEPL",
    "CEPO": "CEPO", "CEPS": "CEPS", "CEPU": "CEPU", "CEPV": "CEPV", "CERS": "CERS", "CERT": "CERT",
    "CET": "CET", "CETX": "CETX", "CETY": "CETY", "CEV": "CEV", "CEVA": "CEVA", "CF": "CF",
    "CFBK": "CFBK", "CFFI": "CFFI", "CFFN": "CFFN", "CFG": "CFG", "CFR": "CFR", "CG": "CG",
    "CGAU": "CGAU", "CGC": "CGC", "CGCF": "CGCF", "CGEM": "CGEM", "CGEN": "CGEN", "CGNT": "CGNT",
    "CGNX": "CGNX", "CGON": "CGON", "CGTL": "CGTL", "CGTX": "CGTX", "CHA": "CHA", "CHAI": "CHAI",
    "CHAR": "CHAR", "CHCI": "CHCI", "CHCO": "CHCO", "CHCT": "CHCT", "CHDN": "CHDN", "CHE": "CHE",
    "CHEC": "CHEC", "CHEF": "CHEF", "CHGA": "CHGA", "CHGG": "CHGG", "CHH": "CHH", "CHKP": "CHKP",
    "CHMG": "CHMG", "CHMI": "CHMI", "CHNR": "CHNR", "CHOW": "CHOW", "CHPG": "CHPG", "CHPT": "CHPT",
    "CHR": "CHR", "CHRD": "CHRD", "CHRN": "CHRN", "CHRS": "CHRS", "CHSN": "CHSN", "CHTR": "CHTR",
    "CHYM": "CHYM", "CIA": "CIA", "CIEN": "CIEN", "CIFR": "CIFR", "CIG": "CIG", "CIG-C": "CIG-C",
    "CIGI": "CIGI", "CIGL": "CIGL", "CIIT": "CIIT", "CIM": "CIM", "CINF": "CINF", "CING": "CING",
    "CINT": "CINT", "CION": "CION", "CIRC": "CIRC", "CISO": "CISO", "CISS": "CISS", "CITR": "CITR",
    "CIVB": "CIVB", "CIX": "CIX", "CJMB": "CJMB", "CKX": "CKX", "CLAR": "CLAR", "CLB": "CLB",
    "CLBK": "CLBK", "CLBR": "CLBR", "CLBT": "CLBT", "CLDI": "CLDI", "CLDT": "CLDT", "CLDX": "CLDX",
    "CLFD": "CLFD", "CLGN": "CLGN", "CLH": "CLH", "CLIK": "CLIK", "CLIR": "CLIR", "CLLS": "CLLS",
    "CLMB": "CLMB", "CLMT": "CLMT", "CLNE": "CLNE", "CLNN": "CLNN", "CLOV": "CLOV", "CLPR": "CLPR",
    "CLPS": "CLPS", "CLPT": "CLPT", "CLRB": "CLRB", "CLRO": "CLRO", "CLS": "CLS", "CLSK": "CLSK",
    "CLST": "CLST", "CLVT": "CLVT", "CLW": "CLW", "CLWT": "CLWT", "CLYM": "CLYM", "CM": "CM",
    "CMBT": "CMBT", "CMC": "CMC", "CMCL": "CMCL", "CMCM": "CMCM", "CMCO": "CMCO", "CMCT": "CMCT",
    "CMDB": "CMDB", "CMMB": "CMMB", "CMND": "CMND", "CMP": "CMP", "CMPR": "CMPR", "CMPS": "CMPS",
    "CMPX": "CMPX", "CMRC": "CMRC", "CMRE": "CMRE", "CMS": "CMS", "CMT": "CMT", "CMTG": "CMTG",
    "CMTL": "CMTL", "CMTV": "CMTV", "CNA": "CNA", "CNCK": "CNCK", "CNDT": "CNDT", "CNET": "CNET",
    "CNEY": "CNEY", "CNF": "CNF", "CNH": "CNH", "CNI": "CNI", "CNK": "CNK", "CNL": "CNL",
    "CNM": "CNM", "CNMD": "CNMD", "CNNE": "CNNE", "CNO": "CNO", "CNOB": "CNOB", "CNP": "CNP",
    "CNQ": "CNQ", "CNR": "CNR", "CNS": "CNS", "CNSP": "CNSP", "CNSY": "CNSY", "CNTB": "CNTB",
    "CNTN": "CNTN", "CNTX": "CNTX", "CNTY": "CNTY", "CNVS": "CNVS", "CNX": "CNX", "CNXC": "CNXC",
    "CNXN": "CNXN", "CNXU": "CNXU", "COAG": "COAG", "COCH": "COCH", "COCO": "COCO", "COCP": "COCP",
    "CODA": "CODA", "CODI": "CODI", "CODX": "CODX", "COE": "COE", "COFS": "COFS", "COGT": "COGT",
    "COHN": "COHN", "COHR": "COHR", "COHU": "COHU", "COKE": "COKE", "COLA": "COLA", "COLB": "COLB",
    "COLD": "COLD", "COLL": "COLL", "COLM": "COLM", "COMP": "COMP", "CON": "CON", "COO": "COO",
    "COOK": "COOK", "COOT": "COOT", "COPL": "COPL", "COPR": "COPR", "COR": "COR", "CORT": "CORT",
    "CORZ": "CORZ", "COSM": "COSM", "COSO": "COSO", "COTY": "COTY", "COUR": "COUR", "COYA": "COYA",
    "CP": "CP", "CPA": "CPA", "CPAC": "CPAC", "CPAY": "CPAY", "CPBI": "CPBI", "CPF": "CPF",
    "CPHC": "CPHC", "CPHI": "CPHI", "CPIX": "CPIX", "CPK": "CPK", "CPNG": "CPNG", "CPOP": "CPOP",
    "CPRI": "CPRI", "CPRT": "CPRT", "CPS": "CPS", "CPSH": "CPSH", "CPSS": "CPSS", "CPT": "CPT",
    "CR": "CR", "CRAC": "CRAC", "CRAI": "CRAI", "CRAN": "CRAN", "CRAQ": "CRAQ", "CRBG": "CRBG",
    "CRBP": "CRBP", "CRBU": "CRBU", "CRC": "CRC", "CRCL": "CRCL", "CRCT": "CRCT", "CRD-A": "CRD-A",
    "CRD-B": "CRD-B", "CRDF": "CRDF", "CRDL": "CRDL", "CRDO": "CRDO", "CRE": "CRE", "CRESY": "CRESY",
    "CREX": "CREX", "CRGO": "CRGO", "CRGY": "CRGY", "CRH": "CRH", "CRI": "CRI", "CRIS": "CRIS",
    "CRK": "CRK", "CRL": "CRL", "CRMD": "CRMD", "CRML": "CRML", "CRMT": "CRMT", "CRNC": "CRNC",
    "CRNT": "CRNT", "CRON": "CRON", "CROX": "CROX", "CRS": "CRS", "CRSP": "CRSP", "CRSR": "CRSR",
    "CRT": "CRT", "CRTO": "CRTO", "CRUS": "CRUS", "CRVL": "CRVL", "CRVO": "CRVO", "CRVS": "CRVS",
    "CRWS": "CRWS", "CRWV": "CRWV", "CSAI": "CSAI", "CSBR": "CSBR", "CSGP": "CSGP", "CSHR": "CSHR",
    "CSIQ": "CSIQ", "CSPI": "CSPI", "CSQR": "CSQR", "CSR": "CSR", "CSTE": "CSTE", "CSTL": "CSTL",
    "CSTM": "CSTM", "CSV": "CSV", "CSW": "CSW", "CSWC": "CSWC", "CTAA": "CTAA", "CTAS": "CTAS",
    "CTBI": "CTBI", "CTEV": "CTEV", "CTGO": "CTGO", "CTKB": "CTKB", "CTM": "CTM", "CTMX": "CTMX",
    "CTNM": "CTNM", "CTNT": "CTNT", "CTO": "CTO", "CTOR": "CTOR", "CTOS": "CTOS", "CTRE": "CTRE",
    "CTRI": "CTRI", "CTRM": "CTRM", "CTRN": "CTRN", "CTS": "CTS", "CTSH": "CTSH", "CTSO": "CTSO",
    "CTVA": "CTVA", "CTW": "CTW", "CTXR": "CTXR", "CUB": "CUB", "CUBE": "CUBE", "CUBI": "CUBI",
    "CUE": "CUE", "CULP": "CULP", "CUPR": "CUPR", "CURB": "CURB", "CURI": "CURI", "CURR": "CURR",
    "CURV": "CURV", "CURX": "CURX", "CUVL": "CUVL", "CUZ": "CUZ", "CV": "CV", "CVBF": "CVBF",
    "CVCO": "CVCO", "CVE": "CVE", "CVEO": "CVEO", "CVGI": "CVGI", "CVI": "CVI", "CVKD": "CVKD",
    "CVLG": "CVLG", "CVLT": "CVLT", "CVM": "CVM", "CVNA": "CVNA", "CVR": "CVR", "CVRX": "CVRX",
    "CVSA": "CVSA", "CVU": "CVU", "CVV": "CVV", "CWBC": "CWBC", "CWCO": "CWCO", "CWD": "CWD",
    "CWEN": "CWEN", "CWH": "CWH", "CWK": "CWK", "CWST": "CWST", "CWT": "CWT", "CX": "CX",
    "CXAI": "CXAI", "CXDO": "CXDO", "CXII": "CXII", "CXM": "CXM", "CXT": "CXT", "CXW": "CXW",
    "CYAB": "CYAB", "CYCU": "CYCU", "CYD": "CYD", "CYH": "CYH", "CYN": "CYN", "CYPH": "CYPH",
    "CYRX": "CYRX", "CYTK": "CYTK", "CZFS": "CZFS", "CZNC": "CZNC", "CZWI": "CZWI", "DAAQ": "DAAQ",
    "DAC": "DAC", "DAIC": "DAIC", "DAIO": "DAIO", "DAKT": "DAKT", "DAN": "DAN", "DAO": "DAO",
    "DAR": "DAR", "DARE": "DARE", "DAVA": "DAVA", "DAVE": "DAVE", "DB": "DB", "DBCA": "DBCA",
    "DBD": "DBD", "DBGI": "DBGI", "DBI": "DBI", "DBRG": "DBRG", "DBVT": "DBVT", "DBX": "DBX",
    "DC": "DC", "DCBO": "DCBO", "DCGO": "DCGO", "DCH": "DCH", "DCI": "DCI", "DCO": "DCO",
    "DCOM": "DCOM", "DCOY": "DCOY", "DCTH": "DCTH", "DCX": "DCX", "DDC": "DDC", "DDD": "DDD",
    "DDI": "DDI", "DDL": "DDL", "DDS": "DDS", "DDT": "DDT", "DEA": "DEA", "DEC": "DEC",
    "DECK": "DECK", "DEFT": "DEFT", "DEI": "DEI", "DEO": "DEO", "DERM": "DERM", "DETX": "DETX",
    "DFDV": "DFDV", "DFH": "DFH", "DFIN": "DFIN", "DFLI": "DFLI", "DFNS": "DFNS", "DFSC": "DFSC",
    "DFTX": "DFTX", "DG": "DG", "DGAC": "DGAC", "DGICA": "DGICA", "DGICB": "DGICB", "DGII": "DGII",
    "DGNX": "DGNX", "DGX": "DGX", "DGXX": "DGXX", "DH": "DH", "DHC": "DHC", "DHI": "DHI",
    "DHT": "DHT", "DHX": "DHX", "DIBS": "DIBS", "DIN": "DIN", "DINO": "DINO", "DIOD": "DIOD",
    "DIT": "DIT", "DJCO": "DJCO", "DJT": "DJT", "DK": "DK", "DKI": "DKI", "DKS": "DKS",
    "DLB": "DLB", "DLHC": "DLHC", "DLO": "DLO", "DLPN": "DLPN", "DLTH": "DLTH", "DLTR": "DLTR",
    "DLX": "DLX", "DLXY": "DLXY", "DMAA": "DMAA", "DMAC": "DMAC", "DMC": "DMC", "DMII": "DMII",
    "DMRA": "DMRA", "DMRC": "DMRC", "DNA": "DNA", "DNLI": "DNLI", "DNMX": "DNMX", "DNN": "DNN",
    "DNOW": "DNOW", "DNTH": "DNTH", "DNUT": "DNUT", "DOC": "DOC", "DOCN": "DOCN", "DOCS": "DOCS",
    "DOCU": "DOCU", "DOGZ": "DOGZ", "DOLE": "DOLE", "DOMH": "DOMH", "DOO": "DOO", "DORM": "DORM",
    "DOUG": "DOUG", "DOV": "DOV", "DOX": "DOX", "DOYU": "DOYU", "DPC": "DPC", "DPRO": "DPRO",
    "DPU": "DPU", "DQ": "DQ", "DRCT": "DRCT", "DRD": "DRD", "DRDB": "DRDB", "DRH": "DRH",
    "DRIO": "DRIO", "DRK": "DRK", "DRMA": "DRMA", "DRS": "DRS", "DRTS": "DRTS", "DRVN": "DRVN",
    "DSAC": "DSAC", "DSC": "DSC", "DSGN": "DSGN", "DSGR": "DSGR", "DSGX": "DSGX", "DSP": "DSP",
    "DSS": "DSS", "DSWL": "DSWL", "DSX": "DSX", "DSY": "DSY", "DT": "DT", "DTCX": "DTCX",
    "DTE": "DTE", "DTI": "DTI", "DTIL": "DTIL", "DTM": "DTM", "DTSQ": "DTSQ", "DTSS": "DTSS",
    "DTST": "DTST", "DUKR": "DUKR", "DUO": "DUO", "DUOL": "DUOL", "DUOT": "DUOT", "DV": "DV",
    "DVA": "DVA", "DVLT": "DVLT", "DVN": "DVN", "DWSN": "DWSN", "DWTX": "DWTX", "DX": "DX",
    "DXC": "DXC", "DXCM": "DXCM", "DXF": "DXF", "DXLG": "DXLG", "DXPE": "DXPE", "DXST": "DXST",
    "DXYZ": "DXYZ", "DY": "DY", "DYAI": "DYAI", "DYN": "DYN", "DYNC": "DYNC", "DYOR": "DYOR",
    "E": "E", "EAF": "EAF", "EARN": "EARN", "EBC": "EBC", "EBF": "EBF", "EBMT": "EBMT",
    "EBON": "EBON", "EBS": "EBS", "EC": "EC", "ECAT": "ECAT", "ECBK": "ECBK", "ECC": "ECC",
    "ECG": "ECG", "ECHO": "ECHO", "ECO": "ECO", "ECOR": "ECOR", "ECPG": "ECPG", "ECVT": "ECVT",
    "ECX": "ECX", "EDBL": "EDBL", "EDIT": "EDIT", "EDN": "EDN", "EDRY": "EDRY", "EDSA": "EDSA",
    "EDTK": "EDTK", "EDU": "EDU", "EDUC": "EDUC", "EDVA": "EDVA", "EE": "EE", "EEFT": "EEFT",
    "EEIQ": "EEIQ", "EFC": "EFC", "EFOI": "EFOI", "EFOR": "EFOR", "EFSC": "EFSC", "EFSI": "EFSI",
    "EFT": "EFT", "EFTY": "EFTY", "EFX": "EFX", "EFXT": "EFXT", "EG": "EG", "EGAN": "EGAN",
    "EGBN": "EGBN", "EGG": "EGG", "EGHA": "EGHA", "EGHT": "EGHT", "EGO": "EGO", "EGP": "EGP",
    "EGY": "EGY", "EH": "EH", "EHC": "EHC", "EHGO": "EHGO", "EHLD": "EHLD", "EHTH": "EHTH",
    "EIC": "EIC", "EIG": "EIG", "EIKN": "EIKN", "EIX": "EIX", "EJH": "EJH", "ELA": "ELA",
    "ELAB": "ELAB", "ELAN": "ELAN", "ELBM": "ELBM", "ELDN": "ELDN", "ELE": "ELE", "ELF": "ELF",
    "ELLO": "ELLO", "ELMD": "ELMD", "ELME": "ELME", "ELMT": "ELMT", "ELOG": "ELOG", "ELOX": "ELOX",
    "ELPC": "ELPC", "ELPW": "ELPW", "ELS": "ELS", "ELTK": "ELTK", "ELTX": "ELTX", "ELUT": "ELUT",
    "ELVA": "ELVA", "ELVN": "ELVN", "ELVR": "ELVR", "ELWT": "ELWT", "EMA": "EMA", "EMAT": "EMAT",
    "EMBC": "EMBC", "EMBJ": "EMBJ", "EME": "EME", "EMIS": "EMIS", "EML": "EML", "EMN": "EMN",
    "EMPD": "EMPD", "ENB": "ENB", "ENGN": "ENGN", "ENGS": "ENGS", "ENHA": "ENHA", "ENIC": "ENIC",
    "ENLT": "ENLT", "ENLV": "ENLV", "ENOV": "ENOV", "ENR": "ENR", "ENRD": "ENRD", "ENS": "ENS",
    "ENSC": "ENSC", "ENSG": "ENSG", "ENTA": "ENTA", "ENTG": "ENTG", "ENTX": "ENTX", "ENVA": "ENVA",
    "ENVB": "ENVB", "ENVX": "ENVX", "EOCN": "EOCN", "EOLS": "EOLS", "EONR": "EONR", "EOSE": "EOSE",
    "EOT": "EOT", "EP": "EP", "EPAC": "EPAC", "EPAM": "EPAM", "EPC": "EPC", "EPD": "EPD",
    "EPM": "EPM", "EPOW": "EPOW", "EPR": "EPR", "EPR-E": "EPR-E", "EPRT": "EPRT", "EPRX": "EPRX",
    "EPSM": "EPSM", "EPSN": "EPSN", "EQ": "EQ", "EQBK": "EQBK", "EQH": "EQH", "EQH-A": "EQH-A",
    "EQNR": "EQNR", "EQPT": "EQPT", "EQS": "EQS", "EQT": "EQT", "EQX": "EQX", "ERAS": "ERAS",
    "ERIC": "ERIC", "ERIE": "ERIE", "ERII": "ERII", "ERNA": "ERNA", "ERO": "ERO", "EROC": "EROC",
    "EROK": "EROK", "ES": "ES", "ESAB": "ESAB", "ESCA": "ESCA", "ESE": "ESE", "ESEA": "ESEA",
    "ESI": "ESI", "ESLA": "ESLA", "ESLT": "ESLT", "ESNT": "ESNT", "ESOA": "ESOA", "ESP": "ESP",
    "ESQ": "ESQ", "ESRT": "ESRT", "ESS": "ESS", "ESTA": "ESTA", "ESTC": "ESTC", "ESYN": "ESYN",
    "ETD": "ETD", "ETO": "ETO", "ETON": "ETON", "ETOR": "ETOR", "ETR": "ETR", "ETRA": "ETRA",
    "ETS": "ETS", "ETSS": "ETSS", "ETX": "ETX", "EU": "EU", "EUDA": "EUDA", "EURK": "EURK",
    "EVAC": "EVAC", "EVAX": "EVAX", "EVC": "EVC", "EVCM": "EVCM", "EVER": "EVER", "EVEX": "EVEX",
    "EVF": "EVF", "EVGN": "EVGN", "EVGO": "EVGO", "EVH": "EVH", "EVI": "EVI", "EVLV": "EVLV",
    "EVMN": "EVMN", "EVN": "EVN", "EVO": "EVO", "EVOX": "EVOX", "EVR": "EVR", "EVRG": "EVRG",
    "EVTC": "EVTC", "EVTL": "EVTL", "EWAV": "EWAV", "EWBC": "EWBC", "EWTX": "EWTX", "EXE": "EXE",
    "EXEL": "EXEL", "EXFY": "EXFY", "EXK": "EXK", "EXLS": "EXLS", "EXOD": "EXOD", "EXOZ": "EXOZ",
    "EXP": "EXP", "EXPD": "EXPD", "EXPO": "EXPO", "EXTR": "EXTR", "EXYN": "EXYN", "EYE": "EYE",
    "EYPT": "EYPT", "EZGO": "EZGO", "EZPW": "EZPW", "EZRA": "EZRA", "FA": "FA", "FABC": "FABC",
    "FAC": "FAC", "FACT": "FACT", "FAF": "FAF", "FAMI": "FAMI", "FANG": "FANG", "FATE": "FATE",
    "FATN": "FATN", "FBDT": "FBDT", "FBGL": "FBGL", "FBIN": "FBIN", "FBIO": "FBIO", "FBIZ": "FBIZ",
    "FBK": "FBK", "FBLA": "FBLA", "FBLG": "FBLG", "FBNC": "FBNC", "FBP": "FBP", "FBRT": "FBRT",
    "FBYD": "FBYD", "FC": "FC", "FCAP": "FCAP", "FCBC": "FCBC", "FCBM": "FCBM", "FCCO": "FCCO",
    "FCEL": "FCEL", "FCF": "FCF", "FCFS": "FCFS", "FCHL": "FCHL", "FCN": "FCN", "FCNCA": "FCNCA",
    "FCPT": "FCPT", "FCRS": "FCRS", "FCUV": "FCUV", "FDBC": "FDBC", "FDMM": "FDMM", "FDMT": "FDMT",
    "FDS": "FDS", "FDSB": "FDSB", "FDXF": "FDXF", "FE": "FE", "FEAM": "FEAM", "FEBO": "FEBO",
    "FEDU": "FEDU", "FEIM": "FEIM", "FELE": "FELE", "FEMY": "FEMY", "FENC": "FENC", "FENG": "FENG",
    "FER": "FER", "FERA": "FERA", "FERG": "FERG", "FET": "FET", "FF": "FF", "FFAI": "FFAI",
    "FFBC": "FFBC", "FFIN": "FFIN", "FFIV": "FFIV", "FG": "FG", "FGBI": "FGBI", "FGI": "FGI",
    "FGII": "FGII", "FGL": "FGL", "FGNX": "FGNX", "FHB": "FHB", "FHI": "FHI", "FHN": "FHN",
    "FHTX": "FHTX", "FIBK": "FIBK", "FICO": "FICO", "FIEE": "FIEE", "FIG": "FIG", "FIGR": "FIGR",
    "FIGS": "FIGS", "FIGX": "FIGX", "FINS": "FINS", "FINV": "FINV", "FINW": "FINW", "FIP": "FIP",
    "FIRY": "FIRY", "FISI": "FISI", "FISN": "FISN", "FITB-I": "FITB-I", "FIVE": "FIVE", "FIVN": "FIVN",
    "FIX": "FIX", "FIZZ": "FIZZ", "FJDI": "FJDI", "FJET": "FJET", "FKWL": "FKWL", "FLD": "FLD",
    "FLEX": "FLEX", "FLG": "FLG", "FLGT": "FLGT", "FLL": "FLL", "FLNA": "FLNA", "FLNC": "FLNC",
    "FLNG": "FLNG", "FLNT": "FLNT", "FLO": "FLO", "FLOC": "FLOC", "FLR": "FLR", "FLS": "FLS",
    "FLUT": "FLUT", "FLUX": "FLUX", "FLWS": "FLWS", "FLX": "FLX", "FLXS": "FLXS", "FLY": "FLY",
    "FLYE": "FLYE", "FLYW": "FLYW", "FLYX": "FLYX", "FMAC": "FMAC", "FMAO": "FMAO", "FMBH": "FMBH",
    "FMC": "FMC", "FMFC": "FMFC", "FMNB": "FMNB", "FMS": "FMS", "FMST": "FMST", "FMX": "FMX",
    "FN": "FN", "FNB": "FNB", "FND": "FND", "FNF": "FNF", "FNGR": "FNGR", "FNKO": "FNKO",
    "FNLC": "FNLC", "FNRN": "FNRN", "FNUC": "FNUC", "FNV": "FNV", "FNWB": "FNWB", "FNWD": "FNWD",
    "FOA": "FOA", "FOCL": "FOCL", "FOFO": "FOFO", "FOIL": "FOIL", "FOR": "FOR", "FORM": "FORM",
    "FORR": "FORR", "FORTY": "FORTY", "FOSL": "FOSL", "FOUR": "FOUR", "FOX": "FOX", "FOXA": "FOXA",
    "FOXF": "FOXF", "FOXX": "FOXX", "FPH": "FPH", "FPI": "FPI", "FPS": "FPS", "FR": "FR",
    "FRAF": "FRAF", "FRBA": "FRBA", "FRD": "FRD", "FRGT": "FRGT", "FRHC": "FRHC", "FRME": "FRME",
    "FRMI": "FRMI", "FRMM": "FRMM", "FRNM": "FRNM", "FRO": "FRO", "FROG": "FROG", "FRPH": "FRPH",
    "FRPT": "FRPT", "FRSH": "FRSH", "FRST": "FRST", "FRSX": "FRSX", "FRT": "FRT", "FRTT": "FRTT",
    "FRVO": "FRVO", "FSBC": "FSBC", "FSBW": "FSBW", "FSCO": "FSCO", "FSEA": "FSEA", "FSHP": "FSHP",
    "FSI": "FSI", "FSK": "FSK", "FSLY": "FSLY", "FSM": "FSM", "FSP": "FSP", "FSS": "FSS",
    "FSTR": "FSTR", "FSUN": "FSUN", "FSV": "FSV", "FT": "FT", "FTAI": "FTAI", "FTCI": "FTCI",
    "FTDR": "FTDR", "FTEK": "FTEK", "FTF": "FTF", "FTFT": "FTFT", "FTH": "FTH", "FTHA": "FTHA",
    "FTHM": "FTHM", "FTI": "FTI", "FTK": "FTK", "FTLF": "FTLF", "FTRA": "FTRA", "FTRE": "FTRE",
    "FTS": "FTS", "FTV": "FTV", "FTW": "FTW", "FUBO": "FUBO", "FUFU": "FUFU", "FUL": "FUL",
    "FULC": "FULC", "FULT": "FULT", "FUN": "FUN", "FUNC": "FUNC", "FURY": "FURY", "FUSB": "FUSB",
    "FUSE": "FUSE", "FUTU": "FUTU", "FVAV": "FVAV", "FVCB": "FVCB", "FVN": "FVN", "FVR": "FVR",
    "FVRR": "FVRR", "FWAC": "FWAC", "FWDI": "FWDI", "FWONA": "FWONA", "FWONK": "FWONK", "FWRD": "FWRD",
    "FWRG": "FWRG", "FXAC": "FXAC", "FXHO": "FXHO", "FXNC": "FXNC", "G": "G", "GAB": "GAB",
    "GAB-H": "GAB-H", "GABC": "GABC", "GAIA": "GAIA", "GAIN": "GAIN", "GALT": "GALT", "GAM": "GAM",
    "GAME": "GAME", "GANX": "GANX", "GAP": "GAP", "GASS": "GASS", "GATX": "GATX", "GAU": "GAU",
    "GAUZ": "GAUZ", "GBAB": "GBAB", "GBCI": "GBCI", "GBFH": "GBFH", "GBLI": "GBLI", "GBR": "GBR",
    "GBTG": "GBTG", "GBX": "GBX", "GCBC": "GCBC", "GCDT": "GCDT", "GCGR": "GCGR", "GCL": "GCL",
    "GCMG": "GCMG", "GCO": "GCO", "GCT": "GCT", "GCTK": "GCTK", "GCTS": "GCTS", "GD": "GD",
    "GDC": "GDC", "GDDY": "GDDY", "GDEV": "GDEV", "GDHG": "GDHG", "GDOT": "GDOT", "GDRX": "GDRX",
    "GDS": "GDS", "GDTC": "GDTC", "GDV": "GDV", "GDYN": "GDYN", "GEF": "GEF", "GEF-B": "GEF-B",
    "GEG": "GEG", "GELS": "GELS", "GEMI": "GEMI", "GEN": "GEN", "GENB": "GENB", "GENC": "GENC",
    "GENI": "GENI", "GENK": "GENK", "GEO": "GEO", "GEOS": "GEOS", "GERN": "GERN", "GETY": "GETY",
    "GEV": "GEV", "GEVO": "GEVO", "GFAI": "GFAI", "GFF": "GFF", "GFI": "GFI", "GFL": "GFL",
    "GFR": "GFR", "GFS": "GFS", "GFUZ": "GFUZ", "GGAL": "GGAL", "GGB": "GGB", "GGG": "GGG",
    "GGN": "GGN", "GGR": "GGR", "GGT": "GGT", "GGZ": "GGZ", "GH": "GH", "GHC": "GHC",
    "GHG": "GHG", "GHM": "GHM", "GHRS": "GHRS", "GHXI": "GHXI", "GIB": "GIB", "GIBO": "GIBO",
    "GIC": "GIC", "GIFT": "GIFT", "GIGM": "GIGM", "GIII": "GIII", "GIL": "GIL", "GILT": "GILT",
    "GIPR": "GIPR", "GITS": "GITS", "GIW": "GIW", "GIX": "GIX", "GIXI": "GIXI", "GJO": "GJO",
    "GJP": "GJP", "GJR": "GJR", "GJS": "GJS", "GJT": "GJT", "GKOS": "GKOS", "GL": "GL",
    "GLAS": "GLAS", "GLBE": "GLBE", "GLBS": "GLBS", "GLDG": "GLDG", "GLE": "GLE", "GLED": "GLED",
    "GLIBA": "GLIBA", "GLIBK": "GLIBK", "GLND": "GLND", "GLNG": "GLNG", "GLOB": "GLOB", "GLOO": "GLOO",
    "GLPI": "GLPI", "GLRE": "GLRE", "GLSI": "GLSI", "GLU": "GLU", "GLUE": "GLUE", "GLW": "GLW",
    "GLXG": "GLXG", "GLXY": "GLXY", "GMAB": "GMAB", "GMED": "GMED", "GMEX": "GMEX", "GMHS": "GMHS",
    "GMM": "GMM", "GMRS": "GMRS", "GMTL": "GMTL", "GNE": "GNE", "GNK": "GNK", "GNL": "GNL",
    "GNLN": "GNLN", "GNLX": "GNLX", "GNPX": "GNPX", "GNS": "GNS", "GNSS": "GNSS", "GNT": "GNT",
    "GNTA": "GNTA", "GNTX": "GNTX", "GNW": "GNW", "GO": "GO", "GOAI": "GOAI", "GOGO": "GOGO",
    "GOLD": "GOLD", "GOLF": "GOLF", "GOOD": "GOOD", "GOOS": "GOOS", "GORO": "GORO", "GOSS": "GOSS",
    "GOTU": "GOTU", "GOVX": "GOVX", "GP": "GP", "GPAC": "GPAC", "GPAT": "GPAT", "GPC": "GPC",
    "GPCR": "GPCR", "GPGI": "GPGI", "GPI": "GPI", "GPK": "GPK", "GPMT": "GPMT", "GPN": "GPN",
    "GPOR": "GPOR", "GPRE": "GPRE", "GPRK": "GPRK", "GPRO": "GPRO", "GPUS": "GPUS", "GRAB": "GRAB",
    "GRAL": "GRAL", "GRAN": "GRAN", "GRBK": "GRBK", "GRC": "GRC", "GRCE": "GRCE", "GRDN": "GRDN",
    "GRDX": "GRDX", "GRFS": "GRFS", "GRI": "GRI", "GRML": "GRML", "GRMN": "GRMN", "GRND": "GRND",
    "GRNQ": "GRNQ", "GRNT": "GRNT", "GRO": "GRO", "GROV": "GROV", "GROW": "GROW", "GROY": "GROY",
    "GRPN": "GRPN", "GRRR": "GRRR", "GRSD": "GRSD", "GRVY": "GRVY", "GRWG": "GRWG", "GRX": "GRX",
    "GS-D": "GS-D", "GSAT": "GSAT", "GSBC": "GSBC", "GSBD": "GSBD", "GSHD": "GSHD", "GSHR": "GSHR",
    "GSIT": "GSIT", "GSIW": "GSIW", "GSK": "GSK", "GSL": "GSL", "GSM": "GSM", "GSRF": "GSRF",
    "GSRV": "GSRV", "GSUN": "GSUN", "GT": "GT", "GTBP": "GTBP", "GTE": "GTE", "GTEC": "GTEC",
    "GTEN": "GTEN", "GTERA": "GTERA", "GTES": "GTES", "GTIM": "GTIM", "GTLB": "GTLB", "GTM": "GTM",
    "GTN": "GTN", "GTN-A": "GTN-A", "GTX": "GTX", "GTY": "GTY", "GUAC": "GUAC", "GURE": "GURE",
    "GUT": "GUT", "GUTS": "GUTS", "GVA": "GVA", "GVH": "GVH", "GWAV": "GWAV", "GWH": "GWH",
    "GWRE": "GWRE", "GWRS": "GWRS", "GXAI": "GXAI", "GXO": "GXO", "GYGY": "GYGY", "GYRE": "GYRE",
    "GYRO": "GYRO", "HACQ": "HACQ", "HAE": "HAE", "HAFC": "HAFC", "HAFN": "HAFN", "HAIN": "HAIN",
    "HAL": "HAL", "HALO": "HALO", "HAO": "HAO", "HAPN": "HAPN", "HAS": "HAS", "HASI": "HASI",
    "HAVA": "HAVA", "HAWK": "HAWK", "HAYW": "HAYW", "HBAN": "HBAN", "HBB": "HBB", "HBCP": "HBCP",
    "HBIO": "HBIO", "HBM": "HBM", "HBNB": "HBNB", "HBNC": "HBNC", "HBT": "HBT", "HCAC": "HCAC",
    "HCAI": "HCAI", "HCAT": "HCAT", "HCC": "HCC", "HCHL": "HCHL", "HCI": "HCI", "HCIC": "HCIC",
    "HCKT": "HCKT", "HCM": "HCM", "HCMA": "HCMA", "HCSG": "HCSG", "HCTI": "HCTI", "HCWB": "HCWB",
    "HDB": "HDB", "HDL": "HDL", "HDRN": "HDRN", "HDSN": "HDSN", "HE": "HE", "HEI": "HEI",
    "HEI-A": "HEI-A", "HELE": "HELE", "HELP": "HELP", "HEPS": "HEPS", "HERE": "HERE", "HESM": "HESM",
    "HFBL": "HFBL", "HFFG": "HFFG", "HFWA": "HFWA", "HG": "HG", "HGBL": "HGBL", "HGTY": "HGTY",
    "HGV": "HGV", "HHH": "HHH", "HHS": "HHS", "HIFS": "HIFS", "HIG": "HIG", "HIHO": "HIHO",
    "HII": "HII", "HIMS": "HIMS", "HIMX": "HIMX", "HIND": "HIND", "HIPO": "HIPO", "HIT": "HIT",
    "HITI": "HITI", "HIVE": "HIVE", "HIW": "HIW", "HKD": "HKD", "HKIT": "HKIT", "HKPD": "HKPD",
    "HL": "HL", "HLF": "HLF", "HLI": "HLI", "HLIO": "HLIO", "HLIT": "HLIT", "HLLY": "HLLY",
    "HLMN": "HLMN", "HLN": "HLN", "HLNE": "HLNE", "HLP": "HLP", "HLSQ": "HLSQ", "HLXC": "HLXC",
    "HMC": "HMC", "HMH": "HMH", "HMN": "HMN", "HMR": "HMR", "HMY": "HMY", "HNGE": "HNGE",
    "HNI": "HNI", "HNNA": "HNNA", "HNRG": "HNRG", "HNST": "HNST", "HNVR": "HNVR", "HODO": "HODO",
    "HOFT": "HOFT", "HOG": "HOG", "HOLO": "HOLO", "HOMB": "HOMB", "HONA": "HONA", "HOPE": "HOPE",
    "HOS": "HOS", "HOST": "HOST", "HOUR": "HOUR", "HOV": "HOV", "HOVR": "HOVR", "HOWL": "HOWL",
    "HP": "HP", "HPAI": "HPAI", "HPK": "HPK", "HPP": "HPP", "HQ": "HQ", "HQH": "HQH",
    "HQI": "HQI", "HQL": "HQL", "HQY": "HQY", "HR": "HR", "HRB": "HRB", "HRI": "HRI",
    "HRMY": "HRMY", "HROW": "HROW", "HRTG": "HRTG", "HRTX": "HRTX", "HRZN": "HRZN", "HSAI": "HSAI",
    "HSCS": "HSCS", "HSDT": "HSDT", "HSHP": "HSHP", "HSIC": "HSIC", "HSLV": "HSLV", "HST": "HST",
    "HSTM": "HSTM", "HTB": "HTB", "HTCO": "HTCO", "HTCR": "HTCR", "HTFL": "HTFL", "HTGC": "HTGC",
    "HTH": "HTH", "HTHT": "HTHT", "HTLD": "HTLD", "HTLM": "HTLM", "HTO": "HTO", "HTOO": "HTOO",
    "HTT": "HTT", "HTZ": "HTZ", "HUBB": "HUBB", "HUBC": "HUBC", "HUBG": "HUBG", "HUBS": "HUBS",
    "HUCK": "HUCK", "HUDI": "HUDI", "HUHU": "HUHU", "HUIZ": "HUIZ", "HUMA": "HUMA", "HUN": "HUN",
    "HURA": "HURA", "HURC": "HURC", "HURN": "HURN", "HUT": "HUT", "HUYA": "HUYA", "HVMC": "HVMC",
    "HVT": "HVT", "HVT-A": "HVT-A", "HWBK": "HWBK", "HWC": "HWC", "HWKN": "HWKN", "HWM": "HWM",
    "HXHX": "HXHX", "HXL": "HXL", "HY": "HY", "HYFM": "HYFM", "HYFT": "HYFT", "HYLN": "HYLN",
    "HYMC": "HYMC", "HYNE": "HYNE", "HYPD": "HYPD", "HYPR": "HYPR", "HZO": "HZO", "IA": "IA",
    "IACO": "IACO", "IACQ": "IACQ", "IART": "IART", "IAUX": "IAUX", "IBAC": "IBAC", "IBCP": "IBCP",
    "IBEX": "IBEX", "IBG": "IBG", "IBIO": "IBIO", "IBKR": "IBKR", "IBN": "IBN", "IBO": "IBO",
    "IBOC": "IBOC", "IBP": "IBP", "IBRX": "IBRX", "IBTA": "IBTA", "ICCC": "ICCC", "ICCM": "ICCM",
    "ICFI": "ICFI", "ICG": "ICG", "ICHR": "ICHR", "ICL": "ICL", "ICLR": "ICLR", "ICMB": "ICMB",
    "ICON": "ICON", "ICU": "ICU", "ICUI": "ICUI", "IDA": "IDA", "IDAC": "IDAC", "IDAI": "IDAI",
    "IDCC": "IDCC", "IDN": "IDN", "IDR": "IDR", "IDT": "IDT", "IDYA": "IDYA", "IE": "IE",
    "IEAG": "IEAG", "IESC": "IESC", "IEX": "IEX", "IFBD": "IFBD", "IFF": "IFF", "IFRX": "IFRX",
    "IFS": "IFS", "IGAC": "IGAC", "IGC": "IGC", "IGI": "IGI", "IGIC": "IGIC", "IH": "IH",
    "IHG": "IHG", "IHRT": "IHRT", "IHS": "IHS", "IHT": "IHT", "III": "III", "IIIN": "IIIN",
    "IIIV": "IIIV", "IIM": "IIM", "IIPR": "IIPR", "IKT": "IKT", "ILAG": "ILAG", "ILLR": "ILLR",
    "ILLU": "ILLU", "ILPT": "ILPT", "IMA": "IMA", "IMAX": "IMAX", "IMC": "IMC", "IMCC": "IMCC",
    "IMCR": "IMCR", "IMDX": "IMDX", "IMKTA": "IMKTA", "IMMP": "IMMP", "IMMR": "IMMR", "IMMX": "IMMX",
    "IMNM": "IMNM", "IMNN": "IMNN", "IMO": "IMO", "IMOS": "IMOS", "IMPP": "IMPP", "IMRN": "IMRN",
    "IMRX": "IMRX", "IMSR": "IMSR", "IMTE": "IMTE", "IMTX": "IMTX", "IMUX": "IMUX", "IMVT": "IMVT",
    "IMXI": "IMXI", "INAB": "INAB", "INAC": "INAC", "INBK": "INBK", "INBS": "INBS", "INBX": "INBX",
    "INCR": "INCR", "INDB": "INDB", "INDI": "INDI", "INDO": "INDO", "INDP": "INDP", "INDV": "INDV",
    "INEO": "INEO", "INFQ": "INFQ", "INFU": "INFU", "INFY": "INFY", "INGM": "INGM", "INGN": "INGN",
    "INGR": "INGR", "INHD": "INHD", "INIO": "INIO", "INKT": "INKT", "INLF": "INLF", "INLX": "INLX",
    "INM": "INM", "INMB": "INMB", "INMD": "INMD", "INN": "INN", "INNV": "INNV", "INO": "INO",
    "INOD": "INOD", "INR": "INR", "INSE": "INSE", "INSG": "INSG", "INSM": "INSM", "INSP": "INSP",
    "INSW": "INSW", "INTA": "INTA", "INTG": "INTG", "INTJ": "INTJ", "INTR": "INTR", "INTS": "INTS",
    "INTT": "INTT", "INTZ": "INTZ", "INUV": "INUV", "INV": "INV", "INVA": "INVA", "INVE": "INVE",
    "INVH": "INVH", "INVX": "INVX", "INVZ": "INVZ", "IOND": "IOND", "IONQ": "IONQ", "IONR": "IONR",
    "IONS": "IONS", "IOR": "IOR", "IOSP": "IOSP", "IOT": "IOT", "IOTR": "IOTR", "IOVA": "IOVA",
    "IP": "IP", "IPAR": "IPAR", "IPDN": "IPDN", "IPEX": "IPEX", "IPFX": "IPFX", "IPGP": "IPGP",
    "IPHA": "IPHA", "IPI": "IPI", "IPM": "IPM", "IPSC": "IPSC", "IPST": "IPST", "IPVV": "IPVV",
    "IPW": "IPW", "IPWR": "IPWR", "IPX": "IPX", "IPXG": "IPXG", "IQ": "IQ", "IQI": "IQI",
    "IQMX": "IQMX", "IQST": "IQST", "IRAB": "IRAB", "IRD": "IRD", "IRDM": "IRDM", "IREN": "IREN",
    "IRHO": "IRHO", "IRIX": "IRIX", "IRM": "IRM", "IRMD": "IRMD", "IRON": "IRON", "IRS": "IRS",
    "IRT": "IRT", "IRTC": "IRTC", "IRWD": "IRWD", "ISBA": "ISBA", "ISNR": "ISNR", "ISOU": "ISOU",
    "ISPC": "ISPC", "ISPR": "ISPR", "ISTR": "ISTR", "IT": "IT", "ITG": "ITG", "ITGR": "ITGR",
    "ITHA": "ITHA", "ITIC": "ITIC", "ITOC": "ITOC", "ITP": "ITP", "ITRG": "ITRG", "ITRI": "ITRI",
    "ITRN": "ITRN", "ITT": "ITT", "ITW": "ITW", "IVA": "IVA", "IVDA": "IVDA", "IVF": "IVF",
    "IVR": "IVR", "IVT": "IVT", "IVVD": "IVVD", "IX": "IX", "IXHL": "IXHL", "IZEA": "IZEA",
    "IZM": "IZM", "J": "J", "JACK": "JACK", "JACS": "JACS", "JAGU": "JAGU", "JAGX": "JAGX",
    "JAKK": "JAKK", "JAN": "JAN", "JANX": "JANX", "JATT": "JATT", "JAZZ": "JAZZ", "JBDI": "JBDI",
    "JBGS": "JBGS", "JBI": "JBI", "JBIO": "JBIO", "JBL": "JBL", "JBSS": "JBSS", "JBTM": "JBTM",
    "JCAP": "JCAP", "JCI": "JCI", "JCSE": "JCSE", "JCTC": "JCTC", "JDZG": "JDZG", "JEF": "JEF",
    "JELD": "JELD", "JEM": "JEM", "JENA": "JENA", "JF": "JF", "JFIN": "JFIN", "JFU": "JFU",
    "JG": "JG", "JHI": "JHI", "JHS": "JHS", "JHX": "JHX", "JILL": "JILL", "JJSF": "JJSF",
    "JKHY": "JKHY", "JKS": "JKS", "JL": "JL", "JLHL": "JLHL", "JLL": "JLL", "JMIA": "JMIA",
    "JMKE": "JMKE", "JMSB": "JMSB", "JOB": "JOB", "JOBY": "JOBY", "JOE": "JOE", "JONE": "JONE",
    "JOUT": "JOUT", "JOYY": "JOYY", "JRSH": "JRSH", "JRVR": "JRVR", "JSPR": "JSPR", "JTAI": "JTAI",
    "JTTT": "JTTT", "JUNS": "JUNS", "JVA": "JVA", "JWEL": "JWEL", "JXG": "JXG", "JXN": "JXN",
    "JYD": "JYD", "JYNT": "JYNT", "JZ": "JZ", "JZXN": "JZXN", "KAI": "KAI", "KALA": "KALA",
    "KALU": "KALU", "KAPA": "KAPA", "KARD": "KARD", "KARO": "KARO", "KAZR": "KAZR", "KB": "KB",
    "KBDC": "KBDC", "KBH": "KBH", "KBON": "KBON", "KBR": "KBR", "KBSX": "KBSX", "KC": "KC",
    "KCHV": "KCHV", "KD": "KD", "KDK": "KDK", "KE": "KE", "KEEL": "KEEL", "KELYA": "KELYA",
    "KELYB": "KELYB", "KEN": "KEN", "KEP": "KEP", "KEQU": "KEQU", "KEX": "KEX", "KEYY": "KEYY",
    "KFFB": "KFFB", "KFII": "KFII", "KFRC": "KFRC", "KFY": "KFY", "KG": "KG", "KGC": "KGC",
    "KGEI": "KGEI", "KGS": "KGS", "KIDS": "KIDS", "KIDZ": "KIDZ", "KIM": "KIM", "KINS": "KINS",
    "KITT": "KITT", "KKR": "KKR", "KLAR": "KLAR", "KLC": "KLC", "KLIC": "KLIC", "KLRA": "KLRA",
    "KLRS": "KLRS", "KLTR": "KLTR", "KLXE": "KLXE", "KMDA": "KMDA", "KMI": "KMI", "KMPR": "KMPR",
    "KMRK": "KMRK", "KMT": "KMT", "KMTS": "KMTS", "KMX": "KMX", "KN": "KN", "KNDI": "KNDI",
    "KNF": "KNF", "KNRX": "KNRX", "KNSA": "KNSA", "KNSL": "KNSL", "KNTK": "KNTK", "KNX": "KNX",
    "KOD": "KOD", "KODK": "KODK", "KOP": "KOP", "KOPN": "KOPN", "KOS": "KOS", "KOSS": "KOSS",
    "KOYN": "KOYN", "KPET": "KPET", "KPLT": "KPLT", "KPRX": "KPRX", "KPTI": "KPTI", "KR": "KR",
    "KRAQ": "KRAQ", "KRC": "KRC", "KREF": "KREF", "KRG": "KRG", "KRKR": "KRKR", "KRMD": "KRMD",
    "KRMN": "KRMN", "KRNT": "KRNT", "KRNY": "KRNY", "KRO": "KRO", "KROS": "KROS", "KRRO": "KRRO",
    "KRSA": "KRSA", "KRSP": "KRSP", "KRT": "KRT", "KRUS": "KRUS", "KRYS": "KRYS", "KSCP": "KSCP",
    "KSPI": "KSPI", "KSS": "KSS", "KT": "KT", "KTB": "KTB", "KTCC": "KTCC", "KTF": "KTF",
    "KTOS": "KTOS", "KTTA": "KTTA", "KTWO": "KTWO", "KULR": "KULR", "KURA": "KURA", "KUST": "KUST",
    "KVHI": "KVHI", "KVUE": "KVUE", "KVYO": "KVYO", "KWR": "KWR", "KWY": "KWY", "KXIN": "KXIN",
    "KYIV": "KYIV", "KYMR": "KYMR", "KYNB": "KYNB", "KYTX": "KYTX", "KZIA": "KZIA", "L": "L",
    "LAB": "LAB", "LABT": "LABT", "LAD": "LAD", "LADR": "LADR", "LAES": "LAES", "LAFA": "LAFA",
    "LAKE": "LAKE", "LAMR": "LAMR", "LAND": "LAND", "LANV": "LANV", "LAR": "LAR", "LARK": "LARK",
    "LASE": "LASE", "LASR": "LASR", "LATA": "LATA", "LAUR": "LAUR", "LAW": "LAW", "LAWR": "LAWR",
    "LAZ": "LAZ", "LB": "LB", "LBGJ": "LBGJ", "LBRT": "LBRT", "LBRX": "LBRX", "LBTYA": "LBTYA",
    "LBTYB": "LBTYB", "LBTYK": "LBTYK", "LCCC": "LCCC", "LCFY": "LCFY", "LCII": "LCII", "LCLN": "LCLN",
    "LCNB": "LCNB", "LCTX": "LCTX", "LCUT": "LCUT", "LDI": "LDI", "LDOS": "LDOS", "LE": "LE",
    "LEA": "LEA", "LECO": "LECO", "LEDS": "LEDS", "LEE": "LEE", "LEGH": "LEGH", "LEGN": "LEGN",
    "LEGO": "LEGO", "LEN": "LEN", "LEN-B": "LEN-B", "LENZ": "LENZ", "LEO": "LEO", "LESL": "LESL",
    "LEU": "LEU", "LEXX": "LEXX", "LFAC": "LFAC", "LFCR": "LFCR", "LFMD": "LFMD", "LFS": "LFS",
    "LFST": "LFST", "LFT": "LFT", "LFTO": "LFTO", "LFUS": "LFUS", "LFVN": "LFVN", "LFWD": "LFWD",
    "LGCL": "LGCL", "LGCY": "LGCY", "LGHL": "LGHL", "LGIH": "LGIH", "LGL": "LGL", "LGN": "LGN",
    "LGND": "LGND", "LGO": "LGO", "LGPS": "LGPS", "LGVN": "LGVN", "LH": "LH", "LHAI": "LHAI",
    "LHSW": "LHSW", "LHX": "LHX", "LICN": "LICN", "LIDR": "LIDR", "LIEN": "LIEN", "LIF": "LIF",
    "LIFE": "LIFE", "LII": "LII", "LILA": "LILA", "LILAK": "LILAK", "LIME": "LIME", "LIMN": "LIMN",
    "LINC": "LINC", "LIND": "LIND", "LINE": "LINE", "LINK": "LINK", "LION": "LION", "LIQT": "LIQT",
    "LITB": "LITB", "LITE": "LITE", "LITS": "LITS", "LIVE": "LIVE", "LIVN": "LIVN", "LKFN": "LKFN",
    "LKFT": "LKFT", "LKQ": "LKQ", "LKSP": "LKSP", "LLYVA": "LLYVA", "LLYVK": "LLYVK", "LMAT": "LMAT",
    "LMB": "LMB", "LMND": "LMND", "LMNR": "LMNR", "LMRI": "LMRI", "LNAI": "LNAI", "LNC": "LNC",
    "LND": "LND", "LNG": "LNG", "LNKS": "LNKS", "LNN": "LNN", "LNSR": "LNSR", "LNT": "LNT",
    "LNTH": "LNTH", "LNZA": "LNZA", "LOAN": "LOAN", "LOAR": "LOAR", "LOB": "LOB", "LOBO": "LOBO",
    "LOCL": "LOCL", "LOCO": "LOCO", "LODE": "LODE", "LOGI": "LOGI", "LOMA": "LOMA", "LONA": "LONA",
    "LOOP": "LOOP", "LOPE": "LOPE", "LOT": "LOT", "LOVE": "LOVE", "LPA": "LPA", "LPAA": "LPAA",
    "LPBB": "LPBB", "LPCN": "LPCN", "LPCV": "LPCV", "LPG": "LPG", "LPL": "LPL", "LPLA": "LPLA",
    "LPTH": "LPTH", "LPX": "LPX", "LQDA": "LQDA", "LQDT": "LQDT", "LRE": "LRE", "LRHC": "LRHC",
    "LRMR": "LRMR", "LRN": "LRN", "LSAK": "LSAK", "LSBK": "LSBK", "LSCC": "LSCC", "LSE": "LSE",
    "LSF": "LSF", "LSPD": "LSPD", "LSTA": "LSTA", "LSTR": "LSTR", "LTBR": "LTBR", "LTC": "LTC",
    "LTGO": "LTGO", "LTGR": "LTGR", "LTH": "LTH", "LTM": "LTM", "LTRN": "LTRN", "LTRX": "LTRX",
    "LU": "LU", "LUCD": "LUCD", "LUCK": "LUCK", "LUCY": "LUCY", "LUD": "LUD", "LUMN": "LUMN",
    "LUNG": "LUNG", "LUNR": "LUNR", "LUXE": "LUXE", "LVLU": "LVLU", "LVO": "LVO", "LVWR": "LVWR",
    "LW": "LW", "LWAC": "LWAC", "LWAY": "LWAY", "LWLG": "LWLG", "LX": "LX", "LXEH": "LXEH",
    "LXEO": "LXEO", "LXFR": "LXFR", "LXP": "LXP", "LXRX": "LXRX", "LXU": "LXU", "LYB": "LYB",
    "LYEL": "LYEL", "LYG": "LYG", "LYNX": "LYNX", "LYTS": "LYTS", "LYV": "LYV", "LZ": "LZ",
    "LZB": "LZB", "LZM": "LZM", "LZMH": "LZMH", "M": "M", "MAAS": "MAAS", "MAC": "MAC",
    "MACI": "MACI", "MAGH": "MAGH", "MAGN": "MAGN", "MAIA": "MAIA", "MAIN": "MAIN", "MAIR": "MAIR",
    "MAKO": "MAKO", "MAMA": "MAMA", "MAMK": "MAMK", "MAMO": "MAMO", "MAN": "MAN", "MANE": "MANE",
    "MANH": "MANH", "MANU": "MANU", "MARA": "MARA", "MAS": "MAS", "MASK": "MASK", "MASS": "MASS",
    "MAT": "MAT", "MATH": "MATH", "MATV": "MATV", "MATW": "MATW", "MATX": "MATX", "MAX": "MAX",
    "MAYS": "MAYS", "MAZE": "MAZE", "MB": "MB", "MBAI": "MBAI", "MBBC": "MBBC", "MBC": "MBC",
    "MBGL": "MBGL", "MBI": "MBI", "MBIN": "MBIN", "MBIO": "MBIO", "MBLY": "MBLY", "MBOT": "MBOT",
    "MBRX": "MBRX", "MBUU": "MBUU", "MBVI": "MBVI", "MBWM": "MBWM", "MBX": "MBX", "MC": "MC",
    "MCAH": "MCAH", "MCB": "MCB", "MCBS": "MCBS", "MCFT": "MCFT", "MCGA": "MCGA", "MCHB": "MCHB",
    "MCHX": "MCHX", "MCI": "MCI", "MCK": "MCK", "MCRB": "MCRB", "MCRI": "MCRI", "MCRP": "MCRP",
    "MCS": "MCS", "MCTA": "MCTA", "MCY": "MCY", "MD": "MD", "MDA": "MDA", "MDAI": "MDAI",
    "MDBH": "MDBH", "MDCX": "MDCX", "MDGL": "MDGL", "MDIA": "MDIA", "MDLN": "MDLN", "MDRR": "MDRR",
    "MDU": "MDU", "MDWD": "MDWD", "MDXG": "MDXG", "MDXH": "MDXH", "MEC": "MEC", "MED": "MED",
    "MEDP": "MEDP", "MEDS": "MEDS", "MEGL": "MEGL", "MEI": "MEI", "MENS": "MENS", "MEOH": "MEOH",
    "MERC": "MERC", "MESH": "MESH", "MESO": "MESO", "MET-E": "MET-E", "METC": "METC", "METCB": "METCB",
    "MEVO": "MEVO", "MF": "MF", "MFA": "MFA", "MFC": "MFC", "MFG": "MFG", "MFI": "MFI",
    "MFIN": "MFIN", "MFP": "MFP", "MG": "MG", "MGA": "MGA", "MGEE": "MGEE", "MGIH": "MGIH",
    "MGLD": "MGLD", "MGN": "MGN", "MGNI": "MGNI", "MGNX": "MGNX", "MGPI": "MGPI", "MGRC": "MGRC",
    "MGRT": "MGRT", "MGRX": "MGRX", "MGTX": "MGTX", "MGX": "MGX", "MGY": "MGY", "MGYR": "MGYR",
    "MH": "MH", "MHH": "MHH", "MHK": "MHK", "MHO": "MHO", "MI": "MI", "MIAC": "MIAC",
    "MIAX": "MIAX", "MICC": "MICC", "MIDD": "MIDD", "MIMI": "MIMI", "MIND": "MIND", "MINE": "MINE",
    "MIR": "MIR", "MIRA": "MIRA", "MIRM": "MIRM", "MIST": "MIST", "MITK": "MITK", "MITQ": "MITQ",
    "MITT": "MITT", "MKC-V": "MKC-V", "MKDW": "MKDW", "MKL": "MKL", "MKLY": "MKLY", "MKSI": "MKSI",
    "MKTW": "MKTW", "MKTX": "MKTX", "MKZR": "MKZR", "MLAA": "MLAA", "MLAB": "MLAB", "MLCI": "MLCI",
    "MLCO": "MLCO", "MLEC": "MLEC", "MLGO": "MLGO", "MLI": "MLI", "MLKN": "MLKN", "MLM": "MLM",
    "MLP": "MLP", "MLR": "MLR", "MLSS": "MLSS", "MLTX": "MLTX", "MLYS": "MLYS", "MMA": "MMA",
    "MMED": "MMED", "MMI": "MMI", "MMS": "MMS", "MMSI": "MMSI", "MMTX": "MMTX", "MMYT": "MMYT",
    "MNDO": "MNDO", "MNDR": "MNDR", "MNDY": "MNDY", "MNKD": "MNKD", "MNOV": "MNOV", "MNPR": "MNPR",
    "MNRO": "MNRO", "MNSB": "MNSB", "MNSBP": "MNSBP", "MNSO": "MNSO", "MNTK": "MNTK", "MNTN": "MNTN",
    "MNTS": "MNTS", "MNY": "MNY", "MOB": "MOB", "MOBI": "MOBI", "MOBX": "MOBX", "MOD": "MOD",
    "MODD": "MODD", "MOG-A": "MOG-A", "MOG-B": "MOG-B", "MOGU": "MOGU", "MOLN": "MOLN", "MOMO": "MOMO",
    "MORN": "MORN", "MOS": "MOS", "MOV": "MOV", "MOVE": "MOVE", "MPAA": "MPAA", "MPB": "MPB",
    "MPC": "MPC", "MPLT": "MPLT", "MPT": "MPT", "MPTI": "MPTI", "MPU": "MPU", "MPV": "MPV",
    "MPWR": "MPWR", "MQ": "MQ", "MRAM": "MRAM", "MRBK": "MRBK", "MRCO": "MRCO", "MRCY": "MRCY",
    "MRDN": "MRDN", "MREO": "MREO", "MRKR": "MRKR", "MRLN": "MRLN", "MRM": "MRM", "MRNO": "MRNO",
    "MRP": "MRP", "MRSH": "MRSH", "MRT": "MRT", "MRTN": "MRTN", "MRVI": "MRVI", "MRX": "MRX",
    "MS-A": "MS-A", "MS-F": "MS-F", "MSA": "MSA", "MSAI": "MSAI", "MSB": "MSB", "MSBI": "MSBI",
    "MSC": "MSC", "MSEX": "MSEX", "MSGE": "MSGE", "MSGM": "MSGM", "MSGS": "MSGS", "MSGY": "MSGY",
    "MSI": "MSI", "MSLE": "MSLE", "MSM": "MSM", "MSN": "MSN", "MSS": "MSS", "MT": "MT",
    "MTA": "MTA", "MTAK": "MTAK", "MTAL": "MTAL", "MTC": "MTC", "MTCH": "MTCH", "MTD": "MTD",
    "MTDR": "MTDR", "MTEK": "MTEK", "MTEN": "MTEN", "MTEX": "MTEX", "MTG": "MTG", "MTH": "MTH",
    "MTLS": "MTLS", "MTNB": "MTNB", "MTNE": "MTNE", "MTR": "MTR", "MTRN": "MTRN", "MTRX": "MTRX",
    "MTSI": "MTSI", "MTUS": "MTUS", "MTVA": "MTVA", "MTW": "MTW", "MTX": "MTX", "MTZ": "MTZ",
    "MUR": "MUR", "MUSA": "MUSA", "MUX": "MUX", "MUZE": "MUZE", "MVBF": "MVBF", "MVIS": "MVIS",
    "MVST": "MVST", "MWA": "MWA", "MWC": "MWC", "MWG": "MWG", "MWH": "MWH", "MWYN": "MWYN",
    "MX": "MX", "MXC": "MXC", "MXCT": "MXCT", "MXL": "MXL", "MYE": "MYE", "MYFW": "MYFW",
    "MYGN": "MYGN", "MYND": "MYND", "MYO": "MYO", "MYPS": "MYPS", "MYRG": "MYRG", "MYSE": "MYSE",
    "MYSZ": "MYSZ", "MYX": "MYX", "MZTI": "MZTI", "MZYX": "MZYX", "NA": "NA", "NAAS": "NAAS",
    "NABL": "NABL", "NAGE": "NAGE", "NAII": "NAII", "NAK": "NAK", "NAKA": "NAKA", "NAMI": "NAMI",
    "NAMM": "NAMM", "NAMS": "NAMS", "NAT": "NAT", "NATH": "NATH", "NATL": "NATL", "NATR": "NATR",
    "NAUT": "NAUT", "NAVI": "NAVI", "NAVN": "NAVN", "NB": "NB", "NBBK": "NBBK", "NBHC": "NBHC",
    "NBIS": "NBIS", "NBIX": "NBIX", "NBN": "NBN", "NBP": "NBP", "NBR": "NBR", "NBRG": "NBRG",
    "NBTB": "NBTB", "NBTX": "NBTX", "NC": "NC", "NCDL": "NCDL", "NCEL": "NCEL", "NCEW": "NCEW",
    "NCI": "NCI", "NCMI": "NCMI", "NCNA": "NCNA", "NCNO": "NCNO", "NCO": "NCO", "NCPL": "NCPL",
    "NCRA": "NCRA", "NCT": "NCT", "NCTY": "NCTY", "NDLS": "NDLS", "NDRA": "NDRA", "NDSN": "NDSN",
    "NE": "NE", "NECB": "NECB", "NEGG": "NEGG", "NEO": "NEO", "NEOG": "NEOG", "NEON": "NEON",
    "NEOV": "NEOV", "NEPH": "NEPH", "NERV": "NERV", "NESR": "NESR", "NEU": "NEU", "NEUP": "NEUP",
    "NEWP": "NEWP", "NEWT": "NEWT", "NEXA": "NEXA", "NEXM": "NEXM", "NEXN": "NEXN", "NEXR": "NEXR",
    "NEXT": "NEXT", "NFE": "NFE", "NFG": "NFG", "NFGC": "NFGC", "NG": "NG", "NGEN": "NGEN",
    "NGG": "NGG", "NGNE": "NGNE", "NGS": "NGS", "NGVC": "NGVC", "NGVT": "NGVT", "NHC": "NHC",
    "NHI": "NHI", "NHIV": "NHIV", "NHP": "NHP", "NHTC": "NHTC", "NI": "NI", "NIC": "NIC",
    "NICE": "NICE", "NICM": "NICM", "NIKI": "NIKI", "NINE": "NINE", "NIPG": "NIPG", "NIQ": "NIQ",
    "NIU": "NIU", "NIVF": "NIVF", "NIXX": "NIXX", "NJR": "NJR", "NKLR": "NKLR", "NKSH": "NKSH",
    "NKTR": "NKTR", "NKTX": "NKTX", "NL": "NL", "NLOP": "NLOP", "NLY": "NLY", "NMAD": "NMAD",
    "NMAX": "NMAX", "NMFC": "NMFC", "NMG": "NMG", "NMIH": "NMIH", "NMP": "NMP", "NMR": "NMR",
    "NMRA": "NMRA", "NMRK": "NMRK", "NMTC": "NMTC", "NN": "NN", "NNBR": "NNBR", "NNDM": "NNDM",
    "NNE": "NNE", "NNI": "NNI", "NNN": "NNN", "NNNN": "NNNN", "NNOX": "NNOX", "NNVC": "NNVC",
    "NOA": "NOA", "NOAH": "NOAH", "NOC": "NOC", "NODK": "NODK", "NOEM": "NOEM", "NOG": "NOG",
    "NOK": "NOK", "NOMA": "NOMA", "NOMD": "NOMD", "NOV": "NOV", "NOVT": "NOVT", "NP": "NP",
    "NPAC": "NPAC", "NPB": "NPB", "NPCE": "NPCE", "NPK": "NPK", "NPKI": "NPKI", "NPO": "NPO",
    "NPT": "NPT", "NPWR": "NPWR", "NRC": "NRC", "NRDS": "NRDS", "NRDY": "NRDY", "NREF": "NREF",
    "NRG": "NRG", "NRGV": "NRGV", "NRIM": "NRIM", "NRIX": "NRIX", "NRP": "NRP", "NRSN": "NRSN",
    "NRT": "NRT", "NRXP": "NRXP", "NRXS": "NRXS", "NSAI": "NSAI", "NSIT": "NSIT", "NSP": "NSP",
    "NSPR": "NSPR", "NSRX": "NSRX", "NSSC": "NSSC", "NSTS": "NSTS", "NSYS": "NSYS", "NTAP": "NTAP",
    "NTB": "NTB", "NTCL": "NTCL", "NTCT": "NTCT", "NTES": "NTES", "NTGR": "NTGR", "NTHI": "NTHI",
    "NTIC": "NTIC", "NTIP": "NTIP", "NTLA": "NTLA", "NTNX": "NTNX", "NTR": "NTR", "NTRA": "NTRA",
    "NTRB": "NTRB", "NTRP": "NTRP", "NTRS": "NTRS", "NTSK": "NTSK", "NTST": "NTST", "NTWK": "NTWK",
    "NTWO": "NTWO", "NUAI": "NUAI", "NUCL": "NUCL", "NUR": "NUR", "NUS": "NUS", "NUTX": "NUTX",
    "NUVB": "NUVB", "NUWE": "NUWE", "NVA": "NVA", "NVAX": "NVAX", "NVCR": "NVCR", "NVCT": "NVCT",
    "NVEC": "NVEC", "NVGS": "NVGS", "NVMI": "NVMI", "NVNI": "NVNI", "NVNO": "NVNO", "NVR": "NVR",
    "NVRI": "NVRI", "NVS": "NVS", "NVST": "NVST", "NVT": "NVT", "NVTS": "NVTS", "NVX": "NVX",
    "NWAX": "NWAX", "NWBI": "NWBI", "NWCL": "NWCL", "NWE": "NWE", "NWFL": "NWFL", "NWG": "NWG",
    "NWGL": "NWGL", "NWL": "NWL", "NWN": "NWN", "NWPX": "NWPX", "NWS": "NWS", "NWSA": "NWSA",
    "NWTG": "NWTG", "NX": "NX", "NXAT": "NXAT", "NXB": "NXB", "NXDR": "NXDR", "NXDT": "NXDT",
    "NXE": "NXE", "NXGL": "NXGL", "NXH": "NXH", "NXL": "NXL", "NXP": "NXP", "NXPL": "NXPL",
    "NXRT": "NXRT", "NXST": "NXST", "NXT": "NXT", "NXTC": "NXTC", "NXTS": "NXTS", "NXTT": "NXTT",
    "NXXT": "NXXT", "NYAX": "NYAX", "NYC": "NYC", "NYT": "NYT", "NYXH": "NYXH", "OABI": "OABI",
    "OACC": "OACC", "OBA": "OBA", "OBAI": "OBAI", "OBDC": "OBDC", "OBE": "OBE", "OBIO": "OBIO",
    "OBK": "OBK", "OBT": "OBT", "OBX": "OBX", "OC": "OC", "OCAC": "OCAC", "OCC": "OCC",
    "OCFC": "OCFC", "OCG": "OCG", "OCGN": "OCGN", "OCLT": "OCLT", "OCS": "OCS", "OCTV": "OCTV",
    "OCUL": "OCUL", "ODC": "ODC", "ODD": "ODD", "ODTX": "ODTX", "ODYS": "ODYS", "OEC": "OEC",
    "OESX": "OESX", "OFAL": "OFAL", "OFG": "OFG", "OFIX": "OFIX", "OFLX": "OFLX", "OFRM": "OFRM",
    "OGC": "OGC", "OGE": "OGE", "OGEN": "OGEN", "OGG": "OGG", "OGI": "OGI", "OGN": "OGN",
    "OGS": "OGS", "OHAC": "OHAC", "OHI": "OHI", "OI": "OI", "OIA": "OIA", "OIG": "OIG",
    "OII": "OII", "OIM": "OIM", "OIO": "OIO", "OIS": "OIS", "OKE": "OKE", "OKLO": "OKLO",
    "OKUR": "OKUR", "OKYO": "OKYO", "OLB": "OLB", "OLED": "OLED", "OLLI": "OLLI", "OLMA": "OLMA",
    "OLN": "OLN", "OLOX": "OLOX", "OLP": "OLP", "OM": "OM", "OMAB": "OMAB", "OMC": "OMC",
    "OMCL": "OMCL", "OMDA": "OMDA", "OMER": "OMER", "OMEX": "OMEX", "OMF": "OMF", "OMH": "OMH",
    "OMSE": "OMSE", "ONB": "ONB", "ONC": "ONC", "ONCH": "ONCH", "ONCO": "ONCO", "ONCY": "ONCY",
    "ONDS": "ONDS", "ONEG": "ONEG", "ONEN": "ONEN", "ONEW": "ONEW", "ONFO": "ONFO", "ONIT": "ONIT",
    "ONL": "ONL", "ONMD": "ONMD", "ONON": "ONON", "ONT": "ONT", "ONTO": "ONTO", "OOMA": "OOMA",
    "OPAD": "OPAD", "OPAL": "OPAL", "OPBK": "OPBK", "OPCH": "OPCH", "OPEN": "OPEN", "OPFI": "OPFI",
    "OPHC": "OPHC", "OPI": "OPI", "OPK": "OPK", "OPLN": "OPLN", "OPRA": "OPRA", "OPRT": "OPRT",
    "OPRX": "OPRX", "OPTH": "OPTH", "OPTT": "OPTT", "OPTU": "OPTU", "OPTX": "OPTX", "OPXS": "OPXS",
    "OPY": "OPY", "OR": "OR", "ORA": "ORA", "ORBS": "ORBS", "ORC": "ORC", "ORGO": "ORGO",
    "ORI": "ORI", "ORIC": "ORIC", "ORIO": "ORIO", "ORIQ": "ORIQ", "ORKA": "ORKA", "ORKT": "ORKT",
    "ORLY": "ORLY", "ORMP": "ORMP", "ORN": "ORN", "ORRF": "ORRF", "OSBC": "OSBC", "OSCR": "OSCR",
    "OSG": "OSG", "OSIS": "OSIS", "OSK": "OSK", "OSPN": "OSPN", "OSPR": "OSPR", "OSS": "OSS",
    "OST": "OST", "OSTX": "OSTX", "OSUR": "OSUR", "OSW": "OSW", "OTAI": "OTAI", "OTEX": "OTEX",
    "OTF": "OTF", "OTGA": "OTGA", "OTIS": "OTIS", "OTLK": "OTLK", "OTLY": "OTLY", "OTTR": "OTTR",
    "OUST": "OUST", "OUT": "OUT", "OVBC": "OVBC", "OVID": "OVID", "OVLY": "OVLY", "OVV": "OVV",
    "OWL": "OWL", "OWLS": "OWLS", "OWLT": "OWLT", "OXBR": "OXBR", "OXM": "OXM", "OYSE": "OYSE",
    "OZK": "OZK", "P": "P", "PAAC": "PAAC", "PAAI": "PAAI", "PAAS": "PAAS", "PAC": "PAC",
    "PACB": "PACB", "PACH": "PACH", "PACK": "PACK", "PACS": "PACS", "PAG": "PAG", "PAGP": "PAGP",
    "PAGS": "PAGS", "PAHC": "PAHC", "PAII": "PAII", "PAL": "PAL", "PALI": "PALI", "PALO": "PALO",
    "PAM": "PAM", "PAMT": "PAMT", "PANL": "PANL", "PAPL": "PAPL", "PAR": "PAR", "PARA": "PARA",
    "PARK": "PARK", "PARR": "PARR", "PASG": "PASG", "PASW": "PASW", "PATH": "PATH", "PATK": "PATK",
    "PAVM": "PAVM", "PAVS": "PAVS", "PAX": "PAX", "PAY": "PAY", "PAYC": "PAYC", "PAYO": "PAYO",
    "PAYP": "PAYP", "PAYS": "PAYS", "PB": "PB", "PBA": "PBA", "PBAM": "PBAM", "PBF": "PBF",
    "PBFS": "PBFS", "PBH": "PBH", "PBHC": "PBHC", "PBI": "PBI", "PBK": "PBK", "PBLS": "PBLS",
    "PBM": "PBM", "PBR": "PBR", "PBT": "PBT", "PBYI": "PBYI", "PC": "PC", "PCAP": "PCAP",
    "PCB": "PCB", "PCLA": "PCLA", "PCOR": "PCOR", "PCRX": "PCRX", "PCSA": "PCSA", "PCT": "PCT",
    "PCTY": "PCTY", "PCVX": "PCVX", "PCYO": "PCYO", "PD": "PD", "PDC": "PDC", "PDCC": "PDCC",
    "PDEX": "PDEX", "PDFS": "PDFS", "PDLB": "PDLB", "PDM": "PDM", "PDS": "PDS", "PDSB": "PDSB",
    "PDYN": "PDYN", "PEB": "PEB", "PEBK": "PEBK", "PEBO": "PEBO", "PECE": "PECE", "PECO": "PECO",
    "PED": "PED", "PEGA": "PEGA", "PEN": "PEN", "PENG": "PENG", "PEPG": "PEPG", "PERF": "PERF",
    "PERI": "PERI", "PESI": "PESI", "PETS": "PETS", "PETZ": "PETZ", "PEW": "PEW", "PFAI": "PFAI",
    "PFG": "PFG", "PFGC": "PFGC", "PFIS": "PFIS", "PFLT": "PFLT", "PFS": "PFS", "PFSA": "PFSA",
    "PFSI": "PFSI", "PFX": "PFX", "PGAC": "PGAC", "PGC": "PGC", "PGEN": "PGEN", "PGNY": "PGNY",
    "PGY": "PGY", "PHAR": "PHAR", "PHAT": "PHAT", "PHG": "PHG", "PHI": "PHI", "PHIN": "PHIN",
    "PHIO": "PHIO", "PHM": "PHM", "PHOE": "PHOE", "PHOS": "PHOS", "PHR": "PHR", "PHUN": "PHUN",
    "PHVS": "PHVS", "PI": "PI", "PICS": "PICS", "PII": "PII", "PIII": "PIII", "PIM": "PIM",
    "PINE": "PINE", "PINS": "PINS", "PIPR": "PIPR", "PJT": "PJT", "PK": "PK", "PKBK": "PKBK",
    "PKE": "PKE", "PKG": "PKG", "PKOH": "PKOH", "PKX": "PKX", "PL": "PL", "PLAB": "PLAB",
    "PLAG": "PLAG", "PLAY": "PLAY", "PLBC": "PLBC", "PLBL": "PLBL", "PLBY": "PLBY", "PLCE": "PLCE",
    "PLCI": "PLCI", "PLG": "PLG", "PLGO": "PLGO", "PLMK": "PLMK", "PLMR": "PLMR", "PLNT": "PLNT",
    "PLOW": "PLOW", "PLPC": "PLPC", "PLRX": "PLRX", "PLRZ": "PLRZ", "PLSE": "PLSE", "PLSM": "PLSM",
    "PLTK": "PLTK", "PLUN": "PLUN", "PLUR": "PLUR", "PLUS": "PLUS", "PLUT": "PLUT", "PLX": "PLX",
    "PLXS": "PLXS", "PLYX": "PLYX", "PMA": "PMA", "PMAX": "PMAX", "PMCB": "PMCB", "PMEC": "PMEC",
    "PMI": "PMI", "PMM": "PMM", "PMN": "PMN", "PMO": "PMO", "PMT": "PMT", "PMTR": "PMTR",
    "PMTS": "PMTS", "PMVP": "PMVP", "PN": "PN", "PNBK": "PNBK", "PNFP": "PNFP", "PNNT": "PNNT",
    "PNR": "PNR", "PNRG": "PNRG", "PNTG": "PNTG", "PNW": "PNW", "POAS": "POAS", "POCI": "POCI",
    "PODC": "PODC", "PODD": "PODD", "POET": "POET", "POLA": "POLA", "POLE": "POLE", "POM": "POM",
    "PONO": "PONO", "PONY": "PONY", "POOL": "POOL", "POR": "POR", "POST": "POST", "POWI": "POWI",
    "POWL": "POWL", "POWW": "POWW", "PPBT": "PPBT", "PPC": "PPC", "PPCB": "PPCB", "PPHC": "PPHC",
    "PPIH": "PPIH", "PPL": "PPL", "PPLI": "PPLI", "PPSI": "PPSI", "PPT": "PPT", "PPTA": "PPTA",
    "PR": "PR", "PRAA": "PRAA", "PRAX": "PRAX", "PRCH": "PRCH", "PRCT": "PRCT", "PRDO": "PRDO",
    "PRE": "PRE", "PRFX": "PRFX", "PRG": "PRG", "PRGO": "PRGO", "PRGS": "PRGS", "PRHI": "PRHI",
    "PRI": "PRI", "PRIM": "PRIM", "PRK": "PRK", "PRKS": "PRKS", "PRLB": "PRLB", "PRLD": "PRLD",
    "PRM": "PRM", "PRMB": "PRMB", "PRME": "PRME", "PROF": "PROF", "PROK": "PROK", "PROP": "PROP",
    "PROV": "PROV", "PRPL": "PRPL", "PRPO": "PRPO", "PRQR": "PRQR", "PRSO": "PRSO", "PRSU": "PRSU",
    "PRTA": "PRTA", "PRTH": "PRTH", "PRTS": "PRTS", "PRVA": "PRVA", "PRZO": "PRZO", "PS": "PS",
    "PSBD": "PSBD", "PSFE": "PSFE", "PSHG": "PSHG", "PSIG": "PSIG", "PSIX": "PSIX", "PSKY": "PSKY",
    "PSMT": "PSMT", "PSN": "PSN", "PSNL": "PSNL", "PSNY": "PSNY", "PSNYW": "PSNYW", "PSO": "PSO",
    "PSQH": "PSQH", "PSQL": "PSQL", "PSTL": "PSTL", "PSUS": "PSUS", "PSX": "PSX", "PTAC": "PTAC",
    "PTC": "PTC", "PTCT": "PTCT", "PTEN": "PTEN", "PTGX": "PTGX", "PTHS": "PTHS", "PTLE": "PTLE",
    "PTLO": "PTLO", "PTN": "PTN", "PTON": "PTON", "PTOR": "PTOR", "PTRN": "PTRN", "PUBM": "PUBM",
    "PUK": "PUK", "PULM": "PULM", "PUMP": "PUMP", "PURR": "PURR", "PUSA": "PUSA", "PVLA": "PVLA",
    "PW": "PW", "PWCM": "PWCM", "PWP": "PWP", "PWR": "PWR", "PWRL": "PWRL", "PXED": "PXED",
    "PXLW": "PXLW", "PXS": "PXS", "PYPD": "PYPD", "PYT": "PYT", "PYXS": "PYXS", "PZG": "PZG",
    "PZZA": "PZZA", "Q": "Q", "QADR": "QADR", "QBTS": "QBTS", "QCLS": "QCLS", "QCRH": "QCRH",
    "QDEL": "QDEL", "QETA": "QETA", "QFIN": "QFIN", "QGEN": "QGEN", "QH": "QH", "QLEP": "QLEP",
    "QLYS": "QLYS", "QMCO": "QMCO", "QMLS": "QMLS", "QNBC": "QNBC", "QNC": "QNC", "QNCX": "QNCX",
    "QNME": "QNME", "QNRX": "QNRX", "QNST": "QNST", "QNT": "QNT", "QNTM": "QNTM", "QRED": "QRED",
    "QRHC": "QRHC", "QRVO": "QRVO", "QS": "QS", "QSEA": "QSEA", "QSI": "QSI", "QTEX": "QTEX",
    "QTI": "QTI", "QTRX": "QTRX", "QTTB": "QTTB", "QTWO": "QTWO", "QUAD": "QUAD", "QUBT": "QUBT",
    "QUCY": "QUCY", "QUIK": "QUIK", "QUMS": "QUMS", "QURE": "QURE", "QVCG": "QVCG", "QXL": "QXL",
    "QXO": "QXO", "RAC": "RAC", "RACC": "RACC", "RACD": "RACD", "RACE": "RACE", "RADX": "RADX",
    "RAIL": "RAIL", "RAIN": "RAIN", "RAL": "RAL", "RAMP": "RAMP", "RANG": "RANG", "RANI": "RANI",
    "RAPP": "RAPP", "RARE": "RARE", "RAVE": "RAVE", "RAYA": "RAYA", "RBA": "RBA", "RBB": "RBB",
    "RBBN": "RBBN", "RBCAA": "RBCAA", "RBKB": "RBKB", "RBLX": "RBLX", "RBNE": "RBNE", "RBRK": "RBRK",
    "RC": "RC", "RCAT": "RCAT", "RCBC": "RCBC", "RCEL": "RCEL", "RCI": "RCI", "RCKT": "RCKT",
    "RCKY": "RCKY", "RCMT": "RCMT", "RCON": "RCON", "RCT": "RCT", "RCUS": "RCUS", "RDAC": "RDAC",
    "RDAG": "RDAG", "RDCM": "RDCM", "RDDT": "RDDT", "RDGT": "RDGT", "RDHL": "RDHL", "RDI": "RDI",
    "RDIB": "RDIB", "RDN": "RDN", "RDNT": "RDNT", "RDNW": "RDNW", "RDVT": "RDVT", "RDW": "RDW",
    "RDWR": "RDWR", "RDY": "RDY", "RDZN": "RDZN", "REA": "REA", "REAL": "REAL", "REAX": "REAX",
    "REBN": "REBN", "RECT": "RECT", "REED": "REED", "REF": "REF", "REFI": "REFI", "REFR": "REFR",
    "REG": "REG", "REI": "REI", "REKR": "REKR", "RELL": "RELL", "RELX": "RELX", "RELY": "RELY",
    "RENT": "RENT", "RENX": "RENX", "REPL": "REPL", "REPX": "REPX", "RERE": "RERE", "RES": "RES",
    "RETO": "RETO", "REVB": "REVB", "REX": "REX", "REXR": "REXR", "REYN": "REYN", "REZI": "REZI",
    "RFAI": "RFAI", "RFAM": "RFAM", "RFIL": "RFIL", "RFL": "RFL", "RGA": "RGA", "RGC": "RGC",
    "RGCO": "RGCO", "RGEN": "RGEN", "RGLD": "RGLD", "RGNT": "RGNT", "RGNX": "RGNX", "RGP": "RGP",
    "RGR": "RGR", "RGS": "RGS", "RGT": "RGT", "RGTI": "RGTI", "RH": "RH", "RHI": "RHI",
    "RHLD": "RHLD", "RHP": "RHP", "RIBB": "RIBB", "RICK": "RICK", "RIG": "RIG", "RIGL": "RIGL",
    "RILY": "RILY", "RIME": "RIME", "RIOT": "RIOT", "RITM": "RITM", "RJET": "RJET", "RJF": "RJF",
    "RKDA": "RKDA", "RKT": "RKT", "RKTO": "RKTO", "RLAY": "RLAY", "RLGT": "RLGT", "RLI": "RLI",
    "RLJ": "RLJ", "RLMD": "RLMD", "RLYB": "RLYB", "RM": "RM", "RMBI": "RMBI", "RMBS": "RMBS",
    "RMCF": "RMCF", "RMCO": "RMCO", "RMD": "RMD", "RMIX": "RMIX", "RML": "RML", "RMNI": "RMNI",
    "RMR": "RMR", "RMSG": "RMSG", "RMT": "RMT", "RMTI": "RMTI", "RNA": "RNA", "RNAC": "RNAC",
    "RNAQ": "RNAQ", "RNAZ": "RNAZ", "RNG": "RNG", "RNGR": "RNGR", "RNGT": "RNGT", "RNR": "RNR",
    "RNST": "RNST", "RNTX": "RNTX", "RNW": "RNW", "RNXT": "RNXT", "ROAD": "ROAD", "ROC": "ROC",
    "ROCK": "ROCK", "ROG": "ROG", "ROIV": "ROIV", "ROKU": "ROKU", "ROL": "ROL", "ROLR": "ROLR",
    "ROMA": "ROMA", "ROOT": "ROOT", "RPAY": "RPAY", "RPC": "RPC", "RPD": "RPD", "RPGL": "RPGL",
    "RPID": "RPID", "RPM": "RPM", "RPRX": "RPRX", "RPT": "RPT", "RR": "RR", "RRBI": "RRBI",
    "RRC": "RRC", "RREV": "RREV", "RRGB": "RRGB", "RRR": "RRR", "RRX": "RRX", "RS": "RS",
    "RSI": "RSI", "RSKD": "RSKD", "RSSS": "RSSS", "RSVR": "RSVR", "RTAC": "RTAC", "RTB": "RTB",
    "RTO": "RTO", "RUBI": "RUBI", "RUM": "RUM", "RUSHA": "RUSHA", "RUSHB": "RUSHB", "RVLV": "RVLV",
    "RVMD": "RVMD", "RVP": "RVP", "RVSB": "RVSB", "RVSN": "RVSN", "RVT": "RVT", "RVTY": "RVTY",
    "RWAY": "RWAY", "RWT": "RWT", "RXO": "RXO", "RXRX": "RXRX", "RXST": "RXST", "RXT": "RXT",
    "RY": "RY", "RYAAY": "RYAAY", "RYAM": "RYAM", "RYAN": "RYAN", "RYDE": "RYDE", "RYET": "RYET",
    "RYM": "RYM", "RYN": "RYN", "RYOJ": "RYOJ", "RYTM": "RYTM", "RYZ": "RYZ", "RZLT": "RZLT",
    "RZLV": "RZLV", "S": "S", "SA": "SA", "SAAQ": "SAAQ", "SABR": "SABR", "SABS": "SABS",
    "SAC": "SAC", "SACH": "SACH", "SAFE": "SAFE", "SAFT": "SAFT", "SAFX": "SAFX", "SAGT": "SAGT",
    "SAGU": "SAGU", "SAH": "SAH", "SAIC": "SAIC", "SAIH": "SAIH", "SAIL": "SAIL", "SAM": "SAM",
    "SAMG": "SAMG", "SAMO": "SAMO", "SAN": "SAN", "SANA": "SANA", "SANG": "SANG", "SANM": "SANM",
    "SAR": "SAR", "SARO": "SARO", "SATL": "SATL", "SB": "SB", "SBC": "SBC", "SBCF": "SBCF",
    "SBET": "SBET", "SBFG": "SBFG", "SBFM": "SBFM", "SBGI": "SBGI", "SBH": "SBH", "SBLK": "SBLK",
    "SBMT": "SBMT", "SBR": "SBR", "SBRA": "SBRA", "SBS": "SBS", "SBSI": "SBSI", "SBSW": "SBSW",
    "SBXD": "SBXD", "SBXE": "SBXE", "SCAG": "SCAG", "SCCO": "SCCO", "SCE-L": "SCE-L", "SCHL": "SCHL",
    "SCI": "SCI", "SCII": "SCII", "SCKT": "SCKT", "SCL": "SCL", "SCLX": "SCLX", "SCM": "SCM",
    "SCNI": "SCNI", "SCNX": "SCNX", "SCOR": "SCOR", "SCPQ": "SCPQ", "SCSC": "SCSC", "SCTX": "SCTX",
    "SCWO": "SCWO", "SCYX": "SCYX", "SCZM": "SCZM", "SD": "SD", "SDA": "SDA", "SDEV": "SDEV",
    "SDGR": "SDGR", "SDHC": "SDHC", "SDHI": "SDHI", "SDOT": "SDOT", "SDRL": "SDRL", "SDST": "SDST",
    "SEAT": "SEAT", "SEB": "SEB", "SECZ": "SECZ", "SEED": "SEED", "SEER": "SEER", "SEG": "SEG",
    "SEGG": "SEGG", "SEI": "SEI", "SEIC": "SEIC", "SELF": "SELF", "SENEA": "SENEA", "SENEB": "SENEB",
    "SENS": "SENS", "SEPN": "SEPN", "SER": "SER", "SERA": "SERA", "SERV": "SERV", "SES": "SES",
    "SEV": "SEV", "SEVN": "SEVN", "SEZL": "SEZL", "SF": "SF", "SFBC": "SFBC", "SFBS": "SFBS",
    "SFD": "SFD", "SFHG": "SFHG", "SFIX": "SFIX", "SFL": "SFL", "SFM": "SFM", "SFNC": "SFNC",
    "SFST": "SFST", "SFWL": "SFWL", "SG": "SG", "SGA": "SGA", "SGC": "SGC", "SGHC": "SGHC",
    "SGHT": "SGHT", "SGI": "SGI", "SGLD": "SGLD", "SGLY": "SGLY", "SGML": "SGML", "SGMT": "SGMT",
    "SGP": "SGP", "SGRX": "SGRX", "SGRY": "SGRY", "SGU": "SGU", "SHAK": "SHAK", "SHAZ": "SHAZ",
    "SHBI": "SHBI", "SHC": "SHC", "SHEL": "SHEL", "SHEN": "SHEN", "SHFS": "SHFS", "SHG": "SHG",
    "SHIM": "SHIM", "SHIP": "SHIP", "SHLS": "SHLS", "SHMD": "SHMD", "SHO": "SHO", "SHOE": "SHOE",
    "SHOO": "SHOO", "SHOT": "SHOT", "SHPH": "SHPH", "SI": "SI", "SIBN": "SIBN", "SID": "SID",
    "SIDU": "SIDU", "SIEB": "SIEB", "SIF": "SIF", "SIFY": "SIFY", "SIG": "SIG", "SIGA": "SIGA",
    "SIGI": "SIGI", "SII": "SII", "SILC": "SILC", "SILO": "SILO", "SIM": "SIM", "SIMA": "SIMA",
    "SIMO": "SIMO", "SIND": "SIND", "SINT": "SINT", "SION": "SION", "SIRI": "SIRI", "SITC": "SITC",
    "SITE": "SITE", "SITM": "SITM", "SJ": "SJ", "SJT": "SJT", "SKE": "SKE", "SKHY": "SKHY",
    "SKIL": "SKIL", "SKIN": "SKIN", "SKK": "SKK", "SKM": "SKM", "SKT": "SKT", "SKWD": "SKWD",
    "SKY": "SKY", "SKYA": "SKYA", "SKYE": "SKYE", "SKYH": "SKYH", "SKYQ": "SKYQ", "SKYX": "SKYX",
    "SLAB": "SLAB", "SLBT": "SLBT", "SLDB": "SLDB", "SLDE": "SLDE", "SLDP": "SLDP", "SLE": "SLE",
    "SLF": "SLF", "SLG": "SLG", "SLGB": "SLGB", "SLGL": "SLGL", "SLGN": "SLGN", "SLI": "SLI",
    "SLM": "SLM", "SLMT": "SLMT", "SLN": "SLN", "SLND": "SLND", "SLNG": "SLNG", "SLNH": "SLNH",
    "SLP": "SLP", "SLQT": "SLQT", "SLS": "SLS", "SLSN": "SLSN", "SLSR": "SLSR", "SLVM": "SLVM",
    "SLXN": "SLXN", "SM": "SM", "SMA": "SMA", "SMBC": "SMBC", "SMBK": "SMBK", "SMC": "SMC",
    "SMG": "SMG", "SMHI": "SMHI", "SMID": "SMID", "SMJF": "SMJF", "SMMT": "SMMT", "SMP": "SMP",
    "SMPL": "SMPL", "SMR": "SMR", "SMRT": "SMRT", "SMSI": "SMSI", "SMTC": "SMTC", "SMTI": "SMTI",
    "SMTK": "SMTK", "SMWB": "SMWB", "SMX": "SMX", "SMXT": "SMXT", "SN": "SN", "SNA": "SNA",
    "SNAL": "SNAL", "SNAP": "SNAP", "SND": "SND", "SNDA": "SNDA", "SNDK": "SNDK", "SNDL": "SNDL",
    "SNDR": "SNDR", "SNDX": "SNDX", "SNES": "SNES", "SNEX": "SNEX", "SNFCA": "SNFCA", "SNGX": "SNGX",
    "SNN": "SNN", "SNOA": "SNOA", "SNSC": "SNSC", "SNT": "SNT", "SNTG": "SNTG", "SNTI": "SNTI",
    "SNWV": "SNWV", "SNX": "SNX", "SNY": "SNY", "SOAR": "SOAR", "SOBO": "SOBO", "SOC": "SOC",
    "SOCA": "SOCA", "SOGP": "SOGP", "SOHU": "SOHU", "SOLS": "SOLS", "SOLV": "SOLV", "SON": "SON",
    "SONM": "SONM", "SONO": "SONO", "SOPH": "SOPH", "SOR": "SOR", "SORA": "SORA", "SORN": "SORN",
    "SOS": "SOS", "SOTK": "SOTK", "SOUL": "SOUL", "SOUN": "SOUN", "SOWG": "SOWG", "SPAI": "SPAI",
    "SPB": "SPB", "SPCB": "SPCB", "SPCE": "SPCE", "SPEG": "SPEG", "SPFI": "SPFI", "SPH": "SPH",
    "SPHL": "SPHL", "SPHR": "SPHR", "SPIR": "SPIR", "SPKL": "SPKL", "SPMC": "SPMC", "SPNT": "SPNT",
    "SPOK": "SPOK", "SPPL": "SPPL", "SPRB": "SPRB", "SPRC": "SPRC", "SPRO": "SPRO", "SPRU": "SPRU",
    "SPRY": "SPRY", "SPSC": "SPSC", "SPT": "SPT", "SPTX": "SPTX", "SPWH": "SPWH", "SPWR": "SPWR",
    "SPXC": "SPXC", "SQFT": "SQFT", "SQNS": "SQNS", "SR": "SR", "SRAD": "SRAD", "SRBK": "SRBK",
    "SRCE": "SRCE", "SRFM": "SRFM", "SRG": "SRG", "SRI": "SRI", "SRL": "SRL", "SRPT": "SRPT",
    "SRRK": "SRRK", "SRTA": "SRTA", "SRTS": "SRTS", "SRXH": "SRXH", "SRZN": "SRZN", "SSAC": "SSAC",
    "SSB": "SSB", "SSBI": "SSBI", "SSD": "SSD", "SSEA": "SSEA", "SSII": "SSII", "SSL": "SSL",
    "SSM": "SSM", "SSMR": "SSMR", "SSNC": "SSNC", "SSP": "SSP", "SSRM": "SSRM", "SST": "SST",
    "SSTI": "SSTI", "SSTK": "SSTK", "SSYS": "SSYS", "ST": "ST", "STAA": "STAA", "STAG": "STAG",
    "STAK": "STAK", "STBA": "STBA", "STC": "STC", "STDN": "STDN", "STE": "STE", "STEM": "STEM",
    "STEP": "STEP", "STEX": "STEX", "STFS": "STFS", "STG": "STG", "STGW": "STGW", "STHO": "STHO",
    "STI": "STI", "STIM": "STIM", "STKE": "STKE", "STKH": "STKH", "STKS": "STKS", "STLA": "STLA",
    "STLN": "STLN", "STM": "STM", "STN": "STN", "STNE": "STNE", "STNG": "STNG", "STOK": "STOK",
    "STRA": "STRA", "STRL": "STRL", "STRO": "STRO", "STRR": "STRR", "STRT": "STRT", "STRW": "STRW",
    "STRZ": "STRZ", "STT-G": "STT-G", "STTK": "STTK", "STUB": "STUB", "STVN": "STVN", "STWD": "STWD",
    "STX": "STX", "STXS": "STXS", "SU": "SU", "SUGP": "SUGP", "SUI": "SUI", "SUIG": "SUIG",
    "SUJA": "SUJA", "SUMA": "SUMA", "SUNB": "SUNB", "SUNE": "SUNE", "SUNS": "SUNS", "SUPN": "SUPN",
    "SUPV": "SUPV", "SUPX": "SUPX", "SURG": "SURG", "SUZ": "SUZ", "SVA": "SVA", "SVAQ": "SVAQ",
    "SVC": "SVC", "SVCC": "SVCC", "SVCO": "SVCO", "SVIA": "SVIA", "SVIV": "SVIV", "SVM": "SVM",
    "SVRA": "SVRA", "SVRE": "SVRE", "SVRN": "SVRN", "SVV": "SVV", "SW": "SW", "SWAG": "SWAG",
    "SWBI": "SWBI", "SWIM": "SWIM", "SWK": "SWK", "SWKS": "SWKS", "SWMR": "SWMR", "SWRD": "SWRD",
    "SWVL": "SWVL", "SWX": "SWX", "SXC": "SXC", "SXI": "SXI", "SXT": "SXT", "SXTC": "SXTC",
    "SXTP": "SXTP", "SY": "SY", "SYBT": "SYBT", "SYF": "SYF", "SYM": "SYM", "SYNA": "SYNA",
    "SYNX": "SYNX", "SYPR": "SYPR", "SYRE": "SYRE", "SYY": "SYY", "SZZL": "SZZL", "TAC": "TAC",
    "TACH": "TACH", "TACO": "TACO", "TACT": "TACT", "TAK": "TAK", "TAL": "TAL", "TALO": "TALO",
    "TANH": "TANH", "TAOP": "TAOP", "TAOX": "TAOX", "TAP-A": "TAP-A", "TARA": "TARA", "TARS": "TARS",
    "TASK": "TASK", "TATT": "TATT", "TAVI": "TAVI", "TAYD": "TAYD", "TBBB": "TBBB", "TBBK": "TBBK",
    "TBCH": "TBCH", "TBI": "TBI", "TBLA": "TBLA", "TBN": "TBN", "TC": "TC", "TCBI": "TCBI",
    "TCBK": "TCBK", "TCBS": "TCBS", "TCBX": "TCBX", "TCGX": "TCGX", "TCI": "TCI", "TCMD": "TCMD",
    "TCRT": "TCRT", "TCRX": "TCRX", "TCX": "TCX", "TD": "TD", "TDAC": "TDAC", "TDAY": "TDAY",
    "TDC": "TDC", "TDIC": "TDIC", "TDOC": "TDOC", "TDS": "TDS", "TDTH": "TDTH", "TDUP": "TDUP",
    "TDW": "TDW", "TDWD": "TDWD", "TE": "TE", "TEAD": "TEAD", "TECK": "TECK", "TECX": "TECX",
    "TEL": "TEL", "TELA": "TELA", "TELO": "TELO", "TEM": "TEM", "TEN": "TEN", "TENB": "TENB",
    "TENX": "TENX", "TEO": "TEO", "TER": "TER", "TEVA": "TEVA", "TEX": "TEX", "TFC-I": "TFC-I",
    "TFII": "TFII", "TFIN": "TFIN", "TFPM": "TFPM", "TFSL": "TFSL", "TFX": "TFX", "TG": "TG",
    "TGB": "TGB", "TGE": "TGE", "TGEN": "TGEN", "TGHL": "TGHL", "TGL": "TGL", "TGLS": "TGLS",
    "TGS": "TGS", "TGTX": "TGTX", "TH": "TH", "THC": "THC", "THCH": "THCH", "THEO": "THEO",
    "THFF": "THFF", "THG": "THG", "THH": "THH", "THM": "THM", "THO": "THO", "THRM": "THRM",
    "THRY": "THRY", "TIC": "TIC", "TIGO": "TIGO", "TIGR": "TIGR", "TII": "TII", "TIL": "TIL",
    "TILE": "TILE", "TIMB": "TIMB", "TIPT": "TIPT", "TISI": "TISI", "TITN": "TITN", "TJGC": "TJGC",
    "TK": "TK", "TKC": "TKC", "TKLF": "TKLF", "TKNO": "TKNO", "TKO": "TKO", "TKR": "TKR",
    "TLAC": "TLAC", "TLF": "TLF", "TLIH": "TLIH", "TLK": "TLK", "TLN": "TLN", "TLNC": "TLNC",
    "TLPH": "TLPH", "TLRY": "TLRY", "TLS": "TLS", "TLSA": "TLSA", "TLSI": "TLSI", "TLX": "TLX",
    "TLYS": "TLYS", "TMC": "TMC", "TMCI": "TMCI", "TMCR": "TMCR", "TMDE": "TMDE", "TMDX": "TMDX",
    "TME": "TME", "TMP": "TMP", "TMQ": "TMQ", "TMS": "TMS", "TMTS": "TMTS", "TNC": "TNC",
    "TNDM": "TNDM", "TNET": "TNET", "TNGX": "TNGX", "TNK": "TNK", "TNL": "TNL", "TNMG": "TNMG",
    "TNON": "TNON", "TNXP": "TNXP", "TNYA": "TNYA", "TOL": "TOL", "TOMZ": "TOMZ", "TONT": "TONT",
    "TONX": "TONX", "TOON": "TOON", "TOP": "TOP", "TOPP": "TOPP", "TOPS": "TOPS", "TORO": "TORO",
    "TOST": "TOST", "TOUR": "TOUR", "TOVX": "TOVX", "TOWN": "TOWN", "TOYO": "TOYO", "TP": "TP",
    "TPB": "TPB", "TPC": "TPC", "TPCS": "TPCS", "TPET": "TPET", "TPG": "TPG", "TPL": "TPL",
    "TPST": "TPST", "TPVG": "TPVG", "TR": "TR", "TRAD": "TRAD", "TRAK": "TRAK", "TRAW": "TRAW",
    "TRAX": "TRAX", "TRBG": "TRBG", "TRC": "TRC", "TRDA": "TRDA", "TREE": "TREE", "TREO": "TREO",
    "TREX": "TREX", "TRGP": "TRGP", "TRGS": "TRGS", "TRI": "TRI", "TRIB": "TRIB", "TRIN": "TRIN",
    "TRIP": "TRIP", "TRLV": "TRLV", "TRMD": "TRMD", "TRMK": "TRMK", "TRN": "TRN", "TRNO": "TRNO",
    "TRNR": "TRNR", "TRNS": "TRNS", "TRON": "TRON", "TROO": "TROO", "TROX": "TROX", "TRP": "TRP",
    "TRS": "TRS", "TRSG": "TRSG", "TRST": "TRST", "TRT": "TRT", "TRTX": "TRTX", "TRU": "TRU",
    "TRUG": "TRUG", "TRUP": "TRUP", "TRVG": "TRVG", "TRVI": "TRVI", "TRX": "TRX", "TS": "TS",
    "TSAT": "TSAT", "TSBK": "TSBK", "TSCO": "TSCO", "TSEM": "TSEM", "TSHA": "TSHA", "TSLX": "TSLX",
    "TSQ": "TSQ", "TSSI": "TSSI", "TT": "TT", "TTAM": "TTAM", "TTAN": "TTAN", "TTC": "TTC",
    "TTD": "TTD", "TTE": "TTE", "TTEC": "TTEC", "TTEK": "TTEK", "TTGT": "TTGT", "TTI": "TTI",
    "TTMI": "TTMI", "TTRX": "TTRX", "TTWO": "TTWO", "TU": "TU", "TULP": "TULP", "TURB": "TURB",
    "TUSK": "TUSK", "TUYA": "TUYA", "TV": "TV", "TVA": "TVA", "TVAI": "TVAI", "TVC": "TVC",
    "TVE": "TVE", "TVGN": "TVGN", "TVIV": "TVIV", "TVRD": "TVRD", "TVTX": "TVTX", "TW": "TW",
    "TWAV": "TWAV", "TWFG": "TWFG", "TWG": "TWG", "TWI": "TWI", "TWIN": "TWIN", "TWLO": "TWLO",
    "TWLV": "TWLV", "TWST": "TWST", "TX": "TX", "TXG": "TXG", "TXMD": "TXMD", "TXNM": "TXNM",
    "TXT": "TXT", "TY": "TY", "TYG": "TYG", "TYGO": "TYGO", "TYL": "TYL", "TYRA": "TYRA",
    "TZOO": "TZOO", "U": "U", "UA": "UA", "UAA": "UAA", "UAC": "UAC", "UAMY": "UAMY",
    "UAVS": "UAVS", "UBCP": "UBCP", "UBSI": "UBSI", "UCAR": "UCAR", "UCB": "UCB", "UCFI": "UCFI",
    "UCL": "UCL", "UCTT": "UCTT", "UDR": "UDR", "UE": "UE", "UEC": "UEC", "UEIC": "UEIC",
    "UFCS": "UFCS", "UFG": "UFG", "UFI": "UFI", "UFPI": "UFPI", "UFPT": "UFPT", "UG": "UG",
    "UGI": "UGI", "UGP": "UGP", "UHAL": "UHAL", "UHAL-B": "UHAL-B", "UHT": "UHT", "UI": "UI",
    "UIS": "UIS", "UK": "UK", "UL": "UL", "ULBI": "ULBI", "ULCC": "ULCC", "ULH": "ULH",
    "ULS": "ULS", "UMAC": "UMAC", "UMBF": "UMBF", "UMC": "UMC", "UMH": "UMH", "UNB": "UNB",
    "UNCY": "UNCY", "UNF": "UNF", "UNFI": "UNFI", "UNIT": "UNIT", "UNM": "UNM", "UNTY": "UNTY",
    "UONE": "UONE", "UONEK": "UONEK", "UP": "UP", "UPB": "UPB", "UPBD": "UPBD", "UPC": "UPC",
    "UPLD": "UPLD", "UPST": "UPST", "UPWK": "UPWK", "UPXI": "UPXI", "URBN": "URBN", "URG": "URG",
    "URGN": "URGN", "UROY": "UROY", "USAR": "USAR", "USAS": "USAS", "USAU": "USAU", "USB-A": "USB-A",
    "USB-H": "USB-H", "USBC": "USBC", "USCB": "USCB", "USDE": "USDE", "USEA": "USEA", "USFD": "USFD",
    "USGO": "USGO", "USIO": "USIO", "USLM": "USLM", "USNA": "USNA", "USPH": "USPH", "UTHR": "UTHR",
    "UTI": "UTI", "UTL": "UTL", "UTMD": "UTMD", "UTSI": "UTSI", "UTZ": "UTZ", "UUU": "UUU",
    "UUUU": "UUUU", "UVE": "UVE", "UVSP": "UVSP", "UVV": "UVV", "UWMC": "UWMC", "UXIN": "UXIN",
    "UYSC": "UYSC", "UZX": "UZX", "VABK": "VABK", "VAC": "VAC", "VACI": "VACI", "VAI": "VAI",
    "VAL": "VAL", "VALE": "VALE", "VALN": "VALN", "VALU": "VALU", "VANI": "VANI", "VATE": "VATE",
    "VBIO": "VBIO", "VBNK": "VBNK", "VC": "VC", "VCEL": "VCEL", "VCIG": "VCIG", "VCRE": "VCRE",
    "VCTR": "VCTR", "VCV": "VCV", "VCYT": "VCYT", "VECA": "VECA", "VECO": "VECO", "VEEA": "VEEA",
    "VEEE": "VEEE", "VEEV": "VEEV", "VEL": "VEL", "VELO": "VELO", "VENU": "VENU", "VEON": "VEON",
    "VERA": "VERA", "VERI": "VERI", "VERU": "VERU", "VERX": "VERX", "VET": "VET", "VFC": "VFC",
    "VFF": "VFF", "VFS": "VFS", "VG": "VG", "VGAS": "VGAS", "VGM": "VGM", "VGNT": "VGNT",
    "VGZ": "VGZ", "VHC": "VHC", "VHCP": "VHCP", "VHI": "VHI", "VHUB": "VHUB", "VIA": "VIA",
    "VIAV": "VIAV", "VICI": "VICI", "VICR": "VICR", "VIDA": "VIDA", "VII": "VII", "VIK": "VIK",
    "VINP": "VINP", "VIOT": "VIOT", "VIP": "VIP", "VIPS": "VIPS", "VIR": "VIR", "VIRC": "VIRC",
    "VIRT": "VIRT", "VISN": "VISN", "VIST": "VIST", "VITL": "VITL", "VIV": "VIV", "VIVK": "VIVK",
    "VIVO": "VIVO", "VIVS": "VIVS", "VKI": "VKI", "VKQ": "VKQ", "VKTX": "VKTX", "VLGEA": "VLGEA",
    "VLN": "VLN", "VLO": "VLO", "VLOS": "VLOS", "VLRS": "VLRS", "VLT": "VLT", "VLTO": "VLTO",
    "VLY": "VLY", "VMAR": "VMAR", "VMC": "VMC", "VMD": "VMD", "VMET": "VMET", "VMI": "VMI",
    "VMO": "VMO", "VMRK": "VMRK", "VNCE": "VNCE", "VNDA": "VNDA", "VNET": "VNET", "VNME": "VNME",
    "VNO": "VNO", "VNOM": "VNOM", "VNRX": "VNRX", "VNT": "VNT", "VNTG": "VNTG", "VOD": "VOD",
    "VOGX": "VOGX", "VOR": "VOR", "VOXR": "VOXR", "VOYA": "VOYA", "VOYG": "VOYG", "VPG": "VPG",
    "VPV": "VPV", "VRA": "VRA", "VRAX": "VRAX", "VRCA": "VRCA", "VRDN": "VRDN", "VREX": "VREX",
    "VRM": "VRM", "VRME": "VRME", "VRNS": "VRNS", "VRRM": "VRRM", "VRSK": "VRSK", "VRSN": "VRSN",
    "VRTS": "VRTS", "VRXA": "VRXA", "VS": "VS", "VSA": "VSA", "VSAT": "VSAT", "VSEC": "VSEC",
    "VSH": "VSH", "VSME": "VSME", "VSNT": "VSNT", "VST": "VST", "VSTM": "VSTM", "VSTS": "VSTS",
    "VSXY": "VSXY", "VTAK": "VTAK", "VTEX": "VTEX", "VTGN": "VTGN", "VTIX": "VTIX", "VTMX": "VTMX",
    "VTN": "VTN", "VTOL": "VTOL", "VTRS": "VTRS", "VTS": "VTS", "VTSI": "VTSI", "VTVT": "VTVT",
    "VUZI": "VUZI", "VVOS": "VVOS", "VVR": "VVR", "VVV": "VVV", "VVX": "VVX", "VWAV": "VWAV",
    "VYGR": "VYGR", "VYX": "VYX", "VZLA": "VZLA", "WABC": "WABC", "WAFD": "WAFD", "WAFDP": "WAFDP",
    "WAFU": "WAFU", "WAL": "WAL", "WALD": "WALD", "WASH": "WASH", "WAT": "WAT", "WATR": "WATR",
    "WATT": "WATT", "WAVE": "WAVE", "WAY": "WAY", "WB": "WB", "WBD": "WBD", "WBI": "WBI",
    "WBTN": "WBTN", "WBUY": "WBUY", "WBX": "WBX", "WCC": "WCC", "WCCB": "WCCB", "WCT": "WCT",
    "WD": "WD", "WDC": "WDC", "WDFC": "WDFC", "WDS": "WDS", "WEAV": "WEAV", "WEC": "WEC",
    "WEN": "WEN", "WENC": "WENC", "WENN": "WENN", "WERN": "WERN", "WEST": "WEST", "WETH": "WETH",
    "WETO": "WETO", "WEX": "WEX", "WEYS": "WEYS", "WF": "WF", "WFCF": "WFCF", "WFF": "WFF",
    "WFG": "WFG", "WFRD": "WFRD", "WGO": "WGO", "WGS": "WGS", "WH": "WH", "WHD": "WHD",
    "WHG": "WHG", "WHK": "WHK", "WHLR": "WHLR", "WHR": "WHR", "WHWK": "WHWK", "WIMI": "WIMI",
    "WINA": "WINA", "WING": "WING", "WIT": "WIT", "WIX": "WIX", "WK": "WK", "WKC": "WKC",
    "WKEY": "WKEY", "WKHS": "WKHS", "WKSP": "WKSP", "WLCO": "WLCO", "WLDN": "WLDN", "WLDS": "WLDS",
    "WLFC": "WLFC", "WLII": "WLII", "WLK": "WLK", "WLTH": "WLTH", "WLY": "WLY", "WLYB": "WLYB",
    "WMB": "WMB", "WMG": "WMG", "WMK": "WMK", "WMS": "WMS", "WNC": "WNC", "WNEB": "WNEB",
    "WNW": "WNW", "WOK": "WOK", "WOOF": "WOOF", "WOR": "WOR", "WPAC": "WPAC", "WPC": "WPC",
    "WPM": "WPM", "WPP": "WPP", "WPRT": "WPRT", "WRAP": "WRAP", "WRB": "WRB", "WRBY": "WRBY",
    "WRD": "WRD", "WRLD": "WRLD", "WRN": "WRN", "WS": "WS", "WSBC": "WSBC", "WSBF": "WSBF",
    "WSBK": "WSBK", "WSC": "WSC", "WSE": "WSE", "WSFS": "WSFS", "WSHP": "WSHP", "WSM": "WSM",
    "WSO": "WSO", "WSO-B": "WSO-B", "WST": "WST", "WSTN": "WSTN", "WT": "WT", "WTBA": "WTBA",
    "WTF": "WTF", "WTFC": "WTFC", "WTG": "WTG", "WTI": "WTI", "WTM": "WTM", "WTRG": "WTRG",
    "WTS": "WTS", "WTTR": "WTTR", "WU": "WU", "WULF": "WULF", "WVE": "WVE", "WVVI": "WVVI",
    "WW": "WW", "WWD": "WWD", "WWR": "WWR", "WWW": "WWW", "WXM": "WXM", "WY": "WY",
    "WYFI": "WYFI", "WYHG": "WYHG", "WYY": "WYY", "XAIR": "XAIR", "XBIO": "XBIO", "XBIT": "XBIT",
    "XBP": "XBP", "XCBE": "XCBE", "XCH": "XCH", "XCUR": "XCUR", "XE": "XE", "XELB": "XELB",
    "XENE": "XENE", "XERS": "XERS", "XFLH": "XFLH", "XFLT": "XFLT", "XFOR": "XFOR", "XGN": "XGN",
    "XHG": "XHG", "XHLD": "XHLD", "XHR": "XHR", "XIII": "XIII", "XLAB": "XLAB", "XLO": "XLO",
    "XMAX": "XMAX", "XMTR": "XMTR", "XNCR": "XNCR", "XNDU": "XNDU", "XNET": "XNET", "XOS": "XOS",
    "XP": "XP", "XPEL": "XPEL", "XPER": "XPER", "XPL": "XPL", "XPOF": "XPOF", "XPON": "XPON",
    "XPRO": "XPRO", "XRAY": "XRAY", "XRN": "XRN", "XRPN": "XRPN", "XRTX": "XRTX", "XRX": "XRX",
    "XSLL": "XSLL", "XTER": "XTER", "XTIA": "XTIA", "XTLB": "XTLB", "XTND": "XTND", "XTNT": "XTNT",
    "XWEL": "XWEL", "XXI": "XXI", "XXII": "XXII", "XYF": "XYF", "XYL": "XYL", "XYZ": "XYZ",
    "XZO": "XZO", "YAAS": "YAAS", "YALA": "YALA", "YARW": "YARW", "YB": "YB", "YCBD": "YCBD",
    "YCY": "YCY", "YDDL": "YDDL", "YDES": "YDES", "YDKG": "YDKG", "YELP": "YELP", "YETI": "YETI",
    "YEXT": "YEXT", "YFOR": "YFOR", "YHC": "YHC", "YHGJ": "YHGJ", "YHNA": "YHNA", "YI": "YI",
    "YIBO": "YIBO", "YICC": "YICC", "YJ": "YJ", "YMAT": "YMAT", "YMM": "YMM", "YMT": "YMT",
    "YORW": "YORW", "YOU": "YOU", "YOUL": "YOUL", "YPF": "YPF", "YQ": "YQ", "YRD": "YRD",
    "YSG": "YSG", "YSS": "YSS", "YSWY": "YSWY", "YSXT": "YSXT", "YTRA": "YTRA", "YUMC": "YUMC",
    "YXT": "YXT", "YYAI": "YYAI", "Z": "Z", "ZBAO": "ZBAO", "ZBIO": "ZBIO", "ZBRA": "ZBRA",
    "ZCMD": "ZCMD", "ZD": "ZD", "ZDAI": "ZDAI", "ZDGE": "ZDGE", "ZENA": "ZENA", "ZEO": "ZEO",
    "ZEPP": "ZEPP", "ZETA": "ZETA", "ZG": "ZG", "ZGN": "ZGN", "ZH": "ZH", "ZIM": "ZIM",
    "ZION": "ZION", "ZIP": "ZIP", "ZJK": "ZJK", "ZJYL": "ZJYL", "ZKH": "ZKH", "ZKIN": "ZKIN",
    "ZKP": "ZKP", "ZLAB": "ZLAB", "ZNB": "ZNB", "ZNTL": "ZNTL", "ZONE": "ZONE", "ZOOZ": "ZOOZ",
    "ZSQR": "ZSQR", "ZSTK": "ZSTK", "ZTG": "ZTG", "ZTO": "ZTO", "ZTS": "ZTS", "ZUMZ": "ZUMZ",
    "ZURA": "ZURA", "ZVIA": "ZVIA", "ZVRA": "ZVRA", "ZWS": "ZWS", "ZYBT": "ZYBT", "ZYME": "ZYME",
}
