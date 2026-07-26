import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "id" | "en" | "ru" | "cn";

const STORAGE_KEY = "aicryptostockpro:lang";
export const LANG_ORDER: Lang[] = ["en", "id", "ru", "cn"];
export const LANG_LABEL: Record<Lang, string> = { id: "ID", en: "EN", ru: "RU", cn: "CN" };

// Static UI translations. Dynamic content (news, AI analysis, asset detail
// long-form text) is translated at request time via /api/translate.
const STRINGS: Record<string, { id: string; en: string; ru: string; cn: string }> = {
  app_title: { id: "AI Crypto Stock Pro", en: "AI Crypto Stock Pro", ru: "AI Crypto Stock Pro", cn: "AI Crypto Stock Pro" },
  app_sub_loading: { id: "memuat…", en: "loading…", ru: "загрузка…", cn: "加载中…" },
  ver_label: { id: "Ver", en: "Ver", ru: "Вер", cn: "版本" },
  premium: { id: "PREMIUM", en: "PREMIUM", ru: "ПРЕМИУМ", cn: "高级" },
  premium_label: { id: "PREMIUM", en: "PREMIUM", ru: "ПРЕМИУМ", cn: "高级" },
  buy_long: { id: "BUY/LONG", en: "BUY/LONG", ru: "ПОКУПКА/ЛОНГ", cn: "买入/多头" },
  hold: { id: "HOLD", en: "HOLD", ru: "ДЕРЖАТЬ", cn: "持有" },
  sell_short: { id: "SELL/SHORT", en: "SELL/SHORT", ru: "ПРОДАЖА/ШОРТ", cn: "卖出/空头" },
  asset: { id: "aset", en: "asset", ru: "актив", cn: "资产" },
  assets: { id: "aset", en: "assets", ru: "активов", cn: "资产" },

  // Categories
  category_crypto: { id: "Crypto", en: "Crypto", ru: "Крипто", cn: "加密" },
  category_etf: { id: "ETF", en: "ETF", ru: "ETF", cn: "ETF" },
  category_stock_id: { id: "Saham IDX", en: "IDX Stocks", ru: "Акции IDX", cn: "IDX 股票" },
  category_stock_us: { id: "World Stocks", en: "World Stocks", ru: "Мировые Акции", cn: "全球股票" },
  category_world_stocks: { id: "World Stocks", en: "World Stocks", ru: "Мировые Акции", cn: "全球股票" },
  category_gold_silver: { id: "Gold/Silver", en: "Gold/Silver", ru: "Золото/Серебро", cn: "黄金/白银" },
  category_commodity: { id: "Commodities", en: "Commodities", ru: "Сырьё", cn: "大宗商品" },
  category_forex: { id: "Forex", en: "Forex", ru: "Форекс", cn: "外汇" },

  // Search bar
  search_placeholder: { id: "Cari simbol aset…", en: "Search asset symbol…", ru: "Поиск символа…", cn: "搜索资产…" },
  search_no_results: { id: "Tidak ada hasil", en: "No results", ru: "Ничего не найдено", cn: "无结果" },

  // Time frame dropdown
  tf_select: { id: "Pilih Time Frame", en: "Select Time Frame", ru: "Выберите ТФ", cn: "选择时间框架" },

  // VipModal / Subscription
  vip_title: { id: "Fitur Khusus Member", en: "Members-Only Feature", ru: "Только для подписчиков", cn: "仅限会员" },
  vip_body: {
    id: "Subscribe atau login sebagai admin untuk lihat detail Sinyal AI eksklusif.",
    en: "Subscribe or log in as admin to view exclusive AI signal details.",
    ru: "Подпишитесь или войдите как админ, чтобы увидеть сигналы AI.",
    cn: "订阅或以管理员身份登录以查看专属 AI 信号详情。",
  },
  vip_contact_label: { id: "Hubungi kami:", en: "Contact us:", ru: "Свяжитесь с нами:", cn: "联系我们：" },
  vip_login_btn: { id: "SUDAH PUNYA CODE? LOGIN", en: "ALREADY HAVE CODE? LOGIN", ru: "УЖЕ ЕСТЬ КОД? ВОЙТИ", cn: "已有代码？登录" },
  vip_subscribe_btn: { id: "SUBSCRIBE $20/BULAN", en: "SUBSCRIBE $20/MONTH", ru: "ПОДПИСАТЬСЯ $20/МЕС", cn: "订阅 $20/月" },
  vip_free_trial: { id: "3 hari gratis, lalu $20/bulan", en: "3 days free, then $20/month", ru: "3 дня бесплатно, затем $20/мес", cn: "免费 3 天，之后 $20/月" },

  // Login modal
  login_modal_title: { id: "Login CryptoStock", en: "Login CryptoStock", ru: "Вход CryptoStock", cn: "登录 CryptoStock" },
  login_modal_body: {
    id: "Login admin/beta tester dengan email dan unlock code.",
    en: "Admin/beta tester login with email and unlock code.",
    ru: "Вход для админа/бета-тестера с email и кодом.",
    cn: "管理员/测试员邮箱和解锁码登录。",
  },
  login_title: { id: "Masukkan Unlock Code", en: "Enter Unlock Code", ru: "Введите код", cn: "输入解锁码" },
  login_email: { id: "Email", en: "Email", ru: "Email", cn: "邮箱" },
  login_code: { id: "Unlock Code", en: "Unlock Code", ru: "Код разблокировки", cn: "解锁码" },
  login_submit: { id: "UNLOCK", en: "UNLOCK", ru: "РАЗБЛОКИРОВАТЬ", cn: "解锁" },
  login_invalid: { id: "Email atau code salah", en: "Invalid email or code", ru: "Неверный email или код", cn: "邮箱或代码错误" },
  login_hint_admin: {
    id: "Belum punya unlock code? Hubungi admin dan berikan email Anda.",
    en: "Don't have an unlock code? Contact admin with your email.",
    ru: "Нет кода? Свяжитесь с админом.",
    cn: "没有解锁码？请联系管理员。",
  },
  login_support_footer: {
    id: "Untuk pertanyaan dan keluhan harap menghubungi SUPPORT, EMAIL: cryptostockapps@gmail.com",
    en: "For questions and complaints please contact SUPPORT, EMAIL: cryptostockapps@gmail.com",
    ru: "Для вопросов и жалоб пишите в SUPPORT, EMAIL: cryptostockapps@gmail.com",
    cn: "咨询与投诉请联系 SUPPORT，邮箱：cryptostockapps@gmail.com",
  },
  login: { id: "LOGIN", en: "LOGIN", ru: "ВОЙТИ", cn: "登录" },
  logged: { id: "LOGGED", en: "LOGGED", ru: "ВХОД", cn: "已登录" },

  // Asset detail
  detail_signal: { id: "Sinyal Teknikal", en: "Technical Signal", ru: "Технич. сигнал", cn: "技术信号" },
  detail_confidence: { id: "Confidence AI", en: "AI Confidence", ru: "Уверенность AI", cn: "AI 置信度" },
  detail_entry: { id: "ENTRY", en: "ENTRY", ru: "ВХОД", cn: "入场" },
  detail_stop: { id: "STOP LOSS", en: "STOP LOSS", ru: "СТОП-ЛОСС", cn: "止损" },
  detail_tp: { id: "TAKE PROFIT", en: "TAKE PROFIT", ru: "ТЕЙК-ПРОФИТ", cn: "止盈" },
  detail_ai_entry: { id: "AI ENTRY", en: "AI ENTRY", ru: "AI ВХОД", cn: "AI 入场" },
  detail_ai_sl: { id: "AI SL", en: "AI SL", ru: "AI СЛ", cn: "AI 止损" },
  detail_ai_tp: { id: "AI TP", en: "AI TP", ru: "AI ТП", cn: "AI 止盈" },
  detail_indicators: { id: "Indikator Teknikal", en: "Technical Indicators", ru: "Индикаторы", cn: "技术指标" },
  detail_reasons: { id: "Alasan", en: "Reasons", ru: "Причины", cn: "原因" },
  detail_ai_btn: { id: "ANALISA", en: "ANALYZE", ru: "АНАЛИЗ", cn: "分析" },
  detail_ai_predict_btn: { id: "PREDIKSI", en: "PREDICT", ru: "ПРОГНОЗ", cn: "预测" },
  detail_target_profit: { id: "Target Profit", en: "Target Profit", ru: "Целевая прибыль", cn: "目标利润" },
  detail_ai_repeat: { id: "ULANGI", en: "RUN AGAIN", ru: "ЗАПУСТИТЬ", cn: "重新运行" },
  detail_ai_running: { id: "MENGANALISA…", en: "ANALYZING…", ru: "АНАЛИЗ…", cn: "分析中…" },
  detail_ai_section: { id: "Multi-AI Ensemble", en: "Multi-AI Ensemble", ru: "Multi-AI Ансамбль", cn: "多 AI 集成" },
  detail_ai_hint: {
    id: "Tekan ANALISA AI untuk konsensus Claude Fable 5 + Opus 4.8 + Sonnet 4.6 berdasarkan teknikal, berita global, makro & politik terkini.",
    en: "Press AI ANALYSIS for consensus from Claude Fable 5 + Opus 4.8 + Sonnet 4.6 based on technicals, global news, macro & politics.",
    ru: "Нажмите AI АНАЛИЗ для консенсуса Claude Fable 5 + Opus 4.8 + Sonnet 4.6 по техническому анализу и макро.",
    cn: "点击 AI 分析获取 Claude Fable 5 + Opus 4.8 + Sonnet 4.6 基于技术面、宏观和政治的共识。",
  },
  // Dynamic template — `{models}` is replaced at runtime with the current
  // AI model labels fetched from GET /api/ai/models so the hint text
  // never becomes stale when the backend upgrades to a newer Claude / GPT
  // / Gemini version.
  detail_ai_hint_template: {
    id: "Tekan ANALISA AI untuk konsensus {models} berdasarkan teknikal, berita global, makro & politik terkini.",
    en: "Press AI ANALYSIS for consensus from {models} based on technicals, global news, macro & politics.",
    ru: "Нажмите AI АНАЛИЗ для консенсуса {models} по техническому анализу и макро.",
    cn: "点击 AI 分析获取 {models} 基于技术面、宏观和政治的共识。",
  },
  detail_consensus: { id: "KONSENSUS AI", en: "AI CONSENSUS", ru: "AI КОНСЕНСУС", cn: "AI 共识" },
  detail_models: { id: "Detail Model", en: "Model Details", ru: "Детали моделей", cn: "模型详情" },
  detail_news: { id: "Berita Terkait", en: "Related News", ru: "Новости", cn: "相关新闻" },
  detail_track_record: { id: "Track Record", en: "Track Record", ru: "История", cn: "历史记录" },
  detail_historic_signals: { id: "sinyal historis", en: "historic signals", ru: "историч. сигналов", cn: "历史信号" },
  detail_wr_7d: { id: "WIN RATE 7D", en: "WIN RATE 7D", ru: "WR 7Д", cn: "7天胜率" },
  detail_wr_30d: { id: "WIN RATE 30D", en: "WIN RATE 30D", ru: "WR 30Д", cn: "30天胜率" },
  detail_wr_all: { id: "ALL TIME", en: "ALL TIME", ru: "ВСЁ ВРЕМЯ", cn: "全部" },
  detail_recent_signals: { id: "Sinyal Terakhir", en: "Recent Signals", ru: "Последние сигналы", cn: "最近信号" },
  detail_news_factors: { id: "📰 Faktor Berita & Makro", en: "📰 News & Macro Factors", ru: "📰 Новости и Макро", cn: "📰 新闻与宏观" },
  detail_risk: { id: "⚠️ Risiko", en: "⚠️ Risk Factors", ru: "⚠️ Риски", cn: "⚠️ 风险" },
  detail_news_live: { id: "📡 Berita Live yang Digunakan", en: "📡 Live News Used", ru: "📡 Live новости", cn: "📡 使用的实时新闻" },
  detail_generated_at: { id: "Dianalisa", en: "Analyzed", ru: "Проанализировано", cn: "分析时间" },

  // Market badges
  badge_crypto: { id: "CRYPTO", en: "CRYPTO", ru: "КРИПТО", cn: "加密" },
  badge_etf: { id: "ETF", en: "ETF", ru: "ETF", cn: "ETF" },
  badge_stock_id: { id: "SAHAM IDX", en: "IDX STOCK", ru: "АКЦИИ IDX", cn: "IDX 股票" },
  badge_stock_us: { id: "WORLD STOCK", en: "WORLD STOCK", ru: "МИРОВЫЕ АКЦИИ", cn: "全球股票" },
  badge_gold_silver: { id: "GOLD/SILVER", en: "GOLD/SILVER", ru: "ЗОЛОТО/СЕРЕБРО", cn: "黄金/白银" },
  badge_commodity: { id: "KOMODITAS", en: "COMMODITY", ru: "СЫРЬЁ", cn: "大宗商品" },
  badge_forex: { id: "FOREX", en: "FOREX", ru: "ФОРЕКС", cn: "外汇" },

  // News page
  news_title: { id: "Berita", en: "News", ru: "Новости", cn: "新闻" },
  news_live_title: { id: "Berita Live", en: "Live News", ru: "Live новости", cn: "实时新闻" },
  news_rss_source: { id: "RSS publik", en: "Public RSS", ru: "Публичный RSS", cn: "公开 RSS" },
  news_loading: { id: "memuat…", en: "loading…", ru: "загрузка…", cn: "加载中…" },
  news_update: { id: "update", en: "updated", ru: "обновлено", cn: "更新" },
  news_all: { id: "SEMUA", en: "ALL", ru: "ВСЕ", cn: "全部" },
  news_market_crypto: { id: "CRYPTO", en: "CRYPTO", ru: "КРИПТО", cn: "加密" },
  news_market_etf: { id: "ETF", en: "ETF", ru: "ETF", cn: "ETF" },
  news_market_stock_id: { id: "SAHAM IDX", en: "IDX STOCKS", ru: "АКЦИИ IDX", cn: "IDX 股票" },
  news_market_stock_us: { id: "SAHAM US", en: "US STOCKS", ru: "АКЦИИ US", cn: "美股" },
  news_market_gold_silver: { id: "EMAS/PERAK", en: "GOLD/SILVER", ru: "ЗОЛОТО/СЕРЕБРО", cn: "黄金/白银" },
  news_market_commodity: { id: "KOMODITAS", en: "COMMODITY", ru: "СЫРЬЁ", cn: "大宗商品" },
  news_market_forex: { id: "FOREX", en: "FOREX", ru: "ФОРЕКС", cn: "外汇" },
  news_empty: { id: "Belum ada berita.", en: "No news yet.", ru: "Пока нет новостей.", cn: "暂无新闻。" },
  // Relative time formatter units (used in news feed timestamps).
  news_time_ago: { id: "lalu", en: "ago", ru: "назад", cn: "前" },
  news_time_second_short: { id: "d", en: "s", ru: "с", cn: "秒" },
  news_time_minute_short: { id: "m", en: "m", ru: "м", cn: "分" },
  news_time_hour_short: { id: "j", en: "h", ru: "ч", cn: "小时" },
  news_time_day_short: { id: "h", en: "d", ru: "д", cn: "天" },
  news_tab_news: { id: "Berita", en: "News", ru: "Новости", cn: "新闻" },
  news_tab_disclaimer: { id: "Disclaimer", en: "Disclaimer", ru: "Дисклеймер", cn: "免责声明" },
  news_disclaimer_subtitle: {
    id: "Harap baca dengan cermat sebelum mengambil keputusan",
    en: "Please read carefully before making decisions",
    ru: "Пожалуйста, прочитайте внимательно перед принятием решений",
    cn: "请在做出决定前仔细阅读",
  },

  // Disclaimer
  disclaimer_title: { id: "Disclaimer & Info Live", en: "Disclaimer & Live Info", ru: "Дисклеймер и Live", cn: "免责声明和实时信息" },
  disclaimer_body: {
    id: "Dengan menggunakan aplikasi ini, Anda setuju bahwa: (1) Semua informasi yang ditampilkan hanya untuk edukasi & referensi, BUKAN ajakan atau rekomendasi untuk membeli/menjual aset apapun. (2) Semua keputusan buy/sell, long/short, buka/tutup posisi, serta keuntungan maupun kerugian adalah tanggung jawab pribadi pengguna sepenuhnya. (3) Pengembang dan pemilik aplikasi TIDAK memperoleh imbalan dari trade Anda dan TIDAK menanggung kerugian apapun akibat penggunaan aplikasi. (4) Analisa AI, sinyal teknikal, dan berita adalah hasil interpretasi otomatis; akurasi tidak dijamin dan dapat berubah setiap saat. (5) Pasar aset (crypto, saham, forex, komoditas) memiliki risiko tinggi termasuk kehilangan seluruh modal. Jangan trading dengan uang yang tidak Anda sanggup rugi. (6) Aplikasi ini tidak memberikan nasihat keuangan, pajak, atau hukum — konsultasikan dengan profesional bersertifikat sebelum keputusan penting. (7) Data pasar disediakan pihak ketiga (Binance, Yahoo Finance) yang dapat mengalami delay atau tidak akurat. (8) Dengan melanjutkan penggunaan, Anda menyatakan telah membaca, memahami, dan menyetujui seluruh disclaimer ini.",
    en: "By using this app, you agree that: (1) All information shown is for education & reference only, NOT a solicitation or recommendation to buy/sell any asset. (2) All buy/sell, long/short, and open/close decisions, plus any profits or losses, are solely your responsibility. (3) The developer and app owner DO NOT receive any compensation from your trades and DO NOT bear any liability for losses from using this app. (4) AI analysis, technical signals, and news are automated interpretations; accuracy is not guaranteed and may change any time. (5) Asset markets (crypto, stocks, forex, commodities) carry high risk including total capital loss. Do not trade money you cannot afford to lose. (6) This app does NOT provide financial, tax, or legal advice — consult certified professionals before major decisions. (7) Market data is provided by third parties (Binance, Yahoo Finance) which may be delayed or inaccurate. (8) By continuing to use the app you confirm you have read, understood, and agreed to all of this disclaimer.",
    ru: "Используя приложение, вы соглашаетесь: (1) Вся информация только для образования и справки, НЕ является рекомендацией к покупке/продаже. (2) Все решения buy/sell/long/short и открытия/закрытия позиций, а также прибыль или убытки — исключительно ваша ответственность. (3) Разработчик и владелец НЕ получают вознаграждения с ваших сделок и НЕ несут ответственности за убытки. (4) AI-анализ и сигналы — автоматические интерпретации; точность не гарантирована. (5) Рынки (крипто, акции, форекс, сырьё) — высокий риск, включая потерю всего капитала. Не торгуйте средствами, потеря которых недопустима. (6) Приложение не даёт финансовых, налоговых или юридических советов — консультируйтесь со специалистами. (7) Рыночные данные предоставлены третьими лицами (Binance, Yahoo Finance) и могут задерживаться. (8) Продолжая использование, вы подтверждаете согласие со всеми пунктами.",
    cn: "使用本应用即表示您同意：（1）所有显示的信息仅供教育和参考，绝非买卖资产的招揽或推荐。（2）所有买入/卖出、多头/空头和开仓/平仓决定以及任何盈利或亏损完全由您自行负责。（3）开发者和所有者不从您的交易中获取任何报酬，也不对因使用本应用产生的任何损失承担责任。（4）AI 分析、技术信号和新闻均为自动化解读；准确性不保证并可能随时变化。（5）资产市场（加密、股票、外汇、大宗商品）风险高，可能导致本金全部损失。请勿使用不能承受损失的资金进行交易。（6）本应用不提供金融、税务或法律建议 — 重大决策请咨询持证专业人士。（7）市场数据由第三方（Binance, Yahoo Finance）提供，可能延迟或不准确。（8）继续使用即表示您已阅读、理解并同意本免责声明的全部内容。",
  },
  disclaimer_read_carefully: {
    id: "⚠️ HARAP BACA DENGAN SEKSAMA",
    en: "⚠️ PLEASE READ CAREFULLY",
    ru: "⚠️ ПОЖАЛУЙСТА, ПРОЧИТАЙТЕ ВНИМАТЕЛЬНО",
    cn: "⚠️ 请仔细阅读",
  },
  disclaimer_accept: { id: "Saya Mengerti", en: "I Understand", ru: "Понятно", cn: "我明白" },

  // Common
  retry: { id: "Coba lagi", en: "Retry", ru: "Повторить", cn: "重试" },
  loading: { id: "Memuat…", en: "Loading…", ru: "Загрузка…", cn: "加载中…" },
  back: { id: "Kembali", en: "Back", ru: "Назад", cn: "返回" },
  close: { id: "Tutup", en: "Close", ru: "Закрыть", cn: "关闭" },
};

type StringEntry = { id: string; en: string; ru: string; cn: string };

type Ctx = {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggle: () => void;
  t: (key: keyof typeof STRINGS | string) => string;
  ready: boolean;
};

const I18nContext = createContext<Ctx | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // First install defaults to EN (English) — this is a global-audience app.
  // Existing users keep whatever they saved in AsyncStorage.
  const [lang, setLangState] = useState<Lang>("en");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((v) => {
        if (v && LANG_ORDER.includes(v as Lang)) setLangState(v as Lang);
      })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    AsyncStorage.setItem(STORAGE_KEY, l).catch(() => {});
  }, []);

  const toggle = useCallback(() => {
    // Cycle through: ID → EN → RU → CN → ID
    const idx = LANG_ORDER.indexOf(lang);
    const next = LANG_ORDER[(idx + 1) % LANG_ORDER.length];
    setLang(next);
  }, [lang, setLang]);

  const t = useCallback(
    (key: string): string => {
      const entry = (STRINGS as Record<string, StringEntry>)[key];
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
