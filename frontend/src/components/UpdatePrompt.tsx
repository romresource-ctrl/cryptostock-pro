/**
 * UpdatePrompt — v10.1.6
 *
 * On every cold start, asks the backend what the LATEST published app
 * version is. If the installed build is older, a modal pops up telling
 * the user to update **via Google Play Store**. Dismissible with "Later".
 *
 * v10.1.5 — Server-driven texts (title/body/button/later) from
 *   /api/app-version so copy changes don't need a new APK.
 * v10.1.6 — ANTI-PHISHING TRUST: popup lama ("Ask the admin for the
 *   latest APK", "Get Latest APK") membuat user takut karena banyak scam
 *   APK dan uninstall app. Perubahan di sini:
 *     • Badge resmi "Google Play" di atas tombol (bukan ikon roket).
 *     • URL tujuan ditampilkan di bawah tombol → user bisa verifikasi.
 *     • Teks sumber "Opens Google Play Store" eksplisit.
 *     • URL target diambil dari server (`prompt.url` → play_store_url).
 *     • `Linking.openURL` menerima HTTPS Play Store URL langsung (bukan
 *       market:// pada iOS/web preview); Android akan dideep-link ke
 *       Play Store app oleh system handler untuk URL play.google.com.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import {
  Linking,
  Modal,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { API_BASE } from "@/src/lib/api";
import { APP_VERSION } from "@/src/lib/version";
import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";

const DEFAULT_PLAY_STORE_URL =
  "https://play.google.com/store/apps/details?id=com.cryptostockapps.aicryptostockpro";

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
  const [serverPrompt, setServerPrompt] = useState<Record<string, any> | null>(null);
  const [playStoreUrl, setPlayStoreUrl] = useState<string>(DEFAULT_PLAY_STORE_URL);

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
          // URL target: prefer prompt.url, fallback top-level play_store_url.
          const promptUrl =
            typeof data?.prompt?.url === "string" && data.prompt.url.trim()
              ? data.prompt.url.trim()
              : null;
          const topUrl =
            typeof data?.play_store_url === "string" && data.play_store_url.trim()
              ? data.play_store_url.trim()
              : null;
          setPlayStoreUrl(promptUrl || topUrl || DEFAULT_PLAY_STORE_URL);
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

  // Pilih string server sesuai bahasa aktif; fallback ke i18n lokal.
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
  const sourceLabel =
    srv("source_label") ||
    (lang === "id"
      ? "Membuka Google Play Store"
      : lang === "ru"
      ? "Открывает Google Play Store"
      : lang === "cn"
      ? "将打开 Google Play Store"
      : "Opens Google Play Store");
  const storeHint = srv("store_hint") || "Google Play";

  const openStore = () => {
    // v10.1.6 — Buka URL HTTPS Play Store langsung. Android OS akan
    // mendeep-link ke app Play Store resmi untuk URL play.google.com;
    // iOS/web membuka tab Play Store web. Hindari skema market:// supaya
    // tidak terkesan link mencurigakan.
    Linking.openURL(playStoreUrl).catch(() => {});
  };

  // Tampilan "host" URL yang bisa dibaca user untuk verifikasi anti-phishing.
  const displayHost = (() => {
    try {
      const u = new URL(playStoreUrl);
      return `${u.host}${u.pathname}`;
    } catch {
      return playStoreUrl;
    }
  })();

  return (
    <Modal visible transparent animationType="fade">
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
        <View
          style={[
            styles.box,
            { backgroundColor: colors.surface, borderColor: colors.accentBlue },
          ]}
        >
          {/* v10.1.6 — Badge resmi "Google Play" (bukan roket) supaya
              user langsung mengenali tujuan sebagai Play Store resmi. */}
          <View style={styles.badgeRow}>
            <View
              style={[
                styles.playBadge,
                {
                  backgroundColor: colors.accentBlue + "1A",
                  borderColor: colors.accentBlue + "66",
                },
              ]}
            >
              <Ionicons name="logo-google-playstore" size={14} color={colors.accentBlue} />
              <Text style={[styles.playBadgeText, { color: colors.accentBlue }]}>
                {storeHint}
              </Text>
            </View>
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
            <Ionicons name="logo-google-playstore" size={16} color="#fff" />
            <Text style={styles.updateBtnText}>{buttonText}</Text>
          </TouchableOpacity>

          {/* v10.1.6 — Baris "Opens Google Play Store" + URL tujuan
              terlihat → user bisa verifikasi SEBELUM menekan, menghapus
              kecurigaan phishing APK. */}
          <View style={styles.sourceRow}>
            <Ionicons
              name="shield-checkmark"
              size={11}
              color={colors.success || "#22c55e"}
            />
            <Text style={[styles.sourceLabel, { color: colors.textMuted }]} numberOfLines={1}>
              {sourceLabel}
            </Text>
          </View>
          <Text
            style={[styles.sourceUrl, { color: colors.textMuted }]}
            numberOfLines={1}
          >
            {displayHost}
          </Text>

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
  badgeRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 10,
  },
  playBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    borderWidth: 1,
  },
  playBadgeText: { fontSize: 11, fontWeight: "800", letterSpacing: 0.3 },
  title: { fontSize: 17, fontWeight: "800", letterSpacing: 0.3, textAlign: "center" },
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
  updateBtnText: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 0.5 },
  sourceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 8,
  },
  sourceLabel: { fontSize: 10.5, fontWeight: "700" },
  sourceUrl: {
    fontSize: 10,
    fontWeight: "600",
    opacity: 0.75,
    marginTop: 2,
    maxWidth: "100%",
  },
  laterBtn: { marginTop: 10, paddingVertical: 6 },
  laterText: { fontSize: 12, fontWeight: "700" },
});
