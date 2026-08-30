/**
 * v8.12.36 — Trending Tickers column.
 *
 * Sits to the right of the Watchlist on the dashboard. Aggregates
 * the currently-loaded dashboard data from EVERY market and surfaces
 * the top N movers by absolute 24-hour percentage change. Users get
 * a glance at the loudest names across the whole app without having
 * to swipe through each column.
 *
 * Purely client-side: no extra backend call, so it's near-free and
 * updates live as the dashboard polls.
 */
import React, { useMemo } from "react";
import { FlatList, StyleSheet, Text, View } from "react-native";

import type { AssetSignal, Category, Market } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type TrendingHit = { asset: AssetSignal; market: Market };

type Props = {
  title: string;
  data: Record<Category, AssetSignal[]>;
  categories: readonly Category[];
  onPress: (a: AssetSignal, m: Market) => void;
  locked: boolean;
  emptyHint?: string;
  /** Column width — the dashboard passes its own COL_WIDTH so we align. */
  colWidth: number;
  /** Max rows to show. Default 12. */
  limit?: number;
  /** Optional child renderer for the actual card so the parent's memoised
   *  AssetCard is used (keeps sparkline + premium ribbon consistent). */
  renderCard: (hit: TrendingHit) => React.ReactNode;
};

export default function TrendingColumn({
  title,
  data,
  categories,
  locked: _locked,
  emptyHint,
  colWidth: _colWidth,
  limit = 12,
  renderCard,
}: Props) {
  const { colors } = useTheme();

  const hits: TrendingHit[] = useMemo(() => {
    const all: TrendingHit[] = [];
    categories.forEach((k) => {
      (data[k] || []).forEach((a) => {
        if (!a || !a.symbol) return;
        if (typeof a.change_pct_24h !== "number") return;
        all.push({ asset: a, market: k as Market });
      });
    });
    // Sort by absolute 24h % change (loudest movers first, both up + down).
    all.sort((x, y) => {
      const dx = Math.abs(x.asset.change_pct_24h ?? 0);
      const dy = Math.abs(y.asset.change_pct_24h ?? 0);
      return dy - dx;
    });
    return all.slice(0, limit);
  }, [data, categories, limit]);

  return (
    <View style={[styles.column, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.header, { borderColor: colors.border }]}>
        <Text style={[styles.title, { color: "#EF4444" }]} numberOfLines={1}>
          {title}
        </Text>
      </View>
      {hits.length === 0 ? (
        <View style={{ paddingVertical: 30, paddingHorizontal: 12 }}>
          <Text style={{ color: colors.textMuted, fontSize: 11.5, textAlign: "center", lineHeight: 16 }}>
            {emptyHint || "Loading top movers…"}
          </Text>
        </View>
      ) : (
        <FlatList
          data={hits}
          keyExtractor={(h) => `${h.market}:${h.asset.symbol}`}
          renderItem={({ item }) => <>{renderCard(item)}</>}
          showsVerticalScrollIndicator={false}
          contentContainerStyle={{ paddingBottom: 24 }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  column: {
    borderRadius: 12,
    overflow: "hidden",
  },
  header: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderBottomWidth: 0.5,
  },
  title: {
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
});
