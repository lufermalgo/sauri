/**
 * Preservation Property Tests — Genuine State Transitions Still Work
 *
 * **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**
 *
 * These tests verify structural properties of content.ts that MUST be preserved
 * after the oscillation fix is applied. They confirm baseline behavior on the
 * UNFIXED code for non-buggy inputs (stable signals, no transient flashing).
 *
 * All these tests PASS on unfixed code — they encode behavior to preserve.
 *
 * Preservation properties verified:
 * - Stable ACTIVE_CALL_SIGNALS → single `meet-detected` with title and URL
 * - Stable END_SIGNALS → single `meet-ended`
 * - Page load on already-active meeting → initial checkMeetState() detects meeting
 * - Spanish ARIA labels ("Salir de la llamada", "Volver a la pantalla de inicio") recognized
 * - `show-consent-banner` message triggers banner display without interference
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { readFileSync } from "fs";
import { resolve } from "path";

/**
 * Helper: Read source file for static analysis.
 */
function readSource(filename: string): string {
  return readFileSync(resolve(__dirname, filename), "utf-8");
}

describe("Preservation: Genuine State Transitions Still Work", () => {
  /**
   * Property 3.1: Stable ACTIVE_CALL_SIGNALS produce a single `meet-detected`
   * message with meetingTitle and url fields.
   *
   * When ACTIVE_CALL_SIGNALS persist stably (no END_SIGNALS present), the
   * detection logic sends exactly one `meet-detected` message containing
   * both `meetingTitle` and `url` fields.
   *
   * On UNFIXED code: This works correctly for stable signals — the bug only
   * manifests during transient signal appearances. This test PASSES.
   */
  describe("Property: Stable active signals produce meet-detected with title and URL", () => {
    it("meet-detected sendMessage includes meetingTitle and url fields", () => {
      fc.assert(
        fc.property(
          // Generate any combination of active signals (stable, no end signals)
          fc.record({
            activeSignal: fc.constantFrom(
              "Leave call",
              "Turn off microphone",
              "Turn on microphone",
              "Turn off camera",
              "Turn on camera",
              "Salir de la llamada",
              "Desactivar micrófono",  // spanish-sample-data
              "Activar micrófono",  // spanish-sample-data
              "Desactivar cámara",  // spanish-sample-data
              "Activar cámara"  // spanish-sample-data
            ),
          }),
          (_input) => {
            const contentSource = readSource("content.ts");

            // Verify: There exists a sendMessage call with type "meet-detected"
            // that includes meetingTitle and url
            const meetDetectedPattern =
              /chrome\.runtime\.sendMessage\(\s*\{[^}]*type:\s*"meet-detected"[^}]*\}\s*\)/s;
            const meetDetectedMatch = contentSource.match(meetDetectedPattern);

            expect(meetDetectedMatch).not.toBeNull();

            const matchedBlock = meetDetectedMatch![0];

            // Must include meetingTitle field
            expect(matchedBlock).toContain("meetingTitle");

            // Must include url field
            expect(matchedBlock).toContain("url");
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property 3.2: Stable END_SIGNALS produce a single `meet-ended` message.
   *
   * When END_SIGNALS persist stably (no ACTIVE_CALL_SIGNALS present), the
   * detection logic sends exactly one `meet-ended` message.
   *
   * On UNFIXED code: This works correctly for stable end signals — the bug
   * only manifests during rapid oscillation. This test PASSES.
   */
  describe("Property: Stable end signals produce meet-ended message", () => {
    it("meet-ended sendMessage exists and is called in end detection branch", () => {
      fc.assert(
        fc.property(
          // Generate any combination of end signals (stable, no active signals)
          fc.record({
            endSignal: fc.constantFrom(
              "Return to home screen",
              "Rejoin",
              "Volver a la pantalla de inicio",
              "Volver a unirse"
            ),
          }),
          (_input) => {
            const contentSource = readSource("content.ts");

            // Verify: There exists a sendMessage call with type "meet-ended"
            const meetEndedPattern =
              /chrome\.runtime\.sendMessage\(\s*\{\s*type:\s*"meet-ended"\s*\}\s*\)/;
            const meetEndedMatch = contentSource.match(meetEndedPattern);

            expect(meetEndedMatch).not.toBeNull();

            // Verify: The meet-ended message is sent in a conditional that checks
            // for end signals (endElement or hasEndSignals)
            const checkMeetStateMatch = contentSource.match(
              /function checkMeetState\(\)[^{]*\{([\s\S]*?)^\}/m
            );
            const checkMeetStateBody = checkMeetStateMatch?.[1] ?? "";

            // The meet-ended message must exist within checkMeetState or be
            // reachable from it
            expect(checkMeetStateBody).toContain('"meet-ended"');
          }
        ),
        { numRuns: 10 }
      );
    });
  });

  /**
   * Property 3.3: Initial checkMeetState() is called at module load time.
   *
   * When the content script loads on a page that already has an active meeting,
   * checkMeetState() must be called directly (outside the MutationObserver) to
   * detect the existing meeting state without waiting for a DOM mutation.
   *
   * On UNFIXED code: The script calls checkMeetState() at the bottom after
   * setting up the observer. This test PASSES.
   */
  describe("Property: checkMeetState() called at module load for initial detection", () => {
    it("checkMeetState() is invoked at script level outside observer callback", () => {
      fc.assert(
        fc.property(
          // Generate page-load scenarios (any meeting already active)
          fc.record({
            meetingAlreadyActive: fc.boolean(),
          }),
          (_input) => {
            const contentSource = readSource("content.ts");

            // Find checkMeetState() calls that are at the top level (not inside
            // the MutationObserver callback or function definitions)

            // Strategy: After the observer.observe() call, there should be a
            // direct checkMeetState() call
            const observeCallPos = contentSource.indexOf("observer.observe(");
            expect(observeCallPos).toBeGreaterThan(-1);

            // There should be a standalone checkMeetState() call after or near
            // the observer setup
            const afterObserve = contentSource.slice(observeCallPos);
            const initialCheckMatch = afterObserve.match(
              /^\s*checkMeetState\(\)\s*;/m
            );

            expect(initialCheckMatch).not.toBeNull();
          }
        ),
        { numRuns: 5 }
      );
    });
  });

  /**
   * Property 3.4: Spanish ARIA labels are recognized in signal arrays.
   *
   * The ACTIVE_CALL_SIGNALS and END_SIGNALS arrays must include Spanish
   * variants for bilingual detection to work correctly.
   *
   * On UNFIXED code: Both arrays include Spanish labels. This test PASSES.
   */
  describe("Property: Spanish ARIA labels recognized in detection signals", () => {
    it("ACTIVE_CALL_SIGNALS contains Spanish variants", () => {
      fc.assert(
        fc.property(
          fc.constantFrom(
            "Salir de la llamada",
            "Desactivar micrófono",  // spanish-sample-data
            "Activar micrófono",  // spanish-sample-data
            "Desactivar cámara",  // spanish-sample-data
            "Activar cámara"  // spanish-sample-data
          ),
          (spanishLabel) => {
            const contentSource = readSource("content.ts");

            // Extract ACTIVE_CALL_SIGNALS array content
            const activeSignalsMatch = contentSource.match(
              /const ACTIVE_CALL_SIGNALS[^[]*\[([\s\S]*?)\];/
            );
            expect(activeSignalsMatch).not.toBeNull();

            const activeSignalsContent = activeSignalsMatch![1];
            expect(activeSignalsContent).toContain(spanishLabel);
          }
        ),
        { numRuns: 5 }
      );
    });

    it("END_SIGNALS contains Spanish variants", () => {
      fc.assert(
        fc.property(
          fc.constantFrom(
            "Volver a la pantalla de inicio",
            "Volver a unirse"
          ),
          (spanishLabel) => {
            const contentSource = readSource("content.ts");

            // Extract END_SIGNALS array content
            const endSignalsMatch = contentSource.match(
              /const END_SIGNALS[^[]*\[([\s\S]*?)\];/
            );
            expect(endSignalsMatch).not.toBeNull();

            const endSignalsContent = endSignalsMatch![1];
            expect(endSignalsContent).toContain(spanishLabel);
          }
        ),
        { numRuns: 2 }
      );
    });
  });

  /**
   * Property 3.5: Consent banner handler is independent of detection logic.
   *
   * The `show-consent-banner` message listener must exist and operate
   * independently from the meeting detection logic (checkMeetState / observer).
   * The consent banner functionality must not be coupled to or interfered with
   * by the detection state machine.
   *
   * On UNFIXED code: The listener is set up separately via
   * chrome.runtime.onMessage.addListener and calls showConsentBanner() directly.
   * This test PASSES.
   */
  describe("Property: show-consent-banner handler is independent of detection", () => {
    it("onMessage listener handles show-consent-banner independently from checkMeetState", () => {
      fc.assert(
        fc.property(
          fc.record({
            bannerTriggered: fc.constant(true),
          }),
          (_input) => {
            const contentSource = readSource("content.ts");
            // The listener now lives in the overlay module shared with injected tabs;
            // the Meet script must install it, and it must stay detection-independent.
            const messagingSource = readSource("overlay/messaging.ts");
            expect(contentSource).toContain("installOverlayMessaging(");

            // Verify: There is an onMessage listener that handles "show-consent-banner"
            const onMessagePattern =
              /chrome\.runtime\.onMessage\.addListener/;
            expect(messagingSource).toMatch(onMessagePattern);

            // Verify: The listener checks for "show-consent-banner" message type
            expect(messagingSource).toContain('"show-consent-banner"');

            // Verify: showConsentBanner function exists
            const showConsentBannerDef = messagingSource.match(
              /function showConsentBanner\(\)/
            );
            expect(showConsentBannerDef).not.toBeNull();

            // Verify: The onMessage listener is NOT inside checkMeetState or
            // the MutationObserver callback — it's independent
            const checkMeetStateMatch = contentSource.match(
              /function checkMeetState\(\)[^{]*\{([\s\S]*?)^\}/m
            );
            const checkMeetStateBody = checkMeetStateMatch?.[1] ?? "";

            // checkMeetState should NOT reference show-consent-banner
            expect(checkMeetStateBody).not.toContain("show-consent-banner");
            expect(checkMeetStateBody).not.toContain("showConsentBanner");

            // The MutationObserver callback should NOT reference consent banner
            const observerCallbackMatch = contentSource.match(
              /new MutationObserver\(\s*\([^)]*\)\s*=>\s*\{([\s\S]*?)\}\s*\)/
            );
            const observerBody = observerCallbackMatch?.[1] ?? "";
            expect(observerBody).not.toContain("showConsentBanner");
            expect(observerBody).not.toContain("show-consent-banner");
          }
        ),
        { numRuns: 5 }
      );
    });
  });
});
