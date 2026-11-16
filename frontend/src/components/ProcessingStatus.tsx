import { useEffect, useState } from "react";
import type { MeetingState } from "../api";
import { copy } from "../copy/es";
import {
  ACTIVE_STAGES, NO_SPEECH_CAUSE, detectProcessingStage, estimateProgress, expectedStageSeconds, formatElapsed,
  roundMinutes, secondsSince, type ActiveStage, type DetectedStage, type SummarySignal,
} from "../processing-estimate";
import { ProgressBar } from "./ui";
import "../styles/processing.css";

interface ProcessingStatusProps {
  meeting: MeetingState | null;
  hasTranscript: boolean;
  diarizationNotFound: boolean;
  error: boolean;
  hasDiarization?: boolean;
  summary?: SummarySignal;
  /** Recording length; without it no estimate is shown. */
  audioSeconds?: number | null;
  /** Upload time (meeting createdAt). */
  createdAt?: string | null;
}

// Screen readers hear the estimate at most this often; the visible figures tick every second.
const ANNOUNCE_EVERY_MS = 15_000;
const TICK_MS = 1000;

/** Wall clock that ticks every second while `active` and the page is visible. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      clearInterval(timer);
      timer = undefined;
      if (document.hidden) return;
      setNow(Date.now());
      timer = setInterval(() => setNow(Date.now()), TICK_MS);
    };
    start();
    document.addEventListener("visibilitychange", start);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", start);
    };
  }, [active]);
  return now;
}

const STEP_KEYS = ["upload", ...ACTIVE_STAGES] as const;
type StepKey = typeof STEP_KEYS[number];
type StepState = "done" | "current" | "pending";

function stepState(step: StepKey, stage: ActiveStage | "done"): StepState {
  if (stage === "done") return "done";
  const index = STEP_KEYS.indexOf(step);
  const current = STEP_KEYS.indexOf(stage);
  return index < current ? "done" : index === current ? "current" : "pending";
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3.5 8.5l3 3 6-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Stepper({ stage }: { stage: ActiveStage | "done" }) {
  const text = copy.processing;
  return (
    <ol className="processing-steps" aria-label={text.stepsLabel}>
      {STEP_KEYS.map((step, index) => {
        const state = stepState(step, stage);
        return (
          <li key={step} className={`processing-step processing-step--${state}`}
            aria-current={state === "current" ? "step" : undefined}>
            <span className="processing-step-marker" aria-hidden="true">
              {state === "done" ? <CheckIcon /> : index + 1}
            </span>
            <span className="processing-step-label">{text.steps[step]}</span>
            <span className="processing-sr-only">{`, ${text.stepState[state]}`}</span>
          </li>
        );
      })}
    </ol>
  );
}

function headlineFor(stage: ActiveStage, processState: string): string {
  const text = copy.processing;
  if (stage === "transcription") return processState === "queued" ? text.queued : text.transcribing;
  return stage === "speakers" ? text.identifying : text.summarizing;
}

export function ProcessingStatus({
  meeting, hasTranscript, diarizationNotFound, error, hasDiarization = false, summary = "none",
  audioSeconds = null, createdAt = null,
}: ProcessingStatusProps) {
  const text = copy.processing;
  const detected: DetectedStage | null = meeting ? detectProcessingStage({
    processState: meeting.processState, hasTranscript, diarizationNotFound, hasDiarization, summary,
  }) : null;
  const active = !error && (detected === "transcription" || detected === "speakers" || detected === "summary");
  const now = useNow(active);

  // When the page itself sees a stage begin, time it from then; a stage already running on open has no start.
  const [mountedAt] = useState(() => Date.now());
  const [track, setTrack] = useState<{ stage: DetectedStage | null; since: number | null }>({ stage: detected, since: null });
  if (track.stage !== detected) {
    // Leaving the loading state is not a real stage start: the page simply learned the state.
    setTrack({ stage: detected, since: track.stage === null ? null : Date.now() });
  }

  if (error) return <p role="alert">{text.loadFailed}</p>;
  if (!meeting || detected === null) return <p role="status">{text.loading}</p>;
  if (detected === "failed" && meeting.failureCause === NO_SPEECH_CAUSE) return (
    <div role="status" className="processing-current">
      <p className="processing-headline">{text.noSpeechTitle}</p>
      <p className="processing-explain">{text.noSpeechBody}</p>
    </div>
  );
  if (detected === "failed") return (
    <p role="status">{text.failed}: {text.failureCause(meeting.failureCause)}</p>
  );
  if (detected === "live") {
    const label = meeting.processState === "joining" ? text.joining : text.recording;
    return <>
      <ProgressBar label={label} />
      <p role="status">{label}</p>
    </>;
  }
  if (detected === "unknown") return <p role="status">{text.unknown}</p>;
  if (detected === "done") return (
    <div className="processing processing--done">
      <Stepper stage="done" />
      <div className="processing-current">
        <p role="status" className="processing-headline">{text.completed}</p>
        <p className="processing-explain">{text.doneBody}</p>
      </div>
    </div>
  );

  const stage = detected;
  const headline = headlineFor(stage, meeting.processState);
  const sinceUpload = (at: number) => secondsSince(createdAt, at) ?? (at - mountedAt) / 1000;
  const estimateAt = (at: number) => estimateProgress({
    stage, audioSeconds, elapsedSinceUploadSeconds: sinceUpload(at),
    stageElapsedSeconds: track.since === null ? null : Math.max(0, (at - track.since) / 1000),
  });
  const estimate = estimateAt(now);
  const audioMinutes = typeof audioSeconds === "number" && audioSeconds > 0 ? roundMinutes(audioSeconds) : null;
  const stageMinutes = audioMinutes === null ? null : roundMinutes(expectedStageSeconds(audioSeconds as number)[stage]);
  const explanation = estimate?.overtime ? text.explain.overtime
    : meeting.processState === "queued" ? text.explain.queued
      : stage === "transcription" ? text.explain.transcription(audioMinutes, stageMinutes)
        : stage === "speakers" ? text.explain.speakers : text.explain.summary(stageMinutes);
  const remaining = estimate === null ? text.noEstimate
    : estimate.overtime || estimate.remainingSeconds === null ? text.overtime
      : estimate.remainingSeconds < 60 ? text.remainingUnderMinute : text.remaining(roundMinutes(estimate.remainingSeconds));
  const showPercent = estimate !== null && !estimate.overtime;

  // The spoken estimate only changes every ANNOUNCE_EVERY_MS of wall clock.
  const announced = estimateAt(now - (now % ANNOUNCE_EVERY_MS));
  const announcement = announced === null ? "" : announced.overtime ? text.overtime
    : text.announce(headline, announced.percent,
      announced.remainingSeconds === null ? null : roundMinutes(announced.remainingSeconds));

  return (
    <div className="processing">
      <Stepper stage={stage} />
      <div className="processing-current">
        <p role="status" className="processing-headline">{headline}</p>
        <p className="processing-explain">{explanation}</p>
      </div>
      <div className="processing-meter">
        <ProgressBar label={headline} value={estimate === null ? undefined : estimate.percent}
          valueText={showPercent ? text.percent(estimate.percent) : text.overtime} />
        <div className="processing-figures">
          {showPercent && <span className="processing-percent">{text.percent(estimate.percent)}</span>}
          <span className="processing-elapsed">{text.elapsed(formatElapsed(sinceUpload(now)))}</span>
          <span className={`processing-remaining${estimate?.overtime ? " processing-remaining--overtime" : ""}`}>
            {remaining}
          </span>
        </div>
      </div>
      <p className="processing-hint">{text.leaveHint}</p>
      <span className="processing-sr-only" aria-live="polite">{announcement}</span>
    </div>
  );
}
