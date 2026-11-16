import { useEffect, useState } from "react";
import {
  announceEstimate, estimateProgress, explainSummary, explainTranscription, expectedStageSeconds, formatElapsed, remainingText,
  roundMinutes, secondsSince, type ActiveStage,
} from "../processing-estimate";
import { ProgressBar } from "./ui";
import "../styles/processing.css";
import { useT } from "../i18n";

interface StageProgressProps {
  stage: ActiveStage;
  /** Names the stage for the progress bar and the spoken estimate. */
  label: string;
  /** Show the label as a visible headline (the stage card); the summary section has its own heading. */
  showHeadline?: boolean;
  queued?: boolean;
  /** Recording length; without it no estimate is shown. */
  audioSeconds: number | null;
  /** Upload time (meeting createdAt). */
  createdAt: string | null;
  /** When the page saw this stage begin; null when it was already running on open. */
  stageStartedAt: number | null;
}

// Screen readers hear the estimate at most this often; the visible figures tick every second.
const ANNOUNCE_EVERY_MS = 15_000;
const TICK_MS = 1000;

/** Wall clock that ticks every second while the page is visible. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
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
  }, []);
  return now;
}

/**
 * Plain-language explanation, progress bar, elapsed time and estimate of one running stage. It only
 * exists while the stage runs, so its clock stops with it.
 */
export function StageProgress({
  stage, label, showHeadline = false, queued = false, audioSeconds, createdAt, stageStartedAt,
}: StageProgressProps) {
  const { t } = useT();
  const now = useNow();
  const [mountedAt] = useState(() => Date.now());

  const sinceUpload = (at: number) => secondsSince(createdAt, at) ?? (at - mountedAt) / 1000;
  // A page opened mid-stage cannot know when speakers or the summary began: the time since the upload
  // also holds a transcription of any length, so only the time this page has watched counts as overtime.
  const stageStart = stageStartedAt ?? (stage === "transcription" ? null : mountedAt);
  const estimateAt = (at: number) => estimateProgress({
    stage, audioSeconds, elapsedSinceUploadSeconds: sinceUpload(at),
    stageElapsedSeconds: stageStart === null ? null : Math.max(0, (at - stageStart) / 1000),
  });
  const estimate = estimateAt(now);
  const audioMinutes = typeof audioSeconds === "number" && audioSeconds > 0 ? roundMinutes(audioSeconds) : null;
  const stageMinutes = audioMinutes === null ? null : roundMinutes(expectedStageSeconds(audioSeconds as number)[stage]);
  const explanation = estimate?.overtime ? t("processing:explain.overtime")
    : queued ? t("processing:explain.queued")
      : stage === "transcription" ? explainTranscription(audioMinutes, stageMinutes)
        : stage === "speakers" ? t("processing:explain.speakers") : explainSummary(stageMinutes);
  const remaining = estimate === null ? t("processing:noEstimate")
    : estimate.overtime || estimate.remainingSeconds === null ? t("processing:overtime")
      : estimate.remainingSeconds < 60 ? t("processing:remainingUnderMinute") : remainingText(roundMinutes(estimate.remainingSeconds));
  const showPercent = estimate !== null && !estimate.overtime;

  // The spoken estimate only changes every ANNOUNCE_EVERY_MS of wall clock.
  const announced = estimateAt(now - (now % ANNOUNCE_EVERY_MS));
  const announcement = announced === null ? "" : announced.overtime ? t("processing:overtime")
    : announceEstimate(label, announced.percent,
      announced.remainingSeconds === null ? null : roundMinutes(announced.remainingSeconds));

  return (
    <div className="processing-stage">
      {showHeadline ? (
        <div className="processing-current">
          <p role="status" className="processing-headline">{label}</p>
          <p className="processing-explain">{explanation}</p>
        </div>
      ) : <p className="processing-explain">{explanation}</p>}
      <div className="processing-meter">
        <ProgressBar label={label} value={estimate === null ? undefined : estimate.percent}
          valueText={showPercent ? t("processing:percent", { value: estimate.percent }) : t("processing:overtime")} />
        <div className="processing-figures">
          {showPercent && <span className="processing-percent">{t("processing:percent", { value: estimate.percent })}</span>}
          <span className="processing-elapsed">{t("processing:elapsed", { time: formatElapsed(sinceUpload(now)) })}</span>
          <span className={`processing-remaining${estimate?.overtime ? " processing-remaining--overtime" : ""}`}>
            {remaining}
          </span>
        </div>
      </div>
      <p className="processing-hint">{t("processing:leaveHint")}</p>
      <span className="processing-sr-only" aria-live="polite">{announcement}</span>
    </div>
  );
}
