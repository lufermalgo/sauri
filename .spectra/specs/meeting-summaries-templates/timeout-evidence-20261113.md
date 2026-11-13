# T14/T26 — evidencia de corrección de timeout (2026-11-13)

## Candidato y alcance

Base: #899 `afa74e3d90cbf226500e5157f73d8a59a39466ce`, rama destino `feature/summary-qa-delivery`.
Rama aislada: `bugfix/summary-generation-timeout`; commit RED `c470c21` (solo tests nuevos sobre la implementación anterior). El commit GREEN siguiente contiene implementación, regresión PostgreSQL y trazabilidad. PR apilado, sin merge ni despliegue; Fer integra y Ansel coordina validación de runtime/navegador. Continuación de task_b7a67614c4f7420e, sin nueva tarjeta. No se modificó la rama/worktree de #899 ni #900.

## Diagnóstico acotado

`engine.py` usaba `httpx.AsyncClient(timeout=60.0)` para `/api/generate` con `stream=False`.
En logs existentes, consultados solo por patrones sin datos de sesión: retries worker
19:39:56 / 19:41:18 / 19:43:03 UTC; Ollama POST500 tras 1m0s/1m10s con cancelaciones.
La coincidencia más el límite de lectura explican el corte antes de cabeceras. El logger
del worker no muestra la clase de excepción; no se inventa stacktrace ni se atribuye el
500 a una falla intrínseca del modelo. No se solicitó ninguna inferencia real.

Default nuevo: 900s por intento, finito y configurable; conexión 10s. El presupuesto total
cancela el HTTP incluso con transporte que no implemente timeouts de inactividad. 900s no
es garantía de latencia/calidad para la grabación de Fer: evita el corte artificial de un
minuto, con margen debajo del ack timeout RabbitMQ default 1800s. Si el broker real tiene
otro límite, hay que mantener margen para DB/ack antes del despliegue.

## Comandos y resultados observados

Desde el worktree; `PY=/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python` (venv existente, sin instalaciones):

- RED antes del fix: `PYTHONPATH=backend /opt/homebrew/bin/pytest backend/tests/summaries/test_engine_timeout.py -q` → **12 failed in 0.49s**. Casos: default/configuración, inválidos, timeout de lectura de cliente propio/inyectado y límite total.
- GREEN: `PYTHONPATH=backend "$PY" -m pytest backend/tests/summaries/test_engine_timeout.py -q` → **12 passed** (última ejecución 1.74s).
- Regresión desde `backend`: `SAURI_QA_POSTGRES_URL=postgresql+asyncpg://postgres@127.0.0.1:49192/sauri_t11_timeout PYTHONPATH=. "$PY" -m pytest -q tests/summaries tests/templates tests/meetings/test_processing.py tests/speaker_review/test_generation_api.py --ignore=tests/summaries/test_worker_broker.py` → **91 passed, 1 skipped in 30.84s**. Skip: migración PostgreSQL requiere `SAURI_MIGRATION_TEST_ADMIN_URL`; no se configuró ese gate en esta corrida (caller ya lo verificó por separado). Incluye timeout total y HTTP503 sin artefacto/claim y transición terminal `failed` con PostgreSQL real.
- `cd backend && "$PY" -m mypy app tests/summaries/test_engine_timeout.py tests/summaries/test_worker.py --no-incremental` → **Success: no issues found in 76 source files**.
- `"$PY" -m ruff check backend/app/summaries/engine.py backend/app/summaries/factory.py backend/tests/summaries/test_engine_timeout.py backend/tests/summaries/test_worker.py` → **All checks passed**.
- `"$PY" -m ruff format --check backend/app/summaries/engine.py backend/app/summaries/factory.py backend/tests/summaries/test_engine_timeout.py` → **3 files already formatted**.
- `docker compose config --no-interpolate --format json` y `git diff --check` → exit0; configuración validada sin iniciar servicios.
- Transporte HTTP real loopback: script temporal `loopback.py` junto al worktree (no toca Ollama). Servidor `asyncio.start_server` en puerto aleatorio de 127.0.0.1; espera **61s sin cabeceras**, luego devuelve JSON canónico sintético. Motor con default nuevo → **PASS, elapsed=61.15s, calls=1**. No es mock HTTP ni evidencia de calidad del modelo.

## Aislamiento y limpieza

PostgreSQL16: único contenedor propio `sauri-summary-timeout-pg-75e708`, puerto host loopback efímero, base `sauri_t11_timeout`, datos en tmpfs, sin volumen persistente ni red nueva. Fixture creó/borró schemas UUID; consulta final `information_schema.schemata WHERE schema_name LIKE 't11_%'` → **0 filas**. Eliminado con `docker rm -f -v sauri-summary-timeout-pg-75e708`; inventario filtrado → vacío. Primera instancia propia con `--network none` fue recreada antes de pruebas para permitir conexión local; ambas eliminadas. No se tocaron otros contenedores/volúmenes/redes ni servicios nativos.

## Instalación segura (a cargo de Ansel; no ejecutada)

1. Revisar e integrar el PR **en la rama de #899**, preservando su contenido y cualquier entrega paralela coordinada (#900 no está incluida ni modificada). Construir una imagen versionada desde ese candidato combinado revisado; un build no requiere detener el worker actual.
2. Mantener el runtime actual mientras haya ASR/diarización u otros jobs activos. No hacer `compose up`, reinicio ni hot-patch del worker compartido durante la grabación `Transcribing`.
3. En ventana coordinada, una vez drenados todos sus trabajos y sin nuevas admisiones, configurar `SUMMARIZATION_TIMEOUT_SECONDS=900` en el entorno efectivo del worker. Verificar ack timeout del broker (> presupuesto + margen) y conservar URL/modelo locales y todas las credenciales/mounts/variables actuales. No imprimir secretos.
4. Recrear **solo worker** con la imagen revisada y configuración efectiva del proyecto/override QA que Ansel administra (`up -d --no-deps worker`, únicamente tras el drenaje). No ejecutar Compose sin esos overrides ni recrear API/DB/broker/portal/engines. `.env` sola no cambia un proceso vivo. Conservar la imagen/configuración anterior para rollback cuando no haya jobs activos.
5. Verificar arranque y suscripciones; Ansel coordina una nueva solicitud real y recorrido navegador. La solicitud ya fallida permanece fallida por diseño: no se reencola ni modifica automáticamente.

## Límites

No se rerunearon broker/integración completa que el caller ya pasó (19 API/worker y 15 pipeline en descartables), ni migración con admin; no se reclama ese gate para este SHA. No hay cambios Rust/TypeScript/UI ni aceptación de producto. No se cambió prompt, plantilla, modelo, esquema, transcript, retención, fallbacks ni retry policy. No se consultó ni expuso texto de transcripciones o secretos. Runtime/browser deliberadamente a cargo de Ansel después de coordinar, según contrato.
