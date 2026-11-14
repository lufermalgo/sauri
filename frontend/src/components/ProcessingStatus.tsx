import type { MeetingState } from "../api";
import { copy } from "../copy/es";

interface ProcessingStatusProps {
  meeting: MeetingState | null;
  hasTranscript: boolean;
  diarizationNotFound: boolean;
  error: boolean;
}

export function ProcessingStatus({ meeting, hasTranscript, diarizationNotFound, error }: ProcessingStatusProps) {
  const text = copy.processing;
  if (error) return <p role="alert">{text.loadFailed}</p>;
  if (!meeting) return <p role="status">{text.loading}</p>;
  if (meeting.processState === "failed") return (
    <p role="status">{text.failed}: {text.failureCause(meeting.failureCause)}</p>
  );
  const labels: Record<string, string> = {
    queued: text.queued,
    joining: text.joining,
    recording: text.recording,
    transcribing: text.transcribing,
    completed: text.completed,
  };
  const identifying = hasTranscript && diarizationNotFound &&
    ["transcribing", "completed"].includes(meeting.processState);
  return <p role="status">{identifying ? text.identifying : labels[meeting.processState] ?? text.unknown}</p>;
}
