import type { Meeting, Transcript, SpeechTurn } from "@sauri/shared-types";

export interface PlaybackSource {
  source_id: string;
  url: string;
  mime_type: string | null;
  quality_label?: string | null;
  width?: number | null;
  height?: number | null;
  video_offset_ms?: number | null;
}

export type VideoPresence = "muxed" | "separate" | "absent" | "unknown";

export interface PlaybackManifest {
  meeting_id: string;
  duration_seconds: number;
  video_presence: VideoPresence;
  audio_source: PlaybackSource;
  muxed_video_source: PlaybackSource | null;
  video_sources: PlaybackSource[];
}

export interface TimedPassage {
  id: string;
  text: string;
  startMs: number | null;
  endMs: number | null;
  sequence: number;
}

interface TranscriptSegmentResponse {
  id: string;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  sequence: number;
}

interface TranscriptResponse {
  transcript_id: string;
  meeting_id: string;
  language: string;
  provider: string;
  supports_turns: boolean;
  created_at: string;
  segments: TranscriptSegmentResponse[];
}

export type MeetingTranscript = Transcript & {
  segments: TimedPassage[];
  turns: SpeechTurn[];
};

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_KEY = "sauri_token";

function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    throw new Error("Not authenticated: token not found");
  }
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function registerMeeting(meetLink: string): Promise<Meeting> {
  const response = await fetch(`${BASE_URL}/api/v1/meetings`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ meet_link: meetLink }),
  });
  return handleResponse<Meeting>(response);
}

export async function listMeetings(): Promise<Meeting[]> {
  const response = await fetch(`${BASE_URL}/api/v1/meetings`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  return handleResponse<Meeting[]>(response);
}

export async function getPlaybackManifest(
  meetingId: string
): Promise<PlaybackManifest> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${meetingId}/playback`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );
  return handleResponse<PlaybackManifest>(response);
}

export async function getTranscript(meetingId: string): Promise<MeetingTranscript> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/transcript`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );
  const transcript = await handleResponse<TranscriptResponse>(response);
  const segments = transcript.segments.map((segment) => {
    const hasValidTiming =
      segment.start_ms !== null &&
      segment.end_ms !== null &&
      Number.isFinite(segment.start_ms) &&
      Number.isFinite(segment.end_ms) &&
      segment.start_ms >= 0 &&
      segment.end_ms > segment.start_ms;

    return {
      id: segment.id,
      text: segment.text,
      sequence: segment.sequence,
      startMs: hasValidTiming ? segment.start_ms : null,
      endMs: hasValidTiming ? segment.end_ms : null,
    };
  });
  const turns: SpeechTurn[] = segments.flatMap((segment) => {
    if (segment.startMs === null || segment.endMs === null) return [];
    return [{
      id: segment.id,
      transcriptId: transcript.transcript_id,
      text: segment.text,
      startMs: segment.startMs,
      endMs: segment.endMs,
      sequence: segment.sequence,
    }];
  });

  return {
    id: transcript.transcript_id,
    meetingId: transcript.meeting_id,
    language: transcript.language,
    provider: transcript.provider,
    supportsTurns: transcript.supports_turns,
    createdAt: transcript.created_at,
    segments,
    turns,
  };
}

export interface SpeakerReviewItem {
  speakerId: string;
  currentLabel: string;
  attributionState: "recognized" | "uncertain";
  disposition: "confirmed" | "named" | "corrected" | null;
  excerptRef: string;
  expectedVersion: number;
}

export interface SpeakerReview {
  reviewId: string;
  revisionId: string;
  status: "pending" | "complete";
  items: SpeakerReviewItem[];
}

export type SpeakerDisposition = "confirmed" | "named" | "corrected";

export interface SpeakerDispositionRequest {
  disposition: SpeakerDisposition;
  label?: string;
  expectedVersion: number;
}

export async function getSpeakerReview(meetingId: string): Promise<SpeakerReview> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/speaker-review`,
    { method: "GET", headers: getAuthHeaders() }
  );
  return handleResponse<SpeakerReview>(response);
}

export async function submitSpeakerDisposition(
  meetingId: string,
  revisionId: string,
  speakerId: string,
  request: SpeakerDispositionRequest
): Promise<SpeakerReview> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/speaker-review/revisions/${encodeURIComponent(revisionId)}/speakers/${encodeURIComponent(speakerId)}`,
    {
      method: "PUT",
      headers: {
        ...getAuthHeaders(),
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({
        disposition: request.disposition,
        label: request.label,
        expected_version: request.expectedVersion,
      }),
    }
  );
  return handleResponse<SpeakerReview>(response);
}

export async function playSpeakerExcerpt(
  meetingId: string,
  revisionId: string,
  speakerId: string
): Promise<void> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/speaker-review/revisions/${encodeURIComponent(revisionId)}/speakers/${encodeURIComponent(speakerId)}/excerpt`,
    { method: "GET", headers: getAuthHeaders() }
  );
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Error ${response.status}: ${body}`);
  }
  const audioUrl = URL.createObjectURL(await response.blob());
  const audio = new Audio(audioUrl);
  const releaseUrl = () => URL.revokeObjectURL(audioUrl);
  audio.addEventListener("ended", releaseUrl, { once: true });
  audio.addEventListener("error", releaseUrl, { once: true });
  try {
    await audio.play();
  } catch (error) {
    releaseUrl();
    throw error;
  }
}
