// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { SpeakerRecognitionTestScreen } from "./SpeakerRecognitionTestScreen";
import * as api from "../api";

vi.mock("../api", () => ({
  uploadRecording: vi.fn(),
  getMeeting: vi.fn(),
  getTranscript: vi.fn(),
  getSpeakerReview: vi.fn(),
  getDiarization: vi.fn(),
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
  fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
  return file;
}

function selectSyntheticVideo() {
  const file = new File(["synthetic video"], "sample.mp4", { type: "video/mp4" });
  fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
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
    const input = screen.getByLabelText(/^recording$/i);
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
    fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
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
    fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
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
    fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
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
    fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
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
    fireEvent.change(screen.getByLabelText(/^recording$/i), { target: { files: [file] } });
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

  it("does not expose diagnostic copying for a selected recording", () => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn().mockReturnValue("blob:synthetic-recording"),
      revokeObjectURL: vi.fn(),
    });
    render(<SpeakerRecognitionTestScreen />);
    selectSyntheticAudio();

    expect(screen.queryByRole("button", { name: /copy diagnostic/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^upload$/i })).toBeVisible();
  });

  it("shows why upload is blocked when duration is unavailable", async () => {
    const uploadRecording = vi.mocked(api.uploadRecording);
    const createObjectURL = vi.fn().mockReturnValue("blob:synthetic-recording");
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    render(<SpeakerRecognitionTestScreen />);
    selectSyntheticAudio();
    fireLoadedMetadata(Number.NaN);
    fireEvent.click(screen.getByRole("button", { name: /upload/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/duration.*unavailable|metadata.*duration/i);
    expect(uploadRecording).not.toHaveBeenCalled();
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
      sequence: 1,
    },
    {
      id: "segment-test-2",
      startMs: 3750,
      endMs: 4750,
      text: "La firma sigue pendiente.",
      sequence: 2,
    },
  ],
  turns: [],
};

const diarization = {
  speakers: [
    { id: "speaker-test-2", label: "Speaker 2", sequence: 2 },
    { id: "speaker-test-7", label: "Speaker 7", sequence: 7 },
  ],
  assignments: [
    { turn_id: "segment-test-1", speaker_id: "speaker-test-2" },
    { turn_id: "segment-test-2", speaker_id: "speaker-test-7" },
  ],
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
  getDiarization: (meetingId: string) => Promise<api.MeetingDiarization>;
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
  it.each(["success", "failure"])("ignores a late upload %s after another recording is selected", async (outcome) => {
    let resolveUpload!: (value: api.RecordingUploadResult) => void;
    let rejectUpload!: (reason: Error) => void;
    const pendingUpload = new Promise<api.RecordingUploadResult>((resolve, reject) => {
      resolveUpload = resolve;
      rejectUpload = reject;
    });
    const uploadRecording = vi.mocked(api.uploadRecording).mockReturnValue(pendingUpload);
    const getMeeting = vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("processing"));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn().mockReturnValue("blob:synthetic"), revokeObjectURL: vi.fn() });
    render(<SpeakerRecognitionTestScreen />);
    selectSyntheticAudio();
    fireLoadedMetadata(12);
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));
    await waitFor(() => expect(uploadRecording).toHaveBeenCalledTimes(1));
    selectSyntheticVideo();
    fireLoadedMetadata(24);
    await act(async () => {
      if (outcome === "success") resolveUpload({ recording_id: "recording-a", state: "transcribing" });
      else rejectUpload(new Error("Late failure for recording A"));
      await pendingUpload.catch(() => undefined);
    });
    expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(getMeeting).not.toHaveBeenCalled();
  });

  it("stops observing a terminal unreconstructible generation and retains its transcript", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    const getDiarization = vi.spyOn(apiMocks, "getDiarization").mockResolvedValue({
      speakers: [], assignments: [], diarization_state: "not_reconstructible",
    });
    const getSpeakerReview = vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);
    await uploadSyntheticRecording();
    expect(await screen.findByRole("alert")).toHaveTextContent("Speaker separation is unavailable for this recording");
    expect(screen.getByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.queryByText("Separating speakers…")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open playback and speaker paragraphs" })).not.toBeInTheDocument();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2100)); });
    expect(getDiarization).toHaveBeenCalledTimes(1);
    expect(getSpeakerReview).not.toHaveBeenCalled();
  });
  it("shows persisted processing state before loading transcript or speaker review", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("processing"));
    const getTranscript = vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue(diarization);
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
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue(diarization);
    const getSpeakerReview = vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    const meetingId = await uploadSyntheticRecording();

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(getTranscript).toHaveBeenCalledWith(meetingId);
    expect(screen.getByRole("link", { name: "Open playback and speaker paragraphs" }))
      .toHaveAttribute("href", `?meetingId=${meetingId}`);
    expect(document.querySelector("audio, video")).toHaveAttribute("hidden");
    expect(getSpeakerReview).toHaveBeenCalledWith(meetingId);
    expect(await screen.findByText(/pending/i)).toBeVisible();
  });

  it("keeps observing speakers after ASR completes and opens playback only once they arrive", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    const getDiarization = vi.spyOn(apiMocks, "getDiarization")
      .mockRejectedValueOnce(new Error("Error 404"))
      .mockResolvedValue(diarization);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording();
    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Separating speakers");
    expect(screen.queryByRole("link", { name: "Open playback and speaker paragraphs" })).not.toBeInTheDocument();

    expect(await screen.findByRole("link", { name: "Open playback and speaker paragraphs" }, { timeout: 4000 })).toBeVisible();
    expect(getDiarization).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Separating speakers…")).not.toBeInTheDocument();
  });

  it("does not mistake a successful HTTP response for completed speaker separation", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization")
      .mockResolvedValueOnce({ speakers: [], assignments: [], diarization_state: "processing" })
      .mockResolvedValue({ ...diarization, diarization_state: "completed" });
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);
    await uploadSyntheticRecording();
    expect(await screen.findByText("Separating speakers…")).toBeVisible();
    expect(await screen.findByRole("link", { name: "Open playback and speaker paragraphs" }, { timeout: 4000 })).toBeVisible();
  });

  it("observes latest_attempt when there is no completed generation yet", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization")
      .mockResolvedValueOnce({ speakers: [], assignments: [], diarization_state: null,
        latest_attempt: { processing_revision: 1, diarization_state: "processing", failure_cause: null } })
      .mockResolvedValue({ ...diarization, diarization_state: "completed" });
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);
    await uploadSyntheticRecording();
    expect(await screen.findByText("Separating speakers…")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open playback and speaker paragraphs" })).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Open playback and speaker paragraphs" }, { timeout: 4000 })).toBeVisible();
  });

  it("reports failed separation without hiding the completed transcript or offering ready playback", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue({ speakers: [], assignments: [], diarization_state: "failed" });
    await uploadSyntheticRecording();
    expect(await screen.findByRole("alert")).toHaveTextContent("Speaker separation failed");
    expect(screen.getByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open playback and speaker paragraphs" })).not.toBeInTheDocument();
  });

  it("keeps the completed transcript visible while speaker review is not yet available", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue(diarization);
    vi.spyOn(apiMocks, "getSpeakerReview").mockRejectedValue(new Error("Error 404"));

    await uploadSyntheticRecording();

    const firstTurn = await screen.findByText("La propuesta queda para el viernes.");
    const firstTurnRow = firstTurn.closest("li");
    expect(firstTurnRow).not.toBeNull();
    expect(within(firstTurnRow as HTMLElement).getByText("Speaker 2")).toBeVisible();
    expect(screen.queryByText(/processing: completed/i)).not.toBeInTheDocument();
  });

  it("preserves each segment's timestamp, exact text and unresolved backend speaker label as read-only content", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue(diarization);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording();

    const firstTurn = await screen.findByText("La propuesta queda para el viernes.");
    const firstTurnRow = firstTurn.closest("li");
    expect(firstTurnRow).not.toBeNull();
    expect(within(firstTurnRow as HTMLElement).getByText("00:01")).toBeVisible();
    expect(within(firstTurnRow as HTMLElement).getByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(within(firstTurnRow as HTMLElement).getByText("Speaker 2")).toBeVisible();

    const secondTurn = screen.getByText("La firma sigue pendiente.");
    const secondTurnRow = secondTurn.closest("li");
    expect(secondTurnRow).not.toBeNull();
    expect(secondTurnRow).not.toBe(firstTurnRow);
    expect(within(secondTurnRow as HTMLElement).getByText("00:03")).toBeVisible();
    expect(within(secondTurnRow as HTMLElement).getByText("La firma sigue pendiente.")).toBeVisible();
    expect(within(secondTurnRow as HTMLElement).getByText("Speaker 7")).toBeVisible();

    expect(screen.queryByRole("textbox", { name: /transcript|segment/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit transcript/i })).not.toBeInTheDocument();
  });

  it("renders a persisted speaker-review item with its current backend label and pending state", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue(diarization);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording();

    expect(await screen.findByText("Speaker 8")).toBeVisible();
    expect(screen.getByText(/review pending/i)).toBeVisible();
  });

  it("limits the completed screen to upload, transcript inspection and speaker review", async () => {
    vi.spyOn(apiMocks, "getMeeting").mockResolvedValue(meeting("completed"));
    vi.spyOn(apiMocks, "getTranscript").mockResolvedValue(transcript);
    vi.spyOn(apiMocks, "getDiarization").mockResolvedValue(diarization);
    vi.spyOn(apiMocks, "getSpeakerReview").mockResolvedValue(review);

    await uploadSyntheticRecording(() => {
      expect(screen.getByLabelText(/^recording$/i)).toBeVisible();
      expect(screen.getByRole("button", { name: /upload/i })).toBeVisible();
    });

    expect(await screen.findByText("La propuesta queda para el viernes.")).toBeVisible();
    expect(screen.getByText(/transcript/i)).toBeVisible();
    expect(screen.getByText(/speaker review/i)).toBeVisible();
    expect(screen.queryByText(/library|analytics|settings|meeting management/i)).not.toBeInTheDocument();
  });
});
