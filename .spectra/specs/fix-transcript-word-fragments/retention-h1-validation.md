# H1 / #903 — retención transaccional de fuente y revisiones

## Alcance y entrega

- Encargo correctivo de Ansel, 2026-11-13; spec existente `fix-transcript-word-fragments`, delta #880 y hallazgo preliminar T20/#659. T20/gate final **no se cierran** por esta pieza.
- Base exacta: `178f893551405774bc5d9006d0eb90cd4c33f586` (PR902).
- Código y pruebas: commit `f304adfec4c83f3382ece7760aa61a5e30b2715b`.
- PR para revisión e incorporación QA por Ansel: https://github.com/lufermalgo/sauri/pull/905, base `qa/combined-899-900`; rama `bugfix/issue-903-retention-revisions`, worktree `.worktrees/fix-retention-h1-902`.
- Sin merge ni instalación viva. No cambios de esquema/migraciones, HTTP/UI, retención temporal, modelos/inferencia o reconocimiento protegido #248/#246/#253. Los deltas documentales no reabren fases aprobadas.

## Corrección y relaciones

`backend/app/retention/worker.py` elimina reviews del meeting fuente (cascadas de items/receipts), después todas las diarizaciones del transcript (speakers/assignments y ambos JSON), después transcript por DELETE SQL (turns, summary requests y artifacts mediante cascadas existentes). Ambas expiraciones usan el helper sin commit intermedio. Evita FK restrictivas y NULL updates ORM de turns cargados. Recording expirado sin transcript elimina también sus reviews legacy; no asume una diarización existente para encontrarlas.

La asociación review→fuente es por meeting/revisión porque `transcripts.meeting_id` es UNIQUE y no existe FK review→transcript. No se elimina por dueño ni se llama a `delete_meeting`. Snapshot exacto confirma preservación de otro meeting del mismo dueño y uno ajeno, sus nombres/reviews, usuarios/plantillas, meetings, claims, operaciones/outbox de recuperación y ledger de resumen sin contenido. Expirar solo transcript conserva recording/media/objetos vigentes. Borrado de audio/video por expiración de recording mantiene su comportamiento previo.

## RED → GREEN real

Archivo nuevo: `backend/tests/integration/test_retention_revision_artifacts.py`.

1. Antes de editar producción: **4 failed in 1.65s**, sin errores de setup. Se observó `ForeignKeyViolationError: diarizations_transcript_id_fkey`, `NotNullViolationError: speech_turns.transcript_id` y dos fallos de falta de borrado previo de hijos.
2. Primer helper: **4 passed in 1.08s**.
3. Contraejemplo adicional legacy, recording expirado sin transcript: **1 failed in 0.34s**; permanecían reviews/items/receipts. Se corrigió el caso sin fuente.
4. Suite final ampliada: **7 passed in 1.67s**, PostgreSQL 16 real, esquema completo y FK activas; no SQLite como sustituto.

Los siete casos son: expiración por recording y por transcript con tres generaciones completed/failed/pending; legacy sin transcript; rollback ante fallo después de borrar hijos para ambas rutas; rollback ante fallo justo antes de commit para ambas rutas. Se cargan turns en ORM en el caso independiente. Se verifica el snapshot de todas las tablas, incluyendo ambos JSON, nombres, summaries, media y auditoría. Retry y ciclo repetido prueban idempotencia.

El fallo inyectado tras hijos consulta que ya se borraron las diarizaciones dentro de la transacción real; el fallo de commit ocurre después de flush. Tras rollback se compara el snapshot completo original. Solo el punto de fallo y ObjectStore están inyectados; persistencia, constraints y transacciones son PostgreSQL reales. No se debilitaron pruebas existentes.

## Comandos ejecutados

Intérprete del proyecto: `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python` (Python 3.13.4). Desde `backend/`, con `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider` y cachés auxiliares fuera del repositorio:

```bash
$PY -m pytest tests/integration/test_retention_revision_artifacts.py -q -p no:cacheprovider --tb=short
$PY -m pytest tests/retention tests/meetings tests/diarization \
  tests/speaker_review/test_generation_api.py \
  tests/speaker_review/test_review_state.py \
  tests/speaker_review/test_review_resume.py \
  tests/speaker_review/test_disposition_idempotency.py \
  tests/integration/test_retention_revision_artifacts.py \
  tests/integration/test_diarization_reservation_concurrency.py \
  tests/integration/test_final_presentation.py -q -p no:cacheprovider --tb=short
$PY -m ruff check --no-cache app/retention/worker.py tests/integration/test_retention_revision_artifacts.py
$PY -m ruff check --no-cache .
$PY -m mypy --cache-dir=<scratch>/mypy-h1 .
git diff --check
```

**Regresión final configurada: 345 passed, 7 warnings in 23.05s**, exit 0. Incluye H1, retención existente, meetings, diarización, reviews seleccionadas, concurrencia PostgreSQL completa y presentación final. Las advertencias son deprecaciones existentes (`utcnow`, HTTP_422, adaptador datetime de SQLite), no fallos nuevos.

Entorno dedicado: `SAURI_QA_POSTGRES_URL=postgresql+asyncpg://sauri_qa@127.0.0.1:60029/sauri_qa_retention`; `OBJECT_STORE_ENDPOINT=http://127.0.0.1:60839`, bucket `sauri-h1-903-synthetic`, credenciales sintéticas de fixture y `PLAYBACK_TEST_FRONTEND_ORIGIN=http://localhost:5173`. La suite de playback verificó range/CORS reales. Se sembró exclusivamente `qa/synthetic.webm` con bytes sintéticos para las consultas de disponibilidad de tests con inferencia mock; nunca se invocó inferencia real ni se usó audio del dueño.

### Intentos fallidos y deuda comparada, sin ocultarlos

- Un primer comando añadió todo `tests/speaker_review`: colección bloqueada por `ModuleNotFoundError: app.transcription.processing_pipeline` en `test_processing_readiness.py`. Reproducido igual en copia exacta de base `178f893`. No se implementó/activó ese trabajo protegido ni se afirma PASS del backend completo. La selección explícita pertinente de arriba está identificada por archivo.
- Primer intento de esa selección: **341 passed / 4 failed** por `KeyError: OBJECT_STORE_ENDPOINT`. Se corrigió el entorno de prueba con S3 temporal real desde imagen ya cacheada, sin cambiar tests, y se repitieron todos los 345 con éxito. No se usó el store vivo ni se sustituyó esa integración por mocks.
- Ruff de archivos modificados: **PASS**. `ruff check .`: exit 1, **3 diagnósticos preexistentes**, salida byte-idéntica a base (`009_recording_media_sources.py` imports, `auth/token.py` UTC, `test_processing_readiness.py` imports).
- `mypy .`: exit 1, **82 errores en 8 archivos**. Comparé contra `git archive 178f893 backend` en scratch con mismo intérprete/configuración. Multiconjunto de diagnósticos idéntico, sin errores nuevos en worker/test H1; solo cambia orden y cantidad de archivos revisados (198→199). No es PASS global. Se corrigió durante desarrollo el único error nuevo de tipado en la sonda de fallo SQL.
- `git diff --check`, hooks normales de commit/push: PASS. No TypeScript/Rust modificado.

## CI remota y estado del PR

PR905 está OPEN, no draft y MERGEABLE respecto de QA, no integrado. La corrida CI `43514251944` no inició jobs por la anotación de GitHub: “recent account payments have failed or your spending limit needs to be increased”. Ambos checks figuran FAILURE/UNSTABLE por ese bloqueo de cuenta; `--log-failed` devuelve `log not found`. No es evidencia de tests ejecutados ni PASS remoto; no se cambió billing, límites ni workflows para eludirlo. Los resultados locales anteriores son la evidencia disponible para revisión de Ansel.

### Cierre documental H1.3 y revisión independiente

Ansel revisó el código exacto `f304adfec4c83f3382ece7760aa61a5e30b2715b` y registró [su evidencia independiente](https://github.com/lufermalgo/sauri/pull/905#issuecomment-6865834566): **23 PASS** PostgreSQL+retención en 2.44 s, Ruff de archivos cambiados y diff PASS, sin hallazgos nuevos accionables en el diff acotado. ObjectStore fue simulado en esa corrida; no reemplaza ni repite la evidencia S3 temporal de los 345 tests anteriores. El comentario documenta limpieza de sus recursos temporales. Esta evidencia es de Ansel; este cierre documental no ejecuta nuevamente suites.

Se verificaron las annotations de **ambos** checks `132191994090` y `132191993653`: jobs no iniciados por pagos fallidos/límite GitHub. CI externa bloqueada, no fallo funcional demostrado y no PASS remoto. No rerun, bypass, modificación de billing ni nuevo aviso de facturación.

**H1.3 completado solo como validación local y entrega documental.** No se declara integrabilidad plena, integración, instalación ni aceptación de producto; #903, T19 completo y T20/#659 siguen abiertos. Fer conserva merge; Ansel coordina incorporación QA. El commit documental previo `9108160954023930e3c9aba2f56a2d3c328e3320` y este cierre no modifican el código ni los tests de `f304adf`.

## Limpieza y preservación del entorno

Solo dos contenedores propios, imágenes ya disponibles:

- `sauri-h1-902-pg`, PostgreSQL 16 Alpine, tmpfs `/var/lib/postgresql/data`, puerto loopback aleatorio.
- `sauri-h1-903-s3`, imagen RustFS fijada en Compose, tmpfs `/data`, puerto loopback aleatorio.

Sin volúmenes persistentes ni redes nuevas (Mounts vacíos; tmpfs explícito). La instancia inicial PostgreSQL sin networking se reemplazó y eliminó al corregir conectividad local. Tras la suite final focal, un trap ejecutó `docker rm -f -v sauri-h1-902-pg sauri-h1-903-s3`; ambos eliminados. Consultas posteriores de contenedores/volúmenes/redes por las dos etiquetas de unidad devolvieron **listas vacías**. No se eliminaron imágenes cacheadas, recursos ajenos, datos persistentes ni entorno QA de Fer. El worktree original PR902 seguía limpio y en `178f893` al terminar pruebas.

## Identidad del código ensayado y límites

SHA256 de los archivos finales (sin cambios posteriores de código en el commit documental):

- worker: `2a937cdf8e4aef704a47f4175c96963ad558660fdaa76c1c85f27400cdf1a3ce`.
- test: `52bd59d87d0f637235d3bdd66fa388b77ba64550e8e07cfd7bd0b8da883ad28a`.

Logs y fixture temporal adicionales: scratch del hilo `th_71bd4b06fc0a426f` (`h1-red.log`, `h1-legacy-red.log`, `h1-final-regressions.log`, `h1-*-ruff.log`, `h1-*-mypy.log`). No contienen datos reales de reuniones.

La atomicidad demostrada es DB: objetos externos borrados antes de un error DB no se restauran, igual que antes. No se modifica el acceso HTTP durante el lapso anterior al ciclo de retención ni se certifica una carrera concurrente retención/inferencia en vivo. No hubo GPU, modelos, harness acústico, grabaciones reales ni aceptación de producto. T19 completo conserva sus bloqueos y T20 requiere su gate posterior independiente; esta corrección no otorga `NO_ACTIONABLE_FINDINGS`.
