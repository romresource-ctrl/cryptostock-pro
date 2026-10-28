// v10.6.7 — Statistik menang/kalah & PnL per Auto-Close % dan REVERSE vs
// Normal (DEMO / REAL terpisah). Kartu lipat di Running Positions.
import React, { useCallback, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { getDeviceId } from "@/src/lib/deviceId";
import { api, type AsiStatsRow, type AsiStatsBreakdown } from "@/src/lib/api";

const GREEN = "#22C55E";
const RED = "#EF4444";

export default function TradeStatsCard() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [net, setNet] = useState<"demo" | "real">("real");
  const [data, setData] = useState<AsiStatsBreakdown | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const did = await getDeviceId();
      setData(await api.asi.statsBreakdown(did));
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) load();
  };

  const d = data?.[net];
  const Row = ({ label, r, testID }: { label: string; r: AsiStatsRow; testID: string }) => {
    const n = r.wins + r.losses;
    const wr = n ? Math.round((100 * r.wins) / n) : 0;
    return (
      <View style={[s.row, { borderColor: colors.border }]} testID={testID}>
        <Text style={[s.cLabel, { color: colors.textPrimary }]}>{label}</Text>
        <Text style={[s.cNum, { color: GREEN }]}>{r.wins}</Text>
        <Text style={[s.cNum, { color: RED }]}>{r.losses}</Text>
        <Text style={[s.cNum, { color: colors.textPrimary }]}>{wr}%</Text>
        <Text style={[s.cPnl, { color: r.pnl >= 0 ? GREEN : RED }]}>
          {r.pnl >= 0 ? "+" : ""}{r.pnl.toFixed(2)}
        </Text>
      </View>
    );
  };
  const Head = () => (
    <View style={s.row}>
      <Text style={[s.cLabel, s.head, { color: colors.textMuted }]} />
      <Text style={[s.cNum, s.head, { color: colors.textMuted }]}>W</Text>
      <Text style={[s.cNum, s.head, { color: colors.textMuted }]}>L</Text>
      <Text style={[s.cNum, s.head, { color: colors.textMuted }]}>WR</Text>
      <Text style={[s.cPnl, s.head, { color: colors.textMuted }]}>PnL $</Text>
    </View>
  );

  return (
    <View style={[s.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <TouchableOpacity onPress={toggle} style={s.header} testID="stats-toggle">
        <Ionicons name="stats-chart" size={16} color={colors.textPrimary} />
        <Text style={[s.title, { color: colors.textPrimary }]}>{t("stats_title")}</Text>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
      </TouchableOpacity>
      {open ? (
        <View style={{ marginTop: 8 }}>
          <View style={s.tabs}>
            {(["real", "demo"] as const).map((k) => (
              <TouchableOpacity key={k} onPress={() => setNet(k)} testID={`stats-net-${k}`}
                style={[s.tab, { borderColor: colors.border,
                  backgroundColor: net === k ? (k === "real" ? "#FB923C" : "#60A5FA") : "transparent" }]}>
                <Text style={{ color: net === k ? "#0B0E11" : colors.textPrimary, fontWeight: "900", fontSize: 12 }}>
                  {k.toUpperCase()}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
          {loading ? <ActivityIndicator style={{ marginVertical: 12 }} color={colors.textPrimary} /> : !d ? (
            <Text style={{ color: colors.textMuted, fontSize: 12, marginTop: 8 }}>{t("stats_empty")}</Text>
          ) : (
            <>
              <Text style={[s.section, { color: colors.textMuted }]}>{t("stats_by_reverse")}</Text>
              <Head />
              {d.by_reverse.length ? d.by_reverse.map((r) => (
                <Row key={r.kind} testID={`stats-rev-${r.kind}`}
                  label={r.kind === "reverse" ? "⇅ REVERSE" : "Normal"} r={r} />
              )) : <Text style={{ color: colors.textMuted, fontSize: 12 }}>{t("stats_empty")}</Text>}
              <Text style={[s.section, { color: colors.textMuted }]}>{t("stats_by_ac")}</Text>
              <Head />
              {d.by_ac.length ? d.by_ac.map((r) => (
                <Row key={r.ac} testID={`stats-ac-${r.ac}`}
                  label={r.ac > 0 ? `AC ${r.ac}%` : "TP mode"} r={r} />
              )) : <Text style={{ color: colors.textMuted, fontSize: 12 }}>{t("stats_empty")}</Text>}
            </>
          )}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 12 },
  header: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 32 },
  title: { flex: 1, fontWeight: "900", fontSize: 13 },
  tabs: { flexDirection: "row", gap: 8, marginBottom: 4 },
  tab: { flex: 1, minHeight: 36, borderWidth: 1, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  section: { fontSize: 11, fontWeight: "900", marginTop: 10, marginBottom: 2, letterSpacing: 0.5 },
  row: { flexDirection: "row", alignItems: "center", paddingVertical: 5, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: "transparent" },
  head: { fontSize: 10, fontWeight: "900" },
  cLabel: { flex: 1.6, fontSize: 12, fontWeight: "800" },
  cNum: { flex: 0.7, fontSize: 12, fontWeight: "800", textAlign: "center" },
  cPnl: { flex: 1.1, fontSize: 12, fontWeight: "900", textAlign: "right" },
});
