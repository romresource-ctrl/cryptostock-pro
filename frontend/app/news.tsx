import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Image,
  Linking,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, type Market, type NewsItem } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type MarketFilter = "all" | Market;

const AUTO_REFRESH_MS = 60_000;

function formatRelative(iso: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const diff = Math.floor((Date.now() - t) / 1000);
  if (diff < 60) return `${diff}d lalu`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}j lalu`;
  return `${Math.floor(diff / 86400)}h lalu`;
}

function NewsRow({ item }: { item: NewsItem }) {
  const { colors } = useTheme();
  const open = () => {
    if (item.url) Linking.openURL(item.url).catch(() => {});
  };
  return (
    <TouchableOpacity
      onPress={open}
      activeOpacity={0.7}
      testID={`news-item-${item.title.slice(0, 20)}`}
      style={[styles.row, { backgroundColor: colors.surface, borderColor: colors.border }]}
    >
      {item.image ? (
        <Image source={{ uri: item.image }} style={styles.thumb} resizeMode="cover" />
      ) : (
        <View style={[styles.thumb, styles.thumbPlaceholder, { backgroundColor: colors.surfaceAlt }]}>
          <Ionicons name="newspaper-outline" size={18} color={colors.textMuted} />
        </View>
      )}
      <View style={styles.rowBody}>
        <View style={styles.rowHead}>
          <Text style={[styles.source, { color: colors.accentBlue }]} numberOfLines={1}>
            {item.source}
          </Text>
          <Text style={[styles.time, { color: colors.textMuted }]}>{formatRelative(item.published)}</Text>
        </View>
        <Text style={[styles.title, { color: colors.textPrimary }]} numberOfLines={3}>
          {item.title}
        </Text>
        {item.summary ? (
          <Text style={[styles.summary, { color: colors.textSecondary }]} numberOfLines={2}>
            {item.summary}
          </Text>
        ) : null}
      </View>
    </TouchableOpacity>
  );
}

export default function NewsScreen() {
  const { colors } = useTheme();
  const router = useRouter();
  const [marketFilter, setMarketFilter] = useState<MarketFilter>("all");
  const [symbolFilter, setSymbolFilter] = useState<{ symbol: string; market: Market } | null>(null);
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [fetchedAt, setFetchedAt] = useState<string>("");
  const [watchlistCrypto, setWatchlistCrypto] = useState<string[]>([]);
  const [watchlistStocks, setWatchlistStocks] = useState<string[]>([]);

  // Load active profile watchlist for symbol chips
  useEffect(() => {
    void (async () => {
      try {
        const w = await api.watchlist();
        setWatchlistCrypto(w.crypto);
        setWatchlistStocks(w.stocks);
      } catch {
        // ignore
      }
    })();
  }, []);

  const load = useCallback(
    async (m: MarketFilter, sym: { symbol: string; market: Market } | null) => {
      setLoading(true);
      try {
        const r = sym ? await api.newsForAsset(sym.market, sym.symbol, 30) : await api.news(m, 50);
        setItems(r.items);
        setFetchedAt(new Date(r.fetched_at).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(marketFilter, symbolFilter);
    const id = setInterval(() => void load(marketFilter, symbolFilter), AUTO_REFRESH_MS);
    return () => clearInterval(id);
  }, [marketFilter, symbolFilter, load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load(marketFilter, symbolFilter);
    setRefreshing(false);
  }, [load, marketFilter, symbolFilter]);

  const markets: { key: MarketFilter; label: string }[] = [
    { key: "all", label: "SEMUA" },
    { key: "crypto", label: "CRYPTO" },
    { key: "etf", label: "ETF" },
    { key: "stock_id", label: "SAHAM IDX" },
    { key: "stock_us", label: "SAHAM US" },
  ];

  const symbolChips: { symbol: string; market: Market }[] = [
    ...watchlistCrypto.map((s) => ({ symbol: s, market: "crypto" as const })),
    ...watchlistStocks.map((s) => ({ symbol: s, market: "stock_id" as const })),
  ].filter((c) => {
    if (marketFilter === "all") return true;
    return c.market === marketFilter;
  });

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          testID="news-back-button"
          style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={[styles.appTitle, { color: colors.textPrimary }]}>Berita Live</Text>
          <Text style={[styles.appSub, { color: colors.textMuted }]}>
            RSS publik • {fetchedAt ? `update ${fetchedAt}` : "memuat…"}
            {symbolFilter ? ` • ${symbolFilter.symbol}` : ""}
          </Text>
        </View>
      </View>

      {/* Market filter pills */}
      <View style={styles.filterRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          {markets.map((f) => {
            const active = f.key === marketFilter && !symbolFilter;
            return (
              <TouchableOpacity
                key={f.key}
                onPress={() => {
                  setMarketFilter(f.key);
                  setSymbolFilter(null);
                }}
                testID={`news-filter-${f.key}`}
                style={[
                  styles.pill,
                  {
                    backgroundColor: active ? colors.accentBlue : colors.surface,
                    borderColor: active ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Text style={[styles.pillText, { color: active ? "#fff" : colors.textSecondary }]}>{f.label}</Text>
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      </View>

      {/* Symbol chips */}
      {symbolChips.length > 0 && (
        <View style={styles.symbolRow}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: 16, gap: 6, alignItems: "center" }}
          >
            {symbolChips.map((c) => {
              const active = symbolFilter?.symbol === c.symbol && symbolFilter?.market === c.market;
              return (
                <TouchableOpacity
                  key={`${c.market}-${c.symbol}`}
                  onPress={() => setSymbolFilter(active ? null : c)}
                  testID={`news-symbol-${c.symbol}`}
                  style={[
                    styles.symbolChip,
                    {
                      backgroundColor: active ? colors.accentBlue + "22" : colors.surface,
                      borderColor: active ? colors.accentBlue : colors.border,
                    },
                  ]}
                >
                  <Text style={[styles.symbolChipText, { color: active ? colors.accentBlue : colors.textSecondary }]}>
                    {c.symbol}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>
      )}

      {loading && items.length === 0 ? (
        <View style={styles.loader}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i, idx) => `${idx}-${i.title.slice(0, 30)}`}
          renderItem={({ item }) => <NewsRow item={item} />}
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32, gap: 8, paddingTop: 8 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accentBlue} />
          }
          ListEmptyComponent={
            <Text style={{ color: colors.textMuted, textAlign: "center", marginTop: 40 }}>
              Belum ada berita.
            </Text>
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 12,
  },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  appTitle: { fontSize: 20, fontWeight: "700", letterSpacing: 0.3 },
  appSub: { fontSize: 11, marginTop: 2 },
  filterRow: { height: 56, justifyContent: "center" },
  pill: {
    height: 36, paddingHorizontal: 14, borderRadius: 18, borderWidth: 1, flexShrink: 0,
    alignItems: "center", justifyContent: "center",
  },
  pillText: { fontSize: 12, fontWeight: "600", letterSpacing: 0.5 },
  symbolRow: { height: 44, justifyContent: "center" },
  symbolChip: {
    height: 30, paddingHorizontal: 10, borderRadius: 15, borderWidth: 1, flexShrink: 0,
    alignItems: "center", justifyContent: "center",
  },
  symbolChipText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.4 },
  loader: { flex: 1, alignItems: "center", justifyContent: "center" },
  row: {
    flexDirection: "row", padding: 10, borderRadius: 10, borderWidth: 1, gap: 10,
  },
  thumb: { width: 80, height: 80, borderRadius: 8 },
  thumbPlaceholder: { alignItems: "center", justifyContent: "center" },
  rowBody: { flex: 1, justifyContent: "space-between" },
  rowHead: { flexDirection: "row", justifyContent: "space-between", marginBottom: 4 },
  source: { fontSize: 10, fontWeight: "700", letterSpacing: 0.4, flex: 1 },
  time: { fontSize: 10, marginLeft: 8 },
  title: { fontSize: 13, fontWeight: "600", lineHeight: 18 },
  summary: { fontSize: 11, marginTop: 4, lineHeight: 15 },
});
