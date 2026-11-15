import { describe, expect, it } from "vitest";
import { transcriptToText } from "./transcript-export";

describe("transcriptToText", () => {
  it("writes one [mm:ss] line per turn", () => {
    const text = transcriptToText([
      { timestampMs: 0, speakerLabel: "Speaker A", text: "Hello there" },
      { timestampMs: 65_432, speakerLabel: "Speaker B", text: "Second turn" },
    ]);
    expect(text).toBe("[00:00] Speaker A: Hello there\n[01:05] Speaker B: Second turn");
  });

  it("keeps an unresolved speaker label as given", () => {
    expect(transcriptToText([{ timestampMs: 1000, speakerLabel: "Speaker N", text: "x" }])).toBe(
      "[00:01] Speaker N: x",
    );
  });

  it("uses hh:mm:ss on every line once the meeting passes one hour", () => {
    const text = transcriptToText([
      { timestampMs: 59_000, speakerLabel: "A", text: "early" },
      { timestampMs: 3_725_000, speakerLabel: "B", text: "late" },
    ]);
    expect(text).toBe("[00:00:59] A: early\n[01:02:05] B: late");
  });

  it("omits the bracket when the timestamp is missing", () => {
    expect(transcriptToText([{ timestampMs: null, speakerLabel: "A", text: "no time" }])).toBe("A: no time");
  });

  it("collapses line breaks inside a turn so each turn stays on one line", () => {
    expect(transcriptToText([{ timestampMs: 0, speakerLabel: "A", text: "one\ntwo \r\n three" }])).toBe(
      "[00:00] A: one two three",
    );
  });

  it("returns an empty string for no turns", () => {
    expect(transcriptToText([])).toBe("");
  });
});
