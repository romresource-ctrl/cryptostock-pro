import { Ionicons } from "@expo/vector-icons";
import React from "react";
import {
  Linking,
  Modal,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  visible: boolean;
  onClose: () => void;
  onLogin: () => void;
};

const CONTACT_EMAIL = "kevinAIpro@gmail.com";
const CONTACT_WA = "6282186597571";

export default function VipModal({ visible, onClose, onLogin }: Props) {
  const { colors } = useTheme();
  const gold = "#F0B90B";

  const openWa = () => Linking.openURL(`https://wa.me/${CONTACT_WA}`).catch(() => {});
  const openEmail = () => Linking.openURL(`mailto:${CONTACT_EMAIL}`).catch(() => {});

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
        <View style={[styles.box, { backgroundColor: colors.surface, borderColor: gold }]}>
          <TouchableOpacity onPress={onClose} testID="vip-close-button" style={styles.closeX} hitSlop={10}>
            <Ionicons name="close" size={22} color={colors.textMuted} />
          </TouchableOpacity>
          <View style={[styles.iconRing, { borderColor: gold, backgroundColor: gold + "22" }]}>
            <Ionicons name="star" size={28} color={gold} />
          </View>
          <Text style={[styles.title, { color: gold }]}>VIP Members Only Features</Text>
          <Text style={[styles.body, { color: colors.textPrimary }]}>
            LOGIN or Become Member to view exclusive Premium insights and accurate AI Signals.
          </Text>
          <Text style={[styles.contactLabel, { color: colors.textMuted }]}>Contact Us to unlock:</Text>
          <TouchableOpacity onPress={openEmail} style={[styles.contactRow, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]} testID="vip-email-button">
            <Ionicons name="mail" size={18} color={colors.accentBlue} />
            <Text style={[styles.contactText, { color: colors.textPrimary }]} numberOfLines={1}>{CONTACT_EMAIL}</Text>
            <Ionicons name="open-outline" size={14} color={colors.textMuted} />
          </TouchableOpacity>
          <TouchableOpacity onPress={openWa} style={[styles.contactRow, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]} testID="vip-wa-button">
            <Ionicons name="logo-whatsapp" size={18} color="#25D366" />
            <Text style={[styles.contactText, { color: colors.textPrimary }]} numberOfLines={1}>+{CONTACT_WA}</Text>
            <Ionicons name="open-outline" size={14} color={colors.textMuted} />
          </TouchableOpacity>
          <TouchableOpacity onPress={() => { onClose(); onLogin(); }} style={[styles.loginBtn, { backgroundColor: colors.accentBlue }]} testID="vip-login-button">
            <Ionicons name="key" size={16} color="#fff" />
            <Text style={styles.loginText}>SUDAH PUNYA CODE? LOGIN</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  box: { width: "100%", maxWidth: 380, borderRadius: 16, borderWidth: 1.5, padding: 20, alignItems: "center" },
  closeX: { position: "absolute", top: 12, right: 12, zIndex: 1 },
  iconRing: { width: 64, height: 64, borderRadius: 32, alignItems: "center", justifyContent: "center", borderWidth: 1.5, marginTop: 6, marginBottom: 12 },
  title: { fontSize: 18, fontWeight: "800", letterSpacing: 0.4, textAlign: "center" },
  body: { fontSize: 13, lineHeight: 19, textAlign: "center", marginTop: 10, marginBottom: 14 },
  contactLabel: { fontSize: 10, letterSpacing: 0.6, alignSelf: "stretch", marginBottom: 6, marginTop: 4 },
  contactRow: { flexDirection: "row", alignItems: "center", gap: 10, width: "100%", paddingHorizontal: 12, paddingVertical: 10, borderRadius: 10, borderWidth: 1, marginBottom: 8 },
  contactText: { fontSize: 13, fontWeight: "600", flex: 1 },
  loginBtn: { marginTop: 8, width: "100%", height: 44, borderRadius: 10, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  loginText: { color: "#fff", fontSize: 12, fontWeight: "800", letterSpacing: 0.6 },
});
