# Session Status

## Current State

- **Branch**: main
- **Status**: in-progress — Milestone 3 (diarización) COMPLETO en implementación: tasks 1–16 hechas. Pendiente: commit/PR.
- **Files being touched**: `backend/app/diarizacion/` (8 módulos), `backend/diar-engine/` (servicio real pyannote), `backend/alembic/versions/` (001 fix + 003 nueva), `backend/app/infra/queue_rabbitmq.py`, `backend/app/transcripcion/worker.py`, `backend/app/worker.py`, `backend/tests/diarizacion/` (9 archivos de test)
- **Last commit**: `de5908c` — Merge PR #50 (Milestone 2 TDD tests)
- **Last session date**: 2026-06-12

## Completed

- **Milestone 2 — Transcripción (ASR)**: ALL tasks done. PR #50 merged.
- **Milestone 3 — Identificación de hablantes (diarización)**: tasks 1–16 implementadas y GREEN.
  - 120 tests passing en toda la suite backend (incluye diar-engine contract).
  - Lógica pura: estado, motor, factory, proveedor_local, proveedor_nube, etiquetado, asignacion.
  - Persistencia: ORM models + migración 003 (validada en PostgreSQL real), repository.
  - Cola: `_leer_max_retries` generalizado para `DIARIZATION_MAX_RETRIES`.
  - Worker de diarización + cableado en `app/worker.py` (suscrito a 'diarizar' en runtime, verificado en logs).
  - Publicación de Mensaje_De_Diarizacion al completar transcripción.
  - diar-engine: servicio FastAPI real con pyannote.audio (contrato POST /diarize, GET /health).

## Cambios de infraestructura relevantes

- **Bug Alembic enum RESUELTO**: migración 001 y 003 usan columnas `String` (sin enums de Postgres),
  eliminando el `DuplicateObjectError`. Cadena 001 → 002_uq_transcripcion → 003_diarizacion_schema.
  `alembic upgrade head` corre limpio en PostgreSQL real (11 tablas, version=003_diarizacion_schema).
- Revision 002 renombrada a `002_uq_transcripcion` (cabía en varchar(32) de alembic_version).
- AGENTS.md §3: nueva regla "No mocks in production code".

## Known issues / tech debt (not blocking)

- diar-engine: pyannote.audio requiere HF_TOKEN y modelo gated en runtime del contenedor.
- torch/pyannote.audio no instalados en .venv local (pesados); se instalan vía Dockerfile.
- AUTH_DISABLED bypass needs real auth flow for the extension.

## Open GitHub PRs

- None. Cambios de Milestone 3 sin commitear aún.

## Next session priorities

1. Crear rama feature, commit y PR del Milestone 3 hacia main.
2. Validar diar-engine end-to-end con audio real + HF_TOKEN en el contenedor.
3. Considerar UX del Side Panel para exponer hablantes en la transcripción.
