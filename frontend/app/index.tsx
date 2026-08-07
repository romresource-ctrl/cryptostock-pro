import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  FlatList,
  PanResponder,
  Pressable,
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
import {
  type CategoryKey,
  useCategoryPrefs,
} from "@/src/components/CategoryReorderSheet";
import LoginModal from "@/src/components/LoginModal";
import ChatSheet from "@/src/components/ChatSheet";
import Sparkline from "@/src/components/Sparkline";
import UsdtLocalRateStrip, {
  STABLECOIN_SYMBOLS,
  formatStablecoinLocal,
  useUsdtLocalRate,
} from "@/src/components/UsdtLocalRateStrip";
import VipModal from "@/src/components/VipModal";
import { useAlertEngine } from "@/src/hooks/useAlertEngine";
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
import { useWatchlist } from "@/src/lib/watchlist";
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

// v8.1.3 — Regional filter for the World Stocks column. `all` = default
// (show every stock regardless of region). Any other value filters
// `stock_us` cards to only those matching the region key returned by
// the backend (derived from Yahoo ticker suffix).
type RegionKey =
  | "all" | "us" | "europe" | "canada" | "russia" | "china" | "hongkong"
  | "japan" | "korea" | "taiwan" | "singapore" | "malaysia" | "indonesia"
  | "india" | "australia" | "gulf" | "latam" | "africa";
const REGIONS: { key: RegionKey; flag: string; label: string }[] = [
  { key: "all",       flag: "🌐", label: "All" },
  { key: "us",        flag: "🇺🇸", label: "US" },
  { key: "europe",    flag: "🇪🇺", label: "Europe" },
  { key: "canada",    flag: "🇨🇦", label: "Canada" },
  { key: "china",     flag: "🇨🇳", label: "China" },
  { key: "hongkong",  flag: "🇭🇰", label: "HK" },
  { key: "japan",     flag: "🇯🇵", label: "Japan" },
  { key: "korea",     flag: "🇰🇷", label: "Korea" },
  { key: "taiwan",    flag: "🇹🇼", label: "Taiwan" },
  { key: "singapore", flag: "🇸🇬", label: "SG" },
  { key: "malaysia",  flag: "🇲🇾", label: "Malaysia" },
  { key: "india",     flag: "🇮🇳", label: "India" },
  { key: "australia", flag: "🇦🇺", label: "AU" },
  { key: "gulf",      flag: "🛢️", label: "Gulf" },
  { key: "latam",     flag: "🌎", label: "LATAM" },
  { key: "africa",    flag: "🇿🇦", label: "Africa" },
  { key: "russia",    flag: "🇷🇺", label: "Russia" },
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
  regionFilter: RegionKey = "all",
  market?: Market,
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
  // v8.1.3 — Region filter only applies to World Stocks (stock_us).
  // Other markets (crypto, gold, forex, etc.) pass through unchanged
  // so tapping a region never hides them.
  if (regionFilter !== "all" && market === "stock_us") {
    out = out.filter((a) => (a.region || "us") === regionFilter);
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
  // v8.5.3 — Watchlist star button.  Tap ⭐ to add/remove this asset from
  // the user's favorites (persisted in AsyncStorage).  A small yellow
  // filled star means "in watchlist", grey outline means "not saved".
  const watch = useWatchlist();
  const starred = watch.has(market, asset.symbol);

  // v8.4.0 — For USD-pegged stablecoins, render the price in the user's
  // LOCAL currency (Rp / ¥ / € / …) instead of "$1.00". Users trading in
  // non-USD countries want to know how much a stablecoin is worth in
  // their own money. `useUsdtLocalRate()` returns null (skip) for USD
  // locales or when the FX API is unreachable, so USD users still see
  // the original price.
  const localFx = useUsdtLocalRate();
  const isStable = market === "crypto" && STABLECOIN_SYMBOLS.has(asset.symbol.toUpperCase());
  const priceDisplay =
    (isStable && asset.price != null && formatStablecoinLocal(asset.price, localFx)) ||
    formatPrice(asset.price, market);

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
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <TouchableOpacity
            onPress={() => watch.toggle(market, asset.symbol)}
            hitSlop={8}
            testID={`watchlist-star-${market}-${asset.symbol}`}
            style={styles.starBtn}
          >
            <Ionicons
              name={starred ? "star" : "star-outline"}
              size={14}
              color={starred ? "#F0B90B" : colors.textMuted}
            />
          </TouchableOpacity>
          <View style={[styles.signalPill, { backgroundColor: sig.bg }]}>
            <Text style={[styles.signalText, { color: sig.fg }]}>{asset.label}</Text>
          </View>
        </View>
      </View>
      <View style={styles.cardMid}>
        <Text style={[styles.price, { color: colors.textPrimary }]} numberOfLines={1}>
          {priceDisplay}
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
  // v8.1.3 — Regional filter for World Stocks. Default "all" shows every
  // stock; other keys filter stock_us column only.
  const [regionFilter, setRegionFilter] = useState<RegionKey>("all");
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

  // Ordered categories — user's saved order from CategoryReorderSheet takes
  // top priority.  Hidden categories are filtered out entirely from the
  // horizontal scroll. If the user has NOT customized the order yet, we
  // still lift the chip-selected view[] pair to the front (legacy quick-
  // filter). Once they touch the reorder sheet their explicit order wins.
  // v8.5.3 — Watchlist state for the sticky "⭐ Watchlist" column that
  // appears at the very start of the horizontal scroll.  We combine the
  // user's starred entries with the currently-loaded data so live prices
  // + signals stay accurate without an extra fetch per starred asset.
  const watchlist = useWatchlist();
  const watchlistAssets = useMemo<(AssetSignal & { _market: Category })[]>(() => {
    if (!watchlist.ready || watchlist.size === 0) return [];
    const out: (AssetSignal & { _market: Category })[] = [];
    for (const entry of watchlist.entries) {
      const m = entry.market as Category;
      const pool = (data as Record<string, AssetSignal[]>)[m];
      if (!pool) continue;
      const hit = pool.find((a) => a.symbol.toUpperCase() === entry.symbol.toUpperCase());
      if (hit) out.push({ ...hit, _market: m });
    }
    return out;
  }, [watchlist.entries, watchlist.ready, watchlist.size, data]);

  // v8.5.3 — Alert engine: evaluates saved price alerts against every
  // dashboard data refresh and fires a local notification when triggered.
  useAlertEngine(data as Record<string, AssetSignal[]>);

  const [categoryPrefs, saveCategoryPrefs] = useCategoryPrefs();
  const [reorderOpen, setReorderOpen] = useState(false); // eslint-disable-line @typescript-eslint/no-unused-vars

  // v8.5.2 — INLINE horizontal drag & drop directly from the ☰ handle
  // in every column header. No modal.  We track finger X and swap
  // adjacent columns as the finger passes their centers.
  const [dragCat, setDragCat] = useState<Category | null>(null);
  const dragDx = useRef(new Animated.Value(0)).current;
  const colCentersRef = useRef<Map<Category, { x: number; w: number }>>(new Map());
  const draggingOrderRef = useRef<Category[]>([]);
  const dragStartXRef = useRef<number>(0);

  const persistOrder = useCallback(
    (order: Category[]) => {
      void saveCategoryPrefs(order as CategoryKey[], categoryPrefs.hidden);
    },
    [saveCategoryPrefs, categoryPrefs.hidden],
  );

  const makeColumnPan = useCallback(
    (cat: Category) =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onStartShouldSetPanResponderCapture: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: (evt) => {
          setDragCat(cat);
          dragDx.setValue(0);
          dragStartXRef.current = evt.nativeEvent.pageX;
          draggingOrderRef.current = orderedCategoriesRef.current.slice();
        },
        onPanResponderMove: (evt, gs) => {
          dragDx.setValue(gs.dx);
          // Recompute finger X relative to page and compare to each
          // column's center to determine swap target.
          const fingerX = dragStartXRef.current + gs.dx;
          const order = draggingOrderRef.current;
          const myIdx = order.indexOf(cat);
          if (myIdx < 0) return;
          let targetIdx = myIdx;
          for (let i = 0; i < order.length; i++) {
            if (i === myIdx) continue;
            const other = order[i];
            const layout = colCentersRef.current.get(other);
            if (!layout) continue;
            const otherCenter = layout.x + layout.w / 2;
            if (i < myIdx && fingerX < otherCenter) {
              targetIdx = i;
              break;
            }
            if (i > myIdx && fingerX > otherCenter) {
              targetIdx = i;
            }
          }
          if (targetIdx !== myIdx) {
            const next = order.slice();
            next.splice(myIdx, 1);
            next.splice(targetIdx, 0, cat);
            draggingOrderRef.current = next;
            persistOrder(next);
            // Re-anchor drag start so column stays under finger after swap.
            dragStartXRef.current = fingerX;
            dragDx.setValue(0);
          }
        },
        onPanResponderRelease: () => {
          Animated.spring(dragDx, {
            toValue: 0,
            useNativeDriver: true,
            speed: 30,
            bounciness: 4,
          }).start(() => setDragCat(null));
        },
        onPanResponderTerminate: () => {
          dragDx.setValue(0);
          setDragCat(null);
        },
      }),
    [dragDx, persistOrder],
  );
  const DEFAULT_ORDER_ARR: Category[] = useMemo(
    () => ["crypto", "etf", "stock_id", "stock_us", "gold_silver", "commodity", "forex"],
    [],
  );
  const orderedCategories: Category[] = useMemo(() => {
    const savedOrder = categoryPrefs.order as Category[];
    const visible = savedOrder.filter((k) => !categoryPrefs.hidden.has(k as CategoryKey));
    if (visible.length === 0) return ALL_CATEGORIES; // safety net
    // Detect "untouched" prefs → saved order matches default & nothing hidden.
    const isDefault =
      categoryPrefs.hidden.size === 0 &&
      savedOrder.length === DEFAULT_ORDER_ARR.length &&
      savedOrder.every((k, i) => k === DEFAULT_ORDER_ARR[i]);
    if (!isDefault) return visible; // respect user's saved order strictly.
    // Legacy behaviour: lift `view[]` chips to the front on default order.
    const selected = view.filter((v) => visible.includes(v));
    const rest = visible.filter((k) => !selected.includes(k));
    return [...selected, ...rest];
  }, [view, categoryPrefs, ALL_CATEGORIES, DEFAULT_ORDER_ARR]);

  // Keep a live ref to `orderedCategories` so PanResponder callbacks
  // (created once) always see the newest order.
  const orderedCategoriesRef = useRef<Category[]>(orderedCategories);
  useEffect(() => {
    orderedCategoriesRef.current = orderedCategories;
  }, [orderedCategories]);

  // v8.0.4 — Lazy-load. On the first paint we only fetch the TWO markets
  // the user currently has on-screen (`view`). The other 6 markets stay
  // empty until the user actually swipes to them (their `useEffect` will
  // pick up the change to `view` and fetch on demand). This cuts cold-
  // start network traffic from 8 HTTP requests → 1 batched request that
  // returns exactly what the user can see.
  const load = useCallback(async (tf: Timeframe, selected: Category[], regionArg: RegionKey = "all") => {
    setLoadingMap((prev) => {
      const next = { ...prev };
      selected.forEach((k) => { next[k] = true; });
      return next;
    });
    try {
      const res = await api.dashboardBatch(selected as Market[], tf, {
        sort: "premium",
        full: false,
        region: regionArg,
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
    void load(timeframe, ALL_CATEGORIES, regionFilter);
    const id = setInterval(() => void load(timeframe, ALL_CATEGORIES, regionFilter), REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [timeframe, ALL_CATEGORIES, load, regionFilter]);

  // v8.1.3 — toggleCategory kept for reference but no longer used by
  // the UI (the old asset-category chips were replaced by region chips).
  // We keep the `view` state so the ordering/highlight logic in
  // orderedCategories still works.
  const _toggleCategory = (k: Category) => {
    setView((prev) => {
      if (prev.includes(k)) {
        if (prev.length === 1) return prev;
        return prev.filter((x) => x !== k);
      }
      if (prev.length >= 2) return [prev[1], k];
      return [...prev, k];
    });
  };
  void _toggleCategory; // silence unused-var lint

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load(timeframe, view, regionFilter);
    setRefreshing(false);
  }, [load, timeframe, view, regionFilter]);

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
          {/* v8.4.9 — Alerts button moved to header (user removed the
              dashboard-body pill).  Users still create alerts from the
              🔔 icon on each asset's detail page. */}
          <TouchableOpacity
            onPress={() => router.push("/alerts" as never)}
            testID="header-alerts-button"
            style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
          >
            <Ionicons name="notifications-outline" size={18} color="#F0B90B" />
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
              <View style={{ flexDirection: "row", gap: 6, alignItems: "center" }}>
                {/* v8.1.4 — Dedicated admin unlock button (🔑). Placed
                    next to LOGIN so both flows are single-tap
                    discoverable — no more brittle long-press that
                    silently fails on React Native Web / some Android
                    OEMs. Tap = admin unlock modal directly. */}
                <Pressable
                  onPress={() => setLoginOpen(true)}
                  testID="admin-unlock-button"
                  accessibilityLabel="Admin unlock"
                  accessibilityHint="Enter admin unlock code"
                  hitSlop={8}
                  style={({ pressed }) => [
                    styles.iconBtn,
                    {
                      backgroundColor: pressed ? colors.accentBlue : colors.surface,
                      borderColor: colors.border,
                    },
                  ]}
                >
                  <Ionicons name="key" size={16} color={colors.textPrimary} />
                </Pressable>
                <Pressable
                  onPress={() => setVipOpen(true)}
                  // Long-press still supported as legacy shortcut.
                  // Pressable's onLongPress is more reliable than
                  // TouchableOpacity on RN Web + Android.
                  onLongPress={() => setLoginOpen(true)}
                  delayLongPress={400}
                  testID="login-button"
                  accessibilityHint="Long press to enter admin unlock code"
                  style={({ pressed }) => [
                    styles.loginBtn,
                    {
                      backgroundColor: colors.accentBlue,
                      borderColor: colors.accentBlue,
                      opacity: pressed ? 0.7 : 1,
                    },
                  ]}
                >
                  <Ionicons name="log-in-outline" size={14} color="#fff" />
                  <Text style={styles.loginBtnText}>{t("login")}</Text>
                </Pressable>
              </View>
            )
          )}
        </View>
      </View>

      {/* v8.4.0 — Live FX widget: shows "1 USDT ≈ <local currency>" based
          on device locale. Hides silently for USD locales / unsupported
          currencies / offline. See UsdtLocalRateStrip.tsx. */}
      <UsdtLocalRateStrip />

      {/* v8.1.3 — Region filter chips (replaces old asset-category chips).
          Filter World Stocks column by country/region. "All" shows all
          columns as normal. Tap a region → World Stocks column shows
          only stocks from that region; other columns (crypto/gold/etc.)
          remain visible. */}
      <View style={styles.viewRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          {REGIONS.map((r) => {
            const active = regionFilter === r.key;
            return (
              <TouchableOpacity
                key={r.key}
                onPress={() => setRegionFilter(active ? "all" : r.key)}
                testID={`region-${r.key}`}
                activeOpacity={0.75}
                style={[
                  styles.viewPill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Text style={{ fontSize: 14 }}>{r.flag}</Text>
                <Text style={[styles.viewPillText, { color: active ? "#fff" : colors.textSecondary }]}>{r.label}</Text>
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

      {/* v8.5.0 — Reorder button. Compact pill just under the search bar so
          it's discoverable without crowding the header row. Tapping opens
          CategoryReorderSheet where users drag columns and toggle
          visibility. Hidden when the user is actively searching to avoid
          overlap with the search-results header. */}
      {/* v8.4.9 — Dashboard-body pill row removed per user request.
          Reorder → long-press ☰ handle in column header.
          Alerts → 🔔 icon di top-header. */}
      {!searchQuery.trim() && categoryPrefs.hidden.size > 0 ? (
        <View style={styles.reorderRow}>
          <Text style={[styles.reorderHiddenBadge, { color: colors.textMuted }]}>
            {categoryPrefs.hidden.size} {t("reorder_hidden_suffix") || "disembunyikan"}
          </Text>
        </View>
      ) : null}

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
        {/* v8.4.9 — Horizontal ScrollView restored (react-native-draggable-
            flatlist@4.x is not compatible with Reanimated 4 in Expo SDK 53+).
            Users still reorder columns via long-press on the ☰ handle which
            opens the CategoryReorderSheet where they use ↑/↓ buttons to
            move a category up or down. */}
        <ScrollView
          horizontal
          scrollEnabled={dragCat === null}
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 0 }}
          decelerationRate="fast"
          disableIntervalMomentum
          snapToOffsets={
            SCREEN_W < 640 && dragCat === null
              ? (() => {
                  const colW = Math.floor((SCREEN_W - 8) / 2);
                  const pairW = (colW + 8) * 2;
                  const pageCount = Math.ceil(orderedCategories.length / 2);
                  return Array.from({ length: pageCount }, (_, i) => i * pairW);
                })()
              : undefined
          }
          snapToAlignment="start"
        >
          {watchlist.size > 0 ? (() => {
            const colW = SCREEN_W < 640 ? Math.floor((SCREEN_W - 8) / 2) : 190;
            return (
              <View key="__watchlist__" style={{ width: colW, marginRight: 8 }}>
                <WatchlistColumn
                  title={`⭐ ${t("watchlist_title") || "Watchlist"}`}
                  data={watchlistAssets}
                  onPress={(a, m) => handleAssetPress(a, m)}
                  locked={!hasAccess}
                  emptyHint={
                    t("watchlist_loading") ||
                    "Menunggu data harga…"
                  }
                />
              </View>
            );
          })() : null}
          {orderedCategories.map((k, idx) => {
            const catLabel = t(`category_${k}`).toUpperCase();
            const colW = SCREEN_W < 640 ? Math.floor((SCREEN_W - 8) / 2) : 190;
            const isLast = idx === orderedCategories.length - 1;
            const pan = makeColumnPan(k);
            const isDragging = dragCat === k;
            return (
              <Animated.View
                key={k}
                onLayout={(e) => {
                  colCentersRef.current.set(k, {
                    x: e.nativeEvent.layout.x,
                    w: e.nativeEvent.layout.width,
                  });
                }}
                style={{
                  width: colW,
                  marginRight: isLast ? 0 : 8,
                  transform: isDragging ? [{ translateX: dragDx }] : [],
                  zIndex: isDragging ? 10 : 1,
                  elevation: isDragging ? 6 : 0,
                }}
              >
                <ListColumn
                  title={catLabel}
                  market={k}
                  data={filterAssets(data[k], searchQuery, signalFilter, regionFilter, k)}
                  loading={loadingMap[k]}
                  onPress={handleAssetPress}
                  locked={!hasAccess}
                  panHandlers={pan.panHandlers}
                  isDragging={isDragging}
                />
              </Animated.View>
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
  title, market, data, loading, onPress, locked, panHandlers, isDragging,
}: { title: string; market: Market; data: AssetSignal[]; loading: boolean; onPress: (a: AssetSignal, market?: Market) => void; locked: boolean; panHandlers?: object; isDragging?: boolean }) {
  const { colors } = useTheme();
  return (
    <View style={[
      styles.column,
      {
        backgroundColor: colors.surfaceAlt,
        borderWidth: isDragging ? 2 : 0,
        borderColor: colors.accentBlue,
      },
    ]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: colors.textPrimary }]} numberOfLines={1}>
          {title}
        </Text>
        {panHandlers ? (
          <View
            {...(panHandlers as object)}
            testID={`column-reorder-${market}`}
            style={styles.columnReorderBtn}
          >
            <Ionicons name="reorder-three" size={16} color={colors.textMuted} />
          </View>
        ) : null}
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
          scrollEnabled={!isDragging}
        />
      )}
    </View>
  );
}

// v8.5.3 — Watchlist column: mixed-market list of the user's starred assets.
// Each row carries its own `_market` so the star toggle + onPress can route
// back to the correct asset detail screen.
type WatchlistAsset = AssetSignal & { _market: Market };
function WatchlistColumn({
  title, data, onPress, locked, emptyHint,
}: {
  title: string;
  data: WatchlistAsset[];
  onPress: (a: AssetSignal, market: Market) => void;
  locked: boolean;
  emptyHint: string;
}) {
  const { colors } = useTheme();
  return (
    <View style={[styles.column, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.columnHeader, { borderColor: colors.border }]}>
        <Text style={[styles.columnTitle, { color: "#F0B90B" }]} numberOfLines={1}>
          {title}
        </Text>
      </View>
      {data.length === 0 ? (
        <View style={{ paddingVertical: 30, paddingHorizontal: 12 }}>
          <Text style={{ color: colors.textMuted, fontSize: 11.5, textAlign: "center", lineHeight: 16 }}>
            {emptyHint}
          </Text>
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(a) => `${a._market}:${a.symbol}`}
          renderItem={({ item }) => (
            <AssetCard
              asset={item}
              market={item._market}
              locked={locked}
              onPress={() => onPress(item, item._market)}
            />
          )}
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
  reorderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "flex-start",
    paddingHorizontal: 12,
    paddingTop: 4,
    paddingBottom: 4,
    gap: 8,
  },
  reorderBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 14,
    borderWidth: 1,
  },
  reorderBtnText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  reorderHiddenBadge: { fontSize: 10.5, fontWeight: "600" },
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
  columnTitle: { fontSize: 13, fontWeight: "700", letterSpacing: 1, flex: 1 },
  columnCount: { fontSize: 11, fontWeight: "500" },
  // v8.5.4 — Tiny ☰ handle inside every column header.  Tap opens the
  // reorder sheet; long-press opens it too (matches the "hamburger =
  // rearrange" mental model users know from Binance/TradingView).
  columnReorderBtn: {
    width: 24,
    height: 24,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 6,
    marginLeft: 4,
  },
  fullPanel: { flex: 1, borderRadius: 12, paddingHorizontal: 8, paddingTop: 8, marginHorizontal: 8 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8, paddingTop: 8, paddingBottom: 24 },
  card: { borderWidth: 1, borderRadius: 10, padding: 10, marginTop: 8, position: "relative", minHeight: 132, justifyContent: "space-between" },
  cardTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  ticker: { fontSize: 14, fontWeight: "700", letterSpacing: 0.4, flexShrink: 1 },
  signalPill: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  starBtn: {
    width: 22,
    height: 22,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 6,
  },
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
