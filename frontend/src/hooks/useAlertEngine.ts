/**
 * useAlertEngine — evaluates saved price alerts against the current
 * dashboard prices and fires a local notification when a target crosses.
 *
 * Intended to be mounted ONCE in the dashboard (`app/index.tsx`) so it
 * receives every 60-second refresh via the `data` prop.  Non-crypto and
 * crypto assets both flow through the same code path — the trigger only
 * cares about a numeric price crossing.
 *
 * One-shot behaviour: once triggered, the alert flips `enabled=false`
 * (via `markAlertTriggered`) so it doesn't spam on subsequent ticks.
 */
import * as Notifications from "expo-notifications";
import { useEffect, useRef } from "react";
import { Platform } from "react-native";

import type { AssetSignal } from "@/src/lib/api";
import { getAlertsSync, markAlertTriggered, type AlertRow } from "@/src/lib/alerts";

async function fireAlertNotif(alert: AlertRow, price: number) {
  const dirText = alert.direction === "above" ? "melewati atas" : "turun di bawah";
  const title = `🔔 Alarm ${alert.symbol}`;
  const body = `Harga ${alert.symbol} ${dirText} ${alert.target}. Sekarang: ${price.toFixed(4)}`;
  // On web, `scheduleNotificationAsync` is a no-op; use a browser
  // Notification if permission was granted.  Native devices use
  // scheduleNotificationAsync via expo-notifications.
  try {
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && (window as any).Notification) {
        if ((window as any).Notification.permission === "granted") {
          // eslint-disable-next-line no-new
          new (window as any).Notification(title, { body });
        }
      }
      return;
    }
    await Notifications.scheduleNotificationAsync({
      content: {
        title,
        body,
        data: {
          deeplink: `/asset/${alert.market}/${alert.symbol}`,
          alertId: alert.id,
        },
      },
      trigger: null,
    });
  } catch {
    /* silent — never block the render loop on a notif failure */
  }
}

function evaluate(alert: AlertRow, price: number): boolean {
  if (!Number.isFinite(price) || !alert.enabled) return false;
  if (alert.direction === "above") return price >= alert.target;
  return price <= alert.target;
}

/**
 * The engine.  Receives the currently-loaded dashboard data map and runs
 * a check every time it changes.  Uses a ref to remember the last price
 * per alert so a threshold that crosses BETWEEN ticks still fires exactly
 * once (rather than every subsequent tick until reset).
 */
export function useAlertEngine(
  data: Record<string, AssetSignal[]>,
): void {
  const lastFiredRef = useRef<Record<string, number>>({});

  useEffect(() => {
    const alerts = getAlertsSync().filter((a) => a.enabled);
    if (alerts.length === 0) return;
    for (const alert of alerts) {
      const pool = data[alert.market];
      if (!pool) continue;
      const asset = pool.find(
        (a) => a.symbol.toUpperCase() === alert.symbol.toUpperCase(),
      );
      if (!asset) continue;
      const price = Number(asset.price);
      if (!Number.isFinite(price)) continue;
      if (evaluate(alert, price)) {
        // Debounce: don't refire within 5 minutes even if the flag hasn't
        // been persisted yet (protects against rapid consecutive ticks).
        const lastFired = lastFiredRef.current[alert.id] || 0;
        if (Date.now() - lastFired < 5 * 60 * 1000) continue;
        lastFiredRef.current[alert.id] = Date.now();
        void fireAlertNotif(alert, price);
        markAlertTriggered(alert.id);
      }
    }
  }, [data]);
}
