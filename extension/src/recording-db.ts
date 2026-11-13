// Shared IndexedDB helpers for the sauri-recordings database.
// Used by both offscreen.ts (write chunks) and background.ts (read/assemble/clear).
// This module has NO side effects — all operations are explicit function calls.

import { applyCompletionEvent, type CompletionTrigger } from "./core/recording-completion";

export const DB_NAME = "sauri-recordings";
export const DB_VERSION = 2;
export const COMPLETION_STORE = "completion_records";
export const STORE_NAME = "chunks";

export interface RecordingCompletion {
  sessionId: string;
  provider: "meet" | "teams";
  meetingId: string;
  recordingId?: string;
  capturedTabId: number;
  status: "capturing" | "finalizing" | "upload_pending" | "uploading" | "upload_succeeded" | "upload_failed" | "upload_outcome_unavailable" | "processing" | "processing_assets_unavailable" | "processing_failed" | "processing_succeeded" | "review_launch_pending" | "review_opened";
  captureError?: boolean;
  trigger?: "stop" | "captured_tab_closed";
  reviewTabId?: number;
  updatedAt: number;
}

/** Resolve only after commit, never after an individual successful write. */
async function completionTransaction<T>(
  mode: IDBTransactionMode,
  operate: (store: IDBObjectStore, result: (value: T) => void, fail: (error: Error) => void) => void,
): Promise<T> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(COMPLETION_STORE, mode);
    let result: T;
    let failure: Error | undefined;
    tx.oncomplete = () => { db.close(); resolve(result); };
    tx.onabort = tx.onerror = () => { db.close(); reject(failure ?? tx.error ?? new Error("Completion transaction failed")); };
    try {
      operate(tx.objectStore(COMPLETION_STORE), (value) => { result = value; }, (error) => { failure = error; tx.abort(); });
    } catch (error) {
      failure = error instanceof Error ? error : new Error("Completion transaction failed");
      tx.abort();
    }
  });
}

function requiredId(value: string): boolean {
  return typeof value === "string" && value.trim().length > 0 && value === value.trim();
}

export async function createCompletion(record: RecordingCompletion): Promise<RecordingCompletion> {
  if (!requiredId(record.sessionId) || !requiredId(record.meetingId) ||
      (record.recordingId !== undefined && !requiredId(record.recordingId))) {
    throw new Error("Invalid recording completion identity");
  }
  return completionTransaction("readwrite", (store, result, fail) => {
    const request = store.get(record.sessionId);
    request.onsuccess = () => {
      const existing = request.result as RecordingCompletion | undefined;
      if (existing) {
        if (existing.meetingId !== record.meetingId || existing.capturedTabId !== record.capturedTabId ||
            existing.provider !== record.provider || (record.recordingId !== undefined && existing.recordingId !== record.recordingId)) {
          fail(new Error("Recording completion identity mismatch"));
        } else result(existing);
        return;
      }
      // This read and the insert share the same readwrite transaction: concurrent
      // sessions cannot reserve the same meeting before the first one commits.
      const all = store.getAll();
      all.onsuccess = () => {
        if ((all.result as RecordingCompletion[]).some(saved =>
          saved.meetingId === record.meetingId || (record.recordingId !== undefined && saved.recordingId === record.recordingId))) {
          fail(new Error("Recording completion identity already assigned"));
          return;
        }
        store.add(record);
        result(record);
      };
    };
  });
}

/** Persist the validated ingestion identity; a retry can only repeat the same mapping. */
export async function bindRecordingId(sessionId: string, meetingId: string, recordingId: string): Promise<RecordingCompletion> {
  if (!requiredId(sessionId) || !requiredId(meetingId) || !requiredId(recordingId)) {
    throw new Error("Invalid recording identity response");
  }
  return completionTransaction("readwrite", (store, result, fail) => {
    const request = store.get(sessionId);
    request.onsuccess = () => {
      const record = request.result as RecordingCompletion | undefined;
      if (!record || record.meetingId !== meetingId || (record.recordingId && record.recordingId !== recordingId)) {
        fail(new Error("Recording identity response mismatch"));
        return;
      }
      if (record.recordingId) { result(record); return; }
      const all = store.getAll();
      all.onsuccess = () => {
        if ((all.result as RecordingCompletion[]).some(saved => saved.sessionId !== sessionId && saved.recordingId === recordingId)) {
          fail(new Error("Recording identity response already assigned"));
          return;
        }
        const updated = { ...record, recordingId, updatedAt: Date.now() };
        store.put(updated);
        result(updated);
      };
    };
  });
}

export async function setUploadOutcome(
  sessionId: string, meetingId: string,
  status: "uploading" | "upload_succeeded" | "upload_failed" | "upload_outcome_unavailable",
): Promise<void> {
  return completionTransaction("readwrite", (store, result, fail) => {
    const request = store.get(sessionId);
    request.onsuccess = () => {
      const record = request.result as RecordingCompletion | undefined;
      if (!record || record.meetingId !== meetingId ||
          (status === "upload_succeeded" && !record.recordingId)) {
        fail(new Error("Upload outcome identity mismatch"));
        return;
      }
      store.put({ ...record, status, updatedAt: Date.now() });
      result(undefined);
    };
  });
}

/** The caller must independently verify processing and assets before persisting success. */
export async function claimReviewLaunch(sessionId: string): Promise<boolean> {
  return completionTransaction("readwrite", (store, result) => {
    const request = store.get(sessionId);
    request.onsuccess = () => {
      const record = request.result as RecordingCompletion | undefined;
      if (!record || record.status !== "processing_succeeded" || !record.recordingId) { result(false); return; }
      store.put({ ...record, status: "review_launch_pending", updatedAt: Date.now() });
      result(true);
    };
  });
}

export async function getCompletion(sessionId: string): Promise<RecordingCompletion | undefined> {
  return completionTransaction("readonly", (store, result) => {
    const request = store.get(sessionId);
    request.onsuccess = () => result(request.result);
  });
}

export async function getCapturingCompletion(tabId: number): Promise<RecordingCompletion | undefined> {
  const resolution = await completionTransaction<{ record?: RecordingCompletion; ambiguous: boolean }>("readwrite", (store, result) => {
    const request = store.index("capturedTabId").getAll(tabId);
    request.onsuccess = () => {
      const active = (request.result as RecordingCompletion[]).filter((record) => record.status === "capturing" && !record.captureError);
      if (active.length > 1) {
        // There is no safe winner, including when the UI projection is missing.
        // Commit the error for every candidate atomically before reporting it;
        // aborting here would roll back the feedback and a retry could pick another session.
        for (const record of active) store.put({ ...record, captureError: true, updatedAt: Date.now() });
        result({ ambiguous: true });
      } else result({ record: active[0], ambiguous: false });
    };
  });
  if (resolution.ambiguous) throw new Error("Ambiguous active recording for captured tab");
  return resolution.record;
}

export async function claimCompletion(sessionId: string, trigger: CompletionTrigger): Promise<boolean> {
  return completionTransaction("readwrite", (store, result) => {
    const request = store.get(sessionId);
    request.onsuccess = () => {
      const record = request.result as RecordingCompletion | undefined;
      if (!record || record.captureError) { result(false); return; }
      const decision = applyCompletionEvent({ ...record, completionClaimed: record.status !== "capturing" }, trigger);
      if (decision.shouldFinalize) {
        store.put({ ...record, status: "finalizing", trigger: trigger === "stop" ? "stop" : "captured_tab_closed", updatedAt: Date.now() });
      }
      result(decision.shouldFinalize);
    };
  });
}

// Finalizing is a durable outbox: replay is safe because offscreen checks sessionId
// and MediaRecorder state. Failed captures retain their chunks and identity.
export async function getPendingFinalizations(): Promise<RecordingCompletion[]> {
  return completionTransaction("readonly", (store, result) => {
    const request = store.getAll();
    request.onsuccess = () => result((request.result as RecordingCompletion[]).filter(r => r.status === "finalizing" && !r.captureError));
  });
}

export async function settleCapture(sessionId: string, failed = false): Promise<void> {
  return completionTransaction("readwrite", (store, result) => {
    const request = store.get(sessionId);
    request.onsuccess = () => {
      const record = request.result as RecordingCompletion | undefined;
      if (record && (!record.captureError || failed) && (record.status === "capturing" || record.status === "finalizing")) {
        store.put({ ...record, captureError: failed, status: failed ? record.status : "upload_pending", updatedAt: Date.now() });
      }
      result(undefined);
    };
  });
}

export interface ChunkRecord {
  sessionId: string;
  blob: Blob;
  timestamp: number;
}

export function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    let blocked = false;
    request.onblocked = () => {
      blocked = true;
      reject(new Error("Recording database upgrade blocked; close older extension contexts and retry"));
    };

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
        store.createIndex("by_session", "sessionId", { unique: false });
      }
      if (!db.objectStoreNames.contains(COMPLETION_STORE)) {
        const completion = db.createObjectStore(COMPLETION_STORE, { keyPath: "sessionId" });
        completion.createIndex("capturedTabId", "capturedTabId", { unique: false });
      }
    };

    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => db.close();
      if (blocked) db.close();
      else resolve(db);
    };
    request.onerror = () => reject(request.error);
  });
}

export async function storeChunk(sessionId: string, blob: Blob): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const record: ChunkRecord = {
      sessionId,
      blob,
      timestamp: Date.now(),
    };
    const request = store.add(record);
    request.onerror = () => reject(request.error);
    tx.onabort = tx.onerror = () => { db.close(); reject(tx.error ?? new Error("Chunk write failed")); };
    tx.oncomplete = () => { db.close(); resolve(); };
  });
}

export async function getChunksBySession(sessionId: string): Promise<Blob[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("by_session");
    const request = index.getAll(sessionId);
    request.onsuccess = () => {
      const records = request.result as ChunkRecord[];
      // Sort by timestamp to ensure correct order
      records.sort((a, b) => a.timestamp - b.timestamp);
      resolve(records.map((r) => r.blob));
    };
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

/**
 * Remove all chunks for a given session from IndexedDB.
 */
export async function clearSession(sessionId: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("by_session");
    const request = index.openCursor(sessionId);
    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) {
        cursor.delete();
        cursor.continue();
      }
    };
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => {
      db.close();
      reject(tx.error);
    };
  });
}

/**
 * Reads all chunks for a session and assembles them into a single Blob
 * with the specified mimeType.
 */
export async function assembleBlob(
  sessionId: string,
  mimeType: string
): Promise<Blob> {
  const blobs = await getChunksBySession(sessionId);
  return new Blob(blobs, { type: mimeType });
}
