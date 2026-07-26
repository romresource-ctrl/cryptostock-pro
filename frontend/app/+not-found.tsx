import { router } from "expo-router";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";

import { useTheme } from "@/src/theme/ThemeContext";

/**
 * Catch-all for unmatched deep links (e.g. `aicryptostockpro:///` returned
 * from Google Play Billing purchase sheet or misconfigured intents). Instead
 * of showing Expo Router's default "Unmatched Route / Page could not be
 * found" error screen, silently redirect back to the dashboard. This
 * mirrors what most consumer apps do — deep-link failures should never be
 * user-visible.
 */
export default function NotFoundScreen() {
  const { colors } = useTheme();

  useEffect(() => {
    // Use replace so the broken URL doesn't stay in nav history.
    const t = setTimeout(() => {
      try {
        router.replace("/");
      } catch {
        /* ignore */
      }
    }, 50);
    return () => clearTimeout(t);
  }, []);

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: colors.background,
      }}
    >
      <ActivityIndicator size="large" color={colors.accentBlue} />
    </View>
  );
}
