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
  login: { id: "LOGIN", en: "LOGIN" },
  logged: { id: "LOGGED", en: "LOGGED" },
  // Asset detail
  detail_signal: { id: "Sinyal Teknikal", en: "Technical Signal" },
  detail_confidence: { id: "Confidence AI", en: "AI Confidence" },
  detail_entry: { id: "ENTRY", en: "ENTRY" },
  detail_stop: { id: "STOP LOSS", en: "STOP LOSS" },
  detail_tp: { id: "TAKE PROFIT", en: "TAKE PROFIT" },
  detail_ai_entry: { id: "AI ENTRY", en: "AI ENTRY" },
  detail_ai_sl: { id: "AI SL", en: "AI SL" },
  detail_ai_tp: { id: "AI TP", en: "AI TP" },
  detail_indicators: { id: "Indikator Teknikal", en: "Technical Indicators" },
  detail_reasons: { id: "Alasan", en: "Reasons" },
  detail_ai_btn: { id: "ANALISA AI", en: "AI ANALYSIS" },
  detail_ai_repeat: { id: "ULANGI", en: "RUN AGAIN" },
  detail_ai_running: { id: "MENGANALISA…", en: "ANALYZING…" },
  detail_ai_section: { id: "Multi-AI Ensemble", en: "Multi-AI Ensemble" },
  detail_ai_hint: {
    id: "Tekan ANALISA AI untuk konsensus Claude Sonnet 4.6 + GPT-5.2 + Gemini 3.1 Pro berdasarkan teknikal, berita global, makro & politik terkini.",
    en: "Press AI ANALYSIS to get a consensus from Claude Sonnet 4.6 + GPT-5.2 + Gemini 3.1 Pro based on technicals, global news, macro & latest politics.",
  },
  detail_consensus: { id: "KONSENSUS AI", en: "AI CONSENSUS" },
  detail_models: { id: "Detail Model", en: "Model Details" },
  detail_news: { id: "Berita Terkait", en: "Related News" },
  detail_track_record: { id: "Track Record", en: "Track Record" },
  detail_historic_signals: { id: "sinyal historis", en: "historic signals" },
  detail_wr_7d: { id: "WIN RATE 7D", en: "WIN RATE 7D" },
  detail_wr_30d: { id: "WIN RATE 30D", en: "WIN RATE 30D" },
  detail_wr_all: { id: "ALL TIME", en: "ALL TIME" },
  detail_recent_signals: { id: "Sinyal Terakhir", en: "Recent Signals" },
  detail_news_factors: { id: "📰 Faktor Berita & Makro", en: "📰 News & Macro Factors" },
  detail_risk: { id: "⚠️ Risiko", en: "⚠️ Risk Factors" },
  detail_news_live: { id: "📡 Berita Live yang Digunakan", en: "📡 Live News Used" },
  detail_generated_at: { id: "Dianalisa", en: "Analyzed" },
  // Market badges
  badge_crypto: { id: "CRYPTO", en: "CRYPTO" },
  badge_etf: { id: "ETF", en: "ETF" },
  badge_stock_id: { id: "SAHAM IDX", en: "IDX STOCK" },
  badge_stock_us: { id: "SAHAM US", en: "US STOCK" },
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
