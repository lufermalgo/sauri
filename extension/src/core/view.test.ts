// Feature: chrome-side-panel, Property 16: Total and exclusive ViewState derivation

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { deriveViewState } from "./view";
import type { RemoteRequest } from "./types";

const requestArb = fc.oneof(
  fc.record({
    phase: fc.constant("initial" as const),
    data: fc.constant(null),
    previous: fc.constant(null),
  }),
  fc.record({
    phase: fc.constant("in_progress" as const),
    data: fc.constant(null),
    previous: fc.oneof(fc.constant(null), fc.array(fc.integer())),
  }),
  fc.record({
    phase: fc.constant("success" as const),
    data: fc.array(fc.integer(), { maxLength: 10 }),
    previous: fc.constant(null),
  }),
  fc.record({
    phase: fc.constant("failure" as const),
    data: fc.constant(null),
    previous: fc.oneof(fc.constant(null), fc.array(fc.integer(), { maxLength: 10 })),
  })
);

describe("deriveViewState", () => {
  it("Property 16: exactly one of four states; keeps previous on error (Req. 12.3, 12.5, 12.6, 12.7)", () => {
    fc.assert(
      fc.property(requestArb, (request: RemoteRequest<number>) => {
        const state = deriveViewState(request);
        expect(["loading", "withData", "empty", "error"]).toContain(state);

        if (request.phase === "in_progress" || request.phase === "initial") {
          expect(state).toBe("loading");
        } else if (request.phase === "success") {
          if ((request.data?.length ?? 0) > 0) {
            expect(state).toBe("withData");
          } else {
            expect(state).toBe("empty");
          }
        } else if (request.phase === "failure") {
          expect(state).toBe("error");
        }
      }),
      { numRuns: 100 }
    );
  });
});
