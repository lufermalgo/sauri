# Pilot done — four owner-run checks

This checklist is the predeclared completion rule for Fer's pilot run, not a claim that the current product passes. Run it on one controlled, non-customer Meet capture. Do not use customer information, repeat an upload or processing run of the recording already processed, or treat a missing capability as a pass. If a safe, authorized test capture is not available, stop and mark the affected checks **Not available yet**.

**Before starting:** note the portal build/version being checked (if shown) and use `http://127.0.0.1:3201/`. Use only a controlled test meeting and non-sensitive/synthetic spoken content; make sure any recording is appropriate and participants have been informed/permission obtained. Keep the recording identifier only as needed to find this test in the portal; do not copy transcript or participant details into this checklist. Use the same one new recording for checks 1–4; do not upload or process it a second time.

For each check, record exactly one outcome: **Pass**, **Fail**, or **Not available yet**. Record a short, non-sensitive observation. Do not infer a pass from logs, code, or a prior recording when the visible result is required.

## Checks

1. **Record a Meet with the extension**
   - In the controlled Meet tab, start recording using the Sauri extension and follow the tab-selection flow.
   - **Pass only if** the extension visibly starts capture for the selected Meet tab and the resulting recording is available in Sauri for this same test session. If capture does not start or no corresponding recording appears, mark **Fail**. If the extension or a safe test setup is unavailable, mark **Not available yet**.

2. **Closing the Meet tab starts processing automatically**
   - Close the Meet tab used for that capture; do not manually upload the recording or start processing another way.
   - **Pass only if** the matching recording enters an observable processing state without another user action. If it remains idle/failed or requires a manual trigger, mark **Fail**. If no processing state can be observed, mark **Not available yet** and note what was visible; do not guess from elapsed time.

3. **Transcript and speakers are visible in the portal**
   - Open the matching recording in the portal and inspect its completed transcript.
   - **Pass only if** transcript text and speaker labels are both visible for the recording. An unresolved/uncertain speaker shown as `Speaker N` is an honest label and counts as visible; do not require every voice to have a known name or judge recognition accuracy in this pilot. If the transcript or all speaker labels are absent after processing is complete, mark **Fail**. If processing has not completed or the view cannot be reached, mark **Not available yet**.

4. **A summary is visible**
   - In the same portal view, look for the meeting summary as a distinct artifact, separate from transcript text.
   - **Pass only if** summary content for this recording is visibly presented as a summary. A tab or empty placeholder alone does not pass. If no summary is shown, mark **Not available yet** (not a pass, and not proof of a particular technical cause); if a purported summary is present but is clearly just the transcript, mark **Fail**. This check does not select or imply a summary provider.

## Pilot outcome

The pilot is **done only when all four checks are Pass** for the same controlled recording and the same checked build. Any **Fail** means the pilot did not pass; any **Not available yet** means the pilot is incomplete. Record outcomes and brief observations here without sensitive content:

| Check | Outcome (Pass / Fail / Not available yet) | Brief non-sensitive observation |
|---|---|---|
| 1. Extension capture and recording appears |  |  |
| 2. Tab close starts processing |  |  |
| 3. Transcript and speaker labels visible |  |  |
| 4. Summary visible as a separate artifact |  |  |

**Build/version checked:**  
**Test date:**  

These checks define this pilot only. They do not claim broader product acceptance, technical QA, privacy/security approval, or release readiness.
