import React, { useEffect, useMemo, useState } from "react";
import { Alert, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, type AsiBotConfig, type AsiCredential, type AsiLeaderRow,
  type AsiPnl, type AsiTradeResp,
} from "@/src/lib/api";

const GOLD = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";

type ExchangeId = "binance" | "bybit" | "okx" | "bitget";
const EXCHANGES: { id: ExchangeId; label: string; needsPass: boolean }[] = [
  { id: "binance", label: "Binance Futures", needsPass: false },
  { id: "bybit",   label: "Bybit Perpetual",  needsPass: false },
  { id: "okx",     label: "OKX Swap",         needsPass: true  },
  { id: "bitget",  label: "Bitget Futures",   needsPass: true  },
];

export default function ASIBotScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [deviceId, setDeviceId] = useState<string>("");
  const [creds, setCreds] = useState<AsiCredential[]>([]);
  const [bot, setBot] = useState<AsiBotConfig>({
    enabled: false, exchange: "binance", mode: "semi",
    max_trades_per_day: 5, risk_pct: 5, leverage: 10, whitelist: [], profile: "confluence",
  });
  const [pnl, setPnl] = useState<AsiPnl | null>(null);
  const [leader, setLeader] = useState<AsiLeaderRow[]>([]);
  const [trades, setTrades] = useState<AsiTradeResp[]>([]);
  const [connectOpen, setConnectOpen] = useState(false);
  const [disclaimerAck, setDisclaimerAck] = useState(false);

  useEffect(() => {
    (async () => {
      const did = await getDeviceId();
      setDeviceId(did);
      refresh(did);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = async (did?: string) => {
    const id = did || deviceId; if (!id) return;
    try {
      const c = await api.asi.listCredentials(id);
      setCreds(c.items);
      const b = await api.asi.getBot(id);
      if (b.exists) setBot({ ...bot, ...b });
      const p = await api.asi.pnl(id); setPnl(p);
      const l = await api.asi.leaderboard(7); setLeader(l.items);
      const t = await api.asi.listTrades(id); setTrades(t.items.slice(0, 10));
    } catch {}
  };

  const activeCred = creds.find((c) => c.exchange === bot.exchange);
  const canUseBot = !!activeCred && disclaimerAck;

  const saveBot = async (next: Partial<AsiBotConfig>) => {
    const merged = { ...bot, ...next };
    setBot(merged);
    try { await api.asi.saveBot(deviceId, merged); } catch {}
  };

  const toggleBot = async (val: boolean) => {
    if (val && !canUseBot) {
      Alert.alert(
        "Butuh Koneksi + Persetujuan",
        !activeCred ? "Hubungkan API exchange terlebih dahulu." : "Centang persetujuan disclaimer sebelum mengaktifkan bot.",
      );
      return;
    }
    await saveBot({ enabled: val });
  };

  return (
    <View style={[s.root, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="asi-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: colors.textPrimary }]}>🤖 ASI-Bot</Text>
          <Text style={[s.sub, { color: colors.textMuted }]}>
            Artificial Super Intelligence · Auto-Trade Futures
          </Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32 }}>
        {/* Big status card */}
        <View style={[s.card, { borderColor: bot.enabled ? GREEN : colors.border, backgroundColor: colors.surface }]}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
            <View style={[s.dot, { backgroundColor: bot.enabled ? GREEN : colors.textMuted }]} />
            <Text style={[s.cardTitle, { color: colors.textPrimary }]}>
              {bot.enabled ? "AKTIF" : "NONAKTIF"}
            </Text>
            <View style={{ flex: 1 }} />
            <Switch value={bot.enabled} onValueChange={toggleBot} trackColor={{ true: GOLD }} testID="asi-toggle" />
          </View>
          <Text style={[s.cardSub, { color: colors.textMuted }]}>
            {bot.enabled ? "Bot sedang memindai sinyal & siap eksekusi." : "Nyalakan untuk mulai auto-trade."}
          </Text>
        </View>

        {/* Connect exchange */}
        <SectionHeader title="Koneksi Exchange" />
        <View style={{ gap: 8 }}>
          {EXCHANGES.map((ex) => {
            const c = creds.find((x) => x.exchange === ex.id);
            return (
              <TouchableOpacity
                key={ex.id}
                onPress={() => { setBot({ ...bot, exchange: ex.id }); setConnectOpen(true); }}
                style={[s.row, { backgroundColor: colors.surface, borderColor: bot.exchange === ex.id ? GOLD : colors.border }]}
                testID={`asi-ex-${ex.id}`}
              >
                <Text style={[s.rowLabel, { color: colors.textPrimary }]}>{ex.label}</Text>
                <View style={{ flex: 1 }} />
                {c ? (
                  <Text style={{ color: GREEN, fontSize: 11, fontWeight: "800" }}>
                    {c.testnet ? "TESTNET" : "MAINNET"} · {c.api_key_mask}
                  </Text>
                ) : (
                  <Text style={{ color: colors.textMuted, fontSize: 11 }}>Belum terhubung →</Text>
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Mode */}
        <SectionHeader title="Mode" />
        <View style={{ flexDirection: "row", gap: 10 }}>
          {(["semi", "full"] as const).map((m) => {
            const active = bot.mode === m;
            return (
              <TouchableOpacity
                key={m}
                onPress={() => saveBot({ mode: m })}
                style={[s.modeChip, { borderColor: active ? GOLD : colors.border, backgroundColor: active ? GOLD : colors.surface }]}
                testID={`asi-mode-${m}`}
              >
                <Text style={{ fontSize: 20 }}>{m === "semi" ? "🖐️" : "🤖"}</Text>
                <Text style={[s.modeTitle, { color: active ? "#0B0E11" : colors.textPrimary }]}>
                  {m === "semi" ? "Semi-Auto" : "Full-Auto"}
                </Text>
                <Text style={[s.modeSub, { color: active ? "#0B0E11" : colors.textMuted }]}>
                  {m === "semi" ? "Preview & konfirmasi tiap trade" : "Eksekusi otomatis tanpa konfirmasi"}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Parameters */}
        <SectionHeader title="Parameter Risiko" />
        <ParamRow label="Risk per Trade" value={`${bot.risk_pct}%`}
                  onDec={() => saveBot({ risk_pct: Math.max(1, bot.risk_pct - 1) })}
                  onInc={() => saveBot({ risk_pct: Math.min(30, bot.risk_pct + 1) })}
                  colors={colors} testID="asi-risk" />
        <ParamRow label="Leverage" value={`${bot.leverage}x`}
                  onDec={() => saveBot({ leverage: Math.max(1, bot.leverage - 1) })}
                  onInc={() => saveBot({ leverage: Math.min(125, bot.leverage + 1) })}
                  colors={colors} testID="asi-lev" />
        {bot.mode === "full" ? (
          <ParamRow label="Max Trade / Hari" value={`${bot.max_trades_per_day}`}
                    onDec={() => saveBot({ max_trades_per_day: Math.max(1, bot.max_trades_per_day - 1) })}
                    onInc={() => saveBot({ max_trades_per_day: Math.min(50, bot.max_trades_per_day + 1) })}
                    colors={colors} testID="asi-maxtrade" />
        ) : null}

        {/* Disclaimer */}
        <SectionHeader title="Disclaimer Wajib" />
        <View style={[s.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={{ color: colors.textPrimary, fontSize: 12.5, lineHeight: 19 }}>
            • Risiko slippage, latency & kerugian pasar adalah 100% tanggung jawab Anda.{"\n"}
            • Pengembang tidak bertanggung jawab atas kegagalan API exchange.{"\n"}
            • JANGAN PERNAH centang izin {`"Enable Withdrawals"`} di API key exchange.{"\n"}
            • Aplikasi non-custodial — dana tetap 100% di exchange milik Anda.
          </Text>
          <TouchableOpacity
            onPress={() => setDisclaimerAck(!disclaimerAck)}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 }}
            testID="asi-disc"
          >
            <View style={[s.checkbox, { borderColor: GOLD, backgroundColor: disclaimerAck ? GOLD : "transparent" }]}>
              {disclaimerAck ? <Ionicons name="checkmark" size={14} color="#0B0E11" /> : null}
            </View>
            <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 12.5 }}>
              Saya mengerti & menerima semua risiko di atas
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => router.push("/asi-legal" as never)}
            style={{ marginTop: 10, alignItems: "center" }}
            testID="asi-legal-link"
          >
            <Text style={{ color: GOLD, fontSize: 12, fontWeight: "800", textDecorationLine: "underline" }}>
              Baca Terms, Privacy & Compliance Lengkap →
            </Text>
          </TouchableOpacity>
        </View>

        {/* PnL */}
        <SectionHeader title="Rekap PnL" />
        <View style={{ flexDirection: "row", gap: 8 }}>
          {(["daily", "weekly", "monthly"] as const).map((k) => {
            const row = pnl?.[k];
            const pos = (row?.pnl_usdt ?? 0) >= 0;
            return (
              <View key={k} style={[s.pnlCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                <Text style={[s.pnlLabel, { color: colors.textMuted }]}>
                  {k === "daily" ? "Hari Ini" : k === "weekly" ? "Minggu" : "Bulan"}
                </Text>
                <Text style={[s.pnlValue, { color: pos ? GREEN : RED }]}>
                  {pos ? "+" : ""}${(row?.pnl_usdt ?? 0).toFixed(2)}
                </Text>
                <Text style={{ color: pos ? GREEN : RED, fontSize: 11, fontWeight: "700" }}>
                  {pos ? "+" : ""}{(row?.pnl_pct ?? 0).toFixed(2)}%
                </Text>
                <Text style={{ color: colors.textMuted, fontSize: 10, marginTop: 4 }}>
                  {row?.trades ?? 0} trade · W{row?.wins ?? 0}/L{row?.losses ?? 0}
                </Text>
              </View>
            );
          })}
        </View>

        {/* Leaderboard */}
        <SectionHeader title="🏆 Top 10 Trader (7 hari)" />
        <View style={{ gap: 6 }}>
          {leader.length === 0 ? (
            <Text style={{ color: colors.textMuted, fontSize: 12, padding: 8 }}>
              Belum ada data leaderboard. Jadilah yang pertama.
            </Text>
          ) : leader.map((row) => (
            <View key={row.rank} style={[s.leaderRow, { backgroundColor: colors.surface, borderColor: colors.border }]}>
              <Text style={[s.rank, { color: row.rank <= 3 ? GOLD : colors.textMuted }]}>#{row.rank}</Text>
              <Text style={[s.handle, { color: colors.textPrimary }]}>{row.handle}***</Text>
              <View style={{ flex: 1 }} />
              <Text style={{ color: row.pnl_usdt >= 0 ? GREEN : RED, fontWeight: "800" }}>
                {row.pnl_usdt >= 0 ? "+" : ""}${row.pnl_usdt.toFixed(2)}
              </Text>
              <Text style={{ color: colors.textMuted, fontSize: 10, marginLeft: 6 }}>
                {row.trades}T · {row.wr}%
              </Text>
            </View>
          ))}
        </View>

        {/* Recent trades */}
        {trades.length ? (
          <>
            <SectionHeader title="Trade Terbaru" />
            {trades.map((t, i) => (
              <View key={i} style={[s.leaderRow, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                <Text style={{ color: t.side === "BUY" ? GREEN : RED, fontWeight: "900", width: 46 }}>{t.side}</Text>
                <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{t.symbol}</Text>
                <View style={{ flex: 1 }} />
                <Text style={{ color: t.pnl_usdt >= 0 ? GREEN : RED, fontWeight: "800" }}>
                  {t.pnl_usdt >= 0 ? "+" : ""}${(t.pnl_usdt ?? 0).toFixed(2)}
                </Text>
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>

      <ConnectExchangeModal
        visible={connectOpen}
        onClose={() => setConnectOpen(false)}
        exchange={bot.exchange as ExchangeId}
        colors={colors}
        onSaved={async () => { setConnectOpen(false); await refresh(); }}
        deviceId={deviceId}
      />
    </View>
  );
}

function SectionHeader({ title }: { title: string }) {
  const { colors } = useTheme();
  return (
    <Text style={[{ color: colors.textPrimary, fontWeight: "900", fontSize: 13, marginTop: 20, marginBottom: 10, letterSpacing: 0.3 }]}>
      {title}
    </Text>
  );
}

function ParamRow({ label, value, onDec, onInc, colors, testID }: {
  label: string; value: string; onDec: () => void; onInc: () => void; colors: any; testID?: string;
}) {
  return (
    <View style={[s.paramRow, { backgroundColor: colors.surface, borderColor: colors.border }]} testID={testID}>
      <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{label}</Text>
      <View style={{ flex: 1 }} />
      <TouchableOpacity onPress={onDec} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="remove" size={16} color={colors.textPrimary} />
      </TouchableOpacity>
      <Text style={{ color: GOLD, fontWeight: "900", width: 70, textAlign: "center", fontSize: 14 }}>{value}</Text>
      <TouchableOpacity onPress={onInc} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="add" size={16} color={colors.textPrimary} />
      </TouchableOpacity>
    </View>
  );
}

function ConnectExchangeModal({ visible, onClose, exchange, colors, onSaved, deviceId }: {
  visible: boolean; onClose: () => void; exchange: ExchangeId; colors: any;
  onSaved: () => void; deviceId: string;
}) {
  const [k, setK] = useState(""); const [s2, setS2] = useState(""); const [p, setP] = useState("");
  const [testnet, setTestnet] = useState(true); const [loading, setLoading] = useState(false);
  const ex = useMemo(() => EXCHANGES.find((e) => e.id === exchange)!, [exchange]);

  const save = async () => {
    if (!k || !s2) return Alert.alert("Lengkapi", "API Key & Secret wajib diisi.");
    if (ex.needsPass && !p) return Alert.alert("Lengkapi", `${ex.label} butuh passphrase.`);
    setLoading(true);
    try {
      await api.asi.saveCredential(deviceId, {
        exchange, api_key: k.trim(), api_secret: s2.trim(),
        password: ex.needsPass ? p.trim() : null, testnet,
      });
      setK(""); setS2(""); setP(""); onSaved();
    } catch (e: any) {
      Alert.alert("Gagal", e?.message || String(e));
    } finally { setLoading(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={m.backdrop} onPress={onClose}>
        <Pressable style={[m.sheet, { backgroundColor: colors.surface }]} onPress={(e) => e.stopPropagation()}>
          <Text style={[m.title, { color: colors.textPrimary }]}>Hubungkan {ex.label}</Text>
          <Text style={[m.sub, { color: colors.textMuted }]}>
            Buat API key di dashboard {ex.label}, HANYA centang {`"Enable Futures"`}. JANGAN centang {`"Enable Withdrawals"`}.
          </Text>
          <TextInput value={k} onChangeText={setK} placeholder="API Key" placeholderTextColor={colors.textMuted}
                     style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} autoCapitalize="none" />
          <TextInput value={s2} onChangeText={setS2} placeholder="API Secret" placeholderTextColor={colors.textMuted}
                     style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} secureTextEntry autoCapitalize="none" />
          {ex.needsPass ? (
            <TextInput value={p} onChangeText={setP} placeholder="Passphrase" placeholderTextColor={colors.textMuted}
                       style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} secureTextEntry autoCapitalize="none" />
          ) : null}
          <View style={{ flexDirection: "row", alignItems: "center", marginTop: 10 }}>
            <Switch value={testnet} onValueChange={setTestnet} trackColor={{ true: GOLD }} />
            <Text style={{ color: colors.textPrimary, marginLeft: 8, fontWeight: "700" }}>
              Testnet (uji dulu tanpa uang nyata)
            </Text>
          </View>
          <TouchableOpacity onPress={save} disabled={loading}
                            style={[m.save, { backgroundColor: loading ? colors.textMuted : GOLD }]}>
            <Text style={{ color: "#0B0E11", fontWeight: "900", letterSpacing: 0.6 }}>
              {loading ? "MEMVERIFIKASI..." : "SIMPAN & VALIDASI"}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={onClose} style={{ padding: 12, alignItems: "center" }}>
            <Text style={{ color: colors.textMuted }}>Batal</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  sub: { fontSize: 11, marginTop: 2 },
  card: { borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 4 },
  cardTitle: { fontWeight: "900", fontSize: 13, letterSpacing: 0.5 },
  cardSub: { marginTop: 6, fontSize: 12, lineHeight: 18 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  row: { flexDirection: "row", alignItems: "center", padding: 12, borderWidth: 1, borderRadius: 10 },
  rowLabel: { fontWeight: "800" },
  modeChip: { flex: 1, borderWidth: 1.5, borderRadius: 14, padding: 12, alignItems: "flex-start", gap: 6 },
  modeTitle: { fontWeight: "900", fontSize: 13 },
  modeSub: { fontSize: 10.5, lineHeight: 15 },
  paramRow: { flexDirection: "row", alignItems: "center", padding: 10, borderWidth: 1, borderRadius: 10, marginBottom: 8, gap: 10 },
  stepBtn: { width: 32, height: 32, borderRadius: 8, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  checkbox: { width: 20, height: 20, borderRadius: 5, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  pnlCard: { flex: 1, padding: 12, borderRadius: 12, borderWidth: 1 },
  pnlLabel: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5, textTransform: "uppercase" },
  pnlValue: { fontSize: 16, fontWeight: "900", marginTop: 4 },
  leaderRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 10, borderWidth: 1, borderRadius: 10 },
  rank: { fontWeight: "900", width: 32 },
  handle: { fontWeight: "900", letterSpacing: 1 },
});

const m = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.65)", justifyContent: "flex-end" },
  sheet: { borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, gap: 10,
           paddingBottom: Platform.OS === "ios" ? 32 : 20 },
  title: { fontSize: 16, fontWeight: "900" },
  sub: { fontSize: 11.5, lineHeight: 17 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: Platform.OS === "ios" ? 12 : 8,
           marginTop: 10 },
  save: { padding: 14, borderRadius: 12, alignItems: "center", marginTop: 10 },
});
