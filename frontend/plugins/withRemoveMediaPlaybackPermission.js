/**
 * withRemoveMediaPlaybackPermission — Expo config plugin.
 *
 * Purpose (v8.5.5):
 *   expo-audio auto-declares android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK
 *   AND registers a matching <service …foregroundServiceType="mediaPlayback">
 *   entry in its own AndroidManifest.xml (see node_modules/expo-audio/android/
 *   src/main/AndroidManifest.xml). That capability is intended for music/video
 *   players and Google Play blocks its use in apps that do not perform
 *   user-noticeable media playback (trading/signal apps, in our case). This
 *   plugin strips BOTH the permission AND the matching service node from the
 *   merged AndroidManifest.xml before Gradle assembles the APK/AAB.
 *
 * How it works:
 *   - Uses `tools:node="remove"` marker (manifest-merger directive) so the
 *     permission and service are deleted from the final manifest even if a
 *     downstream library re-declares them.
 *   - Ensures the `xmlns:tools` namespace is registered on the <manifest>
 *     root element (required for `tools:*` attributes to be honored).
 *   - Applied on top of expo-audio's config plugin, so record-audio and
 *     mic-related capabilities remain intact.
 */
const { withAndroidManifest } = require("@expo/config-plugins");

const BLOCKED_PERMISSIONS = [
  "android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK",
];

// Service nodes to strip. TEMPORARILY EMPTY (v8.5.9) — the service
// removal logic was untested against the real Android build and may be
// contributing to recent build failures. Keeping the array in place so
// we can re-enable specific entries once the base build is confirmed
// green. Permission-only removal (below) is the SAFE baseline and has
// shipped successfully before.
const BLOCKED_SERVICES = [];

// Ensures the manifest tag has `xmlns:tools`. Manifest-merger requires this
// namespace for the tools:node attribute to take effect.
function ensureToolsNamespace(manifest) {
  const attributes = manifest.$ ?? {};
  if (!attributes["xmlns:tools"]) {
    attributes["xmlns:tools"] = "http://schemas.android.com/tools";
    manifest.$ = attributes;
  }
}

// Adds or updates a <uses-permission> node with tools:node="remove". If an
// entry already exists we mutate it in-place to keep manifest order stable.
function upsertRemovalDeclaration(manifest, permissionName) {
  manifest["uses-permission"] = manifest["uses-permission"] ?? [];
  const entries = manifest["uses-permission"];
  const existing = entries.find(
    (e) => e && e.$ && e.$["android:name"] === permissionName,
  );
  if (existing) {
    existing.$["tools:node"] = "remove";
  } else {
    entries.push({
      $: {
        "android:name": permissionName,
        "tools:node": "remove",
      },
    });
  }
}

// Adds/updates a <service> node with tools:node="remove" under <application>.
// If a matching entry exists (by name or by foregroundServiceType), we mutate
// it in place; otherwise we append a minimal removal stub.
function upsertServiceRemoval(manifest, { nameMatch, typeMatch }) {
  const applications = manifest.application ?? [];
  if (applications.length === 0) return;
  const app = applications[0];
  app.service = app.service ?? [];
  const services = app.service;

  const existing = services.find((s) => {
    if (!s || !s.$) return false;
    const nm = s.$["android:name"];
    const fst = s.$["android:foregroundServiceType"];
    return (nameMatch && nm === nameMatch) || (typeMatch && fst === typeMatch);
  });

  if (existing) {
    existing.$["tools:node"] = "remove";
    // Ensure android:name is present when using tools:node="remove" so the
    // manifest-merger can target the correct service.
    if (nameMatch && !existing.$["android:name"]) {
      existing.$["android:name"] = nameMatch;
    }
  } else if (nameMatch) {
    services.push({
      $: {
        "android:name": nameMatch,
        "tools:node": "remove",
      },
    });
  }
}

const withRemoveMediaPlaybackPermission = (config) => {
  return withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults.manifest;
    ensureToolsNamespace(manifest);
    for (const perm of BLOCKED_PERMISSIONS) {
      upsertRemovalDeclaration(manifest, perm);
    }
    for (const svc of BLOCKED_SERVICES) {
      upsertServiceRemoval(manifest, svc);
    }
    return cfg;
  });
};

module.exports = withRemoveMediaPlaybackPermission;
