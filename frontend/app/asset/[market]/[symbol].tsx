import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import PriceChart from "@/src/components/PriceChart";
import {
  TIMEFRAMES,
  type AnalyzeResponse,
  type ChartResponse,
  type Market,
  type ModelResult,
  type Timeframe,
  api,
  formatPct,
  formatPrice,
} from "@/src/lib/api";
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
  const router = useRouter();
  const params = useLocalSearchParams<{ market: string; symbol: string; timeframe?: string }>();
  const market = (params.market === "stock" ? "stock" : "crypto") as Market;
  const symbol = String(params.symbol || "").toUpperCase();
  const initialTf = (TIMEFRAMES.includes(params.timeframe as Timeframe) ? params.timeframe : "1h") as Timeframe;

  const [timeframe, setTimeframe] = useState<Timeframe>(initialTf);
  const [chart, setChart] = useState<ChartResponse | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [loadingChart, setLoadingChart] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string>("");

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
      const a = await api.analyze(market, symbol, timeframe);
      setAnalysis(a);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAnalyzing(false);
    }
  }, [market, symbol, timeframe]);

  useEffect(() => {
    void loadChart(timeframe);
    setAnalysis(null);
  }, [timeframe, loadChart]);

  const ticker = chart?.ticker ?? {};
  const sig = chart?.signal;
  const sigColors = signalColors(colors, sig?.action || "HOLD");
  const change = ticker.change_pct_24h ?? 0;
  const changeColor = change >= 0 ? colors.accentUp : colors.accentDown;

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
          <Text style={[styles.symbolTitle, { color: colors.textPrimary }]}>
            {symbol} <Text style={[styles.marketBadge, { color: colors.textMuted }]}>{market === "crypto" ? "CRYPTO" : "SAHAM"}</Text>
          </Text>
          <Text style={[styles.priceBig, { color: colors.textPrimary }]}>
            {formatPrice(ticker.price ?? null, market)}{" "}
            <Text style={{ color: changeColor, fontSize: 14, fontWeight: "600" }}>{formatPct(ticker.change_pct_24h)}</Text>
          </Text>
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
          {loadingChart ? (
            <View style={styles.chartLoader}>
              <ActivityIndicator color={colors.accentBlue} />
            </View>
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
              <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Sinyal Teknikal</Text>
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
              <EntryCell label="ENTRY" value={formatPrice(sig.entry, market)} color={colors.accentBlue} colors={colors} />
              <EntryCell label="STOP LOSS" value={formatPrice(sig.stop_loss, market)} color={colors.accentDown} colors={colors} />
              <EntryCell label="TAKE PROFIT" value={formatPrice(sig.take_profit, market)} color={colors.accentUp} colors={colors} />
            </View>
            {sig.reasons.length > 0 && (
              <View style={{ marginTop: 10 }}>
                {sig.reasons.map((r, i) => (
                  <Text key={i} style={[styles.reasonLine, { color: colors.textSecondary }]}>
                    • {r}
                  </Text>
                ))}
              </View>
            )}
          </View>
        )}

        {/* AI Ensemble */}
        <View style={[styles.section, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.sectionHeader}>
            <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Multi-AI Ensemble</Text>
            <TouchableOpacity
              onPress={runAnalysis}
              disabled={analyzing}
              testID="run-ai-analysis-button"
              style={[styles.analyzeBtn, { backgroundColor: analyzing ? colors.surfaceHighlight : colors.accentBlue }]}
            >
              {analyzing ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <>
                  <Ionicons name="sparkles" size={14} color="#fff" />
                  <Text style={styles.analyzeBtnText}>{analysis ? "ULANGI" : "ANALISA AI"}</Text>
                </>
              )}
            </TouchableOpacity>
          </View>

          {!analysis && !analyzing && (
            <Text style={[styles.aiHint, { color: colors.textMuted }]}>
              Tekan ANALISA AI untuk konsensus Claude Sonnet 4.6 + GPT-5.4 + Gemini 3.1 Pro
              berdasarkan teknikal, berita global, makro & politik terkini.
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
                <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>KONSENSUS AI</Text>
                <Text style={[styles.consensusAction, { color: signalColors(colors, analysis.consensus.action).fg }]}>
                  {analysis.consensus.label} • {analysis.consensus.confidence}%
                </Text>
                <Text style={[styles.consensusSummary, { color: colors.textPrimary }]}>
                  {analysis.consensus.summary}
                </Text>
                {analysis.consensus.timeframe_view ? (
                  <Text style={[styles.consensusTfView, { color: colors.textSecondary }]}>
                    📊 {analysis.consensus.timeframe_view}
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
                <EntryCell label="AI ENTRY" value={formatPrice(analysis.consensus.entry, market)} color={colors.accentBlue} colors={colors} />
                <EntryCell label="AI SL" value={formatPrice(analysis.consensus.stop_loss, market)} color={colors.accentDown} colors={colors} />
                <EntryCell label="AI TP" value={formatPrice(analysis.consensus.take_profit, market)} color={colors.accentUp} colors={colors} />
              </View>

              {/* News & Risk */}
              {analysis.consensus.news_factors.length > 0 && (
                <View style={{ marginTop: 16 }}>
                  <Text style={[styles.subTitle, { color: colors.textPrimary }]}>📰 Faktor Berita & Makro</Text>
                  {analysis.consensus.news_factors.map((n, i) => (
                    <Text key={i} style={[styles.bullet, { color: colors.textSecondary }]}>
                      • {n}
                    </Text>
                  ))}
                </View>
              )}
              {analysis.consensus.risk_factors.length > 0 && (
                <View style={{ marginTop: 12 }}>
                  <Text style={[styles.subTitle, { color: colors.textPrimary }]}>⚠️ Risiko</Text>
                  {analysis.consensus.risk_factors.map((n, i) => (
                    <Text key={i} style={[styles.bullet, { color: colors.textSecondary }]}>
                      • {n}
                    </Text>
                  ))}
                </View>
              )}
              <Text style={[styles.generatedAt, { color: colors.textMuted }]}>
                Dianalisa: {new Date(analysis.generated_at).toLocaleString("id-ID")}
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
  generatedAt: { fontSize: 10, marginTop: 12, textAlign: "right" },
});
