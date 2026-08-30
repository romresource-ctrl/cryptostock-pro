/**
 * v8.12.38 — Trending Tickers column with tap-to-cycle mode filter.
 *
 * Sits to the right of the Watchlist on the dashboard. Aggregates the
 * currently-loaded dashboard data from EVERY market and surfaces the
 * top N tickers by the currently-selected metric:
 *
 *   • gainers  — largest positive 24h % change
 *   • losers   — largest negative 24h % change
 *   • volume   — highest 24h USD volume
 *
 * Tap the "🔥 Trending" header pill to cycle through the three modes.
 * Selection is persisted to AsyncStorage across app relaunches.
 *
 * Purely client-side: no extra backend call — updates live as the
 * dashboard polls.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { FlatList, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

import type { AssetSignal, Category, Market } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type TrendingMode = "gainers" | "losers" | "volume";
type TrendingHit = { asset: AssetSignal; market: Market };

const MODE_KEY = "@ai-crypto-stock-pro:trending-mode:v1";
const MODES: TrendingMode[] = ["gainers", "losers", "volume"];

const MODE_META: Record<
  TrendingMode,
  { emoji: string; labelId: string; labelEn: string; color: string }
> = {
  gainers: { emoji: "🚀", labelId: "Top Gainers", labelEn: "Top Gainers", color: "#22C55E" },
  losers: { emoji: "📉", labelId: "Top Losers", labelEn: "Top Losers", color: "#EF4444" },
  volume: { emoji: "💧", labelId: "High Volume", labelEn: "High Volume", color: "#3B82F6" },
};

type Props = {
  /** Fallback title used when the user has never chosen a mode (unused now — we
   *  always render "<emoji> <mode label>" once the mode is known). Kept in the
   *  API so callers do not have to change their JSX. */
  title?: string;
  data: Record<Category, AssetSignal[]>;
  categories: readonly Category[];
  onPress: (a: AssetSignal, m: Market) => void;
  locked: boolean;
  emptyHint?: string;
  colWidth: number;
  limit?: number;
  renderCard: (hit: TrendingHit) => React.ReactNode;
  /** Optional label for the current mode ("gainers"/"losers"/"volume"). If the
   *  caller passes localised strings for these we use them; otherwise we fall
   *  back to English. */
  modeLabels?: Partial<Record<TrendingMode, string>>;
};

export default function TrendingColumn({
  data,
  categories,
  locked: _locked,
  emptyHint,
  colWidth: _colWidth,
  limit = 12,
  renderCard,
  modeLabels,
}: Props) {
  const { colors } = useTheme();
  const [mode, setMode] = useState<TrendingMode>("gainers");
  const [loaded, setLoaded] = useState(false);

  // Load persisted mode on mount.
  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(MODE_KEY);
        if (raw && MODES.includes(raw as TrendingMode)) {
          setMode(raw as TrendingMode);
        }
      } catch {
        /* ignore */
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const cycleMode = useCallback(() => {
    setMode((prev) => {
      const idx = MODES.indexOf(prev);
      const next = MODES[(idx + 1) % MODES.length];
      AsyncStorage.setItem(MODE_KEY, next).catch(() => {
        /* ignore */
      });
      return next;
    });
  }, []);

  const hits: TrendingHit[] = useMemo(() => {
    if (!loaded) return [];
    const all: TrendingHit[] = [];
    categories.forEach((k) => {
      (data[k] || []).forEach((a) => {
        if (!a || !a.symbol) return;
        // For gainers/losers we need a valid % change. For volume we need
        // a valid numeric volume_24h. Skip entries missing the metric.
        if (mode === "volume") {
          if (typeof a.volume_24h !== "number") return;
        } else {
          if (typeof a.change_pct_24h !== "number") return;
        }
        all.push({ asset: a, market: k as Market });
      });
    });

    if (mode === "gainers") {
      all.sort((x, y) => (y.asset.change_pct_24h ?? 0) - (x.asset.change_pct_24h ?? 0));
    } else if (mode === "losers") {
      all.sort((x, y) => (x.asset.change_pct_24h ?? 0) - (y.asset.change_pct_24h ?? 0));
    } else {
      all.sort((x, y) => (y.asset.volume_24h ?? 0) - (x.asset.volume_24h ?? 0));
    }
    return all.slice(0, limit);
  }, [loaded, data, categories, mode, limit]);

  const meta = MODE_META[mode];
  const label = modeLabels?.[mode] || meta.labelEn;

  return (
    <View style={[styles.column, { backgroundColor: colors.surfaceAlt }]}>
      {/* Tappable header pill — tap anywhere on it to cycle modes. */}
      <TouchableOpacity
        onPress={cycleMode}
        activeOpacity={0.7}
        style={[styles.header, { borderColor: colors.border }]}
        testID={`trending-mode-${mode}`}
        accessibilityLabel={`Trending mode: ${label}. Tap to change.`}
      >
        <Text style={[styles.title, { color: meta.color }]} numberOfLines={1}>
          {meta.emoji} {label}
        </Text>
        <Text style={[styles.cycleHint, { color: colors.textMuted }]} numberOfLines={1}>
          {"↻"}
        </Text>
      </TouchableOpacity>
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
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 6,
  },
  title: {
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.4,
    flex: 1,
  },
  cycleHint: {
    fontSize: 12,
    fontWeight: "700",
    opacity: 0.8,
  },
});
