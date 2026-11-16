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
  listMeetings: vi.fn(),
  getMeetingSummary: vi.fn(),
  getLatestSummaryRequest: vi.fn(),
  getTranscript: vi.fn(),
  getPlaybackManifest: vi.fn(),
  getDiarization: vi.fn(),
  getSpeakerReview: vi.fn(),
  submitSpeakerDisposition: vi.fn(),
  newIdempotencyKey: vi.fn(),
}));

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.mocked(api.listMeetings).mockResolvedValue([{ id: "r-1", title: "Synthetic meeting", createdAt: "2026-11-14T12:00:00Z" } as Awaited<ReturnType<typeof api.listMeetings>>[number]]);
  vi.mocked(api.getMeetingSummary).mockResolvedValue(null);
  vi.mocked(api.getLatestSummaryRequest).mockResolvedValue(null);
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
  it("shows the real title, date and turns without technical metadata", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(
      transcript([
        turn({ id: "t1", text: "Hola", startMs: 0, endMs: 1000, sequence: 1 }), // spanish-sample-data
        turn({ id: "t2", text: "¿Cómo estás?", startMs: 1000, endMs: 2500, sequence: 2 }), // spanish-sample-data
      ])
    );

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    await waitFor(() => screen.getByRole("heading", { name: copy.meeting.transcript }));

    expect(await screen.findByRole("heading", { name: "Synthetic meeting" })).toBeVisible();
    expect(screen.getByText(new Date("2026-11-14T12:00:00Z").toLocaleDateString("es", { day: "numeric", month: "long", year: "numeric" }))).toBeVisible();
    expect(screen.queryByText(/es-CO|Provider|Language/)).not.toBeInTheDocument();
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
    await waitFor(() => expect(seekButton).toBeEnabled());
    await screen.findByTestId("playback-audio");
    fireEvent.click(seekButton);

    expect(screen.getByTestId("playback-audio")).toHaveProperty("currentTime", 0.5);
  });

  it("shows the speaker-identification state when diarization is not found", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));
    vi.spyOn(api, "getDiarization").mockRejectedValue(new Error("Error 404"));

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    await waitFor(() => expect(processingCard()).toHaveTextContent(copy.processing.identifying));
    expect(headerBadge()).toHaveTextContent(copy.processing.identifying);
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
      labelsBySpeakerId: { "speaker-a": "Synthetic Person A", "speaker-b": "Synthetic Person B" },
      items: [
        { speakerId: "speaker-a", currentLabel: "Synthetic Person A", attributionState: "attributed", disposition: "named", expectedVersion: 1 },
        { speakerId: "speaker-b", currentLabel: "Synthetic Person B", attributionState: "attributed", disposition: "named", expectedVersion: 1 },
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
    const unresolvedLabels = screen.getAllByText(copy.transcript.legacyUnknownSpeaker, { selector: '[data-testid="transcript-speaker-label"]' });
    const passageDetails = screen.getByText(copy.meeting.passages(3)).closest("details");
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
    fireEvent.click(screen.getByText(copy.meeting.passages(3)));
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
    const transcriptHeading = await screen.findByRole("heading", { name: copy.meeting.transcript });
    expect(
      player.compareDocumentPosition(transcriptHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the empty-state message when there are no segments", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([]));

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    await waitFor(() => screen.getByText(copy.meeting.emptyTranscript));
  });

  it("the 'Back to list' button invokes onBack", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));
    const onBack = vi.fn();

    render(<TranscriptView meetingId="r-1" onBack={onBack} />);
    await waitFor(() => screen.getByRole("heading", { name: copy.meeting.transcript }));

    fireEvent.click(screen.getByRole("link", { name: copy.meeting.back }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("unauthenticated flow: API error is shown as an alert", async () => {
    vi.spyOn(api, "getTranscript").mockRejectedValue(
      new Error("Not authenticated: token not found")
    );

    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);

    const alert = await waitFor(() => screen.getByRole("alert"));
    expect(alert).toHaveTextContent(copy.meeting.transcriptLoadFailed);
  });
});

// Synthetic fixtures for speaker review.
function review(overrides: Partial<api.SpeakerReview> = {}): api.SpeakerReview {
  return {
    reviewId: "review-1", revisionId: "revision-1", status: "pending",
    labelsBySpeakerId: { "speaker-1": "Speaker 1", "speaker-2": "Known Speaker" },
    items: [
      { speakerId: "speaker-1", currentLabel: "Speaker 1", attributionState: "uncertain", disposition: null, expectedVersion: 1 },
      { speakerId: "speaker-2", currentLabel: "Known Speaker", attributionState: "attributed", disposition: null, expectedVersion: 1 },
    ],
    ...overrides,
  };
}

const sr = copy.speakerReview;

function reviewConflict(): Error {
  return Object.assign(new Error(sr.conflict), { reason: "conflict" });
}

describe("TranscriptView — speaker review", () => {
  const loadReview = () => vi.mocked(api.getSpeakerReview);
  const submit = () => vi.mocked(api.submitSpeakerDisposition);
  const loadTranscript = () => vi.spyOn(api, "getTranscript").mockResolvedValue(transcript([turn()]));

  beforeEach(() => {
    let counter = 0;
    vi.mocked(api.newIdempotencyKey).mockImplementation(() => `key-${++counter}`);
  });

  it("shows the pending review with every action, and the complete state", async () => {
    loadTranscript();
    loadReview().mockResolvedValue(review());
    const { unmount } = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: copy.transcript.numberedSpeaker("1") })).toBeDefined();
    expect(screen.getByText(sr.pending)).toBeVisible();
    for (const label of [copy.transcript.numberedSpeaker("1"), "Known Speaker"]) {
      fireEvent.click(screen.getByRole("button", { name: sr.selectSpeaker(label) }));
      expect(screen.getByRole("button", { name: sr.listenTo(label) })).toBeDefined();
      expect(screen.getByRole("button", { name: sr.saveNameFor(label) })).toBeDisabled();
      expect(screen.getByRole("button", { name: sr.confirmFor(label) })).toBeEnabled();
      expect(screen.getByRole("button", { name: sr.correctFor(label) })).toBeDisabled();
      expect(screen.getByRole("textbox", { name: sr.nameFor(label) })).toBeDefined();
    }
    unmount();

    loadTranscript();
    loadReview().mockResolvedValue(review({ status: "complete" }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText(sr.complete)).toBeDefined();
  });

  it("plays the speaker's longest stretch on the original recording", async () => {
    vi.mocked(api.getTranscript).mockResolvedValue({
      ...transcript([]),
      presentation: "words",
      turns: [
        { ...turn({ id: "w1", sequence: 1, startMs: 0, endMs: 1000 }), speakerId: "speaker-1", speakerLabel: "Speaker 1", wordCount: 2, hasAmbiguous: false },
        { ...turn({ id: "w2", sequence: 2, startMs: 1000, endMs: 2000 }), speakerId: "speaker-2", speakerLabel: "Known Speaker", wordCount: 2, hasAmbiguous: false },
        { ...turn({ id: "w3", sequence: 3, startMs: 2000, endMs: 9000 }), speakerId: "speaker-1", speakerLabel: "Speaker 1", wordCount: 9, hasAmbiguous: false },
      ],
    });
    vi.mocked(api.getPlaybackManifest).mockResolvedValue(playback);
    loadReview().mockResolvedValue(review());
    const play = vi.spyOn(PlaybackController.prototype, "playInterval").mockResolvedValue();
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const button = await screen.findByRole("button", { name: sr.listenTo(copy.transcript.numberedSpeaker("1")) });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(play).toHaveBeenCalledWith(2000, 9000));
    // Speaker 2 only has one second of speech: still playable, with a warning.
    expect(screen.getByRole("button", { name: sr.listenTo("Known Speaker") })).toBeEnabled();
    expect(screen.getByText(sr.shortInterval)).toBeVisible();
  });

  it("disables listening and explains why when the speaker has no usable stretch", async () => {
    loadTranscript();
    vi.mocked(api.getPlaybackManifest).mockResolvedValue(playback);
    vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [{ turn_id: "turn-1", speaker_id: "speaker-2" }] });
    loadReview().mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByTestId("playback-audio");
    expect(await screen.findByRole("button", { name: sr.listenTo(copy.transcript.numberedSpeaker("1")) })).toBeDisabled();
    expect(screen.getByText(sr.noInterval)).toBeVisible();
  });

  it.each([
    ["confirm", "confirmed", undefined],
    ["save name", "named", "Ana"],
    ["correct", "corrected", "Ana"],
  ] as const)("submits %s for one speaker only, with version and idempotency key", async (_action, disposition, label) => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    const update = submit().mockResolvedValue(review({ items: [
      { ...review().items[0], disposition },
      review().items[1],
    ] }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByRole("heading", { name: copy.transcript.numberedSpeaker("1") });
    if (label) {
      fireEvent.change(screen.getByRole("textbox", { name: sr.nameFor(copy.transcript.numberedSpeaker("1")) }), { target: { value: ` ${label} ` } });
    }
    const buttonName = disposition === "confirmed" ? sr.confirmFor(copy.transcript.numberedSpeaker("1"))
      : disposition === "named" ? sr.saveNameFor(copy.transcript.numberedSpeaker("1")) : sr.correctFor(copy.transcript.numberedSpeaker("1"));
    fireEvent.click(screen.getByRole("button", { name: buttonName }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("r-1", "revision-1", "speaker-1", {
      disposition, expectedVersion: 1, idempotencyKey: "key-1", ...(label ? { label } : {}),
    }));
    expect(await screen.findByText(sr.confirmedState)).toBeDefined();
    expect(screen.getByRole("heading", { name: "Known Speaker" })).toBeDefined();
  });

  it("shows the chosen name on every turn of that speaker after saving", async () => {
    vi.mocked(api.getTranscript).mockResolvedValue({
      ...transcript([]),
      presentation: "words",
      turns: [
        { ...turn({ id: "w1", sequence: 1, startMs: 0, endMs: 1000 }), speakerId: "speaker-1", speakerLabel: "Speaker 1", wordCount: 2, hasAmbiguous: false },
        { ...turn({ id: "w2", sequence: 2, startMs: 1000, endMs: 2000 }), speakerId: "speaker-2", speakerLabel: "Known Speaker", wordCount: 2, hasAmbiguous: false },
        { ...turn({ id: "w3", sequence: 3, startMs: 2000, endMs: 3000 }), speakerId: "speaker-1", speakerLabel: "Speaker 1", wordCount: 2, hasAmbiguous: false },
      ],
    });
    loadReview().mockResolvedValue(review());
    submit().mockResolvedValue(review({
      labelsBySpeakerId: { "speaker-1": "Ana", "speaker-2": "Known Speaker" },
      items: [{ ...review().items[0], currentLabel: "Ana", disposition: "named", expectedVersion: 2 }, review().items[1]],
    }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    fireEvent.change(await screen.findByRole("textbox", { name: sr.nameFor(copy.transcript.numberedSpeaker("1")) }), { target: { value: "Ana" } });
    fireEvent.click(screen.getByRole("button", { name: sr.saveNameFor(copy.transcript.numberedSpeaker("1")) }));
    const panel = screen.getByRole("region", { name: copy.meeting.transcript });
    await waitFor(() => expect(within(panel).getAllByText("Ana", { selector: '[data-testid="transcript-speaker-label"]' })).toHaveLength(2));
    expect(within(panel).getAllByText("Known Speaker", { selector: '[data-testid="transcript-speaker-label"]' })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Ana" })).toBeDefined();
  });

  it("reuses the idempotency key when the same action is retried after a failure", async () => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    const update = submit().mockRejectedValueOnce(new Error("Error 503")).mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const confirm = await screen.findByRole("button", { name: sr.confirmFor(copy.transcript.numberedSpeaker("1")) });
    fireEvent.click(confirm);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.speakerReview.saveFailed);
    fireEvent.click(confirm);
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update.mock.calls[0][3].idempotencyKey).toBe("key-1");
    expect(update.mock.calls[1][3].idempotencyKey).toBe("key-1");

    fireEvent.click(screen.getByRole("button", { name: sr.selectSpeaker("Known Speaker") }));
    fireEvent.click(screen.getByRole("button", { name: sr.confirmFor("Known Speaker") }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(3));
    expect(update.mock.calls[2][3].idempotencyKey).toBe("key-2");
  });

  it("explains a stale review and uses a new key for the next action", async () => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    const update = submit().mockRejectedValueOnce(reviewConflict()).mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const confirm = await screen.findByRole("button", { name: sr.confirmFor(copy.transcript.numberedSpeaker("1")) });
    fireEvent.click(confirm);
    expect((await screen.findByRole("alert")).textContent).toBe(sr.conflict);
    fireEvent.click(confirm);
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update.mock.calls[1][3].idempotencyKey).toBe("key-2");
  });

  it("asks for the review again after remounting", async () => {
    loadTranscript();
    const load = loadReview().mockResolvedValue(review());
    const view = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: copy.transcript.numberedSpeaker("1") })).toBeDefined();
    view.unmount();
    loadTranscript();
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: copy.transcript.numberedSpeaker("1") })).toBeDefined();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("exposes review actions as keyboard-operable native buttons", async () => {
    loadTranscript(); loadReview().mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByRole("button", { name: sr.confirmFor(copy.transcript.numberedSpeaker("1")) });
    const article = screen.getByRole("heading", { name: copy.transcript.numberedSpeaker("1") }).closest("article");
    const buttons = within(article as HTMLElement).getAllByRole("button");
    expect(buttons).toHaveLength(5);
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
    const panel = await screen.findByRole("region", { name: copy.meeting.transcript });
    const button = await within(panel).findByRole("button", { name: copy.transcript.playAt("01:05") });
    await screen.findByTestId("playback-audio");
    expect(within(panel).getAllByText("Speaker A")).toHaveLength(2);
    expect(within(panel).getByText(copy.transcript.unknownSpeaker)).toBeVisible();
    expect(within(panel).getAllByLabelText(copy.transcript.ambiguous)).toHaveLength(1);
    expect(within(panel).getByRole("button", { name: copy.transcript.playAt("01:08") }))
      .toHaveAccessibleDescription(new RegExp(copy.transcript.ambiguous));
    expect(within(panel).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByText("Legacy segment must not be shown")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(seek).toHaveBeenCalledWith(65432);
    expect(screen.getByTestId("playback-audio")).toHaveProperty("currentTime", 65.432);
  });

  it("highlights and follows the visible word turn using the actual media clock, including seeks and gaps", async () => {
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const audio = await screen.findByTestId("playback-audio") as HTMLAudioElement;
    const panel = screen.getByRole("region", { name: copy.meeting.transcript });
    const rows = within(panel).getAllByRole("listitem");
    const scroll = vi.fn();
    Object.defineProperty(rows[1], "scrollIntoView", { value: scroll });
    audio.currentTime = 68.25;
    fireEvent.timeUpdate(audio);
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).toHaveClass("meeting-turn--active");
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

function processingCard(): HTMLElement {
  return document.querySelector(".meeting-processing") as HTMLElement;
}

function headerBadge(): HTMLElement {
  return document.querySelector(".ui-status-badge") as HTMLElement;
}

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
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByText(copy.processing.queued)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await advance(4999);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "transcribing" });
    await advance(1);
    expect(api.getMeeting).toHaveBeenCalledTimes(2);
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByText(copy.processing.transcribing)).toBeVisible();
    vi.mocked(api.getTranscript).mockResolvedValue({ ...transcript([turn()]), presentation: "segments" });
    await advance();
    expect(within(processingCard()).getByText(copy.processing.identifying)).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [] });
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    await advance();
    expect(screen.getByText("Synthetic attributed turn")).toBeVisible();
    // Speakers are done; the automatic summary request is expected next, so the header is not ready yet.
    expect(headerBadge()).toHaveTextContent(copy.processing.summarizing);
    expect(screen.queryByText(copy.meeting.ready)).not.toBeInTheDocument();
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByRole("status"))
      .toHaveTextContent(copy.processing.summarizing);
    const calls = vi.mocked(api.getMeeting).mock.calls.length;
    await advance(10000);
    // No summary request appeared: the card briefly confirms completion, then goes away.
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByRole("status"))
      .toHaveTextContent(copy.processing.completed);
    expect(headerBadge()).toHaveTextContent(copy.meeting.ready);
    await advance(20000);
    expect(document.querySelector(".meeting-processing")).not.toBeInTheDocument();
    expect(api.getMeeting).toHaveBeenCalledTimes(calls);
    await advance(20000);
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

  it("explains a recording without speech, offers no retry and shows no transcript placeholder", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "failed", failureCause: "no_speech_detected" });
    await open();
    expect(screen.getByText(copy.processing.noSpeechTitle)).toBeVisible();
    expect(screen.getByText(copy.processing.noSpeechBody)).toBeVisible();
    expect(screen.queryByText(copy.processing.failureCause("engine_failure"))).not.toBeInTheDocument();
    expect(screen.queryByText(copy.processing.transcriptPending)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reintentar/i })).not.toBeInTheDocument();
    await advance(20000);
    expect(api.getMeeting).toHaveBeenCalledTimes(1);
  });

  it("keeps polling completed with missing speakers and reloads word turns after the revision arrives", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    await open();
    expect(within(processingCard()).getByText(copy.processing.identifying)).toBeVisible();
    expect(headerBadge()).toHaveTextContent(copy.processing.identifying);
    expect(screen.queryByText(copy.meeting.ready)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await advance(4999);
    expect(api.getDiarization).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(api.getDiarization).toHaveBeenCalledTimes(2);
    expect(within(processingCard()).getByText(copy.processing.identifying)).toBeVisible();

    vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [] });
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    await advance();
    expect(api.getTranscript).toHaveBeenCalledTimes(3);
    expect(vi.mocked(api.getTranscript).mock.invocationCallOrder.at(-1)).toBeGreaterThan(
      vi.mocked(api.getDiarization).mock.invocationCallOrder.at(-1)!,
    );
    expect(screen.getByText("Synthetic attributed turn")).toBeVisible();
    expect(screen.queryByText(copy.processing.identifying)).not.toBeInTheDocument();
    await advance(20000);
    expect(api.getMeeting).toHaveBeenCalledTimes(3);
    expect(api.getDiarization).toHaveBeenCalledTimes(3);
    // The summary wait and the success state end on their own timers.
    await advance(20000);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("follows the automatic summary after speakers, then confirms completion and hides the card", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    vi.mocked(api.getLatestSummaryRequest).mockResolvedValue(null);
    vi.mocked(api.getMeetingSummary).mockResolvedValue(null);
    await open();
    const card = () => document.querySelector(".meeting-processing") as HTMLElement | null;
    expect(within(card()!).getByRole("status")).toHaveTextContent(copy.processing.identifying);
    // Transcription is completed, yet the header follows the stage still running.
    expect(headerBadge()).toHaveTextContent(copy.processing.identifying);
    vi.mocked(api.getDiarization).mockResolvedValue({ speakers: [], assignments: [] });
    vi.mocked(api.getLatestSummaryRequest).mockResolvedValue({ eventId: "e-1", generation: 1, status: "pending" });
    await advance();
    expect(within(card()!).getByRole("status")).toHaveTextContent(copy.processing.summarizing);
    expect(headerBadge()).toHaveTextContent(copy.processing.summarizing);
    expect(screen.queryByText(copy.meeting.ready)).not.toBeInTheDocument();
    expect(card()!.querySelector("[aria-current='step']")).toHaveTextContent(copy.processing.steps.summary);
    // A running summary keeps the card past the short wait for the automatic request.
    vi.mocked(api.getLatestSummaryRequest).mockResolvedValue({ eventId: "e-1", generation: 1, status: "running" });
    await advance(15000);
    expect(within(card()!).getByRole("status")).toHaveTextContent(copy.processing.summarizing);
    expect(headerBadge()).toHaveTextContent(copy.processing.summarizing);
    vi.mocked(api.getMeetingSummary).mockResolvedValue({
      summaryId: "s-1", meetingId: "r-1", templateId: "t", templateName: "General", templateVersion: 1,
      topic: "Synthetic topic", keyPoints: [], reviewState: "draft", generation: 1,
      createdAt: "2026-11-14T12:00:00Z", updatedAt: "2026-11-14T12:00:00Z",
    });
    vi.mocked(api.getLatestSummaryRequest).mockResolvedValue({ eventId: "e-1", generation: 1, status: "succeeded" });
    await advance();
    expect(within(card()!).getByRole("status")).toHaveTextContent(copy.processing.completed);
    expect(headerBadge()).toHaveTextContent(copy.meeting.ready);
    await advance(3000);
    expect(card()).toBeNull();
    expect(headerBadge()).toHaveTextContent(copy.meeting.ready);
    // Final state: no poll of the meeting, speakers or summary request keeps running.
    const settledCalls = vi.mocked(api.getLatestSummaryRequest).mock.calls.length;
    await advance(30000);
    expect(api.getLatestSummaryRequest).toHaveBeenCalledTimes(settledCalls);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops speaker polling at fifteen minutes and explains the wait limit", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    await open();
    await advance(15 * 60 * 1000 - 1);
    expect(within(processingCard()).getByText(copy.processing.identifying)).toBeVisible();
    expect(api.getDiarization).toHaveBeenCalledTimes(180);
    await advance(1);
    expect(screen.getByText(copy.processing.speakerWaitExpired)).toBeVisible();
    expect(processingCard()).not.toHaveTextContent(copy.processing.identifying);
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
    // Poll timer, speaker deadline and the one-second progress ticker of the processing card.
    expect(vi.getTimerCount()).toBe(3);
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "failed", failureCause: "engine_failure" });
    await advance();
    expect(vi.getTimerCount()).toBe(0);
    await advance(15 * 60 * 1000);
    expect(screen.queryByText(copy.processing.speakerWaitExpired)).not.toBeInTheDocument();
    view.unmount();
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "completed" });
    const next = await open();
    expect(vi.getTimerCount()).toBe(3);
    next.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not mislabel a diarization service error as pending identification", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "transcribing" });
    vi.mocked(api.getTranscript).mockResolvedValue(transcript([turn()]));
    vi.mocked(api.getDiarization).mockRejectedValue(new Error("Error 503"));
    await open();
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByText(copy.processing.transcribing)).toBeVisible();
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
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByText(copy.processing.queued)).toBeVisible();
    await act(async () => { finish({ meetingId: "r-1", processState: "failed", failureCause: "engine_failure" }); });
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByText(copy.processing.queued)).toBeVisible();
    expect(screen.queryByText(new RegExp(copy.processing.failed))).not.toBeInTheDocument();
  });
});


describe("TranscriptView — Terra composition", () => {
  beforeEach(() => {
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    vi.mocked(api.getPlaybackManifest).mockResolvedValue(playback);
  });

  it("keeps the transcript visible alongside exactly two side tabs without turn editing", async () => {
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const panel = await screen.findByRole("region", { name: copy.meeting.transcript });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map(tab => tab.textContent)).toEqual([copy.meeting.summaryTab, copy.meeting.chatTab]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(panel).toBeVisible();
    const rows = within(panel).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      expect(row.querySelector(".meeting-timestamp")).toHaveTextContent(/\d{2}:\d{2}/);
      expect(row.querySelector(".meeting-speaker")).not.toBeEmptyDOMElement();
      expect(row.textContent).toContain("Synthetic");
    }
    expect(within(panel).queryByRole("textbox")).not.toBeInTheDocument();
    expect(panel.querySelector("[contenteditable]" )).not.toBeInTheDocument();
    fireEvent.click(tabs[1]);
    const chat = screen.getByRole("tabpanel", { name: copy.meeting.chatTab });
    expect(chat).toHaveTextContent(copy.meeting.chatUnavailable);
    expect(within(chat).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(chat).queryByRole("button")).not.toBeInTheDocument();
    expect(panel).toBeVisible();
    fireEvent.keyDown(tabs[1], { key: "Home" });
    expect(tabs[0]).toHaveFocus();
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  });

  it("keeps transcript-following active even when the chat tab is selected", async () => {
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const audio = await screen.findByTestId("playback-audio") as HTMLAudioElement;
    const rows = within(screen.getByRole("region", { name: copy.meeting.transcript })).getAllByRole("listitem");
    const scroll = vi.fn();
    Object.defineProperty(rows[1], "scrollIntoView", { value: scroll });
    fireEvent.click(screen.getByRole("tab", { name: copy.meeting.chatTab }));
    audio.currentTime = 68.25;
    fireEvent.timeUpdate(audio);
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).toHaveClass("meeting-turn--active");
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("reports unavailable metadata without inventing a title or a date", async () => {
    vi.mocked(api.listMeetings).mockRejectedValueOnce(new Error("Synthetic failure"));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText(copy.meeting.metadataFailed)).toBeVisible();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.meeting.untitled);
    expect(document.querySelector("time")).not.toBeInTheDocument();
  });
});


describe("TranscriptView — visual QA refinements", () => {
  beforeEach(() => {
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    vi.mocked(api.getPlaybackManifest).mockResolvedValue(playback);
  });

  it("makes the full two-line turn a native button that seeks and starts playback", async () => {
    const seek = vi.spyOn(PlaybackController.prototype, "seekTo");
    const play = vi.spyOn(PlaybackController.prototype, "resume");
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByTestId("playback-audio");
    const panel = screen.getByRole("region", { name: copy.meeting.transcript });
    const row = within(panel).getAllByRole("listitem")[0];
    const action = within(row).getByRole("button", { name: copy.transcript.playAt("01:05") });
    expect(action.tagName).toBe("BUTTON");
    expect(action).toHaveAccessibleDescription("Speaker A Synthetic attributed turn");
    expect(within(row).getAllByRole("button")).toHaveLength(1);
    expect(action.querySelector(".meeting-turn-meta .meeting-timestamp")).toHaveTextContent("01:05");
    expect(action.querySelector(".meeting-turn-meta .meeting-speaker")).toHaveTextContent("Speaker A");
    expect(action.querySelector(".meeting-turn-text")).toHaveTextContent("Synthetic attributed turn");
    expect(action.textContent).not.toContain(copy.transcript.play);
    action.focus();
    expect(action).toHaveFocus();
    fireEvent.click(within(action).getByText("Synthetic attributed turn"));
    expect(seek).toHaveBeenCalledWith(65432);
    expect(play).toHaveBeenCalledTimes(1);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    const audio = screen.getByTestId("playback-audio") as HTMLAudioElement;
    fireEvent.timeUpdate(audio);
    expect(row).toHaveAttribute("aria-current", "true");
    expect(action).toHaveAttribute("aria-current", "true");
    expect(row).toHaveClass("meeting-turn--active");
    expect(row.style.getPropertyValue("--meeting-speaker")).toBe("var(--ds-speaker-unresolved)");
  });

  it("keeps untimed turns readable but not playable", async () => {
    const data = attributedTranscript();
    const untimed = { ...data, turns: [{ ...data.turns[0], startMs: null }, ...data.turns.slice(1)] };
    vi.mocked(api.getTranscript).mockResolvedValue(untimed as unknown as MeetingTranscript);
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByTestId("playback-audio");
    const panel = screen.getByRole("region", { name: copy.meeting.transcript });
    const row = within(panel).getAllByRole("listitem")[0];
    expect(within(row).getByRole("button")).toBeDisabled();
    expect(within(row).getByText("Synthetic attributed turn")).toBeVisible();
  });

  it.each(["words", "segments"] as const)("localizes only numeric backend labels in %s presentation", async presentation => {
    const data = attributedTranscript();
    data.presentation = presentation;
    data.turns = [{ ...data.turns[0], speakerId: "speaker-4", speakerLabel: "Speaker 4" }];
    data.segments = data.turns.map(({ id, text, startMs, endMs, sequence }) => ({ id, text, startMs, endMs, sequence }));
    vi.mocked(api.getTranscript).mockResolvedValue(data);
    vi.mocked(api.getDiarization).mockResolvedValue({
      speakers: [{ id: "speaker-4", label: "Speaker 4", sequence: 4 }],
      assignments: [{ turn_id: data.turns[0].id, speaker_id: "speaker-4" }],
    });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByTestId("playback-audio");
    const labels = screen.getAllByTestId("transcript-speaker-label");
    expect(labels).toHaveLength(2);
    labels.forEach(label => expect(label).toHaveTextContent(copy.transcript.numberedSpeaker("4")));
    expect(data.turns[0].speakerLabel).toBe("Speaker 4");
    const row = within(screen.getByRole("region", { name: copy.meeting.transcript })).getByRole("listitem");
    expect(row.style.getPropertyValue("--meeting-speaker")).toBe("var(--ds-speaker-4)");
  });

  it.each(["named", "corrected"] as const)("preserves an explicitly %s user name even if it matches a default label", async disposition => {
    const data = attributedTranscript();
    data.turns = [{ ...data.turns[0], speakerId: "speaker-1", speakerLabel: "Speaker 4" }];
    vi.mocked(api.getTranscript).mockResolvedValue(data);
    vi.mocked(api.getSpeakerReview).mockResolvedValue(review({
      labelsBySpeakerId: { "speaker-1": "Speaker 4" },
      items: [{ ...review().items[0], currentLabel: "Speaker 4", disposition }],
    }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Speaker 4" })).toBeVisible();
    const labels = screen.getAllByTestId("transcript-speaker-label");
    labels.forEach(label => expect(label).toHaveTextContent("Speaker 4"));
    expect(screen.getByRole("textbox", { name: sr.nameFor("Speaker 4") })).toBeVisible();
  });

  it.each(["Speaker A", "Speaker4", "Speaker 4 Smith"])("preserves the backend name %s", async label => {
    const data = attributedTranscript();
    data.turns = [{ ...data.turns[0], speakerLabel: label }];
    vi.mocked(api.getTranscript).mockResolvedValue(data);
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByTestId("playback-audio");
    screen.getAllByTestId("transcript-speaker-label").forEach(element => expect(element).toHaveTextContent(label));
  });

  it("moves completion to a success badge beside the date without a full-width status block", async () => {
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const badge = await screen.findByText(copy.meeting.ready);
    expect(badge).toHaveClass("ui-status-badge--success");
    expect(badge.parentElement?.querySelector("time")).toHaveAttribute("datetime", "2026-11-14T12:00:00Z");
    expect(document.querySelector(".meeting-processing")).not.toBeInTheDocument();
  });

  it("preserves the actual processing text in a soft card until completed", async () => {
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "transcribing" });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findAllByText(copy.processing.transcribing);
    expect(document.querySelector(".meeting-processing")).toHaveTextContent(copy.processing.transcribing);
    expect(screen.queryByText(copy.meeting.ready)).not.toBeInTheDocument();
  });

  it("does not hide ongoing speaker identification when ASR is already completed", async () => {
    vi.mocked(api.getDiarization).mockRejectedValue(new Error("Error 404"));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await waitFor(() => expect(processingCard()).toHaveTextContent(copy.processing.identifying));
    expect(headerBadge()).toHaveTextContent(copy.processing.identifying);
    expect(headerBadge()).toHaveClass("ui-status-badge--progress");
    expect(screen.queryByText(copy.meeting.ready)).not.toBeInTheDocument();
  });
});

describe("TranscriptView — redesigned meeting", () => {
  beforeEach(() => {
    vi.mocked(api.getTranscript).mockResolvedValue(attributedTranscript());
    vi.mocked(api.getPlaybackManifest).mockResolvedValue(playback);
  });

  it("shows pending speakers, focuses their card from the banner and removes the banner after review", async () => {
    const pending = review({ items: [review().items[0]], labelsBySpeakerId: { "speaker-1": "Speaker 1" } });
    vi.mocked(api.getSpeakerReview).mockResolvedValue(pending);
    vi.mocked(api.submitSpeakerDisposition).mockResolvedValue({
      ...pending, status: "complete", items: [{ ...pending.items[0], disposition: "confirmed", expectedVersion: 2 }],
    });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(await screen.findByText(copy.meeting.pendingSpeakers(1))).toBeVisible();
    const card = screen.getByRole("region", { name: sr.heading });
    expect(within(card).getByText(sr.pendingState)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: copy.meeting.reviewSpeakers }));
    expect(card.contains(document.activeElement)).toBe(true);
    fireEvent.click(within(card).getByRole("button", { name: sr.confirmFor(copy.transcript.numberedSpeaker("1")) }));
    await waitFor(() => expect(screen.queryByText(copy.meeting.pendingSpeakers(1))).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: copy.meeting.reviewSpeakers })).not.toBeInTheDocument();
    expect(within(card).getByText(sr.confirmedState)).toBeVisible();
  });

  it("does not show a pending banner for already named, corrected or confirmed speakers", async () => {
    vi.mocked(api.getSpeakerReview).mockResolvedValue(review({ status: "complete", items: [
      { ...review().items[0], disposition: "named" }, { ...review().items[1], disposition: "corrected" },
      { ...review().items[0], speakerId: "speaker-3", disposition: "confirmed" },
    ] }));
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByRole("region", { name: sr.heading });
    expect(screen.queryByRole("button", { name: copy.meeting.reviewSpeakers })).not.toBeInTheDocument();
    expect(screen.getAllByText(sr.confirmedState)).toHaveLength(3);
  });

  it("shows only the selected speaker editor and keeps drafts when switching speakers", async () => {
    vi.mocked(api.getSpeakerReview).mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const first = copy.transcript.numberedSpeaker("1");
    const input = await screen.findByRole("textbox", { name: sr.nameFor(first) });
    fireEvent.change(input, { target: { value: "Synthetic draft" } });
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    const second = screen.getByRole("button", { name: sr.selectSpeaker("Known Speaker") });
    fireEvent.click(second);
    expect(second).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("textbox", { name: sr.nameFor(first) })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: sr.nameFor("Known Speaker") })).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: sr.selectSpeaker(first) }));
    expect(screen.getByRole("textbox", { name: sr.nameFor(first) })).toHaveValue("Synthetic draft");
  });

  it("disables both transcript and playback-passage following without disabling active highlighting", async () => {
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const audio = await screen.findByTestId("playback-audio") as HTMLAudioElement;
    const panel = screen.getByRole("region", { name: copy.meeting.transcript });
    const rows = within(panel).getAllByRole("listitem");
    const passage = document.querySelector('[data-passage-id="word-turn-2"]')!;
    const rowScroll = vi.fn();
    const passageScroll = vi.fn();
    Object.defineProperty(rows[1], "scrollIntoView", { value: rowScroll });
    Object.defineProperty(passage, "scrollIntoView", { value: passageScroll });
    const follow = screen.getByRole("checkbox", { name: copy.meeting.followPlayback });
    expect(follow).toBeChecked();
    fireEvent.click(follow);
    audio.currentTime = 68.25;
    fireEvent.timeUpdate(audio);
    expect(rows[1]).toHaveAttribute("aria-current", "true");
    expect(passage).toHaveAttribute("aria-current", "true");
    expect(rowScroll).not.toHaveBeenCalled();
    expect(passageScroll).not.toHaveBeenCalled();
    fireEvent.click(follow);
    expect(rowScroll).toHaveBeenCalledWith({ block: "nearest" });
    audio.currentTime = 65.5;
    fireEvent.timeUpdate(audio);
    audio.currentTime = 68.5;
    fireEvent.timeUpdate(audio);
    expect(passageScroll).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("renders hidden skeletons for the header, player, transcript and panel while opening", async () => {
    let finish!: (data: MeetingTranscript) => void;
    vi.mocked(api.getTranscript).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const { container } = render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.meeting.opening);
    expect(container.querySelector(".meeting-loading-heading")).toHaveAttribute("aria-hidden", "true");
    for (const selector of [".meeting-playback-card", ".meeting-transcript", ".meeting-side-column"]) {
      expect(container.querySelector(`${selector} .ui-skeleton`)).toBeInTheDocument();
    }
    expect(container.querySelector(".meeting-grid")).toHaveAttribute("aria-hidden", "true");
    await waitFor(() => expect(api.getTranscript).toHaveBeenCalled());
    await act(async () => { finish(attributedTranscript()); });
    expect(screen.queryByText(copy.meeting.opening)).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: copy.meeting.transcript })).toBeVisible();
  });

  it("keeps ghost turns and an estimated, labelled processing progress when no transcript exists yet", async () => {
    vi.mocked(api.getTranscript).mockRejectedValue(new Error("Error 404"));
    vi.mocked(api.getMeeting).mockResolvedValue({ meetingId: "r-1", processState: "transcribing" });
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    const panel = await screen.findByRole("region", { name: copy.meeting.transcript });
    expect(within(panel).getByText(copy.meeting.transcriptPlaceholder)).toBeVisible();
    expect(within(panel).getByText(copy.processing.transcriptPending)).toBeVisible();
    expect(panel.querySelector(".meeting-transcript-skeleton")).toHaveAttribute("aria-hidden", "true");
    expect(panel.querySelectorAll(".meeting-skeleton-turn")).toHaveLength(3);
    // The 180 s recording allows an honest estimate: determinate, capped and marked as estimated.
    const bar = screen.getByRole("progressbar", { name: copy.processing.transcribing });
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeLessThanOrEqual(95);
    expect(document.querySelector(".processing-remaining")?.textContent).toMatch(
      new RegExp(`${copy.processing.remainingUnderMinute}|${copy.processing.remaining(1)}|${copy.processing.remaining(2)}|${copy.processing.overtime}`));
    expect(within(document.querySelector(".meeting-processing") as HTMLElement).getByRole("status")).toHaveTextContent(copy.processing.transcribing);
  });

  it("places the sidebar and speakers between playback and transcript in reading order", async () => {
    vi.mocked(api.getSpeakerReview).mockResolvedValue(review());
    render(<TranscriptView meetingId="r-1" onBack={vi.fn()} />);
    await screen.findByRole("region", { name: sr.heading });
    const grid = document.querySelector(".meeting-grid")!;
    expect([...grid.children].map(child => child.className)).toEqual([
      "ui-card meeting-playback-card", "meeting-side-column", "ui-card meeting-transcript",
    ]);
    const side = grid.querySelector(".meeting-side-column")!;
    expect(side.querySelector(".meeting-sidebar")!.compareDocumentPosition(side.querySelector(".meeting-speaker-review")!))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
