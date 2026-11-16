import { useEffect, useRef } from "react";
import type { BulkRun } from "./useLibraryBulk";
import { Button, Dialog, ProgressBar } from "./ui";
import { t, useT } from "../i18n";
import { bulkDeletedText, bulkDownloadedText } from "../library-bulk-text";

interface LibraryBulkDialogProps {
  run: BulkRun;
  onStop: () => void;
  onRetry: () => void;
  onClose: () => void;
  /** Where focus goes when the dialog closes (the list header, since rows may be gone). */
  returnFocus: () => HTMLElement | null;
}

function resultSentence(run: BulkRun): string {
  if (run.ids.length === 0) return run.kind === "downloadSummary" ? t("library:bulk.noneWithSummary") : t("library:bulk.noneReady");
  const done = run.succeeded.length;
  const failed = run.failed.length;
  if (run.kind === "delete") return bulkDeletedText(done, failed);
  return bulkDownloadedText(done, failed, run.kind === "downloadSummary");
}

/**
 * Progress and result of a bulk action. While it runs, Escape and the close button ask it to stop
 * (the remaining recordings are left alone); the live region announces progress and the result.
 */
export function LibraryBulkDialog({ run, onStop, onRetry, onClose, returnFocus }: LibraryBulkDialogProps) {
  const { t } = useT();
  const running = run.phase === "running";
  const closeButton = useRef<HTMLButtonElement>(null);
  const total = run.ids.length;
  const processed = run.succeeded.length + run.failed.length;

  // When the run ends the keyboard user is already on the next useful control.
  useEffect(() => {
    if (!running) closeButton.current?.focus();
  }, [running]);

  const runningDownloadTitle = run.kind === "downloadSummary" ? t("library:bulk.runningDownloadSummariesTitle") : t("library:bulk.runningDownloadTitle");
  const title = running
    ? (run.kind === "delete" ? t("library:bulk.runningDeleteTitle") : runningDownloadTitle)
    : (run.kind === "delete" ? t("library:bulk.doneDeleteTitle") : t("library:bulk.doneDownloadTitle"));
  const progress = run.kind === "delete" ? t("library:bulk.deleting", { current: run.current, total }) : t("library:bulk.downloading", { current: run.current, total });
  const notes = running ? [] : [
    run.skipped > 0
      ? (run.kind === "downloadSummary" ? t("library:bulk.skippedNoSummary", { count: run.skipped }) : t("library:bulk.skippedNotReady", { count: run.skipped }))
      : null,
    run.notProcessed.length > 0 ? t("library:bulk.notProcessed", { count: run.notProcessed.length }) : null,
    run.failed.length > 0 && run.kind === "delete" ? t("library:bulk.failedKept") : null,
  ].filter((note): note is string => note !== null);

  return (
    <Dialog title={title} size="sm" closeLabel={t("library:bulk.close")} returnFocus={returnFocus}
      onClose={running ? onStop : onClose}>
      <div className="library-bulk-dialog">
        <p role="status" className="library-bulk-status">
          {running ? (run.stopping ? t("library:bulk.stopping") : progress) : resultSentence(run)}
        </p>
        {running && (
          <ProgressBar label={t("library:bulk.progressLabel")} value={total === 0 ? 0 : Math.round((processed / total) * 100)}
            valueText={progress} />
        )}
        {notes.map((note) => <p key={note} className="library-bulk-note">{note}</p>)}
        <div className="library-bulk-actions">
          {running ? (
            <Button variant="secondary" size="sm" disabled={run.stopping} onClick={onStop}>{t("library:bulk.stop")}</Button>
          ) : (
            <>
              {run.failed.length > 0 && <Button variant="secondary" size="sm" onClick={onRetry}>{t("library:bulk.retry")}</Button>}
              <button ref={closeButton} type="button" className="ui-button ui-button--primary ui-button--sm"
                onClick={onClose}>{t("library:bulk.close")}</button>
            </>
          )}
        </div>
      </div>
    </Dialog>
  );
}
