import React from "react";
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";

export default function AsiLegalScreen() {
  const router = useRouter();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: colors.background, paddingTop: insets.top }}>
      <View style={s.header}>
        <TouchableOpacity onPress={() => router.back()} testID="legal-back" hitSlop={10}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
        </TouchableOpacity>
        <Text style={[s.title, { color: colors.textPrimary }]}>
          Terms, Privacy & Compliance — ASI-Bot
        </Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: insets.bottom + 32, gap: 16 }}>
        <Section title="📜 In-App Disclaimer & Terms of Use">
          <Para colors={colors}>
            <B>1. Non-Custodial.</B>{" "}
            AI Crypto Stock Pro {`("Aplikasi")`} <B>bukan</B> broker/bursa.
            Aplikasi tidak menerima deposit, tidak memegang dana user,
            dan tidak memiliki akses penarikan dana. 100% dana tetap di
            akun exchange Anda (Binance / Bybit / OKX / Bitget).
          </Para>
          <Para colors={colors}>
            <B>2. Risiko Trading Otomatis.</B>{" "}
            Semua risiko slippage, latency jaringan, kerugian pergerakan
            pasar, dan likuidasi adalah <B>100% tanggung jawab pengguna</B>.
            Pengembang tidak menjamin profitabilitas dan tidak bertanggung
            jawab atas kerugian finansial dalam bentuk apa pun.
          </Para>
          <Para colors={colors}>
            <B>3. Kegagalan Pihak Ketiga.</B>{" "}
            Pengembang tidak bertanggung jawab atas kegagalan eksekusi,
            keterlambatan sinyal, atau downtime yang disebabkan oleh
            gangguan API dari pihak exchange.
          </Para>
          <Para colors={colors}>
            <B>4. Larangan Izin Withdrawal.</B>{" "}
            Saat membuat API key di exchange,{" "}
            <B>JANGAN PERNAH mencentang izin {`"Enable Withdrawals"`}</B>.
            ASI-Bot akan otomatis menolak API key dengan izin tersebut.
          </Para>
          <Para colors={colors}>
            <B>5. Whitelist Top-100.</B>{" "}
            Hanya 100 perpetual futures USDT-margined paling liquid yang
            diperbolehkan. Pembatasan ini melindungi user dari rug-pull
            dan likuiditas tipis.
          </Para>
          <Para colors={colors}>
            <B>6. Lokasi Pengguna.</B>{" "}
            Fitur trading futures tunduk pada regulasi masing-masing
            yurisdiksi. User bertanggung jawab memastikan penggunaan sesuai
            hukum setempat.
          </Para>
        </Section>

        <Section title="🔒 Privacy Policy (ASI-Bot)">
          <Para colors={colors}>
            <B>Penyimpanan API Key.</B>{" "}
            API Key dan API Secret exchange Anda disimpan dalam bentuk
            terenkripsi menggunakan <B>AES-256-GCM envelope encryption</B>{" "}
            (standar yang sama dipakai AWS Encryption SDK dan Google Tink).
            Master key tidak pernah dibagikan ke pihak ketiga.
          </Para>
          <Para colors={colors}>
            <B>Penggunaan Kunci.</B>{" "}
            Kunci hanya didekripsi di memori backend saat mengirim order
            atas perintah eksplisit Anda (Semi-Auto 1-tap atau Full-Auto
            yang Anda aktifkan). Tidak pernah dikirim ke sistem lain.
          </Para>
          <Para colors={colors}>
            <B>Data yang Dikumpulkan.</B>{" "}
            Device ID anonim, inisial 3-huruf (handle), riwayat order yang
            Anda eksekusi, dan statistik PnL. Tidak ada data pribadi
            (nama, email, nomor telepon) wajib dikumpulkan.
          </Para>
          <Para colors={colors}>
            <B>Hak Pengguna.</B>{" "}
            Anda dapat menghapus semua credential dan histori kapan saja
            melalui tombol {`"Delete"`} di halaman ASI-Bot. Setelah dihapus,
            data tidak dapat dipulihkan.
          </Para>
        </Section>

        <Section title="📱 Google Play Data Safety Declaration">
          <Para colors={colors}>
            Deklarasi yang WAJIB dicantumkan di Google Play Console →
            App Content → Data Safety sebelum publikasi:
          </Para>
          <Bullet colors={colors}>
            <B>Data types collected:</B> App activity (trade history,
            PnL), App info and performance (device ID),
            Financial info (encrypted API key for trading only).
          </Bullet>
          <Bullet colors={colors}>
            <B>Data is shared with third parties?</B> No. (API key
            dipakai langsung oleh backend untuk order submission ke
            exchange yang Anda pilih; bukan {`"sharing"`}.)
          </Bullet>
          <Bullet colors={colors}>
            <B>Data is encrypted in transit?</B> Yes (HTTPS/TLS 1.3).
          </Bullet>
          <Bullet colors={colors}>
            <B>Data is encrypted at rest?</B> Yes (AES-256-GCM).
          </Bullet>
          <Bullet colors={colors}>
            <B>User can request data deletion?</B> Yes (in-app Delete
            button).
          </Bullet>
          <Bullet colors={colors}>
            <B>App category:</B> Finance. Target audience: 18+.
          </Bullet>
        </Section>

        <Text style={{ color: colors.textMuted, fontSize: 11, textAlign: "center", marginTop: 10 }}>
          Terakhir diperbarui: {new Date().toISOString().split("T")[0]}
          {"\n"}Versi: 9.4.3 (ASI-Bot Hard-Bracket Mainnet)
        </Text>
      </ScrollView>
    </View>
  );
}

function Section({ title, children }: any) {
  const { colors } = useTheme();
  return (
    <View style={[s.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <Text style={[s.sTitle, { color: colors.textPrimary }]}>{title}</Text>
      {children}
    </View>
  );
}
function B({ children }: any) {
  return <Text style={{ fontWeight: "900" }}>{children}</Text>;
}
function Para({ children, colors }: any) {
  return <Text style={{ color: colors.textSecondary, fontSize: 12.5, lineHeight: 19, marginTop: 8 }}>{children}</Text>;
}
function Bullet({ children, colors }: any) {
  return (
    <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 18, marginTop: 6 }}>
      • {children}
    </Text>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  title: { fontSize: 15, fontWeight: "900", flex: 1 },
  card: { padding: 14, borderRadius: 14, borderWidth: 1 },
  sTitle: { fontSize: 14, fontWeight: "900", letterSpacing: 0.3 },
});
