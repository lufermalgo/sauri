// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  Reflect.deleteProperty(URL, "createObjectURL");
  Reflect.deleteProperty(URL, "revokeObjectURL");
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
    expect(await screen.findByText(text.generating)).toBeVisible();
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
      expect(await screen.findByText(text.generating)).toBeVisible();
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

  it("downloads exactly the copied plain text as resumen-<id>.txt and revokes the object URL", async () => {
    artifact = summary;
    const expected = "Synthetic planning\n- First synthetic point\n- Second synthetic point";
    const blobs: Blob[] = [];
    const createObjectURL = vi.fn((blob: Blob) => { blobs.push(blob); return "blob:synthetic"; });
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const downloads: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push(`${this.download}|${this.href}`);
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: text.download }));
    expect(downloads).toEqual(["resumen-meeting-1.txt|blob:synthetic"]);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic");
    expect(document.querySelector("a[download]")).toBeNull();
    expect(blobs).toHaveLength(1);
    expect(blobs[0].type).toContain("text/plain");
    const content = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blobs[0]);
    });
    expect(content).toBe(expected);
    fireEvent.click(screen.getByRole("button", { name: text.copy }));
    await screen.findByText(text.copied);
    expect(writeText).toHaveBeenCalledWith(content);
  });

  it("shows the generating skeleton card with an accessible status while the summary is pending", async () => {
    latest = pending;
    const view = render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    const status = await screen.findByText(text.generating);
    expect(status).toHaveAttribute("role", "status");
    expect(screen.getByText(text.generatingBadge)).toBeVisible();
    expect(screen.getByText(text.generatingHelp)).toBeVisible();
    const skeletons = view.container.querySelectorAll(".ui-skeleton");
    expect(skeletons.length).toBeGreaterThan(6);
    for (const skeleton of skeletons) expect(skeleton).toHaveAttribute("aria-hidden", "true");
    expect(view.container.querySelectorAll(".summary-skeleton-point")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: text.generate })).not.toBeInTheDocument();
  });

  it("removes the skeleton once the summary succeeds", async () => {
    latest = pending;
    vi.useFakeTimers();
    const view = render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    await act(async () => {});
    expect(view.container.querySelector(".ui-skeleton")).not.toBeNull();
    artifact = summary;
    latest = { ...pending, status: "succeeded" };
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText(text.draft)).toBeVisible();
    expect(view.container.querySelector(".ui-skeleton")).toBeNull();
    expect(screen.queryByText(text.generating)).not.toBeInTheDocument();
  });

  it("offers Generate by default and when transcriptReady is true", async () => {
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} transcriptReady />);
    expect(await screen.findByRole("button", { name: text.generate })).toBeVisible();
    expect(screen.queryByText(text.waitingTitle)).not.toBeInTheDocument();
  });

  it("does not offer Generate while the transcript is not ready and shows the calm note with skeleton lines", async () => {
    const view = render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} transcriptReady={false} />);
    expect(await screen.findByText(text.waitingTitle)).toBeVisible();
    expect(screen.getByText(text.waitingTitle).parentElement).toHaveTextContent(`${text.waitingTitle} ${text.waitingBody}`);
    expect(screen.queryByRole("button", { name: text.generate })).not.toBeInTheDocument();
    expect(view.container.querySelectorAll(".ui-skeleton")).toHaveLength(5);
    expect(callsEndingWith("/summary-requests")).toHaveLength(0);
  });

  it("does not offer a retry that would generate while the transcript is not ready", async () => {
    latest = { ...pending, status: "failed", failure_cause: "llm_unavailable" };
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} transcriptReady={false} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.failureCause("llm_unavailable"));
    expect(screen.queryByRole("button", { name: text.retry })).not.toBeInTheDocument();
  });

  it("offers no download button without a summary", async () => {
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    await screen.findByRole("button", { name: text.generate });
    expect(screen.queryByRole("button", { name: text.download })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: text.copy })).not.toBeInTheDocument();
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
    expect(screen.getByText(text.generating)).toBeVisible();
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count + 1);
    artifact = summary;
    latest = { ...pending, status: "succeeded" };
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText(text.draft)).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count + 2);
  });

  it("reports its progress signal to the meeting view", async () => {
    vi.useFakeTimers();
    const onSignalChange = vi.fn();
    latest = pending;
    await act(async () => { render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} onSignalChange={onSignalChange} />); });
    expect(onSignalChange).toHaveBeenLastCalledWith("waiting");
    artifact = summary;
    latest = { ...pending, status: "succeeded" };
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(onSignalChange).toHaveBeenLastCalledWith("settled");
  });

  it("reports none when nothing was requested", async () => {
    const onSignalChange = vi.fn();
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} onSignalChange={onSignalChange} />);
    await screen.findByText(text.empty);
    expect(onSignalChange).toHaveBeenLastCalledWith("none");
  });

  it("looks again when an automatic request is expected and keeps checking until it appears", async () => {
    vi.useFakeTimers();
    const view = render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    await act(async () => {});
    const initial = callsEndingWith("/summary-requests/latest").length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    // Nothing requested and nothing expected: no polling.
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(initial);
    await act(async () => { view.rerender(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} expectAutoRequest />); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(initial + 1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(initial + 2);
    latest = pending;
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByText(text.generating)).toBeVisible();
    await act(async () => { view.rerender(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />); });
    // Turning the expectation off does not trigger an extra load.
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(initial + 3);
  });

  it("polls an accepted POST after five seconds without submitting a duplicate", async () => {
    vi.useFakeTimers();
    await act(async () => { render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: text.generate })); });
    expect(screen.getByText(text.generating)).toBeVisible();
    expect(callsEndingWith("/summary-requests")).toHaveLength(1);
    const count = callsEndingWith("/summary-requests/latest").length;
    await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
    expect(callsEndingWith("/summary-requests/latest")).toHaveLength(count);
    latest = { ...pending, status: "running" };
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByText(text.generating)).toBeVisible();
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
    expect(await screen.findByText(text.generating)).toBeVisible();
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
    expect(await screen.findByText(text.generating)).toBeVisible();
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

const structured = {
  ...summary, template_version: 2, schema_version: 2,
  topic: "Synthetic paragraph about the meeting.",
  key_points: [
    {
      title: "Synthetic block one",
      items: [
        { text: "Synthetic fact", sub_items: ["Synthetic phase one", "Synthetic phase two"] },
        { text: "Decision: synthetic decision", sub_items: [] },
      ],
      sources: [{ passage_id: "P0001", start_ms: 65432, end_ms: 75000 }],
    },
    {
      title: "Synthetic block two",
      items: [{ text: "Another fact", sub_items: [] }],
      sources: [{ passage_id: "P0002", start_ms: 125000, end_ms: 135000 }],
    },
  ],
  conclusion: "Synthetic conclusion paragraph.",
};
const structuredPlainText = [
  `${text.mainTopic}\nSynthetic paragraph about the meeting.`,
  `${text.detailedKeyPoints}\n1. Synthetic block one\n- Synthetic fact\n  - Synthetic phase one\n  - Synthetic phase two\n- Decision: synthetic decision\n\n2. Synthetic block two\n- Another fact`,
  `${text.conclusion}\nSynthetic conclusion paragraph.`,
].join("\n\n");

describe("structured (v2) summary", () => {
  it("renders the topic paragraph, numbered blocks with nested items and the conclusion", async () => {
    artifact = structured as unknown as typeof summary;
    const seek = vi.fn();
    render(<SummaryPanel meetingId="meeting-1" onSeek={seek} />);
    expect(await screen.findByRole("heading", { name: text.mainTopic })).toBeVisible();
    expect(screen.getByRole("heading", { name: text.detailedKeyPoints })).toBeVisible();
    expect(screen.getByRole("heading", { name: text.conclusion })).toBeVisible();
    expect(screen.getByText("Synthetic paragraph about the meeting.")).toBeVisible();
    expect(screen.getByText("Synthetic conclusion paragraph.")).toBeVisible();
    const blocks = screen.getAllByRole("heading", { level: 4 });
    expect(blocks.map((block) => block.textContent)).toEqual(["Synthetic block one", "Synthetic block two"]);
    expect(screen.getByText("Synthetic phase two")).toBeVisible();
    expect(screen.getByText(/Decision: synthetic decision/)).toBeVisible();
    fireEvent.click(screen.getByRole("link", { name: text.sourceAt("02:05") }));
    expect(seek).toHaveBeenLastCalledWith(125000);
  });

  it("copies and downloads the same structure without minutes or timestamps", async () => {
    artifact = structured as unknown as typeof summary;
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const blobs: Blob[] = [];
    Object.assign(URL, { createObjectURL: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:synthetic"; }), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: text.copy }));
    expect(writeText).toHaveBeenCalledWith(structuredPlainText);
    expect(structuredPlainText).not.toMatch(/\d{1,2}:\d{2}/);
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    const content = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blobs[0]);
    });
    expect(content).toBe(structuredPlainText);
  });

  it("still renders and exports a stored v1 summary exactly as before", async () => {
    artifact = summary;
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<SummaryPanel meetingId="meeting-1" onSeek={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: text.topic })).toBeVisible();
    expect(screen.getByRole("heading", { name: text.keyPoints })).toBeVisible();
    expect(screen.queryByRole("heading", { name: text.conclusion })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: text.copy }));
    expect(writeText).toHaveBeenCalledWith("Synthetic planning\n- First synthetic point\n- Second synthetic point");
  });
});

describe("meeting summary tab integration", () => {
  it("keeps the player mounted, seeks through its controller and keeps polling the pending summary behind the chat tab", async () => {
    artifact = summary;
    latest = { ...pending, status: "running", generation: 2 };
    const summaryFetch = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/meetings/meeting-1")) return response({ meeting_id: "meeting-1", process_state: "completed" });
      if (url.endsWith("/meetings")) return response([{ meeting_id: "meeting-1", title: "Synthetic meeting", created_at: "2026-11-14T12:00:00Z" }]);
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
    const view = render(<TranscriptView meetingId="meeting-1" />);
    const tab = await screen.findByRole("tab", { name: copy.meeting.summaryTab });
    const audio = await screen.findByTestId("playback-audio") as HTMLAudioElement;
    Object.defineProperty(audio, "duration", { configurable: true, value: 180 });
    fireEvent.loadedMetadata(audio);
    expect(callsEndingWith("/summary")).toHaveLength(1);
    const chatTab = screen.getByRole("tab", { name: copy.meeting.chatTab });
    chatTab.focus();
    fireEvent.keyDown(chatTab, { key: "ArrowLeft" });
    expect(tab).toHaveFocus();
    expect(tab).toHaveAttribute("aria-selected", "true");
    await screen.findByText(text.generating);
    fireEvent.click(screen.getByRole("tab", { name: copy.meeting.chatTab }));
    // The summary panel stays mounted behind the chat tab, so the status (and the header derived
    // from it) keeps refreshing while the summary is pending or running. The poll timer was
    // armed with real timers, hence the real wait.
    const count = callsEndingWith("/summary-requests/latest").length;
    latest = { ...pending, status: "succeeded" };
    await waitFor(() => {
      expect(callsEndingWith("/summary-requests/latest").length).toBeGreaterThan(count);
    }, { timeout: 8000 });
    await act(async () => { fireEvent.click(tab); });
    expect(screen.getByText(text.draft)).toBeVisible();
    expect(screen.getByTestId("playback-audio")).toBe(audio);
    fireEvent.click(screen.getByRole("link", { name: text.sourceAt("01:05") }));
    expect(audio.currentTime).toBe(65.432);
    view.unmount();
  }, 15000);
});
