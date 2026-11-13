import { describe, expect, it } from "vitest";
import { representativeSpeakerInterval } from "./speaker-review-interval";
import type { MeetingDiarization, MeetingTranscript } from "./api";

const turn = (id: string, startMs: number, endMs: number, sequence: number) => ({
  id, transcriptId: "transcript", text: "Synthetic voice", startMs, endMs, sequence,
});
const assignments = (pairs: Array<[string, string]>): MeetingDiarization["assignments"] =>
  pairs.map(([turn_id, speaker_id]) => ({ turn_id, speaker_id }));
const select = (turns: MeetingTranscript["turns"], pairs: Array<[string, string]>, speaker = "A") =>
  representativeSpeakerInterval(turns, assignments(pairs), speaker);

describe("representative speaker interval from original media", () => {
  it("prefers a continuous extended turn over tiny fragments, caps playback without deriving media", () => {
    const turns = [turn("one", 0, 300, 1), turn("two", 300, 1000, 2),
      turn("other", 1000, 2000, 3), turn("long", 2000, 32000, 4)];
    expect(select(turns, [["one", "A"], ["two", "A"], ["other", "B"], ["long", "A"]]))
      .toEqual({ startMs: 2000, endMs: 22000, short: false });
  });

  it("keeps a natural short pause, but never bridges a long gap or an unknown/switch", () => {
    const turns = [turn("a", 0, 3000, 1), turn("b", 3100, 6000, 2),
      turn("unknown", 6000, 6200, 3), turn("c", 6200, 9000, 4),
      turn("d", 10000, 14000, 5)];
    expect(select(turns, [["a", "A"], ["b", "A"], ["c", "A"], ["d", "A"]]))
      .toEqual({ startMs: 0, endMs: 6000, short: false });
  });

  it("removes overlap with the other speaker and marks a too-short stretch honestly", () => {
    const turns = [turn("a", 0, 3000, 1), turn("b", 2500, 4000, 2), turn("c", 3900, 5700, 3)];
    expect(select(turns, [["a", "A"], ["b", "B"], ["c", "A"]]))
      .toEqual({ startMs: 0, endMs: 2500, short: true });
  });

  it("does not play across an overlapping foreign turn spanning multiple source turns", () => {
    const turns = [turn("foreign", 0, 4500, 1), turn("a", 1000, 2000, 2),
      turn("b", 2200, 5200, 3)];
    expect(select(turns, [["foreign", "B"], ["a", "A"], ["b", "A"]]))
      .toEqual({ startMs: 4500, endMs: 5200, short: true });
  });

  it("does not invent speech for missing assignments or invalid timings", () => {
    expect(select([turn("a", 1, 1, 1), turn("b", 20, 200, 2)], [["a", "A"]])).toBeNull();
  });
});
