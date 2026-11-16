// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SpeakerTimeline, type TimelineTurn } from "./SpeakerTimeline";
import { t } from "../i18n";

afterEach(cleanup);
const turns: TimelineTurn[] = [
  { id: "a", startMs: 10000, endMs: 30000, speakerId: "s1", speakerLabel: "Synthetic One", color: "var(--ds-speaker-1)" },
  { id: "b", startMs: 30000, endMs: 90000, speakerId: "s2", speakerLabel: "Synthetic Two", color: "var(--ds-speaker-2)" },
];
function setup(overrides: Partial<Parameters<typeof SpeakerTimeline>[0]> = {}) {
  const onSeek = vi.fn();
  render(<SpeakerTimeline turns={turns} durationMs={100000} currentTimeMs={15000} keyPointTimes={[20000, 60000]}
    onSeek={onSeek} {...overrides} />);
  return onSeek;
}

describe("SpeakerTimeline", () => {
  it("positions proportional segments, retaining silence and the actual speaker colors", () => {
    setup();
    const segments = screen.getAllByTestId("timeline-segment");
    expect(segments[0]).toHaveStyle({ left: "10%", width: "20%", background: "var(--ds-speaker-1)" });
    expect(segments[1]).toHaveStyle({ left: "30%", width: "60%", background: "var(--ds-speaker-2)" });
    expect(screen.getByText("Synthetic One")).toBeVisible();
    expect(screen.getByText("Synthetic Two")).toBeVisible();
    expect(screen.getByText(t("meeting:keyPoints"))).toBeVisible();
    expect(screen.getByRole("slider", { name: t("meeting:timeline") })).toHaveAttribute("aria-valuenow", "15000");
  });

  it("seeks to a key point and to the clicked position, clamped to the duration", () => {
    const seek = setup();
    fireEvent.click(screen.getByRole("button", { name: t("meeting:keyPointAt", { time: "00:20" }) }));
    expect(seek).toHaveBeenLastCalledWith(20000);
    const slider = screen.getByRole("slider");
    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({ left: 20, width: 200 } as DOMRect);
    fireEvent.click(slider, { clientX: 70 });
    expect(seek).toHaveBeenLastCalledWith(25000);
    fireEvent.click(slider, { clientX: 500 });
    expect(seek).toHaveBeenLastCalledWith(100000);
  });

  it.each([["ArrowLeft", 10000], ["ArrowRight", 20000], ["Home", 0], ["End", 100000]])("seeks using %s", (key, expected) => {
    const seek = setup();
    fireEvent.keyDown(screen.getByRole("slider"), { key });
    expect(seek).toHaveBeenCalledWith(expected);
  });

  it.each([[0, "ArrowLeft", 0], [99000, "ArrowRight", 100000]])("clamps keyboard movement at %s", (currentTimeMs, key, expected) => {
    const seek = setup({ currentTimeMs });
    fireEvent.keyDown(screen.getByRole("slider"), { key });
    expect(seek).toHaveBeenCalledWith(expected);
  });

  it("disables seeking without playable media", () => {
    const seek = setup({ disabled: true });
    expect(screen.getByRole("slider")).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(screen.getByRole("slider"), { key: "ArrowRight" });
    fireEvent.click(screen.getByRole("button", { name: t("meeting:keyPointAt", { time: "00:20" }) }));
    expect(seek).not.toHaveBeenCalled();
  });

  it("ignores invalid intervals and markers without dividing by zero", () => {
    setup({ durationMs: 0, turns: [...turns, { ...turns[0], id: "invalid", startMs: null }], keyPointTimes: [NaN, -1, 100] });
    expect(screen.queryByTestId("timeline-segment")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("slider")).toHaveAttribute("aria-valuenow", "0");
  });
});
