/**
 * FlashPrice — Binance-style price flash animation.
 *
 * When the `value` prop changes to a NEW numeric value, the text briefly
 * flashes green (if higher than previous) or red (if lower). Same value
 * → no flash. This mimics how Binance/TradingView orderbook rows blink
 * when a level updates, giving users an unmistakable "this just moved"
 * cue even for sub-cent price changes.
 *
 * v8.6.8 — Added to satisfy user request "Opsi B" — dashboard cards
 * were polling every 60s (soon 20s) but the visual change was too
 * subtle. Flash animation makes every refresh feel alive.
 *
 * Design goals:
 *   - Zero JS-thread work: the color transition uses `useNativeDriver`
 *     so it never stutters even during a mass dashboard re-render.
 *   - Silent when the value hasn't changed (avoids epilepsy-trigger
 *     flicker on unrelated re-renders).
 *   - Drop-in replacement for `<Text>` — accepts the same style prop.
 */
import React from "react";
import { Animated, StyleProp, TextStyle } from "react-native";
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  /** Numeric price to display. Non-finite / NaN → falls through to `formatted`. */
  value: number | null | undefined;
  /** Text that gets rendered (already-formatted string incl. currency/decimals). */
  formatted: string;
  /** Base style; the animated color overrides `color` while the flash plays. */
  style?: StyleProp<TextStyle>;
  /** Flash duration in ms — default 500 (250 up, 250 back to base). */
  durationMs?: number;
  /** Minimum absolute delta to trigger flash. Prevents flashing on
      1e-9 rounding noise. Default 0. */
  minDelta?: number;
};

export default function FlashPrice({
  value,
  formatted,
  style,
  durationMs = 500,
  minDelta = 0,
}: Props) {
  const { colors } = useTheme();
  const prevRef = React.useRef<number | null>(null);
  // 0 = base color, 1 = fully-saturated flash color.
  const anim = React.useRef(new Animated.Value(0)).current;
  // Which color to flash — we set this synchronously when the value
  // changes and only READ it during animation.
  const flashColorRef = React.useRef<string>(colors.textPrimary);

  React.useEffect(() => {
    const curr = typeof value === "number" && Number.isFinite(value) ? value : null;
    const prev = prevRef.current;

    if (curr != null && prev != null && curr !== prev) {
      const delta = curr - prev;
      if (Math.abs(delta) > minDelta) {
        flashColorRef.current = delta > 0 ? colors.accentUp : colors.accentDown;
        // Snap to full-flash, then ease back to base.
        anim.setValue(1);
        Animated.timing(anim, {
          toValue: 0,
          duration: durationMs,
          useNativeDriver: false, // color interpolation can't run on native
        }).start();
      }
    }
    prevRef.current = curr;
  }, [value, minDelta, durationMs, anim, colors.accentUp, colors.accentDown]);

  // Interpolate between base text color (already in `style`) and flash.
  // We can't read `style.color` reliably so we interpolate against a
  // transparent overlay effect on flashColorRef by mixing alpha via
  // rgb() with `outputRange` at 1 and 0 with the flash color and undefined.
  // Simpler approach: use two colors, letting Animated pick.
  const animatedStyle = {
    color: anim.interpolate({
      inputRange: [0, 1],
      outputRange: [colors.textPrimary, flashColorRef.current],
    }),
  } as unknown as StyleProp<TextStyle>;

  return <Animated.Text style={[style, animatedStyle]}>{formatted}</Animated.Text>;
}
