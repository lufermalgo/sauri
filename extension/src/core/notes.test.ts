// Feature: chrome-side-panel, Property 3: Note title placeholder
// Feature: chrome-side-panel, Property 4: NoteCard date format
// Feature: chrome-side-panel, Property 5: Projection of Notes to Cards (bijection with required fields)

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { displayTitle, formatNoteDate, projectCards, TITLE_PLACEHOLDER } from "./notes";
import type { NoteDTO } from "./types";

describe("displayTitle", () => {
  it("Property 3: null/empty/whitespace-only title -> placeholder; otherwise, original title (Req. 4.4, 7.5)", () => {
    fc.assert(
      fc.property(
        fc.option(fc.string(), { nil: null }),
        (title) => {
          const result = displayTitle(title);
          const isBlank = title === null || title.trim().length === 0;
          if (isBlank) {
            expect(result).toBe(TITLE_PLACEHOLDER);
          } else {
            expect(result).toBe(title);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("formatNoteDate", () => {
  it("Property 4: produces the D/M, HH:MM pattern (Req. 4.5)", () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date(2000, 0, 1), max: new Date(2099, 11, 31) }),
        (date) => {
          const result = formatNoteDate(date.toISOString());
          expect(result).toMatch(/^\d{1,2}\/\d{1,2}, \d{2}:\d{2}$/);
          const [datePart, timePart] = result.split(", ");
          const [d, m] = datePart.split("/").map(Number);
          expect(d).toBeGreaterThanOrEqual(1);
          expect(d).toBeLessThanOrEqual(31);
          expect(m).toBeGreaterThanOrEqual(1);
          expect(m).toBeLessThanOrEqual(12);
          const [hh, mm] = timePart.split(":").map(Number);
          expect(hh).toBeGreaterThanOrEqual(0);
          expect(hh).toBeLessThanOrEqual(23);
          expect(mm).toBeGreaterThanOrEqual(0);
          expect(mm).toBeLessThanOrEqual(59);
          expect(timePart.length).toBe(5); // HH:MM with two digits each
        }
      ),
      { numRuns: 100 }
    );
  });
});

const noteArb = fc.record({
  meetingId: fc.uuid(),
  title: fc.option(fc.string(), { nil: null }),
  processState: fc.constantFrom("queued", "recording", "completed", "failed"),
  createdAt: fc.date({ min: new Date(2000, 0, 1), max: new Date(2099, 11, 31) }).map((d) => d.toISOString()),
});

describe("projectCards", () => {
  it("Property 5: bijection by meetingId + displayable title + formatted date (Req. 4.2, 4.3)", () => {
    fc.assert(
      fc.property(fc.array(noteArb, { maxLength: 25 }), (notes: NoteDTO[]) => {
        // Unique meetingId to verify strict bijection
        const uniqueIds = Array.from(new Set(notes.map((n) => n.meetingId)));
        const uniqueNotes = uniqueIds.map((id) => notes.find((n) => n.meetingId === id)!);

        const cards = projectCards(uniqueNotes);

        expect(cards.length).toBe(uniqueNotes.length);
        for (const note of uniqueNotes) {
          const card = cards.find((t) => t.meetingId === note.meetingId);
          expect(card).toBeDefined();
          expect(card!.displayedTitle.length).toBeGreaterThan(0);
          expect(card!.displayedDate).toMatch(/^\d{1,2}\/\d{1,2}, \d{2}:\d{2}$/);
        }
      }),
      { numRuns: 100 }
    );
  });
});
