/**
 * v8.12.36 — Dashboard chatroom presence badge.
 *
 * Lightweight hook that polls `/chat/online` every ONLINE_POLL_MS to
 * keep a live count of how many members are currently sitting inside
 * the chatroom. Used by the CHATROOM button on the dashboard to show
 * a coloured badge whenever at least one other member is online, so
 * users know when it's worth peeking inside.
 *
 * The endpoint also accepts an optional `device_id` heartbeat so the
 * caller can keep itself in the presence roll while polling. We only
 * heartbeat when the caller has premium access (i.e. the CHATROOM is
 * actually visible to them) — this avoids inflating the count with
 * anonymous browsers.
 */
import { useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

import { getDeviceId } from "@/src/lib/deviceId";

const ONLINE_POLL_MS = 20_000; // 20s cadence — cheap presence read.

function backendBase(): string {
  const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
  return `${RAW.replace(/\/+$/, "")}/api`;
}

export function useChatPresence(opts?: { heartbeat?: boolean }): number {
  const [online, setOnline] = useState<number>(0);
  const heartbeat = !!opts?.heartbeat;
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const fetchOnce = async () => {
      try {
        const did = heartbeat ? await getDeviceId() : "";
        const qs = did ? `?device_id=${encodeURIComponent(did)}` : "";
        const res = await fetch(`${backendBase()}/chat/online${qs}`);
        if (!res.ok) return;
        const j = await res.json();
        if (!cancelledRef.current && typeof j?.online === "number") {
          setOnline(j.online);
        }
      } catch {
        /* silent — badge just stays at last value */
      }
    };

    const loop = async () => {
      await fetchOnce();
      if (cancelledRef.current) return;
      timer = setTimeout(loop, ONLINE_POLL_MS);
    };
    loop();

    // Refresh instantly when the app comes back to the foreground so
    // the badge feels alive after returning from another app.
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active" && !cancelledRef.current) fetchOnce();
    });

    return () => {
      cancelledRef.current = true;
      if (timer) clearTimeout(timer);
      sub.remove();
    };
  }, [heartbeat]);

  return online;
}
