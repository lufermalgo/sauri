# Product Acceptance — Uploaded Meeting Default Title (#633)

## Candidate and scope

- **Outcome:** `INSUFFICIENT_USER_EVIDENCE`
- **Exact candidate:** `5f9b26afc76ec02e9c9d3a9c1ccc2ff5044a546f`
- **Candidate identity:** PR #634, `bugfix/issue-633-upload-default-title`, merged into `main` on 2026-10-30; exact candidate SHA remains `5f9b26afc76ec02e9c9d3a9c1ccc2ff5044a546f`.
- **Feature evaluated:** title behavior for newly uploaded meetings only. No retroactive renaming, migration, upload-screen redesign, or unrelated behavior is evaluated.
- **Authorized expected behavior:** when no meaningful title is supplied, use the uploaded recording's safe filename basename without disclosing a local path; preserve a non-empty explicit title. Issue #633 also requires safe handling of synthetic edge cases.
- **Technical evidence:** Nia's exact-candidate browser QA PASS is recorded in child task `task_820cc986bc9c4ddf`: authenticated synthetic upload→list; absent/blank titles displayed the basename, explicit title was retained, and markup-like filename content rendered as text. The run did not use a real meeting recording or a representative user's session. Focused tests and changed-file Ruff/mypy also passed per PR #634; security is `N/A`. None of this by itself is product acceptance.

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
- **Technical browser evidence:** one exact-candidate synthetic QA session (Nia, `task_820cc986bc9c4ddf`) passed the upload-to-list scenarios; the task includes a screenshot and DOM snapshot. This establishes the observed technical UI behavior only.
- **User evidence:** 0 representative functional-user sessions; 0 of 3 criteria observed in the predeclared user session. The QA session does not count toward the one-user minimum because it was an engineering verification with synthetic data, not a representative user's product-use observation.
- **Limitations:** the predeclared user-evidence threshold cannot yet be evaluated. No real recording/user observation was performed in this evidence set. The authorized real recording must remain local. The one-user minimum does not establish usability for a broader user population.

## Decision

`INSUFFICIENT_USER_EVIDENCE` for exact candidate `5f9b26afc76ec02e9c9d3a9c1ccc2ff5044a546f`. Criteria and evidence method remain frozen. Nia's exact-candidate synthetic browser QA is valuable technical evidence, but does not meet the predeclared minimum of one functional-user session covering all three criteria; no such user observation is documented. To change this outcome, Ansel must coordinate the missing non-sensitive user observation against this exact candidate (not another technical QA run); re-evaluate after any candidate change. This report does not approve privacy, security, or release readiness.
