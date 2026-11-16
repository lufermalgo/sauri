import { useEffect, useRef } from "react";
import { copy } from "../copy/es";
import type { BulkRun } from "./useLibraryBulk";
import { Button, Dialog, ProgressBar } from "./ui";

const text = copy.library.bulk;

interface LibraryBulkDialogProps {
  run: BulkRun;
  onStop: () => void;
  onRetry: () => void;
  onClose: () => void;
  /** Where focus goes when the dialog closes (the list header, since rows may be gone). */
  returnFocus: () => HTMLElement | null;
}

function resultSentence(run: BulkRun): string {
  if (run.ids.length === 0) return text.noneReady;
  const done = run.succeeded.length;
  const failed = run.failed.length;
  return run.kind === "delete" ? text.deleted(done, failed) : text.downloaded(done, failed);
}

/**
 * Progress and result of a bulk action. While it runs, Escape and the close button ask it to stop
 * (the remaining recordings are left alone); the live region announces progress and the result.
 */
export function LibraryBulkDialog({ run, onStop, onRetry, onClose, returnFocus }: LibraryBulkDialogProps) {
  const running = run.phase === "running";
  const closeButton = useRef<HTMLButtonElement>(null);
  const total = run.ids.length;
  const processed = run.succeeded.length + run.failed.length;

  // When the run ends the keyboard user is already on the next useful control.
  useEffect(() => {
    if (!running) closeButton.current?.focus();
  }, [running]);

  const title = running
    ? (run.kind === "delete" ? text.runningDeleteTitle : text.runningDownloadTitle)
    : (run.kind === "delete" ? text.doneDeleteTitle : text.doneDownloadTitle);
  const progress = run.kind === "delete" ? text.deleting(run.current, total) : text.downloading(run.current, total);
  const notes = running ? [] : [
    run.skipped > 0 ? text.skippedNotReady(run.skipped) : null,
    run.notProcessed.length > 0 ? text.notProcessed(run.notProcessed.length) : null,
    run.failed.length > 0 && run.kind === "delete" ? text.failedKept : null,
  ].filter((note): note is string => note !== null);

  return (
    <Dialog title={title} size="sm" closeLabel={text.close} returnFocus={returnFocus}
      onClose={running ? onStop : onClose}>
      <div className="library-bulk-dialog">
        <p role="status" className="library-bulk-status">
          {running ? (run.stopping ? text.stopping : progress) : resultSentence(run)}
        </p>
        {running && (
          <ProgressBar label={text.progressLabel} value={total === 0 ? 0 : Math.round((processed / total) * 100)}
            valueText={progress} />
        )}
        {notes.map((note) => <p key={note} className="library-bulk-note">{note}</p>)}
        <div className="library-bulk-actions">
          {running ? (
            <Button variant="secondary" size="sm" disabled={run.stopping} onClick={onStop}>{text.stop}</Button>
          ) : (
            <>
              {run.failed.length > 0 && <Button variant="secondary" size="sm" onClick={onRetry}>{text.retry}</Button>}
              <button ref={closeButton} type="button" className="ui-button ui-button--primary ui-button--sm"
                onClick={onClose}>{text.close}</button>
            </>
          )}
        </div>
      </div>
    </Dialog>
  );
}
