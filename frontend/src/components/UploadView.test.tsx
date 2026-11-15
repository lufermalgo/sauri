// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { UploadView } from "./UploadView";
import { App } from "../App";
import * as api from "../api";
import { copy } from "../copy/es";

vi.mock("../api", async (importOriginal) => ({
  ...await importOriginal<typeof api>(),
  uploadWithProgress: vi.fn(),
  listMeetings: vi.fn(),
}));

vi.mock("./TranscriptView", () => ({
  TranscriptView: ({ meetingId }: { meetingId: string }) => <h2>Meeting {meetingId}</h2>,
}));

beforeEach(() => {
  vi.mocked(api.listMeetings).mockResolvedValue([]);
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn().mockReturnValue("blob:synthetic-recording"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

function selectRecording(duration = 12.2, videoWidth = 0) {
  const file = new File(["synthetic recording"], "sample.webm", { type: "video/webm" });
  fireEvent.change(screen.getByLabelText(copy.upload.fileLabel), { target: { files: [file] } });
  const media = document.querySelector("video")!;
  Object.defineProperty(media, "duration", { configurable: true, value: duration });
  Object.defineProperty(media, "videoWidth", { configurable: true, value: videoWidth });
  fireEvent.loadedMetadata(media);
  return file;
}

describe("UploadView", () => {
  it("requires finite recording metadata and uses actual video tracks rather than the file MIME", async () => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ recording_id: "recording-1", state: "transcribing" });
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByRole("button", { name: copy.upload.submit })).toBeDisabled();
    const file = selectRecording();
    fireEvent.click(screen.getByRole("button", { name: copy.upload.submit }));

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith(file, expect.objectContaining({
      duration_seconds: 13,
      capture_origin: "web_upload",
      video_presence: "absent",
    }), expect.any(Function));
    expect(upload.mock.calls[0][1]).not.toHaveProperty("title");
    expect(upload.mock.calls[0][1]).not.toHaveProperty("meet_link");
  });

  it("declares muxed video when browser metadata reports a video track", async () => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ recording_id: "recording-1", state: "transcribing" });
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording(18, 1280);
    fireEvent.click(screen.getByRole("button", { name: copy.upload.submit }));
    await waitFor(() => expect(upload).toHaveBeenCalledWith(expect.any(File), expect.objectContaining({
      duration_seconds: 18, video_presence: "muxed",
    }), expect.any(Function)));
  });

  it.each([Infinity, NaN, 0])("blocks upload for invalid duration %s", (duration) => {
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording(duration);
    expect(screen.getByRole("alert")).toHaveTextContent(copy.upload.errors.invalidDuration);
    expect(screen.getByRole("button", { name: copy.upload.submit })).toBeDisabled();
    expect(api.uploadWithProgress).not.toHaveBeenCalled();
  });

  it("shows real byte progress and waits for server confirmation even at 100%", async () => {
    const onUploaded = vi.fn();
    let confirm!: (result: api.RecordingUploadResult) => void;
    vi.mocked(api.uploadWithProgress).mockImplementation(() => new Promise((resolve) => { confirm = resolve; }));
    render(<UploadView onUploaded={onUploaded} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: copy.upload.submit }));
    const report = vi.mocked(api.uploadWithProgress).mock.calls[0][2];
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
    act(() => report({ loaded: 250, total: 1000 }));
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "25");
    expect(screen.getByText(copy.upload.percentUploaded(25))).toBeVisible();
    expect(screen.getByLabelText(copy.upload.fileLabel)).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.upload.back })).toBeDisabled();
    act(() => report({ loaded: 1000, total: 1000 }));
    expect(screen.getByText(copy.upload.awaitingConfirmation)).toBeVisible();
    expect(onUploaded).not.toHaveBeenCalled();
    await act(async () => confirm({ recording_id: "recording-1", state: "transcribing" }));
    expect(onUploaded).toHaveBeenCalledWith(vi.mocked(api.uploadWithProgress).mock.calls[0][1].meeting_id);
  });

  it.each([
    { kind: "network", message: copy.upload.errors.network },
    { kind: "HTTP", message: copy.upload.errors.http(500) },
  ])("retains the same file and identifiers after $kind failure", async ({ message }) => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockRejectedValueOnce(new Error(message)).mockResolvedValueOnce({ recording_id: "recording-1", state: "transcribing" });
    const onUploaded = vi.fn();
    render(<UploadView onUploaded={onUploaded} onBack={vi.fn()} />);
    const file = selectRecording();
    fireEvent.click(screen.getByRole("button", { name: copy.upload.submit }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(onUploaded).not.toHaveBeenCalled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText(file.name)).toBeVisible();
    const data = upload.mock.calls[0][1];
    fireEvent.click(screen.getByRole("button", { name: copy.upload.retry }));
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(data.meeting_id));
    expect(upload.mock.calls.map(([audio, metadata]) => [audio, metadata])).toEqual([[file, data], [file, data]]);
  });

  it("revokes local media URLs on replacement and unmount", () => {
    const { unmount } = render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording();
    vi.mocked(URL.createObjectURL).mockReturnValueOnce("blob:replacement");
    selectRecording();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-recording");
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:replacement");
  });

  it("does not navigate after leaving the view while an upload is pending", async () => {
    let confirm!: (result: api.RecordingUploadResult) => void;
    vi.mocked(api.uploadWithProgress).mockImplementation(() => new Promise((resolve) => { confirm = resolve; }));
    const onUploaded = vi.fn();
    const { unmount } = render(<UploadView onUploaded={onUploaded} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: copy.upload.submit }));
    unmount();
    await act(async () => confirm({ recording_id: "recording-1", state: "transcribing" }));
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("opens the uploaded meeting from the list through App's existing view switch", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "synthetic-token" });
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ recording_id: "recording-not-meeting", state: "transcribing" });
    render(<App />);
    fireEvent.click(screen.getByRole("link", { name: copy.shell.upload }));
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: copy.upload.submit }));
    const meetingId = upload.mock.calls[0][1].meeting_id;
    expect(await screen.findByRole("heading", { name: `Meeting ${meetingId}` })).toBeVisible();
    expect(screen.queryByRole("heading", { name: copy.upload.title })).not.toBeInTheDocument();
    expect(window.location.pathname).toBe(`/meetings/${meetingId}`);
    window.history.replaceState({}, "", "/");
  });
});
