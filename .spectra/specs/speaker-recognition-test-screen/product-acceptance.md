# Product-acceptance protocol — speaker-recognition test screen

**Protocol version:** 1.3

**Status:** PREDECLARED — no user observations recorded
**Scope:** The owner-run test screen in `.spectra/specs/speaker-recognition-test-screen/`, specifically the upload → processing → transcript → speaker-review journey. This protocol is not the broader pilot in `pilot-done.md` and does not assess general product readiness.

## Frozen test target

- **Feature:** Minimal speaker-recognition test screen described by the approved requirements for this spec.
- **Candidate commit to test:** `13846b18a225925505eb47b307189c3724f0f22f` (PR #741's exact head verified on GitHub before this protocol revision; its parent is `15329eec4e1bbc2fc4726a74de763dd6d9832d5c`).
- **Version rule:** A result applies only to this exact code version. Before a session, verify that the application being exercised is built from this commit. A different commit, rebuilt candidate with changes, or changed acceptance criteria requires a new protocol version before any new observation; results must not be transferred to it.
- **Revision history:** Version 1.1 replaced the earlier pre-observation candidate reference with the then-current exact PR head. Version 1.2 added the approved Requirement 4.5 leave-and-return check. Version 1.3 makes the unresolved-attribution and both correction behaviors explicit, and identifies the pre-session runtime/input checks. No user observation had occurred when these revisions were made.

## Target user and authorized representative test path

- **Target user profile:** The owner of the Sauri test screen who needs to exercise the recording-to-transcript and speaker-correction flow; the approved representative participant for this bounded test is Fer, using the owner-run screen.
- **Authorized path:** Before the session, Ansel confirms that the running web test screen is built from the exact frozen candidate and confirms that the planned synthetic input is available. Fer then performs one end-to-end session in that instance using one fresh **synthetic** audio or video file. Use synthetic media with at least three distinct, intelligible synthetic voices and clear audible segments suitable for speaker excerpts; scenario 4 requires the resulting review to contain (a) one unresolved `Speaker N` item, (b) a separate automatically assigned speaker-name item, and (c) a third item that can remain pending. Follow the same uploaded item through all four scenarios. If the candidate/input does not produce any required state, record the affected threshold as **Not observed**, not Pass. Do not substitute prerecorded synthetic UI responses or a mock/screenshot-only rendering for the interactive flow.
- **Minimum sample:** One completed session by the named representative participant (n=1). This is sufficient only to evaluate this owner's narrow test-screen journey. It does not establish usability or acceptance for a broader or diverse customer population.
- **Privacy boundary:** Use no real meeting, participant identity, customer information, or personal data. Do not capture or publish audio, video, transcript contents, names, credentials, or screen recordings. Keep only brief, non-sensitive observations and pass/fail outcomes.

## Scenarios and fixed thresholds

Run the scenarios in order in the same session and on the same synthetic recording. Record **Pass** only when the stated visible behavior is observed in the running candidate. Any failed threshold is a failure; do not infer success from code, logs, mocks, elapsed time, QA, or a prior run.

| # | Scenario | Pass threshold |
|---|---|---|
| 1 | Select and upload synthetic audio or video | The screen accepts the selected supported synthetic file; the user can start the upload; the screen visibly transitions into processing for that submitted recording without a second, unrelated workflow. |
| 2 | Processing to result in the same flow | A processing state is visibly shown before completion. When processing completes, the transcript and speaker-review capability for that same recording become available in the same test-screen flow. No fabricated progress or inferred completion counts. |
| 3 | Transcript timestamps and unresolved speaker attribution | The visible transcript shows text, a timestamp, and a speaker attribution for each displayed turn. The session must include an actually unresolved or uncertain turn, and the running UI must show the literal `Speaker N` fallback for it rather than implying a confirmed identity. If no unresolved/uncertain turn occurs in the result, record this threshold **Not observed**, not Pass. This checks visible, honest presentation only; it does not score diarization accuracy or require every speaker to be named. |
| 4 | Excerpt playback, both correction paths, and resume pending review | With the three distinct review items specified above, play the clear excerpt for the unresolved item, replace its `Speaker N` label through the existing review flow, and observe the chosen label. Separately correct the automatically assigned name on the second item and observe the corrected name. Leave the third item pending, navigate away from the recording before completing review, then return to that same recording. Pass only if Sauri requests the pending review again, exposes the remaining item for review, and does not represent the recording as fully reviewed/completed. Each behavior must be directly observed; if the required input/result state is absent, record the corresponding behavior **Not observed**, not Pass. |

## Decision rule and evidence record

- **`PRODUCT_ACCEPTED`:** all four scenarios pass in the single qualifying session on the exact frozen candidate, and the session record has enough direct observation to verify every threshold.
- **`PRODUCT_NOT_ACCEPTED`:** any scenario is observed to fail its fixed threshold. Record which threshold failed and a short non-sensitive observation; do not broaden scope or change criteria after seeing the result.
- **`INSUFFICIENT_USER_EVIDENCE`:** no qualifying session exists, the exact candidate cannot be verified, any mandatory scenario is not observed, or the notes do not permit a pass/fail decision. Absence of failure is not a pass.

For a future session, record below (without sensitive content): participant profile (Fer / owner-run), candidate commit actually verified, date, synthetic input type (audio/video only), each scenario outcome, a short non-sensitive observation for each, and any limits or deviations. Record sample size as `n=1`. Do not enter an acceptance verdict in this document until the session has happened and the evidence is reviewed; use only the outcomes above.

| Scenario | Outcome (Pass / Fail / Not observed) | Brief non-sensitive observation |
|---|---|---|
| 1. Upload starts processing | Not observed | |
| 2. Processing yields result in same flow | Not observed | |
| 3a. Timestamps and attribution for displayed turns | Not observed | |
| 3b. An unresolved turn visibly uses `Speaker N` | Not observed | |
| 4a. Excerpt playback and replacement of unresolved `Speaker N` | Not observed | |
| 4b. Correction of a separately auto-assigned name | Not observed | |
| 4c. Leave, return, and resume the third pending review item | Not observed | |

**Observed candidate:** Not tested.

**Session date:** Not tested.

**Sample:** n=0; no user evidence recorded.
**Product outcome:** `INSUFFICIENT_USER_EVIDENCE` until a qualifying session is observed and evaluated. This is a protocol status, not a verdict on the feature's merits.

## Separate gates and limits

This protocol does not replace technical decoding/isolation limits or their validation, QA, security review, privacy decisions, or release approval. Passing these user scenarios cannot waive those gates. The broader four-check owner pilot, including extension capture, automatic processing on tab close, and summary availability, remains separate and is not part of this product-acceptance decision.
