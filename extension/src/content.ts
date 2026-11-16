// Content script injected into https://meet.google.com/*
// Detects the active meeting via ARIA attributes (es/en), notifies the background service worker.
// Hosts the recording overlay (consent notice, countdown, floating controls) in Shadow DOM.
// Any other recorded tab receives the same overlay through overlay/entry.ts instead.

import { installOverlayMessaging } from "./overlay/messaging";

installOverlayMessaging({ currentTitle: () => extractMeetingTitle() });

// --- ARIA-based detection signals (English / Spanish variants) ---

const ACTIVE_CALL_SIGNALS: string[] = [
  // English
  "Leave call",
  "Turn off microphone",
  "Turn on microphone",
  "Turn off camera",
  "Turn on camera",
  // Spanish — literal ARIA labels Google Meet's Spanish UI renders. They are Meet's own texts, not
  // Sauri's: both languages are recognized whatever language the extension itself speaks.
  "Salir de la llamada",
  "Desactivar micrófono", // spanish-sample-data i18n-ignore
  "Activar micrófono", // spanish-sample-data i18n-ignore
  "Desactivar cámara", // spanish-sample-data i18n-ignore
  "Activar cámara", // spanish-sample-data i18n-ignore
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
  "Estás presentando", // spanish-sample-data i18n-ignore
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
