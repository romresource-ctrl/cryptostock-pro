/**
 * Babel config for Expo SDK 54 + Reanimated 4 + Gesture Handler v2.
 *
 * v8.6.16 — Explicit registration of `react-native-worklets/plugin`
 * so that chart pan/pinch gestures (Gesture.Pan / Gesture.Pinch in
 * CandlestickChart.tsx) can hop between UI and JS threads via
 * Reanimated worklets. Without this plugin, native Android build
 * fails with "Reanimated worklets require the react-native-worklets
 * Babel plugin" at runtime the moment a gesture callback fires.
 *
 * Requirements imposed by the plugin:
 *   1. `react-native-worklets/plugin` MUST be the LAST entry in the
 *      `plugins` array. Because we only register it here (all other
 *      transforms come from `babel-preset-expo`), it's trivially last.
 *   2. `babel-preset-expo` MUST be the first (and only) preset — it
 *      bundles TypeScript/Flow/JSX/optional-chaining/etc. transforms
 *      that Metro relies on for both Android and iOS builds.
 *   3. `api.cache(true)` is safe here — this config is fully static
 *      and has no environment-dependent branches.
 *
 * Do NOT add other plugins (e.g. legacy `react-native-reanimated/plugin`
 * which was renamed to `react-native-worklets/plugin` in RN Worklets 0.5)
 * — doing so risks duplicating the worklet transform and re-introducing
 * the exact build failure this file exists to fix.
 */
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
    plugins: ["react-native-worklets/plugin"],
  };
};
