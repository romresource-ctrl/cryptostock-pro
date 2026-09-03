/**
 * DipTopPopup — v8.13.0
 *
 * Mini floating alert that appears at top-center of the screen when
 * the DipTopZone reaches its terminal tier (dip3 or top3). Auto-dismisses
 * after 4 seconds via opacity fade + translateY animation.
 *
 * Non-interactive (pointerEvents="none"), so it never blocks chart
 * gestures or scroll.
 */
import React, { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import type { DipTopZone } from "@/src/hooks/useDipTopAlert";

interface Props {
  zone: DipTopZone;
  /** Optional current price for context on the popup */
  livePrice?: number | null;
  /** Symbol / market label ("BTC", "ETH", etc) */
  symbol?: string | null;
}

const DipTopPopup: React.FC<Props> = ({ zone, livePrice, symbol }) => {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(-16)).current;
  // Retain the last non-idle zone so we can render its label
  // even while the popup fades out.
  const displayedRef = useRef<DipTopZone>("idle");

  useEffect(() => {
    // Only fire for terminal tiers (tier 3). Lower tiers are shown
    // by the DipTopBadge in the toggle row; the popup is reserved
    // for the "wink" extremes.
    const isTerminal = zone === "dip3" || zone === "top3";
    if (!isTerminal) return;

    displayedRef.current = zone;
    opacity.setValue(0);
    translateY.setValue(-16);

    // Fade + slide-in over 250ms, hold 3.3s, fade out 450ms
    const anim = Animated.sequence([
      Animated.parallel([
        Animated.timing(opacity, { toValue: 1, duration: 250, useNativeDriver: true }),
        Animated.timing(translateY, { toValue: 0, duration: 250, useNativeDriver: true }),
      ]),
      Animated.delay(3300),
      Animated.parallel([
        Animated.timing(opacity, { toValue: 0, duration: 450, useNativeDriver: true }),
        Animated.timing(translateY, { toValue: -12, duration: 450, useNativeDriver: true }),
      ]),
    ]);
    anim.start();
    return () => anim.stop();
  }, [zone, opacity, translateY]);

  // Nothing to render before first trigger
  if (displayedRef.current === "idle") return null;

  const isDip = displayedRef.current === "dip3";
  const emoji = isDip ? "💎" : "🔥";
  const title = isDip ? "BUY THE DIP #3" : "SELL THE TOP #3";
  const subtitle = isDip
    ? "Price hit deepest valley of the recent swing"
    : "Price hit highest peak of the recent swing";
  const bg = isDip ? "#0EA5E9" : "#F97316";
  const priceStr = livePrice != null && Number.isFinite(livePrice)
    ? formatCompactPrice(livePrice)
    : null;

  return (
    <Animated.View
      pointerEvents="none"
      style={[
        styles.wrapper,
        { opacity, transform: [{ translateY }] },
      ]}
    >
      <View style={[styles.card, { backgroundColor: bg }]}>
        <Text style={styles.emoji}>{emoji}</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle} numberOfLines={2}>
            {subtitle}
          </Text>
          {symbol || priceStr ? (
            <Text style={styles.price}>
              {symbol ? symbol.toUpperCase() : ""}
              {symbol && priceStr ? "  " : ""}
              {priceStr || ""}
            </Text>
          ) : null}
        </View>
      </View>
    </Animated.View>
  );
};

function formatCompactPrice(p: number): string {
  // v8.12.54 — Aligned with the global adaptive precision (see
  // formatPrice in src/lib/api.ts). Sub-dollar tokens now render with
  // 5 decimals so DipTop pop-ups match the header price exactly.
  const abs = Math.abs(p);
  if (abs >= 1000) return `$${p.toFixed(0)}`;
  if (abs >= 1) return `$${p.toFixed(2)}`;
  if (abs >= 0.01) return `$${p.toFixed(5)}`;
  if (abs >= 0.0001) return `$${p.toFixed(6)}`;
  return `$${p.toFixed(8)}`;
}

const styles = StyleSheet.create({
  wrapper: {
    position: "absolute",
    top: 8,
    left: 16,
    right: 16,
    zIndex: 100,
    alignItems: "center",
  },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 10,
    minWidth: 260,
    maxWidth: 360,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.4,
    shadowRadius: 6,
    elevation: 8,
  },
  emoji: { fontSize: 22 },
  title: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "900",
    letterSpacing: 0.6,
  },
  subtitle: {
    color: "#f8fafc",
    fontSize: 10.5,
    fontWeight: "600",
    marginTop: 1,
    opacity: 0.9,
  },
  price: {
    color: "#fff",
    fontSize: 11,
    fontWeight: "800",
    marginTop: 2,
    fontVariant: ["tabular-nums"],
  },
});

export default DipTopPopup;
