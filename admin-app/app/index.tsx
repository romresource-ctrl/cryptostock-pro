import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { fetchLoggedUsers, type LoggedUser } from "@/lib/adminApi";
import { generateUnlockCode } from "@/lib/unlockCode";

type Tab = "generator" | "users";

function timeAgo(iso: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return iso;
  const diff = Math.floor((Date.now() - t) / 1000);
  if (diff < 60) return `${diff}d lalu`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}j lalu`;
  return `${Math.floor(diff / 86400)}h lalu`;
}

export default function AdminScreen() {
  const [tab, setTab] = useState<Tab>("generator");

  // Generator state
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [genError, setGenError] = useState("");

  // Logged users state
  const [users, setUsers] = useState<LoggedUser[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [usersError, setUsersError] = useState("");
  const [filter, setFilter] = useState("");

  const generate = async () => {
    setGenError("");
    setCopied(false);
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) { setGenError("Masukkan email user."); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setGenError("Format email tidak valid."); return;
    }
    setBusy(true);
    try {
      setCode(await generateUnlockCode(trimmed));
    } finally { setBusy(false); }
  };

  const copyCode = async () => {
    if (!code) return;
    await Clipboard.setStringAsync(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const copyMsg = async () => {
    if (!code || !email) return;
    const m = `Hi! Berikut unlock code KevinAI Pro Anda:\n\nEmail: ${email.trim().toLowerCase()}\nUnlock Code: ${code}\n\nBuka app → tombol LOGIN (pojok kanan atas) → isi email & code.`;
    await Clipboard.setStringAsync(m);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    setUsersError("");
    try {
      setUsers(await fetchLoggedUsers());
    } catch (e) {
      setUsersError((e as Error).message);
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "users" && users.length === 0 && !loadingUsers) void loadUsers();
  }, [tab, users.length, loadingUsers, loadUsers]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await loadUsers();
    setRefreshing(false);
  }, [loadUsers]);

  const filteredUsers = filter
    ? users.filter((u) => u.email.toLowerCase().includes(filter.toLowerCase()))
    : users;

  const generateForUser = async (em: string) => {
    setEmail(em);
    setTab("generator");
    setCode(await generateUnlockCode(em));
  };

  const [revoking, setRevoking] = useState<string | null>(null);
  const doRevoke = async (em: string) => {
    setRevoking(em);
    try {
      await revokeUser(em);
      setUsers((prev) => prev.filter((u) => u.email !== em));
    } catch (e) {
      setUsersError((e as Error).message);
    } finally {
      setRevoking(null);
    }
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <View style={styles.header}>
        <View style={styles.headerIcon}>
          <Ionicons name="key" size={22} color="#F0B90B" />
        </View>
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={styles.title}>KevinAI Pro</Text>
          <Text style={styles.subtitle}>Admin Console</Text>
        </View>
      </View>

      <View style={styles.tabs}>
        <TouchableOpacity
          onPress={() => setTab("generator")}
          testID="tab-generator"
          style={[styles.tab, tab === "generator" && styles.tabActive]}
        >
          <Ionicons name="construct" size={14} color={tab === "generator" ? "#F0B90B" : "#848E9C"} />
          <Text style={[styles.tabText, { color: tab === "generator" ? "#EAECEF" : "#848E9C" }]}>GENERATOR</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => setTab("users")}
          testID="tab-users"
          style={[styles.tab, tab === "users" && styles.tabActive]}
        >
          <Ionicons name="people" size={14} color={tab === "users" ? "#0ECB81" : "#848E9C"} />
          <Text style={[styles.tabText, { color: tab === "users" ? "#EAECEF" : "#848E9C" }]}>
            LOGGED USERS {users.length > 0 ? `· ${users.length}` : ""}
          </Text>
        </TouchableOpacity>
      </View>

      {tab === "generator" ? (
        <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
          <View style={styles.card}>
            <Text style={styles.label}>EMAIL USER</Text>
            <TextInput
              value={email}
              onChangeText={setEmail}
              placeholder="user@example.com"
              placeholderTextColor="#5E6673"
              autoCapitalize="none"
              keyboardType="email-address"
              style={styles.input}
              testID="admin-email-input"
            />
            {genError ? <Text style={styles.error}>{genError}</Text> : null}
            <TouchableOpacity
              onPress={generate}
              disabled={busy}
              style={[styles.genBtn, { opacity: busy ? 0.6 : 1 }]}
              testID="admin-generate-button"
            >
              {busy ? <ActivityIndicator color="#0B0E11" /> : (
                <>
                  <Ionicons name="construct" size={16} color="#0B0E11" />
                  <Text style={styles.genBtnText}>GENERATE UNLOCK CODE</Text>
                </>
              )}
            </TouchableOpacity>

            {code ? (
              <View style={styles.resultBox}>
                <Text style={styles.resultLabel}>UNLOCK CODE</Text>
                <Text style={styles.codeBig} selectable>{code}</Text>
                <Text style={styles.resultEmail}>untuk: {email.trim().toLowerCase()}</Text>
                <View style={styles.actionRow}>
                  <TouchableOpacity onPress={copyCode} style={styles.copyBtn}>
                    <Ionicons name="copy" size={14} color="#EAECEF" />
                    <Text style={styles.copyBtnText}>Salin Code</Text>
                  </TouchableOpacity>
                  <TouchableOpacity onPress={copyMsg} style={[styles.copyBtn, { backgroundColor: "#2962FF" }]}>
                    <Ionicons name="chatbubble-ellipses" size={14} color="#fff" />
                    <Text style={[styles.copyBtnText, { color: "#fff" }]}>Salin Pesan</Text>
                  </TouchableOpacity>
                </View>
                {copied && <Text style={styles.copied}>✓ Berhasil disalin</Text>}
              </View>
            ) : null}
          </View>
        </ScrollView>
      ) : (
        <View style={{ flex: 1 }}>
          <View style={styles.searchBar}>
            <Ionicons name="search" size={16} color="#5E6673" />
            <TextInput
              value={filter}
              onChangeText={setFilter}
              placeholder="cari email…"
              placeholderTextColor="#5E6673"
              autoCapitalize="none"
              style={styles.searchInput}
            />
          </View>

          {usersError ? (
            <View style={styles.card}>
              <Text style={styles.error}>Gagal load: {usersError}</Text>
              <TouchableOpacity onPress={loadUsers} style={[styles.genBtn, { marginTop: 12 }]}>
                <Ionicons name="refresh" size={16} color="#0B0E11" />
                <Text style={styles.genBtnText}>COBA LAGI</Text>
              </TouchableOpacity>
            </View>
          ) : loadingUsers && users.length === 0 ? (
            <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
              <ActivityIndicator color="#F0B90B" />
            </View>
          ) : (
            <FlatList
              data={filteredUsers}
              keyExtractor={(u) => u.email}
              refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#F0B90B" />}
              contentContainerStyle={{ padding: 16, gap: 8 }}
              ListEmptyComponent={
                <Text style={{ color: "#5E6673", textAlign: "center", marginTop: 40 }}>
                  {filter ? "Tidak ada email yang cocok." : "Belum ada user yang login."}
                </Text>
              }
              renderItem={({ item }) => (
                <View style={styles.userRow}>
                  <View style={styles.userAvatar}>
                    <Ionicons name="checkmark-circle" size={20} color="#0ECB81" />
                  </View>
                  <View style={{ flex: 1, marginLeft: 10 }}>
                    <Text style={styles.userEmail} numberOfLines={1}>{item.email}</Text>
                    <Text style={styles.userMeta}>
                      Login {item.login_count}× · {timeAgo(item.last_seen)}
                    </Text>
                  </View>
                  <TouchableOpacity
                    onPress={() => generateForUser(item.email)}
                    style={styles.userGenBtn}
                    testID={`gen-for-${item.email}`}
                  >
                    <Ionicons name="key" size={14} color="#F0B90B" />
                  </TouchableOpacity>
                  <TouchableOpacity
                    onPress={() => doRevoke(item.email)}
                    disabled={revoking === item.email}
                    style={styles.userRevokeBtn}
                    testID={`revoke-${item.email}`}
                  >
                    {revoking === item.email ? (
                      <ActivityIndicator color="#F6465D" size="small" />
                    ) : (
                      <Ionicons name="trash-outline" size={14} color="#F6465D" />
                    )}
                  </TouchableOpacity>
                </View>
              )}
            />
          )}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0B0E11" },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 14 },
  headerIcon: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "#F0B90B22", alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "#F0B90B",
  },
  title: { fontSize: 18, fontWeight: "700", color: "#EAECEF" },
  subtitle: { fontSize: 11, color: "#848E9C", marginTop: 2 },
  tabs: { flexDirection: "row", borderBottomWidth: 1, borderColor: "#2B3139", paddingHorizontal: 16 },
  tab: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 12, borderBottomWidth: 2, borderColor: "transparent",
  },
  tabActive: { borderColor: "#F0B90B" },
  tabText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.6 },
  card: {
    marginHorizontal: 16, marginTop: 12, padding: 16, borderRadius: 14,
    backgroundColor: "#181A20", borderWidth: 1, borderColor: "#2B3139",
  },
  label: { fontSize: 10, color: "#848E9C", letterSpacing: 0.7, marginBottom: 6 },
  input: {
    height: 46, borderRadius: 10, borderWidth: 1, borderColor: "#2B3139",
    backgroundColor: "#1E2329", color: "#EAECEF", paddingHorizontal: 12, fontSize: 14,
  },
  error: { color: "#F6465D", fontSize: 12, marginTop: 8 },
  genBtn: {
    marginTop: 14, height: 46, borderRadius: 10, backgroundColor: "#F0B90B",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  genBtnText: { color: "#0B0E11", fontWeight: "800", fontSize: 13, letterSpacing: 0.7 },
  resultBox: {
    marginTop: 18, padding: 14, borderRadius: 12,
    backgroundColor: "#0B0E11", borderWidth: 1, borderColor: "#F0B90B",
  },
  resultLabel: { fontSize: 10, color: "#F0B90B", letterSpacing: 0.8 },
  codeBig: {
    fontSize: 28, fontWeight: "800", color: "#F0B90B",
    fontVariant: ["tabular-nums"], letterSpacing: 2, marginTop: 4, textAlign: "center",
  },
  resultEmail: { fontSize: 11, color: "#848E9C", textAlign: "center", marginTop: 6 },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  copyBtn: {
    flex: 1, height: 38, borderRadius: 8, backgroundColor: "#2B3139",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
  },
  copyBtnText: { color: "#EAECEF", fontSize: 12, fontWeight: "700" },
  copied: { color: "#0ECB81", fontSize: 11, textAlign: "center", marginTop: 8 },
  searchBar: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: 16, marginTop: 12, paddingHorizontal: 12,
    height: 40, borderRadius: 10, borderWidth: 1, borderColor: "#2B3139", backgroundColor: "#181A20",
  },
  searchInput: { flex: 1, color: "#EAECEF", fontSize: 13 },
  userRow: {
    flexDirection: "row", alignItems: "center",
    padding: 12, borderRadius: 10, borderWidth: 1,
    borderColor: "#2B3139", backgroundColor: "#181A20",
  },
  userAvatar: {
    width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center",
    backgroundColor: "#0ECB8122",
  },
  userEmail: { color: "#EAECEF", fontSize: 13, fontWeight: "600" },
  userMeta: { color: "#848E9C", fontSize: 10, marginTop: 2 },
  userGenBtn: {
    width: 34, height: 34, borderRadius: 8,
    backgroundColor: "#F0B90B22", borderWidth: 1, borderColor: "#F0B90B",
    alignItems: "center", justifyContent: "center",
  },
  userRevokeBtn: {
    width: 34, height: 34, borderRadius: 8, marginLeft: 6,
    backgroundColor: "#F6465D22", borderWidth: 1, borderColor: "#F6465D",
    alignItems: "center", justifyContent: "center",
  },
});
