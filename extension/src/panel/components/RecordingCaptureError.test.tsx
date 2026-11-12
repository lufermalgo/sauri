import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { createCompletion, getCapturingCompletion, settleCapture } from "../../recording-db";
import { RecordingCaptureError } from "./RecordingCaptureError";

async function record(sessionId: string) {
  await createCompletion({ sessionId, meetingId: `meeting-${sessionId}`, capturedTabId: 41, provider: "meet", status: "capturing", updatedAt: 1 });
}

beforeEach(() => { vi.stubGlobal("indexedDB", new IDBFactory()); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("durable capture error feedback", () => {
  it("shows the real ambiguous-handle error and restores it on panel reopen", async () => {
    await record("capture-a");
    await record("capture-b");
    await expect(getCapturingCompletion(41)).rejects.toThrow("Ambiguous");
    const panel = render(<RecordingCaptureError sessionId="capture-a" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Recording could not be finalized");
    expect(screen.getByRole("alert")).toHaveTextContent("Saving has not been confirmed");
    expect(screen.getByRole("alert")).toHaveTextContent("capture-a");
    panel.unmount();
    render(<RecordingCaptureError sessionId="capture-a" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("capture-a");
  });

  it("does not show a previous recording's error for another session", async () => {
    await record("failed");
    await settleCapture("failed", true);
    await record("valid");
    const panel = render(<RecordingCaptureError sessionId="failed" />);
    await screen.findByRole("alert");
    panel.rerender(<RecordingCaptureError sessionId="valid" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    panel.rerender(<RecordingCaptureError />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("refreshes errors committed while the panel stays open", async () => {
    await record("live");
    render(<RecordingCaptureError sessionId="live" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(async () => { await settleCapture("live", true); });
    expect(await screen.findByRole("alert", {}, { timeout: 2500 })).toHaveTextContent("live");
  });

  it("reports unavailable persistence rather than a successful save", async () => {
    vi.stubGlobal("indexedDB", { open: () => { throw new Error("unavailable"); } });
    render(<RecordingCaptureError sessionId="unavailable" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Recording status unavailable");
    expect(screen.getByRole("alert")).toHaveTextContent("Saving has not been confirmed");
  });
});
