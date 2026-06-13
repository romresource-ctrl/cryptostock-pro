import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  FlatList,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth/AuthContext";
import LoginModal from "@/src/components/LoginModal";
import Sparkline from "@/src/components/Sparkline";
import VipModal from "@/src/components/VipModal";
import {
  TIMEFRAMES,
  type AssetSignal,
  type Market,
  type Timeframe,
  api,
  formatPct,
  formatPrice,
} from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

const REFRESH_INTERVAL_MS = 60_000;
type ViewMode = "crypto" | "stock" | "both";

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
  asset, onPress, market, locked,
}: { asset: AssetSignal; onPress: () => void; market: Market; locked: boolean }) {
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
      {locked && (
        <View style={[styles.lockBadge, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}>
          <Ionicons name="lock-closed" size={9} color={colors.textMuted} />
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
        <View style={{ alignItems: "flex-end" }}>
          <Text style={[styles.confidenceLabel, { color: colors.textMuted }]}>AI</Text>
          <Text style={[styles.confidenceVal, { color: sig.fg }]}>{asset.confidence}%</Text>
        </View>
      </View>
      {wr !== null ? (
        <View style={[styles.wrRow, { borderTopColor: colors.border }]} testID={`wr-badge-${market}-${asset.symbol}`}>
          <Text style={[styles.wrLabel, { color: colors.textMuted }]}>WR 30d</Text>
          <Text style={[styles.wrVal, { color: wrCol }]}>
            {wr.toFixed(0)}%
            <Text style={[styles.wrSub, { color: colors.textMuted }]}> · {asset.track_record.n_30d}</Text>
          </Text>
        </View>
      ) : (
        <View style={[styles.wrRow, { borderTopColor: colors.border }]} testID={`wr-empty-${market}-${asset.symbol}`}>
          <Text style={[styles.wrLabel, { color: colors.textMuted }]}>WR 30d</Text>
          <Text style={[styles.wrVal, { color: colors.textMuted }]}>—</Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

export default function Dashboard() {
  const { colors, mode, toggle } = useTheme();
  const router = useRouter();
  const { isUnlocked, email, logout, loaded: authLoaded } = useAuth();

  const [view, setView] = useState<ViewMode>("both");
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [crypto, setCrypto] = useState<AssetSignal[]>([]);
  const [stocks, setStocks] = useState<AssetSignal[]>([]);
  const [premiumCount, setPremiumCount] = useState(0);
  const [loadingCrypto, setLoadingCrypto] = useState(true);
  const [loadingStock, setLoadingStock] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [loginOpen, setLoginOpen] = useState(false);
  const [vipOpen, setVipOpen] = useState(false);
  const [lockedToast, setLockedToast] = useState(false);

  const needCrypto = view === "crypto" || view === "both";
  const needStock = view === "stock" || view === "both";

  const load = useCallback(async (tf: Timeframe, v: ViewMode) => {
    const wantCrypto = v === "crypto" || v === "both";
    const wantStock = v === "stock" || v === "both";
    if (wantCrypto) setLoadingCrypto(true);
    if (wantStock) setLoadingStock(true);
    try {
      const calls: Promise<unknown>[] = [];
      if (wantCrypto) calls.push(api.dashboard("crypto", tf, { full: true, sort: "premium" }));
      else calls.push(Promise.resolve(null));
      if (wantStock) calls.push(api.dashboard("stock", tf, { full: true, sort: "premium" }));
      else calls.push(Promise.resolve(null));
      const [c, s] = (await Promise.allSettled(calls)) as PromiseSettledResult<{ assets: AssetSignal[]; premium_count: number } | null>[];
      let pCount = 0;
      if (wantCrypto) {
        if (c.status === "fulfilled" && c.value) { setCrypto(c.value.assets); pCount += c.value.premium_count; }
      } else setCrypto([]);
      if (wantStock) {
        if (s.status === "fulfilled" && s.value) { setStocks(s.value.assets); pCount += s.value.premium_count; }
      } else setStocks([]);
      setPremiumCount(pCount);
      setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } finally {
      setLoadingCrypto(false);
      setLoadingStock(false);
    }
  }, []);

  useEffect(() => {
    void load(timeframe, view);
    const id = setInterval(() => void load(timeframe, view), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [timeframe, view, load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load(timeframe, view);
    setRefreshing(false);
  }, [load, timeframe, view]);

  const handleAssetPress = (a: AssetSignal) => {
    if (!isUnlocked) {
      setVipOpen(true);
      return;
    }
    router.push(`/asset/${a.market}/${a.symbol}?timeframe=${timeframe}` as never);
  };

  const consensus = useMemo(() => {
    const all = [...(needCrypto ? crypto : []), ...(needStock ? stocks : [])];
    return {
      buy: all.filter((a) => a.action === "BUY").length,
      sell: all.filter((a) => a.action === "SELL").length,
      hold: all.filter((a) => a.action === "HOLD").length,
    };
  }, [crypto, stocks, needCrypto, needStock]);

  const viewPills: { key: ViewMode; label: string; icon: string }[] = [
    { key: "crypto", label: "Crypto", icon: "logo-bitcoin" },
    { key: "stock", label: "Saham", icon: "trending-up" },
    { key: "both", label: "Crypto + Saham", icon: "grid" },
  ];

  const SCREEN_W = Dimensions.get("window").width;

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.appTitle, { color: colors.textPrimary }]}>KevinAI Pro</Text>
          <Text style={[styles.appSub, { color: colors.textMuted }]} numberOfLines={1}>
            {premiumCount > 0 ? `⭐ ${premiumCount} Premium · ` : ""}
            {lastUpdate ? `update ${lastUpdate}` : "memuat…"}
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
          {authLoaded && (
            isUnlocked ? (
              <TouchableOpacity
                onPress={() => logout()}
                testID="logout-button"
                style={[styles.unlockedBtn, { backgroundColor: "#0ECB81" + "22", borderColor: "#0ECB81" }]}
              >
                <Ionicons name="checkmark-circle" size={14} color="#0ECB81" />
                <Text style={[styles.unlockedText, { color: "#0ECB81" }]} numberOfLines={1}>
                  {email && email.length > 12 ? email.split("@")[0] : email}
                </Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                onPress={() => setLoginOpen(true)}
                testID="login-button"
                style={[styles.loginBtn, { backgroundColor: colors.accentBlue, borderColor: colors.accentBlue }]}
              >
                <Ionicons name="log-in-outline" size={14} color="#fff" />
                <Text style={styles.loginBtnText}>LOGIN</Text>
              </TouchableOpacity>
            )
          )}
        </View>
      </View>

      {/* View mode pills */}
      <View style={styles.viewRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          {viewPills.map((vp) => {
            const active = vp.key === view;
            return (
              <TouchableOpacity
                key={vp.key}
                onPress={() => setView(vp.key)}
                testID={`view-${vp.key}`}
                style={[
                  styles.viewPill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Ionicons name={vp.icon as never} size={14} color={active ? "#fff" : colors.textSecondary} />
                <Text style={[styles.viewPillText, { color: active ? "#fff" : colors.textSecondary }]}>{vp.label}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      </View>

      {/* Consensus strip */}
      <View style={[styles.consensusStrip, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={styles.consensusItem}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
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

      {/* Asset lists */}
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.dualScroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accentBlue} />}
      >
        {view === "both" ? (
          <View style={styles.dualRow}>
            <ListColumn title="CRYPTO" market="crypto" data={crypto} loading={loadingCrypto} onPress={handleAssetPress} locked={!isUnlocked} />
            <ListColumn title="SAHAM" market="stock" data={stocks} loading={loadingStock} onPress={handleAssetPress} locked={!isUnlocked} />
          </View>
        ) : view === "crypto" ? (
          <FullList title="CRYPTO" market="crypto" data={crypto} loading={loadingCrypto} onPress={handleAssetPress} locked={!isUnlocked} screenW={SCREEN_W} />
        ) : (
          <FullList title="SAHAM" market="stock" data={stocks} loading={loadingStock} onPress={handleAssetPress} locked={!isUnlocked} screenW={SCREEN_W} />
        )}
      </ScrollView>

      {/* Locked toast */}
      {lockedToast && (
        <View style={[styles.toast, { backgroundColor: colors.surface, borderColor: colors.accentBlue }]} testID="locked-toast">
          <Ionicons name="lock-closed" size={14} color={colors.accentBlue} />
          <Text style={[styles.toastText, { color: colors.textPrimary }]}>
            Login dulu untuk akses detail aset
          </Text>
        </View>
      )}

      <LoginModal visible={loginOpen} onClose={() => setLoginOpen(false)} />
      <VipModal
        visible={vipOpen}
        onClose={() => setVipOpen(false)}
        onLogin={() => setLoginOpen(true)}
      />
    </SafeAreaView>
  );
}

function ListColumn({
  title, market, data, loading, onPress, locked,
}: { title: string; market: Market; data: AssetSignal[]; loading: boolean; onPress: (a: AssetSignal) => void; locked: boolean }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.column, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: colors.textPrimary }]}>{title}</Text>
        <Text style={[styles.columnCount, { color: colors.textMuted }]}>{data.length}</Text>
      </View>
      {loading && data.length === 0 ? (
        <View style={{ paddingVertical: 40, alignItems: "center" }}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(a) => a.symbol}
          renderItem={({ item }) => <AssetCard asset={item} market={market} locked={locked} onPress={() => onPress(item)} />}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
      )}
    </View>
  );
}

function FullList({
  title, market, data, loading, onPress, locked, screenW,
}: { title: string; market: Market; data: AssetSignal[]; loading: boolean; onPress: (a: AssetSignal) => void; locked: boolean; screenW: number }) {
  const { colors } = useTheme();
  // Two-column grid for single-market view
  return (
    <View style={[styles.fullPanel, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: colors.textPrimary }]}>{title}</Text>
        <Text style={[styles.columnCount, { color: colors.textMuted }]}>{data.length} aset</Text>
      </View>
      {loading && data.length === 0 ? (
        <View style={{ paddingVertical: 40, alignItems: "center" }}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <View style={styles.grid}>
          {data.map((a) => (
            <View key={a.symbol} style={{ width: (screenW - 32 - 8) / 2 }}>
              <AssetCard asset={a} market={market} locked={locked} onPress={() => onPress(a)} />
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 16,
    paddingTop: 8, paddingBottom: 10,
  },
  appTitle: { fontSize: 22, fontWeight: "700", letterSpacing: 0.3 },
  appSub: { fontSize: 11, marginTop: 2 },
  headerActions: { flexDirection: "row", gap: 8, alignItems: "center" },
  iconBtn: { width: 36, height: 36, borderRadius: 10, alignItems: "center", justifyContent: "center", borderWidth: 1 },
  loginBtn: {
    height: 36, paddingHorizontal: 12, borderRadius: 10, borderWidth: 1,
    flexDirection: "row", alignItems: "center", gap: 5,
  },
  loginBtnText: { color: "#fff", fontSize: 12, fontWeight: "700", letterSpacing: 0.6 },
  unlockedBtn: {
    height: 36, paddingHorizontal: 10, borderRadius: 10, borderWidth: 1,
    flexDirection: "row", alignItems: "center", gap: 5, maxWidth: 140,
  },
  unlockedText: { fontSize: 11, fontWeight: "700", maxWidth: 90 },
  viewRow: { height: 50, justifyContent: "center" },
  viewPill: {
    height: 36, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, flexShrink: 0,
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  viewPillText: { fontSize: 12, fontWeight: "700", letterSpacing: 0.4 },
  consensusStrip: {
    marginHorizontal: 16, marginTop: 4, borderRadius: 12, borderWidth: 1,
    flexDirection: "row", paddingVertical: 10,
  },
  consensusItem: { flex: 1, alignItems: "center" },
  consensusNum: { fontSize: 18, fontWeight: "700" },
  consensusLabel: { fontSize: 10, marginTop: 2, letterSpacing: 0.5 },
  consensusDivider: { width: 1, marginVertical: 6 },
  tfRow: { height: 56, justifyContent: "center", marginTop: 2 },
  tfPill: {
    height: 36, minWidth: 50, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, flexShrink: 0,
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
  fullPanel: { flex: 1, borderRadius: 12, paddingHorizontal: 8, paddingTop: 8, marginHorizontal: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8, paddingTop: 8, paddingBottom: 24 },
  card: { borderWidth: 1, borderRadius: 10, padding: 10, marginTop: 8, position: "relative", minHeight: 132, justifyContent: "space-between" },
  cardTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  ticker: { fontSize: 14, fontWeight: "700", letterSpacing: 0.4, flexShrink: 1 },
  signalPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  signalText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  cardMid: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  price: { fontSize: 13, fontWeight: "600", fontVariant: ["tabular-nums"], flexShrink: 1 },
  change: { fontSize: 11, fontWeight: "600", marginLeft: 4 },
  cardBottom: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 6 },
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
    position: "absolute", top: -1, right: -1,
    paddingHorizontal: 6, paddingVertical: 2,
    borderTopRightRadius: 9, borderBottomLeftRadius: 8,
    flexDirection: "row", alignItems: "center", gap: 3,
  },
  premiumRibbonText: { fontSize: 8, fontWeight: "800", letterSpacing: 0.6, color: "#0B0E11" },
  lockBadge: {
    position: "absolute", bottom: 6, right: 6,
    width: 16, height: 16, borderRadius: 8, borderWidth: 1,
    alignItems: "center", justifyContent: "center", opacity: 0.6,
  },
  toast: {
    position: "absolute", bottom: 32, left: 16, right: 16,
    paddingVertical: 12, paddingHorizontal: 16, borderRadius: 10, borderWidth: 1,
    flexDirection: "row", alignItems: "center", gap: 8,
  },
  toastText: { fontSize: 13, fontWeight: "600", flex: 1 },
});
