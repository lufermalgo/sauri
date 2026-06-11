// Cola de subida idempotente en IndexedDB para la extensión sauri.
// Estados: pending → processing → done/failed
// Reintentos con la misma clave_idempotencia sin duplicar subidas.
// Recuperación por chrome.alarms y chrome.runtime.onStartup.

export type UploadJobStatus = "pending" | "processing" | "done" | "failed";

export interface UploadJob {
  id: string;
  sessionId: string;
  claveIdempotencia: string;
  status: UploadJobStatus;
  retryCount: number;
  maxRetries: number;
  createdAt: number;
  lastAttemptAt?: number;
  errorMessage?: string;
  blobBase64: string;
  mimeType: string;
  notificationEmittedAt?: string;
}

export type EnqueueUploadInput = Pick<
  UploadJob,
  "sessionId" | "claveIdempotencia" | "blobBase64" | "mimeType" | "notificationEmittedAt"
>;

const DB_NAME = "sauri-upload-queue";
const DB_VERSION = 1;
const STORE_NAME = "jobs";

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("status", "status", { unique: false });
        store.createIndex("createdAt", "createdAt", { unique: false });
        store.createIndex("claveIdempotencia", "claveIdempotencia", { unique: true });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * Adds a new upload job to the queue with status='pending', retryCount=0, maxRetries=3.
 * Uses sessionId as clave_idempotencia to prevent duplicates.
 */
export async function enqueueUpload(input: EnqueueUploadInput): Promise<UploadJob> {
  const db = await openDB();
  const job: UploadJob = {
    id: crypto.randomUUID(),
    sessionId: input.sessionId,
    claveIdempotencia: input.claveIdempotencia,
    status: "pending",
    retryCount: 0,
    maxRetries: 3,
    createdAt: Date.now(),
    blobBase64: input.blobBase64,
    mimeType: input.mimeType,
    notificationEmittedAt: input.notificationEmittedAt,
  };

  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    const store = tx.objectStore(STORE_NAME);
    const request = store.add(job);
    request.onsuccess = () => resolve(job);
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
export async function markProcessing(jobId: string): Promise<void> {
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
      job.status = "processing";
      job.lastAttemptAt = Date.now();
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
