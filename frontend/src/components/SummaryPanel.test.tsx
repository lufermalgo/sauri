// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SummaryPanel } from "./SummaryPanel";
import { TranscriptView } from "./TranscriptView";
import { copy } from "../copy/es";

const summary = {
  summary_id: "summary-1", meeting_id: "meeting-1", template_id: "template-1",
  template_name: "General", template_version: 1, topic: "Synthetic planning",
  key_points: [
    { text: "First synthetic point", sources: [{ passage_id: "P0001", start_ms: 65432, end_ms: 75000 }] },
    { text: "Second synthetic point", sources: [{ passage_id: "P0002", start_ms: 125000, end_ms: 135000 }] },
  ],
  review_state: "draft", generation: 1, created_at: "2026-11-14T12:00:00Z", updated_at: "2026-11-14T12:00:00Z",
};
const pending = { event_id: "event-1", generation: 1, status: "pending" };
const text = copy.summary;
let artifact: typeof summary | null;
let latest: { event_id: string; generation: number; status: string; failure_cause?: string } | null;
let fetchMock: Mock<[url: string, init?: RequestInit], Promise<Response>>;

function response(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

function callsEndingWith(path: string) {
  return fetchMock.mock.calls.filter(([url]) => String(url).endsWith(path));
}

beforeEach(() => {
  artifact = null;
  latest = null;
  vi.stubGlobal("localStorage", { getItem: () => "synthetic-token", removeItem: vi.fn() });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/summary")) return response(artifact, artifact ? 200 : 404);
    if (url.endsWith("/summary-requests/latest")) return response(latest, latest ? 200 : 404);
    if (url.endsWith("/summary-requests") && init?.method === "POST") {
      latest = { ...pending, generation: (latest?.generation ?? 0) + 1 };
      return response(latest, 202);
    }
    throw new Error("Unexpected request");
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SummaryPanel", () => {
  it("renders the draft, topic, points and timed source links that seek to exact milliseconds", async () => {
    artifact = summary;
    latest = { ...pending, status: "succeeded" };
    const seek = vi.fn();
    render(<SummaryPanel meetingId="meeting-1" onSeek={seek} />);
    expect(await screen.findByText(text.draft)).toBeVisible();
    expect(screen.getByText(summary.topic)).toBeVisible();
    for (const point of summary.key_points) expect(screen.getByText(point.text)).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: text.sourceAt("01:05") }));
    expect(seek).toHaveBeenLastCalledWith(65432);
    fireEvent.click(screen.getByRole("link", { name: text.sourceAt("02:05") }));
    expect(seek).toHaveBeenLastCalledWith(125000);
  });

  it("posts an empty default-template request and enters pending after acceptance", async () => {
    render(<SummaryPanel meetingId="meeting / 1" onSeek={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: text.generate }));
    expect(await screen.findByText(text.pending)).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/meeting%20%2F%201/summary-requests"), {
      method: "POST", headers: { Authorization: "Bearer synthetic-token", "Content-Type": "application/json" }, body: "{}",
    });
    expect(screen.queryByRole("button", { name: text.generate })).not.toBeInTheDocument();
  });

  it.each(["context_exceeded", "summary_invalid", "llm_unavailable", "unrecognized"]) (
    "explains failed cause %s and retries with another POST", async (cause) => {
      latest = { ...pending, status: "failed", failure_cause: cause };
      render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
      expect(await screen.findByRole("alert")).toHaveTextContent(text.failureCause(cause));
      fireEvent.click(screen.getByRole("button", { name: text.retry }));
      expect(await screen.findByText(text.pending)).toBeVisible();
      expect(callsEndingWith("/summary-requests")).toHaveLength(1);
    },
  );

  it("copies only topic and point text as plain text", async () => {
    artifact = summary;
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: text.copy }));
    expect(writeText).toHaveBeenCalledWith("Synthetic planning\n- First synthetic point\n- Second synthetic point");
    expect(await screen.findByText(text.copied)).toBeVisible();
  });

  it("handles unavailable clipboard without claiming a successful copy", async () => {
    artifact = summary;
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: text.copy }));
    expect(await screen.findByText(text.copyFailed)).toBeVisible();
    expect(screen.queryByText(text.copied)).not.toBeInTheDocument();
  });

  it("handles denied clipboard permissions without losing the draft", async () => {
    artifact = summary;
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("Permission denied")) } });
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: text.copy }));
    expect(await screen.findByText(text.copyFailed)).toBeVisible();
    expect(screen.getByText(summary.topic)).toBeVisible();
  });

  it("polls every five seconds through running to ready, then stops", async () => {
    latest = pending;
    vi.useFakeTimers();
    await act(async () => { render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />); });
    const count = callsEndingWith("/summary-requests/latest").length;
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count);
    latest = { ...pending, status: "running" };
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText(text.running)).toBeVisible();
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count + 1);
    artifact = summary;
    latest = { ...pending, status: "succeeded" };
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText(text.draft)).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count + 2);
  });

  it("polls an accepted POST after five seconds without submitting a duplicate", async () => {
    vi.useFakeTimers();
    await act(async () => { render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: text.generate })); });
    expect(screen.getByText(text.pending)).toBeVisible();
    expect(callsEndingWith("/summary-requests")).toHaveLength(1);
    const count = callsEndingWith("/summary-requests/latest").length;
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count);
    latest = { ...pending, status: "running" };
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText(text.running)).toBeVisible();
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count + 1);
    expect(callsEndingWith("/summary-requests")).toHaveLength(1);
  });

  it("pauses polling while the page is hidden, resumes on visibility, and cleans up on unmount", async () => {
    latest = pending;
    vi.useFakeTimers();
    const view = render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    await act(async () => {});
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(1);
    hidden.mockReturnValue(false);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(2);
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    fireEvent(document, new Event("visibilitychange"));
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(2);
  });

  it("does not show an old artifact as the result of a newer request", async () => {
    artifact = summary;
    latest = { ...pending, generation: 2, status: "running" };
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    expect(await screen.findByText(text.running)).toBeVisible();
    expect(screen.queryByText(summary.topic)).not.toBeInTheDocument();
  });

  it("shows a newer failure even when an older artifact exists", async () => {
    artifact = summary;
    latest = { ...pending, generation: 2, status: "failed", failure_cause: "summary_invalid" };
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.failureCause("summary_invalid"));
    expect(screen.getByRole("button", { name: text.retry })).toBeVisible();
    expect(screen.queryByText(summary.topic)).not.toBeInTheDocument();
  });

  it("does not claim success until the current generation artifact is available", async () => {
    artifact = summary;
    latest = { ...pending, generation: 2, status: "succeeded" };
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.resultUnavailable);
    expect(screen.queryByText(summary.topic)).not.toBeInTheDocument();
    artifact = { ...summary, generation: 2 };
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    expect(await screen.findByText(text.draft)).toBeVisible();
    expect(callsEndingWith("/summary-requests")).toHaveLength(0);
  });

  it("shows legacy points without inventing citation links", async () => {
    fetchMock.mockImplementation(async (url: string) => url.endsWith("/summary")
      ? response({ ...summary, key_points: ["Legacy point"] }) : response(null, 404));
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    expect(await screen.findByText("Legacy point")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps request failures retryable without exposing raw server errors", async () => {
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    await screen.findByRole("button", { name: text.generate });
    fetchMock.mockResolvedValueOnce(response({ detail: "private diagnostic" }, 500));
    fireEvent.click(screen.getByRole("button", { name: text.generate }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.requestFailed);
    expect(screen.queryByText(/private diagnostic/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: text.generate }));
    expect(await screen.findByText(text.pending)).toBeVisible();
  });

  it("does not treat a load failure as an empty summary or generate a new request on reload", async () => {
    fetchMock.mockRejectedValueOnce(new Error("private network diagnostic"));
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.loadFailed);
    expect(screen.queryByRole("button", { name: text.generate })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    expect(await screen.findByRole("button", { name: text.generate })).toBeVisible();
    expect(callsEndingWith("/summary-requests")).toHaveLength(0);
  });

  it("ignores late results from a previous meeting", async () => {
    let resolveOld!: (value: Response) => void;
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveOld = resolve; }));
    const view = render(<SummaryPanel meetingId="meeting-old" onSeek={vi.fn()} />);
    view.rerender(<SummaryPanel meetingId="meeting-new" onSeek={vi.fn()} />);
    await screen.findByRole("button", { name: text.generate });
    await act(async () => { resolveOld(response(summary)); });
    expect(screen.queryByText(summary.topic)).not.toBeInTheDocument();
  });
});

describe("meeting summary tab integration", () => {
  it("keeps the player mounted, seeks through its controller and polls only while the summary tab is visible", async () => {
    artifact = summary;
    latest = { ...pending, status: "running", generation: 2 };
    const summaryFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/transcript")) return response({
        transcript_id: "transcript-1", meeting_id: "meeting-1", language: "es", provider: "local",
        supports_turns: true, created_at: "2026-11-14T12:00:00Z",
        segments: [{ id: "turn-1", sequence: 1, text: "Synthetic turn", start_ms: 65000, end_ms: 75000 }],
      });
      if (url.endsWith("/diarization")) return response({ speakers: [], assignments: [] });
      if (url.endsWith("/playback")) return response({
        meeting_id: "meeting-1", duration_seconds: 180, video_presence: "absent",
        audio_source: { source_id: "audio-1", url: "http://localhost/synthetic.wav", mime_type: "audio/wav" },
        muxed_video_source: null, video_sources: [],
      });
      if (url.endsWith("/speaker-review")) return response(null, 404);
      return summaryFetch(url, init);
    });
    const view = render(<TranscriptView meetingId="meeting-1" onBack={vi.fn()} />);
    const tab = await screen.findByRole("tab", { name: text.tab });
    const audio = await screen.findByTestId("playback-audio") as HTMLAudioElement;
    Object.defineProperty(audio, "duration", { configurable: true, value: 180 });
    fireEvent.loadedMetadata(audio);
    expect(callsEndingWith("/summary")).toHaveLength(0);
    const transcriptTab = screen.getByRole("tab", { name: text.transcriptTab });
    transcriptTab.focus();
    fireEvent.keyDown(transcriptTab, { key: "ArrowRight" });
    expect(tab).toHaveFocus();
    expect(tab).toHaveAttribute("aria-selected", "true");
    await screen.findByText(text.running);
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("tab", { name: text.transcriptTab }));
    const count = callsEndingWith("/summary-requests/latest").length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count);
    latest = { ...pending, status: "succeeded" };
    await act(async () => { fireEvent.click(tab); });
    expect(screen.getByText(text.draft)).toBeVisible();
    expect(screen.getByTestId("playback-audio")).toBe(audio);
    fireEvent.click(screen.getByRole("link", { name: text.sourceAt("01:05") }));
    expect(audio.currentTime).toBe(65.432);
    view.unmount();
  });
});
