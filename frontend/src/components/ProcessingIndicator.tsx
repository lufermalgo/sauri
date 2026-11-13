import { useEffect, useRef, useState } from "react";
import { getProcessing, type ProcessingSnapshot } from "../api";
import copy from "../../messages/processing.es.json";

// Localized user-facing copy is data, separate from English code identifiers.
const LABELS: Record<string, string> = copy.stages;
const STATES: Record<string, string> = copy.states;

interface Props {
  meetingId: string;
  onReady?: (snapshot: ProcessingSnapshot) => Promise<void>;
  onPending?: () => void;
  onProgress?: (snapshot: ProcessingSnapshot) => Promise<void>;
}

/** Polls reads only. A transport error is never a failed processing job. */
export function ProcessingIndicator({ meetingId, onReady, onPending, onProgress }: Props) {
  const [confirmed, setConfirmed] = useState<ProcessingSnapshot | null>(null);
  const [queryFailed, setQueryFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  const callbacks = useRef({ onReady, onPending, onProgress });
  callbacks.current = { onReady, onPending, onProgress };

  useEffect(() => {
    setConfirmed(null);
    setQueryFailed(false);
  }, [meetingId]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();
    let deliveredExecution: string | undefined;

    async function poll() {
      try {
        const snapshot = await getProcessing(meetingId, controller.signal);
        if (!active) return;
        const execution = JSON.stringify(snapshot.execution);
        if (snapshot.ready) {
          if (execution !== deliveredExecution) {
            await callbacks.current.onReady?.(snapshot);
            if (!active) return;
            deliveredExecution = execution;
          }
        } else {
          deliveredExecution = undefined;
          callbacks.current.onPending?.();
          await callbacks.current.onProgress?.(snapshot);
          if (!active) return;
        }
        setConfirmed(snapshot);
        setQueryFailed(false);
      } catch {
        if (!active) return;
        setQueryFailed(true);
      }
      if (active) timer = window.setTimeout(poll, 2000);
    }
    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [meetingId, retry]);

  // Never render the previous meeting while its cleanup/new effect is pending.
  const snapshot = confirmed?.meeting_id === meetingId ? confirmed : null;
  return (
    <section aria-label={copy.region}>
      {queryFailed && (
        <div role="alert">
          <p>{copy.queryError}</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>{copy.retryQuery}</button>
        </div>
      )}
      {queryFailed && snapshot && <p>{copy.lastConfirmed}</p>}
      <p role="status">
        {!snapshot ? copy.querying : snapshot.failed
          ? copy.failed
          : snapshot.ready ? copy.ready
          : snapshot.stages.some((stage) => stage.state === "active")
            ? copy.active
            : copy.pending}
      </p>
      {snapshot && !snapshot.ready && <p>{copy.partial}</p>}
      {snapshot && !snapshot.ready && !snapshot.failed && <progress aria-label={copy.progress} />}
      {snapshot && <ul>{snapshot.stages.map((stage) => (
        <li key={stage.key}>{LABELS[stage.key] ?? copy.unknownStage}: {STATES[stage.state] ?? copy.states.unavailable}</li>
      ))}</ul>}
      {snapshot?.ready && <p>{copy.humanReview}</p>}
    </section>
  );
}
