// Shared core types (extension/src/core). No DOM/network dependencies.

export type CaptureState = "idle" | "recording" | "stopping";
export type CaptureEvent = "start" | "stop" | "finished" | "start_failure";

export type ViewState = "loading" | "withData" | "empty" | "error";

export interface RemoteRequest<T> {
  phase: "initial" | "in_progress" | "success" | "failure";
  data: T[] | null;
  previous: T[] | null;
}

export interface NoteDTO {
  meetingId: string;
  title: string | null;
  processState: string;
  createdAt: string | null;
}

export interface NoteCard {
  meetingId: string;
  displayedTitle: string;
  displayedDate: string;
  processState: string;
  createdAt: string | null;
}

export interface NotesFilter {
  processState?: string;
  from?: string; // ISO-8601
  to?: string; // ISO-8601
}

export interface SpeechTurnDTO {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
  sequence: number;
}

export interface TranscriptDTO {
  transcriptId: string;
  meetingId: string;
  segments: SpeechTurnDTO[];
}

export interface SpeakerDTO {
  id: string;
  label: string;
  sequence: number;
}

export interface SpeakerAssignmentDTO {
  turnId: string;
  speakerId: string;
}

export interface DiarizationDTO {
  diarizationId: string;
  meetingId: string;
  diarizationState: string;
  speakerCount: number;
  speakers: SpeakerDTO[];
  assignments: SpeakerAssignmentDTO[];
}

export interface InterventionDTO {
  turnId: string;
  text: string;
  startMs: number;
  endMs: number;
  sequence: number;
  speaker: SpeakerDTO | null;
}

export interface SpeakingTimeEntry {
  speaker: SpeakerDTO;
  timeMs: number;
}

export interface AuthAttempt {
  success: boolean;
  atMs: number;
}

export type CaptureSource = "picker" | "current-tab";

/** Expected picker outcomes are not recording failures. */
export type CaptureStartResult =
  | { ok: true; sessionId: string }
  | { ok: false; reason: "cancelled" | "no-tab-audio" | "unsupported-surface" | "busy" | "current-tab-unavailable" | "microphone-permission" | "failed" };

export type RecordingResolution = "480p" | "720p" | "1080p";

export interface RecordingSettings {
  countdownSeconds: 0 | 3 | 5 | 10;
  resolution: RecordingResolution;
  showControlBar: boolean;
  skipMicWarning: boolean;
}
