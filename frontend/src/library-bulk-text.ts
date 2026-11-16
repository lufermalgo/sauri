import { t } from "./i18n";

/** "Deleted 3 recordings." or, when some failed, "Deleted 2; 1 couldn't be deleted." */
export function bulkDeletedText(done: number, failed: number): string {
  return failed === 0
    ? t("library:bulk.deleted", { count: done })
    : t("library:bulk.deletedPartial", { done, failed: t("library:bulk.deleteFailedCount", { count: failed }) });
}

/** Same for downloads; `summaries` picks the wording for summaries instead of transcripts. */
export function bulkDownloadedText(done: number, failed: number, summaries = false): string {
  if (failed === 0) {
    return summaries
      ? t("library:bulk.downloadedSummaries", { count: done })
      : t("library:bulk.downloadedTranscripts", { count: done });
  }
  return t("library:bulk.downloadedPartial", { done, failed: t("library:bulk.downloadFailedCount", { count: failed }) });
}
