/**
 * v9.3.0 — ASI-Bot Trade Sheet.
 *
 * Bottom sheet yang menerima sinyal (dari AI Suggestions atau Asset
 * Detail) dan menampilkan preview trade dengan parameter editable.
 * Satu tap "EXECUTE TRADE" mengirim bracket order ke exchange user.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Alert, Modal, Platform, Pressable, ScrollView, StyleSheet, Text,
  TouchableOpacity, View,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { useTraderProfile } from "@/src/lib/useTraderProfile";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, formatPrice, type AsiCredential, type AsiPreview,
} from "@/src/lib/api";

const GOLD = "#F0B90B";
const MINT = "#4ADE80"; // v9.4.3 — ASI-Bot accent (hijau muda + teks putih)
const BLUE = "#3B82F6"; // v9.9.9 — chip DEMO (testnet)
const GREEN = "#22C55E";
const RED = "#EF4444";
const PURPLE = "#C084FC"; // v10.0.1 — tombol Market Price (ungu muda)
const LIGHT_BLUE_BTN = "#38BDF8"; // v9.8.5 — tombol "Lihat Recent Trades"

export type AsiTradeIntent = {
  symbol: string;              // e.g. "BTC", "ETH"
  side: "BUY" | "SELL";
  entry: number;
  stop_loss: number;
  take_profits: number[];      // [tp1, tp2, tp3]
  source?: "ai-suggestions" | "asset-detail" | "asi-bot-semi";
  // v9.9.13 — Tag singkat modul formula pemicu (label kartu history)
  formula_tag?: string | null;
};

// v9.9.13 — Tag singkat formula yang benar-benar memicu sinyal.
// Prioritas pola spesifik; fallback ke formula dasar profil.
export function formulaTagFromSignal(
  ind?: any, reasons?: string[] | null, profile?: string | null,
): string | null {
  const i = ind || {};
  if (i.vwap_engine === "SCALP-15M") return "Open-Scalp Modules";
  const tags: string[] = [];
  if (i.power_of_tower) tags.push("Power of Tower Pattern");
  if (i.john_wick) tags.push("John Wick Candle Stick");
  const r = (reasons || []).join(" ").toLowerCase();
  if (r.includes("kiss")) tags.push("KISS Pivot");
  if (i.box_break_long || i.box_break_short) tags.push("Box Theory");
  if (tags.length) return tags.slice(0, 2).join(" · ");
  if (profile === "scalper") return "7 Fast VWAP";
  if (profile === "day") return "5 KISS VWAP";
  if (profile === "swing") return "5 Multi-day Trend";
  return null;
}

type Props = {
  visible: boolean;
  onClose: () => void;
  intent: AsiTradeIntent | null;
  // v9.8.7 — Dipakai saat sheet dibuka dari dalam AISuggestionsSheet:
  // menutup trade sheet DAN popup suggestions sekaligus (mis. tombol
  // "View Recent Trades" setelah eksekusi sukses).
  onCloseAll?: () => void;
};

export default function AsiTradeSheet({ visible, onClose, onCloseAll, intent }: Props) {
  const router = useRouter();
  const { colors } = useTheme();
  const { t, tEN } = useI18n();
  const { apiProfile } = useTraderProfile();
  const insets = useSafeAreaInsets();

  // v9.8.7 — Tutup SEMUA layer (trade sheet + suggestions popup) lalu
  // kembali ke ASI-Bot. router.replace (bukan push) supaya tidak menumpuk
  // route yang sama ketika user memang sudah di /asi-bot.
  const goToRecentTrades = () => {
    if (onCloseAll) onCloseAll(); else onClose();
    router.replace("/asi-bot" as never);
  };

  const [deviceId, setDeviceId] = useState("");
  const [creds, setCreds] = useState<AsiCredential[]>([]);
  const [exchange, setExchange] = useState<"binance" | "bybit" | "okx" | "bitget">("binance");
  const [riskPct, setRiskPct] = useState(5);
  const [leverage, setLeverage] = useState(10);
  const [tpCount, setTpCount] = useState<1 | 2 | 3>(3);
  const [trailingCbRate, setTrailingCbRate] = useState<number>(2);
  const [preview, setPreview] = useState<AsiPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [executing, setExecuting] = useState(false);
  // v9.9.6 — flag credential selesai dimuat; mencegah flash empty-state
  // "hubungkan exchange" sesaat saat sheet dibuka (tombol hilang-muncul).
  const [credsLoaded, setCredsLoaded] = useState(false);
  // v9.9.0 — Margin mode wajib dipilih sebelum eksekusi (default ISOLATED).
  const [marginMode, setMarginMode] = useState<"isolated" | "cross">("isolated");
  // v10.0.1 — Tipe eksekusi: LIMIT (moderate, default) vs MARKET (instan).
  const [entryMode, setEntryMode] = useState<"limit" | "market">("limit");
  // v9.9.5 — Network aktif dari bot config (testnet = demo).
  const [activeTestnet, setActiveTestnet] = useState(true);
  // v9.9.9 — simpan bot config utk persist active_testnet saat user
  // ganti jaringan langsung dari chip di sheet ini.
  const [botCfg, setBotCfg] = useState<any>(null);
  // v9.8.5 — Hasil eksekusi ditampilkan sebagai panel di DALAM sheet
  // (Alert.alert bawaan tidak tampil di web preview). null = belum eksekusi.
  const [execResult, setExecResult] = useState<{ ok: boolean; title: string; body: string } | null>(null);

  // Reset panel hasil tiap kali intent baru dibuka.
  useEffect(() => { setExecResult(null); setCredsLoaded(false); }, [intent, visible]);

  // v10.2.18 — Preview "Calculating…" dulu bisa stuck selamanya bila
  // request >5s / jaringan putus. Keputusan user: setelah 5 detik,
  // tampilkan pesan error + tombol Retry (jangan diam saja).
  const [previewTimeout, setPreviewTimeout] = useState(false);
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const retryPreview = () => {
    setPreviewTimeout(false);
    setPreview(null);
    setPreviewAttempt((n) => n + 1);
  };

  useEffect(() => {
    if (!visible || !intent) return;
    (async () => {
      const did = await getDeviceId();
      setDeviceId(did);
      let net = true;
      try {
        // v9.9.0 — Default margin mode dari bot config (diset di halaman
        // ASI-Bot). User tetap bisa ubah per-trade di selector bawah.
        const b = await api.asi.getBot(did);
        if (b.exists && (b as any).margin_mode) {
          setMarginMode((b as any).margin_mode as "isolated" | "cross");
        }
        // v10.0.1 — Default tipe eksekusi dari bot config.
        if (b.exists && (b as any).entry_mode) {
          setEntryMode((b as any).entry_mode as "limit" | "market");
        }
        // v9.9.5 — Network aktif dari bot config (switch di halaman
        // ASI-Bot). Credential tiap jaringan slot terpisah.
        net = b.exists ? ((b as any).active_testnet ?? true) : true;
        setActiveTestnet(net);
        if (b.exists) setBotCfg(b);
      } catch {}
      try {
        const r = await api.asi.listCredentials(did);
        setCreds(r.items);
        // v9.9.5 — pilih exchange dari credential yang COCOK dengan
        // network aktif, fallback ke credential apa pun.
        const match = r.items.find((c) => !!c.testnet === net) || r.items[0];
        if (match) setExchange(match.exchange as any);
      } catch {}
      setCredsLoaded(true);
    })();
  }, [visible, intent]);

  // v9.9.9 — STRICT: credential harus cocok dengan jaringan yang dipilih
  // chip (DEMO/REAL). Tidak ada fallback silang jaringan — bila jaringan
  // pilihan belum terhubung, tampilkan empty-state "hubungkan dulu".
  const activeCred = useMemo(
    () => creds.find((c) => c.exchange === exchange && !!c.testnet === activeTestnet),
    [creds, exchange, activeTestnet],
  );

  useEffect(() => {
    if (!visible || !intent || !deviceId || !activeCred) {
      setPreview(null);
      setPreviewTimeout(false);
      return;
    }
    setPreviewTimeout(false);
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      // v10.2.18 — Watchdog 5 detik: bila request tidak selesai di 5s,
      // nyalakan state previewTimeout agar UI menampilkan tombol Retry.
      const watchdog = setTimeout(() => {
        if (!cancelled) {
          setPreviewTimeout(true);
          setLoading(false);
        }
      }, 5000);
      try {
        const p = await api.asi.previewTrade(deviceId, {
          exchange, symbol: intent.symbol, side: intent.side,
          entry: intent.entry, stop_loss: intent.stop_loss,
          // v10.0.9 — kirim ladder PENUH; backend yang menggeser level
          // (2 TP → [TP2,TP3], 1 TP → [TP2]) supaya preview = eksekusi.
          take_profits: intent.take_profits,
          risk_pct: riskPct, leverage, tp_count: tpCount,
          testnet: activeTestnet,
        });
        if (cancelled) return;
        clearTimeout(watchdog);
        setPreview(p);
        setPreviewTimeout(false);
      } catch (e: any) {
        if (cancelled) return;
        clearTimeout(watchdog);
        // v10.2.18 — Error jaringan tanpa code/detail → tampilkan Retry
        // (jangan stuck "Calculating…"). Error HTTP backend tetap
        // menimpa preview seperti sebelumnya.
        if (e?.code || e?.detail) {
          setPreview({
            ok: false, message: e?.detail?.message || e?.message || t("ats_no_preview"),
            balance_usdt: 0, margin_usdt: 0, size_usdt: 0, qty: 0,
            leverage, risk_pct: riskPct, est_loss_usdt: 0, tp_estimations: [],
          });
          setPreviewTimeout(false);
        } else {
          setPreviewTimeout(true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [visible, intent, deviceId, exchange, riskPct, leverage, tpCount, activeCred, activeTestnet, previewAttempt]);

  const execute = async () => {
    if (!intent || !preview?.ok) return;
    // v9.7.7 — Cek duplikat posisi terbuka pada symbol+exchange yang sama.
    // Jika sudah ada, konfirmasi dulu sebelum menambah posisi (pyramid).
    // v9.8.5 — Alert.alert no-op di web → pakai window.confirm fallback
    // (tanpa ini promise tidak pernah resolve dan eksekusi menggantung).
    try {
      const list = await api.asi.listTrades(deviceId);
      const sym = String(intent.symbol).toUpperCase();
      const dup = (list.items || []).find(
        (tr) => String(tr.status || "").toLowerCase() === "open"
          && String(tr.symbol || "").toUpperCase() === sym
          && (tr.exchange || "") === exchange,
      );
      if (dup) {
        const dupBody = t("ats_dup_body")
          .replace("{side}", String(dup.side))
          .replace("{symbol}", sym)
          .replace("{exchange}", exchange.toUpperCase())
          .replace("{pnl}", (dup.pnl_usdt ?? 0).toFixed(2));
        const proceed = Platform.OS === "web"
          ? window.confirm(`${t("ats_dup_title")}\n\n${dupBody}`)
          : await new Promise<boolean>((resolve) => {
              Alert.alert(t("ats_dup_title"), dupBody, [
                { text: t("ats_dup_cancel"), style: "cancel", onPress: () => resolve(false) },
                { text: t("ats_dup_add"), onPress: () => resolve(true) },
              ]);
            });
        if (!proceed) return;
      }
    } catch {}
    setExecuting(true);
    try {
      const res = await api.asi.executeTrade(deviceId, {
        exchange, symbol: intent.symbol, side: intent.side,
        entry: intent.entry, stop_loss: intent.stop_loss,
        take_profits: intent.take_profits,
        risk_pct: riskPct, leverage, mode: "semi",
        tp_count: tpCount, trailing_callback_rate: trailingCbRate,
        margin_mode: marginMode,
        testnet: activeTestnet,
        // v9.9.13 — label formula di kartu Recent Trades
        // v10.0.16 — Label formula mengikuti Trader Profile apa adanya;
        // null = dashboard default (bukan lagi dipaksa "confluence").
        profile: apiProfile ?? null,
        formula_tag: intent.formula_tag ?? formulaTagFromSignal(null, null, apiProfile),
        entry_mode: entryMode,
      });
      // v9.9.13 — Entry LIMIT deep: order dipasang di harga sinyal dan
      // MENUNGGU terisi (maks 1 candle). Belum ada posisi terbuka.
      if ((res as any).pending) {
        setExecResult({
          ok: true,
          title: tEN("ats_pending_title"),
          body:
            `LIMIT ${intent.side} ${intent.symbol} @ ${res.entry_price?.toFixed?.(6) ?? intent.entry}\n` +
            `${res.testnet ? "TESTNET" : "MAINNET"}\n` +
            tEN("ats_pending_body"),
        });
        return;
      }
      // v9.9.2 — Backend sekarang GARANSI: res.ok === true berarti SL+TP
      // sudah TERVERIFIKASI di Binance (via openAlgoOrders). Bracket soft
      // tidak lagi dibuat untuk trade baru — rollback otomatis dilakukan
      // bila gagal. Jadi panel sukses selalu bersih tanpa warning.
      const actualMM = (res as any).actual_margin_mode || marginMode;
      const layerNote = (res as any).layered
        ? `\n${tEN("ats_layered_note").replace("{n}", "2+")}`
        : "";
      setExecResult({
        ok: true,
        title: tEN("ats_exec_done"),
        body:
          `${intent.side} ${intent.symbol} @ ${res.entry_price?.toFixed?.(6) ?? intent.entry}\n` +
          `Qty: ${res.qty} · ${tEN("ats_leverage")}: ${(res as any).actual_leverage ?? res.leverage}x · ${String(actualMM).toUpperCase()}\n` +
          `${res.testnet ? "TESTNET" : "MAINNET"}\n` +
          `✓ SL/TP on ${{ binance: "Binance", bybit: "Bybit", okx: "OKX", bitget: "Bitget" }[exchange] || "Exchange"}` + layerNote,
      });
    } catch (e: any) {
      // v9.9.2 — api.ts sudah menempelkan e.code dan e.detail dari
      // response body JSON {code, message, rollback_done, ...}.
      const code: string | undefined = e?.code;
      const msg: string = e?.detail?.message || e?.message || String(e);
      // v10.0.15 — Notifikasi MENGIKUTI BAHASA pilihan user (dashboard):
      // reason code backend dipetakan ke string i18n; fallback ke pesan
      // English backend (backend tidak pernah kirim Bahasa Indonesia lagi).
      const localizedBody = ((): string => {
        if (code === "qty_zero") return t("ats_err_qty_zero");
        if (code === "min_notional") return t("ats_err_min_notional")
          .replace("{size}", String((e?.detail?.size_usdt ?? 0).toFixed?.(2) ?? "0.00"))
          .replace("{min}", String((e?.detail?.min_notional ?? 5).toFixed?.(2) ?? "5.00"));
        if (code === "balance_fetch_failed") return t("ats_err_balance");
        if (code === "symbol_filters_missing") return t("ats_err_filters");
        if (code === "exchange_unreachable") return t("ats_err_unreachable");
        if (code === "margin_mode_mismatch") return t("ats_err_mm_mismatch");
        if (code === "opposite_position") return t("ats_err_opposite");
        if (code === "margin_mode_set_failed") return t("ats_err_mm_failed");
        if (code === "position_not_visible") return t("ats_err_pos_not_visible");
        if (code === "execute_failed") return t("ats_err_execute_generic");
        // v10.2.35 — Bracket failures: body mengikuti bahasa user
        // (sebelumnya jatuh ke pesan mentah backend).
        if (code === "bracket_sl_failed") return t("ats_err_bracket_sl");
        if (code === "bracket_tp_incomplete") return t("ats_err_bracket_tp");
        if (code === "bracket_sl_not_verified") return t("ats_err_bracket_verify");
        if (code === "bracket_failed_rollback_failed") return t("ats_err_rollback_failed");
        return msg || t("ats_err_execute_generic");
      })();
      let title = t("ats_exec_failed");
      let infoOnly = false;
      if (code === "bracket_sl_failed" || code === "bracket_tp_incomplete"
          || code === "bracket_sl_not_verified") {
        if (e?.detail?.rollback_done) {
          title = tEN("ats_rollback_info_title");
          infoOnly = true;
        } else {
          title = tEN("ats_bracket_rollback_title");
        }
      } else if (code === "margin_mode_mismatch"
                 || code === "margin_mode_set_failed") {
        title = t("ats_margin_mismatch_title");
        infoOnly = true;
      } else if (code === "bracket_failed_rollback_failed"
                 || e?.detail?.requires_manual_action) {
        title = tEN("ats_rollback_failed_title");
      }
      setExecResult({ ok: false, title, body: localizedBody, infoOnly } as any);
    } finally { setExecuting(false); }
  };

  if (!intent) return null;
  const sideColor = intent.side === "BUY" ? GREEN : RED;
  const executed = !!execResult?.ok;

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <Pressable style={s.backdrop} onPress={onClose}>
        <Pressable style={[s.sheet, { backgroundColor: colors.surface, paddingBottom: insets.bottom + 16 }]}
                   onPress={(e) => e.stopPropagation()}>
          {/* v9.9.10 — flexShrink agar konten menyusut dan footer sticky
              (tombol EXECUTE) SELALU terlihat di bawah, tidak pernah
              terdorong keluar layar saat konten panjang. */}
          <ScrollView showsVerticalScrollIndicator={false} style={{ flexShrink: 1 }}>
            {/* Header */}
            <View style={s.header}>
              <View style={[s.sideBadge, { backgroundColor: sideColor }]}>
                <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 11, letterSpacing: 1 }}>
                  {intent.side === "BUY" ? "LONG" : "SHORT"}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.title, { color: colors.textPrimary }]}>{intent.symbol}</Text>
                <Text style={[s.caption, { color: colors.textMuted }]}>{t("ats_subtitle")}</Text>
              </View>
              <TouchableOpacity onPress={onClose} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.textMuted} />
              </TouchableOpacity>
            </View>

            {/* v9.9.6 — Loading state saat credential belum termuat
                (anti-flash empty-state). Empty state hanya tampil setelah
                credential benar-benar selesai dimuat dan memang kosong
                untuk network aktif. */}
            {!credsLoaded ? (
              <View style={[s.empty, { backgroundColor: colors.background }]}>
                <Text style={{ color: colors.textMuted, fontSize: 12, marginTop: 10 }}>
                  {t("ats_calculating")}
                </Text>
              </View>
            ) : !activeCred ? (
              <View style={[s.empty, { backgroundColor: colors.background }]}>
                <Text style={{ fontSize: 36 }}>🔌</Text>
                <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 14, marginTop: 10 }}>
                  {t("ats_no_cred_title")}
                </Text>
                <Text style={{ color: colors.textMuted, fontSize: 12, textAlign: "center", lineHeight: 18, marginTop: 6 }}>
                  {t("ats_no_cred_body")}
                  {`\n(${activeTestnet ? "🧪 TESTNET" : "🔴 MAINNET"})`}
                </Text>
                <TouchableOpacity
                  style={[s.cta, { backgroundColor: MINT, marginTop: 14 }]}
                  onPress={() => { if (onCloseAll) onCloseAll(); else onClose(); router.replace("/asi-bot" as never); }}>
                  <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.6 }}>{t("ats_connect_cta")}</Text>
                </TouchableOpacity>
              </View>
            ) : (
              <>
                {/* Network picker — v9.9.9: TEPAT 2 chip: DEMO (Testnet)
                    atau REAL (Mainnet). Tap langsung memilih jaringan
                    SEBELUM execute + disimpan ke bot config. Jaringan
                    tanpa credential tampil redup + label Not connected. */}
                <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
                  {([
                    { isTest: true, label: t("asi_demo_badge"), sub: "Testnet", color: BLUE },
                    { isTest: false, label: "REAL", sub: "Mainnet", color: GREEN },
                  ] as const).map((opt) => {
                    const act = activeTestnet === opt.isTest;
                    const hasCred = creds.some((c) => c.exchange === exchange && !!c.testnet === opt.isTest);
                    return (
                      <TouchableOpacity
                        key={String(opt.isTest)}
                        onPress={() => {
                          // v9.9.9 — ganti jaringan = kotak bawah WAJIB
                          // langsung reset (jangan tampilkan angka jaringan
                          // sebelumnya), lalu preview di-refetch oleh effect.
                          setPreview(null);
                          setActiveTestnet(opt.isTest);
                          if (deviceId && botCfg) {
                            const next = { ...botCfg, active_testnet: opt.isTest };
                            setBotCfg(next);
                            api.asi.saveBot(deviceId, next).catch(() => {});
                          }
                        }}
                        style={[s.exChip, {
                          flex: 1, alignItems: "center", paddingVertical: 10,
                          backgroundColor: act ? opt.color : colors.background,
                          borderColor: act ? opt.color : colors.border,
                          opacity: hasCred ? 1 : 0.55,
                        }]}
                        testID={opt.isTest ? "ats-net-demo" : "ats-net-real"}
                      >
                        <Text style={{
                          color: act ? "#0B0E11" : colors.textPrimary,
                          fontWeight: "900", fontSize: 12, letterSpacing: 0.4,
                        }}>
                          {opt.label} ({opt.sub})
                        </Text>
                        {!hasCred ? (
                          <Text style={{
                            color: act ? "#0B0E11" : colors.textMuted,
                            fontSize: 9, fontWeight: "700", marginTop: 1,
                          }}>
                            {t("asi_not_connected")}
                          </Text>
                        ) : null}
                      </TouchableOpacity>
                    );
                  })}
                </View>

                {/* Level grid — v10.0.9: level TP yang ditampilkan MENGIKUTI
                    pergeseran ladder backend (2 TP → TP1 cell = harga level
                    TP2, dst) supaya yang user lihat = yang benar-benar
                    dipasang di exchange. */}
                <View style={s.grid}>
                  <LevelCell label="ENTRY" value={formatPrice(intent.entry, "crypto")} color={colors.textPrimary} colors={colors} />
                  <LevelCell label="STOP LOSS" value={formatPrice(intent.stop_loss, "crypto")} color={RED} colors={colors} />
                  {(() => {
                    const full = intent.take_profits || [];
                    const shifted = (full.length >= 3 && tpCount < 3)
                      ? full.slice(1, 1 + tpCount)
                      : full.slice(0, tpCount);
                    return shifted.map((tp, i) => (
                      <LevelCell key={`tp${i}`} label={`TP${i + 1}`} value={formatPrice(tp ?? NaN, "crypto")} color={GREEN} colors={colors} />
                    ));
                  })()}
                  <LevelCell label="SIDE" value={intent.side === "BUY" ? "LONG" : "SHORT"} color={sideColor} colors={colors} />
                </View>

                {/* Risk & Leverage */}
                <StepperRow label={t("ats_risk_per_trade")} value={`${riskPct}%`} colors={colors}
                  onDec={() => setRiskPct(Math.max(1, riskPct - 1))}
                  onInc={() => setRiskPct(Math.min(30, riskPct + 1))} />
                <StepperRow label={t("ats_leverage")} value={`${leverage}x`} colors={colors}
                  onDec={() => setLeverage(Math.max(1, leverage - 1))}
                  onInc={() => setLeverage(Math.min(125, leverage + 1))} />

                {/* v9.9.0 — Margin Mode selector (WAJIB sebelum eksekusi).
                    ISOLATED default: kerugian terbatas pada margin posisi.
                    CROSS: seluruh saldo futures jadi jaminan. */}
                <View style={{ marginTop: 4 }}>
                  <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
                    {t("ats_margin_mode")}
                  </Text>
                  <View style={{ flexDirection: "row", gap: 8 }}>
                    {(["isolated", "cross"] as const).map((mm) => {
                      const active = marginMode === mm;
                      return (
                        <TouchableOpacity
                          key={mm}
                          onPress={() => setMarginMode(mm)}
                          style={{
                            flex: 1, paddingVertical: 10, borderRadius: 10,
                            borderWidth: 1.5,
                            borderColor: active ? MINT : colors.border,
                            backgroundColor: active ? MINT : "transparent",
                            alignItems: "center",
                          }}
                          testID={`asi-margin-${mm}`}
                        >
                          <Text style={{
                            color: active ? "#FFFFFF" : colors.textPrimary,
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

                {/* v10.0.1 — Tipe eksekusi entry: MARKET PRICE (ungu muda,
                    instan) vs LIMIT PRICE (kuning, entry moderate).
                    Persist ke bot config (dipakai juga Full-Auto). */}
                <View style={{ marginTop: 4 }}>
                  <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: "700", marginBottom: 6 }}>
                    {t("ats_entry_mode")}
                  </Text>
                  <View style={{ flexDirection: "row", gap: 8 }}>
                    {(["market", "limit"] as const).map((em) => {
                      const active = entryMode === em;
                      const col = em === "market" ? PURPLE : GOLD;
                      return (
                        <TouchableOpacity
                          key={em}
                          onPress={() => {
                            setEntryMode(em);
                            if (deviceId && botCfg) {
                              const next = { ...(botCfg as any), entry_mode: em };
                              setBotCfg(next);
                              api.asi.saveBot(deviceId, next).catch(() => {});
                            }
                          }}
                          style={{
                            flex: 1, paddingVertical: 10, borderRadius: 10,
                            borderWidth: 1.5,
                            borderColor: active ? col : colors.border,
                            backgroundColor: active ? col : "transparent",
                            alignItems: "center",
                          }}
                          testID={`asi-entry-${em}`}
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

                {/* v9.6.0 — TP Strategy selector */}
                <View style={{ flexDirection: "row", gap: 6, marginTop: 10 }}>
                  {([1, 2, 3] as const).map((n) => {
                    const act = tpCount === n;
                    const lbl = n === 1 ? "1 TP · 100%" : n === 2 ? "2 TP · 50/50" : "3 TP · 50/25/25";
                    return (
                      <TouchableOpacity key={n} onPress={() => setTpCount(n)}
                        style={[s.exChip, { flex: 1, alignItems: "center", backgroundColor: act ? MINT : colors.background, borderColor: act ? MINT : colors.border }]}>
                        <Text style={{ color: act ? "#FFFFFF" : colors.textPrimary, fontWeight: "900", fontSize: 10.5 }}>{lbl}</Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>
                <StepperRow
                  label={t("ats_trailing_cb")}
                  value={trailingCbRate === 0 ? "OFF" : `${trailingCbRate.toFixed(1)}%`}
                  colors={colors}
                  onDec={() => setTrailingCbRate(Math.max(0, Math.round((trailingCbRate - 0.5) * 10) / 10))}
                  onInc={() => setTrailingCbRate(Math.min(10, Math.round((trailingCbRate + 0.5) * 10) / 10))}
                />

                {/* Preview */}
                <View style={[s.preview, { backgroundColor: colors.background, borderColor: colors.border }]}>
                  {previewTimeout ? (
                    // v10.2.18 — Preview stuck/gagal >5s: tampilkan pesan
                    // error + tombol Retry (jangan diam saja).
                    <View style={{ gap: 10, alignItems: "flex-start" }}>
                      <Text style={{ color: RED, fontSize: 12, lineHeight: 18 }}>
                        {t("ats_preview_timeout")
                          || "Perhitungan preview terlalu lama. Periksa koneksi lalu coba lagi."}
                      </Text>
                      <TouchableOpacity
                        onPress={retryPreview}
                        style={{
                          paddingHorizontal: 14, paddingVertical: 8,
                          borderRadius: 8, backgroundColor: MINT,
                        }}
                        testID="ats-preview-retry"
                      >
                        <Text style={{ color: "#FFFFFF", fontWeight: "900", fontSize: 12 }}>
                          {t("common_retry") || "Coba Lagi"}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  ) : loading && !preview ? (
                    <Text style={{ color: colors.textMuted, fontSize: 12 }}>{t("ats_calculating")}</Text>
                  ) : preview?.ok ? (
                    <>
                      {/* v9.9.9 — Label jaringan di kotak angka: user harus
                          tahu angka ini milik akun DEMO atau REAL. */}
                      <PreviewRow
                        label={`${t("ats_balance")} · ${activeTestnet ? t("asi_demo_badge") : "REAL"}`}
                        value={`$${preview.balance_usdt.toFixed(2)}`} colors={colors} />
                      <PreviewRow label={t("ats_margin")} value={`$${preview.margin_usdt.toFixed(2)}`} colors={colors} highlight />
                      <PreviewRow label={t("ats_size")} value={`$${preview.size_usdt.toFixed(2)} (${preview.qty.toFixed(6)})`} colors={colors} />
                      <PreviewRow label={t("ats_est_loss")} value={`-$${preview.est_loss_usdt.toFixed(2)}`} colors={colors} valueColor={RED} />
                      {preview.tp_estimations.map((tp, i) => (
                        <PreviewRow key={i} label={`TP${i + 1} ${t("ats_profit")} (${Math.round(tp.qty_share * 100)}%)`}
                                    value={`+$${tp.est_profit_usdt.toFixed(2)}`} colors={colors} valueColor={GREEN} />
                      ))}
                    </>
                  ) : (
                    <Text style={{ color: RED, fontSize: 12 }}>
                      {(() => {
                        // v9.8.3 — Reason code dari backend dipetakan ke pesan
                        // terlokalisasi. Fallback ke message mentah.
                        const reason = (preview as any)?.reason as string | undefined;
                        if (reason === "not_listed") {
                          return t("ats_err_not_listed").replace("{symbol}", intent.symbol);
                        }
                        if (reason === "market_inactive") {
                          return t("ats_err_inactive").replace("{symbol}", intent.symbol);
                        }
                        if (reason === "min_notional") {
                          // v9.8.8 — posisi di bawah minimum notional exchange
                          return t("ats_err_min_notional")
                            .replace("{size}", (preview?.size_usdt ?? 0).toFixed(2))
                            .replace("{min}", (preview?.min_notional ?? 0).toFixed(2));
                        }
                        // v10.0.15 — Reason code lain terlokalisasi (bahasa
                        // mengikuti pilihan user di dashboard).
                        if (reason === "qty_zero") return t("ats_err_qty_zero");
                        if (reason === "balance_fetch_failed") return t("ats_err_balance");
                        if (reason === "symbol_filters_missing") return t("ats_err_filters");
                        if (reason === "exchange_unreachable") return t("ats_err_unreachable");
                        if (reason === "margin_mode_mismatch") return t("ats_err_mm_mismatch");
                        if (reason === "opposite_position") return t("ats_err_opposite");
                        if (reason === "margin_mode_set_failed") return t("ats_err_mm_failed");
                        return preview?.message || t("ats_no_preview");
                      })()}
                    </Text>
                  )}
                </View>

                {/* Execute button dipindah ke sticky footer (v9.9.10) */}

                {/* v9.8.5 — Panel hasil eksekusi di dalam sheet (Alert.alert
                    tidak tampil di web preview, jadi hasil harus in-app). */}
                {execResult ? (
                  <View style={{
                    marginTop: 12, borderRadius: 12, padding: 12,
                    borderWidth: 1.5,
                    borderColor: execResult.ok ? GREEN : (execResult.infoOnly ? GOLD : RED),
                    backgroundColor: execResult.ok
                      ? "rgba(34,197,94,0.08)"
                      : execResult.infoOnly
                        ? "rgba(245,166,35,0.08)"
                        : "rgba(239,68,68,0.08)",
                  }} testID="asi-exec-result">
                    <Text style={{
                      color: execResult.ok ? GREEN : (execResult.infoOnly ? GOLD : RED),
                      fontWeight: "900", fontSize: 13, letterSpacing: 0.3,
                    }}>
                      {execResult.title}
                    </Text>
                    <Text style={{ color: colors.textPrimary, fontSize: 12, marginTop: 6, lineHeight: 18 }}>
                      {execResult.body}
                    </Text>
                    <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
                      {execResult.ok ? (
                        <TouchableOpacity
                          onPress={goToRecentTrades}
                          style={{ flex: 1, backgroundColor: LIGHT_BLUE_BTN, borderRadius: 10, paddingVertical: 11, alignItems: "center" }}
                          testID="asi-exec-view-recent"
                        >
                          <Text style={{ color: "#FFFFFF", fontWeight: "900", fontSize: 11.5 }}>
                            {t("asi_exec_view_recent")}
                          </Text>
                        </TouchableOpacity>
                      ) : (
                        <TouchableOpacity
                          onPress={() => setExecResult(null)}
                          style={{ flex: 1, backgroundColor: RED, borderRadius: 10, paddingVertical: 11, alignItems: "center" }}
                          testID="asi-exec-retry"
                        >
                          <Text style={{ color: "#FFFFFF", fontWeight: "900", fontSize: 11.5 }}>
                            {t("ats_try_again")}
                          </Text>
                        </TouchableOpacity>
                      )}
                      <TouchableOpacity
                        onPress={onClose}
                        style={{ flex: 1, backgroundColor: colors.background, borderRadius: 10, paddingVertical: 11, alignItems: "center", borderWidth: 1, borderColor: colors.border }}
                        testID="asi-exec-close"
                      >
                        <Text style={{ color: colors.textPrimary, fontWeight: "900", fontSize: 11.5 }}>
                          {t("common_close")}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                ) : null}
                <Text style={{ color: colors.textMuted, fontSize: 10.5, textAlign: "center", marginTop: 8, lineHeight: 16 }}>
                  {t("ats_footer1")}{"\n"}
                  {t("ats_footer2")}
                </Text>
              </>
            )}
          </ScrollView>

          {/* v9.9.10 — STICKY FOOTER: tombol EXECUTE SELALU terlihat di
              bawah sheet (di luar area scroll), tidak pernah terdorong
              keluar layar walau konten panjang. Setelah SUKSES tombol
              berubah "✅ EXECUTED" dan terkunci (anti double-order). */}
          {credsLoaded && activeCred && intent ? (
            <View style={{ paddingTop: 10, borderTopWidth: 1, borderTopColor: colors.border }}>
              <TouchableOpacity
                onPress={execute}
                disabled={executing || !preview?.ok || executed}
                style={[s.cta, {
                  backgroundColor: executed
                    ? GREEN
                    : (executing || !preview?.ok ? colors.textMuted : sideColor),
                  opacity: executed ? 0.85 : 1,
                  marginTop: 0,
                }]}
                testID="asi-trade-execute">
                <Ionicons name={executed ? "checkmark-circle" : "rocket"} size={18} color="#FFFFFF" />
                <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.8 }}>
                  {executed
                    ? `✅ ${t("ats_executed_btn")}`
                    : executing
                      ? t("ats_sending")
                      : `EXECUTE ${intent.side === "BUY" ? "LONG" : "SHORT"} ${activeTestnet ? "(TESTNET)" : ""}`}
                </Text>
              </TouchableOpacity>
            </View>
          ) : null}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function LevelCell({ label, value, color, colors }: any) {
  return (
    <View style={[s.cell, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <Text style={{ color: colors.textMuted, fontSize: 10, fontWeight: "700", letterSpacing: 0.5 }}>{label}</Text>
      <Text style={{ color, fontSize: 13, fontWeight: "900", marginTop: 2 }}>{value}</Text>
    </View>
  );
}

function StepperRow({ label, value, onDec, onInc, colors }: any) {
  return (
    <View style={[s.stepRow, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{label}</Text>
      <View style={{ flex: 1 }} />
      <TouchableOpacity onPress={onDec} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="remove" size={14} color={colors.textPrimary} />
      </TouchableOpacity>
      <Text style={{ color: GOLD, fontWeight: "900", width: 70, textAlign: "center" }}>{value}</Text>
      <TouchableOpacity onPress={onInc} style={[s.stepBtn, { borderColor: colors.border }]}>
        <Ionicons name="add" size={14} color={colors.textPrimary} />
      </TouchableOpacity>
    </View>
  );
}

function PreviewRow({ label, value, colors, valueColor, highlight }: any) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: 4 }}>
      <Text style={{ color: colors.textMuted, fontSize: 12 }}>{label}</Text>
      <Text style={{ color: valueColor || (highlight ? GOLD : colors.textPrimary),
                     fontSize: 12.5, fontWeight: "800" }}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.65)", justifyContent: "flex-end" },
  sheet: { maxHeight: "90%", borderTopLeftRadius: 24, borderTopRightRadius: 24,
           padding: 18, paddingTop: 16 },
  header: { flexDirection: "row", alignItems: "center", gap: 12, marginBottom: 10 },
  sideBadge: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6 },
  title: { fontSize: 20, fontWeight: "900", letterSpacing: 0.5 },
  caption: { fontSize: 11, marginTop: 2 },
  empty: { padding: 24, borderRadius: 14, alignItems: "center", marginTop: 10 },
  cta: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
         paddingVertical: 14, borderRadius: 12 },
  exChip: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 12 },
  cell: { width: "32%", padding: 8, borderWidth: 1, borderRadius: 8 },
  stepRow: { flexDirection: "row", alignItems: "center", padding: 10, borderWidth: 1,
             borderRadius: 10, marginTop: 10, gap: 8 },
  stepBtn: { width: 28, height: 28, borderRadius: 7, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  preview: { padding: 12, borderRadius: 10, borderWidth: 1, marginTop: 12 },
});
