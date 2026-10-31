import { describe, expect, it } from "vitest";
import { createPlaybackIntervals, groupTranscriptTurns } from "./transcript-turns";

interface SourceSegment {
  id: string;
  text: string;
  startMs: number | null;
  endMs: number | null;
  sequence: number;
}

function segment(overrides: Partial<SourceSegment> & Pick<SourceSegment, "id" | "sequence">): SourceSegment {
  return {
    text: `Synthetic ${overrides.id}`,
    startMs: overrides.sequence * 100,
    endMs: overrides.sequence * 100 + 80,
    ...overrides,
  };
}

describe("transcript turn grouping", () => {
  it("groups maximal adjacent runs by validated speaker ID and preserves source order", () => {
    const sources = [
      segment({ id: "a1", sequence: 1, text: "Hello" }),
      segment({ id: "a2", sequence: 2, text: "there" }),
      segment({ id: "b1", sequence: 3, text: "How is it going?" }),
      segment({ id: "a3", sequence: 4, text: "Thanks" }),
    ];

    const turns = groupTranscriptTurns(sources, new Map([
      ["a1", "speaker-a"], ["a2", "speaker-a"], ["b1", "speaker-b"], ["a3", "speaker-a"],
    ]));

    expect(turns).toEqual([
      { id: "a1", sourceIds: ["a1", "a2"], text: "Hello there", timestampMs: 100, sequence: 1, speakerId: "speaker-a", speakerLabel: "Speaker N" },
      { id: "b1", sourceIds: ["b1"], text: "How is it going?", timestampMs: 300, sequence: 3, speakerId: "speaker-b", speakerLabel: "Speaker N" },
      { id: "a3", sourceIds: ["a3"], text: "Thanks", timestampMs: 400, sequence: 4, speakerId: "speaker-a", speakerLabel: "Speaker N" },
    ]);
  });

  it("keeps distinct speaker IDs separate even when their visible labels match", () => {
    const sources = [
      segment({ id: "first", sequence: 1, text: "First" }),
      segment({ id: "second", sequence: 2, text: "Second" }),
    ];

    const turns = groupTranscriptTurns(sources, new Map([
      ["first", "speaker-one"], ["second", "speaker-two"],
    ]));

    expect(turns.map(({ sourceIds }) => sourceIds)).toEqual([["first"], ["second"]]);
    expect(turns.map(({ speakerLabel }) => speakerLabel)).toEqual(["Speaker N", "Speaker N"]);
  });

  it("breaks runs at missing or non-positive assignments and at invalid timing", () => {
    const sources = [
      segment({ id: "before-missing", sequence: 1, text: "Before" }),
      segment({ id: "missing", sequence: 2, text: "Unassigned" }),
      segment({ id: "after-missing", sequence: 3, text: "After" }),
      segment({ id: "zero", sequence: 4, text: "Zero overlap" }),
      segment({ id: "invalid", sequence: 5, text: "Invalid time", startMs: null }),
      segment({ id: "after-invalid", sequence: 6, text: "After invalid" }),
    ];

    const turns = groupTranscriptTurns(sources, new Map([
      ["before-missing", "speaker-a"], ["after-missing", "speaker-a"],
      ["invalid", "speaker-a"], ["after-invalid", "speaker-a"],
    ]));

    expect(turns.map(({ sourceIds }) => sourceIds)).toEqual([
      ["before-missing"], ["missing"], ["after-missing"], ["zero"], ["invalid"], ["after-invalid"],
    ]);
    expect(turns.find(({ id }) => id === "invalid")?.timestampMs).toBeNull();
    expect(createPlaybackIntervals(sources, turns)).toEqual([
      { id: "before-missing", presentationTurnId: "before-missing", startMs: 100, endMs: 180, text: "Before", sequence: 1 },
      { id: "missing", presentationTurnId: "missing", startMs: 200, endMs: 280, text: "Unassigned", sequence: 2 },
      { id: "after-missing", presentationTurnId: "after-missing", startMs: 300, endMs: 380, text: "After", sequence: 3 },
      { id: "zero", presentationTurnId: "zero", startMs: 400, endMs: 480, text: "Zero overlap", sequence: 4 },
      { id: "after-invalid", presentationTurnId: "after-invalid", startMs: 600, endMs: 680, text: "After invalid", sequence: 6 },
    ]);
  });

  it("sorts stably by sequence, preserves source objects, and derives exact one-to-one intervals", () => {
    const sources = [
      segment({ id: "late", sequence: 3, text: "Last", startMs: 310, endMs: 450 }),
      segment({ id: "first", sequence: 1, text: "First", startMs: 0, endMs: 100 }),
      segment({ id: "middle", sequence: 2, text: "   ", startMs: 80, endMs: 160 }),
      segment({ id: "same-sequence", sequence: 2, text: "Middle two", startMs: 150, endMs: 220 }),
    ];
    const original = structuredClone(sources);

    const turns = groupTranscriptTurns(sources, new Map([
      ["first", "speaker-a"], ["middle", "speaker-a"], ["same-sequence", "speaker-a"], ["late", "speaker-a"],
    ]));
    const intervals = createPlaybackIntervals(sources, turns);

    expect(turns[0]).toMatchObject({
      id: "first", sourceIds: ["first", "middle", "same-sequence", "late"],
      text: "First Middle two Last", timestampMs: 0, sequence: 1, speakerId: "speaker-a",
    });
    expect(sources).toEqual(original);
    expect(intervals).toEqual([
      { id: "first", presentationTurnId: "first", startMs: 0, endMs: 100, text: "First", sequence: 1 },
      { id: "middle", presentationTurnId: "first", startMs: 80, endMs: 160, text: "   ", sequence: 2 },
      { id: "same-sequence", presentationTurnId: "first", startMs: 150, endMs: 220, text: "Middle two", sequence: 2 },
      { id: "late", presentationTurnId: "first", startMs: 310, endMs: 450, text: "Last", sequence: 3 },
    ]);
    expect(intervals).toHaveLength(sources.length);
    expect(intervals[0].endMs).toBeLessThan(intervals[1].startMs);
    expect(intervals[1].endMs).toBeGreaterThan(intervals[2].startMs);
    expect(intervals[2].endMs).toBeLessThan(intervals[3].startMs);
  });
});
