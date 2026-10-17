# Task 1.2 diagnostic inventory

Complete, unfiltered command outputs, versions, and exit statuses are preserved in the sibling `.txt` files. Each Ruff reported location is counted under the active rule and backend-relative path; mypy errors are grouped by backend-relative path and error code.

## Ruff (189 reported locations)

- `alembic/env.py`: I001 × 2
- `alembic/versions/001_initial_schema.py`: I001 × 5
- `alembic/versions/002_unique_transcripcion_reunion_id.py`: I001 × 4
- `alembic/versions/003_diarizacion_schema.py`: I001 × 5
- `alembic/versions/004_usuarios_schema.py`: I001 × 5
- `alembic/versions/005_fix_uuid_columns_to_varchar.py`: E501 × 4, I001 × 4
- `alembic/versions/006_add_titulo_reunion.py`: E501 × 1, I001 × 4
- `alembic/versions/007_rename_schema_to_english.py`: E501 × 6, I001 × 4
- `app/auth/audit.py`: E501 × 1
- `app/auth/authorization.py`: B008 × 2, E501 × 1
- `app/auth/dependencies.py`: B008 × 1, B904 × 1
- `app/auth/token.py`: B904 × 1
- `app/diarization/assignment.py`: I001 × 1
- `app/diarization/cloud_provider.py`: B904 × 1
- `app/diarization/state.py`: I001 × 1
- `app/diarization/worker.py`: I001 × 3
- `app/infra/models.py`: I001 × 1
- `app/ingestion/router.py`: B008 × 3, B904 × 2
- `app/meetings/router.py`: A002 × 2, B008 × 12, B904 × 2, I001 × 1
- `app/meetings/schemas.py`: B008 × 1
- `app/meetings/service.py`: A002 × 1
- `app/meetings/state_machine.py`: I001 × 1
- `app/transcription/cloud_provider.py`: B904 × 1
- `asr-engine/main.py`: B904 × 4
- `diar-engine/main.py`: B904 × 4
- `tests/auth/test_access_control_property.py`: B008 × 1
- `tests/conftest.py`: B008 × 2
- `tests/diar_engine/test_contract.py`: I001 × 1
- `tests/diarization/test_assignment_property.py`: B007 × 1, B905 × 2, I001 × 1
- `tests/diarization/test_cloud_provider_property.py`: E402 × 2, I001 × 2
- `tests/diarization/test_diarization_engine_property.py`: I001 × 1
- `tests/diarization/test_integration.py`: E501 × 1, I001 × 7
- `tests/diarization/test_labeling_property.py`: I001 × 1
- `tests/diarization/test_local_provider_property.py`: E402 × 1, I001 × 1
- `tests/diarization/test_migration.py`: I001 × 1
- `tests/diarization/test_repository.py`: B017 × 9, I001 × 7
- `tests/diarization/test_worker.py`: E501 × 10, I001 × 2
- `tests/infra/test_queue_retries.py`: F401 × 1
- `tests/library/conftest.py`: F401 × 3, W292 × 1
- `tests/test_queue.py`: I001 × 6
- `tests/transcription/test_cloud_provider.py`: I001 × 3
- `tests/transcription/test_factory.py`: I001 × 4
- `tests/transcription/test_integration.py`: F401 × 1, I001 × 1
- `tests/transcription/test_local_provider.py`: B905 × 1, I001 × 1
- `tests/transcription/test_repository.py`: F401 × 4, I001 × 1
- `tests/transcription/test_worker.py`: I001 × 17

Ruff locations mapped: 189 across 46 paths. Footer: 189 errors; 132 fixable, including 6 unsafe fixes.

## mypy (292 errors)

- `tests/auth/conftest.py`: no-untyped-def × 1
- `tests/auth/test_access_control_property.py`: no-untyped-def × 2
- `tests/auth/test_auth_disabled_scope.py`: no-untyped-def × 3
- `tests/auth/test_login.py`: no-untyped-def × 6
- `tests/auth/test_user_model.py`: no-untyped-def × 2
- `tests/diar_engine/test_contract.py`: attr-defined × 3, no-untyped-def × 7, unused-ignore × 1
- `tests/diarization/test_cloud_provider_property.py`: no-untyped-def × 9
- `tests/diarization/test_factory_property.py`: arg-type × 1, assignment × 1, no-untyped-call × 3, no-untyped-def × 27, var-annotated × 1
- `tests/diarization/test_integration.py`: no-untyped-def × 11, type-arg × 3
- `tests/diarization/test_local_provider_property.py`: arg-type × 1, no-untyped-def × 6, type-arg × 1, var-annotated × 1
- `tests/diarization/test_migration.py`: arg-type × 1, no-untyped-call × 1, no-untyped-def × 8, union-attr × 2
- `tests/diarization/test_repository.py`: no-untyped-def × 5, type-arg × 5
- `tests/diarization/test_state_property.py`: arg-type × 1
- `tests/diarization/test_worker.py`: no-untyped-def × 10, type-arg × 12, var-annotated × 1
- `tests/infra/test_adaptadores_conformidad_property.py`: no-untyped-def × 5, type-arg × 10
- `tests/infra/test_queue_retries.py`: no-untyped-def × 7
- `tests/meetings/test_diarization_endpoint.py`: no-untyped-def × 5
- `tests/meetings/test_note_management.py`: no-untyped-def × 11
- `tests/meetings/test_title_history.py`: no-untyped-def × 1
- `tests/meetings/test_transcript_turn_id.py`: no-untyped-def × 1
- `tests/speaker_review/test_disposition_idempotency.py`: import-untyped × 2
- `tests/test_migration.py`: arg-type × 1, no-untyped-call × 3, no-untyped-def × 4, union-attr × 2
- `tests/test_queue.py`: attr-defined × 4, misc × 3, no-untyped-def × 28
- `tests/transcription/test_cloud_provider.py`: arg-type × 1, no-untyped-def × 5, type-arg × 1, var-annotated × 1
- `tests/transcription/test_factory.py`: arg-type × 1, no-untyped-def × 9
- `tests/transcription/test_integration.py`: no-untyped-def × 4
- `tests/transcription/test_local_provider.py`: arg-type × 1, no-untyped-def × 5, type-arg × 2, var-annotated × 1
- `tests/transcription/test_meeting_capture_property.py`: arg-type × 1, no-untyped-def × 1, type-arg × 3, var-annotated × 1
- `tests/transcription/test_repository.py`: no-untyped-def × 2, type-arg × 2
- `tests/transcription/test_worker.py`: arg-type × 2, no-untyped-def × 13, type-arg × 11, var-annotated × 2

mypy errors mapped: 292 across 30 paths. Footer: 292 errors in 30 files (120 source files checked).
