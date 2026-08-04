/**
 * <PushRegistrar /> — invisible component that watches the current
 * subscription state and (re)registers for push notifications when the
 * user becomes Premium.
 *
 * Requirements (v8.3.0):
 *  - Only prompt after the user has subscribed. Non-premium users are never
 *    interrupted by the notification dialog.
 *  - Language cohort follows `useI18n().lang`. If the user changes language
 *    later, silently re-register so the backend routes them to the correct
 *    slot (id → 08:45 IDX pre-market, en → 08:45 Asia session, etc.).
 *  - Never crash the app tree — swallow all errors silently.
 */
import { useEffect, useRef } from "react";

import { useI18n } from "@/src/i18n/I18nContext";
import { useSubscription } from "@/src/lib/subscriptionContext";
import {
  refreshPushLanguageIfRegistered,
  registerForPushIfEligible,
} from "@/src/lib/pushRegistrar";

export function PushRegistrar() {
  const { isPremium } = useSubscription();
  const { lang } = useI18n();
  // Track whether we've already run the pre-permission flow for this
  // premium session — prevents re-showing the dialog on every re-render.
  const promptedRef = useRef(false);

  useEffect(() => {
    if (!isPremium) return;
    if (promptedRef.current) {
      // Already prompted — just make sure the backend has the current lang.
      refreshPushLanguageIfRegistered(lang).catch(() => {});
      return;
    }
    promptedRef.current = true;
    registerForPushIfEligible(lang).catch(() => {});
  }, [isPremium, lang]);

  return null;
}
