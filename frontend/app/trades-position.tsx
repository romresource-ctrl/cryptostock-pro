// v10.0.6 — Trades Position screen.
// Dedicated page accessible from the Dashboard (button next to Trader
// Profile picker). Shows the SAME list of trades as the Recent Trades
// section inside ASI-Bot, so users can check positions without scrolling
// the long ASI-Bot screen. Supports CLOSE (open), CANCEL (pending), and
// swipe-to-delete for closed/cancelled/expired/orphaned cards.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator, Alert, Platform, ScrollView, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";
// v10.1.1 — Touchable dari RNGH untuk KARTU: bernegosiasi dengan gesture
// Swipeable sehingga swipe-delete TIDAK lagi memicu navigasi tap.
import { TouchableOpacity as CardTouchable } from "react-native-gesture-handler";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { useTraderProfile } from "@/src/lib/useTraderProfile";
import { prefetchChart } from "@/src/lib/chartCache";
import { readPageCache, writePageCache } from "@/src/lib/pageCache";
import { useBinanceMultiTicker } from "@/src/hooks/useBinanceMultiTicker";
import { markTradeDeleted, filterDeletedTrades } from "@/src/lib/deletedTrades";
import { getDeviceId } from "@/src/lib/deviceId";
import { api, type AsiTradeResp } from "@/src/lib/api";

const GOLD = "#4ADE80";
const YELLOW = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";
const BLUE = "#38BDF8";
const PURPLE = "#A78BFA";
const ORANGE = "#F97316"; // v10.1.5 — chip REAL

type AnyTrade = AsiTradeResp & Record<string, any>;

export default function TradesPositionScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const { apiProfile } = useTraderProfile();
  const [deviceId, setDeviceId] = useState<string>("");
  const [trades, setTrades] = useState<AnyTrade[]>([]);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  // v10.1.5 — Saldo DEMO/REAL untuk ringkasan dua kolom di atas list.
  const [balance, setBalance] = useState<{
    demo: { connected: boolean; available_usdt: number | null };
    real: { connected: boolean; available_usdt: number | null };
  }>({ demo: { connected: false, available_usdt: null },
       real: { connected: false, available_usdt: null } });
  const pollRef = useRef<any>(null);
  const priceRef = useRef<any>(null);

  useEffect(() => {
    (async () => setDeviceId(await getDeviceId()))();
  }, []);

  const load = useCallback(async () => {
    if (!deviceId) return;
    // v10.2.9 — PERCEPATAN LOAD: fetch balance DIPARARELKAN dan tidak
    // lagi menahan spinner list. Sebelumnya `await balance` (memanggil
    // API Binance, bisa 1-3 detik di produksi saat cache 4s miss)
    // menghalangi finally → halaman Running Positions terasa sangat
    // lambat padahal daftar posisi sudah siap.
    const fetchBalance = async () => {
      // v10.1.5 — Saldo kedua jaringan (opsional; jangan ganggu list).
      // v10.1.7 — Hanya update balance bila fetch sukses & nilainya valid
      // (tidak null), supaya saldo DEMO/REAL tidak "hilang-timbul" saat
      // request sesaat gagal.
      try {
        const b = await api.asi.balance(deviceId, "binance");
        setBalance((prev) => ({
          demo: {
            connected: b.demo?.connected ?? prev.demo.connected,
            available_usdt: b.demo?.available_usdt != null ? b.demo.available_usdt : prev.demo.available_usdt,
          },
          real: {
            connected: b.real?.connected ?? prev.real.connected,
            available_usdt: b.real?.available_usdt != null ? b.real.available_usdt : prev.real.available_usdt,
          },
        }));
      } catch { /* no-op */ }
    };
    fetchBalance(); // fire-and-forget: TIDAK ditunggu, spinner hanya
                    // menunggu daftar posisi.
    try {
      // v10.2.2 — History diperluas 50 → 100 posisi (permintaan user).
      const r = await api.asi.listTrades(deviceId, 100);
      const items = (await filterDeletedTrades(((r as any).items || r || []) as AnyTrade[]))
        // v10.2.9 — Anti-resurrect: kartu yang baru saja dihapus user
        // (optimistic) tidak boleh muncul lagi akibat race dengan poll
        // 5 detik yang sedang in-flight.
        // v10.2.16 — filterDeletedTrades: tombstone BERSAMA lintas
        // halaman (delete di Recent Trades juga berlaku di sini).
        .filter((x) => !deletedRef.current.has(String((x as any)._id || x.id || "")));
      setTrades(items);
      // v10.2.16 — Prefetch chart untuk SEMUA kartu yang terlihat begitu
      // list selesai dimuat → tap kartu membuka halaman detail aset
      // seketika (tanpa menunggu network).
      try {
        const bases = Array.from(new Set(
          items.map((x) => String((x as any).symbol || "").replace(/USDT$/i, "").toUpperCase())
              .filter(Boolean)
        )).slice(0, 30);
        bases.forEach((b, i) => setTimeout(
          () => prefetchChart("crypto", b, "1h", apiProfile ?? undefined),
          i * 120,
        ));
      } catch { /* abaikan */ }
      // v10.2.9 — Simpan ke page cache supaya kunjungan berikutnya
      // halaman langsung menggambar daftar ini TANPA spinner.
      writePageCache(`trades:${deviceId}`, items);
    } catch { /* keep previous */ }
    finally { setLoading(false); }
  }, [deviceId, apiProfile]);

  // v10.2.9 — INSTANT OPEN: render cache terakhir seketika saat halaman
  // dibuka (keluhan user: "buka Running Positions sangat lambat"),
  // lalu load() menyusul dengan data segar di background.
  useEffect(() => {
    if (!deviceId) return;
    let alive = true;
    (async () => {
      const cached = await readPageCache<AnyTrade[]>(`trades:${deviceId}`);
      if (alive && cached && cached.length > 0) {
        // v10.2.16 — Saring tombstone bersama: kartu yang dihapus di
        // Recent Trades tidak boleh bangkit dari cache halaman ini.
        setTrades(await filterDeletedTrades(cached));
        setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [deviceId]);

  useFocusEffect(
    useCallback(() => {
      if (!deviceId) return;
      load();
      // v10.1.8 — Interval 5 detik (disamakan dengan Recent Trades) supaya
      // status LIMIT WAITING → OPEN sinkron antar layar tanpa jeda 10-20s.
      // v10.2.11 — FOCUS-GATED: berhenti saat layar tidak terlihat supaya
      // tidak membebani halaman grafik yang dibuka di atasnya.
      pollRef.current = setInterval(load, 5_000);
      return () => clearInterval(pollRef.current);
    }, [deviceId, load])
  );

  // Mark price polling untuk posisi OPEN *dan* LIMIT pending — kartu
  // pending juga harus ticking supaya user bisa memantau harga live
  // terhadap harga limit-nya (v10.1.8, keluhan "kartu diam").
  const openSyms = useMemo(() =>
    Array.from(new Set(
      trades.filter((t2) => (t2.status === "open" || t2.status === "pending_entry") && t2.symbol).map((t2) => t2.symbol as string)
    )), [trades]);

  const openSymsKey = openSyms.join(",");
  // v10.0.10 — Flash direction per simbol (naik=hijau, turun=merah) supaya
  // harga & PnL "berkedip hidup" tiap ada perubahan tick.
  const prevPricesRef = useRef<Record<string, number>>({});
  // v10.2.9 — Set id kartu yang sedang/baru dihapus secara optimistic;
  // dipakai load() untuk mencegat kartu "muncul lagi" akibat race poll.
  const deletedRef = useRef<Set<string>>(new Set());
  const flashTimerRef = useRef<any>(null);
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});
  // v10.2.16 — WS aggTrade langsung dari device (sumber yang sama dengan
  // halaman grafik yang terbukti LIVE). Polling backend 300ms bisa
  // membeku bila upstream production terblokir / request menggantung —
  // stream ini membuat harga & PnL kartu kembali "berkedip" realtime.
  // Keduanya di-MERGE: polling tetap melengkapi simbol non-Binance.
  const wsPx = useBinanceMultiTicker(openSyms);
  useEffect(() => {
    const ks = Object.keys(wsPx);
    if (ks.length === 0) return;
    const f: Record<string, "up" | "down"> = {};
    ks.forEach((k) => {
      const prev = prevPricesRef.current[k];
      const v = wsPx[k];
      if (prev != null && v !== prev) f[k] = v > prev ? "up" : "down";
    });
    prevPricesRef.current = { ...prevPricesRef.current, ...wsPx };
    setPrices((cur) => ({ ...cur, ...wsPx }));
    if (Object.keys(f).length > 0) {
      setFlash((cur) => ({ ...cur, ...f }));
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
      flashTimerRef.current = setTimeout(() => setFlash({}), 700);
    }
  }, [wsPx]);
  useFocusEffect(
    useCallback(() => {
      if (!openSyms.length) {
        if (priceRef.current) { clearInterval(priceRef.current); priceRef.current = null; }
        return;
      }
      // v10.2.16 — Anti penumpukan: interval 300ms tapi respons backend
      // bisa 2-5 detik di jaringan HP → tanpa guard, request menumpuk
      // dan harga justru tampak membeku. Lewati tick bila request
      // sebelumnya belum selesai.
      let inFlight = false;
      const tick = async () => {
        if (inFlight) return;
        inFlight = true;
        try {
          const r = await api.asi.prices(openSyms);
          const m: Record<string, number> = {};
          Object.entries(r.prices || {}).forEach(([k, v]) => {
            m[k.replace(/USDT$/, "")] = v as number;
          });
          // Bandingkan dengan tick sebelumnya → tentukan arah kedip.
          const f: Record<string, "up" | "down"> = {};
          Object.entries(m).forEach(([k, v]) => {
            const prev = prevPricesRef.current[k];
            if (prev != null && v !== prev) f[k] = v > prev ? "up" : "down";
          });
          prevPricesRef.current = { ...prevPricesRef.current, ...m };
          // v10.2.4 — MERGE, jangan timpa: response kosong sesaat tidak
          // boleh menghapus harga yang sudah tampil (anti dash serentak).
          setPrices((cur) => ({ ...cur, ...m }));
          if (Object.keys(f).length > 0) {
            setFlash((cur) => ({ ...cur, ...f }));
            if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
            flashTimerRef.current = setTimeout(() => setFlash({}), 700);
          }
        } catch { /* ignore */ }
        finally { inFlight = false; }
      };
      tick();
      // v10.1.7 — Polling 300ms (sebelumnya 2000ms) agar mark price
      // real-time dan berkedip persis seperti chart candlestick.
      // v10.2.11 — HANYA saat layar terlihat (useFocusEffect): sebelumnya
      // interval 300ms ini terus berjalan saat user membuka grafik aset
      // di atas layar ini → membebani CPU/network HP → grafik lambat.
      priceRef.current = setInterval(tick, 300);
      return () => clearInterval(priceRef.current);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [openSymsKey])
  );

  const onClose = useCallback(async (tr: AnyTrade) => {
    const isPending = tr.status === "pending_entry";
    // v10.0.15 — Semua teks dialog mengikuti bahasa pilihan user.
    const confirmMsg = isPending
      ? t("pos_cancel_body")
      : t("pos_close_body");
    const ask = Platform.OS === "web"
      ? Promise.resolve(window.confirm(confirmMsg))
      : new Promise<boolean>((resolve) => Alert.alert(
          isPending ? t("pos_cancel_title") : t("pos_close_title"),
          confirmMsg,
          [{ text: t("pos_btn_back"), style: "cancel", onPress: () => resolve(false) },
           { text: isPending ? t("asi_btn_cancel") : t("asi_recent_close"),
             style: "destructive", onPress: () => resolve(true) }]
        ));
    const ok = await ask;
    if (!ok) return;
    setBusyId(tr.id || tr._id);
    try {
      await api.asi.closeTrade(deviceId, tr.id || tr._id);
      await load();
    } catch (e: any) {
      Alert.alert(t("asi_close_failed") || "Action failed", String(e?.message || e));
    } finally { setBusyId(null); }
  }, [deviceId, load, t]);

  const onDelete = useCallback(async (tr: AnyTrade) => {
    const tid = String(tr.id || (tr as any)._id || "");
    if (!tid || !deviceId) return;
    // v10.2.9 — OPTIMISTIC DELETE (keluhan user: hapus kartu lambat &
    // kadang tidak terdelete). Kartu langsung hilang dari layar;
    // request jalan di background; gagal → kartu dikembalikan + alert.
    deletedRef.current.add(tid);
    // v10.2.16 — Tombstone BERSAMA: Recent Trades juga memfilter id ini
    // dari cache & poll-nya (fix: hapus di Running Positions tidak
    // menghilangkan kartu di Recent Trades).
    void markTradeDeleted(tid);
    setTrades((list) => list.filter((x) => String((x as any)._id || x.id || "") !== tid));
    // Lepas flag anti-resurrect setelah 15 detik (server sudah pasti
    // menghapus; poll berikutnya membawa data bersih).
    setTimeout(() => deletedRef.current.delete(tid), 15_000);
    try {
      await api.asi.deleteTrade(deviceId, tid);
    } catch (e: any) {
      deletedRef.current.delete(tid);
      Alert.alert(t("asi_close_failed") || "Action failed", String(e?.message || e));
      await load();
    }
  }, [deviceId, load, t]);

  // Local price formatter (adaptive precision, no `market` dependency).
  const fp = (v: number | null | undefined): string => {
    if (v == null || isNaN(Number(v))) return "—";
    const n = Number(v);
    const abs = Math.abs(n);
    if (abs >= 1000) return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (abs >= 100) return n.toFixed(2);
    if (abs >= 1) return n.toFixed(4);
    if (abs >= 0.01) return n.toFixed(5);
    if (abs >= 0.0001) return n.toFixed(6);
    return n.toFixed(8).replace(/\.?0+$/, "");
  };

  const fmtDateTime = (iso?: string | null): string => {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const closedReason = (r?: string | null): string => {
    const x = String(r || "");
    if (/^TP\d?$/.test(x)) return `Closed on ${x}`;
    if (x === "SL") return "Closed on SL";
    if (x === "cancelled_pending") return "Canceled by user";
    if (x === "entry_expired") return "Canceled: expired";
    if (x === "manual_cleanup") return "Closed on cleanup";
    if (x === "bracket_failed_after_fill") return "Closed: bracket fail";
    if (x === "orphaned_no_credential") return "No credential (orphaned)";
    if (x === "MANUAL") return "Closed manually";
    if (x === "TRAILING") return "Closed on Trailing Stop";
    if (x === "BREAK_EVEN") return "Closed on Break-Even";
    // v10.1.5 — "position_closed_externally" tidak ditampilkan apa adanya;
    // disajikan sebagai "Closed on exchange" tanpa kode internal.
    if (x === "position_closed_externally") return "Closed on exchange";
    return x ? `Closed: ${x}` : "Closed";
  };

  const renderCard = (tr: AnyTrade) => {
    const isOpen = tr.status === "open";
    const isPending = tr.status === "pending_entry";
    const isLong = tr.side === "BUY";
    const symKey = tr.symbol ? String(tr.symbol).replace("USDT", "") : "";
    const live = symKey ? prices[symKey] : undefined;
    // v10.0.10 — PnL REALTIME: dihitung ulang dari mark price live tiap
    // tick 2 detik (bukan menunggu refresh DB 10 detik). Fallback ke
    // nilai DB bila harga belum masuk. Catatan: memakai qty awal; setelah
    // partial TP, nilai DB (10s) yang lebih akurat.
    let pnl = Number(tr.pnl_usdt ?? 0);
    if (isOpen && live != null && tr.entry_price && tr.qty) {
      pnl = (isLong ? 1 : -1) * (live - Number(tr.entry_price)) * Number(tr.qty);
    }
    const flashDir = symKey ? flash[symKey] : undefined;
    const borderColor = isPending ? YELLOW
      : (isOpen ? (pnl >= 0 ? GREEN : RED) : colors.border);
    const canDelete = !isOpen && !isPending;
    const inner = (
      <CardTouchable activeOpacity={0.75}
        onPress={() => {
          // v10.1.1 — Normalisasi symbol ("XRPUSDT" → "XRP") sebelum
          // membuka detail aset/chart.
          const base = String(tr.symbol || "").replace(/USDT$/, "");
          if (!base) return;
          // v10.2.9 — PREFETCH: fetch chart mulai SEKARANG (sebelum
          // navigasi selesai) supaya halaman grafik terbuka hampir
          // instan — keluhan user "grafik lambat saat tap kartu".
          prefetchChart("crypto", base, "1h", apiProfile ?? undefined);
          router.push(`/asset/crypto/${encodeURIComponent(base)}` as any);
        }}
        style={[s.card, { backgroundColor: colors.surface, borderColor }]}>
        {/* v10.1.7 — Layout 3-BARIS (anti-jiggle):
            Baris 1 : Tanggal & Jam · (closed reason bila CLOSED)
            Baris 2 : Symbol (kiri) | Mark Price (tengah) | PnL $ + % (kanan)
            Baris 3 : Semua badge (D/R, LONG/SHORT, mode, entry mode,
                      layer, status, margin mode, leverage, formula). */}

        {/* ───────────── BARIS 1 : Tanggal & Jam ───────────── */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Text style={{ fontSize: 11, fontWeight: "800", color: "#FFFFFF" }}>
            {tr.filled_at
              ? `filled ${fmtDateTime(tr.filled_at)}`
              : (tr.created_at ? fmtDateTime(tr.created_at) : "")}
          </Text>
          {!isOpen && !isPending ? (
            <>
              <Text style={{ color: "#FFFFFF", fontSize: 11 }}>·</Text>
              <Text numberOfLines={1} style={{ fontSize: 11, fontWeight: "800", color: "#FFFFFF", flexShrink: 1 }}>
                {closedReason(tr.close_reason)}
                {tr.closed_at ? ` · ${fmtDateTime(tr.closed_at)}` : ""}
              </Text>
            </>
          ) : null}
        </View>

        {/* ───────────── BARIS 2 : Symbol | Mark | PnL ───────────── */}
        <View style={{
          marginTop: 4, flexDirection: "row", alignItems: "center",
          justifyContent: "space-between", gap: 8,
        }}>
          {/* Kiri: Symbol/USDT (slot flex=1) */}
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text numberOfLines={1}
              style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
              {tr.symbol}/USDT
            </Text>
          </View>
          {/* Tengah: Mark Price (lebar tetap, tabular-nums → anti-jiggle).
              v10.2.4 — KOLOM INI TIDAK BOLEH PERNAH KOSONG ("—"):
              • OPEN/LIMIT → mark price live ticking (putih terang + flash)
              • CLOSED → harga exit (closed_price), fallback entry price
              Sesuai permintaan user: mark price harus SELALU tampil baik
              opened maupun closed. */}
          <View style={{ width: 110, alignItems: "center" }}>
            <View style={{
              paddingHorizontal: 7, paddingVertical: 2, borderRadius: 5,
              backgroundColor: live != null && flashDir === "up" ? GREEN + "33"
                : live != null && flashDir === "down" ? RED + "33" : "transparent",
            }}>
              <Text style={{
                color: "#FFFFFF", fontSize: 14, fontWeight: "900",
                fontVariant: ["tabular-nums"], letterSpacing: 0.3,
              }}>
                {live != null
                  ? `$${fp(live)}${flashDir ? (flashDir === "up" ? " ▲" : " ▼") : ""}`
                  : `$${fp(tr.closed_price ?? tr.entry_price)}`}
              </Text>
            </View>
          </View>
          {/* Kanan: PnL $ + % (lebar tetap 100px → anti-jiggle) */}
          <View style={{ width: 100, alignItems: "flex-end" }}>
            {isPending ? (
              <View style={{ paddingHorizontal: 7, paddingVertical: 3, borderRadius: 6, backgroundColor: YELLOW }}>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 10 }}>LIMIT WAITING</Text>
              </View>
            ) : (
              <View style={{ alignItems: "flex-end" }}>
                <View style={{
                  paddingHorizontal: 7, paddingVertical: 2, borderRadius: 5,
                  backgroundColor: isOpen && flashDir === "up" ? GREEN + "33"
                    : isOpen && flashDir === "down" ? RED + "33" : "transparent",
                }}>
                  <Text style={{
                    color: pnl >= 0 ? GREEN : RED, fontWeight: "900",
                    fontSize: 17, fontVariant: ["tabular-nums"],
                  }}>
                    {pnl >= 0 ? "+" : "-"}${Math.abs(pnl).toFixed(2)}
                  </Text>
                </View>
                {/* v10.1.7 — % PnL SELALU tampil, baik OPEN maupun CLOSED
                    (sesuai permintaan user untuk kartu closed position). */}
                {tr.margin_usdt ? (
                  <Text style={{
                    color: pnl >= 0 ? GREEN : RED, fontWeight: "700", fontSize: 10,
                    fontVariant: ["tabular-nums"],
                  }}>
                    {pnl >= 0 ? "+" : ""}{(pnl / Number(tr.margin_usdt) * 100).toFixed(2)}%
                    {isOpen && flashDir ? (flashDir === "up" ? " ▲" : " ▼") : ""}
                  </Text>
                ) : null}
              </View>
            )}
          </View>
        </View>

        {/* ───────────── BARIS 3 : SEMUA BADGE (bungkus bila banyak) ───────────── */}
        <View style={{ marginTop: 6, flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {/* D/R Demo/Real */}
          <View style={{
            paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
            backgroundColor: tr.testnet ? "#60A5FA" : "#F97316",
          }}>
            <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
              {tr.testnet ? "D" : "R"}
            </Text>
          </View>
          {/* Mode SEMI/FULL */}
          {tr.mode ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: tr.mode === "full" ? BLUE : GOLD }}>
              <Text style={{ fontSize: 11, fontWeight: "900" }}>
                {tr.mode === "full" ? "🤖" : "🦾"}
              </Text>
            </View>
          ) : null}
          {/* Entry Mode L/M */}
          {tr.entry_mode ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: tr.entry_mode === "market" ? PURPLE : YELLOW }}>
              <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                {tr.entry_mode === "market" ? "M" : "L"}
              </Text>
            </View>
          ) : null}
          {/* LONG / SHORT */}
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: isLong ? GREEN : RED }}>
            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
              {isLong ? "LONG" : "SHORT"}
            </Text>
          </View>
          {/* Leverage */}
          {tr.leverage ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: colors.surfaceAlt || "#1F2937" }}>
              <Text style={{ color: GREEN, fontWeight: "900", fontSize: 10 }}>
                {tr.leverage}x
              </Text>
            </View>
          ) : null}
          {/* Margin mode */}
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: ((tr.actual_margin_mode || tr.margin_mode) === "cross") ? PURPLE : "#14B8A6" }}>
            <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9 }}>
              {String(tr.actual_margin_mode || tr.margin_mode || "ISOLATED").toUpperCase()}
            </Text>
          </View>
          {/* Formula tag */}
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: colors.surfaceAlt || "#1F2937" }}>
            <Text numberOfLines={1} style={{ color: colors.textMuted, fontSize: 9, fontWeight: "800" }}>
              ⚙️ {String(tr.formula_tag
                || ({ scalper: "7 Fast VWAP", day: "5 KISS VWAP", swing: "5 Multi-day Trend", longterm: "Confluence v9" } as Record<string, string>)[String(tr.profile || "")]
                || "Confluence v9")}
            </Text>
          </View>
          {/* Status badge */}
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: isOpen ? GREEN : isPending ? YELLOW : colors.border }}>
            <Text style={{ color: isOpen ? "#0B0E11" : isPending ? "#0B0E11" : colors.textMuted, fontWeight: "900", fontSize: 9 }}>
              {isOpen ? "OPEN" : isPending ? "LIMIT" : "CLOSED"}
            </Text>
          </View>
        </View>

        {/* v10.1.8 — Tombol aksi di BARIS SENDIRI, SELALU rata kanan.
            Sebelumnya digabung di baris badge (flexWrap) → spacer
            ter-wrap dan tombol jatuh ke kiri saat badge penuh. */}
        {(isOpen || isPending) ? (
          <View style={{ marginTop: 6, flexDirection: "row", justifyContent: "flex-end" }}>
            <CardTouchable
              style={{ paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6,
                       backgroundColor: isPending ? YELLOW : RED }}
              onPress={() => onClose(tr)}
              disabled={busyId === (tr.id || tr._id)}
            >
              {busyId === (tr.id || tr._id)
                ? <ActivityIndicator size="small" color="#0B0E11" />
                : <Text style={{ color: isPending ? "#0B0E11" : "#fff", fontWeight: "900", fontSize: 11 }}>
                    {isPending ? "CANCEL" : "CLOSE"}
                  </Text>}
            </CardTouchable>
          </View>
        ) : null}

        {/* Detail terkecil (SL/TP/Margin/Entry) — baris pelengkap.
            v10.2.1 — Entry price PUTIH TERANG agar jelas terbaca. */}
        <View style={{ marginTop: 4, gap: 1 }}>
          <Text style={{ fontSize: 11, lineHeight: 15 }}>
            <Text style={{ color: "#FFFFFF", fontWeight: "800" }}>
              Entry {tr.entry_price ? fp(tr.entry_price) : "—"}
            </Text>
            {"  ·  "}
            <Text style={{ color: RED, fontWeight: "800" }}>
              SL {tr.stop_loss ? fp(tr.stop_loss) : "—"}
            </Text>
            {"  ·  "}
            <Text style={{ color: GREEN, fontWeight: "800" }}>
              TP {(tr.take_profits || []).map((x: number) => fp(x)).join(" / ") || "—"}
            </Text>
            {tr.margin_usdt != null ? (
              <>
                {"  ·  "}
                <Text style={{ color: YELLOW, fontWeight: "800" }}>
                  Margin ${Number(tr.margin_usdt).toFixed(2)}
                </Text>
              </>
            ) : null}
            {/* v10.2.4 — Close price eksplisit di kartu closed
                (permintaan user). */}
            {!isOpen && !isPending && tr.closed_price ? (
              <>
                {"  ·  "}
                <Text style={{ color: "#FFFFFF", fontWeight: "800" }}>
                  Close {fp(tr.closed_price)}
                </Text>
              </>
            ) : null}
          </Text>
          {/* Riwayat TP hit */}
          {(() => {
            const tpOnly = (Array.isArray(tr.tp_fills) ? tr.tp_fills : [])
              .filter((f: any) => String(f?.level || "").startsWith("TP"));
            if (!tpOnly.length && !tr.be_moved) return null;
            return (
            <View style={{ marginTop: 2 }}>
              {tpOnly.map((f: any, i: number) => (
                <Text key={i} style={{ fontSize: 10.5, fontWeight: "800", color: "#FFFFFF" }}>
                  ✓ {String(f.level)} hit · ${fp(Number(f.price))}
                  {f.pnl != null ? (
                    <Text style={{ color: Number(f.pnl) >= 0 ? GREEN : RED, fontWeight: "900" }}>
                      {"  "}{Number(f.pnl) >= 0 ? "+" : "-"}${Math.abs(Number(f.pnl)).toFixed(2)}
                    </Text>
                  ) : null}
                </Text>
              ))}
              {tr.be_moved ? (
                <Text style={{ fontSize: 10, fontWeight: "800", color: BLUE, marginTop: 1 }}>
                  🛡️ SL moved to break-even (entry)
                </Text>
              ) : null}
            </View>
            );
          })()}
        </View>
      </CardTouchable>
    );

    if (!canDelete) return <View key={tr.id || tr._id}>{inner}</View>;
    return (
      <ReanimatedSwipeable
        key={tr.id || tr._id}
        renderRightActions={() => (
          <TouchableOpacity
            testID={`tp-del-${tr.symbol || "trade"}`}
            style={{ backgroundColor: RED, justifyContent: "center", alignItems: "center",
                     width: 72, borderRadius: 10, marginVertical: 4 }}
            onPress={() => onDelete(tr)}
          >
            <Ionicons name="trash-outline" size={20} color="#fff" />
            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10, marginTop: 2 }}>DELETE</Text>
          </TouchableOpacity>
        )}
      >
        {inner}
      </ReanimatedSwipeable>
    );
  };

  const openList = useMemo(() => trades.filter((x) => x.status === "open"), [trades]);
  const pendList = useMemo(() => trades.filter((x) => x.status === "pending_entry"), [trades]);
  const histList = useMemo(() => trades.filter((x) =>
    x.status !== "open" && x.status !== "pending_entry"), [trades]);

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={[s.header, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <TouchableOpacity onPress={() => router.back()} style={s.backBtn} testID="tp-back">
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 16 }}>
          Running Positions · {openList.length + pendList.length}
        </Text>
        <TouchableOpacity onPress={load} style={s.backBtn}>
          <Ionicons name="refresh" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 40, gap: 8 }}>
        {loading ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <ActivityIndicator color={GOLD} />
          </View>
        ) : trades.length === 0 ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <Text style={{ color: colors.textMuted, textAlign: "center" }}>
              {t("asi_recent_empty")}
            </Text>
          </View>
        ) : (
          <>
            {/* v10.1.5 — Ringkasan harian 2 KOLOM (DEMO biru / REAL oranye)
                sesuai mockup user. Setiap kolom: P:L count (W×/L×), P (hijau
                nominal + %), L (merah nominal + %), Balance USDT available
                di baris paling bawah. Reset tiap 00:00 jam DEVICE user. */}
            {(() => {
              const pad2 = (n: number) => String(n).padStart(2, "0");
              const dayKey = (d: Date) =>
                `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
              const today = dayKey(new Date());
              const agg = (isDemo: boolean) => {
                let w = 0, l = 0, pU = 0, lU = 0, pP = 0, lP = 0;
                histList.forEach((t2: any) => {
                  if (Boolean(t2.testnet) !== isDemo) return;
                  const iso = t2.closed_at || t2.updated_at;
                  if (!iso) return;
                  const d = new Date(iso);
                  if (isNaN(d.getTime()) || dayKey(d) !== today) return;
                  const pnl2 = Number(t2.pnl_usdt || 0);
                  const marg = Math.max(1, Number(t2.margin_usdt || 1));
                  if (pnl2 > 0) { w++; pU += pnl2; pP += (pnl2 / marg) * 100; }
                  else if (pnl2 < 0) { l++; lU += pnl2; lP += (pnl2 / marg) * 100; }
                });
                return { w, l, pU, lU, pP, lP };
              };
              const demo = agg(true);
              const real = agg(false);
              const demoBal = balance.demo?.available_usdt;
              const realBal = balance.real?.available_usdt;
              const col = (
                title: string, titleColor: string, data: ReturnType<typeof agg>,
                bal: number | null | undefined,
              ) => (
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={{ color: titleColor, fontWeight: "900", fontSize: 13, letterSpacing: 0.6 }}>
                    {title}
                  </Text>
                  <Text style={{ fontSize: 11.5, fontWeight: "800" }}>
                    <Text style={{ color: GREEN }}>P :</Text>
                    <Text style={{ color: colors.textPrimary }}>{` ${data.w}`}</Text>
                    <Text style={{ color: colors.textMuted }}>x </Text>
                    <Text style={{ color: RED }}>L :</Text>
                    <Text style={{ color: colors.textPrimary }}>{` ${data.l}`}</Text>
                    <Text style={{ color: colors.textMuted }}>x</Text>
                  </Text>
                  <Text style={{ color: GREEN, fontSize: 11.5, fontWeight: "800", fontVariant: ["tabular-nums"] }}>
                    P: +${data.pU.toFixed(2)} (+{data.pP.toFixed(1)}%)
                  </Text>
                  <Text style={{ color: RED, fontSize: 11.5, fontWeight: "800", fontVariant: ["tabular-nums"] }}>
                    L: -${Math.abs(data.lU).toFixed(2)} ({data.lP.toFixed(1)}%)
                  </Text>
                  <Text style={{ fontSize: 11.5, fontWeight: "800" }}>
                    <Text style={{ color: titleColor }}>Balance:</Text>
                    <Text style={{ color: colors.textPrimary, fontVariant: ["tabular-nums"] }}>
                      {" "}${bal != null ? Number(bal).toFixed(2) : "—"}
                    </Text>
                  </Text>
                </View>
              );
              return (
                <View style={{
                  paddingHorizontal: 4, paddingVertical: 6, gap: 4,
                }}>
                  <View style={{ flexDirection: "row", gap: 14 }}>
                    {col("DEMO", BLUE, demo, demoBal)}
                    {col("REAL", ORANGE, real, realBal)}
                  </View>
                  {/* v10.1.6 — Penjelasan reset harian (Q2 user): statistik
                      P:L adalah harian & direset 00:00 jam perangkat; bot
                      Full-Auto TIDAK berhenti, tetap berjalan 24/7. */}
                  <Text style={{
                    color: colors.textMuted, fontSize: 9.5, fontWeight: "600",
                    lineHeight: 13, opacity: 0.85,
                  }}>
                    ⏱ {t("pos_daily_reset_note")}
                  </Text>
                </View>
              );
            })()}
            {openList.length > 0 && openList.map(renderCard)}
            {pendList.length > 0 && (
              <>
                <Text style={[s.section, { color: YELLOW }]}>
                  PENDING LIMIT · {pendList.length}
                </Text>
                {pendList.map(renderCard)}
              </>
            )}
            {histList.length > 0 && (
              <>
                <Text style={[s.section, { color: colors.textMuted }]}>
                  HISTORY · {histList.length}
                </Text>
                {histList.map(renderCard)}
              </>
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 10, paddingVertical: 10, borderBottomWidth: 1,
  },
  backBtn: { padding: 6, borderRadius: 6 },
  section: { fontWeight: "900", fontSize: 11, letterSpacing: 0.5, marginTop: 8, marginBottom: 2 },
  card: {
    borderRadius: 10, borderWidth: 1, padding: 10, marginVertical: 2,
  },
});
