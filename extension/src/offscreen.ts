// Documento offscreen para MediaRecorder.
// Captura Pista_De_Audio + Pista_De_Video via tabCapture stream, troceo timeslice 5s.
// Producción: chunks persistidos en IndexedDB ensamblados por sessionId.

import { storeChunk, getChunksBySession, clearSession, openDB, STORE_NAME } from "./recording-db";

console.log("[sauri] Offscreen document loaded");

let recorder: MediaRecorder | null = null;
let audioCtx: AudioContext | null = null;
let currentSessionId: string | null = null;

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
    message: { type: string; streamId?: string; sessionId?: string; captureMode?: CaptureMode; resolution?: Resolution; micDeviceId?: string | null },
    _sender,
    sendResponse
  ) => {
    if (message.type === "start-recording" && message.streamId) {
      const sessionId = message.sessionId ?? crypto.randomUUID();
      const captureMode: CaptureMode = message.captureMode ?? "screen_audio";
      const resolution: Resolution = message.resolution ?? { width: 1280, height: 720 };
      const micDeviceId: string | null = message.micDeviceId ?? null;
      startRecording(message.streamId, sessionId, captureMode, resolution, micDeviceId);
      sendResponse({ ok: true, sessionId });
    } else if (message.type === "stop-recording") {
      stopRecording();
      sendResponse({ ok: true });
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

async function startRecording(
  streamId: string,
  sessionId: string,
  captureMode: CaptureMode,
  resolution: Resolution,
  micDeviceId: string | null
): Promise<void> {
  try {
    currentSessionId = sessionId;

    // Build getUserMedia constraints based on capture mode
    const audioConstraint = {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    } as unknown as MediaTrackConstraints;

    const mediaConstraints: MediaStreamConstraints =
      captureMode === "audio_only"
        ? { audio: audioConstraint, video: false }
        : {
            audio: audioConstraint,
            video: {
              mandatory: {
                chromeMediaSource: "tab",
                chromeMediaSourceId: streamId,
                maxWidth: resolution.width,
                maxHeight: resolution.height,
              },
            } as unknown as MediaTrackConstraints,
          };

    const tabStream =
      await navigator.mediaDevices.getUserMedia(mediaConstraints);

    // CRITICAL - Audio loopback: connect tab audio to AudioContext destination
    // so the tab audio is NOT muted for the user
    audioCtx = new AudioContext();
    const tabSource = audioCtx.createMediaStreamSource(tabStream);
    tabSource.connect(audioCtx.destination);

    // Determine the audio stream to use for recording
    let recordingStream: MediaStream;

    if (micDeviceId) {
      // Mix mic audio with tab audio for recording
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: { exact: micDeviceId } },
      });

      const micSource = audioCtx.createMediaStreamSource(micStream);
      const mixDestination = audioCtx.createMediaStreamDestination();

      // Connect both tab audio and mic audio to the mix destination
      tabSource.connect(mixDestination);
      micSource.connect(mixDestination);

      // Build the recording stream: mixed audio + video (if present)
      const videoTrack = tabStream.getVideoTracks()[0];
      if (videoTrack) {
        recordingStream = new MediaStream([
          mixDestination.stream.getAudioTracks()[0],
          videoTrack,
        ]);
      } else {
        recordingStream = mixDestination.stream;
      }

      console.log("[sauri] Mic mixed with tab audio for recording");
    } else {
      // No mic — use tab stream as-is for recording
      recordingStream = tabStream;
    }

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

    recorder.ondataavailable = async (event: BlobEvent) => {
      if (event.data.size > 0 && currentSessionId) {
        await storeChunk(currentSessionId, event.data);
        console.log(
          `[sauri] Chunk stored in IndexedDB: ${event.data.size} bytes (session: ${currentSessionId})`
        );
      }
    };

    recorder.onstop = async () => {
      console.log("[sauri] Recording stopped, assembling from IndexedDB...");

      if (!currentSessionId) {
        console.error("[sauri] No sessionId available at stop time");
        return;
      }

      const storedSessionId = currentSessionId;

      // Read all chunks from IndexedDB for this session to calculate final size
      const blobs = await getChunksBySession(storedSessionId);
      const blob = new Blob(blobs, { type: mimeType });
      console.log(
        `[sauri] Final blob: ${blob.size} bytes from ${blobs.length} chunks`
      );

      // Send metadata-only message — no recording data transfer
      chrome.runtime.sendMessage({
        type: "recording-stopped",
        sessionId: storedSessionId,
        size: blob.size,
        mimeType,
      });

      // Cleanup audio context and tracks
      // NOTE: chunks are NOT cleared here — background handles cleanup after successful upload
      currentSessionId = null;
      if (audioCtx) {
        audioCtx.close();
        audioCtx = null;
      }
      tabStream.getTracks().forEach((track) => track.stop());
    };

    // Start recording with 5-second chunks
    recorder.start(5000);
    console.log("[sauri] Recording started (5s chunks, IndexedDB persistence)");
  } catch (error) {
    console.error("[sauri] Failed to start recording:", error);
    currentSessionId = null;
    chrome.runtime.sendMessage({
      type: "recording-error",
      error: String(error),
    });
  }
}

function stopRecording(): void {
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
    console.log("[sauri] Stopping recorder...");
  }
}
