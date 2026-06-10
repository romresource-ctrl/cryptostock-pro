import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

import { storage } from "@/src/utils/storage";

export type ThemeMode = "dark" | "light";

export const palette = {
  dark: {
    background: "#0B0E11",
    surface: "#181A20",
    surfaceAlt: "#1E2329",
    surfaceHighlight: "#2B3139",
    textPrimary: "#EAECEF",
    textSecondary: "#848E9C",
    textMuted: "#5E6673",
    accentUp: "#0ECB81",
    accentDown: "#F6465D",
    accentHold: "#FCD535",
    accentBlue: "#2962FF",
    border: "#2B3139",
    overlay: "rgba(0,0,0,0.55)",
  },
  light: {
    background: "#FAFAFA",
    surface: "#FFFFFF",
    surfaceAlt: "#F5F5F5",
    surfaceHighlight: "#EAECEF",
    textPrimary: "#1E2329",
    textSecondary: "#707A8A",
    textMuted: "#9AA3B0",
    accentUp: "#02C076",
    accentDown: "#F6465D",
    accentHold: "#F3BA2F",
    accentBlue: "#2962FF",
    border: "#EAECEF",
    overlay: "rgba(0,0,0,0.35)",
  },
};

type ThemeContextValue = {
  mode: ThemeMode;
  colors: typeof palette.dark;
  toggle: () => void;
  setMode: (m: ThemeMode) => void;
};

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const STORAGE_KEY = "aitrade.theme";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>("dark");

  useEffect(() => {
    (async () => {
      const saved = await storage.getItem<string>(STORAGE_KEY, "");
      if (saved === "dark" || saved === "light") setModeState(saved);
      // Default = dark (Pro Exchange aesthetic). User can toggle.
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setMode = (m: ThemeMode) => {
    setModeState(m);
    void storage.setItem(STORAGE_KEY, m);
  };
  const toggle = () => setMode(mode === "dark" ? "light" : "dark");

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, colors: palette[mode], toggle, setMode }),
    [mode],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
