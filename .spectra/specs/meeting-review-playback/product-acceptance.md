# Product Acceptance — Meeting Review Playback (T-8)

## Candidate and scope

- **Outcome:** `INSUFFICIENT_USER_EVIDENCE`
- **Exact candidate:** `6a9c838b1bab204d35ec046a4b9fad7e786ccbdb`
- **Candidate identity:** verified as an ancestor of `origin/main` at `c5b9c2f93a70806a2415e4d79f6924cbf905730a`; `git merge-base --is-ancestor 6a9c838b1bab204d35ec046a4b9fad7e786ccbdb origin/main` exited 0. An earlier `T8_CANDIDATE_ANCESTRY=0` result was inconsistent and could not be reproduced with this direct ancestry check.
- **Approved requirements:** `.spectra/specs/meeting-review-playback/requirements.md`, blob `5d0ba0ca01eba1a82c2bb41d432ccacfa7dbb175`.
- **Approved design reference:** `.spectra/specs/meeting-review-playback/design.md`, blob `add1950a1c6d28bdc51a022089fd26f2e37b99aa`.
- **Approved task-plan reference:** `.spectra/specs/meeting-review-playback/tasks.md` at commit `b88a07b64d3a7f0e04ff9e6139d8645bcf9cf10b` (the file blob at that commit is `264fc6d7c2f0ebddd241bd7b5da7ef2865fa435d`). The current file blob is `a089fe5a92dbe1be3abbbae04f93180a10e6b085`; the difference adds only GitHub issue/card/PR tracking lines and does not change task actions or acceptance evidence.
- **Approved product baseline:** `PRODUCT_BASELINE.md`, blob `1c1b124a1664cec13b7fc6950bb0d30ca98d0899`.
- **Feature evaluated:** T-8 playback controller, as included in the exact candidate above. Issue #306 is closed and PR #313 is merged; neither is product-acceptance evidence.

## Frozen user-evaluation plan

This plan is fixed before any user observations. No user evaluation has been conducted for this report.

### Target users and minimum sample

- **Target profile:** Functional users who use Sauri to review meeting media and its transcript, consistent with `Functional_User` in the approved requirements.
- **Minimum sample:** 2 representative users. Fer will conduct controlled sessions, according to the recorded owner decision.
- **Test material:** Synthetic media and transcript fixtures only. Do not use real meetings, recordings, participant identities, personal data, or customer content.

### Scenarios and observable criteria

Each participant is given a neutral task prompt for the behavior below. A scenario passes when the participant's action produces the specified, directly observable behavior in the candidate. Record pass/fail and concise observations by ephemeral participant code and scenario. Do not record sessions or collect identifying details. Do not impose a time limit or moderator-intervention threshold; those are not approved product criteria.

| Approved criterion | Scenario | Pass condition |
|---|---|---|
| R1.1 | Seek to a position in playable media. | Seeking moves playback to the user-selected media position. |
| R1.2 | Pause playing media. | Playback pauses. |
| R1.3 | Resume paused media. | Playback resumes. |
| R1.4 | Select a playback speed. | Media plays at the selected speed; no particular speed value is required. |
| R1.5 | If the media has more than one available quality/resolution, choose another option. | The chosen available option is applied to playback. If there is only one available option, mark this conditional scenario N/A, not failed. Do not invent options. |
| R1.6 | Adjust the volume of media with audio. | The playback volume changes in response to the user's adjustment. |
| R1.7 | Mute and unmute media with audio. | Playback audio is muted and can then be unmuted. |
| R2.1 | Observe the transcript while media is playing. | The passage associated with the current playback time is visibly highlighted. |
| R2.2 | Continue playback into a different timed passage. | The visible highlight moves to the passage associated with the new playback time. |
| R3.1 | Select a transcript paragraph or fragment and activate its associated playback control. | Playback starts from that passage's linked time. |

No specific control layout, time display, video-specific behavior, playback-speed value, or quality value is being added to the approved criteria. Transcript editing, library, notes, summary, metadata, and unrelated meeting-view behavior are out of scope for this evaluation.

### Overall threshold and evidence method

- The user-evidence threshold for `PRODUCT_ACCEPTED` is that **both participants pass every applicable scenario above**. The conditional quality scenario is excluded from the denominator only when the fixture has exactly one available quality/resolution option. A scenario that does not produce its pass condition is a failure for that participant; no average score or partial pass is used.
- Fer observes the controlled sessions and records a minimal scenario-by-participant results table, ephemeral codes, whether each scenario is pass/fail/N/A, and concise non-sensitive observations. No audio/video recording, names, identities, PII, or real meeting material.
- Evidence is bound to the exact candidate `6a9c838b1bab204d35ec046a4b9fad7e786ccbdb`. If a different candidate is tested, acceptance must be evaluated separately against that exact version.

## Evidence and limitations

- **User participants observed:** 0.
- **Scenarios observed:** 0.
- **User-evidence result:** Not available; candidate runtime readiness, synthetic fixture availability, and participant availability have not been verified for these sessions.
- **Technical evidence:** The task packet reports QA PASS for 21 frontend tests, typecheck, and diff-check, and Zev reported no actionable findings. Those are technical/security inputs only, not user evidence or product acceptance. Browser/device behavior and signed-source delivery integration were not tested according to the packet.
- **Limitations:** With no representative-user observations, the frozen user threshold cannot be evaluated. This report does not claim that the feature works for users or that any mandatory user criterion passes.

## Decision

`INSUFFICIENT_USER_EVIDENCE` for exact candidate `6a9c838b1bab204d35ec046a4b9fad7e786ccbdb`. The pre-test plan is frozen, but the minimum two-user evidence is absent. This is not `PRODUCT_ACCEPTED` and does not waive or change any approved requirement. Re-evaluate when the exact candidate is executable with the synthetic fixture and two representative users are available; retain this plan unless the evaluated candidate or approved criteria change.
