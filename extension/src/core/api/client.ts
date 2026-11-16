// Shared API client (Side Panel + Detail View) — Req. 13.1, 13.3,
// 13.4, 13.5, 14.1, 14.4, 14.5
import type { NoteDTO, TranscriptDTO, DiarizationDTO } from "../types";
import { storeSessionCredentials } from "../session-token";
import { authorizedRequest, InvalidSessionError } from "./authorized-fetch";
import { signOut, withSessionLock } from "./session-refresh";
import { InsecureTransportError, validateTransport } from "./transport";

export const DEFAULT_BACKEND_URL = "http://localhost:8000";
const TIMEOUT_MS = 10_000;

export { InvalidSessionError, InsecureTransportError, validateTransport, signOut };

/** Missing resource (404) — distinct from a real failure, to derive ViewState "empty" (Req. 7.6, 8.8, 10.5) */
export class NotFoundError extends Error {
  constructor() {
    super("Resource not found");
    this.name = "NotFoundError";
  }
}

async function request<T>(backendUrl: string, path: string, init?: RequestInit): Promise<T> {
  return authorizedRequest(
    backendUrl,
    path,
    init ?? {},
    async (response) => {
      if (response.status === 404) {
        throw new NotFoundError();
      }
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      return (await response.json()) as T;
    },
    TIMEOUT_MS,
  );
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
  // 204 response with no body — doesn't reuse request<T>() because that
  // function always tries to parse the response as JSON.
  await authorizedRequest(
    backendUrl,
    `/api/v1/meetings/${meetingId}`,
    { method: "DELETE" },
    async (response) => {
      if (response.status === 404) {
        throw new NotFoundError();
      }
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
    },
    TIMEOUT_MS,
  );
}

/**
 * POST /api/v1/auth/login (Req. 13.2, 13.3). The extension asks for a refreshable session:
 * the access token goes to chrome.storage.session and the rotating refresh token to
 * chrome.storage.local, so the user stays signed in across reloads and restarts.
 */
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
      body: JSON.stringify({ email, password, client: "extension" }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error("Invalid credentials");
    }

    const body = (await response.json()) as { access_token: string; expires_in: number; refresh_token?: string };
    // Held back while another context refreshes, so a late refresh cannot overwrite the new sign-in.
    await withSessionLock(() => storeSessionCredentials(body.access_token, body.refresh_token));
    return { accessToken: body.access_token, expiresIn: body.expires_in };
  } finally {
    clearTimeout(timeoutId);
  }
}
