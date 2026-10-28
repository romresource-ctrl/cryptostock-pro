import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, Platform, RefreshControl, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { useTraderProfile } from "@/src/lib/useTraderProfile";
import { usePremiumAccess } from "@/src/lib/usePremiumAccess";
import PremiumLocked from "@/src/components/PremiumLocked";
import { api, type AsiLiveRow } from "@/src/lib/api";
import { getDeviceId } from "@/src/lib/deviceId";
import { readPageCache, writePageCache } from "@/src/lib/pageCache";
import { formulaTagFromSignal } from "@/src/components/AsiTradeSheet";
import { quickExecute, reverseLevels } from "@/src/lib/quickExecute";

const GOLD = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";
const BLUE = "#3B82F6";
const LIGHT_BLUE = "#38BDF8";
const PURPLE = "#A78BFA";

const LIVE_REFRESH_MS = 15_000;

export default function CopyTradeScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t, lang } = useI18n();
  const insets = useSafeAreaInsets();
  const [leader, setLeader] = useState<AsiLiveRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { hasAccess, loaded: accessLoaded } = usePremiumAccess();
  const { apiProfile } = useTraderProfile();
  // v10.2.18 — Keputusan user: EXECUTE langsung eksekusi tanpa popup
  // sheet parameter. Pakai setting user di halaman ASI-Bot (risk%,
  // leverage, margin mode, jumlah TP, trailing callback, entry mode),
  // lalu navigasi ke Running Positions.
  const [preparingRank, setPreparingRank] = useState<string | null>(null);

  const onExecuteCopy = useCallback(async (row: AsiLiveRow, reverse: boolean = false) => {
    if (!row.symbol || !row.side) return;
    const base = String(row.symbol).replace("/USDT", "").replace("USDT", "");
    const busyKey = `${row.rank}${reverse ? "r" : ""}`;
    setPreparingRank(busyKey);
    try {
      const did = await getDeviceId();
      // Ambil parameter yang sudah di-set user di halaman ASI-Bot.
      let bot: any = null;
      try { bot = await api.asi.getBot(did); } catch { /* fallback default */ }
      if (!bot?.exists) {
        Alert.alert(
          t("asi_copy_need_setup_title") || "Setup ASI-Bot dulu",
          t("asi_copy_need_setup_body")
            || "Hubungkan exchange dan atur parameter bot (Risk %, Leverage, TP, dst.) di halaman ASI-Bot sebelum menyalin posisi.",
          [
            { text: t("common_cancel") || "Batal", style: "cancel" },
            { text: "ASI-Bot", onPress: () => router.push("/asi-bot" as never) },
          ],
        );
        return;
      }
      // Entry = mark price saat ini (bukan entry trader historis).
      let entry = Number(row.entry_price || 0);
      try {
        const p = await api.asi.price(base);
        if (p.price > 0) entry = p.price;
      } catch { /* keep fallback */ }
      // Guard parameter minimal yang wajib ada untuk bracket.
      if (!entry || !row.stop_loss || !(row.take_profits || []).length) {
        Alert.alert(
          t("asi_copy_bad_signal_title") || "Sinyal tidak lengkap",
          t("asi_copy_bad_signal_body")
            || "Posisi ini tidak punya SL/TP yang bisa disalin. Pilih rank lain atau coba lagi nanti.",
        );
        return;
      }
      const exchange = (bot.exchange || "binance") as
        "binance" | "bybit" | "okx" | "bitget";
      // Cek duplikat posisi terbuka pada symbol+exchange yang sama.
      try {
        const list = await api.asi.listTrades(did);
        const dup = (list.items || []).find(
          (tr: any) => String(tr.status || "").toLowerCase() === "open"
            && String(tr.symbol || "").toUpperCase() === base.toUpperCase()
            && (tr.exchange || "") === exchange,
        );
        if (dup) {
          const dupBody = (t("ats_dup_body") || "Anda sudah punya posisi {side} {symbol} aktif di {exchange} (PnL ${pnl}). Tambah posisi lagi (pyramid)?")
            .replace("{side}", String((dup as any).side))
            .replace("{symbol}", base)
            .replace("{exchange}", exchange.toUpperCase())
            .replace("{pnl}", ((dup as any).pnl_usdt ?? 0).toFixed(2));
          const proceed = Platform.OS === "web"
            // eslint-disable-next-line no-alert
            ? window.confirm(`${t("ats_dup_title") || "Posisi Sudah Terbuka"}\n\n${dupBody}`)
            : await new Promise<boolean>((resolve) => {
                Alert.alert(t("ats_dup_title") || "Posisi Sudah Terbuka", dupBody, [
                  { text: t("ats_dup_cancel") || "Batal", style: "cancel", onPress: () => resolve(false) },
                  { text: t("ats_dup_add") || "Ya, tambah", onPress: () => resolve(true) },
                ]);
              });
          if (!proceed) return;
        }
      } catch { /* best effort dup check */ }
      try {
        const origSide: "BUY" | "SELL" = row.side === "BUY" ? "BUY" : "SELL";
        const tps0 = (row.take_profits || []).map((v) => Number(v));
        // v10.6.1 — REVERSE: arah dibalik, jarak SL/TP % dicerminkan dari
        // harga sekarang (Long the Dip / Short the Top).
        const lv = reverse
          ? reverseLevels(origSide, Number(row.entry_price || entry), Number(row.stop_loss), tps0, entry)
          : { side: origSide, stop_loss: Number(row.stop_loss), take_profits: tps0 };
        const baseTag = formulaTagFromSignal(null, null, apiProfile);
        await quickExecute({
          symbol: base, side: lv.side, entry,
          stop_loss: lv.stop_loss, take_profits: lv.take_profits,
          profile: apiProfile ?? null,
          formula_tag: reverse ? `${baseTag || "Leaderboard"} · REVERSE` : baseTag,
        });
        // Sukses → langsung buka Running Positions.
        router.push("/trades-position" as never);
      } catch (e: any) {
        const code: string | undefined = e?.code;
        const msg: string = e?.detail?.message || e?.message || String(e);
        const title = t("asi_copy_exec_failed") || "Gagal mengeksekusi";
        const body = code === "qty_zero"
          ? (t("ats_err_qty_zero") || "Qty 0 — Risk/Leverage/Balance tidak cukup.")
          : code === "min_notional"
            ? (t("ats_err_min_notional") || "Ukuran posisi di bawah minimum notional exchange.").replace("{size}", String((e?.detail?.size_usdt ?? 0).toFixed?.(2) ?? "0.00")).replace("{min}", String((e?.detail?.min_notional ?? 5).toFixed?.(2) ?? "5.00"))
            : (msg || "Unknown error");
        if (Platform.OS === "web") {
          // eslint-disable-next-line no-alert
          window.alert(`${title}\n\n${body}`);
        } else {
          Alert.alert(title, body);
        }
      }
    } finally {
      setPreparingRank(null);
    }
  }, [apiProfile, router, t]);

  const load = useCallback(async () => {
    try {
      const l = await api.asi.leaderboardLive();
      setLeader(l.items || []);
      // v10.2.9 — Simpan ke page cache supaya kunjungan berikutnya
      // leaderboard langsung tergambar TANPA spinner.
      writePageCache("leaderboard:live", l.items || []);
    } catch {
      /* keep previous rows */
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  // v10.2.9 — INSTANT OPEN: render baris leaderboard terakhir dari cache
  // seketika saat halaman dibuka (keluhan user: "buka leaderboard sangat
  // lama"), lalu fetch segar jalan di background.
  useEffect(() => {
    let alive = true;
    (async () => {
      const cached = await readPageCache<AsiLiveRow[]>("leaderboard:live");
      if (alive && cached && cached.length > 0) {
        setLeader(cached);
        setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, LIVE_REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    load();
  }, [load]);

  // v10.0.13 — Mark price Binance Futures Perpetual realtime untuk tiap
  // posisi OPEN di leaderboard. Polling 2s + flash hijau/merah per tick,
  // sejajar dengan Positions screen dan Recent Trades (ASI-Bot).
  const [livePx, setLivePx] = useState<Record<string, number>>({});
  const [flashDir, setFlashDir] = useState<Record<string, "up" | "down">>({});
  const prevPxRef = useRef<Record<string, number>>({});
  const flashTimerRef = useRef<any>(null);
  const openSymsKey = useMemo(() => {
    const set = new Set<string>();
    leader.forEach((row) => {
      if (row.status === "open" && row.symbol) {
        set.add(String(row.symbol).replace(/USDT$/, ""));
      }
    });
    return Array.from(set).join(",");
  }, [leader]);
  useEffect(() => {
    if (!openSymsKey) { setLivePx({}); return; }
    const syms = openSymsKey.split(",");
    let alive = true;
    const tick = async () => {
      try {
        const r = await api.asi.prices(syms);
        if (!alive) return;
        const m: Record<string, number> = {};
        Object.entries(r.prices || {}).forEach(([k, v]) => {
          m[k.replace(/USDT$/, "")] = v as number;
        });
        const f: Record<string, "up" | "down"> = {};
        Object.entries(m).forEach(([k, v]) => {
          const prev = prevPxRef.current[k];
          if (prev != null && v !== prev) f[k] = v > prev ? "up" : "down";
        });
        prevPxRef.current = m;
        setLivePx(m);
        if (Object.keys(f).length > 0) {
          setFlashDir((cur) => ({ ...cur, ...f }));
          if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
          flashTimerRef.current = setTimeout(() => setFlashDir({}), 700);
        }
      } catch { /* keep previous */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [openSymsKey]);

  // v10.0.13 — Format harga adaptif (sama polanya dengan Positions/Recent).
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

  // v10.0.5 — Format tanggal/jam & teks penyebab close, sama seperti
  // kartu Recent Trades ("Closed on SL/TP1", "Canceled upon expiry", dst).
  const fmtDateTime = (iso?: string | null): string => {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const closedReasonText = (rc?: string | null): string => {
    const r = String(rc || "");
    if (/^TP\d?$/.test(r)) return `Closed on ${r}`;
    if (r === "SL") return "Closed on SL";
    if (r === "cancelled_pending") return "Canceled upon user cancel";
    if (r === "entry_expired") return "Canceled upon expiry (2 candles)";
    if (r === "manual_cleanup") return "Closed on cleanup";
    if (r === "merged_into_layer") return "Merged into layer";
    if (r === "bracket_failed_after_fill") return "Closed upon bracket failure";
    if (r === "MANUAL" || r === "manual") return "Closed Manually";
    if (r === "manual_close_all") return "Closed by Close All";
    if (r === "position_closed_externally") return "Closed on exchange";
    if (r === "TRAILING") return "Closed on Trailing Stop";
    if (r === "BREAK_EVEN") return "Closed on Break-Even";
    if (r === "AC") return "Closed on Auto-Close";
    return r ? `Closed on ${r}` : "Closed";
  };

  // Localized relative time: "5m ago" / "5m lalu" / "5м назад" / "5分前"
  const timeAgo = (iso?: string | null): string => {
    if (!iso) return "";
    const tt = Date.parse(iso);
    if (!Number.isFinite(tt)) return "";
    const d = Math.max(0, Math.floor((Date.now() - tt) / 1000));
    const gap = lang === "cn" ? "" : " ";
    if (d < 60) return `${d}${t("news_time_second_short")}${gap}${t("news_time_ago")}`;
    if (d < 3600) return `${Math.floor(d / 60)}${t("news_time_minute_short")}${gap}${t("news_time_ago")}`;
    if (d < 86400) return `${Math.floor(d / 3600)}${t("news_time_hour_short")}${gap}${t("news_time_ago")}`;
    return `${Math.floor(d / 86400)}${t("news_time_day_short")}${gap}${t("news_time_ago")}`;
  };

  // v9.6.4 — Premium gate: halaman ini khusus member premium.
  if (accessLoaded && !hasAccess) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
        <View style={s.header}>
          <TouchableOpacity onPress={() => router.back()} testID="copy-back" hitSlop={10}>
            <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={[s.title, { color: colors.textPrimary }]}>🏆 Copy Trade · LIVE</Text>
            <Text style={[s.sub, { color: colors.textMuted }]}>
              {t("copy_sub")}
            </Text>
          </View>
        </View>
        <PremiumLocked bodyKey="premium_locked_copy_body" />
      </View>
    );
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="copy-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={[s.title, { color: colors.textPrimary }]}>🏆 Copy Trade · LIVE</Text>
          <Text style={[s.sub, { color: colors.textMuted }]}>
            {t("copy_sub")}
          </Text>
        </View>
        <View style={s.livePill}>
          <View style={s.liveDot} />
          <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 10 }}>LIVE</Text>
        </View>
      </View>

      <ScrollView
        contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 10 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={GOLD} />}
      >
        {loading ? (
          <View style={{ paddingVertical: 40, alignItems: "center" }}>
            <ActivityIndicator color={GOLD} />
            <Text style={{ color: colors.textMuted, marginTop: 10, fontSize: 12 }}>{t("copy_loading")}</Text>
          </View>
        ) : leader.length === 0 ? (
          <View style={[s.empty, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Ionicons name="pulse-outline" size={28} color={colors.textMuted} />
            <Text style={{ color: colors.textPrimary, fontWeight: "800", marginTop: 8 }}>
              {t("copy_empty_title")}
            </Text>
            <Text style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", marginTop: 6, lineHeight: 18 }}>
              {t("copy_empty_body")}
            </Text>
          </View>
        ) : (
          leader.map((row) => {
            // v10.0.5 — SATU kartu = SATU posisi (rank per posisi, PnL tidak
            // digabung per trader). PnL ditaruh paling kanan di atas tombol
            // EXECUTE (EXECUTE hanya untuk posisi open).
            const isOpen = row.status === "open";
            const isLong = row.side === "BUY";
            const busyKey = String(row.rank);
            // v10.0.13 — PnL realtime dari mark price Futures Perp.
            const symBase = row.symbol ? String(row.symbol).replace(/USDT$/, "") : "";
            const lp = symBase ? livePx[symBase] : undefined;
            let pnl = Number(row.pnl_usdt ?? 0);
            if (isOpen && lp != null && row.entry_price && (row as any).qty) {
              pnl = (isLong ? 1 : -1) * (lp - Number(row.entry_price)) * Number((row as any).qty);
            }
            const fd = symBase ? flashDir[symBase] : undefined;
            return (
              <View
                key={`${row.rank}-${row.symbol}-${row.status}`}
                style={[s.card, { backgroundColor: colors.surface, borderColor: row.rank <= 3 ? GOLD : colors.border }]}
              >
                <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
                  <Text style={[s.rank, { color: row.rank <= 3 ? GOLD : colors.textMuted }]}>#{row.rank}</Text>
                  <View style={{ flex: 1 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <Text style={[s.handle, { color: colors.textPrimary }]}>{row.handle}***</Text>
                      <View style={{
                        paddingHorizontal: 5, paddingVertical: 1.5, borderRadius: 4,
                        backgroundColor: row.testnet ? BLUE : GREEN,
                      }}>
                        <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 8.5, letterSpacing: 0.4 }}>
                          {row.testnet ? "D" : "R"}
                        </Text>
                      </View>
                      {!isOpen ? (
                        <View style={{
                          paddingHorizontal: 5, paddingVertical: 1.5, borderRadius: 4,
                          backgroundColor: colors.border,
                        }}>
                          <Text style={{ color: colors.textMuted, fontWeight: "900", fontSize: 8.5 }}>CLOSED</Text>
                        </View>
                      ) : null}
                      {/* v10.0.5 — Tanggal/jam entry seperti Recent Trades */}
                      <Text style={{ fontSize: 9, fontWeight: "700", color: colors.textMuted }}>
                        {fmtDateTime(row.created_at)}
                      </Text>
                      {/* v10.0.5 — Penyebab close (PUTIH) di sebelah tanggal */}
                      {!isOpen ? (
                        <Text numberOfLines={1} style={{ fontSize: 9, fontWeight: "800", color: colors.textPrimary, flexShrink: 1 }}>
                          {closedReasonText(row.close_reason)}
                        </Text>
                      ) : null}
                    </View>
                    <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: 2 }}>
                      {t("copy_wr_line").replace("{wr}", String(row.wr30d ?? 0)).replace("{n}", String(row.trades30d ?? 0))}
                    </Text>
                  </View>
                </View>

                <View
                  style={[s.tradeRow, { borderColor: colors.border, backgroundColor: colors.background, opacity: isOpen ? 1 : 0.8 }]}
                  testID={`copy-pos-${row.rank}`}
                >
                  <View style={{ flex: 1, gap: 2 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      {/* v10.0.5 — Badge mode bot seperti Recent Trades:
                          Semi=🦾 (emas), Full=🤖 (biru muda) */}
                      {row.mode ? (
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                          backgroundColor: row.mode === "full" ? LIGHT_BLUE : GOLD,
                        }}>
                          <Text style={{ fontSize: 11, fontWeight: "900" }}>
                            {row.mode === "full" ? "🤖" : "🦾"}
                          </Text>
                        </View>
                      ) : null}
                      {/* v10.0.5 — Chip cara masuk: L (kuning) / M (ungu) */}
                      {row.entry_mode ? (
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                          backgroundColor: row.entry_mode === "market" ? PURPLE : GOLD,
                        }}>
                          <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                            {row.entry_mode === "market" ? "M" : "L"}
                          </Text>
                        </View>
                      ) : null}
                      <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
                        {row.symbol}/USDT
                      </Text>
                      <View style={{
                        paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                        backgroundColor: isLong ? GREEN : RED,
                      }}>
                        <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
                          {isLong ? "LONG" : "SHORT"} {row.leverage ? `${row.leverage}x` : ""}
                        </Text>
                      </View>
                      {/* v10.0.13 — Mark price PERP realtime (poll 2s), BESAR
                          & PUTIH + flash hijau/merah seperti candlestick */}
                      {isOpen && lp != null ? (
                        <View style={{
                          paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4,
                          backgroundColor: fd === "up" ? GREEN + "33" : fd === "down" ? RED + "33" : "transparent",
                        }}>
                          <Text style={{
                            color: "#FFFFFF", fontWeight: "900", fontSize: 13,
                            fontVariant: ["tabular-nums"], letterSpacing: 0.3,
                          }}>
                            ${fp(lp)}{fd ? (fd === "up" ? " ▲" : " ▼") : ""}
                          </Text>
                        </View>
                      ) : null}
                    </View>
                    <Text style={{ color: colors.textMuted, fontSize: 11 }}>
                      {t("copy_entry_line")
                        .replace("{price}", fp(row.entry_price || 0))
                        .replace("{ago}", timeAgo(row.created_at))}
                    </Text>
                    <Text style={{ color: colors.textMuted, fontSize: 10.5, lineHeight: 15 }} numberOfLines={2}>
                      <Text style={{ color: RED, fontWeight: "800" }}>
                        SL {row.stop_loss ? fp(row.stop_loss) : "—"}
                      </Text>
                      {"  ·  "}
                      <Text style={{ color: GREEN, fontWeight: "800" }}>
                        TP {(row.take_profits || []).map((x) => fp(x)).join(" / ") || "—"}
                      </Text>
                    </Text>
                    {/* v10.6.1 — Badge parameter lengkap seperti Recent Trades */}
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 3 }}>
                      {row.margin_mode ? (
                        <View style={[s.pBadge, { backgroundColor: "#14B8A6" }]}>
                          <Text style={s.pBadgeTxt}>{String(row.margin_mode).toUpperCase()}</Text>
                        </View>
                      ) : null}
                      {Number(row.auto_close_pct) > 0 ? (
                        <View style={[s.pBadge, { backgroundColor: GOLD }]}>
                          <Text style={s.pBadgeTxt}>AC {row.auto_close_pct}%</Text>
                        </View>
                      ) : row.tp_count ? (
                        <View style={[s.pBadge, { backgroundColor: GOLD }]}>
                          <Text style={s.pBadgeTxt}>{row.tp_count} TP</Text>
                        </View>
                      ) : null}
                      {Number(row.margin_usdt) > 0 ? (
                        <View style={[s.pBadge, { backgroundColor: "#FB923C" }]}>
                          <Text style={s.pBadgeTxt}>Margin ${Number(row.margin_usdt).toFixed(2)}</Text>
                        </View>
                      ) : null}
                      {row.formula_tag ? (
                        <View style={[s.pBadge, { backgroundColor: colors.border }]}>
                          <Text style={[s.pBadgeTxt, { color: colors.textPrimary }]} numberOfLines={1}>
                            ⚙️ {row.formula_tag}
                          </Text>
                        </View>
                      ) : null}
                    </View>
                    {!isOpen ? (
                      <Text style={{ color: colors.textMuted, fontSize: 10.5 }}>
                        Closed @ {row.closed_price ? fp(row.closed_price) : "—"}
                        {row.closed_at ? ` · ${fmtDateTime(row.closed_at)}` : ""}
                      </Text>
                    ) : null}
                    {/* v10.0.13 — TP partial hits: menunjukkan harga close
                        parsial TP1/TP2. TP3 akan memfinalkan posisi dan
                        tidak muncul di sini (sudah tutup penuh). */}
                    {Array.isArray((row as any).tp_fills) && (row as any).tp_fills.length > 0 ? (
                      <View style={{ marginTop: 2, gap: 1 }}>
                        {(row as any).tp_fills.map((f: any, i: number) => (
                          <Text key={i} style={{ fontSize: 10.5, fontWeight: "800", color: "#FFFFFF" }}>
                            ✓ {String(f.level)} HIT · ${f.price != null ? fp(Number(f.price)) : "—"}
                            {f.pnl != null ? (
                              <Text style={{ color: Number(f.pnl) >= 0 ? GREEN : RED, fontWeight: "900" }}>
                                {"  "}{Number(f.pnl) >= 0 ? "+" : "-"}${Math.abs(Number(f.pnl)).toFixed(2)}
                              </Text>
                            ) : null}
                          </Text>
                        ))}
                      </View>
                    ) : null}
                  </View>
                  {/* v10.0.5 — PnL paling kanan, di atas tombol EXECUTE */}
                  <View style={{ alignItems: "flex-end", gap: 6 }}>
                    {/* v10.6.1 — REVERSE: eksekusi arah KEBALIKAN posisi
                        trader (Long the Dip / Short the Top), 1 tap. */}
                    {isOpen ? (
                      <TouchableOpacity
                        style={[s.copyBtn, { backgroundColor: isLong ? RED : GREEN }]}
                        onPress={() => onExecuteCopy(row, true)}
                        disabled={preparingRank === `${busyKey}r`}
                        testID={`copy-reverse-${row.rank}`}
                      >
                        {preparingRank === `${busyKey}r`
                          ? <ActivityIndicator size="small" color="#FFFFFF" />
                          : <Text style={{ color: "#FFFFFF", fontWeight: "900", fontSize: 11 }}>
                              REVERSE: {isLong ? "SHORT" : "LONG"}
                            </Text>}
                      </TouchableOpacity>
                    ) : null}
                    <View style={{ alignItems: "flex-end" }}>
                      {/* v10.0.13 — PnL juga dapat flash background sesuai arah tick */}
                      <View style={{
                        paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4,
                        backgroundColor: isOpen && fd === "up" ? GREEN + "33"
                          : isOpen && fd === "down" ? RED + "33" : "transparent",
                      }}>
                        <Text style={{ color: pnl >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 17, fontVariant: ["tabular-nums"] }}>
                          {pnl >= 0 ? "+" : "-"}${Math.abs(pnl).toFixed(2)}
                        </Text>
                      </View>
                      {(() => {
                        const pct = isOpen && row.entry_price && (row as any).margin_usdt
                          ? (pnl / Number((row as any).margin_usdt)) * 100
                          : row.pnl_pct;
                        return pct != null ? (
                          <Text style={{ color: pnl >= 0 ? GREEN : RED, fontWeight: "700", fontSize: 10 }}>
                            {pct >= 0 ? "+" : ""}{Number(pct).toFixed(2)}%
                            {isOpen && fd ? (fd === "up" ? " ▲" : " ▼") : ""}
                          </Text>
                        ) : null;
                      })()}
                    </View>
                    {/* v10.0.5 — EXECUTE SELALU tampil di bawah angka PnL,
                        tapi READ-ONLY (abu, nonaktif) untuk posisi closed;
                        hanya posisi OPEN yang bisa dieksekusi. */}
                    <TouchableOpacity
                      style={[s.copyBtn, { backgroundColor: isOpen ? GOLD : colors.border, opacity: isOpen ? 1 : 0.6 }]}
                      onPress={() => onExecuteCopy(row)}
                      disabled={!isOpen || preparingRank === busyKey}
                      testID={`copy-execute-${row.rank}`}
                    >
                      {preparingRank === busyKey
                        ? <ActivityIndicator size="small" color="#0B0E11" />
                        : <Text style={{ color: isOpen ? "#0B0E11" : colors.textMuted, fontWeight: "900", fontSize: 11 }}>{t("copy_execute")}</Text>}
                    </TouchableOpacity>
                  </View>
                </View>
              </View>
            );
          })
        )}

        {leader.length > 0 && (
          <Text style={{ color: colors.textMuted, fontSize: 11, textAlign: "center", marginTop: 20, lineHeight: 17 }}>
            {t("copy_footer")}
          </Text>
        )}
      </ScrollView>

      {/* v10.2.18 — Trade sheet copy dihapus. EXECUTE kini langsung
          mengeksekusi dengan parameter dari halaman ASI-Bot. */}
    </View>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.3 },
  sub: { fontSize: 11, marginTop: 2 },
  livePill: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: GOLD, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999,
  },
  liveDot: { width: 7, height: 7, borderRadius: 999, backgroundColor: "#0B0E11" },
  card: { padding: 14, borderRadius: 14, borderWidth: 1.5, gap: 10 },
  rank: { fontSize: 22, fontWeight: "900", width: 42 },
  handle: { fontWeight: "900", fontSize: 15, letterSpacing: 1.5 },
  tradeRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 10, borderRadius: 10, borderWidth: 1,
  },
  copyBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8 },
  pBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4, maxWidth: 220 },
  pBadgeTxt: { color: "#0B0E11", fontWeight: "900", fontSize: 9.5 },
  empty: {
    padding: 32, borderRadius: 14, borderWidth: 1,
    alignItems: "center", gap: 2,
  },
});
