import React, { useEffect, useMemo, useState } from "react";
import { Alert, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import ReanimatedSwipeable from "react-native-gesture-handler/ReanimatedSwipeable";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { usePremiumAccess } from "@/src/lib/usePremiumAccess";
import { useTraderProfile } from "@/src/lib/useTraderProfile";
import PremiumLocked from "@/src/components/PremiumLocked";
import AISuggestionsSheet from "@/src/components/AISuggestionsSheet";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  api, formatPrice, type AsiBotConfig, type AsiCredential,
  type AsiPnl, type AsiTradeResp,
} from "@/src/lib/api";

const GOLD = "#4ADE80"; // v9.4.1 — primary ASI-Bot accent (hijau muda)
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
  const { profile: traderProfile, explicit: traderExplicit } = useTraderProfile();
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
  // v9.9.13 — Hapus kartu history dari Recent Trades (per-row ✕).
  const [deletingIds, setDeletingIds] = useState<Record<string, boolean>>({});
  // v9.8.1 — AISuggestionsSheet popup (daftar aset hasil scan, dibuka
  // dari tombol PICK A SIGNAL). Sheet ini punya AsiTradeSheet internal.
  const [suggestOpen, setSuggestOpen] = useState(false);

  useEffect(() => {
    (async () => {
      const did = await getDeviceId();
      setDeviceId(did);
      refresh(did);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // v9.7.6 — Saat SALAH SATU bot RUNNING (semi atau full), refresh daftar
  // trade berkala agar PnL & status terbuka/tertutup tetap live.
  useEffect(() => {
    const anyRunning = !!(bot.semi_enabled || bot.full_enabled || bot.enabled);
    if (!anyRunning || !deviceId) return;
    const id = setInterval(() => refresh(), 20_000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.semi_enabled, bot.full_enabled, bot.enabled, deviceId]);

  // v9.9.13 — Mark price REALTIME untuk posisi open: polling batch 2 detik
  // (backend cache 1 detik via proxy SG). Angka harga di samping symbol
  // berubah live, dan frame kartu hijau/merah mengikuti PnL live.
  const [livePx, setLivePx] = useState<Record<string, number>>({});
  const openSymsKey = trades
    .filter((t2) => String(t2.status || "").toLowerCase() === "open")
    .map((t2) => t2.symbol)
    .filter((v, i, a) => a.indexOf(v) === i)
    .join(",");
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
          m[k.replace(/USDT$/, "")] = v;
        });
        setLivePx(m);
      } catch { /* pertahankan harga terakhir */ }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [openSymsKey]);

  // v9.8.0 — Sinkronkan Trader Profile global ke bot.profile saat berubah.
  // Full-Auto scanner akan membaca field ini di scheduler → sinyal yang
  // dieksekusi otomatis mengikuti profil yang user pilih di header.
  useEffect(() => {
    if (!deviceId || !credsLoaded) return;
    const target: "scalper" | "day" | "swing" | "confluence" =
      traderExplicit && (traderProfile === "scalper" || traderProfile === "day" || traderProfile === "swing")
        ? traderProfile
        : "confluence";
    if (bot.profile === target) return;
    saveBot({ profile: target }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [traderProfile, traderExplicit, deviceId, credsLoaded]);

  const refresh = async (did?: string) => {
    const id = did || deviceId; if (!id) return;
    try {
      const c = await api.asi.listCredentials(id);
      setCreds(c.items);
      const b = await api.asi.getBot(id);
      if (b.exists) setBot({ ...bot, ...b });
      const p = await api.asi.pnl(id); setPnl(p);
      const t2 = await api.asi.listTrades(id, 20); setTrades(t2.items.slice(0, 20));
      // v9.9.9 — saldo available kedua jaringan, di-refresh bersama PnL.
      try {
        const b = await api.asi.balance(id, bot.exchange);
        setBalance({ demo: b.demo, real: b.real });
      } catch { /* saldo opsional — jangan ganggu refresh utama */ }
    } catch {}
    finally { setCredsLoaded(true); }
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
    // v9.7.4 — Functional setState: always merge from the LATEST state so
    // rapid successive taps (toggle + risk +/-) can never overwrite each
    // other with a stale snapshot (this silently re-disabled the bot).
    return new Promise<void>((resolve) => {
      setBot((prev) => {
        const merged = { ...prev, ...next };
        api.asi.saveBot(deviceId, merged).catch(() => {});
        return merged;
      });
      resolve();
    });
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
      : { full_enabled: false, enabled: !!bot.semi_enabled });
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

  // v9.9.13 — Swipe-to-delete untuk kartu HISTORY (closed/expired/
  // cancelled/layered). Posisi open/pending tidak bisa dihapus —
  // harus CLOSE/cancel dulu (ditegakkan juga di backend).
  const deleteOneTrade = async (trade: AsiTradeResp) => {
    const tid = (trade as any)._id as string | undefined;
    if (!tid || !deviceId) return;
    const lockKey = tid;
    if (deletingIds[lockKey]) return;
    setDeletingIds((prev) => ({ ...prev, [lockKey]: true }));
    try {
      await api.asi.deleteTrade(deviceId, tid);
      // Hapus langsung dari state lokal agar kartu hilang instan.
      setTrades((list) => list.filter((x) => (x as any)._id !== tid));
    } catch (e: any) {
      Alert.alert(t("asi_close_failed"), String(e?.message || e));
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
          colors={colors}
          t={t}
        />
        {(bot.full_enabled) ? (
          <Text style={{ color: colors.textMuted, fontSize: 10.5, marginTop: 6,
                         lineHeight: 15, textAlign: "center" }}>
            {t("asi_stop_hint")}
          </Text>
        ) : null}

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

        {/* Parameters */}
        <SectionHeader title={t("asi_sec_risk")} />
        <ParamRow label={t("asi_risk_per_trade")} value={`${bot.risk_pct}%`}
                  onDec={() => saveBot({ risk_pct: Math.max(1, bot.risk_pct - 1) })}
                  onInc={() => saveBot({ risk_pct: Math.min(30, bot.risk_pct + 1) })}
                  colors={colors} testID="asi-risk" />
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
            const active = (bot.tp_count ?? 3) === n;
            const accent = bot.mode === "full" ? ORANGE : GOLD;
            const label = n === 1 ? t("asi_tp_1_label") : n === 2 ? t("asi_tp_2_label") : t("asi_tp_3_label");
            return (
              <TouchableOpacity
                key={n}
                onPress={() => saveBot({ tp_count: n })}
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
        {bot.mode === "full" ? (
          <ParamRow label={t("asi_max_trades_day")} value={`${bot.max_trades_per_day}`}
                    onDec={() => saveBot({ max_trades_per_day: Math.max(1, bot.max_trades_per_day - 1) })}
                    onInc={() => saveBot({ max_trades_per_day: Math.min(50, bot.max_trades_per_day + 1) })}
                    colors={colors} testID="asi-maxtrade" />
        ) : null}
        <ParamRow label={t("asi_daily_loss_limit")}
                  value={(bot.daily_loss_limit_usdt ?? 0) === 0 ? "OFF" : `$${bot.daily_loss_limit_usdt}`}
                  onDec={() => saveBot({ daily_loss_limit_usdt: Math.max(0, (bot.daily_loss_limit_usdt ?? 0) - 10) })}
                  onInc={() => saveBot({ daily_loss_limit_usdt: Math.min(100000, (bot.daily_loss_limit_usdt ?? 0) + 10) })}
                  colors={colors} testID="asi-dailyloss" />
        <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: -4, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_daily_loss_hint")}
        </Text>

        <ParamRow
          label={t("asi_trailing_label")}
          value={(bot.trailing_callback_rate ?? 0) === 0 ? "OFF" : `${(bot.trailing_callback_rate ?? 0).toFixed(1)}%`}
          onDec={() => saveBot({ trailing_callback_rate: Math.max(0, Math.round(((bot.trailing_callback_rate ?? 0) - 0.5) * 10) / 10) })}
          onInc={() => saveBot({ trailing_callback_rate: Math.min(10, Math.round(((bot.trailing_callback_rate ?? 0) + 0.5) * 10) / 10) })}
          colors={colors} testID="asi-trailing"
        />
        <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: -4, marginBottom: 8, lineHeight: 16 }}>
          {t("asi_trailing_hint")}
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
            { key: "real", label: "REAL", chipColor: GREEN, data: balance.real },
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
        {/* v9.9.2 — Banner REPAIR hanya untuk trade LAMA (pre-v9.9.2) yang
            masih berstatus soft, ATAU trade baru di mana bracket_live=false
            (user mungkin cancel manual algo order di Binance app). Trade
            baru v9.9.2 selalu hard-verified atau tidak tersimpan. */}
        {trades.some((tr) => String(tr.status).toLowerCase() === "open"
          && ((tr.bracket_live === false)
              || (tr.bracket_type === "soft" && tr.bracket_live !== true))) ? (
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
            {(tradesExpanded ? trades : trades.slice(0, 10)).map((tr, i) => {
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
              const rowBody = (
                <View style={[s.leaderRow, { backgroundColor: colors.surface, borderColor }]}>
                {/* v10.0.1 — Baris paling atas: badge DEMO/REAL (REAL
                    kuning) + tanggal/jam eksekusi — dipindah dari baris
                    badge agar baris utama tidak sempit. */}
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                    backgroundColor: tr.testnet ? LIGHT_BLUE : YELLOW,
                  }}>
                    <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 9, letterSpacing: 0.4 }}>
                      {tr.testnet ? t("asi_demo_badge") : "REAL"}
                    </Text>
                  </View>
                  <Text style={{ fontSize: 9, fontWeight: "700", color: colors.textMuted }}>
                    {(() => {
                      const iso = String((tr as any).created_at || (tr as any).updated_at || "");
                      if (!iso) return "";
                      const d = new Date(iso);
                      if (isNaN(d.getTime())) return "";
                      const pad = (n: number) => String(n).padStart(2, "0");
                      return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} · ${pad(d.getHours())}:${pad(d.getMinutes())}`;
                    })()}
                  </Text>
                </View>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  {/* v10.0.1 — MODE badge: Semi=🦾 (hijau), Full=🤖 (biru muda) */}
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                    backgroundColor: modeBadge === "full" ? LIGHT_BLUE : GOLD,
                  }}>
                    <Text style={{ fontSize: 11, fontWeight: "900" }}>
                      {modeBadge === "full" ? "🤖" : "🦾"}
                    </Text>
                  </View>
                  {/* v10.0.1 — Chip cara masuk: L (kuning) / M (ungu),
                      disingkat agar tidak bentrok dengan badge LIMIT
                      status. Tetap disembunyikan saat pending (status
                      sudah menyampaikan LIMIT). */}
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
                  {/* v9.9.4 — Badge layering (berapa kali averaging). */}
                  {(tr as any).layer_count && (tr as any).layer_count > 1 ? (
                    <View style={{
                      paddingHorizontal: 5, paddingVertical: 2, borderRadius: 4,
                      backgroundColor: GOLD,
                    }}>
                      <Text style={{ color: "#0B0E11", fontWeight: "900", fontSize: 8.5 }}>
                        {t("ats_layer_badge").replace("{n}", String((tr as any).layer_count))}
                      </Text>
                    </View>
                  ) : null}
                  {/* OPEN / CLOSED / LIMIT badge */}
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
                    backgroundColor: isOpen ? GREEN : isPending ? YELLOW : colors.border,
                  }}>
                    <Text style={{ color: isOpen ? ACCENT_TEXT : isPending ? "#0B0E11" : colors.textMuted, fontWeight: "900", fontSize: 9 }}>
                      {isOpen ? t("asi_status_active") : isPending ? t("asi_status_pending") : "CLOSED"}
                    </Text>
                  </View>
                  <Text style={{ color: tr.side === "BUY" ? GREEN : RED, fontWeight: "900", width: 44, fontSize: 12 }}>
                    {/* v9.8.6 — Futures convention: tampilkan LONG/SHORT,
                        bukan BUY/SELL (permintaan user). */}
                    {tr.side === "BUY" ? "LONG" : "SHORT"}
                  </Text>
                  {/* v9.9.10 — Peringatan hanya bila bracket BENAR-BENAR
                      tidak terverifikasi di exchange (algo & legacy).
                      Proteksi legacy/manual (sl_order_id null tapi order
                      ada di Binance) tidak lagi ditandai ⚠️. */}
                  {isOpen && ((tr.bracket_live === false)
                      || (tr.bracket_type === "soft" && tr.bracket_live !== true)) ? (
                    <TouchableOpacity
                      onPress={() => Alert.alert(
                        t("asi_soft_warn_title"),
                        tr.soft_bracket_reason || t("asi_soft_warn_body"),
                      )}
                      testID={`asi-soft-${tr.symbol}`}
                    >
                      <Text style={{ fontSize: 13 }}>⚠️</Text>
                    </TouchableOpacity>
                  ) : null}
                  <Text numberOfLines={1} style={{ color: colors.textPrimary, fontWeight: "700", flexShrink: 1 }}>{tr.symbol}</Text>
                  {/* v9.9.13 — Mark price REALTIME di samping symbol (posisi
                      open): polling 2 detik, hijau/merah vs entry. */}
                  {isOpen ? (() => {
                    const lp = livePx[symBase] ?? (tr as any).mark_price ?? null;
                    if (!lp || !tr.entry_price) return null;
                    const profitSide = tr.side === "BUY" ? lp >= tr.entry_price : lp <= tr.entry_price;
                    return (
                      <Text style={{ color: profitSide ? GREEN : RED, fontWeight: "900", fontSize: 11 }}>
                        {formatPrice(lp, "crypto")}
                      </Text>
                    );
                  })() : null}
                  <View style={{ flex: 1 }} />
                  <View style={{ alignItems: "flex-end", flexShrink: 0 }}>
                    <Text style={{ color: pos ? GREEN : RED, fontWeight: "800" }}>
                      {pos ? "+" : ""}${dispPnl.toFixed(2)}
                    </Text>
                    <Text style={{ color: pos ? GREEN : RED, fontSize: 10, fontWeight: "700" }}>
                      {pos ? "+" : ""}{pct.toFixed(1)}%
                    </Text>
                  </View>
                </View>
                {/* v9.9.2 — Baris verifikasi proteksi untuk posisi OPEN.
                    Tampilkan SL, TP, margin mode AKTUAL + status native.
                    "Native OK" hanya hijau bila bracket_type=hard DAN
                    (bracket_live tidak false). */}
                {/* v9.9.7 — Row 2: [DEMO/REAL chip] SL · TP · MARGIN · LEVx.
                    Susunan IDENTIK untuk demo & real: slot chip selalu ada
                    (DEMO biru utk testnet, REAL hijau utk mainnet) sehingga
                    semua baris sejajar rapi ke bawah. Leverage diperjelas
                    hijau tebal (permintaan user). */}
                {/* v9.9.13 — Baris detail + tombol CLOSE juga tampil untuk
                    LIMIT PENDING (CLOSE = batalkan order limit). */}
                {isOpen || isPending ? (
                  <View style={{ marginTop: 6, gap: 2 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Text style={{ color: colors.textMuted, fontSize: 10, lineHeight: 15, flex: 1 }} numberOfLines={2}>
                        {/* v9.9.9 — Margin USDT wajib tampil di tiap posisi */}
                        <Text style={{ color: YELLOW, fontWeight: "900" }}>
                          {`Margin $${(tr.margin_usdt ?? ((tr.entry_price && tr.qty && tr.leverage) ? tr.entry_price * tr.qty / tr.leverage : 0)).toFixed(2)}`}
                        </Text>
                        {"  ·  "}
                        {/* v9.9.13 — Entry Price di antara Margin dan SL
                            (permintaan user, menyusul baris closed). */}
                        <Text style={{ color: colors.textPrimary, fontWeight: "800" }}>
                          Entry {formatPrice(tr.entry_price, "crypto")}
                        </Text>
                        {"  ·  "}
                        <Text style={{ color: RED, fontWeight: "800" }}>SL {formatPrice(tr.stop_loss, "crypto")}</Text>
                        {"  ·  "}
                        <Text style={{ color: GREEN, fontWeight: "800" }}>
                          TP {(tr.take_profits || []).map((x) => formatPrice(x, "crypto")).join(" / ") || "—"}
                        </Text>
                        {"  ·  "}
                        <Text style={{
                          color: ((tr.actual_margin_mode || tr.margin_mode) === "cross") ? PURPLE : TEAL,
                          fontWeight: "800",
                        }}>
                          {String(tr.actual_margin_mode || tr.margin_mode || "isolated").toUpperCase()}
                        </Text>
                        {"  ·  "}
                        <Text style={{ color: GREEN, fontWeight: "900", fontSize: 11 }}>
                          {`${(tr as any).actual_leverage ?? tr.leverage ?? "?"}x`}
                        </Text>
                      </Text>
                      {/* v9.9.8 — CLOSE dipindah ke baris 2, persis di bawah
                          angka PnL (kanan), dijamin di dalam frame. */}
                      {/* v9.9.13 — LIMIT pending: tombol = CANCEL (emas)
                          membatalkan order antri; setelah posisi OPEN
                          berubah menjadi CLOSE (merah) menutup posisi. */}
                      <TouchableOpacity
                        onPress={() => closeOneTrade(tr)}
                        disabled={isClosing}
                        style={{
                          paddingHorizontal: 12, paddingVertical: 7, borderRadius: 8,
                          backgroundColor: isClosing ? colors.border : isPending ? GOLD : RED,
                          minWidth: 60, alignItems: "center", flexShrink: 0,
                          alignSelf: "center",
                        }}
                        testID={`asi-close-${tr.symbol}`}
                      >
                        <Text style={{ color: isPending ? "#0B0E11" : "#fff", fontWeight: "900", fontSize: 10, letterSpacing: 0.4 }}>
                          {isClosing
                            ? (isPending ? t("asi_cancelling") : t("asi_recent_closing"))
                            : (isPending ? t("asi_btn_cancel") : t("asi_recent_close"))}
                        </Text>
                      </TouchableOpacity>
                    </View>
                    {/* v9.9.13 — Baris ketiga SATU BARIS: status proteksi
                        (kiri) + formula singkat (kanan, tidak keluar
                        bingkai kartu). */}
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Text numberOfLines={1} style={{
                        fontSize: 10, fontWeight: "800", flexShrink: 0,
                        color: isPending ? GOLD : (tr.bracket_type === "hard" && tr.bracket_live !== false) ? GREEN : ORANGE,
                      }}>
                        {isPending
                          ? t("asi_pending_line")
                          : (tr.bracket_type === "hard" && tr.bracket_live !== false)
                            ? `✓ SL/TP on ${{ binance: "Binance", bybit: "Bybit", okx: "OKX", bitget: "Bitget" }[String(tr.exchange || "").toLowerCase()] || "Exchange"}`
                            : t("asi_bracket_soft_short")}
                      </Text>
                      <View style={{ flex: 1 }} />
                      {((tr as any).profile || (tr as any).formula_tag) ? (
                        <Text numberOfLines={1} style={{ fontSize: 9, fontWeight: "700", color: colors.textMuted, flexShrink: 1, textAlign: "right" }}>
                          {`⚙️ ${t("asi_formula_label")}: ${formulaLines(t, (tr as any).profile, (tr as any).formula_tag)[0]}`}
                        </Text>
                      ) : null}
                    </View>
                  </View>
                ) : (
                  /* v10.0.1 — Trade CLOSED: badge DEMO/REAL sudah dipindah
                     ke row atas; baris ini cukup detail numerik. */
                  <View style={{ marginTop: 6, gap: 2 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Text style={{ color: colors.textMuted, fontSize: 10, lineHeight: 15, flex: 1 }} numberOfLines={2}>
                        <Text style={{ color: YELLOW, fontWeight: "900" }}>
                          {`Margin $${(tr.margin_usdt ?? ((tr.entry_price && tr.qty && tr.leverage) ? tr.entry_price * tr.qty / tr.leverage : 0)).toFixed(2)}`}
                        </Text>
                        {"  ·  "}
                        <Text style={{ color: colors.textPrimary, fontWeight: "800" }}>
                          Entry {formatPrice(tr.entry_price, "crypto")}
                        </Text>
                        {"  ·  "}
                        <Text style={{ color: RED, fontWeight: "800" }}>SL {formatPrice(tr.stop_loss, "crypto")}</Text>
                        {"  ·  "}
                        <Text style={{ color: GREEN, fontWeight: "800" }}>
                          TP {(tr.take_profits || []).map((x) => formatPrice(x, "crypto")).join(" / ") || "—"}
                        </Text>
                        {"  ·  "}
                        <Text style={{
                          color: ((tr.actual_margin_mode || tr.margin_mode) === "cross") ? PURPLE : TEAL,
                          fontWeight: "800",
                        }}>
                          {String(tr.actual_margin_mode || tr.margin_mode || "isolated").toUpperCase()}
                        </Text>
                        {"  ·  "}
                        <Text style={{ color: GREEN, fontWeight: "900", fontSize: 11 }}>
                          {`${(tr as any).actual_leverage ?? tr.leverage ?? "?"}x`}
                        </Text>
                      </Text>
                    </View>
                    {/* v10.0.1 — "Closed on {Exchange}" + Formula sejajar
                        satu baris di bawah detail (bukan dua baris lagi). */}
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Text numberOfLines={1} style={{ fontSize: 10, fontWeight: "800", flexShrink: 0 }}>
                        <Text style={{ color: pos ? GREEN : RED }}>
                          {t("asi_closed_on")} {({ binance: "Binance", bybit: "Bybit", okx: "OKX", bitget: "Bitget" } as Record<string, string>)[tr.exchange || "binance"] || tr.exchange}
                        </Text>
                        <Text style={{ color: colors.textMuted }}>
                          {tr.close_reason ? `  ·  ${String(tr.close_reason).toUpperCase()}` : ""}
                        </Text>
                      </Text>
                      <View style={{ flex: 1 }} />
                      {((tr as any).profile || (tr as any).formula_tag) ? (
                        <Text numberOfLines={1} style={{ fontSize: 9, fontWeight: "700", color: colors.textMuted, flexShrink: 1, textAlign: "right" }}>
                          {`⚙️ ${t("asi_formula_label")}: ${formulaLines(t, (tr as any).profile, (tr as any).formula_tag)[0]}`}
                        </Text>
                      ) : null}
                    </View>
                  </View>
                )}
                </View>
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
            })}
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
function StatusCard({ kind, running, onPrimary, onStop, colors, t }: {
  kind: "semi" | "full";
  running: boolean;
  onPrimary: () => void;
  onStop: () => void;
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
          <TouchableOpacity
            onPress={onPrimary}
            disabled={running}
            style={[s.bigBtn, { backgroundColor: running ? colors.border : PINK }]}
            testID="asi-start-full"
          >
            <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.5 }}>{t("asi_run_bot")}</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onStop}
            disabled={!running}
            style={[s.bigBtn, { backgroundColor: !running ? colors.border : LIGHT_BLUE }]}
            testID="asi-stop-full"
          >
            <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.5 }}>{t("asi_stop_bot")}</Text>
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
