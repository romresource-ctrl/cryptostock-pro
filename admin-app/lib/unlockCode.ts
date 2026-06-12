/**
 * Shared unlock-code algorithm.
 *
 * MUST be identical to /app/frontend/src/auth/unlockCode.ts so the codes
 * generated here are accepted by the main KevinAI Pro app.
 */
import * as Crypto from "expo-crypto";

export const UNLOCK_SECRET = "KevinAI-Pro-2026-Premium-Unlock-Secret-v1-DoNotShare";

export async function generateUnlockCode(email: string): Promise<string> {
  const normalized = email.trim().toLowerCase();
  if (!normalized) return "";
  const message = `${UNLOCK_SECRET}::${normalized}`;
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    message,
  );
  const c = digest.substring(0, 12).toUpperCase();
  return `${c.substring(0, 4)}-${c.substring(4, 8)}-${c.substring(8, 12)}`;
}
