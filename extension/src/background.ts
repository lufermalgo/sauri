// Service worker (MV3) — entry point for the sauri extension's background.
// Ephemeral state lives in chrome.storage.session (survives SW restarts within the session).
// NEVER use module-level variables for mutable state (the SW is ephemeral).

import {
  enqueueUpload,
  getNextPendingJob,
  markProcessing,
  markDone,
  markFailed,
} from "./upload-queue";
import { assembleBlob, clearSession } from "./recording-db";

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
  videoPresence?: "muxed" | "absent";
  micDeviceId?: string | null;
  notificationEmittedAt?: string;
  tabId?: number;
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
  mimeType: string,
  sessionId: string,
  notificationEmittedAt?: string,
  title?: string,
  meetLink?: string,
  videoPresence: "muxed" | "absent" = "absent"
): Promise<void> {
  try {
    // Read Blob directly from shared sauri-recordings IndexedDB
    const blob = await assembleBlob(sessionId, mimeType);

    // Build IngestionData JSON payload
    const ingestionData = {
      meeting_id: crypto.randomUUID(),
      idempotency_key: sessionId,
      capture_origin: "chrome_extension",
      duration_seconds: 0,
      interrupted: false,
      video_presence: videoPresence,
      notice_issued_at: notificationEmittedAt ?? null,
      title: title ?? null,
      meet_link: meetLink ?? null,
    };

    const formData = new FormData();
    // Single WebM container with audio+video interleaved — send as "audio"
    formData.append("audio", blob, "recording.webm");
    formData.append("data", JSON.stringify(ingestionData));

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

    const response = await fetch(`${BACKEND_URL}/api/v1/ingestion/upload`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (response.ok) {
      const result = await response.json();
      console.log("[sauri] Upload successful:", result);
      // Clear chunks from IndexedDB after successful upload
      await clearSession(sessionId);
    } else {
      throw new Error(`Upload failed: ${response.status} ${response.statusText}`);
    }
  } catch (error) {
    console.error("[sauri] Upload error:", error);
    throw error;
  }
}

// --- Side Panel (Req. 1.1, 1.2, 1.7) ---

async function configureSidePanel(): Promise<void> {
  try {
    // Do NOT use openPanelOnActionClick: true — that prevents onClicked from
    // firing, and without onClicked Chrome never grants activeTab on the
    // Meet tab (chrome.tabCapture.getMediaStreamId requires it). Instead we
    // open the panel manually from onClicked (Req. 1.1).
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false });
  } catch (error) {
    console.error("[sauri] Could not configure the Side_Panel:", error);
  }
}

chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id) {
    await chrome.sidePanel.open({ tabId: tab.id });
  }
});

// --- Initialization ---

chrome.runtime.onInstalled.addListener(async () => {
  await setState(DEFAULT_STATE);
  await configureSidePanel();
  console.log("[sauri] Extension installed, state initialized to idle");
});

configureSidePanel();

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const state = await getState();
  if (state.status === "recording" && state.tabId === tabId) {
    await handleStopCapture();
  }
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
      size?: number;
      mimeType?: string;
      sessionId?: string;
      error?: string;
      resolution?: Resolution;
      captureMode?: CaptureMode;
      videoPresence?: "muxed" | "absent";
      micDeviceId?: string | null;
      emittedAt?: string;
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
        handleRecordingStopped(message.size!, message.mimeType!, message.sessionId);
        sendResponse({ ok: true });
        break;

      case "capture-video-presence":
        handleCaptureVideoPresence(message.videoPresence);
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
        handleNotificationEmitted(message.emittedAt);
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

    // Ask the content script for the current title again: the one captured
    // when the meeting was detected (meet-detected) is usually the generic
    // "Meet" — Google Meet updates document.title with the real session name
    // a few seconds later. By the time recording starts it's usually current.
    let meetingTitle = currentState.meetingTitle;
    try {
      const response = (await chrome.tabs.sendMessage(tab.id!, { type: "get-current-title" })) as
        | { title?: string }
        | undefined;
      if (response?.title) meetingTitle = response.title;
    } catch (error) {
      console.warn("[sauri] Could not refresh meeting title:", error);
    }

    chrome.runtime.sendMessage({
      type: "start-recording",
      streamId,
      sessionId,
      resolution: res,
      captureMode,
      micDeviceId: micDeviceId ?? null,
    });

    // Update state to recording with sessionId, resolution, micDeviceId, and the
    // captured tab (needed later to dismiss the consent banner on that same tab)
    await setState({
      ...currentState,
      status: "recording",
      sessionId,
      resolution: res,
      micDeviceId,
      tabId: tab.id,
      meetingTitle,
    });
    console.log(`[sauri] Capture started — status: recording, sessionId: ${sessionId}, resolution: ${res.width}x${res.height}, mode: ${captureMode}, mic: ${micDeviceId ?? "none"}`);

    // Send consent banner to the content script in the active tab. Best-effort:
    // if the tab's content script isn't listening (e.g. stale after an extension
    // reload), don't let it surface as an unhandled rejection.
    chrome.tabs.sendMessage(tab.id!, { type: "show-consent-banner" }).catch((error) => {
      console.warn("[sauri] Could not show consent banner:", error);
    });

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

  await hideConsentBanner(currentState.tabId);

  // Enqueue upload job — the queue handles retries with the same idempotencyKey
  const sid = sessionId ?? crypto.randomUUID();
  await enqueueUpload({
    sessionId: sid,
    idempotencyKey: sid, // sessionId = idempotencyKey ensures idempotent retries
    mimeType,
    notificationEmittedAt,
    title: currentState.meetingTitle,
    meetLink: currentState.meetingUrl,
    videoPresence: currentState.videoPresence ?? "absent",
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

  const currentState = await getState();
  await hideConsentBanner(currentState.tabId);

  await setState(DEFAULT_STATE);
  console.log("[sauri] Recording error, state reset to idle");
}

async function hideConsentBanner(tabId?: number): Promise<void> {
  if (!tabId) return;
  try {
    await chrome.tabs.sendMessage(tabId, { type: "hide-consent-banner" });
  } catch (error) {
    console.warn("[sauri] Could not hide consent banner:", error);
  }
}

async function handleNotificationEmitted(emittedAt?: string): Promise<void> {
  if (!emittedAt) return;
  const currentState = await getState();
  await setState({ ...currentState, notificationEmittedAt: emittedAt });
  console.log(`[sauri] Notification emitted at: ${emittedAt}`);
}

async function handleCaptureVideoPresence(
  videoPresence?: "muxed" | "absent"
): Promise<void> {
  if (!videoPresence) return;
  const currentState = await getState();
  await setState({ ...currentState, videoPresence });
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
 * and marks done/failed accordingly. Uses the same idempotencyKey
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
    await uploadRecording(
      job.mimeType,
      job.sessionId,
      job.notificationEmittedAt,
      job.title,
      job.meetLink,
      job.videoPresence ?? "absent"
    );
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
