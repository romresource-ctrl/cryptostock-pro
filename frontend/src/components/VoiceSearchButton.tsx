/**
 * v8.12.37 — Voice Search button for the dashboard search bar.
 *
 * Cross-platform speech-to-text:
 *   - Native (iOS / Android APK/AAB build): `expo-speech-recognition`
 *   - Web preview: `window.SpeechRecognition` / webkit equivalent
 *   - Expo Go client (native module missing): friendly Alert
 *
 * v8.12.37 HOTFIX: The v8.12.36 listener wiring used
 *   `mod.addSpeechRecognitionListener("result", cb)` — a method that
 *   does NOT exist on `expo-speech-recognition`. The correct API is
 *   `ExpoSpeechRecognitionModule.addListener("result", cb)`. Because
 *   the listener never registered, the "result" event fired by the
 *   native recogniser was silently dropped and the search bar never
 *   filled in with the spoken symbol on APK builds. Fixed here.
 *
 * Behaviour:
 *   - Tap → check permission (contextual request if undetermined) →
 *     start listening. Icon animates red while active.
 *   - `result` event with `isFinal=true` → `onTranscript(cleaned)`,
 *     where cleaned = uppercase alphanumeric only (tickers).
 *   - Tap again while listening → stop.
 *   - Denied twice → Alert with "Open Settings" shortcut.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Animated, Easing, Linking, Platform, TouchableOpacity } from "react-native";

import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  onTranscript: (text: string) => void;
  size?: number;
  /** ISO language hint (e.g. "id-ID", "en-US"). Tickers are latin so
   * "en-US" tends to yield the highest accuracy across accents. */
  lang?: string;
};

// -----------------------------------------------------------------------
// Web fallback — window.SpeechRecognition / webkit variant.
// -----------------------------------------------------------------------
type BrowserSR = new () => any;
function getBrowserSR(): BrowserSR | null {
  if (typeof window === "undefined") return null;
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

// -----------------------------------------------------------------------
// Native lazy import — the module bundles native code that is missing in
// Expo Go / on web, so requiring it at top-level would crash there.
// -----------------------------------------------------------------------
let _nativeMod: any = null;
async function loadNativeMod(): Promise<any | null> {
  if (_nativeMod !== null) return _nativeMod || null;
  if (Platform.OS === "web") return null;
  try {
    _nativeMod = await import("expo-speech-recognition");
    return _nativeMod;
  } catch {
    _nativeMod = false;
    return null;
  }
}

function cleanTranscript(raw: string): string {
  // Whisper-ish normalisation for tickers: uppercase, alphanumeric only.
  return (raw || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export default function VoiceSearchButton({ onTranscript, size = 16, lang = "en-US" }: Props) {
  const { colors } = useTheme();
  const [listening, setListening] = useState(false);
  const activeRef = useRef(false);
  const pulse = useRef(new Animated.Value(1)).current;
  const webSRRef = useRef<any>(null);
  // Track subscriptions so we can tear them down when the mic stops.
  const subsRef = useRef<({ remove?: () => void } | null)[]>([]);

  // Pulse animation while listening.
  useEffect(() => {
    if (!listening) {
      pulse.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1.25,
          duration: 500,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: Platform.OS !== "web",
        }),
        Animated.timing(pulse, {
          toValue: 1,
          duration: 500,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: Platform.OS !== "web",
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [listening, pulse]);

  const cleanupSubs = useCallback(() => {
    subsRef.current.forEach((s) => {
      try {
        s?.remove?.();
      } catch {
        /* ignore */
      }
    });
    subsRef.current = [];
  }, []);

  const stop = useCallback(async () => {
    activeRef.current = false;
    setListening(false);
    try {
      webSRRef.current?.stop?.();
    } catch {
      /* ignore */
    }
    try {
      const mod = await loadNativeMod();
      mod?.ExpoSpeechRecognitionModule?.stop?.();
    } catch {
      /* ignore */
    }
    cleanupSubs();
  }, [cleanupSubs]);

  const startWeb = useCallback(() => {
    const SR = getBrowserSR();
    if (!SR) {
      Alert.alert(
        "Voice search unavailable",
        "Your browser does not support speech recognition. Try Chrome or Safari.",
      );
      return;
    }
    try {
      const rec = new SR();
      rec.lang = lang;
      rec.interimResults = false;
      rec.continuous = false;
      rec.maxAlternatives = 1;
      rec.onstart = () => {
        activeRef.current = true;
        setListening(true);
      };
      rec.onerror = () => {
        activeRef.current = false;
        setListening(false);
      };
      rec.onend = () => {
        activeRef.current = false;
        setListening(false);
      };
      rec.onresult = (evt: any) => {
        try {
          const text = evt?.results?.[0]?.[0]?.transcript ?? "";
          const cleaned = cleanTranscript(text);
          if (cleaned) onTranscript(cleaned);
        } catch {
          /* ignore */
        }
      };
      webSRRef.current = rec;
      rec.start();
    } catch (e: any) {
      Alert.alert("Voice search error", e?.message || "Could not start voice search.");
    }
  }, [lang, onTranscript]);

  const startNative = useCallback(async () => {
    const mod = await loadNativeMod();
    const M = mod?.ExpoSpeechRecognitionModule;
    if (!M) {
      Alert.alert(
        "Voice search not available",
        "Voice search requires the APK/AAB build of the app (not Expo Go). Please generate a new build to enable it.",
      );
      return;
    }
    try {
      // Permission contract: check → request → settings fallback.
      let perm: any = null;
      try {
        perm = await M.getPermissionsAsync?.();
      } catch {
        perm = null;
      }
      if (!perm?.granted) {
        const asked = await M.requestPermissionsAsync?.();
        if (!asked?.granted) {
          if (asked?.canAskAgain === false) {
            Alert.alert(
              "Microphone permission needed",
              "Enable microphone + speech recognition for AI Crypto Stock Pro in Settings.",
              [
                { text: "Cancel", style: "cancel" },
                { text: "Open Settings", onPress: () => Linking.openSettings() },
              ],
            );
          }
          return;
        }
      }

      // Clean up any leftover subscriptions from a previous session.
      cleanupSubs();

      // v8.12.37 — Correct API: ExpoSpeechRecognitionModule.addListener.
      const onResult = (evt: any) => {
        try {
          // Only accept the FINAL transcript. Partial (isFinal=false)
          // events would spam the search bar mid-sentence.
          if (evt && evt.isFinal === false) return;
          const text = evt?.results?.[0]?.transcript ?? "";
          const cleaned = cleanTranscript(text);
          if (cleaned) onTranscript(cleaned);
        } catch {
          /* ignore */
        }
      };
      const onEnd = () => {
        activeRef.current = false;
        setListening(false);
        cleanupSubs();
      };
      const onErr = (evt: any) => {
        activeRef.current = false;
        setListening(false);
        cleanupSubs();
        const code = evt?.error || "unknown";
        if (code === "not-allowed" || code === "service-not-allowed") {
          Alert.alert(
            "Microphone blocked",
            "Please allow microphone access in your device Settings.",
            [
              { text: "Cancel", style: "cancel" },
              { text: "Open Settings", onPress: () => Linking.openSettings() },
            ],
          );
        } else if (code === "no-speech" || code === "aborted") {
          // Silent — user just didn't say anything.
        } else if (code === "network") {
          Alert.alert("Voice search offline", "Voice recognition needs an internet connection on this device.");
        }
      };
      subsRef.current = [
        M.addListener?.("result", onResult) ?? null,
        M.addListener?.("end", onEnd) ?? null,
        M.addListener?.("error", onErr) ?? null,
      ];

      activeRef.current = true;
      setListening(true);
      M.start({
        lang,
        interimResults: false,
        continuous: false,
        maxAlternatives: 1,
      });
    } catch (e: any) {
      activeRef.current = false;
      setListening(false);
      cleanupSubs();
      Alert.alert("Voice search error", e?.message || "Could not start voice search.");
    }
  }, [cleanupSubs, lang, onTranscript]);

  const onPress = useCallback(async () => {
    if (activeRef.current) {
      stop();
      return;
    }
    if (Platform.OS === "web") startWeb();
    else await startNative();
  }, [startNative, startWeb, stop]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      cleanupSubs();
    };
  }, [cleanupSubs]);

  return (
    <TouchableOpacity
      onPress={onPress}
      hitSlop={8}
      style={{ paddingHorizontal: 6 }}
      testID="voice-search-button"
      accessibilityLabel="Voice search"
    >
      <Animated.View style={{ transform: [{ scale: pulse }] }}>
        <Ionicons
          name={listening ? "mic" : "mic-outline"}
          size={size}
          color={listening ? "#EF4444" : colors.textMuted}
        />
      </Animated.View>
    </TouchableOpacity>
  );
}
