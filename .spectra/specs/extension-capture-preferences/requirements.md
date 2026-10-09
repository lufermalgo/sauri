# Requirements — Extension Capture and Preferences

## Introduction

This specification defines the extension's on-demand capture journey for a user-selected Google Meet tab and the two capture preferences in the owner-designated baseline snapshot: countdown duration and whether the floating recording indicator is shown. It also states the observable controls and outcomes expected when the indicator is visible, and how the user ends capture when it is hidden. These are product requirements for future evaluation, not claims about current implementation or verified audio/video reliability.

**Source authority note:** The owner-approved product content is the `PRODUCT_BASELINE.md` snapshot published in `main` at commit `d738e78d65940f17d209edf9a54af5d34e92e059` (blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`). The current baseline header and approval annotation in commit `22df139f204f6fe0cc2229d62173bfe0e86c274b` confirm approval of that exact product content; the later commit changed approval/status language only, not product scope. `PRODUCT_DISCOVERY.md` is discovery/traceability context, not approval or implementation authorization.

**Central thesis:** Capture starts only after the user deliberately selects the Google Meet tab, and the user has an explicit way to finish capture whether the floating indicator is visible or hidden.

**Scope:** Extension preferences for countdown duration and indicator visibility; deliberate, on-demand selection of a Google Meet Chrome tab; the configured countdown and expected audio/video capture; visible indicator timer, controls, and outcomes; and ending capture by stopping Chrome tab sharing when the indicator is hidden.

**Out of scope:** Exact selector composition/options and what happens if the user clicks record again after closing the selector without selecting a tab; countdown values/default; microphone selection persistence or effect; 720p or other resolution settings; alternate capture modes shown only in references; notes access and notes behavior (to avoid duplication, they belong in a distinct notes specification); processing feedback; consent/privacy governance; and cancel disposal or retention. Stopping is expected to store the recording in Sauri and start transcription, as specified below; this does not establish a technical reliability threshold.

## Glossary

- **Capture_Session**: An on-demand capture initiated from the Chrome extension for a user-selected Google Meet Chrome tab.
- **Countdown_Duration**: The duration configured in extension preferences and applied between selecting a tab and the start of recording.
- **Floating_Indicator**: The movable, in-recording extension control that the user may choose to show or hide.
- **Selected_Meet_Tab**: The Google Meet Chrome tab deliberately selected by the user for a Capture_Session.

## Requirements

### Requirement 1: Configure capture preferences

**User Story:** As a recorder, I want to configure the countdown duration and whether the floating indicator appears, so that capture follows my preferences.

#### Acceptance Criteria

1. THE Extension SHALL provide a user-accessible preference for selecting a Countdown_Duration.
2. THE Extension SHALL provide a user-accessible preference for showing or hiding the Floating_Indicator during a Capture_Session.
3. WHEN the user changes either preference, THE Extension SHALL apply the selected value to subsequent Capture_Sessions.
4. WHEN a Selected_Meet_Tab is selected, THE Extension SHALL display a countdown for the configured Countdown_Duration and begin recording only after that duration elapses.
5. THE Extension SHALL NOT require a particular Countdown_Duration default, value, or option list; those choices remain open.

**Traceability:** Approved `PRODUCT_BASELINE.md` content (`d738e78`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`; approval recorded by `22df139`), §§3 and 5 (countdown and indicator-visibility preferences); `PRODUCT_DISCOVERY.md` (commit `a8cb4adaeb9320ddc59999c174825fb5a489e86f`, blob `261cc6f3ec17db462aa1e2ff6fd13e3c8f07c90d`), 2026-10-09 “Referencias de controles de la extensión y visibilidad del indicador” and “Precisión de diarización e indicador flotante” (the preference includes showing/hiding the floating indicator; screenshot values are not choices).

### Requirement 2: Start capture only after deliberate Meet-tab selection

**User Story:** As a recorder, I want to select the Google Meet tab before capture begins, so that the extension captures the meeting I chose rather than starting implicitly.

#### Acceptance Criteria

1. WHEN the user initiates “record session” from the Chrome extension, THE Extension SHALL open a browser tab-selection flow in which the user can deliberately select a Selected_Meet_Tab.
2. WHEN the user closes the tab-selection flow without selecting a tab, THE Extension SHALL NOT start a Capture_Session.
3. WHEN the user selects a Selected_Meet_Tab, THE Extension SHALL run the configured Countdown_Duration before recording begins.
4. WHEN the configured Countdown_Duration elapses after selection, THE Extension SHALL begin recording the Selected_Meet_Tab with both audio and video included in the Capture_Session; this criterion sets no quality or reliability threshold.
5. THE Extension SHALL NOT start a Capture_Session unless the user explicitly initiates recording and selects a Selected_Meet_Tab.
6. THE Extension capture journey SHALL be limited to a user-selected Google Meet Chrome tab; it SHALL NOT require whole-window or full-screen capture.

**Traceability:** Approved `PRODUCT_BASELINE.md` content (`d738e78`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`; approval recorded by `22df139`), §§3, 4.A items 1–3, 5, and 6 (on-demand selected Meet-tab capture); `PRODUCT_DISCOVERY.md` (commit `a8cb4adaeb9320ddc59999c174825fb5a489e86f`, blob `261cc6f3ec17db462aa1e2ff6fd13e3c8f07c90d`), 2026-10-09 “Precisión del flujo de grabación bajo demanda” (tab selection, configured countdown, and audio/video expectation) and “Referencia visual de selector de pestaña/ventana/pantalla” (reference does not determine selector technology/options).

**Boundary:** “Expected audio and video” records the product expectation; it is not a technical reliability guarantee or a claim that existing code satisfies it. The selector's exact composition/options and the result of clicking record again after closing without selection remain open (`PRODUCT_BASELINE.md` §7.4; `PRODUCT_DISCOVERY.md`, 2026-10-09 “Cerrar el selector sin elegir una pestaña”).

### Requirement 3: Provide the expected controls when the indicator is visible

**User Story:** As a recorder who shows the floating indicator, I want to see elapsed time and capture controls, so that I can monitor and manage an active capture.

#### Acceptance Criteria

1. WHERE the user has enabled the Floating_Indicator, WHEN a Capture_Session is recording, THE Extension SHALL display the Floating_Indicator with a timer showing elapsed recording time.
2. WHERE the Floating_Indicator is displayed, THE Extension SHALL provide controls to cancel, pause, resume, and stop the Capture_Session.
3. WHEN the user cancels a Capture_Session, THE Extension SHALL end capture without triggering another action; this requirement does not define disposal or retention of captured data.
4. WHEN the user pauses a Capture_Session, THE Extension SHALL temporarily pause capture and allow the user to resume that Capture_Session.
5. WHEN the user resumes a paused Capture_Session, THE Extension SHALL continue capture in that Capture_Session.
6. WHEN the user stops a Capture_Session from the Floating_Indicator, THE Extension SHALL end recording, store the recording in Sauri, and start transcription.
7. WHERE the Floating_Indicator is displayed, THE Extension SHALL provide a microphone-selection control; this requirement does not define selection persistence or its effect on capture.
8. WHERE the Floating_Indicator is displayed, THE Extension SHALL allow the user to move it to another on-screen position.

**Traceability:** Approved `PRODUCT_BASELINE.md` content (`d738e78`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`; approval recorded by `22df139`), §4.A item 4 and §5 (visible indicator and capture controls); `PRODUCT_DISCOVERY.md` (commit `a8cb4adaeb9320ddc59999c174825fb5a489e86f`, blob `261cc6f3ec17db462aa1e2ff6fd13e3c8f07c90d`), 2026-10-09 “Controles esperados durante la grabación,” “Precisión sobre cancelar, pausar y detener,” and “Precisión de diarización e indicador flotante” (visible timer, cancel/pause/resume/stop, microphone selector, and movement; stop outcome stored in the baseline is specified above).

### Requirement 4: End capture when the indicator is hidden

**User Story:** As a recorder who hides the floating indicator, I want to end capture by stopping tab sharing, so that capture remains controllable without an on-screen indicator.

#### Acceptance Criteria

1. WHERE the user has disabled the Floating_Indicator, WHEN a Capture_Session is recording, THE Extension SHALL NOT display the Floating_Indicator or require in-recording controls.
2. WHERE the Floating_Indicator is hidden, WHEN the user stops sharing the Selected_Meet_Tab, THE Extension SHALL end the Capture_Session, store the recording in Sauri, and start transcription.
3. THE Extension SHALL NOT require an additional hidden or alternate in-recording control to end capture when the Floating_Indicator is hidden.

**Traceability:** Approved `PRODUCT_BASELINE.md` content (`d738e78`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`; approval recorded by `22df139`), §§3, 4.A items 4–5, and 5–6 (hiding is intentional, no in-recording controls required, end by stopping tab sharing); `PRODUCT_DISCOVERY.md` (commit `a8cb4adaeb9320ddc59999c174825fb5a489e86f`, blob `261cc6f3ec17db462aa1e2ff6fd13e3c8f07c90d`), 2026-10-09 “Precisiones sobre captura, diarización, notas, portal y CRM” (latest clarification that stopping sharing ends capture and no hidden control is inferred).

**Boundary:** Notes access is intentionally not specified in this capture/preferences artifact; the notes access journey belongs in a distinct notes specification to avoid duplicate criteria. Access when the indicator is hidden remains an open product/design boundary (`PRODUCT_BASELINE.md` §§4.A.4, 7.5).

### Requirement 5: Preserve unresolved decisions and scope boundaries

**User Story:** As a product owner, I want unresolved choices and adjacent product areas kept outside these requirements, so that the specification does not silently decide product behavior.

#### Acceptance Criteria

1. THE Extension capture feature SHALL NOT define the exact tab-selector composition/options or the behavior after the selector closes without a selection and the user clicks record again.
2. THE Extension capture feature SHALL NOT define a countdown default, values, or option list; the screenshot's “3s” is not a confirmed value.
3. THE Extension capture feature SHALL NOT define microphone-selection persistence or effect, a 720p requirement, or alternate capture modes shown only in visual references.
4. THE Extension capture feature SHALL NOT define notes access or note creation/content, processing feedback, a consent workflow, privacy/data-governance policy, or cancel disposal/retention.
5. THE Extension capture feature SHALL NOT define transcript editing, speaker review, web meeting-library behavior, or CRM/CRM-AI behavior.

**Traceability:** Approved `PRODUCT_BASELINE.md` content (`d738e78`, blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`; approval recorded by `22df139`), §§4.A, 6–7 (selector, notes, processing, privacy/governance boundaries, and non-goals); `PRODUCT_DISCOVERY.md` (commit `a8cb4adaeb9320ddc59999c174825fb5a489e86f`, blob `261cc6f3ec17db462aa1e2ff6fd13e3c8f07c90d`), 2026-10-09 “Referencias de controles de la extensión y visibilidad del indicador,” “Referencia visual de selector de pestaña/ventana/pantalla,” “Cerrar el selector sin elegir una pestaña,” and “Precisiones sobre captura, diarización, notas, portal y CRM” (visual-only settings and unresolved interactions).

## Traceability Summary

The owner-approved source is the product content of `PRODUCT_BASELINE.md` published in `main` at commit `d738e78d65940f17d209edf9a54af5d34e92e059` (blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`), as confirmed by the checked-in approval header and annotation in commit `22df139f204f6fe0cc2229d62173bfe0e86c274b`; the later annotation changed no product scope. Requirement-level traceability above cites applicable baseline sections and dated discovery decisions; later discovery clarifications prevail where noted. `PRODUCT_DISCOVERY.md` at commit `a8cb4adaeb9320ddc59999c174825fb5a489e86f` (blob `261cc6f3ec17db462aa1e2ff6fd13e3c8f07c90d`) informs traceability but is not itself baseline approval or implementation authorization. Existing development is current-state evidence only—not product acceptance or authorization to extend without evaluating it against approved requirements and evidence. This requirements document is not self-approved, and no product acceptance is claimed.
