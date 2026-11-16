// Shared API client (Side Panel + Detail View) — Req. 13.1, 13.3,
// 13.4, 13.5, 14.1, 14.4, 14.5
import type { NoteDTO, TranscriptDTO, DiarizationDTO } from "../types";
import { clearSessionToken, readSessionToken, storeSessionToken } from "../session-token";

export const DEFAULT_BACKEND_URL = "http://localhost:8000";
const TIMEOUT_MS = 10_000;

export class InvalidSessionError extends Error {
  constructor() {
    super("Invalid or expired session");
    this.name = "InvalidSessionError";
  }
}

export class InsecureTransportError extends Error {
  constructor(url: string) {
    super(`The backend must be used over HTTPS (or http://localhost in development): ${url}`);
    this.name = "InsecureTransportError";
  }
}

/** Missing resource (404) — distinct from a real failure, to derive ViewState "empty" (Req. 7.6, 8.8, 10.5) */
export class NotFoundError extends Error {
  constructor() {
    super("Resource not found");
    this.name = "NotFoundError";
  }
}

/** Requires https:// except on http://localhost or 127.0.0.1 (development) — Req. 13.5 */
export function validateTransport(backendUrl: string): void {
  const url = new URL(backendUrl);
  const isLocalhost = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  if (url.protocol === "https:") return;
  if (url.protocol === "http:" && isLocalhost) return;
  throw new InsecureTransportError(backendUrl);
}

/** Stores the user session in chrome.storage.session, never in synced storage (Req. 13.3) */
export const storeSession = storeSessionToken;

async function request<T>(backendUrl: string, path: string, init?: RequestInit): Promise<T> {
  validateTransport(backendUrl);

  const session = await readSessionToken();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (session) {
    headers["Authorization"] = `Bearer ${session}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${backendUrl}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });

    if (response.status === 401) {
      await clearSessionToken();
      throw new InvalidSessionError();
    }

    if (response.status === 404) {
      throw new NotFoundError();
    }

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

/** GET /api/v1/meetings/ — Note history (Req. 4.1) */
export async function listMeetings(backendUrl: string = DEFAULT_BACKEND_URL): Promise<NoteDTO[]> {
  const raw = await request<
    Array<{
      meeting_id: string;
      title: string | null;
      process_state: string;
      created_at: string | null;
    }>
  >(backendUrl, "/api/v1/meetings/");

  return raw.map((r) => ({
    meetingId: r.meeting_id,
    title: r.title ?? null,
    processState: r.process_state,
    createdAt: r.created_at,
  }));
}

/** GET /api/v1/meetings/{id} — processing state (Detail View → polling while transcribing) */
export async function getMeeting(
  meetingId: string,
  backendUrl: string = DEFAULT_BACKEND_URL
): Promise<{ meetingId: string; processState: string }> {
  const raw = await request<{ meeting_id: string; process_state: string }>(
    backendUrl,
    `/api/v1/meetings/${meetingId}`
  );
  return { meetingId: raw.meeting_id, processState: raw.process_state };
}

/** GET /api/v1/meetings/{id}/transcript (Req. 6.3) */
export async function getTranscript(
  meetingId: string,
  backendUrl: string = DEFAULT_BACKEND_URL
): Promise<TranscriptDTO> {
  const raw = await request<{
    transcript_id: string;
    meeting_id: string;
    segments: Array<{ id: string; text: string; start_ms: number; end_ms: number; sequence: number }>;
  }>(backendUrl, `/api/v1/meetings/${meetingId}/transcript`);

  return {
    transcriptId: raw.transcript_id,
    meetingId: raw.meeting_id,
    segments: raw.segments.map((s) => ({
      id: s.id,
      text: s.text,
      startMs: s.start_ms,
      endMs: s.end_ms,
      sequence: s.sequence,
    })),
  };
}

/** GET /api/v1/meetings/{id}/diarization (Req. 6.3) */
export async function getDiarization(
  meetingId: string,
  backendUrl: string = DEFAULT_BACKEND_URL
): Promise<DiarizationDTO> {
  const raw = await request<{
    diarization_id: string;
    meeting_id: string;
    diarization_state: string;
    speaker_count: number;
    speakers: Array<{ id: string; label: string; sequence: number }>;
    assignments: Array<{ turn_id: string; speaker_id: string }>;
  }>(backendUrl, `/api/v1/meetings/${meetingId}/diarization`);

  return {
    diarizationId: raw.diarization_id,
    meetingId: raw.meeting_id,
    diarizationState: raw.diarization_state,
    speakerCount: raw.speaker_count,
    speakers: raw.speakers,
    assignments: raw.assignments.map((a) => ({
      turnId: a.turn_id,
      speakerId: a.speaker_id,
    })),
  };
}

/** PATCH /api/v1/meetings/{id} — renames a note (My Notes → rename) */
export async function renameMeeting(
  meetingId: string,
  newTitle: string,
  backendUrl: string = DEFAULT_BACKEND_URL
): Promise<void> {
  await request<{ meeting_id: string; title: string }>(
    backendUrl,
    `/api/v1/meetings/${meetingId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle }),
    }
  );
}

/** DELETE /api/v1/meetings/{id} — deletes a note (My Notes → delete) */
export async function deleteMeeting(
  meetingId: string,
  backendUrl: string = DEFAULT_BACKEND_URL
): Promise<void> {
  validateTransport(backendUrl);

  const session = await readSessionToken();
  const headers: Record<string, string> = {};
  if (session) {
    headers["Authorization"] = `Bearer ${session}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    // 204 response with no body — doesn't reuse request<T>() because that
    // function always tries to parse the response as JSON.
    const response = await fetch(`${backendUrl}/api/v1/meetings/${meetingId}`, {
      method: "DELETE",
      headers,
      signal: controller.signal,
    });

    if (response.status === 401) {
      await clearSessionToken();
      throw new InvalidSessionError();
    }
    if (response.status === 404) {
      throw new NotFoundError();
    }
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
  } finally {
    clearTimeout(timeoutId);
  }
}

/** POST /api/v1/auth/login (Req. 13.2, 13.3) */
export async function login(
  email: string,
  password: string,
  backendUrl: string = DEFAULT_BACKEND_URL
): Promise<{ accessToken: string; expiresIn: number }> {
  validateTransport(backendUrl);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error("Invalid credentials");
    }

    const body = (await response.json()) as { access_token: string; expires_in: number };
    await storeSession(body.access_token);
    return { accessToken: body.access_token, expiresIn: body.expires_in };
  } finally {
    clearTimeout(timeoutId);
  }
}
