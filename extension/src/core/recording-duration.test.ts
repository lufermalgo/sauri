import { describe, expect, it } from "vitest";
import { parseDurationSeconds, recordedDurationSeconds } from "./recording-duration";

describe("recordedDurationSeconds", () => {
  it.each([
    [36_100, 37],
    [37_000, 37],
    [37_001, 38],
    [1_000, 1],
    [1_001, 2],
  ])("rounds %d ms up to %d s", (ms, seconds) => {
    expect(recordedDurationSeconds(ms)).toBe(seconds);
  });

  it.each([0, 1, 250, -5, Number.NaN, Number.POSITIVE_INFINITY])("never returns less than 1 (%s ms)", ms => {
    expect(recordedDurationSeconds(ms)).toBe(1);
  });
});

describe("parseDurationSeconds", () => {
  it("keeps positive whole seconds and rejects everything else", () => {
    expect(parseDurationSeconds(37)).toBe(37);
    for (const bad of [0, -1, 1.5, Number.NaN, "37", null, undefined]) expect(parseDurationSeconds(bad)).toBeUndefined();
  });
});
