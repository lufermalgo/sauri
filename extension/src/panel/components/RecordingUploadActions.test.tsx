import { Blob as NativeBlob } from "node:buffer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { createCompletion, getChunksBySession, getCompletion, storeChunk, type RecordingCompletion } from "../../recording-db";
import { RecordingCompletionStatus } from "./RecordingCompletionStatus";
import { panelCopy as copy } from "../copy";

const failed: RecordingCompletion = { sessionId: "session-copy", meetingId: "meeting-copy", provider: "meet", capturedTabId: 7, status: "upload_failed", updatedAt: 1 };
const createObjectURL = vi.fn(() => "blob:synthetic-copy");
const revokeObjectURL = vi.fn();
beforeEach(async () => {
  // Native Blob survives the structured clone used by fake-indexeddb.
  vi.stubGlobal("Blob", NativeBlob);
  vi.stubGlobal("indexedDB", new IDBFactory());
  vi.stubGlobal("chrome", { runtime: { sendMessage: vi.fn(async () => ({ ok: true })) } });
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  });
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  await createCompletion(failed);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("recording upload actions", () => {
  it("renders indeterminate upload without byte counts or a fabricated percentage", async () => {
    const record = { ...failed, sessionId: "upload-live", meetingId: "upload-meeting", status: "uploading" as const };
    await createCompletion(record);
    render(<RecordingCompletionStatus sessionId={record.sessionId} />);
    const progress = await screen.findByRole("progressbar");
    expect(progress).not.toHaveAttribute("aria-valuenow");
    expect(screen.getByText(copy.uploading)).toBeInTheDocument();
    expect(screen.queryByText(/\d+\s*(MB|KB)/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: copy.download })).not.toBeInTheDocument();
  });
  it("requests a retry for exactly the durable session without assuming success", async () => {
    render(<RecordingCompletionStatus sessionId={failed.sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: copy.retry }));
    await waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: "retry-upload", sessionId: failed.sessionId }));
    expect(await getCompletion(failed.sessionId)).toMatchObject({ status: "upload_failed" });
    expect(screen.queryByText(copy.saved)).not.toBeInTheDocument();
  });
  it("reports an unavailable retry handler instead of inventing a successful retry", async () => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false, error: "unknown message type" });
    render(<RecordingCompletionStatus sessionId={failed.sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: copy.retry }));
    expect(await screen.findByText(copy.retryError)).toBeInTheDocument();
    expect(screen.queryByText("unknown message type")).not.toBeInTheDocument();
    expect((await getCompletion(failed.sessionId))?.status).toBe("upload_failed");
  });
  it("downloads the existing chunks as a WebM copy and never clears the recording", async () => {
    await storeChunk(failed.sessionId, new Blob(["existing media"], { type: "audio/webm" }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("sauri-session-copy.webm");
      expect(this.href).toBe("blob:synthetic-copy");
    });
    render(<RecordingCompletionStatus sessionId={failed.sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: copy.download }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(createObjectURL).toHaveBeenCalledWith(expect.objectContaining({ size: 14, type: "audio/webm" }));
    expect((await getChunksBySession(failed.sessionId))).toHaveLength(1);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });
  it("reports missing local media without producing an empty download", async () => {
    render(<RecordingCompletionStatus sessionId={failed.sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: copy.download }));
    expect(await screen.findByText(copy.downloadError)).toBeInTheDocument();
    expect(createObjectURL).not.toHaveBeenCalled();
  });
});
