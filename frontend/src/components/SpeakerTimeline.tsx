import type { CSSProperties } from "react";
import { useT } from "../i18n";

export interface TimelineTurn {
  id: string;
  startMs: number | null;
  endMs: number | null;
  speakerId?: string;
  speakerLabel: string;
  color: string;
}

interface SpeakerTimelineProps {
  turns: TimelineTurn[];
  durationMs: number;
  currentTimeMs: number;
  keyPointTimes?: number[];
  disabled?: boolean;
  onSeek: (timeMs: number) => void;
}

function timestamp(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function SpeakerTimeline({ turns, durationMs, currentTimeMs, keyPointTimes = [], disabled = false, onSeek }: SpeakerTimelineProps) {
  const { t } = useT();
  const duration = Number.isFinite(durationMs) ? Math.max(0, durationMs) : 0;
  const unavailable = disabled || duration === 0;
  const clamp = (time: number) => Math.max(0, Math.min(duration, time));
  const position = clamp(currentTimeMs);
  const percentage = (time: number) => duration > 0 ? clamp(time) / duration * 100 : 0;
  const timedTurns = turns.filter(turn => turn.startMs !== null && turn.endMs !== null &&
    Number.isFinite(turn.startMs) && Number.isFinite(turn.endMs) && turn.startMs >= 0 &&
    turn.endMs > turn.startMs && turn.startMs < duration);
  const speakers = [...new Map(turns.map(turn => [turn.speakerId ?? turn.speakerLabel, turn])).values()];
  const markers = [...new Set(keyPointTimes.filter(time => Number.isFinite(time) && time >= 0 && time <= duration))];

  return <div className="meeting-timeline">
    <div className="meeting-timeline-track">
      <div className="meeting-timeline-slider" role="slider" tabIndex={unavailable ? -1 : 0}
        aria-label={t("meeting:timeline")} aria-valuemin={0} aria-valuemax={duration} aria-valuenow={position}
        aria-valuetext={t("meeting:timelinePosition", { time: timestamp(position) })} aria-disabled={unavailable}
        onClick={event => {
          if (unavailable) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          if (bounds.width > 0) onSeek(clamp((event.clientX - bounds.left) / bounds.width * duration));
        }}
        onKeyDown={event => {
          if (unavailable) return;
          let next: number;
          switch (event.key) {
            case "ArrowLeft": next = position - 5000; break;
            case "ArrowRight": next = position + 5000; break;
            case "Home": next = 0; break;
            case "End": next = duration; break;
            default: return;
          }
          event.preventDefault();
          onSeek(clamp(next));
        }}>
        <span className="meeting-timeline-segments" aria-hidden="true">
          {timedTurns.map(turn => <span key={turn.id} data-testid="timeline-segment"
            className="meeting-timeline-segment" style={{
              left: `${percentage(turn.startMs!)}%`,
              width: `${percentage(turn.endMs!) - percentage(turn.startMs!)}%`,
              background: turn.color,
            }} />)}
        </span>
        <span aria-hidden="true" className="meeting-timeline-position"
          style={{ left: `clamp(1px, ${percentage(position)}%, calc(100% - 2px))` }} />
      </div>
      {markers.map(time => <button type="button" className="meeting-key-point" key={time}
        aria-label={t("meeting:keyPointAt", { time: timestamp(time) })} title={t("meeting:keyPointAt", { time: timestamp(time) })}
        disabled={unavailable} onClick={() => onSeek(time)}
        style={{ "--marker-position": `${percentage(time)}%` } as CSSProperties} />)}
    </div>
    <div className="meeting-timeline-legend">
      {speakers.map(speaker => <span key={speaker.speakerId ?? speaker.speakerLabel}>
        <span aria-hidden="true" className="meeting-legend-dot" style={{ background: speaker.color }} />
        {speaker.speakerLabel}
      </span>)}
      {markers.length > 0 && <span><span aria-hidden="true" className="meeting-legend-marker" />{t("meeting:keyPoints")}</span>}
    </div>
  </div>;
}
