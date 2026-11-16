// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { UploadView } from "./UploadView";
import { App } from "../App";
import * as api from "../api";
import { t } from "../i18n";
import { fileSizeText, transferredText } from "../upload-format";

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
  fireEvent.change(screen.getByLabelText(t("upload:fileLabel")), { target: { files: [file] } });
  const media = document.querySelector("video")!;
  Object.defineProperty(media, "duration", { configurable: true, value: duration });
  Object.defineProperty(media, "videoWidth", { configurable: true, value: videoWidth });
  fireEvent.loadedMetadata(media);
  return file;
}

describe("UploadView", () => {
  it("requires finite recording metadata and uses actual video tracks rather than the file MIME", async () => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" });
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    expect(screen.queryByRole("button", { name: t("upload:submit") })).not.toBeInTheDocument();
    const file = selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));

    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    expect(upload).toHaveBeenCalledWith(file, expect.objectContaining({
      duration_seconds: 13,
      capture_origin: "web_upload",
      video_presence: "absent",
    }), expect.any(Function));
    expect(upload.mock.calls[0][1]).toHaveProperty("title", "sample.webm");
    expect(upload.mock.calls[0][1]).not.toHaveProperty("meet_link");
  });

  it("declares muxed video when browser metadata reports a video track", async () => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" });
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording(18, 1280);
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    await waitFor(() => expect(upload).toHaveBeenCalledWith(expect.any(File), expect.objectContaining({
      duration_seconds: 18, video_presence: "muxed",
    }), expect.any(Function)));
  });

  it.each([Infinity, NaN, 0])("blocks upload for invalid duration %s", (duration) => {
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording(duration);
    expect(screen.getByRole("alert")).toHaveTextContent(t("upload:errors.invalidDuration"));
    expect(screen.getByRole("button", { name: t("upload:submit") })).toBeDisabled();
    expect(api.uploadWithProgress).not.toHaveBeenCalled();
  });

  it("shows real byte progress and waits for server confirmation even at 100%", async () => {
    const onUploaded = vi.fn();
    let confirm!: (result: api.RecordingUploadResult) => void;
    vi.mocked(api.uploadWithProgress).mockImplementation(() => new Promise((resolve) => { confirm = resolve; }));
    render(<UploadView onUploaded={onUploaded} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    const report = vi.mocked(api.uploadWithProgress).mock.calls[0][2];
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
    act(() => report({ loaded: 250, total: 1000 }));
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "25");
    expect(screen.getByText(transferredText(250, 1000, 25))).toBeVisible();
    expect(screen.getByText(t("upload:transferHeading"))).toBeVisible();
    expect(screen.getByText(t("upload:transferHelp"))).toBeVisible();
    expect(screen.getByLabelText(t("upload:fileLabel"))).toBeDisabled();
    expect(screen.getByRole("button", { name: new RegExp(t("upload:back")) })).toBeDisabled();
    act(() => report({ loaded: 1000, total: 1000 }));
    expect(screen.getByText(t("upload:awaitingConfirmation"))).toBeVisible();
    expect(onUploaded).not.toHaveBeenCalled();
    await act(async () => confirm({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" }));
    expect(onUploaded).toHaveBeenCalledWith("meeting-1");
  });

  it.each([
    { kind: "network", message: t("upload:errors.network") },
    { kind: "HTTP", message: t("upload:errors.http", { status: 500 }) },
  ])("retains the same file and identifiers after $kind failure", async ({ message }) => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockRejectedValueOnce(new Error(message)).mockResolvedValueOnce({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" });
    const onUploaded = vi.fn();
    render(<UploadView onUploaded={onUploaded} onBack={vi.fn()} />);
    const file = selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(onUploaded).not.toHaveBeenCalled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText(file.name)).toBeVisible();
    const data = upload.mock.calls[0][1];
    fireEvent.click(screen.getByRole("button", { name: t("upload:retry") }));
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("meeting-1"));
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
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    unmount();
    await act(async () => confirm({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" }));
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("opens the uploaded meeting from the list through App's existing view switch", async () => {
    vi.stubGlobal("localStorage", { getItem: (key: string) => (key === "sauri_token" ? "synthetic-token" : null) });
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ meeting_id: "server-meeting-id", recording_id: "recording-not-meeting", state: "transcribing" });
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: t("shell:upload") })[0]);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    expect(upload.mock.calls[0][1].meeting_id).not.toBe("server-meeting-id");
    expect(await screen.findByRole("heading", { name: "Meeting server-meeting-id" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: t("upload:heading") })).not.toBeInTheDocument();
    expect(window.location.pathname).toBe("/meetings/server-meeting-id");
    window.history.replaceState({}, "", "/");
  });

  it("navigates with the server-confirmed meeting id even when it differs from the generated one", async () => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockResolvedValue({ meeting_id: "server-meeting-id", recording_id: "recording-1", state: "transcribing" });
    const onUploaded = vi.fn();
    render(<UploadView onUploaded={onUploaded} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith("server-meeting-id"));
    expect(upload.mock.calls[0][1].meeting_id).not.toBe("server-meeting-id");
  });

  it("reuses the same meeting id and idempotency key on retry and sends the file name as title", async () => {
    const upload = vi.mocked(api.uploadWithProgress);
    upload.mockRejectedValueOnce(new Error(t("upload:errors.network")))
      .mockResolvedValueOnce({ meeting_id: "meeting-1", recording_id: "recording-1", state: "transcribing" });
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    const file = selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: t("upload:retry") }));
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
    const [first, second] = upload.mock.calls.map(([, data]) => data);
    expect(second.meeting_id).toBe(first.meeting_id);
    expect(second.idempotency_key).toBe(first.idempotency_key);
    expect(first.title).toBe(file.name);
  });

  it("does not show a percentage when the total is unknown", () => {
    vi.mocked(api.uploadWithProgress).mockImplementation(() => new Promise(() => {}));
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    const report = vi.mocked(api.uploadWithProgress).mock.calls[0][2];
    act(() => report({ loaded: 4096, total: null }));
    expect(screen.getByText(t("upload:bytesSent", { bytes: 4096 }))).toBeVisible();
    expect(screen.getByText(t("upload:transferHelp"))).toBeVisible();
    expect(screen.queryByText(/%/, { selector: ".upload-progress-figures" })).not.toBeInTheDocument();
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
  });

  it("shows the server error as is with a retry button", async () => {
    vi.mocked(api.uploadWithProgress).mockRejectedValue(new Error("Mensaje exacto del servidor"));
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Mensaje exacto del servidor");
    expect(screen.getByRole("button", { name: t("upload:retry") })).toBeEnabled();
  });

  it("shows file name and size in MB and lets the user remove the file", () => {
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    const file = new File([new Uint8Array(3 * 1048576)], "big.webm", { type: "video/webm" });
    fireEvent.change(screen.getByLabelText(t("upload:fileLabel")), { target: { files: [file] } });
    expect(screen.getByText("big.webm")).toBeVisible();
    expect(screen.getByText(fileSizeText(file.size))).toBeVisible();
    expect(fileSizeText(file.size)).toMatch(/^3,0 MB$/);
    fireEvent.click(screen.getByRole("button", { name: t("upload:remove") }));
    expect(screen.queryByText("big.webm")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("upload:submit") })).not.toBeInTheDocument();
  });

  it("formats transfer figures in MB with the percentage only when the total is known", async () => {
    vi.mocked(api.uploadWithProgress).mockImplementation(() => new Promise(() => {}));
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    const report = vi.mocked(api.uploadWithProgress).mock.calls[0][2];
    act(() => report({ loaded: 312 * 1048576, total: 473 * 1048576 }));
    const figures = screen.getByText(transferredText(312 * 1048576, 473 * 1048576, 65));
    expect(figures).toBeVisible();
    expect(figures.textContent).toMatch(/^312 MB .* 473 MB .* 65 %$/);
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "65");
  });

  it("shows the duration next to the size only once the metadata is known", () => {
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    const file = new File(["synthetic recording"], "sample.webm", { type: "video/webm" });
    fireEvent.change(screen.getByLabelText(t("upload:fileLabel")), { target: { files: [file] } });
    expect(screen.queryByText(/\d\d:\d\d/)).not.toBeInTheDocument();
    const media = document.querySelector("video")!;
    Object.defineProperty(media, "duration", { configurable: true, value: 3260 });
    Object.defineProperty(media, "videoWidth", { configurable: true, value: 0 });
    fireEvent.loadedMetadata(media);
    expect(screen.getByText(/54:20/)).toBeVisible();
    expect(screen.getByText(fileSizeText(file.size))).toBeVisible();
  });

  it("selects a dropped file through the same path as the file input", () => {
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    const file = new File(["synthetic recording"], "dropped.webm", { type: "video/webm" });
    fireEvent.drop(screen.getByTestId("upload-dropzone"), { dataTransfer: { files: [file] } });
    expect(screen.getByText("dropped.webm")).toBeVisible();
    expect(document.querySelector("video")).toHaveAttribute("src", "blob:synthetic-recording");
  });

  it("ignores drops while an upload is in progress", () => {
    vi.mocked(api.uploadWithProgress).mockImplementation(() => new Promise(() => {}));
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    selectRecording();
    fireEvent.click(screen.getByRole("button", { name: t("upload:submit") }));
    const other = new File(["other"], "other.webm", { type: "video/webm" });
    fireEvent.drop(screen.getByTestId("upload-dropzone"), { dataTransfer: { files: [other] } });
    expect(screen.queryByText("other.webm")).not.toBeInTheDocument();
    expect(screen.getByText("sample.webm")).toBeVisible();
  });

  it("does not offer diagnostics copy nor format or size limits", () => {
    render(<UploadView onUploaded={vi.fn()} onBack={vi.fn()} />);
    expect(screen.queryByText(/diagn.stico/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/formatos|tama.o m.ximo|GB/i)).not.toBeInTheDocument();
  });
});
