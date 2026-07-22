// Feature: chrome-side-panel, Property 14: SpeakingTime calculation and coverage

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { calculateSpeakingTime } from "./speakerTime";
import type { SpeechTurnDTO, SpeakerAssignmentDTO, SpeakerDTO } from "./types";

const speakerArb = fc.record({
  id: fc.uuid(),
  label: fc.string({ minLength: 1 }),
  sequence: fc.integer({ min: 1, max: 20 }),
});

describe("calculateSpeakingTime", () => {
  it("Property 14: one entry per speaker (incl. time 0) and correct sum (end-start) (Req. 10.1, 10.2)", () => {
    fc.assert(
      fc.property(
        fc.array(speakerArb, { maxLength: 6 }).map((hs) => {
          const ids = Array.from(new Set(hs.map((h) => h.id)));
          return ids.map((id) => hs.find((h) => h.id === id)!);
        }),
        fc.array(
          fc.record({
            id: fc.uuid(),
            startMs: fc.integer({ min: 0, max: 1000 }),
            endMs: fc.integer({ min: 0, max: 2000 }),
            sequence: fc.integer({ min: 0, max: 30 }),
          }),
          { maxLength: 15 }
        ),
        (speakers: SpeakerDTO[], rawTurns) => {
          const turns: SpeechTurnDTO[] = rawTurns.map((t) => ({
            ...t,
            text: "x",
            endMs: Math.max(t.endMs, t.startMs),
          }));

          // Assigns each turn to a random speaker (or none) deterministically by index
          const assignments: SpeakerAssignmentDTO[] = turns
            .map((t, i) =>
              speakers.length > 0 && i % 2 === 0
                ? { turnId: t.id, speakerId: speakers[i % speakers.length].id }
                : null
            )
            .filter((a): a is SpeakerAssignmentDTO => a !== null);

          const entries = calculateSpeakingTime(turns, assignments, speakers);

          expect(entries.length).toBe(speakers.length);

          for (const speaker of speakers) {
            const entry = entries.find((e) => e.speaker.id === speaker.id);
            expect(entry).toBeDefined();

            const speakerTurnIds = new Set(
              assignments.filter((a) => a.speakerId === speaker.id).map((a) => a.turnId)
            );
            const expected = turns
              .filter((t) => speakerTurnIds.has(t.id))
              .reduce((acc, t) => acc + (t.endMs - t.startMs), 0);

            expect(entry!.timeMs).toBe(expected);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
