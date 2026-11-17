// Small persistent log of capture events. Chrome's console output is lost when the service
// worker sleeps, so the reason a capture was cancelled used to vanish. Only event names and
// technical codes are stored: never titles, URLs or any meeting content.

export interface DiagnosticEntry {
  at: string;
  event: string;
  detail?: string;
}

export const DIAGNOSTICS_KEY = "sauriDiagnostics";
export const DIAGNOSTICS_LIMIT = 50;

let queue: Promise<void> = Promise.resolve();

/** Appends one entry, keeping the newest DIAGNOSTICS_LIMIT. Never throws: logging must not break a recording. */
export function logDiagnostic(event: string, detail?: string): Promise<void> {
  const entry: DiagnosticEntry = { at: new Date().toISOString(), event, ...(detail ? { detail: detail.slice(0, 200) } : {}) };
  queue = queue.then(async () => {
    try {
      const stored = await chrome.storage.local.get(DIAGNOSTICS_KEY);
      const previous = Array.isArray(stored?.[DIAGNOSTICS_KEY]) ? stored[DIAGNOSTICS_KEY] as DiagnosticEntry[] : [];
      await chrome.storage.local.set({ [DIAGNOSTICS_KEY]: [...previous, entry].slice(-DIAGNOSTICS_LIMIT) });
    } catch { /* Storage unavailable: the console line is all that remains. */ }
  });
  return queue;
}

export function errorCode(error: unknown): string {
  return error instanceof Error ? `${error.name}: ${error.message}` : String(error);
}
