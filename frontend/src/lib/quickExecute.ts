// v10.6.1 — Eksekusi 1-tap memakai setting ASI-Bot user (risk/margin,
// leverage, TP/AC, margin mode, entry mode, jaringan). Dipakai EXECUTE &
// REVERSE di Leaderboard serta REVERSE di detail aset.
import { api } from "@/src/lib/api";
import { getDeviceId } from "@/src/lib/deviceId";

type Side = "BUY" | "SELL";

/** Balik arah sinyal: jarak SL/TP (dalam %) dari entry asli dicerminkan
 *  ke sisi berlawanan dari harga entry baru. */
export function reverseLevels(side: Side, origEntry: number, sl: number,
  tps: number[], newEntry: number): { side: Side; stop_loss: number; take_profits: number[] } {
  if (!(origEntry > 0) || !(sl > 0) || !(newEntry > 0)) {
    throw new Error("Level sinyal tidak lengkap (entry/SL) — REVERSE dibatalkan.");
  }
  const pct = (x: number) => Math.abs(x - origEntry) / origEntry;
  const newSide: Side = side === "BUY" ? "SELL" : "BUY";
  const dir = newSide === "BUY" ? 1 : -1;
  return {
    side: newSide,
    stop_loss: newEntry * (1 - dir * pct(sl)),
    take_profits: tps.map((tp) => newEntry * (1 + dir * pct(tp))),
  };
}

export async function quickExecute(p: {
  symbol: string; side: Side; entry: number; stop_loss: number;
  take_profits: number[]; formula_tag?: string | null; profile?: string | null;
}): Promise<void> {
  const did = await getDeviceId();
  const bot: any = await api.asi.getBot(did);
  if (!bot?.exists) {
    const e: any = new Error("Setup ASI-Bot dulu: hubungkan exchange & atur parameter bot.");
    e.code = "need_setup";
    throw e;
  }
  await api.asi.executeTrade(did, {
    exchange: (bot.exchange || "binance"),
    symbol: p.symbol,
    side: p.side,
    entry: p.entry,
    stop_loss: p.stop_loss,
    take_profits: p.take_profits,
    risk_pct: Number(bot.risk_pct ?? 5),
    leverage: Number(bot.leverage ?? 10),
    mode: "semi",
    tp_count: (Number(bot.tp_count ?? 3) as 1 | 2 | 3),
    auto_close_pct: Number(bot.auto_close_pct ?? 0) as any,
    margin_usdt: Number(bot.margin_usdt ?? 0),
    trailing_callback_rate: Number(bot.trailing_callback_rate ?? 2),
    margin_mode: (bot.margin_mode || "isolated"),
    testnet: bot.active_testnet ?? true,
    profile: p.profile ?? null,
    formula_tag: p.formula_tag ?? null,
    entry_mode: (bot.entry_mode || "limit"),
  } as any);
}
