// Content script inyectado en https://meet.google.com/*
// Detecta la reunión activa por atributos ARIA (es/en), notifica al background service worker.
// Muestra banner de consentimiento de grabación en Shadow DOM (Notificacion_De_Grabacion).

export {};

console.log("[sauri] Content script loaded on Meet page");

// --- Consent banner (Shadow DOM) ---

let bannerHost: HTMLElement | null = null;

function showConsentBanner(): void {
  // Avoid duplicates
  if (bannerHost && document.body.contains(bannerHost)) return;

  // Create host element
  bannerHost = document.createElement("div");
  bannerHost.id = "sauri-consent-banner-host";
  document.body.appendChild(bannerHost);

  // Attach Shadow DOM to isolate styles from Meet's CSS
  const shadow = bannerHost.attachShadow({ mode: "closed" });

  // Banner markup
  const wrapper = document.createElement("div");
  wrapper.innerHTML = `
    <style>
      .sauri-banner {
        position: fixed;
        top: 8px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 2147483647;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 14px;
        background: rgba(30, 30, 30, 0.92);
        color: #fff;
        font-family: 'Google Sans', Roboto, Arial, sans-serif;
        font-size: 13px;
        border-radius: 20px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        backdrop-filter: blur(4px);
        user-select: none;
      }
      .sauri-banner .rec-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #d93025;
        animation: pulse 1.5s infinite;
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }
      .sauri-banner .dismiss-btn {
        background: none;
        border: none;
        color: #aaa;
        cursor: pointer;
        font-size: 16px;
        line-height: 1;
        padding: 0 0 0 6px;
      }
      .sauri-banner .dismiss-btn:hover {
        color: #fff;
      }
    </style>
    <div class="sauri-banner">
      <span class="rec-dot"></span>
      <span>sauri está grabando esta reunión</span>
      <button class="dismiss-btn" aria-label="Cerrar">✕</button>
    </div>
  `;
  shadow.appendChild(wrapper);

  // Dismiss handler
  const dismissBtn = shadow.querySelector(".dismiss-btn");
  dismissBtn?.addEventListener("click", () => {
    bannerHost?.remove();
    bannerHost = null;
  });

  // Record timestamp of notification emission (emitida_en)
  const emitidaEn = new Date().toISOString();
  console.log(`[sauri] Consent banner shown, emitida_en: ${emitidaEn}`);

  // Notify background of the emission timestamp
  chrome.runtime.sendMessage({
    type: "notification-emitted",
    emitidaEn,
  });
}

// --- Listen for show-consent-banner message from background ---

chrome.runtime.onMessage.addListener(
  (message: { type: string }, _sender, sendResponse) => {
    if (message.type === "show-consent-banner") {
      showConsentBanner();
      sendResponse({ ok: true });
    }
    return false;
  }
);

// --- ARIA-based detection signals (English / Spanish variants) ---

const ACTIVE_CALL_SIGNALS: string[] = [
  // English
  "Leave call",
  "Turn off microphone",
  "Turn on microphone",
  "Turn off camera",
  "Turn on camera",
  // Spanish
  "Salir de la llamada",
  "Desactivar micrófono",
  "Activar micrófono",
  "Desactivar cámara",
  "Activar cámara",
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
  // Spanish
  "Presentar ahora",
  "Dejar de presentar",
  "Estás presentando",
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
