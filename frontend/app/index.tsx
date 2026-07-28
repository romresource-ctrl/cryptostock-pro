import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  useWindowDimensions,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth/AuthContext";
import LoginModal from "@/src/components/LoginModal";
import ChatSheet from "@/src/components/ChatSheet";
import Sparkline from "@/src/components/Sparkline";
import VipModal from "@/src/components/VipModal";
import { useI18n } from "@/src/i18n/I18nContext";
import {
  type AssetSignal,
  type Market,
  type Timeframe,
  api,
  formatPct,
  formatPrice,
} from "@/src/lib/api";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { usePremiumAccess } from "@/src/lib/usePremiumAccess";
import { APP_VERSION } from "@/src/lib/version";
import { useTheme } from "@/src/theme/ThemeContext";

const REFRESH_INTERVAL_MS = 60_000;
type Category = Market;

const CATEGORIES: { key: Category; label: string; icon: string }[] = [
  { key: "crypto", label: "Crypto", icon: "logo-bitcoin" },
  { key: "etf", label: "ETF", icon: "pie-chart" },
  { key: "stock_id", label: "Saham IDX", icon: "trending-up" },
  { key: "stock_us", label: "World Stocks", icon: "globe" },
  { key: "gold_silver", label: "Gold/Silver", icon: "medal" },
  { key: "commodity", label: "Commodities", icon: "cube" },
  { key: "forex", label: "Forex", icon: "swap-horizontal" },
];

function signalColors(colors: ReturnType<typeof useTheme>["colors"], action: string) {
  if (action === "BUY") return { fg: colors.accentUp, bg: colors.accentUp + "26" };
  if (action === "SELL") return { fg: colors.accentDown, bg: colors.accentDown + "26" };
  return { fg: colors.accentHold, bg: colors.accentHold + "26" };
}

// Filter assets by search query (case-insensitive, matches symbol prefix/contains)
type SignalFilter = null | "premium" | "BUY" | "HOLD" | "SELL";

function filterAssets(
  list: AssetSignal[] | undefined,
  query: string,
  signalFilter: SignalFilter = null,
): AssetSignal[] {
  if (!list) return [];
  let out = list;
  const q = query.trim().toUpperCase();
  if (q) {
    out = out.filter((a) => (a.symbol || "").toUpperCase().includes(q));
  }
  if (signalFilter) {
    if (signalFilter === "premium") {
      out = out.filter((a) => a.is_premium);
    } else {
      out = out.filter((a) => (a.action || "").toUpperCase() === signalFilter);
    }
  }
  return out;
}
function wrColor(colors: ReturnType<typeof useTheme>["colors"], wr: number | null): string {
  if (wr === null) return colors.textMuted;
  if (wr >= 65) return colors.accentUp;
  if (wr >= 50) return colors.accentHold;
  return colors.accentDown;
}

// v8.0.4 — Memoised so column re-renders (poll ticker, other markets
// finishing their fetch, safe-area updates, etc.) do NOT force every
// visible card to re-run all its layout + Sparkline SVG work. The
// custom prop comparator ignores identity changes on the `onPress`
// closure that the parent inevitably recreates each render.
const AssetCard = React.memo(function AssetCard({
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
}, (prev, next) => (
  // Fast equality — the only things that change per poll are the
  // metric numbers; deep-compare those and ignore closure identity.
  prev.market === next.market &&
  prev.locked === next.locked &&
  prev.asset.symbol === next.asset.symbol &&
  prev.asset.price === next.asset.price &&
  prev.asset.action === next.asset.action &&
  prev.asset.label === next.asset.label &&
  prev.asset.confidence === next.asset.confidence &&
  prev.asset.change_pct_24h === next.asset.change_pct_24h &&
  prev.asset.is_premium === next.asset.is_premium &&
  (prev.asset.track_record?.wr_30d ?? null) === (next.asset.track_record?.wr_30d ?? null) &&
  (prev.asset.track_record?.n_30d ?? 0) === (next.asset.track_record?.n_30d ?? 0)
));

export default function Dashboard() {
  const { colors, mode, toggle } = useTheme();
  const router = useRouter();
  const { isUnlocked, logout, loaded: authLoaded } = useAuth();
  const { isPremium } = useSubscription();
  const { hasAccess } = usePremiumAccess();
  const { lang, toggle: toggleLang, t } = useI18n();

  const [view, setView] = useState<Category[]>(["crypto", "stock_us"]);
  const [timeframe] = useState<Timeframe>("1h");
  const [searchQuery, setSearchQuery] = useState("");
  const [data, setData] = useState<Record<Category, AssetSignal[]>>({
    crypto: [], etf: [], stock_id: [], stock_us: [],
    world_stocks: [], gold_silver: [], commodity: [], forex: [],
  });
  const [premiumCount, setPremiumCount] = useState(0);
  // v8.1.3 — Tap-to-filter on the consensus strip. Tap PREMIUM/BUY/HOLD/SELL
  // to instantly filter every column to only show matching cards. Tap
  // the same filter again to clear.
  const [signalFilter, setSignalFilter] = useState<SignalFilter>(null);
  const toggleSignalFilter = useCallback((f: Exclude<SignalFilter, null>) => {
    setSignalFilter((prev) => (prev === f ? null : f));
  }, []);
  const [loadingMap, setLoadingMap] = useState<Record<Category, boolean>>({
    // v8.0.7 — load ALL categories on cold start to eliminate the empty
    // columns on first swipe. Because the backend now serves via one
    // batched `/api/dashboard/batch` call (75s cache), the extra cost
    // over lazy-loading just 2 categories is negligible.
    crypto: true, etf: true, stock_id: true, stock_us: true,
    world_stocks: true, gold_silver: true, commodity: true, forex: true,
  });
  const [refreshing, setRefreshing] = useState(false);
  const [, setLastUpdate] = useState<string>("");
  const [loginOpen, setLoginOpen] = useState(false);
  const [vipOpen, setVipOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  // All 7 categories are always loaded in parallel so user can swipe horizontally
  // between them on phone, or see multiple columns at once on tablet.
  const ALL_CATEGORIES: Category[] = useMemo(
    () => CATEGORIES.map((c) => c.key),
    [],
  );

  // Ordered categories — put user-selected (view[]) FIRST so they appear at the
  // start of the horizontal scroll on phones (2 visible per screen). This lets
  // the user pick which two columns they see first on the dashboard.
  const orderedCategories: Category[] = useMemo(() => {
    const selected = view.filter((v) => ALL_CATEGORIES.includes(v));
    const rest = ALL_CATEGORIES.filter((k) => !selected.includes(k));
    return [...selected, ...rest];
  }, [view, ALL_CATEGORIES]);

  // v8.0.4 — Lazy-load. On the first paint we only fetch the TWO markets
  // the user currently has on-screen (`view`). The other 6 markets stay
  // empty until the user actually swipes to them (their `useEffect` will
  // pick up the change to `view` and fetch on demand). This cuts cold-
  // start network traffic from 8 HTTP requests → 1 batched request that
  // returns exactly what the user can see.
  const load = useCallback(async (tf: Timeframe, selected: Category[]) => {
    // Mark only the markets we are about to fetch as "loading" so their
    // columns show a spinner; the invisible columns stay untouched.
    setLoadingMap((prev) => {
      const next = { ...prev };
      selected.forEach((k) => { next[k] = true; });
      return next;
    });
    try {
      // One batched HTTP call covering all visible markets.
      const res = await api.dashboardBatch(selected as Market[], tf, {
        sort: "premium",
        full: false,
      });
      setData((prev) => {
        const next = { ...prev };
        selected.forEach((k) => {
          const m = res.markets?.[k];
          if (m && Array.isArray(m.assets)) {
            next[k] = m.assets;
          }
        });
        return next;
      });
      // Premium counter reflects ONLY currently-loaded markets — matches
      // what the user actually sees at the top of the dashboard.
      let pCount = 0;
      Object.values(res.markets || {}).forEach((m) => {
        pCount += m?.premium_count ?? 0;
      });
      setPremiumCount(pCount);
      setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    } finally {
      setLoadingMap((prev) => {
        const next = { ...prev };
        selected.forEach((k) => { next[k] = false; });
        return next;
      });
    }
  }, []);

  useEffect(() => {
    // v8.0.7 — Removed lazy-loading: fetch every category (still ONE
    // batched HTTP call thanks to /api/dashboard/batch), so users never
    // hit an empty column when swiping between markets. Cache TTL of
    // 300s on the backend keeps this cheap on subsequent polls.
    void load(timeframe, ALL_CATEGORIES);
    const id = setInterval(() => void load(timeframe, ALL_CATEGORIES), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [timeframe, ALL_CATEGORIES, load]);

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

  // Accepts an optional explicit market — used when the caller knows
  // exactly which column the user tapped (search results, list column).
  // Falls back to `a.market` which the backend sets on every AssetSignal.
  const handleAssetPress = (a: AssetSignal, marketOverride?: Market) => {
    if (!hasAccess) {
      setVipOpen(true);
      return;
    }
    const m = marketOverride ?? a.market ?? "crypto";
    // Forex / gold-silver symbols contain "/" (EUR/USD, XAU/USD) which
    // breaks Expo Router path segments AND FastAPI route matching (both
    // decode %2F back to /). Use "-" as URL-safe separator; backend
    // translates it back before the pool lookup.
    const urlSafeSymbol = a.symbol.replace(/\//g, "-");
    router.push(
      `/asset/${m}/${urlSafeSymbol}?timeframe=${timeframe}` as never,
    );
  };

  const consensus = useMemo(() => {
    const all = view.flatMap((k) => data[k] || []).filter((a) => a && a.action);
    return {
      buy: all.filter((a) => a.action === "BUY").length,
      sell: all.filter((a) => a.action === "SELL").length,
      hold: all.filter((a) => a.action === "HOLD").length,
    };
  }, [data, view]);

  const { width: SCREEN_W } = useWindowDimensions();

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      <View style={styles.header}>
        <View style={styles.headerTitleWrap}>
          <Text
            style={[styles.appTitle, { color: colors.textPrimary }]}
            numberOfLines={2}
            adjustsFontSizeToFit
            minimumFontScale={0.7}
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
                backgroundColor:
                  lang === "en" ? "#1E66F5" :
                  lang === "ru" ? "#8B5CF6" :
                  lang === "cn" ? "#F59E0B" :
                  "#E53935",
                borderColor:
                  lang === "en" ? "#1E66F5" :
                  lang === "ru" ? "#8B5CF6" :
                  lang === "cn" ? "#F59E0B" :
                  "#E53935",
              },
            ]}
          >
            <Text style={styles.langBtnText}>{lang.toUpperCase()}</Text>
          </TouchableOpacity>
          {authLoaded && (
            (isUnlocked || isPremium) ? (
              <TouchableOpacity
                onPress={() => {
                  // For admin-code unlock, allow logout on press. For
                  // subscription-based premium, keep as read-only status
                  // (user cancels in Play Store).
                  if (isUnlocked && !isPremium) {
                    logout();
                  }
                }}
                testID="logged-button"
                style={[styles.unlockedBtn, { backgroundColor: colors.accentBlue, borderColor: colors.accentBlue }]}
              >
                <Ionicons name="checkmark-circle" size={14} color="#fff" />
                <Text style={[styles.unlockedText, { color: "#fff" }]} numberOfLines={1}>
                  {t("logged")}
                </Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity
                onPress={() => setVipOpen(true)}
                // v8.1.1 — long-press bypasses the paywall and goes
                // straight to the admin unlock modal. Discoverable via
                // tooltip on iOS/accessibilityHint on Android.
                onLongPress={() => setLoginOpen(true)}
                delayLongPress={400}
                testID="login-button"
                accessibilityHint="Long press to enter admin unlock code"
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

      {/* Consensus strip — v8.1.3: each item is now a tap-to-filter chip.
          Tap PREMIUM → show only premium picks across all columns.
          Tap BUY/LONG → only BUY signals. Tap HOLD → only HOLD. Tap
          SELL/SHORT → only SELL. Tap the active filter again to clear. */}
      <View style={[styles.consensusStrip, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={() => toggleSignalFilter("premium")}
          testID="filter-premium"
          style={[
            styles.consensusItem,
            signalFilter === "premium" && {
              backgroundColor: "#F0B90B22",
              borderRadius: 8,
              borderWidth: 1,
              borderColor: "#F0B90B",
            },
          ]}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Ionicons name="star" size={14} color="#F0B90B" />
            <Text style={[styles.consensusNum, { color: "#F0B90B" }]}>{premiumCount}</Text>
          </View>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("premium_label")}</Text>
        </TouchableOpacity>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={() => toggleSignalFilter("BUY")}
          testID="filter-buy"
          style={[
            styles.consensusItem,
            signalFilter === "BUY" && {
              backgroundColor: colors.accentUp + "22",
              borderRadius: 8,
              borderWidth: 1,
              borderColor: colors.accentUp,
            },
          ]}
        >
          <Text style={[styles.consensusNum, { color: colors.accentUp }]}>{consensus.buy}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("buy_long")}</Text>
        </TouchableOpacity>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={() => toggleSignalFilter("HOLD")}
          testID="filter-hold"
          style={[
            styles.consensusItem,
            signalFilter === "HOLD" && {
              backgroundColor: colors.accentHold + "22",
              borderRadius: 8,
              borderWidth: 1,
              borderColor: colors.accentHold,
            },
          ]}
        >
          <Text style={[styles.consensusNum, { color: colors.accentHold }]}>{consensus.hold}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("hold")}</Text>
        </TouchableOpacity>
        <View style={[styles.consensusDivider, { backgroundColor: colors.border }]} />
        <TouchableOpacity
          activeOpacity={0.7}
          onPress={() => toggleSignalFilter("SELL")}
          testID="filter-sell"
          style={[
            styles.consensusItem,
            signalFilter === "SELL" && {
              backgroundColor: colors.accentDown + "22",
              borderRadius: 8,
              borderWidth: 1,
              borderColor: colors.accentDown,
            },
          ]}
        >
          <Text style={[styles.consensusNum, { color: colors.accentDown }]}>{consensus.sell}</Text>
          <Text style={[styles.consensusLabel, { color: colors.textMuted }]}>{t("sell_short")}</Text>
        </TouchableOpacity>
      </View>

      {/* Search bar (v6.0.3: 70% width + CHATROOM button next to it) */}
      <View style={styles.tfRow}>
        <View
          style={[
            styles.searchBox,
            {
              flex: 0.7,
              backgroundColor: colors.surface,
              borderColor: colors.border,
            },
          ]}
        >
          <Ionicons name="search" size={16} color={colors.textMuted} style={{ marginLeft: 10 }} />
          <TextInput
            testID="asset-search-input"
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder={t("search_placeholder")}
            placeholderTextColor={colors.textMuted}
            style={[styles.searchInput, { color: colors.textPrimary }]}
            autoCapitalize="characters"
            autoCorrect={false}
          />
          {searchQuery ? (
            <TouchableOpacity onPress={() => setSearchQuery("")} hitSlop={8} style={{ paddingHorizontal: 10 }}>
              <Ionicons name="close-circle" size={16} color={colors.textMuted} />
            </TouchableOpacity>
          ) : null}
        </View>
        {/* CHATROOM button (moved from header row → next to search).
            Premium/unlocked: gold clickable → open Chatroom.
            Non-premium: grey → tap shows Members Only popup. */}
        <TouchableOpacity
          onPress={() => {
            if (hasAccess) {
              setChatOpen(true);
            } else {
              Alert.alert(
                "Members Only",
                "Chatroom is only available for premium subscribers. Subscribe to unlock.",
                [
                  { text: "Cancel", style: "cancel" },
                  { text: "Subscribe", onPress: () => setVipOpen(true) },
                ],
              );
            }
          }}
          testID="dashboard-chatroom-button"
          style={[
            styles.searchChatBtn,
            {
              backgroundColor: hasAccess ? "#F0B90B" : colors.surface,
              borderColor: hasAccess ? "#F0B90B" : colors.border,
            },
          ]}
        >
          <Ionicons
            name="chatbubbles"
            size={16}
            color={hasAccess ? "#000" : colors.textSecondary}
          />
          <Text
            style={[
              styles.searchChatBtnText,
              { color: hasAccess ? "#000" : colors.textSecondary },
            ]}
          >
            CHATROOM
          </Text>
        </TouchableOpacity>
      </View>

      {/* Asset lists — always show ALL 7 category columns.
       * On phone: 2 columns fit per screen, swipe horizontally for others.
       * On tablet/Chromebook: 4-7 columns fit at once (no swipe needed).
       * Chip selection (view[]) auto-scrolls to first selected category.
       * When user is searching (v6.0.7): show a UNIFIED cross-market
       * results list instead of forcing the user to swipe between columns.
       */}
      {searchQuery.trim() ? (
        <SearchResults
          query={searchQuery.trim()}
          data={data}
          categories={ALL_CATEGORIES}
          onPress={handleAssetPress}
          locked={!hasAccess}
        />
      ) : (
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ paddingBottom: 20 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accentBlue} />}
      >
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 8, gap: 8 }}
          decelerationRate="fast"
          pagingEnabled={SCREEN_W < 640}
          snapToInterval={SCREEN_W < 640 ? Math.floor((SCREEN_W - 16) / 2) + 8 : undefined}
        >
          {orderedCategories.map((k) => {
            const catLabel = t(`category_${k}`).toUpperCase();
            // Column width: phone → exactly 2 per screen; tablet → fixed ~180
            const colW = SCREEN_W < 640 ? Math.floor((SCREEN_W - 24) / 2) : 190;
            const highlighted = view.includes(k);
            return (
              <View key={k} style={{ width: colW, opacity: highlighted ? 1 : 0.72 }}>
                <ListColumn
                  title={catLabel}
                  market={k}
                  data={filterAssets(data[k], searchQuery, signalFilter)}
                  loading={loadingMap[k]}
                  onPress={handleAssetPress}
                  locked={!hasAccess}
                />
              </View>
            );
          })}
        </ScrollView>
      </ScrollView>
      )}

      <LoginModal visible={loginOpen} onClose={() => setLoginOpen(false)} />
      <VipModal
        visible={vipOpen}
        onClose={() => setVipOpen(false)}
        onLogin={() => {
          // Close paywall first, then open admin unlock modal on next tick
          // to avoid overlapping-modal race on Android.
          setVipOpen(false);
          setTimeout(() => setLoginOpen(true), 250);
        }}
      />
      {/* Bottom-sheet chatroom (55% screen height) — leaves top half of
          the dashboard interactable so premium users can chat while
          still scrolling through asset columns / candles above. */}
      <ChatSheet visible={chatOpen} onClose={() => setChatOpen(false)} />
    </SafeAreaView>
  );
}

function SearchResults({
  query,
  data,
  categories,
  onPress,
  locked,
}: {
  query: string;
  data: Record<Category, AssetSignal[]>;
  categories: Category[];
  onPress: (a: AssetSignal, market?: Market) => void;
  locked: boolean;
}) {
  const { colors } = useTheme();
  const { width: screenW } = useWindowDimensions();
  const q = query.toUpperCase();

  // Backend-powered cross-pool search (v7.0.3) — 300ms debounced. Scans
  // the FULL universe (not just the top-50 on dashboard) so users can
  // find any listed symbol they type. Falls back to local filter while
  // backend response is in flight.
  const [remoteHits, setRemoteHits] = useState<{ asset: AssetSignal; market: Market }[]>([]);
  const [searching, setSearching] = useState(false);
  useEffect(() => {
    if (!query.trim()) return;
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const res = await api.search(query.trim());
        if (!cancelled) {
          const arr = (res.hits || []).map((a) => ({
            asset: a,
            market: (a.market as Market) ?? "crypto",
          }));
          setRemoteHits(arr);
        }
      } catch {
        if (!cancelled) setRemoteHits([]);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  // Merge local (already-loaded dashboard data) + remote (full pool).
  // De-duplicate by market+symbol; local wins because it has fresher
  // premium/AI enrichment applied by the dashboard endpoint.
  type Hit = { asset: AssetSignal; market: Market; rank: number };
  const seen = new Set<string>();
  const merged: Hit[] = [];
  const rank = (sym: string) => (sym === q ? 0 : sym.startsWith(q) ? 1 : sym.includes(q) ? 2 : 3);
  categories.forEach((k) => {
    (data[k] || []).forEach((a) => {
      const sym = (a.symbol || "").toUpperCase();
      const r = rank(sym);
      if (r < 3) {
        const key = `${k}-${a.symbol}`;
        if (!seen.has(key)) {
          seen.add(key);
          merged.push({ asset: a, market: k, rank: r });
        }
      }
    });
  });
  remoteHits.forEach((h) => {
    const key = `${h.market}-${h.asset.symbol}`;
    if (!seen.has(key)) {
      seen.add(key);
      const sym = (h.asset.symbol || "").toUpperCase();
      merged.push({ asset: h.asset, market: h.market, rank: rank(sym) });
    }
  });
  merged.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    return (a.asset.symbol || "").localeCompare(b.asset.symbol || "");
  });

  const numCols = screenW < 640 ? 2 : Math.max(3, Math.floor(screenW / 200));
  const cardW = (screenW - 24 - 8 * (numCols - 1)) / numCols;

  if (merged.length === 0) {
    return (
      <View style={{ flex: 1, paddingTop: 60, alignItems: "center", gap: 8 }}>
        {searching ? (
          <ActivityIndicator color={colors.accentBlue} />
        ) : (
          <>
            <Ionicons name="search" size={28} color={colors.textMuted} />
            <Text style={{ color: colors.textMuted, fontSize: 13, fontWeight: "600" }}>
              {`No matches for "${query}"`}
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: 11 }}>
              Try a different symbol, e.g. BTC, AAPL, SIDO
            </Text>
          </>
        )}
      </View>
    );
  }

  return (
    <ScrollView
      style={{ flex: 1 }}
      contentContainerStyle={{ padding: 12, paddingBottom: 24 }}
      keyboardShouldPersistTaps="handled"
    >
      {searching && (
        <View style={{ paddingBottom: 8, alignItems: "center" }}>
          <ActivityIndicator size="small" color={colors.accentBlue} />
        </View>
      )}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {merged.map((h) => (
          <View key={`${h.market}-${h.asset.symbol}`} style={{ width: cardW }}>
            <SearchHitCard hit={h} onPress={onPress} locked={locked} />
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function SearchHitCard({
  hit,
  onPress,
  locked,
}: {
  hit: { asset: AssetSignal; market: Market };
  onPress: (a: AssetSignal, market?: Market) => void;
  locked: boolean;
}) {
  const { asset, market } = hit;

  const marketLabel: Record<Market, string> = {
    crypto: "CRYPTO",
    etf: "ETF",
    stock_id: "IDX",
    stock_us: "US",
    world_stocks: "US",
    gold_silver: "GOLD",
    commodity: "COMM",
    forex: "FX",
  };
  const marketBadgeColor: Record<Market, string> = {
    crypto: "#F0B90B",
    etf: "#8B5CF6",
    stock_id: "#E53935",
    stock_us: "#1E66F5",
    world_stocks: "#1E66F5",
    gold_silver: "#FFC107",
    commodity: "#FF7043",
    forex: "#00BFA5",
  };

  return (
    <View style={{ position: "relative" }}>
      <AssetCard
        asset={asset}
        market={market}
        locked={locked}
        onPress={() => onPress(asset, market)}
      />
      {/* Market badge overlay (top-right corner) so users know which
          category the matched asset came from. */}
      <View
        style={[
          styles.searchHitBadgeOverlay,
          {
            backgroundColor: marketBadgeColor[market] + "E6",
            borderColor: marketBadgeColor[market],
          },
        ]}
        pointerEvents="none"
      >
        <Text style={styles.searchHitBadgeOverlayText}>{marketLabel[market]}</Text>
      </View>
    </View>
  );
}

function ListColumn({
  title, market, data, loading, onPress, locked,
}: { title: string; market: Market; data: AssetSignal[]; loading: boolean; onPress: (a: AssetSignal, market?: Market) => void; locked: boolean }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.column, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: colors.textPrimary }]}>{title}</Text>
      </View>
      {loading && data.length === 0 ? (
        <View style={{ paddingVertical: 40, alignItems: "center" }}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(a) => a.symbol}
          renderItem={({ item }) => <AssetCard asset={item} market={market} locked={locked} onPress={() => onPress(item, market)} />}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
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
  appTitle: { fontSize: 15, fontWeight: "800", letterSpacing: 0.2, lineHeight: 18 },
  headerTitleWrap: { flex: 1, paddingRight: 8 },
  appSub: { fontSize: 11, marginTop: 2 },
  headerActions: { flexDirection: "row", gap: 8, alignItems: "center", flexShrink: 0 },
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
  chatBtn: {
    height: 36,
    paddingHorizontal: 10,
    borderRadius: 10,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
  },
  chatBtnText: { fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },
  searchChatBtn: {
    flex: 0.3,
    height: 40,
    borderRadius: 12,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  searchChatBtnText: { fontSize: 11, fontWeight: "800", letterSpacing: 0.4 },
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
  tfRow: {
    height: 56,
    marginTop: 2,
    paddingHorizontal: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  searchBox: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 12,
    height: 40,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    fontWeight: "600",
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  searchHitBadgeOverlay: {
    position: "absolute",
    top: 6,
    left: 6,
    minWidth: 40,
    height: 18,
    paddingHorizontal: 5,
    borderRadius: 5,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
    zIndex: 10,
  },
  searchHitBadgeOverlayText: {
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 0.4,
    color: "#fff",
  },
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
