import type { RecordingCompletion } from "../recording-db";

export type ProcessingStatus = Extract<RecordingCompletion["status"],
  "processing" | "processing_assets_unavailable" | "processing_failed" | "processing_succeeded">;

/** A server response is evidence only when it belongs to the uploaded recording. */
export function resolveProcessingStatus(
  record: RecordingCompletion,
  meeting: unknown,
  transcript?: unknown,
  playback?: unknown,
): ProcessingStatus | undefined {
  if (!record.recordingId || !record.meetingId || !meeting || typeof meeting !== "object") return undefined;
  const status = meeting as Record<string, unknown>;
  if (status.meeting_id !== record.meetingId || status.recording_id !== record.recordingId) return undefined;
  if (["queued", "joining", "recording", "transcribing"].includes(String(status.process_state))) return "processing";
  if (status.process_state === "failed") return "processing_failed";
  if (status.process_state !== "completed") return undefined;
  const text = transcript as Record<string, unknown> | undefined;
  const video = playback as Record<string, unknown> | undefined;
  const transcriptReady = text?.meeting_id === record.meetingId && typeof text.transcript_id === "string" && !!text.transcript_id;
  const videoReady = video?.meeting_id === record.meetingId &&
    ((video.video_presence === "muxed" && !!video.muxed_video_source && typeof video.muxed_video_source === "object" &&
      typeof (video.muxed_video_source as Record<string, unknown>).url === "string" && !!(video.muxed_video_source as Record<string, unknown>).url) ||
      (video.video_presence === "separate" && Array.isArray(video.video_sources) && video.video_sources.some(source =>
        !!source && typeof source === "object" && typeof source.url === "string" && !!source.url)));
  return transcriptReady && videoReady ? "processing_succeeded" : "processing_assets_unavailable";
}
