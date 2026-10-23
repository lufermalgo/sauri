// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { SpeakerRecognitionTestScreen } from "./SpeakerRecognitionTestScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  getMeeting: vi.fn(),
  getTranscript: vi.fn(),
  getSpeakerReview: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const meeting = (processState: "processing" | "completed") => ({
  id: "meeting-test-1",
  processState,
});

const transcript = {
  id: "transcript-test-1",
  meetingId: "meeting-test-1",
  language: "es-CO",
  provider: "local",
  supportsTurns: true,
  createdAt: "2026-01-01T00:00:00Z",
  segments: [
    {
      id: "segment-test-1",
      startMs: 1250,
      endMs: 2500,
      text: "La propuesta queda para el viernes.",
      speakerLabel: "Speaker 2",
      sequence: 1,
    },
  ],
  turns: [],
};

const review = {
  reviewId: "review-test-1",
  revisionId: "revision-test-1",
  status: "pending",
  items: [],
};

const apiMocks = api as unknown as {
  getMeeting: (meetingId: string) => Promise<{ id: string; processState: string }>;
  getTranscript: (meetingId: string) => Promise<typeof transcript>;
  getSpeakerReview: (meetingId: string) => Promise<typeof review>;
};

describe("SpeakerRecognitionTestScreen", () => {
  it("shows persisted processing state before loading transcript or speaker review", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("processing"));
    const getTranscript = vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    const getSpeakerReview = vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    render(<SpeakerRecognitionTestScreen meetingId="meeting-test-1" />);

    expect(await screen.findByText(/processing/i)).toBeVisible();
    expect(getTranscript).not.toHaveBeenCalled();
    expect(getSpeakerReview).not.toHaveBeenCalled();
    expect(screen.queryByText("La propuesta queda para el viernes.")).not.toBeInTheDocument();
  });

  it("loads transcript and persisted speaker review after processing completes", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    const getTranscript = vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    const getSpeakerReview = vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    render(<SpeakerRecognitionTestScreen meetingId="meeting-test-1" />);

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(getTranscript).toHaveBeenCalledWith("meeting-test-1");
    expect(getSpeakerReview).toHaveBeenCalledWith("meeting-test-1");
    await waitFor(() => {
      expect(screen.getByText(/pending/i)).toBeVisible();
    });
  });

  it("preserves segment timestamp, exact text and unresolved backend speaker label as read-only content", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    render(<SpeakerRecognitionTestScreen meetingId="meeting-test-1" />);

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.getByText("00:01")).toBeVisible();
    expect(screen.getByText("Speaker 2")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: /transcript|segment/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit transcript/i })).not.toBeInTheDocument();
  });

  it("limits the screen to upload, processing, transcript inspection and speaker review", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    render(<SpeakerRecognitionTestScreen meetingId="meeting-test-1" />);

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.getByText(/transcript/i)).toBeVisible();
    expect(screen.getByText(/speaker review/i)).toBeVisible();
    expect(screen.queryByText(/library|analytics|settings|meeting management/i)).not.toBeInTheDocument();
  });
});
