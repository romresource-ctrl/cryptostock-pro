import * as Application from "expo-application";
import * as Device from "expo-device";
import { Platform } from "react-native";
import * as SecureStore from "expo-secure-store";

const FALLBACK_KEY = "cryptostock.device_fingerprint";

/**
 * Get a stable device identifier that survives app restarts.
 *
 * Strategy:
 *  - Android: expo-application `androidId` (per-install unique, stable)
 *  - iOS: expo-application `iosIdForVendorAsync` (per-vendor)
 *  - Web/fallback: generate a random UUID and persist in SecureStore
 *
 * NOTE: iOS Vendor ID resets when ALL apps from the same vendor are
 * uninstalled; Android ID resets on factory reset. This is acceptable
 * for our binding purposes (admin can reset device binding if needed).
 */
export async function getDeviceId(): Promise<string> {
  try {
    if (Platform.OS === "android") {
      const id = Application.getAndroidId();
      if (id) return `android:${id}`;
    }
    if (Platform.OS === "ios") {
      const id = await Application.getIosIdForVendorAsync();
      if (id) return `ios:${id}`;
    }
  } catch {
    // fall through to SecureStore fallback
  }
  // Fallback: persistent random UUID (web / unknown platforms)
  // v9.2.0 — Web: baca/tulis localStorage LANGSUNG. Shim web
  // expo-secure-store tidak konsisten antar sesi → device id berubah
  // (ephemeral) → entitlement premium selalu gagal diverifikasi backend.
  if (Platform.OS === "web") {
    try {
      const ls = globalThis.localStorage?.getItem(FALLBACK_KEY);
      if (ls) return ls;
      const rnd = `web:${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
      globalThis.localStorage?.setItem(FALLBACK_KEY, rnd);
      return rnd;
    } catch {
      /* fallthrough ke SecureStore */
    }
  }
  try {
    const existing = await SecureStore.getItemAsync(FALLBACK_KEY);
    if (existing) return existing;
    const rnd = `web:${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
    await SecureStore.setItemAsync(FALLBACK_KEY, rnd);
    return rnd;
  } catch {
    // Last-resort ephemeral ID (should never happen)
    return `ephemeral:${Math.random().toString(36).slice(2)}`;
  }
}

/**
 * Human-readable device name for admin display.
 * e.g. "Samsung SM-A546E" or "iPhone 14 Pro"
 */
export function getDeviceName(): string {
  const brand = Device.brand || Device.manufacturer || "";
  const model = Device.modelName || "";
  if (brand && model) return `${brand} ${model}`.trim();
  return Device.deviceName || `${Platform.OS} device`;
}
