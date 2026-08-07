/**
 * /alerts — full-screen list of the user's price alerts.
 *
 * Each row: symbol · direction · target · current price · enabled toggle
 *           · delete button.  Tapping a row opens the asset detail page.
 *
 * Users reach this screen from the news tab's "Price Alerts" quick link,
 * from the notification tap-through, or from a header button on the
 * dashboard (added in a follow-up).
 */
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React from "react";
import {
  FlatList,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "@/src/i18n/I18nContext";
import { useAlerts, type AlertRow } from "@/src/lib/alerts";
import { useTheme } from "@/src/theme/ThemeContext";

export default function AlertsScreen() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const router = useRouter();
  const { alerts, ready, update, remove } = useAlerts();

  const renderItem = ({ item }: { item: AlertRow }) => {
    const dirColor = item.direction === "above" ? colors.accentUp : colors.accentDown;
    const isTriggered = !!item.triggeredAt;
    return (
      <TouchableOpacity
        onPress={() => router.push(`/asset/${item.market}/${item.symbol}` as never)}
        style={[
          styles.row,
          { backgroundColor: colors.surface, borderColor: colors.border, opacity: item.enabled ? 1 : 0.6 },
        ]}
        testID={`alert-row-${item.id}`}
      >
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={[styles.symbol, { color: colors.textPrimary }]}>
              {item.symbol.toUpperCase()}
            </Text>
            <Text style={[styles.market, { color: colors.textMuted }]}>· {item.market}</Text>
            {isTriggered ? (
              <Text style={[styles.triggeredPill, { color: colors.accentUp, borderColor: colors.accentUp }]}>
                ● {t("alert_triggered") || "Terpicu"}
              </Text>
            ) : null}
          </View>
          <Text style={[styles.desc, { color: colors.textMuted }]} numberOfLines={2}>
            {item.direction === "above"
              ? (t("alert_desc_above") || "Naik di atas")
              : (t("alert_desc_below") || "Turun di bawah")}{" "}
            <Text style={{ color: dirColor, fontWeight: "800" }}>
              {item.target.toLocaleString("en-US", { maximumFractionDigits: 6 })}
            </Text>
            {item.note ? <Text>{"  · "}{item.note}</Text> : null}
          </Text>
        </View>
        <Switch
          value={item.enabled}
          onValueChange={(v) => update(item.id, { enabled: v, triggeredAt: v ? undefined : item.triggeredAt })}
          trackColor={{ false: colors.border, true: colors.accentUp + "80" }}
          thumbColor={item.enabled ? colors.accentUp : colors.textMuted}
        />
        <TouchableOpacity
          onPress={() => remove(item.id)}
          hitSlop={10}
          style={{ marginLeft: 8, padding: 6 }}
          testID={`alert-delete-${item.id}`}
        >
          <Ionicons name="trash-outline" size={18} color={colors.accentDown} />
        </TouchableOpacity>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]}>
      <View style={styles.header}>
        <TouchableOpacity
          onPress={() => router.back()}
          testID="alerts-back-button"
          style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
        >
          <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={[styles.title, { color: colors.textPrimary }]}>
          🔔 {t("alerts_screen_title") || "Alarm Harga"}
        </Text>
        <View style={{ width: 36 }} />
      </View>

      {!ready ? null : alerts.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="notifications-off-outline" size={48} color={colors.textMuted} />
          <Text style={[styles.emptyTitle, { color: colors.textPrimary }]}>
            {t("alerts_empty_title") || "Belum ada alarm harga"}
          </Text>
          <Text style={[styles.emptyBody, { color: colors.textMuted }]}>
            {t("alerts_empty_body") ||
              "Buka detail aset lalu ketuk 🔔 di sebelah tombol back untuk membuat alarm harga."}
          </Text>
        </View>
      ) : (
        <FlatList
          data={alerts}
          keyExtractor={(a) => a.id}
          renderItem={renderItem}
          contentContainerStyle={{ padding: 12, gap: 8 }}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 10,
  },
  iconBtn: { width: 36, height: 36, borderRadius: 10, alignItems: "center", justifyContent: "center", borderWidth: 1 },
  title: { fontSize: 15, fontWeight: "800" },
  row: {
    flexDirection: "row",
    alignItems: "center",
    padding: 12,
    borderRadius: 12,
    borderWidth: 1,
  },
  symbol: { fontSize: 15, fontWeight: "900" },
  market: { fontSize: 11 },
  desc: { fontSize: 12, marginTop: 3, lineHeight: 16 },
  triggeredPill: { fontSize: 9.5, fontWeight: "800", borderWidth: 1, borderRadius: 6, paddingHorizontal: 5, paddingVertical: 1 },
  empty: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 32,
    gap: 8,
  },
  emptyTitle: { fontSize: 16, fontWeight: "700", marginTop: 12 },
  emptyBody: { fontSize: 12.5, textAlign: "center", lineHeight: 18 },
});
