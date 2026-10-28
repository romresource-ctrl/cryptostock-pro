import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";
// v10.1.1 — Touchable dari RNGH untuk KARTU trade: bernegosiasi dengan
// gesture Swipeable sehingga swipe-delete TIDAK memicu navigasi tap.
import { TouchableOpacity as CardTouchable } from "react-native-gesture-handler";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { usePremiumAccess } from "@/src/lib/usePremiumAccess";
import { useTraderProfile, PROFILE_META } from "@/src/lib/useTraderProfile";
import { prefetchChart } from "@/src/lib/chartCache";
import { readPageCache, writePageCache } from "@/src/lib/pageCache";
import { useBinanceMultiTicker } from "@/src/hooks/useBinanceMultiTicker";
import { markTradeDeleted, filterDeletedTrades } from "@/src/lib/deletedTrades";
import PremiumLocked from "@/src/components/PremiumLocked";
import SizingSelector from "@/src/components/SizingSelector";
import AISuggestionsSheet from "@/src/components/AISuggestionsSheet";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, formatPrice, type AsiBotConfig, type AsiCredential,
  type AsiPnl, type AsiTradeResp,
} from "@/src/lib/api";

const GOLD = "#4ADE80"; // v9.4.1 — primary ASI-Bot accent (hijau muda)
// v10.1.1 — Warna chip BOT ENGINE ASI-Bot dibuat biru terang supaya tidak
// monoton hijau (diminta user): beda dari Titan-Bot (ungu), Full-Auto
// (oranye), Semi-Auto (hijau).
const ASI_BLUE = "#3B82F6";
const YELLOW = "#F0B90B"; // v10.0.1 — kuning asli utk Limit Price / chip LIMIT
const ORANGE = "#F97316"; // v9.6.3 — Full-Auto active accent
const PINK = "#EC4899"; // v9.7.4 — START BOT button
const LIGHT_BLUE = "#38BDF8"; // v9.7.4 — STOP BOT button
const GREEN = "#22C55E";
const RED = "#EF4444";
const ACCENT_TEXT = "#FFFFFF"; // teks di atas tombol primary
const TEAL = "#2DD4BF"; // v9.9.0 — badge margin ISOLATED
const PURPLE = "#A78BFA"; // v9.9.0 — badge margin CROSS

type ExchangeId = "binance" | "bybit" | "okx" | "bitget";
const EXCHANGES: { id: ExchangeId; label: string; needsPass: boolean }[] = [
  { id: "binance", label: "Binance Futures", needsPass: false },
  { id: "bybit",   label: "Bybit Perpetual",  needsPass: false },
  { id: "okx",     label: "OKX Swap",         needsPass: true  },
  { id: "bitget",  label: "Bitget Futures",   needsPass: true  },
];

export default function ASIBotScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const { hasAccess, loaded: accessLoaded } = usePremiumAccess();
  // v9.8.0 — Baca Trader Profile aktif dari hook global (bukan dari
  // bot.profile backend). Sinkron dengan ikon header & modal picker.
  const { profile: traderProfile, explicit: traderExplicit, apiProfile } = useTraderProfile();
  const [deviceId, setDeviceId] = useState<string>("");
  const [creds, setCreds] = useState<AsiCredential[]>([]);
  // v9.8.0 — flag yang menandakan refresh pertama selesai, agar PICK A
  // SIGNAL tidak keliru menampilkan "need_connect" saat state belum terisi.
  const [credsLoaded, setCredsLoaded] = useState(false);
  const [bot, setBot] = useState<AsiBotConfig>({
    enabled: false, exchange: "binance", mode: "semi",
    max_trades_per_day: 5, risk_pct: 5, leverage: 10, whitelist: [], profile: "confluence",
    min_confidence: 75, daily_loss_limit_usdt: 0,
    tp_count: 3, trailing_callback_rate: 2,
    // v9.7.6 — independent toggles
    semi_enabled: false, full_enabled: false,
    // v9.7.7 — persistent disclaimer
    disclaimer_ack: false,
    // v9.9.5 — network aktif (credential mainnet/testnet slot terpisah)
    active_testnet: true,
    // v10.0.14 — Sumber sinyal default = formula internal ASI-Bot
    signal_source: "asi_bot",
  });
  const [pnl, setPnl] = useState<AsiPnl | null>(null);
  const [trades, setTrades] = useState<AsiTradeResp[]>([]);
  // v9.9.8 — Recent Trades: 10 tampil default, toggle kanan expand ke
  // max 20 dengan scroll ke bawah. Trade CLOSED (demo maupun real) tetap
  // tersimpan sebagai history — tidak pernah dihapus dari daftar.
  const [tradesExpanded, setTradesExpanded] = useState(false);
  // v9.9.9 — Saldo available USDT KEDUA jaringan (kartu DEMO di atas,
  // kartu REAL di bawahnya) di atas Recent Trades.
  const [balance, setBalance] = useState<{
    demo: { connected: boolean; available_usdt: number | null };
    real: { connected: boolean; available_usdt: number | null };
  }>({ demo: { connected: false, available_usdt: null }, real: { connected: false, available_usdt: null } });
  const [connectOpen, setConnectOpen] = useState(false);
  // v9.7.6 — track in-flight close requests per trade id
  const [closingIds, setClosingIds] = useState<Record<string, boolean>>({});
  const [closingAll, setClosingAll] = useState(false);
  // v9.9.13 — Hapus kartu history dari Recent Trades (per-row ✕).
  const [deletingIds, setDeletingIds] = useState<Record<string, boolean>>({});
  // v10.2.9 — Anti-resurrect set untuk delete optimistic (dipakai refresh).
  const deletedIdsRef = useRef<Set<string>>(new Set());
  // v9.8.1 — AISuggestionsSheet popup (daftar aset hasil scan, dibuka
  // dari tombol PICK A SIGNAL). Sheet ini punya AsiTradeSheet internal.
  const [suggestOpen, setSuggestOpen] = useState(false);

  // v10.2.7 — Scan debug: jawaban "kenapa bot tidak eksekusi" per device.
  type ScanDebug = {
    device_in_scanner: boolean;
    btc_regime?: string | null;
    report: {
      scanned: boolean;
      skip_reason?: string | null;
      skip_code?: string | null;
      skip_params?: Record<string, string | number>;
      signals: number;
      placed: number;
      rejects: Record<string, number>;
    } | null;
  };
  const [scanDebug, setScanDebug] = useState<ScanDebug | null>(null);

  useEffect(() => {
    (async () => {
      const did = await getDeviceId();
      setDeviceId(did);
      // v10.2.16 — Restore SELURUH pengaturan bot (mode Full/Semi,
      // parameter, disclaimer) dari local storage supaya tidak reset
      // saat keluar-masuk halaman atau aplikasi ditutup. Refresh dari
      // backend tetap berjalan setelah ini sebagai sumber kebenaran.
      try {
        const raw = await AsyncStorage.getItem("@asi_bot_prefs");
        if (raw) {
          const prefs = JSON.parse(raw);
          if (prefs && typeof prefs === "object") {
            setBot((prev) => ({ ...prev, ...prefs }));
          }
        }
      } catch { /* ignore */ }
      try {
        const cached = await readPageCache<AsiTradeResp[]>(`asibot-trades:${did}`);
        // v10.2.16 — Saring tombstone bersama: kartu yang dihapus di
        // Running Positions tidak boleh bangkit dari cache halaman ini.
        if (cached && cached.length > 0) setTrades(await filterDeletedTrades(cached));
      } catch { /* abaikan */ }
      // v10.2.16 — Restore credentials & balance dari page cache: tanpa
      // ini, tiap keluar-masuk halaman kartu DEMO/REAL kembali tampil
      // "Not connected" sampai fetch jaringan selesai. Cache hanya untuk
      // tampilan awal — refresh di bawah tetap menimpa dengan data segar.
      try {
        const cachedCreds = await readPageCache<AsiCredential[]>(`asibot-creds:${did}`);
        if (cachedCreds && cachedCreds.length > 0) setCreds(cachedCreds);
        const cachedBal = await readPageCache<typeof balance>(`asibot-balance:${did}`);
        if (cachedBal) setBalance(cachedBal);
      } catch { /* abaikan */ }
      refresh(did);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // v9.7.6 — Saat SALAH SATU bot RUNNING (semi atau full), refresh daftar
  // trade berkala agar PnL & status terbuka/tertutup tetap live.
  // v10.2.11 — FOCUS-GATED: interval dimatikan saat layar TIDAK terlihat
  // (mis. user membuka grafik aset di atas layar ini). Sebelumnya polling
  // 5 detik + harga 300ms terus berjalan di background, membebani CPU &
  // network HP → halaman grafik yang baru dibuka jadi lambat (keluhan
  // user: "grafik dari kartu Running Positions lambat, dari dashboard
  // cepat").
  useFocusEffect(
    useCallback(() => {
      const anyRunning = !!(bot.semi_enabled || bot.full_enabled || bot.enabled);
      if (!anyRunning || !deviceId) return;
      // v10.1.8 — Interval disamakan dengan Running Positions (5 detik)
      // supaya status trade (LIMIT WAITING → OPEN) tidak desync antar
      // layar. Backend punya cache balance 4 detik untuk melindungi
      // rate-limit API key user.
      const id = setInterval(() => refresh(), 5_000);
      return () => clearInterval(id);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bot.semi_enabled, bot.full_enabled, bot.enabled, deviceId])
  );

  // v10.2.7 — Poll /asi/scan-debug tiap 30 detik untuk info status scanner.
  useFocusEffect(
    useCallback(() => {
      if (!deviceId) return;
      let alive = true;
      const tick = async () => {
        try {
          const d = await api.asi.scanDebug(deviceId);
          if (!alive) return;
          setScanDebug(d as any);
        } catch { /* keep previous */ }
      };
      tick();
      const id = setInterval(tick, 30_000);
      return () => { alive = false; clearInterval(id); };
    }, [deviceId])
  );

  // v9.9.13 — Mark price REALTIME untuk posisi open: polling batch 2 detik
  // (backend cache 1 detik via proxy SG). Angka harga di samping symbol
  // berubah live, dan frame kartu hijau/merah mengikuti PnL live.
  const [livePx, setLivePx] = useState<Record<string, number>>({});
  // v10.0.13 — Flash direction (naik=hijau, turun=merah) agar harga & PnL
  // "berkedip hidup" tiap tick, seperti efek candlestick di chart.
  const prevPxRef = useRef<Record<string, number>>({});
  const flashTimerRef = useRef<any>(null);
  const [flashDir, setFlashDir] = useState<Record<string, "up" | "down">>({});
  // v10.1.8 — Sertakan pending_entry: kartu LIMIT juga harus ticking
  // (keluhan user "kartu diam") agar harga live terlihat bergerak
  // terhadap harga limit yang dipasang.
  const openSymsKey = trades
    .filter((t2) => ["open", "pending_entry"].includes(String(t2.status || "").toLowerCase()))
    .map((t2) => t2.symbol)
    .filter((v, i, a) => a.indexOf(v) === i)
    .join(",");
  // v10.2.16 — WS aggTrade langsung dari device (sumber yang sama dengan
  // halaman grafik yang terbukti LIVE). Polling backend 300ms bisa
  // membeku bila upstream production terblokir / request menggantung —
  // stream ini membuat harga & PnL kartu kembali "berkedip" realtime.
  // Keduanya di-MERGE: polling tetap melengkapi simbol non-Binance.
  const wsPx = useBinanceMultiTicker(openSymsKey ? openSymsKey.split(",") : []);
  useEffect(() => {
    const ks = Object.keys(wsPx);
    if (ks.length === 0) return;
    const f: Record<string, "up" | "down"> = {};
    ks.forEach((k) => {
      const prev = prevPxRef.current[k];
      const v = wsPx[k];
      if (prev != null && v !== prev) f[k] = v > prev ? "up" : "down";
    });
    prevPxRef.current = { ...prevPxRef.current, ...wsPx };
    setLivePx((cur) => ({ ...cur, ...wsPx }));
    if (Object.keys(f).length > 0) {
      setFlashDir((cur) => ({ ...cur, ...f }));
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
      flashTimerRef.current = setTimeout(() => setFlashDir({}), 700);
    }
  }, [wsPx]);
  useFocusEffect(
    useCallback(() => {
      if (!openSymsKey) { setLivePx({}); return; }
      const syms = openSymsKey.split(",");
      let alive = true;
      // v10.2.16 — Anti penumpukan: interval 300ms tapi respons backend
      // bisa 2-5 detik di jaringan HP → tanpa guard, request menumpuk
      // dan harga justru tampak membeku. Lewati tick bila request
      // sebelumnya belum selesai.
      let inFlight = false;
      const tick = async () => {
        if (inFlight) return;
        inFlight = true;
        try {
          const r = await api.asi.prices(syms);
          if (!alive) return;
          const m: Record<string, number> = {};
          Object.entries(r.prices || {}).forEach(([k, v]) => {
            m[k.replace(/USDT$/, "")] = v;
          });
          // Arah flash per simbol untuk tick ini
          const f: Record<string, "up" | "down"> = {};
          Object.entries(m).forEach(([k, v]) => {
            const prev = prevPxRef.current[k];
            if (prev != null && v !== prev) f[k] = v > prev ? "up" : "down";
          });
          prevPxRef.current = { ...prevPxRef.current, ...m };
          // v10.2.4 — MERGE, jangan timpa: bila satu response sesaat kosong
          // (upstream gagal), harga lama TETAP tampil — kartu tidak pernah
          // kehilangan mark price serentak (akar keluhan "tidak berkedip /
          // jadi dash berulang").
          setLivePx((cur) => ({ ...cur, ...m }));
          if (Object.keys(f).length > 0) {
            setFlashDir((cur) => ({ ...cur, ...f }));
            if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
            flashTimerRef.current = setTimeout(() => setFlashDir({}), 700);
          }
        } catch { /* pertahankan harga terakhir */ }
        finally { inFlight = false; }
      };
      tick();
      // v10.1.7 — Polling kembali ke 300ms seperti sebelumnya agar harga
      // mark price "berkedip hidup" dan match dengan candlestick realtime.
      // v10.2.11 — HANYA saat layar terlihat (useFocusEffect).
      const id = setInterval(tick, 300);
      return () => { alive = false; clearInterval(id); };
       
    }, [openSymsKey])
  );

  // v10.0.16 — Sinkronkan Trader Profile global ke bot.profile PERSIS
  // apa adanya: scalper / day (Intraday) / swing / longterm (Confluence
  // v9). Belum memilih → null (dashboard default gate 5, gaya v5.1.8).
  // Full-Auto scanner membaca field ini di scheduler → sinyal yang
  // dieksekusi otomatis mengikuti profil yang user pilih di header.
  useEffect(() => {
    if (!deviceId || !credsLoaded) return;
    const target: "scalper" | "day" | "swing" | "longterm" | null =
      traderExplicit ? (traderProfile as any) : null;
    if ((bot.profile ?? null) === target) return;
    saveBot({ profile: target }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traderProfile, traderExplicit, deviceId, credsLoaded]);

  const refresh = async (did?: string) => {
    const id = did || deviceId; if (!id) return;
    // v10.2.1 — Fix "Recent Trades kosong" + "not connected": sebelumnya
    // seluruh refresh di-wrap satu try/catch — jika listCredentials atau
    // getBot gagal duluan (mis. backend restart sesaat), setTrades tidak
    // pernah terpanggil → kartu Recent Trades mendadak kosong meski
    // Running Positions (polling independen) tetap jalan. Sekarang tiap
    // call punya try/catch sendiri sehingga satu kegagalan tidak
    // meng-reset bagian lain.
    try {
      const c = await api.asi.listCredentials(id);
      setCreds(c.items);
      writePageCache(`asibot-creds:${id}`, c.items);
    } catch { /* keep existing creds */ }
    try {
      const b = await api.asi.getBot(id);
      if (b.exists) {
        setBot((prev) => {
          const resolvedMode = b.full_enabled ? "full" : (b.mode || prev.mode);
          return { ...prev, ...b, mode: resolvedMode };
        });
      }
    } catch { /* keep existing bot cfg */ }
    try {
      const p = await api.asi.pnl(id); setPnl(p);
    } catch { /* keep PnL */ }
    try {
      const t2 = await api.asi.listTrades(id, 100);
      // v10.2.2 — History diperluas 50 → 100 posisi (permintaan user).
      // v10.2.9 — Anti-resurrect: kartu yang baru dihapus optimistic tidak
      // boleh muncul lagi akibat race dengan refresh yang in-flight.
      const items = (await filterDeletedTrades(t2.items.slice(0, 100)))
        .filter((x) => !deletedIdsRef.current.has(String((x as any)._id || "")));
      setTrades(items);
      // v10.2.16 — Prefetch chart untuk SEMUA kartu yang terlihat begitu
      // list selesai dimuat (bukan hanya saat tap). Tap kartu → data
      // sudah warm di cache → halaman detail aset tampil instan.
      // chartCache internal dedupe TTL 90s + batas 60 entri.
      try {
        const bases = Array.from(new Set(
          items.map((x) => String((x as any).symbol || "").replace(/USDT$/i, "").toUpperCase())
              .filter(Boolean)
        )).slice(0, 30);
        bases.forEach((b, i) => setTimeout(
          () => prefetchChart("crypto", b, "1h", apiProfile ?? undefined),
          i * 120,
        ));
      } catch { /* abaikan — fallback fetch normal tetap jalan */ }
      // v10.2.9 — Simpan ke page cache: kunjungan berikutnya daftar
      // langsung tergambar instan sebelum refresh pertama selesai.
      writePageCache(`asibot-trades:${id}`, items);
    } catch { /* keep trades (jangan kosongkan!) */ }
    // v9.9.9 — saldo available kedua jaringan, di-refresh bersama PnL.
    // v10.1.7 — Hanya patch nilai bila non-null supaya kolom DEMO/REAL
    // tidak hilang-timbul saat API balance sesaat gagal.
    try {
      const b = await api.asi.balance(id, bot.exchange);
      setBalance((prev) => {
        const next = {
          demo: {
            // v10.2.1 — "connected" juga sticky: sekali connected=true, baru
            // berubah ke false kalau API eksplisit bilang false, bukan karena
            // network timeout sesaat.
            connected: b.demo?.connected === false ? false : (b.demo?.connected ?? prev.demo.connected),
            available_usdt: b.demo?.available_usdt != null ? b.demo.available_usdt : prev.demo.available_usdt,
          },
          real: {
            connected: b.real?.connected === false ? false : (b.real?.connected ?? prev.real.connected),
            available_usdt: b.real?.available_usdt != null ? b.real.available_usdt : prev.real.available_usdt,
          },
        };
        // v10.2.16 — Cache balance agar status connected & saldo tidak
        // reset ke "Not connected" tiap keluar-masuk halaman.
        writePageCache(`asibot-balance:${id}`, next);
        return next;
      });
    } catch { /* saldo opsional — jangan ganggu refresh utama */ }
    setCredsLoaded(true);
  };

  const activeTestnet = bot.active_testnet ?? true;
  // v9.9.5 — credential dicocokkan dengan network AKTIF (slot terpisah).
  // Fallback ke credential lain di exchange yang sama hanya untuk
  // kompatibilitas data lama.
  const activeCred =
    creds.find((c) => c.exchange === bot.exchange && !!c.testnet === activeTestnet)
    || creds.find((c) => c.exchange === bot.exchange);
  // v9.7.7 — Disclaimer dibaca dari backend config (permanent, sekali centang)
  const canUseBot = !!activeCred && !!bot.disclaimer_ack;

  // v9.6.4 — Premium gate: halaman ini khusus member premium.
  // (__DEV__ bypass membuat web preview tetap bisa diakses untuk testing.)
  if (accessLoaded && !hasAccess) {
    return (
      <View style={[s.root, { backgroundColor: colors.background, paddingTop: insets.top }]}>
        <View style={s.header}>
          <TouchableOpacity onPress={() => router.back()} testID="asi-back" hitSlop={10}>
            <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={[s.title, { color: colors.textPrimary }]}>🤖 ASI-Bot</Text>
            <Text style={[s.sub, { color: colors.textMuted }]}>
              Artificial Super Intelligence · Auto-Trade Futures
            </Text>
          </View>
        </View>
        <PremiumLocked bodyKey="premium_locked_asi_body" />
      </View>
    );
  }

  const saveBot = async (next: Partial<AsiBotConfig>) => {
    // v9.7.4 — Functional setState: merge dari state TERBARU agar tap
    // berurutan tidak saling menimpa snapshot basi.
    // v10.1.6 — JANGAN telan error simpan (`.catch(()=>{})` lama): bila
    // simpan gagal, UI tampak berubah tapi server tetap menjalankan bot
    // (kasus user: STOP tidak tersimpan → bot tetap eksekusi semalaman).
    // Kini kita await & beri tahu user bila gagal agar bisa retry.
    let merged: AsiBotConfig = { ...bot, ...next };
    setBot((prev) => { merged = { ...prev, ...next }; return merged; });
    try {
      // v10.3.3 — kirim offset zona waktu device (reset/resume 00:00 lokal).
      merged = { ...merged, tz_offset_min: -new Date().getTimezoneOffset() };
      await api.asi.saveBot(deviceId, merged);
      // v10.2.16 — Persist SEMUA pengaturan (mode Full/Semi, parameter,
      // disclaimer) ke local storage supaya tidak hilang saat user
      // keluar-masuk halaman atau menutup aplikasi.
      AsyncStorage.setItem("@asi_bot_prefs", JSON.stringify(merged)).catch(() => {});
    } catch (e: any) {
      Alert.alert(t("asi_save_failed_title"), t("asi_save_failed_body"));
      throw e;
    }
  };

  const openSignalPicker = () => {
    // v9.8.1 — Semi-Auto PICK A SIGNAL: buka popup daftar aset hasil scan
    // (AISuggestionsSheet) yang sudah difilter sesuai Trader Profile aktif.
    // Setiap kartu aset punya tombol "⚡ EXECUTE SEMI-AUTO" langsung.
    //
    // Koneksi exchange TIDAK wajib untuk MELIHAT sinyal — hanya wajib saat
    // eksekusi (AsiTradeSheet menampilkan CTA "HUBUNGKAN EXCHANGE" sendiri).
    // Yang wajib hanya persetujuan disclaimer (kecuali di __DEV__ preview).
    if (!__DEV__ && credsLoaded && !bot.disclaimer_ack) {
      Alert.alert(t("asi_alert_need_title"), t("asi_alert_need_ack"));
      return;
    }
    setSuggestOpen(true);
  };

  const toggleFull = async (val: boolean) => {
    if (val && !canUseBot) {
      Alert.alert(
        t("asi_alert_need_title"),
        !activeCred ? t("asi_alert_need_connect") : t("asi_alert_need_ack"),
      );
      return;
    }
    // v9.7.6 — Full-Auto independent toggle. Scheduler scans ONLY when
    // full_enabled is true. STOP leaves open positions alive (native SL/TP).
    await saveBot(val
      ? { full_enabled: true, enabled: true, mode: "full",
          auto_disabled_reason: null, auto_disabled_at: null }
      : { full_enabled: false, enabled: !!bot.semi_enabled, mode: "full" });
  };

  const closeOneTrade = async (trade: AsiTradeResp) => {
    // v9.8.4 — Kunci in-flight per (symbol|exchange) supaya fallback
    // close-by-symbol (untuk row TANPA _id, mis. data dari backend lama)
    // juga ter-dedupe dengan benar.
    const tid = (trade as any)._id as string | undefined;
    const lockKey = tid || `${trade.exchange}:${trade.symbol}`;
    if (closingIds[lockKey]) return;
    setClosingIds((prev) => ({ ...prev, [lockKey]: true }));
    try {
      if (tid) {
        await api.asi.closeTrade(deviceId, tid);
      } else {
        await api.asi.closeTradeBySymbol(deviceId, trade.symbol, trade.exchange);
      }
      await refresh();
    } catch (e: any) {
      Alert.alert(t("asi_close_failed"), String(e?.message || e));
    } finally {
      setClosingIds((prev) => {
        const next = { ...prev };
        delete next[lockKey];
        return next;
      });
    }
  };

  // v10.2.27 — CLOSE ALL: tutup semua posisi open (market) + batalkan
  // semua order LIMIT pending sekaligus (backend close-all menangani
  // keduanya). Dipakai tombol di header Recent Trades.
  const closeAllTrades = async () => {
    if (closingAll) return;
    const openCount = trades.filter((x) =>
      (x as any).status === "open" || (x as any).status === "pending_entry").length;
    if (openCount === 0) return;
    const ask = Platform.OS === "web"
      ? Promise.resolve(window.confirm(t("asi_close_all_body")))
      : await new Promise<boolean>((resolve) => Alert.alert(
          t("asi_close_all_title"), t("asi_close_all_body"),
          [{ text: t("pos_btn_back"), style: "cancel", onPress: () => resolve(false) },
           { text: t("asi_close_all"), style: "destructive", onPress: () => resolve(true) }]
        ));
    if (!ask) return;
    setClosingAll(true);
    try {
      const res = await api.asi.closeAllTrades(deviceId);
      if (res.errors && res.errors.length > 0) {
        Alert.alert(
          t("asi_close_failed"),
          res.errors.map((e) => `${e.symbol}: ${e.error}`).join("\n"),
        );
      }
      await refresh();
    } catch (e: any) {
      Alert.alert(t("asi_close_failed"), String(e?.message || e));
    } finally {
      setClosingAll(false);
    }
  };

  // v9.9.13 — Swipe-to-delete untuk kartu HISTORY (closed/expired/
  // cancelled/layered). Posisi open/pending tidak bisa dihapus —
  // harus CLOSE/cancel dulu (ditegakkan juga di backend).
  const deleteOneTrade = async (trade: AsiTradeResp) => {
    const tid = (trade as any)._id as string | undefined;
    if (!tid || !deviceId) return;
    const lockKey = tid;
    if (deletingIds[lockKey]) return;
    // v10.2.9 — OPTIMISTIC DELETE: kartu langsung hilang (keluhan user:
    // hapus lambat & kadang tidak terdelete). Request jalan di
    // background; gagal → data dimuat ulang + alert.
    deletedIdsRef.current.add(tid);
    // v10.2.16 — Tombstone BERSAMA: Running Positions juga memfilter id
    // ini dari cache & poll-nya (fix: hapus di Recent Trades tidak
    // menghilangkan kartu di Running Positions).
    void markTradeDeleted(tid);
    setTrades((list) => list.filter((x) => (x as any)._id !== tid));
    setTimeout(() => deletedIdsRef.current.delete(tid), 15_000);
    setDeletingIds((prev) => ({ ...prev, [lockKey]: true }));
    try {
      await api.asi.deleteTrade(deviceId, tid);
    } catch (e: any) {
      deletedIdsRef.current.delete(tid);
      Alert.alert(t("asi_close_failed"), String(e?.message || e));
      await refresh();
    } finally {
      setDeletingIds((prev) => {
        const next = { ...prev };
        delete next[lockKey];
        return next;
      });
    }
  };

  return (
    <View style={[s.root, { backgroundColor: colors.background, paddingTop: insets.top }]}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="asi-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: colors.textPrimary }]}>🤖 ASI-Bot</Text>
          <Text style={[s.sub, { color: colors.textMuted }]}>
            Artificial Super Intelligence · Auto-Trade Futures
          </Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32 }}>
        {/* v9.7.6 — SATU kartu status di atas. Isinya berganti mengikuti
            tombol mode (chip Semi-Auto / Full-Auto) yang user tekan.
            Backend tetap punya semi_enabled + full_enabled independen. */}
        <StatusCard
          kind={bot.mode === "full" ? "full" : "semi"}
          running={bot.mode === "full" ? !!bot.full_enabled : !!bot.semi_enabled}
          onPrimary={() => (bot.mode === "full" ? toggleFull(true) : openSignalPicker())}
          onStop={() => toggleFull(false)}
          reverseOn={!!bot.reverse_signal}
          onToggleReverse={() => saveBot({ reverse_signal: !bot.reverse_signal, reverse_toggle: true } as any)}
          colors={colors}
          t={t}
        />
        {bot.mode === "full" ? (
          <Text style={{ color: colors.textMuted, fontSize: 10.5, marginTop: 6, lineHeight: 15, textAlign: "center" }}>
            {t(bot.reverse_signal ? "asi_reverse_on" : "asi_reverse_hint")}
            {!bot.reverse_signal && (bot as any).reverse_auto_off_at
              ? `\n${t("asi_reverse_auto_off")}` : ""}
          </Text>
        ) : null}
        {(bot.full_enabled) ? (
          <Text style={{ color: colors.textMuted, fontSize: 10.5, marginTop: 6,
                         lineHeight: 15, textAlign: "center" }}>
            {t("asi_stop_hint")}
          </Text>
        ) : null}

        {/* v10.2.7 — SCAN DIAGNOSTICS line: terlihat hanya saat Full-Auto
            aktif. Menjawab "kenapa bot tidak eksekusi" tanpa perlu buka
            log: discan/skip + alasan, sinyal lolos, posisi terpasang,
            dan alasan reject terbanyak. */}
        {bot.full_enabled && scanDebug ? (() => {
          const r = scanDebug.report;
          let line: string;
          if (!scanDebug.device_in_scanner) {
            line = t("asi_scan_unregistered");
          } else if (r && !r.scanned) {
            let skipTxt = r.skip_reason || "unknown";
            if (r.skip_code) {
              const tpl = t(`asi_skip_${r.skip_code}`);
              if (tpl && tpl !== `asi_skip_${r.skip_code}`) {
                skipTxt = Object.entries(r.skip_params || {}).reduce(
                  (acc, [k, v]) => acc.replace(`{${k}}`, String(v)), tpl);
              }
            }
            line = `${t("asi_scan_skip")}: ${skipTxt}`;
          } else if (r) {
            const topReject = Object.entries(r.rejects || {})
              .sort((a, b) => b[1] - a[1])[0];
            // v10.2.12 — Tampilkan rezim BTC gate bila bukan neutral
            // supaya user paham kenapa satu arah sedang diblokir.
            const regimeLabel = scanDebug.btc_regime && scanDebug.btc_regime !== "neutral"
              ? ` · ${t("asi_scan_regime")}: ${scanDebug.btc_regime.replace(/_/g, " ")}`
              : "";
            line = t("asi_scan_active")
              .replace("{s}", String(r.signals)).replace("{p}", String(r.placed)) +
              regimeLabel +
              (topReject && r.placed === 0
                ? ` · ${t("asi_scan_top_reject")}: ${topReject[0]} (${topReject[1]}×)`
                : "");
          } else {
            line = t("asi_scan_waiting");
          }
          return (
            <Text testID="asi-scan-debug"
                  style={{ color: colors.textMuted, fontSize: 10, marginTop: 4,
                           lineHeight: 14, textAlign: "center" }}>
              {line}
            </Text>
          );
        })() : null}

        {/* Connect exchange */}
        <SectionHeader title={t("asi_sec_exchange")} />
        {/* v9.9.5 — Network switch GLOBAL: memilih jaringan aktif untuk
            Semi & Full-Auto. Credential mainnet & testnet disimpan di
            slot terpisah → switching instan tanpa input ulang API key. */}
        <View style={{ flexDirection: "row", gap: 8, marginBottom: 10 }}>
          {([true, false] as const).map((isTest) => {
            const active = activeTestnet === isTest;
            return (
              <TouchableOpacity
                key={String(isTest)}
                onPress={() => saveBot({ active_testnet: isTest })}
                style={{
                  flex: 1, paddingVertical: 10, borderRadius: 10, borderWidth: 1.5,
                  borderColor: active ? (isTest ? GOLD : RED) : colors.border,
                  backgroundColor: active ? (isTest ? GOLD : RED) : colors.surface,
                  alignItems: "center",
                }}
                testID={isTest ? "asi-net-testnet" : "asi-net-mainnet"}
              >
                <Text style={{
                  color: active ? (isTest ? ACCENT_TEXT : "#fff") : colors.textPrimary,
                  fontWeight: "900", fontSize: 12, letterSpacing: 0.6,
                }}>
                  {isTest ? "🧪 TESTNET" : "🔴 MAINNET"}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <View style={{ gap: 8 }}>
          {EXCHANGES.map((ex) => {
            // v9.9.5 — tampilkan status KEDUA slot jaringan; slot yang
            // aktif ditandai border emas pada teks status.
            const cTest = creds.find((x) => x.exchange === ex.id && !!x.testnet);
            const cMain = creds.find((x) => x.exchange === ex.id && !x.testnet);
            const cActive = activeTestnet ? cTest : cMain;
            return (
              <TouchableOpacity
                key={ex.id}
                onPress={() => { setBot({ ...bot, exchange: ex.id }); setConnectOpen(true); }}
                style={[s.row, { backgroundColor: colors.surface, borderColor: bot.exchange === ex.id ? GOLD : colors.border }]}
                testID={`asi-ex-${ex.id}`}
              >
                <Text style={[s.rowLabel, { color: colors.textPrimary }]}>{ex.label}</Text>
                <View style={{ flex: 1 }} />
                <View style={{ alignItems: "flex-end", gap: 2 }}>
                  <Text style={{
                    fontSize: 10.5, fontWeight: "800",
                    color: cActive ? GREEN : colors.textMuted,
                  }}>
                    {cActive
                      ? `${activeTestnet ? "🧪 TESTNET" : "🔴 MAINNET"} ✓ · ${cActive.api_key_mask}`
                      : (cTest || cMain)
                        ? t("asi_net_other_only")
                        : t("asi_not_connected")}
                  </Text>
                  <Text style={{ color: colors.textMuted, fontSize: 9 }}>
                    {`🧪 ${cTest ? "✓" : "—"}   🔴 ${cMain ? "✓" : "—"}`}
                  </Text>
                </View>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* Mode */}
        <SectionHeader title={t("asi_sec_mode")} />
        <View style={{ flexDirection: "row", gap: 10 }}>
          {(["semi", "full"] as const).map((m) => {
            const active = bot.mode === m;
            const accent = m === "full" ? ORANGE : GOLD;
            return (
              <TouchableOpacity
                key={m}
                onPress={() => saveBot({ mode: m })}
                style={[s.modeChip, { borderColor: active ? accent : colors.border, backgroundColor: active ? accent : colors.surface }]}
                testID={`asi-mode-${m}`}
              >
                <Text style={{ fontSize: 20 }}>{m === "semi" ? "🦾" : "🤖"}</Text>
                <Text style={[s.modeTitle, { color: active ? ACCENT_TEXT : colors.textPrimary }]}>
                  {m === "semi" ? "Semi-Auto" : "Full-Auto"}
                </Text>
                <Text style={[s.modeSub, { color: active ? ACCENT_TEXT : colors.textMuted }]}>
                  {m === "semi" ? t("asi_mode_semi_sub") : t("asi_mode_full_sub")}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>

        {/* v10.0.14 — Bot Engine: 2 pilihan eksklusif untuk Semi & Full-Auto.
            • ASI-Bot  → formula internal (Confluence v9 / VWAP engines)
            • Titan-Bot → engine cloud eksternal (white-label WunderTrading);
              Entry/SL/TP 100% mengikuti sinyal Titan-Bot, risk & leverage
              tetap dari setting user. */}
        <View style={{ marginTop: 14 }}>
          <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
            BOT ENGINE
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {([
              { k: "asi_bot",
                // v10.0.16 — Chip ASI-Bot: label DAN emoji mengikuti Trader
                // Profile yang dipilih (🏃 Scalper / ⚡ Intraday / 📈 Swing /
                // 🧠 Confluence v9). Belum memilih → emoji 🧠 + label default.
                label: "ASI-Bot",
                emoji: traderExplicit && traderProfile
                  ? (PROFILE_META[traderProfile]?.emoji ?? "🧠")
                  : "🧠",
                sub: traderExplicit && traderProfile
                  ? (PROFILE_META[traderProfile]?.label ?? traderProfile)
                  : "Default · Confluence (longgar)" },
              // v10.1.1 — Titan-Bot DIBEKUKAN SEMENTARA (keputusan user):
              // tombol tetap tampil tetapi redup & tidak bisa diklik sampai
              // user meminta dinyalakan. Setting signal_source="cloud_pro"
              // yang sudah tersimpan TETAP berfungsi di backend (relay jalan
              // terus); hanya pemilihan baru via UI yang dikunci.
              { k: "cloud_pro", label: "Titan-Bot", emoji: "⚡", sub: "Segera Hadir", disabled: true },
            ] as const).map((opt) => {
              const isDisabled = (opt as any).disabled === true;
              const active = (bot.signal_source ?? "asi_bot") === opt.k;
              const accent = opt.k === "cloud_pro" ? "#8B5CF6" : ASI_BLUE;
              return (
                <TouchableOpacity
                  key={opt.k}
                  onPress={() => { if (!isDisabled) saveBot({ signal_source: opt.k }); }}
                  disabled={isDisabled}
                  activeOpacity={isDisabled ? 1 : 0.7}
                  style={{
                    flex: 1, paddingVertical: 12, paddingHorizontal: 8,
                    borderRadius: 12, borderWidth: 1.5,
                    borderColor: active ? accent : colors.border,
                    backgroundColor: active ? accent : colors.surface,
                    alignItems: "center",
                    opacity: isDisabled ? 0.45 : 1,
                  }}
                  testID={`asi-engine-${opt.k}`}
                >
                  <Text style={{ fontSize: 22 }}>{opt.emoji}</Text>
                  <Text style={{
                    color: active ? ACCENT_TEXT : colors.textPrimary,
                    fontWeight: "900", fontSize: 13, marginTop: 3,
                  }}>
                    {opt.label}
                  </Text>
                  <Text style={{
                    color: active ? ACCENT_TEXT : colors.textMuted,
                    fontSize: 9, marginTop: 2, textAlign: "center",
                  }}>
                    {opt.sub}
                  </Text>
                  {isDisabled ? (
                    <View style={{
                      marginTop: 4, paddingHorizontal: 6, paddingVertical: 1,
                      borderRadius: 4, backgroundColor: colors.border,
                    }}>
                      <Text style={{ color: colors.textMuted, fontSize: 8, fontWeight: "800" }}>
                        COMING SOON
                      </Text>
                    </View>
                  ) : null}
                </TouchableOpacity>
              );
            })}
          </View>
          <Text style={{ color: colors.textMuted, fontSize: 10, marginTop: 6, lineHeight: 14 }}>
            {bot.signal_source === "cloud_pro"
              ? t("asi_engine_caption_cloud")
              : t("asi_engine_caption_asi")
                  .replace("{profile}", traderExplicit && traderProfile
                    ? (PROFILE_META[traderProfile]?.label ?? traderProfile)
                    : t("asi_engine_default_profile"))}
          </Text>
        </View>

        {/* Parameters */}
        <SectionHeader title={t("asi_sec_risk")} />
        <SizingSelector riskPct={bot.risk_pct} marginUsd={bot.margin_usdt ?? 0}
                  onRisk={(v) => saveBot({ risk_pct: v })}
                  onMargin={(v) => saveBot({ margin_usdt: v })}
                  riskLabel={t("asi_risk_per_trade")} marginLabel={t("asi_margin_per_trade")}
                  accent={bot.mode === "full" ? ORANGE : GOLD}
                  colors={colors} testPrefix="asi" />
        <ParamRow label="Leverage" value={`${bot.leverage}x`}
                  onDec={() => saveBot({ leverage: Math.max(1, bot.leverage - 1) })}
                  onInc={() => saveBot({ leverage: Math.min(125, bot.leverage + 1) })}
                  colors={colors} testID="asi-lev" />
        {/* v9.9.0 — Margin Mode selector (Cross/Isolated). Dipakai Full-Auto
            scheduler (via bot config) DAN jadi default di trade sheet.
            SL/TP native tetap terpasang di Binance untuk kedua mode. */}
        <View style={{ marginBottom: 8 }}>
          <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
            {t("ats_margin_mode")}
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {(["isolated", "cross"] as const).map((mm) => {
              const active = (bot.margin_mode ?? "isolated") === mm;
              const accent = bot.mode === "full" ? ORANGE : GOLD;
              return (
                <TouchableOpacity
                  key={mm}
                  onPress={() => saveBot({ margin_mode: mm })}
                  style={{
                    flex: 1, paddingVertical: 10, borderRadius: 10,
                    borderWidth: 1.5,
                    borderColor: active ? accent : colors.border,
                    backgroundColor: active ? accent : colors.surface,
                    alignItems: "center",
                  }}
                  testID={`asi-bot-margin-${mm}`}
                >
                  <Text style={{
                    color: active ? ACCENT_TEXT : colors.textPrimary,
                    fontWeight: "900", fontSize: 11.5, letterSpacing: 0.6,
                  }}>
                    {mm === "isolated" ? t("ats_margin_isolated") : t("ats_margin_cross")}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
          <Text style={{ color: colors.textMuted, fontSize: 10, lineHeight: 14, marginTop: 6 }}>
            {t("ats_bracket_native")}
          </Text>
        </View>
        {/* v10.0.1 — Tipe eksekusi entry: MARKET PRICE (ungu muda, instan)
            vs LIMIT PRICE (kuning, entry moderate -0.5/-0.3 ATR). Dipakai
            Semi-Auto sheet & Full-Auto scheduler via bot config. */}
        <View style={{ marginBottom: 8 }}>
          <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
            {t("ats_entry_mode")}
          </Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {(["market", "limit"] as const).map((em) => {
              const active = (bot.entry_mode ?? "limit") === em;
              const accent = em === "market" ? PURPLE : YELLOW;
              return (
                <TouchableOpacity
                  key={em}
                  onPress={() => saveBot({ entry_mode: em })}
                  style={{
                    flex: 1, paddingVertical: 10, borderRadius: 10,
                    borderWidth: 1.5,
                    borderColor: active ? accent : colors.border,
                    backgroundColor: active ? accent : colors.surface,
                    alignItems: "center",
                  }}
                  testID={`asi-bot-entry-${em}`}
                >
                  <Text style={{
                    color: active ? "#0B0E11" : colors.textPrimary,
                    fontWeight: "900", fontSize: 11.5, letterSpacing: 0.4,
                  }}>
                    {em === "market" ? t("ats_entry_market") : t("ats_entry_limit")}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>
        {/* v9.6.0 — Centang TP1/TP2/TP3 (dibawah leverage).
            v9.7.4 — warna aktif mengikuti mode: Semi-Auto=hijau, Full-Auto=orange */}
        <View style={{ flexDirection: "row", gap: 8, marginBottom: 6 }}>
          {([1, 2, 3] as const).map((n) => {
            const active = !bot.auto_close_pct && (bot.tp_count ?? 3) === n;
            const accent = bot.mode === "full" ? ORANGE : GOLD;
            const label = n === 1 ? t("asi_tp_1_label") : n === 2 ? t("asi_tp_2_label") : t("asi_tp_3_label");
            return (
              <TouchableOpacity
                key={n}
                onPress={() => saveBot({ tp_count: n, auto_close_pct: 0 })}
                style={[s.tpChip, {
                  borderColor: active ? accent : colors.border,
                  backgroundColor: active ? accent : colors.surface,
                }]}
                testID={`asi-tp-${n}`}
              >
                <Text style={{ color: active ? ACCENT_TEXT : colors.textPrimary, fontWeight: "900", fontSize: 12.5 }}>
                  {label}
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <Text style={{ color: colors.textMuted, fontSize: 11, marginBottom: 10, lineHeight: 16 }}>
          {t("asi_tp_hint")}
        </Text>
        {/* v10.2.36 — Auto-Close Profit (ROI % margin). Eksklusif dgn 1/2/3 TP. */}
        <Text style={{ color: colors.textPrimary, fontWeight: "800", fontSize: 12.5, marginBottom: 6 }}>
          {t("asi_autoclose_title")}
        </Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 6 }}>
          {([10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 65, 75, 100, 150, 200] as const).map((p) => {
            const active = bot.auto_close_pct === p;
            const accent = bot.mode === "full" ? ORANGE : GOLD;
            return (
              <TouchableOpacity
                key={p}
                onPress={() => saveBot({ auto_close_pct: active ? 0 : p })}
                style={[s.acChip, {
                  borderColor: active ? accent : colors.border,
                  backgroundColor: active ? accent : colors.surface,
                }]}
                testID={`asi-autoclose-${p}`}
              >
                <Text style={{ color: active ? ACCENT_TEXT : colors.textPrimary, fontWeight: "900", fontSize: 12.5 }}>
                  {active ? "✓ " : ""}{p}%
                </Text>
              </TouchableOpacity>
            );
          })}
        </View>
        <Text style={{ color: colors.textMuted, fontSize: 11, marginBottom: 10, lineHeight: 16 }}>
          {bot.auto_close_pct ? t("asi_autoclose_on").replace("{p}", String(bot.auto_close_pct)) : t("asi_autoclose_hint")}
        </Text>
        {bot.mode === "full" ? (
          <ParamRow label={t("asi_max_trades_day")} value={`${bot.max_trades_per_day}`}
                    onDec={() => saveBot({ max_trades_per_day: Math.max(1, bot.max_trades_per_day - 1) })}
                    onInc={() => saveBot({ max_trades_per_day: Math.min(50, bot.max_trades_per_day + 1) })}
                    colors={colors} testID="asi-maxtrade" />
        ) : null}
        <ParamRow label={t("asi_daily_profit_limit")}
                  value={(bot.daily_profit_limit_usdt ?? 0) === 0 ? "OFF" : `$${bot.daily_profit_limit_usdt}`}
                  onDec={() => saveBot({ daily_profit_limit_usdt: Math.max(0, (bot.daily_profit_limit_usdt ?? 0) - 10) })}
                  onInc={() => saveBot({ daily_profit_limit_usdt: Math.min(100000, (bot.daily_profit_limit_usdt ?? 0) + 10) })}
                  colors={colors} testID="asi-dailyprofit" />
        <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: -4, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_daily_profit_hint")}
        </Text>
        <ParamRow label={t("asi_daily_loss_limit")}
                  value={(bot.daily_loss_limit_usdt ?? 0) === 0 ? "OFF" : `$${bot.daily_loss_limit_usdt}`}
                  onDec={() => saveBot({ daily_loss_limit_usdt: Math.max(0, (bot.daily_loss_limit_usdt ?? 0) - 10) })}
                  onInc={() => saveBot({ daily_loss_limit_usdt: Math.min(100000, (bot.daily_loss_limit_usdt ?? 0) + 10) })}
                  colors={colors} testID="asi-dailyloss" />
        <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: -4, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_daily_loss_hint")}
        </Text>

        <Text style={{ color: colors.textMuted, fontSize: 11, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_slguard_hint")}
        </Text>

        {bot.auto_disabled_reason ? (
          <View style={{ padding: 10, borderRadius: 10, borderWidth: 1.5,
                          borderColor: RED, backgroundColor: "rgba(239,68,68,0.08)",
                          flexDirection: "row", alignItems: "flex-start", gap: 8, marginBottom: 10 }}>
            <Ionicons name="shield-checkmark" size={18} color={RED} />
            <Text style={{ color: colors.textPrimary, fontSize: 11.5, flex: 1, lineHeight: 16 }}>
              <Text style={{ fontWeight: "900" }}>{t("asi_auto_disabled")}</Text> {bot.auto_disabled_reason}
            </Text>
          </View>
        ) : null}

        {/* Disclaimer — v9.7.7: hanya tampil saat BELUM pernah di-ACK.
            Sekali di-centang → tersimpan di backend (bot.disclaimer_ack=true)
            dan box ini disembunyikan selamanya. */}
        {!bot.disclaimer_ack ? (
          <>
            <SectionHeader title={t("asi_sec_disclaimer")} />
        <View style={[s.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={{ color: colors.textPrimary, fontSize: 12.5, lineHeight: 19 }}>
            {t("asi_disc_body")}
          </Text>
          <TouchableOpacity
            onPress={() => saveBot({ disclaimer_ack: true })}
            style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 10 }}
            testID="asi-disc"
          >
            <View style={[s.checkbox, { borderColor: GOLD, backgroundColor: "transparent" }]} />
            <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 12.5 }}>
              {t("asi_disc_ack")}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => router.push("/asi-legal" as never)}
            style={{ marginTop: 10, alignItems: "center" }}
            testID="asi-legal-link"
          >
            <Text style={{ color: GOLD, fontSize: 12, fontWeight: "800", textDecorationLine: "underline" }}>
              {t("asi_legal_link")}
            </Text>
          </TouchableOpacity>
        </View>
          </>
        ) : null}

        {/* PnL */}
        <SectionHeader title={t("asi_sec_pnl")} />
        <View style={{ flexDirection: "row", gap: 8 }}>
          {(["daily", "weekly", "monthly"] as const).map((k) => {
            const row = pnl?.[k];
            const pos = (row?.pnl_usdt ?? 0) >= 0;
            return (
              <View key={k} style={[s.pnlCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                <Text style={[s.pnlLabel, { color: colors.textMuted }]}>
                  {k === "daily" ? t("asi_pnl_daily") : k === "weekly" ? t("asi_pnl_weekly") : t("asi_pnl_monthly")}
                </Text>
                <Text style={[s.pnlValue, { color: pos ? GREEN : RED }]}>
                  {pos ? "+" : ""}${(row?.pnl_usdt ?? 0).toFixed(2)}
                </Text>
                <Text style={{ color: pos ? GREEN : RED, fontSize: 11, fontWeight: "700" }}>
                  {pos ? "+" : ""}{(row?.pnl_pct ?? 0).toFixed(2)}%
                </Text>
                <Text style={{ color: colors.textMuted, fontSize: 10, marginTop: 4 }}>
                  {row?.trades ?? 0} trade · W{row?.wins ?? 0}/L{row?.losses ?? 0}
                </Text>
              </View>
            );
          })}
        </View>
        {/* v9.9.5 — Demo (testnet) PnL terpisah, tidak masuk PnL real. */}
        {(pnl?.demo?.trades ?? 0) > 0 ? (
          <Text style={{ color: colors.textMuted, fontSize: 10.5, marginTop: 6 }}>
            {t("asi_pnl_demo")
              .replace("{pnl}", `${(pnl!.demo!.pnl_usdt >= 0 ? "+" : "")}$${pnl!.demo!.pnl_usdt.toFixed(2)}`)
              .replace("{n}", String(pnl!.demo!.trades))}
          </Text>
        ) : null}

        {/* Leaderboard — hidden on this screen; pindah ke /copy-trade */}

        {/* v9.9.9 — Dua kartu saldo available USDT langsung dari exchange:
            DEMO (testnet) di ATAS, REAL (mainnet) di BAWAHNYA. Refresh
            realtime mengikuti siklus PnL. */}
        <View style={{ gap: 8, marginTop: 14 }}>
          {([
            { key: "demo", label: t("asi_demo_badge"), chipColor: LIGHT_BLUE, data: balance.demo },
            { key: "real", label: "REAL", chipColor: "#F97316", data: balance.real },
          ] as const).map((row) => (
            <View key={row.key} style={{
              flexDirection: "row", alignItems: "center", gap: 8,
              backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1,
              borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10,
            }}>
              <View style={{
                paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                backgroundColor: row.chipColor,
              }}>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                  {row.label}
                </Text>
              </View>
              <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700", flex: 1 }}>
                {t("asi_balance_label")}
              </Text>
              <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 14 }}>
                {!row.data.connected
                  ? t("asi_not_connected")
                  : row.data.available_usdt === null
                    ? "—"
                    : `$${row.data.available_usdt.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </Text>
            </View>
          ))}
        </View>

        {/* Recent trades — v9.7.6: selalu tampil; SEMI/FULL badge + tombol CLOSE untuk posisi open.
            v9.9.8: trade closed TETAP tampil sebagai history (tidak dihapus).
            Default 10 terbaru; toggle chevron di kanan expand ke max 20
            dengan scroll di dalam area daftar. */}
        <View style={{ flexDirection: "row", alignItems: "center", marginTop: 20, marginBottom: 10 }}>
          <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 13, letterSpacing: 0.3, flex: 1 }}>
            {t("asi_sec_recent")}
          </Text>
          {/* v10.2.27 — CLOSE ALL di kanan atas, samping toggle jumlah.
              Tutup semua posisi open + batalkan semua pending LIMIT. */}
          {trades.some((x) => (x as any).status === "open" || (x as any).status === "pending_entry") ? (
            <TouchableOpacity
              onPress={closeAllTrades}
              disabled={closingAll}
              style={{
                flexDirection: "row", alignItems: "center", gap: 4,
                paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
                borderWidth: 1, borderColor: RED,
                backgroundColor: "rgba(239,68,68,0.12)",
                opacity: closingAll ? 0.6 : 1, marginRight: 8,
              }}
              testID="asi-close-all"
            >
              {closingAll ? (
                <ActivityIndicator size="small" color={RED} />
              ) : (
                <Ionicons name="close-circle" size={13} color={RED} />
              )}
              <Text style={{ color: RED, fontSize: 11, fontWeight: "900", letterSpacing: 0.4 }}>
                {closingAll ? t("asi_close_all_working") : t("asi_close_all")}
              </Text>
            </TouchableOpacity>
          ) : null}
          {trades.length > 10 ? (
            <TouchableOpacity
              onPress={() => setTradesExpanded((v) => !v)}
              style={{
                flexDirection: "row", alignItems: "center", gap: 4,
                paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
                borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
              }}
              testID="asi-trades-toggle"
            >
              <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "800" }}>
                {tradesExpanded ? "10" : `${trades.length}`}
              </Text>
              <Ionicons
                name={tradesExpanded ? "chevron-up" : "chevron-down"}
                size={14} color={colors.textMuted}
              />
            </TouchableOpacity>
          ) : null}
        </View>
        {/* v10.1.5 — Banner global "Open positions WITHOUT native SL/TP"
            dihilangkan sesuai permintaan user: peringatan ini membingungkan
            terutama saat posisi profit. Soft watcher di backend tetap aktif
            melindungi; proteksi tidak berubah, hanya UI yang disembunyikan. */}
        {false ? (
          <TouchableOpacity
            onPress={async () => {
              try {
                const res = await api.asi.repairBrackets(deviceId, bot.exchange);
                // v9.9.8 — HANYA tampilkan popup bila ada kegagalan NYATA
                // (posisi masih terbuka & bracket tetap gagal terpasang =
                // uang berisiko). Hasil benign (posisi sudah tertutup,
                // level TP terlewati, auto-close sukses) diproses diam-diam
                // — tidak ada uang berkurang, tidak perlu popup.
                const failed = (res.results || []).filter((r) => !r.ok);
                if (failed.length > 0) {
                  Alert.alert(
                    t("asi_repair_title"),
                    failed.map((f) => `${f.symbol}: ${(f.errors || []).join(" | ")}`).join("\n"),
                  );
                }
                await refresh();
              } catch (e: any) {
                Alert.alert(t("asi_close_failed"), String(e?.message || e));
              }
            }}
            style={{
              backgroundColor: "rgba(239,68,68,0.12)", borderColor: RED, borderWidth: 1.5,
              borderRadius: 10, paddingVertical: 10, paddingHorizontal: 12, marginBottom: 8,
            }}
            testID="asi-repair-brackets"
          >
            <Text style={{ color: RED, fontWeight: "900", fontSize: 12, textAlign: "center" }}>
              {t("asi_repair_cta")}
            </Text>
          </TouchableOpacity>
        ) : null}
        {trades.length === 0 ? (
          <View style={[s.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Text style={{ color: colors.textMuted, fontSize: 12, lineHeight: 18 }}>
              {t("asi_recent_empty")}
            </Text>
          </View>
        ) : (
          <ScrollView
            style={tradesExpanded ? { maxHeight: 520 } : undefined}
            nestedScrollEnabled
            showsVerticalScrollIndicator={tradesExpanded}
          >
            {(() => {
              // v10.2.1 — URUTAN KARTU (user request): OPEN di paling
              // atas, lalu PENDING LIMIT (menunggu fill), terakhir
              // CLOSED/CANCELLED. Dalam tiap grup, urut DESC berdasarkan
              // waktu (filled_at > created_at > updated_at).
              const _rank = (t: any) => {
                const s = String(t?.status || "").toLowerCase();
                if (s === "open") return 0;
                if (s === "pending_entry") return 1;
                return 2;
              };
              const _ts = (t: any) => {
                const iso = String(t?.filled_at || t?.created_at || t?.updated_at || "");
                const d = iso ? new Date(iso).getTime() : NaN;
                return isNaN(d) ? 0 : d;
              };
              const sorted = [...trades].sort((a, b) => {
                const r = _rank(a) - _rank(b);
                return r !== 0 ? r : _ts(b) - _ts(a);
              });
              return (tradesExpanded ? sorted : sorted.slice(0, 10)).map((tr, i) => {
              // v9.8.4 — Case-insensitive: beberapa row lama bisa menyimpan
              // status "OPEN"/"Closed". Tombol CLOSE HARUS selalu muncul
              // (dan aktif) untuk setiap posisi yang masih terbuka.
              const statusLower = String(tr.status || "").toLowerCase();
              const isOpen = statusLower === "open";
              // v9.9.13 — LIMIT entry menunggu fill: badge PENDING +
              // tombol CLOSE berfungsi sebagai cancel order.
              const isPending = statusLower === "pending_entry";
              const margin = tr.margin_usdt
                || ((tr.entry_price || 0) * (tr.qty || 0) / Math.max(1, tr.leverage || 1));
              // v9.9.13 — PnL LIVE dari mark price realtime (poll 2s) utk
              // posisi open; fallback ke pnl tersimpan. FRAME kartu: hijau
              // saat profit, merah saat loss (open & closed), emas pending.
              // Symbol dinormalisasi (row lama bisa menyimpan "XRPUSDT").
              const symBase = String(tr.symbol || "").replace(/USDT$/, "");
              const lpNow = livePx[symBase] ?? null;
              const livePnl = (isOpen && lpNow && tr.entry_price && tr.qty)
                ? (tr.side === "BUY" ? lpNow - tr.entry_price : tr.entry_price - lpNow) * (tr.qty || 0)
                : (tr.pnl_usdt ?? 0);
              const dispPnl = isOpen ? livePnl : (tr.pnl_usdt ?? 0);
              const pct = margin > 0 ? (dispPnl / margin) * 100 : 0;
              const pos = dispPnl >= 0;
              const tid = (tr as any)._id as string | undefined;
              const lockKey = tid || `${tr.exchange}:${tr.symbol}`;
              const isClosing = !!closingIds[lockKey];
              const modeBadge = tr.mode === "full" ? "full" : "semi";
              const borderColor = isPending ? GOLD : (dispPnl >= 0 ? GREEN : RED);
              // v9.9.13 — Kartu dibungkus Swipeable HANYA untuk history
              // (closed/expired/cancelled/layered): geser kiri → HAPUS.
              // v10.1.1 — Seluruh kartu dapat DITEKAN → detail aset/chart.
              // Tombol di dalam (CLOSE/CANCEL/⚠️) tetap menang karena
              // touchable terdalam yang menerima tap.
              const openDetail = () => {
                if (!symBase) return;
                // v10.2.9 — PREFETCH chart sebelum navigasi supaya
                // halaman grafik terbuka hampir instan.
                prefetchChart("crypto", symBase, "1h", apiProfile ?? undefined);
                router.push(`/asset/crypto/${encodeURIComponent(symBase)}` as any);
              };
              const rowBody = (
                <CardTouchable activeOpacity={0.8} onPress={openDetail}
                  style={[s.leaderRow, { backgroundColor: colors.surface, borderColor }]}>
                {/* v10.1.7 — Layout 3-BARIS (anti-jiggle):
                    Baris 1 : Tanggal/Jam · (closed reason jika sudah closed)
                    Baris 2 : Symbol/USDT (kiri) | Mark Price (tengah) | PnL $ + % (kanan)
                    Baris 3 : SEMUA badge (D/R, SEMI/FULL, L/M, LONG/SHORT,
                              leverage, margin mode, layer, status, formula). */}

                {/* ───── BARIS 1 : Tanggal & Jam ─────
                    v10.2.1 — Teks dinaikkan dari fontSize 9.5+textMuted
                    menjadi 11+putih terang agar jelas terbaca. */}
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={{ fontSize: 11, fontWeight: "800", color: "#FFFFFF" }}>
                    {(() => {
                      const iso = String((tr as any).filled_at || (tr as any).created_at || (tr as any).updated_at || "");
                      if (!iso) return "";
                      const d = new Date(iso);
                      if (isNaN(d.getTime())) return "";
                      const pad = (n: number) => String(n).padStart(2, "0");
                      return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
                    })()}
                  </Text>
                  {!isOpen && !isPending ? (() => {
                    const rc = String((tr as any).close_reason || "");
                    const acP = Number((tr as any).auto_close_pct) || 0;
                    let txt: string;
                    if (acP > 0 && rc === "TP1") txt = `Closed on AC ${acP}%`;
                    else if (/^TP\d?$/.test(rc)) txt = `Closed on ${rc}`;
                    else if (rc === "SL") txt = "Closed on SL";
                    else if (rc === "cancelled_pending") txt = "Canceled by user";
                    else if (rc === "entry_expired") txt = "Canceled: expired";
                    else if (rc === "manual_cleanup") txt = "Closed on cleanup";
                    else if (rc === "merged_into_layer") txt = "Merged into layer";
                    else if (rc === "bracket_failed_after_fill") txt = "Closed: bracket fail";
                    else if (rc === "MANUAL") txt = "Closed Manually";
                    else if (rc === "TRAILING") txt = "Closed on Trailing Stop";
                    else if (rc === "BREAK_EVEN") txt = "Closed on Break-Even";
                    else if (rc === "position_closed_externally") txt = "Closed on exchange";
                    else txt = rc ? `Closed on ${rc}` : "Closed";
                    return (
                      <>
                        <Text style={{ color: colors.textMuted, fontSize: 9.5 }}>·</Text>
                        <Text numberOfLines={1} style={{ fontSize: 11, fontWeight: "800", color: "#FFFFFF", flexShrink: 1 }}>
                          {txt}
                        </Text>
                      </>
                    );
                  })() : null}
                  {/* v10.6.1 — Status chip kanan atas, tepat di atas PnL */}
                  <View style={{
                    marginLeft: "auto", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                    backgroundColor: isOpen ? GREEN : isPending ? YELLOW : colors.border,
                  }}>
                    <Text testID="rt-status-badge" style={{ color: isOpen ? ACCENT_TEXT : isPending ? "#0B0E11" : colors.textMuted, fontWeight: "900", fontSize: 9 }}>
                      {isOpen ? "OPEN" : isPending ? "LIMIT" : "CLOSED"}
                    </Text>
                  </View>
                </View>

                {/* ───── BARIS 2 : Symbol | Mark Price | PnL ───── */}
                <View style={{
                  marginTop: 4, flexDirection: "row", alignItems: "center",
                  justifyContent: "space-between", gap: 8,
                }}>
                  {/* Kiri: Symbol/USDT */}
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text numberOfLines={1}
                      style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
                      {tr.symbol}/USDT
                    </Text>
                  </View>
                  {/* Tengah: Mark price (lebar tetap 110, tabular-nums → anti-jiggle) */}
                  <View style={{ width: 110, alignItems: "center" }}>
                    {/* v10.2.4 — KOLOM INI TIDAK BOLEH PERNAH KOSONG:
                        OPEN/LIMIT → mark price live ticking (putih terang
                        + flash); CLOSED → harga exit (closed_price),
                        fallback entry price. Permintaan user eksplisit:
                        mark price harus SELALU tampil opened maupun
                        closed. */}
                    {(() => {
                      const lp = livePx[symBase] ?? (isOpen ? (tr as any).mark_price : null) ?? null;
                      const fd = flashDir[symBase];
                      const bg = lp != null && fd === "up" ? GREEN + "33"
                        : lp != null && fd === "down" ? RED + "33" : "transparent";
                      const fallbackPx = (tr as any).closed_price ?? tr.entry_price;
                      return (
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 2, borderRadius: 5,
                          backgroundColor: bg, flexDirection: "row", alignItems: "center",
                        }}>
                          <Text style={{
                            color: "#FFFFFF", fontWeight: "900", fontSize: 14,
                            fontVariant: ["tabular-nums"], letterSpacing: 0.3,
                          }}>
                            {lp != null
                              ? `$${formatPrice(lp, "crypto")}`
                              : `$${formatPrice(fallbackPx, "crypto")}`}
                          </Text>
                          <Text style={{
                            width: 13, textAlign: "center", fontSize: 11, fontWeight: "900",
                            color: fd === "up" ? GREEN : RED,
                          }}>
                            {lp != null && fd ? (fd === "up" ? "▲" : "▼") : ""}
                          </Text>
                        </View>
                      );
                    })()}
                  </View>
                  {/* Kanan: PnL $ + % (lebar tetap 100 → anti-jiggle).
                      v10.1.8 — PENDING (LIMIT) harus tampil "LIMIT WAITING"
                      persis seperti Running Positions — JANGAN tampilkan
                      PnL $0.00/0.00% yang bikin user mengira posisi sudah
                      masuk. */}
                  <View style={{ width: 100, alignItems: "flex-end" }}>
                    {isPending ? (
                      <View style={{
                        paddingHorizontal: 7, paddingVertical: 3, borderRadius: 6,
                        backgroundColor: YELLOW,
                      }}>
                        <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 10 }}>
                          LIMIT WAITING
                        </Text>
                      </View>
                    ) : (
                      <>
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4,
                          backgroundColor: isOpen && flashDir[symBase] === "up" ? GREEN + "33"
                            : isOpen && flashDir[symBase] === "down" ? RED + "33" : "transparent",
                        }}>
                          <Text style={{
                            color: pos ? GREEN : RED, fontWeight: "900", fontSize: 16,
                            fontVariant: ["tabular-nums"],
                          }}>
                            {pos ? "+" : ""}${dispPnl.toFixed(2)}
                          </Text>
                        </View>
                        {/* v10.1.7 — % PnL SELALU ditampilkan baik OPEN maupun CLOSED */}
                        <Text style={{
                          color: pos ? GREEN : RED, fontSize: 10, fontWeight: "700",
                          fontVariant: ["tabular-nums"],
                        }}>
                          {pos ? "+" : ""}{pct.toFixed(2)}%
                          {isOpen && flashDir[symBase] ? (flashDir[symBase] === "up" ? " ▲" : " ▼") : ""}
                        </Text>
                      </>
                    )}
                  </View>
                </View>

                {/* ───── BARIS 3 : SEMUA BADGE ───── */}
                <View style={{ marginTop: 6, flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  {/* D/R Demo/Real — oranye utk REAL */}
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                    backgroundColor: tr.testnet ? "#60A5FA" : "#F97316",
                  }}>
                    <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                      {tr.testnet ? "D" : "R"}
                    </Text>
                  </View>
                  {/* Mode SEMI/FULL (emoji) */}
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                    backgroundColor: modeBadge === "full" ? LIGHT_BLUE : GOLD,
                  }}>
                    <Text style={{ fontSize: 11, fontWeight: "900" }}>
                      {modeBadge === "full" ? "🤖" : "🦾"}
                    </Text>
                  </View>
                  {/* L / M entry */}
                  {(tr as any).entry_mode && !isPending ? (
                    <View style={{
                      paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                      backgroundColor: (tr as any).entry_mode === "market" ? PURPLE : YELLOW,
                    }}>
                      <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                        {(tr as any).entry_mode === "market" ? "M" : "L"}
                      </Text>
                    </View>
                  ) : null}
                  {/* LONG / SHORT */}
                  <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                                 backgroundColor: tr.side === "BUY" ? GREEN : RED }}>
                    <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
                      {tr.side === "BUY" ? "LONG" : "SHORT"}
                    </Text>
                  </View>
                  {/* Leverage */}
                  {tr.leverage ? (
                    <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                                   backgroundColor: "#1F2937" }}>
                      <Text style={{ color: GREEN, fontWeight: "900", fontSize: 10 }}>
                        {`${Number((tr as any).actual_leverage) > 0 ? (tr as any).actual_leverage : tr.leverage}x`}
                      </Text>
                    </View>
                  ) : null}
                  {/* Margin mode */}
                  <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                                 backgroundColor: ((tr.actual_margin_mode || tr.margin_mode) === "cross") ? PURPLE : TEAL }}>
                    <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9 }}>
                      {String(tr.actual_margin_mode || tr.margin_mode || "ISOLATED").toUpperCase()}
                    </Text>
                  </View>
                  {/* Layer */}
                  {(tr as any).layer_count && (tr as any).layer_count > 1 ? (
                    <View style={{ paddingHorizontal: 5, paddingVertical: 2, borderRadius: 4, backgroundColor: GOLD }}>
                      <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 8.5 }}>
                        {t("ats_layer_badge").replace("{n}", String((tr as any).layer_count))}
                      </Text>
                    </View>
                  ) : null}
                  {/* v10.3.0 — AC badge (sama dengan Running Positions) */}
                  {Number((tr as any).auto_close_pct) > 0 ? (
                    <View testID={`rt-ac-badge-${(tr as any).id || (tr as any)._id || ""}`}
                      style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: YELLOW }}>
                      <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9 }}>
                        AC {(tr as any).auto_close_pct}%
                      </Text>
                    </View>
                  ) : null}
                  {/* v10.6.4 — REVERSE badge */}
                  {String((tr as any).formula_tag || "").includes("REVERSE") ? (
                    <View testID={`rt-reverse-badge-${(tr as any).id || (tr as any)._id || ""}`}
                      style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: "#A78BFA" }}>
                      <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9 }}>⇅ REVERSE</Text>
                    </View>
                  ) : null}
                  {/* Formula tag */}
                  <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, backgroundColor: "#1F2937" }}>
                    <Text numberOfLines={1} style={{ color: colors.textMuted, fontSize: 9, fontWeight: "800" }}>
                      ⚙️ {formulaLines(t, (tr as any).profile, (tr as any).formula_tag)[0]}
                    </Text>
                  </View>
                </View>

                {/* v10.1.8 — Tombol aksi di BARIS SENDIRI, SELALU rata
                    kanan. Sebelumnya tombol digabung di baris badge
                    (flexWrap) → kalau badge penuh, spacer ter-wrap dan
                    tombol jatuh ke kiri. */}
                {(isOpen || isPending) ? (
                  <View style={{ marginTop: 6, flexDirection: "row", justifyContent: "flex-end" }}>
                    <CardTouchable
                      onPress={() => closeOneTrade(tr)}
                      disabled={isClosing}
                      style={{
                        paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                        backgroundColor: isClosing ? colors.border : isPending ? GOLD : RED,
                        minWidth: 60, alignItems: "center",
                      }}
                      testID={`asi-close-${tr.symbol}`}
                    >
                      <Text style={{ color: isPending ? "#0B0E11" : "#fff", fontWeight: "900", fontSize: 10, letterSpacing: 0.4 }}>
                        {isClosing
                          ? (isPending ? t("asi_cancelling") : t("asi_recent_closing"))
                          : (isPending ? t("asi_btn_cancel") : t("asi_recent_close"))}
                      </Text>
                    </CardTouchable>
                  </View>
                ) : null}

                {/* Detail numerik (Entry / SL / TP / Margin) — baris pelengkap kecil.
                    v10.2.1 — Entry PUTIH TERANG, text size naik 10→11. */}
                <View style={{ marginTop: 4, gap: 1 }}>
                  <Text style={{ fontSize: 11, lineHeight: 15 }}>
                    <Text style={{ color: "#FFFFFF", fontWeight: "800" }}>
                      Entry {formatPrice(tr.entry_price, "crypto")}
                    </Text>
                    {"  ·  "}
                    <Text style={{ color: RED, fontWeight: "800" }}>SL {formatPrice(tr.stop_loss, "crypto")}</Text>
                    {"  ·  "}
                    <Text style={{ color: GREEN, fontWeight: "800" }}>
                      TP {(tr.take_profits || []).map((x) => formatPrice(x, "crypto")).join(" / ") || "—"}
                    </Text>
                    {"  ·  "}
                    <Text style={{ color: YELLOW, fontWeight: "800" }}>
                      Margin ${(tr.margin_usdt ?? ((tr.entry_price && tr.qty && tr.leverage) ? tr.entry_price * tr.qty / tr.leverage : 0)).toFixed(2)}
                    </Text>
                    {/* v10.2.4 — Close price eksplisit di kartu closed
                        (permintaan user). */}
                    {!isOpen && !isPending && (tr as any).closed_price ? (
                      <>
                        {"  ·  "}
                        <Text style={{ color: "#FFFFFF", fontWeight: "800" }}>
                          Close {formatPrice((tr as any).closed_price, "crypto")}
                        </Text>
                      </>
                    ) : null}
                  </Text>
                  {/* TP fills history */}
                  {(() => {
                    const tpOnly = (Array.isArray((tr as any).tp_fills) ? (tr as any).tp_fills : [])
                      .filter((f: any) => String(f?.level || "").startsWith("TP"));
                    if (!tpOnly.length) return null;
                    return (
                    <View style={{ gap: 1 }}>
                      {tpOnly.map((f: any, i: number) => (
                        <Text key={i} style={{ fontSize: 10.5, fontWeight: "800", color: "#FFFFFF" }}>
                          ✓ {Number((tr as any).auto_close_pct) > 0 && String(f.level) === "TP1" ? `AC ${(tr as any).auto_close_pct}%` : String(f.level)} HIT · ${f.price != null ? formatPrice(Number(f.price), "crypto") : "—"}
                          {f.pnl != null ? (
                            <Text style={{ color: Number(f.pnl) >= 0 ? GREEN : RED, fontWeight: "900" }}>
                              {"  "}{Number(f.pnl) >= 0 ? "+" : "-"}${Math.abs(Number(f.pnl)).toFixed(2)}
                            </Text>
                          ) : null}
                        </Text>
                      ))}
                    </View>
                    );
                  })()}
                </View>
                </CardTouchable>
              );
              if (isOpen || isPending || !tid) {
                return <React.Fragment key={tid || i}>{rowBody}</React.Fragment>;
              }
              return (
                <ReanimatedSwipeable
                  key={tid || i}
                  friction={1.6}
                  rightThreshold={48}
                  overshootRight={false}
                  renderRightActions={() => (
                    <TouchableOpacity
                      onPress={() => deleteOneTrade(tr)}
                      disabled={!!deletingIds[lockKey]}
                      style={{
                        justifyContent: "center", alignItems: "center",
                        backgroundColor: RED, borderRadius: 10,
                        paddingHorizontal: 18, marginLeft: 6,
                      }}
                      testID={`asi-del-${tr.symbol}`}
                    >
                      <Text style={{ color: "#fff", fontWeight: "900", fontSize: 11, letterSpacing: 0.5 }}>
                        {deletingIds[lockKey] ? "…" : t("asi_delete")}
                      </Text>
                    </TouchableOpacity>
                  )}
                >
                  {rowBody}
                </ReanimatedSwipeable>
              );
            });
            })()}
          </ScrollView>
        )}
      </ScrollView>

      <ConnectExchangeModal
        visible={connectOpen}
        onClose={() => setConnectOpen(false)}
        exchange={bot.exchange as ExchangeId}
        colors={colors}
        onSaved={async (savedTestnet) => {
          setConnectOpen(false);
          // v9.9.5 — Setelah menyimpan key untuk suatu jaringan, langsung
          // jadikan jaringan itu aktif (niat user jelas ingin memakainya).
          if (typeof savedTestnet === "boolean") {
            await saveBot({ active_testnet: savedTestnet });
          }
          await refresh();
        }}
        deviceId={deviceId}
      />

      {/* v9.8.1 — Popup daftar aset hasil scan (difilter Trader Profile
          aktif). Tiap kartu aset punya tombol "⚡ EXECUTE SEMI-AUTO".
          Sheet internal sudah memuat AsiTradeSheet + duplicate-position
          confirm. Saat ditutup → refresh agar trade baru muncul. */}
      <AISuggestionsSheet
        visible={suggestOpen}
        onClose={() => { setSuggestOpen(false); refresh(); }}
        onRequestSubscribe={() => { setSuggestOpen(false); router.replace("/" as never); }}
      />
    </View>
  );
}

function SectionHeader({ title }: { title: string }) {
  const { colors } = useTheme();
  return (
    <Text style={[{ color: colors.textPrimary, fontWeight: "900", fontSize: 13, marginTop: 20, marginBottom: 10, letterSpacing: 0.3 }]}>
      {title}
    </Text>
  );
}

// v9.7.7 — Satu kartu status di atas. Berganti isi menurut `kind`:
//   • semi: "READY" + SATU tombol "🎯 PILIH SINYAL" (buka AI Suggestions).
//     Tidak ada STOP (eksekusi 1-tap, bukan proses kontinu).
//   • full: START (pink) → scan 24/7. STOP (light blue) → henti scan baru,
//     posisi lama tetap aman via native SL/TP.
function StatusCard({ kind, running, onPrimary, onStop, reverseOn, onToggleReverse, colors, t }: {
  kind: "semi" | "full";
  running: boolean;
  onPrimary: () => void;
  onStop: () => void;
  reverseOn: boolean;
  onToggleReverse: () => void;
  colors: any;
  t: (k: string) => string;
}) {
  const isFull = kind === "full";
  const accent = isFull ? ORANGE : GREEN;
  const title = isFull ? t("asi_card_full_title") : t("asi_card_semi_title");
  // Semi: "READY" (tidak pernah "stopped"). Full: STOPPED / RUNNING.
  const statusLine = isFull
    ? (running ? t("asi_status_running") : t("asi_status_stopped"))
    : t("asi_semi_ready");
  const sub = isFull
    ? (running ? t("asi_card_full_sub_on") : t("asi_card_full_sub_off"))
    : t("asi_card_semi_sub_ready");
  const emoji = isFull ? "🤖" : "🦾";
  return (
    <View style={[s.card, {
      borderColor: (isFull ? running : true) ? accent : colors.border,
      backgroundColor: colors.surface,
      borderWidth: 2,
    }]} testID={`asi-card-${kind}`}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <Text style={{ fontSize: 20 }}>{emoji}</Text>
        <View style={[s.dot, { backgroundColor: accent }]} />
        <Text style={[s.cardTitle, { color: accent }]}>
          {title.toUpperCase()} · {statusLine}
        </Text>
        <View style={{ flex: 1 }} />
        <View style={{
          paddingHorizontal: 7, paddingVertical: 2, borderRadius: 5,
          backgroundColor: accent,
        }}>
          <Text style={{
            color: ACCENT_TEXT, fontWeight: "900", fontSize: 9.5, letterSpacing: 0.5,
          }}>
            {isFull ? t("asi_badge_full") : t("asi_badge_semi")}
          </Text>
        </View>
      </View>
      <Text style={[s.cardSub, { color: colors.textMuted }]}>{sub}</Text>
      {isFull ? (
        <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
          {/* v10.6.2 — SATU tombol bergantian Start/Stop + Reverse di kanan */}
          <TouchableOpacity
            onPress={running ? onStop : onPrimary}
            style={[s.bigBtn, { backgroundColor: running ? LIGHT_BLUE : PINK }]}
            testID="asi-toggle-full"
          >
            <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.5 }}>
              {running ? t("asi_stop_bot") : t("asi_run_bot")}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onToggleReverse}
            style={[s.bigBtn, { backgroundColor: reverseOn ? ORANGE : colors.border }]}
            testID="asi-reverse-toggle"
          >
            <Text style={{ color: reverseOn ? ACCENT_TEXT : colors.textPrimary, fontWeight: "900", letterSpacing: 0.5 }}>
              ⇅ REVERSE {reverseOn ? "ON" : "OFF"}
            </Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View style={{ marginTop: 12 }}>
          <TouchableOpacity
            onPress={onPrimary}
            style={[s.bigBtn, { backgroundColor: PINK }]}
            testID="asi-pick-signal"
          >
            <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.6, fontSize: 13 }}>
              {t("asi_pick_signal")}
            </Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

// v9.9.13 — Label formula SINGKAT yang dipakai saat trade dieksekusi.
// Tag modul spesifik yang memicu sinyal (mis. "John Wick Candle Stick")
// diprioritaskan; fallback ke formula dasar profil.
function formulaLines(t: (k: string) => string, profile?: string | null, tag?: string | null): string[] {
  if (tag) return [tag];
  const p = profile || "confluence";
  if (p === "scalper") return [t("asi_formula_scalper")];
  if (p === "day") return [t("asi_formula_day")];
  if (p === "swing") return [t("asi_formula_swing")];
  return [t("asi_formula_confluence")];
}

function ParamRow({ label, value, onDec, onInc, colors, testID }: {
  label: string; value: string; onDec: () => void; onInc: () => void; colors: any; testID?: string;
}) {
  return (
    <View style={[s.paramRow, { backgroundColor: colors.surface, borderColor: colors.border }]} testID={testID}>
      <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{label}</Text>
      <View style={{ flex: 1 }} />
      <TouchableOpacity onPress={onDec} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="remove" size={16} color={colors.textPrimary} />
      </TouchableOpacity>
      <Text style={{ color: GOLD, fontWeight: "900", width: 70, textAlign: "center", fontSize: 14 }}>{value}</Text>
      <TouchableOpacity onPress={onInc} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="add" size={16} color={colors.textPrimary} />
      </TouchableOpacity>
    </View>
  );
}

function ConnectExchangeModal({ visible, onClose, exchange, colors, onSaved, deviceId }: {
  visible: boolean; onClose: () => void; exchange: ExchangeId; colors: any;
  onSaved: (savedTestnet?: boolean) => void; deviceId: string;
}) {
  const { t } = useI18n();
  const [k, setK] = useState(""); const [s2, setS2] = useState(""); const [p, setP] = useState("");
  const [network, setNetwork] = useState<"testnet" | "mainnet">("testnet");
  const [mainnetAck, setMainnetAck] = useState(false);
  const [loading, setLoading] = useState(false);
  const [serverIp, setServerIp] = useState("143.198.197.107");
  const [copied, setCopied] = useState(false);
  const ex = useMemo(() => EXCHANGES.find((e) => e.id === exchange)!, [exchange]);
  const isMainnet = network === "mainnet";

  useEffect(() => {
    if (visible) {
      api.asi.serverIp().then((r) => { if (r?.ip) setServerIp(r.ip); }).catch(() => {});
    }
  }, [visible]);

  const copyIp = async () => {
    await Clipboard.setStringAsync(serverIp);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const save = async () => {
    if (!k || !s2) return Alert.alert(t("asi_alert_fill_title"), t("asi_alert_fill_body"));
    if (ex.needsPass && !p) return Alert.alert(t("asi_alert_fill_title"), t("asi_alert_pass_body").replace("{ex}", ex.label));
    if (isMainnet && !mainnetAck) {
      return Alert.alert(t("asi_alert_mainnet_title"), t("asi_alert_mainnet_body"));
    }
    setLoading(true);
    try {
      await api.asi.saveCredential(deviceId, {
        exchange, api_key: k.trim(), api_secret: s2.trim(),
        password: ex.needsPass ? p.trim() : null, testnet: !isMainnet,
      });
      // v9.9.5 — Hanya slot jaringan yang dipilih yang ditimpa; slot
      // jaringan lain tetap utuh.
      setK(""); setS2(""); setP(""); setMainnetAck(false); onSaved(!isMainnet);
    } catch (e: any) {
      // v9.6.9 — Backend returns {code, message} on validation failure.
      // Fetch wrapper surfaces either `detail` (FastAPI JSON) or `message`.
      const detail = e?.detail || e?.body?.detail || e?.data || {};
      const code: string | undefined = detail?.code || e?.code;
      const localized = code && t(`asi_err_${code}`);
      // t() returns the key itself when missing — treat that as "no translation"
      const human = (localized && localized !== `asi_err_${code}`)
        ? localized
        : (detail?.message || e?.message || String(e));
      Alert.alert(t("asi_alert_fail_title"), human);
    } finally { setLoading(false); }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={m.backdrop} onPress={onClose}>
        <Pressable style={[m.sheet, { backgroundColor: colors.surface }]} onPress={(e) => e.stopPropagation()}>
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ gap: 10 }}>
            <Text style={[m.title, { color: colors.textPrimary }]}>{t("asi_connect_title").replace("{ex}", ex.label)}</Text>
            <Text style={[m.sub, { color: colors.textMuted }]}>
              {t("asi_connect_sub")}
            </Text>

            {/* Network selector: TESTNET / MAINNET */}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
              {(["testnet", "mainnet"] as const).map((n) => {
                const active = network === n;
                const isM = n === "mainnet";
                return (
                  <TouchableOpacity
                    key={n}
                    onPress={() => setNetwork(n)}
                    style={[m.netChip, {
                      flex: 1,
                      backgroundColor: active ? (isM ? RED : GOLD) : colors.background,
                      borderColor: active ? (isM ? RED : GOLD) : colors.border,
                    }]}
                  >
                    <Text style={{
                      color: active ? (isM ? "#fff" : ACCENT_TEXT) : colors.textPrimary,
                      fontWeight: "900", fontSize: 12, letterSpacing: 0.8,
                    }}>
                      {isM ? "🔴 MAINNET" : "🧪 TESTNET"}
                    </Text>
                    <Text style={{
                      color: active ? (isM ? "#FFE5E5" : "rgba(255,255,255,0.85)") : colors.textMuted,
                      fontSize: 10, marginTop: 2,
                    }}>
                      {isM ? t("asi_net_mainnet_sub") : t("asi_net_testnet_sub")}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            {/* IP Whitelist guidance card (crucial for Binance & security) */}
            <View style={[m.ipCard, { borderColor: colors.border, backgroundColor: colors.background }]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Ionicons name="shield-checkmark" size={16} color={GOLD} />
                <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 12 }}>
                  {t("asi_ip_title")}
                </Text>
              </View>
              <Text style={{ color: colors.textMuted, fontSize: 11, lineHeight: 16 }}>
                {t("asi_ip_sub")}
              </Text>

              {/* IP Copy Box */}
              <View style={[m.ipRow, { backgroundColor: colors.surface, borderColor: GOLD }]}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: colors.textMuted, fontSize: 9.5, fontWeight: "700" }}>{t("asi_ip_label")}</Text>
                  <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 13, fontFamily: Platform.OS === "ios" ? "Courier" : "monospace", letterSpacing: 0.5 }}>
                    {serverIp}
                  </Text>
                </View>
                <TouchableOpacity onPress={copyIp} style={[m.copyBtn, { backgroundColor: copied ? GREEN : GOLD }]}>
                  <Ionicons name={copied ? "checkmark" : "copy-outline"} size={14} color={ACCENT_TEXT} />
                  <Text style={{ color: ACCENT_TEXT, fontWeight: "900", fontSize: 11 }}>
                    {copied ? t("asi_ip_copied") : t("asi_ip_copy")}
                  </Text>
                </TouchableOpacity>
              </View>

              <View style={{ gap: 3, marginTop: 4 }}>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step1")}</Text>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step2")}</Text>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step3")}</Text>
                <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }}>{t("asi_ip_step4")}</Text>
              </View>
            </View>

            <TextInput value={k} onChangeText={setK} placeholder="API Key" placeholderTextColor={colors.textMuted}
                       style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} autoCapitalize="none" />
            <TextInput value={s2} onChangeText={setS2} placeholder="API Secret" placeholderTextColor={colors.textMuted}
                       style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} secureTextEntry autoCapitalize="none" />
            {ex.needsPass ? (
              <TextInput value={p} onChangeText={setP} placeholder="Passphrase" placeholderTextColor={colors.textMuted}
                         style={[m.input, { color: colors.textPrimary, borderColor: colors.border }]} secureTextEntry autoCapitalize="none" />
            ) : null}

            {isMainnet ? (
              <Pressable
                onPress={() => setMainnetAck((v) => !v)}
                style={[m.warnBox, { borderColor: RED, backgroundColor: "rgba(239,68,68,0.08)" }]}
              >
                <View style={[s.checkbox, { borderColor: RED, backgroundColor: mainnetAck ? RED : "transparent" }]}>
                  {mainnetAck ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                </View>
                <Text style={{ color: colors.textPrimary, fontSize: 11.5, flex: 1, lineHeight: 16 }}>
                  {t("asi_mainnet_ack")}
                </Text>
              </Pressable>
            ) : null}

            <TouchableOpacity onPress={save} disabled={loading || (isMainnet && !mainnetAck)}
                              style={[m.save, { backgroundColor: loading ? colors.textMuted : (isMainnet ? RED : GOLD) }]}>
              <Text style={{ color: isMainnet ? "#fff" : ACCENT_TEXT, fontWeight: "900", letterSpacing: 0.6 }}>
                {loading ? t("asi_verifying") : isMainnet ? t("asi_save_mainnet") : t("asi_save_testnet")}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onClose} style={{ padding: 8, alignItems: "center" }}>
              <Text style={{ color: colors.textMuted }}>{t("common_cancel")}</Text>
            </TouchableOpacity>
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  sub: { fontSize: 11, marginTop: 2 },
  card: { borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 4 },
  bigBtn: { flex: 1, paddingVertical: 13, borderRadius: 12, alignItems: "center" },
  cardTitle: { fontWeight: "900", fontSize: 13, letterSpacing: 0.5 },
  cardSub: { marginTop: 6, fontSize: 12, lineHeight: 18 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  row: { flexDirection: "row", alignItems: "center", padding: 12, borderWidth: 1, borderRadius: 10 },
  rowLabel: { fontWeight: "800" },
  modeChip: { flex: 1, borderWidth: 1.5, borderRadius: 14, padding: 12, alignItems: "flex-start", gap: 6 },
  tpChip: { flex: 1, borderWidth: 1.5, borderRadius: 10, paddingVertical: 10, alignItems: "center" },
  acChip: { width: "30.5%", minHeight: 44, borderWidth: 1.5, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  modeTitle: { fontWeight: "900", fontSize: 13 },
  modeSub: { fontSize: 10.5, lineHeight: 15 },
  paramRow: { flexDirection: "row", alignItems: "center", padding: 10, borderWidth: 1, borderRadius: 10, marginBottom: 8, gap: 10 },
  stepBtn: { width: 32, height: 32, borderRadius: 8, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  checkbox: { width: 20, height: 20, borderRadius: 5, borderWidth: 1.5, alignItems: "center", justifyContent: "center" },
  pnlCard: { flex: 1, padding: 12, borderRadius: 12, borderWidth: 1 },
  pnlLabel: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5, textTransform: "uppercase" },
  pnlValue: { fontSize: 16, fontWeight: "900", marginTop: 4 },
  leaderRow: { gap: 6, padding: 10, borderWidth: 1, borderRadius: 10 },
  rank: { fontWeight: "900", width: 32 },
  handle: { fontWeight: "900", letterSpacing: 1 },
});

const m = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.65)", justifyContent: "flex-end" },
  sheet: { borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 20, gap: 10,
           maxHeight: "88%",
           paddingBottom: Platform.OS === "ios" ? 32 : 20 },
  title: { fontSize: 16, fontWeight: "900" },
  sub: { fontSize: 11.5, lineHeight: 17 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: Platform.OS === "ios" ? 12 : 8,
           marginTop: 8 },
  save: { padding: 14, borderRadius: 12, alignItems: "center", marginTop: 10 },
  netChip: { padding: 12, borderRadius: 12, borderWidth: 1.5, alignItems: "center" },
  warnBox: { flexDirection: "row", gap: 10, alignItems: "flex-start", padding: 12,
             borderRadius: 10, borderWidth: 1.5, marginTop: 10 },
  ipCard: { padding: 12, borderRadius: 12, borderWidth: 1, gap: 6, marginTop: 4 },
  ipRow: { flexDirection: "row", alignItems: "center", padding: 10, borderRadius: 8, borderWidth: 1, gap: 8, marginTop: 2 },
  copyBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 7, borderRadius: 6 },
});
