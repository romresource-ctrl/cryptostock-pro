/**
 * CategoryReorderSheet — bottom-sheet modal that lets the user reorder
 * the dashboard category columns and toggle their visibility.
 *
 * v8.4.9 — Rewritten WITHOUT `react-native-draggable-flatlist` because
 * that library is incompatible with Reanimated 4 in Expo SDK 53+ (it
 * caused Android release builds to fail).  We now use a plain FlatList
 * with per-row **Up / Down** buttons for reordering — same functional
 * outcome, works on every RN version, and is friendlier for accessibility.
 */
import AsyncStorage from "@react-native-async-storage/async-storage"; // eslint-disable-line @typescript-eslint/no-unused-vars
import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

export type CategoryKey =
  | "crypto"
  | "etf"
  | "stock_id"
  | "stock_us"
  | "gold_silver"
  | "commodity"
  | "forex";

const DEFAULT_ORDER: CategoryKey[] = [
  "crypto", "etf", "stock_id", "stock_us", "gold_silver", "commodity", "forex",
];

const CATEGORY_ICONS: Record<CategoryKey, string> = {
  crypto: "logo-bitcoin",
  etf: "pie-chart",
  stock_id: "trending-up",
  stock_us: "globe",
  gold_silver: "medal",
  commodity: "cube",
  forex: "swap-horizontal",
};

const STORAGE_ORDER = "dashboard:categoryOrder";
const STORAGE_HIDDEN = "dashboard:categoryHidden";

export type CategoryPrefs = {
  order: CategoryKey[];
  hidden: Set<CategoryKey>;
  ready: boolean;
};

export function useCategoryPrefs(): [
  CategoryPrefs,
  (order: CategoryKey[], hidden: Set<CategoryKey>) => Promise<void>,
] {
  const [state, setState] = useState<CategoryPrefs>({
    order: DEFAULT_ORDER,
    hidden: new Set(),
    ready: false,
  });

  useEffect(() => {
    (async () => {
      try {
        const AS = (await import("@react-native-async-storage/async-storage")).default;
        const [orderRaw, hiddenRaw] = await Promise.all([
          AS.getItem(STORAGE_ORDER),
          AS.getItem(STORAGE_HIDDEN),
        ]);
        let order: CategoryKey[] = DEFAULT_ORDER;
        if (orderRaw) {
          const parsed = JSON.parse(orderRaw) as string[];
          const valid = parsed.filter((k): k is CategoryKey =>
            (DEFAULT_ORDER as string[]).includes(k),
          );
          const missing = DEFAULT_ORDER.filter((k) => !valid.includes(k));
          order = [...valid, ...missing];
        }
        const hidden = new Set<CategoryKey>(
          hiddenRaw
            ? (JSON.parse(hiddenRaw) as string[]).filter((k): k is CategoryKey =>
                (DEFAULT_ORDER as string[]).includes(k),
              )
            : [],
        );
        setState({ order, hidden, ready: true });
      } catch {
        setState({ order: DEFAULT_ORDER, hidden: new Set(), ready: true });
      }
    })();
  }, []);

  const save = useCallback(
    async (order: CategoryKey[], hidden: Set<CategoryKey>) => {
      setState({ order, hidden, ready: true });
      try {
        const AS = (await import("@react-native-async-storage/async-storage")).default;
        await Promise.all([
          AS.setItem(STORAGE_ORDER, JSON.stringify(order)),
          AS.setItem(STORAGE_HIDDEN, JSON.stringify([...hidden])),
        ]);
      } catch {
        /* silent */
      }
    },
    [],
  );

  return [state, save];
}

export default function CategoryReorderSheet({
  visible,
  onClose,
  initialOrder,
  initialHidden,
  onSave,
}: {
  visible: boolean;
  onClose: () => void;
  initialOrder: CategoryKey[];
  initialHidden: Set<CategoryKey>;
  onSave: (order: CategoryKey[], hidden: Set<CategoryKey>) => void;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [draftOrder, setDraftOrder] = useState<CategoryKey[]>(initialOrder);
  const [draftHidden, setDraftHidden] = useState<Set<CategoryKey>>(initialHidden);

  useEffect(() => {
    if (visible) {
      setDraftOrder(initialOrder);
      setDraftHidden(new Set(initialHidden));
    }
  }, [visible, initialOrder, initialHidden]);

  const anyChange = useMemo(() => {
    if (draftOrder.length !== initialOrder.length) return true;
    if (draftOrder.some((k, i) => k !== initialOrder[i])) return true;
    if (draftHidden.size !== initialHidden.size) return true;
    for (const k of draftHidden) if (!initialHidden.has(k)) return true;
    return false;
  }, [draftOrder, draftHidden, initialOrder, initialHidden]);

  const moveUp = useCallback((index: number) => {
    if (index <= 0) return;
    setDraftOrder((prev) => {
      const next = [...prev];
      [next[index - 1], next[index]] = [next[index], next[index - 1]];
      return next;
    });
  }, []);

  const moveDown = useCallback((index: number) => {
    setDraftOrder((prev) => {
      if (index >= prev.length - 1) return prev;
      const next = [...prev];
      [next[index + 1], next[index]] = [next[index], next[index + 1]];
      return next;
    });
  }, []);

  const toggleHidden = useCallback((key: CategoryKey) => {
    setDraftHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const resetToDefault = useCallback(() => {
    setDraftOrder(DEFAULT_ORDER);
    setDraftHidden(new Set());
  }, []);

  const handleSave = useCallback(() => {
    const visibleCount = draftOrder.filter((k) => !draftHidden.has(k)).length;
    if (visibleCount === 0) return;
    onSave(draftOrder, draftHidden);
    onClose();
  }, [draftOrder, draftHidden, onSave, onClose]);

  const renderItem = ({ item, index }: { item: CategoryKey; index: number }) => {
    const label = t(`category_${item}`);
    const hidden = draftHidden.has(item);
    const isFirst = index === 0;
    const isLast = index === draftOrder.length - 1;
    return (
      <View
        style={[
          styles.row,
          { backgroundColor: colors.surface, borderColor: colors.border, opacity: hidden ? 0.55 : 1 },
        ]}
      >
        <View style={styles.arrowCol}>
          <TouchableOpacity
            onPress={() => moveUp(index)}
            disabled={isFirst}
            hitSlop={6}
            testID={`reorder-up-${item}`}
            style={[styles.arrowBtn, { opacity: isFirst ? 0.3 : 1 }]}
          >
            <Ionicons name="chevron-up" size={16} color={colors.textPrimary} />
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => moveDown(index)}
            disabled={isLast}
            hitSlop={6}
            testID={`reorder-down-${item}`}
            style={[styles.arrowBtn, { opacity: isLast ? 0.3 : 1 }]}
          >
            <Ionicons name="chevron-down" size={16} color={colors.textPrimary} />
          </TouchableOpacity>
        </View>
        <Ionicons
          name={CATEGORY_ICONS[item] as never}
          size={18}
          color={hidden ? colors.textMuted : colors.accentBlue}
          style={{ marginRight: 10, marginLeft: 4 }}
        />
        <Text
          style={[styles.rowLabel, { color: hidden ? colors.textMuted : colors.textPrimary }]}
          numberOfLines={1}
        >
          {label}
        </Text>
        <Switch
          testID={`reorder-toggle-${item}`}
          value={!hidden}
          onValueChange={() => toggleHidden(item)}
          trackColor={{ false: colors.border, true: colors.accentUp + "80" }}
          thumbColor={hidden ? colors.textMuted : colors.accentUp}
        />
      </View>
    );
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={{ flex: 1 }} onPress={() => {}}>
          <SafeAreaView
            edges={["bottom"]}
            style={[
              styles.sheet,
              { backgroundColor: colors.surface, borderColor: colors.border },
            ]}
          >
            <View style={[styles.grabber, { backgroundColor: colors.border }]} />

            <View style={styles.header}>
              <TouchableOpacity onPress={onClose} testID="reorder-cancel">
                <Text style={[styles.headerBtn, { color: colors.textMuted }]}>
                  {t("common_cancel") || "Cancel"}
                </Text>
              </TouchableOpacity>
              <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>
                {t("reorder_title") || "Atur Urutan Kategori"}
              </Text>
              <TouchableOpacity
                onPress={handleSave}
                disabled={!anyChange}
                testID="reorder-save"
              >
                <Text
                  style={[
                    styles.headerBtn,
                    { color: anyChange ? colors.accentUp : colors.textMuted, fontWeight: "800" },
                  ]}
                >
                  {t("common_save") || "Save"}
                </Text>
              </TouchableOpacity>
            </View>

            <Text style={[styles.hint, { color: colors.textMuted }]}>
              {t("reorder_hint_arrows") ||
                "Gunakan tombol ↑ ↓ untuk memindahkan kategori. Toggle switch untuk menampilkan/menyembunyikan kolom di dashboard."}
            </Text>

            <View style={{ flex: 1 }}>
              <FlatList
                data={draftOrder}
                keyExtractor={(item) => item}
                renderItem={renderItem}
                contentContainerStyle={{ paddingHorizontal: 12, paddingBottom: 12 }}
              />
            </View>

            <TouchableOpacity
              onPress={resetToDefault}
              style={[styles.resetBtn, { borderTopColor: colors.border }]}
              testID="reorder-reset"
            >
              <Ionicons name="refresh" size={16} color={colors.accentBlue} />
              <Text style={[styles.resetTxt, { color: colors.accentBlue }]}>
                {t("reorder_reset") || "Kembalikan ke urutan bawaan"}
              </Text>
            </TouchableOpacity>
          </SafeAreaView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  sheet: {
    height: "80%",
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    paddingTop: 6,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOffset: { width: 0, height: -3 }, shadowOpacity: 0.2, shadowRadius: 8 },
      android: { elevation: 12 },
    }),
  },
  grabber: {
    width: 42, height: 4, borderRadius: 2,
    alignSelf: "center", marginBottom: 8, marginTop: 6,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 10,
  },
  headerBtn: { fontSize: 15 },
  headerTitle: { fontSize: 16, fontWeight: "800", flex: 1, textAlign: "center" },
  hint: {
    fontSize: 12, lineHeight: 17,
    paddingHorizontal: 16, marginBottom: 10,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 8,
    paddingRight: 10,
    paddingLeft: 4,
    marginBottom: 8,
  },
  arrowCol: {
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    marginRight: 4,
  },
  arrowBtn: {
    width: 26,
    height: 22,
    alignItems: "center",
    justifyContent: "center",
  },
  rowLabel: { flex: 1, fontSize: 15, fontWeight: "600" },
  resetBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderTopWidth: 1,
  },
  resetTxt: { fontSize: 13, fontWeight: "700" },
});
