# Requirements — Chrome Recording Completion

## Introduction

This specification defines the completion path for a Chrome recording: capture ends either when the user presses Stop or when the captured meeting tab is closed; the resulting audio and video are uploaded and processed; and successful processing leads to one authenticated Sauri tab showing that recording's video and transcript. The owner requested this functional flow on 2026-10-30 (source: APX chat `th_a9681ad91c2f4b5d`, owner message at 14:48), explicitly naming Meet and Teams. Teams capture is a newly requested capability, not an assertion about existing support. The owner also clarified that the meeting-ended event alone is not an authorized capture-stop trigger.

**Central thesis:** Both independently authorized end events complete the same recording lifecycle, whose upload and processing outcomes remain truthful and bound to that recording, with a single authenticated review tab after successful processing.

**Scope:** Stop-button and captured-tab-close completion; automatic audio/video upload; recording-specific, truthful outcome and processing states; and opening exactly one authenticated Sauri tab with the successfully processed recording's video and transcript. Existing playback behavior is referenced only as the review destination, not redefined here.

**Out of scope:** Visual redesign; a new consent or privacy/retention policy; treating a meeting-ended signal as a stop trigger; claiming Teams capture already exists; changing transcript or playback behavior; and defining upload-defect remediation (tracked separately). The extension capture-preferences requirements remain the upstream source for the prior Meet capture journey; they do not establish this completion flow. Requirements here are authorized by the cited owner direction and the previously approved portal amendment, not by the current DRAFT baseline snapshot, and are not implementation authorization or self-approval.

## Glossary

- **Captured_Meeting_Tab**: The Chrome tab for the Meet or Teams meeting whose audio and video are being captured in the active recording.
- **Recording**: The single capture instance and its finalized audio/video assets, upload/processing outcome, and associated meeting review destination.
- **Completion_Trigger**: Either the user activating Stop for the active recording or the user closing its Captured_Meeting_Tab; the two triggers are independently sufficient.
- **Processing_Success**: The state in which processing for the Recording has completed successfully and its transcript and video are available in Sauri for review.
- **Review_Tab**: A browser tab showing the Sauri meeting review for the same Recording, with its video and transcript.

## Requirements

### Requirement 1: Complete capture on either authorized trigger

**User Story:** As a recorder, I want either stopping explicitly or closing the captured meeting tab to finish capture, so that I do not have to perform a separate stop action after ending the meeting session.

#### Acceptance Criteria

1. WHEN the user activates Stop during an active Recording, THE Extension SHALL finalize that Recording's captured audio and video.
2. WHEN the user closes the Captured_Meeting_Tab during an active Recording, THE Extension SHALL finalize that Recording's captured audio and video without requiring a separate Stop action.
3. WHEN either Completion_Trigger occurs, THE Extension SHALL associate the finalized audio and video with the same Recording and meeting.
4. WHEN both stop and tab-close events are received for one active Recording, THE Extension SHALL treat them as completion of that same Recording, not create another Recording.
5. THE Extension SHALL NOT treat a meeting-ended signal by itself as a Completion_Trigger.

**Traceability:** Owner direction, 2026-10-30 14:48, APX chat `th_a9681ad91c2f4b5d`; approved amendment `docs/product/baseline.md` at `f31c1437d002a49849fc577446290ab83d29a584` provides prior portal scope context but does not itself authorize this extension delta.

### Requirement 2: Automatically upload the finalized recording

**User Story:** As a recorder, I want finalized audio and video uploaded automatically, so that the recording can be processed and reviewed without a manual upload step.

#### Acceptance Criteria

1. WHEN a Recording is finalized by either Completion_Trigger, THE Extension SHALL initiate upload of both its finalized audio and video without requiring a separate user upload action.
2. WHEN upload completes, THE Extension and Sauri SHALL associate its outcome with the same Recording and meeting that produced the uploaded assets.
3. WHEN upload succeeds, THE Extension SHALL present and retain a success outcome associated with that Recording.
4. WHEN upload is in progress, THE Extension SHALL present a state that does not claim upload success.
5. IF upload fails, THEN THE Extension SHALL present and retain a failure outcome associated with that Recording, rather than reporting success.
6. IF upload is retried for the same Recording, THEN THE Extension and Sauri SHALL NOT represent the retry as a different Recording or create a duplicate meeting recording.

**Traceability:** Owner direction, 2026-10-30 14:48, APX chat `th_a9681ad91c2f4b5d`. Upload-failure diagnosis/remediation is separately tracked by `task_11001b7f5b084e09`; this requirement defines observable product outcome, not that defect's technical fix.

### Requirement 3: Report processing outcome for the same recording

**User Story:** As a recorder, I want to know whether processing of my uploaded recording succeeded or failed, so that I can distinguish a ready transcript from an incomplete recording.

#### Acceptance Criteria

1. WHEN the uploaded audio and video for a Recording are accepted for processing, THE Extension or Sauri SHALL present a processing-in-progress state associated with that Recording.
2. WHEN processing reaches Processing_Success, THE Extension or Sauri SHALL present a success state associated with that Recording.
3. IF processing fails, THEN THE Extension or Sauri SHALL present and retain a failure state associated with that Recording, rather than indicating Processing_Success.
4. WHEN the user reloads or retries the completion flow, THE Extension or Sauri SHALL continue to show the outcome belonging to the same Recording and SHALL NOT present a stale success or failure from another Recording.

**Traceability:** Owner direction, 2026-10-30 14:48, APX chat `th_a9681ad91c2f4b5d` (automatic upload → transcription → Sauri destination; same-recording truthful outcomes and no duplicates clarified in Cyrus reconciliation `th_43d13245e795427d`).

### Requirement 4: Open one authenticated review tab after successful processing

**User Story:** As an authenticated Sauri user, I want the completed recording's video and transcript opened together in one Sauri tab, so that I can review the meeting without searching for it or opening duplicate tabs.

#### Acceptance Criteria

1. WHEN a Recording reaches Processing_Success, THE Extension SHALL open a new Review_Tab for that same Recording.
2. THE Review_Tab SHALL require an authenticated Sauri session and access authorization for the user before exposing the Recording's video or transcript.
3. THE Review_Tab SHALL show both the Recording's video and its transcript.
4. WHEN processing has not succeeded, THE Extension SHALL NOT present the Recording as ready for video-and-transcript review.
5. WHEN a completion event, retry, or page reload is repeated for the same Recording, THE Extension SHALL NOT open more than one Review_Tab for that Recording as a result of that repeated event or retry.
6. THE Extension and Sauri SHALL NOT associate the Review_Tab with a different meeting or Recording.

**Traceability:** Owner direction, 2026-10-30 14:48, APX chat `th_a9681ad91c2f4b5d`; authenticated access boundary from `SECURITY.md` at upstream commit `46c8605d4dc635655838b33b98f11a67b7316053`; review destination is consistent with `.spectra/specs/meeting-review-playback/requirements.md` (blob `5d0ba0ca01eba1a82c2bb41d432ccacfa7dbb175`), which defines playback/transcript behavior but not this launch flow.

### Requirement 5: Preserve scope and security boundaries

**User Story:** As a Sauri user, I want completion behavior to stay within the authorized flow and access boundaries, so that capture does not start or expose meeting data through an unapproved trigger or unauthenticated destination.

#### Acceptance Criteria

1. THE Extension SHALL support the specified completion flow for Meet and Teams captures without implying that Teams capture is already implemented.
2. THE Extension SHALL NOT finalize an active Recording solely because it receives a meeting-ended signal.
3. THE Extension SHALL NOT expose a Recording's video or transcript in a Review_Tab unless the user is authenticated and authorized to access that Recording.
4. THE Extension SHALL NOT introduce a visual redesign, consent workflow, retention rule, or privacy-policy change under this specification.
5. THE Extension SHALL NOT treat a completion event, upload retry, processing retry, or page reload as authorization to create a second recording or duplicate Review_Tab for the same Recording.

**Traceability:** Owner direction, 2026-10-30 14:48, APX chat `th_a9681ad91c2f4b5d`; Cyrus reconciliation `th_43d13245e795427d`; `SECURITY.md` at upstream commit `46c8605d4dc635655838b33b98f11a67b7316053`.

## Traceability Summary

**Version:** Requirements authoring snapshot 1.0; phase status `complete` means authored only and does not imply approval. Mira's verdict for the exact submitted snapshot is required before design proceeds.

**Authority and upstream versions:** The operative functional scope comes from Fer's 2026-10-30 owner direction in APX chat `th_a9681ad91c2f4b5d` and Cyrus's reconciliation in `th_43d13245e795427d`. The previously approved portal amendment is `docs/product/baseline.md` at commit `f31c1437d002a49849fc577446290ab83d29a584`; the current baseline snapshot at upstream `origin/main` (`46c8605d4dc635655838b33b98f11a67b7316053`) is explicitly DRAFT and is not used as blanket authority. Related upstream requirements snapshots are `.spectra/specs/extension-capture-preferences/requirements.md` (blob `abc5fabd0dafa5b2ab26775417046e9ecee91676`) and `.spectra/specs/meeting-review-playback/requirements.md` (blob `5d0ba0ca01eba1a82c2bb41d432ccacfa7dbb175`). They inform prior capture and review boundaries; neither is cited as approval of this new completion flow. `SECURITY.md` is read at upstream commit `46c8605d4dc635655838b33b98f11a67b7316053`.

**Assumptions and limits:** “Retain” means the outcome remains associated with the same Recording across reload/retry; no duration or storage mechanism is prescribed. “One Review_Tab” means retries and repeated completion events must not create a duplicate tab for that Recording; this does not prescribe tab-selection implementation. Successful processing is the sole review-tab launch condition in this scope. Upload failure remediation remains separate. These requirements do not claim current Meet/Teams functionality, technical reliability, product acceptance, or implementation authorization.
