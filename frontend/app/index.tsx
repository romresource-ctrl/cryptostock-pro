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
import {
  TIMEFRAMES,
  type AssetSignal,
  type DashboardSort,
  type Market,
  type Profile,
  type Timeframe,
  api,
  formatPct,
  formatPrice,
} from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

const REFRESH_INTERVAL_MS = 60_000;

function signalColors(colors: ReturnType<typeof useTheme>["colors"], action: string) {
  if (action === "BUY") return { fg: colors.accentUp, bg: colors.accentUp + "26" };
  if (action === "SELL") return { fg: colors.accentDown, bg: colors.accentDown + "26" };
  return { fg: colors.accentHold, bg: colors.accentHold + "26" };
}

function wrColor(colors: ReturnType<typeof useTheme>["colors"], wr: number | null): string {
  if (wr === null) return colors.textMuted;
  if (wr >= 65) return colors.accentUp;
  if (wr >= 50) return colors.accentHold;
  return colors.accentDown;
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
  const wr = asset.track_record?.wr_30d ?? null;
  const wrCol = wrColor(colors, wr);
  const premium = asset.is_premium;
  const premiumGold = "#F0B90B";

  return (
    <TouchableOpacity
      onPress={onPress}
      activeOpacity={0.75}
      testID={`asset-card-${market}-${asset.symbol}`}
      style={[
        styles.card,
        {
          backgroundColor: colors.surface,
          borderColor: premium ? premiumGold : colors.border,
          borderWidth: premium ? 1.5 : 1,
          shadowColor: premium ? premiumGold : "transparent",
          shadowOpacity: premium ? 0.35 : 0,
          shadowRadius: premium ? 6 : 0,
          shadowOffset: { width: 0, height: 0 },
          elevation: premium ? 4 : 0,
        },
      ]}
    >
      {premium && (
        <View style={[styles.premiumRibbon, { backgroundColor: premiumGold }]} testID={`premium-badge-${market}-${asset.symbol}`}>
          <Ionicons name="star" size={9} color="#0B0E11" />
          <Text style={styles.premiumRibbonText}>PREMIUM</Text>
        </View>
      )}
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
        <Sparkline data={asset.spark} color={sig.fg} width={64} height={22} />
        <View style={styles.confidenceWrap}>
          <Text style={[styles.confidenceLabel, { color: colors.textMuted }]}>AI</Text>
          <Text style={[styles.confidenceVal, { color: sig.fg }]}>{asset.confidence}%</Text>
        </View>
      </View>

      {wr !== null && (
        <View style={[styles.wrRow, { borderTopColor: colors.border }]} testID={`wr-badge-${market}-${asset.symbol}`}>
          <Text style={[styles.wrLabel, { color: colors.textMuted }]}>WR 30d</Text>
          <Text style={[styles.wrVal, { color: wrCol }]}>
            {wr.toFixed(0)}%
            <Text style={[styles.wrSub, { color: colors.textMuted }]}> · {asset.track_record.n_30d}</Text>
          </Text>
        </View>
      )}
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
      ) : data.length === 0 ? (
        <Text style={[styles.emptyBox, { color: colors.textMuted }]}>
          Profil ini belum punya aset {title.toLowerCase()}. Tap ⚙ untuk tambah.
        </Text>
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
  const [sort, setSort] = useState<DashboardSort>("premium");
  const [premiumOnly, setPremiumOnly] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [crypto, setCrypto] = useState<AssetSignal[]>([]);
  const [stocks, setStocks] = useState<AssetSignal[]>([]);
  const [premiumCount, setPremiumCount] = useState(0);
  const [loadingCrypto, setLoadingCrypto] = useState(true);
  const [loadingStock, setLoadingStock] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  const loadProfiles = useCallback(async () => {
    const r = await api.profiles();
    setProfiles(r.profiles);
    setActiveId(r.active_id);
  }, []);

  const load = useCallback(async (tf: Timeframe, s: DashboardSort, po: boolean) => {
    setLoadingCrypto(true);
    setLoadingStock(true);
    try {
      const [c, st] = await Promise.allSettled([
        api.dashboard("crypto", tf, { sort: s, premiumOnly: po }),
        api.dashboard("stock", tf, { sort: s, premiumOnly: po }),
      ]);
      let pCount = 0;
      if (c.status === "fulfilled") {
        setCrypto(c.value.assets);
        setActiveId(c.value.profile_id);
        pCount += c.value.premium_count;
      }
      if (st.status === "fulfilled") {
        setStocks(st.value.assets);
        pCount += st.value.premium_count;
      }
      setPremiumCount(pCount);
      setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } finally {
      setLoadingCrypto(false);
      setLoadingStock(false);
    }
  }, []);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  useEffect(() => {
    void load(timeframe, sort, premiumOnly);
    const id = setInterval(() => void load(timeframe, sort, premiumOnly), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [timeframe, sort, premiumOnly, load, activeId]);

  const switchProfile = async (id: string) => {
    if (id === activeId) return;
    setActiveId(id);
    try {
      await api.activateProfile(id);
      await load(timeframe, sort, premiumOnly);
    } catch {
      // ignore
    }
  };

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([loadProfiles(), load(timeframe, sort, premiumOnly)]);
    setRefreshing(false);
  }, [load, loadProfiles, timeframe, sort, premiumOnly]);

  const handleAssetPress = (a: AssetSignal) => {
    router.push(`/asset/${a.market}/${a.symbol}?timeframe=${timeframe}` as never);
  };

  const consensus = useMemo(() => {
    const all = [...crypto, ...stocks];
    return {
      buy: all.filter((a) => a.action === "BUY").length,
      sell: all.filter((a) => a.action === "SELL").length,
      hold: all.filter((a) => a.action === "HOLD").length,
    };
  }, [crypto, stocks]);

  const activeName = profiles.find((p) => p.id === activeId)?.name ?? "Profil";

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      {/* Header */}
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.appTitle, { color: colors.textPrimary }]}>AITrade Pro</Text>
          <Text style={[styles.appSub, { color: colors.textMuted }]} numberOfLines={1}>
            {activeName} • {lastUpdate ? `update ${lastUpdate}` : "memuat…"}
          </Text>
        </View>
        <View style={styles.headerActions}>
          <TouchableOpacity
            onPress={() => router.push("/news" as never)}
            testID="news-button"
            style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
          >
            <Ionicons name="newspaper-outline" size={18} color={colors.textPrimary} />
          </TouchableOpacity>
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

      {/* Profile selector */}
      <View style={styles.profileRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          {profiles.map((p) => {
            const active = p.id === activeId;
            return (
              <TouchableOpacity
                key={p.id}
                onPress={() => switchProfile(p.id)}
                testID={`profile-${p.id}`}
                style={[
                  styles.profilePill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Ionicons
                  name={active ? "bookmark" : "bookmark-outline"}
                  size={12}
                  color={active ? "#fff" : colors.textSecondary}
                />
                <Text style={[styles.profilePillText, { color: active ? "#fff" : colors.textSecondary }]} numberOfLines={1}>
                  {p.name}
                </Text>
              </TouchableOpacity>
            );
          })}
          <TouchableOpacity
            onPress={() => router.push("/manage" as never)}
            testID="profile-manage-btn"
            style={[styles.profilePill, { backgroundColor: colors.surface, borderColor: colors.border, borderStyle: "dashed" }]}
          >
            <Ionicons name="add" size={14} color={colors.textSecondary} />
            <Text style={[styles.profilePillText, { color: colors.textSecondary }]}>Kelola</Text>
          </TouchableOpacity>
        </ScrollView>
      </View>

      {/* Consensus strip */}
      <View style={[styles.consensusStrip, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.consensusItem}>
          <View style={styles.premiumNumWrap}>
            <Ionicons name="star" size={14} color="#F0B90B" />
            <Text style={[styles.consensusNum, { color: "#F0B90B" }]}>{premiumCount}</Text>
          </View>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>PREMIUM</Text>
        </View>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
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

      {/* Sort / Premium-only filter */}
      <View style={styles.sortRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          <TouchableOpacity
            onPress={() => setPremiumOnly((v) => !v)}
            testID="premium-only-toggle"
            style={[
              styles.sortPill,
              {
                backgroundColor: premiumOnly ? "#F0B90B" : colors.surface,
                borderColor: premiumOnly ? "#F0B90B" : colors.border,
              },
            ]}
          >
            <Ionicons name="star" size={11} color={premiumOnly ? "#0B0E11" : "#F0B90B"} />
            <Text style={[styles.sortPillText, { color: premiumOnly ? "#0B0E11" : colors.textSecondary }]}>
              PREMIUM ONLY
            </Text>
          </TouchableOpacity>
          {(["premium", "confidence", "wr", "default"] as DashboardSort[]).map((s) => {
            const active = s === sort;
            const label = s === "premium" ? "⭐ Sort: Premium" : s === "confidence" ? "Sort: AI%" : s === "wr" ? "Sort: WR" : "Default";
            return (
              <TouchableOpacity
                key={s}
                onPress={() => setSort(s)}
                testID={`sort-${s}`}
                style={[
                  styles.sortPill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Text style={[styles.sortPillText, { color: active ? "#fff" : colors.textSecondary }]}>{label}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
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
    paddingHorizontal: 16,
    paddingTop: 8,
    paddingBottom: 10,
  },
  appTitle: { fontSize: 22, fontWeight: "700", letterSpacing: 0.3 },
  appSub: { fontSize: 11, marginTop: 2 },
  headerActions: { flexDirection: "row", gap: 8 },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  profileRow: { height: 48, justifyContent: "center" },
  profilePill: {
    height: 32,
    paddingHorizontal: 12,
    borderRadius: 16,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flexShrink: 0,
  },
  profilePillText: { fontSize: 12, fontWeight: "600", maxWidth: 140 },
  consensusStrip: {
    marginHorizontal: 16,
    marginTop: 4,
    borderRadius: 12,
    borderWidth: 1,
    flexDirection: "row",
    paddingVertical: 10,
  },
  consensusItem: { flex: 1, alignItems: "center" },
  consensusNum: { fontSize: 18, fontWeight: "700" },
  consensusLabel: { fontSize: 10, marginTop: 2, letterSpacing: 0.5 },
  consensusDivider: { width: 1, marginVertical: 6 },
  tfRow: { height: 56, justifyContent: "center", marginTop: 4 },
  tfPill: {
    height: 36, minWidth: 50, paddingHorizontal: 14,
    borderRadius: 18, borderWidth: 1, flexShrink: 0,
    alignItems: "center", justifyContent: "center",
  },
  tfPillText: { fontSize: 12, fontWeight: "600" },
  dualScroll: { paddingHorizontal: 8, paddingBottom: 24 },
  dualRow: { flexDirection: "row", gap: 8 },
  column: { flex: 1, borderRadius: 12, paddingHorizontal: 6, paddingTop: 8 },
  columnHeader: {
    paddingHorizontal: 6, paddingBottom: 8, borderBottomWidth: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  columnTitle: { fontSize: 13, fontWeight: "700", letterSpacing: 1 },
  columnCount: { fontSize: 11, fontWeight: "500" },
  loadingBox: { paddingVertical: 40, alignItems: "center" },
  emptyBox: { textAlign: "center", padding: 16, fontSize: 11, lineHeight: 16 },
  card: { borderWidth: 1, borderRadius: 10, padding: 10, marginTop: 8 },
  cardTop: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6,
  },
  ticker: { fontSize: 14, fontWeight: "700", letterSpacing: 0.4, flexShrink: 1 },
  signalPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  signalText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  cardMid: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  price: { fontSize: 13, fontWeight: "600", fontVariant: ["tabular-nums"], flexShrink: 1 },
  change: { fontSize: 11, fontWeight: "600", marginLeft: 4 },
  cardBottom: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6,
  },
  confidenceWrap: { alignItems: "flex-end" },
  confidenceLabel: { fontSize: 9, letterSpacing: 0.5 },
  confidenceVal: { fontSize: 13, fontWeight: "700" },
  wrRow: {
    marginTop: 8, paddingTop: 6, borderTopWidth: StyleSheet.hairlineWidth,
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
  },
  wrLabel: { fontSize: 9, letterSpacing: 0.5 },
  wrVal: { fontSize: 12, fontWeight: "700" },
  wrSub: { fontSize: 9, fontWeight: "500" },
  premiumRibbon: {
    position: "absolute",
    top: -1,
    right: -1,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderTopRightRadius: 9,
    borderBottomLeftRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
  },
  premiumRibbonText: { fontSize: 8, fontWeight: "800", letterSpacing: 0.6, color: "#0B0E11" },
  premiumNumWrap: { flexDirection: "row", alignItems: "center", gap: 4 },
  sortRow: { height: 50, justifyContent: "center", marginTop: 2 },
  sortPill: {
    height: 32, paddingHorizontal: 12, borderRadius: 16, borderWidth: 1, flexShrink: 0,
    flexDirection: "row", alignItems: "center", gap: 5,
  },
  sortPillText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.4 },
});
