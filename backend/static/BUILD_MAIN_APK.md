# CryptoStock Pro Main App — APK Build Guide (v2.1.3+)

⚠️ **PENTING:** File ini untuk build **APK USER (CryptoStock Pro)** yang dipakai
teman-teman Anda. BUKAN untuk admin tool. Untuk admin tool build, lihat
`CryptoStock-Admin-Source.zip` yang berbeda.

## Persyaratan (sama seperti admin app):
1. Node.js 20+ dari https://nodejs.org
2. Terminal (Command Prompt / Terminal / Git Bash)
3. Akun Expo gratis dari https://expo.dev/signup

## Step-by-Step

### 1. Ekstrak ZIP
```bash
unzip CryptoStock-App-Source.zip
cd frontend
```

### 2. Install dependencies
```bash
npm install --global yarn eas-cli
yarn install
```
(~3-5 menit)

### 3. Login Expo
```bash
eas login
```

### 4. (SEKALI SAJA) Init project
```bash
eas init
```
Pilih "Yes" saat ditanya create new project.

### 5. VERIFY .env config
Buka file `.env` dan pastikan:
```
EXPO_PUBLIC_BACKEND_URL=https://cryptostock-pro.preview.emergentagent.com
```
Kalau URL production Anda BEDA (setelah Publish), ganti dengan URL Anda.

### 6. Build APK
```bash
eas build --platform android --profile preview
```
- Pilih "Yes" untuk generate keystore
- Tunggu ~15-25 menit
- Download link APK muncul di terminal + di dashboard Expo

### 7. Install & Test
1. Transfer APK ke HP
2. **Uninstall APK versi lama dulu** (v2.1.2 / v2.0.x) supaya tidak konflik
3. Install APK baru
4. Buka app → header harus tampil "CryptoStock Pro Ver 2.1.3"
5. Tap LOGIN → input email + code (dari admin tool) → UNLOCK
6. ✅ Sukses = header tampil "LOGGED" biru

## Verifikasi Auth Baru

Buka APK → tap LOGIN → input email + code. Tapi PENTING:
- Code HARUS di-generate via admin tool `.../api/admin-tool` (bukan hitung sendiri)
- Code case-sensitive — masukkan HURUF BESAR persis seperti admin tool tampilkan
- Format: `XXXX-XXXX-XXXX` (12 karakter hex + 2 dash)

Kalau login fail dengan pesan "Unlock code tidak ditemukan":
- Cek admin tool `/api/admin-tool` → tab USERS & CODES → refresh → cari email Anda
- Code HARUS tampil dengan status **UNUSED** atau **ACTIVE**
- Kalau tidak ada → generate code baru & coba lagi
- Kalau ada tapi login masih fail → mungkin ini bukan APK v2.1.3 yang Anda install (uninstall + install ulang)

## Beda dengan APK Lama (v2.0.x / v2.1.2)

| Fitur | Old APK (< 2.1.3) | New APK (2.1.3+) |
|-------|-------------------|-------------------|
| Auth verification | Offline SHA-256 hash | Backend `/api/auth/verify` |
| Device binding | ❌ Tidak ada | ✅ 1 kode = 1 HP |
| Expiry / durasi | ❌ Tidak ada (semua lifetime) | ✅ Monthly / Quarterly / etc. |
| Code source | Deterministic dari email | Random di database |
| Auto-logout expired | ❌ Tidak | ✅ Ya, cek tiap 60 detik |
| Sends X-App-Version | ❌ Tidak | ✅ Ya |

Kalau APK Anda tidak menunjukkan "LOGGED" biru padahal input code benar, artinya
APK Anda BUKAN v2.1.3 (mungkin v2.1.2 yang di-branding v2.1.3, atau build lama).
Solusi: rebuild dari source ZIP TERBARU ini.
