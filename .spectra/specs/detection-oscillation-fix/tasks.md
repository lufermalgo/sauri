# Implementation Plan

## Overview

Fix the detection oscillation bug in `extension/src/content.ts` by replacing boolean flags with a state machine, adding debounce to the MutationObserver, implementing signal priority logic, and requiring a confirmation period before accepting meeting-ended state. All changes are confined to a single file.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1", "2"],
      "description": "Write exploration and preservation tests on unfixed code"
    },
    {
      "wave": 2,
      "tasks": ["3.1", "3.2"],
      "description": "Replace boolean flags with state machine and add debounce"
    },
    {
      "wave": 3,
      "tasks": ["3.3", "3.4", "3.5"],
      "description": "Add signal priority, confirmation period, and deduplication guards"
    },
    {
      "wave": 4,
      "tasks": ["3.6"],
      "description": "Preserve initial state check on page load"
    },
    {
      "wave": 5,
      "tasks": ["3.7", "3.8"],
      "description": "Verify exploration and preservation tests pass on fixed code"
    },
    {
      "wave": 6,
      "tasks": ["4"],
      "description": "Final checkpoint — all tests pass"
    }
  ]
}
```

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** — Detection Oscillation During Transient DOM Changes
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the oscillation bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases:
    - Simulate rapid DOM mutations where END_SIGNALS appear transiently (<500ms) while ACTIVE_CALL_SIGNALS are present or reappear quickly
    - Simulate both ACTIVE_CALL_SIGNALS and END_SIGNALS present simultaneously during an active call
  - Bug Condition from design: `isBugCondition(input)` holds when:
    - `hasEndSignals AND hasActiveSignals AND currentState == 'active'`
    - OR `hasEndSignals AND currentState == 'active' AND elapsedSinceLastEval < 500`
    - OR `mutations.length > 1 AND elapsedSinceLastEval < 100`
  - Test asserts: for inputs satisfying bug condition, no `meet-ended` message is sent and no duplicate `meet-detected` messages are sent (at most one `meet-detected` per genuine join)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct — it proves the bug exists because current code sends spurious messages)
  - Document counterexamples found (e.g., "meet-ended sent while ACTIVE_CALL_SIGNALS still present", "oscillation: meet-ended → meet-detected → meet-ended in <1s")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** — Genuine State Transitions Still Work
  - **IMPORTANT**: Follow observation-first methodology
  - **IMPORTANT**: Write these tests BEFORE implementing the fix
  - Observe behavior on UNFIXED code for non-buggy inputs (stable signals, no transient flashing):
    - Observe: stable ACTIVE_CALL_SIGNALS (persisting >2s, no END_SIGNALS) → single `meet-detected` with title and URL
    - Observe: stable END_SIGNALS (persisting >2s, no ACTIVE_CALL_SIGNALS) → single `meet-ended`
    - Observe: page load on already-active meeting → initial `checkMeetState()` detects meeting
    - Observe: Spanish ARIA labels ("Salir de la llamada", "Volver a la pantalla de inicio") are recognized
    - Observe: `show-consent-banner` message triggers banner display without interference
  - Write property-based tests: for all inputs where `NOT isBugCondition(input)` (signals persist stably beyond debounce + confirmation periods), the detection logic produces:
    - Exactly one `meet-detected` when genuinely joining (with correct title and URL)
    - Exactly one `meet-ended` when genuinely leaving
    - Bilingual ARIA label recognition preserved
    - Consent banner functionality unaffected
  - Verify tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix detection oscillation in content script

  - [x] 3.1 Replace boolean flags with state machine
    - Replace `let meetDetected = false` and `let meetEnded = false` with:
      - `type MeetState = 'idle' | 'active' | 'ending' | 'ended'`
      - `let meetState: MeetState = 'idle'`
    - Remove the old boolean flag declarations
    - _Bug_Condition: isBugCondition(input) — mutual flag reset (`meetDetected = false` / `meetEnded = false`) allows infinite re-triggering_
    - _Expected_Behavior: State machine prevents re-entry; only valid transitions emit messages_
    - _Preservation: State semantics map 1:1 to old behavior for stable signals_
    - _Requirements: 2.1, 2.2, 2.6_

  - [x] 3.2 Add debounce to MutationObserver callback
    - Replace direct `checkMeetState()` call in MutationObserver with `clearTimeout`/`setTimeout` pattern
    - Debounce period: 500ms of DOM quiet before evaluating state
    - Each new mutation resets the timer (clear + set)
    - _Bug_Condition: No debounce causes 100s of evaluations per second during UI transitions_
    - _Expected_Behavior: Only evaluate state once DOM has been stable for 500ms_
    - _Preservation: Genuine state changes (signals persist >500ms) still detected_
    - _Requirements: 2.3_

  - [x] 3.3 Add signal priority logic
    - In `checkMeetState()`, check ACTIVE_CALL_SIGNALS first
    - If `hasActiveSignals` is true: state should be `active` regardless of END_SIGNALS presence
    - If `hasEndSignals AND NOT hasActiveSignals`: begin ending transition
    - Cancel any pending ending confirmation if active signals reappear
    - _Bug_Condition: END_SIGNALS checked first without priority causes premature meet-ended when both signals coexist_
    - _Expected_Behavior: ACTIVE_CALL_SIGNALS override END_SIGNALS; state stays active_
    - _Preservation: When only END_SIGNALS are present (genuine leave), behavior unchanged_
    - _Requirements: 2.4_

  - [x] 3.4 Add confirmation period for ending state
    - When transitioning to `ending` state, start a 2-second confirmation timer
    - If ACTIVE_CALL_SIGNALS reappear during the 2s window (next debounced check), cancel the timer and return to `active`
    - On timer expiry without active signals: transition to `ended`, send `meet-ended` message
    - _Bug_Condition: Immediate acceptance of END_SIGNALS without confirmation allows transient signals to trigger false ends_
    - _Expected_Behavior: END_SIGNALS must persist 2s without active signal reappearance before accepting ended state_
    - _Preservation: Genuine meeting ends (signals persist >2s) still produce meet-ended within ~2.5s total_
    - _Requirements: 2.5_

  - [x] 3.5 Add deduplication guards for message sending
    - Send `meet-detected` only on transitions: `idle → active` or `ended → active`
    - Send `meet-ended` only on transition: `ending → ended` (after confirmation period)
    - No message on `active → active` (stable state) or `ending → active` (cancelled transition)
    - _Bug_Condition: Mutual flag reset allows repeated message sending on same logical state_
    - _Expected_Behavior: At most one message per genuine state transition_
    - _Preservation: One meet-detected per join, one meet-ended per leave — same as before for stable scenarios_
    - _Requirements: 2.6_

  - [x] 3.6 Preserve initial state check on page load
    - Keep the direct `checkMeetState()` call at script load (not debounced)
    - Ensure it runs through the same state machine logic
    - Initial check can bypass debounce since there are no prior mutations to settle
    - _Preservation: Initial detection of already-active meeting continues to work_
    - _Requirements: 3.3_

  - [x] 3.7 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — No Oscillation During Transient DOM Changes
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior (no spurious messages during transient DOM changes)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [x] 3.8 Verify preservation tests still pass
    - **Property 2: Preservation** — Genuine State Transitions Still Work
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint — Ensure all tests pass
  - Run project typecheck to validate TypeScript compiles
  - Run all property-based tests (bug condition + preservation)
  - Ensure no regressions in existing functionality
  - Ask the user if questions arise

## Notes

- Tasks 1 and 2 MUST be completed before task 3 (write tests on unfixed code first)
- All implementation changes are in a single file: `extension/src/content.ts`
- The state machine (`idle → active → ending → ended`) replaces the boolean flags that caused the oscillation loop
- Debounce (500ms) + confirmation period (2s) means genuine meeting ends are detected within ~2.5s — acceptable tradeoff for eliminating oscillation
- Property-based tests should mock `chrome.runtime.sendMessage` and simulate DOM mutations with `document.querySelector` returning controlled elements
- The initial `checkMeetState()` call at script load bypasses debounce intentionally (no prior mutations to settle)
