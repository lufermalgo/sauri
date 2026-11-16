import { panelCopy as copy } from "../copy";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import * as db from "../../recording-db";
import { RecordingCompletionStatus } from "./RecordingCompletionStatus";

function record(status: db.RecordingCompletion["status"], extra: Partial<db.RecordingCompletion> = {}): db.RecordingCompletion {
  return { sessionId: "session-current", meetingId: "meeting-current", recordingId: "recording-current", provider: "meet", capturedTabId: 626, updatedAt: 100, status, ...extra };
}
beforeEach(() => { vi.stubGlobal("indexedDB", new IDBFactory()); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("RecordingCompletionStatus — durable outcomes", () => {
  it.each<[db.RecordingCompletion["status"], string, "status" | "alert"]>([
    ["finalizing", copy.saving, "status"],
    ["upload_pending", copy.saving, "status"],
    ["uploading", copy.saving, "status"],
    ["upload_succeeded", copy.saved, "status"],
    ["upload_failed", copy.uploadFailed, "alert"],
    ["upload_outcome_unavailable", copy.uploadUnknown, "alert"],
    ["processing", copy.saved, "status"],
    ["processing_assets_unavailable", copy.processingUnavailable, "alert"],
    ["processing_status_unavailable", copy.processingUnavailable, "alert"],
    ["processing_failed", copy.processingFailed, "alert"],
    ["processing_succeeded", copy.reviewReady, "status"],
    ["review_launch_pending", copy.reviewPending, "status"],
    ["review_opened", copy.reviewOpened, "status"],
  ])("shows %s from the selected durable record", async (status, title, role) => {
    await db.createCompletion(record(status));
    render(<RecordingCompletionStatus sessionId="session-current" />);
    const region = await screen.findByRole(role);
    expect(region).toHaveTextContent(title);
    expect(region).toHaveTextContent("session-current");
    expect(region).toHaveTextContent("meeting-current");
    expect([...screen.queryAllByRole("status"), ...screen.queryAllByRole("alert")]).toHaveLength(1);
  });

  it("capture error overrides even a stale successful outcome", async () => {
    await db.createCompletion(record("processing_succeeded", { captureError: true }));
    render(<RecordingCompletionStatus sessionId="session-current" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.captureErrorHelp);
    expect(screen.queryByText(copy.reviewReady)).not.toBeInTheDocument();
  });

  it("does not fall back to another recording when the selected record is missing", async () => {
    await db.createCompletion(record("review_opened"));
    const read = vi.spyOn(db, "getCompletion");
    render(<RecordingCompletionStatus sessionId="missing-session" />);
    await waitFor(() => expect(read).toHaveBeenCalledWith("missing-session"));
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("recovers the latest record, not an older successful one, without worker state", async () => {
    await db.createCompletion(record("review_opened"));
    await db.createCompletion(record("upload_failed", { sessionId: "session-latest", meetingId: "meeting-latest", recordingId: "recording-latest", updatedAt: 300 }));
    render(<RecordingCompletionStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent("session-latest");
    expect(screen.queryByText(copy.reviewOpened)).not.toBeInTheDocument();
  });

  it("removes a previously successful result if the next durable read fails, then recovers", async () => {
    await db.createCompletion(record("processing_succeeded"));
    const read = vi.spyOn(db, "getCompletion");
    render(<RecordingCompletionStatus sessionId="session-current" />);
    await screen.findByText(copy.reviewReady);
    read.mockRejectedValue(new Error("synthetic storage failure — not user-facing"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(copy.statusUnavailable), { timeout: 2200 });
    expect(screen.queryByText(copy.reviewReady)).not.toBeInTheDocument();
    expect(screen.queryByText(/synthetic storage/)).not.toBeInTheDocument();
    read.mockResolvedValue(record("processing_failed"));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(copy.processingFailed), { timeout: 2200 });
  });

  it("discards a late read for the old selection after switching sessions", async () => {
    let resolveOld!: (record: db.RecordingCompletion) => void;
    vi.spyOn(db, "getCompletion").mockImplementation(id => id === "session-current"
      ? new Promise(resolve => { resolveOld = resolve; })
      : Promise.resolve(record("upload_failed", { sessionId: id, meetingId: "meeting-next" })));
    const view = render(<RecordingCompletionStatus sessionId="session-current" />);
    view.rerender(<RecordingCompletionStatus sessionId="session-next" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("session-next");
    await act(async () => resolveOld(record("review_opened")));
    expect(screen.getByRole("alert")).toHaveTextContent("session-next");
    expect(screen.queryByText(copy.reviewOpened)).not.toBeInTheDocument();
    view.unmount();
  });
});

it("keeps a healthy active capture out of completion feedback", async () => {
  await db.createCompletion(record("capturing"));
  const read = vi.spyOn(db, "getCompletion");
  render(<RecordingCompletionStatus sessionId="session-current" />);
  await waitFor(() => expect(read).toHaveBeenCalled());
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
