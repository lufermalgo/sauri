import { describe, expect, it } from "vitest";
import type { MeetingDiarization } from "./api";
import { projectTranscript } from "./transcript-turns";

const sources = [{ id: "parent", text: "A😀 B.", startMs: 0, endMs: 900, sequence: 1 }];
function result(): MeetingDiarization {
  return { diarization_id: "dia", transcript_id: "tx", processing_revision: 2,
    speakers: [{ id: "a", label: "Speaker 1", sequence: 1 }, { id: "b", label: "Speaker 2", sequence: 2 }],
    assignments: [{ turn_id: "parent", speaker_id: "a", overlap_ms: 900 }],
    presentation: { version: 2, policy_version: "exclusive-source-v1", transcript_id: "tx", diarization_id: "dia",
      processing_revision: 2, pieces: [
        { source_turn_id: "parent", char_start: 0, char_end: 2, speaker_id: "a",
          intervals: [{ start_ms: 0, end_ms: 100 }, { start_ms: 200, end_ms: 300 }] },
        { source_turn_id: "parent", char_start: 2, char_end: 5, speaker_id: "b",
          intervals: [{ start_ms: 500, end_ms: 900 }] },
      ] } };
}

describe("source-referenced projection", () => {
  it("preserves codepoint text, separate seeks/gaps and A/B identities", () => {
    const projected = projectTranscript(sources, result(), "tx")!;
    expect(projected.turns.map((p) => p.text).join("")).toBe(sources[0].text);
    expect(projected.turns.map((p) => p.speakerId)).toEqual(["a", "b"]);
    expect(projected.intervals.map((p) => [p.startMs, p.endMs])).toEqual([[0, 100], [200, 300], [500, 900]]);
    expect(projected.turns.every((p) => p.sourceIds[0] === "parent")).toBe(true);
    expect(sources[0].text).toBe("A😀 B.");
  });
  it("keeps a whole uncertain parent visible without using its v1 winner", () => {
    const data = result();
    data.presentation!.pieces = [{ source_turn_id: "parent", char_start: 0, char_end: 5, speaker_id: null,
      intervals: [{ start_ms: 0, end_ms: 900 }] }];
    const projected = projectTranscript(sources, data, "tx")!;
    expect(projected.turns).toHaveLength(1);
    expect(projected.turns[0].text).toBe("A😀 B.");
    expect(projected.turns[0].speakerId).toBeUndefined();
  });
  for (const corrupt of ["revision", "speaker", "range", "interval", "parent", "partition"]) {
    it(`rejects ${corrupt} mismatch as a whole without legacy identity fallback`, () => {
      const data = result();
      if (corrupt === "revision") data.presentation!.processing_revision = 1;
      if (corrupt === "speaker") data.presentation!.pieces[0].speaker_id = "other-revision";
      if (corrupt === "range") data.presentation!.pieces[0].char_end = 50;
      if (corrupt === "interval") data.presentation!.pieces[0].intervals[0].start_ms = -1;
      if (corrupt === "parent") data.presentation!.pieces[0].source_turn_id = "other-source";
      if (corrupt === "partition") data.presentation!.pieces.splice(1);
      const projected = projectTranscript(sources, data, "tx")!;
      expect(projected.turns).toHaveLength(1);
      expect(projected.turns[0].speakerId).toBeUndefined();
      expect(projected.turns[0].text).toBe(sources[0].text);
    });
  }
  it("groups consecutive same-speaker parents while preserving original intervals and gap", () => {
    const data = result();
    const parents = [
      { id: "one", text: "One.", startMs: 0, endMs: 1000, sequence: 1 },
      { id: "two", text: "Two.", startMs: 2000, endMs: 3000, sequence: 2 },
    ];
    data.presentation!.pieces = parents.map((source) => ({ source_turn_id: source.id,
      char_start: 0, char_end: 4, speaker_id: "a", intervals: [{ start_ms: source.startMs, end_ms: source.endMs }] }));
    const projected = projectTranscript(parents, data, "tx")!;
    expect(projected.turns).toHaveLength(1);
    expect(projected.turns[0].sourceIds).toEqual(["one", "two"]);
    expect(projected.turns[0].text).toBe("One. Two.");
    expect(projected.intervals.map((p) => [p.startMs, p.endMs])).toEqual([[0, 1000], [2000, 3000]]);
    expect(new Set(projected.intervals.map((p) => p.presentationTurnId))).toEqual(new Set([projected.turns[0].id]));
  });
  it("does not invent retrospective projections", () => {
    expect(projectTranscript(sources, { ...result(), presentation: null }, "tx")).toBeNull();
  });
});
