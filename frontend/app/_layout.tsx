import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import { Stack, useRouter } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import * as SystemUI from "expo-system-ui";
import { useEffect } from "react";
import { Platform } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AuthProvider } from "@/src/auth/AuthContext";
import DisclaimerModal from "@/src/components/DisclaimerModal";
import { PushRegistrar } from "@/src/components/PushRegistrar";
import { useIconFonts } from "@/src/hooks/use-icon-fonts";
import { I18nProvider } from "@/src/i18n/I18nContext";
import { SubscriptionProvider } from "@/src/lib/subscriptionContext";
import { ThemeProvider, useTheme } from "@/src/theme/ThemeContext";

// Keep the native splash visible from cold start until icon fonts register.
// Required because @expo/vector-icons' componentDidMount fallback fires
// Font.loadAsync against a broken vendor path if any <Icon> mounts before
// the family is registered — which throws on Android Expo Go.
SplashScreen.preventAutoHideAsync();

// v8.3.0 — Push notification module-scope config (Emergent-managed push).
// Foreground handler + Android channel MUST live outside any component so
// they exist before any push notification arrives (per push playbook).
// Guarded for web because expo-notifications native calls crash on web.
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}

if (Platform.OS === "android") {
  Notifications.setNotificationChannelAsync("default", {
    name: "Market Pulse",
    description: "Daily market signals & news",
    importance: Notifications.AndroidImportance.MAX,
    sound: "default",
    vibrationPattern: [0, 250, 250, 250],
    lightColor: "#F0B90B",
  }).catch(() => {
    /* channel creation is best-effort — swallow errors */
  });
}

function RootStack() {
  const { mode, colors } = useTheme();

  // v8.13.2 — The Stack's `contentStyle` only colors the RN-rendered
  // content; it does NOT change the native Android window background.
  // Without this, the OS window's default white background is what
  // briefly shows through during a screen transition (most visible on
  // the back-navigation pop), even though app.json's splash screen is
  // black. Keep the native window background in sync with the theme.
  useEffect(() => {
    SystemUI.setBackgroundColorAsync(colors.background).catch(() => {
      /* best-effort — not available on web */
    });
  }, [colors.background]);

  return (
    <>
      <StatusBar style={mode === "dark" ? "light" : "dark"} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
          animation: "slide_from_right",
        }}
      />
    </>
  );
}

function PushTapListener() {
  // v8.3.0 — Route the user into the correct asset detail when they tap
  // a notification. Handles both warm-start (app open) and cold-start
  // (app killed) taps. Web guard skips native-only APIs.
  const router = useRouter();

  useEffect(() => {
    if (Platform.OS === "web") return;

    const openTarget = (data: Record<string, unknown> | null | undefined) => {
      if (!data) return;
      const url = (data.deeplink || data.action_url) as string | undefined;
      if (!url) return;
      try {
        if (url.startsWith("http")) {
          Linking.openURL(url);
        } else {
          router.push(url as never);
        }
      } catch {
        /* navigation failed — silent */
      }
    };

    const warmSub = Notifications.addNotificationResponseReceivedListener(
      (response) => {
        const data = response.notification.request.content.data ?? {};
        openTarget(data);
      },
    );

    Notifications.getLastNotificationResponseAsync()
      .then((response) => {
        if (!response) return;
        openTarget(response.notification.request.content.data ?? {});
      })
      .catch(() => {
        /* ignore */
      });

    return () => {
      warmSub.remove();
    };
  }, [router]);

  return null;
}

export default function RootLayout() {
  const [loaded, error] = useIconFonts();

  useEffect(() => {
    if (loaded || error) {
      SplashScreen.hideAsync();
    }
  }, [loaded, error]);

  // If the CDN is unreachable we fall through on error rather than wedging
  // the app — icons will tofu, but the app still boots.
  if (!loaded && !error) return null;

  return (
    // v8.13.3 — Explicit dark backdrop on the outermost container. This is
    // a plain RN View with no background of its own, so any moment where
    // no themed screen content has painted over it yet (e.g. mid native-
    // stack transition) let the raw white native window show through.
    // Static color (not theme-reactive) is intentional — this is only a
    // backstop for that gap frame, and the app always boots dark.
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#0B0E11" }}>
      <SafeAreaProvider>
        <KeyboardProvider>
          <ThemeProvider>
            <I18nProvider>
              <AuthProvider>
                <SubscriptionProvider>
                  <PushRegistrar />
                  <PushTapListener />
                  <RootStack />
                  {/* v8.12.44 — Disclaimer temporarily DISABLED per user
                      request so the dashboard is visible immediately on
                      launch (contest snapshot capture). Uncomment the
                      line below to re-enable the blocking legal modal. */}
                  {/* <DisclaimerModal /> */}
                </SubscriptionProvider>
              </AuthProvider>
            </I18nProvider>
          </ThemeProvider>
        </KeyboardProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
