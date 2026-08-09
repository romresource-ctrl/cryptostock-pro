/**
 * TickCounter — small pill that increments every time the Binance kline
 * WebSocket delivers a new frame. Placed next to the "● LIVE" badge on
 * the asset detail screen (v8.6.12).
 *
 * Why this exists:
 *   At the 1h timeframe, a live candle's OHLC changes by fractions of a
 *   pixel every 200-1000ms — literally imperceptible to the eye.  Users
 *   have (rightfully) complained that the chart "looks static".  This
 *   pill gives them undeniable visual proof that data IS streaming:
 *   every WS frame → number goes up → pill flashes accent-blue for
 *   300ms and settles back.  If they see the number climbing they can
 *   be sure the connection is live.
 */
import React from "react";
import { Animated, Easing, StyleSheet, View } from "react-native";
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  /** Millisecond timestamp of the most recent WS frame (from useBinanceKline). */
  updatedAt: number;
};

export default function TickCounter({ updatedAt }: Props) {
  const { colors } = useTheme();
  const [count, setCount] = React.useState(0);
  const flash = React.useRef(new Animated.Value(0)).current;
  const lastUpdatedRef = React.useRef<number>(updatedAt);

  React.useEffect(() => {
    if (updatedAt !== lastUpdatedRef.current) {
      lastUpdatedRef.current = updatedAt;
      setCount((c) => c + 1);
      flash.setValue(1);
      Animated.timing(flash, {
        toValue: 0,
        duration: 350,
        easing: Easing.out(Easing.quad),
        useNativeDriver: false,
      }).start();
    }
  }, [updatedAt, flash]);

  const bg = flash.interpolate({
    inputRange: [0, 1],
    outputRange: [colors.surfaceAlt, colors.accentBlue],
  });
  const fg = flash.interpolate({
    inputRange: [0, 1],
    outputRange: [colors.textMuted, "#000"],
  });

  return (
    <View style={{ marginLeft: 6 }}>
      <Animated.View
        style={[
          styles.pill,
          { backgroundColor: bg, borderColor: colors.border },
        ]}
      >
        <Animated.Text style={[styles.txt, { color: fg }]}>
          {"⚡ "}
          {count}
        </Animated.Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 6,
    borderWidth: 1,
    minWidth: 32,
    alignItems: "center",
  },
  txt: {
    fontSize: 10,
    fontWeight: "800",
    fontVariant: ["tabular-nums"],
  },
});
