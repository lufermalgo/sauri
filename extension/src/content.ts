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

// --- State tracking ---

let meetDetected = false;
let meetEnded = false;

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
  const activeElement = findElementByAriaLabel(ACTIVE_CALL_SIGNALS);
  const endElement = findElementByAriaLabel(END_SIGNALS);

  if (endElement && !meetEnded) {
    // Meeting has ended
    meetEnded = true;
    meetDetected = false;
    console.log("[sauri] Meeting ended detected");
    chrome.runtime.sendMessage({ type: "meet-ended" });
    return;
  }

  if (activeElement && !meetDetected) {
    // Active call detected
    meetDetected = true;
    meetEnded = false;
    const meetingTitle = extractMeetingTitle();
    console.log(`[sauri] Active meeting detected: "${meetingTitle}"`);
    chrome.runtime.sendMessage({
      type: "meet-detected",
      meetingTitle,
      url: window.location.href,
    });
  }
}

// --- MutationObserver to watch for DOM changes ---

const observer = new MutationObserver(() => {
  checkMeetState();
});

observer.observe(document.body, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["aria-label"],
});

// Initial check in case the page is already in a call
checkMeetState();
