// v10.7.4 — Hitung mundur istirahat circuit-breaker (3 loss beruntun).
// Mandiri: poll /asi/scan-debug tiap 30 dtk, detak 1 dtk saat aktif.
import React, { useCallback, useEffect, useState } from "react";
import { Text, View } from "react-native";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/lib/api";
import { getDeviceId } from "@/src/lib/deviceId";
import { useI18n } from "@/src/i18n/I18nContext";

const GOLD = "#F0B90B";

export default function CbCountdown({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  const [resumeAt, setResumeAt] = useState<number>(NaN);
  const [now, setNow] = useState(() => Date.now());

  useFocusEffect(
    useCallback(() => {
      let alive = true;
      const tick = async () => {
        try {
          const did = await getDeviceId();
          const d: any = await api.asi.scanDebug(did);
          if (!alive) return;
          const r = d?.report;
          setResumeAt(r?.skip_code === "circuit_breaker"
            ? Date.parse(String(r?.skip_params?.resume_at || "")) : NaN);
        } catch { /* keep previous */ }
      };
      tick();
      const id = setInterval(tick, 30_000);
      return () => { alive = false; clearInterval(id); };
    }, [])
  );

  const active = Number.isFinite(resumeAt) && resumeAt > now;
  useEffect(() => {
    if (!Number.isFinite(resumeAt)) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [resumeAt]);

  if (!active) return null;
  const left = Math.floor((resumeAt - now) / 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  const txt = `⏳ ${t("asi_cb_resume").replace(
    "{t}", `${Math.floor(left / 3600)}:${pad(Math.floor((left % 3600) / 60))}:${pad(left % 60)}`)}`;
  return (
    <View testID="cb-countdown" style={{
      paddingHorizontal: compact ? 8 : 14, paddingVertical: compact ? 3 : 8,
      borderRadius: compact ? 6 : 10, borderWidth: 1.5, borderColor: GOLD,
      backgroundColor: "rgba(240,185,11,0.12)",
    }}>
      <Text style={{ color: GOLD, fontWeight: "900", fontSize: compact ? 11 : 15, letterSpacing: 0.4 }}>
        {txt}
      </Text>
    </View>
  );
}
