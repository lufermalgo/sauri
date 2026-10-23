// @vitest-environment jsdom
/**
 * Frontend component tests: transcript view.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.5 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import type { Transcript, SpeechTurn } from "@sauri/shared-types";
import type { TimedPassage } from "../api";

import { TranscriptView } from "./TranscriptView";
import * as api from "../api";

vi.mock("../api", () => ({
  getTranscript: vi.fn(),
  getSpeakerReview: vi.fn(),
  playSpeakerExcerpt: vi.fn(),
  submitSpeakerDisposition: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function transcript(
  turns: SpeechTurn[]
): Transcript & { segments: TimedPassage[]; turns: SpeechTurn[] } {
  return {
    id: "t-1",
    meetingId: "r-1",
    language: "es-CO",
    provider: "local",
    supportsTurns: true,
    createdAt: new Date().toISOString(),
    segments: [],
    turns,
  };
}

// Turn text below is realistic Spanish speech content (the product
// transcribes Spanish-language meeting audio) — spanish-sample-data.
function turn(overrides: Partial<SpeechTurn> = {}): SpeechTurn {
  return {
    id: "turn-1",
    transcriptId: "t-1",
    text: "Hola, buenas tardes.", // spanish-sample-data
    startMs: 0,
    endMs: 1500,
    sequence: 1,
    ...overrides,
  };
}

describe("TranscriptView — renders the transcript view", () => {
  it("shows language, provider, and turns with their timestamps", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(
      transcript([
        turn({ id: "t1", text: "Hola", startMs: 0, endMs: 1000, sequence: 1 }), // spanish-sample-data
        turn({ id: "t2", text: "¿Cómo estás?", startMs: 1000, endMs: 2500, sequence: 2 }), // spanish-sample-data
      ])
    );

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    await waitFor(() => screen.getByText(/Transcript/));

    expect(screen.getByText(/es-CO/)).toBeDefined();
    expect(screen.getByText(/local/)).toBeDefined();
    expect(screen.getByText("Hola")).toBeDefined(); // spanish-sample-data
    expect(screen.getByText("¿Cómo estás?")).toBeDefined(); // spanish-sample-data
    expect(screen.getByText(/00:00.*00:01/)).toBeDefined();
  });

  it("shows the empty-state message when there are no segments", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([]));

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    await waitFor(() => screen.getByText("No transcript segments."));
  });

  it("the 'Back to list' button invokes onBack", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));
    const onBack = vi.fn();

    render(<TranscriptView meetingId="r-1" onBack={onBack} />);
    await waitFor(() => screen.getByText(/Transcript/));

    fireEvent.click(screen.getByRole("button", { name: /Back to list/i }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("unauthenticated flow: API error is shown as an alert", async () => {
    vi.spyOn(api, "getTranscript").mockRejectedValue(
      new Error("Not authenticated: token not found")
    );

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    const alert = await waitFor(() => screen.getByRole("alert"));
    expect(alert.textContent).toMatch(/Not authenticated/);
  });
});

// Synthetic fixtures and typed meeting-API boundary seam for speaker review.
interface SpeakerReview {
  reviewId: string;
  revisionId: string;
  status: "pending" | "complete";
  items: Array<{
    speakerId: string;
    currentLabel: string;
    attributionState: "recognized" | "uncertain";
    disposition: string | null;
    excerptRef: string;
    expectedVersion: number;
  }>;
}
interface DispositionRequest {
  disposition: "confirmed" | "named" | "corrected";
  label?: string;
  expectedVersion: number;
}
const reviewApi = api as unknown as {
  getSpeakerReview: (meetingId: string) => Promise<SpeakerReview>;
  playSpeakerExcerpt: (meetingId: string, revisionId: string, speakerId: string) => Promise<void>;
  submitSpeakerDisposition: (meetingId: string, revisionId: string, speakerId: string, request: DispositionRequest) => Promise<SpeakerReview>;
};
function review(overrides: Partial<SpeakerReview> = {}): SpeakerReview {
  return {
    reviewId: "review-1", revisionId: "revision-1", status: "pending",
    items: [
      { speakerId: "speaker-1", currentLabel: "Speaker 1", attributionState: "uncertain", disposition: null, excerptRef: "opaque-1", expectedVersion: 1 },
      { speakerId: "speaker-2", currentLabel: "Known Speaker", attributionState: "recognized", disposition: null, excerptRef: "opaque-2", expectedVersion: 1 },
    ],
    ...overrides,
  };
}

describe("TranscriptView — speaker review", () => {
  const loadReview = () => vi.spyOn(reviewApi, "getSpeakerReview");
  const playExcerpt = () => vi.spyOn(reviewApi, "playSpeakerExcerpt");
  const submit = () => vi.spyOn(reviewApi, "submitSpeakerDisposition");
  const loadTranscript = () => vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));

  it("renders pending and complete states and labels uncertain speakers as Speaker N", async () => {
    loadTranscript();
    loadReview().mockResolvedValue(review());
    const { unmount } = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText("Speaker 1")).toBeDefined();
    expect((await screen.findAllByRole("button", { name: /confirm/i })).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("button", { name: /name/i })).length).toBeGreaterThan(0);
    expect((await screen.findAllByRole("button", { name: /correct/i })).length).toBeGreaterThan(0);
    unmount();

    loadTranscript();
    loadReview().mockResolvedValue(review({ status: "complete" }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText(/complete/i)).toBeDefined();
  });

  it("requests playback of the chosen speaker excerpt", async () => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    const play = playExcerpt().mockResolvedValue();
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /play.*speaker 1|speaker 1.*play/i }));
    await waitFor(() => expect(play).toHaveBeenCalledWith("r-1", "revision-1", "speaker-1"));
  });

  it.each([
    ["Confirm", { disposition: "confirmed", expectedVersion: 1 }],
    ["Name", { disposition: "named", label: "Ana", expectedVersion: 1 }],
    ["Correct", { disposition: "corrected", label: "Ana", expectedVersion: 1 }],
  ] as const)("submits explicit %s for one item only", async (action, request) => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    const update = submit().mockResolvedValue(review({ items: [
      { ...review().items[0], currentLabel: action === "Confirm" ? "Speaker 1" : "Ana", disposition: request.disposition },
      review().items[1],
    ] }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Speaker 1");
    if (action !== "Confirm") {
      fireEvent.change(screen.getByRole("textbox", { name: /name for speaker 1/i }), {
        target: { value: "Ana" },
      });
    }
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${action} Speaker 1$`, "i") }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("r-1", "revision-1", "speaker-1", request));
    expect(screen.getByText("Known Speaker")).toBeDefined();
  });

  it("reloads pending state after remount and exposes failed requests without advancing", async () => {
    loadTranscript();
    const load = loadReview().mockResolvedValue(review());
    const view = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText("Speaker 1")).toBeDefined();
    view.unmount();
    load.mockResolvedValue(review()); loadTranscript();
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText("Speaker 1")).toBeDefined();
    expect(load).toHaveBeenCalledTimes(2);

    submit().mockRejectedValue(new Error("Request failed"));
    fireEvent.click(screen.getAllByRole("button", { name: /confirm/i })[0]);
    expect((await screen.findByRole("alert")).textContent).toContain("Request failed");
    expect(screen.getAllByRole("button", { name: /confirm/i })[0]).toBeDefined();
  });

  it("exposes review actions as keyboard-operable native buttons", async () => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const buttons = await screen.findAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4);
    for (const button of buttons) expect(button.tagName).toBe("BUTTON");
  });
});
