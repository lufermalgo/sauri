# Requirements — Owner-Run Speaker-Recognition Test Screen

## Introduction

Fer requested a minimal portal screen for personally exercising speaker recognition end to end: upload an audio or video recording, see processing progress, inspect the resulting transcript with speaker labels and timestamps, and use speaker review to name or correct speakers. The approved product baseline describes transcription and speaker identification, honest unresolved attribution as `Speaker N`, and human review/correction of speaker names. This screen is a narrow owner-testing surface for those capabilities, not a redesign of the portal.

**Thesis:** A single minimal screen should let its user exercise the recording-to-speaker-review path while preserving the baseline's honest attribution and per-user identity boundary.

**Scope:** Select an audio/video recording for upload; observe processing progress; view a transcript containing speaker labels and timestamps; and reuse speaker review to assign or correct speaker names.

**Out of scope:** Portal redesign or visual polish; new speaker-identification or identity-matching behavior; transcript-text editing; cross-user sharing of speaker names/identity associations; progress percentages; and processing-time targets. The bounded media-decoding behavior in Requirement 4 is a scoped security constraint for speaker-excerpt playback, not a limit on recording upload or general media playback. Compose/diarization-engine setup, secure `HF_TOKEN` provisioning, the real end-to-end/fresh-database check, and ASR `base` versus `small` evaluation remain separate tracked prerequisites/validation work, not new screen behavior in this requirements artifact.

**Traceability and authority:** The authorized addition of this owner-run test screen, including upload, processing progress, transcript display with `Speaker N` and timestamps, and reuse of speaker review, comes from Fer's explicit request in chat `th_f60036dcde764968` (2026-10-22 02:23). The product behavior it exercises is grounded in the owner-approved `docs/product/baseline.md` snapshot at commit `f5ff445fd508983740cd6b5a89c08adafcbb9295` (file blob `c43cad6515b01a52037ad9cd4e09010a40477fb4`): §3 establishes honest attribution and human correction; §4.B defines the speaker-review journey; §4.C provides the portal context for revisiting recordings and transcripts. Section 4.C is contextual authority for the portal surface, not the source of speaker-review behavior. The baseline's §9 records its source and approval. The test-screen additions are authorized by the owner request, not by the unmerged draft in PR #528. The speaker-excerpt resource limits in Requirement 4 are a separate owner decision recorded in the #599 card on 2026-10-31: source media used for excerpt decoding is limited to 20 MiB and 30 seconds of decoded audio, each excerpt is limited to 10 seconds, at most two decodings may run concurrently per worker, and exceeding a limit requires explicit rejection rather than silent truncation. This is a decoding constraint only; it does not limit uploads or general playback.

## Glossary

- **Test_Screen:** The minimal portal screen requested for owner-run testing of recording upload, processing, transcript display, and speaker review.
- **Speaker_Label:** The displayed speaker identity for a transcript turn. It may be a recognized name or the unresolved `Speaker N` label where identity is unknown or uncertain.
- **Speaker_Review:** The existing speaker-review interaction through which the user can review speakers, play a clear audio excerpt, and replace an unresolved label or correct an assigned name.
- **Transcript_Turn:** A transcript passage attributed to one speaker and associated with a timestamp.
- **Excerpt_Decode_Request:** A request to read and decode stored source media to serve a speaker-specific review excerpt.

## Requirements

### Requirement 1: Upload an audio or video recording for the test flow

**User Story:** As the Sauri owner, I want to upload an audio or video recording from one screen, so that I can exercise speaker recognition without relying on a full portal redesign.

#### Acceptance Criteria

1. WHEN the user selects an audio or video recording for the Test_Screen, THE Test_Screen SHALL provide an upload action that starts processing that selected recording.
2. THE Test_Screen SHALL remain a minimal test surface and SHALL NOT require the user to navigate a redesigned meeting library or unrelated portal areas to start this test flow.

### Requirement 2: Show processing progress before presenting the result

**User Story:** As the Sauri owner, I want to see that the uploaded recording is being processed, so that I can distinguish the processing step from the resulting transcript and review.

#### Acceptance Criteria

1. WHEN an uploaded recording is being processed, THE Test_Screen SHALL display a processing-progress state.
2. WHEN processing of the uploaded recording is complete, THE Test_Screen SHALL present its transcript and speaker-review capability in the same test flow.

### Requirement 3: Present speaker-attributed transcript turns with timestamps

**User Story:** As the Sauri owner, I want to inspect timestamps and speaker attribution for transcript turns, so that I can evaluate the result of speaker recognition.

#### Acceptance Criteria

1. WHEN the transcript is presented, THE Test_Screen SHALL show each Transcript_Turn with its timestamp, Speaker_Label, and transcript text.
2. WHEN a speaker is unknown or attribution is uncertain, THE Test_Screen SHALL display `Speaker N` rather than imply that an identity is confirmed.

### Requirement 4: Reuse speaker review to name or correct speakers

**User Story:** As the Sauri owner, I want to review and name unresolved speakers or correct assigned names, so that I can exercise the existing human speaker-correction flow.

#### Acceptance Criteria

1. WHEN the transcript is available, THE Test_Screen SHALL make the existing Speaker_Review available for its speakers.
2. THE Speaker_Review SHALL let the user play a clear audio excerpt for a speaker and replace `Speaker N` with a chosen name or label.
3. THE Speaker_Review SHALL let the user correct an automatically assigned speaker name.
4. THE Speaker_Review SHALL preserve the approved per-user identity boundary; it SHALL NOT share a user's speaker names or identity associations with other users.
5. WHEN the user leaves before completing speaker review, THE system SHALL retain the review as pending and request it again when the user returns to that recording.
6. THE system SHALL NOT represent incomplete speaker review as complete.
7. WHEN an Excerpt_Decode_Request is made, THE system SHALL reject it if the source media exceeds 20 MiB or if decoding it would exceed 30 seconds of decoded audio; it SHALL NOT decode beyond the duration cap.
8. WHEN Sauri derives a speaker-review excerpt, THE system SHALL select only a valid candidate interval of at most 10 seconds; it SHALL NOT silently truncate a longer candidate, and SHALL reject excerpt derivation explicitly if no valid candidate interval fits the cap.
9. WHEN an Excerpt_Decode_Request would exceed the per-worker limit of two concurrent decodings, THE system SHALL reject it explicitly.
10. WHEN Sauri rejects an Excerpt_Decode_Request for a resource limit, THE system SHALL show a clear message that the excerpt could not be provided because a limit was exceeded, without exposing internal decoder details.

**Traceability:** Fer's owner decision recorded in the #599 card (2026-10-31); security evidence in issue #599 identifies unbounded source-object retrieval and FFmpeg execution at `backend/app/meetings/router.py` (`get_speaker_excerpt`) and `backend/app/meetings/speaker_excerpt_service.py` (`decode_audio_interval`). The existing `.spectra/specs/recording-speaker-review/design.md` requires validated speaker-specific excerpts and prevents a revision becoming ready when no candidate passes; it does not authorize exceeding the owner-selected cap. Its longest-first candidate selection must be bounded by this requirement, not used to clamp an over-limit excerpt silently.

### Requirement 5: Keep the test scope bounded

**User Story:** As the Sauri owner, I want this test screen to stay focused on exercising upload and speaker recognition, so that it can be delivered without pre-empting the separate portal design work.

#### Acceptance Criteria

1. THE Test_Screen SHALL NOT introduce a full portal redesign or unrelated meeting-management capabilities.
2. THE Test_Screen SHALL NOT allow manual transcript-text editing; speaker correction changes attribution only.
3. THE Test_Screen SHALL use synthetic recording data for automated validation; real meeting recordings and personal or confidential customer data SHALL NOT be used as test fixtures.
