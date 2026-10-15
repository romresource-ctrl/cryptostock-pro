/**
 * v10.2.16 — Tombstone delete trade BERSAMA untuk Recent Trades
 * (asi-bot) & Running Positions (trades-position).
 *
 * Keluhan user: hapus kartu di Recent Trades TIDAK menghilangkan kartu
 * yang sama di Running Positions (dan sebaliknya). Akar masalah: kedua
 * halaman punya anti-resurrect set + page cache MASING-MASING
 * (`asibot-trades:{id}` vs `trades:{id}`) — delete di satu halaman
 * tidak membersihkan cache/halaman satunya, sehingga kartu "bangkit
 * lagi" saat halaman lain dibuka.
 *
 * Solusi: satu set tombstone module-level (dibagikan kedua halaman di
 * runtime yang sama) + persist ke AsyncStorage supaya cache basi dari
 * sesi sebelumnya ikut tersaring saat mount. TTL 2 menit — cukup untuk
 * menutup race poll/cache; delete backend sendiri permanen.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const KEY = "asibot-deleted-trades:v1";
const TTL_MS = 120_000;

const mem = new Map<string, number>();
let loaded = false;

async function ensureLoaded(): Promise<void> {
  if (loaded) return;
  loaded = true;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw) {
      const obj = JSON.parse(raw);
      const now = Date.now();
      Object.entries(obj || {}).forEach(([id, ts]) => {
        if (typeof ts === "number" && now - ts < TTL_MS) mem.set(id, ts);
      });
    }
  } catch { /* abaikan */ }
}

/** Tandai trade dihapus (panggil saat optimistic delete). Fire-and-forget. */
export async function markTradeDeleted(id: string): Promise<void> {
  if (!id) return;
  await ensureLoaded();
  mem.set(id, Date.now());
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(Object.fromEntries(mem)));
  } catch { /* abaikan */ }
}

/** True bila id baru saja dihapus (masih dalam TTL). */
export function isTradeDeletedSync(id: string): boolean {
  const ts = mem.get(id);
  return ts != null && Date.now() - ts < TTL_MS;
}

/** Filter daftar trade dari tombstone bersama (await di load/refresh). */
export async function filterDeletedTrades<T extends Record<string, any>>(
  items: T[],
): Promise<T[]> {
  await ensureLoaded();
  return items.filter((x) => !isTradeDeletedSync(String(x?._id || x?.id || "")));
}
