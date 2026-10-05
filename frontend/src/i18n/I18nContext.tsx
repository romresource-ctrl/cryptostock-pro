import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "id" | "en" | "ru" | "cn";

const STORAGE_KEY = "aicryptostockpro:lang";
export const LANG_ORDER: Lang[] = ["en", "id", "ru", "cn"];
export const LANG_LABEL: Record<Lang, string> = { id: "ID", en: "EN", ru: "RU", cn: "CN" };

// Static UI translations. Dynamic content (news, AI analysis, asset detail
// long-form text) is translated at request time via /api/translate.
const STRINGS: Record<string, { id: string; en: string; ru: string; cn: string }> = {
  app_title: { id: "AI Crypto\nStock Pro", en: "AI Crypto\nStock Pro", ru: "AI Crypto\nStock Pro", cn: "AI Crypto\nStock Pro" },
  app_sub_loading: { id: "memuat…", en: "loading…", ru: "загрузка…", cn: "加载中…" },
  app_tagline: {
    id: "Crypto Signal • Stock Signal • Trading Predictions",
    en: "Crypto Signal • Stock Signal • Trading Predictions",
    ru: "Crypto Signal • Stock Signal • Trading Predictions",
    cn: "加密信号 • 股票信号 • 交易预测",
  },
  syncing_market: {
    id: "Menyinkronkan data pasar…",
    en: "Syncing Market Data…",
    ru: "Синхронизация рыночных данных…",
    cn: "正在同步市场数据…",
  },
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

  // v8.5.3 — Watchlist
  watchlist_title: { id: "Favorit", en: "Watchlist", ru: "Избранное", cn: "自选" },
  watchlist_empty: {
    id: "Belum ada aset favorit. Tap ⭐ pada kartu untuk menambahkan ke sini.",
    en: "No favorites yet. Tap ⭐ on any card to add.",
    ru: "Нет избранного. Нажмите ⭐ на карточке, чтобы добавить.",
    cn: "尚无自选。点按卡片上的 ⭐ 添加。",
  },
  watchlist_loading: {
    id: "Aset favorit belum tampil — tunggu data harga selesai dimuat.",
    en: "Loading favorites — waiting for price data.",
    ru: "Загрузка избранного…",
    cn: "正在加载自选…",
  },

  // v8.12.36 — Trending column
  trending_title: { id: "🔥 Trending", en: "🔥 Trending", ru: "🔥 Тренды", cn: "🔥 热门" },
  trending_loading: {
    id: "Menganalisis pergerakan pasar…",
    en: "Analysing market moves…",
    ru: "Анализ движений рынка…",
    cn: "分析市场动向…",
  },
  // v8.12.38 — Trending mode labels (tap header to cycle).
  trending_gainers: { id: "Top Gainers", en: "Top Gainers", ru: "Топ Роста", cn: "涨幅榜" },
  trending_losers: { id: "Top Losers", en: "Top Losers", ru: "Топ Падения", cn: "跌幅榜" },
  trending_volume: { id: "High Volume", en: "High Volume", ru: "Высокий Объём", cn: "高成交量" },
  // v8.12.38 — Recent search chips.
  recent_label: { id: "Terakhir dicari", en: "Recent", ru: "Недавние", cn: "最近" },
  recent_clear: { id: "Hapus", en: "Clear", ru: "Очистить", cn: "清空" },

  // v8.12.41 — First-launch Disclaimer Modal.
  disclaimer_first_title: {
    id: "Peringatan Penting",
    en: "Important Disclaimer",
    ru: "Важное предупреждение",
    cn: "重要免责声明",
  },
  disclaimer_first_body: {
    id: "AI Crypto Stock Pro menyediakan sinyal trading dan analisis pasar HANYA untuk tujuan EDUKASI. Ini BUKAN nasihat keuangan. Trading melibatkan risiko besar termasuk kemungkinan kehilangan seluruh modal. Kinerja masa lalu tidak menjamin hasil di masa depan. Anda sepenuhnya bertanggung jawab atas keputusan investasi Anda.",
    en: "AI Crypto Stock Pro provides trading signals and market analytics for EDUCATIONAL purposes only. It is NOT financial advice. Trading involves substantial risk, including possible loss of all invested capital. Past performance does not guarantee future results. You are solely responsible for your investment decisions.",
    ru: "AI Crypto Stock Pro предоставляет торговые сигналы и рыночную аналитику ТОЛЬКО в образовательных целях. Это НЕ финансовый совет. Торговля связана со значительным риском, включая возможную потерю всего инвестированного капитала.",
    cn: "AI Crypto Stock Pro 仅出于教育目的提供交易信号和市场分析。这不是财务建议。交易涉及重大风险,包括可能损失所有投资资金。",
  },
  disclaimer_bullet_1: {
    id: "Bukan nasihat keuangan — hanya untuk edukasi",
    en: "Not financial advice — for education only",
    ru: "Не финансовый совет — только для обучения",
    cn: "非财务建议 — 仅供教育",
  },
  disclaimer_bullet_2: {
    id: "Trading berisiko kehilangan modal Anda",
    en: "Trading carries risk of losing your capital",
    ru: "Торговля несёт риск потери капитала",
    cn: "交易有损失资本的风险",
  },
  disclaimer_bullet_3: {
    id: "Sinyal AI bisa salah — selalu DYOR (riset sendiri)",
    en: "AI signals may be wrong — always DYOR",
    ru: "Сигналы ИИ могут быть ошибочными — всегда проводите собственное исследование",
    cn: "AI 信号可能出错 — 请自行研究",
  },
  disclaimer_bullet_4: {
    id: "Kami bukan penasihat investasi terdaftar",
    en: "We are not registered investment advisors",
    ru: "Мы не являемся зарегистрированными инвестиционными консультантами",
    cn: "我们不是注册投资顾问",
  },
  disclaimer_checkbox: {
    id: "Saya sudah membaca dan mengerti — ini bukan nasihat keuangan",
    en: "I have read and understood — this is not financial advice",
    ru: "Я прочитал(а) и понял(а) — это не финансовый совет",
    cn: "我已阅读并理解 — 这不是财务建议",
  },
  disclaimer_agree: { id: "Saya Setuju", en: "I Agree", ru: "Согласен", cn: "我同意" },
  disclaimer_decline: { id: "Tolak", en: "Decline", ru: "Отклонить", cn: "拒绝" },

  // v8.12.41 — Post-Subscribe Privacy Notice Popup.
  privacy_notice_title: {
    id: "Privasi Anda",
    en: "Your Privacy",
    ru: "Ваша конфиденциальность",
    cn: "您的隐私",
  },
  privacy_notice_subtitle: {
    id: "Catatan singkat tentang data yang kami gunakan selama berlangganan.",
    en: "A quick note about the data we use while you're subscribed.",
    ru: "Краткая заметка о данных, которые мы используем во время подписки.",
    cn: "关于订阅期间我们使用的数据的简要说明。",
  },
  privacy_notice_1: {
    id: "Kami menyimpan status langganan + ID perangkat untuk memvalidasi akses Premium.",
    en: "We store your subscription state + device ID so we can validate premium access.",
    ru: "Мы храним статус подписки + идентификатор устройства для проверки доступа Premium.",
    cn: "我们存储订阅状态 + 设备 ID 以验证高级访问权限。",
  },
  privacy_notice_2: {
    id: "Pesan Chatroom terlihat oleh pengguna lain. ID perangkat digunakan untuk indikator online.",
    en: "Chatroom messages are visible to other users. Your device ID is used for the presence dot.",
    ru: "Сообщения в чате видны другим пользователям. Идентификатор устройства используется для индикатора онлайн.",
    cn: "聊天室消息对其他用户可见。您的设备 ID 用于显示在线状态。",
  },
  privacy_notice_3: {
    id: "Watchlist dan preferensi disimpan HANYA di perangkat ini — tidak di server kami.",
    en: "Watchlist and preferences stay on THIS device only — not on our servers.",
    ru: "Список наблюдения и настройки хранятся ТОЛЬКО на этом устройстве.",
    cn: "关注列表和偏好设置仅保存在此设备上,不在我们的服务器上。",
  },
  privacy_notice_4: {
    id: "Kami TIDAK PERNAH mengumpulkan wallet address, private key, atau kredensial broker.",
    en: "We NEVER collect wallet addresses, private keys, or brokerage credentials.",
    ru: "Мы НИКОГДА не собираем адреса кошельков, закрытые ключи или учётные данные брокеров.",
    cn: "我们绝不会收集钱包地址、私钥或经纪账户凭据。",
  },
  privacy_notice_read_full: {
    id: "Baca Kebijakan Privasi lengkap",
    en: "Read the full Privacy Policy",
    ru: "Читать полную Политику Конфиденциальности",
    cn: "阅读完整的隐私政策",
  },
  privacy_notice_ok: {
    id: "Mengerti",
    en: "Got it",
    ru: "Понятно",
    cn: "明白了",
  },

  // v8.6.3 — Price Alerts feature removed. i18n keys deleted with it.

  // v8.5.0 — Category reorder sheet
  reorder_button: { id: "Atur Kolom", en: "Reorder", ru: "Порядок", cn: "排列" },
  reorder_title: { id: "Atur Urutan Kategori", en: "Reorder Categories", ru: "Порядок Категорий", cn: "类别排序" },
  reorder_hint: {
    id: "Tekan & tahan ⋮ untuk menyeret. Toggle untuk menampilkan/menyembunyikan kolom di dashboard.",
    en: "Long-press ⋮ to drag. Toggle to show/hide a column on the dashboard.",
    ru: "Удерживайте ⋮ для перетаскивания. Переключатель — показать/скрыть колонку.",
    cn: "长按 ⋮ 以拖动。切换开关以显示/隐藏该列。",
  },
  reorder_hint_arrows: {
    id: "Gunakan tombol ↑ ↓ untuk memindahkan kategori. Toggle switch untuk menampilkan/menyembunyikan kolom.",
    en: "Use the ↑ ↓ buttons to move a category. Toggle to show/hide a column on the dashboard.",
    ru: "Используйте кнопки ↑ ↓ для перемещения. Переключатель — показать/скрыть.",
    cn: "使用 ↑ ↓ 按钮上下移动类别。切换开关以显示/隐藏该列。",
  },
  reorder_reset: {
    id: "Kembalikan ke urutan bawaan",
    en: "Reset to default order",
    ru: "Сбросить порядок",
    cn: "恢复默认顺序",
  },
  reorder_hidden_suffix: { id: "disembunyikan", en: "hidden", ru: "скрыто", cn: "已隐藏" },
  common_cancel: { id: "Batal", en: "Cancel", ru: "Отмена", cn: "取消" },
  common_save: { id: "Simpan", en: "Save", ru: "Сохранить", cn: "保存" },

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
  // v8.7.0 — WR history popup
  wr_modal_title: { id: "Riwayat Win Rate", en: "Win Rate History", ru: "История Win Rate", cn: "胜率历史" },
  wr_modal_hint: { id: "Ketuk WR untuk melihat detail", en: "Tap WR to see details", ru: "Нажмите WR для деталей", cn: "点击 WR 查看详情" },
  wr_tab_7d: { id: "7 Hari", en: "7 Days", ru: "7 дней", cn: "7天" },
  wr_tab_30d: { id: "30 Hari", en: "30 Days", ru: "30 дней", cn: "30天" },
  wr_tab_all: { id: "Semua", en: "All Time", ru: "Всё время", cn: "全部" },
  wr_summary_total: { id: "Total", en: "Total", ru: "Всего", cn: "总数" },
  wr_summary_win: { id: "Win", en: "Win", ru: "Побед", cn: "胜" },
  wr_summary_loss: { id: "Loss/SL", en: "Loss/SL", ru: "Убыток/SL", cn: "亏损" },
  wr_summary_be: { id: "BE", en: "BE", ru: "БУ", cn: "持平" },
  wr_summary_wr: { id: "WR", en: "WR", ru: "WR", cn: "胜率" },
  wr_empty: { id: "Belum ada sinyal historis yang tercatat pada periode ini.", en: "No historic signals recorded for this period yet.", ru: "Пока нет записей за этот период.", cn: "此期间暂无历史信号。" },
  wr_close: { id: "Tutup", en: "Close", ru: "Закрыть", cn: "关闭" },
  detail_news_factors: { id: "📰 Faktor Berita & Makro", en: "📰 News & Macro Factors", ru: "📰 Новости и Макро", cn: "📰 新闻与宏观" },
  detail_risk: { id: "⚠️ Risiko", en: "⚠️ Risk Factors", ru: "⚠️ Риски", cn: "⚠️ 风险" },
  detail_news_live: { id: "📡 Berita Live yang Digunakan", en: "📡 Live News Used", ru: "📡 Live новости", cn: "📡 使用的实时新闻" },
  detail_generated_at: { id: "Dianalisa", en: "Analyzed", ru: "Проанализировано", cn: "分析时间" },

  // v8.3.1 — Legal links in Disclaimer page (Google Play compliance)
  legal_links_label: { id: "Legal & Kebijakan", en: "Legal & Policies", ru: "Юридич. документы", cn: "法律与政策" },
  legal_privacy: { id: "Kebijakan Privasi", en: "Privacy Policy", ru: "Политика конфиденциальности", cn: "隐私政策" },
  legal_terms: { id: "Syarat & Ketentuan", en: "Terms of Service", ru: "Условия использования", cn: "服务条款" },
  legal_data_deletion: { id: "Hapus Akun & Data", en: "Delete Account & Data", ru: "Удалить аккаунт и данные", cn: "删除账户与数据" },

  // v8.3.9 — Position Size Calculator
  pos_calc_title: { id: "Kalkulator Ukuran Posisi", en: "Position Size Calculator", ru: "Калькулятор размера позиции", cn: "仓位大小计算器" },
  pos_calc_subtitle: {
    id: "Hitung otomatis dari Entry & SL sinyal",
    en: "Auto-calculated from signal Entry & SL",
    ru: "Автоматически из Entry и SL сигнала",
    cn: "根据信号入场价与止损自动计算",
  },
  pos_calc_missing_signal: {
    id: "Butuh Entry & Stop Loss dari sinyal aktif.",
    en: "Needs active signal Entry & Stop Loss.",
    ru: "Требуется активный сигнал с Entry и Stop Loss.",
    cn: "需要有活跃信号的入场价与止损。",
  },
  pos_calc_entry: { id: "Entry Price", en: "Entry Price", ru: "Цена входа", cn: "入场价" },
  pos_calc_sl: { id: "Stop Loss", en: "Stop Loss", ru: "Стоп-лосс", cn: "止损" },
  pos_calc_balance: { id: "Initial Margin", en: "Initial Margin", ru: "Начальная маржа", cn: "初始保证金" },
  pos_calc_risk_pct: { id: "Risk %", en: "Risk %", ru: "Риск %", cn: "风险%" },
  pos_calc_position_size: { id: "Ukuran Posisi", en: "Position Size", ru: "Размер позиции", cn: "仓位大小" },
  pos_calc_position_value: { id: "Nilai Posisi", en: "Position Value", ru: "Стоимость позиции", cn: "仓位价值" },
  pos_calc_max_loss: { id: "Maks. Kerugian", en: "Max Loss", ru: "Макс. убыток", cn: "最大亏损" },
  pos_calc_leverage: { id: "Leverage", en: "Leverage", ru: "Плечо", cn: "杠杆" },
  // v8.4.0 — Leverage input + margin & projected profit
  pos_calc_leverage_input: { id: "Leverage (×)", en: "Leverage (×)", ru: "Плечо (×)", cn: "杠杆(×)" },
  pos_calc_margin_required: { id: "Margin Dibutuhkan", en: "Margin Required", ru: "Требуемая маржа", cn: "所需保证金" },
  pos_calc_of_balance: { id: "dari saldo", en: "of balance", ru: "от баланса", cn: "占余额" },
  pos_calc_projected_profit: { id: "Proyeksi Profit (TP)", en: "Projected Profit (TP)", ru: "Прогноз прибыли (TP)", cn: "预期收益 (TP)" },
  pos_calc_hint: {
    id: "Tip: pakai Risk 1–2% per trade untuk jaga saldo jangka panjang.",
    en: "Tip: use 1–2% risk per trade for long-term account preservation.",
    ru: "Совет: используйте риск 1–2% на сделку.",
    cn: "提示：每笔交易风险控制在1-2%以延长账户寿命。",
  },

  // v8.3.5 — Market Brief page (re-read pushed briefings)
  news_tab_market_brief: { id: "Brief Pasar", en: "Market Brief", ru: "Брифинг", cn: "市场简报" },
  market_brief_title: { id: "Brief Pasar", en: "Market Brief", ru: "Брифинг рынка", cn: "市场简报" },
  market_brief_subtitle: {
    id: "Ringkasan push 24 jam terakhir",
    en: "Last 24h push briefings",
    ru: "Пуш-брифинги за 24 часа",
    cn: "过去24小时推送简报",
  },
  market_brief_banner: {
    id: "⚠️ PERHATIAN! Brief akan hilang dalam 24 jam.",
    en: "⚠️ ATTENTION! Briefs will disappear in 24 hours.",
    ru: "⚠️ ВНИМАНИЕ! Брифинги исчезнут через 24 часа.",
    cn: "⚠️ 注意！简报将在 24 小时后消失。",
  },
  market_brief_empty_title: {
    id: "Belum ada brief hari ini",
    en: "No briefings yet today",
    ru: "Пока нет брифингов",
    cn: "今日暂无简报",
  },
  market_brief_empty_body: {
    id: "Brief pertama akan muncul di jadwal berikutnya sesuai bahasa Anda (contoh: 08:45 WIB untuk pre-market IDX).",
    en: "The next scheduled brief for your language will appear here.",
    ru: "Следующий запланированный брифинг появится здесь.",
    cn: "下一次预定简报将出现在此处。",
  },
  market_brief_error: { id: "Gagal memuat", en: "Failed to load", ru: "Ошибка загрузки", cn: "加载失败" },
  market_brief_premium_title: {
    id: "Brief Pasar — Fitur Premium",
    en: "Market Brief — Premium Feature",
    ru: "Брифинг рынка — премиум",
    cn: "市场简报 — 高级功能",
  },
  market_brief_premium_body: {
    id: "Aktifkan Premium untuk membaca ringkasan push notification (pre-market, close, dsb) yang terlewat di lock screen.",
    en: "Upgrade to Premium to re-read the push briefings you may have missed on your lock screen.",
    ru: "Оформите Premium, чтобы читать пропущенные пуш-брифинги.",
    cn: "升级至高级版即可查看错过的推送简报。",
  },
  market_brief_premium_cta: { id: "Ke Dashboard", en: "Go to Dashboard", ru: "На Дашборд", cn: "前往仪表盘" },

  // v8.7.1 — AI-generated Daily Market Brief (Claude Sonnet 4.6)
  brief_session_morning: { id: "Brief Pagi", en: "Morning Brief", ru: "Утренний брифинг", cn: "早间简报" },
  brief_session_evening: { id: "Brief Sore", en: "Evening Brief", ru: "Вечерний брифинг", cn: "晚间简报" },
  brief_generated: { id: "Dibuat", en: "Generated", ru: "Создано", cn: "生成于" },
  brief_sentiment_bullish: { id: "BULLISH", en: "BULLISH", ru: "БЫЧИЙ", cn: "看涨" },
  brief_sentiment_bearish: { id: "BEARISH", en: "BEARISH", ru: "МЕДВЕЖИЙ", cn: "看跌" },
  brief_sentiment_mixed: { id: "CAMPURAN", en: "MIXED", ru: "СМЕШАННЫЙ", cn: "混合" },
  brief_sentiment_neutral: { id: "NETRAL", en: "NEUTRAL", ru: "НЕЙТРАЛЬНЫЙ", cn: "中性" },
  brief_section_crypto: { id: "Crypto", en: "Crypto", ru: "Крипто", cn: "加密货币" },
  brief_section_stocks: { id: "Saham", en: "Stocks", ru: "Акции", cn: "股票" },
  brief_section_forex: { id: "Forex", en: "Forex", ru: "Форекс", cn: "外汇" },
  brief_section_gold: { id: "Emas & Komoditas", en: "Gold & Commodities", ru: "Золото и товары", cn: "黄金与商品" },
  brief_top_movers: { id: "Pergerak Terbesar", en: "Top Movers", ru: "Топ движений", cn: "涨跌榜" },
  brief_top_headlines: { id: "Berita Utama", en: "Top Headlines", ru: "Главные новости", cn: "头条" },
  brief_warnings: { id: "Zona Peringatan", en: "Warning Zones", ru: "Зоны риска", cn: "风险区" },
  brief_show_more: { id: "Baca detail lengkap", en: "Read full details", ru: "Показать детали", cn: "查看详情" },
  brief_show_less: { id: "Ciutkan", en: "Show less", ru: "Свернуть", cn: "收起" },
  brief_loading: { id: "Menghasilkan brief pasar...", en: "Generating market brief...", ru: "Формируется брифинг...", cn: "生成简报中..." },
  brief_error_title: { id: "Brief tidak tersedia", en: "Brief unavailable", ru: "Брифинг недоступен", cn: "简报不可用" },
  brief_empty_title: { id: "Belum ada brief", en: "No brief yet", ru: "Пока нет брифинга", cn: "暂无简报" },
  brief_empty_body: { id: "Brief pertama akan otomatis dibuat sebentar lagi. Tarik ke bawah untuk refresh.", en: "The first brief will be generated shortly. Pull down to refresh.", ru: "Первый брифинг появится совсем скоро.", cn: "首份简报即将自动生成。" },
  brief_retry: { id: "Coba lagi", en: "Try again", ru: "Повторить", cn: "重试" },
  brief_paywall_title: { id: "🔒 Analisis Aksi Premium", en: "🔒 Premium Actionable Analysis", ru: "🔒 Премиум-разбор", cn: "🔒 高级操作分析" },
  brief_paywall_body: {
    id: "Rekomendasi beli/jual/long/short per aset (Crypto, Saham, Forex, Emas) hanya tersedia untuk anggota Premium. Upgrade untuk akses insight AI penuh.",
    en: "Per-asset buy/sell/long/short recommendations (Crypto, Stocks, Forex, Gold) are Premium only. Upgrade to unlock the full AI insight.",
    ru: "Рекомендации купить/продать/long/short по активам доступны только Premium.",
    cn: "买/卖/多/空 建议仅限高级会员使用。",
  },
  brief_paywall_cta: { id: "Upgrade ke Premium", en: "Upgrade to Premium", ru: "Оформить Premium", cn: "升级会员" },

  // v8.2.3 — AI Prediction box: Beli/Jual (stocks) vs BUY/SELL (crypto) & Risk/Reward info
  ai_pred_action_buy_stock: { id: "BELI", en: "BUY", ru: "ПОКУПКА", cn: "买入" },
  ai_pred_action_sell_stock: { id: "JUAL", en: "SELL", ru: "ПРОДАЖА", cn: "卖出" },
  ai_pred_action_buy_crypto: { id: "LONG", en: "LONG", ru: "LONG", cn: "做多" },
  ai_pred_action_sell_crypto: { id: "SHORT", en: "SHORT", ru: "SHORT", cn: "做空" },
  ai_pred_prepare_buy_stock: {
    id: "Bersiap BELI. Pantau entry di ~{entry}, TP {tp}, SL {sl}.",
    en: "Prepare to BUY. Watch entry ~{entry}, TP {tp}, SL {sl}.",
    ru: "Готовьтесь к ПОКУПКЕ. Вход ~{entry}, TP {tp}, SL {sl}.",
    cn: "准备买入。入场 ~{entry}, TP {tp}, SL {sl}。",
  },
  ai_pred_prepare_sell_stock: {
    id: "Bersiap JUAL. Pantau entry di ~{entry}, TP {tp}, SL {sl}.",
    en: "Prepare to SELL. Watch entry ~{entry}, TP {tp}, SL {sl}.",
    ru: "Готовьтесь к ПРОДАЖЕ. Вход ~{entry}, TP {tp}, SL {sl}.",
    cn: "准备卖出。入场 ~{entry}, TP {tp}, SL {sl}。",
  },
  ai_pred_prepare_buy_crypto: {
    id: "Bersiap LONG. Pantau entry di ~{entry}, TP {tp}, SL {sl}.",
    en: "Prepare LONG. Watch entry ~{entry}, TP {tp}, SL {sl}.",
    ru: "Готовьтесь к LONG. Вход ~{entry}, TP {tp}, SL {sl}.",
    cn: "准备做多。入场 ~{entry}, TP {tp}, SL {sl}。",
  },
  ai_pred_prepare_sell_crypto: {
    id: "Bersiap SHORT. Pantau entry di ~{entry}, TP {tp}, SL {sl}.",
    en: "Prepare SHORT. Watch entry ~{entry}, TP {tp}, SL {sl}.",
    ru: "Готовьтесь к SHORT. Вход ~{entry}, TP {tp}, SL {sl}.",
    cn: "准备做空。入场 ~{entry}, TP {tp}, SL {sl}。",
  },
  ai_pred_wait: {
    id: "Tunggu — momentum belum jelas. Pantau breakout dari high/low terakhir untuk sinyal berikutnya.",
    en: "Wait — no clear momentum yet. Watch break of recent high/low for next signal.",
    ru: "Ждите — импульс неясен. Следите за пробоем high/low.",
    cn: "等待——动能不明朗。留意近期高/低点突破。",
  },
  ai_pred_rr_line: {
    id: "R/R 1:{ratio} · Risiko: {level} ({riskPct}%) · Potensi Profit: {rewardPct}%",
    en: "R/R 1:{ratio} · Risk: {level} ({riskPct}%) · Reward: {rewardPct}%",
    ru: "R/R 1:{ratio} · Риск: {level} ({riskPct}%) · Профит: {rewardPct}%",
    cn: "R/R 1:{ratio} · 风险: {level} ({riskPct}%) · 收益: {rewardPct}%",
  },
  ai_pred_rr_label: { id: "Risk/Reward", en: "Risk/Reward", ru: "Риск/Профит", cn: "风险/收益" },
  ai_pred_risk_low: { id: "Rendah", en: "Low", ru: "Низкий", cn: "低" },
  ai_pred_risk_medium: { id: "Sedang", en: "Medium", ru: "Средний", cn: "中" },
  ai_pred_risk_high: { id: "Tinggi", en: "High", ru: "Высокий", cn: "高" },
  ai_pred_rr_hint_low: {
    id: "Setup ideal — reward jauh lebih besar dari risiko",
    en: "Ideal setup — reward far outweighs risk",
    ru: "Идеальная сделка — прибыль намного больше риска",
    cn: "理想设置 — 收益远大于风险",
  },
  ai_pred_rr_hint_medium: {
    id: "Setup seimbang — kelola posisi dengan disiplin",
    en: "Balanced setup — manage size with discipline",
    ru: "Сбалансированная сделка — соблюдайте дисциплину",
    cn: "均衡设置 — 严格控仓",
  },
  ai_pred_rr_hint_high: {
    id: "Risiko tinggi — pertimbangkan posisi lebih kecil",
    en: "High risk — consider a smaller position",
    ru: "Высокий риск — уменьшите размер позиции",
    cn: "高风险 — 建议减小仓位",
  },

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

  // v9.2.0 — AI Suggestions (Trader Profile modal + sheet)
  ai_suggestions_title: { id: "SARAN AI", en: "AI SUGGESTIONS", ru: "РЕКОМЕНДАЦИИ ИИ", cn: "AI 建议" },
  ai_suggestions_sub: {
    id: "Pindai peluang LONG/SHORT terkuat — lengkap Entry, SL & TP",
    en: "Scan the strongest LONG/SHORT setups — full Entry, SL & TP",
    ru: "Сканируйте сильнейшие сетапы LONG/SHORT — с Entry, SL и TP",
    cn: "扫描最强 LONG/SHORT 机会 — 含入场、止损和止盈",
  },
  // v9.7.9 — Footer hint di TraderProfileModal: modal tetap terbuka setelah
  // memilih profil agar user langsung bisa tap AI Suggestions.
  ai_profile_footer_hint: {
    id: "Modal tetap terbuka setelah memilih — langsung tap AI Suggestions. Ketuk profil aktif untuk melepas (mesin default: Confluence).",
    en: "The modal stays open after selecting — tap AI Suggestions right away. Tap the active profile to unselect (default engine: Confluence).",
    ru: "Окно остаётся открытым после выбора — сразу нажмите AI Suggestions. Нажмите активный профиль, чтобы снять выбор (движок по умолчанию: Confluence).",
    cn: "选择后弹窗保持打开——可立即点击 AI 建议。再次点击已选档案可取消（默认引擎：Confluence）。",
  },
  ai_sheet_sub: {
    id: "Peluang terkuat hasil pindaian formula — lengkap Entry · SL · TP",
    en: "Strongest setups from the formula scan — full Entry · SL · TP",
    ru: "Сильнейшие сетапы по формуле — Entry · SL · TP",
    cn: "公式扫描出的最强机会 — 含入场 · 止损 · 止盈",
  },
  ai_locked_title: { id: "Fitur Premium", en: "Premium Feature", ru: "Премиум-функция", cn: "高级功能" },
  ai_locked_sub: {
    id: "AI Suggestions memindai seluruh market dan menyajikan peluang LONG/SHORT terkuat — lengkap dengan Entry, SL & TP.",
    en: "AI Suggestions scans all markets and serves the strongest LONG/SHORT setups — complete with Entry, SL & TP.",
    ru: "AI Suggestions сканирует все рынки и показывает сильнейшие сетапы LONG/SHORT — с Entry, SL и TP.",
    cn: "AI 建议扫描所有市场，呈现最强 LONG/SHORT 机会 — 含入场、止损和止盈。",
  },
  ai_upgrade: { id: "Upgrade ke Premium", en: "Upgrade to Premium", ru: "Перейти на Премиум", cn: "升级到高级版" },
  ai_empty_title: { id: "Belum ada setup", en: "No setups yet", ru: "Пока нет сетапов", cn: "暂无信号" },
  ai_empty_sub: {
    id: "Tidak ada aset yang lolos formula di kategori ini saat ini. Coba kategori lain atau tunggu candle berikutnya.",
    en: "No assets passed the formula in this category right now. Try another category or wait for the next candle.",
    ru: "Сейчас ни один актив не прошёл формулу в этой категории. Попробуйте другую категорию или дождитесь следующей свечи.",
    cn: "当前该类别没有资产通过公式筛选。请尝试其他类别或等待下一根K线。",
  },
  ai_open_detail: { id: "Buka Detail Aset  →", en: "Open Asset Detail  →", ru: "Открыть детали актива  →", cn: "打开资产详情  →" },
  ai_daily_bias: { id: "BIAS HARIAN", en: "DAILY BIAS", ru: "ДНЕВНОЙ БИАС", cn: "日线偏向" },

  // v9.5.0 — ASI-Bot page
  asi_status_active: { id: "AKTIF", en: "ACTIVE", ru: "АКТИВЕН", cn: "已启用" },
  asi_status_inactive: { id: "NONAKTIF", en: "INACTIVE", ru: "ВЫКЛ", cn: "已停用" },
  asi_status_on_sub: { id: "Bot sedang memindai sinyal & siap eksekusi.", en: "Bot is scanning signals & ready to execute.", ru: "Бот сканирует сигналы и готов к исполнению.", cn: "机器人正在扫描信号并准备执行。" },
  asi_status_off_sub: { id: "Nyalakan untuk mulai auto-trade.", en: "Turn on to start auto-trading.", ru: "Включите для автоторговли.", cn: "开启以开始自动交易。" },
  asi_sec_exchange: { id: "Koneksi Exchange", en: "Exchange Connection", ru: "Подключение биржи", cn: "交易所连接" },
  asi_not_connected: { id: "Belum terhubung →", en: "Not connected →", ru: "Не подключено →", cn: "未连接 →" },
  asi_sec_mode: { id: "Mode", en: "Mode", ru: "Режим", cn: "模式" },
  asi_mode_semi_sub: { id: "Preview & konfirmasi tiap trade", en: "Preview & confirm every trade", ru: "Предпросмотр и подтверждение сделки", cn: "每笔交易预览并确认" },
  asi_mode_full_sub: { id: "Eksekusi otomatis tanpa konfirmasi", en: "Auto-execute without confirmation", ru: "Автоисполнение без подтверждения", cn: "无需确认自动执行" },
  asi_sec_risk: { id: "Parameter Risiko", en: "Risk Parameters", ru: "Параметры риска", cn: "风险参数" },
  asi_risk_per_trade: { id: "Risk per Trade", en: "Risk per Trade", ru: "Риск на сделку", cn: "每笔风险" },
  asi_max_trades_day: { id: "Max Trade / Hari", en: "Max Trades / Day", ru: "Макс. сделок / день", cn: "每日最大交易数" },
  asi_daily_loss_limit: { id: "Limit Rugi Harian (USDT)", en: "Daily Loss Limit (USDT)", ru: "Дневной лимит убытка (USDT)", cn: "每日亏损限额 (USDT)" },
  asi_daily_loss_hint: { id: "Bot otomatis mati bila kerugian realized hari ini mencapai limit. Set OFF untuk nonaktifkan.", en: "Bot auto-stops when today's realized loss hits the limit. Set OFF to disable.", ru: "Бот выключится при достижении дневного лимита убытка. OFF — отключить.", cn: "当日已实现亏损达到限额时机器人自动停止。设为 OFF 关闭。" },
  asi_auto_disabled: { id: "Bot auto-mati:", en: "Bot auto-disabled:", ru: "Бот авто-отключён:", cn: "机器人自动停用：" },
  asi_sec_disclaimer: { id: "Disclaimer Wajib", en: "Mandatory Disclaimer", ru: "Обязательный дисклеймер", cn: "必读免责声明" },
  asi_disc_body: {
    id: "• Risiko slippage, latency & kerugian pasar adalah 100% tanggung jawab Anda.\n• Pengembang tidak bertanggung jawab atas kegagalan API exchange.\n• JANGAN PERNAH centang izin \"Enable Withdrawals\" di API key exchange.\n• Aplikasi non-custodial — dana tetap 100% di exchange milik Anda.",
    en: "• Slippage, latency & market loss risks are 100% your responsibility.\n• The developer is not liable for exchange API failures.\n• NEVER tick the \"Enable Withdrawals\" permission on your exchange API key.\n• Non-custodial app — funds stay 100% on your own exchange.",
    ru: "• Риски проскальзывания, задержек и убытков — 100% ваша ответственность.\n• Разработчик не отвечает за сбои API биржи.\n• НИКОГДА не включайте разрешение «Enable Withdrawals» для API-ключа.\n• Некастодиальное приложение — средства на 100% остаются на вашей бирже.",
    cn: "• 滑点、延迟与市场亏损风险 100% 由您承担。\n• 开发者不对交易所 API 故障负责。\n• 切勿在交易所 API 密钥上勾选\"Enable Withdrawals\"权限。\n• 非托管应用 — 资金 100% 保留在您自己的交易所。",
  },
  asi_disc_ack: { id: "Saya mengerti & menerima semua risiko di atas", en: "I understand & accept all risks above", ru: "Я понимаю и принимаю все риски выше", cn: "我已理解并接受以上所有风险" },
  asi_legal_link: { id: "Baca Terms, Privacy & Compliance Lengkap →", en: "Read full Terms, Privacy & Compliance →", ru: "Полные Условия и Конфиденциальность →", cn: "阅读完整条款、隐私与合规 →" },
  asi_sec_tp: { id: "Strategi Take Profit", en: "Take Profit Strategy", ru: "Стратегия Take Profit", cn: "止盈策略" },
  asi_tp_hint: {
    id: "Pilih berapa target TP. Trailing Stop otomatis aktif setelah TP1 tercapai untuk mengunci profit.",
    en: "Choose how many TP targets. Trailing Stop auto-activates after TP1 is hit to lock in profits.",
    ru: "Выберите количество TP. Trailing Stop активируется после TP1, чтобы зафиксировать прибыль.",
    cn: "选择 TP 目标数量。TP1 达成后自动启用追踪止损以锁定利润。",
  },
  asi_tp_1_label: { id: "1 TP · 100%", en: "1 TP · 100%", ru: "1 TP · 100%", cn: "1 TP · 100%" },
  asi_tp_2_label: { id: "2 TP · 50/50", en: "2 TP · 50/50", ru: "2 TP · 50/50", cn: "2 TP · 50/50" },
  asi_tp_3_label: { id: "3 TP · 33/33/34", en: "3 TP · 33/33/34", ru: "3 TP · 33/33/34", cn: "3 TP · 33/33/34" },
  asi_trailing_label: { id: "Trailing Stop Callback", en: "Trailing Stop Callback", ru: "Trailing Stop Callback", cn: "追踪止损回调" },
  asi_trailing_hint: {
    id: "SL otomatis mengikuti harga puncak dengan jarak X% (native Binance). 0 = nonaktif. Aktif setelah TP1.",
    en: "SL auto-trails the peak price by X% (native Binance). 0 = disabled. Activates after TP1.",
    ru: "SL автоматически следует за пиковой ценой на X% (нативно Binance). 0 = выкл. Активно после TP1.",
    cn: "SL 自动跟随峰值价格 X%（币安原生）。0 = 关闭。TP1 后生效。",
  },
  asi_sec_pnl: { id: "Rekap PnL", en: "PnL Summary", ru: "Сводка PnL", cn: "盈亏汇总" },
  asi_pnl_daily: { id: "Hari Ini", en: "Today", ru: "Сегодня", cn: "今日" },
  asi_pnl_weekly: { id: "Minggu", en: "Week", ru: "Неделя", cn: "本周" },
  asi_pnl_monthly: { id: "Bulan", en: "Month", ru: "Месяц", cn: "本月" },
  asi_sec_recent: { id: "Trade Terbaru", en: "Recent Trades", ru: "Последние сделки", cn: "最近交易" },
  asi_alert_need_title: { id: "Butuh Koneksi + Persetujuan", en: "Connection + Consent Required", ru: "Нужно подключение + согласие", cn: "需要连接 + 同意" },
  asi_alert_need_connect: { id: "Hubungkan API exchange terlebih dahulu.", en: "Connect your exchange API first.", ru: "Сначала подключите API биржи.", cn: "请先连接交易所 API。" },
  asi_alert_need_ack: { id: "Centang persetujuan disclaimer sebelum mengaktifkan bot.", en: "Tick the disclaimer consent before enabling the bot.", ru: "Отметьте согласие с дисклеймером перед включением бота.", cn: "启用机器人前请勾选免责声明同意。" },
  asi_connect_title: { id: "Hubungkan {ex}", en: "Connect {ex}", ru: "Подключить {ex}", cn: "连接 {ex}" },
  asi_connect_sub: {
    id: "Masukkan API Key & Secret ANDA sendiri. Dana tetap 100% aman di akun exchange Anda (non-custodial).",
    en: "Enter YOUR OWN API Key & Secret. Funds stay 100% safe on your exchange account (non-custodial).",
    ru: "Введите ВАШИ собственные API Key и Secret. Средства на 100% остаются на вашей бирже (некастодиально).",
    cn: "请输入您自己的 API Key 和 Secret。资金 100% 保留在您的交易所账户（非托管）。",
  },
  asi_net_mainnet_sub: { id: "Uang nyata", en: "Real money", ru: "Реальные деньги", cn: "真实资金" },
  asi_net_testnet_sub: { id: "Uji coba gratis", en: "Free sandbox", ru: "Бесплатный тест", cn: "免费模拟" },
  asi_ip_title: { id: "IP Whitelist Server (Wajib di Binance)", en: "Server IP Whitelist (Required on Binance)", ru: "IP-whitelist сервера (обязательно на Binance)", cn: "服务器 IP 白名单（币安必填）" },
  asi_ip_sub: { id: "Binance mewajibkan pembatasan IP untuk API key berizin Futures:", en: "Binance requires IP restriction for Futures-enabled API keys:", ru: "Binance требует ограничения по IP для API-ключей с Futures:", cn: "币安要求启用合约权限的 API 密钥设置 IP 限制：" },
  asi_ip_label: { id: "IP STATIS SERVER ASI-BOT", en: "ASI-BOT STATIC SERVER IP", ru: "СТАТИЧЕСКИЙ IP СЕРВЕРА ASI-BOT", cn: "ASI-BOT 服务器静态 IP" },
  asi_ip_copy: { id: "Salin IP", en: "Copy IP", ru: "Копировать IP", cn: "复制 IP" },
  asi_ip_copied: { id: "Tersalin!", en: "Copied!", ru: "Скопировано!", cn: "已复制！" },
  asi_ip_step1: { id: "1️⃣ Centang \"Enable Futures\"", en: "1️⃣ Tick \"Enable Futures\"", ru: "1️⃣ Отметьте «Enable Futures»", cn: "1️⃣ 勾选 \"Enable Futures\"" },
  asi_ip_step2: { id: "2️⃣ JANGAN centang \"Enable Withdrawals\"", en: "2️⃣ DO NOT tick \"Enable Withdrawals\"", ru: "2️⃣ НЕ отмечайте «Enable Withdrawals»", cn: "2️⃣ 请勿勾选 \"Enable Withdrawals\"" },
  asi_ip_step3: { id: "3️⃣ Pilih \"Restrict access to trusted IPs only\"", en: "3️⃣ Select \"Restrict access to trusted IPs only\"", ru: "3️⃣ Выберите «Restrict access to trusted IPs only»", cn: "3️⃣ 选择 \"Restrict access to trusted IPs only\"" },
  asi_ip_step4: { id: "4️⃣ Paste IP di atas ke kotak Binance lalu klik \"Confirm\"", en: "4️⃣ Paste the IP above into Binance then click \"Confirm\"", ru: "4️⃣ Вставьте IP выше в Binance и нажмите «Confirm»", cn: "4️⃣ 将上方 IP 粘贴到币安并点击 \"Confirm\"" },
  asi_alert_fill_title: { id: "Lengkapi", en: "Incomplete", ru: "Заполните", cn: "请填写完整" },
  asi_alert_fill_body: { id: "API Key & Secret wajib diisi.", en: "API Key & Secret are required.", ru: "API Key и Secret обязательны.", cn: "API Key 和 Secret 为必填项。" },
  asi_alert_pass_body: { id: "{ex} butuh passphrase.", en: "{ex} requires a passphrase.", ru: "{ex} требует passphrase.", cn: "{ex} 需要密码短语。" },
  asi_alert_mainnet_title: { id: "Konfirmasi Mainnet", en: "Mainnet Confirmation", ru: "Подтверждение Mainnet", cn: "主网确认" },
  asi_alert_mainnet_body: {
    id: "Anda akan menghubungkan akun UANG NYATA. Pastikan API key TIDAK memiliki izin Withdraw. Centang persetujuan dulu.",
    en: "You are connecting a REAL MONEY account. Make sure the API key has NO Withdraw permission. Tick the consent first.",
    ru: "Вы подключаете счёт с РЕАЛЬНЫМИ деньгами. Убедитесь, что у API-ключа НЕТ разрешения на вывод. Сначала отметьте согласие.",
    cn: "您正在连接真实资金账户。请确保 API 密钥没有提现权限。请先勾选同意。",
  },
  asi_mainnet_ack: {
    id: "Saya paham ini akun UANG NYATA dan API key saya TANPA izin penarikan (withdraw). Risiko 100% tanggung jawab saya.",
    en: "I understand this is a REAL MONEY account and my API key has NO withdrawal permission. Risk is 100% my responsibility.",
    ru: "Я понимаю, что это счёт с РЕАЛЬНЫМИ деньгами, и у моего API-ключа НЕТ разрешения на вывод. Риск 100% на мне.",
    cn: "我明白这是真实资金账户，且我的 API 密钥没有提现权限。风险 100% 由我承担。",
  },
  asi_verifying: { id: "MEMVERIFIKASI...", en: "VERIFYING...", ru: "ПРОВЕРКА...", cn: "验证中..." },
  asi_save_mainnet: { id: "SIMPAN KE MAINNET", en: "SAVE TO MAINNET", ru: "СОХРАНИТЬ В MAINNET", cn: "保存到主网" },
  asi_save_testnet: { id: "SIMPAN KE TESTNET", en: "SAVE TO TESTNET", ru: "СОХРАНИТЬ В TESTNET", cn: "保存到测试网" },
  asi_alert_fail_title: { id: "Gagal", en: "Failed", ru: "Ошибка", cn: "失败" },

  // v9.7.4 — START/STOP button + deactivation dialog
  asi_status_running: { id: "RUNNING", en: "RUNNING", ru: "РАБОТАЕТ", cn: "运行中" },
  asi_status_stopped: { id: "STOPPED", en: "STOPPED", ru: "ОСТАНОВЛЕН", cn: "已停止" },
  asi_stop_hint: {
    id: "Stop hanya menghentikan trade BARU — posisi terbuka tetap dijaga SL/TP native di Binance sampai close sesuai parameter.",
    en: "Stop only halts NEW trades — open positions stay protected by native SL/TP on Binance until they close per their parameters.",
    ru: "Стоп останавливает только НОВЫЕ сделки — открытые позиции защищены нативными SL/TP на Binance до закрытия по параметрам.",
    cn: "停止仅阻止新开仓——未平仓头寸仍由币安原生 SL/TP 保护，直至按参数平仓。",
  },
  asi_recent_empty: {
    id: "Belum ada trade. Bot akan mengeksekusi otomatis saat sinyal memenuhi syarat — posisi open/closed lengkap dengan PnL $ dan % akan tampil di sini.",
    en: "No trades yet. The bot will auto-execute when signals qualify — open/closed positions with full $ and % PnL will appear here.",
    ru: "Сделок пока нет. Бот исполнит автоматически при подходящем сигнале — открытые/закрытые позиции с PnL в $ и % появятся здесь.",
    cn: "暂无交易。当信号符合条件时机器人将自动执行——持仓/已平仓及完整的 $ 和 % 盈亏将显示在此处。",
  },
  asi_run_bot: { id: "▶ START BOT", en: "▶ START BOT", ru: "▶ ЗАПУСТИТЬ БОТА", cn: "▶ 启动机器人" },
  asi_stop_bot: { id: "■ STOP BOT", en: "■ STOP BOT", ru: "■ ОСТАНОВИТЬ", cn: "■ 停止机器人" },
  asi_running_hint: { id: "Bot aktif — memindai pasar tiap 5 menit & eksekusi otomatis saat sinyal lolos.", en: "Bot is running — scans the market every 5 minutes & auto-executes when signals qualify.", ru: "Бот работает — сканирует рынок каждые 5 минут и исполняет при подходящих сигналах.", cn: "机器人运行中——每 5 分钟扫描市场，信号合格时自动执行。" },
  asi_running_hint_semi: {
    id: "Bot aktif (Semi-Auto) — buka AI Suggestions, pilih sinyal, lalu konfirmasi eksekusi. Posisi terjaga SL/TP native.",
    en: "Bot active (Semi-Auto) — open AI Suggestions, pick a signal, then confirm execution. Positions stay protected by native SL/TP.",
    ru: "Бот активен (Semi-Auto) — откройте AI Suggestions, выберите сигнал и подтвердите исполнение. Позиции защищены нативным SL/TP.",
    cn: "机器人已激活（半自动）——打开 AI 建议，选择信号后确认执行。持仓由原生 SL/TP 保护。",
  },

  // v9.7.6 — Independent Semi / Full status cards + manual close
  asi_card_semi_title: { id: "Semi-Auto", en: "Semi-Auto", ru: "Semi-Auto", cn: "半自动" },
  asi_card_full_title: { id: "Full-Auto", en: "Full-Auto", ru: "Full-Auto", cn: "全自动" },
  asi_card_semi_sub_on: {
    id: "Siap eksekusi 1-tap dari AI Suggestions. SL/TP native aktif.",
    en: "Ready for 1-tap execution from AI Suggestions. Native SL/TP armed.",
    ru: "Готов к 1-клик исполнению из AI Suggestions. Нативный SL/TP активен.",
    cn: "可从 AI 建议一键执行。原生 SL/TP 已激活。",
  },
  asi_card_semi_sub_off: {
    id: "Nyalakan untuk membuka eksekusi 1-tap pada sinyal baru.",
    en: "Turn on to unlock 1-tap execution on new signals.",
    ru: "Включите, чтобы разблокировать 1-клик исполнение на новых сигналах.",
    cn: "开启以解锁对新信号的一键执行。",
  },
  asi_card_full_sub_on: {
    id: "Pemindai berjalan di background tiap 5 menit — eksekusi otomatis saat sinyal lolos.",
    en: "Scanner running in background every 5 minutes — auto-executes when signals qualify.",
    ru: "Сканер работает в фоне каждые 5 минут — автоисполнение при подходящих сигналах.",
    cn: "后台扫描每 5 分钟运行一次——信号合格时自动执行。",
  },
  asi_card_full_sub_off: {
    id: "Nyalakan untuk membiarkan ASI memindai & trading otomatis selama 24/7.",
    en: "Turn on to let ASI scan & auto-trade 24/7 in the background.",
    ru: "Включите, чтобы ASI сканировал и торговал автоматически 24/7.",
    cn: "开启以让 ASI 全天候后台扫描并自动交易。",
  },
  asi_recent_close: { id: "TUTUP", en: "CLOSE", ru: "ЗАКРЫТЬ", cn: "平仓" },
  asi_recent_closing: { id: "menutup…", en: "closing…", ru: "закрытие…", cn: "平仓中…" },
  asi_badge_semi: { id: "SEMI", en: "SEMI", ru: "SEMI", cn: "半自动" },
  asi_badge_full: { id: "FULL", en: "FULL", ru: "FULL", cn: "全自动" },
  asi_close_failed: {
    id: "Gagal menutup posisi",
    en: "Failed to close position",
    ru: "Не удалось закрыть позицию",
    cn: "平仓失败",
  },
  // v9.7.7 — Semi tidak punya STOP; cukup READY + tombol PILIH SINYAL.
  asi_semi_ready: { id: "SIAP", en: "READY", ru: "ГОТОВО", cn: "就绪" },
  asi_card_semi_sub_ready: {
    id: "Pilih sinyal dari AI Suggestions, lalu eksekusi 1-tap. Posisi langsung muncul di Recent Trades dengan SL/TP native aktif.",
    en: "Pick a signal from AI Suggestions and execute in 1-tap. The position appears instantly in Recent Trades with native SL/TP armed.",
    ru: "Выберите сигнал в AI Suggestions и исполните в 1 клик. Позиция сразу появится в Recent Trades с нативным SL/TP.",
    cn: "从 AI 建议中选择信号并一键执行。持仓立即出现在最近交易中，原生 SL/TP 已激活。",
  },
  asi_pick_signal: {
    id: "🎯 PILIH SINYAL",
    en: "🎯 PICK A SIGNAL",
    ru: "🎯 ВЫБРАТЬ СИГНАЛ",
    cn: "🎯 选择信号",
  },
  asi_scanning: {
    id: "🔎 Memindai sinyal…",
    en: "🔎 Scanning signals…",
    ru: "🔎 Поиск сигналов…",
    cn: "🔎 正在扫描信号…",
  },
  asi_no_signal_title: {
    id: "Belum Ada Sinyal",
    en: "No Signal Available",
    ru: "Сигналов пока нет",
    cn: "暂无信号",
  },
  asi_no_signal_body: {
    id: "Belum ada sinyal valid untuk profile {profile} saat ini. Coba lagi beberapa menit lagi atau ganti profile di bagian Mode.",
    en: "No valid signal for the {profile} profile right now. Try again in a few minutes or switch profile in the Mode section.",
    ru: "Сейчас нет валидных сигналов для профиля {profile}. Повторите через несколько минут или смените профиль в разделе Mode.",
    cn: "当前没有 {profile} 配置的有效信号。请稍后再试，或在模式部分切换配置。",
  },
  // v9.7.8 — AI Suggestions one-tap execute button + success Alert.
  ai_trade_execute_semi: {
    id: "EKSEKUSI SEMI-AUTO",
    en: "EXECUTE SEMI-AUTO",
    ru: "ВЫПОЛНИТЬ SEMI-AUTO",
    cn: "执行半自动",
  },
  asi_exec_success_title: {
    id: "✅ Order Terkirim",
    en: "✅ Order Submitted",
    ru: "✅ Ордер отправлен",
    cn: "✅ 订单已提交",
  },
  asi_exec_view_recent: {
    id: "Lihat Recent Trades",
    en: "View Recent Trades",
    ru: "К последним сделкам",
    cn: "查看最近交易",
  },
  common_close: {
    id: "Tutup",
    en: "Close",
    ru: "Закрыть",
    cn: "关闭",
  },
  asi_hint_concurrent: {
    id: "Keduanya bisa dijalankan bersamaan — status masing-masing diperbarui independen.",
    en: "Both can run simultaneously — each status updates independently.",
    ru: "Оба могут работать одновременно — статусы обновляются независимо.",
    cn: "两者可同时运行——各自状态独立更新。",
  },

  // v9.8.3 — AsiTradeSheet full localization (id/en/ru/cn)
  ats_subtitle: {
    id: "Trade dengan ASI-Bot (Semi-Auto)",
    en: "Trade with ASI-Bot (Semi-Auto)",
    ru: "Сделка через ASI-Bot (Semi-Auto)",
    cn: "使用 ASI-Bot 交易（半自动）",
  },
  ats_no_cred_title: {
    id: "Belum terhubung ke exchange",
    en: "Not connected to an exchange",
    ru: "Нет подключения к бирже",
    cn: "尚未连接交易所",
  },
  ats_no_cred_body: {
    id: "Hubungkan API Binance / Bybit / OKX / Bitget di halaman ASI-Bot sebelum trade otomatis.",
    en: "Connect your Binance / Bybit / OKX / Bitget API on the ASI-Bot page before auto-trading.",
    ru: "Подключите API Binance / Bybit / OKX / Bitget на странице ASI-Bot перед автоторговлей.",
    cn: "请先在 ASI-Bot 页面连接 Binance / Bybit / OKX / Bitget API，然后再进行自动交易。",
  },
  ats_connect_cta: {
    id: "HUBUNGKAN EXCHANGE",
    en: "CONNECT EXCHANGE",
    ru: "ПОДКЛЮЧИТЬ БИРЖУ",
    cn: "连接交易所",
  },
  ats_risk_per_trade: { id: "Risiko per Trade", en: "Risk per Trade", ru: "Риск на сделку", cn: "每笔交易风险" },
  ats_leverage: { id: "Leverage", en: "Leverage", ru: "Плечо", cn: "杠杆" },
  ats_trailing_cb: {
    id: "Trailing Callback (setelah TP1)",
    en: "Trailing Callback (after TP1)",
    ru: "Трейлинг-колбэк (после TP1)",
    cn: "追踪回调（TP1 之后）",
  },
  ats_calculating: { id: "Menghitung preview…", en: "Calculating preview…", ru: "Расчёт превью…", cn: "正在计算预览…" },
  ats_balance: { id: "Saldo USDT", en: "USDT Balance", ru: "Баланс USDT", cn: "USDT 余额" },
  ats_margin: { id: "Margin Dipakai", en: "Margin Used", ru: "Используемая маржа", cn: "已用保证金" },
  ats_size: { id: "Ukuran Posisi", en: "Position Size", ru: "Размер позиции", cn: "仓位规模" },
  ats_est_loss: { id: "Potensi Rugi (SL)", en: "Est. Loss (SL)", ru: "Оцен. убыток (SL)", cn: "预计亏损 (SL)" },
  ats_profit: { id: "Profit", en: "Profit", ru: "Профит", cn: "盈利" },
  ats_no_preview: { id: "Preview belum tersedia.", en: "Preview not available.", ru: "Превью недоступно.", cn: "预览不可用。" },
  ats_sending: { id: "MENGIRIM ORDER…", en: "SENDING ORDER…", ru: "ОТПРАВКА ОРДЕРА…", cn: "正在发送订单…" },
  ats_footer1: {
    id: "Bracket SL + TP1/TP2/TP3 otomatis terpasang.",
    en: "Bracket SL + TP1/TP2/TP3 is placed automatically.",
    ru: "Скобка SL + TP1/TP2/TP3 выставляется автоматически.",
    cn: "SL + TP1/TP2/TP3 括号单自动挂出。",
  },
  ats_footer2: {
    id: "Risiko slippage & kerugian pasar 100% tanggung jawab Anda.",
    en: "Slippage & market-loss risk is 100% your responsibility.",
    ru: "Риск проскальзывания и убытков — полностью ваша ответственность.",
    cn: "滑点与市场亏损风险 100% 由您自行承担。",
  },
  ats_dup_title: { id: "Posisi Sudah Terbuka", en: "Position Already Open", ru: "Позиция уже открыта", cn: "已有持仓" },
  ats_dup_body: {
    id: "Anda sudah punya posisi {side} {symbol} aktif di {exchange} (PnL ${pnl}).\n\nTambah posisi lagi (pyramid)?",
    en: "You already have an open {side} {symbol} position on {exchange} (PnL ${pnl}).\n\nAdd another position (pyramid)?",
    ru: "У вас уже есть открытая позиция {side} {symbol} на {exchange} (PnL ${pnl}).\n\nДобавить ещё позицию (пирамидинг)?",
    cn: "您在 {exchange} 已有 {side} {symbol} 持仓（盈亏 ${pnl}）。\n\n要加仓（金字塔）吗？",
  },
  ats_dup_cancel: { id: "Batal", en: "Cancel", ru: "Отмена", cn: "取消" },
  ats_dup_add: { id: "Ya, tambah", en: "Yes, add", ru: "Да, добавить", cn: "是，加仓" },
  ats_exec_failed: { id: "Gagal Eksekusi", en: "Execution Failed", ru: "Ошибка исполнения", cn: "执行失败" },
  ats_err_not_listed: {
    id: "{symbol} tidak tersedia sebagai perpetual USDT di exchange ini.",
    en: "{symbol} is not available as a USDT perpetual on this exchange.",
    ru: "{symbol} недоступен как USDT-перпетуал на этой бирже.",
    cn: "{symbol} 在该交易所没有 USDT 永续合约。",
  },
  ats_err_inactive: {
    id: "{symbol} sedang tidak aktif di exchange ini.",
    en: "{symbol} is currently inactive on this exchange.",
    ru: "{symbol} сейчас неактивен на этой бирже.",
    cn: "{symbol} 当前在该交易所不可用。",
  },
  ai_not_tradable: {
    id: "Tidak tersedia di Binance Futures",
    en: "Not available on Binance Futures",
    ru: "Недоступен на Binance Futures",
    cn: "Binance 合约不可用",
  },
  // v9.8.5 — In-sheet execution result (Alert tidak tampil di web preview)
  ats_exec_done: {
    id: "✅ Order Berhasil Dieksekusi",
    en: "✅ Order Successfully Executed",
    ru: "✅ Ордер успешно исполнен",
    cn: "✅ 订单已成功执行",
  },
  ats_executed_btn: {
    id: "TEREKSEKUSI",
    en: "EXECUTED",
    ru: "ИСПОЛНЕНО",
    cn: "已执行",
  },
  ats_try_again: { id: "Coba Lagi", en: "Try Again", ru: "Повторить", cn: "重试" },
  // v9.9.0 — Margin mode selector + bracket repair
  ats_margin_mode: { id: "Margin Mode", en: "Margin Mode", ru: "Режим маржи", cn: "保证金模式" },
  ats_margin_isolated: { id: "ISOLATED", en: "ISOLATED", ru: "ИЗОЛИРОВАННАЯ", cn: "逐仓" },
  ats_margin_cross: { id: "CROSS", en: "CROSS", ru: "КРОСС", cn: "全仓" },
  ats_bracket_native: {
    id: "SL/TP dipasang native di Binance — tetap bekerja walau app ditutup. Isolated: rugi terbatas margin posisi. Cross: seluruh saldo jadi jaminan.",
    en: "SL/TP are placed natively on Binance — they keep working even if the app is closed. Isolated: loss limited to position margin. Cross: entire futures balance is collateral.",
    ru: "SL/TP выставляются нативно на Binance — работают даже при закрытом приложении. Isolated: убыток ограничен маржой позиции. Cross: залогом является весь баланс фьючерсов.",
    cn: "SL/TP 以原生方式挂在 Binance——即使关闭 App 也持续生效。逐仓：亏损仅限仓位保证金。全仓：整个合约余额作为担保。",
  },
  asi_repair_cta: {
    id: "⚠️ Ada posisi TANPA SL/TP native — ketuk untuk pasang ulang",
    en: "⚠️ Open positions WITHOUT native SL/TP — tap to re-attach",
    ru: "⚠️ Есть позиции БЕЗ нативных SL/TP — нажмите, чтобы перевыставить",
    cn: "⚠️ 有持仓缺少原生 SL/TP——点击重新挂出",
  },
  asi_repair_title: { id: "Perbaikan Bracket", en: "Bracket Repair", ru: "Восстановление скобок", cn: "修复括号单" },
  asi_repair_ok: {
    id: "Berhasil memasang SL/TP native untuk {n} posisi.",
    en: "Successfully attached native SL/TP for {n} position(s).",
    ru: "Нативные SL/TP выставлены для {n} позиций.",
    cn: "已为 {n} 个持仓挂出原生 SL/TP。",
  },
  asi_soft_warn_title: { id: "SL/TP Native Hilang", en: "Native SL/TP Missing", ru: "Нет нативных SL/TP", cn: "缺少原生 SL/TP" },
  asi_soft_warn_body: {
    id: "Bracket native gagal terpasang. Posisi dipantau watcher backend (soft). Ketuk banner merah di atas untuk memasang ulang.",
    en: "Native bracket failed to attach. The position is monitored by the backend watcher (soft). Tap the red banner above to re-attach.",
    ru: "Нативная скобка не выставлена. Позицию отслеживает бэкенд-наблюдатель (soft). Нажмите красный баннер выше, чтобы перевыставить.",
    cn: "原生括号单未能挂出。该持仓由后台监控器（软）看护。点击上方红色横幅重新挂出。",
  },
  ats_err_min_notional: {
    id: "Ukuran posisi ${size} di bawah minimum exchange (${min}). Naikkan Risk % atau Leverage.",
    en: "Position size ${size} is below the exchange minimum (${min}). Raise Risk % or Leverage.",
    ru: "Размер позиции ${size} ниже минимума биржи (${min}). Увеличьте риск % или плечо.",
    cn: "仓位规模 ${size} 低于交易所最小值（${min}）。请提高风险 % 或杠杆。",
  },

  // v9.6.9 — Credential validation error codes (backend returns {code, message})
  asi_err_ip_or_key_invalid: {
    id: "API Key/Secret salah ATAU IP server (143.198.197.107) belum di-whitelist di Binance.",
    en: "Invalid API Key/Secret OR server IP (143.198.197.107) not whitelisted in Binance.",
    ru: "Неверный API Key/Secret ИЛИ IP сервера (143.198.197.107) не добавлен в whitelist Binance.",
    cn: "API Key/Secret 错误，或服务器 IP (143.198.197.107) 未加入 Binance 白名单。",
  },
  asi_err_key_format_invalid: {
    id: "Format API key tidak valid. Periksa salinan key Anda.",
    en: "Invalid API key format. Please check your key.",
    ru: "Неверный формат API key. Проверьте ключ.",
    cn: "API key 格式无效，请检查。",
  },
  asi_err_region_blocked: {
    id: "Binance menolak lokasi server (HTTP 451). Hubungi admin.",
    en: "Binance rejected server location (HTTP 451). Contact admin.",
    ru: "Binance отклонил локацию сервера (HTTP 451). Свяжитесь с администратором.",
    cn: "Binance 拒绝服务器所在地区 (HTTP 451)，请联系管理员。",
  },
  asi_err_withdraw_enabled: {
    id: "API key Anda MEMILIKI izin PENARIKAN. ASI-Bot MENOLAK key seperti ini. Buat key baru TANPA 'Enable Withdrawals'.",
    en: "Your API key has WITHDRAW permission. ASI-Bot refuses such keys. Create a new key WITHOUT 'Enable Withdrawals'.",
    ru: "Ваш API ключ имеет разрешение на ВЫВОД. ASI-Bot отклоняет такие ключи. Создайте новый ключ БЕЗ 'Enable Withdrawals'.",
    cn: "您的 API 密钥已启用提现权限，ASI-Bot 拒绝使用此类密钥。请创建新密钥并关闭 'Enable Withdrawals'。",
  },
  asi_err_trade_disabled: {
    id: "API key tidak punya izin trading. Centang 'Enable Futures' di Binance.",
    en: "API key has no trading permission. Enable 'Futures' in Binance API Management.",
    ru: "У API ключа нет разрешения на торговлю. Включите 'Futures' в Binance.",
    cn: "API 密钥没有交易权限，请在 Binance 启用 'Futures'。",
  },
  asi_err_proxy_down: {
    id: "Relay IP server tidak dapat dihubungi. Mohon hubungi admin aplikasi.",
    en: "Server IP relay is unreachable. Please contact the app admin.",
    ru: "Релей IP сервера недоступен. Свяжитесь с администратором приложения.",
    cn: "服务器 IP 中继无法访问，请联系应用管理员。",
  },
  asi_err_auth_failed: {
    id: "Autentikasi API key gagal.",
    en: "API key authentication failed.",
    ru: "Ошибка авторизации API ключа.",
    cn: "API 密钥认证失败。",
  },

  // v9.5.0 — Copy Trade page
  copy_sub: { id: "10 trader yang SEDANG di posisi · hilang otomatis bila closed", en: "Top 10 traders CURRENTLY in positions · auto-removed when closed", ru: "Топ-10 трейдеров в позициях · исчезают при закрытии", cn: "当前持仓前 10 名交易者 · 平仓后自动消失" },
  copy_loading: { id: "Memuat posisi aktif…", en: "Loading active positions…", ru: "Загрузка активных позиций…", cn: "正在加载持仓…" },
  copy_empty_title: { id: "Tidak ada posisi aktif saat ini", en: "No active positions right now", ru: "Сейчас нет активных позиций", cn: "当前没有持仓" },
  copy_empty_body: {
    id: "Trader akan muncul di sini saat mereka\nmembuka posisi lewat ASI-Bot. Daftar akan refresh otomatis tiap 15 detik.",
    en: "Traders will appear here when they\nopen positions via ASI-Bot. The list auto-refreshes every 15 seconds.",
    ru: "Трейдеры появятся здесь, когда\nоткроют позиции через ASI-Bot. Список обновляется каждые 15 секунд.",
    cn: "当交易者通过 ASI-Bot 开仓时\n将显示在此处。列表每 15 秒自动刷新。",
  },
  copy_open_count: { id: "{n} POS AKTIF", en: "{n} OPEN POS", ru: "{n} ОТКР. ПОЗ.", cn: "{n} 个持仓" },
  copy_wr_line: { id: "WR 30h: {wr}% · {n} trade closed", en: "WR 30d: {wr}% · {n} closed trades", ru: "WR 30д: {wr}% · {n} закрытых", cn: "30天胜率: {wr}% · {n} 笔已平仓" },
  copy_unrealized: { id: "UNREALIZED", en: "UNREALIZED", ru: "НЕРЕАЛИЗ.", cn: "未实现" },
  copy_entry_line: { id: "Entry ${price} · dibuka {ago}", en: "Entry ${price} · opened {ago}", ru: "Вход ${price} · открыта {ago}", cn: "入场 ${price} · {ago}开仓" },
  copy_execute: { id: "EXECUTE", en: "EXECUTE", ru: "EXECUTE", cn: "EXECUTE" },
  copy_footer: { id: "Daftar refresh tiap 15 detik · trader hilang otomatis saat posisi mereka ditutup.", en: "List refreshes every 15 seconds · traders auto-removed when their positions close.", ru: "Обновление каждые 15 секунд · трейдеры исчезают при закрытии позиций.", cn: "列表每 15 秒刷新 · 交易者平仓后自动移除。" },

  // v9.6.4 — Premium gate (ASI-Bot & Copy Trade)
  premium_locked_title: { id: "Fitur Khusus Premium", en: "Premium Members Only", ru: "Только для Premium", cn: "仅限高级会员" },
  premium_locked_asi_body: {
    id: "ASI-Bot auto-trading hanya tersedia untuk member premium. Upgrade untuk menghubungkan exchange Anda dan mulai trading otomatis dengan SL/TP native.",
    en: "ASI-Bot auto-trading is available for premium members only. Upgrade to connect your exchange and start automated trading with native SL/TP.",
    ru: "ASI-Bot автоторговля доступна только Premium-участникам. Обновите, чтобы подключить биржу и торговать автоматически с нативным SL/TP.",
    cn: "ASI-Bot 自动交易仅限高级会员使用。升级以连接您的交易所并开始自动交易（含原生止损/止盈）。",
  },
  premium_locked_copy_body: {
    id: "Copy Trade live leaderboard hanya tersedia untuk member premium. Upgrade untuk memantau dan menyalin posisi top trader secara real-time.",
    en: "Copy Trade live leaderboard is available for premium members only. Upgrade to watch and copy top traders' positions in real-time.",
    ru: "Live-таблица Copy Trade доступна только Premium-участникам. Обновите, чтобы следить и копировать позиции топ-трейдеров в реальном времени.",
    cn: "Copy Trade 实时排行榜仅限高级会员使用。升级以实时查看并复制顶级交易者的持仓。",
  },
  asi_trade_cta: { id: "Trade {side} dengan ASI-Bot", en: "Trade {side} with ASI-Bot", ru: "Сделка {side} с ASI-Bot", cn: "用 ASI-Bot 交易 {side}" },
  premium_locked_cta: { id: "UPGRADE KE PREMIUM", en: "UPGRADE TO PREMIUM", ru: "ОБНОВИТЬ ДО PREMIUM", cn: "升级到高级版" },
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
