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
  /** The engine found no speech in the recording; a terminal, expected outcome. */
  NoSpeechDetected = "no_speech_detected",
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

/** Raw meeting-list record returned by GET /api/v1/meetings. */
export interface MeetingListApiResponse {
  meeting_id: string;
  meet_link: string | null;
  origin: MeetingOrigin;
  process_state: ProcessState;
  failure_cause: FailureCause | null;
  created_at: string | null;
  title: string;
  duration_seconds?: number | null;
  speaker_count?: number | null;
  summary_topic?: string | null;
}

/** Meeting-list record normalized for frontend presentation and selection. */
export interface MeetingListItem {
  id: string;
  meetLink: string | null;
  origin: MeetingOrigin;
  processState: ProcessState;
  failureCause: FailureCause | null;
  createdAt: string | null;
  title: string;
  durationSeconds: number | null;
  speakerCount: number | null;
  summaryTopic: string | null;
}

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

export interface SummarySource {
  passageId: string;
  startMs: number;
  endMs: number;
}

export interface SummaryKeyPoint {
  text: string;
  sources: SummarySource[];
}

/** Current successful summary artifact, including legacy points without citations. */
export interface MeetingSummary {
  summaryId: string;
  meetingId: string;
  templateId: string;
  templateName: string;
  templateVersion: number;
  topic: string;
  keyPoints: Array<SummaryKeyPoint | string>;
  reviewState: "draft";
  generation: number;
  createdAt: string;
  updatedAt: string;
}

/** Durable lifecycle state of one accepted summary request. */
export interface SummaryRequestStatus {
  eventId: string;
  generation: number;
  status: "pending" | "running" | "succeeded" | "failed";
  failureCause?: string | null;
}

/** User-owned summary template; instructions are opaque and preserved unchanged. */
export interface SummaryTemplate {
  id: string;
  name: string;
  ownerId: string;
  categoryId?: string;
  version: number;
  instructions: string;
  isDefault: boolean;
  createdAt: string;
  updatedAt: string;
}

/** Optional owner-scoped grouping for personal templates. */
export interface TemplateCategory {
  id: string;
  name: string;
  ownerId: string;
  createdAt: string;
}

/** How GET /meetings/{id}/transcript presents speech: attributed word turns or legacy segments. */
export type TranscriptPresentation = "words" | "segments";

/** Speaker turn built from attributed words of the latest completed diarization revision. */
export interface AttributedTurn {
  sequence: number;
  speakerId: string | null;
  speakerLabel: string | null;
  startMs: number;
  endMs: number;
  text: string;
  wordCount: number;
  hasAmbiguous: boolean;
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
