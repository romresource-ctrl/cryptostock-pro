import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, type Profile } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type Tab = "crypto" | "stocks";

export default function ManageAssets() {
  const { colors } = useTheme();
  const router = useRouter();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [editing, setEditing] = useState<Profile | null>(null);
  const [editName, setEditName] = useState("");
  const [available, setAvailable] = useState<{ crypto: string[]; stocks: string[] }>({ crypto: [], stocks: [] });
  const [tab, setTab] = useState<Tab>("crypto");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [newProfileOpen, setNewProfileOpen] = useState(false);
  const [newProfileName, setNewProfileName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.profiles();
      setProfiles(r.profiles);
      setActiveId(r.active_id);
      setAvailable({ crypto: r.available_crypto, stocks: r.available_stocks });
      const cur = r.profiles.find((p) => p.id === r.active_id) ?? r.profiles[0];
      if (cur) {
        setEditing(cur);
        setEditName(cur.name);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectProfile = (p: Profile) => {
    setEditing(p);
    setEditName(p.name);
  };

  const toggleSymbol = (sym: string) => {
    if (!editing) return;
    if (tab === "crypto") {
      const has = editing.crypto.includes(sym);
      const next = has ? editing.crypto.filter((x) => x !== sym) : [...editing.crypto, sym];
      setEditing({ ...editing, crypto: next });
    } else {
      const has = editing.stocks.includes(sym);
      const next = has ? editing.stocks.filter((x) => x !== sym) : [...editing.stocks, sym];
      setEditing({ ...editing, stocks: next });
    }
  };

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await api.updateProfile(editing.id, {
        name: editName.trim() || editing.name,
        crypto: editing.crypto,
        stocks: editing.stocks,
      });
      await load();
    } finally {
      setSaving(false);
    }
  };

  const activate = async (id: string) => {
    await api.activateProfile(id);
    setActiveId(id);
  };

  const deleteProfile = async (id: string) => {
    if (profiles.length <= 1) return;
    try {
      await api.deleteProfile(id);
      await load();
    } catch (e) {
      // swallow; load() will resync
      void e;
    }
  };

  const createProfile = async () => {
    const name = newProfileName.trim() || "Profil Baru";
    try {
      await api.createProfile({ name, crypto: [], stocks: [] });
      setNewProfileOpen(false);
      setNewProfileName("");
      await load();
    } catch {
      setNewProfileOpen(false);
    }
  };

  const list = tab === "crypto" ? available.crypto : available.stocks;
  const selected = tab === "crypto" ? (editing?.crypto ?? []) : (editing?.stocks ?? []);

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
        <Text style={[styles.title, { color: colors.textPrimary }]}>Profil & Aset</Text>
        <TouchableOpacity
          onPress={save}
          disabled={saving || !editing}
          testID="save-profile-button"
          style={[styles.saveBtn, { backgroundColor: colors.accentBlue, opacity: !editing || saving ? 0.6 : 1 }]}
        >
          {saving ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.saveBtnText}>SIMPAN</Text>}
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={styles.loader}>
          <ActivityIndicator color={colors.accentBlue} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
          {/* Profile chips */}
          <View style={styles.section}>
            <View style={styles.sectionTitleRow}>
              <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Profil Watchlist</Text>
              <TouchableOpacity
                onPress={() => setNewProfileOpen(true)}
                testID="new-profile-button"
                style={[styles.miniBtn, { borderColor: colors.accentBlue }]}
              >
                <Ionicons name="add" size={14} color={colors.accentBlue} />
                <Text style={[styles.miniBtnText, { color: colors.accentBlue }]}>BARU</Text>
              </TouchableOpacity>
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsRow}>
              {profiles.map((p) => {
                const selectedEdit = editing?.id === p.id;
                const isActive = p.id === activeId;
                return (
                  <TouchableOpacity
                    key={p.id}
                    onPress={() => selectProfile(p)}
                    testID={`profile-chip-${p.id}`}
                    style={[
                      styles.profileChip,
                      {
                        backgroundColor: selectedEdit ? colors.accentBlue + "22" : colors.surface,
                        borderColor: selectedEdit ? colors.accentBlue : colors.border,
                      },
                    ]}
                  >
                    {isActive && <Ionicons name="bookmark" size={11} color={colors.accentUp} />}
                    <Text style={[styles.profileChipText, { color: selectedEdit ? colors.accentBlue : colors.textPrimary }]} numberOfLines={1}>
                      {p.name}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            {editing && (
              <View style={[styles.editorBox, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                <Text style={[styles.miniLabel, { color: colors.textMuted }]}>NAMA PROFIL</Text>
                <TextInput
                  value={editName}
                  onChangeText={setEditName}
                  testID="profile-name-input"
                  placeholder="contoh: Spot, Futures, Konservatif"
                  placeholderTextColor={colors.textMuted}
                  style={[styles.input, { color: colors.textPrimary, borderColor: colors.border }]}
                />
                <View style={styles.actionRow}>
                  <TouchableOpacity
                    onPress={() => activate(editing.id)}
                    disabled={editing.id === activeId}
                    testID="activate-profile-button"
                    style={[styles.actionBtn, {
                      backgroundColor: editing.id === activeId ? colors.surfaceAlt : colors.accentUp + "22",
                      borderColor: colors.accentUp,
                    }]}
                  >
                    <Ionicons name="bookmark" size={14} color={colors.accentUp} />
                    <Text style={[styles.actionBtnText, { color: colors.accentUp }]}>
                      {editing.id === activeId ? "AKTIF" : "JADIKAN AKTIF"}
                    </Text>
                  </TouchableOpacity>
                  {profiles.length > 1 && (
                    <TouchableOpacity
                      onPress={() => deleteProfile(editing.id)}
                      testID="delete-profile-button"
                      style={[styles.actionBtn, { backgroundColor: colors.accentDown + "22", borderColor: colors.accentDown }]}
                    >
                      <Ionicons name="trash-outline" size={14} color={colors.accentDown} />
                      <Text style={[styles.actionBtnText, { color: colors.accentDown }]}>HAPUS</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            )}
          </View>

          {/* Tabs */}
          <View style={[styles.tabs, { borderColor: colors.border }]}>
            <TouchableOpacity
              onPress={() => setTab("crypto")}
              testID="tab-crypto"
              style={[styles.tab, { borderBottomColor: tab === "crypto" ? colors.accentBlue : "transparent" }]}
            >
              <Text style={[styles.tabText, { color: tab === "crypto" ? colors.textPrimary : colors.textMuted }]}>
                CRYPTO • {editing?.crypto.length ?? 0}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setTab("stocks")}
              testID="tab-stocks"
              style={[styles.tab, { borderBottomColor: tab === "stocks" ? colors.accentBlue : "transparent" }]}
            >
              <Text style={[styles.tabText, { color: tab === "stocks" ? colors.textPrimary : colors.textMuted }]}>
                SAHAM • {editing?.stocks.length ?? 0}
              </Text>
            </TouchableOpacity>
          </View>

          <View style={styles.grid}>
            {list.map((sym) => {
              const isOn = selected.includes(sym);
              return (
                <TouchableOpacity
                  key={sym}
                  onPress={() => toggleSymbol(sym)}
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
          </View>
        </ScrollView>
      )}

      <Modal visible={newProfileOpen} transparent animationType="fade" onRequestClose={() => setNewProfileOpen(false)}>
        <View style={[styles.modalOverlay, { backgroundColor: colors.overlay }]}>
          <View style={[styles.modalBox, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Text style={[styles.modalTitle, { color: colors.textPrimary }]}>Profil Baru</Text>
            <Text style={[styles.miniLabel, { color: colors.textMuted, marginTop: 12 }]}>NAMA</Text>
            <TextInput
              value={newProfileName}
              onChangeText={setNewProfileName}
              testID="new-profile-name-input"
              placeholder="contoh: Day Trade BTC"
              placeholderTextColor={colors.textMuted}
              style={[styles.input, { color: colors.textPrimary, borderColor: colors.border }]}
              autoFocus
            />
            <View style={[styles.actionRow, { marginTop: 16 }]}>
              <TouchableOpacity
                onPress={() => setNewProfileOpen(false)}
                style={[styles.actionBtn, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}
              >
                <Text style={[styles.actionBtnText, { color: colors.textSecondary }]}>BATAL</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={createProfile}
                testID="confirm-new-profile-button"
                style={[styles.actionBtn, { backgroundColor: colors.accentBlue, borderColor: colors.accentBlue }]}
              >
                <Text style={[styles.actionBtnText, { color: "#fff" }]}>BUAT</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 12, gap: 12,
  },
  iconBtn: {
    width: 36, height: 36, borderRadius: 10,
    alignItems: "center", justifyContent: "center", borderWidth: 1,
  },
  title: { fontSize: 18, fontWeight: "700", flex: 1 },
  saveBtn: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 8 },
  saveBtnText: { color: "#fff", fontSize: 12, fontWeight: "700", letterSpacing: 0.8 },
  loader: { flex: 1, alignItems: "center", justifyContent: "center" },
  section: { paddingHorizontal: 16, paddingTop: 4 },
  sectionTitleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sectionTitle: { fontSize: 13, fontWeight: "700", letterSpacing: 0.6 },
  miniBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, borderWidth: 1,
  },
  miniBtnText: { fontSize: 10, fontWeight: "700", letterSpacing: 0.5 },
  chipsRow: { gap: 8, paddingVertical: 10, paddingRight: 4 },
  profileChip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 18,
    borderWidth: 1, flexShrink: 0, flexDirection: "row", alignItems: "center", gap: 4,
  },
  profileChipText: { fontSize: 12, fontWeight: "600", maxWidth: 160 },
  editorBox: { padding: 12, borderRadius: 10, borderWidth: 1, marginTop: 4 },
  miniLabel: { fontSize: 10, letterSpacing: 0.6, marginBottom: 4 },
  input: {
    height: 40, borderRadius: 8, borderWidth: 1, paddingHorizontal: 10, fontSize: 14,
  },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  actionBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 8, borderWidth: 1,
  },
  actionBtnText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.5 },
  tabs: { flexDirection: "row", borderBottomWidth: 1, marginTop: 16 },
  tab: { flex: 1, alignItems: "center", paddingVertical: 12, borderBottomWidth: 2 },
  tabText: { fontSize: 12, fontWeight: "700", letterSpacing: 0.6 },
  grid: { flexDirection: "row", flexWrap: "wrap", padding: 12, gap: 8 },
  tile: {
    width: "31%", paddingHorizontal: 10, paddingVertical: 14, borderRadius: 10, borderWidth: 1,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  tileSym: { fontSize: 13, fontWeight: "700", letterSpacing: 0.4 },
  modalOverlay: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  modalBox: { width: "100%", maxWidth: 360, borderRadius: 12, borderWidth: 1, padding: 16 },
  modalTitle: { fontSize: 16, fontWeight: "700" },
});
