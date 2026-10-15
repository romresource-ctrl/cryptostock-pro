/**
 * v10.2.9 — Page cache (stale-while-revalidate).
 *
 * Keluhan user: membuka halaman Running Positions / Leaderboard /
 * grafik aset terasa SANGAT lambat padahal endpoint backend cepat
 * (<0.3 detik). Penyebabnya: halaman selalu memulai dari state KOSONG
 * lalu menunggu round-trip jaringan sebelum menggambar apa pun.
 *
 * Solusi: simpan payload terakhir yang sukses ke AsyncStorage. Saat
 * halaman dibuka, data cache langsung dirender (instan, tanpa spinner),
 * sementara fetch segar jalan di background dan menggantikan data begitu
 * tiba. Pola ini tidak mengubah kebenaran data — cache hanya untuk
 * penampilan awal dan selalu ditimpa response terbaru.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const PREFIX = "pagecache:v1:";

/** Baca cache halaman. Mengembalikan null bila tidak ada/rusak. */
export async function readPageCache<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return (parsed?.data ?? null) as T | null;
  } catch {
    return null;
  }
}

/** Tulis cache halaman (fire-and-forget, tidak pernah throw). */
export function writePageCache(key: string, data: unknown): void {
  try {
    AsyncStorage.setItem(
      PREFIX + key,
      JSON.stringify({ at: Date.now(), data }),
    ).catch(() => { /* abaikan penuh/gagal */ });
  } catch { /* abaikan */ }
}
