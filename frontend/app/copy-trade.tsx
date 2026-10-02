import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { api, type AsiLiveRow } from "@/src/lib/api";

const GOLD = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";
const BLUE = "#3B82F6";

const LIVE_REFRESH_MS = 15_000;

function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const d = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (d < 60) return `${d}d lalu`;
  if (d < 3600) return `${Math.floor(d / 60)}m lalu`;
  if (d < 86400) return `${Math.floor(d / 3600)}j lalu`;
  return `${Math.floor(d / 86400)}h lalu`;
}

export default function CopyTradeScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [leader, setLeader] = useState<AsiLiveRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const l = await api.asi.leaderboardLive();
      setLeader(l.items || []);
    } catch {
      /* keep previous rows */
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, LIVE_REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="copy-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: colors.textPrimary }]}>🏆 Copy Trade · LIVE</Text>
          <Text style={[s.sub, { color: colors.textMuted }]}>
            10 trader yang SEDANG di posisi · hilang otomatis bila closed
          </Text>
        </View>
        <View style={s.livePill}>
          <View style={s.liveDot} />
          <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 10 }}>LIVE</Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 10 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={GOLD} />}
      >
        {loading ? (
          <View style={{ paddingVertical: 40, alignItems: "center" }}>
            <ActivityIndicator color={GOLD} />
            <Text style={{ color: colors.textMuted, marginTop: 10, fontSize: 12 }}>Memuat posisi aktif…</Text>
          </View>
        ) : leader.length === 0 ? (
          <View style={[s.empty, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Ionicons name="pulse-outline" size={28} color={colors.textMuted} />
            <Text style={{ color: colors.textPrimary, fontWeight: "800", marginTop: 8 }}>
              Tidak ada posisi aktif saat ini
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", marginTop: 6, lineHeight: 18 }}>
              Trader akan muncul di sini saat mereka{"\n"}
              membuka posisi lewat ASI-Bot. Daftar akan refresh otomatis tiap 15 detik.
            </Text>
          </View>
        ) : (
          leader.map((row) => {
            const t = row.latest_trade || {};
            const isLong = t.side === "BUY";
            return (
              <View
                key={`${row.handle}-${row.rank}`}
                style={[s.card, { backgroundColor: colors.surface, borderColor: row.rank <= 3 ? GOLD : colors.border }]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <Text style={[s.rank, { color: row.rank <= 3 ? GOLD : colors.textMuted }]}>#{row.rank}</Text>
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                      <Text style={[s.handle, { color: colors.textPrimary }]}>{row.handle}***</Text>
                      <View style={[s.openPill, { borderColor: BLUE }]}>
                        <View style={[s.liveDot, { backgroundColor: BLUE }]} />
                        <Text style={{ color: BLUE, fontWeight: "900", fontSize: 10 }}>
                          {row.open_count} POS AKTIF
                        </Text>
                      </View>
                    </View>
                    <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: 2 }}>
                      WR 30h: {row.wr30d}% · {row.trades30d} trade closed
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={{ color: colors.textMuted, fontSize: 10, fontWeight: "700" }}>UNREALIZED</Text>
                    <Text style={{ color: row.unrealized_usdt >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 18 }}>
                      {row.unrealized_usdt >= 0 ? "+" : ""}${row.unrealized_usdt.toFixed(2)}
                    </Text>
                  </View>
                </View>

                {t.symbol && t.side ? (
                  <View style={[s.tradeRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
                    <View style={{ flex: 1, gap: 2 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                        <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
                          {t.symbol}/USDT
                        </Text>
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                          backgroundColor: isLong ? GREEN : RED,
                        }}>
                          <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
                            {isLong ? "LONG" : "SHORT"} {t.leverage ? `${t.leverage}x` : ""}
                          </Text>
                        </View>
                      </View>
                      <Text style={{ color: colors.textMuted, fontSize: 11 }}>
                        Entry ${(t.entry_price || 0).toLocaleString()} · dibuka {timeAgo(t.created_at)}
                      </Text>
                    </View>
                    <TouchableOpacity style={[s.copyBtn, { backgroundColor: GOLD, opacity: 0.6 }]} disabled>
                      <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 11 }}>SEGERA</Text>
                    </TouchableOpacity>
                  </View>
                ) : null}
              </View>
            );
          })
        )}

        {leader.length > 0 && (
          <Text style={{ color: colors.textMuted, fontSize: 11, textAlign: "center", marginTop: 20, lineHeight: 17 }}>
            Daftar refresh tiap 15 detik · trader hilang otomatis saat posisi mereka ditutup.
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  sub: { fontSize: 11, marginTop: 2 },
  livePill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: GOLD, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
  },
  liveDot: { width: 7, height: 7, borderRadius: 999, backgroundColor: "#0B0E11" },
  card: { padding: 14, borderRadius: 14, borderWidth: 1.5, gap: 10 },
  rank: { fontSize: 22, fontWeight: "900", width: 42 },
  handle: { fontWeight: "900", fontSize: 15, letterSpacing: 1.5 },
  openPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 7, paddingVertical: 3, borderRadius: 999, borderWidth: 1,
  },
  tradeRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 10, borderRadius: 10, borderWidth: 1,
  },
  copyBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8 },
  empty: {
    padding: 32, borderRadius: 14, borderWidth: 1,
    alignItems: "center", gap: 2,
  },
});
