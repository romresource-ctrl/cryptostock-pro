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
const DEFAULT_RISK_PCT = "1.0";
const DEFAULT_BALANCE = "1000";

type Props = {
  entryPrice: number | null | undefined;
  stopLoss: number | null | undefined;
  symbol: string;
  action?: string; // BUY / SELL / HOLD / LONG / SHORT
  quoteLabel?: string; // e.g. "USD" for BTC/USDT, "IDR" for BBCA
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
}: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const [balance, setBalance] = useState<string>(DEFAULT_BALANCE);
  const [riskPct, setRiskPct] = useState<string>(DEFAULT_RISK_PCT);

  // Load persisted values on mount so returning users don't re-enter.
  useEffect(() => {
    (async () => {
      try {
        const [b, r] = await Promise.all([
          AsyncStorage.getItem(STORAGE_BALANCE),
          AsyncStorage.getItem(STORAGE_RISK_PCT),
        ]);
        if (b) setBalance(b);
        if (r) setRiskPct(r);
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
    const b = parseFloat(balance.replace(/,/g, "")) || 0;
    const r = parseFloat(riskPct) || 0;
    const e = Number(entryPrice) || 0;
    const s = Number(stopLoss) || 0;
    if (b <= 0 || r <= 0 || e <= 0 || s <= 0 || e === s) return null;
    const riskAmount = b * (r / 100);
    const distance = Math.abs(e - s);
    const distancePct = (distance / e) * 100;
    const positionSize = riskAmount / distance;
    const positionValue = positionSize * e;
    // Leverage estimate: how many × the account balance the trade uses.
    const leverage = positionValue / b;
    return { riskAmount, distance, distancePct, positionSize, positionValue, leverage };
  }, [balance, riskPct, entryPrice, stopLoss]);

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

          {/* User inputs — Balance + Risk % */}
          <View style={styles.inputRow}>
            <View style={{ flex: 1, marginRight: 6 }}>
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
            <View style={{ flex: 1, marginLeft: 6 }}>
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
                  {formatMoney(calc.positionValue)} {quoteLabel}
                </Text>
              </View>
              <View style={styles.resultRow}>
                <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                  {t("pos_calc_max_loss")}
                </Text>
                <Text style={[styles.resultValue, { color: colors.accentDown }]}>
                  −{formatMoney(calc.riskAmount)} {quoteLabel}
                  <Text style={{ fontSize: 10, color: colors.textMuted }}>
                    {"  "}({calc.distancePct.toFixed(2)}%)
                  </Text>
                </Text>
              </View>
              {calc.leverage > 1 ? (
                <View style={styles.resultRow}>
                  <Text style={[styles.resultLabel, { color: colors.textMuted }]}>
                    {t("pos_calc_leverage")}
                  </Text>
                  <Text
                    style={[
                      styles.resultValue,
                      { color: calc.leverage > 3 ? colors.accentDown : colors.textPrimary },
                    ]}
                  >
                    {calc.leverage.toFixed(2)}×
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
  inputRow: { flexDirection: "row", marginTop: 10 },
  inputLabel: { fontSize: 10, letterSpacing: 0.4, textTransform: "uppercase", marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 14,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
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
  emptyHint: { fontSize: 11, marginTop: 10, fontStyle: "italic" },
});
