// v10.2.37 — Margin per Trade ($), editable (menggantikan Risk per Trade %).
import React, { useEffect, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";

type Props = {
  label: string;
  value: number;
  onCommit: (v: number) => void;
  colors: any;
  testID?: string;
};

export default function MarginInputRow({ label, value, onCommit, colors, testID }: Props) {
  const [txt, setTxt] = useState(value > 0 ? String(value) : "");
  useEffect(() => { setTxt(value > 0 ? String(value) : ""); }, [value]);
  const commit = () => {
    const n = Math.max(0, Math.round((parseFloat(txt.replace(",", ".")) || 0) * 100) / 100);
    if (n !== value) onCommit(n);
    setTxt(n > 0 ? String(n) : "");
  };
  return (
    <View style={[s.row, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Text style={[s.label, { color: colors.textPrimary }]}>{label}</Text>
      <View style={[s.inputWrap, { borderColor: colors.border }]}>
        <Text style={{ color: colors.textMuted, fontWeight: "900" }}>$</Text>
        <TextInput
          testID={testID}
          value={txt}
          onChangeText={setTxt}
          onBlur={commit}
          onSubmitEditing={commit}
          keyboardType="decimal-pad"
          returnKeyType="done"
          placeholder="100"
          placeholderTextColor={colors.textMuted}
          style={[s.input, { color: colors.textPrimary }]}
        />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between",
         borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8, marginBottom: 10 },
  label: { fontSize: 14, fontWeight: "800", flex: 1 },
  inputWrap: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderRadius: 10,
               paddingHorizontal: 10, minHeight: 44, minWidth: 120 },
  input: { flex: 1, fontSize: 16, fontWeight: "900", paddingVertical: 6, paddingHorizontal: 6, textAlign: "right" },
});
