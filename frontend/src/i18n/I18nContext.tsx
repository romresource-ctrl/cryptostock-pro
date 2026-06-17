import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "id" | "en";

const STORAGE_KEY = "kevinaipro:lang";

// Static UI translations. Keys map to Indonesian (default) strings; English
// strings are written here too. Dynamic content (news, AI analysis) is
// translated server-side via /api/translate (cached in MongoDB).
const STRINGS: Record<string, { id: string; en: string }> = {
  app_title: { id: "CryptoStock", en: "CryptoStock" },
  app_sub_loading: { id: "memuat…", en: "loading…" },
  ver_label: { id: "Ver", en: "Ver" },
  // Header / navigation
  premium: { id: "PREMIUM", en: "PREMIUM" },
  premium_label: { id: "PREMIUM", en: "PREMIUM" },
  buy_long: { id: "BUY/LONG", en: "BUY/LONG" },
  hold: { id: "HOLD", en: "HOLD" },
  sell_short: { id: "SELL/SHORT", en: "SELL/SHORT" },
  asset: { id: "aset", en: "asset" },
  assets: { id: "aset", en: "assets" },
  category_crypto: { id: "Crypto", en: "Crypto" },
  category_etf: { id: "ETF", en: "ETF" },
  category_stock_id: { id: "Saham IDX", en: "IDX Stocks" },
  category_stock_us: { id: "Saham US", en: "US Stocks" },
  // VipModal
  vip_title: { id: "Fitur Khusus Member VIP", en: "VIP Members Only Features" },
  vip_body: {
    id: "LOGIN atau jadi Member untuk lihat insight Premium eksklusif dan Sinyal AI yang akurat.",
    en: "LOGIN or Become Member to view exclusive Premium insights and accurate AI Signals.",
  },
  vip_contact_label: { id: "Hubungi kami untuk membuka:", en: "Contact us to unlock:" },
  vip_login_btn: { id: "SUDAH PUNYA CODE? LOGIN", en: "ALREADY HAVE CODE? LOGIN" },
  // Login modal
  login_title: { id: "Masukkan Unlock Code", en: "Enter Unlock Code" },
  login_email: { id: "Email", en: "Email" },
  login_code: { id: "Unlock Code", en: "Unlock Code" },
  login_submit: { id: "UNLOCK", en: "UNLOCK" },
  login_invalid: { id: "Email atau code salah", en: "Invalid email or code" },
  // Asset detail
  detail_signal: { id: "Sinyal", en: "Signal" },
  detail_confidence: { id: "Confidence AI", en: "AI Confidence" },
  detail_entry: { id: "Entry", en: "Entry" },
  detail_stop: { id: "Stop Loss", en: "Stop Loss" },
  detail_tp: { id: "Take Profit", en: "Take Profit" },
  detail_indicators: { id: "Indikator Teknikal", en: "Technical Indicators" },
  detail_reasons: { id: "Alasan", en: "Reasons" },
  detail_ai_btn: { id: "ANALISA AI", en: "AI ANALYSIS" },
  detail_ai_running: { id: "MENGANALISA…", en: "ANALYZING…" },
  detail_consensus: { id: "Konsensus AI", en: "AI Consensus" },
  detail_models: { id: "Detail Model", en: "Model Details" },
  detail_news: { id: "Berita Terkait", en: "Related News" },
  detail_track_record: { id: "Track Record", en: "Track Record" },
  // News page
  news_title: { id: "Berita", en: "News" },
  news_all: { id: "SEMUA", en: "ALL" },
  news_empty: { id: "Belum ada berita.", en: "No news yet." },
  // Common
  retry: { id: "Coba lagi", en: "Retry" },
  loading: { id: "Memuat…", en: "Loading…" },
  back: { id: "Kembali", en: "Back" },
  close: { id: "Tutup", en: "Close" },
};

type Ctx = {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggle: () => void;
  t: (key: keyof typeof STRINGS | string) => string;
  ready: boolean;
};

const I18nContext = createContext<Ctx | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("id");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((v) => {
        if (v === "en" || v === "id") setLangState(v);
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    AsyncStorage.setItem(STORAGE_KEY, l).catch(() => {});
  }, []);

  const toggle = useCallback(() => setLang(lang === "id" ? "en" : "id"), [lang, setLang]);

  const t = useCallback(
    (key: string): string => {
      const entry = (STRINGS as Record<string, { id: string; en: string }>)[key];
      if (!entry) return key;
      return entry[lang] ?? entry.id;
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, toggle, t, ready }), [lang, setLang, toggle, t, ready]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}
