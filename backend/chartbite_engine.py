import datetime

import numpy as np
import pandas as pd
from motor.motor_asyncio import AsyncIOMotorDatabase


class SignalAndTPTrackerEngine:
    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str = "active_trades"):
        self.collection = db[collection_name]

    # =========================================================================
    # 1. FORMULA & ENTRY GATE (Mengevaluasi Sinyal, MTF Zone, dan Target TP/SL)
    # =========================================================================
    def generate_validated_signal(
        self,
        ticker: str,
        df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        raw_signal: str,  # 'LONG' atau 'SHORT' dari indikator utama Anda
        atr_multiplier: float = 1.5,
    ) -> dict | None:
        """
        Menggabungkan Formula (EMA MTF + ATR) dan Gate (Multi-Condition + Anti-Repaint).
        Mengembalikan dict sinyal siap simpan ke MongoDB jika lolos gate, atau None jika ditolak.
        """
        if len(df) < 15 or len(mtf_df) < 50 or raw_signal not in ["LONG", "SHORT"]:
            return None

        # --- FORMULA: Hitung ATR(14) ---
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()

        # --- FORMULA: Klasifikasi Tren MTF (EMA 20 & EMA 50) ---
        ema_fast = mtf_df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        ema_slow = mtf_df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        mtf_close = mtf_df["close"].iloc[-1]

        if mtf_close > ema_fast > ema_slow:
            mtf_status = "FULL_BULLISH"
        elif mtf_close > ema_slow:
            mtf_status = "BULLISH"
        elif mtf_close < ema_fast < ema_slow:
            mtf_status = "FULL_BEARISH"
        elif mtf_close < ema_slow:
            mtf_status = "BEARISH"
        else:
            mtf_status = "MIXED"

        # --- GATE 1: Anti-Repaint (Ambil bar ke -2 yang sudah close) ---
        confirmed_bar = df.iloc[-2]
        entry_price = float(confirmed_bar["close"])
        atr = float(confirmed_bar["atr"])

        if np.isnan(atr) or atr == 0:
            return None

        # --- GATE 2: Multi-Condition Filter (Sinyal harus searah MTF Zone) ---
        if raw_signal == "LONG" and mtf_status in ["BULLISH", "FULL_BULLISH"]:
            sl = round(entry_price - (atr_multiplier * atr), 4)
            tp1 = round(entry_price + (1.0 * atr), 4)
            tp2 = round(entry_price + (2.0 * atr), 4)
            tp3 = round(entry_price + (3.0 * atr), 4)
        elif raw_signal == "SHORT" and mtf_status in ["BEARISH", "FULL_BEARISH"]:
            sl = round(entry_price + (atr_multiplier * atr), 4)
            tp1 = round(entry_price - (1.0 * atr), 4)
            tp2 = round(entry_price - (2.0 * atr), 4)
            tp3 = round(entry_price - (3.0 * atr), 4)
        else:
            # Ditolak oleh Gate MTF
            return None

        # Format dokumen siap insert ke MongoDB
        return {
            "ticker": ticker,
            "action": raw_signal,
            "mtf_zone": mtf_status,
            "entry_price": round(entry_price, 4),
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "tp1_hit": False,
            "tp2_hit": False,
            "tp3_hit": False,
            "status": "ACTIVE",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }

    # =========================================================================
    # 2. SAVE SIGNAL KE MONGODB
    # =========================================================================
    async def save_new_signal(self, signal_doc: dict) -> str:
        result = await self.collection.insert_one(signal_doc)
        return str(result.inserted_id)

    # =========================================================================
    # 3. REAL-TIME TP HIT & SL TRACKER (Dipanggil di dalam Loop WebSocket)
    # =========================================================================
    async def process_realtime_tick(
        self, ticker: str, current_price: float, ws_broadcast_callback
    ):
        """
        Memantau pergerakan harga live WebSocket terhadap trade ACTIVE di MongoDB.
        Menggunakan State Gate (tpX_hit) agar notifikasi hanya terkirim 1x per target.
        """
        cursor = self.collection.find({"ticker": ticker, "status": "ACTIVE"})
        async for trade in cursor:
            trade_id = trade["_id"]
            action = trade["action"]
            update_fields = {}
            alerts = []

            if action == "LONG":
                # Cek Stop Loss terlebih dahulu
                if current_price <= trade["sl"]:
                    update_fields["status"] = "STOPPED_OUT"
                    alerts.append(("SL_HIT", f"Stop Loss hit on {ticker} at {current_price}"))
                else:
                    if not trade.get("tp1_hit", False) and current_price >= trade["tp1"]:
                        update_fields["tp1_hit"] = True
                        alerts.append(("TP1_HIT", f"TP1 hit on {ticker} at {current_price}"))
                    if not trade.get("tp2_hit", False) and current_price >= trade["tp2"]:
                        update_fields["tp2_hit"] = True
                        alerts.append(("TP2_HIT", f"TP2 hit on {ticker} at {current_price}"))
                    if not trade.get("tp3_hit", False) and current_price >= trade["tp3"]:
                        update_fields["tp3_hit"] = True
                        update_fields["status"] = "COMPLETED"
                        alerts.append(("TP3_HIT", f"TP3 (Final Target) hit on {ticker} at {current_price}"))

            elif action == "SHORT":
                if current_price >= trade["sl"]:
                    update_fields["status"] = "STOPPED_OUT"
                    alerts.append(("SL_HIT", f"Stop Loss hit on {ticker} at {current_price}"))
                else:
                    if not trade.get("tp1_hit", False) and current_price <= trade["tp1"]:
                        update_fields["tp1_hit"] = True
                        alerts.append(("TP1_HIT", f"TP1 hit on {ticker} at {current_price}"))
                    if not trade.get("tp2_hit", False) and current_price <= trade["tp2"]:
                        update_fields["tp2_hit"] = True
                        alerts.append(("TP2_HIT", f"TP2 hit on {ticker} at {current_price}"))
                    if not trade.get("tp3_hit", False) and current_price <= trade["tp3"]:
                        update_fields["tp3_hit"] = True
                        update_fields["status"] = "COMPLETED"
                        alerts.append(("TP3_HIT", f"TP3 (Final Target) hit on {ticker} at {current_price}"))

            # Update MongoDB & Broadcast via WebSocket jika ada target/SL tersentuh
            if update_fields:
                update_fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
                await self.collection.update_one(
                    {"_id": trade_id}, {"$set": update_fields}
                )
                for event_type, message in alerts:
                    payload = {
                        "event": event_type,
                        "trade_id": str(trade_id),
                        "ticker": ticker,
                        "action": action,
                        "price": current_price,
                        "message": message,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                    await ws_broadcast_callback(ticker, payload)
