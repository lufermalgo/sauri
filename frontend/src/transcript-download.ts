import { getDiarization, getSpeakerReview, getTranscript } from "./api";
import { meeting as text } from "./copy/meeting";
import { titleToFilename } from "./download-filename";
import { presentTranscriptTurns } from "./transcript-presentation";
import { transcriptToText } from "./transcript-export";

/** Starts a browser download of `content` as a UTF-8 text file. */
export function saveTextFile(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Give the browser time to start reading the download before releasing it.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function transcriptFilename(meetingId: string, title: string | null | undefined): string {
  return titleToFilename(title, "txt") ?? text.transcriptFilename(meetingId);
}

/** A recording without speaker data is exported with generic names; any other failure is an error. */
async function optional<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (error) {
    const missing = error instanceof Error &&
      (error.message === "Error 404" || (error as { reason?: unknown }).reason === "not_found");
    if (missing) return null;
    throw error;
  }
}

export class EmptyTranscriptError extends Error {
  constructor() {
    super("empty transcript");
  }
}

/**
 * Fetches a recording's transcript and downloads it as `<title>.txt`: the same file the recording's
 * download menu produces (reviewed speaker names included). Rejects when it cannot be prepared.
 */
export async function downloadMeetingTranscript(meetingId: string, title: string | null | undefined): Promise<void> {
  const [transcript, diarization, review] = await Promise.all([
    getTranscript(meetingId), optional(getDiarization(meetingId)), optional(getSpeakerReview(meetingId)),
  ]);
  const turns = presentTranscriptTurns(transcript, diarization, review);
  if (turns.length === 0) throw new EmptyTranscriptError();
  saveTextFile(transcriptFilename(meetingId, title), transcriptToText(turns));
}
