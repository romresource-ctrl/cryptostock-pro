/**
 * locale-quote.ts — auto-detect the user's local quote currency for the
 * Position Size Calculator and other places that previously hard-coded
 * "USDT" / "USD" / "IDR".
 *
 * Uses `expo-localization.getLocales()` (native + web supported) to read
 * the device's region-provided `currencyCode`, then maps it to a symbol
 * + display label.  Falls back to `USD` when the OS can't provide one
 * (e.g. Playwright headless with a stripped locale).
 *
 * The app-language pill (ID / RU / CN in the header) still takes priority
 * for the three known translation markets — a user who explicitly picks
 * Indonesian on an English device clearly wants Rupiah, not Dollars.
 */
import * as Localization from "expo-localization";

import type { Lang } from "@/src/i18n/I18nContext";

export type QuoteInfo = {
  /** ISO 4217 currency code, e.g. "IDR", "USD", "EUR". Shown as text next to numbers. */
  code: string;
  /** Currency glyph. "Rp" / "$" / "€" / "¥". */
  symbol: string;
  /** Flag emoji for tooltips. */
  flag: string;
};

const FALLBACK: QuoteInfo = { code: "USD", symbol: "$", flag: "🇺🇸" };

// Common region → symbol/flag map.  We don't try to be complete — the
// ISO 4217 code is enough for the label; the symbol is only cosmetic.
const CODE_META: Record<string, { symbol: string; flag: string }> = {
  USD: { symbol: "$", flag: "🇺🇸" },
  IDR: { symbol: "Rp", flag: "🇮🇩" },
  EUR: { symbol: "€", flag: "🇪🇺" },
  GBP: { symbol: "£", flag: "🇬🇧" },
  JPY: { symbol: "¥", flag: "🇯🇵" },
  CNY: { symbol: "¥", flag: "🇨🇳" },
  KRW: { symbol: "₩", flag: "🇰🇷" },
  TWD: { symbol: "NT$", flag: "🇹🇼" },
  HKD: { symbol: "HK$", flag: "🇭🇰" },
  SGD: { symbol: "S$", flag: "🇸🇬" },
  MYR: { symbol: "RM", flag: "🇲🇾" },
  THB: { symbol: "฿", flag: "🇹🇭" },
  VND: { symbol: "₫", flag: "🇻🇳" },
  PHP: { symbol: "₱", flag: "🇵🇭" },
  INR: { symbol: "₹", flag: "🇮🇳" },
  AUD: { symbol: "A$", flag: "🇦🇺" },
  CAD: { symbol: "C$", flag: "🇨🇦" },
  NZD: { symbol: "NZ$", flag: "🇳🇿" },
  ZAR: { symbol: "R", flag: "🇿🇦" },
  RUB: { symbol: "₽", flag: "🇷🇺" },
  UAH: { symbol: "₴", flag: "🇺🇦" },
  TRY: { symbol: "₺", flag: "🇹🇷" },
  BRL: { symbol: "R$", flag: "🇧🇷" },
  MXN: { symbol: "MX$", flag: "🇲🇽" },
  ARS: { symbol: "AR$", flag: "🇦🇷" },
  CHF: { symbol: "Fr", flag: "🇨🇭" },
  SEK: { symbol: "kr", flag: "🇸🇪" },
  NOK: { symbol: "kr", flag: "🇳🇴" },
  DKK: { symbol: "kr", flag: "🇩🇰" },
  PLN: { symbol: "zł", flag: "🇵🇱" },
  AED: { symbol: "د.إ", flag: "🇦🇪" },
  SAR: { symbol: "﷼", flag: "🇸🇦" },
};

// App-language override → force a specific currency regardless of the
// device region.  Common on web preview / dev builds where the browser
// reports en-US even though the user is clearly Indonesian / Russian /
// Chinese.  "en" is intentionally missing — English users get their real
// device region so a British player still sees GBP, a French user EUR.
const APP_LANG_TO_CODE: Record<Exclude<Lang, "en">, string> = {
  id: "IDR",
  ru: "RUB",
  cn: "CNY",
};

// Cheap in-memory memo so we're not calling getLocales() on every render.
let _cachedDeviceInfo: QuoteInfo | null = null;

function metaFor(code: string): QuoteInfo {
  const upper = code.toUpperCase();
  const meta = CODE_META[upper];
  if (meta) return { code: upper, symbol: meta.symbol, flag: meta.flag };
  // Unknown code — still use the ISO 4217 short as both code & symbol so
  // callers never render "undefined".
  return { code: upper, symbol: upper, flag: "" };
}

function readDeviceQuote(): QuoteInfo {
  if (_cachedDeviceInfo) return _cachedDeviceInfo;
  try {
    const locales = Localization.getLocales();
    if (locales && locales.length > 0) {
      const first = locales[0];
      // `currencyCode` is the ISO 4217 the OS/browser associates with the
      // primary locale — exactly what we want for the quote label.
      if (first.currencyCode) {
        _cachedDeviceInfo = metaFor(String(first.currencyCode));
        return _cachedDeviceInfo;
      }
      // As a secondary, use `currencySymbol` when currencyCode is missing
      // (some older browsers).  We can't derive an ISO code from a bare
      // symbol so we default to USD but keep whatever symbol the OS gave.
      if (first.currencySymbol) {
        _cachedDeviceInfo = { ...FALLBACK, symbol: first.currencySymbol };
        return _cachedDeviceInfo;
      }
    }
  } catch {
    /* fallthrough to USD */
  }
  _cachedDeviceInfo = FALLBACK;
  return _cachedDeviceInfo;
}

/**
 * Pick the correct quote label for a given market and app language.
 *
 * Rules (in priority order):
 *   1. `stock_id` → always IDR (the exchange is Jakarta).
 *   2. App language pill (id / ru / cn) → force IDR / RUB / CNY so the
 *      user's explicit choice always beats a mis-detected device region.
 *   3. Device locale via expo-localization (`currencyCode`).
 *   4. USD fallback.
 */
export function getQuoteInfo(
  market: string,
  appLang: Lang,
): QuoteInfo {
  if (market === "stock_id") return metaFor("IDR");
  if (appLang !== "en" && APP_LANG_TO_CODE[appLang]) {
    return metaFor(APP_LANG_TO_CODE[appLang]);
  }
  return readDeviceQuote();
}

/**
 * String helper used by the two `<PositionSizeCalculator quoteLabel={...} />`
 * call-sites at app/asset/[market]/[symbol].tsx.  Returns just the ISO
 * code (e.g. "IDR"), because the calculator renders it after the money
 * amount ("15,000,000 IDR").
 */
export function getQuoteLabel(market: string, appLang: Lang): string {
  return getQuoteInfo(market, appLang).code;
}
