# Bugfix — Restore lint-clean backend baseline (Ruff and mypy)

## Descripción del Bug

On the unmodified `origin/main` snapshot `a753dee72703f3aeaf97c3b163de6b4954ab80e9`, the backend Ruff and mypy checks exit non-zero due to pre-existing lint/type findings. This blocks the existing default quality gate; this bugfix documents restoring the checks without relaxing lint/type configuration. Narrow team technical dispositions permit explicit exception chaining for the two `HTTPException` raises in `backend/diar-engine/main.py`, the two cloud-provider timeout branches in `backend/app/diarization/cloud_provider.py` and `backend/app/transcription/cloud_provider.py`, and the two `HTTPException` raises in `backend/asr-engine/main.py`; these changes alter only internal exception cause/traceback context and preserve the specified HTTP responses, logs, and `ExternalServiceError` behavior. A separate narrow team technical disposition permits renaming the internal `register_meeting` parameter that shadows the Python builtin `input`, together with its in-repository keyword callsite; the HTTP request/response contract and meeting origin semantics remain unchanged. No other runtime behavior change is permitted.

## Pasos para Reproducir

1. Check out the unmodified snapshot `a753dee72703f3aeaf97c3b163de6b4954ab80e9` in a clean worktree.
2. For the recorded baseline reproduction, use the exact existing environment from Nia's pre-change run: root `backend/.venv`, Python 3.13.4, Ruff 0.15.17, and mypy 2.1.0. Do not install or upgrade packages as part of this reproduction. The handoff does not record how that environment was provisioned, so these versions identify the observed run but do not guarantee that a newly provisioned environment will reproduce identical counts.
3. From `backend/`, run `ruff check .` and record exit code and complete output.
4. From `backend/`, run `mypy .` and record exit code and complete output.
5. From `backend/`, run `pytest -q` and record exit code and summary to establish the unchanged test baseline.

**Recorded baseline evidence:** On `a753dee72703f3aeaf97c3b163de6b4954ab80e9` in the environment above, Ruff exited 1 with 183 errors (126 fixable, 6 unsafe); mypy exited 1 with 290 errors across 29 files of 114 checked; `pytest -q` exited 0 (203 passed, 2 skipped, 23.88 s). The owner-authored issue #228 separately quotes 185 Ruff errors (128 fixable) from another environment, and itself notes 183 in the main checkout; counts differ by environment/tool invocation and are not universal acceptance thresholds.

**Separate corrected-candidate validation:** In a fresh environment provisioned from `backend/` with `pip install -e ".[dev]"`, record the actual resolved Python/Ruff/mypy versions before running the same checks. Issue #228 identifies Ruff 0.17.x and mypy 2.4.x as its target, but the handoff does not establish exact resolved versions for a fresh install. Do not represent this target validation as the historical baseline reproduction.

## Comportamiento Actual (Defecto)

WHEN `ruff check .` is run from `backend/` on the cited unmodified snapshot with the recorded existing environment,
THEN the command exits 1 and reports pre-existing lint findings (183 in Nia's recorded run).

WHEN `mypy .` is run from `backend/` on the cited unmodified snapshot with the recorded existing environment,
THEN the command exits 1 and reports 290 errors across 29 files of 114 checked.

WHEN the default `pytest -q` suite is run on that same snapshot and environment,
THEN it exits 0 with 203 passed and 2 skipped; this is the recorded pre-change behavior, not a claim about a later candidate.

WHEN Ruff 0.17.1 checks the exact `backend/diar-engine/main.py` source from candidate `6288107180c93abf4b72236f5b2887a8b283057c`,
THEN the command exits 1 with B904 at lines 198 and 211 because the two `HTTPException` raises inside `except Exception as e` do not explicitly chain the caught exception; the exact reproduction and output are recorded under Scope and Evidence Notes.

WHEN Ruff 0.17.1 checks `app/meetings/service.py` from base `origin/main` snapshot `34648abf50a79e3bdbf1dcbd50b229b072ca7ca2`,
THEN `ruff check app/meetings/service.py` exits 1 with A002 because `register_meeting` names a parameter `input`, shadowing the Python builtin; the exact reproduction and output are recorded under Scope and Evidence Notes.

WHEN Ruff checks `backend/app/diarization/cloud_provider.py` at the timeout branch in T-3.1.14 / issue #339, or `backend/app/transcription/cloud_provider.py` at the timeout branch in T-3.1.24 / issue #349,
THEN it reports B904 because the `TimeoutException` branch raises `ExternalServiceError` without explicit exception chaining; the corresponding `HTTPStatusError` and connect/request-error sibling branches already chain their caught exceptions.

WHEN Ruff 0.17.1 checks the pre-fix `backend/asr-engine/main.py` source at `81a093299ea9bc1555f73f6d520e024368ee5fa3` from T-3.1.25 / issue #350,
THEN it exits 1 and reports B904 at lines 172 and 204 because the two `HTTPException` raises inside `except Exception as e` do not explicitly chain the caught exception; the deterministic reproduction and diagnostics are recorded under Scope and Evidence Notes.

## Comportamiento Esperado (Correcto)

WHEN the backend development dependencies are freshly provisioned from the existing `pyproject.toml` and the supported project toolchain is used,
THEN `ruff check .` SHALL exit 0 without changing Ruff configuration or suppressing findings through ignores or relaxed rules.

WHEN the backend development dependencies are freshly provisioned from the existing `pyproject.toml` and the supported project toolchain is used,
THEN `mypy .` SHALL exit 0 without changing mypy configuration or suppressing findings through ignores or relaxed rules.

WHEN the default backend test suite is run on the corrected candidate,
THEN `pytest -q` SHALL exit 0; this criterion does not authorize weakening/skipping tests to obtain a pass.

WHEN either of the two caught exceptions in `backend/diar-engine/main.py` is translated into an `HTTPException`,
THEN the system SHALL explicitly chain that exception using `raise ... from e`, thereby preserving it as the explicit cause; the resulting HTTP status and response body SHALL remain unchanged.

WHEN `register_meeting` in `backend/app/meetings/service.py` is corrected for Ruff A002,
THEN the implementation SHALL rename its `input` parameter to a non-builtin name and update the sole in-repository keyword callsite in `backend/app/meetings/router.py` in the same change. Only the internal Python callable keyword name changes; the HTTP request/response contract and meeting origin semantics SHALL remain unchanged.

WHEN a timeout exception is translated into `ExternalServiceError` by either `backend/app/diarization/cloud_provider.py` or `backend/app/transcription/cloud_provider.py`,
THEN the system SHALL explicitly chain the caught timeout using `raise ... from exc`, matching the already-chained sibling error branches in each module; the resulting `ExternalServiceError` message and handling SHALL remain unchanged.

WHEN the caught exception at `backend/asr-engine/main.py:172` is translated into `HTTPException`,
THEN the system SHALL raise `HTTPException(status_code=500, detail=f"Audio download failed: {e}") from e`; the explicit cause SHALL preserve the caught exception and the HTTP 500 status and `detail` string SHALL remain unchanged.

WHEN the caught exception at `backend/asr-engine/main.py:204` is translated into `HTTPException`,
THEN the system SHALL raise `HTTPException(status_code=500, detail=f"Transcription failed: {e}") from e`; the explicit cause SHALL preserve the caught exception and the HTTP 500 status and `detail` string SHALL remain unchanged.

## Comportamiento Sin Cambios (Prevención de Regresiones)

WHEN existing backend application and test code is checked by Ruff and mypy,
THEN the system SHALL CONTINUE TO apply the repository's existing lint and typing configuration; this repair SHALL NOT relax configuration or add ignores.

WHEN the default backend pytest suite is run,
THEN it SHALL CONTINUE TO execute its default tests without weakening markers or skipping tests merely to obtain a passing result.

WHEN application code is changed to address a lint or typing finding,
THEN existing runtime behavior SHALL CONTINUE unchanged, supported by focused regression tests for each affected behavior or documented semantic-equivalence evidence for changes that are purely static/formatting and do not alter executable behavior; the only team-approved runtime-semantic exceptions are the explicit exception-context changes and the internal Python keyword rename specified above, and any other finding whose correction would alter runtime behavior must be stopped and reported for a separate decision.

WHEN either caught exception in `backend/diar-engine/main.py` is translated to an HTTP error after explicit chaining is added,
THEN the service SHALL CONTINUE TO return HTTP 500 with the same `detail` text (`Audio download failed: {e}` or `Diarization failed: {e}` respectively); only the internal explicit cause/traceback context may differ.

WHEN a timeout is caught by either named cloud-provider timeout branch after explicit chaining is added,
THEN the system SHALL CONTINUE TO raise the same `ExternalServiceError` with the same message, and no HTTP response or customer-visible failure cause SHALL be added; only the internal explicit cause/traceback context may differ.

WHEN either named `backend/asr-engine/main.py` exception is translated after explicit chaining is added,
THEN the service SHALL CONTINUE TO return HTTP 500 with the same `detail` text (`Audio download failed: {e}` or `Transcription failed: {e}` respectively) and preserve existing log lines; only the internal explicit cause/traceback context may differ.

WHEN the `register_meeting` parameter rename and its router callsite update are applied,
THEN the system SHALL CONTINUE TO use the same HTTP request/response contract and meeting origin semantics; only the internal Python callable keyword name SHALL change.

WHEN dependency provisioning is the only apparent explanation for a tool failure,
THEN the investigation SHALL CONTINUE to distinguish environment/toolchain effects from pre-existing source findings; no dependency/configuration change is authorized by this spec.

## Restricciones del Fix

- Scope is limited to existing backend lint/type findings in application code and tests, plus verification of the default backend test suite.
- Do not change `backend/pyproject.toml` lint or mypy configuration, add ignores, or relax rules.
- Do not make runtime behavior changes except the team-approved explicit exception chaining for the two `HTTPException` raises in `backend/diar-engine/main.py`, the two timeout branches in `backend/app/diarization/cloud_provider.py` and `backend/app/transcription/cloud_provider.py`, and the two `HTTPException` raises in `backend/asr-engine/main.py` at lines 172 and 204; plus the team-approved rename of the `register_meeting` `input` parameter in `backend/app/meetings/service.py` to a non-builtin name, with its sole in-repository keyword callsite in `backend/app/meetings/router.py` updated in the same change. Exception chaining may alter only internal exception cause/traceback context; the `diar-engine` and `asr-engine` changes must preserve HTTP 500 status, response `detail`, and existing log lines, and the cloud-provider changes must preserve the `ExternalServiceError` type, message, and handling. For the rename, only the internal Python callable keyword name may change; the HTTP request/response contract and meeting origin semantics must remain unchanged. Do not add features or make unrelated edits. Stop and report any other finding that cannot be corrected without runtime behavior change.
- Validate against a fresh environment provisioned with `pip install -e ".[dev]"` and the currently specified toolchain constraints; issue #228 names Ruff 0.17.x and mypy 2.4.x as its target. Do not treat the scratch-run versions or error counts as acceptance thresholds.
- Use synthetic data only. No real recordings, transcripts, identities, credentials, or customer data.

## Criterios de Aceptación

1. From `backend/` in a freshly provisioned project environment, `ruff check .` exits 0 with the repository's existing configuration unchanged.
2. From `backend/` in that environment, `mypy .` exits 0 with the repository's existing configuration unchanged.
3. The default `pytest -q` suite exits 0 for an unblocked acceptance result; tests and markers are not weakened or skipped to obtain a pass. If integration-marked tests fail solely because required external services are unavailable, record the exact command/output and unavailable service as a blocked result, preserve the tests/markers, and do not claim green acceptance until the tests pass in an environment with those services.
4. For every changed production-code path, focused regression tests for affected behavior pass, or the change is documented with semantic-equivalence evidence showing that it is purely static/formatting and leaves executable behavior unchanged. Focused evidence for the team-approved `diar-engine` and `asr-engine` exception-context changes verifies explicit chaining while preserving HTTP 500 status, response `detail`, and applicable log lines; for the two cloud-provider timeout branches, it verifies explicit chaining while preserving `ExternalServiceError` type, message, and handling; for the `register_meeting` rename, it verifies the HTTP request/response contract and meeting origin semantics remain unchanged. A full-suite pass alone does not establish this criterion.
5. No runtime behavior changes are included except the team-approved exception-context changes for the two `HTTPException` raises in `backend/diar-engine/main.py`, the two cloud-provider timeout branches, and the two named `HTTPException` raises in `backend/asr-engine/main.py`, plus the internal `register_meeting` parameter rename and its router callsite update. No new features, unrelated edits, lint/type ignores, or lint/mypy configuration changes are included.
6. The candidate report records exact Python/Ruff/mypy versions, each command and exit/output, and distinguishes toolchain-dependent findings from source findings.

## Root-Cause Hypothesis and Confidence

**Hypothesis (high confidence for the observed baseline):** existing backend application and test sources contain lint/type findings accumulated before this work. Nia reproduced the failures on the unmodified source snapshot; the mypy output includes `no-untyped-def` findings in tests, and the issue reports the same baseline failure using the main checkout's own environment. This makes dependency provisioning alone an insufficient explanation. Exact finding counts vary by environment/tool versions; the specific root cause of each diagnostic remains to be confirmed during repair. Candidate root cause and runtime effects remain unverified.

## Scope and Evidence Notes

- Authorized expected behavior: owner-authored GitHub issue #228, `https://github.com/lufermalgo/sauri/issues/228` (open; retrieved 2026-10-16). Its scope and completion criteria are represented above; this bugfix does not reopen product discovery.
- Reproduction evidence for the historical baseline: Nia's pre-change run and saved outputs referenced by Ansel: Ruff `stp_cfa0f075e26242da`; mypy `stp_2910f8592d9743e5`. These are evidence references, not candidate code SHAs.
- B904 reproduction on exact source candidate `6288107180c93abf4b72236f5b2887a8b283057c`: Ruff version `0.17.1`; from `backend/`, ran `git show 6288107180c93abf4b72236f5b2887a8b283057c:backend/diar-engine/main.py | /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check --stdin-filename diar-engine/main.py -`; exit code `1`. Output:

  ```text
  B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
     --> diar-engine/main.py:198:9
      |
  196 |     except Exception as e:
  197 |         logger.error("Failed to download audio: %s", e)
  198 |         raise HTTPException(status_code=500, detail=f"Audio download failed: {e}")
      |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  199 |
  200 |     try:
      |

  B904 Within an `except` clause, raise exceptions with `raise ... from err` or `raise ... from None` to distinguish them from errors in exception handling
     --> diar-engine/main.py:211:9
      |
  209 |     except Exception as e:
  210 |         logger.error("Diarization failed: %s", e)
  211 |         raise HTTPException(status_code=500, detail=f"Diarization failed: {e}")
      |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  212 |
  213 |     finally:
      |

  Found 2 errors.
  ```

  This reproduction was run by Zoya from the exact candidate source blob. Nia independently confirmed the candidate SHA and Ruff version but reported being unable to capture diagnostics. The full output above is the result of the exact command recorded here.
- Decision provenance for `backend/diar-engine/main.py`: Fer's recorded «autorizar 1 y 2 como excepciones acotadas» refers to previously listed B904 cases and is not claimed here as endpoint-specific approval. Ansel recorded the endpoint-specific technical disposition on 2026-10-19: allow `from e` for these two B904 cases while preserving the HTTP response.
- Decision provenance for the cloud-provider timeout branches: Ansel's task handoff authorizes chaining only for T-3.1.14 / issue #339 (`backend/app/diarization/cloud_provider.py`) and T-3.1.24 / issue #349 (`backend/app/transcription/cloud_provider.py`). Evidence recorded in that handoff: in each module the `HTTPStatusError` and `(ConnectError, RequestError)` sibling branches already chain; the timeout branch is the only unchained sibling. `ExternalServiceError` is defined and raised only in its respective module and is caught nowhere in `backend/app`; no customer-facing `failure_cause` is derived from `str(e)`, `repr(e)`, or `type(e)`. Ansel also reports the explicit chaining effect was executed on Python 3.11.12 and 3.13.4. This exception authorizes only internal cause/traceback context changes; it does not authorize other runtime behavior or any policy/configuration exception. Stop and route any further scope change to Ansel.
- Decision provenance for the ASR HTTP errors: Ansel's explicit 2026-10-21 amendment instruction is recorded in APX card `task_802908d6ac9446da` and authorizes only appending `from e` to the two `HTTPException` raises in T-3.1.25 / issue #350 (`backend/asr-engine/main.py`: `Audio download failed: {e}` and `Transcription failed: {e}`). It requires HTTP 500, the exact `detail` strings, and all other runtime behavior to remain unchanged, with no lint ignores or configuration changes. QA evidence is recorded in card `task_d02b6e8c4d814984`: Nia PASS for candidate `2b2fa4e06738ebe6a5f02d504aada0716c78f455` (PR head `47ec0c33ae6f13aa5efce3442f52f80301e4175f`), including Ruff and two focused tests. The present amendment changes only this specification artifact; it does not alter that reviewed code candidate.
- Reproduction evidence for ASR B904: From `backend/`, using Ruff `0.17.1`, ran `git show 2b2fa4e06738ebe6a5f02d504aada0716c78f455^:backend/asr-engine/main.py | /Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff check --stdin-filename asr-engine/main.py -`; exit code `1`. The pre-fix source is exact base `81a093299ea9bc1555f73f6d520e024368ee5fa3`. Output includes B904 at `asr-engine/main.py:172` for `Audio download failed: {e}` and at `:204` for `Transcription failed: {e}`; it reports four findings total, the other two being the separately tracked SIM115 and SIM105 findings. This run reproduces the exact lint defects authorized by this amendment.
- A002 reproduction on base `origin/main` `34648abf50a79e3bdbf1dcbd50b229b072ca7ca2`: Ruff version `0.17.1`; from `backend/`, ran `ruff check app/meetings/service.py` using `/Users/lufermalgo/.virtualenvs/sauri-issue-262-lint-baseline-a6c74bb/bin/ruff`; exit code `1`. Literal output:

  ```text
  A002 Function argument `input` is shadowing a Python builtin
     --> app/meetings/service.py:156:5
      |
  154 | async def register_meeting(
  155 |     session: AsyncSession,
  156 |     input: dict[str, Any],
      |     ^^^^^
  157 |     created_by: str,
  158 | ) -> Meeting:
      |

  Found 1 error.
  ```

  This reproduction was run against the clean worktree at the specified base commit; the command reports the literal output above.
- A002 decision provenance: Ansel's instruction on APX card `task_802908d6ac9446da` authorizes the narrow team technical disposition stated above for T-3.1.21 / #346. The reviewed plan source is approved `tasks.md` snapshot `a498c14b079052fc5c62891d5d6d42d9c6c6a181`; its design source is `design.md` snapshot `0baa3d2a9ee54f5f6e9d9f64bd91ea8f17bc465d`. This authorization is limited to the internal Python callable keyword rename and the in-repository callsite update, with no lint ignore/configuration or other behavior change.
- The saved project baseline claim does not assert that a future candidate passes. No implementation or corrected candidate has been validated in this authoring phase; the exact pre-fix A002 and B904 reproductions above are diagnostic evidence only.
