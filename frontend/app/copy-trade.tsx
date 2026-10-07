import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { usePremiumAccess } from "@/src/lib/usePremiumAccess";
import PremiumLocked from "@/src/components/PremiumLocked";
import { api, type AsiLiveRow, type AsiLiveTrade } from "@/src/lib/api";
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
  const [preparingRank, setPreparingRank] = useState<string | null>(null);

  // v10.0.3 — Terima posisi SPESIFIK (trader bisa punya >1 posisi open;
  // tiap kartu posisi punya tombol EXECUTE sendiri).
  const onExecuteCopy = useCallback(async (row: AsiLiveRow, tr: AsiLiveTrade) => {
    if (!tr.symbol || !tr.side) return;
    const busyKey = `${row.rank}:${tr.symbol}`;
    setPreparingRank(busyKey);
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
            return (
              <View
                key={`${row.handle}-${row.rank}`}
                style={[s.card, { backgroundColor: colors.surface, borderColor: row.rank <= 3 ? GOLD : colors.border }]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <Text style={[s.rank, { color: row.rank <= 3 ? GOLD : colors.textMuted }]}>#{row.rank}</Text>
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <Text style={[s.handle, { color: colors.textPrimary }]}>{row.handle}***</Text>
                      <View style={{
                        paddingHorizontal: 5, paddingVertical: 1.5, borderRadius: 4,
                        backgroundColor: row.testnet ? BLUE : GREEN,
                      }}>
                        <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 8.5, letterSpacing: 0.4 }}>
                          {row.testnet ? t("asi_demo_badge") : "REAL"}
                        </Text>
                      </View>
                      {/* v10.0.4 — Pill penghitung OPEN/CLOSED dihapus: tiap
                          posisi sudah tampil satu per satu sebagai kartu
                          terpisah dengan PnL masing-masing (tidak digabung). */}
                    </View>
                    <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: 2 }}>
                      {t("copy_wr_line").replace("{wr}", String(row.wr30d)).replace("{n}", String(row.trades30d))}
                    </Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={{ color: colors.textMuted, fontSize: 10, fontWeight: "700" }}>
                      {(row.open_count ?? 0) > 0 ? t("copy_total_24h") : t("copy_realized_24h")}
                    </Text>
                    {/* v10.0.3 — Metrik utama = TOTAL profit $ 24h. */}
                    <Text style={{ color: (row.total_profit_usdt ?? row.unrealized_usdt) >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 20 }}>
                      {(row.total_profit_usdt ?? row.unrealized_usdt) >= 0 ? "+" : ""}${(row.total_profit_usdt ?? row.unrealized_usdt).toFixed(2)}
                    </Text>
                    {(row.open_count ?? 0) > 0 ? (
                      <Text style={{ color: colors.textMuted, fontSize: 10, fontWeight: "700" }}>
                        {`open ${row.unrealized_pct && row.unrealized_pct >= 0 ? "+" : ""}${(row.unrealized_pct ?? 0).toFixed(2)}%`}
                      </Text>
                    ) : null}
                  </View>
                </View>

                {/* v10.0.3 — SEMUA posisi open sebagai kartu terpisah.
                    v10.0.4 — posisi closed 24h juga tampil lengkap (read-only). */}
                {(row.open_trades || []).map((ot, oi) => {
                  if (!ot.symbol || !ot.side) return null;
                  const otLong = ot.side === "BUY";
                  const busyKey = `${row.rank}:${ot.symbol}`;
                  const otPnl = ot.pnl_usdt ?? null;
                  return (
                    <View key={`${row.rank}-${ot.symbol}-${oi}`} style={[s.tradeRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
                      <View style={{ flex: 1, gap: 2 }}>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                          <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
                            {ot.symbol}/USDT
                          </Text>
                          <View style={{
                            paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                            backgroundColor: otLong ? GREEN : RED,
                          }}>
                            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
                              {otLong ? "LONG" : "SHORT"} {ot.leverage ? `${ot.leverage}x` : ""}
                            </Text>
                          </View>
                          {/* PnL live per posisi */}
                          {otPnl != null ? (
                            <Text style={{ color: otPnl >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 11 }}>
                              {otPnl >= 0 ? "+" : ""}${otPnl.toFixed(2)}
                            </Text>
                          ) : null}
                        </View>
                        <Text style={{ color: colors.textMuted, fontSize: 11 }}>
                          {t("copy_entry_line")
                            .replace("{price}", (ot.entry_price || 0).toLocaleString())
                            .replace("{ago}", timeAgo(ot.created_at))}
                        </Text>
                        <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }} numberOfLines={2}>
                          <Text style={{ color: RED, fontWeight: "800" }}>
                            SL {ot.stop_loss ? ot.stop_loss.toLocaleString() : "—"}
                          </Text>
                          {"  ·  "}
                          <Text style={{ color: GREEN, fontWeight: "800" }}>
                            TP {(ot.take_profits || []).map((x) => x.toLocaleString()).join(" / ") || "—"}
                          </Text>
                        </Text>
                      </View>
                      <TouchableOpacity
                        style={[s.copyBtn, { backgroundColor: GOLD }]}
                        onPress={() => onExecuteCopy(row, ot)}
                        disabled={preparingRank === busyKey}
                        testID={`copy-execute-${row.rank}-${ot.symbol}`}
                      >
                        {preparingRank === busyKey
                          ? <ActivityIndicator size="small" color="#0B0E11" />
                          : <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 11 }}>{t("copy_execute")}</Text>}
                      </TouchableOpacity>
                    </View>
                  );
                })}

                {/* v10.0.4 — Kartu posisi CLOSED: lengkap (symbol, side, entry,
                    SL, TP, PnL realized, harga & alasan close) tapi read-only —
                    TIDAK ada tombol EXECUTE karena posisi sudah selesai. */}
                {(row.closed_trades || []).map((ct, ci) => {
                  if (!ct.symbol || !ct.side) return null;
                  const ctLong = ct.side === "BUY";
                  const ctPnl = ct.pnl_usdt ?? null;
                  return (
                    <View
                      key={`${row.rank}-closed-${ct.symbol}-${ci}`}
                      style={[s.tradeRow, { borderColor: colors.border, backgroundColor: colors.background, opacity: 0.75 }]}
                      testID={`copy-closed-${row.rank}-${ct.symbol}-${ci}`}
                    >
                      <View style={{ flex: 1, gap: 2 }}>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
                            {ct.symbol}/USDT
                          </Text>
                          <View style={{
                            paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                            backgroundColor: ctLong ? GREEN : RED,
                          }}>
                            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
                              {ctLong ? "LONG" : "SHORT"} {ct.leverage ? `${ct.leverage}x` : ""}
                            </Text>
                          </View>
                          <View style={{
                            paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                            backgroundColor: colors.border,
                          }}>
                            <Text style={{ color: colors.textMuted, fontWeight: "900", fontSize: 9 }}>CLOSED</Text>
                          </View>
                          {/* PnL realized */}
                          {ctPnl != null ? (
                            <Text style={{ color: ctPnl >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 11 }}>
                              {ctPnl >= 0 ? "+" : ""}${ctPnl.toFixed(2)}
                            </Text>
                          ) : null}
                        </View>
                        <Text style={{ color: colors.textMuted, fontSize: 11 }}>
                          {t("copy_entry_line")
                            .replace("{price}", (ct.entry_price || 0).toLocaleString())
                            .replace("{ago}", timeAgo(ct.created_at))}
                        </Text>
                        <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }} numberOfLines={2}>
                          <Text style={{ color: RED, fontWeight: "800" }}>
                            SL {ct.stop_loss ? ct.stop_loss.toLocaleString() : "—"}
                          </Text>
                          {"  ·  "}
                          <Text style={{ color: GREEN, fontWeight: "800" }}>
                            TP {(ct.take_profits || []).map((x) => x.toLocaleString()).join(" / ") || "—"}
                          </Text>
                        </Text>
                        <Text style={{ color: colors.textMuted, fontSize: 10.5 }}>
                          Closed @ {ct.closed_price ? ct.closed_price.toLocaleString() : "—"}
                          {ct.close_reason ? ` · ${ct.close_reason}` : ""}
                          {ct.closed_at ? ` · ${timeAgo(ct.closed_at)}` : ""}
                        </Text>
                      </View>
                    </View>
                  );
                })}
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
