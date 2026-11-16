import { panelCopy as copy } from "../../i18n/spanish";
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
    expect(region).not.toHaveTextContent("session-current");
    expect(region).not.toHaveTextContent("meeting-current");
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
    const now = Date.now();
    await db.createCompletion(record("review_opened", { updatedAt: now - 1000 }));
    await db.createCompletion(record("upload_failed", { sessionId: "session-latest", meetingId: "meeting-latest", recordingId: "recording-latest", updatedAt: now }));
    render(<RecordingCompletionStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.uploadFailed);
    expect(document.querySelector("[data-session-id='session-latest']")).not.toBeNull();
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
    expect((await screen.findByRole("alert")).closest("[data-session-id]")).toHaveAttribute("data-session-id", "session-next");
    await act(async () => resolveOld(record("review_opened")));
    expect(screen.getByRole("alert").closest("[data-session-id]")).toHaveAttribute("data-session-id", "session-next");
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

describe("RecordingCompletionStatus — acknowledgement on reopen", () => {
  const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 60)); });

  it("shows an unacknowledged recent failure when the panel opens", async () => {
    await db.createCompletion(record("processing_failed", { updatedAt: Date.now() }));
    render(<RecordingCompletionStatus />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.processingFailed);
  });

  it("persists Volver so the outcome is gone on the next open, without resurrecting an older record", async () => {
    const now = Date.now();
    await db.createCompletion(record("review_opened", { sessionId: "session-old", meetingId: "meeting-old", recordingId: "recording-old", updatedAt: now - 5000 }));
    await db.createCompletion(record("processing_failed", { updatedAt: now }));
    const first = render(<RecordingCompletionStatus />);
    await screen.findByRole("alert");
    await act(async () => { screen.getByRole("button", { name: copy.back }).click(); });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await settle();
    expect((await db.getCompletion("session-current"))?.acknowledgedAt).toBeTypeOf("number");
    first.unmount();
    render(<RecordingCompletionStatus />);
    await settle();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("never hides an in-progress record, even if it carries an acknowledgement", async () => {
    await db.createCompletion(record("uploading", { updatedAt: Date.now(), acknowledgedAt: Date.now() }));
    render(<RecordingCompletionStatus />);
    expect(await screen.findByRole("status")).toHaveTextContent(copy.saving);
  });

  it("does not durably acknowledge an in-progress outcome that can still fail later", async () => {
    await db.createCompletion(record("processing", { updatedAt: Date.now() }));
    render(<RecordingCompletionStatus />);
    await screen.findByRole("status");
    await act(async () => { screen.getByRole("button", { name: copy.back }).click(); });
    await settle();
    expect((await db.getCompletion("session-current"))?.acknowledgedAt).toBeUndefined();
  });

  it("treats a terminal outcome older than seven days as acknowledged", async () => {
    await db.createCompletion(record("processing_failed", { updatedAt: Date.now() - 8 * 24 * 60 * 60 * 1000 }));
    render(<RecordingCompletionStatus />);
    await settle();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("RecordingCompletionStatus — no technical ids, portal link, failure cause", () => {
  it("opens the recording in the portal when it was uploaded and renders no ids", async () => {
    const create = vi.fn().mockResolvedValue({ id: 9 });
    vi.stubGlobal("chrome", { tabs: { create } });
    await db.createCompletion(record("processing_failed", { updatedAt: Date.now() }));
    render(<RecordingCompletionStatus sessionId="session-current" />);
    const region = await screen.findByRole("alert");
    expect(region).not.toHaveTextContent("session-current");
    expect(region).not.toHaveTextContent("meeting-current");
    await act(async () => { screen.getByRole("button", { name: copy.openPortal }).click(); });
    expect(create).toHaveBeenCalledWith({ url: expect.stringContaining("meetingId=meeting-current") });
  });

  it("offers no portal link before the upload was accepted", async () => {
    await db.createCompletion(record("upload_failed", { recordingId: undefined }));
    render(<RecordingCompletionStatus sessionId="session-current" />);
    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: copy.openPortal })).not.toBeInTheDocument();
  });

  it("explains a no-speech failure", async () => {
    await db.createCompletion(record("processing_failed", { failureCause: "no_speech_detected" }));
    render(<RecordingCompletionStatus sessionId="session-current" />);
    const region = await screen.findByRole("alert");
    expect(region).toHaveTextContent(copy.noSpeech);
    expect(region).toHaveTextContent(copy.noSpeechHelp);
    expect(region).not.toHaveTextContent(copy.processingFailed);
  });

  it("keeps the generic failure text with a pointer to the portal for other causes", async () => {
    await db.createCompletion(record("processing_failed", { failureCause: "engine_failed" }));
    render(<RecordingCompletionStatus sessionId="session-current" />);
    const region = await screen.findByRole("alert");
    expect(region).toHaveTextContent(copy.processingFailed);
    expect(region).toHaveTextContent(copy.processingFailedHelp);
  });
});
