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
  /** Short-lived signed link to the preview frame; absent until one exists. */
  thumbnail_url?: string | null;
  media_kind?: MediaKind | null;
}

/** What the recording turned out to be, when the backend knows. */
export type MediaKind = "video" | "audio";

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
  thumbnailUrl: string | null;
  mediaKind: MediaKind | null;
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

/** One bullet of a thematic block, with optional nested detail. */
export interface SummaryItem {
  text: string;
  subItems: string[];
}

/** Thematic block of a structured (schema v2) summary. Sources are metadata, never shown as text. */
export interface SummaryBlock {
  title: string;
  items: SummaryItem[];
  sources: SummarySource[];
}

/**
 * Current successful summary artifact. Schema v1 keeps flat points (some legacy ones without
 * citations); schema v2 carries thematic blocks and a conclusion.
 */
export interface MeetingSummary {
  summaryId: string;
  meetingId: string;
  templateId: string;
  templateName: string;
  templateVersion: number;
  topic: string;
  schemaVersion?: 1 | 2;
  keyPoints: Array<SummaryKeyPoint | SummaryBlock | string>;
  conclusion?: string | null;
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
  /** ISO 8601 UTC time the request was accepted; absent on requests that predate the field. */
  requestedAt?: string | null;
  /** ISO 8601 UTC time the worker first took the job; absent until it starts. */
  startedAt?: string | null;
}

/** Pipeline stages a user can explicitly regenerate (POST /api/v1/meetings/{id}/regenerate). */
export type RegenerationStage = "transcription" | "speakers" | "summary";

/** Body of POST /api/v1/meetings/{id}/regenerate; `cascade` is off unless asked for. */
export interface RegenerationRequest {
  stage: RegenerationStage;
  /** Summary template; applies to a summary run or to a cascade that ends in one. */
  template_id?: string;
  cascade?: boolean;
}

/** Wire form of one regeneration operation (202 on request, then GET .../regenerate/{id|latest}). */
export interface RegenerationOperationResponse {
  operation_id: string;
  meeting_id: string;
  stage: RegenerationStage;
  status: "accepted" | "running" | "succeeded" | "failed";
  cascade: boolean;
  requested_at: string;
  started_at?: string;
  finished_at?: string;
  failure_cause?: string;
  /** Stages this operation computes again. */
  replaces: RegenerationStage[];
  /** Existing later outputs left visible but out of date; the UI may suggest regenerating them. */
  stale: RegenerationStage[];
  parent_operation_id?: string;
  next_operation_id?: string;
  summary_request_id?: string;
  /** Content-free outcome, e.g. how many speaker names were carried over. */
  details?: Record<string, unknown>;
}

/** Optional additions to GET /api/v1/meetings/{id}; each is omitted when empty. */
export interface MeetingRegenerationHints {
  stale_stages?: RegenerationStage[];
  active_operation?: Pick<RegenerationOperationResponse, "operation_id" | "stage" | "status" | "requested_at" | "started_at">;
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

export * from "./engines";
