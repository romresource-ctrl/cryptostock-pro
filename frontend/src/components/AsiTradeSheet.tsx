/**
 * v9.3.0 — ASI-Bot Trade Sheet.
 *
 * Bottom sheet yang menerima sinyal (dari AI Suggestions atau Asset
 * Detail) dan menampilkan preview trade dengan parameter editable.
 * Satu tap "EXECUTE TRADE" mengirim bracket order ke exchange user.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Alert, Modal, Pressable, ScrollView, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, formatPrice, type AsiCredential, type AsiPreview,
} from "@/src/lib/api";

const GOLD = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";

export type AsiTradeIntent = {
  symbol: string;              // e.g. "BTC", "ETH"
  side: "BUY" | "SELL";
  entry: number;
  stop_loss: number;
  take_profits: number[];      // [tp1, tp2, tp3]
  source?: "ai-suggestions" | "asset-detail";
};

type Props = {
  visible: boolean;
  onClose: () => void;
  intent: AsiTradeIntent | null;
};

export default function AsiTradeSheet({ visible, onClose, intent }: Props) {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const [deviceId, setDeviceId] = useState("");
  const [creds, setCreds] = useState<AsiCredential[]>([]);
  const [exchange, setExchange] = useState<"binance" | "bybit" | "okx" | "bitget">("binance");
  const [riskPct, setRiskPct] = useState(5);
  const [leverage, setLeverage] = useState(10);
  const [preview, setPreview] = useState<AsiPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);

  useEffect(() => {
    if (!visible || !intent) return;
    (async () => {
      const did = await getDeviceId();
      setDeviceId(did);
      try {
        const r = await api.asi.listCredentials(did);
        setCreds(r.items);
        if (r.items.length > 0) {
          setExchange(r.items[0].exchange as any);
        }
      } catch {}
    })();
  }, [visible, intent]);

  useEffect(() => {
    if (!visible || !intent || !deviceId || creds.length === 0) {
      setPreview(null);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const p = await api.asi.previewTrade(deviceId, {
          exchange, symbol: intent.symbol, side: intent.side,
          entry: intent.entry, stop_loss: intent.stop_loss,
          take_profits: intent.take_profits.slice(0, 3),
          risk_pct: riskPct, leverage,
        });
        setPreview(p);
      } catch (e: any) {
        setPreview({ ok: false, message: e?.message || "Preview gagal",
                     balance_usdt: 0, margin_usdt: 0, size_usdt: 0, qty: 0,
                     leverage, risk_pct: riskPct, est_loss_usdt: 0, tp_estimations: [] });
      } finally { setLoading(false); }
    }, 250);
    return () => clearTimeout(t);
  }, [visible, intent, deviceId, exchange, riskPct, leverage, creds.length]);

  const activeCred = useMemo(
    () => creds.find((c) => c.exchange === exchange),
    [creds, exchange],
  );

  const execute = async () => {
    if (!intent || !preview?.ok) return;
    setExecuting(true);
    try {
      const res = await api.asi.executeTrade(deviceId, {
        exchange, symbol: intent.symbol, side: intent.side,
        entry: intent.entry, stop_loss: intent.stop_loss,
        take_profits: intent.take_profits.slice(0, 3),
        risk_pct: riskPct, leverage, mode: "semi",
      });
      Alert.alert(
        "✅ Order Terkirim",
        `${intent.side} ${intent.symbol} @ ${res.entry_price?.toFixed?.(6) ?? intent.entry}\n` +
        `Qty: ${res.qty} · Leverage: ${res.leverage}x\n` +
        `${res.testnet ? "TESTNET" : "MAINNET"}`,
      );
      onClose();
    } catch (e: any) {
      Alert.alert("Gagal Eksekusi", e?.message || String(e));
    } finally { setExecuting(false); }
  };

  if (!intent) return null;
  const sideColor = intent.side === "BUY" ? GREEN : RED;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.backdrop} onPress={onClose}>
        <Pressable style={[s.sheet, { backgroundColor: colors.surface, paddingBottom: insets.bottom + 16 }]}
                   onPress={(e) => e.stopPropagation()}>
          <ScrollView showsVerticalScrollIndicator={false}>
            {/* Header */}
            <View style={s.header}>
              <View style={[s.sideBadge, { backgroundColor: sideColor }]}>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 11, letterSpacing: 1 }}>
                  {intent.side === "BUY" ? "LONG" : "SHORT"}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.title, { color: colors.textPrimary }]}>{intent.symbol}</Text>
                <Text style={[s.caption, { color: colors.textMuted }]}>Trade dengan ASI-Bot (Semi-Auto)</Text>
              </View>
              <TouchableOpacity onPress={onClose} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.textMuted} />
              </TouchableOpacity>
            </View>

            {/* No credential state */}
            {creds.length === 0 ? (
              <View style={[s.empty, { backgroundColor: colors.background }]}>
                <Text style={{ fontSize: 36 }}>🔌</Text>
                <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 14, marginTop: 10 }}>
                  Belum terhubung ke exchange
                </Text>
                <Text style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", lineHeight: 18, marginTop: 6 }}>
                  Hubungkan API Binance / Bybit / OKX / Bitget di halaman ASI-Bot sebelum trade otomatis.
                </Text>
                <TouchableOpacity
                  style={[s.cta, { backgroundColor: GOLD, marginTop: 14 }]}
                  onPress={() => { onClose(); router.push("/asi-bot" as never); }}>
                  <Text style={{ color: "#0B0E11", fontWeight: "900", letterSpacing: 0.6 }}>HUBUNGKAN EXCHANGE</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <>
                {/* Exchange picker */}
                <View style={{ flexDirection: "row", gap: 6, marginTop: 10 }}>
                  {creds.map((c) => {
                    const act = c.exchange === exchange;
                    return (
                      <TouchableOpacity key={c.exchange} onPress={() => setExchange(c.exchange as any)}
                        style={[s.exChip, { backgroundColor: act ? GOLD : colors.background, borderColor: act ? GOLD : colors.border }]}>
                        <Text style={{ color: act ? "#0B0E11" : colors.textPrimary, fontWeight: "800", fontSize: 11 }}>
                          {c.exchange.toUpperCase()} {c.testnet ? "·T" : ""}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>

                {/* Level grid */}
                <View style={s.grid}>
                  <LevelCell label="ENTRY" value={formatPrice(intent.entry, "crypto")} color={colors.textPrimary} colors={colors} />
                  <LevelCell label="STOP LOSS" value={formatPrice(intent.stop_loss, "crypto")} color={RED} colors={colors} />
                  <LevelCell label="TP1" value={formatPrice(intent.take_profits[0] ?? NaN, "crypto")} color={GREEN} colors={colors} />
                  <LevelCell label="TP2" value={formatPrice(intent.take_profits[1] ?? NaN, "crypto")} color={GREEN} colors={colors} />
                  <LevelCell label="TP3" value={formatPrice(intent.take_profits[2] ?? NaN, "crypto")} color={GREEN} colors={colors} />
                  <LevelCell label="SIDE" value={intent.side === "BUY" ? "LONG" : "SHORT"} color={sideColor} colors={colors} />
                </View>

                {/* Risk & Leverage */}
                <StepperRow label="Risk per Trade" value={`${riskPct}%`} colors={colors}
                  onDec={() => setRiskPct(Math.max(1, riskPct - 1))}
                  onInc={() => setRiskPct(Math.min(30, riskPct + 1))} />
                <StepperRow label="Leverage" value={`${leverage}x`} colors={colors}
                  onDec={() => setLeverage(Math.max(1, leverage - 1))}
                  onInc={() => setLeverage(Math.min(125, leverage + 1))} />

                {/* Preview */}
                <View style={[s.preview, { backgroundColor: colors.background, borderColor: colors.border }]}>
                  {loading ? (
                    <Text style={{ color: colors.textMuted, fontSize: 12 }}>Menghitung preview...</Text>
                  ) : preview?.ok ? (
                    <>
                      <PreviewRow label="Saldo USDT" value={`$${preview.balance_usdt.toFixed(2)}`} colors={colors} />
                      <PreviewRow label="Margin Dipakai" value={`$${preview.margin_usdt.toFixed(2)}`} colors={colors} highlight />
                      <PreviewRow label="Ukuran Posisi" value={`$${preview.size_usdt.toFixed(2)} (${preview.qty.toFixed(6)})`} colors={colors} />
                      <PreviewRow label="Potensi Rugi (SL)" value={`-$${preview.est_loss_usdt.toFixed(2)}`} colors={colors} valueColor={RED} />
                      {preview.tp_estimations.map((t, i) => (
                        <PreviewRow key={i} label={`TP${i + 1} Profit (${Math.round(t.qty_share * 100)}%)`}
                                    value={`+$${t.est_profit_usdt.toFixed(2)}`} colors={colors} valueColor={GREEN} />
                      ))}
                    </>
                  ) : (
                    <Text style={{ color: RED, fontSize: 12 }}>
                      {preview?.message || "Preview belum tersedia."}
                    </Text>
                  )}
                </View>

                {/* Execute button */}
                <TouchableOpacity
                  onPress={execute}
                  disabled={executing || !preview?.ok}
                  style={[s.cta, {
                    backgroundColor: executing || !preview?.ok ? colors.textMuted : sideColor,
                    marginTop: 14,
                  }]}
                  testID="asi-trade-execute">
                  <Ionicons name="rocket" size={18} color="#0B0E11" />
                  <Text style={{ color: "#0B0E11", fontWeight: "900", letterSpacing: 0.8 }}>
                    {executing ? "MENGIRIM ORDER..." : `EXECUTE ${intent.side === "BUY" ? "LONG" : "SHORT"} ${activeCred?.testnet ? "(TESTNET)" : ""}`}
                  </Text>
                </TouchableOpacity>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, textAlign: "center", marginTop: 8, lineHeight: 16 }}>
                  Bracket SL + TP1/TP2/TP3 (split 40/30/30) otomatis terpasang.{"\n"}
                  Risiko slippage & kerugian pasar 100% tanggung jawab Anda.
                </Text>
              </>
            )}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function LevelCell({ label, value, color, colors }: any) {
  return (
    <View style={[s.cell, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <Text style={{ color: colors.textMuted, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 }}>{label}</Text>
      <Text style={{ color, fontSize: 13, fontWeight: "900", marginTop: 2 }}>{value}</Text>
    </View>
  );
}

function StepperRow({ label, value, onDec, onInc, colors }: any) {
  return (
    <View style={[s.stepRow, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{label}</Text>
      <View style={{ flex: 1 }} />
      <TouchableOpacity onPress={onDec} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="remove" size={14} color={colors.textPrimary} />
      </TouchableOpacity>
      <Text style={{ color: GOLD, fontWeight: "900", width: 70, textAlign: "center" }}>{value}</Text>
      <TouchableOpacity onPress={onInc} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="add" size={14} color={colors.textPrimary} />
      </TouchableOpacity>
    </View>
  );
}

function PreviewRow({ label, value, colors, valueColor, highlight }: any) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 4 }}>
      <Text style={{ color: colors.textMuted, fontSize: 12 }}>{label}</Text>
      <Text style={{ color: valueColor || (highlight ? GOLD : colors.textPrimary),
                     fontSize: 12.5, fontWeight: "800" }}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.65)", justifyContent: "flex-end" },
  sheet: { maxHeight: "90%", borderTopLeftRadius: 24, borderTopRightRadius: 24,
           padding: 18, paddingTop: 16 },
  header: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 10 },
  sideBadge: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.5 },
  caption: { fontSize: 11, marginTop: 2 },
  empty: { padding: 24, borderRadius: 14, alignItems: "center", marginTop: 10 },
  cta: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
         paddingVertical: 14, borderRadius: 12 },
  exChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 12 },
  cell: { width: "32%", padding: 8, borderWidth: 1, borderRadius: 8 },
  stepRow: { flexDirection: "row", alignItems: "center", padding: 10, borderWidth: 1,
             borderRadius: 10, marginTop: 10, gap: 8 },
  stepBtn: { width: 28, height: 28, borderRadius: 7, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  preview: { padding: 12, borderRadius: 10, borderWidth: 1, marginTop: 12 },
});
