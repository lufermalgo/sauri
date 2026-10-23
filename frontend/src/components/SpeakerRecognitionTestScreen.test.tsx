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

function selectSyntheticAudio() {
  const file = new File(["synthetic audio"], "sample.webm", { type: "audio/webm" });
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
