import { FailureCause } from "@sauri/shared-types";
import { t } from "./i18n";

// Honest progress estimate for meeting processing. The backend reports stages, never a percentage,
// so everything here is an estimate derived from measured speeds and elapsed wall-clock time.

/** Measured on the owner's Mac; tune here when the engines change. */
export const ESTIMATE_FACTORS = {
  /** Transcription seconds per second of audio (54 min audio → ~313 s). */
  transcriptionPerAudioSecond: 0.1,
  /** Speaker identification, roughly constant. */
  speakersSeconds: 15,
  /** Summary seconds per second of audio, with a floor (54 min → ~381 s). */
  summaryPerAudioSecond: 0.12,
  summaryMinSeconds: 60,
} as const;

/** The estimate never claims more than this until the work really finishes. */
export const PROGRESS_CAP = 0.95;

/** Failure cause for a recording without detected speech: an expected outcome, shown as its own message. */
export const NO_SPEECH_CAUSE = FailureCause.NoSpeechDetected;

export type ActiveStage = "transcription" | "speakers" | "summary";
export const ACTIVE_STAGES: readonly ActiveStage[] = ["transcription", "speakers", "summary"];

/** Stage as observed by the page, plus the non-estimable situations. */
export type DetectedStage = ActiveStage | "done" | "live" | "failed" | "unknown";

/** What the page knows about the automatic summary. */
export type SummarySignal =
  | "waiting" // a request is pending or running
  | "expected" // speakers just finished; the automatic request may not be visible yet
  | "settled" // a summary exists, or the latest request ended
  | "none"; // nothing requested and nothing expected

export interface StageSignals {
  processState: string | undefined;
  hasTranscript: boolean;
  diarizationNotFound: boolean;
  hasDiarization: boolean;
  summary: SummarySignal;
}

export function detectProcessingStage(signals: StageSignals): DetectedStage {
  const { processState, hasTranscript, diarizationNotFound, hasDiarization, summary } = signals;
  switch (processState) {
    case "failed": return "failed";
    case "joining":
    case "recording": return "live";
    case "queued": return "transcription";
    case "transcribing":
      return hasTranscript && diarizationNotFound ? "speakers" : "transcription";
    case "completed":
      // completed means ASR is done; speakers and summary may still be running.
      if (hasTranscript && diarizationNotFound) return "speakers";
      if (hasDiarization && (summary === "waiting" || summary === "expected")) return "summary";
      return "done";
    default: return "unknown";
  }
}

/**
 * Plain-language label of a detected stage. The meeting header and the stepper both read it, so
 * the header never says the meeting is ready while a stage is still running.
 */
export function stageLabel(stage: DetectedStage, processState: string | undefined): string {
  switch (stage) {
    case "transcription": return processState === "queued" ? t("processing:queued") : t("processing:transcribing");
    case "speakers": return t("processing:identifying");
    case "summary": return t("processing:summarizing");
    case "done": return t("meeting:ready");
    case "failed": return t("processing:failed");
    case "live": return processState === "joining" ? t("processing:joining") : t("processing:recording");
    case "unknown": return t("processing:unknown");
  }
}

export function expectedStageSeconds(audioSeconds: number): Record<ActiveStage, number> {
  const audio = Math.max(0, audioSeconds);
  return {
    transcription: ESTIMATE_FACTORS.transcriptionPerAudioSecond * audio,
    speakers: ESTIMATE_FACTORS.speakersSeconds,
    summary: Math.max(ESTIMATE_FACTORS.summaryMinSeconds, ESTIMATE_FACTORS.summaryPerAudioSecond * audio),
  };
}

export interface EstimateInput {
  stage: ActiveStage;
  audioSeconds: number | null | undefined;
  /** Seconds since the upload (meeting createdAt). */
  elapsedSinceUploadSeconds: number;
  /** Seconds since this page saw the stage begin; null when the page opened mid-stage. */
  stageElapsedSeconds?: number | null;
}

export interface ProcessingEstimate {
  /** Overall fraction 0..PROGRESS_CAP. */
  fraction: number;
  /** Rounded overall percentage, never above 95. */
  percent: number;
  /** Estimated seconds left; null when the current stage is past its expected time. */
  remainingSeconds: number | null;
  /** The current stage is taking longer than measured. */
  overtime: boolean;
  /** Expected seconds of the current stage. */
  stageExpectedSeconds: number;
}

/** Null when the audio duration is unknown: then there is nothing honest to estimate. */
export function estimateProgress(input: EstimateInput): ProcessingEstimate | null {
  const { stage, audioSeconds } = input;
  if (typeof audioSeconds !== "number" || !Number.isFinite(audioSeconds) || audioSeconds <= 0) return null;
  const expected = expectedStageSeconds(audioSeconds);
  const index = ACTIVE_STAGES.indexOf(stage);
  const total = ACTIVE_STAGES.reduce((sum, key) => sum + expected[key], 0);
  const before = ACTIVE_STAGES.slice(0, index).reduce((sum, key) => sum + expected[key], 0);
  const after = ACTIVE_STAGES.slice(index + 1).reduce((sum, key) => sum + expected[key], 0);
  const stageExpected = expected[stage];
  // Opened mid-stage: assume earlier stages took their nominal time since the upload.
  const stageElapsed = Math.max(0, input.stageElapsedSeconds ??
    Math.max(0, input.elapsedSinceUploadSeconds) - before);
  const overtime = stageElapsed > stageExpected;
  const stageDone = Math.min(stageElapsed, stageExpected);
  const fraction = Math.min(PROGRESS_CAP, (before + stageDone) / total);
  return {
    fraction,
    percent: Math.round(fraction * 100),
    remainingSeconds: overtime ? null : stageExpected - stageElapsed + after,
    overtime,
    stageExpectedSeconds: stageExpected,
  };
}

/** `m:ss`, or `h:mm:ss` from one hour on. */
export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

/** Whole minutes for plain-language texts, at least one. */
export function roundMinutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

/** Seconds since an ISO timestamp, or null when it is missing or invalid. */
export function secondsSince(iso: string | null | undefined, nowMs: number): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  return Number.isNaN(at) ? null : Math.max(0, (nowMs - at) / 1000);
}

/** "1 minute" / "3 minutes" (the plural form follows the active language). */
function minutesPhrase(minutes: number): string {
  return t("processing:minutes", { count: minutes });
}

/** Visible estimate of what is left, in whole minutes (a single minute reads "about a minute"). */
export function remainingText(minutes: number): string {
  return t("processing:remaining", { count: Math.max(1, minutes) });
}

export function explainTranscription(audioMinutes: number | null, stageMinutes: number | null): string {
  return audioMinutes && stageMinutes
    ? t("processing:explain.transcriptionTimed", { audio: minutesPhrase(audioMinutes), stage: minutesPhrase(stageMinutes) })
    : t("processing:explain.transcription");
}

export function explainSummary(stageMinutes: number | null): string {
  return stageMinutes
    ? t("processing:explain.summaryTimed", { stage: minutesPhrase(stageMinutes) })
    : t("processing:explain.summary");
}

/** What a screen reader hears about the stage: its name, the approximate percent and the time left. */
export function announceEstimate(stage: string, percent: number | null, minutes: number | null): string {
  return [
    stage,
    percent === null ? null : t("processing:announcePercent", { percent }),
    minutes === null ? null : t("processing:announceRemaining", { count: Math.max(1, minutes) }),
  ].filter(Boolean).join(", ");
}

/** Failure causes the backend reports as codes; `engine_failure` is the older spelling of `engine_failed`. */
const PROCESSING_FAILURE_KEYS = {
  could_not_join: "could_not_join",
  meeting_cancelled: "meeting_cancelled",
  engine_failure: "engine_failed",
  engine_failed: "engine_failed",
  engine_contract_mismatch: "engine_contract_mismatch",
  invalid_response: "invalid_response",
} as const;

/** The translated sentence for a processing failure code; an unknown or missing code gets the generic one. */
export function processingFailureText(cause?: string | null): string {
  const key = cause && cause in PROCESSING_FAILURE_KEYS
    ? PROCESSING_FAILURE_KEYS[cause as keyof typeof PROCESSING_FAILURE_KEYS]
    : "unknown";
  return t(`processing:failureCause.${key}`);
}
