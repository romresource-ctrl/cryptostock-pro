# CryptoStock Admin — APK Build Guide

## Persyaratan Minimum di Laptop
1. **Node.js 20+** → download & install dari https://nodejs.org (LTS)
2. **Terminal**: Command Prompt (Windows), Terminal (Mac), atau Git Bash
3. **Akun Expo** (GRATIS): daftar di https://expo.dev/signup (butuh 2 menit)

Tidak perlu Android Studio. Tidak perlu Java. Build terjadi di server Expo.

---

## Step-by-Step Build APK

### Step 1: Ekstrak ZIP
Unzip `CryptoStock-Admin-Source.zip` ke folder mana saja, misal `~/Desktop/admin-app/`.

### Step 2: Install dependencies
Buka Terminal, masuk ke folder:
```bash
cd ~/Desktop/admin-app
```

Install package:
```bash
npm install --global yarn eas-cli
yarn install
```
(perlu ~2-3 menit tergantung internet)

### Step 3: Login ke Expo
```bash
eas login
```
Masukkan email + password akun Expo Anda (dari step Persyaratan #3).

### Step 4: (SEKALI SAJA) Konfigurasi project
```bash
eas init
```
- Konfirmasi "Yes" saat ditanya buat project baru.
- EAS otomatis assign project ID ke `app.json`.

### Step 5: Build APK di cloud
```bash
eas build --platform android --profile preview
```
- Pilih **"Yes"** saat ditanya "Generate a new Android Keystore?"
- Tunggu **15-25 menit** (EAS build di server Expo).
- Setelah selesai, terminal akan tampilkan URL APK di https://expo.dev/accounts/USERNAME/projects/unlockkeygen/builds/xxxxx

### Step 6: Download APK
1. Klik URL yang diberikan.
2. Di halaman Expo dashboard → klik **"Install"** → pilih **"Download"**.
3. Transfer file `.apk` ke HP admin Anda (via WhatsApp/USB/Google Drive).

### Step 7: Install di HP
1. Aktifkan **"Install from Unknown Sources"** di HP:
   - Settings → Security → Install unknown apps → izinkan browser/file manager.
2. Tap file `.apk` di HP → Install.
3. Buka **UnlockKeyGen** dari home screen HP.

---

## Kalau Ada Error

### "Failed to authenticate"
Pastikan Anda login dengan `eas login` (bukan `expo login`).

### Build gagal karena "Project not configured"
Jalankan `eas init` lagi, pilih "Yes" untuk create new project.

### APK tidak bisa dibuka setelah install
Cek "Install from Unknown Sources" di Settings HP sudah aktif.

### Backend URL / Admin Token salah
Sebelum build, cek `lib/adminApi.ts` — harus sesuai dengan backend production Anda:
```typescript
BACKEND_URL = "https://cryptostock-pro.preview.emergentagent.com"
ADMIN_TOKEN = "kevin-admin-2026-do-not-share-xyz789"
```
Kalau URL production Anda beda (setelah deploy custom domain, dll), edit sebelum step 5.

---

## Test Setelah Install

Buka UnlockKeyGen di HP → tab GENERATOR → masukkan:
- `test@example.com` → hasilnya **HARUS** `3459-10B0-3308`

Kalau hasil sama = build sukses & algoritma match dengan main app.
Kalau beda → `UNLOCK_SECRET` di `lib/unlockCode.ts` mungkin sudah diubah — restore ke original & rebuild.

---

## Backup Solution: Web Admin Tool

Kalau proses build APK terlalu lama/ribet, gunakan web version di:
```
https://cryptostock-pro.preview.emergentagent.com/api/admin-tool
```
Fitur 100% sama. Simpan sebagai bookmark di HP → 1-tap akses.
