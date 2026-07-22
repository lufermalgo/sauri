// Feature: chrome-side-panel, Property 9: Mapping of SpeechTurns to Interventions (bijection and preservation)
// Feature: chrome-side-panel, Property 11: Speaker attribution to the Intervention

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { mapInterventions, attributeSpeaker, UNIDENTIFIED_SPEAKER_LABEL } from "./interventions";
import type { TranscriptDTO, SpeechTurnDTO, SpeakerDTO, SpeakerAssignmentDTO } from "./types";

const turnArb = fc.record({
  id: fc.uuid(),
  text: fc.string(),
  startMs: fc.integer({ min: 0, max: 100000 }),
  endMs: fc.integer({ min: 0, max: 100000 }),
  sequence: fc.integer({ min: 0, max: 100 }),
});

describe("mapInterventions", () => {
  it("Property 9: bijection by turnId and field preservation (Req. 8.1, 8.5, 14.2)", () => {
    fc.assert(
      fc.property(fc.array(turnArb, { maxLength: 30 }), (rawSegments: SpeechTurnDTO[]) => {
        const uniqueIds = Array.from(new Set(rawSegments.map((s) => s.id)));
        const segments = uniqueIds.map((id) => rawSegments.find((s) => s.id === id)!);

        const transcript: TranscriptDTO = {
          transcriptId: "t1",
          meetingId: "r1",
          segments,
        };

        const interventions = mapInterventions(transcript);
        expect(interventions.length).toBe(segments.length);
        for (const turn of segments) {
          const intervention = interventions.find((i) => i.turnId === turn.id);
          expect(intervention).toBeDefined();
          expect(intervention!.text).toBe(turn.text);
          expect(intervention!.startMs).toBe(turn.startMs);
          expect(intervention!.endMs).toBe(turn.endMs);
          expect(intervention!.sequence).toBe(turn.sequence);
        }
      }),
      { numRuns: 100 }
    );
  });
});

const speakerArb = fc.record({
  id: fc.uuid(),
  label: fc.string({ minLength: 1 }),
  sequence: fc.integer({ min: 1, max: 20 }),
});

describe("attributeSpeaker", () => {
  it("Property 11: with assignment -> assigned speaker; without -> placeholder; text/time preserved (Req. 8.3, 8.7)", () => {
    fc.assert(
      fc.property(
        turnArb,
        fc.array(speakerArb, { maxLength: 5 }),
        fc.boolean(),
        (turn: SpeechTurnDTO, speakers: SpeakerDTO[], withAssignment: boolean) => {
          const chosenSpeaker = speakers[0];
          const assignments: SpeakerAssignmentDTO[] =
            withAssignment && chosenSpeaker
              ? [{ turnId: turn.id, speakerId: chosenSpeaker.id }]
              : [];

          const intervention = attributeSpeaker(turn, assignments, speakers);

          expect(intervention.text).toBe(turn.text);
          expect(intervention.startMs).toBe(turn.startMs);
          expect(intervention.endMs).toBe(turn.endMs);

          if (withAssignment && chosenSpeaker) {
            expect(intervention.speaker).not.toBeNull();
            expect(intervention.speaker!.id).toBe(chosenSpeaker.id);
            expect(intervention.speaker!.label).toBe(chosenSpeaker.label);
          } else {
            expect(intervention.speaker).toBeNull();
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("placeholder 'unidentified speaker' is defined", () => {
    expect(UNIDENTIFIED_SPEAKER_LABEL.length).toBeGreaterThan(0);
  });
});
