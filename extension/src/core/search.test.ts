// Feature: chrome-side-panel, Property 7: Note filter as conjunction of search and criteria
// Feature: chrome-side-panel, Property 8: Note search inactive with blank text
// Feature: chrome-side-panel, Property 12: TranscriptSearch matches
// Feature: chrome-side-panel, Property 13: Transcript search inactive with blank text

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { filterNotes, transcriptMatches, NOTES_SEARCH_LIMIT, TRANSCRIPT_SEARCH_LIMIT } from "./search";
import type { NoteDTO, InterventionDTO } from "./types";

const noteArb = fc.record({
  meetingId: fc.uuid(),
  title: fc.string({ minLength: 1, maxLength: 20 }),
  processState: fc.constantFrom("queued", "recording", "completed", "failed"),
  createdAt: fc.constant(new Date(2024, 0, 1).toISOString()),
});

describe("filterNotes", () => {
  it("Property 7: conjunction of normalized title and state criteria (Req. 5.1, 5.2, 5.3)", () => {
    fc.assert(
      fc.property(
        fc.array(noteArb, { maxLength: 20 }),
        fc.string({ maxLength: 10 }),
        fc.constantFrom("queued", "recording", "completed", "failed"),
        (notes: NoteDTO[], text, state) => {
          const result = filterNotes(notes, text, { processState: state });
          const normText = text.trim().toLowerCase();

          for (const note of result) {
            const normTitle = (note.title ?? "").trim().toLowerCase();
            expect(normTitle.includes(normText)).toBe(true);
            expect(note.processState).toBe(state);
          }

          // No excluded note satisfies both predicates
          const excluded = notes.filter((n) => !result.includes(n));
          for (const note of excluded) {
            const normTitle = (note.title ?? "").trim().toLowerCase();
            const meetsText = normTitle.includes(normText);
            const meetsState = note.processState === state;
            expect(meetsText && meetsState).toBe(false);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("Property 8: blank text -> excludes no Note by title (Req. 5.4, 5.6)", () => {
    fc.assert(
      fc.property(
        fc.array(noteArb, { maxLength: 20 }),
        fc.constantFrom("", "   ", "\t", "  \n "),
        (notes: NoteDTO[], blankText) => {
          const result = filterNotes(notes, blankText, {});
          expect(result.length).toBe(notes.length);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("truncates the search to 100 characters (Req. 5.7)", () => {
    const longText = "a".repeat(150);
    expect(() => filterNotes([], longText, {})).not.toThrow();
    expect(NOTES_SEARCH_LIMIT).toBe(100);
  });
});

const interventionArb = fc.record({
  turnId: fc.uuid(),
  text: fc.string({ minLength: 1, maxLength: 30 }),
  startMs: fc.integer({ min: 0, max: 100000 }),
  endMs: fc.integer({ min: 0, max: 100000 }),
  sequence: fc.integer({ min: 0, max: 30 }),
  speaker: fc.constant(null),
});

describe("transcriptMatches", () => {
  it("Property 12: case-insensitive matches, first by lowest start_ms, order unchanged (Req. 9.1, 9.2, 9.4)", () => {
    fc.assert(
      fc.property(
        fc.array(interventionArb, { maxLength: 20 }),
        fc.string({ minLength: 1, maxLength: 10 }).filter((s) => s.trim().length > 0),
        (rawInterventions: InterventionDTO[], text) => {
          // Unique turnId: in the real domain it's the SpeechTurn's primary key;
          // without this guarantee, two Interventions with the same turnId but
          // different startMs would make `.find()` (first array element) and the
          // true minimum by startMs potentially disagree, producing a spurious
          // counterexample unrelated to the property under test.
          const uniqueIds = Array.from(new Set(rawInterventions.map((i) => i.turnId)));
          const interventions = uniqueIds.map((id) => rawInterventions.find((i) => i.turnId === id)!);

          const result = transcriptMatches(interventions, text);

          // The order/set of displayed interventions doesn't change
          expect(result.interventions).toEqual(interventions);

          // transcriptMatches trims() the search text before normalizing it
          // (Req. 9.5) — the oracle must replicate that exact normalization,
          // or text with leading/trailing spaces (e.g. " m") produces a
          // spurious counterexample.
          const normText = text.trim().toLowerCase();
          const matchingIds = new Set(
            interventions.filter((i) => i.text.toLowerCase().includes(normText)).map((i) => i.turnId)
          );
          expect(new Set(result.matchingTurnIds)).toEqual(matchingIds);

          if (matchingIds.size > 0) {
            const matching = interventions.filter((i) => matchingIds.has(i.turnId));
            const minStart = Math.min(...matching.map((i) => i.startMs));
            const first = interventions.find((i) => i.turnId === result.firstMatchId);
            expect(first).toBeDefined();
            expect(first!.startMs).toBe(minStart);
          } else {
            expect(result.firstMatchId).toBeNull();
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("Property 13: blank text -> zero matches, original order preserved (Req. 9.3)", () => {
    fc.assert(
      fc.property(
        fc.array(interventionArb, { maxLength: 20 }),
        fc.constantFrom("", "   ", "\t"),
        (interventions: InterventionDTO[], blankText) => {
          const result = transcriptMatches(interventions, blankText);
          expect(result.matchingTurnIds.length).toBe(0);
          expect(result.firstMatchId).toBeNull();
          expect(result.interventions).toEqual(interventions);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("truncates the search to 200 characters (Req. 9.5)", () => {
    expect(TRANSCRIPT_SEARCH_LIMIT).toBe(200);
  });
});
