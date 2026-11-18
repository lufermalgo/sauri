// On-demand injection of the recording overlay into the tab being recorded.
// Least privilege: no broad host permissions. The grant comes from `activeTab`
// (the user opened Sauri from that tab); where Chrome refuses, the recording
// still works through the side panel and the tab simply gets no overlay.

import overlayScript from "./overlay/entry?iife";
import { canCaptureCurrentTab, isMeetUrl } from "./core/capture";

/**
 * Makes sure the overlay script runs in the tab. Returns whether the overlay can be
 * reached. Meet tabs already host it through the static content script. Calling this
 * again on the same page is harmless: the script installs itself only once.
 */
export async function ensureOverlay(tabId: number, url?: string): Promise<boolean> {
  if (isMeetUrl(url)) return true;
  if (!canCaptureCurrentTab(url)) return false;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: [overlayScript] });
    return true;
  } catch (error) {
    // Typical causes: no grant for this tab (activeTab expired or never given), the PDF
    // viewer, or a page that closed meanwhile. Never fatal for the recording.
    console.warn("[sauri] Overlay unavailable on this tab:", error);
    return false;
  }
}

/**
 * Injects the overlay again, replacing a script orphaned by an extension reload. Meet's static
 * content script stops answering after a reload until the tab is refreshed; this recovers it.
 */
export async function reinjectOverlay(tabId: number): Promise<boolean> {
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: [overlayScript] });
    return true;
  } catch (error) {
    console.warn("[sauri] Could not reinject the overlay:", error);
    return false;
  }
}
