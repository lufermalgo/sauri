# Continuación QA combinada #899 + #900 + #901 — 2026-11-13

## Propiedad y alcance

Ansel transfirió explícitamente esta integración a la sesión `th_24c851fe9f0e4329`, luego de confirmar finalizada la ejecución original `th_e43e4f20b2ce4f1f`. Único worktree de ejecución: `.worktrees/qa-combined-899-900`, rama `qa/combined-899-900`, PR902 draft (base `feature/summary-qa-delivery`). Sin merge a main, sin ediciones en el checkout raíz.

Se revisaron `combined-899-900-qa.md` y el delta completo de #901. Merge funcional **6d03f2afe4621199d64d3f10753af9d8b303c6c6**, padres `d9289898feaacdf488a86d38825460fb68447381` y **c4bd7c573142ad248447d6724ae33378ad79004d**. Incluye también el commit RED padre `c470c21`, para conservar los 12 tests del contrato. Merge sin conflictos; no se reimplementó el fix.

Delta de producción: únicamente engine/factory de resúmenes y configuración/documentación del timeout. No cambios en frontend, reproducción, proyección v2, prompt, modelo, plantilla, retry policy, fuentes o esquemas. No generación real ni clips.

## Pruebas de esta continuación

Intérprete `backend/.venv/bin/python` del repositorio principal; comandos desde backend del worktree:

- `pytest tests/summaries/test_engine_timeout.py -q`: **12 passed**. Default/configuración finita positiva, HTTP lectura/conexión y límite total.
- `pytest -q tests/summaries tests/templates tests/meetings/test_processing.py tests/speaker_review/test_generation_api.py tests/integration/test_combined_presentation_migration.py --ignore=tests/summaries/test_worker_broker.py`: **98 passed**, 7 warnings Alembic `path_separator`, sin skips. PostgreSQL16 desechable propio; incluye migración summaries y preservación 014→015. URL `SAURI_QA_POSTGRES_URL` usa base exclusiva `sauri_t11_combined901`; `SAURI_MIGRATION_TEST_ADMIN_URL` apunta al mismo PG desechable. No tests destructivos contra QA persistente.
- Primer ensayo sin contraseña: 87 passed, 2 failed y 9 errors de autenticación PostgreSQL. Se corrigió la configuración del runner leyendo en memoria el entorno del PG temporal (sin imprimir la contraseña); rerun completo 98 passed. No se alteraron tests para aprobar.
- `mypy app/summaries/engine.py app/summaries/factory.py tests/summaries/test_engine_timeout.py tests/summaries/test_worker.py --follow-imports=silent`: **Success, 4 source files**. No se reclama mypy global green.
- `ruff check` sobre esos cuatro archivos: **PASS**. `git diff d928989..HEAD --check`: **PASS**.
- `npm run typecheck`: **PASS** en extensión/frontend/shared-types, aunque este delta no modifica TS. No cambios Rust, validación Rust no aplicable.
- `npm test --workspace frontend`: **19 archivos / 185 tests PASS**, incluyendo presentación combinada, reproducción, resumen e indicador. Avisos jsdom `HTMLMediaElement.pause` no implementado; no son evidencia de reproducción real.
- No se repitió HTTP de 61s, broker desechable ni la suite backend completa previa; se conserva evidencia anterior sin atribuir sus resultados al nuevo SHA.

## Instalación observada a 20:29Z

Proyecto existente `sauri-local-qa-04d47768cad6`.

- API/worker: **sauri-combined-api:6d03f2a**, image ID `sha256:1fba70e20bbf6923def47992fa959cd8c6b5bf29bf227cd2f75ad366ff0d028d`. Derivada de imagen combinada `4eda2ba`, COPY exclusivo de los dos archivos funcionales, sin dependencias/modelos nuevos. Label revision del SHA funcional.
- Portal **sin recrear**: `sauri-combined-portal:4eda2ba-qa2`, puerto **15273**, bundle **/assets/index-DFMxJy96.js**.
- API **18100**, PG persistente **15532**, RabbitMQ **15773/15774**, Minio **19100/19101**: mismos puertos. Motores nativos **8001/PID3923 y 8002/PID82512**, no reiniciados.
- Antes de actuar: 9 meetings completed, 9 diarizations completed, único outbox de resumen failed. Cuatro colas transcribe/diarize/summarize/summarize.failed **0 ready / 0 unacknowledged**. Broker `consumer_timeout={ok,1800000}`.
- Se detuvo primero API para congelar admisiones, se repitió gate de colas/DB y recién entonces se detuvo worker. No se interrumpió inferencia activa. Se repitió gate tras instalación: mismo resultado inactivo.
- Los archivos operativos históricos en temp de otra sesión no eran legibles bajo los permisos actuales. No se eludió la restricción: se reconstruyó la configuración desde `docker inspect` del runtime efectivo, preservando todos sus overrides. Configuración privada original guardada modo0600 en temp propio.
- Se recrearon **solo API y worker** con el mismo nombre, Config y HostConfig efectivos. Comparación automática: **entorno idéntico salvo SUMMARIZATION_TIMEOUT_SECONDS=900**, HostConfig completo, mounts, entrypoint y cmd idénticos. Se conservaron red/aliases, puertos, credenciales, modelos y flags acústicos. Labels de procedencia Compose conservados; hashes/image labels obsoletos removidos y label de candidato agregado. Una futura operación Compose debe mantener este candidato y timeout; los archivos históricos no se modificaron.
- Factory real en worker instalado: `timeout_seconds=900.0`, env `900`; hashes SHA256 engine/factory idénticos al worktree: `33808da61f619f3a5883d5c5ffba89892a556d9effba76595096a87395d6ff94` / `7d58f54d8d75b6709be46dde33a3cd77a0dad126d4ef0542787bf6eb229b0890`. Código revisado/tests: total y lectura900s, conexión10s. No se invocó generate ni Ollama.
- API `/health`: `{"status":"ok"}`; portal `/portal-health`: `ok`, estado healthy. Un curl inicial durante arranque recibió empty reply; health pasó en el reintento del mismo gate. `/health` en portal devuelve SPA, no se usó como prueba de salud.
- Logs worker: suscripción transcribe, diarize, summarize, summarize.failed a20:29:13Z; retención iniciada, sin errores observados en el filtro de arranque.
- Bundle realmente servido: 0 `http://localhost:8000`, 0 `/excerpt`, 0 `Play excerpt for `, 1 `Listen to `. No se reintrodujo la ruta vieja. Esto no identifica por sí solo la pestaña que originó el404 ni certifica reproducción protegida real.

## Preservación y limpieza

Antes/después del reemplazo se compararon **cantidad + MD5 del JSON ordenado de todas las filas de las 26 tablas públicas**: igualdad exacta. No hubo migración viva, reproceso, sustitución de revisión ni escritura al object store. Postgres/Minio/broker/portal/motores persistentes no se recrearon. No se afirma una comprobación nueva de bytes de objetos.

Artefactos privados en `/var/folders/x6/96ywnlxd7kxfr4qns4c8_0hc0000gn/T/apx-scratch-d2296a21/th_24c851fe9f0e4329/`: `deploy-timeout.py`, `Dockerfile.timeout`, `test-combined.py`, inspecciones privadas y hashes before/after. No publicar inspecciones: contienen configuración privada.

PG temporal heredado `sauri-qa-combined-899-900-pg`: se reutilizó para estas pruebas, se verificó ausencia de otros clientes (solo conexión administrativa propia) y **se detuvo y eliminó con `docker rm -v`**. Volumen anónimo exclusivo `32d77fe4be8a2a5c8acfc6254cb23beb6c34e6fd6440ac419b4e39a96b639a9b` eliminado; `docker volume inspect` devolvió no such volume, inventario del contenedor vacío. Intento inicial de rm sin detenerlo fue rechazado y no borró nada; se corrigió stop→rm. Los dos contenedores API/worker reemplazados, ya detenidos, también se eliminaron sin `-v`; imagen anterior e inspecciones privadas permiten reconstruir rollback. Ningún recurso persistente de QA se borró.

## Pendiente explícito

Ansel conserva navegador y nueva solicitud real autorizada. Esta continuación no abre otra sesión ni genera trabajo real. Falta validar resumen nuevo, reproducción protegida e identificar origen del404 con navegador APX; no se declara aceptación de producto ni CI remota green. PR902 continúa draft, sin merge main. T14/T26 `task_b7a67614c4f7420e` permanece abierta para ese recorrido.
