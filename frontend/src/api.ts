import type {
  Meeting,
  MeetingListApiResponse,
  MeetingListItem,
  Transcript,
  SpeechTurn,
} from "@sauri/shared-types";

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
  speakerLabel?: string;
  sequence: number;
}

interface TranscriptSegmentResponse {
  id: string;
  text: string;
  start_ms: number | null;
  end_ms: number | null;
  speaker_label?: string;
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

export interface MeetingDiarization {
  diarization_state?: string | null;
  speakers: Array<{ id: string; label: string; sequence: number }>;
  processing_revision?: number | null;
  assignments: Array<{ turn_id: string; speaker_id: string; overlap_ms?: number | null }>;
  latest_attempt?: {
    processing_revision: number;
    diarization_state: string;
    failure_cause: string | null;
  } | null;
}

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
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event("sauri:unauthorized"));
  }
  if (!response.ok) {
    throw new Error(`Error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export async function login(
  email: string,
  password: string
): Promise<LoginResponse> {
  const response = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return handleResponse<LoginResponse>(response);
}

export interface RecordingUploadData {
  duration_seconds: number;
  meeting_id: string;
  idempotency_key: string;
  capture_origin: "web_upload";
  video_presence: "absent" | "muxed";
}

export interface RecordingUploadResult {
  recording_id: string;
  state: string;
}

export async function uploadRecording(
  audio: File,
  data: RecordingUploadData
): Promise<RecordingUploadResult> {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    throw new Error("Not authenticated: token not found");
  }

  const formData = new FormData();
  formData.append("audio", audio);
  formData.append("data", JSON.stringify(data));

  const response = await fetch(`${BASE_URL}/api/v1/ingestion/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  return handleResponse<RecordingUploadResult>(response);
}

export async function registerMeeting(meetLink: string): Promise<Meeting> {
  const response = await fetch(`${BASE_URL}/api/v1/meetings`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ meet_link: meetLink }),
  });
  return handleResponse<Meeting>(response);
}

export interface MeetingState {
  meetingId: string;
  processState: string;
}

interface MeetingStateResponse {
  meeting_id: string;
  process_state: string;
}

export async function getMeeting(meetingId: string): Promise<MeetingState> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}`,
    { method: "GET", headers: getAuthHeaders() }
  );
  const meeting = await handleResponse<MeetingStateResponse>(response);
  return { meetingId: meeting.meeting_id, processState: meeting.process_state };
}

export async function listMeetings(): Promise<MeetingListItem[]> {
  const response = await fetch(`${BASE_URL}/api/v1/meetings`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  const meetings = await handleResponse<MeetingListApiResponse[]>(response);
  return meetings.map((meeting) => ({
    id: meeting.meeting_id,
    meetLink: meeting.meet_link,
    origin: meeting.origin,
    processState: meeting.process_state,
    failureCause: meeting.failure_cause,
    createdAt: meeting.created_at,
    title: meeting.title,
  }));
}

export async function getPlaybackManifest(
  meetingId: string
): Promise<PlaybackManifest> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/playback`,
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
      ...(segment.speaker_label === undefined ? {} : { speakerLabel: segment.speaker_label }),
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

export async function getDiarization(meetingId: string): Promise<MeetingDiarization> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/diarization`,
    { method: "GET", headers: getAuthHeaders() }
  );
  return handleResponse<MeetingDiarization>(response);
}

export interface SpeakerReviewItem {
  speakerId: string;
  currentLabel: string;
  attributionState: "recognized" | "uncertain";
  disposition: "confirmed" | "named" | "corrected" | null;
  excerptRef: string | null;
  expectedVersion?: number;
}

export interface SpeakerReview {
  reviewId: string;
  revisionId: string;
  status: "pending" | "complete";
  labelsBySpeakerId?: Record<string, string>;
  items: SpeakerReviewItem[];
}

interface SpeakerReviewItemResponse {
  speaker_id: string;
  current_label: string;
  attribution_state: "recognized" | "uncertain";
  disposition: "confirmed" | "named" | "corrected" | null;
  excerpt_ref: string | null;
  version?: number;
  expected_version?: number;
}

interface SpeakerReviewResponse {
  review_id: string;
  revision_id: string | number;
  status: "pending" | "complete";
  labels_by_speaker_id?: Record<string, string>;
  items: SpeakerReviewItemResponse[];
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
  return adaptSpeakerReview(await handleResponse<SpeakerReviewResponse>(response));
}

function adaptSpeakerReview(review: SpeakerReviewResponse): SpeakerReview {
  return {
    reviewId: review.review_id,
    revisionId: String(review.revision_id),
    status: review.status,
    ...(review.labels_by_speaker_id === undefined ? {} : { labelsBySpeakerId: review.labels_by_speaker_id }),
    items: review.items.map((item) => {
      // T14 uses expected_version; older servers exposed version.
      const expectedVersion = item.expected_version ?? item.version;
      return {
        speakerId: item.speaker_id,
        currentLabel: item.current_label,
        attributionState: item.attribution_state,
        disposition: item.disposition,
        excerptRef: item.excerpt_ref,
        expectedVersion,
      };
    }),
  };
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
  return adaptSpeakerReview(await handleResponse<SpeakerReviewResponse>(response));
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
  if (response.status === 401) {
    await handleResponse<void>(response);
  }
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
