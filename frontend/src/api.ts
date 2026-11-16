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
export const TOKEN_KEY = "sauri_token";

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

/** Ends the session on 401 and throws "Error <status>" for any other failure. */
function rejectUnlessOk(response: Response): void {
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event("sauri:unauthorized"));
  }
  if (!response.ok) {
    throw new Error(`Error ${response.status}`);
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  rejectUnlessOk(response);
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
  title: string;
}

export interface RecordingUploadResult {
  meeting_id: string;
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
          !("meeting_id" in result) || typeof result.meeting_id !== "string" || !result.meeting_id.trim() ||
          !("recording_id" in result) || typeof result.recording_id !== "string" || !result.recording_id.trim() ||
          !("state" in result) || typeof result.state !== "string" || !result.state.trim()
        ) throw new Error("Invalid upload response");
        resolve({ meeting_id: result.meeting_id, recording_id: result.recording_id, state: result.state });
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
    durationSeconds: meeting.duration_seconds ?? null,
    speakerCount: meeting.speaker_count ?? null,
    summaryTopic: meeting.summary_topic ?? null,
    thumbnailUrl: meeting.thumbnail_url ?? null,
    mediaKind: meeting.media_kind ?? null,
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
  schema_version?: number;
  key_points: Array<string | {
    text: string;
    sources: Array<{ passage_id: string; start_ms: number; end_ms: number }>;
  } | {
    title: string;
    items: Array<{ text: string; sub_items?: string[] }>;
    sources: Array<{ passage_id: string; start_ms: number; end_ms: number }>;
  }>;
  conclusion?: string | null;
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
  requested_at?: string | null;
  started_at?: string | null;
}

function mapSummaryRequest(request: SummaryRequestStatusResponse): SummaryRequestStatus {
  return {
    eventId: request.event_id,
    generation: request.generation,
    status: request.status,
    failureCause: request.failure_cause,
    requestedAt: request.requested_at,
    startedAt: request.started_at,
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
    schemaVersion: summary.schema_version === 2 ? 2 : 1,
    keyPoints: summary.key_points.map((point) => {
      if (typeof point === "string") return point;
      const sources = point.sources.map((source) => ({
        passageId: source.passage_id, startMs: source.start_ms, endMs: source.end_ms,
      }));
      if ("title" in point) {
        return {
          title: point.title,
          items: point.items.map((item) => ({ text: item.text, subItems: item.sub_items ?? [] })),
          sources,
        };
      }
      return { text: point.text, sources };
    }),
    conclusion: summary.conclusion ?? null,
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

export type SpeakerDisposition = "confirmed" | "named" | "corrected";

export interface SpeakerReviewItem {
  speakerId: string;
  currentLabel: string;
  attributionState: string;
  disposition: SpeakerDisposition | null;
  expectedVersion: number;
}

export interface SpeakerReview {
  reviewId: string;
  revisionId: string;
  status: "pending" | "complete";
  items: SpeakerReviewItem[];
  labelsBySpeakerId: Record<string, string>;
}

interface SpeakerReviewItemResponse {
  speaker_id: string;
  current_label: string;
  attribution_state: string;
  disposition: SpeakerDisposition | null;
  version: number;
}

interface SpeakerReviewResponse {
  review_id: string;
  revision_id: string | number;
  status: "pending" | "complete";
  items: SpeakerReviewItemResponse[];
  labels_by_speaker_id?: Record<string, string>;
}

export interface SpeakerDispositionRequest {
  disposition: SpeakerDisposition;
  label?: string;
  expectedVersion: number;
  /** One key per user action; resend the same key when retrying that action. */
  idempotencyKey: string;
}

export type SpeakerReviewFailure = "conflict" | "not_found";

/** Raised for the review responses the user must act on: a stale revision (409) or a missing meeting (404). */
export class SpeakerReviewRequestError extends Error {
  readonly reason: SpeakerReviewFailure;

  constructor(reason: SpeakerReviewFailure) {
    super(reason === "conflict" ? copy.speakerReview.conflict : copy.speakerReview.notFound);
    this.name = "SpeakerReviewRequestError";
    this.reason = reason;
  }
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

function speakerReviewUrl(meetingId: string): string {
  return `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/speaker-review`;
}

async function handleSpeakerReviewResponse(response: Response): Promise<SpeakerReview> {
  if (response.status === 404) throw new SpeakerReviewRequestError("not_found");
  if (response.status === 409) throw new SpeakerReviewRequestError("conflict");
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
      expectedVersion: item.version,
    })),
    labelsBySpeakerId: review.labels_by_speaker_id ?? {},
  };
}

export async function getSpeakerReview(meetingId: string): Promise<SpeakerReview> {
  const response = await fetch(speakerReviewUrl(meetingId), { method: "GET", headers: getAuthHeaders() });
  return handleSpeakerReviewResponse(response);
}

export async function submitSpeakerDisposition(
  meetingId: string,
  revisionId: string,
  speakerId: string,
  request: SpeakerDispositionRequest
): Promise<SpeakerReview> {
  const response = await fetch(
    `${speakerReviewUrl(meetingId)}/revisions/${encodeURIComponent(revisionId)}/speakers/${encodeURIComponent(speakerId)}`,
    {
      method: "PUT",
      headers: getAuthHeaders(),
      body: JSON.stringify({
        disposition: request.disposition,
        ...(request.label === undefined ? {} : { label: request.label }),
        expected_version: request.expectedVersion,
        idempotency_key: request.idempotencyKey,
      }),
    }
  );
  return handleSpeakerReviewResponse(response);
}

export async function renameMeeting(
  meetingId: string,
  title: string
): Promise<{ meetingId: string; title: string }> {
  const response = await fetch(`${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}`, {
    method: "PATCH",
    headers: getAuthHeaders(),
    body: JSON.stringify({ title }),
  });
  const renamed = await handleResponse<{ meeting_id: string; title: string }>(response);
  return { meetingId: renamed.meeting_id, title: renamed.title };
}

export async function deleteMeeting(meetingId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    // handleResponse clears the session on 401 and throws "Error <status>".
    await handleResponse<never>(response);
  }
}

/** A summary template owned by the signed-in user. Edits apply to future summaries only. */
export interface SummaryTemplate {
  id: string;
  name: string;
  instructions: string;
  categoryId: string | null;
  version: number;
  isDefault: boolean;
  /** Note shown while the starter template is unedited. */
  provenance: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface TemplateCategory {
  id: string;
  name: string;
  createdAt: string;
}

export interface TemplateInput {
  name: string;
  instructions: string;
  categoryId: string | null;
}

interface TemplateResponse {
  id: string;
  name: string;
  instructions: string;
  category_id: string | null;
  version: number;
  is_default: boolean;
  provenance?: string | null;
  created_at: string;
  updated_at: string;
}

interface TemplateCategoryResponse {
  id: string;
  name: string;
  created_at: string;
}

function mapTemplate(template: TemplateResponse): SummaryTemplate {
  return {
    id: template.id,
    name: template.name,
    instructions: template.instructions,
    categoryId: template.category_id,
    version: template.version,
    isDefault: template.is_default,
    provenance: template.provenance ?? null,
    createdAt: template.created_at,
    updatedAt: template.updated_at,
  };
}

function mapTemplateCategory(category: TemplateCategoryResponse): TemplateCategory {
  return { id: category.id, name: category.name, createdAt: category.created_at };
}

export async function listTemplates(): Promise<SummaryTemplate[]> {
  const response = await fetch(`${BASE_URL}/api/v1/templates`, { method: "GET", headers: getAuthHeaders() });
  return (await handleResponse<TemplateResponse[]>(response)).map(mapTemplate);
}

export async function getTemplate(templateId: string): Promise<SummaryTemplate> {
  const response = await fetch(
    `${BASE_URL}/api/v1/templates/${encodeURIComponent(templateId)}`,
    { method: "GET", headers: getAuthHeaders() },
  );
  return mapTemplate(await handleResponse<TemplateResponse>(response));
}

export async function createTemplate(input: TemplateInput): Promise<SummaryTemplate> {
  const response = await fetch(`${BASE_URL}/api/v1/templates`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ name: input.name, instructions: input.instructions, category_id: input.categoryId }),
  });
  return mapTemplate(await handleResponse<TemplateResponse>(response));
}

/** Sends only the fields present in `changes`; an absent field is left untouched by the API. */
export async function updateTemplate(
  templateId: string,
  changes: Partial<TemplateInput>,
): Promise<SummaryTemplate> {
  const body: Record<string, string | null> = {};
  if (changes.name !== undefined) body.name = changes.name;
  if (changes.instructions !== undefined) body.instructions = changes.instructions;
  if (changes.categoryId !== undefined) body.category_id = changes.categoryId;
  const response = await fetch(`${BASE_URL}/api/v1/templates/${encodeURIComponent(templateId)}`, {
    method: "PATCH",
    headers: getAuthHeaders(),
    body: JSON.stringify(body),
  });
  return mapTemplate(await handleResponse<TemplateResponse>(response));
}

export async function listTemplateCategories(): Promise<TemplateCategory[]> {
  const response = await fetch(`${BASE_URL}/api/v1/templates/categories`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  return (await handleResponse<TemplateCategoryResponse[]>(response)).map(mapTemplateCategory);
}

export async function createTemplateCategory(name: string): Promise<TemplateCategory> {
  const response = await fetch(`${BASE_URL}/api/v1/templates/categories`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ name }),
  });
  return mapTemplateCategory(await handleResponse<TemplateCategoryResponse>(response));
}

export async function setDefaultTemplate(templateId: string): Promise<void> {
  const response = await fetch(`${BASE_URL}/api/v1/templates/default`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify({ template_id: templateId }),
  });
  rejectUnlessOk(response);
}
