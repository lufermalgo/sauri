# Requirements — Meeting Review Playback

## Introduction

This specification defines the approved playback and transcript-linking behaviors for meeting media in the meeting review experience. Users need to control ordinary playback and relate the currently playing moment to the corresponding transcript passage, or start playback from a selected passage.

**Core idea:** Meeting media and transcript behave as synchronized representations during review, while the user retains ordinary control over playback.

**Approved scope:** Seek, playback speed, quality/resolution selection, pause/resume, volume, mute/unmute, playback-synchronized transcript highlighting, and starting playback from the linked time of a selected transcript paragraph or fragment by activating its associated control.

**Explicit exclusions:** Transcript editing is deferred and not approved. This specification does not add or define a meeting library, notes, summary, metadata, or unrelated meeting-view behavior. It does not prescribe the exact playback control, time representation, or video-specific behavior; those are design boundaries. It also does not prescribe layout, styling, implementation, or particular speed/quality values.

**Traceability:** This scope is grounded in the owner-approved `PRODUCT_BASELINE.md` content published at commit `d738e78d65940f17d209edf9a54af5d34e92e059` (blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`), particularly §4.C.4 and the “Meeting playback with transcript time synchronization and jump-from-fragment” capability in §5. Relevant discovery context is `PRODUCT_DISCOVERY.md` §2.3 (meeting view), §5.13 (playback details pending design), and §7, “2026-10-09 — Precisiones sobre captura, diarización, notas, portal y CRM.” These references establish approved behavior while leaving the identified control, time representation, and video-specific details to design; they do not reopen settled scope.

Existing implementation and tests are current-state evidence only. Their presence or behavior is not product acceptance and does not authorize extending or treating existing behavior as approved without evaluation against these approved requirements and the cited evidence.

## Glossary

- **Meeting_View**: The user-facing meeting review view in which Meeting_Media and its Transcript are presented for review.
- **Meeting_Media**: The recorded media being reviewed in the meeting view.
- **Functional_User**: The person using Sauri to review meeting media and its transcript.
- **Transcript**: The meeting's text divided into passages associated with meeting-media times where available.
- **Transcript_Passage**: A paragraph or fragment of transcript text with an associated meeting-media time.
- **Playback_Control**: The user-operable control associated with a Transcript_Passage that initiates playback from that passage's linked time; its exact form is for design.

## Requirements

### Requirement 1: Ordinary media controls

**User Story:** As a Functional_User, I want ordinary controls for meeting playback, so I can review the recording at my own pace.

#### Acceptance Criteria

1. WHEN Meeting_Media is available for playback, THE Meeting_View SHALL provide a way to seek to a user-selected position in the media.
2. WHEN Meeting_Media is playing, THE Meeting_View SHALL provide a way to pause playback.
3. WHEN Meeting_Media is paused, THE Meeting_View SHALL provide a way to resume playback.
4. WHEN Meeting_Media is available for playback, THE Meeting_View SHALL provide a way for the Functional_User to select a playback speed. WHEN the Functional_User selects a playback speed, THE Meeting_View SHALL play Meeting_Media at that selected speed.
5. WHEN Meeting_Media has more than one available quality or resolution, THE Meeting_View SHALL let the Functional_User select among those options and SHALL apply the selected option to playback.
6. WHEN Meeting_Media has audio, THE Meeting_View SHALL provide a way to adjust its playback volume.
7. WHEN Meeting_Media has audio, THE Meeting_View SHALL provide a way to mute and unmute its playback audio.

### Requirement 2: Highlight transcript passage during playback

**User Story:** As a Functional_User, I want the transcript passage for the current media time to be highlighted, so I can follow which words correspond to playback.

#### Acceptance Criteria

1. WHILE Meeting_Media is playing, THE Meeting_View SHALL visibly highlight the Transcript_Passage associated with the current playback time.
2. WHEN playback reaches a time associated with a different Transcript_Passage, THE Meeting_View SHALL move the visible highlight to that passage.

### Requirement 3: Start playback from a transcript passage

**User Story:** As a Functional_User, I want to select a transcript paragraph or fragment and activate its associated control, so I can review the media from that passage.

#### Acceptance Criteria

1. WHEN the Functional_User activates the Playback_Control associated with a selected Transcript_Passage, THE Meeting_View SHALL start Meeting_Media playback from that passage's linked time.

### Requirement 4: Scope boundaries

**User Story:** As a Functional_User, I want the playback behavior to stay within approved scope, so that deferred and unrelated capabilities are not treated as part of this feature.

#### Acceptance Criteria

1. THE Meeting_View SHALL NOT provide transcript editing as a behavior required by this specification.
2. THE Meeting_View SHALL NOT treat a meeting library, notes, summary, metadata, or other unrelated meeting-view behavior as requirements of this specification.
3. THE Meeting_View SHALL NOT require a particular Playback_Control form, time representation, or video-specific behavior under this specification.
4. THE Meeting_View SHALL NOT require a particular playback-speed value or quality/resolution option under this specification.
