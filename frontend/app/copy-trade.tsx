import React, { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { api, type AsiLeaderRow } from "@/src/lib/api";

const GOLD = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";

export default function CopyTradeScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [leader, setLeader] = useState<AsiLeaderRow[]>([]);
  const [period, setPeriod] = useState<7 | 30 | 90>(7);

  useEffect(() => {
    (async () => {
      try {
        const l = await api.asi.leaderboard(period);
        setLeader(l.items);
      } catch {}
    })();
  }, [period]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="copy-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: colors.textPrimary }]}>🏆 Copy Trade</Text>
          <Text style={[s.sub, { color: colors.textMuted }]}>Top 10 trader anonim · ikuti trade real-time</Text>
        </View>
      </View>

      <View style={{ flexDirection: "row", gap: 8, padding: 16 }}>
        {[7, 30, 90].map((d) => (
          <TouchableOpacity key={d} onPress={() => setPeriod(d as 7 | 30 | 90)}
            style={[s.chip, { backgroundColor: period === d ? GOLD : colors.surface, borderColor: period === d ? GOLD : colors.border }]}>
            <Text style={{ color: period === d ? "#0B0E11" : colors.textPrimary, fontWeight: "800" }}>
              {d} HARI
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 10 }}>
        {leader.length === 0 ? (
          <Text style={{ color: colors.textMuted, textAlign: "center", padding: 32 }}>
            Belum ada data leaderboard untuk periode ini.{"\n"}
            Jadilah yang pertama lewat ASI-Bot!
          </Text>
        ) : leader.map((row) => (
          <View key={row.rank} style={[s.card, { backgroundColor: colors.surface, borderColor: row.rank <= 3 ? GOLD : colors.border }]}>
            <Text style={[s.rank, { color: row.rank <= 3 ? GOLD : colors.textMuted }]}>#{row.rank}</Text>
            <View style={{ flex: 1 }}>
              <Text style={[s.handle, { color: colors.textPrimary }]}>{row.handle}***</Text>
              <Text style={{ color: colors.textMuted, fontSize: 11 }}>
                {row.trades} trade · WR {row.wr}%
              </Text>
            </View>
            <View style={{ alignItems: "flex-end" }}>
              <Text style={{ color: row.pnl_usdt >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 18 }}>
                {row.pnl_usdt >= 0 ? "+" : ""}${row.pnl_usdt.toFixed(2)}
              </Text>
              <TouchableOpacity style={[s.copyBtn, { backgroundColor: GOLD }]} disabled>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 11 }}>SEGERA</Text>
              </TouchableOpacity>
            </View>
          </View>
        ))}
        <Text style={{ color: colors.textMuted, fontSize: 11, textAlign: "center", marginTop: 20, lineHeight: 17 }}>
          Fitur Copy Trade eksekusi otomatis akan aktif setelah{"\n"}
          jaringan trader-master mencapai minimum 10 user terverifikasi.
        </Text>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  sub: { fontSize: 11, marginTop: 2 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1 },
  card: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 14, borderWidth: 1.5 },
  rank: { fontSize: 22, fontWeight: "900", width: 42 },
  handle: { fontWeight: "900", fontSize: 15, letterSpacing: 1.5 },
  copyBtn: { marginTop: 6, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6 },
});
