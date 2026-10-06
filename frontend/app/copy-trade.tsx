import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { usePremiumAccess } from "@/src/lib/usePremiumAccess";
import PremiumLocked from "@/src/components/PremiumLocked";
import { api, type AsiLiveRow } from "@/src/lib/api";
import AsiTradeSheet, { type AsiTradeIntent } from "@/src/components/AsiTradeSheet";

const GOLD = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";
const BLUE = "#3B82F6";

const LIVE_REFRESH_MS = 15_000;

export default function CopyTradeScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t, lang } = useI18n();
  const insets = useSafeAreaInsets();
  const [leader, setLeader] = useState<AsiLiveRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { hasAccess, loaded: accessLoaded } = usePremiumAccess();
  // v9.9.9 — EXECUTE kini fungsional: membuka trade sheet berisi posisi
  // trader yang di-copy dengan harga pasar SAAT INI (bukan entry lama).
  const [sheetOpen, setSheetOpen] = useState(false);
  const [copyIntent, setCopyIntent] = useState<AsiTradeIntent | null>(null);
  const [preparingRank, setPreparingRank] = useState<number | null>(null);

  const onExecuteCopy = useCallback(async (row: AsiLiveRow) => {
    const tr = row.latest_trade || {};
    if (!tr.symbol || !tr.side) return;
    setPreparingRank(row.rank);
    try {
      const base = String(tr.symbol).replace("/USDT", "").replace("USDT", "");
      let entry = tr.entry_price || 0;
      try {
        const p = await api.asi.price(base);
        if (p.price > 0) entry = p.price;
      } catch { /* fallback ke entry trader bila ticker gagal */ }
      setCopyIntent({
        symbol: base,
        side: tr.side === "BUY" ? "BUY" : "SELL",
        entry,
        stop_loss: tr.stop_loss || 0,
        take_profits: tr.take_profits || [],
        source: "asi-bot-semi",
      });
      setSheetOpen(true);
    } finally {
      setPreparingRank(null);
    }
  }, []);

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

  // Localized relative time: "5m ago" / "5m lalu" / "5м назад" / "5分前"
  const timeAgo = (iso?: string | null): string => {
    if (!iso) return "";
    const tt = Date.parse(iso);
    if (!Number.isFinite(tt)) return "";
    const d = Math.max(0, Math.floor((Date.now() - tt) / 1000));
    const gap = lang === "cn" ? "" : " ";
    if (d < 60) return `${d}${t("news_time_second_short")}${gap}${t("news_time_ago")}`;
    if (d < 3600) return `${Math.floor(d / 60)}${t("news_time_minute_short")}${gap}${t("news_time_ago")}`;
    if (d < 86400) return `${Math.floor(d / 3600)}${t("news_time_hour_short")}${gap}${t("news_time_ago")}`;
    return `${Math.floor(d / 86400)}${t("news_time_day_short")}${gap}${t("news_time_ago")}`;
  };

  // v9.6.4 — Premium gate: halaman ini khusus member premium.
  if (accessLoaded && !hasAccess) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
        <View style={s.header}>
          <TouchableOpacity onPress={() => router.back()} testID="copy-back" hitSlop={10}>
            <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={[s.title, { color: colors.textPrimary }]}>🏆 Copy Trade · LIVE</Text>
            <Text style={[s.sub, { color: colors.textMuted }]}>
              {t("copy_sub")}
            </Text>
          </View>
        </View>
        <PremiumLocked bodyKey="premium_locked_copy_body" />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="copy-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: colors.textPrimary }]}>🏆 Copy Trade · LIVE</Text>
          <Text style={[s.sub, { color: colors.textMuted }]}>
            {t("copy_sub")}
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
            <Text style={{ color: colors.textMuted, marginTop: 10, fontSize: 12 }}>{t("copy_loading")}</Text>
          </View>
        ) : leader.length === 0 ? (
          <View style={[s.empty, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Ionicons name="pulse-outline" size={28} color={colors.textMuted} />
            <Text style={{ color: colors.textPrimary, fontWeight: "800", marginTop: 8 }}>
              {t("copy_empty_title")}
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", marginTop: 6, lineHeight: 18 }}>
              {t("copy_empty_body")}
            </Text>
          </View>
        ) : (
          leader.map((row) => {
            const tr = row.latest_trade || {};
            const isLong = tr.side === "BUY";
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
                      {/* v9.9.7 — Badge kecil DEMO/REAL: leaderboard kini
                          menampilkan keduanya (strategi bot identik), user
                          wajib bisa membedakan jaringan trader. */}
                      <View style={{
                        paddingHorizontal: 5, paddingVertical: 1.5, borderRadius: 4,
                        backgroundColor: row.testnet ? BLUE : GREEN,
                      }}>
                        <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 8.5, letterSpacing: 0.4 }}>
                          {row.testnet ? t("asi_demo_badge") : "REAL"}
                        </Text>
                      </View>
                      <View style={[s.openPill, { borderColor: BLUE }]}>
                        <View style={[s.liveDot, { backgroundColor: BLUE }]} />
                        <Text style={{ color: BLUE, fontWeight: "900", fontSize: 10 }}>
                          {t("copy_open_count").replace("{n}", String(row.open_count))}
                        </Text>
                      </View>
                    </View>
                    <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: 2 }}>
                      {t("copy_wr_line").replace("{wr}", String(row.wr30d)).replace("{n}", String(row.trades30d))}
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={{ color: colors.textMuted, fontSize: 10, fontWeight: "700" }}>{t("copy_unrealized")}</Text>
                    {/* v9.7.7 — persentase jadi metrik utama (hijau = profit) */}
                    <Text style={{ color: row.unrealized_pct && row.unrealized_pct >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 20 }}>
                      {row.unrealized_pct && row.unrealized_pct >= 0 ? "+" : ""}{(row.unrealized_pct ?? 0).toFixed(2)}%
                    </Text>
                    <Text style={{ color: row.unrealized_usdt >= 0 ? GREEN : RED, fontWeight: "700", fontSize: 11 }}>
                      {row.unrealized_usdt >= 0 ? "+" : ""}${row.unrealized_usdt.toFixed(2)}
                    </Text>
                  </View>
                </View>

                {tr.symbol && tr.side ? (
                  <View style={[s.tradeRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
                    <View style={{ flex: 1, gap: 2 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                        <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
                          {tr.symbol}/USDT
                        </Text>
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                          backgroundColor: isLong ? GREEN : RED,
                        }}>
                          <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
                            {isLong ? "LONG" : "SHORT"} {tr.leverage ? `${tr.leverage}x` : ""}
                          </Text>
                        </View>
                      </View>
                      <Text style={{ color: colors.textMuted, fontSize: 11 }}>
                        {t("copy_entry_line")
                          .replace("{price}", (tr.entry_price || 0).toLocaleString())
                          .replace("{ago}", timeAgo(tr.created_at))}
                      </Text>
                      {/* v9.9.9 — Detail lengkap di leaderboard: SL & TP dari
                          posisi trader (permintaan user: Entry/SL/TP/Lev/PnL
                          harus terlihat di semua rank 1-25). */}
                      <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }} numberOfLines={2}>
                        <Text style={{ color: RED, fontWeight: "800" }}>
                          SL {tr.stop_loss ? tr.stop_loss.toLocaleString() : "—"}
                        </Text>
                        {"  ·  "}
                        <Text style={{ color: GREEN, fontWeight: "800" }}>
                          TP {(tr.take_profits || []).map((x) => x.toLocaleString()).join(" / ") || "—"}
                        </Text>
                      </Text>
                      {/* v9.9.9 — Bila trader punya >1 posisi terbuka,
                          tunjukkan jumlah sisanya agar pill "N OPEN POS"
                          tidak membingungkan. */}
                      {(row.open_count ?? 0) > 1 ? (
                        <Text style={{ color: BLUE, fontSize: 10, fontWeight: "700", marginTop: 1 }}>
                          {t("copy_more_positions").replace("{n}", String((row.open_count ?? 1) - 1))}
                        </Text>
                      ) : null}
                    </View>
                    <TouchableOpacity
                      style={[s.copyBtn, { backgroundColor: GOLD }]}
                      onPress={() => onExecuteCopy(row)}
                      disabled={preparingRank === row.rank}
                      testID={`copy-execute-${row.rank}`}
                    >
                      {preparingRank === row.rank
                        ? <ActivityIndicator size="small" color="#0B0E11" />
                        : <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 11 }}>{t("copy_execute")}</Text>}
                    </TouchableOpacity>
                  </View>
                ) : null}
              </View>
            );
          })
        )}

        {leader.length > 0 && (
          <Text style={{ color: colors.textMuted, fontSize: 11, textAlign: "center", marginTop: 20, lineHeight: 17 }}>
            {t("copy_footer")}
          </Text>
        )}
      </ScrollView>

      {/* v9.9.9 — Trade sheet untuk eksekusi copy (pakai harga pasar kini) */}
      <AsiTradeSheet
        visible={sheetOpen}
        onClose={() => setSheetOpen(false)}
        intent={copyIntent}
      />
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
