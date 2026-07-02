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
import AdminDebugModal from "@/src/components/AdminDebugModal";
import LoginModal from "@/src/components/LoginModal";
import Sparkline from "@/src/components/Sparkline";
import VipModal from "@/src/components/VipModal";
import { useI18n } from "@/src/i18n/I18nContext";
import {
  TIMEFRAMES,
  type AssetSignal,
  type Market,
  type Timeframe,
  api,
  formatPct,
  formatPrice,
} from "@/src/lib/api";
import { APP_VERSION } from "@/src/lib/version";
import { useTheme } from "@/src/theme/ThemeContext";

const REFRESH_INTERVAL_MS = 60_000;
type Category = Market;

const CATEGORIES: { key: Category; label: string; icon: string }[] = [
  { key: "crypto", label: "Crypto", icon: "logo-bitcoin" },
  { key: "etf", label: "ETF", icon: "pie-chart" },
  { key: "stock_id", label: "Saham IDX", icon: "trending-up" },
  { key: "stock_us", label: "Saham US", icon: "globe" },
];

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
  const { lang, toggle: toggleLang, t } = useI18n();

  const [view, setView] = useState<Category[]>(["crypto", "stock_id"]);
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [data, setData] = useState<Record<Category, AssetSignal[]>>({ crypto: [], etf: [], stock_id: [], stock_us: [] });
  const [premiumCount, setPremiumCount] = useState(0);
  const [loadingMap, setLoadingMap] = useState<Record<Category, boolean>>({ crypto: true, etf: false, stock_id: true, stock_us: false });
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [loginOpen, setLoginOpen] = useState(false);
  const [vipOpen, setVipOpen] = useState(false);
  const [lockedToast, setLockedToast] = useState(false);

  const load = useCallback(async (tf: Timeframe, selected: Category[]) => {
    const updates: Record<Category, boolean> = { crypto: false, etf: false, stock_id: false, stock_us: false };
    selected.forEach((k) => { updates[k] = true; });
    setLoadingMap(updates);
    try {
      const results = await Promise.allSettled(
        selected.map((k) => api.dashboard(k, tf, { full: true, sort: "premium" })),
      );
      let pCount = 0;
      const next = { crypto: [], etf: [], stock_id: [], stock_us: [] } as Record<Category, AssetSignal[]>;
      selected.forEach((k, i) => {
        const r = results[i];
        if (r.status === "fulfilled") {
          next[k] = r.value.assets;
          pCount += r.value.premium_count;
        }
      });
      setData(next);
      setPremiumCount(pCount);
      setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } finally {
      setLoadingMap({ crypto: false, etf: false, stock_id: false, stock_us: false });
    }
  }, []);

  useEffect(() => {
    void load(timeframe, view);
    const id = setInterval(() => void load(timeframe, view), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [timeframe, view, load]);

  const toggleCategory = (k: Category) => {
    setView((prev) => {
      if (prev.includes(k)) {
        // Don't allow zero selection — keep at least 1
        if (prev.length === 1) return prev;
        return prev.filter((x) => x !== k);
      }
      // Max 2 selected
      if (prev.length >= 2) return [prev[1], k];
      return [...prev, k];
    });
  };

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
    const all = view.flatMap((k) => data[k]);
    return {
      buy: all.filter((a) => a.action === "BUY").length,
      sell: all.filter((a) => a.action === "SELL").length,
      hold: all.filter((a) => a.action === "HOLD").length,
    };
  }, [data, view]);

  const SCREEN_W = Dimensions.get("window").width;
  const selectedCount = view.length;

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      <View style={styles.header}>
        <View style={styles.headerTitleWrap}>
          <Text
            style={[styles.appTitle, { color: colors.textPrimary }]}
            numberOfLines={1}
            adjustsFontSizeToFit
            minimumFontScale={0.6}
          >{t("app_title")}</Text>
          <Text style={[styles.appSub, { color: colors.textMuted }]} numberOfLines={1}>
            {`${t("ver_label")} ${APP_VERSION}`}
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
            onPress={toggleLang}
            testID="lang-toggle-button"
            style={[
              styles.iconBtn,
              {
                backgroundColor: lang === "en" ? "#1E66F5" : "#E53935",
                borderColor: lang === "en" ? "#1E66F5" : "#E53935",
              },
            ]}
          >
            <Text style={styles.langBtnText}>{lang === "en" ? "EN" : "ID"}</Text>
          </TouchableOpacity>
          {authLoaded && (
            isUnlocked ? (
              <TouchableOpacity
                onPress={() => logout()}
                testID="logout-button"
                style={[styles.unlockedBtn, { backgroundColor: colors.accentBlue, borderColor: colors.accentBlue }]}
              >
                <Ionicons name="checkmark-circle" size={14} color="#fff" />
                <Text style={[styles.unlockedText, { color: "#fff" }]} numberOfLines={1}>
                  {t("logged")}
                </Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                onPress={() => setLoginOpen(true)}
                testID="login-button"
                style={[styles.loginBtn, { backgroundColor: colors.accentBlue, borderColor: colors.accentBlue }]}
              >
                <Ionicons name="log-in-outline" size={14} color="#fff" />
                <Text style={styles.loginBtnText}>{t("login")}</Text>
              </TouchableOpacity>
            )
          )}
        </View>
      </View>

      {/* Category chips (multi-select, max 2) */}
      <View style={styles.viewRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          {CATEGORIES.map((vp) => {
            const active = view.includes(vp.key);
            return (
              <TouchableOpacity
                key={vp.key}
                onPress={() => toggleCategory(vp.key)}
                testID={`category-${vp.key}`}
                style={[
                  styles.viewPill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Ionicons name={vp.icon as never} size={14} color={active ? "#fff" : colors.textSecondary} />
                <Text style={[styles.viewPillText, { color: active ? "#fff" : colors.textSecondary }]}>{t(`category_${vp.key}`)}</Text>
                {active && (
                  <View style={styles.activeOrder}>
                    <Text style={styles.activeOrderText}>{view.indexOf(vp.key) + 1}</Text>
                  </View>
                )}
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
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("premium_label")}</Text>
        </View>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <View style={styles.consensusItem}>
          <Text style={[styles.consensusNum, { color: colors.accentUp }]}>{consensus.buy}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("buy_long")}</Text>
        </View>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <View style={styles.consensusItem}>
          <Text style={[styles.consensusNum, { color: colors.accentHold }]}>{consensus.hold}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("hold")}</Text>
        </View>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <View style={styles.consensusItem}>
          <Text style={[styles.consensusNum, { color: colors.accentDown }]}>{consensus.sell}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("sell_short")}</Text>
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
        {selectedCount === 2 ? (
          <View style={styles.dualRow}>
            {view.map((k) => {
              const catLabel = t(`category_${k}`).toUpperCase();
              return (
                <ListColumn
                  key={k}
                  title={catLabel}
                  market={k}
                  data={data[k]}
                  loading={loadingMap[k]}
                  onPress={handleAssetPress}
                  locked={!isUnlocked}
                />
              );
            })}
          </View>
        ) : (
          (() => {
            const k = view[0];
            const catLabel = t(`category_${k}`).toUpperCase();
            return (
              <FullList
                title={catLabel}
                market={k}
                data={data[k]}
                loading={loadingMap[k]}
                onPress={handleAssetPress}
                locked={!isUnlocked}
                screenW={SCREEN_W}
                assetLabel={t("asset")}
              />
            );
          })()
        )}
      </ScrollView>

      {/* Locked toast */}
      {lockedToast && (
        <View style={[styles.toast, { backgroundColor: colors.surface, borderColor: colors.accentBlue }]} testID="locked-toast">
          <Ionicons name="lock-closed" size={14} color={colors.accentBlue} />
          <Text style={[styles.toastText, { color: colors.textPrimary }]}>
            {lang === "en" ? "Login first to access asset details" : "Login dulu untuk akses detail aset"}
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
  title, market, data, loading, onPress, locked, screenW, assetLabel,
}: { title: string; market: Market; data: AssetSignal[]; loading: boolean; onPress: (a: AssetSignal) => void; locked: boolean; screenW: number; assetLabel: string }) {
  const { colors } = useTheme();
  // Two-column grid for single-market view
  return (
    <View style={[styles.fullPanel, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: colors.textPrimary }]}>{title}</Text>
        <Text style={[styles.columnCount, { color: colors.textMuted }]}>{data.length} {assetLabel}</Text>
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
  appTitle: { fontSize: 18, fontWeight: "800", letterSpacing: 0.2 },
  headerTitleWrap: { flex: 1, paddingRight: 8, maxWidth: 180 },
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
  langBtnText: { fontSize: 12, fontWeight: "800", color: "#fff", letterSpacing: 0.6 },
  activeOrder: {
    minWidth: 16, height: 16, paddingHorizontal: 4, borderRadius: 8,
    backgroundColor: "rgba(255,255,255,0.25)",
    alignItems: "center", justifyContent: "center", marginLeft: 2,
  },
  activeOrderText: { fontSize: 9, fontWeight: "800", color: "#fff" },
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
