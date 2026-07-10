# Bugfix Requirements Document

## Introduction

The content script (`extension/src/content.ts`) oscillates between sending `meet-detected` and `meet-ended` messages to the background service worker. This causes the extension state to flip rapidly between "pending" and "idle", confusing the user and potentially interrupting active recordings. The root cause is that `checkMeetState()` fires on every DOM mutation without debounce, has no priority logic when both active and end signals coexist, and uses mutual flag resets that allow infinite re-triggering.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN Google Meet re-renders its UI during an active call (participant joins/leaves, screen share toggle, network reconnection) AND an END_SIGNAL element briefly appears in the DOM THEN the system sends a `meet-ended` message and resets `meetDetected = false`

1.2 WHEN the DOM stabilizes after a transient re-render AND ACTIVE_CALL_SIGNALS reappear THEN the system sends a new `meet-detected` message, creating an oscillation loop between `meet-detected` and `meet-ended`

1.3 WHEN multiple DOM mutations fire in rapid succession (100s per second during UI transitions) THEN the system evaluates `checkMeetState()` on every single mutation without any debounce, causing redundant state evaluations and message sends

1.4 WHEN both ACTIVE_CALL_SIGNALS and END_SIGNALS are present simultaneously in the DOM during a transition THEN the system treats the first END_SIGNAL found as authoritative and fires `meet-ended`, ignoring that active call buttons are still present

### Expected Behavior (Correct)

2.1 WHEN Google Meet re-renders its UI during an active call AND an END_SIGNAL element briefly appears in the DOM THEN the system SHALL NOT immediately send `meet-ended`; it SHALL wait for the DOM to settle (debounce period) before evaluating state

2.2 WHEN ACTIVE_CALL_SIGNALS reappear within the debounce/settling window after a transient END_SIGNAL appearance THEN the system SHALL cancel any pending state transition and SHALL NOT send `meet-ended` or a duplicate `meet-detected` message

2.3 WHEN multiple DOM mutations fire in rapid succession THEN the system SHALL debounce `checkMeetState()` evaluations, only evaluating state once the DOM has been stable for a minimum period (e.g., 500ms)

2.4 WHEN both ACTIVE_CALL_SIGNALS and END_SIGNALS are present simultaneously in the DOM THEN the system SHALL prioritize ACTIVE_CALL_SIGNALS and remain in the "meeting detected" state

2.5 WHEN a `meet-ended` state is detected after debounce THEN the system SHALL require the ended state to persist for a confirmation period (e.g., 2 seconds) without ACTIVE_CALL_SIGNALS reappearing before accepting the transition as final and sending the `meet-ended` message

2.6 WHEN the evaluated state after debounce is the same as the current known state THEN the system SHALL NOT send any message to the background service worker (no duplicate messages)

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a user genuinely joins a Google Meet call AND ACTIVE_CALL_SIGNALS appear and persist in the DOM THEN the system SHALL CONTINUE TO detect the meeting and send a single `meet-detected` message with the meeting title and URL

3.2 WHEN a user genuinely leaves a Google Meet call AND END_SIGNALS persist while ACTIVE_CALL_SIGNALS are absent THEN the system SHALL CONTINUE TO detect the meeting end and send a single `meet-ended` message

3.3 WHEN the content script is first loaded on a Google Meet page that is already in an active call THEN the system SHALL CONTINUE TO perform an initial state check and detect the active meeting

3.4 WHEN the background service worker sends a `show-consent-banner` message THEN the system SHALL CONTINUE TO display the consent banner in Shadow DOM without interference from detection logic changes

3.5 WHEN ARIA labels in Spanish or English variants are used by Google Meet THEN the system SHALL CONTINUE TO recognize both language variants for all detection signals
