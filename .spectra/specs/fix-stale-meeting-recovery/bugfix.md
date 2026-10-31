# Bugfix — Safe recovery for stale queued or transcribing meetings

## Bug Description

Some meetings remain in `Queued` or `Transcribing` after processing stops, with no supported operator recovery path. On 2026-10-30, read-only QA observed six such records; the evidence does not establish why each became stale or whether replay is safe.

**Root-cause hypothesis (low confidence):** processing may stop after the meeting state advances while the corresponding work is no longer progressing. The evidence is consistent with this state mismatch, but does not establish the failure point or rule out alternatives. Empty queue totals and present audio objects do not prove that no per-meeting worker is active or that no output/review exists.

## Reproduction Steps

**Deterministic synthetic reproduction (QA, 2026-10-31; isolated SQLite, no live meeting mutation):**

1. Create a synthetic meeting record in `queued` state with an existing recording and invoke the existing upload/re-ingestion path for that same recording.
2. Assert the result is `is_new=False`, the meeting remains `queued`, one recording remains, no transcript is created, and no new processing job is published.
3. Repeat with a synthetic meeting in `transcribing` state and the same existing-recording setup; assert the same no-requeue/no-state-change behavior.
4. Observe that this existing path is idempotent for the upload but does not recover the stale processing state. Do not use live meeting data or requeue/reset any real meeting.

Nia reports the synthetic reproduction and two existing focused tests passed (**4/4**) at prior spec commit `7df69034cc960b9f970d0d0ce9ba552f68896de4`. The test script was temporary, not committed; exact focused command is not in the available QA note.

**Read-only live metadata, 2026-10-31:** six records remained `queued`/`transcribing`; one `queued` record had one transcript, the other five had none; all six had zero diarizations/reviews/items. Each queue reported zero ready and zero unacknowledged messages but had one consumer. This does not establish absence of per-meeting active work. A worker process inspection attempt failed with `ps: not found`; it was not retried or bypassed. No content was read and no live state was changed. Candidate meeting IDs and time remain opaque and must be verified before any action; they are not test inputs. Do not treat all six as eligible: any prior transcript/diarization/review or uncertain active-work status excludes replay.

## Current Behavior (Defect)

WHEN a meeting remains in `Queued` or `Transcribing` after its processing has stopped, THEN the system provides no supported operator-initiated recovery path, leaving the meeting in that state.

WHEN the existing recording for a synthetic stale `queued` or `transcribing` meeting is uploaded again, THEN the current ingestion path returns `is_new=False`, leaves its state unchanged, and does not publish new processing work; the ordinary idempotent upload therefore does not recover the stale meeting.

WHEN queue totals are empty and the audio object exists, THEN those observations alone do not establish per-meeting replay eligibility or rule out active work and existing outputs.

## Expected Behavior (Correct)

The approved product baseline supports the outcome that recordings and transcripts are available for later review; it does not define a recovery mechanism. The scope for recovery in this fix comes from Fer's explicit decision, recorded in chat `th_1013e406220c4f34` on 2026-10-31 and on task card `task_31c25607a8684d7b`.

WHEN an operator initiates recovery for a meeting in `Queued` or `Transcribing`, THEN the system SHALL allow it to proceed only after the design establishes and verifies that the specific meeting is eligible and no processing is active that could collide; it SHALL stop without mutations if any condition is uncertain. Any existing transcript, diarization, review, or other generated processing output SHALL make that meeting ineligible for replay; existing notes and confirmed speakers SHALL remain preserved.

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
2. WHEN active processing or any eligibility uncertainty is detected, or an existing transcript, diarization, review, or other generated processing output is present, THE SYSTEM SHALL abort/no-op without replaying, requeueing, or altering state/data.
3. WHEN recovery runs, THE SYSTEM SHALL preserve confirmed speakers and existing notes and SHALL NOT change retention or consent.
4. WHEN a meeting is ineligible or cannot be verified, THE SYSTEM SHALL leave it unchanged and present a verifiable result without exposing transcript content.
5. WHEN an operational pilot is enabled, THE SYSTEM SHALL limit the first pilot to one meeting and allow its final result and preservation of artifacts to be verified before expansion.
6. FOR ALL recovery paths, THE SYSTEM SHALL NOT trigger automatically; regression tests SHALL demonstrate that ordinary processing and ingestion behavior remain unchanged.
7. QA SHALL provide a deterministic synthetic reproduction of the stale-state no-recovery condition and observable guarded abort/success outcomes before implementation can be considered verified. Nia's existing synthetic reproduction shows the current ingestion path leaves queued/transcribing state unchanged and does not republish work; it does not establish live per-meeting worker idleness or authorize replay. The live metadata report excludes any meeting with prior processing output from replay eligibility.

## Traceability

- **Approved baseline product content:** `PRODUCT_BASELINE.md` snapshot `f5ff445fd508983740cd6b5a89c08adafcbb9295`; it supports the expectation of later availability, not a retry mechanism.
- **Scope amendment:** `PRODUCT_BASELINE.md` snapshot `f31c1437d002a49849fc577446290ab83d29a584`; use only the portal/Phase 2 scope Fer authorized in the corresponding approval card. The current snapshot on `main` is marked DRAFT and is not treated as wholly approved.
- **Recovery scope decision:** Fer's 2026-10-31 authorization in chat `th_1013e406220c4f34`: manual operator initiation, never automatic, one-meeting pilot with verification before expansion, and preservation/privacy boundaries.
- **QA evidence:** Nia's 2026-10-31 synthetic SQLite reproduction plus two focused tests (4/4 reported passing at prior spec commit `7df69034cc960b9f970d0d0ce9ba552f68896de4`; temporary script path `/var/folders/x6/96ywnlxd7kxfr4qns4c8_0hc0000gn/T/apx-scratch-d2296a21/th_78b4ee80085b47b2/test_stale_reproduction.py`; the exact test command is not in the report). Nia's read-only live metadata on this card found six stale rows, one with a transcript and five without; all six had zero diarizations/reviews/items. Queues had one consumer each and no ready/unacknowledged deliveries, which does not prove per-meeting worker idleness. No content or live state was accessed/changed. Any prior generated output or uncertain active-work status excludes replay.
