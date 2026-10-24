/**
 * @sauri/shared-types
 *
 * Domain types shared between the Chrome extension and the web frontend.
 * Reflect the data model defined in design.md.
 */

// --- Enums ---

/** Lifecycle state of a Meeting's capture and transcription process. */
export enum ProcessState {
  Queued = "queued",
  Joining = "joining",
  Recording = "recording",
  Transcribing = "transcribing",
  Completed = "completed",
  Failed = "failed",
}

/** Failure cause recorded when the state is "failed". */
export enum FailureCause {
  CouldNotJoin = "could_not_join",
  MeetingCancelled = "meeting_cancelled",
  EngineFailure = "engine_failure",
}

/** Origin of the Meeting record. */
export enum MeetingOrigin {
  Link = "link",
  CalendarInvite = "calendar_invite",
  Manual = "manual",
}

/** Origin of the recording capture. */
export enum CaptureOrigin {
  ChromeExtension = "chrome_extension",
  ServerBot = "server_bot",
  WebUpload = "web_upload",
}

// --- Interfaces ---

/** Record of a Google Meet meeting in sauri. */
export interface Meeting {
  id: string;
  meetLink: string | null;
  origin: MeetingOrigin;
  calendarInviteId?: string;
  scheduledStartTime?: string;
  processState: ProcessState;
  failureCause?: FailureCause;
  createdBy: string;
  createdAt: string;
}

/** Container for a meeting's recording (audio + video). */
export interface SessionRecording {
  id: string;
  meetingId: string;
  idempotencyKey: string;
  captureOrigin: CaptureOrigin;
  audioRef: string;
  videoRef?: string;
  durationSeconds: number;
  interrupted: boolean;
  expiresAt?: string;
  finishedAt: string;
}

/** Transcript document generated from the audio track. */
export interface Transcript {
  id: string;
  meetingId: string;
  language: string;
  provider: string;
  supportsTurns: boolean;
  expiresAt?: string;
  createdAt: string;
}

/** Timed speech segment within a Transcript. */
export interface SpeechTurn {
  id: string;
  transcriptId: string;
  text: string;
  startMs: number;
  endMs: number;
  sequence: number;
}
