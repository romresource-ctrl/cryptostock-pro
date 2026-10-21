// v10.2.38 — Pilih ukuran posisi: Risk per Trade (%) ATAU Margin per Trade ($).
import React, { useEffect, useState } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import MarginInputRow from "@/src/components/MarginInputRow";

type Props = {
  riskPct: number;
  marginUsd: number;
  onRisk: (v: number) => void;
  onMargin: (v: number) => void;
  riskLabel: string;
  marginLabel: string;
  accent: string;
  colors: any;
  testPrefix: string;
};

export default function SizingSelector({ riskPct, marginUsd, onRisk, onMargin, riskLabel, marginLabel, accent, colors, testPrefix }: Props) {
  const [mode, setMode] = useState<"risk" | "margin">(marginUsd > 0 ? "margin" : "risk");
  useEffect(() => { if (marginUsd > 0) setMode("margin"); }, [marginUsd]);
  const pick = (m: "risk" | "margin") => {
    setMode(m);
    if (m === "risk" && marginUsd > 0) onMargin(0); // margin 0 → backend pakai Risk %
  };
  return (
    <View>
      <View style={s.chips}>
        {(["risk", "margin"] as const).map((m) => {
          const act = mode === m;
          return (
            <TouchableOpacity key={m} onPress={() => pick(m)} testID={`${testPrefix}-mode-${m}`}
              style={[s.chip, { borderColor: act ? accent : colors.border, backgroundColor: act ? accent : colors.surface }]}>
              <Text style={{ color: act ? "#0B0E11" : colors.textPrimary, fontWeight: "900", fontSize: 12 }}>
                {act ? "✓ " : ""}{m === "risk" ? riskLabel : marginLabel}
              </Text>
            </TouchableOpacity>
          );
        })}
      </View>
      {mode === "margin" ? (
        <MarginInputRow label={marginLabel} value={marginUsd} onCommit={onMargin}
          colors={colors} testID={`${testPrefix}-margin-usdt`} />
      ) : (
        <View style={[s.row, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Text style={[s.label, { color: colors.textPrimary }]}>{riskLabel}</Text>
          <TouchableOpacity testID={`${testPrefix}-risk-dec`} onPress={() => onRisk(Math.max(1, riskPct - 1))}
            style={[s.btn, { borderColor: colors.border }]}>
            <Text style={{ color: colors.textPrimary, fontSize: 18, fontWeight: "900" }}>−</Text>
          </TouchableOpacity>
          <Text style={[s.val, { color: accent }]}>{riskPct}%</Text>
          <TouchableOpacity testID={`${testPrefix}-risk-inc`} onPress={() => onRisk(Math.min(30, riskPct + 1))}
            style={[s.btn, { borderColor: colors.border }]}>
            <Text style={{ color: colors.textPrimary, fontSize: 18, fontWeight: "900" }}>+</Text>
          </TouchableOpacity>
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  chips: { flexDirection: "row", gap: 8, marginBottom: 8 },
  chip: { flex: 1, minHeight: 44, borderWidth: 1.5, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  row: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderRadius: 12,
         paddingHorizontal: 12, paddingVertical: 8, marginBottom: 10, gap: 10 },
  label: { fontSize: 14, fontWeight: "800", flex: 1 },
  btn: { width: 44, height: 44, borderWidth: 1, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  val: { fontSize: 16, fontWeight: "900", minWidth: 44, textAlign: "center" },
});
