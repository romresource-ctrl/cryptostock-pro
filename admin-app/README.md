# KevinAI Admin — Unlock Code Generator

Aplikasi terpisah untuk generate unlock code KevinAI Pro. **ADMIN ONLY — Jangan distribusikan APK ini ke user.**

## Cara kerja
Algoritma sama dengan main app (`SHA-256(SECRET || "::" || email)` → 12 hex char format `XXXX-XXXX-XXXX`). Karena algoritmanya deterministik dan offline:
- Email **A** selalu menghasilkan code **A1**.
- Code A1 hanya valid untuk email A. Tidak bisa pakai untuk email B.
- Tidak butuh server / koneksi internet.

`UNLOCK_SECRET` di `lib/unlockCode.ts` HARUS PERSIS SAMA dengan yang ada di main app (`/app/frontend/src/auth/unlockCode.ts`). Kalau berubah, semua code lama jadi invalid.

## Cara build APK

### Opsi A — Build cepat via Expo (rekomendasi)
```bash
cd /app/admin-app
yarn install
npx eas build --platform android --profile preview --local
# atau cloud build:
npx eas build --platform android --profile preview
```
APK output ada di folder yang ditunjukkan EAS. Install ke HP Anda saja.

### Opsi B — Coba dulu di Expo Go (tanpa build)
```bash
cd /app/admin-app
yarn install
npx expo start --tunnel
```
Scan QR di Expo Go (Android). Anda bisa test alur generate code sebelum build APK.

## Cara pakai
**Tab GENERATOR:**
1. Masukkan email user di kolom EMAIL USER.
2. Tap **GENERATE UNLOCK CODE** → keluar code 12-char format `XXXX-XXXX-XXXX`.
3. Tap **Salin Pesan** untuk copy template lengkap untuk dikirim ke user.

**Tab LOGGED USERS:**
- Menampilkan semua email user yang sudah berhasil login & unlock di KevinAI Pro.
- Auto-load saat tab dibuka. Pull-to-refresh untuk update manual.
- Search bar untuk filter email.
- Tap icon kunci kuning di samping email → langsung generate code untuk user itu (pindah ke tab Generator).
- Data sumber dari `GET /api/admin/users` di backend (protected dengan `X-Admin-Token`).

## Konfigurasi
Edit `/app/admin-app/lib/adminApi.ts`:
- `BACKEND_URL` = URL deployment KevinAI Pro (default: preview URL Emergent)
- `ADMIN_TOKEN` = harus PERSIS SAMA dengan `ADMIN_TOKEN` di `/app/backend/.env`

## Sample test
- Email: `test@example.com` → Code: `3459-10B0-3308`
- Email: `kevin@gmail.com` → Code: `D03C-F514-2254`
- Email: `admin@kevinai.pro` → Code: `BB3B-94EB-0FAA`

(Hasil persis akan sama selama `UNLOCK_SECRET` tidak diubah.)
