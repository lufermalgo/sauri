# Bugfix — Uploaded meeting remains queued after processing completes

## Bug Description

A meeting created in `queued` and then given an uploaded recording can complete transcription and diarization while its meeting record still reports `queued`. The observed rejected transition prevents the meeting state from reflecting completed processing, despite the transcript and speaker assignments being available.

**Expected-behavior authority:** owner-approved `docs/product/baseline.md` snapshot `f31c1437d002a49849fc577446290ab83d29a584`, §4.B.1–3: after a stopped recording is stored, Sauri transcribes it and attempts speaker identification; when processing finishes, the user is asked to review speaker names. The baseline leaves processing-progress labels and state details open (§5, “Other side-panel tab names/content and processing-progress states”; §6, “Processing experience”). This bugfix therefore does not prescribe a new UI label or exact state vocabulary.

## Reproduction Steps

1. Start the isolated test stack with synthetic recording data.
2. `POST /api/v1/meetings/`; confirm the 201 response identifies the new meeting's state as `queued`.
3. Upload a valid synthetic recording for that meeting with `POST /api/v1/ingestion/upload`.
4. Allow the worker to finish transcription and diarization successfully.
5. Confirm `GET /api/v1/meetings/{meeting_id}/transcript` and `GET /api/v1/meetings/{meeting_id}/diarization` succeed, then retrieve `GET /api/v1/meetings/{meeting_id}`.
6. Observe that the meeting still reports `queued` and the worker logs a rejected completion transition.

**Evidence:** Nia's isolated synthetic E2E on candidate `3de13e6e228309b3c3de296b0c28fa249939a390`: meeting creation 201 (initial queued), upload 200; ASR and diarization each returned 200, one speaker/four assignments persisted; transcript and diarization GETs returned 200; meeting GET returned 200 but remained queued; worker warned that the completion transition was rejected. This is a control-path reproduction of the state defect, not a reproduction of the separate original diarization 404. The private QA stack was removed after the run.

## Current Behavior (Defect)

WHEN an uploaded meeting begins in `queued` and the worker completes transcription and diarization,
THEN the meeting GET response still reports `queued`, and the worker records that its completion transition was rejected.

**Root-cause hypothesis (high confidence):** the direct-upload worker path attempts `recording_uploaded` while the meeting remains in its initial `queued` state. `backend/app/meetings/service.py` initializes a registered meeting as `queued`, while `backend/app/meetings/state_machine.py` permits `recording_uploaded` from `recording` but not from `queued`. This matches the worker's observed rejected-transition warning and the persisted state. The isolated run did not capture a stack trace identifying the exact call site, so implementation must verify the event sequence before changing the transition rules.

## Expected Behavior (Correct)

WHEN processing of an uploaded recording finishes successfully,
THEN the system SHALL reflect that processing has finished rather than continue to report the meeting as queued, and SHALL make the meeting available for the speaker-name review described in the approved baseline.

WHEN processing has not finished or has failed,
THEN the system SHALL NOT report successful completion or make the speaker review appear complete.

This requirement does not prescribe the exact state enum or user-facing progress wording, which the approved baseline leaves open.

## Unchanged Behavior (Regression Prevention)

WHEN a meeting is registered,
THEN the system SHALL CONTINUE TO initialize it as queued until processing begins, unless the existing upload flow requires an explicitly designed transition.

WHEN transcription and diarization complete successfully,
THEN the system SHALL CONTINUE TO persist and return the transcript and speaker assignments associated with the meeting.

WHEN processing fails,
THEN the system SHALL CONTINUE TO represent the failure rather than report successful completion.

WHEN a meeting follows the existing capture path through `joining` and `recording`,
THEN the system SHALL CONTINUE TO support its established state transitions and processing behavior.

WHEN the separate automatic-diarization 404 issue is investigated or addressed,
THEN this fix SHALL CONTINUE TO remain scoped to the queued-after-success state defect and SHALL NOT claim to resolve that independent issue or alter the gates for #248.

## Fix Constraints

- Do not invent or expose a new user-facing processing-state label; the baseline leaves progress wording open.
- Do not change the transcript or diarization API response contract as part of this defect.
- Keep this defect separate from the original GET `/diarization` 404 and from #248; no unsupported conclusion about that failure is authorized.
- Preserve the established meeting-capture state transitions and failure reporting.
- Use synthetic test data only.

## Acceptance Criteria

1. WHEN a meeting starts in `queued`, receives an uploaded recording, and transcription plus diarization finish successfully, THE SYSTEM SHALL return a meeting state that reflects successful processing rather than `queued`.
2. WHEN the successful processing result is retrieved, THE SYSTEM SHALL continue to return the persisted transcript and diarization results for that meeting.
3. WHEN uploaded-meeting processing has not finished or has failed, THE SYSTEM SHALL NOT report successful processing completion.
4. WHEN an existing capture-path meeting progresses through its established transitions, THE SYSTEM SHALL CONTINUE TO preserve those transitions and their behavior.
5. WHEN validating this state defect, THE SYSTEM SHALL use synthetic fixtures and SHALL NOT treat the result as proof that the separate GET `/diarization` 404 is fixed.
