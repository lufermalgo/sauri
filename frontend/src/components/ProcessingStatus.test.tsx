// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { ProcessingStatus } from "./ProcessingStatus";
import { copy } from "../copy/es";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const NOW = new Date("2026-11-15T10:00:00Z");
type Props = ComponentProps<typeof ProcessingStatus>;

function base(overrides: Partial<Props> = {}): Props {
  return {
    meeting: { meetingId: "m-1", processState: "transcribing" },
    hasTranscript: false, diarizationNotFound: true, error: false, ...overrides,
  };
}

function ago(seconds: number): string {
  return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

function currentStep(): string | null {
  return document.querySelector('[aria-current="step"] .processing-step-label')?.textContent ?? null;
}

describe("ProcessingStatus — real states", () => {
  it.each(["queued", "transcribing"] as const)(
    "shows the real %s state and no percentage without a known duration", (processState) => {
      render(<ProcessingStatus {...base({ meeting: { meetingId: "m-1", processState } })} />);
      expect(screen.getByRole("status")).toHaveTextContent(copy.processing[processState]);
      expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
      expect(document.body.textContent).not.toContain("%");
      expect(screen.getByText(copy.processing.noEstimate)).toBeInTheDocument();
    },
  );

  it.each(["joining", "recording"] as const)("keeps live %s capture without an estimate", (processState) => {
    render(<ProcessingStatus {...base({ meeting: { meetingId: "m-1", processState }, audioSeconds: 600 })} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.processing[processState]);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
    expect(document.body.textContent).not.toContain("%");
  });

  it.each(["transcribing", "completed"])("shows identification after transcript availability in %s", (processState) => {
    render(<ProcessingStatus {...base({ meeting: { meetingId: "m-1", processState }, hasTranscript: true })} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.processing.identifying);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not claim identification before a transcript exists", () => {
    render(<ProcessingStatus {...base()} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.processing.transcribing);
  });

  it.each(["could_not_join", "meeting_cancelled", "engine_failure", "engine_failed",
    "engine_contract_mismatch", "invalid_response", "unknown", null])(
    "explains failure %s without exposing raw diagnostics or inventing a retry", (failureCause) => {
      render(<ProcessingStatus {...base({
        meeting: { meetingId: "m-1", processState: "failed", failureCause }, hasTranscript: true,
      })} />);
      expect(screen.getByRole("status")).toHaveTextContent(copy.processing.failed);
      expect(screen.getByRole("status")).toHaveTextContent(copy.processing.failureCause(failureCause));
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    },
  );

  it("explains a recording without detected speech instead of a generic failure, with no retry", () => {
    render(<ProcessingStatus {...base({
      meeting: { meetingId: "m-1", processState: "failed", failureCause: "no_speech_detected" }, hasTranscript: false,
    })} />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(copy.processing.noSpeechTitle);
    expect(status).toHaveTextContent(copy.processing.noSpeechBody);
    expect(status).not.toHaveTextContent(copy.processing.failureCause("engine_failed"));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("does not turn a state load failure into a processing state", () => {
    render(<ProcessingStatus {...base({ meeting: null, error: true })} />);
    expect(screen.getByRole("alert")).toHaveTextContent(copy.processing.loadFailed);
  });
});

describe("ProcessingStatus — stepper", () => {
  it.each([
    [base(), copy.processing.steps.transcription, 1],
    [base({ meeting: { meetingId: "m-1", processState: "queued" } }), copy.processing.steps.transcription, 1],
    [base({ hasTranscript: true }), copy.processing.steps.speakers, 2],
    [base({ meeting: { meetingId: "m-1", processState: "completed" }, hasTranscript: true, diarizationNotFound: false,
      hasDiarization: true, summary: "waiting" }), copy.processing.steps.summary, 3],
    [base({ meeting: { meetingId: "m-1", processState: "completed" }, hasTranscript: true, diarizationNotFound: false,
      hasDiarization: true, summary: "expected" }), copy.processing.steps.summary, 3],
  ] as const)("marks the current stage and the finished ones (%#)", (props, current, doneCount) => {
    render(<ProcessingStatus {...props} />);
    const steps = screen.getByRole("list", { name: copy.processing.stepsLabel });
    expect(steps.querySelectorAll("li")).toHaveLength(4);
    expect(currentStep()).toBe(current);
    expect(steps.querySelectorAll(".processing-step--done")).toHaveLength(doneCount);
    expect(steps.querySelector(".processing-step--done")).toHaveTextContent(copy.processing.steps.upload);
    expect(steps.querySelector("[aria-current='step']")).toHaveTextContent(copy.processing.stepState.current);
  });

  it("shows a success state with every step done once speakers and summary are settled", () => {
    render(<ProcessingStatus {...base({
      meeting: { meetingId: "m-1", processState: "completed" }, hasTranscript: true, diarizationNotFound: false,
      hasDiarization: true, summary: "settled", audioSeconds: 600,
    })} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.processing.completed);
    expect(screen.getByText(copy.processing.doneBody)).toBeInTheDocument();
    expect(document.querySelectorAll(".processing-step--done")).toHaveLength(4);
    expect(document.querySelector("[aria-current='step']")).toBeNull();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});

describe("ProcessingStatus — estimate", () => {
  it("shows an estimated percentage, elapsed and remaining time that tick every second", () => {
    vi.useFakeTimers({ now: NOW });
    // 54 min of audio: transcription ~324 s, speakers 15 s, summary ~389 s.
    render(<ProcessingStatus {...base({ audioSeconds: 54 * 60, createdAt: ago(120) })} />);
    const bar = screen.getByRole("progressbar", { name: copy.processing.transcribing });
    expect(bar).toHaveAttribute("aria-valuenow", "16");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(screen.getByText(copy.processing.percent(16))).toBeInTheDocument();
    expect(screen.getByText(copy.processing.elapsed("2:00"))).toBeInTheDocument();
    expect(screen.getByText(copy.processing.remaining(10))).toBeInTheDocument();
    expect(screen.getByText(copy.processing.explain.transcription(54, 5))).toBeInTheDocument();
    expect(screen.getByText(copy.processing.leaveHint)).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getByText(copy.processing.elapsed("2:05"))).toBeInTheDocument();
  });

  it("switches to overtime wording instead of a frozen percentage when the page opens late", () => {
    vi.useFakeTimers({ now: NOW });
    render(<ProcessingStatus {...base({ audioSeconds: 21 * 60, createdAt: ago(3 * 3600) })} />);
    const bar = screen.getByRole("progressbar", { name: copy.processing.transcribing });
    expect(Number(bar.getAttribute("aria-valuenow"))).toBeLessThanOrEqual(95);
    expect(bar).toHaveAttribute("aria-valuetext", copy.processing.overtime);
    expect(document.querySelector(".processing-remaining")).toHaveTextContent(copy.processing.overtime);
    expect(screen.getByText(copy.processing.explain.overtime)).toBeInTheDocument();
    expect(document.querySelector(".processing-percent")).toBeNull();
    expect(screen.getByText(copy.processing.elapsed("3:00:00"))).toBeInTheDocument();
  });

  it("times a stage from the moment the page sees it begin", () => {
    vi.useFakeTimers({ now: NOW });
    // The upload was long ago, so an opened-mid-stage guess would already be overtime.
    const props = base({ audioSeconds: 54 * 60, createdAt: ago(2000) });
    const view = render(<ProcessingStatus {...props} />);
    expect(document.querySelector(".processing-remaining")).toHaveTextContent(copy.processing.overtime);
    view.rerender(<ProcessingStatus {...props} hasTranscript />);
    expect(currentStep()).toBe(copy.processing.steps.speakers);
    expect(document.querySelector(".processing-remaining")).not.toHaveTextContent(copy.processing.overtime);
    act(() => { vi.advanceTimersByTime(20_000); });
    expect(document.querySelector(".processing-remaining")).toHaveTextContent(copy.processing.overtime);
  });

  it("does not claim a slow stage when the page opens right after speakers started", () => {
    vi.useFakeTimers({ now: NOW });
    // 94 minutes of audio uploaded 14 minutes ago: transcription took most of that time, not speakers.
    const props = base({
      meeting: { meetingId: "m-1", processState: "completed" },
      audioSeconds: 94 * 60, createdAt: ago(850), hasTranscript: true, diarizationNotFound: true,
    });
    render(<ProcessingStatus {...props} />);
    expect(currentStep()).toBe(copy.processing.steps.speakers);
    expect(screen.queryByText(copy.processing.overtime)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.processing.explain.overtime)).not.toBeInTheDocument();
    // Only time this page watched the running stage can make it overtime.
    act(() => { vi.advanceTimersByTime(20_000); });
    expect(document.querySelector(".processing-remaining")).toHaveTextContent(copy.processing.overtime);
  });

  it("announces the estimate politely at most every fifteen seconds", () => {
    vi.useFakeTimers({ now: NOW });
    render(<ProcessingStatus {...base({ audioSeconds: 54 * 60, createdAt: ago(120) })} />);
    const live = document.querySelector("[aria-live='polite']") as HTMLElement;
    expect(live).not.toHaveAttribute("role");
    expect(screen.getAllByRole("status")).toHaveLength(1);
    const first = live.textContent;
    expect(first).toContain(copy.processing.transcribing);
    let changes = 0;
    let previous = first;
    for (let second = 0; second < 30; second++) {
      act(() => { vi.advanceTimersByTime(1000); });
      if (live.textContent !== previous) changes++;
      previous = live.textContent;
    }
    expect(changes).toBeLessThanOrEqual(2);
    expect(live.textContent).not.toBe(first);
  });

  it("stops ticking while the page is hidden and when the work is done", () => {
    vi.useFakeTimers({ now: NOW });
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const props = base({ audioSeconds: 600, createdAt: ago(10) });
    const view = render(<ProcessingStatus {...props} />);
    expect(vi.getTimerCount()).toBe(1);
    hidden.mockReturnValue(true);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(vi.getTimerCount()).toBe(0);
    hidden.mockReturnValue(false);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(vi.getTimerCount()).toBe(1);
    view.rerender(<ProcessingStatus {...props} meeting={{ meetingId: "m-1", processState: "completed" }}
      hasTranscript diarizationNotFound={false} hasDiarization summary="settled" />);
    expect(vi.getTimerCount()).toBe(0);
    hidden.mockRestore();
  });
});
