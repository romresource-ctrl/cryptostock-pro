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

// v8.6.5 — Legacy helpers removed. We used to compute device-currency &
// app-lang overrides, but the calculator now uses USDT globally except
// for IDX Stocks (see getQuoteInfo below).
//
// Cheap in-memory memo — kept in case future features re-introduce
// device-currency detection.
let _cachedDeviceInfo: QuoteInfo | null = null;
void _cachedDeviceInfo;

function metaFor(code: string): QuoteInfo {
  const upper = code.toUpperCase();
  const meta = CODE_META[upper];
  if (meta) return { code: upper, symbol: meta.symbol, flag: meta.flag };
  // Unknown code — still use the ISO 4217 short as both code & symbol so
  // callers never render "undefined".
  return { code: upper, symbol: upper, flag: "" };
}

/**
 * Pick the correct quote label for a given market and app language.
 *
 * v8.6.5 — Simplified per user requirement: global trading platforms
 * quote in USDT regardless of user language. Only Indonesia Stock
 * Exchange (`stock_id`) prices are in Rupiah because that's how they
 * appear on IDX. Language pill no longer overrides the quote — a
 * Chinese-speaking user still sees "USDT" for Bitcoin, not "CNY".
 *
 * Rules:
 *   1. `stock_id` → IDR (Jakarta exchange native currency).
 *   2. Every other market (crypto, world_stocks, stock_us, etf,
 *      gold_silver, commodity, forex) → USDT.
 */
export function getQuoteInfo(
  market: string,
  _appLang: Lang, // kept for API compatibility; no longer read
): QuoteInfo {
  if (market === "stock_id") return metaFor("IDR");
  return { code: "USDT", symbol: "$", flag: "" };
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
