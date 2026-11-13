# Candidato de #908 dirigido a main — #907

## Contrato y estado

APX `task_e2a1fd161b4d4910`. Nahuel prepara, publica y verifica; **Ansel revisa e integra**. Base `origin/main` = `ea1dd2acbe0de39e74d9f046816124037bedb465`. Rama `perf/907-main-delivery`, worktree `.worktrees/perf-907-main-delivery`, nuevos y aislados. No se edita el checkout raíz ni worktrees ajenos. No se ejecutaron modelos, inferencia acústica, nuevos benchmarks acústicos, transcripciones ni datos del dueño. Costo diagnóstico externo: ninguno.

#908 se fusionó en `qa/combined-899-900` mediante `bd638ee3a8fc6336a74235ab9f43c82b073ff6e7`, **no en main**. #902 tiene base `feature/summary-qa-delivery` y #899 apunta a main con conflictos; fusionar esas ramas completas arrastraría cambios de presentación, frontend e inferencia que esta unidad no necesita. Se extraen archivos pertinentes del candidato aprobado, no se reimplementa T1–T3 ni se incorpora toda la rama QA. Los requisitos y diseño de las tres fases se conservan; T6–T12 generales siguen siendo backlog, no una reescritura ya terminada.

## Inventario mínimo y trazabilidad

| Pieza | Archivos | Origen / razón |
|---|---|---|
| Entrega íntegra #908 | `.spectra/specs/performance-observability-pipeline/{.config.spectra,requirements.md,design.md,tasks.md,evidence.md,assignment-benchmark.json}`, `_tools/benchmark-assignment.py`, `backend/app/diarization/assignment.py`, `backend/tests/diarization/test_assignment_equivalence.py`, `backend/app/summaries/engine.py`, `backend/tests/summaries/test_engine_usage.py` | #907, commits `8b17a86` y `e51e2ec`, documentación hasta `63621c9`; todos los archivos de #908 preservados. Solo tasks/evidence reciben estado adicional de esta entrega. |
| Prerrequisito opt-in de assignment | `backend/tests/diarization/test_exclusive_assignment.py`; opción `require_exclusive=False` ya incluida en el archivo de #908 | `e4ca3b8`/#880; el modo por defecto conserva atribución acumulada. No se incorpora ningún cambio de sus callsites ni VAD/ASR nativos. Se incluye para conservar completo el contrato de #908 y probar ambos modos. |
| Solicitud durable y outbox | `backend/app/summaries/{__init__,service,repository,outbox}.py` | #278 (`744ae88`, `54f7d1c`), #284 (`4398c09`). Propiedad de reunión/plantilla, snapshot inmutable, generaciones y publicación confirmada recuperable. Sin estos módulos el engine de telemetría quedaría sin camino de ejecución real. |
| Worker y proveedor local | `backend/app/summaries/{factory,worker}.py`, `backend/app/worker.py` | #280 (`2b03b70`, `9589adf`), #282 (`30137b7`), #901 (`c4bd7c5`). Registro real del consumidor, configuración fail-closed y presupuesto finito; no se cambia la estrategia de generación. |
| Entrada/salida y recuperación | `backend/app/summaries/router.py`, `backend/app/main.py` | #284 y wiring del stack #899/#902: registrar rutas autenticadas y lifecycle del outbox. No se incorpora UI. |
| Entrega confirmada y terminal autenticado | `backend/app/infra/queue_rabbitmq.py`, `backend/tests/test_queue.py` | #278/#280. Confirmación `Basic.Ack` antes de marcar el outbox, firma por topic y reintento terminal sin pérdida. Se conserva el endurecimiento de logs existente sin payload ni URL del broker. |
| Esquema ORM coherente | `backend/app/infra/models.py` (solo nombre de FK de plantilla predeterminada) | El stack QA ya nombra `fk_users_default_summary_template_id_summary_templates`; coincide con migración 014 ya en main y permite teardown PostgreSQL con la dependencia circular. No se incorporan campos de presentación ni migración 015. |
| Configuración de worker | `.env.example`, `docker-compose.yml` | Solo `SUMMARIZATION_OLLAMA_URL`, `SUMMARIZATION_OLLAMA_MODEL`, `SUMMARIZATION_TIMEOUT_SECONDS`; no se crean servicios ni se cambian credenciales del dueño. Deben configurarse antes de instalar: la ausencia bloquea el worker, como en el stack aprobado. |
| Contratos de dependencias | `backend/tests/summaries/{test_engine_timeout,test_summary_api,test_worker,test_worker_broker}.py`, `backend/tests/integration/test_summary_pipeline.py` | RED/GREEN #277–#284 y #901, extraídos sin debilitar. PostgreSQL, RabbitMQ y rutas reales; generación simulada explícita en pruebas, nunca presentada como inferencia real. |

Ya están en main: modelos y migración 014 (#270), resolver/CRUD/default de plantillas (#272/#274/#276), contratos compartidos (#286). No hace falta repetirlos ni modificarlos.

Excluido deliberadamente: frontend, paquetes TypeScript, Rust, presentación/granularidad de transcripción, reconocimiento acústico, VAD, exportadores/collector OTel, paneles y admisión global de recursos. La telemetría entregada es el evento seguro de Ollama T5, no observabilidad integral desplegada. Los cambios de #899/#902 no incluidos no se declaran integrados.

## Pruebas reales del candidato

Entorno instalado del proyecto: `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/{python,ruff,mypy}` (Python 3.13). Comandos desde `backend/` salvo indicación. PostgreSQL 16 y RabbitMQ 3 locales exclusivamente temporales: `sauri-perf907-pg` (puerto local 51085), `sauri-t10-mq-90720261113` (51086). Datos sintéticos. Bases separadas `sauri_t11_sauri_qa_perf907`, `sauri_t15_perf907`, `sauri_t9_perf907`; admin de migración apunta a **ese contenedor**, nunca a una instalación compartida.

Variables de validación (credencial exclusivamente sintética y temporal):

```bash
export SAURI_QA_POSTGRES_URL='postgresql+asyncpg://postgres:synthetic-test-only@127.0.0.1:51085/sauri_t11_sauri_qa_perf907'
export SAURI_QA_SUMMARY_READ_URL='postgresql+asyncpg://postgres:synthetic-test-only@127.0.0.1:51085/sauri_t15_perf907'
export SAURI_QA_RABBITMQ_URL='amqp://guest:guest@127.0.0.1:51086/'
export SAURI_MIGRATION_TEST_ADMIN_URL='postgresql+asyncpg://postgres:synthetic-test-only@127.0.0.1:51085/postgres'
python -m pytest tests/diarization tests/summaries tests/templates tests/transcription tests/meetings tests/test_queue.py --ignore=tests/meetings/test_playback_storage_integration.py -q
```

**408 passed**, 34,86 s, 9 warnings de deprecación, sin skips. Incluye oracle diferencial de 400 ejemplos, privacidad/allowlist numérica y fallo de logger, timeout/cancelación, propiedad de artefactos/estado, atomicidad/idempotencia, concurrencia y reintentos reales de broker, upgrade/downgrade PostgreSQL de 014 preservando 012/013.

```bash
export SAURI_QA_POSTGRES_URL='postgresql+asyncpg://postgres:synthetic-test-only@127.0.0.1:51085/sauri_t9_perf907'
export SAURI_QA_RABBITMQ_CONTAINER='sauri-t10-mq-90720261113'
python -m pytest tests/integration/test_summary_pipeline.py -q
```

**15 passed**, 7,76 s, sin skips. Ruta request autenticado → outbox → RabbitMQ confirmado → worker → artefacto persistido y lectura; el motor se dobla explícitamente. Incluye caída y recuperación del broker propio durante lifespan. No se certifica nueva generación real ni instalación.

La primera preparación sin URLs produjo 10 errores y skips; se crearon los recursos anteriores. La primera base T11 no incluía `sauri_qa`, requerido por una prueba heredada de diarización; se usó el nombre que cumple ambos guards, sin tocar tests. Una ampliación a meetings intentó el contrato de storage sin `OBJECT_STORE_ENDPOINT`: falla idéntica comprobada en baseline `ea1dd2a` (KeyError); se excluye **ese único contrato ajeno** de la regresión ampliada, no se presenta como probado ni se accede al storage del dueño. La primera prueba de reinicio de broker falló porque Docker reasignó el puerto efímero al reiniciarlo; se recreó el contenedor propio con puerto explícito y la suite completa pasó. Ningún fallo se resolvió debilitando controles.

### Análisis estático

```bash
ruff check app/diarization/assignment.py app/summaries app/infra/queue_rabbitmq.py app/infra/models.py app/main.py app/worker.py tests/diarization/test_assignment_equivalence.py tests/diarization/test_exclusive_assignment.py tests/summaries tests/integration/test_summary_pipeline.py tests/test_queue.py ../_tools/benchmark-assignment.py
mypy app/diarization/assignment.py app/summaries app/infra/queue_rabbitmq.py app/infra/models.py app/main.py app/worker.py tests/diarization/test_assignment_equivalence.py tests/diarization/test_exclusive_assignment.py tests/summaries tests/integration/test_summary_pipeline.py tests/test_queue.py ../_tools/benchmark-assignment.py
ruff check .
mypy .
```

Focales: **Ruff PASS**, **mypy PASS (25 archivos)**. Full: **3 errores Ruff / 82 errores mypy en 8 archivos**, tanto en baseline aislado (`git archive origin/main backend`) como candidato; comparación de diagnósticos exactos: **0 nuevos, 0 eliminados**. No se afirma full lint/typecheck verde. Sin cambios TS/Rust/UX: typecheck TS, Rust y recorrido visual no corresponden a esta entrega.

### Benchmark de etapa, no acústico

Se preserva `assignment-benchmark.json` original de #908. Repetición CPU sintética sobre el mismo código y baseline `178f893` usando el comando sin opciones (desde raíz):

```bash
PYTHONPATH=backend /Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python _tools/benchmark-assignment.py
```

1500 turnos / 2154 segmentos / 4 hablantes, warmup 1, 7 muestras alternadas, construcción del índice incluida y salidas iguales: acumulado **223,152 → 5,806 ms (38,44x)**; exclusivo **249,209 → 5,754 ms (43,31x)**. Ambas reducciones >97%. No equivale a mejora de precisión ni a aceleración total. Intentar `--baseline-ref ea1dd2a` falla porque main carece del argumento exclusivo; el comparador de ambos modos debe usar la base preoptimización de #908 (`178f893`, valor por defecto), no se inventa un tiempo para un modo inexistente en main.

## Seguridad y promoción

Revisión acotada: mismos archivos funcionales que #908/stack previamente aprobado; evento Ollama construido con allowlist, contadores inválidos omitidos, sin prompts/respuestas/modelos libres/URLs/excepciones en el evento, no introduce llamada adicional; errores de logging no modifican el resultado. Auth owner-scoped y mensajes firmados se conservan con pruebas. No se cambiaron hooks, CI, límites, secretos, proveedores ni costos. No se ejecutó pipeline con datos reales ni se tocó el despliegue local que usa el dueño.

Bloqueo externo verificado por API en run `43521042915`, anotación del check `132215072227`: “The job was not started because recent account payments have failed or your spending limit needs to be increased.” Los dos jobs tienen steps vacíos. No se elude CI, no se paga ni se cambian límites. El PR puede revisarse con esta evidencia local; no se afirma que sea integrable mientras los controles requeridos estén bloqueados. Ansel debe inspeccionar los checks del candidato actual y respetar las protecciones al integrar.

Publicación, SHA definitivo, PR, comprobación del diff y limpieza de recursos se registran en `evidence.md` al completar la entrega. Esta documentación no convierte el merge de #908 a QA en un merge a main.
