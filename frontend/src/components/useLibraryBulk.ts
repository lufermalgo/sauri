import { useCallback, useEffect, useRef, useState } from "react";

export type BulkKind = "delete" | "download";

export interface BulkRun {
  kind: BulkKind;
  phase: "running" | "done";
  /** Everything this run was asked to process. */
  ids: string[];
  /** 1-based position of the item being processed. */
  current: number;
  succeeded: string[];
  failed: string[];
  /** Left unprocessed because the user stopped the run. */
  notProcessed: string[];
  /** Selected recordings that do not apply to the action (e.g. no transcript yet). */
  skipped: number;
  stopping: boolean;
}

/**
 * Runs one action over many recordings, one at a time (a concurrency of 1: the API and the browser's
 * download manager both cope badly with bursts), keeps going after an individual failure and lets the
 * user stop between items. `perform` must reject when an item fails.
 */
export function useLibraryBulk(perform: (kind: BulkKind, id: string) => Promise<void>) {
  const [run, setRun] = useState<BulkRun | null>(null);
  const performRef = useRef(perform);
  performRef.current = perform;
  const stopRequested = useRef(false);
  const alive = useRef(true);
  const busy = useRef(false);
  useEffect(() => () => { alive.current = false; }, []);

  const start = useCallback(async (kind: BulkKind, ids: string[], skipped = 0) => {
    if (busy.current || ids.length === 0) return;
    busy.current = true;
    stopRequested.current = false;
    const succeeded: string[] = [];
    const failed: string[] = [];
    let notProcessed: string[] = [];
    const publish = (patch: Partial<BulkRun>) => {
      if (!alive.current) return;
      setRun({
        kind, phase: "running", ids, current: 1, succeeded: [...succeeded], failed: [...failed],
        notProcessed, skipped, stopping: stopRequested.current, ...patch,
      });
    };
    publish({});
    for (let index = 0; index < ids.length; index += 1) {
      if (stopRequested.current || !alive.current) {
        notProcessed = ids.slice(index);
        break;
      }
      publish({ current: index + 1 });
      try {
        await performRef.current(kind, ids[index]);
        succeeded.push(ids[index]);
      } catch {
        failed.push(ids[index]);
      }
    }
    busy.current = false;
    publish({ phase: "done", current: ids.length });
  }, []);

  const stop = useCallback(() => {
    stopRequested.current = true;
    setRun((current) => (current?.phase === "running" ? { ...current, stopping: true } : current));
  }, []);

  const retry = useCallback(() => {
    if (run && run.failed.length > 0) void start(run.kind, run.failed, run.skipped);
  }, [run, start]);

  const close = useCallback(() => setRun(null), []);

  /** Shows a finished run that never started (nothing applied), e.g. no transcript is ready. */
  const showEmpty = useCallback((kind: BulkKind, skipped: number) => {
    setRun({ kind, phase: "done", ids: [], current: 0, succeeded: [], failed: [], notProcessed: [], skipped, stopping: false });
  }, []);

  return { run, start, stop, retry, close, showEmpty };
}
