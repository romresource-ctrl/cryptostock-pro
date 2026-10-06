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
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, formatPrice, type AsiCredential, type AsiPreview,
} from "@/src/lib/api";

const GOLD = "#F0B90B";
const MINT = "#4ADE80"; // v9.4.3 — ASI-Bot accent (hijau muda + teks putih)
const GREEN = "#22C55E";
const RED = "#EF4444";
const LIGHT_BLUE_BTN = "#38BDF8"; // v9.8.5 — tombol "Lihat Recent Trades"

export type AsiTradeIntent = {
  symbol: string;              // e.g. "BTC", "ETH"
  side: "BUY" | "SELL";
  entry: number;
  stop_loss: number;
  take_profits: number[];      // [tp1, tp2, tp3]
  source?: "ai-suggestions" | "asset-detail" | "asi-bot-semi";
};

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
  const { t } = useI18n();
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
  // v9.9.0 — Margin mode wajib dipilih sebelum eksekusi (default ISOLATED).
  const [marginMode, setMarginMode] = useState<"isolated" | "cross">("isolated");
  // v9.9.5 — Network aktif dari bot config (testnet = demo).
  const [activeTestnet, setActiveTestnet] = useState(true);
  // v9.8.5 — Hasil eksekusi ditampilkan sebagai panel di DALAM sheet
  // (Alert.alert bawaan tidak tampil di web preview). null = belum eksekusi.
  const [execResult, setExecResult] = useState<{ ok: boolean; title: string; body: string } | null>(null);

  // Reset panel hasil tiap kali intent baru dibuka.
  useEffect(() => { setExecResult(null); }, [intent, visible]);

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
        // v9.9.5 — Network aktif dari bot config (switch di halaman
        // ASI-Bot). Credential tiap jaringan slot terpisah.
        net = b.exists ? ((b as any).active_testnet ?? true) : true;
        setActiveTestnet(net);
      } catch {}
      try {
        const r = await api.asi.listCredentials(did);
        setCreds(r.items);
        // v9.9.5 — pilih exchange dari credential yang COCOK dengan
        // network aktif, fallback ke credential apa pun.
        const match = r.items.find((c) => !!c.testnet === net) || r.items[0];
        if (match) setExchange(match.exchange as any);
      } catch {}
    })();
  }, [visible, intent]);

  // v9.9.5 — credential untuk network AKTIF (slot mainnet/testnet
  // terpisah). Fallback ke slot lain hanya utk data lama.
  // CATATAN: harus didefinisikan SEBELUM useEffect preview di bawah
  // (dipakai di dependency array-nya).
  const activeCred = useMemo(
    () => creds.find((c) => c.exchange === exchange && !!c.testnet === activeTestnet)
          || creds.find((c) => c.exchange === exchange),
    [creds, exchange, activeTestnet],
  );

  useEffect(() => {
    if (!visible || !intent || !deviceId || !activeCred) {
      setPreview(null);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const p = await api.asi.previewTrade(deviceId, {
          exchange, symbol: intent.symbol, side: intent.side,
          entry: intent.entry, stop_loss: intent.stop_loss,
          take_profits: intent.take_profits.slice(0, tpCount),
          risk_pct: riskPct, leverage, tp_count: tpCount,
          testnet: activeTestnet,
        });
        setPreview(p);
      } catch (e: any) {
        setPreview({ ok: false, message: e?.message || t("ats_no_preview"),
                     balance_usdt: 0, margin_usdt: 0, size_usdt: 0, qty: 0,
                     leverage, risk_pct: riskPct, est_loss_usdt: 0, tp_estimations: [] });
      } finally { setLoading(false); }
    }, 250);
    return () => clearTimeout(t);
  }, [visible, intent, deviceId, exchange, riskPct, leverage, tpCount, activeCred, activeTestnet]);

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
        take_profits: intent.take_profits.slice(0, tpCount),
        risk_pct: riskPct, leverage, mode: "semi",
        tp_count: tpCount, trailing_callback_rate: trailingCbRate,
        margin_mode: marginMode,
        testnet: activeTestnet,
      });
      // v9.9.2 — Backend sekarang GARANSI: res.ok === true berarti SL+TP
      // sudah TERVERIFIKASI di Binance (via openAlgoOrders). Bracket soft
      // tidak lagi dibuat untuk trade baru — rollback otomatis dilakukan
      // bila gagal. Jadi panel sukses selalu bersih tanpa warning.
      const actualMM = (res as any).actual_margin_mode || marginMode;
      const layerNote = (res as any).layered
        ? `\n${t("ats_layered_note").replace("{n}", "2+")}`
        : "";
      setExecResult({
        ok: true,
        title: t("ats_exec_done"),
        body:
          `${intent.side} ${intent.symbol} @ ${res.entry_price?.toFixed?.(6) ?? intent.entry}\n` +
          `Qty: ${res.qty} · ${t("ats_leverage")}: ${(res as any).actual_leverage ?? res.leverage}x · ${String(actualMM).toUpperCase()}\n` +
          `${res.testnet ? "TESTNET" : "MAINNET"}\n` +
          `${t("asi_bracket_native_ok")}` + layerNote,
      });
    } catch (e: any) {
      // v9.9.2 — api.ts sudah menempelkan e.code dan e.detail dari
      // response body JSON {code, message, rollback_done, ...}.
      const code: string | undefined = e?.code;
      const msg: string = e?.detail?.message || e?.message || String(e);
      let title = t("ats_exec_failed");
      if (code === "bracket_sl_failed" || code === "bracket_tp_incomplete"
          || code === "bracket_sl_not_verified") {
        title = t("ats_bracket_rollback_title");
      } else if (code === "margin_mode_mismatch"
                 || code === "margin_mode_set_failed") {
        title = t("ats_margin_mismatch_title");
      } else if (code === "bracket_failed_rollback_failed"
                 || e?.detail?.requires_manual_action) {
        title = t("ats_rollback_failed_title");
      }
      setExecResult({ ok: false, title, body: msg });
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
          <ScrollView showsVerticalScrollIndicator={false}>
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

            {/* No credential state (untuk network AKTIF) */}
            {!activeCred ? (
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
                {/* Exchange picker */}
                <View style={{ flexDirection: "row", gap: 6, marginTop: 10 }}>
                  {creds.map((c) => {
                    const act = c.exchange === exchange;
                    return (
                      <TouchableOpacity key={c.exchange} onPress={() => setExchange(c.exchange as any)}
                        style={[s.exChip, { backgroundColor: act ? MINT : colors.background, borderColor: act ? MINT : colors.border }]}>
                        <Text style={{ color: act ? "#FFFFFF" : colors.textPrimary, fontWeight: "800", fontSize: 11 }}>
                          {c.exchange.toUpperCase()} {c.testnet ? "·T" : ""}
                        </Text>
                      </TouchableOpacity>
                    );
                  })}
                </View>

                {/* Level grid */}
                <View style={s.grid}>
                  <LevelCell label="ENTRY" value={formatPrice(intent.entry, "crypto")} color={colors.textPrimary} colors={colors} />
                  <LevelCell label="STOP LOSS" value={formatPrice(intent.stop_loss, "crypto")} color={RED} colors={colors} />
                  {tpCount >= 1 ? (
                    <LevelCell label="TP1" value={formatPrice(intent.take_profits[0] ?? NaN, "crypto")} color={GREEN} colors={colors} />
                  ) : null}
                  {tpCount >= 2 ? (
                    <LevelCell label="TP2" value={formatPrice(intent.take_profits[1] ?? NaN, "crypto")} color={GREEN} colors={colors} />
                  ) : null}
                  {tpCount >= 3 ? (
                    <LevelCell label="TP3" value={formatPrice(intent.take_profits[2] ?? NaN, "crypto")} color={GREEN} colors={colors} />
                  ) : null}
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

                {/* v9.6.0 — TP Strategy selector */}
                <View style={{ flexDirection: "row", gap: 6, marginTop: 10 }}>
                  {([1, 2, 3] as const).map((n) => {
                    const act = tpCount === n;
                    const lbl = n === 1 ? "1 TP · 100%" : n === 2 ? "2 TP · 50/50" : "3 TP · 33/33/34";
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
                  {loading ? (
                    <Text style={{ color: colors.textMuted, fontSize: 12 }}>{t("ats_calculating")}</Text>
                  ) : preview?.ok ? (
                    <>
                      <PreviewRow label={t("ats_balance")} value={`$${preview.balance_usdt.toFixed(2)}`} colors={colors} />
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
                        return preview?.message || t("ats_no_preview");
                      })()}
                    </Text>
                  )}
                </View>

                {/* Execute button — v9.8.5: setelah SUKSES tombol berubah
                    menjadi "✅ EXECUTED" dan TERKUNCI (tidak bisa ditekan
                    lagi) supaya tidak ada order ganda tak sengaja. */}
                <TouchableOpacity
                  onPress={execute}
                  disabled={executing || !preview?.ok || executed}
                  style={[s.cta, {
                    backgroundColor: executed
                      ? GREEN
                      : (executing || !preview?.ok ? colors.textMuted : sideColor),
                    marginTop: 14,
                    opacity: executed ? 0.85 : 1,
                  }]}
                  testID="asi-trade-execute">
                  <Ionicons name={executed ? "checkmark-circle" : "rocket"} size={18} color="#FFFFFF" />
                  <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.8 }}>
                    {executed
                      ? `✅ ${t("ats_executed_btn")}`
                      : executing
                        ? t("ats_sending")
                        : `EXECUTE ${intent.side === "BUY" ? "LONG" : "SHORT"} ${activeCred?.testnet ? "(TESTNET)" : ""}`}
                  </Text>
                </TouchableOpacity>

                {/* v9.8.5 — Panel hasil eksekusi di dalam sheet (Alert.alert
                    tidak tampil di web preview, jadi hasil harus in-app). */}
                {execResult ? (
                  <View style={{
                    marginTop: 12, borderRadius: 12, padding: 12,
                    borderWidth: 1.5,
                    borderColor: execResult.ok ? GREEN : RED,
                    backgroundColor: execResult.ok
                      ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)",
                  }} testID="asi-exec-result">
                    <Text style={{
                      color: execResult.ok ? GREEN : RED,
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
