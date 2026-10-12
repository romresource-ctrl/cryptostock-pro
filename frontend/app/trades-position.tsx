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
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";
// v10.1.1 — Touchable dari RNGH untuk KARTU: bernegosiasi dengan gesture
// Swipeable sehingga swipe-delete TIDAK lagi memicu navigasi tap.
import { TouchableOpacity as CardTouchable } from "react-native-gesture-handler";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { getDeviceId } from "@/src/lib/deviceId";
import { api, type AsiTradeResp } from "@/src/lib/api";

const GOLD = "#4ADE80";
const YELLOW = "#F0B90B";
const GREEN = "#22C55E";
const RED = "#EF4444";
const BLUE = "#38BDF8";
const PURPLE = "#A78BFA";

type AnyTrade = AsiTradeResp & Record<string, any>;

export default function TradesPositionScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const [deviceId, setDeviceId] = useState<string>("");
  const [trades, setTrades] = useState<AnyTrade[]>([]);
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const pollRef = useRef<any>(null);
  const priceRef = useRef<any>(null);

  useEffect(() => {
    (async () => setDeviceId(await getDeviceId()))();
  }, []);

  const load = useCallback(async () => {
    if (!deviceId) return;
    try {
      const r = await api.asi.listTrades(deviceId, 50);
      setTrades(((r as any).items || r || []) as AnyTrade[]);
    } catch { /* keep previous */ }
    finally { setLoading(false); }
  }, [deviceId]);

  useEffect(() => {
    if (!deviceId) return;
    load();
    pollRef.current = setInterval(load, 10_000);
    return () => clearInterval(pollRef.current);
  }, [deviceId, load]);

  // Mark price polling for OPEN positions.
  const openSyms = useMemo(() =>
    Array.from(new Set(
      trades.filter((t2) => t2.status === "open" && t2.symbol).map((t2) => t2.symbol as string)
    )), [trades]);

  const openSymsKey = openSyms.join(",");
  // v10.0.10 — Flash direction per simbol (naik=hijau, turun=merah) supaya
  // harga & PnL "berkedip hidup" tiap ada perubahan tick.
  const prevPricesRef = useRef<Record<string, number>>({});
  const flashTimerRef = useRef<any>(null);
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});
  useEffect(() => {
    if (!openSyms.length) {
      if (priceRef.current) { clearInterval(priceRef.current); priceRef.current = null; }
      return;
    }
    const tick = async () => {
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
        prevPricesRef.current = m;
        setPrices(m);
        if (Object.keys(f).length > 0) {
          setFlash((cur) => ({ ...cur, ...f }));
          if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
          flashTimerRef.current = setTimeout(() => setFlash({}), 700);
        }
      } catch { /* ignore */ }
    };
    tick();
    priceRef.current = setInterval(tick, 2000);
    return () => clearInterval(priceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSymsKey]);

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
    try {
      await api.asi.deleteTrade(deviceId, tr.id || tr._id);
      await load();
    } catch { /* keep */ }
  }, [deviceId, load]);

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
          if (base) router.push(`/asset/crypto/${encodeURIComponent(base)}` as any);
        }}
        style={[s.card, { backgroundColor: colors.surface, borderColor }]}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Mode & entry badges, same vocab as Recent Trades */}
          {tr.mode ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: tr.mode === "full" ? BLUE : GOLD }}>
              <Text style={{ fontSize: 11, fontWeight: "900" }}>
                {tr.mode === "full" ? "🤖" : "🦾"}
              </Text>
            </View>
          ) : null}
          {tr.entry_mode ? (
            <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                           backgroundColor: tr.entry_mode === "market" ? PURPLE : YELLOW }}>
              <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                {tr.entry_mode === "market" ? "M" : "L"}
              </Text>
            </View>
          ) : null}
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: tr.testnet ? "#60A5FA" : "#F97316" }}>
            <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9 }}>
              {tr.testnet ? "D" : "R"}
            </Text>
          </View>
          <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 15 }}>
            {tr.symbol}/USDT
          </Text>
          <View style={{ paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                         backgroundColor: isLong ? GREEN : RED }}>
            <Text style={{ color: "#fff", fontWeight: "900", fontSize: 10 }}>
              {isLong ? "LONG" : "SHORT"} {tr.leverage ? `${tr.leverage}x` : ""}
            </Text>
          </View>
          {live != null ? (
            // v10.0.13 — Mark price PERP: besar, putih terang, berkedip
            // (background flash hijau/merah 700ms) saat tick berubah. Angka
            // menonjol seperti harga di detail aset.
            <View style={{
              paddingHorizontal: 7, paddingVertical: 2, borderRadius: 5,
              backgroundColor: flashDir === "up" ? GREEN + "33"
                : flashDir === "down" ? RED + "33" : "transparent",
            }}>
              <Text style={{
                color: "#FFFFFF", fontSize: 15, fontWeight: "900",
                fontVariant: ["tabular-nums"], letterSpacing: 0.3,
              }}>
                ${fp(live)}{flashDir ? (flashDir === "up" ? " ▲" : " ▼") : ""}
              </Text>
            </View>
          ) : null}
        </View>

        <View style={{ marginTop: 6, flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
          <View style={{ flex: 1, gap: 2 }}>
            {/* v10.0.16 — Entry price PUTIH TERANG (bukan abu) mengikuti
                gaya kartu Recent Trades. */}
            <Text style={{ color: colors.textMuted, fontSize: 11 }}>
              <Text style={{ color: "#FFFFFF", fontWeight: "900" }}>
                Entry {tr.entry_price ? fp(tr.entry_price) : "—"}
              </Text>
              {tr.filled_at ? ` · filled ${fmtDateTime(tr.filled_at)}` : (tr.created_at ? ` · ${fmtDateTime(tr.created_at)}` : "")}
            </Text>
            {/* v10.0.16 — Formula yang dipakai (persis kartu Recent Trades) */}
            {(tr.profile || tr.formula_tag) ? (
              <Text numberOfLines={1} style={{ fontSize: 10, fontWeight: "700", color: colors.textMuted }}>
                ⚙️ Formula: {String(tr.formula_tag || tr.profile)}
              </Text>
            ) : null}
            <Text style={{ fontSize: 10.5, lineHeight: 15 }}>
              <Text style={{ color: RED, fontWeight: "800" }}>
                SL {tr.stop_loss ? fp(tr.stop_loss) : "—"}
              </Text>
              {"  ·  "}
              <Text style={{ color: GREEN, fontWeight: "800" }}>
                TP {(tr.take_profits || []).map((x: number) => fp(x)).join(" / ") || "—"}
              </Text>
            </Text>
            {tr.margin_usdt != null ? (
              <Text style={{ color: YELLOW, fontSize: 10.5, fontWeight: "700" }}>
                Margin ${Number(tr.margin_usdt).toFixed(2)}
              </Text>
            ) : null}
            {/* v10.0.13 — Riwayat TP hit: tampilkan tiap level yang sudah
                terisi dengan harga closed-nya (putih terang). TP3 selalu
                menutup posisi penuh dan sudah masuk PnL total di atas.
                v10.1.1 — HANYA baris TP yang ditampilkan; catatan parsial
                berlabel SL (fill adverse/slippage) disembunyikan agar
                posisi OPEN tidak tampak seolah kena SL. */}
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
            {!isOpen && !isPending ? (
              <Text style={{ color: colors.textMuted, fontSize: 10.5 }}>
                {closedReason(tr.close_reason)}
                {tr.closed_price ? ` @ ${fp(tr.closed_price)}` : ""}
                {tr.closed_at ? ` · ${fmtDateTime(tr.closed_at)}` : ""}
              </Text>
            ) : null}
          </View>

          <View style={{ alignItems: "flex-end", gap: 6, minWidth: 92 }}>
            {isPending ? (
              <View style={{ paddingHorizontal: 7, paddingVertical: 3, borderRadius: 6, backgroundColor: YELLOW }}>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 10 }}>LIMIT WAITING</Text>
              </View>
            ) : (
              <View style={{ alignItems: "flex-end" }}>
                {/* v10.0.13 — PnL juga mendapat background flash saat tick
                    berubah supaya 'hidup' seperti chart. */}
                <View style={{
                  paddingHorizontal: 7, paddingVertical: 2, borderRadius: 5,
                  backgroundColor: flashDir === "up" ? GREEN + "33"
                    : flashDir === "down" ? RED + "33" : "transparent",
                }}>
                  <Text style={{ color: pnl >= 0 ? GREEN : RED, fontWeight: "900", fontSize: 19, fontVariant: ["tabular-nums"] }}>
                    {pnl >= 0 ? "+" : "-"}${Math.abs(pnl).toFixed(2)}
                  </Text>
                </View>
                {/* v10.0.10 — % PnL realtime terhadap margin + indikator LIVE
                    yang berkedip mengikuti arah tick harga. */}
                {isOpen && tr.margin_usdt ? (
                  <Text style={{ color: pnl >= 0 ? GREEN : RED, fontWeight: "700", fontSize: 10 }}>
                    {pnl >= 0 ? "+" : ""}{(pnl / Number(tr.margin_usdt) * 100).toFixed(2)}%
                    {flashDir ? (flashDir === "up" ? " ▲" : " ▼") : ""}
                  </Text>
                ) : null}
                {isOpen ? (
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 3, marginTop: 1 }}>
                    <View style={{
                      width: 6, height: 6, borderRadius: 3,
                      backgroundColor: flashDir ? (flashDir === "up" ? GREEN : RED) : colors.textMuted,
                    }} />
                    <Text style={{ color: colors.textMuted, fontSize: 8.5, fontWeight: "800", letterSpacing: 0.5 }}>LIVE</Text>
                  </View>
                ) : null}
              </View>
            )}
            {(isOpen || isPending) ? (
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
            ) : null}
          </View>
        </View>
      </CardTouchable>
    );

    if (!canDelete) return <View key={tr.id || tr._id}>{inner}</View>;
    return (
      <ReanimatedSwipeable
        key={tr.id || tr._id}
        renderRightActions={() => (
          <TouchableOpacity
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
        <TouchableOpacity onPress={() => router.back()} style={s.backBtn}>
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
            {/* v10.1.3 — Statistik harian menggantikan baris "OPEN
                POSITIONS · n" (sudah ter-cover total di header). Format:
                W : L (jumlah) · P : L ($% kumulatif) reset tiap 00:00. */}
            {(() => {
              // v10.1.1 — Reset harian pukul 00:00 mengikuti JAM DEVICE
              // user (bukan UTC): kunci tanggal dihitung dari Date lokal
              // perangkat, begitu pula saat mengelompokkan trade closed.
              const pad2 = (n: number) => String(n).padStart(2, "0");
              const dayKey = (d: Date) =>
                `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
              const today = dayKey(new Date());
              let wins = 0, losses = 0, pUsd = 0, lUsd = 0, pPct = 0, lPct = 0;
              histList.forEach((t2: any) => {
                const iso = t2.closed_at || t2.updated_at;
                if (!iso) return;
                const d = new Date(iso);
                if (isNaN(d.getTime()) || dayKey(d) !== today) return;
                const pnl2 = Number(t2.pnl_usdt || 0);
                const marg = Math.max(1, Number(t2.margin_usdt || 1));
                if (pnl2 > 0) { wins++; pUsd += pnl2; pPct += (pnl2 / marg) * 100; }
                else if (pnl2 < 0) { losses++; lUsd += pnl2; lPct += (pnl2 / marg) * 100; }
              });
              return (
                <View style={{ paddingHorizontal: 2, paddingVertical: 4, gap: 2 }}>
                  <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "800" }}>
                    W : L <Text style={{ color: GREEN }}>{wins}</Text>
                    <Text style={{ color: colors.textMuted }}> : </Text>
                    <Text style={{ color: RED }}>{losses}</Text>
                  </Text>
                  <Text style={{ fontSize: 11, fontWeight: "800" }}>
                    <Text style={{ color: colors.textMuted }}>P : L </Text>
                    <Text style={{ color: GREEN }}>+${pUsd.toFixed(2)} (+{pPct.toFixed(1)}%)</Text>
                    <Text style={{ color: colors.textMuted }}> : </Text>
                    <Text style={{ color: RED }}>-${Math.abs(lUsd).toFixed(2)} ({lPct.toFixed(1)}%)</Text>
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
