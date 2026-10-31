# Bugfix — Safe recovery for stale queued or transcribing meetings

## Bug Description

Some meetings remain in `Queued` or `Transcribing` after processing stops. QA reproduced that re-ingesting an already registered recording through `process_ingestion` returns the existing recording and leaves the meeting state unchanged; the evidence does not establish whether another supported recovery path exists, why each live record became stale, or whether replay is safe.

**Root-cause hypothesis (low confidence):** the existing idempotent ingestion service returns the existing recording without recovering a stale meeting state. The synthetic test supports this behavior only at `process_ingestion`; it does not exercise the API/publisher boundary or establish that no separate operator recovery mechanism exists. The cause of the live stale states remains unresolved. Empty queue totals and present audio objects do not prove that no per-meeting worker is active or that no output/review exists.

## Reproduction Steps

**Deterministic synthetic reproduction (QA, 2026-10-31; isolated SQLite, no live meeting mutation):**

1. In isolated synthetic SQLite, create a meeting in `queued` state with one existing recording.
2. Call `app.ingestion.service.process_ingestion` with data identifying that same recording.
3. Assert `is_new=False`; reload the meeting and assert it remains `queued`, exactly one recording remains, and no transcript exists. Do not assert or infer anything about API routing or message publication; this test does not exercise either boundary.
4. Repeat with the synthetic meeting in `transcribing` state and assert the same service return and persisted-record state. This establishes that this service call does not recover the stale state; it does not establish whether another operator recovery mechanism exists. No live meeting data or state is used.

Nia's attached synthetic test source (`med_c4ff44f45c1d4c41`) and exact output (`med_88226181783b4449`) report **4 passed in 3.11s** at prior spec commit `bc9626c1f69f4e1dbbf84c531cb4c5352853d580`: two parameterized service-level cases and two existing tests. No API route or publisher is present in that reproduction.

**Read-only live metadata, 2026-10-31:** six records remained `queued`/`transcribing`; one `queued` record had one transcript, the other five had none; all six had zero diarizations/reviews/items. Each queue reported zero ready and zero unacknowledged messages but had one consumer. This does not establish absence of per-meeting active work. A worker process inspection attempt failed with `ps: not found`; it was not retried or bypassed. No content was read and no live state was changed. Candidate meeting IDs and time remain opaque and must be verified before any action; they are not test inputs. Do not treat all six as eligible: any prior transcript/diarization/review or uncertain active-work status excludes replay.

## Current Behavior (Defect)

WHEN an existing recording for a synthetic stale `queued` or `transcribing` meeting is passed again to `app.ingestion.service.process_ingestion`, THEN the service returns `is_new=False` and leaves the meeting state unchanged; this service call therefore does not recover the stale meeting.

The available evidence does not determine whether a separate supported operator-initiated recovery path exists, and the service-level reproduction does not make claims about message publication.

WHEN queue totals are empty and the audio object exists, THEN those observations alone do not establish per-meeting replay eligibility or rule out active work and existing outputs.

## Expected Behavior (Correct)

The approved product baseline supports the outcome that recordings and transcripts are available for later review; it does not define a recovery mechanism. The scope for recovery in this fix comes from Fer's explicit decision, recorded in chat `th_1013e406220c4f34` on 2026-10-31 and on task card `task_31c25607a8684d7b`.

WHEN an operator initiates recovery for a meeting in `Queued` or `Transcribing`, THEN the system SHALL allow it to proceed only after the design establishes and verifies that the specific meeting is eligible and no processing is active that could collide; it SHALL stop without mutations if any condition is uncertain. Any existing transcript, diarization, review, or other generated processing output SHALL make that meeting ineligible for replay; existing notes and confirmed speakers SHALL remain preserved.

WHEN the first operational use of recovery is authorized, THEN the operator SHALL process exactly one pilot meeting and verify its final result and preservation of artifacts/reviews before expanding use. A candidate already holding a transcript SHALL remain unchanged, SHALL NOT be selected as that first pilot, and SHALL be reported as not recovered / requiring review until preservation is demonstrated or Fer clarifies the handling.

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
7. QA SHALL reproduce the existing-recording case at `app.ingestion.service.process_ingestion` and assert only its service return and persisted meeting/recording/transcript state; this reproduction SHALL NOT be treated as evidence about API routing or message publication. Before implementation can be considered verified, QA SHALL separately exercise the actual recovery entry point and verify its guarded abort/success outcomes. The live metadata report does not establish per-meeting worker idleness; any prior generated output or uncertain active-work status excludes replay.

## Traceability

- **Approved baseline product content:** `PRODUCT_BASELINE.md` content reference `f5ff445fd508983740cd6b5a89c08adafcbb9295` supports later availability, not a retry mechanism. The post-Meet portal scope amendment is `f31c1437d002a49849fc577446290ab83d29a584`; the current approved baseline records approval of exact content at commit `85b603ada14996842d913cfbbed4bcffe9fe54c5`, blob `2337a46b2ba78ef4364e23a86df9918db621c881`. No retry behavior is derived from the baseline; manual recovery scope comes only from Fer's explicit authorization below.
- **Recovery scope decision:** Fer's 2026-10-31 authorization in chat `th_1013e406220c4f34`: manual operator initiation, never automatic, one-meeting pilot with verification before expansion, and preservation/privacy boundaries. Cyrus's clarification in task message `msg_caa9f07c30cf482f`: a queued meeting with an existing transcript remains intact, requires review, and is not the first pilot.
- **QA evidence:** Nia's 2026-10-31 synthetic SQLite reproduction and exact output are attached to task `task_31c25607a8684d7b` as `med_c4ff44f45c1d4c41` (source) and `med_88226181783b4449` (4 passed in 3.11s at prior spec commit `bc9626c1f69f4e1dbbf84c531cb4c5352853d580`). The test invokes `process_ingestion` only and does not exercise the API/publisher boundary. Nia's read-only live metadata found six stale rows; one had a transcript and five did not; all six had zero diarizations/reviews/items. Queues had one consumer each and no ready/unacknowledged deliveries, which does not prove per-meeting worker idleness. No content or live state was accessed/changed. Any prior generated output or uncertain active-work status excludes replay.
