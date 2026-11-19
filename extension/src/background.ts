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
  releaseProcessing,
  resetFailedJobsForSession,
  type UploadJob,
} from "./upload-queue";
import { assembleBlob, clearSession, createCompletion, getCapturingCompletion, claimCompletion, getCompletion, getPendingFinalizations, settleCapture, bindRecordingId, setUploadOutcome, setProcessingStatus, getProcessingCompletions, claimReviewLaunch, claimReviewCreate, markReviewOpened, getPendingReviewLaunches, type RecordingCompletion } from "./recording-db";
import { readFailureCause, resolveProcessingStatus } from "./core/processing-status";
import { matchesCaptureHandle, type CompletionTrigger, type CaptureHandle } from "./core/recording-completion";

import { canCaptureCurrentTab, isMeetUrl } from "./core/capture";
import { ensureOverlay, reinjectOverlay } from "./overlay-injection";
import { errorCode, logDiagnostic } from "./core/diagnostics";
import type { CaptureSource, CaptureStartResult } from "./core/types";
import { validCaptureDimensions } from "./core/resolution";
import { portalDestination } from "./panel/portal";
import { readRecordingSettings } from "./panel/recordingSettings";
import { parseDurationSeconds } from "./core/recording-duration";
import { ensureLocalToken, isLocalAppAvailable, LocalAppUnavailableError, migrateLegacyCredentials } from "./core/local-pairing";
import { authorizedRequest } from "./core/api/authorized-fetch";

export {};

// Maximum title length sent for a recording named after its tab.
const MAX_TAB_TITLE_LENGTH = 200;

function tabTitleOf(title?: string): string | undefined {
  const trimmed = title?.trim().slice(0, MAX_TAB_TITLE_LENGTH).trim();
  return trimmed || undefined;
}

// --- State interface ---

interface Resolution {
  width: number;
  height: number;
}

type CaptureMode = "screen_audio" | "audio_only";

interface SauriState {
  status: "idle" | "pending" | "recording";
  // Page URL of a Meet tab only ("" for any other tab); sent as `meet_link`.
  meetingUrl?: string;
  // Meet title, or the tab title for any other recorded tab.
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
  paused: boolean;
  elapsedMs?: number;
  segmentStartedAt?: number;
  showControlBar?: boolean;
  micLabel?: string;
  // False when the recorded tab cannot host the overlay; controls live in the panel only.
  overlayAvailable?: boolean;
}

const DEFAULT_STATE: SauriState = { status: "idle", paused: false };

// --- State helpers ---

async function getState(): Promise<SauriState> {
  const result = await chrome.storage.session.get("sauriState");
  const state = (result.sauriState as SauriState) ?? DEFAULT_STATE;
  return { ...state, paused: state.paused ?? false };
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

// --- Backend upload ---

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
      // Legacy jobs queued before the duration was persisted have no value to send.
      duration_seconds: job.durationSeconds ?? 0,
      interrupted: false,
      video_presence: videoPresence,
      notice_issued_at: notificationEmittedAt ?? null,
      // When capture began: the backend orders the library by when a recording was made.
      ...(completion.startedAt !== undefined ? { recorded_at: new Date(completion.startedAt).toISOString() } : {}),
      title: title ?? null,
      meet_link: meetLink ?? null,
    };

    const formData = new FormData();
    // Single WebM container with audio+video interleaved — send as "audio"
    formData.append("audio", blob, "recording.webm");
    formData.append("data", JSON.stringify(ingestionData));

    const response = await authorizedRequest(
      "/api/v1/ingestion/upload",
      { method: "POST", body: formData },
      async (reply) => reply,
    );

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

void migrateLegacyCredentials().catch(() => {
  console.warn("[sauri] Legacy credential cleanup unavailable");
});

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

// A full page load in the recorded tab drops the overlay: bring it back. The script
// restores the notice and controls itself by asking for the recording state.
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  try {
    const state = await getState();
    if (state.status !== "recording" || state.tabId !== tabId) return;
    const available = await ensureOverlay(tabId, tab.url);
    const latest = await getState();
    if (latest.sessionId === state.sessionId && latest.overlayAvailable !== available) {
      await setState({ ...latest, overlayAvailable: available });
    }
  } catch (error) {
    console.warn("[sauri] Could not restore the overlay after navigation:", error);
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
      durationSeconds?: number;
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
    // Media-owner messages cannot come from a page. Overlay controls are
    // separately bound to the exact recording session and originating Meet tab.
    if (_sender.tab && ["start-capture", "capture-ready", "recording-stopped", "recording-error", "capture-video-presence", "set-capture-mode", "retry-upload", "recording-settings-changed"].includes(message.type)) {
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

      case "recording-settings-changed":
        void (async () => {
          try { sendResponse({ ok: await applyLiveRecordingSettings() }); }
          catch { sendResponse({ ok: false }); }
        })();
        return true;

      case "get-recording-ui":
        void (async () => {
          const state = await getState();
          sendResponse({ state: state.status === "recording" && state.tabId === _sender.tab?.id ? recordingUI(state) : undefined });
        })();
        return true;

      case "pause-capture":
      case "resume-capture":
      case "cancel-capture":
      case "stop-capture":
        void (async () => {
          try {
            sendResponse({ ok: await handleCaptureControl(message.type, message.sessionId, _sender.tab?.id) });
          } catch (error) {
            console.warn("[sauri] Capture control unavailable:", error);
            sendResponse({ ok: false });
          }
        })();
        return true;

      case "retry-upload":
        void (async () => {
          try {
            sendResponse(await handleRetryUpload(message.sessionId));
          } catch {
            sendResponse({ ok: false, reason: "retry-unavailable" });
          }
        })();
        return true;

      case "recording-stopped":
        handleRecordingStopped(message.size!, message.mimeType!, message.sessionId, message.durationSeconds);
        sendResponse({ ok: true });
        break;

      case "capture-video-presence":
        handleCaptureVideoPresence(message.videoPresence);
        sendResponse({ ok: true });
        break;

      case "recording-error":
        console.error("[sauri] Recording error from offscreen:", message.error);
        void logDiagnostic("recording-error", String(message.error));
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
  if ((await getState()).status === "recording" || (await chrome.storage.session.get("sauriCountdown")).sauriCountdown) return;
  const newState: SauriState = {
    status: "pending",
    paused: false,
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
  countdownSeconds: number;
  cancelled?: boolean;
}

async function handleCaptureReady(sessionId?: string): Promise<{ ok: boolean; reason?: "cancelled" }> {
  try {
    const stored = await chrome.storage.session.get("sauriCaptureRequest");
    const request = stored.sauriCaptureRequest as CaptureRequest | undefined;
    if (!request || request.state.sessionId !== sessionId) return { ok: false };
    const { state, meetingId } = request;
    if (request.cancelled) return { ok: false, reason: "cancelled" };
    // Acquire the selected stream first, but persist no media or completion until
    // the countdown finishes. Current-tab stream IDs must be consumed promptly.
    // A tab that cannot host the overlay records without a countdown instead of failing.
    if (state.overlayAvailable !== false && request.countdownSeconds > 0) {
      await chrome.storage.session.set({ sauriCountdown: { requestId: state.sessionId, tabId: state.tabId } });
      try {
        const showCountdown = () => chrome.tabs.sendMessage(state.tabId, { type: "show-countdown", seconds: request.countdownSeconds, requestId: state.sessionId });
        let countdown: { ok?: boolean } | undefined;
        try {
          countdown = await showCountdown();
        } catch (error) {
          // The page script stopped answering (typically a Meet tab opened before the extension
          // was reloaded). Reinject it once; if it still fails, record without a countdown
          // rather than dropping the user's share.
          void logDiagnostic("countdown-unreachable", errorCode(error));
          if (await reinjectOverlay(state.tabId)) {
            try { countdown = await showCountdown(); }
            catch (retry) { void logDiagnostic("countdown-skipped", errorCode(retry)); countdown = undefined; }
          } else void logDiagnostic("countdown-skipped", "overlay could not be reinjected");
          if (!countdown) countdown = { ok: true };
        }
        const stored = (await chrome.storage.session.get("sauriCountdown")).sauriCountdown;
        if (!countdown?.ok || stored?.cancelled) {
          void logDiagnostic("countdown-cancelled", stored?.cancelled ? "cancelled by the user" : "no confirmation from the page");
          return { ok: false, reason: "cancelled" };
        }
      } finally {
        await chrome.storage.session.remove("sauriCountdown");
      }
    }
    const latest = (await chrome.storage.session.get("sauriCaptureRequest")).sauriCaptureRequest as CaptureRequest | undefined;
    if (!latest || latest.cancelled) return { ok: false, reason: "cancelled" };
    await createCompletion({
      sessionId: state.sessionId, meetingId, provider: state.provider ?? "meet",
      capturedTabId: state.tabId, status: "capturing", updatedAt: Date.now(), startedAt: Date.now(),
    });
    await setState(state);
    return { ok: true };
  } catch (error) {
    console.error("[sauri] Could not bind selected media:", error);
    void logDiagnostic("bind-failed", errorCode(error));
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
        const settings = await readRecordingSettings();
        if (!await ensureOffscreenDocument()) return { ok: false, reason: "busy" };
        if (micDeviceId) {
          const permission = await chrome.runtime.sendMessage({ type: "check-microphone-permission" });
          if (!permission?.ok) return { ok: false, reason: "microphone-permission" };
        }
        // The overlay must exist before the picker or the countdown. Only the tab that is
        // active now can host it: with the picker, another tab may end up being recorded.
        const overlayAvailable = await ensureOverlay(tab.id, tab.url);
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
        const currentState = await getState();
        const captureMode = currentState.captureMode ?? "screen_audio";
        // Only the three offered sizes are accepted; anything else records at the default.
        const res = validCaptureDimensions(resolution);
        const isMeet = isMeetUrl(tab.url);
        let meetingTitle = isMeet ? currentState.meetingTitle : tabTitleOf(tab.title);
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
          countdownSeconds: settings.countdownSeconds,
          state: {
            status: "recording", sessionId, provider: isMeet ? "meet" : "tab", resolution: res, pickerSource: source,
            captureMode, micDeviceId, tabId: tab.id, meetingTitle,
            paused: false, elapsedMs: 0, showControlBar: settings.showControlBar,
            meetingUrl: isMeet ? tab.url : "", overlayAvailable,
          },
        };
        await chrome.storage.session.set({ sauriCaptureRequest: request });
        // The offscreen binds this request only after the picker returns valid
        // media. No durable session or recording projection exists on cancel.
        const result: CaptureStartResult & { segmentStartedAt?: number; micLabel?: string } = await chrome.runtime.sendMessage({
          type: "start-recording", sessionId, source, ...(streamId ? { streamId } : {}), resolution: res, captureMode,
          micDeviceId: micDeviceId ?? null,
        });
        if (!result?.ok) {
          void logDiagnostic("start-not-completed", result?.reason ?? "no response from the recorder");
          if (await getCompletion(sessionId)) await handleRecordingError(sessionId);
          return result ?? { ok: false, reason: "failed" };
        }
        const activeCapture = await getCompletion(sessionId);
        if (activeCapture?.status !== "capturing" || activeCapture.captureError) return result;
        const recording = await getState();
        if (recording.sessionId === sessionId) {
          await setState({ ...recording, segmentStartedAt: result.segmentStartedAt ?? Date.now(), micLabel: result.micLabel });
          await syncRecordingUI(await getState());
        }
        if (overlayAvailable) {
          try { await chrome.tabs.sendMessage(tab.id, { type: "show-consent-banner" }); }
          catch (error) { console.warn("[sauri] Could not show consent banner:", error); }
        }
        // Sharing may have ended while the banner message was in flight.
        if ((await getCompletion(sessionId))?.status === "capturing") {
          chrome.action.setBadgeText({ text: "REC" });
          chrome.action.setBadgeBackgroundColor({ color: "#b83230" });
        }
        return result;
      } catch (error) {
        console.error("[sauri] Failed to start capture:", error);
        void logDiagnostic("start-failed", errorCode(error));
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

/** Applies the settings that can change mid-recording: today only the floating control bar. */
async function applyLiveRecordingSettings(): Promise<boolean> {
  const state = await getState();
  if (state.status !== "recording") return true;
  const { showControlBar } = await readRecordingSettings();
  if ((state.showControlBar ?? true) === showControlBar) return true;
  const next = { ...state, showControlBar };
  await setState(next);
  await syncRecordingUI(next);
  return true;
}

function recordingUI(state: SauriState) {
  return {
    sessionId: state.sessionId, paused: state.paused ?? false,
    elapsedMs: state.elapsedMs ?? 0, segmentStartedAt: state.segmentStartedAt,
    showControlBar: state.showControlBar ?? true, micLabel: state.micLabel, micActive: !!state.micDeviceId,
  };
}

async function syncRecordingUI(state: SauriState): Promise<void> {
  if (state.tabId === undefined || state.overlayAvailable === false) return;
  try { await chrome.tabs.sendMessage(state.tabId, { type: "recording-ui", state: recordingUI(state) }); }
  catch (error) { console.warn("[sauri] Could not update recording controls:", error); }
}

async function handleCaptureControl(type: string, sessionId?: string, senderTabId?: number): Promise<boolean> {
  const state = await getState();
  if (type === "cancel-capture" && state.status !== "recording") {
    const { sauriCaptureRequest, sauriCountdown } = await chrome.storage.session.get(["sauriCaptureRequest", "sauriCountdown"]);
    const request = sauriCaptureRequest as CaptureRequest | undefined;
    if (!request || (sessionId !== undefined && sessionId !== request.state.sessionId)) return false;
    if (senderTabId !== undefined && (senderTabId !== request.state.tabId || sessionId !== request.state.sessionId)) return false;
    await chrome.storage.session.set({ sauriCaptureRequest: { ...request, cancelled: true } });
    void logDiagnostic("capture-cancelled-before-start", senderTabId === undefined ? "sharing ended or cancelled from the recorder or panel" : "cancelled from the page");
    if (sauriCountdown?.requestId === request.state.sessionId) {
      await chrome.storage.session.set({ sauriCountdown: { ...sauriCountdown, cancelled: true } });
      try { await chrome.tabs.sendMessage(sauriCountdown.tabId, { type: "cancel-countdown" }); }
      catch { /* Closing the tab also closes its pending countdown response. */ }
    }
    return true;
  }
  if (state.status !== "recording" || !state.sessionId) return false;
  if (sessionId !== undefined && sessionId !== state.sessionId) return false;
  if (senderTabId !== undefined && (senderTabId !== state.tabId || sessionId !== state.sessionId)) return false;
  if (type === "stop-capture") return handleStopCapture();
  const command = type === "cancel-capture" ? "cancel-recording" : type === "pause-capture" ? "pause-recording" : "resume-recording";
  const response = await chrome.runtime.sendMessage({ type: command, sessionId: state.sessionId });
  if (!response?.ok) return false;
  const latest = await getState();
  if (latest.sessionId !== state.sessionId) return true;
  if (type === "cancel-capture") {
    await hideConsentBanner(latest.tabId, latest.overlayAvailable);
    await setState(DEFAULT_STATE);
    await chrome.action.setBadgeText({ text: "" });
  } else {
    await setState({ ...latest, paused: response.paused, elapsedMs: response.elapsedMs, segmentStartedAt: response.segmentStartedAt });
    await syncRecordingUI(await getState());
  }
  return true;
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
  sessionId?: string,
  durationSeconds?: number
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
    await hideConsentBanner(currentState.tabId, currentState.overlayAvailable);
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
        durationSeconds: parseDurationSeconds(durationSeconds),
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
  await hideConsentBanner(currentState.tabId, currentState.overlayAvailable);

  await setState(DEFAULT_STATE);
  console.log("[sauri] Recording error, state reset to idle");
}

async function hideConsentBanner(tabId?: number, overlayAvailable?: boolean): Promise<void> {
  if (!tabId || overlayAvailable === false) return;
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

async function handleRetryUpload(sessionId?: string) {
  if (typeof sessionId !== "string" || !sessionId.trim() || !await resetFailedJobsForSession(sessionId)) {
    return { ok: false, reason: "nothing-to-retry" };
  }
  void processUploadQueue().catch(() => {
    console.warn("[sauri] Manual upload processing unavailable; pending jobs remain queued");
  });
  return { ok: true };
}

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

  // Waiting for the desktop app is not a failed upload and must not exhaust retries.
  if (!await isLocalAppAvailable()) return;
  try { await ensureLocalToken(); }
  catch { return; }

  console.log(`[sauri] Processing upload job: ${job.id} (session: ${job.sessionId}, attempt: ${job.retryCount + 1})`);

  if (!await markProcessing(job.id)) return; // Concurrent completion/alarm already owns this attempt.

  try {
    if (job.meetingId) await setUploadOutcome(job.sessionId, job.meetingId, "uploading");
    await uploadRecording(job);
    await markDone(job.id);
  } catch (error) {
    if (error instanceof LocalAppUnavailableError || !await isLocalAppAvailable()) {
      await releaseProcessing(job.id);
      return;
    }
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
  if (!await isLocalAppAvailable()) {
    await setProcessingStatus(record.sessionId, record.meetingId, record.recordingId, "processing_status_unavailable");
    return;
  }
  const base = `/api/v1/meetings/${encodeURIComponent(record.meetingId)}`;
  async function read(path: string): Promise<unknown> {
    return authorizedRequest(`${base}${path}`, {}, async (response) => {
      if (!response.ok) throw new Error(`Protected recording asset unavailable (${response.status})`);
      return response.json();
    });
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
    await setProcessingStatus(record.sessionId, record.meetingId, record.recordingId, status ?? "processing_status_unavailable",
      status === "processing_failed" ? readFailureCause(meeting) : undefined);
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
async function reconcileReviewLaunches(): Promise<void> {
  for (const candidate of await getPendingReviewLaunches()) {
    try {
      if (!candidate.recordingId) continue;
      if ((candidate.reviewStatus ?? candidate.status) !== "review_launch_pending" && !await claimReviewLaunch(candidate.sessionId)) continue;
      const record = await getCompletion(candidate.sessionId);
      if (!record || (record.reviewStatus ?? record.status) !== "review_launch_pending" || record.meetingId !== candidate.meetingId ||
          record.recordingId !== candidate.recordingId) continue;
      const target = await portalDestination(record.meetingId);
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
