import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

import { storage } from "@/src/utils/storage";
import { verifyUnlockCode } from "@/src/auth/unlockCode";

const STORAGE_KEY = "kevinai.auth";

type AuthState = {
  email: string;
  code: string;
  unlockedAt: string;
};

type AuthContextValue = {
  loaded: boolean;
  isUnlocked: boolean;
  email: string | null;
  login: (email: string, code: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      const saved = await storage.getItem<AuthState>(STORAGE_KEY, null as AuthState | null);
      if (saved && saved.email && saved.code) {
        // Verify cached code is still valid (in case secret was rotated)
        const ok = await verifyUnlockCode(saved.email, saved.code);
        if (ok) setAuth(saved);
      }
      setLoaded(true);
    })();
  }, []);

  const login = async (email: string, code: string) => {
    const cleanEmail = email.trim().toLowerCase();
    const cleanCode = code.trim().toUpperCase();
    if (!cleanEmail || !cleanCode) {
      return { ok: false, error: "Email dan unlock code wajib diisi." };
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      return { ok: false, error: "Format email tidak valid." };
    }
    const ok = await verifyUnlockCode(cleanEmail, cleanCode);
    if (!ok) {
      return { ok: false, error: "Unlock code tidak cocok untuk email ini." };
    }
    const next: AuthState = {
      email: cleanEmail,
      code: cleanCode,
      unlockedAt: new Date().toISOString(),
    };
    await storage.setItem(STORAGE_KEY, next);
    setAuth(next);
    return { ok: true };
  };

  const logout = async () => {
    await storage.removeItem(STORAGE_KEY);
    setAuth(null);
  };

  const value = useMemo<AuthContextValue>(
    () => ({
      loaded,
      isUnlocked: !!auth,
      email: auth?.email ?? null,
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
