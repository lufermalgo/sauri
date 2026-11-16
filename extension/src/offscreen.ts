// Offscreen document for MediaRecorder.
// Captures Audio_Track + Video_Track via the native sharing picker, chunked on a 5s timeslice.
// Production: chunks persisted in IndexedDB, assembled by sessionId.

import { storeChunk, getChunksBySession, clearSession, openDB, STORE_NAME, settleCapture, claimCompletion, COMPLETION_STORE } from "./recording-db";
import { videoPresenceFromStream } from "./core/capture";
import type { CaptureSource, CaptureStartResult } from "./core/types";
import { recordedDurationSeconds } from "./core/recording-duration";

console.log("[sauri] Offscreen document loaded");

let recorder: MediaRecorder | null = null;
let audioCtx: AudioContext | null = null;
let currentSessionId: string | null = null;
let stopRequested = false;
let discardRequested = false;
let discardSucceeded = false;
let finished: Promise<void> = Promise.resolve();
let elapsedMs = 0;
let segmentStartedAt: number | undefined;

async function microphoneGranted(): Promise<boolean> {
  try { return (await navigator.permissions.query({ name: "microphone" as PermissionName })).state === "granted"; }
  catch { return false; }
}

// --- Local IndexedDB helpers (not shared — only used in offscreen) ---

/**
 * Returns sessionIds still present in IndexedDB (unfinished/orphaned sessions).
 * Useful for future recovery by background alarm.
 */
async function getUnfinishedSessions(): Promise<string[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("by_session");
    const request = index.openKeyCursor(null, "nextunique");
    const sessionIds: string[] = [];
    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) {
        sessionIds.push(cursor.key as string);
        cursor.continue();
      }
    };
    tx.oncomplete = () => {
      db.close();
      resolve(sessionIds);
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

// --- Capture mode type ---

type CaptureMode = "screen_audio" | "audio_only";

interface Resolution {
  width: number;
  height: number;
}

// --- Message listener ---

chrome.runtime.onMessage.addListener(
  (
    message: { type: string; source?: CaptureSource; streamId?: string; sessionId?: string; captureMode?: CaptureMode; resolution?: Resolution; micDeviceId?: string | null },
    _sender,
    sendResponse
  ) => {
    if (_sender.tab) return false;
    if (message.type === "check-microphone-permission") {
      void (async () => { sendResponse({ ok: await microphoneGranted() }); })();
      return true;
    } else if (message.type === "pause-recording" || message.type === "resume-recording") {
      sendResponse(changePause(message.sessionId, message.type === "pause-recording"));
    } else if (message.type === "cancel-recording") {
      void (async () => {
        try { sendResponse({ ok: await cancelRecording(message.sessionId) }); }
        catch { sendResponse({ ok: false }); }
      })();
      return true;
    } else if (message.type === "get-capture-status") {
      sendResponse({ active: currentSessionId !== null });
    } else if (message.type === "start-recording" && message.sessionId) {
      const sessionId = message.sessionId;
      const captureMode: CaptureMode = message.captureMode ?? "screen_audio";
      const resolution: Resolution = message.resolution ?? { width: 1280, height: 720 };
      const micDeviceId: string | null = message.micDeviceId ?? null;
      if (currentSessionId) {
        sendResponse({ ok: false, reason: "busy" });
        return false;
      }
      void (async () => {
        sendResponse(await startRecording(sessionId, captureMode, resolution, micDeviceId, message.source ?? "picker", message.streamId));
      })();
      return true;
    } else if (message.type === "stop-recording") {
      sendResponse({ ok: stopRecording(message.sessionId) });
    } else if (message.type === "get-unfinished-sessions") {
      getUnfinishedSessions().then((sessions) => {
        sendResponse({ ok: true, sessions });
      });
      return true; // async sendResponse
    } else if (
      message.type === "clear-session" &&
      message.sessionId
    ) {
      clearSession(message.sessionId).then(() => {
        sendResponse({ ok: true });
      });
      return true; // async sendResponse
    }
    return false;
  }
);

// --- Recording logic ---

// Hints not present in the project's DOM typings; older Chrome may ignore them.
type PickerOptions = DisplayMediaStreamOptions & {
  selfBrowserSurface: "include";
  preferCurrentTab: boolean;
  monitorTypeSurfaces: "exclude";
  surfaceSwitching: "include";
  systemAudio: "exclude";
};

async function chooseTab(resolution: Resolution): Promise<MediaStream> {
  const video = {
    displaySurface: "browser", width: { max: resolution.width }, height: { max: resolution.height },
  };
  const audio: MediaTrackConstraints & { suppressLocalAudioPlayback: boolean } = {
    suppressLocalAudioPlayback: false,
  };
  const options: PickerOptions = {
    video, audio, selfBrowserSurface: "include", preferCurrentTab: false,
    monitorTypeSurfaces: "exclude", surfaceSwitching: "include", systemAudio: "exclude",
  };
  try {
    return await navigator.mediaDevices.getDisplayMedia(options);
  } catch (error) {
    // Only retry unsupported options, never a cancellation/permission denial.
    if (!(error instanceof TypeError)) throw error;
    return navigator.mediaDevices.getDisplayMedia({ video, audio: true });
  }
}

async function startRecording(
  sessionId: string,
  captureMode: CaptureMode,
  resolution: Resolution,
  micDeviceId: string | null,
  source: CaptureSource,
  streamId?: string
): Promise<CaptureStartResult & { segmentStartedAt?: number; micLabel?: string }> {
  let resolveFinished!: () => void;
  finished = new Promise(resolve => { resolveFinished = resolve; });
  const streams: MediaStream[] = [];
  const cleanup = () => {
    currentSessionId = null;
    recorder = null;
    if (audioCtx) { void audioCtx.close(); audioCtx = null; }
    streams.forEach(stream => stream.getTracks().forEach(track => track.stop()));
    resolveFinished();
  };
  let captureFailed = false;
  let captureReady = false;
  let sourceEnded = false;
  const finalizeEndedCapture = async () => {
    try {
      if (discardRequested) return;
      // Same durable claim as the origin-tab fallback; a restart can replay it.
      await claimCompletion(sessionId, "captured-tab-close");
      stopRecording(sessionId);
    } catch {
      captureFailed = true;
      stopRecording(sessionId);
      void chrome.runtime.sendMessage({ type: "recording-error", sessionId, error: "Could not finalize ended capture" });
    }
  };
  try {
    currentSessionId = sessionId;
    stopRequested = false;
    discardRequested = false;
    discardSucceeded = false;
    elapsedMs = 0;
    segmentStartedAt = undefined;
    if (micDeviceId && !await microphoneGranted()) {
      cleanup();
      return { ok: false, reason: "microphone-permission" };
    }
    let micLabel: string | undefined;
    let chunkWrites: Promise<void> = Promise.resolve();

    let tabStream: MediaStream;
    try {
      if (source === "current-tab") {
        if (!streamId) throw new Error("Current tab stream ID missing");
        const tabConstraints = { chromeMediaSource: "tab", chromeMediaSourceId: streamId };
        tabStream = await navigator.mediaDevices.getUserMedia({
          audio: { mandatory: tabConstraints } as unknown as MediaTrackConstraints,
          video: { mandatory: { ...tabConstraints, maxWidth: resolution.width, maxHeight: resolution.height } } as unknown as MediaTrackConstraints,
        });
      } else {
        tabStream = await chooseTab(resolution);
      }
    } catch (error) {
      if (source === "picker" && error instanceof DOMException && ["NotAllowedError", "AbortError"].includes(error.name)) {
        cleanup();
        return { ok: false, reason: "cancelled" };
      }
      if (source === "current-tab") {
        cleanup();
        return { ok: false, reason: "current-tab-unavailable" };
      }
      throw error;
    }
    streams.push(tabStream);
    if (!tabStream.getAudioTracks().length) {
      cleanup();
      return { ok: false, reason: "no-tab-audio" };
    }
    const videoTrack = tabStream.getVideoTracks()[0];
    // displaySurface is only a picker hint: reject windows/monitors even if an
    // older Chrome ignores the optional exclusion hints.
    if (!videoTrack || (source === "picker" && videoTrack.getSettings().displaySurface !== "browser")) {
      cleanup();
      return { ok: false, reason: "unsupported-surface" };
    }
    const sharingEnded = () => sourceEnded || videoTrack.readyState === "ended";
    videoTrack.addEventListener("ended", () => {
      sourceEnded = true;
      if (captureReady) void finalizeEndedCapture();
      else void chrome.runtime.sendMessage({ type: "cancel-capture", sessionId });
    }, { once: true });

    let audioTracks = tabStream.getAudioTracks();
    let tabSource: MediaStreamAudioSourceNode | undefined;
    if (source === "current-tab" || micDeviceId) {
      audioCtx = new AudioContext();
      tabSource = audioCtx.createMediaStreamSource(tabStream);
      // Direct tab capture mutes local playback; only this source needs loopback.
      // Display capture requests local playback and must NOT be looped back.
      // Both playback assumptions remain NOT VERIFIED in the owner's Chrome.
      if (source === "current-tab") tabSource.connect(audioCtx.destination);
    }
    if (micDeviceId) {
      let micStream: MediaStream;
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: { deviceId: { exact: micDeviceId } },
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "NotAllowedError") {
          cleanup();
          return { ok: false, reason: "microphone-permission" };
        }
        throw error;
      }
      streams.push(micStream);
      micLabel = micStream.getAudioTracks()[0]?.label;
      const micSource = audioCtx!.createMediaStreamSource(micStream);
      const mixDestination = audioCtx!.createMediaStreamDestination();
      tabSource!.connect(mixDestination);
      micSource.connect(mixDestination);
      audioTracks = mixDestination.stream.getAudioTracks();
      streams.push(mixDestination.stream);
    }
    // Keep the source video track only as a sharing-lifetime sentinel in
    // audio_only; it is not passed to MediaRecorder or stored in the file.
    const recordingStream = new MediaStream([
      ...audioTracks, ...(captureMode === "audio_only" ? [] : [videoTrack]),
    ]);
    if (sharingEnded()) { cleanup(); return { ok: false, reason: "cancelled" }; }
    const ready = await chrome.runtime.sendMessage({ type: "capture-ready", sessionId });
    if (!ready?.ok) {
      if (ready?.reason === "cancelled") { cleanup(); return { ok: false, reason: "cancelled" }; }
      throw new Error("Could not bind capture identity");
    }
    captureReady = true;
    chrome.runtime.sendMessage({ type: "capture-video-presence", videoPresence: videoPresenceFromStream(recordingStream) });

    // Determine supported mimeType based on capture mode
    let mimeType: string;
    if (captureMode === "audio_only") {
      const preferredAudioMime = "audio/webm;codecs=opus";
      const fallbackAudioMime = "audio/webm";
      mimeType = MediaRecorder.isTypeSupported(preferredAudioMime)
        ? preferredAudioMime
        : fallbackAudioMime;
    } else {
      const preferredVideoMime = "video/webm;codecs=vp8,opus";
      const fallbackVideoMime = "video/webm";
      mimeType = MediaRecorder.isTypeSupported(preferredVideoMime)
        ? preferredVideoMime
        : fallbackVideoMime;
    }

    console.log(`[sauri] Capture mode: ${captureMode}`);
    console.log(`[sauri] Using mimeType: ${mimeType}`);
    console.log(`[sauri] Session ID: ${sessionId}`);

    // Create MediaRecorder with the appropriate stream
    recorder = new MediaRecorder(recordingStream, { mimeType });

    recorder.ondataavailable = (event: BlobEvent) => {
      if (!discardRequested && event.data.size > 0) {
        chunkWrites = chunkWrites.then(async () => {
          try { await storeChunk(sessionId, event.data); }
          catch {
            if (discardRequested) return;
            captureFailed = true;
            await settleCapture(sessionId, true);
            void chrome.runtime.sendMessage({ type: "recording-error", sessionId, error: "Could not persist capture chunk" });
            stopRecording(sessionId);
          }
        });
      }
    };

    recorder.onstop = async () => {
      console.log("[sauri] Recording stopped, assembling from IndexedDB...");

      if (!currentSessionId) {
        console.error("[sauri] No sessionId available at stop time");
        return;
      }

      try {
        await chunkWrites;
        if (discardRequested) {
          await clearSession(sessionId);
          // Remove the capture identity only after all pending chunk writes finish.
          // A crash before deletion leaves a failed tombstone, never an upload intent.
          const db = await openDB();
          try {
            await new Promise<void>((resolve, reject) => {
              const tx = db.transaction(COMPLETION_STORE, "readwrite");
              tx.objectStore(COMPLETION_STORE).delete(sessionId);
              tx.oncomplete = () => resolve();
              tx.onerror = () => reject(tx.error);
              tx.onabort = () => reject(tx.error);
            });
          } finally { db.close(); }
          discardSucceeded = true;
          return;
        }
        if (captureFailed) return;
        const blobs = await getChunksBySession(sessionId);
        const blob = new Blob(blobs, { type: mimeType });
        await settleCapture(sessionId);

        // Metadata only. Chunks remain until the upload owner confirms success.
        closeRunningSegment();
        chrome.runtime.sendMessage({
          type: "recording-stopped", sessionId, size: blob.size, mimeType,
          durationSeconds: recordedDurationSeconds(elapsedMs),
        });
      } catch {
        await settleCapture(sessionId, true);
        void chrome.runtime.sendMessage({ type: "recording-error", sessionId, error: "Could not persist final media" });
      } finally {
        cleanup();
      }
    };

    // Start recording with 5-second chunks
    recorder.onerror = () => {
      if (discardRequested) return;
      captureFailed = true;
      void settleCapture(sessionId, true);
      void chrome.runtime.sendMessage({ type: "recording-error", sessionId, error: "MediaRecorder failed" });
      stopRecording(sessionId);
    };
    recorder.start(5000);
    segmentStartedAt = Date.now();
    if (sharingEnded()) await finalizeEndedCapture();
    else if (stopRequested) stopRecording(sessionId);
    console.log("[sauri] Recording started (5s chunks, IndexedDB persistence)");
    return { ok: true, sessionId, segmentStartedAt, micLabel };
  } catch (error) {
    console.error("[sauri] Failed to start recording:", error);
    cleanup();
    await settleCapture(sessionId, true);
    if (captureReady) chrome.runtime.sendMessage({
      type: "recording-error", sessionId,
      error: "Could not start recording",
    });
    return { ok: false, reason: "failed" };
  }
}

// Folds the running segment into elapsedMs. Idempotent: pause and stop both
// call it, and the recorded total never includes paused time.
function closeRunningSegment(): void {
  if (segmentStartedAt === undefined) return;
  elapsedMs += Math.max(0, Date.now() - segmentStartedAt);
  segmentStartedAt = undefined;
}

function stopRecording(sessionId?: string): boolean {
  if (!sessionId || sessionId !== currentSessionId) return false;
  if (discardRequested) return false;
  stopRequested = true;
  // Measure at the stop request, not after the final chunks are persisted.
  closeRunningSegment();
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
    console.log("[sauri] Stopping recorder...");
  }
  return true;
}

function changePause(sessionId: string | undefined, pause: boolean) {
  if (sessionId !== currentSessionId || !recorder || stopRequested || recorder.state === "inactive") return { ok: false };
  try {
    if (pause && recorder.state === "recording") {
      recorder.pause();
      closeRunningSegment();
    } else if (!pause && recorder.state === "paused") {
      recorder.resume();
      segmentStartedAt = Date.now();
    }
    return { ok: true, paused: recorder.state === "paused", elapsedMs, segmentStartedAt };
  } catch {
    // Do not claim a pause if the browser's MediaRecorder cannot apply it.
    return { ok: false };
  }
}

async function cancelRecording(sessionId?: string): Promise<boolean> {
  // Whichever disposition reached the media owner first wins. Saving cannot
  // be converted to discarding after finalization has already started.
  if (!sessionId || sessionId !== currentSessionId || stopRequested || !recorder || recorder.state === "inactive") return false;
  stopRequested = true;
  discardRequested = true;
  // Disable the existing durable finalization/recovery path before stopping.
  try { await settleCapture(sessionId, true); }
  catch (error) { stopRequested = false; discardRequested = false; throw error; }
  recorder.stop();
  await finished;
  return discardSucceeded;
}
