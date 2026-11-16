import type { MeetingSummary } from "@sauri/shared-types";
import { getMeetingSummary } from "./api";
import { titleToFilename } from "./download-filename";
import { summaryPlainText } from "./summary-export";
import { saveTextFile } from "./transcript-download";
import { t } from "./i18n";

/** `<title> - resumen.txt`: distinct from the transcript's `<title>.txt` so both can sit in one folder. */
export function summaryFilename(meetingId: string, title: string | null | undefined): string {
  return titleToFilename(title, "txt", t("meeting:summaryFilenameSuffix")) ?? t("meeting:summaryFilename", { id: meetingId });
}

export class NoSummaryError extends Error {
  constructor() {
    super("no summary");
  }
}

/** Fetches the latest summary and downloads it as plain text. Rejects with `NoSummaryError` when there is none yet. */
export async function downloadMeetingSummary(meetingId: string, title: string | null | undefined): Promise<void> {
  const summary = await getMeetingSummary(meetingId);
  if (summary === null) throw new NoSummaryError();
  saveTextFile(summaryFilename(meetingId, title), summaryPlainText(summary));
}
