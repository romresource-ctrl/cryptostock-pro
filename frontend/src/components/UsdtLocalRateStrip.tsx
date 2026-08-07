/**
 * UsdtLocalRateStrip — live-FX helper for stablecoin display.
 *
 * v8.4.2 (rewrite):
 *   • Locale is detected with `expo-localization` (region code from device).
 *   • App-language override (ID / RU / CN from the top-right pill) takes
 *     precedence — English users fall back to their device region.
 *   • Rates come from https://open.er-api.com/v6/latest/USD (free, no key).
 *     Cached in AsyncStorage for 6 hours to keep the widget "live" without
 *     hammering the endpoint on every mount.
 *   • Numbers are formatted MANUALLY (no Intl / no toLocaleString) because
 *     "USDT" is not an ISO currency code — Intl.NumberFormat would throw.
 *
 * Public surface:
 *   • <UsdtLocalRateStrip />           — dashboard header widget.
 *   • useUsdtLocalRate()               — hook returning current rate info.
 *   • formatStablecoinLocal(price, i)  — helper to render "Rp 15,850".
 *   • STABLECOIN_SYMBOLS               — set of USD-pegged tickers.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import * as Localization from "expo-localization";
import React, { useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useI18n, type Lang } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

// ---------------------------------------------------------------------------
// Currency catalogue.  Keyed by ISO region (US, ID, JP, …) primarily, with
// a language-code alias table for common locales that don't map 1:1.
// ---------------------------------------------------------------------------
type CurrencyInfo = { code: string; symbol: string; flag: string; name: string };

const REGION_TO_CURRENCY: Record<string, CurrencyInfo> = {
  ID: { code: "IDR", symbol: "Rp", flag: "🇮🇩", name: "Rupiah" },
  JP: { code: "JPY", symbol: "¥", flag: "🇯🇵", name: "Yen" },
  KR: { code: "KRW", symbol: "₩", flag: "🇰🇷", name: "Won" },
  CN: { code: "CNY", symbol: "¥", flag: "🇨🇳", name: "Yuan" },
  TW: { code: "TWD", symbol: "NT$", flag: "🇹🇼", name: "TWD" },
  HK: { code: "HKD", symbol: "HK$", flag: "🇭🇰", name: "HKD" },
  TH: { code: "THB", symbol: "฿", flag: "🇹🇭", name: "Baht" },
  VN: { code: "VND", symbol: "₫", flag: "🇻🇳", name: "Dong" },
  MY: { code: "MYR", symbol: "RM", flag: "🇲🇾", name: "Ringgit" },
  SG: { code: "SGD", symbol: "S$", flag: "🇸🇬", name: "SGD" },
  PH: { code: "PHP", symbol: "₱", flag: "🇵🇭", name: "Peso" },
  IN: { code: "INR", symbol: "₹", flag: "🇮🇳", name: "Rupee" },
  AE: { code: "AED", symbol: "د.إ", flag: "🇦🇪", name: "Dirham" },
  SA: { code: "SAR", symbol: "﷼", flag: "🇸🇦", name: "Riyal" },
  RU: { code: "RUB", symbol: "₽", flag: "🇷🇺", name: "Ruble" },
  UA: { code: "UAH", symbol: "₴", flag: "🇺🇦", name: "Hryvnia" },
  TR: { code: "TRY", symbol: "₺", flag: "🇹🇷", name: "Lira" },
  BR: { code: "BRL", symbol: "R$", flag: "🇧🇷", name: "Real" },
  MX: { code: "MXN", symbol: "MX$", flag: "🇲🇽", name: "Peso" },
  AR: { code: "ARS", symbol: "AR$", flag: "🇦🇷", name: "Peso" },
  GB: { code: "GBP", symbol: "£", flag: "🇬🇧", name: "Pound" },
  AU: { code: "AUD", symbol: "A$", flag: "🇦🇺", name: "AUD" },
  CA: { code: "CAD", symbol: "C$", flag: "🇨🇦", name: "CAD" },
  NZ: { code: "NZD", symbol: "NZ$", flag: "🇳🇿", name: "NZD" },
  ZA: { code: "ZAR", symbol: "R", flag: "🇿🇦", name: "Rand" },
  PL: { code: "PLN", symbol: "zł", flag: "🇵🇱", name: "Złoty" },
  SE: { code: "SEK", symbol: "kr", flag: "🇸🇪", name: "Krona" },
  NO: { code: "NOK", symbol: "kr", flag: "🇳🇴", name: "Krone" },
  DK: { code: "DKK", symbol: "kr", flag: "🇩🇰", name: "Krone" },
  CH: { code: "CHF", symbol: "Fr", flag: "🇨🇭", name: "Franc" },
  // Eurozone regions all resolve to EUR — kept as separate entries so the
  // flag emoji matches the user's country.
  DE: { code: "EUR", symbol: "€", flag: "🇩🇪", name: "Euro" },
  FR: { code: "EUR", symbol: "€", flag: "🇫🇷", name: "Euro" },
  IT: { code: "EUR", symbol: "€", flag: "🇮🇹", name: "Euro" },
  ES: { code: "EUR", symbol: "€", flag: "🇪🇸", name: "Euro" },
  NL: { code: "EUR", symbol: "€", flag: "🇳🇱", name: "Euro" },
  PT: { code: "EUR", symbol: "€", flag: "🇵🇹", name: "Euro" },
  IE: { code: "EUR", symbol: "€", flag: "🇮🇪", name: "Euro" },
  AT: { code: "EUR", symbol: "€", flag: "🇦🇹", name: "Euro" },
  FI: { code: "EUR", symbol: "€", flag: "🇫🇮", name: "Euro" },
  BE: { code: "EUR", symbol: "€", flag: "🇧🇪", name: "Euro" },
  GR: { code: "EUR", symbol: "€", flag: "🇬🇷", name: "Euro" },
  // US = USD; we deliberately keep an entry so callers can still get the
  // flag/name for hover tooltips even though the widget itself hides.
  US: { code: "USD", symbol: "$", flag: "🇺🇸", name: "Dollar" },
};

// App-language pill override → force a specific currency regardless of the
// device region.  Very common on web preview / dev builds where the browser
// reports `en-US` even though the user is clearly Indonesian / Russian /
// Chinese.  "en" is intentionally missing — English users get their real
// device region instead.
const APP_LANG_TO_REGION: Record<Exclude<Lang, "en">, string> = {
  id: "ID",
  ru: "RU",
  cn: "CN",
};

// ---------------------------------------------------------------------------
// Locale detection via expo-localization.  On native this reads the OS
// setting directly; on web it uses `navigator.language`.  We prefer the
// `regionCode` (country) but fall back to parsing the BCP-47 tag.
// ---------------------------------------------------------------------------
function detectRegion(): string {
  try {
    const locales = Localization.getLocales();
    if (locales && locales.length > 0) {
      const first = locales[0];
      if (first.regionCode) return String(first.regionCode).toUpperCase();
      if (first.languageTag) {
        const parts = first.languageTag.split("-");
        if (parts.length > 1) return parts[1].toUpperCase();
      }
    }
  } catch {
    /* expo-localization may not be ready during first render */
  }
  return "US";
}

function pickCurrencyForApp(appLang: Lang): CurrencyInfo | null {
  if (appLang !== "en") {
    const region = APP_LANG_TO_REGION[appLang];
    if (region && REGION_TO_CURRENCY[region]) return REGION_TO_CURRENCY[region];
  }
  const region = detectRegion();
  return REGION_TO_CURRENCY[region] || null;
}

// ---------------------------------------------------------------------------
// Rate fetching with 6-hour AsyncStorage cache.  open.er-api.com is our
// primary source (ECB + FX market composite, no API key).  Frankfurter
// remains as a soft fallback if the primary is temporarily 5xx.
// ---------------------------------------------------------------------------
const CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const STORAGE_KEY = "fx:usdt_local";

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

// ---------------------------------------------------------------------------
// Manual number formatter — deliberately avoids Intl / toLocaleString so
// that we don't accidentally try to format "USDT" (not an ISO currency).
// Produces "17,948" / "1,234.56" / "0.8321" depending on magnitude.
// ---------------------------------------------------------------------------
export function formatNumberManual(n: number): string {
  if (!Number.isFinite(n)) return "0";
  const abs = Math.abs(n);
  let raw: string;
  if (abs >= 100) raw = Math.round(n).toString();
  else if (abs >= 10) raw = n.toFixed(2);
  else if (abs >= 1) raw = n.toFixed(3);
  else raw = n.toFixed(4);

  const negative = raw.startsWith("-");
  const unsigned = negative ? raw.slice(1) : raw;
  const [intPart, decPart] = unsigned.split(".");
  // Insert commas as thousand separators, right-to-left.
  let grouped = "";
  for (let i = 0; i < intPart.length; i++) {
    if (i > 0 && (intPart.length - i) % 3 === 0) grouped += ",";
    grouped += intPart[i];
  }
  return (negative ? "-" : "") + grouped + (decPart ? "." + decPart : "");
}

// ---------------------------------------------------------------------------
// Public hook / helpers.
// ---------------------------------------------------------------------------
export type LocalRateInfo = { rate: number; currency: CurrencyInfo };

export function useUsdtLocalRate(): LocalRateInfo | null {
  const { lang } = useI18n();
  const currency = useMemo(() => pickCurrencyForApp(lang), [lang]);
  const [rate, setRate] = useState<number | null>(null);

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

// Format a USD-quoted stablecoin price in the user's local currency, e.g.
// `formatStablecoinLocal(1.001, {rate: 17948, currency})` → "Rp 17,966".
// Returns null when no local rate is available so the caller can fall back
// to the original USD price string.
export function formatStablecoinLocal(priceUsd: number, info: LocalRateInfo | null): string | null {
  if (!info || !Number.isFinite(priceUsd)) return null;
  return `${info.currency.symbol} ${formatNumberManual(priceUsd * info.rate)}`;
}

// Common USD-pegged stablecoins whose price users expect to see in local
// currency terms.
export const STABLECOIN_SYMBOLS = new Set([
  "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDS",
]);

// ---------------------------------------------------------------------------
// The dashboard header widget itself — "1 USDT ≈ Rp 17,948 🇮🇩 IDR".
// Formatted manually so "USDT" is plain text, not a currency code.
// ---------------------------------------------------------------------------
export default function UsdtLocalRateStrip() {
  const { colors } = useTheme();
  const info = useUsdtLocalRate();

  if (!info) return null;

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
          {info.currency.symbol} {formatNumberManual(info.rate)}
        </Text>
        <Text style={{ color: colors.textMuted }}>
          {"  "}
          {info.currency.flag} {info.currency.code}
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
