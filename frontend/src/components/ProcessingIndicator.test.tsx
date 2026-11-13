// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { ProcessingIndicator } from "./ProcessingIndicator";
import copy from "../../messages/processing.es.json";
import { getProcessing, type ProcessingSnapshot } from "../api";

vi.mock("../api", () => ({ getProcessing: vi.fn() }));
const getState = vi.mocked(getProcessing);
const snapshot = (state = "active", id = "meeting-1"): ProcessingSnapshot => ({
  meeting_id: id,
  execution: { generation: 1, transcript_id: "transcript-1", diarization_revision: 1 },
  ready: state === "completed", failed: state === "failed",
  stages: [
    { key: "audio_preparation", state: "unavailable" },
    { key: "transcription", state: "completed" },
    { key: "diarization", state: state as ProcessingSnapshot["stages"][number]["state"] },
    { key: "result_preparation", state: state === "completed" ? "completed" : "unavailable" },
  ],
});
const flush = () => act(async () => { await Promise.resolve(); });
const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(2000); });

beforeEach(() => { vi.useFakeTimers(); getState.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("truthful processing indicator", () => {
  it("does not equate ASR completion with ready and updates speakers automatically", async () => {
    getState.mockResolvedValueOnce(snapshot("pending"))
      .mockResolvedValueOnce(snapshot("active")).mockResolvedValue(snapshot("completed"));
    const ready = vi.fn().mockResolvedValue(undefined);
    render(<ProcessingIndicator meetingId="meeting-1" onReady={ready} />);
    await flush();
    expect(screen.getByText(`${copy.stages.diarization}: ${copy.states.pending}`)).toBeVisible();
    expect(screen.queryByText("Listo para revisar")).toBeNull();
    expect(ready).not.toHaveBeenCalled();
    await tick();
    expect(screen.getByText(`${copy.stages.diarization}: ${copy.states.active}`)).toBeVisible();
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("value");
    expect(screen.getByText(`${copy.stages.audio_preparation}: ${copy.states.unavailable}`)).toBeVisible();
    expect(document.body.textContent).not.toMatch(/\d+%|tiempo restante/i);
    await tick();
    expect(screen.getByText("Listo para revisar")).toBeVisible();
    expect(ready).toHaveBeenCalledTimes(1);
    await tick();
    expect(ready).toHaveBeenCalledTimes(1);
  });

  it("keeps a query failure separate, labels the retained snapshot and retries only GET", async () => {
    getState.mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue(snapshot("completed"));
    const ready = vi.fn().mockResolvedValue(undefined);
    render(<ProcessingIndicator meetingId="meeting-1" onReady={ready} />);
    await flush(); await tick();
    expect(screen.getByRole("alert")).toHaveTextContent("No pudimos actualizar el estado");
    expect(screen.getByText(/Último estado confirmado/)).toBeVisible();
    expect(screen.queryByText(copy.failed)).toBeNull();
    expect(ready).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar consulta" }));
    await flush();
    expect(getState).toHaveBeenCalledTimes(3);
    expect(screen.getByText("Listo para revisar")).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a confirmed job failure without offering a model retry", async () => {
    getState.mockResolvedValue(snapshot("failed"));
    render(<ProcessingIndicator meetingId="meeting-1" />);
    await flush();
    expect(screen.getByText(`${copy.stages.diarization}: ${copy.states.failed}`)).toBeVisible();
    expect(screen.queryByText("Listo para revisar")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not overlap requests or accept late responses from a different meeting", async () => {
    let finish!: (value: ProcessingSnapshot) => void;
    getState.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }))
      .mockResolvedValue(snapshot("pending", "meeting-2"));
    const ready = vi.fn().mockResolvedValue(undefined);
    const { rerender, unmount } = render(<ProcessingIndicator meetingId="meeting-1" onReady={ready} />);
    await tick(); await tick();
    expect(getState).toHaveBeenCalledTimes(1);
    const firstSignal = getState.mock.calls[0][1];
    rerender(<ProcessingIndicator meetingId="meeting-2" onReady={ready} />);
    await flush();
    expect(firstSignal?.aborted).toBe(true);
    await act(async () => { finish(snapshot("completed")); });
    expect(ready).not.toHaveBeenCalled();
    expect(screen.queryByText("Listo para revisar")).toBeNull();
    unmount(); await tick();
    expect(getState).toHaveBeenCalledTimes(2);
  });

  it("does not declare ready if result retrieval fails, and recovers on a read", async () => {
    getState.mockResolvedValue(snapshot("completed"));
    const ready = vi.fn().mockRejectedValueOnce(new Error("transcript unavailable")).mockResolvedValue(undefined);
    render(<ProcessingIndicator meetingId="meeting-1" onReady={ready} />);
    await flush();
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.queryByText("Listo para revisar")).toBeNull();
    await tick();
    expect(screen.getByText("Listo para revisar")).toBeVisible();
  });

  it("invalidates the delivered result when the current execution changes", async () => {
    const initial = snapshot("completed");
    const pending = { ...snapshot("pending"), execution: { ...initial.execution, diarization_revision: 2 } };
    getState.mockResolvedValueOnce(initial).mockResolvedValueOnce(pending)
      .mockResolvedValue({ ...pending, ready: true, stages: snapshot("completed").stages });
    const ready = vi.fn().mockResolvedValue(undefined);
    const pendingCallback = vi.fn();
    render(<ProcessingIndicator meetingId="meeting-1" onReady={ready} onPending={pendingCallback} />);
    await flush(); await tick();
    expect(pendingCallback).toHaveBeenCalled();
    expect(screen.queryByText("Listo para revisar")).toBeNull();
    await tick();
    expect(ready).toHaveBeenCalledTimes(2);
    expect(ready.mock.calls[1][0].execution.diarization_revision).toBe(2);
  });
});
