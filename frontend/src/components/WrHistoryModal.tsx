/**
 * WR History Modal — v8.7.0
 *
 * Tappable Win-Rate popup: shows 7d / 30d / All-time breakdown of past
 * AI signals for a single asset with per-item outcome (WIN / LOSS / BE),
 * date & time, action label, and % move.
 *
 * Rendered from `app/asset/[market]/[symbol].tsx` when the user taps
 * one of the three WR cells. The three tabs pre-select which period the
 * user tapped, but all three are always available.
 */
import React, { useMemo } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";
import type {
  TrackRecordHistoryItem,
  TrackRecordResponse,
  TrackRecordWrBucket,
} from "@/src/lib/api";

export type WrPeriod = "7d" | "30d" | "all";

interface Props {
  visible: boolean;
  onClose: () => void;
  initialPeriod: WrPeriod;
  data: TrackRecordResponse | null;
  langCode: "id" | "en" | "ru" | "cn";
}

function bucketOutcome(item: TrackRecordHistoryItem): "WIN" | "LOSS" | "BE" {
  if (item.outcome === "WIN" || item.outcome === "LOSS" || item.outcome === "BE") {
    return item.outcome;
  }
  // Fallback: derive from evaluation.hit for legacy rows
  return item.evaluation?.hit ? "WIN" : "LOSS";
}

function formatDateTime(iso: string, langCode: string): { date: string; time: string } {
  try {
    const d = new Date(iso);
    const locale =
      langCode === "id" ? "id-ID" : langCode === "ru" ? "ru-RU" : langCode === "cn" ? "zh-CN" : "en-US";
    const date = d.toLocaleDateString(locale, {
      day: "2-digit",
      month: "short",
      year: "2-digit",
    });
    const time = d.toLocaleTimeString(locale, {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    return { date, time };
  } catch {
    return { date: iso.slice(0, 10), time: "" };
  }
}

function formatPct(pct: number | undefined | null): string {
  if (pct === undefined || pct === null || Number.isNaN(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

const WrHistoryModal: React.FC<Props> = ({ visible, onClose, initialPeriod, data, langCode }) => {
  const { colors } = useTheme();
  const { t } = useI18n();

  const [period, setPeriod] = React.useState<WrPeriod>(initialPeriod);
  React.useEffect(() => {
    if (visible) setPeriod(initialPeriod);
  }, [visible, initialPeriod]);

  const { bucket, items } = useMemo(() => {
    if (!data) return { bucket: null as TrackRecordWrBucket | null, items: [] as TrackRecordHistoryItem[] };
    if (period === "7d") {
      return { bucket: data.win_rate_7d, items: data.history_7d ?? data.recent_signals ?? [] };
    }
    if (period === "30d") {
      return { bucket: data.win_rate_30d, items: data.history_30d ?? data.recent_signals ?? [] };
    }
    return { bucket: data.win_rate_all, items: data.history_all ?? data.recent_signals ?? [] };
  }, [data, period]);

  const wins = bucket?.wins ?? bucket?.hits ?? 0;
  const losses = bucket?.losses ?? (bucket ? Math.max((bucket.total ?? 0) - (bucket.hits ?? 0), 0) : 0);
  const be = bucket?.break_even ?? 0;
  const total = bucket?.total ?? 0;
  const wr = bucket?.win_rate;
  const wrColor =
    wr === null || wr === undefined
      ? colors.textMuted
      : wr >= 65
        ? colors.accentUp
        : wr >= 50
          ? colors.accentHold
          : colors.accentDown;

  const renderTab = (key: WrPeriod, label: string) => {
    const active = period === key;
    return (
      <TouchableOpacity
        key={key}
        onPress={() => setPeriod(key)}
        style={[
          styles.tab,
          {
            backgroundColor: active ? colors.accentUp : colors.surfaceAlt,
            borderColor: active ? colors.accentUp : colors.border,
          },
        ]}
        testID={`wr-tab-${key}`}
      >
        <Text style={[styles.tabText, { color: active ? "#000" : colors.textPrimary }]}>{label}</Text>
      </TouchableOpacity>
    );
  };

  const renderItem = ({ item }: { item: TrackRecordHistoryItem }) => {
    const outcome = bucketOutcome(item);
    const outColor =
      outcome === "WIN" ? colors.accentUp : outcome === "LOSS" ? colors.accentDown : colors.accentHold;
    const outLabel =
      outcome === "WIN" ? "WIN" : outcome === "LOSS" ? "LOSS/SL" : "BE";
    const actColor =
      item.action === "BUY" ? colors.accentUp : item.action === "SELL" ? colors.accentDown : colors.accentHold;
    const { date, time } = formatDateTime(item.created_at, langCode);
    const pct = item.pct_change ?? item.evaluation?.pct_change;
    return (
      <View style={[styles.row, { borderBottomColor: colors.border }]}>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <View style={[styles.actionPill, { backgroundColor: actColor + "22" }]}>
              <Text style={[styles.actionText, { color: actColor }]}>{item.label || item.action}</Text>
            </View>
            <Text style={[styles.rowTf, { color: colors.textMuted }]}>{item.timeframe}</Text>
          </View>
          <Text style={[styles.rowDate, { color: colors.textSecondary, marginTop: 4 }]}>
            {date} · {time}
          </Text>
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={[styles.rowOutcome, { color: outColor }]}>{outLabel}</Text>
          <Text style={[styles.rowPct, { color: outColor, marginTop: 2 }]}>{formatPct(pct)}</Text>
        </View>
      </View>
    );
  };

  return (
    <Modal visible={visible} animationType="fade" transparent onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose}>
        {/* v8.12.32 — Use a plain View here instead of a Pressable.
            Wrapping a FlatList inside a Pressable was intercepting the
            vertical pan gesture on some Android builds so the WR
            history couldn't be scrolled. onPress={stopPropagation} is
            no longer needed since the backdrop only fires when the
            user taps OUTSIDE this container. */}
        <View
          style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}
          onStartShouldSetResponder={() => true}
        >
          {/* Header */}
          <View style={styles.header}>
            <Text style={[styles.title, { color: colors.textPrimary }]}>
              📊 {t("wr_modal_title")}
            </Text>
            <TouchableOpacity onPress={onClose} testID="wr-modal-close" hitSlop={10}>
              <Ionicons name="close" size={22} color={colors.textPrimary} />
            </TouchableOpacity>
          </View>

          {/* Tabs */}
          <View style={styles.tabs}>
            {renderTab("7d", t("wr_tab_7d"))}
            {renderTab("30d", t("wr_tab_30d"))}
            {renderTab("all", t("wr_tab_all"))}
          </View>

          {/* Summary strip */}
          <View style={[styles.summary, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}>
            <SummaryCell label={t("wr_summary_total")} value={String(total)} color={colors.textPrimary} colors={colors} />
            <SummaryCell label={t("wr_summary_win")} value={String(wins)} color={colors.accentUp} colors={colors} />
            <SummaryCell label={t("wr_summary_loss")} value={String(losses)} color={colors.accentDown} colors={colors} />
            <SummaryCell label={t("wr_summary_be")} value={String(be)} color={colors.accentHold} colors={colors} />
            <SummaryCell
              label={t("wr_summary_wr")}
              value={wr === null || wr === undefined ? "—" : `${wr.toFixed(0)}%`}
              color={wrColor}
              colors={colors}
              highlight
            />
          </View>

          {/* List */}
          {items.length === 0 ? (
            <View style={styles.emptyBox}>
              <Text style={[styles.emptyText, { color: colors.textMuted }]}>
                {t("wr_empty")}
              </Text>
            </View>
          ) : (
            <FlatList
              data={items}
              keyExtractor={(_it, i) => `${i}`}
              renderItem={renderItem}
              style={{ maxHeight: 380 }}
              contentContainerStyle={{ paddingHorizontal: 4 }}
              showsVerticalScrollIndicator
              nestedScrollEnabled
              testID="wr-history-list"
            />
          )}

          {/* Close button */}
          <TouchableOpacity
            onPress={onClose}
            style={[styles.closeBtn, { borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}
            testID="wr-modal-close-btn"
          >
            <Text style={[styles.closeBtnText, { color: colors.textPrimary }]}>{t("wr_close")}</Text>
          </TouchableOpacity>
        </View>
      </Pressable>
    </Modal>
  );
};

function SummaryCell({
  label,
  value,
  color,
  colors,
  highlight,
}: {
  label: string;
  value: string;
  color: string;
  colors: ReturnType<typeof useTheme>["colors"];
  highlight?: boolean;
}) {
  return (
    <View style={[styles.sumCell, highlight && { borderLeftWidth: 1, borderLeftColor: colors.border, paddingLeft: 10 }]}>
      <Text style={[styles.sumLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.sumValue, { color, fontWeight: highlight ? "800" : "700" }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 16,
  },
  card: {
    width: "100%",
    maxWidth: 480,
    borderRadius: 16,
    borderWidth: 1,
    padding: 16,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 12,
  },
  title: { fontSize: 16, fontWeight: "700" },
  tabs: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 12,
  },
  tab: {
    flex: 1,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: "center",
  },
  tabText: { fontSize: 12, fontWeight: "700", letterSpacing: 0.3 },
  summary: {
    flexDirection: "row",
    borderRadius: 12,
    borderWidth: 1,
    paddingVertical: 10,
    paddingHorizontal: 8,
    marginBottom: 12,
    justifyContent: "space-between",
  },
  sumCell: { alignItems: "center", flex: 1 },
  sumLabel: { fontSize: 10, fontWeight: "600", letterSpacing: 0.5, marginBottom: 3 },
  sumValue: { fontSize: 15, fontVariant: ["tabular-nums"] },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 10,
    paddingHorizontal: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    gap: 12,
  },
  actionPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  actionText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  rowTf: { fontSize: 11 },
  rowDate: { fontSize: 11, fontVariant: ["tabular-nums"] },
  rowOutcome: { fontSize: 12, fontWeight: "700", letterSpacing: 0.5 },
  rowPct: { fontSize: 12, fontVariant: ["tabular-nums"], fontWeight: "600" },
  emptyBox: { paddingVertical: 28, alignItems: "center", justifyContent: "center" },
  emptyText: { fontSize: 13, textAlign: "center", paddingHorizontal: 20 },
  closeBtn: {
    marginTop: 14,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: "center",
  },
  closeBtnText: { fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
});

export default WrHistoryModal;
