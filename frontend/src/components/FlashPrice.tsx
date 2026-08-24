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
 *
 * v8.6.9 — Gated on a RELATIVE move (default ~0.05%) instead of any
 * change at all, and throttled to at most one flash per ~1.5-2s. Ticks
 * that are too small or too frequent still update the displayed text
 * (via `formatted`) but no longer trigger a flash — sub-threshold
 * drift accumulates against the last-flashed baseline so a real move
 * spread across several tiny ticks still flashes once it clears the
 * threshold.
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
      1e-9 rounding noise. Default 0. Combined (AND) with `minPctChange`. */
  minDelta?: number;
  /** Minimum RELATIVE move (fraction, e.g. 0.0005 = 0.05%) required to
      trigger a flash. Default 0.0005 (~0.05%) — filters out sub-cent/
      sub-bps ticker noise that isn't a meaningful price move. */
  minPctChange?: number;
  /** Minimum time between flashes, in ms. A qualifying move that
      arrives before this elapses updates the displayed text but does
      not re-trigger the flash animation. Default 1500 (throttles to at
      most one flash roughly every 1.5-2s). */
  throttleMs?: number;
};

export default function FlashPrice({
  value,
  formatted,
  style,
  durationMs = 500,
  minDelta = 0,
  minPctChange = 0.0005,
  throttleMs = 1500,
}: Props) {
  const { colors } = useTheme();
  // Baseline the next flash's delta is measured against. Only advances
  // when a flash actually fires, so sub-threshold ticks accumulate
  // instead of resetting the comparison on every render.
  const flashBaseRef = React.useRef<number | null>(null);
  const lastFlashAtRef = React.useRef<number>(0);
  // 0 = base color, 1 = fully-saturated flash color.
  const anim = React.useRef(new Animated.Value(0)).current;
  // Which color to flash — we set this synchronously when the value
  // changes and only READ it during animation.
  const flashColorRef = React.useRef<string>(colors.textPrimary);

  React.useEffect(() => {
    const curr = typeof value === "number" && Number.isFinite(value) ? value : null;
    const base = flashBaseRef.current;

    if (curr == null) {
      flashBaseRef.current = null;
      return;
    }
    if (base == null) {
      flashBaseRef.current = curr;
      return;
    }
    if (curr === base) return;

    const delta = curr - base;
    const relChange = Math.abs(delta) / (Math.abs(base) || 1);
    const now = Date.now();
    const throttleOk = now - lastFlashAtRef.current >= throttleMs;

    if (Math.abs(delta) > minDelta && relChange >= minPctChange && throttleOk) {
      flashColorRef.current = delta > 0 ? colors.accentUp : colors.accentDown;
      // Snap to full-flash, then ease back to base.
      anim.setValue(1);
      Animated.timing(anim, {
        toValue: 0,
        duration: durationMs,
        useNativeDriver: false, // color interpolation can't run on native
      }).start();
      flashBaseRef.current = curr;
      lastFlashAtRef.current = now;
    }
    // Below threshold or still throttled: leave flashBaseRef alone so
    // the next tick's delta is measured cumulatively from here.
  }, [value, minDelta, minPctChange, throttleMs, durationMs, anim, colors.accentUp, colors.accentDown]);

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
