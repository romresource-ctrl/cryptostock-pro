import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

import { getDeviceId, getDeviceName } from "@/src/lib/deviceId";
import { storage } from "@/src/utils/storage";

const STORAGE_KEY = "kevinai.auth";

type AuthState = {
  email: string;
  code: string;
  unlockedAt: string;
  duration: "monthly" | "quarterly" | "half_year" | "yearly" | "lifetime" | null;
  expiresAt: string | null; // null = lifetime
  deviceId: string;
};

export type LoginResult = {
  ok: boolean;
  error?: string;
  reason?:
    | "invalid_code"
    | "email_mismatch"
    | "revoked"
    | "expired"
    | "device_mismatch"
    | "network";
};

type AuthContextValue = {
  loaded: boolean;
  isUnlocked: boolean;
  email: string | null;
  duration: string | null;
  expiresAt: string | null;
  login: (email: string, code: string) => Promise<LoginResult>;
  logout: (reason?: string) => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function backendBase(): string {
  const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
  return `${RAW.replace(/\/+$/, "")}/api`;
}

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false; // lifetime
  const t = Date.parse(expiresAt);
  if (Number.isNaN(t)) return false;
  return t <= Date.now();
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Load persisted session + verify against backend
  useEffect(() => {
    (async () => {
      const saved = await storage.getItem<AuthState>(STORAGE_KEY, null as AuthState | null);
      if (saved && saved.email && saved.code && saved.deviceId) {
        if (isExpired(saved.expiresAt)) {
          await storage.removeItem(STORAGE_KEY);
        } else {
          // Re-verify with backend to catch: revoke, device change, secret rotation
          try {
            let res = await fetch(`${backendBase()}/auth/verify`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                email: saved.email,
                code: saved.code,
                device_id: saved.deviceId,
                device_name: getDeviceName(),
              }),
            });
            let data = await res.json();
            // v10.1.6 — Hardcoded production-host fallback DIHAPUS sesuai
            // deployment policy (semua request harus lewat
            // EXPO_PUBLIC_BACKEND_URL, tidak boleh bypass ke host tetap).
            if (data?.ok) {
              // Refresh expiry/duration from server (in case admin extended it)
              setAuth({
                ...saved,
                duration: data.duration ?? saved.duration,
                expiresAt: data.expires_at ?? saved.expiresAt,
              });
            } else {
              await storage.removeItem(STORAGE_KEY);
            }
          } catch {
            // Offline: trust local expiry
            setAuth(saved);
          }
        }
      }
      setLoaded(true);
    })();
  }, []);

  // Periodic expiry check (every 60s while app is foregrounded)
  useEffect(() => {
    if (!auth) return;
    const t = setInterval(() => {
      if (auth && isExpired(auth.expiresAt)) {
        void logout("expired");
      }
    }, 60_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.expiresAt]);

  const login = async (email: string, code: string): Promise<LoginResult> => {
    const cleanEmail = email.trim().toLowerCase();
    const cleanCode = code.trim().toUpperCase();
    if (!cleanEmail || !cleanCode) {
      return { ok: false, error: "Email dan unlock code wajib diisi." };
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      return { ok: false, error: "Format email tidak valid." };
    }
    const deviceId = await getDeviceId();
    const deviceName = getDeviceName();
    try {
      // v10.1.6 — Hardcoded production-host fallback DIHAPUS sesuai
      // deployment policy: auth hanya lewat EXPO_PUBLIC_BACKEND_URL.
      let res = await fetch(`${backendBase()}/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: cleanEmail,
          code: cleanCode,
          device_id: deviceId,
          device_name: deviceName,
        }),
      });
      let data = await res.json();
      if (!data?.ok) {
        const reason = data?.reason as LoginResult["reason"];
        const msg: Record<string, string> = {
          invalid_code: "Unlock code tidak ditemukan.",
          email_mismatch: "Email tidak cocok dengan code.",
          revoked: "Code telah di-revoke oleh admin.",
          expired: "Code sudah kadaluarsa. Minta code baru ke admin.",
          device_mismatch: "Code sudah terpakai di device lain.",
        };
        return { ok: false, reason, error: msg[reason ?? ""] || "Unlock gagal." };
      }
      const next: AuthState = {
        email: cleanEmail,
        code: cleanCode,
        unlockedAt: new Date().toISOString(),
        duration: data.duration ?? null,
        expiresAt: data.expires_at ?? null,
        deviceId,
      };
      await storage.setItem(STORAGE_KEY, next);
      setAuth(next);
      return { ok: true };
    } catch {
      return { ok: false, reason: "network", error: "Tidak bisa terhubung ke server." };
    }
  };

  const logout = async (_reason?: string) => {
    await storage.removeItem(STORAGE_KEY);
    setAuth(null);
  };

  const value = useMemo<AuthContextValue>(
    () => ({
      loaded,
      isUnlocked: !!auth && !isExpired(auth?.expiresAt),
      email: auth?.email ?? null,
      duration: auth?.duration ?? null,
      expiresAt: auth?.expiresAt ?? null,
      login,
      logout,
    }),
    [auth, loaded],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
