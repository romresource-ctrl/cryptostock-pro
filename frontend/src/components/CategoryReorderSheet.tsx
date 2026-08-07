/**
 * CategoryReorderSheet — bottom-sheet modal with **native drag-to-reorder**.
 *
 * v8.5.1 — Custom PanResponder-based drag (no external library, so it
 * works with any Reanimated version — including Reanimated 4 in Expo
 * SDK 53+ where `react-native-draggable-flatlist@4.x` breaks the build).
 *
 * How it works
 *   • Each row has a fixed height (`ROW_H`).  Long-press the ☰ handle
 *     to grab a row → the row lifts (elevation + border) and follows
 *     the finger.
 *   • As the finger's y moves, we compute a target index by dividing
 *     by `ROW_H` and clamp it into [0, N-1].  When the target changes
 *     we swap the row into the new slot in real time.
 *   • On release, the drag state resets and the final order is saved.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Modal,
  PanResponder,
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

// Each row is padding 8 top + content 40 + padding 8 bottom + margin 8 = 64px.
const ROW_H = 64;

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

  // Live drag state — the row currently being dragged + its animated Y
  // offset so we can visually follow the finger while adjacent rows
  // slide out of the way.
  const [draggingKey, setDraggingKey] = useState<CategoryKey | null>(null);
  const dragY = useRef(new Animated.Value(0)).current;

  // Ref to always read the latest draftOrder inside the PanResponder
  // callbacks (avoids stale-closure bugs when we swap during a drag).
  const draftOrderRef = useRef<CategoryKey[]>(initialOrder);
  useEffect(() => {
    draftOrderRef.current = draftOrder;
  }, [draftOrder]);

  useEffect(() => {
    if (visible) {
      setDraftOrder(initialOrder);
      setDraftHidden(new Set(initialHidden));
      draftOrderRef.current = initialOrder;
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
    const visibleCount = draftOrder.filter((k) => !draftHidden.has(k)).length;
    if (visibleCount === 0) return;
    onSave(draftOrder, draftHidden);
    onClose();
  }, [draftOrder, draftHidden, onSave, onClose]);

  // Build a PanResponder per category so the ☰ handle is the sole drag
  // trigger.  We grab a snapshot of the initial index at grant time, then
  // continuously compute the target slot as the finger moves.
  const makePan = useCallback(
    (key: CategoryKey) =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: (_evt, gs) => Math.abs(gs.dy) > 2,
        onPanResponderGrant: () => {
          setDraggingKey(key);
          dragY.setValue(0);
        },
        onPanResponderMove: (_evt, gs) => {
          dragY.setValue(gs.dy);
          const current = draftOrderRef.current;
          const fromIdx = current.indexOf(key);
          if (fromIdx < 0) return;
          // Number of slots we've moved.  Positive dy = down, so we
          // ADD to the index.  Clamp to [0, N-1].
          const delta = Math.round(gs.dy / ROW_H);
          if (delta === 0) return;
          const toIdx = Math.max(
            0,
            Math.min(current.length - 1, fromIdx + delta),
          );
          if (toIdx === fromIdx) return;
          const next = current.slice();
          next.splice(fromIdx, 1);
          next.splice(toIdx, 0, key);
          draftOrderRef.current = next;
          setDraftOrder(next);
          // Reset the animated offset to the *new* relative position so
          // the row stays under the finger (the swap already moved it
          // by ROW_H visually).
          dragY.setValue(gs.dy - (toIdx - fromIdx) * ROW_H);
        },
        onPanResponderRelease: () => {
          Animated.spring(dragY, {
            toValue: 0,
            useNativeDriver: true,
            speed: 30,
            bounciness: 4,
          }).start(() => {
            setDraggingKey(null);
          });
        },
        onPanResponderTerminate: () => {
          dragY.setValue(0);
          setDraggingKey(null);
        },
      }),
    [dragY],
  );

  // Memoise responders per key so each row keeps the same instance.
  const panResponders = useMemo(() => {
    const map = new Map<CategoryKey, ReturnType<typeof PanResponder.create>>();
    for (const k of DEFAULT_ORDER) map.set(k, makePan(k));
    return map;
  }, [makePan]);

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
                    {
                      color: anyChange ? colors.accentUp : colors.textMuted,
                      fontWeight: "800",
                    },
                  ]}
                >
                  {t("common_save") || "Save"}
                </Text>
              </TouchableOpacity>
            </View>

            <Text style={[styles.hint, { color: colors.textMuted }]}>
              {t("reorder_hint") ||
                "Tekan & tahan ⋮ lalu geser ke atas/bawah untuk memindahkan kategori. Toggle switch untuk menampilkan/menyembunyikan kolom."}
            </Text>

            <View style={{ flex: 1, paddingHorizontal: 12, paddingBottom: 12 }}>
              {draftOrder.map((item) => {
                const label = t(`category_${item}`);
                const hidden = draftHidden.has(item);
                const isActive = draggingKey === item;
                const pan = panResponders.get(item)!;
                return (
                  <Animated.View
                    key={item}
                    style={[
                      styles.row,
                      {
                        backgroundColor: isActive ? colors.surfaceAlt : colors.surface,
                        borderColor: isActive ? colors.accentBlue : colors.border,
                        borderWidth: isActive ? 2 : 1,
                        opacity: hidden ? 0.55 : 1,
                        // Only translate the dragged row; others stay put
                        // and slide into their new slot via re-render.
                        transform: isActive ? [{ translateY: dragY }] : [],
                        // Lift the dragged row visually so it appears
                        // over its neighbours during drag.
                        zIndex: isActive ? 10 : 1,
                        elevation: isActive ? 6 : 0,
                      },
                    ]}
                  >
                    <View {...pan.panHandlers} style={styles.dragHandle} testID={`reorder-drag-${item}`}>
                      <Ionicons name="reorder-three" size={22} color={colors.textMuted} />
                    </View>
                    <Ionicons
                      name={CATEGORY_ICONS[item] as never}
                      size={18}
                      color={hidden ? colors.textMuted : colors.accentBlue}
                      style={{ marginRight: 10 }}
                    />
                    <Text
                      style={[
                        styles.rowLabel,
                        { color: hidden ? colors.textMuted : colors.textPrimary },
                      ]}
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
                  </Animated.View>
                );
              })}
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
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
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
  grabber: { width: 42, height: 4, borderRadius: 2, alignSelf: "center", marginBottom: 8, marginTop: 6 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 10,
  },
  headerBtn: { fontSize: 15 },
  headerTitle: { fontSize: 16, fontWeight: "800", flex: 1, textAlign: "center" },
  hint: { fontSize: 12, lineHeight: 17, paddingHorizontal: 16, marginBottom: 10 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 12,
    paddingVertical: 8,
    paddingHorizontal: 10,
    marginBottom: 8,
    height: 56, // fits inside ROW_H (56 + 8 margin = 64)
  },
  dragHandle: {
    paddingHorizontal: 6,
    paddingVertical: 6,
    marginRight: 6,
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
