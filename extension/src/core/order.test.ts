// Feature: chrome-side-panel, Property 6: Note order (non-increasing by date, total, and repeatable)
// Feature: chrome-side-panel, Property 10: Intervention order by (start_ms, sequence)
// Feature: chrome-side-panel, Property 15: SpeakingTimeView order

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { sortNotes, sortInterventions, sortSpeakingTime } from "./order";
import type { NoteDTO, InterventionDTO, SpeakingTimeEntry } from "./types";

const baseDate = new Date(2024, 0, 1).getTime();

const noteArb = fc.record({
  meetingId: fc.uuid(),
  title: fc.constant<string | null>(null),
  processState: fc.constant("completed"),
  createdAt: fc.integer({ min: 0, max: 20 }).map((i) => new Date(baseDate + i * 3_600_000).toISOString()),
});

describe("sortNotes", () => {
  it("Property 6: desc. by date, tie-break asc. by meetingId, total and idempotent (Req. 4.6)", () => {
    fc.assert(
      fc.property(fc.array(noteArb, { maxLength: 30 }), (notes: NoteDTO[]) => {
        const sorted = sortNotes(notes);
        expect(sorted.length).toBe(notes.length);

        for (let i = 0; i < sorted.length - 1; i++) {
          const a = sorted[i];
          const b = sorted[i + 1];
          const fa = new Date(a.createdAt!).getTime();
          const fb = new Date(b.createdAt!).getTime();
          if (fa === fb) {
            expect(a.meetingId <= b.meetingId).toBe(true);
          } else {
            expect(fa).toBeGreaterThanOrEqual(fb);
          }
        }

        // Idempotence
        expect(sortNotes(sorted)).toEqual(sorted);
      }),
      { numRuns: 100 }
    );
  });
});

const interventionArb = fc.record({
  turnId: fc.uuid(),
  text: fc.string(),
  startMs: fc.integer({ min: 0, max: 10 }),
  endMs: fc.integer({ min: 0, max: 100000 }),
  sequence: fc.integer({ min: 0, max: 10 }),
  speaker: fc.constant(null),
});

describe("sortInterventions", () => {
  it("Property 10: asc. by (start_ms, sequence), total and idempotent (Req. 8.2)", () => {
    fc.assert(
      fc.property(fc.array(interventionArb, { maxLength: 30 }), (interventions: InterventionDTO[]) => {
        const sorted = sortInterventions(interventions);
        expect(sorted.length).toBe(interventions.length);
        for (let i = 0; i < sorted.length - 1; i++) {
          const a = sorted[i];
          const b = sorted[i + 1];
          if (a.startMs === b.startMs) {
            expect(a.sequence).toBeLessThanOrEqual(b.sequence);
          } else {
            expect(a.startMs).toBeLessThanOrEqual(b.startMs);
          }
        }
        expect(sortInterventions(sorted)).toEqual(sorted);
      }),
      { numRuns: 100 }
    );
  });
});

const entryArb = fc.record({
  speaker: fc.record({
    id: fc.uuid(),
    label: fc.string(),
    sequence: fc.integer({ min: 0, max: 10 }),
  }),
  timeMs: fc.integer({ min: 0, max: 10 }),
});

describe("sortSpeakingTime", () => {
  it("Property 15: non-increasing by time, tie-break asc. by sequence, total and idempotent (Req. 10.4)", () => {
    fc.assert(
      fc.property(fc.array(entryArb, { maxLength: 30 }), (entries: SpeakingTimeEntry[]) => {
        const sorted = sortSpeakingTime(entries);
        expect(sorted.length).toBe(entries.length);
        for (let i = 0; i < sorted.length - 1; i++) {
          const a = sorted[i];
          const b = sorted[i + 1];
          if (a.timeMs === b.timeMs) {
            expect(a.speaker.sequence).toBeLessThanOrEqual(b.speaker.sequence);
          } else {
            expect(a.timeMs).toBeGreaterThanOrEqual(b.timeMs);
          }
        }
        expect(sortSpeakingTime(sorted)).toEqual(sorted);
      }),
      { numRuns: 100 }
    );
  });
});
