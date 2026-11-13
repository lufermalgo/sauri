# T19 / #658 — corrección de fixture y concurrencia PostgreSQL

Fecha: 2026-11-13. Responsable: Ansel. Base exacta: PR #902 `178f893551405774bc5d9006d0eb90cd4c33f586`. Rama aislada `test/t19-concurrency-object-store-fixture`; no merge, despliegue ni cambios productivos.

## Descripción del bug y reproducción

Desde `backend/`, ejecutar `python -m pytest tests/integration/test_diarization_reservation_concurrency.py -q` con `SAURI_QA_POSTGRES_URL` apuntando exclusivamente a PostgreSQL QA descartable. La suite ya simula la inferencia y crea la referencia sintética `qa/synthetic.webm`, sin cargar un objeto real. El worker ahora verifica disponibilidad del objeto para mensajes con revisión explícita.

## Comportamiento actual (RED observado)

WHEN se ejecutan los tres casos de worker con revisión explícita sin configuración S3, THEN intentan construir un almacén productivo y fallan con `KeyError: OBJECT_STORE_ENDPOINT` antes de las aserciones de concurrencia. Resultado sobre la base exacta: **3 failed, 6 passed**, 1.68 s. No es un fallo demostrado del algoritmo de locking ni autoriza conectarse al almacén del dueño.

## Comportamiento esperado y solución técnica

WHEN la prueba usa audio e inferencia sintéticos, THEN la suite SHALL proporcionar disponibilidad sintética del objeto exacto, preservando transacciones y locks PostgreSQL reales. Se agrega una fixture opt-in `available_audio`, `AsyncMock(spec=ObjectStore)`, solo en esos tres tests. Se verifica el número exacto de inspecciones y la referencia `qa/synthetic.webm`; no se parchea el worker, repositorio, DB ni validación de disponibilidad productiva.

Esto corrige el entorno de la tarea T19 ya aprobada; no modifica requisitos, diseño funcional ni políticas y no constituye nueva fase de producto. No cambia ni debilita ninguna aserción previa.

## Comportamiento sin cambios / límites

- La suite SHALL CONTINUE TO usar PostgreSQL real; no SQLite.
- SHALL CONTINUE TO comprobar reserva única, claim único, rollback atómico, replay idempotente, identidad nueva por generación y preservación de revisión legacy.
- La disponibilidad y sus fallos SHALL CONTINUE TO comprobarse separadamente en las suites productivas existentes de ObjectStore/worker. Esta fixture no demuestra conexión S3 real ni calidad de diarización.
- No cambios a producción, datos privados, medios, inferencia/GPU, políticas de reconocimiento, #248/#246/#253 ni seguridad.

## Validación y criterios de aceptación

- GREEN final: misma suite, **9 passed**, 1.63 s; PostgreSQL16 Alpine local, contenedor propio, puerto loopback aleatorio, DB `sauri_qa_t19`, tmpfs. Sin red ni volumen nuevo. Un primer GREEN tuvo 9PASS/1error por un conteo nuevo incorrecto de fixture: un caso ejecuta dos revisiones y legítimamente inspecciona dos veces. Se corrigió el conteo específico por caso y se repitió todo.
- Ruff del archivo: PASS, sin exclusiones ni ignores nuevos.
- Mypy estricto del archivo: **28 errores preexistentes**, tanto base exacta como candidato (no se presenta como PASS). Fixture nueva anotada. Se conservan logs para comparar; el alcance no incluye reescribir todas las anotaciones antiguas.
- `git diff --check`: PASS.
- Verificación complementaria sobre base exacta: extensión **256PASS/41 archivos** (70.98 s), y `npm run typecheck` **PASS en los tres workspaces**. Sin cambios TypeScript.
- Cada intento PostgreSQL, incluido RED y primer GREEN fallido, eliminó su contenedor mediante trap `docker rm -f -v`; comprobación final: no existe `sauri-qa-continuity-t19-2139`. Servicios del dueño y contenedor de Nahuel preservados.
- Logs y runner: scratch de este hilo `th_2c248ddd63f9439f`: `t19-postgres.log`, `t19-postgres-green.log`, `extension-regression.log`, `typecheck.log`, `mypy.log`, `mypy-base.log`, `run-pg.sh`.

## Estado de entrega

PR incremental hacia `qa/combined-899-900`, revisión/integración reservada a Fer. El gate completo T19 sigue abierto: su otra suite no puede coleccionar `test_processing_readiness.py` sin #248; este resultado no cierra #658 ni T20. Nahuel mantiene independientemente H1/#903; no se editó su rama ni sus archivos. Sin aceptación global ni certificación del candidato acumulado posterior.
