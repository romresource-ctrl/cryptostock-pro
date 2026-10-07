// v10.0.6 — Trades Position screen.
// Dedicated page accessible from the Dashboard (button next to Trader
// Profile picker). Shows the SAME list of trades as the Recent Trades
// section inside ASI-Bot, so users can check positions without scrolling
// the long ASI-Bot screen. Supports CLOSE (open), CANCEL (pending), and
// swipe-to-delete for closed/cancelled/expired/orphaned cards.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Platform, ScrollView, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { getDeviceId } from "@/src/lib/deviceId";
import { api, type AsiTradeResp } from "@/src/lib/api";

const GOLD = "#4ADE80";
const YELLOW = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";
const BLUE = "#38BDF8";
const PURPLE = "#A78BFA";

type AnyTrade = AsiTradeResp & Record<string, any>;

export default function TradesPositionScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t, tEN } = useI18n();
  const insets = useSafeAreaInsets();
  const [deviceId, setDeviceId] = useState<string>("");
  const [trades, setTrades] = useState<AnyTrade[]>([]);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const pollRef = useRef<any>(null);
  const priceRef = useRef<any>(null);

  useEffect(() => {
    (async () => setDeviceId(await getDeviceId()))();
  }, []);

  const load = useCallback(async () => {
    if (!deviceId) return;
    try {
      const r = await api.asi.listTrades(deviceId, 50);
      setTrades(((r as any).items || r || []) as AnyTrade[]);
    } catch { /* keep previous */ }
    finally { setLoading(false); }
  }, [deviceId]);

  useEffect(() => {
    if (!deviceId) return;
    load();
    pollRef.current = setInterval(load, 10_000);
    return () => clearInterval(pollRef.current);
  }, [deviceId, load]);

  // Mark price polling for OPEN positions.
  const openSyms = useMemo(() =>
    Array.from(new Set(
      trades.filter((t2) => t2.status === "open" && t2.symbol).map((t2) => t2.symbol as string)
    )), [trades]);

  const openSymsKey = openSyms.join(",");
  useEffect(() => {
    if (!openSyms.length) {
      if (priceRef.current) { clearInterval(priceRef.current); priceRef.current = null; }
      return;
    }
    const tick = async () => {
      try {
        const r = await api.asi.prices(openSyms);
        const m: Record<string, number> = {};
        Object.entries(r.prices || {}).forEach(([k, v]) => {
          m[k.replace(/USDT$/, "")] = v as number;
        });
        setPrices(m);
      } catch { /* ignore */ }
    };
    tick();
    priceRef.current = setInterval(tick, 2000);
    return () => clearInterval(priceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSymsKey]);

  const onClose = useCallback(async (tr: AnyTrade) => {
    const isPending = tr.status === "pending_entry";
    const confirmMsg = isPending
      ? "Cancel this pending LIMIT order?"
      : "Close this position at market price?";
    const ask = Platform.OS === "web"
      ? Promise.resolve(window.confirm(confirmMsg))
      : new Promise<boolean>((resolve) => Alert.alert(
          isPending ? "Cancel order" : "Close position",
          confirmMsg,
          [{ text: "Back", style: "cancel", onPress: () => resolve(false) },
           { text: isPending ? "Cancel order" : "Close",
             style: "destructive", onPress: () => resolve(true) }]
        ));
    const ok = await ask;
    if (!ok) return;
    setBusyId(tr.id || tr._id);
    try {
      await api.asi.closeTrade(deviceId, tr.id || tr._id);
      await load();
    } catch (e: any) {
      Alert.alert(tEN("asi_close_failed") || "Action failed", String(e?.message || e));
    } finally { setBusyId(null); }
  }, [deviceId, load, tEN]);

  const onDelete = useCallback(async (tr: AnyTrade) => {
    try {
      await api.asi.deleteTrade(deviceId, tr.id || tr._id);
      await load();
    } catch { /* keep */ }
  }, [deviceId, load]);

  // Local price formatter (adaptive precision, no `market` dependency).
  const fp = (v: number | null | undefined): string => {
    if (v == null || isNaN(Number(v))) return "—";
    const n = Number(v);
    const abs = Math.abs(n);
    if (abs >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (abs >= 100) return n.toFixed(2);
    if (abs >= 1) return n.toFixed(4);
    if (abs >= 0.01) return n.toFixed(5);
    if (abs >= 0.0001) return n.toFixed(6);
    return n.toFixed(8).replace(/\.?0+$/, "");
  };

  const fmtDateTime = (iso?: string | null): string => {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const closedReason = (r?: string | null): string => {
    const x = String(r || "");
    if (/^TP\d?$/.test(x)) return `Closed on ${x}`;
    if (x === "SL") return "Closed on SL";
    if (x === "cancelled_pending") return "Canceled by user";
    if (x === "entry_expired") return "Canceled: expired";
    if (x === "manual_cleanup") return "Closed on cleanup";
    if (x === "bracket_failed_after_fill") return "Closed: bracket fail";
    if (x === "orphaned_no_credential") return "No credential (orphaned)";
    if (x === "MANUAL") return "Closed manually";
    if (x === "position_closed_externally") return "Closed on exchange";
    return x ? `Closed: ${x}` : "Closed";
  };

  const renderCard = (tr: AnyTrade) => {
    const isOpen = tr.status === "open";
    const isPending = tr.status === "pending_entry";
    const isLong = tr.side === "BUY";
    const pnl = Number(tr.pnl_usdt ?? 0);
    const live = tr.symbol ? prices[String(tr.symbol).replace("USDT", "")] : undefined;
    const borderColor = isPending ? YELLOW
      : (isOpen ? (pnl >= 0 ? GREEN : RED) : colors.border);
    const canDelete = !isOpen && !isPending;
    const inner = (
      <View style={[s.card, { backgroundColor: colors.surface, borderColor }]}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Mode & entry badges, same vocab as Recent Trades */}
          {tr.mode ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: tr.mode === "full" ? BLUE : GOLD }}>
              <Text style={{ fontSize: 11, fontWeight: "900" }}>
                {tr.mode === "full" ? "🤖" : "🦾"}
              </Text>
            </View>
          ) : null}
          {tr.entry_mode ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: tr.entry_mode === "market" ? PURPLE : YELLOW }}>
              <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                {tr.entry_mode === "market" ? "M" : "L"}
              </Text>
            </View>
          ) : null}
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: tr.testnet ? BLUE : GREEN }}>
            <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9 }}>
              {tr.testnet ? "DEMO" : "REAL"}
            </Text>
          </View>
          <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
            {tr.symbol}/USDT
          </Text>
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: isLong ? GREEN : RED }}>
            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
              {isLong ? "LONG" : "SHORT"} {tr.leverage ? `${tr.leverage}x` : ""}
            </Text>
          </View>
          {live != null ? (
            <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700" }}>
              · ${fp(live)}
            </Text>
          ) : null}
        </View>

        <View style={{ marginTop: 6, flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={{ color: colors.textMuted, fontSize: 11 }}>
              Entry {tr.entry_price ? fp(tr.entry_price) : "—"}
              {tr.filled_at ? ` · filled ${fmtDateTime(tr.filled_at)}` : (tr.created_at ? ` · ${fmtDateTime(tr.created_at)}` : "")}
            </Text>
            <Text style={{ fontSize: 10.5, lineHeight: 15 }}>
              <Text style={{ color: RED, fontWeight: "800" }}>
                SL {tr.stop_loss ? fp(tr.stop_loss) : "—"}
              </Text>
              {"  ·  "}
              <Text style={{ color: GREEN, fontWeight: "800" }}>
                TP {(tr.take_profits || []).map((x: number) => fp(x)).join(" / ") || "—"}
              </Text>
            </Text>
            {tr.margin_usdt != null ? (
              <Text style={{ color: YELLOW, fontSize: 10.5, fontWeight: "700" }}>
                Margin ${Number(tr.margin_usdt).toFixed(2)}
              </Text>
            ) : null}
            {!isOpen && !isPending ? (
              <Text style={{ color: colors.textMuted, fontSize: 10.5 }}>
                {closedReason(tr.close_reason)}
                {tr.closed_price ? ` @ ${fp(tr.closed_price)}` : ""}
                {tr.closed_at ? ` · ${fmtDateTime(tr.closed_at)}` : ""}
              </Text>
            ) : null}
          </View>

          <View style={{ alignItems: "flex-end", gap: 6, minWidth: 92 }}>
            {isPending ? (
              <View style={{ paddingHorizontal: 7, paddingVertical: 3, borderRadius: 6, backgroundColor: YELLOW }}>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 10 }}>LIMIT WAITING</Text>
              </View>
            ) : (
              <Text style={{ color: pnl >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 17 }}>
                {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
              </Text>
            )}
            {(isOpen || isPending) ? (
              <TouchableOpacity
                style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                         backgroundColor: isPending ? YELLOW : RED }}
                onPress={() => onClose(tr)}
                disabled={busyId === (tr.id || tr._id)}
              >
                {busyId === (tr.id || tr._id)
                  ? <ActivityIndicator size="small" color="#0B0E11" />
                  : <Text style={{ color: isPending ? "#0B0E11" : "#fff", fontWeight: "900", fontSize: 11 }}>
                      {isPending ? "CANCEL" : "CLOSE"}
                    </Text>}
              </TouchableOpacity>
            ) : null}
          </View>
        </View>
      </View>
    );

    if (!canDelete) return <View key={tr.id || tr._id}>{inner}</View>;
    return (
      <ReanimatedSwipeable
        key={tr.id || tr._id}
        renderRightActions={() => (
          <TouchableOpacity
            style={{ backgroundColor: RED, justifyContent: "center", alignItems: "center",
                     width: 72, borderRadius: 10, marginVertical: 4 }}
            onPress={() => onDelete(tr)}
          >
            <Ionicons name="trash-outline" size={20} color="#fff" />
            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10, marginTop: 2 }}>DELETE</Text>
          </TouchableOpacity>
        )}
      >
        {inner}
      </ReanimatedSwipeable>
    );
  };

  const openList = useMemo(() => trades.filter((x) => x.status === "open"), [trades]);
  const pendList = useMemo(() => trades.filter((x) => x.status === "pending_entry"), [trades]);
  const histList = useMemo(() => trades.filter((x) =>
    x.status !== "open" && x.status !== "pending_entry"), [trades]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={[s.header, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 16 }}>
          Trades Position
        </Text>
        <TouchableOpacity onPress={load} style={s.backBtn}>
          <Ionicons name="refresh" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 40, gap: 8 }}>
        {loading ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <ActivityIndicator color={GOLD} />
          </View>
        ) : trades.length === 0 ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <Text style={{ color: colors.textMuted, textAlign: "center" }}>
              {t("asi_recent_empty")}
            </Text>
          </View>
        ) : (
          <>
            {openList.length > 0 && (
              <>
                <Text style={[s.section, { color: colors.textMuted }]}>
                  OPEN POSITIONS · {openList.length}
                </Text>
                {openList.map(renderCard)}
              </>
            )}
            {pendList.length > 0 && (
              <>
                <Text style={[s.section, { color: YELLOW }]}>
                  PENDING LIMIT · {pendList.length}
                </Text>
                {pendList.map(renderCard)}
              </>
            )}
            {histList.length > 0 && (
              <>
                <Text style={[s.section, { color: colors.textMuted }]}>
                  HISTORY · {histList.length}
                </Text>
                {histList.map(renderCard)}
              </>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 10, paddingVertical: 10, borderBottomWidth: 1,
  },
  backBtn: { padding: 6, borderRadius: 6 },
  section: { fontWeight: "900", fontSize: 11, letterSpacing: 0.5, marginTop: 8, marginBottom: 2 },
  card: {
    borderRadius: 10, borderWidth: 1, padding: 10, marginVertical: 2,
  },
});
