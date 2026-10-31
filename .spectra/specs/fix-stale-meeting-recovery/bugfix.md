# Bugfix — Safe recovery for stale queued or transcribing meetings

## Bug Description

Some meetings remain in `Queued` or `Transcribing` after processing stops, with no supported operator recovery path. On 2026-10-30, read-only QA observed six such records; the evidence does not establish why each became stale or whether replay is safe.

**Root-cause hypothesis (low confidence):** processing may stop after the meeting state advances while the corresponding work is no longer progressing. The evidence is consistent with this state mismatch, but does not establish the failure point or rule out alternatives. Empty queue totals and present audio objects do not prove that no per-meeting worker is active or that no output/review exists.

## Reproduction Steps

1. Inspect meeting processing state and timestamps using an authorized, read-only QA procedure; do not inspect or export audio, transcript text, titles, or other meeting content.
2. Identify a meeting still reported as `Queued` or `Transcribing` after its processing has ceased to make progress.
3. Confirm whether the state remains unchanged while the authorized QA/operator check finds no corresponding work progressing.
4. Observe that the current system provides no supported operator-initiated recovery flow; do not requeue, reset, or otherwise mutate the meeting as part of reproduction.

**Available QA evidence:** On 2026-10-30 Nia reported six records in `queued`/`transcribing`; all six had one audio reference and the objects were present; the `transcribe`/`diarize` queues each showed 0 ready and 0 unacknowledged messages. No content was read. The aggregate evidence does not include a deterministic reproduction, per-record timestamps, per-meeting active-worker verification, or verification of existing artifacts/review. Candidate meeting IDs and time remain opaque and must be verified before any action; they are not test inputs.

## Current Behavior (Defect)

WHEN a meeting remains in `Queued` or `Transcribing` after its processing has stopped, THEN the system provides no supported operator-initiated recovery path, leaving the meeting in that state.

WHEN queue totals are empty and the audio object exists, THEN those observations alone do not establish per-meeting replay eligibility or rule out active work and existing outputs.

## Expected Behavior (Correct)

The approved product baseline supports the outcome that recordings and transcripts are available for later review; it does not define a recovery mechanism. The scope for recovery in this fix comes from Fer's explicit decision, recorded in chat `th_1013e406220c4f34` on 2026-10-31 and on task card `task_31c25607a8684d7b`.

WHEN an operator initiates recovery for a meeting in `Queued` or `Transcribing`, THEN the system SHALL allow it to proceed only after the design establishes and verifies that the specific meeting is eligible, no processing is active that could collide, and existing artifacts/reviews will not be overwritten; it SHALL stop without mutations if any condition is uncertain.

WHEN the first operational use of recovery is authorized, THEN the operator SHALL process exactly one pilot meeting and verify its final result and preservation of artifacts/reviews before expanding use.

WHEN an operator performs recovery, THEN the system SHALL act only on the identified meeting and SHALL expose enough evidence for the operator to verify the result without revealing transcript content in logs or shared artifacts.

## Unchanged Behavior (Regression Prevention)

WHEN a meeting is actively processing, THEN the system SHALL CONTINUE TO prevent concurrent recovery from duplicating or interrupting that processing.

WHEN a meeting has confirmed speakers or existing notes, THEN the system SHALL CONTINUE TO preserve those artifacts; recovery SHALL NOT overwrite them.

WHEN a meeting is subject to existing retention or consent rules, THEN the system SHALL CONTINUE TO apply those rules unchanged.

WHEN recovery cannot establish eligibility or preservation of existing state, THEN the system SHALL CONTINUE TO leave the meeting and its data unchanged and communicate a safe no-op/abort result.

WHEN ordinary ingestion retries and normal meeting processing run, THEN the system SHALL CONTINUE TO preserve their existing behavior; this fix SHALL NOT introduce automatic retries.

## Fix Constraints

- Recovery must be explicitly initiated by a human operator; automatic recovery/retries are excluded.
- No destructive reset or blind replay. Eligibility, active-work exclusion, and preservation of outputs/reviews must be specified in `design.md` and demonstrated before any operational action.
- If operational use is authorized after implementation and QA, the first pilot is limited to one meeting; verify its result before considering expansion. This specification does not authorize recovery execution, merge, or deployment.
- Do not overwrite confirmed speakers or notes; do not change retention or consent.
- Do not read or copy transcript content into the repository, PRs, comments, fixtures, shared logs, or evidence. Use synthetic data for automated tests.
- Candidate IDs/time in the card are not eligibility criteria; verify identity before any action and do not include them in public test artifacts.
- Preserve unrelated interfaces and contracts.

## Acceptance Criteria

1. WHEN an operator requests recovery for an eligible meeting, THE SYSTEM SHALL require explicit human initiation and SHALL act only on that meeting.
2. WHEN active processing, an artifact/review that cannot be preserved, or any eligibility uncertainty is detected, THE SYSTEM SHALL abort/no-op without requeueing or altering state/data.
3. WHEN recovery runs, THE SYSTEM SHALL preserve confirmed speakers and existing notes and SHALL NOT change retention or consent.
4. WHEN a meeting is ineligible or cannot be verified, THE SYSTEM SHALL leave it unchanged and present a verifiable result without exposing transcript content.
5. WHEN an operational pilot is enabled, THE SYSTEM SHALL limit the first pilot to one meeting and allow its final result and preservation of artifacts to be verified before expansion.
6. FOR ALL recovery paths, THE SYSTEM SHALL NOT trigger automatically; regression tests SHALL demonstrate that ordinary processing and ingestion behavior remain unchanged.
7. QA SHALL provide a deterministic synthetic reproduction of the stale-state condition and observable abort/success outcomes before implementation can be considered verified. The aggregate operational evidence above does not replace this reproduction or per-meeting verification.

## Traceability

- **Approved baseline product content:** `PRODUCT_BASELINE.md` snapshot `f5ff445fd508983740cd6b5a89c08adafcbb9295`; it supports the expectation of later availability, not a retry mechanism.
- **Scope amendment:** `PRODUCT_BASELINE.md` snapshot `f31c1437d002a49849fc577446290ab83d29a584`; use only the portal/Phase 2 scope Fer authorized in the corresponding approval card. The current snapshot on `main` is marked DRAFT and is not treated as wholly approved.
- **Recovery scope decision:** Fer's 2026-10-31 authorization in chat `th_1013e406220c4f34`: manual operator initiation, never automatic, one-meeting pilot with verification before expansion, and preservation/privacy boundaries.
- **QA evidence:** Nia's 2026-10-30 read-only report on task `task_31c25607a8684d7b` (six stale states, references/objects present, queues without ready or unacknowledged messages, no content inspected). Individual eligibility and absence of active work/review remain unproven.
