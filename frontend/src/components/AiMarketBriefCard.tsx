/**
 * AI Market Brief Card — v8.7.1
 *
 * Rich narrative Market Brief generated 2x/day (06:00 & 18:00 WIB) by
 * Claude Sonnet 4.6. Rendered at the top of the News → Market Brief tab.
 *
 * Layout:
 *   • Header: sentiment badge (Bullish/Bearish/Mixed/Neutral) + session +
 *     "Diperbarui XX menit lalu"
 *   • Summary (2-3 sentence lead) — always visible
 *   • Expandable body: 4 market sections (Crypto / Stocks / Forex / Gold) +
 *     Top Movers strip + Warning zones
 *
 * Auto-refresh every 5 minutes; user can pull-to-refresh via parent.
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { API_BASE } from "@/src/lib/api";
import { useI18n, type Lang } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

interface TopMover {
  symbol: string;
  market: string;
  change_pct_24h: number;
  note?: string;
}

interface TopHeadline {
  title: string;
  source?: string;
  why_matters?: string;
}

export interface MarketBrief {
  id: string;
  session: "morning" | "evening";
  date_key: string;
  generated_at: string;
  lang: string;
  sentiment: "bullish" | "bearish" | "mixed" | "neutral" | null;
  sentiment_score?: number | null;
  summary?: string;
  sections?: {
    crypto?: string;
    stocks?: string;
    forex?: string;
    gold?: string;
  };
  top_movers?: TopMover[];
  top_headlines?: TopHeadline[];
  warning_zones?: string[];
}

interface BriefResponse {
  available: boolean;
  lang: string;
  brief: MarketBrief | null;
}

function formatRelative(iso: string, langCode: string, t: (k: string) => string): string {
  try {
    const ts = new Date(iso).getTime();
    if (isNaN(ts)) return "";
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 60) return `${diff}${t("news_time_second_short")} ${t("news_time_ago")}`;
    if (diff < 3600) return `${Math.floor(diff / 60)}${t("news_time_minute_short")} ${t("news_time_ago")}`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}${t("news_time_hour_short")} ${t("news_time_ago")}`;
    return `${Math.floor(diff / 86400)}${t("news_time_day_short")} ${t("news_time_ago")}`;
  } catch {
    return "";
  }
}

const SENTIMENT_STYLES: Record<string, { emoji: string; labelKey: string }> = {
  bullish: { emoji: "📈", labelKey: "brief_sentiment_bullish" },
  bearish: { emoji: "📉", labelKey: "brief_sentiment_bearish" },
  mixed: { emoji: "⚖️", labelKey: "brief_sentiment_mixed" },
  neutral: { emoji: "😐", labelKey: "brief_sentiment_neutral" },
};

const SECTION_META: {
  key: keyof NonNullable<MarketBrief["sections"]>;
  emoji: string;
  labelKey: string;
}[] = [
  { key: "crypto", emoji: "🪙", labelKey: "brief_section_crypto" },
  { key: "stocks", emoji: "📊", labelKey: "brief_section_stocks" },
  { key: "forex", emoji: "💱", labelKey: "brief_section_forex" },
  { key: "gold", emoji: "🥇", labelKey: "brief_section_gold" },
];

interface Props {
  lang: Lang;
}

const AiMarketBriefCard: React.FC<Props> = ({ lang }) => {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/market-brief?lang=${lang}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data: BriefResponse = await r.json();
      setBrief(data.available ? data.brief : null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [lang]);

  useEffect(() => {
    setLoading(true);
    load();
    // Auto-refresh every 5 minutes
    const id = setInterval(load, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [load]);

  if (loading) {
    return (
      <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <ActivityIndicator color={colors.accentUp} />
        <Text style={[styles.loadingText, { color: colors.textMuted }]}>
          {t("brief_loading")}
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.accentDown }]}>
        <View style={styles.headerRow}>
          <Ionicons name="alert-circle" size={18} color={colors.accentDown} />
          <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>
            {t("brief_error_title")}
          </Text>
        </View>
        <Text style={[styles.body, { color: colors.textMuted }]}>{error}</Text>
        <TouchableOpacity onPress={load} style={[styles.retryBtn, { borderColor: colors.border }]} testID="brief-retry">
          <Text style={[styles.retryText, { color: colors.textPrimary }]}>{t("brief_retry")}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (!brief) {
    return (
      <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.headerRow}>
          <Ionicons name="hourglass-outline" size={18} color={colors.textMuted} />
          <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>
            {t("brief_empty_title")}
          </Text>
        </View>
        <Text style={[styles.body, { color: colors.textMuted }]}>{t("brief_empty_body")}</Text>
      </View>
    );
  }

  const sentiment = SENTIMENT_STYLES[brief.sentiment || "neutral"] || SENTIMENT_STYLES.neutral;
  const sentimentColor =
    brief.sentiment === "bullish"
      ? colors.accentUp
      : brief.sentiment === "bearish"
        ? colors.accentDown
        : colors.accentHold;
  const sessionEmoji = brief.session === "morning" ? "🌅" : "🌇";
  const sessionKey = brief.session === "morning" ? "brief_session_morning" : "brief_session_evening";

  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border, borderLeftColor: sentimentColor, borderLeftWidth: 4 }]} testID="ai-market-brief-card">
      {/* Header */}
      <View style={styles.headerRow}>
        <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>
          {sessionEmoji} {t(sessionKey)}
        </Text>
        <View style={[styles.sentimentPill, { backgroundColor: sentimentColor + "22", borderColor: sentimentColor }]}>
          <Text style={[styles.sentimentText, { color: sentimentColor }]}>
            {sentiment.emoji} {t(sentiment.labelKey)}
            {brief.sentiment_score !== undefined && brief.sentiment_score !== null
              ? ` ${brief.sentiment_score > 0 ? "+" : ""}${brief.sentiment_score}`
              : ""}
          </Text>
        </View>
      </View>
      <View style={styles.metaRow}>
        <Ionicons name="time-outline" size={12} color={colors.textMuted} />
        <Text style={[styles.metaText, { color: colors.textMuted }]}>
          {t("brief_generated")} {formatRelative(brief.generated_at, lang, t)}
        </Text>
        <Text style={[styles.metaText, { color: colors.accentBlue, marginLeft: 8 }]}>
          ✨ Claude Sonnet 4.6
        </Text>
      </View>

      {/* Summary — always visible */}
      {brief.summary ? (
        <Text style={[styles.summary, { color: colors.textPrimary }]}>{brief.summary}</Text>
      ) : null}

      {/* Tap to expand */}
      <TouchableOpacity
        onPress={() => setExpanded((v) => !v)}
        activeOpacity={0.7}
        style={[styles.expandBtn, { borderColor: colors.border }]}
        testID="brief-expand-toggle"
      >
        <Ionicons
          name={expanded ? "chevron-up" : "chevron-down"}
          size={16}
          color={colors.textSecondary}
        />
        <Text style={[styles.expandText, { color: colors.textSecondary }]}>
          {expanded ? t("brief_show_less") : t("brief_show_more")}
        </Text>
      </TouchableOpacity>

      {expanded && (
        <View style={styles.expandedBody}>
          {/* Per-market sections */}
          {brief.sections
            ? SECTION_META.map((s) => {
                const txt = brief.sections?.[s.key];
                if (!txt) return null;
                return (
                  <View key={s.key} style={[styles.section, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}>
                    <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>
                      {s.emoji} {t(s.labelKey)}
                    </Text>
                    <Text style={[styles.sectionBody, { color: colors.textSecondary }]}>{txt}</Text>
                  </View>
                );
              })
            : null}

          {/* Top movers */}
          {Array.isArray(brief.top_movers) && brief.top_movers.length > 0 && (
            <View style={{ marginTop: 4 }}>
              <Text style={[styles.blockTitle, { color: colors.textPrimary }]}>
                🚀 {t("brief_top_movers")}
              </Text>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={{ gap: 8, paddingRight: 16 }}
              >
                {brief.top_movers.slice(0, 5).map((m, i) => {
                  const up = (m.change_pct_24h || 0) >= 0;
                  const mcol = up ? colors.accentUp : colors.accentDown;
                  return (
                    <View
                      key={`${m.symbol}-${i}`}
                      style={[styles.moverCard, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}
                    >
                      <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                        <Text style={[styles.moverSymbol, { color: colors.textPrimary }]}>{m.symbol}</Text>
                        <Text style={[styles.moverPct, { color: mcol }]}>
                          {up ? "+" : ""}
                          {m.change_pct_24h.toFixed(2)}%
                        </Text>
                      </View>
                      {m.note ? (
                        <Text style={[styles.moverNote, { color: colors.textMuted }]} numberOfLines={3}>
                          {m.note}
                        </Text>
                      ) : null}
                    </View>
                  );
                })}
              </ScrollView>
            </View>
          )}

          {/* Warning zones */}
          {Array.isArray(brief.warning_zones) && brief.warning_zones.length > 0 && (
            <View style={[styles.warnBlock, { backgroundColor: colors.accentDown + "12", borderColor: colors.accentDown + "55" }]}>
              <Text style={[styles.blockTitle, { color: colors.accentDown }]}>⚠️ {t("brief_warnings")}</Text>
              {brief.warning_zones.slice(0, 3).map((w, i) => (
                <Text key={i} style={[styles.warnItem, { color: colors.textPrimary }]}>
                  • {w}
                </Text>
              ))}
            </View>
          )}

          {/* Top headlines */}
          {Array.isArray(brief.top_headlines) && brief.top_headlines.length > 0 && (
            <View style={{ marginTop: 8 }}>
              <Text style={[styles.blockTitle, { color: colors.textPrimary }]}>
                📰 {t("brief_top_headlines")}
              </Text>
              {brief.top_headlines.slice(0, 3).map((h, i) => (
                <View key={i} style={[styles.headlineCard, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}>
                  <Text style={[styles.headlineTitle, { color: colors.textPrimary }]} numberOfLines={2}>
                    {h.title}
                  </Text>
                  {h.source ? (
                    <Text style={[styles.headlineSource, { color: colors.accentBlue }]}>{h.source}</Text>
                  ) : null}
                  {h.why_matters ? (
                    <Text style={[styles.headlineWhy, { color: colors.textSecondary }]}>{h.why_matters}</Text>
                  ) : null}
                </View>
              ))}
            </View>
          )}
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    marginTop: 8,
    marginBottom: 12,
    padding: 14,
    borderRadius: 14,
    borderWidth: 1,
    minHeight: 100,
  },
  loadingText: { marginTop: 10, fontSize: 12, textAlign: "center" },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
    gap: 8,
    flexWrap: "wrap",
  },
  headerTitle: { fontSize: 15, fontWeight: "700", flexShrink: 1 },
  sentimentPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
  },
  sentimentText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginBottom: 10,
    flexWrap: "wrap",
  },
  metaText: { fontSize: 10 },
  summary: { fontSize: 13, lineHeight: 20, marginBottom: 8 },
  body: { fontSize: 12, marginTop: 6 },
  expandBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 8,
    borderTopWidth: 1,
    marginTop: 6,
  },
  expandText: { fontSize: 12, fontWeight: "600" },
  expandedBody: { marginTop: 8, gap: 10 },
  section: {
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  sectionTitle: { fontSize: 13, fontWeight: "700", marginBottom: 4 },
  sectionBody: { fontSize: 12, lineHeight: 18 },
  blockTitle: { fontSize: 12, fontWeight: "700", marginBottom: 6, letterSpacing: 0.3 },
  moverCard: {
    width: 170,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  moverSymbol: { fontSize: 12, fontWeight: "700" },
  moverPct: { fontSize: 12, fontWeight: "700", fontVariant: ["tabular-nums"] },
  moverNote: { fontSize: 10, marginTop: 4, lineHeight: 14 },
  warnBlock: {
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    marginTop: 4,
  },
  warnItem: { fontSize: 12, lineHeight: 18, marginTop: 3 },
  headlineCard: {
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    marginTop: 6,
  },
  headlineTitle: { fontSize: 12, fontWeight: "600" },
  headlineSource: { fontSize: 10, marginTop: 3 },
  headlineWhy: { fontSize: 11, marginTop: 3, lineHeight: 16, fontStyle: "italic" },
  retryBtn: {
    marginTop: 10,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: "center",
  },
  retryText: { fontSize: 12, fontWeight: "600" },
});

export default AiMarketBriefCard;
