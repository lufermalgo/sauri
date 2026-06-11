// Shared IndexedDB helpers for the sauri-recordings database.
// Used by both offscreen.ts (write chunks) and background.ts (read/assemble/clear).
// This module has NO side effects — all operations are explicit function calls.

export const DB_NAME = "sauri-recordings";
export const DB_VERSION = 1;
export const STORE_NAME = "chunks";

export interface ChunkRecord {
  sessionId: string;
  blob: Blob;
  timestamp: number;
}

export function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
        store.createIndex("by_session", "sessionId", { unique: false });
      }
    };

    request.onsuccess = () => resolve(request.result);
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
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
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
