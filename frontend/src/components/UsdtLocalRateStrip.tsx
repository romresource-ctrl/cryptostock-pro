/**
 * UsdtLocalRateStrip — compact live-FX widget shown on the dashboard header.
 *
 * Displays "1 USDT ≈ Rp 15,850" (or user's local currency) based on the
 * device locale. Rates are fetched from Frankfurter public API (free,
 * unauthenticated, ECB-sourced) and cached in AsyncStorage for 6 hours to
 * limit network chatter while still feeling "live".
 *
 * The widget hides itself gracefully if:
 *   • User's locale maps to USD (no conversion needed)
 *   • FX fetch fails and no cache
 *   • Unsupported currency
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { NativeModules, Platform, StyleSheet, Text, View } from "react-native";

import { useI18n, type Lang } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

// Locale prefix → currency + flag + symbol. Users mostly care about the
// major countries; if their locale isn't listed we hide the widget.
const LOCALE_TO_CURRENCY: Record<string, { code: string; symbol: string; flag: string; name: string }> = {
  id: { code: "IDR", symbol: "Rp", flag: "🇮🇩", name: "Rupiah" },
  ja: { code: "JPY", symbol: "¥", flag: "🇯🇵", name: "Yen" },
  ko: { code: "KRW", symbol: "₩", flag: "🇰🇷", name: "Won" },
  zh: { code: "CNY", symbol: "¥", flag: "🇨🇳", name: "Yuan" },
  th: { code: "THB", symbol: "฿", flag: "🇹🇭", name: "Baht" },
  vi: { code: "VND", symbol: "₫", flag: "🇻🇳", name: "Dong" },
  ms: { code: "MYR", symbol: "RM", flag: "🇲🇾", name: "Ringgit" },
  hi: { code: "INR", symbol: "₹", flag: "🇮🇳", name: "Rupee" },
  ta: { code: "INR", symbol: "₹", flag: "🇮🇳", name: "Rupee" },
  ar: { code: "AED", symbol: "د.إ", flag: "🇦🇪", name: "Dirham" },
  ru: { code: "RUB", symbol: "₽", flag: "🇷🇺", name: "Ruble" },
  fr: { code: "EUR", symbol: "€", flag: "🇫🇷", name: "Euro" },
  de: { code: "EUR", symbol: "€", flag: "🇩🇪", name: "Euro" },
  it: { code: "EUR", symbol: "€", flag: "🇮🇹", name: "Euro" },
  es: { code: "EUR", symbol: "€", flag: "🇪🇸", name: "Euro" },
  pt: { code: "BRL", symbol: "R$", flag: "🇧🇷", name: "Real" },
  tr: { code: "TRY", symbol: "₺", flag: "🇹🇷", name: "Lira" },
  nl: { code: "EUR", symbol: "€", flag: "🇳🇱", name: "Euro" },
  pl: { code: "PLN", symbol: "zł", flag: "🇵🇱", name: "Złoty" },
  fil: { code: "PHP", symbol: "₱", flag: "🇵🇭", name: "Peso" },
  tl: { code: "PHP", symbol: "₱", flag: "🇵🇭", name: "Peso" },
  // English variants → keep specific ones for GBP / AUD / CAD / SGD
  "en-gb": { code: "GBP", symbol: "£", flag: "🇬🇧", name: "Pound" },
  "en-au": { code: "AUD", symbol: "A$", flag: "🇦🇺", name: "AUD" },
  "en-ca": { code: "CAD", symbol: "C$", flag: "🇨🇦", name: "CAD" },
  "en-sg": { code: "SGD", symbol: "S$", flag: "🇸🇬", name: "SGD" },
  "en-hk": { code: "HKD", symbol: "HK$", flag: "🇭🇰", name: "HKD" },
  "en-nz": { code: "NZD", symbol: "NZ$", flag: "🇳🇿", name: "NZD" },
  "en-za": { code: "ZAR", symbol: "R", flag: "🇿🇦", name: "Rand" },
};

const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6 hours
const STORAGE_KEY = "fx:usdt_local";

function detectDeviceLocale(): string {
  // On native, Intl.NumberFormat().resolvedOptions().locale returns the
  // device locale directly (e.g. "id-ID", "en-US"). On web, same. If the
  // Intl API isn't available for some reason, fall back to Platform hints.
  try {
    const raw = Intl.NumberFormat().resolvedOptions().locale;
    if (raw) return raw.toLowerCase();
  } catch {
    /* fallthrough */
  }
  if (Platform.OS === "ios") {
    const settings = (NativeModules as any)?.SettingsManager?.settings;
    return String(settings?.AppleLocale || settings?.AppleLanguages?.[0] || "en").toLowerCase();
  }
  const cfg = (NativeModules as any)?.I18nManager?.localeIdentifier;
  return String(cfg || "en").toLowerCase();
}

function pickCurrencyForLocale(locale: string) {
  const norm = locale.toLowerCase();
  // Try exact "en-gb" style match first, then just the language prefix "id".
  if (LOCALE_TO_CURRENCY[norm]) return LOCALE_TO_CURRENCY[norm];
  const prefix = norm.split("-")[0];
  return LOCALE_TO_CURRENCY[prefix] || null;
}

// v8.4.1 — App-language → currency override.  The in-app language switcher
// (top-right "EN/ID/RU/CN" pill) is the authoritative signal of what
// currency the user "thinks" in.  If they picked "ID" they want to see Rp
// even if the OS/browser reports en-US (very common on web preview and on
// devices sold worldwide with English UI defaults).  When the user is on
// "EN" we fall back to the device locale so that a British user still sees
// GBP, an Australian user AUD, and a US user just plain USD.
const APP_LANG_TO_CURRENCY: Record<Exclude<Lang, "en">, keyof typeof LOCALE_TO_CURRENCY> = {
  id: "id",
  ru: "ru",
  cn: "zh",
};

function pickCurrencyForApp(appLang: Lang) {
  if (appLang !== "en") {
    const localeKey = APP_LANG_TO_CURRENCY[appLang];
    if (localeKey && LOCALE_TO_CURRENCY[localeKey]) return LOCALE_TO_CURRENCY[localeKey];
  }
  // English users → follow device locale (en-GB → GBP, en-US → hide, ...).
  return pickCurrencyForLocale(detectDeviceLocale());
}

async function fetchRateWithCache(currencyCode: string): Promise<number | null> {
  const key = `${STORAGE_KEY}:${currencyCode}`;
  try {
    const cached = await AsyncStorage.getItem(key);
    if (cached) {
      const parsed = JSON.parse(cached);
      if (parsed?.rate && Date.now() - parsed.at < CACHE_TTL_MS) {
        return Number(parsed.rate);
      }
    }
  } catch {
    /* ignore */
  }
  // v8.4.0 — Provider chain: `open.er-api.com` is our primary (free, no
  // API key, ECB + market composite). Frankfurter is a fallback if the
  // primary is temporarily down. Both return USD-quoted rates.
  const providers: (() => Promise<number | null>)[] = [
    async () => {
      const r = await fetch(`https://open.er-api.com/v6/latest/USD`);
      if (!r.ok) return null;
      const data = await r.json();
      const val = Number(data?.rates?.[currencyCode]);
      return Number.isFinite(val) && val > 0 ? val : null;
    },
    async () => {
      const r = await fetch(
        `https://api.frankfurter.app/latest?from=USD&to=${currencyCode}`,
        { redirect: "follow" },
      );
      if (!r.ok) return null;
      const data = await r.json();
      const val = Number(data?.rates?.[currencyCode]);
      return Number.isFinite(val) && val > 0 ? val : null;
    },
  ];
  for (const p of providers) {
    try {
      const rate = await p();
      if (rate) {
        await AsyncStorage.setItem(key, JSON.stringify({ rate, at: Date.now() }));
        return rate;
      }
    } catch {
      /* try next provider */
    }
  }
  return null;
}

function formatRate(n: number): string {
  // Rp 15,850 (0-2 decimals for high-value currencies) vs 0.83 EUR (2 decimals).
  if (n >= 100) {
    return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  if (n >= 10) {
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

// v8.4.0 — Hook exposing the current USDT ↔ local-currency rate to any
// component. Returns `null` for USD locales or when the network is
// unreachable and no cache exists. Consumers (e.g. the crypto card in
// index.tsx) use this to render stablecoin prices in the user's local
// currency instead of dollars.
export type LocalRateInfo = {
  rate: number;
  currency: NonNullable<ReturnType<typeof pickCurrencyForLocale>>;
};

export function useUsdtLocalRate(): LocalRateInfo | null {
  const { lang } = useI18n();
  const [rate, setRate] = useState<number | null>(null);
  const currency = pickCurrencyForApp(lang);
  useEffect(() => {
    if (!currency) return;
    let cancelled = false;
    (async () => {
      const r = await fetchRateWithCache(currency.code);
      if (!cancelled) setRate(r);
    })();
    return () => {
      cancelled = true;
    };
  }, [currency?.code]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!currency || currency.code === "USD" || !rate) return null;
  return { rate, currency };
}

// v8.4.0 — Format a USD-quoted stablecoin price into the user's local
// currency. Falls back to the default `formatPrice` output when no local
// rate is available (returns null for the caller to handle).
export function formatStablecoinLocal(priceUsd: number, info: LocalRateInfo | null): string | null {
  if (!info || !Number.isFinite(priceUsd)) return null;
  const local = priceUsd * info.rate;
  return `${info.currency.symbol} ${formatRate(local)}`;
}

// Common USD-pegged stablecoins whose price users expect to see in local
// currency terms ("how much is 1 USDT in Rupiah?").
export const STABLECOIN_SYMBOLS = new Set([
  "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDS",
]);

export default function UsdtLocalRateStrip() {
  const { colors } = useTheme();
  const { lang } = useI18n();
  const [rate, setRate] = useState<number | null>(null);
  const currency = pickCurrencyForApp(lang);

  useEffect(() => {
    if (!currency) return;
    let cancelled = false;
    (async () => {
      const r = await fetchRateWithCache(currency.code);
      if (!cancelled) setRate(r);
    })();
    return () => {
      cancelled = true;
    };
  }, [currency?.code]); // eslint-disable-line react-hooks/exhaustive-deps

  // Hide widget silently for USD locales or unsupported cases.
  if (!currency || currency.code === "USD" || !rate) return null;

  return (
    <View
      testID="usdt-local-rate"
      style={[
        styles.strip,
        { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      <Ionicons name="cash-outline" size={13} color={colors.accentUp} />
      <Text style={[styles.text, { color: colors.textPrimary }]} numberOfLines={1}>
        <Text style={{ color: colors.textMuted }}>1 USDT ≈ </Text>
        <Text style={{ fontWeight: "900", color: colors.accentUp }}>
          {currency.symbol} {formatRate(rate)}
        </Text>
        <Text style={{ color: colors.textMuted }}>
          {"  "}
          {currency.flag} {currency.code}
        </Text>
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 5,
    marginHorizontal: 12,
    marginTop: 6,
  },
  text: { fontSize: 11.5, fontVariant: ["tabular-nums"] },
});
