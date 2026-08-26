/**
 * v8.12.34 — Themed skeleton view for the initial dashboard fetch.
 *
 * Replaces the raw blue `<ActivityIndicator />` used at cold-start /
 * per-column loading so the app looks polished (not "empty + spinner")
 * during the first WebSocket handshake. Uses the dark theme surface /
 * border tokens so it visually integrates with the rest of the app —
 * important for the Emergent contest gallery thumbnail.
 */
import React, { useEffect, useMemo, useRef } from "react";
import { Animated, Easing, StyleSheet, Text, View } from "react-native";
import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";

type Props = {
  /** How many skeleton rows to render (default 6). */
  rows?: number;
  /** Show the "Syncing Market Data" label at top. */
  showLabel?: boolean;
  /** Compact height mode (used inside chart panes). */
  compact?: boolean;
};

const MarketSkeleton: React.FC<Props> = ({ rows = 6, showLabel = true, compact = false }) => {
  const { colors } = useTheme();
  const { t } = useI18n();
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, {
          toValue: 1,
          duration: 900,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(shimmer, {
          toValue: 0,
          duration: 900,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [shimmer]);

  const opacity = shimmer.interpolate({ inputRange: [0, 1], outputRange: [0.35, 0.85] });

  const items = useMemo(() => Array.from({ length: rows }), [rows]);

  return (
    <View
      style={[
        styles.wrap,
        compact ? styles.wrapCompact : null,
        { backgroundColor: colors.background },
      ]}
      testID="market-skeleton"
    >
      {showLabel && (
        <View style={styles.labelRow}>
          <View style={[styles.dot, { backgroundColor: colors.accentBlue ?? "#3b82f6" }]} />
          <Text style={[styles.label, { color: colors.textMuted }]}>{t("syncing_market")}</Text>
        </View>
      )}
      {items.map((_, i) => (
        <Animated.View
          key={i}
          style={[
            styles.card,
            {
              backgroundColor: colors.surface,
              borderColor: colors.border,
              opacity,
            },
          ]}
        >
          <View style={styles.rowTop}>
            <View style={[styles.pillSm, { backgroundColor: colors.border }]} />
            <View style={[styles.pillXs, { backgroundColor: colors.border }]} />
          </View>
          <View style={styles.rowMid}>
            <View style={[styles.pillLg, { backgroundColor: colors.border }]} />
            <View style={[styles.pillMd, { backgroundColor: colors.border }]} />
          </View>
          <View style={styles.rowBot}>
            <View style={[styles.pillWide, { backgroundColor: colors.border }]} />
          </View>
        </Animated.View>
      ))}
    </View>
  );
};

const styles = StyleSheet.create({
  wrap: {
    paddingHorizontal: 10,
    paddingTop: 8,
    paddingBottom: 20,
    gap: 8,
  },
  wrapCompact: {
    paddingVertical: 6,
    gap: 6,
  },
  labelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 4,
    paddingBottom: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  label: {
    fontSize: 11,
    fontWeight: "600",
    letterSpacing: 0.3,
  },
  card: {
    borderRadius: 12,
    borderWidth: 0.5,
    paddingVertical: 12,
    paddingHorizontal: 12,
    gap: 8,
  },
  rowTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  rowMid: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 4,
  },
  rowBot: {
    marginTop: 4,
  },
  pillXs: { width: 40, height: 10, borderRadius: 5 },
  pillSm: { width: 70, height: 12, borderRadius: 6 },
  pillMd: { width: 60, height: 14, borderRadius: 7 },
  pillLg: { width: 110, height: 18, borderRadius: 6 },
  pillWide: { width: "100%", height: 8, borderRadius: 4 },
});

export default MarketSkeleton;
