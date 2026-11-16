// Service worker (MV3) — entry point for the sauri extension's background.
// Ephemeral state lives in chrome.storage.session (survives SW restarts within the session).
// NEVER use module-level variables for mutable state (the SW is ephemeral).

import {
  enqueueUpload,
  getUploadJob,
  getNextPendingJob,
  markProcessing,
  markDone,
  markFailed,
  type UploadJob,
} from "./upload-queue";
import { assembleBlob, clearSession, createCompletion, getCapturingCompletion, claimCompletion, getCompletion, getPendingFinalizations, settleCapture, bindRecordingId, setUploadOutcome, setProcessingStatus, getProcessingCompletions, claimReviewLaunch, claimReviewCreate, markReviewOpened, getPendingReviewLaunches, type RecordingCompletion } from "./recording-db";
import { resolveProcessingStatus } from "./core/processing-status";
import { matchesCaptureHandle, type CompletionTrigger, type CaptureHandle } from "./core/recording-completion";

import { canCaptureCurrentTab } from "./core/capture";
import type { CaptureSource, CaptureStartResult } from "./core/types";

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
  provider?: CaptureHandle["provider"];
  pickerSource?: CaptureSource;
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

async function ensureOffscreenDocument(): Promise<boolean> {
  // Check if the offscreen document already exists
  const existingContexts = await chrome.runtime.getContexts({
    contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT],
    documentUrls: [chrome.runtime.getURL(OFFSCREEN_URL)],
  });

  if (existingContexts.length > 0) {
    // An upgrade must not destroy a live (including legacy) recorder. Idle
    // documents are recreated so their creation reasons cannot remain stale.
    if ((await getState()).status === "recording") return false;
    const capture = await chrome.runtime.sendMessage({ type: "get-capture-status" });
    if (capture?.active) return false;
    await chrome.offscreen.closeDocument();
  }

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: [chrome.offscreen.Reason.DISPLAY_MEDIA, chrome.offscreen.Reason.USER_MEDIA],
    justification: "Recording tab audio and video",
  });
  console.log("[sauri] Offscreen document created");
  return true;
}

// --- Backend upload (PoC) ---

const BACKEND_URL = import.meta.env.VITE_SAURI_BACKEND_URL ?? "http://localhost:8000";

async function uploadRecording(job: UploadJob): Promise<void> {
  const { mimeType, sessionId, meetingId, notificationEmittedAt, title, meetLink } = job;
  const videoPresence = job.videoPresence ?? "absent";
  const completion = await getCompletion(sessionId);
  if (!meetingId || !completion || completion.meetingId !== meetingId || job.idempotencyKey !== sessionId) {
    throw new Error("Upload job has no matching persisted recording identity");
  }
  try {
    // Read Blob directly from shared sauri-recordings IndexedDB
    const blob = await assembleBlob(sessionId, mimeType);

    // Build IngestionData JSON payload
    const ingestionData = {
      meeting_id: meetingId,
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
      if (!result || typeof result.recording_id !== "string" || !result.recording_id.trim() ||
          result.recording_id !== result.recording_id.trim() ||
          !["queued", "joining", "recording", "transcribing", "completed", "failed"].includes(result.state)) {
        throw new Error("Invalid ingestion response identity or state");
      }
      await bindRecordingId(sessionId, meetingId, result.recording_id);
      // Keep chunks until the queue and completion outcome have both committed.
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
    // Opening via the action grants activeTab for the current-tab shortcut.
    // Keep onClicked firing; the picker mode does not need this grant.
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
  // Updates must not detach a still-live legacy offscreen capture.
  await setState(await getState());
  await configureSidePanel();
  console.log("[sauri] Extension installed, state initialized to idle");
});

configureSidePanel();

chrome.tabs.onRemoved.addListener(async (tabId) => {
  try {
    const record = await getCapturingCompletion(tabId);
    if (record) await completeRecording(record.sessionId, "captured-tab-close");
    else {
      // A live v1 capture has a session binding but no preallocated meeting ID.
      // Preserve that identity; never synthesize a completion row for legacy media.
      const state = await getState();
      if (state.status === "recording" && state.tabId === tabId && state.sessionId && !await getCompletion(state.sessionId)) {
        await chrome.runtime.sendMessage({ type: "stop-recording", sessionId: state.sessionId });
      }
    }
  } catch (error) {
    console.error("[sauri] Could not finalize captured tab:", error);
  }
});

// On service worker startup, ensure state is loaded from session storage
// (chrome.storage.session persists across SW restarts within the browser session)
(async () => {
  const state = await getState();
  console.log("[sauri] Service worker started, current state:", state.status);
  await resumeFinalizations();
  await reconcileReviewLaunches();
  await reconcilePendingProcessing();
})();

// --- Message handling ---

chrome.runtime.onMessage.addListener(
  (
    message: {
      type: string;
      source?: CaptureSource;
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
    // Page scripts can report discovery, not act as a media owner or a
    // capture control. A different provider tab must not mutate the capture.
    if (_sender.tab && ["start-capture", "capture-ready", "stop-capture", "recording-stopped", "recording-error", "capture-video-presence", "set-capture-mode"].includes(message.type)) {
      sendResponse({ ok: false, error: "Message requires an extension capture context" });
      return false;
    }
    switch (message.type) {
      case "meet-detected":
        handleMeetDetected(message.meetingTitle, message.url);
        sendResponse({ ok: true });
        break;

      case "meet-ended":
        handleMeetEnded();
        sendResponse({ ok: true });
        break;

      case "teams-ended":
        // A Teams capture handle can be supplied by an existing media owner,
        // but page lifecycle notifications are never a completion trigger.
        sendResponse({ ok: true });
        break;

      case "start-capture":
        void (async () => { sendResponse(await handleStartCapture(message.source ?? "picker", message.resolution, message.micDeviceId)); })();
        return true;

      case "capture-ready":
        void (async () => { sendResponse(await handleCaptureReady(message.sessionId)); })();
        return true;

      case "stop-capture":
        void (async () => {
          const stopped = await handleStopCapture();
          sendResponse({ ok: stopped });
        })();
        return true;

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
        void handleRecordingError(message.sessionId);
        sendResponse({ ok: true });
        break;

      case "set-capture-mode":
        handleSetCaptureMode(message.captureMode);
        sendResponse({ ok: true });
        break;

      case "notification-emitted":
        handleNotificationEmitted(message.emittedAt, _sender.tab?.id);
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
  if ((await getState()).status === "recording") return;
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
  const state = await getState();
  // A page discovery signal is not permission to stop or detach a capture.
  if (state.status === "recording") return;
  await setState(DEFAULT_STATE);
  console.log("[sauri] Meet ended — status: idle");
}

// Separate from sauriState: cancellation must not replace the prior projection.
interface CaptureRequest {
  state: SauriState & { sessionId: string; tabId: number };
  meetingId: string;
}

function isMeetUrl(url?: string): boolean {
  return !!url?.startsWith("https://meet.google.com/");
}

async function handleCaptureReady(sessionId?: string): Promise<{ ok: boolean }> {
  try {
    const stored = await chrome.storage.session.get("sauriCaptureRequest");
    const request = stored.sauriCaptureRequest as CaptureRequest | undefined;
    if (!request || request.state.sessionId !== sessionId) return { ok: false };
    const { state, meetingId } = request;
    await createCompletion({
      sessionId: state.sessionId, meetingId, provider: "meet",
      capturedTabId: state.tabId, status: "capturing", updatedAt: Date.now(),
    });
    await setState(state);
    return { ok: true };
  } catch (error) {
    console.error("[sauri] Could not bind selected media:", error);
    return { ok: false };
  }
}

async function handleStartCapture(source: CaptureSource, resolution?: Resolution, micDeviceId?: string | null): Promise<CaptureStartResult> {
  try {
    // Web Locks serialize competing panels without a stale service-worker flag.
    return await navigator.locks.request("sauri-capture-start", { ifAvailable: true }, async lock => {
      if (!lock || (await getState()).status === "recording") return { ok: false, reason: "busy" };
      let startingSessionId: string | undefined;
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab?.id === undefined) return { ok: false, reason: "failed" };
        if (source !== "picker" && source !== "current-tab") return { ok: false, reason: "failed" };
        let streamId: string | undefined;
        if (source === "current-tab") {
          if (!canCaptureCurrentTab(tab.url)) return { ok: false, reason: "current-tab-unavailable" };
          try {
            streamId = await new Promise<string>((resolve, reject) => {
              chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id! }, id => {
                if (chrome.runtime.lastError || !id) reject(new Error("Current tab capture permission unavailable"));
                else resolve(id);
              });
            });
          } catch {
            return { ok: false, reason: "current-tab-unavailable" };
          }
        }
        if (!await ensureOffscreenDocument()) return { ok: false, reason: "busy" };
        const currentState = await getState();
        const captureMode = currentState.captureMode ?? "screen_audio";
        const res = resolution ?? { width: 1280, height: 720 };
        const isMeet = isMeetUrl(tab.url);
        let meetingTitle = isMeet ? currentState.meetingTitle : undefined;
        if (isMeet) {
          try {
            const response = await chrome.tabs.sendMessage(tab.id, { type: "get-current-title" });
            if (response?.title) meetingTitle = response.title;
          } catch (error) {
            console.warn("[sauri] Could not refresh meeting title:", error);
          }
        }
        const sessionId = crypto.randomUUID();
        startingSessionId = sessionId;
        const request: CaptureRequest = {
          meetingId: crypto.randomUUID(),
          state: {
            status: "recording", sessionId, provider: "meet", resolution: res, pickerSource: source,
            captureMode, micDeviceId, tabId: tab.id, meetingTitle,
            meetingUrl: isMeet ? tab.url : "",
          },
        };
        await chrome.storage.session.set({ sauriCaptureRequest: request });
        // The offscreen binds this request only after the picker returns valid
        // media. No durable session or recording projection exists on cancel.
        const result: CaptureStartResult = await chrome.runtime.sendMessage({
          type: "start-recording", sessionId, source, ...(streamId ? { streamId } : {}), resolution: res, captureMode,
          micDeviceId: micDeviceId ?? null,
        });
        if (!result?.ok) {
          if (await getCompletion(sessionId)) await handleRecordingError(sessionId);
          return result ?? { ok: false, reason: "failed" };
        }
        const activeCapture = await getCompletion(sessionId);
        if (activeCapture?.status !== "capturing" || activeCapture.captureError) return result;
        if (isMeet) {
          try { await chrome.tabs.sendMessage(tab.id, { type: "show-consent-banner" }); }
          catch (error) { console.warn("[sauri] Could not show consent banner:", error); }
        }
        // Sharing may have ended while the banner message was in flight.
        if ((await getCompletion(sessionId))?.status === "capturing") {
          chrome.action.setBadgeText({ text: "REC" });
          chrome.action.setBadgeBackgroundColor({ color: "#d93025" });
        }
        return result;
      } catch (error) {
        console.error("[sauri] Failed to start capture:", error);
        if (startingSessionId && await getCompletion(startingSessionId)) await handleRecordingError(startingSessionId);
        return { ok: false, reason: "failed" };
      } finally {
        if (startingSessionId) {
          const stored = await chrome.storage.session.get("sauriCaptureRequest");
          if (stored.sauriCaptureRequest?.state.sessionId === startingSessionId) {
            await chrome.storage.session.remove("sauriCaptureRequest");
          }
        }
      }
    });
  } catch (error) {
    console.error("[sauri] Capture request unavailable:", error);
    return { ok: false, reason: "failed" };
  }
}

async function completeRecording(sessionId: string, trigger: CompletionTrigger): Promise<void> {
  if (!await claimCompletion(sessionId, trigger)) return;
  await requestMediaFinalization(sessionId);
}

async function requestMediaFinalization(sessionId: string): Promise<void> {
  const delivered = await chrome.runtime.sendMessage({ type: "stop-recording", sessionId });
  if (!delivered?.ok) {
    // The offscreen owner rejected this exact session; retain media and an
    // observable non-successful error rather than treating dispatch as capture.
    await settleCapture(sessionId, true);
    console.warn("[sauri] Media owner could not finalize the capture:", sessionId);
    return;
  }
  console.log("[sauri] Stop capture requested");
}

async function resumeFinalizations(): Promise<void> {
  try {
    for (const record of await getPendingFinalizations()) {
      await requestMediaFinalization(record.sessionId);
    }
  } catch (error) {
    // Leave the durable intent intact for the next worker/alarm retry.
    console.warn("[sauri] Finalization delivery pending:", error);
  }
}

async function handleStopCapture(): Promise<boolean> {
  try {
    const state = await getState();
    if (state.status !== "recording" || !state.sessionId || state.tabId === undefined) return false;
    const record = await getCapturingCompletion(state.tabId);
    const projected: CaptureHandle = {
      sessionId: state.sessionId,
      capturedTabId: state.tabId,
      // Pre-provider projections were Meet-only; never infer Teams from them.
      provider: state.provider ?? "meet",
    };
    if (record && matchesCaptureHandle(record, projected)) {
      await completeRecording(record.sessionId, "stop");
      return !(await getCompletion(record.sessionId))?.captureError;
    }
    const projectedRecord = await getCompletion(state.sessionId);
    if (projectedRecord) {
      // Only the projected session may receive this error. Never mark the
      // different handle found on this tab or finalize either capture.
      await settleCapture(projectedRecord.sessionId, true);
    } else if (!record && projected.provider === "meet") {
      // Preserve an actual v1 capture without inventing a durable Teams handle.
      const delivered = await chrome.runtime.sendMessage({ type: "stop-recording", sessionId: state.sessionId });
      return delivered?.ok === true;
    }
    return false;
  } catch (error) {
    console.error("[sauri] Could not finalize recording:", error);
    return false;
  }
}

async function handleRecordingStopped(
  size: number,
  mimeType: string,
  sessionId?: string
): Promise<void> {
  console.log(`[sauri] Recording complete: ${size} bytes (session: ${sessionId ?? "unknown"})`);

  if (!sessionId) return; // Never invent identity for an unbound completion.
  const completion = await getCompletion(sessionId);
  if (!completion || completion.captureError ||
      (completion.status !== "capturing" && completion.status !== "finalizing" && completion.status !== "upload_pending")) return;
  await settleCapture(sessionId);

  // Get notificationEmittedAt from state for upload payload
  const currentState = await getState();
  const ownsProjection = currentState.sessionId === sessionId;
  const notificationEmittedAt = ownsProjection ? currentState.notificationEmittedAt : undefined;

  if (ownsProjection) {
    chrome.action.setBadgeText({ text: "" });
    await hideConsentBanner(currentState.tabId, currentState.meetingUrl);
  }

  // Enqueue upload job — the queue handles retries with the same idempotencyKey
  const sid = sessionId;
  const previous = await getUploadJob(sid);
  if (previous && (previous.sessionId !== sid || previous.meetingId !== completion.meetingId)) {
    throw new Error("Upload job identity mismatch");
  }
  if (!previous) {
    try {
      await enqueueUpload({
        sessionId: sid,
        meetingId: completion.meetingId,
        idempotencyKey: sid, // sessionId = idempotencyKey ensures idempotent retries
        mimeType,
        notificationEmittedAt,
        title: ownsProjection ? currentState.meetingTitle : undefined,
        meetLink: ownsProjection ? currentState.meetingUrl || undefined : undefined,
        videoPresence: ownsProjection ? currentState.videoPresence ?? "absent" : "absent",
      });
    } catch (error) {
      // A racing recording-stopped may have inserted the same job first.
      const winner = await getUploadJob(sid);
      if (!winner || winner.sessionId !== sid || winner.meetingId !== completion.meetingId || winner.mimeType !== mimeType) throw error;
    }
  }
  console.log(`[sauri] Upload job enqueued for session: ${sid}`);

  // Trigger immediate processing attempt
  await processUploadQueue();

  // An old completion must not clear a newer capture's controls.
  if ((await getState()).sessionId === sessionId) await setState(DEFAULT_STATE);
  console.log("[sauri] State reset to idle");
}

async function handleRecordingError(sessionId?: string): Promise<void> {
  const state = await getState();
  const failedSession = sessionId ?? state.sessionId;
  if (failedSession) await settleCapture(failedSession, true);
  if (sessionId && state.sessionId !== sessionId) return;
  // Clear REC badge
  chrome.action.setBadgeText({ text: "" });

  const currentState = await getState();
  await hideConsentBanner(currentState.tabId, currentState.meetingUrl);

  await setState(DEFAULT_STATE);
  console.log("[sauri] Recording error, state reset to idle");
}

async function hideConsentBanner(tabId?: number, meetingUrl?: string): Promise<void> {
  if (!tabId || (meetingUrl !== undefined && !isMeetUrl(meetingUrl))) return;
  try {
    await chrome.tabs.sendMessage(tabId, { type: "hide-consent-banner" });
  } catch (error) {
    console.warn("[sauri] Could not hide consent banner:", error);
  }
}

async function handleNotificationEmitted(emittedAt?: string, senderTabId?: number): Promise<void> {
  if (!emittedAt) return;
  const currentState = await getState();
  if (senderTabId !== undefined && (currentState.tabId !== senderTabId || currentState.provider === "teams")) return;
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

  if (!await markProcessing(job.id)) return; // Concurrent completion/alarm already owns this attempt.

  try {
    if (job.meetingId) await setUploadOutcome(job.sessionId, job.meetingId, "uploading");
    await uploadRecording(job);
    await markDone(job.id);
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : "Upload outcome unavailable";
    const latest = await getUploadJob(job.idempotencyKey);
    if (latest?.status !== "done") {
      if (job.meetingId && (await getCompletion(job.sessionId))?.meetingId === job.meetingId) {
        await setUploadOutcome(job.sessionId, job.meetingId, "upload_failed");
      }
      await markFailed(job.id, errorMsg.slice(0, 160));
    }
    console.warn(`[sauri] Upload job failed: ${job.id} — ${errorMsg}`);
    return;
  }
  try {
    await setUploadOutcome(job.sessionId, job.meetingId!, "upload_succeeded");
    await reconcileReviewLaunches();
    await clearSession(job.sessionId);
    const record = await getCompletion(job.sessionId);
    if (record) await reconcileProcessing(record);
  } catch (error) {
    // Accepted upload remains bound; never invent success if persistence is unavailable.
    console.warn("[sauri] Upload settlement unavailable:", error);
  }
  console.log(`[sauri] Upload job done: ${job.id}`);
}

// Only authenticated reads of the persisted meeting can establish processing success.
async function reconcileProcessing(record: RecordingCompletion): Promise<void> {
  if (!record.recordingId) return;
  const stored = await chrome.storage.sync.get("authToken");
  if (typeof stored.authToken !== "string" || !stored.authToken) {
    await setProcessingStatus(record.sessionId, record.meetingId, record.recordingId, "processing_status_unavailable");
    return;
  }
  const base = `${BACKEND_URL}/api/v1/meetings/${encodeURIComponent(record.meetingId)}`;
  const headers = { Authorization: `Bearer ${stored.authToken}` };
  async function read(path: string): Promise<unknown> {
    const response = await fetch(`${base}${path}`, { headers });
    if (!response.ok) throw new Error(`Protected recording asset unavailable (${response.status})`);
    return response.json();
  }
  let status: ReturnType<typeof resolveProcessingStatus>;
  try {
    const meeting = await read("");
    status = resolveProcessingStatus(record, meeting);
    if (status === "processing_assets_unavailable") {
      // No protected asset is read for a mismatched or undocumented status.
      const transcript = await read("/transcript");
      const playback = await read("/playback");
      status = resolveProcessingStatus(record, meeting, transcript, playback);
    }
    await setProcessingStatus(record.sessionId, record.meetingId, record.recordingId, status ?? "processing_status_unavailable");
    if (status === "processing_succeeded") await reconcileReviewLaunches();
  } catch (error) {
    await setProcessingStatus(record.sessionId, record.meetingId, record.recordingId,
      status === "processing_assets_unavailable" ? status : "processing_status_unavailable");
    // Keep the last server-confirmed state; a 401/404 or network failure cannot imply success.
    console.warn("[sauri] Processing status unavailable:", error);
  }
}

async function reconcilePendingProcessing(): Promise<void> {
  for (const record of await getProcessingCompletions()) await reconcileProcessing(record);
}

// The portal resolves this query parameter to its existing protected meeting review.
// A deployment may override the portal origin; no bearer token or asset enters the URL.
const PORTAL_URL = import.meta.env.VITE_SAURI_PORTAL_URL ?? "http://localhost:5173";

function reviewDestination(meetingId: string): string {
  const url = new URL(PORTAL_URL);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("Invalid Sauri portal origin");
  }
  url.searchParams.set("meetingId", meetingId);
  return url.href;
}

async function reconcileReviewLaunches(): Promise<void> {
  for (const candidate of await getPendingReviewLaunches()) {
    try {
      if (!candidate.recordingId) continue;
      if ((candidate.reviewStatus ?? candidate.status) !== "review_launch_pending" && !await claimReviewLaunch(candidate.sessionId)) continue;
      const record = await getCompletion(candidate.sessionId);
      if (!record || (record.reviewStatus ?? record.status) !== "review_launch_pending" || record.meetingId !== candidate.meetingId ||
          record.recordingId !== candidate.recordingId) continue;
      const target = reviewDestination(record.meetingId);
      // Query before creation, including on a fresh launch: a lost Chrome result
      // must be recovered by the exact canonical URL, never by a prefix match.
      const existing = (await chrome.tabs.query({})).find(tab => tab.url === target);
      if (existing?.id !== undefined) {
        await markReviewOpened(record.sessionId, record.meetingId, record.recordingId, existing.id);
      } else if (await claimReviewCreate(record.sessionId, record.meetingId, record.recordingId)) {
        const created = await chrome.tabs.create({ url: target });
        if (created.id !== undefined) await markReviewOpened(record.sessionId, record.meetingId, record.recordingId, created.id);
      }
      // A failed/ambiguous Chrome create stays pending. Never repeat it blindly:
      // after an interruption, an absent tab does not establish it was never created.
    } catch (error) {
      console.warn("[sauri] Review launch pending; will reconcile existing tab:", error);
    }
  }
}

// --- Alarm-based retry (every 1 minute) ---

chrome.alarms.create(UPLOAD_ALARM_NAME, { periodInMinutes: 1 });

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === UPLOAD_ALARM_NAME) {
    void resumeFinalizations();
    void processUploadQueue();
    void reconcilePendingProcessing();
    void reconcileReviewLaunches();
  }
});

// --- Recovery on browser startup ---

chrome.runtime.onStartup.addListener(() => {
  console.log("[sauri] Browser startup — processing upload queue for recovery");
  processUploadQueue();
});
