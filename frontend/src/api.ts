import { copy } from "./copy/es";
import type {
  Meeting,
  MeetingListApiResponse,
  MeetingListItem,
  Transcript,
  SpeechTurn,
  MeetingSummary,
  SummaryRequestStatus,
  TranscriptPresentation,
  AttributedTurn,
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
  presentation?: TranscriptPresentation;
  turns?: Array<{
    sequence: number;
    speaker_id: string | null;
    speaker_label: string | null;
    start_ms: number;
    end_ms: number;
    text: string;
    word_count: number;
    has_ambiguous: boolean;
  }>;
}

export type MeetingTranscript = Transcript & {
  segments: TimedPassage[];
  presentation?: TranscriptPresentation;
  turns: Array<SpeechTurn & Partial<AttributedTurn>>;
};

export interface MeetingDiarization {
  speakers: Array<{ id: string; label: string; sequence: number }>;
  assignments: Array<{ turn_id: string; speaker_id: string }>;
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

export interface UploadProgress {
  loaded: number;
  total: number | null;
}

export async function uploadWithProgress(
  audio: File,
  data: RecordingUploadData,
  onProgress: (progress: UploadProgress) => void
): Promise<RecordingUploadResult> {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) throw new Error(copy.upload.errors.unauthenticated);

  const formData = new FormData();
  formData.append("audio", audio);
  formData.append("data", JSON.stringify(data));

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = (event) => onProgress({
      loaded: event.loaded,
      total: event.lengthComputable && event.total > 0 ? event.total : null,
    });
    xhr.onload = () => {
      if (xhr.status === 401) {
        localStorage.removeItem(TOKEN_KEY);
        window.dispatchEvent(new Event("sauri:unauthorized"));
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(copy.upload.errors.http(xhr.status)));
        return;
      }
      try {
        const result: unknown = JSON.parse(xhr.responseText);
        if (
          !result || typeof result !== "object" ||
          !("recording_id" in result) || typeof result.recording_id !== "string" || !result.recording_id.trim() ||
          !("state" in result) || typeof result.state !== "string" || !result.state.trim()
        ) throw new Error("Invalid upload response");
        resolve({ recording_id: result.recording_id, state: result.state });
      } catch {
        reject(new Error(copy.upload.errors.invalidResponse));
      }
    };
    xhr.onerror = () => reject(new Error(copy.upload.errors.network));
    xhr.ontimeout = () => reject(new Error(copy.upload.errors.timeout));
    xhr.onabort = () => reject(new Error(copy.upload.errors.aborted));
    xhr.open("POST", `${BASE_URL}/api/v1/ingestion/upload`);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.send(formData);
  });
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
  failureCause?: string | null;
}

interface MeetingStateResponse {
  meeting_id: string;
  process_state: string;
  failure_cause?: string | null;
}

export async function getMeeting(meetingId: string): Promise<MeetingState> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}`,
    { method: "GET", headers: getAuthHeaders() }
  );
  const meeting = await handleResponse<MeetingStateResponse>(response);
  return {
    meetingId: meeting.meeting_id,
    processState: meeting.process_state,
    failureCause: meeting.failure_cause,
  };
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

interface MeetingSummaryResponse {
  summary_id: string;
  meeting_id: string;
  template_id: string;
  template_name: string;
  template_version: number;
  topic: string;
  key_points: Array<string | {
    text: string;
    sources: Array<{ passage_id: string; start_ms: number; end_ms: number }>;
  }>;
  review_state: "draft";
  generation: number;
  created_at: string;
  updated_at: string;
}

interface SummaryRequestStatusResponse {
  event_id: string;
  generation: number;
  status: SummaryRequestStatus["status"];
  failure_cause?: string | null;
}

function mapSummaryRequest(request: SummaryRequestStatusResponse): SummaryRequestStatus {
  return {
    eventId: request.event_id,
    generation: request.generation,
    status: request.status,
    failureCause: request.failure_cause,
  };
}

export async function getMeetingSummary(meetingId: string): Promise<MeetingSummary | null> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/summary`,
    { method: "GET", headers: getAuthHeaders() },
  );
  if (response.status === 404) return null;
  const summary = await handleResponse<MeetingSummaryResponse>(response);
  return {
    summaryId: summary.summary_id,
    meetingId: summary.meeting_id,
    templateId: summary.template_id,
    templateName: summary.template_name,
    templateVersion: summary.template_version,
    topic: summary.topic,
    keyPoints: summary.key_points.map((point) => typeof point === "string" ? point : {
      text: point.text,
      sources: point.sources.map((source) => ({
        passageId: source.passage_id, startMs: source.start_ms, endMs: source.end_ms,
      })),
    }),
    reviewState: summary.review_state,
    generation: summary.generation,
    createdAt: summary.created_at,
    updatedAt: summary.updated_at,
  };
}

export async function getLatestSummaryRequest(meetingId: string): Promise<SummaryRequestStatus | null> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/summary-requests/latest`,
    { method: "GET", headers: getAuthHeaders() },
  );
  if (response.status === 404) return null;
  return mapSummaryRequest(await handleResponse<SummaryRequestStatusResponse>(response));
}

export async function requestMeetingSummary(meetingId: string): Promise<SummaryRequestStatus> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/summary-requests`,
    { method: "POST", headers: getAuthHeaders(), body: JSON.stringify({}) },
  );
  return mapSummaryRequest(await handleResponse<SummaryRequestStatusResponse>(response));
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
    presentation: transcript.presentation ?? "segments",
    turns: transcript.presentation === "words" ? (transcript.turns ?? []).map((turn) => ({
      id: `${transcript.transcript_id}:turn:${turn.sequence}`,
      transcriptId: transcript.transcript_id,
      sequence: turn.sequence,
      speakerId: turn.speaker_id,
      speakerLabel: turn.speaker_label,
      startMs: turn.start_ms,
      endMs: turn.end_ms,
      text: turn.text,
      wordCount: turn.word_count,
      hasAmbiguous: turn.has_ambiguous,
    })) : turns,
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
  excerptRef: string;
  expectedVersion: number;
}

export interface SpeakerReview {
  reviewId: string;
  revisionId: string;
  status: "pending" | "complete";
  items: SpeakerReviewItem[];
}

interface SpeakerReviewItemResponse {
  speaker_id: string;
  current_label: string;
  attribution_state: "recognized" | "uncertain";
  disposition: "confirmed" | "named" | "corrected" | null;
  excerpt_ref: string;
  version: number;
}

interface SpeakerReviewResponse {
  review_id: string;
  revision_id: string | number;
  status: "pending" | "complete";
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
  const review = await handleResponse<SpeakerReviewResponse>(response);
  return {
    reviewId: review.review_id,
    revisionId: String(review.revision_id),
    status: review.status,
    items: review.items.map((item) => ({
      speakerId: item.speaker_id,
      currentLabel: item.current_label,
      attributionState: item.attribution_state,
      disposition: item.disposition,
      excerptRef: item.excerpt_ref,
      expectedVersion: item.version,
    })),
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
