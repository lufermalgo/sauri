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
    `${BASE_URL}/api/v1/meetings/${meetingId}/transcript`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );
  return handleResponse<Transcript & { turns: SpeechTurn[] }>(response);
}
