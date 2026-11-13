// @vitest-environment jsdom
/**
 * Frontend component tests: transcript view.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.5 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, waitFor, fireEvent } from "@testing-library/react";
import type { Transcript, SpeechTurn } from "@sauri/shared-types";
import type { TimedPassage } from "../api";

import { TranscriptView } from "./TranscriptView";
import * as api from "../api";
import { PlaybackController } from "./PlaybackController";

vi.mock("../api", () => ({
  getTranscript: vi.fn(),
  getPlaybackManifest: vi.fn(),
  getDiarization: vi.fn(),
  getSpeakerReview: vi.fn(),
  submitSpeakerDisposition: vi.fn(),
  getSummary: vi.fn().mockResolvedValue(null),
  getLatestSummaryRequest: vi.fn().mockResolvedValue(null),
  listTemplates: vi.fn().mockResolvedValue([]),
  getSummaryRequest: vi.fn(),
  requestSummary: vi.fn(),
}));

beforeEach(() => {
  vi.spyOn(api, "getSummary").mockResolvedValue(null);
  vi.spyOn(api, "getLatestSummaryRequest").mockResolvedValue(null);
  vi.spyOn(api, "listTemplates").mockResolvedValue([]);
  vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(
    null as unknown as Awaited<ReturnType<typeof api.getPlaybackManifest>>,
  );
  vi.spyOn(api, "getDiarization").mockResolvedValue({ processing_revision: 1, speakers: [], assignments: [] });
});

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

describe("T15 — validated generation attribution", () => {
  // Fixtures model the approved T14/T16 contract without changing production types.
  function sources() {
    const data = transcript([
      turn({ id: "source-1", text: "Synthetic opening", startMs: 0, endMs: 400, sequence: 1 }),
      turn({ id: "source-2", text: "continues here", startMs: 600, endMs: 1000, sequence: 2 }),
    ]);
    data.segments = data.turns.map(({ id, text, startMs, endMs, sequence }) => ({ id, text, startMs, endMs, sequence }));
    return data;
  }
  function generation(overlap: number | null = 400, state = "completed") {
    return {
      processing_revision: 2,
      speakers: [{ id: "speaker-2", label: "Speaker 1", sequence: 1 }],
      assignments: [
        { turn_id: "source-1", speaker_id: "speaker-2", overlap_ms: overlap },
        { turn_id: "source-2", speaker_id: "speaker-2", overlap_ms: overlap },
      ],
      latest_attempt: { processing_revision: state === "completed" ? 2 : 3, diarization_state: state, failure_cause: state === "not_reconstructible" ? "audio_unavailable" : null },
    };
  }
  function completedReview(revisionId = "2") {
    return {
      reviewId: "review-2", revisionId, status: "complete" as const,
      labelsBySpeakerId: { "speaker-2": "Synthetic chosen name" }, items: [],
    };
  }
  beforeEach(() => {
    vi.mocked(api.getTranscript).mockResolvedValue(sources());
    vi.mocked(api.getDiarization).mockResolvedValue(generation());
    vi.mocked(api.getSpeakerReview).mockResolvedValue(completedReview());
  });
  function labels() {
    return screen.getAllByTestId("transcript-speaker-label").map((element) => element.textContent);
  }

  it("uses the complete label map after reload, groups positive assignments and preserves source data", async () => {
    const source = sources();
    const before = structuredClone(source);
    vi.mocked(api.getTranscript).mockResolvedValue(source);
    const view = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Synthetic opening continues here");
    await waitFor(() => expect(labels()).toEqual(["Synthetic chosen name"]));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(source).toEqual(before);
    view.unmount();
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await waitFor(() => expect(labels()).toEqual(["Synthetic chosen name"]));
    expect(source).toEqual(before);
  });

  it("never uses pending review.items as the transcript label source", async () => {
    const review = {
      ...completedReview(),
      items: [{ speakerId: "speaker-2", currentLabel: "Synthetic stale item", attributionState: "attributed" as const, disposition: null, excerptRef: "synthetic", expectedVersion: 1 }],
    };
    vi.mocked(api.getSpeakerReview).mockResolvedValue(review);
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await waitFor(() => expect(labels()).toEqual(["Synthetic chosen name"]));
  });

  it("does not apply a historical review even when the speaker key happens to match", async () => {
    const historical = {
      ...completedReview("1"),
      items: [{ speakerId: "speaker-2", currentLabel: "Synthetic historical identity", attributionState: "attributed" as const, disposition: "named" as const, excerptRef: "synthetic", expectedVersion: 1 }],
    };
    vi.mocked(api.getSpeakerReview).mockResolvedValue(historical);
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Synthetic opening continues here");
    expect(labels()).toEqual(["Speaker 1"]);
  });

  it.each([null, 0, -1])("keeps fragments separate and uncertain for overlap %s", async (overlap) => {
    vi.mocked(api.getDiarization).mockResolvedValue(generation(overlap));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Synthetic opening");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(labels()).toEqual(["Speaker N", "Speaker N"]);
    expect(screen.getByText("continues here")).toBeVisible();
  });

  it("does not group unknown speaker IDs even with positive-looking assignments", async () => {
    const unknown = { ...generation(), speakers: [] };
    vi.mocked(api.getDiarization).mockResolvedValue(unknown);
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Synthetic opening");
    expect(labels()).toEqual(["Speaker N", "Speaker N"]);
  });

  it("shows the not_reconstructible status without hiding or grouping source fragments", async () => {
    vi.mocked(api.getDiarization).mockResolvedValue(generation(400, "not_reconstructible"));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    // Match the terminal concept, not incidental UI wording or translation.
    await waitFor(() => expect(screen.getAllByRole("status").some((element) => /not.reconstructible|no.*reconstru/i.test(element.textContent ?? ""))).toBe(true));
    expect(screen.getByText("Synthetic opening")).toBeVisible();
    expect(screen.getByText("continues here")).toBeVisible();
    expect(labels()).toEqual(["Speaker N", "Speaker N"]);
  });

  it.each(["pending", "failed"])("keeps the completed generation and source visible during a newer %s attempt", async (state) => {
    vi.mocked(api.getDiarization).mockResolvedValue(generation(400, state));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Synthetic opening continues here");
    await waitFor(() => expect(labels()).toEqual(["Synthetic chosen name"]));
  });

  it("keeps source fragments visible while diarization is loading and after a transport failure", async () => {
    let reject!: (reason: Error) => void;
    vi.mocked(api.getDiarization).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText("Synthetic opening")).toBeVisible();
    expect(labels()).toEqual(["Speaker N", "Speaker N"]);
    reject(new Error("Synthetic transport failure"));
    await waitFor(() => expect(screen.getByText("continues here")).toBeVisible());
    expect(labels()).toEqual(["Speaker N", "Speaker N"]);
  });

  it.each(["named", "corrected"] as const)("retains a %s label after the speaker leaves pending items", async (disposition) => {
    const pending = {
      ...completedReview(), status: "pending" as const,
      labelsBySpeakerId: { "speaker-2": "Speaker 1" },
      items: [{ speakerId: "speaker-2", currentLabel: "Speaker 1", attributionState: "uncertain" as const, disposition: null, excerptRef: "synthetic", expectedVersion: 1 }],
    };
    vi.mocked(api.getSpeakerReview).mockResolvedValue(pending);
    vi.mocked(api.submitSpeakerDisposition).mockResolvedValue(completedReview());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const input = await screen.findByRole("textbox", { name: "Name for Speaker 1" });
    fireEvent.change(input, { target: { value: "Synthetic chosen name" } });
    fireEvent.click(screen.getByRole("button", { name: `${disposition === "named" ? "Name" : "Correct"} Speaker 1` }));
    await waitFor(() => expect(api.submitSpeakerDisposition).toHaveBeenCalledWith("r-1", "2", "speaker-2", { disposition, expectedVersion: 1, label: "Synthetic chosen name" }));
    await waitFor(() => expect(labels()).toEqual(["Synthetic chosen name"]));
    expect(screen.queryByRole("textbox", { name: "Name for Speaker 1" })).not.toBeInTheDocument();
  });
});

describe("T18 — grouped playback wiring", () => {
  it("feeds exact source intervals to the clock and maps both intervals to one visible playback row", async () => {
    const data = transcript([
      turn({ id: "s1", text: "Synthetic grouped", startMs: 0, endMs: 100, sequence: 1 }),
      turn({ id: "s2", text: "source", startMs: 200, endMs: 300, sequence: 2 }),
    ]);
    data.segments = data.turns.map(({ id, text, startMs, endMs, sequence }) => ({ id, text, startMs, endMs, sequence }));
    vi.mocked(api.getTranscript).mockResolvedValue(data);
    vi.mocked(api.getDiarization).mockResolvedValue({ processing_revision: 2, speakers: [{ id: "s", label: "Speaker 1", sequence: 1 }], assignments: [{ turn_id: "s1", speaker_id: "s", overlap_ms: 100 }, { turn_id: "s2", speaker_id: "s", overlap_ms: 100 }] });
    vi.mocked(api.getPlaybackManifest).mockResolvedValue({ meeting_id: "r-1", duration_seconds: 1, video_presence: "absent", audio_source: { source_id: "synthetic", url: "https://media.example.test/synthetic.wav", mime_type: "audio/wav" }, muxed_video_source: null, video_sources: [] });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const summary = await screen.findByText("Playback passages (1)");
    fireEvent.click(summary);
    const row = summary.closest("details")!.querySelector("li")!;
    expect(row.textContent).toContain("Synthetic grouped source");
    const audio = screen.getByTestId("playback-audio") as HTMLAudioElement;
    for (const [seconds, active] of [[0.05, true], [0.15, false], [0.25, true], [0.3, false]] as const) {
      audio.currentTime = seconds;
      fireEvent.timeUpdate(audio);
      expect(row.getAttribute("aria-current")).toBe(active ? "true" : null);
    }
  });
});

describe("T16 — source visibility and review isolation", () => {
  it("preserves untimed source text without inventing a playback association", async () => {
    const data = transcript([]);
    data.segments = [{ id: "untimed", text: "Synthetic untimed source", sequence: 1, startMs: null, endMs: null }];
    vi.mocked(api.getTranscript).mockResolvedValue(data);
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText("Synthetic untimed source")).toBeVisible();
    expect(screen.getByText("Sin marca de tiempo")).toBeVisible();
    expect(screen.getByRole("button", { name: "Play turn at 00:00" })).toBeDisabled();
  });

  it("does not expose historical review actions as the active review", async () => {
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    vi.mocked(api.getDiarization).mockResolvedValue({ processing_revision: 2, speakers: [], assignments: [] });
    vi.mocked(api.getSpeakerReview).mockResolvedValue({ reviewId: "old", revisionId: "1", status: "pending", labelsBySpeakerId: {}, items: [{ speakerId: "old-speaker", currentLabel: "Synthetic old identity", attributionState: "attributed", disposition: null, excerptRef: "synthetic", expectedVersion: 1 }] });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Hola, buenas tardes.");
    expect(screen.queryByRole("region", { name: "Speaker review" })).not.toBeInTheDocument();
    expect(screen.queryByText("Synthetic old identity")).not.toBeInTheDocument();
  });
});

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

  it("groups adjacent transcript fragments by their assigned speaker while preserving speaker changes", async () => {
    const transcriptData = transcript([
      turn({ id: "fragment-1", text: "Synthetic opening", startMs: 0, endMs: 500, sequence: 1 }),
      turn({ id: "fragment-2", text: "continues here", startMs: 500, endMs: 900, sequence: 2 }),
      turn({ id: "fragment-3", text: "Synthetic reply", startMs: 900, endMs: 1400, sequence: 3 }),
    ]);
    transcriptData.segments = transcriptData.turns.map((speechTurn) => ({
      id: speechTurn.id,
      text: speechTurn.text,
      startMs: speechTurn.startMs,
      endMs: speechTurn.endMs,
      sequence: speechTurn.sequence,
    }));
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcriptData);
    const diarizationApi = api as unknown as {
      getDiarization: ReturnType<typeof vi.fn>;
    };
    diarizationApi.getDiarization.mockResolvedValue({
      processing_revision: 2,
      speakers: [
        { id: "speaker-a", label: "Speaker A", sequence: 1 },
        { id: "speaker-b", label: "Speaker B", sequence: 2 },
      ],
      assignments: [
        { turn_id: "fragment-1", speaker_id: "speaker-a", overlap_ms: 400 },
        { turn_id: "fragment-2", speaker_id: "speaker-a", overlap_ms: 400 },
        { turn_id: "fragment-3", speaker_id: "speaker-b", overlap_ms: 400 },
      ],
    });

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Synthetic opening continues here");
    expect(rows[0].querySelector('[data-testid="transcript-speaker-label"]')?.textContent).toBe("Speaker A");
    expect(rows[1].textContent).toContain("Synthetic reply");
    expect(rows[1].querySelector('[data-testid="transcript-speaker-label"]')?.textContent).toBe("Speaker B");
  });

  it("seeks playback to the first source fragment when a grouped turn is activated", async () => {
    const transcriptData = transcript([
      turn({ id: "fragment-1", text: "Synthetic opening", startMs: 500, endMs: 900, sequence: 1 }),
      turn({ id: "fragment-2", text: "continues here", startMs: 900, endMs: 1300, sequence: 2 }),
    ]);
    transcriptData.segments = transcriptData.turns.map((speechTurn) => ({
      id: speechTurn.id,
      text: speechTurn.text,
      startMs: speechTurn.startMs,
      endMs: speechTurn.endMs,
      sequence: speechTurn.sequence,
    }));
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcriptData);
    const diarizationApi = api as unknown as {
      getDiarization: ReturnType<typeof vi.fn>;
    };
    diarizationApi.getDiarization.mockResolvedValue({
      processing_revision: 2,
      speakers: [{ id: "speaker-a", label: "Speaker A", sequence: 1 }],
      assignments: [
        { turn_id: "fragment-1", speaker_id: "speaker-a", overlap_ms: 400 },
        { turn_id: "fragment-2", speaker_id: "speaker-a", overlap_ms: 400 },
      ],
    });
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue({
      meeting_id: "r-1",
      duration_seconds: 10,
      video_presence: "absent",
      audio_source: { source_id: "audio-1", url: "https://media.example.test/audio.wav", mime_type: "audio/wav" },
      muxed_video_source: null,
      video_sources: [],
    });

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    const seekButton = await screen.findByRole("button", { name: "Play turn at 00:00" });
    fireEvent.click(seekButton);

    expect(screen.getByTestId("playback-audio")).toHaveProperty("currentTime", 0.5);
  });

  it("shows the speaker-identification state when diarization is not found", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    expect(await screen.findByText("Identificando hablantes")).toBeVisible(); // spanish-sample-data
  });

  it("renders a speaker label on every transcript row, including unresolved rows", async () => {
    const transcriptData = transcript([
      turn({ id: "t1", text: "Synthetic first turn", sequence: 1 }),
      turn({ id: "t2", text: "Synthetic second turn", sequence: 2 }),
      turn({ id: "t3", text: "Synthetic unresolved turn", sequence: 3 }),
    ]);
    transcriptData.segments = transcriptData.turns.map((speechTurn) => ({
      id: speechTurn.id,
      text: speechTurn.text,
      startMs: speechTurn.startMs,
      endMs: speechTurn.endMs,
      sequence: speechTurn.sequence,
    }));
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcriptData);
    const diarizationApi = api as unknown as {
      getDiarization: ReturnType<typeof vi.fn>;
    };
    diarizationApi.getDiarization.mockResolvedValue({
      processing_revision: 2,
      speakers: [
        { id: "speaker-a", label: "Speaker 1", sequence: 1 },
        { id: "speaker-b", label: "Speaker 2", sequence: 2 },
      ],
      assignments: [
        { turn_id: "t1", speaker_id: "speaker-a", overlap_ms: 400 },
        { turn_id: "t2", speaker_id: "speaker-b", overlap_ms: 400 },
      ],
    });
    vi.spyOn(api, "getSpeakerReview").mockResolvedValue({
      reviewId: "review-synthetic",
      revisionId: "2",
      status: "complete",
      labelsBySpeakerId: { "speaker-a": "Synthetic Person A", "speaker-b": "Synthetic Person B" },
      items: [
        { speakerId: "speaker-a", currentLabel: "Synthetic Person A", attributionState: "attributed", disposition: "named", excerptRef: "synthetic-a", expectedVersion: 1 },
        { speakerId: "speaker-b", currentLabel: "Synthetic Person B", attributionState: "attributed", disposition: "named", excerptRef: "synthetic-b", expectedVersion: 1 },
      ],
    });
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue({
      meeting_id: "r-1",
      duration_seconds: 10,
      video_presence: "absent",
      audio_source: { source_id: "audio-1", url: "https://media.example.test/audio.wav", mime_type: "audio/wav" },
      muxed_video_source: null,
      video_sources: [],
    });

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    const firstLabels = await screen.findAllByText("Synthetic Person A", { selector: '[data-testid="transcript-speaker-label"]' });
    const secondLabels = screen.getAllByText("Synthetic Person B", { selector: '[data-testid="transcript-speaker-label"]' });
    const unresolvedLabels = screen.getAllByText("Speaker N", { selector: '[data-testid="transcript-speaker-label"]' });
    const passageDetails = screen.getByText("Playback passages (3)").closest("details");
    const rawLabels = Array.from(passageDetails?.querySelectorAll('[data-testid="transcript-speaker-label"]') ?? []);
    const groupedLabels = [...firstLabels, ...secondLabels, ...unresolvedLabels]
      .filter((label) => !passageDetails?.contains(label));
    expect(passageDetails).not.toHaveAttribute("open");
    expect(rawLabels).toHaveLength(3);
    expect(groupedLabels).toHaveLength(3);
    groupedLabels.forEach((label) => expect(label).toBeVisible());
    rawLabels.forEach((label) => expect(label).not.toBeVisible());
    expect(firstLabels).toHaveLength(2);
    expect(secondLabels).toHaveLength(2);
    expect(unresolvedLabels).toHaveLength(2);
    const firstStyle = firstLabels[0].getAttribute("style");
    const secondStyle = secondLabels[0].getAttribute("style");
    expect(firstStyle).toContain("color:");
    expect(secondStyle).toContain("color:");
    expect(secondStyle).not.toBe(firstStyle);
    fireEvent.click(screen.getByText("Playback passages (3)"));
    expect(passageDetails).toHaveAttribute("open");
    rawLabels.forEach((label) => expect(label).toBeVisible());
    groupedLabels.forEach((label) => expect(label).toBeVisible());
  });

  it("renders the playback player before the transcript passages", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue({
      meeting_id: "r-1",
      duration_seconds: 10,
      video_presence: "absent",
      audio_source: {
        source_id: "audio-1",
        url: "https://media.example.test/audio.wav",
        mime_type: "audio/wav",
      },
      muxed_video_source: null,
      video_sources: [],
    });

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    const player = await screen.findByTestId("playback-audio");
    const transcriptHeading = await screen.findByRole("heading", { name: "Transcript" });
    expect(
      player.compareDocumentPosition(transcriptHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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
  labelsBySpeakerId: Record<string, string>;
  items: Array<{
    speakerId: string;
    currentLabel: string;
    attributionState: "attributed" | "uncertain";
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
  submitSpeakerDisposition: (meetingId: string, revisionId: string, speakerId: string, request: DispositionRequest) => Promise<SpeakerReview>;
};
function review(overrides: Partial<SpeakerReview> = {}): SpeakerReview {
  return {
    reviewId: "review-1", revisionId: "1", status: "pending",
    labelsBySpeakerId: { "speaker-1": "Speaker 1", "speaker-2": "Known Speaker" },
    items: [
      { speakerId: "speaker-1", currentLabel: "Speaker 1", attributionState: "uncertain", disposition: null, excerptRef: "opaque-1", expectedVersion: 1 },
      { speakerId: "speaker-2", currentLabel: "Known Speaker", attributionState: "attributed", disposition: null, excerptRef: "opaque-2", expectedVersion: 1 },
    ],
    ...overrides,
  };
}

describe("TranscriptView — speaker review", () => {
  const loadReview = () => vi.spyOn(reviewApi, "getSpeakerReview");
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

  it("plays the selected speaker's longest interval from original playback, not /excerpt", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([
      turn({ id: "a", startMs: 0, endMs: 1000, sequence: 1 }),
      turn({ id: "b", startMs: 1000, endMs: 8000, sequence: 2 }),
      turn({ id: "c", startMs: 8000, endMs: 9000, sequence: 3 }),
    ]));
    loadReview().mockResolvedValue(review({ revisionId: "1" }));
    vi.spyOn(api, "getDiarization").mockResolvedValue({
      processing_revision: 1, speakers: [
        { id: "speaker-1", label: "Speaker 1", sequence: 1 },
        { id: "speaker-2", label: "Known Speaker", sequence: 2 },
      ], assignments: [
        { turn_id: "a", speaker_id: "speaker-1", overlap_ms: 1000 },
        { turn_id: "b", speaker_id: "speaker-1", overlap_ms: 7000 },
        { turn_id: "c", speaker_id: "speaker-2", overlap_ms: 1000 },
      ],
    });
    vi.spyOn(api, "getPlaybackManifest").mockResolvedValue({
      meeting_id: "r-1", duration_seconds: 9, video_presence: "absent",
      audio_source: { source_id: "original", url: "https://media.example.test/original", mime_type: "audio/webm" },
      muxed_video_source: null, video_sources: [],
    });
    const play = vi.spyOn(PlaybackController.prototype, "playInterval").mockResolvedValue();
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const button = await screen.findByRole("button", { name: /listen to speaker 1's speech/i });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(play).toHaveBeenCalledWith(0, 8000));
  });

  it("does not offer original-audio listening for unproven or historical assignments", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn({ id: "t1", endMs: 8000 })]));
    const getDiarization = vi.spyOn(api, "getDiarization").mockResolvedValue({
      processing_revision: 1,
      speakers: [{ id: "speaker-1", label: "Speaker 1", sequence: 1 }],
      assignments: [{ turn_id: "t1", speaker_id: "speaker-1", overlap_ms: null }],
    });
    loadReview().mockResolvedValue(review());
    const view = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByRole("button", { name: /listen to speaker 1's speech/i })).toBeDisabled();
    expect((await screen.findAllByText(/no attributable interval/i)).length).toBe(2);
    view.unmount();

    getDiarization.mockResolvedValue({ processing_revision: 2,
      speakers: [{ id: "speaker-1", label: "Speaker 1", sequence: 1 }],
      assignments: [{ turn_id: "t1", speaker_id: "speaker-1", overlap_ms: 8000 }] });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByText("Hola, buenas tardes.");
    expect(screen.queryByRole("button", { name: /listen to speaker 1's speech/i })).not.toBeInTheDocument();
  });

  it("keeps a chosen name on transcript after the review item leaves the pending list", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn({ id: "t1" })]));
    vi.spyOn(api, "getDiarization").mockResolvedValue({ processing_revision: 1,
      speakers: [{ id: "speaker-1", label: "Speaker 1", sequence: 1 }],
      assignments: [{ turn_id: "t1", speaker_id: "speaker-1", overlap_ms: 1500 }] });
    loadReview().mockResolvedValue(review());
    submit().mockResolvedValue(review({ labelsBySpeakerId: { "speaker-1": "Ana", "speaker-2": "Known Speaker" },
      items: [review().items[1]] }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByRole("button", { name: "Name Speaker 1" });
    fireEvent.change(screen.getByRole("textbox", { name: /name for speaker 1/i }), { target: { value: "Ana" } });
    fireEvent.click(screen.getByRole("button", { name: "Name Speaker 1" }));
    await waitFor(() => expect(screen.getAllByTestId("transcript-speaker-label").some((el) => el.textContent === "Ana")).toBe(true));
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
    await waitFor(() => expect(update).toHaveBeenCalledWith("r-1", "1", "speaker-1", request));
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
