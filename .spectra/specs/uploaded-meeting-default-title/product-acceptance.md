# Product Acceptance — Uploaded Meeting Default Title (#633)

## Candidate and scope

- **Outcome:** `INSUFFICIENT_USER_EVIDENCE`
- **Exact candidate:** `5f9b26afc76ec02e9c9d3a9c1ccc2ff5044a546f`
- **Candidate identity:** PR #634, `bugfix/issue-633-upload-default-title`, currently open against `main`; head SHA verified with `gh pr view 634`.
- **Feature evaluated:** title behavior for newly uploaded meetings only. No retroactive renaming, migration, upload-screen redesign, or unrelated behavior is evaluated.
- **Authorized expected behavior:** when no meaningful title is supplied, use the uploaded recording's safe filename basename without disclosing a local path; preserve a non-empty explicit title. Issue #633 also requires safe handling of synthetic edge cases.
- **Technical evidence:** packet reports Nia `PASS` for 21 focused tests and changed-file Ruff/mypy checks; security is `N/A`. This is not user evidence or product acceptance.

## Frozen user-evaluation plan

This plan is fixed before user observations. No user session for this exact candidate has been observed or documented in this report.

### Target user and minimum sample

- **Target profile:** a functional Sauri user uploading a recording through the web portal and then locating it in the meeting list.
- **Minimum sample:** one functional user session, as the owner explicitly required their repeat of the upload flow in a real browser before merge. This single-user sample supports only the observed initial-user workflow; it does not establish usability for a broader user population.
- **Test material:** one owner-authorized real recording for the no-title upload, kept local and never copied into the repository, task attachments, PR, screenshots, logs, or this report. A synthetic file/name may be used for the explicit-title and safe-name scenarios. Do not capture or share meeting content, participant identities, or personal data.

### Scenarios and observable thresholds

Run on the exact candidate in a real browser. Record only pass/fail and brief non-sensitive observations for each scenario; do not record the session or include the real recording's filename or contents in shared evidence.

| Criterion | Scenario | Pass condition |
|---|---|---|
| A | Upload a recording without a supplied title and open the resulting meeting in the list. | The new meeting displays the uploaded filename's basename as its title; no local directory/path component is shown. |
| B | Upload a synthetic recording with a non-empty explicit title. | The new meeting displays the supplied explicit title, rather than replacing it with the filename. |
| C | For safe-name handling, use a synthetic filename containing path-like components and markup-sensitive characters. | The resulting title contains only the safe basename; path components are absent, and special characters display as text rather than becoming active markup. |

### Evidence method and overall threshold

- The owner performs the browser scenarios against the exact candidate and reports the result per criterion, without disclosing meeting contents or identifying information. Evidence is a documented observation/result table, not a recording or screenshot.
- `PRODUCT_ACCEPTED` requires all three criteria to pass in the minimum one-user session. Any failed mandatory criterion means `PRODUCT_NOT_ACCEPTED`; if results are absent, incomplete, or not bound to this exact candidate, the result is `INSUFFICIENT_USER_EVIDENCE`.
- If the tested candidate changes, repeat acceptance against the new exact candidate; do not transfer this decision.

## Evidence and limitations

- **User sessions observed for this report:** 0.
- **Scenarios observed:** 0 of 3.
- **Browser evidence available:** none for the exact candidate. Existing automated tests and QA results do not establish the upload-to-list behavior in a real browser.
- **Limitations:** the predeclared threshold cannot yet be evaluated. The authorized real recording must remain local. The one-user minimum is tied to the owner's explicit requested test and is not evidence of broader user representativeness.

## Decision

`INSUFFICIENT_USER_EVIDENCE` for exact candidate `5f9b26afc76ec02e9c9d3a9c1ccc2ff5044a546f`. The criteria and evidence method are frozen, but no real-browser user observations are available. Before this product outcome can change, the owner must run the three predeclared scenarios on this exact candidate and provide non-sensitive pass/fail observations; otherwise the candidate must be re-evaluated after any change. This report does not approve merge, privacy, security, or release readiness.
