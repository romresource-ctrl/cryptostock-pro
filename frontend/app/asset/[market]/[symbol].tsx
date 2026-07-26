import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth/AuthContext";
import CandlestickChart from "@/src/components/CandlestickChart";
import PriceChart from "@/src/components/PriceChart";
import TargetProfit from "@/src/components/TargetProfit";
import { useI18n } from "@/src/i18n/I18nContext";
import {
  TIMEFRAMES,
  type AnalyzeResponse,
  type ChartResponse,
  type Market,
  type ModelResult,
  type Timeframe,
  type TrackRecordResponse,
  api,
  formatPct,
  formatPrice,
} from "@/src/lib/api";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";

function signalColors(colors: ReturnType<typeof useTheme>["colors"], action: string) {
  if (action === "BUY") return { fg: colors.accentUp, bg: colors.accentUp + "26" };
  if (action === "SELL") return { fg: colors.accentDown, bg: colors.accentDown + "26" };
  return { fg: colors.accentHold, bg: colors.accentHold + "26" };
}

function ModelChip({ model }: { model: ModelResult }) {
  const { colors } = useTheme();
  const action = model.data?.action ?? "—";
  const sig = signalColors(colors, action);
  const ok = model.ok && model.data;
  return (
    <View style={[styles.modelChip, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <Text style={[styles.modelName, { color: colors.textPrimary }]} numberOfLines={1}>
        {model.name}
      </Text>
      {ok ? (
        <>
          <View style={[styles.signalPill, { backgroundColor: sig.bg, marginTop: 6 }]}>
            <Text style={[styles.signalText, { color: sig.fg }]}>{model.data?.label || action}</Text>
          </View>
          <Text style={[styles.modelConf, { color: sig.fg }]}>{model.data?.confidence ?? 0}%</Text>
        </>
      ) : (
        <Text style={[styles.modelErr, { color: colors.textMuted }]} numberOfLines={2}>
          {model.error || "tidak tersedia"}
        </Text>
      )}
    </View>
  );
}

export default function AssetDetail() {
  const { colors } = useTheme();
  const { lang, t } = useI18n();
  const router = useRouter();
  const params = useLocalSearchParams<{ market: string; symbol: string; timeframe?: string }>();
  const validMarkets = ["crypto", "etf", "stock_id", "stock_us"] as const;
  const market = (validMarkets.includes(params.market as Market) ? params.market : "crypto") as Market;
  const symbol = String(params.symbol || "").toUpperCase();
  const initialTf = (TIMEFRAMES.includes(params.timeframe as Timeframe) ? params.timeframe : "1h") as Timeframe;

  const [timeframe, setTimeframe] = useState<Timeframe>(initialTf);
  const [chart, setChart] = useState<ChartResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [trackRecord, setTrackRecord] = useState<TrackRecordResponse | null>(null);
  // Live-fetched AI model labels from backend. If backend swaps models
  // (e.g. Sonnet 4.6 → Sonnet 5), the hint text updates without a
  // mobile rebuild. Falls back to a generic label if endpoint is down.
  const [aiModelLabels, setAiModelLabels] = useState<string[]>([]);
  const [loadingChart, setLoadingChart] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string>("");
  const [translatedReasons, setTranslatedReasons] = useState<string[] | null>(null);
  const [translatedNewsFactors, setTranslatedNewsFactors] = useState<string[] | null>(null);
  const [translatedRiskFactors, setTranslatedRiskFactors] = useState<string[] | null>(null);
  const [translatedSummary, setTranslatedSummary] = useState<string | null>(null);
  const [translatedTfView, setTranslatedTfView] = useState<string | null>(null);
  const [chartType, setChartType] = useState<"candlestick" | "line">("candlestick");
  const [showPrediction, setShowPrediction] = useState(false);

  // Access gating (issue #2, #3) — kick user back to home if entitlement expires
  const { isPremium, loaded: subLoaded } = useSubscription();
  const { isUnlocked, loaded: authLoaded } = useAuth();
  const hasAccess = isPremium || isUnlocked;
  useEffect(() => {
    // Wait until BOTH auth and subscription state are fully loaded (including
    // backend sync) before deciding to redirect. Prevents a false-negative
    // flash where subscribed users are briefly kicked to home on cold start.
    if (!authLoaded || !subLoaded) return;
    if (!hasAccess) {
      try {
        router.replace("/");
      } catch {
        /* ignore */
      }
    }
  }, [hasAccess, authLoaded, subLoaded]);

  const loadChart = useCallback(
    async (tf: Timeframe) => {
      setLoadingChart(true);
      setError("");
      try {
        const c = await api.chart(market, symbol, tf);
        setChart(c);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoadingChart(false);
      }
    },
    [market, symbol],
  );

  const runAnalysis = useCallback(async () => {
    setAnalyzing(true);
    setError("");
    try {
      const a = await api.analyze(market, symbol, timeframe, lang);
      setAnalysis(a);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAnalyzing(false);
    }
  }, [market, symbol, timeframe, lang]);

  useEffect(() => {
    void loadChart(timeframe);
    setAnalysis(null);
  }, [timeframe, loadChart]);

  // Translate technical reasoning bullets when EN selected (cached server-side)
  useEffect(() => {
    const reasons = chart?.signal?.reasons;
    if (!reasons || reasons.length === 0 || lang !== "en") {
      setTranslatedReasons(null);
      return;
    }
    let live = true;
    (async () => {
      try {
        const r = await api.translate(reasons, "en");
        if (live) setTranslatedReasons(r.items);
      } catch {
        if (live) setTranslatedReasons(null);
      }
    })();
    return () => {
      live = false;
    };
  }, [chart, lang]);

  // Translate AI consensus narrative bullets (news_factors / risk_factors / summary / tf view)
  useEffect(() => {
    if (!analysis || lang !== "en") {
      setTranslatedNewsFactors(null);
      setTranslatedRiskFactors(null);
      setTranslatedSummary(null);
      setTranslatedTfView(null);
      return;
    }
    let live = true;
    const news = analysis.consensus.news_factors || [];
    const risk = analysis.consensus.risk_factors || [];
    const summary = analysis.consensus.summary || "";
    const tfView = analysis.consensus.timeframe_view || "";
    (async () => {
      try {
        const allBatch = [summary, tfView, ...news, ...risk];
        const r = await api.translate(allBatch, "en");
        if (!live) return;
        const items = r.items;
        setTranslatedSummary(items[0] || null);
        setTranslatedTfView(items[1] || null);
        setTranslatedNewsFactors(items.slice(2, 2 + news.length));
        setTranslatedRiskFactors(items.slice(2 + news.length, 2 + news.length + risk.length));
      } catch {
        if (live) {
          setTranslatedNewsFactors(null);
          setTranslatedRiskFactors(null);
          setTranslatedSummary(null);
          setTranslatedTfView(null);
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [analysis, lang]);

  // Load track record once per asset
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const tr = await api.trackRecord(market, symbol);
        if (live) setTrackRecord(tr);
      } catch {
        if (live) setTrackRecord(null);
      }
    })();
    return () => {
      live = false;
    };
  }, [market, symbol]);

  // Fetch current AI model labels once on mount (backend-driven, so
  // Sonnet/Opus/Fable versions stay in sync with whatever the backend
  // actually uses right now).
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const r = await api.aiModels();
        if (live && Array.isArray(r?.models)) {
          setAiModelLabels(r.models.map((m) => m.name).filter(Boolean));
        }
      } catch {
        /* ignore — fallback text will render */
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const ticker = chart?.ticker ?? {};
  const sig = chart?.signal;
  const sigColors = signalColors(colors, sig?.action || "HOLD");
  const change = ticker.change_pct_24h ?? 0;
  const changeColor = change >= 0 ? colors.accentUp : colors.accentDown;

  // Target Profit % (issue #6) — POSITIVE profit target regardless of direction.
  // For BUY/LONG: (take_profit - entry) / entry
  // For SELL/SHORT: (entry - take_profit) / entry
  // Always displayed as a positive % because it represents PROFIT if the trade succeeds.
  const tpPct: number | null = (() => {
    if (!sig || !sig.take_profit || !sig.entry) return null;
    if (sig.action === "HOLD") return null;
    const isShort = sig.action === "SHORT" || sig.action === "SELL";
    const raw = isShort
      ? ((sig.entry - sig.take_profit) / sig.entry) * 100
      : ((sig.take_profit - sig.entry) / sig.entry) * 100;
    return Number.isFinite(raw) ? Math.abs(raw) : null;
  })();
  // Always green (profit target)
  const tpColor = colors.accentUp;

  const screenW = Dimensions.get("window").width - 32;

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          testID="back-button"
          style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1, marginLeft: 12 }}>
          <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between" }}>
            <View style={{ flex: 1, marginRight: 8 }}>
              <Text style={[styles.symbolTitle, { color: colors.textPrimary }]} numberOfLines={1}>
                {symbol} <Text style={[styles.marketBadge, { color: colors.textMuted }]}>{t(
                  market === "crypto" ? "badge_crypto" :
                  market === "etf" ? "badge_etf" :
                  market === "stock_us" ? "badge_stock_us" :
                  "badge_stock_id"
                )}</Text>
              </Text>
              <Text style={[styles.priceBig, { color: colors.textPrimary }]}>
                {formatPrice(ticker.price ?? null, market)}{" "}
                <Text style={{ color: changeColor, fontSize: 14, fontWeight: "600" }}>{formatPct(ticker.change_pct_24h)}</Text>
              </Text>
            </View>
            <View style={{ alignItems: "flex-end", gap: 6 }}>
              {tpPct !== null ? (
                <View
                  style={{
                    paddingHorizontal: 10,
                    paddingVertical: 6,
                    borderRadius: 8,
                    backgroundColor: tpColor + "22",
                    borderWidth: 1.5,
                    borderColor: tpColor,
                    alignItems: "center",
                    minWidth: 76,
                  }}
                  testID="header-target-profit"
                >
                  <Text style={{ fontSize: 9, color: tpColor, letterSpacing: 0.6, fontWeight: "700", lineHeight: 11 }}>
                    Target
                  </Text>
                  <Text style={{ fontSize: 9, color: tpColor, letterSpacing: 0.6, fontWeight: "700", lineHeight: 11 }}>
                    Profit
                  </Text>
                  <Text style={{ fontSize: 15, color: tpColor, fontWeight: "900", fontVariant: ["tabular-nums"], marginTop: 2 }}>
                    +{tpPct.toFixed(2)}%
                  </Text>
                </View>
              ) : null}
              {/* Chatroom button — full-width label */}
              <TouchableOpacity
                onPress={() => router.push("/chat" as never)}
                testID="chat-button"
                style={{
                  minWidth: 100,
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                  borderRadius: 8,
                  backgroundColor: colors.accentBlue + "22",
                  borderWidth: 1.5,
                  borderColor: colors.accentBlue,
                  alignItems: "center",
                  flexDirection: "row",
                  justifyContent: "center",
                  gap: 5,
                }}
              >
                <Ionicons name="chatbubbles" size={13} color={colors.accentBlue} />
                <Text style={{ fontSize: 11, color: colors.accentBlue, fontWeight: "800", letterSpacing: 0.4 }}>
                  CHATROOM
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ paddingBottom: 32 }}>
        {/* Timeframe row */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.tfRowContent}
        >
          {TIMEFRAMES.map((tf) => {
            const active = tf === timeframe;
            return (
              <TouchableOpacity
                key={tf}
                onPress={() => setTimeframe(tf)}
                testID={`detail-timeframe-${tf}`}
                style={[
                  styles.tfPill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Text style={[styles.tfPillText, { color: active ? "#fff" : colors.textSecondary }]}>{tf}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>

        {/* Chart */}
        <View style={[styles.chartBox, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          {/* Chart type toggle */}
          <View style={styles.chartToggleRow}>
            <TouchableOpacity
              testID="chart-toggle-candlestick"
              onPress={() => setChartType("candlestick")}
              style={[
                styles.chartToggleBtn,
                {
                  backgroundColor:
                    chartType === "candlestick" ? colors.accentBlue + "26" : "transparent",
                  borderColor:
                    chartType === "candlestick" ? colors.accentBlue : colors.border,
                },
              ]}
            >
              <Ionicons
                name="stats-chart"
                size={12}
                color={chartType === "candlestick" ? colors.accentBlue : colors.textMuted}
              />
              <Text
                style={[
                  styles.chartToggleText,
                  {
                    color:
                      chartType === "candlestick" ? colors.accentBlue : colors.textMuted,
                  },
                ]}
              >
                Candlestick
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="chart-toggle-line"
              onPress={() => setChartType("line")}
              style={[
                styles.chartToggleBtn,
                {
                  backgroundColor:
                    chartType === "line" ? colors.accentBlue + "26" : "transparent",
                  borderColor:
                    chartType === "line" ? colors.accentBlue : colors.border,
                },
              ]}
            >
              <Ionicons
                name="analytics"
                size={12}
                color={chartType === "line" ? colors.accentBlue : colors.textMuted}
              />
              <Text
                style={[
                  styles.chartToggleText,
                  { color: chartType === "line" ? colors.accentBlue : colors.textMuted },
                ]}
              >
                Line
              </Text>
            </TouchableOpacity>
          </View>
          {loadingChart ? (
            <View style={styles.chartLoader}>
              <ActivityIndicator color={colors.accentBlue} />
            </View>
          ) : chartType === "candlestick" ? (
            <CandlestickChart
              candles={chart?.candles || []}
              width={screenW - 24}
              height={220}
            />
          ) : (
            <PriceChart candles={chart?.candles || []} width={screenW - 24} height={180} />
          )}
          <View style={styles.statsRow}>
            <View style={styles.statItem}>
              <Text style={[styles.statLabel, { color: colors.textMuted }]}>HIGH 24H</Text>
              <Text style={[styles.statVal, { color: colors.textPrimary }]}>{formatPrice(ticker.high_24h ?? null, market)}</Text>
            </View>
            <View style={styles.statItem}>
              <Text style={[styles.statLabel, { color: colors.textMuted }]}>LOW 24H</Text>
              <Text style={[styles.statVal, { color: colors.textPrimary }]}>{formatPrice(ticker.low_24h ?? null, market)}</Text>
            </View>
            <View style={styles.statItem}>
              <Text style={[styles.statLabel, { color: colors.textMuted }]}>VOLUME</Text>
              <Text style={[styles.statVal, { color: colors.textPrimary }]}>
                {ticker.volume_24h ? formatVolume(ticker.volume_24h) : "—"}
              </Text>
            </View>
          </View>
        </View>

        {/* Technical signal */}
        {sig && (
          <View style={[styles.section, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <View style={styles.sectionHeader}>
              <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>{t("detail_signal")}</Text>
              <View style={[styles.signalPillLarge, { backgroundColor: sigColors.bg }]}>
                <Text style={[styles.signalTextLarge, { color: sigColors.fg }]}>
                  {sig.label} • {sig.confidence}%
                </Text>
              </View>
            </View>
            <View style={styles.indGrid}>
              <IndicatorCell label="RSI(14)" value={sig.indicators.rsi?.toFixed(1) ?? "—"} colors={colors} />
              <IndicatorCell label="EMA20" value={formatPrice(sig.indicators.ema20 as number, market)} colors={colors} />
              <IndicatorCell label="EMA50" value={formatPrice(sig.indicators.ema50 as number, market)} colors={colors} />
              <IndicatorCell label="MACD H" value={(sig.indicators.macd_hist ?? 0).toFixed(4)} colors={colors} />
            </View>
            <View style={styles.entryRow}>
              <EntryCell label={t("detail_entry")} value={formatPrice(sig.entry, market)} color={colors.accentBlue} colors={colors} />
              <EntryCell label={t("detail_stop")} value={formatPrice(sig.stop_loss, market)} color={colors.accentDown} colors={colors} />
              <EntryCell label={t("detail_tp")} value={formatPrice(sig.take_profit, market)} color={colors.accentUp} colors={colors} />
            </View>
            {sig.reasons.length > 0 && (
              <View style={{ marginTop: 10 }}>
                {(translatedReasons && translatedReasons.length === sig.reasons.length ? translatedReasons : sig.reasons).map((r, i) => (
                  <Text key={i} style={[styles.reasonLine, { color: colors.textSecondary }]}>
                    • {r}
                  </Text>
                ))}
              </View>
            )}
          </View>
        )}

        {/* Track Record */}
        {trackRecord && (trackRecord.win_rate_30d.total > 0 || trackRecord.win_rate_7d.total > 0) && (
          <View style={[styles.section, { backgroundColor: colors.surface, borderColor: colors.border }]} testID="track-record-section">
            <View style={styles.sectionHeader}>
              <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>📊 {t("detail_track_record")}</Text>
              <Text style={[styles.aiHint, { color: colors.textMuted, marginTop: 0 }]}>
                {trackRecord.win_rate_all.total} {t("detail_historic_signals")}
              </Text>
            </View>
            <View style={styles.entryRow}>
              <WrCell label={t("detail_wr_7d")} stat={trackRecord.win_rate_7d} colors={colors} />
              <WrCell label={t("detail_wr_30d")} stat={trackRecord.win_rate_30d} colors={colors} />
              <WrCell label={t("detail_wr_all")} stat={trackRecord.win_rate_all} colors={colors} />
            </View>
            {trackRecord.recent_signals.length > 0 && (
              <View style={{ marginTop: 12 }}>
                <Text style={[styles.subTitle, { color: colors.textPrimary, marginBottom: 8 }]}>{t("detail_recent_signals")}</Text>
                {trackRecord.recent_signals.slice(0, 5).map((s, i) => {
                  const sigCol = signalColors(colors, s.action);
                  const hit = s.evaluation?.hit;
                  return (
                    <View key={i} style={[styles.recentRow, { borderBottomColor: colors.border }]} testID={`recent-signal-${i}`}>
                      <View style={[styles.signalPill, { backgroundColor: sigCol.bg }]}>
                        <Text style={[styles.signalText, { color: sigCol.fg }]}>{s.label}</Text>
                      </View>
                      <Text style={[styles.recentDate, { color: colors.textMuted }]}>
                        {new Date(s.created_at).toLocaleDateString(lang === "en" ? "en-US" : "id-ID", { day: "2-digit", month: "short" })}
                      </Text>
                      <Text style={[styles.recentTf, { color: colors.textSecondary }]}>{s.timeframe}</Text>
                      <Text style={[styles.recentPct, { color: hit ? colors.accentUp : colors.accentDown }]}>
                        {hit ? "✓" : "✗"} {formatPct(s.evaluation?.pct_change)}
                      </Text>
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        )}

        {/* AI Ensemble */}
        <View style={[styles.section, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.sectionHeader}>
            <Text style={[styles.sectionTitle, { color: colors.textPrimary, flexShrink: 1 }]} numberOfLines={1}>{t("detail_ai_section")}</Text>
            <View style={{ flexDirection: "row", gap: 4, flexShrink: 0 }}>
              <TouchableOpacity
                onPress={() => setShowPrediction((s) => !s)}
                testID="run-ai-prediction-button"
                style={[
                  styles.aiSmallBtn,
                  {
                    backgroundColor: showPrediction ? colors.accentUp : colors.accentUp + "22",
                    borderWidth: showPrediction ? 0 : 1,
                    borderColor: colors.accentUp,
                  },
                ]}
              >
                <Ionicons name="flash" size={11} color={showPrediction ? "#fff" : colors.accentUp} />
                <Text style={[styles.aiSmallBtnText, { color: showPrediction ? "#fff" : colors.accentUp }]}>
                  {t("detail_ai_predict_btn")}
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={runAnalysis}
                disabled={analyzing}
                testID="run-ai-analysis-button"
                style={[styles.aiSmallBtn, { backgroundColor: analyzing ? colors.surfaceHighlight : colors.accentBlue }]}
              >
                {analyzing ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <>
                    <Ionicons name="sparkles" size={11} color="#fff" />
                    <Text style={[styles.aiSmallBtnText, { color: "#fff" }]}>{analysis ? t("detail_ai_repeat") : t("detail_ai_btn")}</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>

          {/* AI Prediction card (instant, no API call) */}
          {showPrediction && chart?.signal ? (
            <View
              style={{
                backgroundColor: colors.accentUp + "10",
                borderColor: colors.accentUp + "55",
                borderWidth: 1,
                borderRadius: 10,
                padding: 12,
                marginBottom: 12,
              }}
            >
              {(() => {
                const s = chart.signal!;
                const isUp = s.action === "BUY" || s.action === "LONG";
                const isDown = s.action === "SELL" || s.action === "SHORT";
                const dirLabel = isUp ? "UP ↑" : isDown ? "DOWN ↓" : "SIDEWAYS →";
                const dirColor = isUp ? colors.accentUp : isDown ? colors.accentDown : colors.accentHold;
                const conf = s.confidence ?? 0;
                const horizonLabel = `Next ${timeframe}`;
                const suggestion = isUp
                  ? `Prepare BUY. Watch entry ~${formatPrice(s.entry, market)}, TP ${formatPrice(s.take_profit, market)}, SL ${formatPrice(s.stop_loss, market)}.`
                  : isDown
                    ? `Prepare SHORT. Watch entry ~${formatPrice(s.entry, market)}, TP ${formatPrice(s.take_profit, market)}, SL ${formatPrice(s.stop_loss, market)}.`
                    : "Wait — no clear momentum yet. Watch break of recent high/low for next signal.";
                return (
                  <>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <Ionicons name="flash" size={16} color={dirColor} />
                      <Text style={{ fontSize: 12, fontWeight: "800", color: colors.textPrimary }}>
                        AI PREDICTION · {horizonLabel}
                      </Text>
                    </View>
                    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <Text style={{ fontSize: 22, fontWeight: "900", color: dirColor, letterSpacing: 0.6 }}>
                        {dirLabel}
                      </Text>
                      <View style={{ alignItems: "flex-end" }}>
                        <Text style={{ fontSize: 10, color: colors.textMuted, letterSpacing: 0.5 }}>CONFIDENCE</Text>
                        <Text style={{ fontSize: 18, fontWeight: "900", color: dirColor, fontVariant: ["tabular-nums"] }}>
                          {conf.toFixed(0)}%
                        </Text>
                      </View>
                    </View>
                    <Text style={{ fontSize: 12, color: colors.textPrimary, lineHeight: 18 }}>{suggestion}</Text>
                    {s.reasons && s.reasons.length > 0 ? (
                      <View style={{ marginTop: 8 }}>
                        {s.reasons.slice(0, 3).map((r, i) => (
                          <Text key={i} style={{ fontSize: 11, color: colors.textMuted, marginTop: 2 }}>
                            • {r}
                          </Text>
                        ))}
                      </View>
                    ) : null}
                    <Text style={{ fontSize: 9, color: colors.textMuted, marginTop: 8, fontStyle: "italic" }}>
                      Instant prediction from technical indicators. Tap {t("detail_ai_btn")} for full multi-model deep analysis.
                    </Text>
                  </>
                );
              })()}
            </View>
          ) : null}

          {!analysis && !analyzing && (
            <Text style={[styles.aiHint, { color: colors.textMuted }]}>
              {aiModelLabels.length >= 2
                ? t("detail_ai_hint_template")
                    .replace("{models}", aiModelLabels.join(" + "))
                : t("detail_ai_hint")}
            </Text>
          )}

          {analysis && (
            <View>
              {/* Consensus */}
              <View
                style={[
                  styles.consensusBox,
                  {
                    borderColor: signalColors(colors, analysis.consensus.action).fg,
                    backgroundColor: signalColors(colors, analysis.consensus.action).bg,
                  },
                ]}
              >
                <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("detail_consensus")}</Text>
                <Text style={[styles.consensusAction, { color: signalColors(colors, analysis.consensus.action).fg }]}>
                  {analysis.consensus.label} • {analysis.consensus.confidence}%
                </Text>
                <Text style={[styles.consensusSummary, { color: colors.textPrimary }]}>
                  {translatedSummary ?? analysis.consensus.summary}
                </Text>
                {analysis.consensus.timeframe_view ? (
                  <Text style={[styles.consensusTfView, { color: colors.textSecondary }]}>
                    📊 {translatedTfView ?? analysis.consensus.timeframe_view}
                  </Text>
                ) : null}
              </View>

              {/* Per-model */}
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 12 }}>
                <View style={{ flexDirection: "row", gap: 8 }}>
                  {analysis.models.map((m) => (
                    <ModelChip key={m.name} model={m} />
                  ))}
                </View>
              </ScrollView>

              {/* Entry/SL/TP from AI */}
              <View style={[styles.entryRow, { marginTop: 16 }]}>
                <EntryCell label={t("detail_ai_entry")} value={formatPrice(analysis.consensus.entry, market)} color={colors.accentBlue} colors={colors} />
                <EntryCell label={t("detail_ai_sl")} value={formatPrice(analysis.consensus.stop_loss, market)} color={colors.accentDown} colors={colors} />
                <EntryCell label={t("detail_ai_tp")} value={formatPrice(analysis.consensus.take_profit, market)} color={colors.accentUp} colors={colors} />
              </View>

              {/* Multi-level Target Profit (Fase 3) — ATR-based TP1/TP2/TP3 + SL */}
              <TargetProfit
                action={analysis.consensus.action}
                entryPrice={
                  analysis.consensus.entry ??
                  analysis.price ??
                  (chart?.candles?.[chart.candles.length - 1]?.close ?? 0)
                }
                candles={chart?.candles ?? []}
                confidence={analysis.consensus.confidence}
                label={analysis.consensus.label}
              />

              {/* News & Risk */}
              {analysis.consensus.news_factors.length > 0 && (
                <View style={{ marginTop: 16 }}>
                  <Text style={[styles.subTitle, { color: colors.textPrimary }]}>{t("detail_news_factors")}</Text>
                  {(translatedNewsFactors && translatedNewsFactors.length === analysis.consensus.news_factors.length
                    ? translatedNewsFactors
                    : analysis.consensus.news_factors
                  ).map((n, i) => (
                    <Text key={i} style={[styles.bullet, { color: colors.textSecondary }]}>
                      • {n}
                    </Text>
                  ))}
                </View>
              )}
              {analysis.consensus.risk_factors.length > 0 && (
                <View style={{ marginTop: 12 }}>
                  <Text style={[styles.subTitle, { color: colors.textPrimary }]}>{t("detail_risk")}</Text>
                  {(translatedRiskFactors && translatedRiskFactors.length === analysis.consensus.risk_factors.length
                    ? translatedRiskFactors
                    : analysis.consensus.risk_factors
                  ).map((n, i) => (
                    <Text key={i} style={[styles.bullet, { color: colors.textSecondary }]}>
                      • {n}
                    </Text>
                  ))}
                </View>
              )}

              {analysis.news_used.length > 0 && (
                <View style={{ marginTop: 16 }}>
                  <Text style={[styles.subTitle, { color: colors.textPrimary }]}>
                    {t("detail_news_live")} ({analysis.news_used.length})
                  </Text>
                  {analysis.news_used.slice(0, 6).map((n, i) => (
                    <TouchableOpacity
                      key={i}
                      onPress={() => n.url && Linking.openURL(n.url).catch(() => {})}
                      activeOpacity={n.url ? 0.7 : 1}
                      testID={`news-used-${i}`}
                      style={[styles.newsRow, { borderColor: colors.border }]}
                    >
                      <View style={styles.newsHeadRow}>
                        <Text style={[styles.newsSource, { color: colors.accentBlue }]} numberOfLines={1}>
                          {n.source}
                        </Text>
                        {n.published ? (
                          <Text style={[styles.newsTime, { color: colors.textMuted }]}>
                            {new Date(n.published).toLocaleDateString(lang === "en" ? "en-US" : "id-ID", { day: "2-digit", month: "short" })}
                          </Text>
                        ) : null}
                      </View>
                      <Text style={[styles.newsTitle, { color: colors.textSecondary }]} numberOfLines={2}>
                        {n.title}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              )}

              <Text style={[styles.generatedAt, { color: colors.textMuted }]}>
                {t("detail_generated_at")}: {new Date(analysis.generated_at).toLocaleString(lang === "en" ? "en-US" : "id-ID")}
              </Text>
            </View>
          )}
        </View>

        {error ? (
          <View style={[styles.section, { backgroundColor: colors.surface, borderColor: colors.accentDown }]}>
            <Text style={{ color: colors.accentDown }}>Error: {error}</Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function IndicatorCell({ label, value, colors }: { label: string; value: string; colors: ReturnType<typeof useTheme>["colors"] }) {
  return (
    <View style={[styles.indCell, { backgroundColor: colors.surfaceAlt }]}>
      <Text style={[styles.indLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.indVal, { color: colors.textPrimary }]}>{value}</Text>
    </View>
  );
}

function EntryCell({ label, value, color, colors }: {
  label: string; value: string; color: string;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={[styles.entryCell, { backgroundColor: colors.surfaceAlt, borderLeftColor: color }]}>
      <Text style={[styles.entryLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.entryVal, { color }]}>{value}</Text>
    </View>
  );
}

function WrCell({ label, stat, colors }: {
  label: string;
  stat: { total: number; hits: number; win_rate: number | null };
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  const wr = stat.win_rate;
  const color = wr === null ? colors.textMuted : wr >= 65 ? colors.accentUp : wr >= 50 ? colors.accentHold : colors.accentDown;
  return (
    <View style={[styles.entryCell, { backgroundColor: colors.surfaceAlt, borderLeftColor: color }]}>
      <Text style={[styles.entryLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.entryVal, { color }]}>
        {wr === null ? "—" : `${wr.toFixed(0)}%`}
      </Text>
      <Text style={[styles.entryLabel, { color: colors.textMuted, marginTop: 2 }]}>
        {stat.hits}/{stat.total} hit
      </Text>
    </View>
  );
}

function formatVolume(v: number): string {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
  if (v >= 1e6) return (v / 1e6).toFixed(2) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(2) + "K";
  return v.toFixed(0);
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  symbolTitle: { fontSize: 20, fontWeight: "700", letterSpacing: 0.4 },
  marketBadge: { fontSize: 10, fontWeight: "600", letterSpacing: 1 },
  priceBig: { fontSize: 22, fontWeight: "700", fontVariant: ["tabular-nums"], marginTop: 2 },
  tfRowContent: { paddingHorizontal: 16, gap: 8, paddingVertical: 8 },
  tfPill: {
    height: 36, minWidth: 50, paddingHorizontal: 14,
    borderRadius: 18, borderWidth: 1, flexShrink: 0,
    alignItems: "center", justifyContent: "center",
  },
  tfPillText: { fontSize: 12, fontWeight: "600" },
  chartBox: {
    marginHorizontal: 16,
    marginTop: 8,
    borderRadius: 12,
    borderWidth: 1,
    padding: 12,
  },
  chartLoader: { height: 180, alignItems: "center", justifyContent: "center" },
  chartToggleRow: {
    flexDirection: "row",
    gap: 6,
    marginBottom: 10,
    justifyContent: "flex-end",
  },
  chartToggleBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 6,
    borderWidth: 1,
  },
  chartToggleText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.4 },
  statsRow: { flexDirection: "row", marginTop: 12, gap: 8 },
  statItem: { flex: 1 },
  statLabel: { fontSize: 9, letterSpacing: 0.6 },
  statVal: { fontSize: 13, fontWeight: "600", fontVariant: ["tabular-nums"], marginTop: 2 },
  section: {
    marginHorizontal: 16,
    marginTop: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
  },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  sectionTitle: { fontSize: 15, fontWeight: "700" },
  signalPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  signalText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  signalPillLarge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6 },
  signalTextLarge: { fontSize: 12, fontWeight: "700", letterSpacing: 0.5 },
  indGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 12 },
  indCell: {
    width: "47%",
    padding: 10,
    borderRadius: 8,
  },
  indLabel: { fontSize: 10, letterSpacing: 0.5 },
  indVal: { fontSize: 14, fontWeight: "600", fontVariant: ["tabular-nums"], marginTop: 2 },
  entryRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  entryCell: {
    flex: 1, padding: 10, borderRadius: 8, borderLeftWidth: 3,
  },
  entryLabel: { fontSize: 9, letterSpacing: 0.5 },
  entryVal: { fontSize: 13, fontWeight: "700", fontVariant: ["tabular-nums"], marginTop: 2 },
  reasonLine: { fontSize: 12, lineHeight: 18, marginTop: 2 },
  analyzeBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
  },
  analyzeBtnText: { color: "#fff", fontSize: 12, fontWeight: "700", letterSpacing: 0.5 },
  aiSmallBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 6,
    borderRadius: 6,
    minWidth: 74,
    justifyContent: "center",
  },
  aiSmallBtnText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.3 },
  aiHint: { fontSize: 12, lineHeight: 18, marginTop: 10 },
  consensusBox: {
    marginTop: 12,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
  },
  consensusLabel: { fontSize: 10, letterSpacing: 1 },
  consensusAction: { fontSize: 22, fontWeight: "800", marginTop: 2 },
  consensusSummary: { fontSize: 13, lineHeight: 20, marginTop: 8 },
  consensusTfView: { fontSize: 12, marginTop: 8 },
  modelChip: {
    width: 130,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  modelName: { fontSize: 11, fontWeight: "700" },
  modelConf: { fontSize: 14, fontWeight: "700", marginTop: 4 },
  modelErr: { fontSize: 10, marginTop: 6 },
  subTitle: { fontSize: 13, fontWeight: "700", marginBottom: 4 },
  bullet: { fontSize: 12, lineHeight: 19 },
  newsRow: { paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth },
  newsHeadRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: 2 },
  newsSource: { fontSize: 10, fontWeight: "700", letterSpacing: 0.4, flex: 1 },
  newsTime: { fontSize: 10, marginLeft: 8 },
  newsTitle: { fontSize: 12, lineHeight: 17 },
  generatedAt: { fontSize: 10, marginTop: 12, textAlign: "right" },
  recentRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth,
  },
  recentDate: { fontSize: 11, width: 56 },
  recentTf: { fontSize: 10, width: 32 },
  recentPct: { fontSize: 11, fontWeight: "700", textAlign: "right", flex: 1 },
});
