// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SpeakerRecognitionTestScreen } from "./SpeakerRecognitionTestScreen";
import * as api from "../api";

vi.mock("../api", () => ({ uploadRecording: vi.fn() }));

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
