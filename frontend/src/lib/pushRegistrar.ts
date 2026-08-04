/**
 * Push notification registration & permission flow (v8.3.0).
 *
 * Called after the user completes subscription. Handles:
 *   1. Pre-permission explainer dialog (why we need notifications).
 *   2. Native `Notifications.requestPermissionsAsync()`.
 *   3. Fetching the native device token via `getDevicePushTokenAsync()`.
 *   4. POSTing {user_id, platform, device_token, language} to
 *      `POST /api/register-push` on the backend.
 *
 * `user_id` is the device ID (already used for device-bound unlock codes),
 * so the same user_id is stable across subscription/restore cycles.
 *
 * All native APIs are guarded with `Platform.OS !== "web"` — push does not
 * work in web preview / Expo Go by design.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Alert, Linking, Platform } from "react-native";

import { API_BASE } from "@/src/lib/api";
import { getDeviceId } from "@/src/lib/deviceId";

const LANGUAGE_TITLES: Record<string, string> = {
  id: "Aktifkan Notifikasi",
  en: "Enable Notifications",
  ru: "Включить уведомления",
  cn: "开启通知",
};

const LANGUAGE_BODIES: Record<string, string> = {
  id:
    "Anda akan menerima ringkasan pasar harian di lock screen — sinyal AI paling akurat + berita paling relevan (WIB 08:45 pra-market IDX, 15:30 penutupan). Bisa dinonaktifkan kapan saja di Pengaturan.",
  en:
    "Get a daily market pulse on your lock screen — top AI signals + fresh news for your region. You can disable it anytime in Settings.",
  ru:
    "Ежедневный пульс рынка прямо на экран блокировки — сильнейшие AI-сигналы и свежие новости. Отключить можно в любой момент в настройках.",
  cn: "在锁屏收到每日市场脉搏 — 顶级 AI 信号与最新新闻。可随时在设置中关闭。",
};

const LANG_ALLOW: Record<string, string> = {
  id: "Ya, Aktifkan",
  en: "Enable",
  ru: "Включить",
  cn: "开启",
};

const LANG_LATER: Record<string, string> = {
  id: "Nanti Saja",
  en: "Not Now",
  ru: "Позже",
  cn: "稍后",
};

const LANG_SETTINGS: Record<string, string> = {
  id: "Buka Pengaturan",
  en: "Open Settings",
  ru: "Открыть настройки",
  cn: "打开设置",
};

const LANG_BLOCKED_BODY: Record<string, string> = {
  id: "Izin notifikasi diblokir. Buka Pengaturan untuk mengaktifkannya secara manual.",
  en: "Notifications are blocked. Open Settings to enable them manually.",
  ru: "Уведомления заблокированы. Откройте настройки, чтобы включить вручную.",
  cn: "通知已被系统阻止。请在设置中手动开启。",
};

// AsyncStorage keys — used to remember the pre-permission dialog outcome
// so we don't spam the user.
const KEY_PRE_PERMISSION_SHOWN = "push:prePermissionShown";
const KEY_LAST_REGISTERED_LANG = "push:lastRegisteredLang";

export type PushRegisterResult =
  | { status: "registered" }
  | { status: "denied"; canAskAgain: boolean }
  | { status: "unsupported" }
  | { status: "error"; error: string };

function pickLang(lang: string, dict: Record<string, string>): string {
  return dict[lang] ?? dict.en;
}

/**
 * Show the pre-permission explainer via native Alert. Resolves true if the
 * user tapped the "Allow" CTA, false otherwise.
 */
function askPrePermission(lang: string): Promise<boolean> {
  return new Promise((resolve) => {
    Alert.alert(
      pickLang(lang, LANGUAGE_TITLES),
      pickLang(lang, LANGUAGE_BODIES),
      [
        { text: pickLang(lang, LANG_LATER), style: "cancel", onPress: () => resolve(false) },
        { text: pickLang(lang, LANG_ALLOW), onPress: () => resolve(true) },
      ],
      { cancelable: true, onDismiss: () => resolve(false) },
    );
  });
}

/**
 * Show a follow-up when permission is blocked — deep-links into Settings.
 */
function showBlockedDialog(lang: string): void {
  Alert.alert(
    pickLang(lang, LANGUAGE_TITLES),
    pickLang(lang, LANG_BLOCKED_BODY),
    [
      { text: pickLang(lang, LANG_LATER), style: "cancel" },
      {
        text: pickLang(lang, LANG_SETTINGS),
        onPress: () => Linking.openSettings().catch(() => {}),
      },
    ],
  );
}

/**
 * Full flow — call after subscription becomes active.
 *
 * @param lang User's current language preference (id/en/ru/cn).
 * @param force If true, skip the "already shown" gate and re-run the dialog.
 */
export async function registerForPushIfEligible(
  lang: string,
  { force = false }: { force?: boolean } = {},
): Promise<PushRegisterResult> {
  // Web / non-physical devices can't receive push notifications.
  if (Platform.OS === "web") return { status: "unsupported" };
  if (!Device.isDevice) return { status: "unsupported" };

  try {
    // First — has the user already granted permission previously? If yes,
    // just refresh the token and re-register (tokens can rotate).
    const existing = await Notifications.getPermissionsAsync();
    if (existing.status !== "granted") {
      // Not granted yet. Decide whether to ask.
      if (!existing.canAskAgain) {
        // Permanently denied — nudge into Settings.
        showBlockedDialog(lang);
        return { status: "denied", canAskAgain: false };
      }
      // Show pre-permission explainer unless already shown in a previous
      // session (or we're forcing a retry).
      const shown = await AsyncStorage.getItem(KEY_PRE_PERMISSION_SHOWN);
      if (!force && shown === "1") {
        // We already asked before. Skip silent retry — user needs to
        // opt in from Settings screen.
        return { status: "denied", canAskAgain: true };
      }
      await AsyncStorage.setItem(KEY_PRE_PERMISSION_SHOWN, "1");
      const wantsPermission = await askPrePermission(lang);
      if (!wantsPermission) {
        return { status: "denied", canAskAgain: true };
      }
      const req = await Notifications.requestPermissionsAsync();
      if (req.status !== "granted") {
        // Show blocked dialog if request came back with canAskAgain false.
        if (!req.canAskAgain) {
          showBlockedDialog(lang);
        }
        return { status: "denied", canAskAgain: req.canAskAgain };
      }
    }

    // 2) We now have permission — fetch the native device token.
    const tokenResp = await Notifications.getDevicePushTokenAsync();
    const deviceToken = String(tokenResp.data ?? "");
    if (!deviceToken) {
      return { status: "error", error: "empty device token" };
    }

    // 3) POST to backend. `user_id` == device id so track-record & unlock
    // codes stay consistent.
    const userId = await getDeviceId();
    const platform = Platform.OS === "ios" ? "ios" : "android";
    const resp = await fetch(`${API_BASE}/register-push`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: userId,
        platform,
        device_token: deviceToken,
        language: lang,
      }),
    });
    if (!resp.ok) {
      return { status: "error", error: `backend ${resp.status}` };
    }
    await AsyncStorage.setItem(KEY_LAST_REGISTERED_LANG, lang);
    return { status: "registered" };
  } catch (e) {
    return { status: "error", error: (e as Error).message || "unknown" };
  }
}

/**
 * Re-register when language changes so the backend cohort mapping stays
 * accurate. Only runs if we already registered at least once (i.e. user
 * previously granted permission).
 */
export async function refreshPushLanguageIfRegistered(lang: string): Promise<void> {
  if (Platform.OS === "web" || !Device.isDevice) return;
  try {
    const last = await AsyncStorage.getItem(KEY_LAST_REGISTERED_LANG);
    if (!last || last === lang) return;
    const perm = await Notifications.getPermissionsAsync();
    if (perm.status !== "granted") return;
    await registerForPushIfEligible(lang, { force: false });
  } catch {
    /* silent */
  }
}
