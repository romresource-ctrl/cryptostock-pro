import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
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

type Filter = "all" | Market;

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
    </TouchableOpacity>
  );
}

export default function NewsScreen() {
  const { colors } = useTheme();
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [fetchedAt, setFetchedAt] = useState<string>("");

  const load = useCallback(async (f: Filter) => {
    setLoading(true);
    try {
      const r = await api.news(f, 50);
      setItems(r.items);
      setFetchedAt(new Date(r.fetched_at).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(filter);
  }, [filter, load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load(filter);
    setRefreshing(false);
  }, [load, filter]);

  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: "SEMUA" },
    { key: "crypto", label: "CRYPTO" },
    { key: "stock", label: "SAHAM" },
  ];

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
          </Text>
        </View>
      </View>

      <View style={styles.filterRow}>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 8, alignItems: "center" }}
        >
          {filters.map((f) => {
            const active = f.key === filter;
            return (
              <TouchableOpacity
                key={f.key}
                onPress={() => setFilter(f.key)}
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

      {loading && items.length === 0 ? (
        <View style={styles.loader}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i, idx) => `${idx}-${i.title.slice(0, 30)}`}
          renderItem={({ item }) => <NewsRow item={item} />}
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32, gap: 8 }}
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
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  appTitle: { fontSize: 20, fontWeight: "700", letterSpacing: 0.3 },
  appSub: { fontSize: 11, marginTop: 2 },
  filterRow: { height: 56, justifyContent: "center" },
  pill: {
    height: 36,
    paddingHorizontal: 14,
    borderRadius: 18,
    borderWidth: 1,
    flexShrink: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  pillText: { fontSize: 12, fontWeight: "600", letterSpacing: 0.5 },
  loader: { flex: 1, alignItems: "center", justifyContent: "center" },
  row: { padding: 12, borderRadius: 10, borderWidth: 1 },
  rowHead: { flexDirection: "row", justifyContent: "space-between", marginBottom: 6 },
  source: { fontSize: 11, fontWeight: "700", letterSpacing: 0.4, flex: 1 },
  time: { fontSize: 10, marginLeft: 8 },
  title: { fontSize: 14, fontWeight: "600", lineHeight: 20 },
  summary: { fontSize: 12, marginTop: 6, lineHeight: 17 },
});
