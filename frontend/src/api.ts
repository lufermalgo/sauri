import type { Meeting, Transcript, SpeechTurn } from "@sauri/shared-types";

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
    const body = await response.text().catch(() => "");
    throw new Error(`Error ${response.status}: ${body}`);
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

export async function getTranscript(
  meetingId: string
): Promise<Transcript & { turns: SpeechTurn[] }> {
  const response = await fetch(
    `${BASE_URL}/api/v1/meetings/${encodeURIComponent(meetingId)}/transcript`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );
  return handleResponse<Transcript & { turns: SpeechTurn[] }>(response);
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
