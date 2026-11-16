// Message wiring shared by the two scripts that can host the recording overlay:
// the static Meet content script and the script injected into any other recorded tab.
// Installation is idempotent per page and tolerates a script left behind by a
// previous extension load (its runtime context is gone, so it can no longer act).

import { initLanguage, watchLanguage } from "../i18n";
import { cancelCountdown, hideRecordingUI, showCountdown, showNotice, syncRecordingUI, type OverlayVariant, type RecordingUI } from "./recording";

const INSTALL_KEY = "__sauriOverlayInstall";
const OVERLAY_HOST_IDS = ["sauri-recording-host", "sauri-consent-banner-host", "sauri-countdown-host"];

interface OverlayInstall { alive(): boolean }

function contextAlive(): boolean {
  // An invalidated extension context reports no runtime id.
  try { return !!chrome.runtime?.id; } catch { return false; }
}

function pageVariant(): OverlayVariant {
  return location.hostname === "meet.google.com" ? "meeting" : "tab";
}

function showConsentBanner(): void {
  if (showNotice(pageVariant())) {
    void chrome.runtime.sendMessage({ type: "notification-emitted", emittedAt: new Date().toISOString() });
  }
}

interface OverlayMessage { type: string; seconds?: number; requestId?: string; state?: RecordingUI }

/**
 * Registers the overlay message handlers once per page. Returns false when a live
 * installation already exists. `currentTitle` answers `get-current-title` (Meet only).
 */
export function installOverlayMessaging(options: { currentTitle?: () => string } = {}): boolean {
  const holder = globalThis as unknown as Record<string, OverlayInstall | undefined>;
  const previous = holder[INSTALL_KEY];
  if (previous?.alive()) return false;
  // Controls bound by a dead script cannot reach the extension; start from a clean page.
  if (previous) OVERLAY_HOST_IDS.forEach(id => document.getElementById(id)?.remove());
  holder[INSTALL_KEY] = { alive: contextAlive };

  // The overlay speaks the language chosen in the options page, or the browser's.
  void initLanguage().catch(() => { /* Spanish stays when the preference cannot be read. */ });
  watchLanguage();

  chrome.runtime.onMessage.addListener(
    (message: OverlayMessage, _sender, sendResponse) => {
      if (message.type === "show-consent-banner") {
        showConsentBanner();
        sendResponse({ ok: true });
      } else if (message.type === "hide-consent-banner") {
        hideRecordingUI();
        sendResponse({ ok: true });
      } else if (message.type === "show-countdown" && message.seconds && message.requestId) {
        void (async () => { sendResponse(await showCountdown(message.seconds!, message.requestId!, pageVariant())); })();
        return true;
      } else if (message.type === "cancel-countdown") {
        cancelCountdown();
        sendResponse({ ok: true });
      } else if (message.type === "recording-ui" && message.state) {
        syncRecordingUI(message.state);
        sendResponse({ ok: true });
      } else if (message.type === "get-current-title" && options.currentTitle) {
        sendResponse({ title: options.currentTitle() });
      }
      return false;
    }
  );

  // A reloaded or navigated recorded tab restores its controls without session storage access.
  void (async () => {
    try {
      const response = await chrome.runtime.sendMessage({ type: "get-recording-ui" });
      if (response?.state) { showConsentBanner(); syncRecordingUI(response.state); }
    } catch { /* An older extension worker may not support UI recovery yet. */ }
  })();
  return true;
}
