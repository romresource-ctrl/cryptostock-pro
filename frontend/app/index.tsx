import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import Sparkline from "@/src/components/Sparkline";
import { TIMEFRAMES, type AssetSignal, type Market, type Timeframe, api, formatPct, formatPrice } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

const REFRESH_INTERVAL_MS = 60_000;

function signalColors(colors: ReturnType<typeof useTheme>["colors"], action: string) {
  if (action === "BUY") return { fg: colors.accentUp, bg: colors.accentUp + "26" };
  if (action === "SELL") return { fg: colors.accentDown, bg: colors.accentDown + "26" };
  return { fg: colors.accentHold, bg: colors.accentHold + "26" };
}

function AssetCard({
  asset,
  onPress,
  market,
}: {
  asset: AssetSignal;
  onPress: () => void;
  market: Market;
}) {
  const { colors } = useTheme();
  const sig = signalColors(colors, asset.action);
  const change = asset.change_pct_24h ?? 0;
  const changeColor = change >= 0 ? colors.accentUp : colors.accentDown;

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.75}
      testID={`asset-card-${market}-${asset.symbol}`}
      style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}
    >
      <View style={styles.cardTop}>
        <Text style={[styles.ticker, { color: colors.textPrimary }]} numberOfLines={1}>
          {asset.symbol}
        </Text>
        <View style={[styles.signalPill, { backgroundColor: sig.bg }]}>
          <Text style={[styles.signalText, { color: sig.fg }]}>{asset.label}</Text>
        </View>
      </View>

      <View style={styles.cardMid}>
        <Text style={[styles.price, { color: colors.textPrimary }]} numberOfLines={1}>
          {formatPrice(asset.price, market)}
        </Text>
        <Text style={[styles.change, { color: changeColor }]} numberOfLines={1}>
          {formatPct(asset.change_pct_24h)}
        </Text>
      </View>

      <View style={styles.cardBottom}>
        <Sparkline data={asset.spark} color={sig.fg} width={70} height={24} />
        <View style={styles.confidenceWrap}>
          <Text style={[styles.confidenceLabel, { color: colors.textMuted }]}>AI</Text>
          <Text style={[styles.confidenceVal, { color: sig.fg }]}>{asset.confidence}%</Text>
        </View>
      </View>
    </TouchableOpacity>
  );
}

function ColumnList({
  title,
  market,
  data,
  loading,
  onPressAsset,
}: {
  title: string;
  market: Market;
  data: AssetSignal[];
  loading: boolean;
  onPressAsset: (a: AssetSignal) => void;
}) {
  const { colors } = useTheme();
  return (
    <View style={[styles.column, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: colors.textPrimary }]}>{title}</Text>
        <Text style={[styles.columnCount, { color: colors.textMuted }]}>{data.length}</Text>
      </View>
      {loading && data.length === 0 ? (
        <View style={styles.loadingBox}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(a) => a.symbol}
          renderItem={({ item }) => (
            <AssetCard asset={item} market={market} onPress={() => onPressAsset(item)} />
          )}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
      )}
    </View>
  );
}

export default function Dashboard() {
  const { colors, mode, toggle } = useTheme();
  const router = useRouter();
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [crypto, setCrypto] = useState<AssetSignal[]>([]);
  const [stocks, setStocks] = useState<AssetSignal[]>([]);
  const [loadingCrypto, setLoadingCrypto] = useState(true);
  const [loadingStock, setLoadingStock] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  const load = useCallback(
    async (tf: Timeframe) => {
      setLoadingCrypto(true);
      setLoadingStock(true);
      try {
        const [c, s] = await Promise.allSettled([
          api.dashboard("crypto", tf),
          api.dashboard("stock", tf),
        ]);
        if (c.status === "fulfilled") setCrypto(c.value.assets);
        if (s.status === "fulfilled") setStocks(s.value.assets);
        setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
      } finally {
        setLoadingCrypto(false);
        setLoadingStock(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(timeframe);
    const id = setInterval(() => void load(timeframe), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [timeframe, load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load(timeframe);
    setRefreshing(false);
  }, [load, timeframe]);

  const handleAssetPress = (a: AssetSignal) => {
    router.push(`/asset/${a.market}/${a.symbol}?timeframe=${timeframe}` as never);
  };

  const consensus = useMemo(() => {
    const all = [...crypto, ...stocks];
    if (!all.length) return { buy: 0, sell: 0, hold: 0 };
    return {
      buy: all.filter((a) => a.action === "BUY").length,
      sell: all.filter((a) => a.action === "SELL").length,
      hold: all.filter((a) => a.action === "HOLD").length,
    };
  }, [crypto, stocks]);

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={[styles.appTitle, { color: colors.textPrimary }]}>AITrade Pro</Text>
          <Text style={[styles.appSub, { color: colors.textMuted }]}>
            Multi-AI sinyal • {lastUpdate ? `update ${lastUpdate}` : "memuat…"}
          </Text>
        </View>
        <View style={styles.headerActions}>
          <TouchableOpacity
            onPress={toggle}
            testID="theme-toggle-button"
            style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
          >
            <Ionicons name={mode === "dark" ? "sunny-outline" : "moon-outline"} size={18} color={colors.textPrimary} />
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => router.push("/manage" as never)}
            testID="manage-assets-button"
            style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
          >
            <Ionicons name="options-outline" size={18} color={colors.textPrimary} />
          </TouchableOpacity>
        </View>
      </View>

      {/* Consensus strip */}
      <View style={[styles.consensusStrip, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.consensusItem}>
          <Text style={[styles.consensusNum, { color: colors.accentUp }]}>{consensus.buy}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>BUY/LONG</Text>
        </View>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <View style={styles.consensusItem}>
          <Text style={[styles.consensusNum, { color: colors.accentHold }]}>{consensus.hold}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>HOLD</Text>
        </View>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <View style={styles.consensusItem}>
          <Text style={[styles.consensusNum, { color: colors.accentDown }]}>{consensus.sell}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>SELL/SHORT</Text>
        </View>
      </View>

      {/* Timeframe selector */}
      <View style={styles.tfRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 12, gap: 8, alignItems: "center" }}
        >
          {TIMEFRAMES.map((tf) => {
            const active = tf === timeframe;
            return (
              <TouchableOpacity
                key={tf}
                testID={`timeframe-${tf}`}
                onPress={() => setTimeframe(tf)}
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
      </View>

      {/* Two-column dashboard */}
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.dualScroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accentBlue} />}
      >
        <View style={styles.dualRow}>
          <ColumnList
            title="CRYPTO"
            market="crypto"
            data={crypto}
            loading={loadingCrypto}
            onPressAsset={handleAssetPress}
          />
          <ColumnList
            title="SAHAM"
            market="stock"
            data={stocks}
            loading={loadingStock}
            onPressAsset={handleAssetPress}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 12,
  },
  appTitle: { fontSize: 22, fontWeight: "700", letterSpacing: 0.3 },
  appSub: { fontSize: 11, marginTop: 2 },
  headerActions: { flexDirection: "row", gap: 8 },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  consensusStrip: {
    marginHorizontal: 16,
    borderRadius: 12,
    borderWidth: 1,
    flexDirection: "row",
    paddingVertical: 10,
  },
  consensusItem: { flex: 1, alignItems: "center" },
  consensusNum: { fontSize: 18, fontWeight: "700" },
  consensusLabel: { fontSize: 10, marginTop: 2, letterSpacing: 0.5 },
  consensusDivider: { width: 1, marginVertical: 6 },
  tfRow: {
    height: 56,
    justifyContent: "center",
    marginTop: 4,
  },
  tfPill: {
    height: 36,
    minWidth: 50,
    paddingHorizontal: 14,
    borderRadius: 18,
    borderWidth: 1,
    flexShrink: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  tfPillText: { fontSize: 12, fontWeight: "600" },
  dualScroll: { paddingHorizontal: 8, paddingBottom: 24 },
  dualRow: { flexDirection: "row", gap: 8 },
  column: {
    flex: 1,
    borderRadius: 12,
    paddingHorizontal: 6,
    paddingTop: 8,
  },
  columnHeader: {
    paddingHorizontal: 6,
    paddingBottom: 8,
    borderBottomWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  columnTitle: { fontSize: 13, fontWeight: "700", letterSpacing: 1 },
  columnCount: { fontSize: 11, fontWeight: "500" },
  loadingBox: { paddingVertical: 40, alignItems: "center" },
  card: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
    marginTop: 8,
  },
  cardTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 6,
  },
  ticker: { fontSize: 14, fontWeight: "700", letterSpacing: 0.4, flexShrink: 1 },
  signalPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  signalText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  cardMid: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  price: { fontSize: 13, fontWeight: "600", fontVariant: ["tabular-nums"], flexShrink: 1 },
  change: { fontSize: 11, fontWeight: "600", marginLeft: 4 },
  cardBottom: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 6,
  },
  confidenceWrap: { alignItems: "flex-end" },
  confidenceLabel: { fontSize: 9, letterSpacing: 0.5 },
  confidenceVal: { fontSize: 13, fontWeight: "700" },
});
