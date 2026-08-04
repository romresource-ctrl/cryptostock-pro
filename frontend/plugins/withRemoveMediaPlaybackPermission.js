/**
 * withRemoveMediaPlaybackPermission — Expo config plugin.
 *
 * Purpose (v8.3.2):
 *   expo-audio auto-declares android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK
 *   in its own AndroidManifest.xml (see node_modules/expo-audio/android/
 *   src/main/AndroidManifest.xml). That permission is intended for music/
 *   video players and Google Play blocks its use in apps that do not
 *   perform user-noticeable media playback (trading/signal apps, in our
 *   case). This plugin strips the permission from the merged
 *   AndroidManifest.xml before Gradle assembles the APK/AAB.
 *
 * How it works:
 *   - Uses `tools:node="remove"` marker (manifest-merger directive) so the
 *     permission is deleted from the final manifest even if a downstream
 *     library re-declares it.
 *   - Ensures the `xmlns:tools` namespace is registered on the <manifest>
 *     root element (required for `tools:*` attributes to be honored).
 *   - Applied on top of expo-audio's config plugin, so record-audio and
 *     mic-related capabilities remain intact.
 */
const { withAndroidManifest } = require("@expo/config-plugins");

const BLOCKED_PERMISSIONS = [
  "android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK",
];

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

const withRemoveMediaPlaybackPermission = (config) => {
  return withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults.manifest;
    ensureToolsNamespace(manifest);
    for (const perm of BLOCKED_PERMISSIONS) {
      upsertRemovalDeclaration(manifest, perm);
    }
    return cfg;
  });
};

module.exports = withRemoveMediaPlaybackPermission;
