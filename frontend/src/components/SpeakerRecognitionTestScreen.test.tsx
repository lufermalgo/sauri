// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { SpeakerRecognitionTestScreen } from "./SpeakerRecognitionTestScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  uploadRecording: vi.fn(),
  getMeeting: vi.fn(),
  getTranscript: vi.fn(),
  getSpeakerReview: vi.fn(),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function createSyntheticWebm(trackType: 1 | 2) {
  // EBML Segment > Tracks > TrackEntry > TrackType (1 = video, 2 = audio).
  return new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0x80, 0x18, 0x53, 0x80, 0x67, 0x8a, 0x16, 0x54, 0xae, 0x6b, 0x85, 0xae, 0x83, 0x83, 0x81, trackType]);
}

function selectSyntheticAudio() {
  const file = new File([createSyntheticWebm(2)], "sample.webm", { type: "audio/webm" });
  fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
  return file;
}

function selectSyntheticVideo() {
  const file = new File(["synthetic video"], "sample.mp4", { type: "video/mp4" });
  fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
  return file;
}

function fireLoadedMetadata(duration: number) {
  const media = document.querySelector("audio, video");
  if (!(media instanceof HTMLMediaElement)) {
    throw new Error("Expected the selected recording metadata element");
  }
  Object.defineProperty(media, "duration", { configurable: true, value: duration });
  fireEvent.loadedMetadata(media);
}

describe("SpeakerRecognitionTestScreen upload metadata", () => {
  it("does not submit until finite browser media duration is available, then rounds seconds up and revokes the object URL", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    uploadRecording.mockResolvedValue({ recording_id: "recording-1", state: "transcribing" });
    const createObjectURL = vi.fn().mockReturnValue("blob:synthetic-recording");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

    render(<SpeakerRecognitionTestScreen />);
    const file = selectSyntheticAudio();
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect(uploadRecording).not.toHaveBeenCalled();

    fireLoadedMetadata(12.2);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(1));
    expect(uploadRecording).toHaveBeenCalledWith(file, expect.objectContaining({
      duration_seconds: 13,
      capture_origin: "web_upload",
      video_presence: "absent",
    }));
    const metadata = uploadRecording.mock.calls[0][1];
    expect(metadata).not.toHaveProperty("meet_link");
    expect(metadata).not.toHaveProperty("title");
    expect(createObjectURL).toHaveBeenCalledWith(file);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-recording");
  });

  it("accepts muxed video and declares its video presence truthfully", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    uploadRecording.mockResolvedValue({ recording_id: "recording-video", state: "transcribing" });
    const createObjectURL = vi.fn().mockReturnValue("blob:synthetic-video");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    const input = screen.getByLabelText(/recording/i);
    expect((input as HTMLInputElement).accept).toContain("video/*");
    const file = selectSyntheticVideo();
    expect(document.querySelector("video")).not.toBeNull();
    fireLoadedMetadata(18.1);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(1));
    expect(uploadRecording).toHaveBeenCalledWith(file, expect.objectContaining({
      duration_seconds: 19,
      video_presence: "muxed",
    }));
  });

  it("inspects WebM by container signature when its MIME type is generic and reads bounded metadata slices", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    uploadRecording.mockResolvedValue({ recording_id: "recording-generic-webm", state: "transcribing" });
    const file = new File([createSyntheticWebm(2)], "renamed.bin", { type: "application/octet-stream" });
    Object.defineProperty(file, "size", { configurable: true, value: 400 * 1024 * 1024 });
    const slice = vi.spyOn(file, "slice");
    const wholeFileReader = vi.spyOn(FileReader.prototype, "readAsArrayBuffer");
    const createObjectURL = vi.fn().mockReturnValue("blob:generic-webm");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
    fireLoadedMetadata(8);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(1));
    expect(uploadRecording).toHaveBeenCalledWith(file, expect.objectContaining({ video_presence: "absent" }));
    expect(slice).toHaveBeenCalled();
    expect(wholeFileReader).toHaveBeenCalled();
    expect(wholeFileReader.mock.calls.every(([blob]) => blob.size <= 64 * 1024)).toBe(true);
  });

  it("rejects WebM with excessive pre-track elements after a bounded number of reads", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    const voidElementCount = 1_000;
    const trackElement = createSyntheticWebm(2).slice(10);
    const segmentContent = new Uint8Array(voidElementCount * 2 + trackElement.length);
    for (let index = 0; index < voidElementCount; index += 1) {
      segmentContent.set([0xec, 0x80], index * 2);
    }
    segmentContent.set(trackElement, voidElementCount * 2);
    const webm = new Uint8Array(10 + segmentContent.length);
    webm.set([0x1a, 0x45, 0xdf, 0xa3, 0x80, 0x18, 0x53, 0x80, 0x67, 0xff]);
    webm.set(segmentContent, 10);
    const file = new File([webm], "many-elements.webm", { type: "application/octet-stream" });
    const readRange = vi.spyOn(FileReader.prototype, "readAsArrayBuffer");
    const createObjectURL = vi.fn().mockReturnValue("blob:many-elements");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
    fireLoadedMetadata(8);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/verify|valid|webm/i);
    expect(uploadRecording).not.toHaveBeenCalled();
    expect(readRange.mock.calls.length).toBeLessThan(300);
  });

  it("refuses WebM metadata beyond the bounded inspection budget", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    const largeHeaderSize = 4 * 1024 * 1024;
    const tracks = createSyntheticWebm(2).slice(10);
    const bytes = new Uint8Array(16 + largeHeaderSize + tracks.length);
    bytes.set([0x1a, 0x45, 0xdf, 0xa3, 0x10, 0x40, 0x00, 0x00], 0);
    bytes.set([0x18, 0x53, 0x80, 0x67, 0x10, 0x40, 0x00, 0x00], 8 + largeHeaderSize);
    bytes.set(tracks, 16 + largeHeaderSize);
    const file = new File([bytes], "large-metadata.webm", { type: "application/octet-stream" });
    const createObjectURL = vi.fn().mockReturnValue("blob:large-metadata");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
    fireLoadedMetadata(8);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/verify|valid|webm/i);
    expect(uploadRecording).not.toHaveBeenCalled();
  });

  it("rejects empty or unrecognized media instead of asserting video is absent", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    const file = new File([], "empty.bin", { type: "application/octet-stream" });
    const createObjectURL = vi.fn().mockReturnValue("blob:empty-media");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
    fireLoadedMetadata(1);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/verify|valid|media/i);
    expect(uploadRecording).not.toHaveBeenCalled();
  });

  it("rejects a video track mislabeled as audio before upload with an actionable error", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    const file = new File([createSyntheticWebm(1)], "video-only.webm", { type: "audio/webm" });
    const createObjectURL = vi.fn().mockReturnValue("blob:synthetic-video-mismatch");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    fireEvent.change(screen.getByLabelText(/recording/i), { target: { files: [file] } });
    fireLoadedMetadata(8);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/video track.*file type.*audio/i);
    expect(uploadRecording).not.toHaveBeenCalled();
  });

  it("reuses meeting and idempotency identifiers when retrying the same upload", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    uploadRecording.mockRejectedValueOnce(new Error("synthetic network failure"));
    uploadRecording.mockResolvedValueOnce({ recording_id: "recording-1", state: "transcribing" });
    const createObjectURL = vi.fn().mockReturnValue("blob:synthetic-recording");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    const file = selectSyntheticAudio();
    fireLoadedMetadata(12);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));
    await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole("button", { name: /retry/i }));
    await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(2));

    const first = uploadRecording.mock.calls[0];
    const retry = uploadRecording.mock.calls[1];
    expect(first[0]).toBe(file);
    expect(retry[0]).toBe(file);
    expect(retry[1].meeting_id).toBe(first[1].meeting_id);
    expect(retry[1].idempotency_key).toBe(first[1].idempotency_key);
  });

  it("does not fabricate a duration or submit when browser metadata is unavailable", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    const createObjectURL = vi.fn().mockReturnValue("blob:synthetic-recording");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    selectSyntheticAudio();
    fireLoadedMetadata(Number.NaN);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect(uploadRecording).not.toHaveBeenCalled();
  });
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
    {
      id: "segment-test-2",
      startMs: 3750,
      endMs: 4750,
      text: "La firma sigue pendiente.",
      speakerLabel: "Speaker 7",
      sequence: 2,
    },
  ],
  turns: [],
};

const review = {
  reviewId: "review-test-1",
  revisionId: "revision-test-1",
  status: "pending",
  items: [
    {
      speakerId: "speaker-test-8",
      currentLabel: "Speaker 8",
      attributionState: "uncertain" as const,
      disposition: null,
      excerptRef: "excerpt-test-8",
      expectedVersion: 1,
    },
  ],
};

const apiMocks = api as unknown as {
  getMeeting: (meetingId: string) => Promise<{ id: string; processState: string }>;
  getTranscript: (meetingId: string) => Promise<typeof transcript>;
  getSpeakerReview: (meetingId: string) => Promise<typeof review>;
};

async function uploadSyntheticRecording(assertUploadControls?: () => void) {
  const uploadRecording = vi.mocked(api.uploadRecording);
  uploadRecording.mockResolvedValue({ recording_id: "recording-test-1", state: "transcribing" });
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn().mockReturnValue("blob:synthetic-t3-recording"),
    revokeObjectURL: vi.fn(),
  });

  render(<SpeakerRecognitionTestScreen />);
  selectSyntheticAudio();
  assertUploadControls?.();
  fireLoadedMetadata(12);
  fireEvent.click(screen.getByRole("button", { name: /upload/i }));
  await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(1));
  return uploadRecording.mock.calls[0][1].meeting_id;
}

describe("SpeakerRecognitionTestScreen processing and transcript inspection", () => {
  it("shows persisted processing state before loading transcript or speaker review", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("processing"));
    const getTranscript = vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    const getSpeakerReview = vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    const meetingId = await uploadSyntheticRecording();

    expect(await screen.findByText(/processing/i)).toBeVisible();
    expect(vi.mocked(apiMocks.getMeeting)).toHaveBeenCalledWith(meetingId);
    expect(getTranscript).not.toHaveBeenCalled();
    expect(getSpeakerReview).not.toHaveBeenCalled();
    expect(screen.queryByText("La propuesta queda para el viernes.")).not.toBeInTheDocument();
  });

  it("loads transcript and persisted speaker review after processing completes", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    const getTranscript = vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    const getSpeakerReview = vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    const meetingId = await uploadSyntheticRecording();

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(getTranscript).toHaveBeenCalledWith(meetingId);
    expect(getSpeakerReview).toHaveBeenCalledWith(meetingId);
    expect(await screen.findByText(/pending/i)).toBeVisible();
  });

  it("preserves segment timestamp, exact text and unresolved backend speaker label as read-only content", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording();

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.getByText("00:01")).toBeVisible();
    expect(screen.getByText("Speaker 2")).toBeVisible();
    expect(screen.getByText("La firma sigue pendiente.")).toBeVisible();
    expect(screen.getByText("00:03")).toBeVisible();
    expect(screen.getByText("Speaker 7")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: /transcript|segment/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit transcript/i })).not.toBeInTheDocument();
  });

  it("renders a persisted speaker-review item with its current backend label", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording();

    expect(await screen.findByRole("heading", { name: "Speaker 8" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(/review pending/i);
    expect(screen.getByRole("button", { name: "Play excerpt for Speaker 8" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Confirm Speaker 8" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Name for Speaker 8" })).toBeVisible();
  });

  it("limits the screen to upload, processing, transcript inspection and speaker review", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording(() => {
      expect(screen.getByLabelText(/^recording$/i)).toBeVisible();
      expect(screen.getByRole("button", { name: /upload/i })).toBeVisible();
    });

    expect(await screen.findByText(/processing/i)).toBeVisible();
    expect(screen.getByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.getByText(/transcript/i)).toBeVisible();
    expect(screen.getByText(/speaker review/i)).toBeVisible();
    expect(screen.queryByText(/library|analytics|settings|meeting management/i)).not.toBeInTheDocument();
  });
});
