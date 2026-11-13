# T3/T4 — precursor deshabilitado de recuperación manual

## Alcance y estado

Unidad aprobada #767/T3+T4, spec `fix-stale-meeting-recovery`; continúa RED histórico `d424f68`. La tarjeta histórica `task_23336cbd897c4cbb` no es accesible (`task_get`: not_found); continuidad APX `task_a5ef66a09de14cc4`, ejecutor Ansel. No existía PR ni ejecución activa de esta unidad al retomar. Rama/worktree canónicos `bugfix/issue-767-stale-recovery-t-3` / `.worktrees/bugfix-issue-767-stale-recovery-t-3`, inicialmente limpio `376beb6`; actualicé por merge normal de `origin/main` `ea1dd2a` antes de la prueba RED y producción. T2/persistencia ya está integrado. No edité checkout raíz ni trabajo de Nahuel (#907 activo independientemente).

Se implementan el POST autenticado y owner-only y `MeetingRecoveryService.recover(meeting_id, actor_id, idempotency_key)`. El resultado real es siempre `pilot_not_armed`; ni siquiera configurar modo pilot y un ID coincidente puede aceptar trabajo en esta etapa. Es el precursor fail-closed expresamente aprobado en T4, no una simulación de recuperación exitosa. No hay productor, operación, cambio de meeting ni consumo de gate. Clave de idempotencia obligatoria de 1–128 caracteres. El contrato completo de aceptación efectiva y su suite API corresponden a T18 y T11/T12; no se declaran completados.

**No integrado ni desplegado. Fer conserva merge.** No recuperación efectiva, piloto, frontend, modelos, inferencias, datos del dueño ni cambios de runtime. No se reabren aprobaciones ni se modifican requisitos/diseño.

## RED → GREEN observado

Intérprete `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python`; comandos desde `backend/`, siempre con `PYTHONDONTWRITEBYTECODE=1` y pytest `-p no:cacheprovider`.

1. Antes de producción: `python -m pytest -p no:cacheprovider tests/meetings/test_manual_recovery_routes.py -q`: **2 failed in 0.32s**, fallos conductuales por ruta ausente (404 vs resultado del dueño y detalle genérico vs Meeting not found). Sin errores de setup/importación.
2. Después de producción, mismas pruebas originales: **2 passed in 0.33s**.
3. Cobertura ampliada sin debilitar asserts: cuatro modos (ausente, disabled, pilot con allowlist coincidente e inválido), mismo 404 para no-dueño/inexistente, sin autenticación, clave ausente/vacía/excesiva; snapshots de meeting+operaciones+outbox y cola sin conectar/publicar. Respuesta exacta de dos campos finitos y sin título centinela en respuesta/log del caso de dueño. **9 casos de la unidad**.
4. Regresión focal con auth, idempotencia de ingestión y GET owner: **37 passed in 1.50s**.
5. Regresión ampliada `python -m pytest -p no:cacheprovider tests/meetings tests/ingestion tests/auth -q`: primer intento **181 passed, 1 failed**, por `OBJECT_STORE_ENDPOINT` ausente en test de integración S3. No era un error del código. Proveí servicio/bucket CORS exclusivamente temporal y repetí la suite completa: **182 passed, 6 warnings in 20.28s**, exit 0. Los warnings son deprecaciones HTTP422 existentes.
6. `python -m ruff check app/meetings/recovery_service.py app/meetings/router.py tests/meetings/test_manual_recovery_routes.py`: **PASS** tras ordenar import nuevo. `python -m mypy` con los mismos tres paths: **Success: no issues found**. No se afirma check global verde.
7. `app.openapi()` generó esquema exitosamente; POST documenta resultado finito y header obligatorio acotado. `git diff --check`: **PASS**. Revisión del diff: solo ruta, servicio fail-closed, tests y evidencia/trazabilidad.

### Compatibilidad mínima y toolchain actual

La validación inicial usó entorno existente Python **3.13.4**, Ruff **0.15.17**, mypy **2.1.0** (no es el entorno estricto #228). Revisé también `requires-python >=3.11`: usé `TypedDict` de `typing_extensions` para compatibilidad de Pydantic con Python3.11. Aprovisioné **venv nuevo exclusivo** en scratch `th_61bc0d207b584884/venv767` con `/opt/homebrew/bin/python3.11 -m venv <ruta>` y `<ruta>/bin/python -m pip install -e '.[dev]'`, sin alterar entornos existentes. Versiones resueltas: **Python3.11.12 / Ruff0.17.5 / mypy2.4.1**. Focal auth+ingestión+recovery **29 PASS**, Ruff/mypy de los mismos3paths **PASS**, `app.openapi()` **PASS**. Repetí después **toda** la regresión con RustFS temporal y esta toolchain nueva: **182 passed,6warnings in46.84s**, exit0; contenedor eliminado y `CLEANUP_VERIFIED`. No hay suppressions ni cambios de dependencia/configuración para aprobar.

## Aislamiento de datos y limpieza

Los fixtures API/DB usan SQLite sintética temporal con teardown existente; no se conectan a DB personal. El único servicio creado fue `sauri-qa-767-s3`, imagen **ya en caché** `sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b`, con `--pull=never`, memoria384m/CPU1, puerto loopback16567, `/data` y `/logs` en tmpfs, sin mounts/volúmenes persistentes del dueño, credenciales exclusivamente sintéticas y bucket descartable. CORS firmado Range real pasó, sin utilizar medios reales. `trap EXIT` ejecutó `docker rm -f -v` y búsqueda exacta de contenedor vacía: **CLEANUP_VERIFIED**. No creó red propia y se verifican volúmenes exclusivamente etiquetados sin remanentes. No se detuvieron ni limpiaron recursos ajenos.

## Límites

Este avance no recupera reuniones, no verifica todo el pipeline de recovery, no autoriza piloto ni cambios de configuración. SQLite valida esta ruta sin escrituras; no se usa como evidencia de locks/concurrencia PostgreSQL de tareas futuras. El S3 real de la regresión prueba entrega de bytes sintéticos, no aceptación de producto ni recorrido de UI. La facturación/límite de GitHub Actions ya impedía iniciar CI: revisar los checks del candidato publicado, no eludir controles ni declarar listo sin verificarlos.
