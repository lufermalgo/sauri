import type { MeetingState } from "../api";
import { copy } from "../copy/es";
import {
  ACTIVE_STAGES, NO_SPEECH_CAUSE, detectProcessingStage, stageLabel, type ActiveStage, type DetectedStage,
  type SummarySignal,
} from "../processing-estimate";
import { useStageStart } from "../useStageStart";
import { StageProgress } from "./StageProgress";
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

export function ProcessingStatus({
  meeting, hasTranscript, diarizationNotFound, error, hasDiarization = false, summary = "none",
  audioSeconds = null, createdAt = null,
}: ProcessingStatusProps) {
  const text = copy.processing;
  const detected: DetectedStage | null = meeting ? detectProcessingStage({
    processState: meeting.processState, hasTranscript, diarizationNotFound, hasDiarization, summary,
  }) : null;
  const stageStartedAt = useStageStart(detected);

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
  // The summary stage keeps only the stepper here: its progress lives in the summary section.
  if (stage === "summary") return (
    <div className="processing">
      <Stepper stage={stage} />
    </div>
  );

  return (
    <div className="processing">
      <Stepper stage={stage} />
      <StageProgress stage={stage} label={stageLabel(stage, meeting.processState)} showHeadline
        queued={meeting.processState === "queued"} audioSeconds={audioSeconds} createdAt={createdAt}
        stageStartedAt={stageStartedAt} />
    </div>
  );
}
