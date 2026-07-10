# Session Status

## Current State

- **Branch**: main
- **Status**: idle
- **Last commit**: `6a1fe30` — Merge PR #74 (chrome-side-panel: Side Panel UI + Vista_De_Detalle)
- **Last session date**: 2026-07-10

## Completed

- **meeting-capture-transcription — 100% de tasks.md implementadas y probadas** (issue #71,
  branch `feature/issue-71-meeting-capture-transcription-tests`): las 22 sub-tareas opcionales
  (`*`) que quedaban pendientes — los 15 property tests de diseño (Hypothesis backend /
  fast-check cliente), unit tests puntuales (5.10, 9.4), tests de extensión (14.8, 14.9),
  tests de frontend (15.2), integración pytest+Docker (17.3) y e2e Playwright (17.4) — están
  implementadas y en verde. De paso se corrigieron dos bugs reales descubiertos por los nuevos
  tests contra Postgres real: `TranscripcionRepository.crear` no reutilizaba la sesión/transacción
  del llamador (rompía atomicidad) y `registrar_reunion` insertaba `EstadoHistorial` antes de que
  `Reunion` se flusheara (violaba FK en Postgres real, enmascarado por SQLite en tests unitarios).
  Ver PR asociado para detalle.
- **Milestone 2 — Transcripción (ASR)**: Tests merged (PR #50), implementation + improvements merged (PR #70).
  - ProveedorNube: Cloud provider with HTTPS/TLS encryption and API key authentication
  - ProveedorLocal: Enhanced with strict configuration validation
  - factory.py: Robust configuration parsing with comprehensive error messages
  - asr-engine: FastAPI microservice with faster-whisper backend
  - S3/MinIO integration for audio asset management
- **Milestone 3 — Identificación de hablantes (diarización)**: tasks 1–16 implementadas y GREEN.
  - 120 tests passing en toda la suite backend (incluye diar-engine contract).
  - Lógica pura: estado, motor, factory, proveedor_local, proveedor_nube, etiquetado, asignacion.
  - Persistencia: ORM models + migración 003 (validada en PostgreSQL real), repository.
  - Cola: `_leer_max_retries` generalizado para `DIARIZATION_MAX_RETRIES`.
  - Worker de diarización + cableado en `app/worker.py` (suscrito a 'diarizar' en runtime, verificado en logs).
  - Publicación de Mensaje_De_Diarizacion al completar transcripción.
  - diar-engine: servicio FastAPI real con pyannote.audio (contrato POST /diarize, GET /health).
- **chrome-side-panel** (issue #69, PR #74 merged): Side Panel UI + Vista_De_Detalle implementadas.
  - Shared core: design tokens, formatting, ordering, search, capture state machine.
  - Backend gaps cerrados: diarización expuesta, ids de turno, títulos de nota, auth real.
  - Cliente_De_API compartido, Side_Panel UI (Task 15), Vista_De_Detalle (Task 16).

## Cambios de infraestructura relevantes

- **Milestone 2 (Transcripción)**: ASR providers with validation, cloud encryption, local engine
- **Milestone 3 (Diarización)**: Pure state machine, diarization worker, diar-engine service
- **AGENTS.md**: New rule "No mocks in production code" (§3), worktree enforcement (§6-7)

## Known issues / tech debt (not blocking)

- diar-engine: pyannote.audio requiere HF_TOKEN y modelo gated en runtime del contenedor.
- torch/pyannote.audio no instalados en .venv local (pesados); se instalan vía Dockerfile.
- AUTH_DISABLED bypass needs real auth flow for the extension.

## Open GitHub PRs

- None. main is clean at `6a1fe30` (PR #74 merged).

## Deuda de proceso

- No GitHub issues created for Milestone 2 or 3 tasks (should have been created pre-implementation per AGENTS.md §13).
  Retroactive creation recommended for traceability.

## Next session priorities

1. Validate end-to-end ASR + diarization + chrome-side-panel workflow with real audio in Chrome.
2. Decide next product module per roadmap (see README.md) — e.g. notas/inteligencia con LLM, CRM (ClickUp).
3. Create GitHub issues retroactively for Milestone 2 and 3 tasks and close with PR references.
