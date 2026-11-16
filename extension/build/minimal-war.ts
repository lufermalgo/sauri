// Keeps web_accessible_resources (WAR) to what a web page really has to load.
//
// CRXJS lists every dynamically injected script (`import x from "./entry?iife"`) as a
// WAR for http://*/* and https://*/*, which lets any website fetch it or probe for the
// extension. Files injected with chrome.scripting.executeScript({ files }) are loaded
// by the extension itself and need no WAR, so they are removed here.

/** Scripts injected on demand by the service worker (see src/overlay-injection.ts). */
export const EXTENSION_INJECTED_FILES = ["src/overlay/entry.js"];

const BROAD_MATCHES = new Set(["<all_urls>", "*://*/*", "http://*/*", "https://*/*"]);

interface WarEntry {
  resources: string[];
  matches?: string[];
  [key: string]: unknown;
}

interface ManifestWithWar {
  web_accessible_resources?: WarEntry[];
  [key: string]: unknown;
}

/** Drops injected-only files from the WAR and refuses any entry open to every website. */
export function minimizeWebAccessibleResources<T extends ManifestWithWar>(manifest: T, injectedFiles = EXTENSION_INJECTED_FILES): T {
  const kept = (manifest.web_accessible_resources ?? [])
    .map((entry) => ({ ...entry, resources: entry.resources.filter((resource) => !injectedFiles.includes(resource)) }))
    .filter((entry) => entry.resources.length > 0);
  const broad = kept.find((entry) => (entry.matches ?? []).some((match) => BROAD_MATCHES.has(match)));
  if (broad) {
    throw new Error(`web_accessible_resources must not be open to every website: ${JSON.stringify(broad)}`);
  }
  const result = { ...manifest };
  if (kept.length > 0) result.web_accessible_resources = kept;
  else delete result.web_accessible_resources;
  return result;
}

/** CRXJS plugin hook: runs after CRXJS has computed the generated WAR. */
export function minimalWebAccessibleResources() {
  return {
    name: "sauri:minimal-web-accessible-resources",
    enforce: "post" as const,
    renderCrxManifest(manifest: ManifestWithWar) {
      return minimizeWebAccessibleResources(manifest);
    },
  };
}
