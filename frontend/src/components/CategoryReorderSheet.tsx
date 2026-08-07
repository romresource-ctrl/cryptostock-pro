/**
 * CategoryReorderSheet — bottom-sheet modal that lets the user drag the
 * dashboard category columns (Crypto, ETF, IDX, World Stocks, …) into
 * their preferred order and/or hide the ones they don't care about.
 *
 * Design notes:
 *   • Uses `react-native-draggable-flatlist` (long-press drag handle).
 *   • Order + hidden set are persisted in AsyncStorage under
 *     `dashboard:categoryOrder` and `dashboard:categoryHidden`.
 *   • The homepage reads back on mount via `useCategoryPrefs()`.
 *   • Sheet is intentionally full-screen height so the drag animation
 *     never collides with the bottom navigation.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import DraggableFlatList, {
  type RenderItemParams,
  ScaleDecorator,
} from "react-native-draggable-flatlist";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

// The categories are typed by `Market` in the API layer but we keep this
// component self-contained so it can be re-used across contexts.
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

// ---------------------------------------------------------------------------
// Public hook — read the current preference set and expose a setter that
// persists atomically.  Homepage uses this to derive its `orderedCategories`
// so the UI reflects the user's choices from the very first render.
// ---------------------------------------------------------------------------
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
        const [orderRaw, hiddenRaw] = await Promise.all([
          AsyncStorage.getItem(STORAGE_ORDER),
          AsyncStorage.getItem(STORAGE_HIDDEN),
        ]);
        let order: CategoryKey[] = DEFAULT_ORDER;
        if (orderRaw) {
          const parsed = JSON.parse(orderRaw) as string[];
          const valid = parsed.filter((k): k is CategoryKey =>
            (DEFAULT_ORDER as string[]).includes(k),
          );
          // Append any newly-added categories that the user hasn't seen yet
          // (forward compatibility — future patches might add e.g. "bonds").
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
      await Promise.all([
        AsyncStorage.setItem(STORAGE_ORDER, JSON.stringify(order)),
        AsyncStorage.setItem(STORAGE_HIDDEN, JSON.stringify([...hidden])),
      ]).catch(() => {});
    },
    [],
  );

  return [state, save];
}

// ---------------------------------------------------------------------------
// The sheet itself.
// ---------------------------------------------------------------------------
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

  // Reset drafts whenever the sheet re-opens so cancel is truly non-destructive.
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
    // Ensure at least ONE category stays visible to avoid an empty dashboard.
    const visibleCount = draftOrder.filter((k) => !draftHidden.has(k)).length;
    if (visibleCount === 0) return;
    onSave(draftOrder, draftHidden);
    onClose();
  }, [draftOrder, draftHidden, onSave, onClose]);

  const renderItem = useCallback(
    ({ item, drag, isActive }: RenderItemParams<CategoryKey>) => {
      const label = t(`category_${item}`);
      const hidden = draftHidden.has(item);
      return (
        <ScaleDecorator>
          <View
            style={[
              styles.row,
              {
                backgroundColor: isActive ? colors.surfaceAlt : colors.surface,
                borderColor: colors.border,
                opacity: hidden ? 0.55 : 1,
              },
            ]}
          >
            <TouchableOpacity
              onLongPress={drag}
              delayLongPress={120}
              disabled={isActive}
              activeOpacity={0.7}
              style={styles.dragHandle}
              testID={`reorder-drag-${item}`}
            >
              <Ionicons name="reorder-three" size={22} color={colors.textMuted} />
            </TouchableOpacity>
            <Ionicons
              name={CATEGORY_ICONS[item] as never}
              size={18}
              color={hidden ? colors.textMuted : colors.accentBlue}
              style={{ marginRight: 10 }}
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
        </ScaleDecorator>
      );
    },
    [colors, draftHidden, t, toggleHidden],
  );

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
            {/* Grabber */}
            <View style={[styles.grabber, { backgroundColor: colors.border }]} />

            {/* Header */}
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
              {t("reorder_hint") ||
                "Tekan & tahan ⋮ untuk menyeret. Toggle untuk menampilkan/menyembunyikan kolom di dashboard."}
            </Text>

            {/* Draggable list */}
            <View style={{ flex: 1 }}>
              <DraggableFlatList
                data={draftOrder}
                onDragEnd={({ data }) => setDraftOrder(data as CategoryKey[])}
                keyExtractor={(item) => item}
                renderItem={renderItem}
                contentContainerStyle={{ paddingHorizontal: 12, paddingBottom: 12 }}
              />
            </View>

            {/* Reset row */}
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
    width: 42,
    height: 4,
    borderRadius: 2,
    alignSelf: "center",
    marginBottom: 8,
    marginTop: 6,
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
    fontSize: 12,
    lineHeight: 17,
    paddingHorizontal: 16,
    marginBottom: 10,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 10,
    marginBottom: 8,
  },
  dragHandle: {
    paddingHorizontal: 4,
    paddingVertical: 4,
    marginRight: 4,
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
