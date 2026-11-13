// Idempotent upload queue in IndexedDB for the sauri extension.
// States: pending → processing → done/failed
// Retries with the same idempotencyKey never duplicate uploads.
// Recovery via chrome.alarms and chrome.runtime.onStartup.

export type UploadJobStatus = "pending" | "processing" | "done" | "failed";

export interface UploadJob {
  id: string;
  sessionId: string;
  meetingId?: string; // absent only for legacy jobs; never synthesize a meeting on retry
  idempotencyKey: string;
  status: UploadJobStatus;
  retryCount: number;
  maxRetries: number;
  createdAt: number;
  lastAttemptAt?: number;
  errorMessage?: string;
  mimeType: string;
  notificationEmittedAt?: string;
  title?: string;
  meetLink?: string;
  videoPresence?: "muxed" | "absent";
}

export type EnqueueUploadInput = Pick<
  UploadJob,
  "sessionId" | "meetingId" | "idempotencyKey" | "mimeType" | "notificationEmittedAt" | "title" | "meetLink" | "videoPresence"
>;

const DB_NAME = "sauri-upload-queue";
const DB_VERSION = 2; // bumped from 1 — see the v1 -> v2 migration below
const STORE_NAME = "jobs";

/**
 * Legacy (v1) on-disk shape of a record in the "jobs" store, kept only to
 * type the schema migration below.
 */
interface LegacyUploadJobV1 {
  id: string;
  sessionId: string;
  claveIdempotencia: string;
  status: UploadJobStatus;
  retryCount: number;
  maxRetries: number;
  createdAt: number;
  lastAttemptAt?: number;
  errorMessage?: string;
  mimeType: string;
  notificationEmittedAt?: string;
  titulo?: string;
  enlaceMeet?: string;
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;

      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("status", "status", { unique: false });
        store.createIndex("createdAt", "createdAt", { unique: false });
        store.createIndex("idempotencyKey", "idempotencyKey", { unique: true });
        return;
      }

      if (event.oldVersion < 2) {
        // Rename claveIdempotencia/titulo/enlaceMeet -> idempotencyKey/title/
        // meetLink on every existing record before touching the index, so
        // pending upload jobs are not lost (Design Decision 6).
        const store = request.transaction!.objectStore(STORE_NAME);
        const cursorRequest = store.openCursor();
        cursorRequest.onsuccess = () => {
          const cursor = cursorRequest.result;
          if (cursor) {
            const legacy = cursor.value as LegacyUploadJobV1;
            const { claveIdempotencia, titulo, enlaceMeet, ...rest } = legacy;
            const migrated: UploadJob = {
              ...rest,
              idempotencyKey: claveIdempotencia,
              title: titulo,
              meetLink: enlaceMeet,
            };
            cursor.update(migrated);
            cursor.continue();
          } else {
            // All records migrated — safe to swap the index now.
            store.createIndex("idempotencyKey", "idempotencyKey", { unique: true });
            if (store.indexNames.contains("claveIdempotencia")) {
              store.deleteIndex("claveIdempotencia");
            }
          }
        };
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Adds a new upload job to the queue with status='pending', retryCount=0, maxRetries=3.
 * Uses sessionId as idempotencyKey to prevent duplicates.
 */
export async function enqueueUpload(input: EnqueueUploadInput): Promise<UploadJob> {
  const db = await openDB();
  const job: UploadJob = {
    id: crypto.randomUUID(),
    sessionId: input.sessionId,
    meetingId: input.meetingId,
    idempotencyKey: input.idempotencyKey,
    status: "pending",
    retryCount: 0,
    maxRetries: 3,
    createdAt: Date.now(),
    mimeType: input.mimeType,
    notificationEmittedAt: input.notificationEmittedAt,
    title: input.title,
    meetLink: input.meetLink,
    videoPresence: input.videoPresence,
  };

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const request = store.add(job);
    tx.oncomplete = () => { db.close(); resolve(job); };
    tx.onabort = tx.onerror = () => { db.close(); reject(tx.error ?? request.error ?? new Error("Duplicate upload job")); };
  });
}

export async function getUploadJob(idempotencyKey: string): Promise<UploadJob | undefined> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const request = tx.objectStore(STORE_NAME).index("idempotencyKey").get(idempotencyKey);
    request.onsuccess = () => resolve(request.result as UploadJob | undefined);
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

/**
 * Returns the oldest pending job (by createdAt), or null if none.
 */
export async function getNextPendingJob(): Promise<UploadJob | null> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const index = store.index("status");
    const request = index.openCursor(IDBKeyRange.only("pending"));

    let oldest: UploadJob | null = null;

    request.onsuccess = () => {
      const cursor = request.result;
      if (cursor) {
        const job = cursor.value as UploadJob;
        if (!oldest || job.createdAt < oldest.createdAt) {
          oldest = job;
        }
        cursor.continue();
      } else {
        resolve(oldest);
      }
    };
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

/**
 * Sets a job's status to 'processing'.
 */
export async function markProcessing(jobId: string): Promise<boolean> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const getRequest = store.get(jobId);
    let claimed = false;
    getRequest.onsuccess = () => {
      const job = getRequest.result as UploadJob | undefined;
      if (job?.status !== "pending") return;
      claimed = true;
      job.status = "processing";
      job.lastAttemptAt = Date.now();
      store.put(job);
    };
    tx.oncomplete = () => { db.close(); resolve(claimed); };
    tx.onabort = tx.onerror = () => { db.close(); reject(tx.error ?? new Error("Upload claim failed")); };
  });
}

/**
 * Sets a job's status to 'done'.
 */
export async function markDone(jobId: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const getRequest = store.get(jobId);

    getRequest.onsuccess = () => {
      const job = getRequest.result as UploadJob | undefined;
      if (!job) {
        reject(new Error(`Job not found: ${jobId}`));
        return;
      }
      job.status = "done";
      store.put(job);
    };
    getRequest.onerror = () => reject(getRequest.error);
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
  });
}

/**
 * Increments retryCount; if retryCount >= maxRetries sets status='failed',
 * else sets status='pending' (for retry on next cycle).
 */
export async function markFailed(jobId: string, error: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const getRequest = store.get(jobId);

    getRequest.onsuccess = () => {
      const job = getRequest.result as UploadJob | undefined;
      if (!job) {
        reject(new Error(`Job not found: ${jobId}`));
        return;
      }
      job.retryCount += 1;
      job.errorMessage = error;
      job.lastAttemptAt = Date.now();
      if (job.retryCount >= job.maxRetries) {
        job.status = "failed";
      } else {
        job.status = "pending";
      }
      store.put(job);
    };
    getRequest.onerror = () => reject(getRequest.error);
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
  });
}

/**
 * Returns jobs that can still be retried: status='pending' or
 * status='processing' (stale — might have been interrupted).
 */
export async function getPendingAndFailedJobs(): Promise<UploadJob[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const store = tx.objectStore(STORE_NAME);
    const request = store.getAll();

    request.onsuccess = () => {
      const all = request.result as UploadJob[];
      // Jobs that can still be retried: pending, or processing (stale/interrupted)
      const retryable = all.filter(
        (j) => j.status === "pending" || j.status === "processing"
      );
      resolve(retryable);
    };
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}
