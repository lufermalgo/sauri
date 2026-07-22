// Feature: chrome-side-panel, Property 17: CaptureState state machine
// Feature: chrome-side-panel, Property 18: New Note button enablement based on CaptureState

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { applyCaptureEvent, newNoteButtonEnabled } from "./capture";
import type { CaptureState, CaptureEvent } from "./types";

const STATES: CaptureState[] = ["idle", "recording", "stopping"];
const EVENTS: CaptureEvent[] = ["start", "stop", "finished", "start_failure"];

const VALID_TRANSITIONS: Record<string, CaptureState> = {
  "idle:start": "recording",
  "recording:stop": "stopping",
  "stopping:finished": "idle",
};

describe("applyCaptureEvent", () => {
  it("Property 17: valid transitions per the table; otherwise keeps the state (Req. 2.4, 3.3, 3.4, 3.5)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...STATES),
        fc.constantFrom(...EVENTS),
        (state, event) => {
          const result = applyCaptureEvent(state, event);
          const key = `${state}:${event}`;
          if (VALID_TRANSITIONS[key]) {
            expect(result).toBe(VALID_TRANSITIONS[key]);
          } else {
            expect(result).toBe(state);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("newNoteButtonEnabled", () => {
  it("Property 18: disabled iff recording/stopping (Req. 2.5)", () => {
    fc.assert(
      fc.property(fc.constantFrom(...STATES), (state) => {
        const enabled = newNoteButtonEnabled(state);
        expect(enabled).toBe(state === "idle");
      }),
      { numRuns: 100 }
    );
  });
});
