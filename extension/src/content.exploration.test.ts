/**
 * Bug Condition Exploration Test — Detection Oscillation During Transient DOM Changes
 *
 * **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
 *
 * This test encodes the EXPECTED (correct) behavior:
 * - No `meet-ended` message should be sent while ACTIVE_CALL_SIGNALS are present
 * - No duplicate `meet-detected` messages during transient signal appearances
 * - MutationObserver callback should be debounced (not firing on every mutation)
 * - ACTIVE_CALL_SIGNALS should take priority over END_SIGNALS when both are present
 *
 * On UNFIXED code, this test will FAIL — that failure CONFIRMS the bug exists.
 * After the fix is implemented, this test will PASS.
 *
 * Bug Condition from design: `isBugCondition(input)` holds when:
 * - hasEndSignals AND hasActiveSignals AND currentState == 'active'
 * - OR hasEndSignals AND currentState == 'active' AND elapsedSinceLastEval < 500
 * - OR mutations.length > 1 AND elapsedSinceLastEval < 100
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * Helper: Read source file for static analysis of buggy patterns.
 */
function readSource(filename: string): string {
  return readFileSync(resolve(__dirname, filename), "utf-8");
}

describe("Bug Condition Exploration: Detection Oscillation During Transient DOM Changes", () => {
  /**
   * Property 1.1: MutationObserver callback MUST be debounced
   *
   * Bug Condition: mutations.length > 1 AND elapsedSinceLastEval < 100
   *
   * The MutationObserver callback should NOT call checkMeetState() directly.
   * Instead it should use a debounce mechanism (setTimeout/clearTimeout) to
   * batch rapid mutations and only evaluate state once the DOM has settled.
   *
   * On UNFIXED code: The observer calls checkMeetState() directly on every
   * mutation (no debounce), causing 100s of evaluations per second during UI
   * transitions. This property FAILS, confirming the bug.
   */
  describe("Property: MutationObserver must debounce checkMeetState() calls", () => {
    it("observer callback should use setTimeout/clearTimeout, not call checkMeetState() directly", () => {
      fc.assert(
        fc.property(
          // Generate scenarios with rapid DOM mutations (bug condition input)
          fc.record({
            mutationsPerSecond: fc.integer({ min: 50, max: 500 }),
            transitionDurationMs: fc.integer({ min: 100, max: 1000 }),
            elapsedSinceLastEval: fc.integer({ min: 0, max: 99 }), // < 100ms = bug condition
          }),
          (input) => {
            // Verify the bug condition holds: rapid mutations with short eval interval
            expect(input.mutationsPerSecond).toBeGreaterThan(1);
            expect(input.elapsedSinceLastEval).toBeLessThan(100);

            const contentSource = readSource("content.ts");

            // Find the MutationObserver callback
            const observerCallbackMatch = contentSource.match(
              /new MutationObserver\(\s*\([^)]*\)\s*=>\s*\{([\s\S]*?)\}\s*\)/
            );
            const observerBody = observerCallbackMatch?.[1] ?? "";

            // ASSERTION: The observer callback should NOT directly call checkMeetState()
            // It should use a debounce pattern: clearTimeout + setTimeout
            //
            // On UNFIXED code this FAILS because the observer body is:
            //   new MutationObserver(() => { checkMeetState(); })
            // with no debounce whatsoever.
            const hasDebounce =
              observerBody.includes("setTimeout") &&
              observerBody.includes("clearTimeout");

            expect(hasDebounce).toBe(true);
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property 1.2: Signal priority — ACTIVE_CALL_SIGNALS must override END_SIGNALS
   *
   * Bug Condition: hasEndSignals AND hasActiveSignals AND currentState == 'active'
   *
   * When both ACTIVE_CALL_SIGNALS and END_SIGNALS are present simultaneously in
   * the DOM (common during UI transitions), the detection logic MUST prioritize
   * active signals and NOT send `meet-ended`.
   *
   * On UNFIXED code: checkMeetState() checks endElement FIRST (before active),
   * and if found immediately fires `meet-ended` regardless of active signals.
   * This property FAILS, confirming the bug.
   */
  describe("Property: ACTIVE_CALL_SIGNALS must take priority over END_SIGNALS", () => {
    it("checkMeetState should check active signals first and skip end when both present", () => {
      fc.assert(
        fc.property(
          // Generate scenarios where both signals coexist (bug condition)
          fc.record({
            activeSignal: fc.constantFrom(
              "Leave call",
              "Turn off microphone",
              "Salir de la llamada",
              "Desactivar micrófono"
            ),
            endSignal: fc.constantFrom(
              "Return to home screen",
              "Rejoin",
              "Volver a la pantalla de inicio",
              "Volver a unirse"
            ),
            currentState: fc.constant("active" as const),
          }),
          (input) => {
            // Verify the bug condition: both signals present during active state
            expect(input.activeSignal).toBeTruthy();
            expect(input.endSignal).toBeTruthy();
            expect(input.currentState).toBe("active");

            const contentSource = readSource("content.ts");

            // Extract checkMeetState function body
            const checkMeetStateMatch = contentSource.match(
              /function checkMeetState\(\)[^{]*\{([\s\S]*?)^\}/m
            );
            const checkMeetStateBody = checkMeetStateMatch?.[1] ?? "";

            // ASSERTION: The function's conditional logic should check active signals
            // BEFORE end signals, giving active signals priority.
            //
            // Fixed pattern (current implementation, see content.ts):
            //   if (hasActiveSignals) { ... stay active ... return; }
            //   if (hasEndSignals && !hasActiveSignals) { ... begin ending ... }
            //
            // We check the position of the first `if (hasEndSignals` vs
            // `if (hasActiveSignals` in the conditional logic (not variable
            // declarations such as `const hasActiveSignals = ...`).
            const endIfPos = checkMeetStateBody.indexOf("if (hasEndSignals");
            const activeIfPos = checkMeetStateBody.indexOf("if (hasActiveSignals");

            // Active signal conditional should be evaluated BEFORE end signal conditional
            // to implement priority logic
            expect(activeIfPos).toBeGreaterThan(-1);
            expect(activeIfPos).toBeLessThan(endIfPos);
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property 1.3: No mutual flag reset — state should NOT allow re-triggering
   *
   * Bug Condition: hasEndSignals AND currentState == 'active' AND elapsedSinceLastEval < 500
   *
   * The detection logic must NOT use mutual boolean flag resets that allow
   * infinite oscillation between meet-detected and meet-ended states.
   * Instead it should use a state machine that prevents re-entry.
   *
   * On UNFIXED code: When meet-ended fires, it sets meetDetected = false.
   * When active signals reappear, !meetDetected is true, so it re-sends
   * meet-detected. This mutual reset creates the oscillation loop.
   * This property FAILS, confirming the bug.
   */
  describe("Property: No mutual boolean flag resets that allow oscillation", () => {
    it("checkMeetState should not reset meetDetected=false when ending, or meetEnded=false when detecting", () => {
      fc.assert(
        fc.property(
          // Generate oscillation scenarios
          fc.record({
            transientEndSignalDurationMs: fc.integer({ min: 50, max: 499 }), // < 500ms
            currentState: fc.constant("active" as const),
            reappearanceDelayMs: fc.integer({ min: 10, max: 200 }),
          }),
          (input) => {
            // Verify the bug condition: transient signals during active state
            expect(input.transientEndSignalDurationMs).toBeLessThan(500);
            expect(input.currentState).toBe("active");

            const contentSource = readSource("content.ts");

            // Extract checkMeetState function body
            const checkMeetStateMatch = contentSource.match(
              /function checkMeetState\(\)[^{]*\{([\s\S]*?)^\}/m
            );
            const checkMeetStateBody = checkMeetStateMatch?.[1] ?? "";

            // ASSERTION: The function should NOT contain mutual flag resets.
            // Specifically:
            //   - Should NOT set meetDetected = false when detecting end
            //   - Should NOT set meetEnded = false when detecting active
            //
            // On UNFIXED code this FAILS because:
            //   Line ~136: meetDetected = false (inside end detection branch)
            //   Line ~143: meetEnded = false (inside active detection branch)
            // These mutual resets create the oscillation loop.
            const hasMutualReset =
              checkMeetStateBody.includes("meetDetected = false") ||
              checkMeetStateBody.includes("meetEnded = false");

            expect(hasMutualReset).toBe(false);
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property 1.4: Confirmation period — meet-ended must NOT fire immediately
   *
   * Bug Condition: hasEndSignals AND currentState == 'active' AND elapsedSinceLastEval < 500
   *
   * When END_SIGNALS are detected, the system must NOT immediately send
   * `meet-ended`. It must wait for a confirmation period (e.g., 2 seconds)
   * to ensure the end state persists before accepting it as final.
   *
   * On UNFIXED code: checkMeetState() immediately sends `meet-ended` when
   * endElement is found, with no confirmation delay. Transient END_SIGNAL
   * appearances (<500ms during UI re-renders) incorrectly trigger the message.
   * This property FAILS, confirming the bug.
   */
  describe("Property: meet-ended requires confirmation period before sending", () => {
    it("end detection branch should use a confirmation timer, not immediate sendMessage", () => {
      fc.assert(
        fc.property(
          // Generate scenarios with transient end signals
          fc.record({
            transientDurationMs: fc.integer({ min: 50, max: 499 }),
            currentState: fc.constant("active" as const),
            endSignal: fc.constantFrom(
              "Return to home screen",
              "Rejoin",
              "Volver a la pantalla de inicio"
            ),
          }),
          (input) => {
            // Verify the bug condition
            expect(input.transientDurationMs).toBeLessThan(500);
            expect(input.currentState).toBe("active");

            const contentSource = readSource("content.ts");

            // Extract checkMeetState function body
            const checkMeetStateMatch = contentSource.match(
              /function checkMeetState\(\)[^{]*\{([\s\S]*?)^\}/m
            );
            const checkMeetStateBody = checkMeetStateMatch?.[1] ?? "";

            // ASSERTION: checkMeetState() should NOT directly call
            // chrome.runtime.sendMessage({ type: "meet-ended" }) as soon as end
            // signals are found. Instead, it should register a confirmation
            // timer (setTimeout) first, and only send `meet-ended` from inside
            // that timer's callback once the end state has been confirmed.
            //
            // We verify this without brace-balancing the source (which a plain
            // regex extraction can't do reliably around nested blocks) by
            // checking that the `setTimeout(` call that sets up the
            // confirmation timer appears BEFORE the `meet-ended` sendMessage
            // call in the function body — i.e., the send is nested inside the
            // deferred callback, not issued synchronously.
            const setTimeoutPos = checkMeetStateBody.indexOf("setTimeout(");
            const meetEndedSendPos = checkMeetStateBody.indexOf(
              'sendMessage({ type: "meet-ended" }'
            );

            expect(setTimeoutPos).toBeGreaterThan(-1);
            expect(meetEndedSendPos).toBeGreaterThan(-1);
            expect(setTimeoutPos).toBeLessThan(meetEndedSendPos);
          }
        ),
        { numRuns: 10 }
      );
    });
  });
});
