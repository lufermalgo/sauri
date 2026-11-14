// @vitest-environment jsdom
/**
 * Frontend component tests: transcript view.
 *
 * Feature: meeting-capture-transcription
 * Task: 15.5 — Validates: Requirements 9.1, 9.2, 4.5
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup, waitFor, fireEvent, act, within } from "@testing-library/react";
import type { Transcript, SpeechTurn } from "@sauri/shared-types";
import { copy } from "../copy/es";
import { PlaybackController } from "./PlaybackController";
import type { MeetingTranscript, TimedPassage } from "../api";

import { TranscriptView } from "./TranscriptView";
import * as api from "../api";

vi.mock("../api", () => ({
  getMeeting: vi.fn(),
  getTranscript: vi.fn(),
  getPlaybackManifest: vi.fn(),
  getDiarization: vi.fn(),
  getSpeakerReview: vi.fn(),
  playSpeakerExcerpt: vi.fn(),
  submitSpeakerDisposition: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
  vi.mocked(api.getSpeakerReview).mockResolvedValue(null as unknown as api.SpeakerReview);
  vi.spyOn(api, "getPlaybackManifest").mockResolvedValue(
    null as unknown as Awaited<ReturnType<typeof api.getPlaybackManifest>>,
  );
  vi.spyOn(api, "getDiarization").mockResolvedValue({ speakers: [], assignments: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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
      speakers: [
        { id: "speaker-a", label: "Speaker A", sequence: 1 },
        { id: "speaker-b", label: "Speaker B", sequence: 2 },
      ],
      assignments: [
        { turn_id: "fragment-1", speaker_id: "speaker-a" },
        { turn_id: "fragment-2", speaker_id: "speaker-a" },
        { turn_id: "fragment-3", speaker_id: "speaker-b" },
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
      speakers: [{ id: "speaker-a", label: "Speaker A", sequence: 1 }],
      assignments: [
        { turn_id: "fragment-1", speaker_id: "speaker-a" },
        { turn_id: "fragment-2", speaker_id: "speaker-a" },
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

    const seekButton = await screen.findByRole("button", { name: copy.transcript.playAt("00:00") });
    fireEvent.click(seekButton);

    expect(screen.getByTestId("playback-audio")).toHaveProperty("currentTime", 0.5);
  });

  it("shows the speaker-identification state when diarization is not found", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    expect(await screen.findByText(copy.processing.identifying)).toBeVisible();
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
      speakers: [
        { id: "speaker-a", label: "Speaker 1", sequence: 1 },
        { id: "speaker-b", label: "Speaker 2", sequence: 2 },
      ],
      assignments: [
        { turn_id: "t1", speaker_id: "speaker-a" },
        { turn_id: "t2", speaker_id: "speaker-b" },
      ],
    });
    vi.spyOn(api, "getSpeakerReview").mockResolvedValue({
      reviewId: "review-synthetic",
      revisionId: "revision-synthetic",
      status: "complete",
      items: [
        { speakerId: "speaker-a", currentLabel: "Synthetic Person A", attributionState: "recognized", disposition: "named", excerptRef: "synthetic-a", expectedVersion: 1 },
        { speakerId: "speaker-b", currentLabel: "Synthetic Person B", attributionState: "recognized", disposition: "named", excerptRef: "synthetic-b", expectedVersion: 1 },
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

    await waitFor(() => expect(screen.getAllByText("Synthetic Person A", { selector: '[data-testid="transcript-speaker-label"]' })).toHaveLength(2));
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
    await screen.findByRole("button", { name: /confirm speaker 1/i });
    const buttons = await screen.findAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(4);
    for (const button of buttons) expect(button.tagName).toBe("BUTTON");
  });
});

const playback: api.PlaybackManifest = {
  meeting_id: "r-1", duration_seconds: 180, video_presence: "absent",
  audio_source: { source_id: "audio-1", url: "http://localhost/synthetic.wav", mime_type: "audio/wav" },
  muxed_video_source: null, video_sources: [],
};

function attributedTranscript(): MeetingTranscript {
  return {
    ...transcript([]),
    presentation: "words",
    segments: [{ id: "legacy", text: "Legacy segment must not be shown", startMs: 0, endMs: 90000, sequence: 1 }],
    turns: [
      { ...turn({ id: "word-turn-1", sequence: 1, text: "Synthetic attributed turn", startMs: 65432, endMs: 68000 }),
        speakerId: "speaker-a", speakerLabel: "Speaker A", wordCount: 3, hasAmbiguous: false },
      { ...turn({ id: "word-turn-2", sequence: 2, text: "Synthetic uncertain turn", startMs: 68000, endMs: 70000 }),
        speakerId: null, speakerLabel: null, wordCount: 3, hasAmbiguous: true },
      { ...turn({ id: "word-turn-3", sequence: 3, text: "Synthetic returning turn", startMs: 70000, endMs: 72000 }),
        speakerId: "speaker-a", speakerLabel: "Speaker A", wordCount: 3, hasAmbiguous: false },
    ],
  };
}

describe("TranscriptView — attributed word turns", () => {
  beforeEach(() => {
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    vi.mocked(api.getPlaybackManifest).mockResolvedValue(playback);
  });

  it("shows backend speaker labels, null attribution, ambiguity and exact timestamp seeks", async () => {
    const seek = vi.spyOn(PlaybackController.prototype, "seekTo");
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const panel = await screen.findByRole("tabpanel", { name: copy.summary.transcriptTab });
    const button = await within(panel).findByRole("button", { name: copy.transcript.playAt("01:05") });
    await screen.findByTestId("playback-audio");
    expect(within(panel).getAllByText("Speaker A")).toHaveLength(2);
    expect(within(panel).getByText(copy.transcript.unknownSpeaker)).toBeVisible();
    expect(within(panel).getAllByLabelText(copy.transcript.ambiguous)).toHaveLength(1);
    expect(within(panel).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("Legacy segment must not be shown")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(seek).toHaveBeenCalledWith(65432);
    expect(screen.getByTestId("playback-audio")).toHaveProperty("currentTime", 65.432);
  });

  it("highlights and follows the visible word turn using the actual media clock, including seeks and gaps", async () => {
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const audio = await screen.findByTestId("playback-audio") as HTMLAudioElement;
    const panel = screen.getByRole("tabpanel", { name: copy.summary.transcriptTab });
    const rows = within(panel).getAllByRole("listitem");
    const scroll = vi.fn();
    Object.defineProperty(rows[1], "scrollIntoView", { value: scroll });
    audio.currentTime = 68.25;
    fireEvent.timeUpdate(audio);
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).toHaveStyle({ backgroundColor: "#fef3c7" });
    expect(rows[0]).not.toHaveAttribute("aria-current");
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
    fireEvent.timeUpdate(audio);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(audio.currentTime).toBe(68.25);
    audio.currentTime = 70;
    fireEvent.seeked(audio);
    expect(rows[2]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).not.toHaveAttribute("aria-current");
    audio.currentTime = 72;
    fireEvent.timeUpdate(audio);
    rows.forEach((row) => expect(row).not.toHaveAttribute("aria-current"));
  });
});

describe("TranscriptView — processing polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "queued" });
    vi.mocked(api.getTranscript).mockRejectedValue(new Error("Error 404"));
    vi.mocked(api.getDiarization).mockRejectedValue(new Error("Error 404"));
    vi.mocked(api.getSpeakerReview).mockRejectedValue(new Error("Error 404"));
  });

  async function open() {
    let view!: ReturnType<typeof render>;
    await act(async () => { view = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />); });
    return view;
  }

  async function advance(ms = 5000) {
    await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  }

  it("polls every five seconds from queued through transcription and identification to completion", async () => {
    await open();
    expect(screen.getByText(copy.processing.queued)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await advance(4999);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "transcribing" });
    await advance(1);
    expect(api.getMeeting).toHaveBeenCalledTimes(2);
    expect(screen.getByText(copy.processing.transcribing)).toBeVisible();
    vi.mocked(api.getTranscript).mockResolvedValue({ ...transcript([turn()]), presentation: "segments" });
    await advance();
    expect(screen.getByText(copy.processing.identifying)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [] });
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    await advance();
    expect(screen.getByText(copy.processing.completed)).toBeVisible();
    expect(screen.getByText("Synthetic attributed turn")).toBeVisible();
    const calls = vi.mocked(api.getMeeting).mock.calls.length;
    await advance(20000);
    expect(api.getMeeting).toHaveBeenCalledTimes(calls);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops while hidden and resumes immediately when visible, without polling after unmount", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const view = await open();
    hidden.mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await advance(20000);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    expect(api.getTranscript).toHaveBeenCalledTimes(1);
    expect(api.getDiarization).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    hidden.mockReturnValue(false);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(api.getMeeting).toHaveBeenCalledTimes(2);
    await advance();
    expect(api.getMeeting).toHaveBeenCalledTimes(3);
    view.unmount();
    await advance(10000);
    expect(api.getMeeting).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not start hidden and clears a pending poll if an in-flight request ends while hidden", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    await open();
    await advance(10000);
    expect(api.getMeeting).not.toHaveBeenCalled();
    let finish!: (state: api.MeetingState) => void;
    vi.mocked(api.getMeeting).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    hidden.mockReturnValue(false);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    hidden.mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => { finish({ meetingId: "r-1", processState: "transcribing" }); });
    await advance(15000);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops on failure even without diarization and never invents a retry action", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "failed", failureCause: "engine_failure" });
    await open();
    expect(screen.getByText(new RegExp(copy.processing.failureCause("engine_failure")))).toBeVisible();
    expect(screen.queryByRole("button", { name: copy.summary.retry })).not.toBeInTheDocument();
    await advance(20000);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    fireEvent(document, new Event("visibilitychange"));
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
  });

  it("keeps polling completed with missing speakers and reloads word turns after the revision arrives", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    await open();
    expect(screen.getByText(copy.processing.identifying)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await advance(4999);
    expect(api.getDiarization).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(api.getDiarization).toHaveBeenCalledTimes(2);
    expect(screen.getByText(copy.processing.identifying)).toBeVisible();

    vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [] });
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    await advance();
    expect(api.getTranscript).toHaveBeenCalledTimes(3);
    expect(vi.mocked(api.getTranscript).mock.invocationCallOrder.at(-1)).toBeGreaterThan(
      vi.mocked(api.getDiarization).mock.invocationCallOrder.at(-1)!,
    );
    expect(screen.getByText("Synthetic attributed turn")).toBeVisible();
    expect(screen.getByText(copy.processing.completed)).toBeVisible();
    expect(screen.queryByText(copy.processing.identifying)).not.toBeInTheDocument();
    await advance(20000);
    expect(api.getMeeting).toHaveBeenCalledTimes(3);
    expect(api.getDiarization).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops speaker polling at fifteen minutes and explains the wait limit", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    await open();
    await advance(15 * 60 * 1000 - 1);
    expect(screen.getByText(copy.processing.identifying)).toBeVisible();
    expect(api.getDiarization).toHaveBeenCalledTimes(180);
    await advance(1);
    expect(screen.getByText(copy.processing.speakerWaitExpired)).toBeVisible();
    expect(screen.queryByText(copy.processing.identifying)).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
    await advance(20000);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(api.getMeeting).toHaveBeenCalledTimes(180);
    expect(api.getTranscript).toHaveBeenCalledTimes(180);
    expect(api.getDiarization).toHaveBeenCalledTimes(180);
  });

  it("does not query hidden while waiting for speakers and includes hidden time in the limit", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    await open();
    hidden.mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await advance(20000);
    expect(api.getDiarization).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(api.getDiarization).toHaveBeenCalledTimes(2);
    hidden.mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await advance(15 * 60 * 1000 - 20000);
    expect(screen.getByText(copy.processing.speakerWaitExpired)).toBeInTheDocument();
    hidden.mockReturnValue(false);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(api.getMeeting).toHaveBeenCalledTimes(2);
    expect(api.getTranscript).toHaveBeenCalledTimes(2);
    expect(api.getDiarization).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ignores a speaker revision that arrives after the wait limit during a slow request", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    await open();
    let finish!: (revision: api.MeetingDiarization) => void;
    vi.mocked(api.getDiarization).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    await advance();
    await advance(15 * 60 * 1000 - 5000);
    expect(screen.getByText(copy.processing.speakerWaitExpired)).toBeVisible();
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    await act(async () => { finish({ speakers: [], assignments: [] }); });
    expect(api.getTranscript).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Synthetic attributed turn")).not.toBeInTheDocument();
    await advance(10000);
    expect(api.getDiarization).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("clears the speaker deadline on failure and on unmount", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    const view = await open();
    expect(vi.getTimerCount()).toBe(2);
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "failed", failureCause: "engine_failure" });
    await advance();
    expect(vi.getTimerCount()).toBe(0);
    await advance(15 * 60 * 1000);
    expect(screen.queryByText(copy.processing.speakerWaitExpired)).not.toBeInTheDocument();
    view.unmount();
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    const next = await open();
    expect(vi.getTimerCount()).toBe(2);
    next.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not mislabel a diarization service error as pending identification", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "transcribing" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    vi.mocked(api.getDiarization).mockRejectedValue(new Error("Error 503"));
    await open();
    expect(screen.getByText(copy.processing.transcribing)).toBeVisible();
    expect(screen.getByText(copy.processing.diarizationFailed)).toBeVisible();
    expect(screen.queryByText(copy.processing.identifying)).not.toBeInTheDocument();
  });

  it("does not overlap requests when a slow response outlasts the polling period", async () => {
    let finish!: (state: api.MeetingState) => void;
    vi.mocked(api.getMeeting).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    await open();
    await advance(15000);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ meetingId: "r-1", processState: "queued" }); });
    await advance(4999);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(api.getMeeting).toHaveBeenCalledTimes(2);
  });

  it("ignores results from a previous meeting when navigating during a request", async () => {
    let finish!: (state: api.MeetingState) => void;
    vi.mocked(api.getMeeting).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const view = await open();
    await act(async () => { view.rerender(<TranscriptView meetingId="new-meeting" onBack={vi.fn()} />); });
    expect(screen.getByText(copy.processing.queued)).toBeVisible();
    await act(async () => { finish({ meetingId: "r-1", processState: "failed", failureCause: "engine_failure" }); });
    expect(screen.getByText(copy.processing.queued)).toBeVisible();
    expect(screen.queryByText(new RegExp(copy.processing.failed))).not.toBeInTheDocument();
  });
});
