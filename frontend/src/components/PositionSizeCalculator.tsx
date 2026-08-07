/**
 * PositionSizeCalculator — inline card on the signal detail page (v8.3.9).
 *
 * Formula (industry-standard fixed-fractional risk model):
 *   Risk Amount   = Account Balance × (Risk % / 100)
 *   Distance      = |Entry Price − Stop Loss|
 *   Position Size = Risk Amount / Distance          (units of the asset)
 *   Position Value= Position Size × Entry Price     (capital deployed)
 *
 * User inputs Account Balance + Risk %. Entry Price and Stop Loss are
 * PRE-POPULATED from the signal (`entryPrice` / `stopLoss` props) so the
 * user only needs to type two numbers to get a position recommendation.
 *
 * Balance & Risk % persist to AsyncStorage so returning users skip data
 * entry entirely — critical for the "use it every single time" goal.
 */
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

const STORAGE_BALANCE = "pos_calc_balance";
const STORAGE_RISK_PCT = "pos_calc_risk_pct";
const STORAGE_LEVERAGE = "pos_calc_leverage";
const DEFAULT_RISK_PCT = "1.0";
const DEFAULT_BALANCE = "1000";
const DEFAULT_LEVERAGE = "1";

type Props = {
  entryPrice: number | null | undefined;
  stopLoss: number | null | undefined;
  symbol: string;
  action?: string; // BUY / SELL / HOLD / LONG / SHORT
  quoteLabel?: string; // e.g. "USD" for BTC/USDT, "IDR" for BBCA
  // v8.4.0 — Optional TP passthrough so the calculator can show a full
  // projected P/L at the recommended take-profit level. Users trading
  // real capital want to see "if TP hits I make $X" alongside "if SL
  // hits I lose $Y" — both anchored to their actual leverage.
  takeProfit?: number | null;
};

function formatMoney(n: number, decimals = 2): string {
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatUnits(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "—";
  // Show more decimals for tiny units (crypto sub-satoshi), fewer for whole shares.
  if (n >= 100) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (n >= 1) return n.toLocaleString("en-US", { maximumFractionDigits: 4 });
  return n.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

export default function PositionSizeCalculator({
  entryPrice,
  stopLoss,
  symbol,
  action,
  quoteLabel = "USD",
  takeProfit,
}: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const [balance, setBalance] = useState<string>(DEFAULT_BALANCE);
  const [riskPct, setRiskPct] = useState<string>(DEFAULT_RISK_PCT);
  const [leverage, setLeverage] = useState<string>(DEFAULT_LEVERAGE);
  // v8.5.2 — Track focus state so the stepper border highlights when
  // the user taps the input (visual affordance that it's editable).
  const [leverageFocused, setLeverageFocused] = useState(false);

  // Load persisted values on mount so returning users don't re-enter.
  useEffect(() => {
    (async () => {
      try {
        const [b, r, l] = await Promise.all([
          AsyncStorage.getItem(STORAGE_BALANCE),
          AsyncStorage.getItem(STORAGE_RISK_PCT),
          AsyncStorage.getItem(STORAGE_LEVERAGE),
        ]);
        if (b) setBalance(b);
        if (r) setRiskPct(r);
        if (l) setLeverage(l);
      } catch {
        /* fall back to defaults */
      }
    })();
  }, []);

  // Persist as user types (debounced via onEndEditing to reduce writes).
  const persist = async (key: string, value: string) => {
    try {
      await AsyncStorage.setItem(key, value);
    } catch {
      /* ignore */
    }
  };

  const calc = useMemo(() => {
    // v8.5.4 — Binance-style Initial Margin sizing (replaces old risk-based)
    // • Initial Margin (input `balance`) = margin locked for the position
    // • Notional = margin × leverage (this is the full position exposure)
    // • Position size (units) = notional / entry price
    // • Max Loss = position size × |entry − SL|  (may exceed margin →
    //   liquidation on real exchange, we surface a warning to the user)
    // • Projected Profit = position size × |TP − entry|
    // • Risk % row is kept as informational only ("% of margin lost @ SL").
    const margin = parseFloat(balance.replace(/,/g, "")) || 0;
    const r = parseFloat(riskPct) || 0;
    const e = Number(entryPrice) || 0;
    const s = Number(stopLoss) || 0;
    const lev = Math.max(1, parseFloat(leverage) || 1);
    if (margin <= 0 || e <= 0 || s <= 0 || e === s) return null;

    const notional = margin * lev;                    // Position Value
    const positionSize = notional / e;                 // in base-asset units
    const marginRequired = margin;                     // by definition = margin
    const marginPctOfBalance = 100;                    // 100% of the margin is used
    const distance = Math.abs(e - s);
    const distancePct = (distance / e) * 100;
    const maxLoss = positionSize * distance;           // dollar loss if SL hits
    const maxLossPctOfMargin = (maxLoss / margin) * 100;
    const liquidationRisk = maxLoss >= margin;         // over-leveraged warning

    // Info-only "target risk" row — how big margin should be if the user
    // truly wanted to lose only `r%` of margin at SL (helps de-leverage).
    const targetRiskAmount = margin * (r / 100);
    const suggestedLev =
      distance > 0 && r > 0
        ? Math.max(1, Math.floor(targetRiskAmount / (positionSize * distance) * lev))
        : lev;

    const tp = Number(takeProfit) || 0;
    // v8.5.6 — Direction inference. If the signal explicitly says BUY/LONG
    // or SELL/SHORT, honor it. Otherwise (HOLD / NEUTRAL / unset), infer
    // direction from the relative position of TP vs Entry so users still
    // see a projected profit whenever TP is defined and valid.
    const actUp = (action || "").toUpperCase();
    const explicitBuy = actUp === "BUY" || actUp === "LONG";
    const explicitSell = actUp === "SELL" || actUp === "SHORT";
    const impliedBuy = !explicitBuy && !explicitSell && tp > e;
    const impliedSell = !explicitBuy && !explicitSell && tp > 0 && tp < e;
    const isBuy = explicitBuy || impliedBuy;
    const isSell = explicitSell || impliedSell;
    const tpValid =
      tp > 0 && tp !== e && ((isBuy && tp > e) || (isSell && tp < e));
    const projectedProfit = tpValid ? Math.abs(tp - e) * positionSize : null;
    const rrRatio =
      tpValid && maxLoss > 0 ? projectedProfit! / maxLoss : null;

    return {
      riskAmount: maxLoss,        // used by existing UI row
      distance,
      distancePct,
      positionSize,
      notional,
      marginRequired,
      marginPctOfBalance,
      leverageX: lev,
      projectedProfit,
      rrRatio,
      maxLossPctOfMargin,
      liquidationRisk,
      suggestedLev,
    };
  }, [balance, riskPct, leverage, entryPrice, stopLoss, takeProfit, action]);

  // Hide entirely when there is no valid signal to base the calc on
  // (e.g. HOLD signal returned entry == stop_loss). Users can still
  // manually override entry/SL in a future iteration.
  const missingSignal =
    !entryPrice || !stopLoss || entryPrice === stopLoss;

  return (
    <View
      testID="position-size-calc"
      style={[
        styles.card,
        { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      {/* Header — tap to expand/collapse */}
      <TouchableOpacity
        onPress={() => setCollapsed((v) => !v)}
        style={styles.header}
        activeOpacity={0.75}
      >
        <Ionicons name="calculator-outline" size={18} color={colors.accentBlue} />
        <View style={{ flex: 1, marginLeft: 8 }}>
          <Text style={[styles.title, { color: colors.textPrimary }]}>
            {t("pos_calc_title")}
          </Text>
          <Text style={[styles.subtitle, { color: colors.textMuted }]}>
            {t("pos_calc_subtitle")}
          </Text>
        </View>
        <Ionicons
          name={collapsed ? "chevron-down" : "chevron-up"}
          size={18}
          color={colors.textMuted}
        />
      </TouchableOpacity>

      {collapsed ? null : missingSignal ? (
        <Text style={[styles.emptyHint, { color: colors.textMuted }]}>
          {t("pos_calc_missing_signal")}
        </Text>
      ) : (
        <>
          {/* Pre-filled from signal */}
          <View style={styles.readonlyRow}>
            <View style={styles.readonlyCell}>
              <Text style={[styles.readonlyLabel, { color: colors.textMuted }]}>
                {t("pos_calc_entry")}
              </Text>
              <Text style={[styles.readonlyValue, { color: colors.textPrimary }]}>
                {formatMoney(entryPrice as number, entryPrice! < 1 ? 6 : 2)}
              </Text>
            </View>
            <View style={styles.readonlyCell}>
              <Text style={[styles.readonlyLabel, { color: colors.textMuted }]}>
                {t("pos_calc_sl")}
              </Text>
              <Text style={[styles.readonlyValue, { color: colors.accentDown }]}>
                {formatMoney(stopLoss as number, stopLoss! < 1 ? 6 : 2)}
              </Text>
            </View>
          </View>

          {/* User inputs — Balance, Risk %, Leverage */}
          <View style={styles.inputRow}>
            <View style={{ flex: 1, marginRight: 4 }}>
              <Text style={[styles.inputLabel, { color: colors.textMuted }]}>
                {t("pos_calc_balance")} ({quoteLabel})
              </Text>
              <TextInput
                testID="pos-calc-balance-input"
                value={balance}
                onChangeText={setBalance}
                onEndEditing={() => persist(STORAGE_BALANCE, balance)}
                keyboardType="decimal-pad"
                placeholder="1000"
                placeholderTextColor={colors.textMuted}
                style={[
                  styles.input,
                  { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background },
                ]}
              />
            </View>
            <View style={{ flex: 1, marginHorizontal: 4 }}>
              <Text style={[styles.inputLabel, { color: colors.textMuted }]}>
                {t("pos_calc_risk_pct")}
              </Text>
              <TextInput
                testID="pos-calc-risk-input"
                value={riskPct}
                onChangeText={setRiskPct}
                onEndEditing={() => persist(STORAGE_RISK_PCT, riskPct)}
                keyboardType="decimal-pad"
                placeholder="1.0"
                placeholderTextColor={colors.textMuted}
                style={[
                  styles.input,
                  { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background },
                ]}
              />
            </View>
            {/* v8.5.2 — Leverage input dengan stepper +/−.  Tombol tap
                supaya user tidak wajib buka keyboard (paling sering user
                cuma mau naik/turun 1 step). Input tetap editable manual
                untuk value non-standard (2.5×, 12×, dst). Selalu terlihat
                pada layar meskipun leverage=1 (spot). */}
            <View style={{ flex: 1.2, marginLeft: 4 }}>
              <Text style={[styles.inputLabel, { color: colors.textMuted }]}>
                {t("pos_calc_leverage_input")}
              </Text>
              <View
                style={[
                  styles.stepperWrap,
                  {
                    borderColor: leverageFocused ? colors.accentBlue : colors.border,
                    backgroundColor: colors.background,
                  },
                ]}
              >
                <TouchableOpacity
                  onPress={() => {
                    const cur = Math.max(1, parseFloat(leverage) || 1);
                    const next = Math.max(1, Math.floor(cur - 1));
                    const val = String(next);
                    setLeverage(val);
                    void persist(STORAGE_LEVERAGE, val);
                  }}
                  hitSlop={6}
                  testID="pos-calc-leverage-minus"
                  style={styles.stepperBtn}
                >
                  <Ionicons name="remove" size={14} color={colors.textPrimary} />
                </TouchableOpacity>
                <TextInput
                  testID="pos-calc-leverage-input"
                  value={leverage}
                  onChangeText={setLeverage}
                  onFocus={() => setLeverageFocused(true)}
                  onBlur={() => {
                    setLeverageFocused(false);
                    void persist(STORAGE_LEVERAGE, leverage);
                  }}
                  keyboardType="decimal-pad"
                  placeholder="1"
                  placeholderTextColor={colors.textMuted}
                  style={[styles.stepperInput, { color: colors.textPrimary }]}
                />
                <TouchableOpacity
                  onPress={() => {
                    const cur = Math.max(1, parseFloat(leverage) || 1);
                    const next = Math.min(125, Math.floor(cur + 1));
                    const val = String(next);
                    setLeverage(val);
                    void persist(STORAGE_LEVERAGE, val);
                  }}
                  hitSlop={6}
                  testID="pos-calc-leverage-plus"
                  style={styles.stepperBtn}
                >
                  <Ionicons name="add" size={14} color={colors.textPrimary} />
                </TouchableOpacity>
              </View>
            </View>
          </View>

          {/* Result */}
          {calc ? (
            <View
              style={[
                styles.resultBox,
                { backgroundColor: colors.accentUp + "12", borderColor: colors.accentUp },
              ]}
            >
              <View style={styles.resultRow}>
                <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                  {t("pos_calc_position_size")}
                </Text>
                <Text style={[styles.resultValue, { color: colors.textPrimary }]}>
                  {formatUnits(calc.positionSize)} {symbol.toUpperCase()}
                </Text>
              </View>
              <View style={styles.resultRow}>
                <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                  {t("pos_calc_position_value")}
                </Text>
                <Text style={[styles.resultValue, { color: colors.textPrimary }]}>
                  {formatMoney(calc.notional)} {quoteLabel}
                </Text>
              </View>
              {/* v8.5.2 — Margin Dibutuhkan SELALU tampil, bahkan saat
                  leverage=1. Ini penting: user harus tahu berapa margin
                  yang dibutuhkan supaya efek dari input Leverage jelas.
                  Pada 1× margin = notional (100% dari nilai posisi). */}
              <View style={styles.resultRow}>
                <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                  {t("pos_calc_margin_required")}
                  <Text style={{ fontSize: 10, color: colors.textMuted }}>
                    {"  "}({calc.leverageX.toFixed(calc.leverageX % 1 === 0 ? 0 : 1)}×)
                  </Text>
                </Text>
                <Text style={[styles.resultValue, { color: colors.textPrimary }]}>
                  {formatMoney(calc.marginRequired)} {quoteLabel}
                  <Text style={{ fontSize: 10, color: colors.textMuted }}>
                    {"  "}({calc.marginPctOfBalance.toFixed(1)}% {t("pos_calc_of_balance")})
                  </Text>
                </Text>
              </View>
              <View style={styles.resultRow}>
                <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                  {t("pos_calc_max_loss")}
                </Text>
                <Text style={[styles.resultValue, { color: colors.accentDown }]}>
                  −{formatMoney(calc.riskAmount)} {quoteLabel}
                  <Text style={{ fontSize: 10, color: colors.textMuted }}>
                    {"  "}({calc.maxLossPctOfMargin.toFixed(1)}% {t("pos_calc_of_balance")})
                  </Text>
                </Text>
              </View>
              {/* v8.5.4 — Liquidation warning: if max loss at SL >= margin,
                  the position gets liquidated before SL. Warn the user. */}
              {calc.liquidationRisk ? (
                <View style={[styles.liqWarn, { borderColor: colors.accentDown, backgroundColor: colors.accentDown + "18" }]}>
                  <Ionicons name="warning" size={14} color={colors.accentDown} />
                  <Text style={[styles.liqWarnTxt, { color: colors.accentDown }]}>
                    {t("pos_calc_liquidation") ||
                      `Peringatan: Max Loss (${calc.maxLossPctOfMargin.toFixed(0)}%) melebihi margin! Posisi akan likuidasi sebelum SL. Kurangi leverage ke ~${calc.suggestedLev}× untuk aman.`}
                  </Text>
                </View>
              ) : null}
              {calc.projectedProfit != null ? (
                <View style={styles.resultRow}>
                  <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                    {t("pos_calc_projected_profit")}
                  </Text>
                  <Text style={[styles.resultValue, { color: colors.accentUp }]}>
                    +{formatMoney(calc.projectedProfit)} {quoteLabel}
                    {calc.rrRatio != null ? (
                      <Text style={{ fontSize: 10, color: colors.textMuted }}>
                        {"  "}(R/R 1:{calc.rrRatio.toFixed(2)})
                      </Text>
                    ) : null}
                  </Text>
                </View>
              ) : null}
              <Text style={[styles.resultHint, { color: colors.textMuted }]}>
                {t("pos_calc_hint")}
              </Text>
            </View>
          ) : null}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginTop: 12,
  },
  header: { flexDirection: "row", alignItems: "center" },
  title: { fontSize: 13, fontWeight: "800" },
  subtitle: { fontSize: 10.5, marginTop: 1 },
  readonlyRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  readonlyCell: { flex: 1 },
  readonlyLabel: { fontSize: 10, letterSpacing: 0.4, textTransform: "uppercase" },
  readonlyValue: { fontSize: 14, fontWeight: "900", marginTop: 2, fontVariant: ["tabular-nums"] },
  inputRow: { flexDirection: "row", marginTop: 10, alignItems: "flex-end" },
  inputLabel: {
    fontSize: 10,
    letterSpacing: 0.4,
    textTransform: "uppercase",
    marginBottom: 4,
    // v8.5.1 — Reserve 2 lines so 3-word labels ("SALDO AKUN (IDR)") don't
    // push their input below the shorter labels ("RISK %", "LEVERAGE (×)").
    minHeight: 26,
    lineHeight: 12,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 14,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
  },
  // v8.5.2 — Stepper composite for Leverage input (−|input|+).
  stepperWrap: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    height: 38,
    overflow: "hidden",
  },
  stepperBtn: {
    width: 28,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
  },
  stepperInput: {
    flex: 1,
    textAlign: "center",
    fontSize: 14,
    fontWeight: "800",
    fontVariant: ["tabular-nums"],
    paddingHorizontal: 2,
    paddingVertical: 0,
    height: 36,
  },
  resultBox: {
    borderWidth: 1,
    borderRadius: 10,
    padding: 10,
    marginTop: 10,
  },
  resultRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  resultLabel: { fontSize: 11, fontWeight: "700" },
  resultValue: { fontSize: 13, fontWeight: "900", fontVariant: ["tabular-nums"] },
  resultHint: { fontSize: 10, marginTop: 4, fontStyle: "italic", lineHeight: 14 },
  liqWarn: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
    marginVertical: 6,
  },
  liqWarnTxt: {
    flex: 1,
    fontSize: 11,
    fontWeight: "700",
    lineHeight: 15,
  },
  emptyHint: { fontSize: 11, marginTop: 10, fontStyle: "italic" },
});
