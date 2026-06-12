/**
 * Shared unlock-code algorithm.
 *
 * Used by BOTH the main app (to verify a code) and the admin
 * "Unlock Code Generator" app (to generate one).
 *
 * Algorithm: SHA-256(SECRET || "::" || normalized_email), take first 12 hex
 * chars uppercase, formatted as `XXXX-XXXX-XXXX`.
 *
 * Properties:
 *   - Deterministic: same email always produces the same code.
 *   - One-to-one: a code generated for email A will not unlock email B.
 *   - Offline: no server / network required for either generation or
 *     verification.
 *
 * NOTE: Both apps MUST use the EXACT SAME `UNLOCK_SECRET`. Changing it
 * invalidates every previously issued code.
 */
import * as Crypto from "expo-crypto";

// DO NOT change this without regenerating every code you have ever issued.
export const UNLOCK_SECRET = "KevinAI-Pro-2026-Premium-Unlock-Secret-v1-DoNotShare";

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export async function generateUnlockCode(email: string): Promise<string> {
  const normalized = normalizeEmail(email);
  if (!normalized) return "";
  const message = `${UNLOCK_SECRET}::${normalized}`;
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    message,
  );
  const c = digest.substring(0, 12).toUpperCase();
  return `${c.substring(0, 4)}-${c.substring(4, 8)}-${c.substring(8, 12)}`;
}

export async function verifyUnlockCode(email: string, code: string): Promise<boolean> {
  const expected = await generateUnlockCode(email);
  if (!expected) return false;
  return expected === code.trim().toUpperCase();
}
