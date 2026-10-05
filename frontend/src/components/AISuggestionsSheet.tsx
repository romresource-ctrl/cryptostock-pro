/**
 * v9.2.0 — AI Suggestions sheet (PREMIUM only).
 *
 * Dibuka dari tombol "AI Suggestions" di dalam popup Trader Profile.
 * User TIDAK lagi memilih aset manual: cukup pilih kategori market,
 * dan daftar aset dengan sinyal AKTIF terkuat (gabungan formula
 * Confluence / VWAP 68-video sesuai profil yang dipilih) langsung
 * tampil lengkap dengan arah LONG/SHORT + Entry, SL, TP1/2/3.
 *
 * Desain: "Dark-First Utility" (lihat /app/design_guidelines.json) —
 * command-center gelap, kartu akordeon dengan grid metrik rapat
 * berdivider, skeleton saat loading, dan locked-state berblur dengan
 * CTA emas untuk non-premium.
 */
import * as Haptics from "expo-haptics";
import { BlurView } from "expo-blur";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, formatPrice, type AssetSignal, type Market } from "@/src/lib/api";
import { getDeviceId } from "@/src/lib/deviceId";
import { useTraderProfile } from "@/src/lib/useTraderProfile";
import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";
import AsiTradeSheet, { type AsiTradeIntent } from "./AsiTradeSheet";

type Props = {
  visible: boolean;
  onClose: () => void;
  onRequestSubscribe: () => void;
};

const CATEGORIES: { key: Market; labelKey: string; icon: string }[] = [
  { key: "crypto", labelKey: "category_crypto", icon: "₿" },
  { key: "stock_id", labelKey: "category_stock_id", icon: "🇮🇩" },
  { key: "stock_us", labelKey: "category_stock_us", icon: "🌍" },
  { key: "gold_silver", labelKey: "category_gold_silver", icon: "🥇" },
  { key: "commodity", labelKey: "category_commodity", icon: "🛢️" },
  { key: "forex", labelKey: "category_forex", icon: "💱" },
  { key: "etf", labelKey: "category_etf", icon: "📊" },
];

const GOLD = "#F0B90B";

function haptic(style: "selection" | "light" | "heavy") {
  if (Platform.OS === "web") return;
  try {
    if (style === "selection") void Haptics.selectionAsync();
    else if (style === "light") void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    else void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
  } catch {
    /* non-fatal */
  }
}

export default function AISuggestionsSheet({ visible, onClose, onRequestSubscribe }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { apiProfile } = useTraderProfile();

  const [market, setMarket] = useState<Market>("crypto");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [engine, setEngine] = useState<string>("CONFLUENCE");
  const [picks, setPicks] = useState<AssetSignal[]>([]);
  const [tradeIntent, setTradeIntent] = useState<AsiTradeIntent | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async (m: Market) => {
    setLoading(true);
    setError(null);
    setExpanded(null);
    try {
      const deviceId = await getDeviceId();
      const res = await api.aiSuggestions(m, "1h", apiProfile ?? undefined, deviceId);
      setPicks(res.suggestions || []);
      setEngine(res.engine || "CONFLUENCE");
    } catch (e: unknown) {
      const msg = String((e as Error)?.message ?? e);
      setError(msg.includes("403") || msg.includes("premium_required") ? "premium_required" : "load_failed");
      setPicks([]);
    } finally {
      setLoading(false);
    }
  }, [apiProfile]);

  useEffect(() => {
    if (visible) void load(market);
  }, [visible, market, load]);

  const openDetail = (asset: AssetSignal) => {
    onClose();
    // v9.2.4 — Teruskan timeframe=1h (TF yang dipakai sheet untuk
    // memindai) agar sinyal di halaman detail SAMA dengan kartu sheet.
    router.push(`/asset/${asset.market}/${asset.symbol}?timeframe=1h` as never);
  };

  const UP = colors.accentUp;
  const DOWN = colors.accentDown;
  const dirColor = (a: AssetSignal) => (a.action === "BUY" ? UP : DOWN);

  // ---------- Locked state (non-premium): blur + upsell emas ----------
  const renderLocked = () => (
    <View style={styles.lockedWrap}>
      {[0, 1, 2, 3].map((i) => (
        <View key={i} style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.cardHead}>
            <View style={[styles.skelLine, { width: 64, backgroundColor: colors.surfaceHighlight }]} />
            <View style={[styles.skelLine, { width: 90, backgroundColor: colors.surfaceHighlight }]} />
            <View style={[styles.skelChip, { backgroundColor: colors.surfaceHighlight }]} />
          </View>
        </View>
      ))}
      <BlurView intensity={Platform.OS === "ios" ? 55 : 80} tint="dark" style={StyleSheet.absoluteFill} />
      <View style={styles.lockedCenter}>
        <View style={[styles.lockedCard, { backgroundColor: colors.surfaceAlt, borderColor: GOLD }]}>
          <Text style={styles.lockEmoji}>🔒</Text>
          <Text style={[styles.lockedTitle, { color: colors.textPrimary }]}>{t("ai_locked_title")}</Text>
          <Text style={[styles.lockedSub, { color: colors.textSecondary }]}>
            {t("ai_locked_sub")}
          </Text>
          <TouchableOpacity
            style={[styles.goldCta, { backgroundColor: GOLD }]}
            onPress={() => {
              haptic("heavy");
              onRequestSubscribe();
            }}
            testID="ai-suggestions-upgrade"
          >
            <Text style={styles.goldCtaText}>{t("ai_upgrade")}</Text>
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );

  // ---------- Skeleton loading ----------
  const renderSkeleton = () => (
    <View>
      {[0, 1, 2, 3, 4].map((i) => (
        <View key={i} style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.cardHead}>
            <View style={[styles.skelLine, { width: 28, backgroundColor: colors.surfaceHighlight }]} />
            <View style={{ flex: 1, gap: 6 }}>
              <View style={[styles.skelLine, { width: 70, backgroundColor: colors.surfaceHighlight }]} />
              <View style={[styles.skelLine, { width: 110, height: 10, backgroundColor: colors.surfaceAlt }]} />
            </View>
            <View style={[styles.skelChip, { backgroundColor: colors.surfaceHighlight }]} />
          </View>
        </View>
      ))}
    </View>
  );

  return (
    <>
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} testID="ai-suggestions-backdrop" />
      <View style={[styles.sheet, { backgroundColor: colors.background, paddingBottom: insets.bottom + 16 }]}>
        <View style={[styles.handle, { backgroundColor: colors.surfaceHighlight }]} />

        {/* Header */}
        <View style={styles.headerRow}>
          <View>
            <Text style={[styles.title, { color: colors.textPrimary }]}>{t("ai_suggestions_title")}</Text>
            <Text style={[styles.subtitle, { color: colors.textSecondary }]}>
              {t("ai_sheet_sub")}
            </Text>
          </View>
          <View style={[styles.engineChip, { borderColor: GOLD }]}>
            <Text style={styles.engineText}>{engine}</Text>
          </View>
        </View>

        {/* Kategori — v9.2.1: flexShrink:0 agar baris chip tidak
            tergepeng (teks terpotong/stack) saat daftar penuh di device. */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={styles.chipsScroll}
          contentContainerStyle={styles.chipsRow}
        >
          {CATEGORIES.map((c) => {
            const active = market === c.key;
            return (
              <TouchableOpacity
                key={c.key}
                testID={`ai-cat-${c.key}`}
                onPress={() => {
                  if (!active) {
                    haptic("selection");
                    setMarket(c.key);
                  }
                }}
                style={[
                  styles.chip,
                  {
                    backgroundColor: active ? GOLD : colors.surface,
                    borderColor: active ? GOLD : colors.border,
                  },
                ]}
              >
                <Text
                  style={[styles.chipText, { color: active ? "#0B0E11" : colors.textSecondary }]}
                  numberOfLines={1}
                >
                  {c.icon}  {t(c.labelKey)}
                </Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        {/* Konten */}
        {error === "premium_required" ? (
          renderLocked()
        ) : loading ? (
          renderSkeleton()
        ) : picks.length === 0 ? (
          <View style={styles.centerBox}>
            <Text style={styles.lockEmoji}>⏳</Text>
            <Text style={[styles.emptyTitle, { color: colors.textPrimary }]}>{t("ai_empty_title")}</Text>
            <Text style={[styles.muted, { color: colors.textSecondary }]}>
              {t("ai_empty_sub")}
            </Text>
          </View>
        ) : (
          <ScrollView style={styles.list} showsVerticalScrollIndicator={false}>
            {picks.map((a, idx) => {
              const key = `${a.market}:${a.symbol}`;
              const isOpen = expanded === key;
              const dc = dirColor(a);
              const rr =
                a.entry != null && a.stop_loss != null && a.take_profit != null
                  ? Math.abs(a.take_profit - a.entry) / Math.max(Math.abs(a.entry - a.stop_loss), 1e-12)
                  : null;
              return (
                <View
                  key={key}
                  style={[
                    styles.card,
                    {
                      backgroundColor: colors.surface,
                      borderColor: isOpen ? dc : colors.border,
                    },
                  ]}
                >
                  <TouchableOpacity
                    testID={`ai-pick-${a.symbol}`}
                    onPress={() => {
                      haptic("light");
                      setExpanded(isOpen ? null : key);
                    }}
                    style={styles.cardHead}
                  >
                    <Text style={[styles.rank, { color: colors.textMuted }]}>
                      {String(idx + 1).padStart(2, "0")}
                    </Text>
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.sym, { color: colors.textPrimary }]}>{a.symbol}</Text>
                      <Text style={[styles.mini, { color: colors.textSecondary }]}>
                        {formatPrice(a.price)}
                        {a.change_pct_24h != null && (
                          <Text style={{ color: a.change_pct_24h >= 0 ? UP : DOWN }}>
                            {`   ${a.change_pct_24h >= 0 ? "▲" : "▼"} ${Math.abs(a.change_pct_24h).toFixed(2)}%`}
                          </Text>
                        )}
                      </Text>
                    </View>
                    <View style={[styles.dirChip, { backgroundColor: dc }]}>
                      <Text style={styles.dirText}>{a.label}</Text>
                    </View>
                    <View style={styles.confWrap}>
                      <Text style={[styles.confNum, { color: GOLD }]}>{a.confidence}</Text>
                      <Text style={[styles.confLabel, { color: colors.textMuted }]}>CONF</Text>
                    </View>
                  </TouchableOpacity>

                  {isOpen && (
                    <View style={[styles.detailBox, { borderTopColor: colors.border }]}>
                      {/* Grid metrik rapat berdivider */}
                      <View style={styles.gridRow}>
                        <View style={styles.gridCell}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>ENTRY ZONE</Text>
                          <Text style={[styles.levelValue, { color: "#3B82F6" }]}>
                            {a.entry_low != null && a.entry_high != null && a.entry_low !== a.entry_high
                              ? `${formatPrice(a.entry_low)} – ${formatPrice(a.entry_high)}`
                              : formatPrice(a.entry)}
                          </Text>
                        </View>
                        <View style={[styles.gridCell, styles.gridDivider, { borderLeftColor: colors.border }]}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>STOP LOSS</Text>
                          <Text style={[styles.levelValue, { color: DOWN }]}>{formatPrice(a.stop_loss)}</Text>
                        </View>
                      </View>
                      <View style={[styles.gridRow, styles.gridRowDivider, { borderTopColor: colors.border }]}>
                        <View style={styles.gridCell}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>TP 1</Text>
                          <Text style={[styles.levelValue, { color: UP }]}>{formatPrice(a.take_profit)}</Text>
                        </View>
                        <View style={[styles.gridCell, styles.gridDivider, { borderLeftColor: colors.border }]}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>TP 2</Text>
                          <Text style={[styles.levelValue, { color: UP }]}>
                            {a.take_profit_2 != null ? formatPrice(a.take_profit_2) : "—"}
                          </Text>
                        </View>
                        <View style={[styles.gridCell, styles.gridDivider, { borderLeftColor: colors.border }]}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>TP 3</Text>
                          <Text style={[styles.levelValue, { color: UP }]}>
                            {a.take_profit_3 != null ? formatPrice(a.take_profit_3) : "—"}
                          </Text>
                        </View>
                      </View>
                      <View style={[styles.gridRow, styles.gridRowDivider, { borderTopColor: colors.border }]}>
                        <View style={styles.gridCell}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>R:R</Text>
                          <Text style={[styles.levelValue, { color: colors.textPrimary }]}>
                            {rr ? `1 : ${rr.toFixed(2)}` : "—"}
                          </Text>
                        </View>
                        <View style={[styles.gridCell, styles.gridDivider, { borderLeftColor: colors.border }]}>
                          <Text style={[styles.levelLabel, { color: colors.textMuted }]}>{t("ai_daily_bias")}</Text>
                          <Text style={[styles.levelValue, { color: colors.textPrimary }]}>
                            {a.indicators?.daily_bias ? String(a.indicators.daily_bias) : "—"}
                          </Text>
                        </View>
                      </View>
                      {a.reasons?.[0] ? (
                        <Text style={[styles.reason, { color: colors.textSecondary }]} numberOfLines={3}>
                          💡 {a.reasons[0]}
                        </Text>
                      ) : null}
                      <TouchableOpacity
                        style={[styles.detailBtn, { borderColor: GOLD }]}
                        onPress={() => openDetail(a)}
                        testID={`ai-open-${a.symbol}`}
                      >
                        <Text style={[styles.detailBtnText, { color: GOLD }]}>{t("ai_open_detail")}</Text>
                      </TouchableOpacity>
                      {/* v9.7.8 — Satu-tap EKSEKUSI SEMI-AUTO via ASI-Bot
                          (crypto only). Trade otomatis muncul di Recent
                          Trades setelah konfirmasi di AsiTradeSheet. */}
                      {a.market === "crypto" && typeof a.entry === "number"
                        && typeof a.stop_loss === "number"
                        && Array.isArray(a.take_profits) && a.take_profits.length > 0 ? (
                        <TouchableOpacity
                          style={[styles.detailBtn, { backgroundColor: "#EC4899", borderColor: "#EC4899", marginTop: 6, flexDirection: "row", justifyContent: "center", alignItems: "center", gap: 6 }]}
                          onPress={() => {
                            Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
                            setTradeIntent({
                              symbol: a.symbol, side: a.action as "BUY" | "SELL",
                              entry: a.entry!, stop_loss: a.stop_loss!,
                              take_profits: a.take_profits || [], source: "ai-suggestions",
                            });
                          }}
                          testID={`ai-trade-${a.symbol}`}
                        >
                          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: "rgba(255,255,255,0.25)" }}>
                            <Text style={{ color: "#FFFFFF", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                              {t("asi_badge_semi")}
                            </Text>
                          </View>
                          <Text style={[styles.detailBtnText, { color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.4 }]}>
                            ⚡ {t("ai_trade_execute_semi")}
                          </Text>
                        </TouchableOpacity>
                      ) : null}
                    </View>
                  )}
                </View>
              );
            })}
            <View style={{ height: 12 }} />
          </ScrollView>
        )}
      </View>
    </Modal>
    <AsiTradeSheet
      visible={!!tradeIntent}
      intent={tradeIntent}
      onClose={() => setTradeIntent(null)}
    />
    </>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: {
    position: "absolute",
    left: 0, right: 0, bottom: 0,
    maxHeight: "88%",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 16,
    paddingTop: 10,
  },
  handle: { alignSelf: "center", width: 44, height: 5, borderRadius: 3, marginBottom: 14 },
  headerRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: 12 },
  title: { fontSize: 22, fontWeight: "800", letterSpacing: 1.2 },
  subtitle: { fontSize: 12, marginTop: 3, lineHeight: 16 },
  engineChip: {
    borderWidth: 1.5, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, marginTop: 2,
  },
  engineText: { color: GOLD, fontSize: 10, fontWeight: "800", letterSpacing: 0.8 },
  chipsScroll: { flexGrow: 0, flexShrink: 0 },
  chipsRow: { gap: 8, paddingVertical: 14 },
  chip: {
    borderWidth: 1, borderRadius: 999, paddingHorizontal: 15, paddingVertical: 9,
    minHeight: 40, justifyContent: "center",
  },
  chipText: { fontSize: 13, fontWeight: "700" },
  list: { flexGrow: 0 },
  card: { borderWidth: 1, borderRadius: 12, marginBottom: 10, overflow: "hidden" },
  cardHead: { flexDirection: "row", alignItems: "center", padding: 14, gap: 12 },
  rank: { fontSize: 13, fontWeight: "700", fontVariant: ["tabular-nums"] },
  sym: { fontSize: 17, fontWeight: "800", letterSpacing: 0.4 },
  mini: { fontSize: 11.5, marginTop: 2, fontVariant: ["tabular-nums"] },
  dirChip: { borderRadius: 6, paddingHorizontal: 10, paddingVertical: 5 },
  dirText: { color: "#fff", fontWeight: "900", fontSize: 11.5, letterSpacing: 0.5 },
  confWrap: { alignItems: "center", minWidth: 40 },
  confNum: { fontSize: 18, fontWeight: "800", fontVariant: ["tabular-nums"] },
  confLabel: { fontSize: 8.5, fontWeight: "700", letterSpacing: 0.8, marginTop: 1 },
  detailBox: { borderTopWidth: 1, paddingHorizontal: 14, paddingVertical: 12 },
  gridRow: { flexDirection: "row" },
  gridRowDivider: { borderTopWidth: 1, marginTop: 10, paddingTop: 10 },
  gridCell: { flex: 1 },
  gridDivider: { borderLeftWidth: 1, paddingLeft: 12 },
  levelLabel: { fontSize: 9.5, fontWeight: "700", letterSpacing: 0.8 },
  levelValue: { fontSize: 14, fontWeight: "800", marginTop: 3, fontVariant: ["tabular-nums"] },
  reason: { fontSize: 11.5, lineHeight: 16, marginTop: 10 },
  detailBtn: {
    borderWidth: 1.5, borderRadius: 10, alignItems: "center",
    paddingVertical: 11, marginTop: 10,
  },
  detailBtnText: { fontWeight: "800", fontSize: 13, letterSpacing: 0.3 },
  centerBox: { alignItems: "center", paddingVertical: 44, gap: 8 },
  lockEmoji: { fontSize: 36 },
  emptyTitle: { fontSize: 16, fontWeight: "800" },
  muted: { fontSize: 12.5, textAlign: "center", lineHeight: 18 },
  // locked state
  lockedWrap: { minHeight: 340, justifyContent: "center" },
  lockedCenter: {
    ...StyleSheet.absoluteFillObject,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  lockedCard: {
    borderWidth: 1.5, borderRadius: 16, padding: 22, alignItems: "center", gap: 8, width: "100%",
  },
  lockedTitle: { fontSize: 18, fontWeight: "800" },
  lockedSub: { fontSize: 12.5, textAlign: "center", lineHeight: 18 },
  goldCta: { borderRadius: 12, paddingHorizontal: 24, paddingVertical: 13, marginTop: 8, width: "100%", alignItems: "center" },
  goldCtaText: { color: "#0B0E11", fontWeight: "900", fontSize: 14, letterSpacing: 0.4 },
  // skeleton
  skelLine: { height: 14, borderRadius: 6 },
  skelChip: { width: 52, height: 26, borderRadius: 6 },
});
