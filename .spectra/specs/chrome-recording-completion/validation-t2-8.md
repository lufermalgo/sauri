# T1.9 / T2.8 — durable Side Panel feedback

2026-11-12. Issues #618 / #626; APX `task_3f4850ed89be4a22`.
Requirements R2.3–2.5, R3.1–3.4, R4.4; approved requirements/design and existing task plan apply. Publication is not integration or owner product acceptance.

## Scope and dependencies

Candidate is stacked on T2.4 PR #839 (`769f7fb`). T1.9 RED is preserved by cherry-pick of PR #838 (`7eb137b`, local `4c3e134`). Do not merge the standalone RED PR or this branch into the prerequisite branch. Fer retains integration. T2.5/T2.6 remain independent, as do the local deployment PRs. No edits to background, shared DB contracts, permissions, upload repair, retention, or Docker.

`RecordingCompletionStatus` replaces the capture-only presentation, retaining its error tests against the new component. It reads the selected durable completion and renders exactly one accessible status/alert with session/meeting identity. An absent worker hint recovers the most recently updated durable record (deterministic tie-break), not an arbitrary success; an explicit missing selection never falls back. Reads recur once per second while mounted and are cancelled/ignored on selection changes/unmount. Failed reads remove stale success and show unavailable, without exposing raw errors. Capture errors override successful-looking state. The component never creates a successful state: processing/asset verification stays in T2.4. No retry RPC is invented.

The panel waits for its initial session projection before recovering a fallback. A newer storage event wins over a late startup snapshot; rendering also gates on selection, preventing a flash of another session's success.

## Executed validation

- Before implementation: `npm run test -- src/panel/SidePanelApp.test.tsx`: **20 behavioral failures / 3 passed**, no import/setup failures.
- Full extension `npm run test`: **40 files / 250 tests passed** on the implementation. All existing generated properties retain 100 cases. One intermediate full run hit a 5-second timeout in the unchanged background lifecycle suite, then a following property failure in the same file; nothing in those tests/production paths was edited. Reducing concurrency (`npm run test -- --maxWorkers=2 --minWorkers=1`) passed all 250, and the subsequent default full suite passed all 250. No timeout, assertion, or test count weakened.
- `npm run typecheck`, `npm run build`, `git diff --check`: passed.
- New direct component coverage: all 14 statuses, exact identity, capture-error override, selected missing record, latest-durable fallback, failed read/recovery, and late-read cancellation. Existing T1.9 includes panel reopen, loss of worker projection, cross-session isolation and changes without worker messages; added initial-projection latency/order tests.
- Browser APX, tab `t4`, `http://127.0.0.1:4186/`: production panel bundle served over an isolated temporary HTTP fixture with **synthetic Chrome/network state**, real browser IndexedDB. At width 320 px visually checked upload failure, ready, changing to another failed session (old ready removed), status unavailable and loss of worker projection; observed expected identity and exactly one outcome. Page error/rejection counter remained empty. Snapshots in routine thread `th_db1a8853f3ba4952` include the rendered pictures. Fixture/scripts are outside the repository and are not shipped.

## Limits and remaining work

This is real production UI driven by synthetic data, not real capture/upload/inference or protected-review end-to-end evidence. No live meeting, owner's DB/data or Docker resources were used. T3.1/T3.2 and owner acceptance remain pending. Integration must follow #839 and revalidate the final main-based candidate/CI; publication does not close the feature globally.
