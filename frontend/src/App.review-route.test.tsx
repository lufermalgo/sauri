// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  });
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

it("holds a direct meeting review behind portal login, then fetches only that meeting's protected assets", async () => {
  window.history.replaceState({}, "", "/?meetingId=meeting-614");
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/auth/login")) return json({ access_token: "synthetic-token", token_type: "bearer", expires_in: 3600 });
    expect(init?.headers).toMatchObject({ Authorization: "Bearer synthetic-token" });
    if (path.endsWith("/processing")) return json({
      meeting_id: "meeting-614", ready: true, failed: false,
      execution: { generation: 1, transcript_id: "transcript-614", diarization_revision: 1 },
      stages: [{ key: "transcription", state: "completed" }, { key: "diarization", state: "completed" }],
    });
    if (path.endsWith("/transcript")) return json({ transcript_id: "transcript-614", meeting_id: "meeting-614", language: "en", provider: "synthetic", supports_turns: true,
      created_at: "2026-01-01T00:00:00Z", segments: [{ id: "segment-614", text: "Synthetic private turn", start_ms: 0, end_ms: 1000, sequence: 0 }] });
    if (path.endsWith("/playback")) return json({ meeting_id: "meeting-614", video_presence: "muxed", duration_seconds: 1,
      audio_source: { source_id: "audio", url: "https://example.invalid/audio", mime_type: "video/webm" },
      muxed_video_source: { source_id: "video", url: "https://example.invalid/video", mime_type: "video/webm" }, video_sources: [] });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "owner@example.test" } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
  await waitFor(() => expect(screen.getAllByText("Synthetic private turn").length).toBeGreaterThan(0));
  expect(fetchMock.mock.calls.map(([input]) => String(input)).filter(url => url.includes("/meetings/")))
    .toEqual(expect.arrayContaining([expect.stringContaining("/meeting-614/transcript"), expect.stringContaining("/meeting-614/playback")]));
  expect(fetchMock.mock.calls.every(([input]) => !String(input).includes("meeting-other"))).toBe(true);
});

it("does not reveal a direct target denied by the server and preserves the target after 401", async () => {
  window.history.replaceState({}, "", "/?meetingId=meeting-614");
  localStorage.setItem("sauri_token", "synthetic-expired-token");
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) => json({ detail: "Unauthorized" }, 401));
  vi.stubGlobal("fetch", fetchMock);
  render(<App />);
  await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy());
  expect(screen.queryByText("Synthetic private turn")).toBeNull();
  expect(localStorage.getItem("sauri_token")).toBeNull();
  expect(window.location.search).toBe("?meetingId=meeting-614");
  expect(fetchMock.mock.calls.every(([input]) => String(input).includes("/meetings/meeting-614/"))).toBe(true);
});
