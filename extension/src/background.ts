// Service worker (MV3) — punto de entrada del background de la extensión sauri.
// Estado efímero en chrome.storage.session (sobrevive reinicios del SW dentro de la sesión).
// NUNCA usar variables de módulo para estado mutable (el SW es efímero).

import {
  enqueueUpload,
  getNextPendingJob,
  markProcessing,
  markDone,
  markFailed,
} from "./upload-queue";

export {};

// --- State interface ---

interface Resolution {
  width: number;
  height: number;
}

type CaptureMode = "screen_audio" | "audio_only";

interface SauriState {
  status: "idle" | "pending" | "recording";
  meetingUrl?: string;
  meetingTitle?: string;
  sessionId?: string;
  resolution?: Resolution;
  captureMode?: CaptureMode;
  micDeviceId?: string | null;
  notificationEmittedAt?: string;
}

const DEFAULT_STATE: SauriState = { status: "idle" };

// --- State helpers ---

async function getState(): Promise<SauriState> {
  const result = await chrome.storage.session.get("sauriState");
  return (result.sauriState as SauriState) ?? DEFAULT_STATE;
}

async function setState(state: SauriState): Promise<void> {
  await chrome.storage.session.set({ sauriState: state });
}

// --- Offscreen document management ---

const OFFSCREEN_URL = "src/offscreen.html";

async function ensureOffscreenDocument(): Promise<void> {
  // Check if the offscreen document already exists
  const existingContexts = await chrome.runtime.getContexts({
    contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_URL)],
  });

  if (existingContexts.length > 0) {
    return; // Already exists
  }

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: [chrome.offscreen.Reason.USER_MEDIA],
    justification: "Recording tab audio and video",
  });
  console.log("[sauri] Offscreen document created");
}

// --- Backend upload (PoC) ---

const BACKEND_URL = "http://localhost:8000";

async function uploadRecording(
  base64Data: string,
  mimeType: string,
  sessionId: string,
  notificationEmittedAt?: string
): Promise<void> {
  try {
    // Decode base64 to binary
    const binaryString = atob(base64Data);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: mimeType });

    // Build DatosIngesta JSON payload
    const datosIngesta = {
      reunion_id: crypto.randomUUID(),
      clave_idempotencia: sessionId,
      origen_captura: "extension_chrome",
      duracion_segundos: 0,
      interrumpida: false,
      notificacion_emitida_en: notificationEmittedAt ?? null,
    };

    const formData = new FormData();
    // Single WebM container with audio+video interleaved — send as "audio"
    formData.append("audio", blob, "recording.webm");
    formData.append("datos", JSON.stringify(datosIngesta));

    // Retrieve auth token from chrome.storage.sync (set by login flow)
    const headers: Record<string, string> = {};
    try {
      const stored = await chrome.storage.sync.get("authToken");
      if (stored.authToken) {
        headers["Authorization"] = `Bearer ${stored.authToken}`;
      } else {
        console.warn("[sauri] No authToken in storage — uploading without auth (dev mode)");
      }
    } catch (e) {
      console.warn("[sauri] Could not read authToken from storage:", e);
    }

    const response = await fetch(`${BACKEND_URL}/api/v1/ingesta/subir`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (response.ok) {
      const result = await response.json();
      console.log("[sauri] Upload successful:", result);
    } else {
      console.error("[sauri] Upload failed:", response.status, response.statusText);
    }
  } catch (error) {
    console.error("[sauri] Upload error:", error);
  }
}

// --- Initialization ---

chrome.runtime.onInstalled.addListener(async () => {
  await setState(DEFAULT_STATE);
  console.log("[sauri] Extension installed, state initialized to idle");
});

// On service worker startup, ensure state is loaded from session storage
// (chrome.storage.session persists across SW restarts within the browser session)
(async () => {
  const state = await getState();
  console.log("[sauri] Service worker started, current state:", state.status);
})();

// --- Message handling ---

chrome.runtime.onMessage.addListener(
  (
    message: {
      type: string;
      meetingTitle?: string;
      url?: string;
      base64Data?: string;
      size?: number;
      mimeType?: string;
      sessionId?: string;
      error?: string;
      resolution?: Resolution;
      captureMode?: CaptureMode;
      micDeviceId?: string | null;
      emitidaEn?: string;
    },
    _sender,
    sendResponse
  ) => {
    switch (message.type) {
      case "meet-detected":
        handleMeetDetected(message.meetingTitle, message.url);
        sendResponse({ ok: true });
        break;

      case "meet-ended":
        handleMeetEnded();
        sendResponse({ ok: true });
        break;

      case "start-capture":
        handleStartCapture(message.resolution, message.micDeviceId);
        sendResponse({ ok: true });
        break;

      case "stop-capture":
        handleStopCapture();
        sendResponse({ ok: true });
        break;

      case "recording-stopped":
        handleRecordingStopped(message.base64Data!, message.size!, message.mimeType!, message.sessionId);
        sendResponse({ ok: true });
        break;

      case "recording-error":
        console.error("[sauri] Recording error from offscreen:", message.error);
        handleRecordingError();
        sendResponse({ ok: true });
        break;

      case "set-capture-mode":
        handleSetCaptureMode(message.captureMode);
        sendResponse({ ok: true });
        break;

      case "notification-emitted":
        handleNotificationEmitted(message.emitidaEn);
        sendResponse({ ok: true });
        break;

      default:
        sendResponse({ ok: false, error: "unknown message type" });
    }
    return false;
  }
);

// --- Handlers ---

async function handleMeetDetected(
  meetingTitle?: string,
  url?: string
): Promise<void> {
  const newState: SauriState = {
    status: "pending",
    meetingUrl: url,
    meetingTitle: meetingTitle ?? "Google Meet",
  };
  await setState(newState);
  console.log(
    `[sauri] Meet detected — status: pending, title: "${newState.meetingTitle}"`
  );
}

async function handleMeetEnded(): Promise<void> {
  await setState(DEFAULT_STATE);
  console.log("[sauri] Meet ended — status: idle");
}

async function handleStartCapture(resolution?: Resolution, micDeviceId?: string | null): Promise<void> {
  try {
    // Default resolution to 720p if not provided
    const res: Resolution = resolution ?? { width: 1280, height: 720 };

    // Get the active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) {
      console.error("[sauri] No active tab found");
      return;
    }

    // Get the media stream ID for the tab
    // NOTE: this must be called from a user gesture context (panel click counts)
    // Wrap in promise since @types/chrome only exposes the callback overload
    const streamId = await new Promise<string>((resolve, reject) => {
      chrome.tabCapture.getMediaStreamId(
        { targetTabId: tab.id! },
        (id) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(id);
          }
        }
      );
    });

    console.log("[sauri] Got streamId for tab capture");

    // Generate a unique sessionId for this recording session
    const sessionId = crypto.randomUUID();

    // Ensure offscreen document exists
    await ensureOffscreenDocument();

    // Send start-recording message to offscreen document with sessionId, resolution, and micDeviceId
    const currentState = await getState();
    const captureMode: CaptureMode = currentState.captureMode ?? "screen_audio";

    chrome.runtime.sendMessage({
      type: "start-recording",
      streamId,
      sessionId,
      resolution: res,
      captureMode,
      micDeviceId: micDeviceId ?? null,
    });

    // Update state to recording with sessionId, resolution, and micDeviceId
    await setState({ ...currentState, status: "recording", sessionId, resolution: res, micDeviceId });
    console.log(`[sauri] Capture started — status: recording, sessionId: ${sessionId}, resolution: ${res.width}x${res.height}, mode: ${captureMode}, mic: ${micDeviceId ?? "none"}`);

    // Send consent banner to the content script in the active tab
    chrome.tabs.sendMessage(tab.id!, { type: "show-consent-banner" });

    // Set REC badge
    chrome.action.setBadgeText({ text: "REC" });
    chrome.action.setBadgeBackgroundColor({ color: "#d93025" });
  } catch (error) {
    console.error("[sauri] Failed to start capture:", error);
  }
}

async function handleStopCapture(): Promise<void> {
  // Send stop-recording message to offscreen document
  chrome.runtime.sendMessage({ type: "stop-recording" });
  console.log("[sauri] Stop capture requested");
}

async function handleRecordingStopped(
  base64Data: string,
  size: number,
  mimeType: string,
  sessionId?: string
): Promise<void> {
  console.log(`[sauri] Recording complete: ${size} bytes (session: ${sessionId ?? "unknown"})`);

  // Clear REC badge
  chrome.action.setBadgeText({ text: "" });

  // Get notificationEmittedAt from state for upload payload
  const currentState = await getState();
  const notificationEmittedAt = currentState.notificationEmittedAt;

  // Enqueue upload job — the queue handles retries with the same clave_idempotencia
  const sid = sessionId ?? crypto.randomUUID();
  await enqueueUpload({
    sessionId: sid,
    claveIdempotencia: sid, // sessionId = clave_idempotencia ensures idempotent retries
    blobBase64: base64Data,
    mimeType,
    notificationEmittedAt,
  });
  console.log(`[sauri] Upload job enqueued for session: ${sid}`);

  // Trigger immediate processing attempt
  await processUploadQueue();

  // Update state to idle
  await setState(DEFAULT_STATE);
  console.log("[sauri] State reset to idle");
}

async function handleRecordingError(): Promise<void> {
  // Clear REC badge
  chrome.action.setBadgeText({ text: "" });

  await setState(DEFAULT_STATE);
  console.log("[sauri] Recording error, state reset to idle");
}

async function handleNotificationEmitted(emitidaEn?: string): Promise<void> {
  if (!emitidaEn) return;
  const currentState = await getState();
  await setState({ ...currentState, notificationEmittedAt: emitidaEn });
  console.log(`[sauri] Notification emitted at: ${emitidaEn}`);
}

async function handleSetCaptureMode(captureMode?: CaptureMode): Promise<void> {
  const mode: CaptureMode = captureMode ?? "screen_audio";
  const currentState = await getState();
  await setState({ ...currentState, captureMode: mode });
  console.log(`[sauri] Capture mode set to: ${mode}`);
}

// --- Upload queue processing ---

const UPLOAD_ALARM_NAME = "sauri-upload-check";

/**
 * Processes the next pending job in the upload queue.
 * Gets the oldest pending job, marks it processing, attempts upload,
 * and marks done/failed accordingly. Uses the same clave_idempotencia
 * (= sessionId) so the backend won't create duplicates on retries.
 */
async function processUploadQueue(): Promise<void> {
  const job = await getNextPendingJob();
  if (!job) {
    return;
  }

  console.log(`[sauri] Processing upload job: ${job.id} (session: ${job.sessionId}, attempt: ${job.retryCount + 1})`);

  await markProcessing(job.id);

  try {
    await uploadRecording(job.blobBase64, job.mimeType, job.sessionId, job.notificationEmittedAt);
    await markDone(job.id);
    console.log(`[sauri] Upload job done: ${job.id}`);
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    await markFailed(job.id, errorMsg);
    console.warn(`[sauri] Upload job failed: ${job.id} — ${errorMsg}`);
  }
}

// --- Alarm-based retry (every 1 minute) ---

chrome.alarms.create(UPLOAD_ALARM_NAME, { periodInMinutes: 1 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === UPLOAD_ALARM_NAME) {
    processUploadQueue();
  }
});

// --- Recovery on browser startup ---

chrome.runtime.onStartup.addListener(() => {
  console.log("[sauri] Browser startup — processing upload queue for recovery");
  processUploadQueue();
});
