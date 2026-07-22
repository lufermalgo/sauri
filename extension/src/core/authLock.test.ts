// Feature: chrome-side-panel, Property 20: Auth lockout after consecutive failures

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { isLocked } from "./authLock";
import type { AuthAttempt } from "./types";

const attemptArb = fc.record({
  success: fc.boolean(),
  atMs: fc.integer({ min: 0, max: 1_000_000 }),
});

describe("isLocked", () => {
  it("Property 20: true iff >=5 consecutive failures and <60s since the 5th (Req. 13.6)", () => {
    fc.assert(
      fc.property(
        fc.array(attemptArb, { minLength: 0, maxLength: 15 }).map((arr) =>
          [...arr].sort((a, b) => a.atMs - b.atMs)
        ),
        fc.integer({ min: 0, max: 1_100_000 }),
        (attempts: AuthAttempt[], now) => {
          const result = isLocked(attempts, now);

          // Reference calculation: consecutive failures at the end of the sequence
          let consecutive = 0;
          for (let i = attempts.length - 1; i >= 0; i--) {
            if (!attempts[i].success) consecutive++;
            else break;
          }

          if (consecutive < 5) {
            expect(result).toBe(false);
          } else {
            const fifthFromEnd = attempts[attempts.length - 5].atMs;
            const withinWindow = now - fifthFromEnd < 60_000;
            expect(result).toBe(withinWindow);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
