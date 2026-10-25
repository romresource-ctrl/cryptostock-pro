/**
 * v8.12.43 — Global "app is ready" signal.
 *
 * Tiny module-scope pub/sub so the Disclaimer + Privacy popups can wait
 * for the dashboard to finish loading its first market batch before they
 * take over the screen. Ensures snapshot / gallery-preview systems
 * (Emergent contest capture, App-Store screenshot bot, etc.) grab a
 * fully populated dashboard rather than the blocking legal modal.
 *
 * Contract:
 *   - Dashboard calls `markAppReady()` once its first data payload has
 *     rendered (i.e. asset cards are visible).
 *   - Consumers call `waitForAppReady()` and get a Promise that resolves
 *     immediately if the flag is already set, otherwise the next time it
 *     flips true. Also accepts a `timeoutMs` fallback so we never block
 *     forever if the dashboard fails to load (e.g. offline).
 */

let _ready = false;
const _waiters: (() => void)[] = [];

export function markAppReady(): void {
  if (_ready) return;
  _ready = true;
  // v10.4.1 — web: splash HTML tetap tampil sampai dashboard benar-benar
  // terisi data (snapshot/thumbnail tidak menangkap skeleton "Syncing").
  try {
    const el = (globalThis as any).document?.getElementById?.("ai-splash");
    if (el) setTimeout(() => el.remove(), 400);
  } catch {
    /* ignore */
  }
  const w = _waiters.splice(0);
  w.forEach((fn) => {
    try {
      fn();
    } catch {
      /* ignore */
    }
  });
}

export function isAppReady(): boolean {
  return _ready;
}

export function waitForAppReady(timeoutMs = 8000): Promise<void> {
  if (_ready) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      resolve();
    };
    _waiters.push(finish);
    if (timeoutMs > 0) {
      setTimeout(finish, timeoutMs);
    }
  });
}
