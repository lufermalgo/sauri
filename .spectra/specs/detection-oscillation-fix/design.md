# Detection Oscillation Fix — Bugfix Design

## Overview

The content script's `checkMeetState()` function in `extension/src/content.ts` oscillates between sending `meet-detected` and `meet-ended` messages during transient DOM changes. The fix introduces a debounced state machine that prevents rapid state flipping by requiring signal persistence before accepting transitions. The approach is minimal: replace the raw `MutationObserver → checkMeetState()` call with a debounced evaluation, add signal priority logic, and implement a confirmation period for the `ended` state.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the oscillation — rapid DOM mutations cause `checkMeetState()` to fire repeatedly, and transient END_SIGNAL appearances cause premature `meet-ended` messages during an active call.
- **Property (P)**: The desired behavior — state transitions only occur after signals persist beyond debounce and confirmation periods, producing exactly one message per genuine transition.
- **Preservation**: Existing behavior that must remain unchanged — genuine meeting detection, genuine meeting end detection, initial state check, consent banner display, and bilingual ARIA label recognition.
- **checkMeetState()**: The function in `extension/src/content.ts` that evaluates DOM signals to determine meeting state and sends messages to the background service worker.
- **ACTIVE_CALL_SIGNALS**: ARIA labels indicating an active call (e.g., "Leave call", "Salir de la llamada").
- **END_SIGNALS**: ARIA labels indicating a meeting has ended (e.g., "Return to home screen", "Volver a la pantalla de inicio").
- **State Machine**: The new `idle → active → ending → ended` lifecycle that gates message emission.

## Bug Details

### Bug Condition

The bug manifests when the MutationObserver fires `checkMeetState()` on every DOM mutation (100s/sec during transitions), there is no priority logic when both ACTIVE_CALL_SIGNALS and END_SIGNALS coexist, and the mutual flag reset (`meetDetected`/`meetEnded`) allows infinite re-triggering.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { mutations: DOMmutation[], currentState: MeetState, elapsedSinceLastEval: number }
  OUTPUT: boolean

  hasActiveSignals := EXISTS label IN ACTIVE_CALL_SIGNALS WHERE document.querySelector('[aria-label="' + label + '"]') != null
  hasEndSignals := EXISTS label IN END_SIGNALS WHERE document.querySelector('[aria-label="' + label + '"]') != null

  RETURN (
    (hasEndSignals AND hasActiveSignals AND currentState == 'active')
    OR (hasEndSignals AND currentState == 'active' AND elapsedSinceLastEval < 500)
    OR (input.mutations.length > 1 AND elapsedSinceLastEval < 100)
  )
END FUNCTION
```

### Examples

- **Participant join re-render**: User is in active call, someone joins, Meet re-renders UI → END_SIGNAL element flashes for ~200ms → current code sends `meet-ended` → active signals reappear → sends `meet-detected` again. **Expected**: No messages sent (transient).
- **Screen share toggle**: User toggles screen share → DOM thrashes with 50+ mutations in 300ms → multiple redundant evaluations fire. **Expected**: Single evaluation after DOM settles.
- **Both signals present**: During transition, both "Leave call" and "Return to home screen" exist in DOM simultaneously. **Expected**: ACTIVE_CALL_SIGNALS take priority, state stays `active`.
- **Genuine meeting end**: User clicks "Leave call" → END_SIGNALS persist for 3+ seconds, no ACTIVE_CALL_SIGNALS present. **Expected**: Single `meet-ended` sent after confirmation period.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Genuine meeting detection: when ACTIVE_CALL_SIGNALS appear and persist, a single `meet-detected` message is sent with title and URL
- Genuine meeting end: when END_SIGNALS persist and ACTIVE_CALL_SIGNALS are absent for the confirmation period, a single `meet-ended` message is sent
- Initial state check on content script load detects an already-active meeting
- Consent banner display via `show-consent-banner` message works without interference
- Both English and Spanish ARIA label variants are recognized

**Scope:**
All inputs that do NOT involve transient signal appearances or rapid DOM mutations during transitions should be completely unaffected by this fix. This includes:
- Stable meeting states (user is solidly in a call with no transitions)
- Consent banner interactions
- Page loads on already-active meetings
- Non-Meet DOM mutations (unrelated elements)

## Hypothesized Root Cause

Based on the bug description and code analysis of `extension/src/content.ts`:

1. **No Debounce on MutationObserver**: The observer calls `checkMeetState()` synchronously on every mutation. During UI transitions, this means hundreds of evaluations per second, each potentially sending messages.

2. **No Signal Priority Logic**: Lines checking `endElement` run before `activeElement` check, and there's no guard for the case where both exist simultaneously. The first `endElement` found immediately triggers `meet-ended`.

3. **Mutual Flag Reset Creates Re-entry**: When `meet-ended` fires, it sets `meetDetected = false`. When active signals reappear and `checkMeetState()` fires again, `!meetDetected` is true, so it re-sends `meet-detected`. This creates the oscillation loop:
   - `endElement` found → `meetEnded = true`, `meetDetected = false` → sends `meet-ended`
   - `activeElement` found → `meetDetected = true`, `meetEnded = false` → sends `meet-detected`
   - Cycle repeats on next mutation

4. **No Confirmation Period**: The code immediately accepts any signal detection as final. There's no waiting to confirm that END_SIGNALS persist before committing to the `ended` state.

## Correctness Properties

Property 1: Bug Condition — No Oscillation During Transient DOM Changes

_For any_ sequence of DOM mutations where END_SIGNALS appear transiently (less than debounce + confirmation period) while ACTIVE_CALL_SIGNALS are also present or reappear quickly, the fixed detection logic SHALL NOT send any `meet-ended` message and SHALL NOT send duplicate `meet-detected` messages. At most one `meet-detected` message is sent per genuine meeting join.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6**

Property 2: Preservation — Genuine State Transitions Still Work

_For any_ input where the bug condition does NOT hold (signals persist stably beyond debounce + confirmation periods), the fixed detection logic SHALL produce the same observable outcome as the original: exactly one `meet-detected` when genuinely joining and exactly one `meet-ended` when genuinely leaving, preserving meeting title extraction, URL reporting, bilingual signal recognition, and consent banner functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `extension/src/content.ts`

**Function**: `checkMeetState()` and `MutationObserver` callback

**Specific Changes**:

1. **Add Debounce to MutationObserver Callback**: Replace the direct `checkMeetState()` call with a debounced version (~500ms). Use a simple `setTimeout`/`clearTimeout` pattern — no external dependencies needed.
   - Clear any pending timeout on each mutation
   - Set a new timeout to call `checkMeetState()` after 500ms of DOM quiet

2. **Implement State Machine**: Replace boolean flags (`meetDetected`, `meetEnded`) with an explicit state variable:
   ```
   type MeetState = 'idle' | 'active' | 'ending' | 'ended'
   let meetState: MeetState = 'idle'
   ```
   - `idle`: No meeting detected yet
   - `active`: Meeting confirmed active (message sent)
   - `ending`: END_SIGNALS detected, waiting confirmation
   - `ended`: Confirmed ended (message sent)

3. **Add Signal Priority Logic**: In the debounced `checkMeetState()`, check ACTIVE_CALL_SIGNALS first. If active signals are present, state should be `active` regardless of END_SIGNALS presence.
   - If `hasActiveSignals`: state → `active` (cancel any ending timeout)
   - If `hasEndSignals AND NOT hasActiveSignals`: state → `ending` (start confirmation timer)

4. **Add Confirmation Period for Ending**: When transitioning to `ending`, start a 2-second confirmation timer. If ACTIVE_CALL_SIGNALS reappear during this window (detected by the next debounced check), cancel the timer and return to `active`.
   - Use a separate `setTimeout` for the confirmation period
   - On confirmation timeout expiry: transition to `ended`, send `meet-ended`

5. **Deduplication Guards**: Only send messages on actual state transitions:
   - Send `meet-detected` only on transition `idle → active` or `ended → active`
   - Send `meet-ended` only on transition `ending → ended` (after confirmation)
   - No message on `active → active` or `ending → active` (cancelled transition)

6. **Preserve Initial Check**: Keep the `checkMeetState()` call at script load, but run it through the same state machine logic (can be called directly for initial check, bypassing debounce since there are no prior mutations to settle).

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate rapid DOM mutations with transient signal appearances and assert on message-sending behavior. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Rapid Mutation Test**: Simulate 50 mutations in 300ms with END_SIGNAL flashing — verify `meet-ended` is incorrectly sent (will fail expectation on unfixed code)
2. **Both Signals Present Test**: Add both ACTIVE_CALL_SIGNALS and END_SIGNALS elements simultaneously — verify END takes incorrect priority (will fail on unfixed code)
3. **Oscillation Loop Test**: Simulate signal appearing/disappearing in alternation — verify multiple messages are sent (will fail on unfixed code)
4. **No Debounce Test**: Fire single mutation with END_SIGNAL while active — verify immediate message without waiting (will fail on unfixed code)

**Expected Counterexamples**:
- Multiple `meet-ended` and `meet-detected` messages sent within seconds
- `meet-ended` sent while ACTIVE_CALL_SIGNALS are still in the DOM
- Possible causes: no debounce, no priority logic, mutual flag reset

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := checkMeetState_fixed(input)
  ASSERT noMessageSent(result) OR singleCorrectMessage(result)
  ASSERT stateTransitionCount(result) <= 1
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT checkMeetState_original(input).messagesEmitted = checkMeetState_fixed(input).messagesEmitted
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for genuine state transitions (stable signals), then write property-based tests capturing that behavior persists after the fix.

**Test Cases**:
1. **Genuine Join Preservation**: Observe that stable ACTIVE_CALL_SIGNALS produce exactly one `meet-detected` on unfixed code, then verify this continues after fix
2. **Genuine Leave Preservation**: Observe that stable END_SIGNALS (no active signals) produce exactly one `meet-ended` on unfixed code, then verify this continues after fix
3. **Initial Check Preservation**: Observe that loading on an already-active page detects the meeting, then verify this continues after fix
4. **Consent Banner Preservation**: Observe that `show-consent-banner` messages work correctly, then verify no interference after fix
5. **Bilingual Detection Preservation**: Observe that Spanish ARIA labels are recognized, then verify this continues after fix

### Unit Tests

- Test debounce: rapid mutations within 500ms produce only one evaluation
- Test state machine transitions: `idle → active`, `active → ending`, `ending → ended`, `ending → active` (cancellation)
- Test signal priority: ACTIVE_CALL_SIGNALS override END_SIGNALS when both present
- Test confirmation period: `ending` state requires 2s without active signals before sending `meet-ended`
- Test deduplication: repeated stable states produce no additional messages
- Test initial check: direct call on script load correctly detects active meeting

### Property-Based Tests

- Generate random sequences of DOM mutation events with varying signal combinations and timing, verify at most one `meet-detected` and one `meet-ended` per genuine transition
- Generate random interleaving of active and end signals with random durations, verify no oscillation occurs
- Generate stable signal scenarios (signals persist > debounce + confirmation), verify correct messages are always sent

### Integration Tests

- Full lifecycle: page load → meeting join → stable call → meeting leave → verify exactly two messages total (`meet-detected`, `meet-ended`)
- Transient disruption: active call → brief signal flash → verify no spurious messages
- Rapid reconnection: meeting end signals appear then active signals return within 2s → verify no `meet-ended` sent
