import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { api } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type Tab = "crypto" | "stocks";

export default function ManageAssets() {
  const { colors } = useTheme();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("crypto");
  const [active, setActive] = useState<{ crypto: string[]; stocks: string[] }>({ crypto: [], stocks: [] });
  const [available, setAvailable] = useState<{ crypto: string[]; stocks: string[] }>({ crypto: [], stocks: [] });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const w = await api.watchlist();
      setActive({ crypto: w.crypto, stocks: w.stocks });
      setAvailable({ crypto: w.available_crypto, stocks: w.available_stocks });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (sym: string) => {
    if (tab === "crypto") {
      setActive((p) => ({
        ...p,
        crypto: p.crypto.includes(sym) ? p.crypto.filter((x) => x !== sym) : [...p.crypto, sym],
      }));
    } else {
      setActive((p) => ({
        ...p,
        stocks: p.stocks.includes(sym) ? p.stocks.filter((x) => x !== sym) : [...p.stocks, sym],
      }));
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.updateWatchlist({ crypto: active.crypto, stocks: active.stocks });
      router.back();
    } finally {
      setSaving(false);
    }
  };

  const list = tab === "crypto" ? available.crypto : available.stocks;
  const selected = tab === "crypto" ? active.crypto : active.stocks;

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          testID="manage-back-button"
          style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={[styles.title, { color: colors.textPrimary }]}>Kelola Aset</Text>
        <TouchableOpacity
          onPress={save}
          disabled={saving}
          testID="save-watchlist-button"
          style={[styles.saveBtn, { backgroundColor: colors.accentBlue, opacity: saving ? 0.6 : 1 }]}
        >
          {saving ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <Text style={styles.saveBtnText}>SIMPAN</Text>
          )}
        </TouchableOpacity>
      </View>

      <View style={[styles.tabs, { borderColor: colors.border }]}>
        <TouchableOpacity
          onPress={() => setTab("crypto")}
          testID="tab-crypto"
          style={[
            styles.tab,
            { borderBottomColor: tab === "crypto" ? colors.accentBlue : "transparent" },
          ]}
        >
          <Text style={[styles.tabText, { color: tab === "crypto" ? colors.textPrimary : colors.textMuted }]}>
            CRYPTO • {active.crypto.length}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setTab("stocks")}
          testID="tab-stocks"
          style={[
            styles.tab,
            { borderBottomColor: tab === "stocks" ? colors.accentBlue : "transparent" },
          ]}
        >
          <Text style={[styles.tabText, { color: tab === "stocks" ? colors.textPrimary : colors.textMuted }]}>
            SAHAM • {active.stocks.length}
          </Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.loader}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.grid}>
          {list.map((sym) => {
            const isOn = selected.includes(sym);
            return (
              <TouchableOpacity
                key={sym}
                onPress={() => toggle(sym)}
                testID={`asset-toggle-${sym}`}
                style={[
                  styles.tile,
                  {
                    backgroundColor: isOn ? colors.accentBlue + "22" : colors.surface,
                    borderColor: isOn ? colors.accentBlue : colors.border,
                  },
                ]}
              >
                <Text style={[styles.tileSym, { color: isOn ? colors.accentBlue : colors.textPrimary }]}>{sym}</Text>
                <Ionicons
                  name={isOn ? "checkmark-circle" : "add-circle-outline"}
                  size={18}
                  color={isOn ? colors.accentBlue : colors.textMuted}
                />
              </TouchableOpacity>
            );
          })}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 12,
  },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  title: { fontSize: 18, fontWeight: "700", flex: 1 },
  saveBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8 },
  saveBtnText: { color: "#fff", fontSize: 12, fontWeight: "700", letterSpacing: 0.8 },
  tabs: { flexDirection: "row", borderBottomWidth: 1 },
  tab: { flex: 1, alignItems: "center", paddingVertical: 12, borderBottomWidth: 2 },
  tabText: { fontSize: 12, fontWeight: "700", letterSpacing: 0.6 },
  loader: { flex: 1, alignItems: "center", justifyContent: "center" },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    padding: 12,
    gap: 8,
  },
  tile: {
    width: "31%",
    paddingHorizontal: 10,
    paddingVertical: 14,
    borderRadius: 10,
    borderWidth: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  tileSym: { fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
});
