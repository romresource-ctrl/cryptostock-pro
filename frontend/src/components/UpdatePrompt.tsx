/**
 * UpdatePrompt — v8.12.69
 *
 * On every cold start, asks the backend what the LATEST published app
 * version is. If the installed build is older, a modal pops up telling
 * the user to update via Google Play. Dismissible with "Later" — it
 * re-appears on the next app start while the build is still outdated,
 * which is exactly what we want for update nagging.
 *
 * Fails silently on any network error so it can never block the app.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import {
  Linking,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { API_BASE } from "@/src/lib/api";
import { APP_VERSION } from "@/src/lib/version";
import { useTheme } from "@/src/theme/ThemeContext";

const PLAY_STORE_URL =
  "https://play.google.com/store/apps/details?id=com.cryptostockapps.aicryptostockpro";
const MARKET_URL = "market://details?id=com.cryptostockapps.aicryptostockpro";

/** "8.12.64" < "8.12.69" → true. Numeric per segment. */
function isOutdated(current: string, latest: string): boolean {
  const a = current.split(".").map((n) => parseInt(n, 10) || 0);
  const b = latest.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x < y) return true;
    if (x > y) return false;
  }
  return false;
}

export default function UpdatePrompt() {
  const { colors } = useTheme();
  const [latestVersion, setLatestVersion] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/app-version`);
        if (!res.ok) return;
        const data = await res.json();
        const latest = String(data?.latest_version ?? "");
        if (alive && latest && isOutdated(APP_VERSION, latest)) {
          setLatestVersion(latest);
        }
      } catch {
        /* offline / backend down — never block the app */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (!latestVersion) return null;

  const openStore = () => {
    // market:// opens the Play Store app directly on Android; the HTTPS
    // URL is the fallback (web preview / devices without Play Store).
    Linking.openURL(Platform.OS === "android" ? MARKET_URL : PLAY_STORE_URL).catch(
      () => Linking.openURL(PLAY_STORE_URL).catch(() => {}),
    );
  };

  return (
    <Modal visible transparent animationType="fade">
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
        <View
          style={[
            styles.box,
            { backgroundColor: colors.surface, borderColor: colors.accentBlue },
          ]}
        >
          <View
            style={[
              styles.iconRing,
              { borderColor: colors.accentBlue, backgroundColor: colors.accentBlue + "22" },
            ]}
          >
            <Ionicons name="rocket" size={26} color={colors.accentBlue} />
          </View>
          <Text style={[styles.title, { color: colors.textPrimary }]}>
            Update Available
          </Text>
          <Text style={[styles.body, { color: colors.textMuted }]}>
            A new version of AI Crypto Stock Pro is available on Google Play.
            {"\n\n"}
            Installed: v{APP_VERSION} → Latest: v{latestVersion}
            {"\n\n"}
            Update now to get the latest features, fixes, and market coverage.
          </Text>
          <TouchableOpacity
            onPress={openStore}
            style={[styles.updateBtn, { backgroundColor: colors.accentBlue }]}
            testID="update-now-button"
          >
            <Ionicons name="logo-google-playstore" size={16} color="#fff" />
            <Text style={styles.updateBtnText}>UPDATE ON PLAY STORE</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => setLatestVersion(null)}
            style={styles.laterBtn}
            testID="update-later-button"
          >
            <Text style={[styles.laterText, { color: colors.textMuted }]}>Later</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  box: {
    width: "100%",
    maxWidth: 340,
    borderRadius: 16,
    borderWidth: 1.5,
    padding: 20,
    alignItems: "center",
  },
  iconRing: {
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    marginBottom: 10,
  },
  title: { fontSize: 17, fontWeight: "800", letterSpacing: 0.3 },
  body: {
    fontSize: 12,
    lineHeight: 18,
    textAlign: "center",
    marginTop: 8,
  },
  updateBtn: {
    marginTop: 16,
    width: "100%",
    height: 44,
    borderRadius: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  updateBtnText: { color: "#fff", fontSize: 12, fontWeight: "900", letterSpacing: 0.6 },
  laterBtn: { marginTop: 10, paddingVertical: 6 },
  laterText: { fontSize: 12, fontWeight: "700" },
});
