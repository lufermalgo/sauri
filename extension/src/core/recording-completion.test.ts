// T1.1 RED — pure, provider-neutral completion transition contract (Req. 1.1–1.5, 5.2).
// This module intentionally does not exist yet. Production owns the transition;
// background.ts will invoke its idempotent claim for the persisted sessionId.
import { describe, expect, it } from "vitest";
import * as fc from "fast-check";
import { applyCompletionEvent } from "./recording-completion";

type Trigger = "stop" | "captured-tab-close" | "meeting-ended";
const sessionIdArb = fc.uuid(); // Synthetic capture IDs only.
const providerArb = fc.constantFrom<"meet" | "teams">("meet", "teams");
const completionTriggerArb = fc.constantFrom<Trigger>("stop", "captured-tab-close");

function claimsFor(sessionId: string, provider: "meet" | "teams", events: Trigger[]) {
  let state = { sessionId, provider, completionClaimed: false };
  const claims: string[] = [];
  for (const event of events) {
    const result = applyCompletionEvent(state, event);
    state = result.state;
    if (result.shouldFinalize) claims.push(state.sessionId);
  }
  return { state, claims };
}

describe("recording completion convergence (T1.1)", () => {
  it("Stop claims finalization once for the active session (Req. 1.1)", () => {
    fc.assert(fc.property(sessionIdArb, providerArb, (sessionId, provider) => {
      const { state, claims } = claimsFor(sessionId, provider, ["stop"]);
      expect(claims).toEqual([sessionId]);
      expect(state.completionClaimed).toBe(true);
    }), { numRuns: 100 });
  });

  it("captured-tab-close independently claims finalization (Req. 1.2)", () => {
    fc.assert(fc.property(sessionIdArb, providerArb, (sessionId, provider) => {
      const { state, claims } = claimsFor(sessionId, provider, ["captured-tab-close"]);
      expect(claims).toEqual([sessionId]);
      expect(state.completionClaimed).toBe(true);
    }), { numRuns: 100 });
  });

  it("both triggers in either order converge on the same session (Req. 1.3–1.4)", () => {
    fc.assert(fc.property(sessionIdArb, providerArb, completionTriggerArb,
      (sessionId, provider, first) => {
        const second = first === "stop" ? "captured-tab-close" : "stop";
        const { state, claims } = claimsFor(sessionId, provider, [first, second]);
        expect(claims).toEqual([sessionId]);
        expect(state.sessionId).toBe(sessionId);
        expect(state.provider).toBe(provider);
      }), { numRuns: 100 });
  });

  it("arbitrary duplicate and interleaved signals never claim twice (Req. 1.4, 5.2)", () => {
    fc.assert(fc.property(sessionIdArb, providerArb,
      fc.array(fc.constantFrom<Trigger>("stop", "captured-tab-close", "meeting-ended"),
        { minLength: 1, maxLength: 30 }),
      (sessionId, provider, events) => {
        const { state, claims } = claimsFor(sessionId, provider, events);
        expect(claims).toEqual(events.some((event) => event !== "meeting-ended") ? [sessionId] : []);
        expect(state.sessionId).toBe(sessionId);
      }), { numRuns: 150 });
  });

  it("meeting-ended alone never finalizes or detaches an active session (Req. 1.5, 5.2)", () => {
    fc.assert(fc.property(sessionIdArb, providerArb,
      fc.integer({ min: 1, max: 20 }), (sessionId, provider, repeats) => {
        const { state, claims } = claimsFor(sessionId, provider,
          Array<Trigger>(repeats).fill("meeting-ended"));
        expect(claims).toEqual([]);
        expect(state).toEqual({ sessionId, provider, completionClaimed: false });
        // A later authorized trigger must still find and finalize the same capture.
        const resumed = applyCompletionEvent(state, "captured-tab-close");
        expect(resumed.shouldFinalize).toBe(true);
        expect(resumed.state.sessionId).toBe(sessionId);
      }), { numRuns: 100 });
  });
});
