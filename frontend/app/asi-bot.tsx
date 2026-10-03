import React, { useEffect, useMemo, useState } from "react";
import { Alert, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, type AsiBotConfig, type AsiCredential,
  type AsiPnl, type AsiTradeResp,
} from "@/src/lib/api";

const GOLD = "#4ADE80"; // v9.4.1 — primary ASI-Bot accent (hijau muda)
const ORANGE = "#F97316"; // v9.6.3 — Full-Auto active accent
const GREEN = "#22C55E";
const RED = "#EF4444";
const ACCENT_TEXT = "#FFFFFF"; // teks di atas tombol primary

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
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const [deviceId, setDeviceId] = useState<string>("");
  const [creds, setCreds] = useState<AsiCredential[]>([]);
  const [bot, setBot] = useState<AsiBotConfig>({
    enabled: false, exchange: "binance", mode: "semi",
    max_trades_per_day: 5, risk_pct: 5, leverage: 10, whitelist: [], profile: "confluence",
    min_confidence: 75, daily_loss_limit_usdt: 0,
    tp_count: 3, trailing_callback_rate: 2,
  });
  const [pnl, setPnl] = useState<AsiPnl | null>(null);
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
      const t2 = await api.asi.listTrades(id); setTrades(t2.items.slice(0, 10));
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
        t("asi_alert_need_title"),
        !activeCred ? t("asi_alert_need_connect") : t("asi_alert_need_ack"),
      );
      return;
    }
    // v9.4.1 — Clear auto-disabled flags when user manually re-enables.
    await saveBot(val
      ? { enabled: true, auto_disabled_reason: null, auto_disabled_at: null }
      : { enabled: false });
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
              {bot.enabled ? t("asi_status_active") : t("asi_status_inactive")}
            </Text>
            <View style={{ flex: 1 }} />
            <Switch value={bot.enabled} onValueChange={toggleBot} trackColor={{ true: GOLD }} testID="asi-toggle" />
          </View>
          <Text style={[s.cardSub, { color: colors.textMuted }]}>
            {bot.enabled ? t("asi_status_on_sub") : t("asi_status_off_sub")}
          </Text>
        </View>

        {/* Connect exchange */}
        <SectionHeader title={t("asi_sec_exchange")} />
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
                  <Text style={{ color: colors.textMuted, fontSize: 11 }}>{t("asi_not_connected")}</Text>
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Mode */}
        <SectionHeader title={t("asi_sec_mode")} />
        <View style={{ flexDirection: "row", gap: 10 }}>
          {(["semi", "full"] as const).map((m) => {
            const active = bot.mode === m;
            const accent = m === "full" ? ORANGE : GOLD;
            return (
              <TouchableOpacity
                key={m}
                onPress={() => saveBot({ mode: m })}
                style={[s.modeChip, { borderColor: active ? accent : colors.border, backgroundColor: active ? accent : colors.surface }]}
                testID={`asi-mode-${m}`}
              >
                <Text style={{ fontSize: 20 }}>{m === "semi" ? "🦾" : "🤖"}</Text>
                <Text style={[s.modeTitle, { color: active ? ACCENT_TEXT : colors.textPrimary }]}>
                  {m === "semi" ? "Semi-Auto" : "Full-Auto"}
                </Text>
                <Text style={[s.modeSub, { color: active ? ACCENT_TEXT : colors.textMuted }]}>
                  {m === "semi" ? t("asi_mode_semi_sub") : t("asi_mode_full_sub")}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Parameters */}
        <SectionHeader title={t("asi_sec_risk")} />
        <ParamRow label={t("asi_risk_per_trade")} value={`${bot.risk_pct}%`}
                  onDec={() => saveBot({ risk_pct: Math.max(1, bot.risk_pct - 1) })}
                  onInc={() => saveBot({ risk_pct: Math.min(30, bot.risk_pct + 1) })}
                  colors={colors} testID="asi-risk" />
        <ParamRow label="Leverage" value={`${bot.leverage}x`}
                  onDec={() => saveBot({ leverage: Math.max(1, bot.leverage - 1) })}
                  onInc={() => saveBot({ leverage: Math.min(125, bot.leverage + 1) })}
                  colors={colors} testID="asi-lev" />
        {/* v9.6.0 — Centang TP1/TP2/TP3 (dibawah leverage) */}
        <View style={{ flexDirection: "row", gap: 8, marginBottom: 6 }}>
          {([1, 2, 3] as const).map((n) => {
            const active = (bot.tp_count ?? 3) === n;
            const label = n === 1 ? t("asi_tp_1_label") : n === 2 ? t("asi_tp_2_label") : t("asi_tp_3_label");
            return (
              <TouchableOpacity
                key={n}
                onPress={() => saveBot({ tp_count: n })}
                style={[s.tpChip, {
                  borderColor: active ? GOLD : colors.border,
                  backgroundColor: active ? GOLD : colors.surface,
                }]}
                testID={`asi-tp-${n}`}
              >
                <Text style={{ color: active ? ACCENT_TEXT : colors.textPrimary, fontWeight: "900", fontSize: 12.5 }}>
                  {label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <Text style={{ color: colors.textMuted, fontSize: 11, marginBottom: 10, lineHeight: 16 }}>
          {t("asi_tp_hint")}
        </Text>
        {bot.mode === "full" ? (
          <ParamRow label={t("asi_max_trades_day")} value={`${bot.max_trades_per_day}`}
                    onDec={() => saveBot({ max_trades_per_day: Math.max(1, bot.max_trades_per_day - 1) })}
                    onInc={() => saveBot({ max_trades_per_day: Math.min(50, bot.max_trades_per_day + 1) })}
                    colors={colors} testID="asi-maxtrade" />
        ) : null}
        <ParamRow label={t("asi_daily_loss_limit")}
                  value={(bot.daily_loss_limit_usdt ?? 0) === 0 ? "OFF" : `$${bot.daily_loss_limit_usdt}`}
                  onDec={() => saveBot({ daily_loss_limit_usdt: Math.max(0, (bot.daily_loss_limit_usdt ?? 0) - 10) })}
                  onInc={() => saveBot({ daily_loss_limit_usdt: Math.min(100000, (bot.daily_loss_limit_usdt ?? 0) + 10) })}
                  colors={colors} testID="asi-dailyloss" />
        <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: -4, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_daily_loss_hint")}
        </Text>

        <ParamRow
          label={t("asi_trailing_label")}
          value={(bot.trailing_callback_rate ?? 0) === 0 ? "OFF" : `${(bot.trailing_callback_rate ?? 0).toFixed(1)}%`}
          onDec={() => saveBot({ trailing_callback_rate: Math.max(0, Math.round(((bot.trailing_callback_rate ?? 0) - 0.5) * 10) / 10) })}
          onInc={() => saveBot({ trailing_callback_rate: Math.min(10, Math.round(((bot.trailing_callback_rate ?? 0) + 0.5) * 10) / 10) })}
          colors={colors} testID="asi-trailing"
        />
        <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: -4, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_trailing_hint")}
        </Text>

        {bot.auto_disabled_reason ? (
          <View style={{ padding: 10, borderRadius: 10, borderWidth: 1.5,
                          borderColor: RED, backgroundColor: "rgba(239,68,68,0.08)",
                          flexDirection: "row", alignItems: "flex-start", gap: 8, marginBottom: 10 }}>
            <Ionicons name="shield-checkmark" size={18} color={RED} />
            <Text style={{ color: colors.textPrimary, fontSize: 11.5, flex: 1, lineHeight: 16 }}>
              <Text style={{ fontWeight: "900" }}>{t("asi_auto_disabled")}</Text> {bot.auto_disabled_reason}
            </Text>
          </View>
        ) : null}

        {/* Disclaimer */}
        <SectionHeader title={t("asi_sec_disclaimer")} />
        <View style={[s.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={{ color: colors.textPrimary, fontSize: 12.5, lineHeight: 19 }}>
            {t("asi_disc_body")}
          </Text>
          <TouchableOpacity
            onPress={() => setDisclaimerAck(!disclaimerAck)}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 }}
            testID="asi-disc"
          >
            <View style={[s.checkbox, { borderColor: GOLD, backgroundColor: disclaimerAck ? GOLD : "transparent" }]}>
              {disclaimerAck ? <Ionicons name="checkmark" size={14} color={ACCENT_TEXT} /> : null}
            </View>
            <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 12.5 }}>
              {t("asi_disc_ack")}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => router.push("/asi-legal" as never)}
            style={{ marginTop: 10, alignItems: "center" }}
            testID="asi-legal-link"
          >
            <Text style={{ color: GOLD, fontSize: 12, fontWeight: "800", textDecorationLine: "underline" }}>
              {t("asi_legal_link")}
            </Text>
          </TouchableOpacity>
        </View>

        {/* PnL */}
        <SectionHeader title={t("asi_sec_pnl")} />
        <View style={{ flexDirection: "row", gap: 8 }}>
          {(["daily", "weekly", "monthly"] as const).map((k) => {
            const row = pnl?.[k];
            const pos = (row?.pnl_usdt ?? 0) >= 0;
            return (
              <View key={k} style={[s.pnlCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                <Text style={[s.pnlLabel, { color: colors.textMuted }]}>
                  {k === "daily" ? t("asi_pnl_daily") : k === "weekly" ? t("asi_pnl_weekly") : t("asi_pnl_monthly")}
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

        {/* Leaderboard — hidden on this screen; pindah ke /copy-trade */}

        {/* Recent trades */}
        {trades.length ? (
          <>
            <SectionHeader title={t("asi_sec_recent")} />
            {trades.map((tr, i) => (
              <View key={i} style={[s.leaderRow, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                <Text style={{ color: tr.side === "BUY" ? GREEN : RED, fontWeight: "900", width: 46 }}>{tr.side}</Text>
                <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{tr.symbol}</Text>
                <View style={{ flex: 1 }} />
                <Text style={{ color: tr.pnl_usdt >= 0 ? GREEN : RED, fontWeight: "800" }}>
                  {tr.pnl_usdt >= 0 ? "+" : ""}${(tr.pnl_usdt ?? 0).toFixed(2)}
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
  const { t } = useI18n();
  const [k, setK] = useState(""); const [s2, setS2] = useState(""); const [p, setP] = useState("");
  const [network, setNetwork] = useState<"testnet" | "mainnet">("testnet");
  const [mainnetAck, setMainnetAck] = useState(false);
  const [loading, setLoading] = useState(false);
  const [serverIp, setServerIp] = useState("143.198.197.107");
  const [copied, setCopied] = useState(false);
  const ex = useMemo(() => EXCHANGES.find((e) => e.id === exchange)!, [exchange]);
  const isMainnet = network === "mainnet";

  useEffect(() => {
    if (visible) {
      api.asi.serverIp().then((r) => { if (r?.ip) setServerIp(r.ip); }).catch(() => {});
    }
  }, [visible]);

  const copyIp = async () => {
    await Clipboard.setStringAsync(serverIp);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const save = async () => {
    if (!k || !s2) return Alert.alert(t("asi_alert_fill_title"), t("asi_alert_fill_body"));
    if (ex.needsPass && !p) return Alert.alert(t("asi_alert_fill_title"), t("asi_alert_pass_body").replace("{ex}", ex.label));
    if (isMainnet && !mainnetAck) {
      return Alert.alert(t("asi_alert_mainnet_title"), t("asi_alert_mainnet_body"));
    }
    setLoading(true);
    try {
      await api.asi.saveCredential(deviceId, {
        exchange, api_key: k.trim(), api_secret: s2.trim(),
        password: ex.needsPass ? p.trim() : null, testnet: !isMainnet,
      });
      setK(""); setS2(""); setP(""); setMainnetAck(false); onSaved();
    } catch (e: any) {
      Alert.alert(t("asi_alert_fail_title"), e?.message || String(e));
    } finally { setLoading(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={m.backdrop} onPress={onClose}>
        <Pressable style={[m.sheet, { backgroundColor: colors.surface }]} onPress={(e) => e.stopPropagation()}>
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
            <Text style={[m.title, { color: colors.textPrimary }]}>{t("asi_connect_title").replace("{ex}", ex.label)}</Text>
            <Text style={[m.sub, { color: colors.textMuted }]}>
              {t("asi_connect_sub")}
            </Text>

            {/* Network selector: TESTNET / MAINNET */}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
              {(["testnet", "mainnet"] as const).map((n) => {
                const active = network === n;
                const isM = n === "mainnet";
                return (
                  <TouchableOpacity
                    key={n}
                    onPress={() => setNetwork(n)}
                    style={[m.netChip, {
                      flex: 1,
                      backgroundColor: active ? (isM ? RED : GOLD) : colors.background,
                      borderColor: active ? (isM ? RED : GOLD) : colors.border,
                    }]}
                  >
                    <Text style={{
                      color: active ? (isM ? "#fff" : ACCENT_TEXT) : colors.textPrimary,
                      fontWeight: "900", fontSize: 12, letterSpacing: 0.8,
                    }}>
                      {isM ? "🔴 MAINNET" : "🧪 TESTNET"}
                    </Text>
                    <Text style={{
                      color: active ? (isM ? "#FFE5E5" : "rgba(255,255,255,0.85)") : colors.textMuted,
                      fontSize: 10, marginTop: 2,
                    }}>
                      {isM ? t("asi_net_mainnet_sub") : t("asi_net_testnet_sub")}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            {/* IP Whitelist guidance card (crucial for Binance & security) */}
            <View style={[m.ipCard, { borderColor: colors.border, backgroundColor: colors.background }]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Ionicons name="shield-checkmark" size={16} color={GOLD} />
                <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 12 }}>
                  {t("asi_ip_title")}
                </Text>
              </View>
              <Text style={{ color: colors.textMuted, fontSize: 11, lineHeight: 16 }}>
                {t("asi_ip_sub")}
              </Text>

              {/* IP Copy Box */}
              <View style={[m.ipRow, { backgroundColor: colors.surface, borderColor: GOLD }]}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: colors.textMuted, fontSize: 9.5, fontWeight: "700" }}>{t("asi_ip_label")}</Text>
                  <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 13, fontFamily: Platform.OS === "ios" ? "Courier" : "monospace", letterSpacing: 0.5 }}>
                    {serverIp}
                  </Text>
                </View>
                <TouchableOpacity onPress={copyIp} style={[m.copyBtn, { backgroundColor: copied ? GREEN : GOLD }]}>
                  <Ionicons name={copied ? "checkmark" : "copy-outline"} size={14} color={ACCENT_TEXT} />
                  <Text style={{ color: ACCENT_TEXT, fontWeight: "900", fontSize: 11 }}>
                    {copied ? t("asi_ip_copied") : t("asi_ip_copy")}
                  </Text>
                </TouchableOpacity>
              </View>

              <View style={{ gap: 3, marginTop: 4 }}>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step1")}</Text>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step2")}</Text>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step3")}</Text>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step4")}</Text>
              </View>
            </View>

            <TextInput value={k} onChangeText={setK} placeholder="API Key" placeholderTextColor={colors.textMuted}
                       style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} autoCapitalize="none" />
            <TextInput value={s2} onChangeText={setS2} placeholder="API Secret" placeholderTextColor={colors.textMuted}
                       style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} secureTextEntry autoCapitalize="none" />
            {ex.needsPass ? (
              <TextInput value={p} onChangeText={setP} placeholder="Passphrase" placeholderTextColor={colors.textMuted}
                         style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} secureTextEntry autoCapitalize="none" />
            ) : null}

            {isMainnet ? (
              <Pressable
                onPress={() => setMainnetAck((v) => !v)}
                style={[m.warnBox, { borderColor: RED, backgroundColor: "rgba(239,68,68,0.08)" }]}
              >
                <View style={[s.checkbox, { borderColor: RED, backgroundColor: mainnetAck ? RED : "transparent" }]}>
                  {mainnetAck ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                </View>
                <Text style={{ color: colors.textPrimary, fontSize: 11.5, flex: 1, lineHeight: 16 }}>
                  {t("asi_mainnet_ack")}
                </Text>
              </Pressable>
            ) : null}

            <TouchableOpacity onPress={save} disabled={loading || (isMainnet && !mainnetAck)}
                              style={[m.save, { backgroundColor: loading ? colors.textMuted : (isMainnet ? RED : GOLD) }]}>
              <Text style={{ color: isMainnet ? "#fff" : ACCENT_TEXT, fontWeight: "900", letterSpacing: 0.6 }}>
                {loading ? t("asi_verifying") : isMainnet ? t("asi_save_mainnet") : t("asi_save_testnet")}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onClose} style={{ padding: 8, alignItems: "center" }}>
              <Text style={{ color: colors.textMuted }}>{t("common_cancel")}</Text>
            </TouchableOpacity>
          </ScrollView>
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
  tpChip: { flex: 1, borderWidth: 1.5, borderRadius: 10, paddingVertical: 10, alignItems: "center" },
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
           maxHeight: "88%",
           paddingBottom: Platform.OS === "ios" ? 32 : 20 },
  title: { fontSize: 16, fontWeight: "900" },
  sub: { fontSize: 11.5, lineHeight: 17 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: Platform.OS === "ios" ? 12 : 8,
           marginTop: 8 },
  save: { padding: 14, borderRadius: 12, alignItems: "center", marginTop: 10 },
  netChip: { padding: 12, borderRadius: 12, borderWidth: 1.5, alignItems: "center" },
  warnBox: { flexDirection: "row", gap: 10, alignItems: "flex-start", padding: 12,
             borderRadius: 10, borderWidth: 1.5, marginTop: 10 },
  ipCard: { padding: 12, borderRadius: 12, borderWidth: 1, gap: 6, marginTop: 4 },
  ipRow: { flexDirection: "row", alignItems: "center", padding: 10, borderRadius: 8, borderWidth: 1, gap: 8, marginTop: 2 },
  copyBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 6 },
});
