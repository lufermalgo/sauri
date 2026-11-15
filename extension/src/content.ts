// Content script injected into https://meet.google.com/*
// Detects the active meeting via ARIA attributes (es/en), notifies the background service worker.
// Shows a recording consent banner in Shadow DOM (Recording_Notice).

import { cancelCountdown, hideRecordingUI, showCountdown, showNotice, syncRecordingUI, type RecordingUI } from "./overlay/recording";

function showConsentBanner(): void {
  if (showNotice()) {
    void chrome.runtime.sendMessage({ type: "notification-emitted", emittedAt: new Date().toISOString() });
  }
}

chrome.runtime.onMessage.addListener(
  (message: { type: string; seconds?: number; requestId?: string; state?: RecordingUI }, _sender, sendResponse) => {
    if (message.type === "show-consent-banner") {
      showConsentBanner();
      sendResponse({ ok: true });
    } else if (message.type === "hide-consent-banner") {
      hideRecordingUI();
      sendResponse({ ok: true });
    } else if (message.type === "show-countdown" && message.seconds && message.requestId) {
      void (async () => { sendResponse(await showCountdown(message.seconds!, message.requestId!)); })();
      return true;
    } else if (message.type === "cancel-countdown") {
      cancelCountdown();
      sendResponse({ ok: true });
    } else if (message.type === "recording-ui" && message.state) {
      syncRecordingUI(message.state);
      sendResponse({ ok: true });
    } else if (message.type === "get-current-title") {
      sendResponse({ title: extractMeetingTitle() });
    }
    return false;
  }
);

// A reloaded Meet tab can restore controls without reading extension session storage.
void (async () => {
  try {
    const response = await chrome.runtime.sendMessage({ type: "get-recording-ui" });
    if (response?.state) { showConsentBanner(); syncRecordingUI(response.state); }
  } catch { /* An older extension worker may not support UI recovery yet. */ }
})();

// --- ARIA-based detection signals (English / Spanish variants) ---

const ACTIVE_CALL_SIGNALS: string[] = [
  // English
  "Leave call",
  "Turn off microphone",
  "Turn on microphone",
  "Turn off camera",
  "Turn on camera",
  // Spanish — literal ARIA labels Google Meet's Spanish UI renders, kept
  // verbatim so bilingual detection keeps working (not leftover domain code).
  "Salir de la llamada",
  "Desactivar micrófono", // spanish-sample-data
  "Activar micrófono", // spanish-sample-data
  "Desactivar cámara", // spanish-sample-data
  "Activar cámara", // spanish-sample-data
];

const END_SIGNALS: string[] = [
  // English
  "Return to home screen",
  "Rejoin",
  // Spanish
  "Volver a la pantalla de inicio",
  "Volver a unirse",
];

const SCREEN_SHARE_SIGNALS: string[] = [
  // English
  "Present now",
  "Stop presenting",
  "You are presenting",
  // Spanish — literal ARIA labels, see note above
  "Presentar ahora",
  "Dejar de presentar",
  "Estás presentando", // spanish-sample-data
];

// --- State machine (replaces boolean flags) ---

type MeetState = 'idle' | 'active' | 'ending' | 'ended';
let meetState: MeetState = 'idle';

// --- Debounce and confirmation timers ---

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
let endingConfirmTimer: ReturnType<typeof setTimeout> | null = null;

const DEBOUNCE_MS = 500;
const ENDING_CONFIRM_MS = 2000;

// --- Utilities ---

function findElementByAriaLabel(labels: string[]): Element | null {
  for (const label of labels) {
    const el = document.querySelector(`[aria-label="${label}"]`);
    if (el) return el;
  }
  return null;
}

function extractMeetingTitle(): string {
  // Try to extract from document title or data attributes
  const title = document.title.replace(/ - Google Meet$/, "").trim();
  return title || "Google Meet";
}

// --- Detection logic ---

function checkMeetState(): void {
  const hasActiveSignals = findElementByAriaLabel(ACTIVE_CALL_SIGNALS) !== null;
  const hasEndSignals = findElementByAriaLabel(END_SIGNALS) !== null;

  // Priority: ACTIVE_CALL_SIGNALS override END_SIGNALS
  if (hasActiveSignals) {
    // Cancel any pending ending confirmation
    if (endingConfirmTimer !== null) {
      clearTimeout(endingConfirmTimer);
      endingConfirmTimer = null;
    }

    // Only send meet-detected on transitions: idle → active, ended → active
    if (meetState === 'idle' || meetState === 'ended') {
      meetState = 'active';
      const meetingTitle = extractMeetingTitle();
      console.log(`[sauri] Active meeting detected: "${meetingTitle}"`);
      chrome.runtime.sendMessage({
        type: "meet-detected",
        meetingTitle,
        url: window.location.href,
      });
    } else if (meetState === 'ending') {
      // Active signals reappeared during confirmation — cancel ending
      meetState = 'active';
      console.log("[sauri] Ending cancelled — active signals reappeared");
    }
    // If already 'active', do nothing (deduplication)
    return;
  }

  if (hasEndSignals && !hasActiveSignals) {
    if (meetState === 'active') {
      // Begin ending transition — start confirmation timer
      meetState = 'ending';
      console.log("[sauri] End signals detected — waiting confirmation...");

      endingConfirmTimer = setTimeout(() => {
        endingConfirmTimer = null;
        // After confirmation period, check one more time
        const stillNoActive = findElementByAriaLabel(ACTIVE_CALL_SIGNALS) === null;
        if (stillNoActive && meetState === 'ending') {
          meetState = 'ended';
          console.log("[sauri] Meeting ended confirmed");
          chrome.runtime.sendMessage({ type: "meet-ended" });
        } else {
          // Active signals reappeared during confirmation
          meetState = 'active';
          console.log("[sauri] Ending cancelled during confirmation — active signals found");
        }
      }, ENDING_CONFIRM_MS);
    }
    // If already 'ending', 'ended', or 'idle' — do nothing
    return;
  }

  // No signals at all — could be loading or between states, do nothing
}

// --- MutationObserver with debounce ---

const observer = new MutationObserver(() => {
  // Debounce: clear any pending evaluation and wait for DOM to settle
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer);
  }
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    checkMeetState();
  }, DEBOUNCE_MS);
});

observer.observe(document.body, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["aria-label"],
});

// Initial check (bypasses debounce — no prior mutations to settle)
checkMeetState();
