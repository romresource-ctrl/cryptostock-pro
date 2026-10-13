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
import { useI18n } from "@/src/i18n/I18nContext";

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
  const { t, lang } = useI18n();
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  // v10.1.5 — Teks popup dari SERVER (bila ada) supaya bisa diubah via
  // Publish tanpa build APK baru. Fallback ke i18n hardcoded bila backend
  // lama / field kosong.
  const [serverPrompt, setServerPrompt] = useState<Record<string, any> | null>(null);

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
          if (data?.prompt && typeof data.prompt === "object") {
            setServerPrompt(data.prompt);
          }
        }
      } catch {
        /* offline / backend down — never block the app */
      }
    })();
    return () => {
      alive = false;
    };
  }, [lang]);

  if (!latestVersion) return null;

  // Pilih string server sesuai bahasa aktif; jatuh kembali ke i18n lokal.
  const srv = (key: string): string | null => {
    const node = serverPrompt?.[key];
    if (!node || typeof node !== "object") return null;
    const s = node[lang] || node.en || node.id;
    return typeof s === "string" && s.trim() ? s : null;
  };
  const titleText = srv("title") || t("update_title");
  const bodyText = srv("body") || t("update_body");
  const buttonText = srv("button") || t("update_now");
  const laterText = srv("later") || t("update_later");

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
            {titleText}
          </Text>
          <Text style={[styles.body, { color: colors.textMuted }]}>
            {bodyText}
          </Text>
          <Text style={[styles.bodyVersion, { color: colors.textMuted }]}>
            {t("update_body_versions")
              .replace("{cur}", APP_VERSION)
              .replace("{latest}", latestVersion)}
          </Text>
          <TouchableOpacity
            onPress={openStore}
            style={[styles.updateBtn, { backgroundColor: colors.accentBlue }]}
            testID="update-now-button"
          >
            <Ionicons name="download-outline" size={16} color="#fff" />
            <Text style={styles.updateBtnText}>{buttonText}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => setLatestVersion(null)}
            style={styles.laterBtn}
            testID="update-later-button"
          >
            <Text style={[styles.laterText, { color: colors.textMuted }]}>{laterText}</Text>
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
  bodyVersion: {
    fontSize: 11,
    lineHeight: 16,
    textAlign: "center",
    marginTop: 6,
    opacity: 0.85,
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
