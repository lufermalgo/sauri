# QA combinado #899 + #900 — 2026-11-13

## Candidato exacto y alcance

- Worktree `.worktrees/qa-combined-899-900`, rama `qa/combined-899-900`.
- Base QA #899 `afa74e3d90cbf226500e5157f73d8a59a39466ce` (funcional `6b9eed3`). Segundo padre integrado: #900 `954b4eae5eacecbb45d1ba7f71fc4ace4319debc`.
- Merge reconciliado `583da329ce876d93bd752a54eff806c17fab13da`; candidato funcional final `4eda2bac16763ee33da694bc4224970b312c32e2`.
- No merge/push a main. Implementación de Nahuel reutilizada, no redelegada. Checkout raíz y cambios ajenos intactos.
- Resumen, plantillas, indicador, pantalla de reconocimiento, controlador de playback y reproducción original de #895/#899 conservados. Solo se adaptaron seams de API/router/TranscriptView para la proyección v2.
- La escucha representativa sigue sobre el original, con la política existente de tramos extendidos; para v2 usa exclusivamente intervalos validados y su speaker de presentación, nunca el assignment padre. Un documento inválido no habilita escucha por identidad legacy. Dos regresiones nuevas verifican coexistencia del SummarySection, nombres revisados, fallback íntegro y límite de escucha 0–6000 sin abarcar el tramo incierto 6000–12000.
- Se preservan `latest_attempt`, último resultado completado, `processing_revision`, `overlap_ms` y review de esa revisión. La prueba generacional ahora corre también con `presentation_version=2`.

## Migración y defecto de integración corregido

#899 ya instala `014_meeting_summaries_templates`; #900 proponía otro hijo directo de 013. En esta combinación la proyección pasa a **015_final_presentation**, hija de **014_meeting_summaries_templates**. Head único; solo añade dos columnas JSON nullable; sin backfill ni cambios de fuentes.

La primera integración PostgreSQL encontró un defecto técnico real de combinación: la FK ORM circular users→summary_templates no tenía nombre, a diferencia de la migración. `metadata.drop_all` fallaba con `Can't emit DROP CONSTRAINT ... it has no name`, contaminando la segunda parametrización. Se alineó el nombre ORM con la FK ya publicada; no cambia la DB existente. Rerun en DB desechable nueva: 2 passed. No se relajaron assertions ni guardas.

## Pruebas ejecutadas sobre el candidato funcional

Intérprete: `/Users/lufermalgo/Proyectos/sauri/backend/.venv/bin/python` (`PY`). PostgreSQL 16 exclusivo de esta tarea, contenedor `sauri-qa-combined-899-900-pg`; sin tocar tablas de QA compartida para pruebas.

- Backend: `$PY -m pytest tests/asr_engine tests/diar_engine tests/transcription tests/diarization tests/meetings --ignore=tests/meetings/test_playback_storage_integration.py -q`: **376 passed, 1 skipped**. Rerun final PASS.
- Resumen/plantillas/processing/generaciones: `tests/summaries tests/templates tests/meetings/test_processing.py tests/speaker_review/test_generation_api.py --ignore=tests/summaries/test_worker_broker.py`: **79 passed** en primera combinación; después de ampliar el endpoint v2, suite generacional **30 passed**. Rerun final sin processing (ya cubierto por la suite amplia): **66 passed**.
- `tests/integration/test_final_presentation.py`: **2 passed** (PostgreSQL real; fuentes, activación por etapas, rollback/retry y acceso).
- `tests/integration/test_combined_presentation_migration.py`: **1 passed**. Cadena completa, 014 poblada con usuario/plantilla/transcript/fuente/diarización; upgrade 015, NULL de columnas nuevas, comparación de filas anteriores, downgrade solo en DB desechable y re-upgrade. Los primeros ensayos del fixture fallaron por omitir campos obligatorios; se corrigieron los datos sintéticos, no el esquema.
- Alembic: upgrade completo→015, downgrade→014 y upgrade→015 PASS. `alembic heads`: solo `015_final_presentation`.
- `tests/integration/test_summary_pipeline.py`: **9 passed, 6 skipped**. No se ejercitó broker desechable/agotamiento; no se inyectaron fallos en la cola del dueño.
- `npm test --workspace frontend`: **19 archivos, 185 pruebas PASS**, incluyendo las dos regresiones combinadas. Los primeros ensayos de esas pruebas se corrigieron para usar el currentLabel del review y reconocer la duplicación intencional de labels entre vista de playback y transcript; no se cambió funcionalidad para ocultar fallos.
- `npm run typecheck`: PASS global extensión/frontend/shared-types. `npm test --workspace @sauri/shared-types`: **2 passed**. `npm run build --workspace frontend`: PASS.
- Mypy focal de los 10 archivos de #900: PASS; nuevo test de migración: PASS. `mypy .`: **82 errores en 8 archivos** preexistentes, no se declara green global.
- Ruff de todos los Python cambiados y `git diff --check`: PASS. Un rerun de Ruff desde backend con paths relativos a raíz falló por rutas; repetido correctamente desde raíz, PASS.
- Avisos jsdom `HTMLMediaElement.pause` no implementado no son evidencia de reproducción real.

## Cronología y contención del video real

Al inicio confirmé ASR completado a **19:57:53Z**, 1519 fuentes, y `diarize` en vuelo (`0 ready / 1 unacknowledged`, DB in_progress, motor PID82512 activo). No se detuvo ningún worker/motor mientras trabajaba.

**Hubo competencia de recursos:** ejecuté suites backend/frontend, typecheck, builds Vite pequeños y PostgreSQL desechable aproximadamente **20:06–20:15Z**, mientras diarización seguía activa. No ejecuté inferencias/modelos extra. La advertencia posterior de Ansel sobre swap llegó después de esas ejecuciones; no puedo cuantificar qué parte de la demora les corresponde. No afirmo que mis pruebas fueran inocuas para el rendimiento. Builds de imágenes y cambio de runtime comenzaron después de comprobar finalización.

El video `b03c8ad0-d481-4770-ab36-5431990d8022` terminó diarización a **20:15:17Z**, **8 speakers / 1517 assignments**. A **20:16:40Z** DB completed y todas las colas `0/0`. El script volvió a comprobar cola vacía y ausencia global de revisiones pending/in_progress inmediatamente antes de detener worker para instalación.

## Instalación QA observada (~20:19Z)

Proyecto conservado `sauri-local-qa-04d47768cad6`. API/worker `sauri-combined-api:4eda2ba`; portal final corregido `sauri-combined-portal:4eda2ba-qa2` (ver incidente de configuración abajo). Imágenes derivadas de las bases ya instaladas de #899; solo COPY del código/app/migraciones y build frontend actual. Sin nuevas dependencias ni descarga de modelos. Primer COPY del portal falló por dist excluido del contexto; corregido usando contexto exclusivo frontend/dist, build PASS.

- DB viva: migración aditiva **014→015** PASS, con worker detenido y cola vacía. No downgrade vivo.
- API/worker/portal reemplazados; Postgres, Minio y RabbitMQ preservados con 8 horas de uptime. No mounts ni datos borrados.
- ASR reiniciado **solo después de finalizar video y vaciar cola**, desde el candidato exacto: nuevo **PID3923**, puerto8001, `ASR_ACOUSTIC_VALIDATION=1`, HF/Transformers offline, mismo checkpoint powerset local ya presente, mismos archivos de capability/token. Motor diarización **PID82512 / 8002 no se reinició**.
- Worker añade solamente `ASR_GRANULAR_PRESENTATION=1`, `DIARIZATION_EXCLUSIVE_ASSIGNMENTS=1`. Comparación automática confirmó cero cambios de entorno API/portal y solo esas dos claves en worker; se conserva Ollama/resumen de #899.
- API health `{"status":"ok"}`, portal-health `ok`, ASR health `{"status":"ok"}`; portal healthy. Worker suscrito transcribe/diarize/summarize/summarize.failed. Health no demuestra inferencia acústica del nuevo flujo.
- No se solicitó reproceso ni se modificó la revisión del video terminado: sigue siendo salida legacy sin proyección retrospectiva. La nueva ruta requiere una ejecución futura autorizada.

## Preservación comprobada

Dump PostgreSQL predeploy privado (modo0600) en temp `combined-predeploy.dump`; no publicarlo. Antes/después se compararon cantidad + MD5 de JSON de todas las filas, excluyendo solo las dos columnas nuevas de diarizations. **Igualdad exacta** para: 9 meetings, 9 transcripts, 4002 speech_turns, 9 diarizations, 38 speakers, 3987 assignments, 9 reviews, 38 review_items, 9 recordings, 9 media_sources, 0 meeting_summaries y 1 summary_template. Esto prueba que el despliegue no sustituyó fuentes/resultados/revisiones existentes; no afirma que exista ya un resumen generado ni acredita bytes de objetos con un hash nuevo. Ningún comando de despliegue escribió al object store.

Artefactos operativos privados en `/var/folders/x6/96ywnlxd7kxfr4qns4c8_0hc0000gn/T/apx-scratch-d2296a21/th_0eb2f9523cf04772/`: `deploy-combined.py`, `combined-899-900.override.yml`, Dockerfiles de imágenes, `combined-before-hashes.json`, `combined-after-hashes.json`. El contenedor PostgreSQL desechable propio se detiene al cierre, sin borrar almacenamiento del dueño.

## Incidente de configuración detectado por Ansel y corregido

El primer portal derivado (~20:19Z) se armó con `npm run build` sin la variable que sí establece el Dockerfile oficial: `VITE_API_BASE_URL=''`. Como consecuencia el bundle `index-BkWKw7cC.js` usó el fallback `http://localhost:8000`; Ansel observó Failed to fetch. Fue un error de esta instalación, no se atribuye al dueño ni se considera una prueba pasada.

Se reconstruyó con **`VITE_API_BASE_URL='' npm run build --workspace frontend`**, usando el proxy `/api/` del nginx existente hacia `api:8000` (el API también se expone en18100, pero el portal usa same-origin). No se usa una variable inventada `VITE_API_URL`. Se reemplazó **solo portal**, dejando API, worker y motores en ejecución. Imagen final `sauri-combined-portal:4eda2ba-qa2`; HTML servido apunta a **`/assets/index-DFMxJy96.js`**. Comprobación directa del JS realmente servido: 0 `http://localhost:8000`, 0 `/excerpt`, 0 `Play excerpt for `, sí `Listen to `. Ruta proxied `/api/v1/meetings/` devuelve401 sin auth, no conexión fallida; no se usó token para validarla.

Sobre el reporte del dueño de **404 en una grabación NUEVA** con botón exacto `Play excerpt for Speaker 5`: ese texto y `/excerpt` no están en el código reconciliado ni en ninguno de los dos bundles combinados servidos en15273. A20:21Z el puerto15173 dio connection refused. Esto descarta la reintroducción de ese botón desde el candidato actual, pero **no prueba todavía cuál pestaña/origen/bundle emitió el404 del dueño**, ni permite atribuirlo a datos históricos. Ansel conserva la inspección de navegador y la reproducción real. El candidato mantiene el original y nunca llama `/excerpt`; sus regresiones incluyen escucha v2 acotada y fallback sin identidad legacy. No afirmo que un401 sin auth sea una validación de reproducción protegida.

## Límite interactivo / aceptación

APX abrió `http://127.0.0.1:15273/` en **t1**. `browser_snapshot` devolvió **paused_by_user: the human has this tab right now; wait for them**. No arrebaté la pestaña ni usé tokens o navegador alternativo. Falta recorrer la combinación instalada, captura real de resumen/presentación/playback y escucha/aceptación acústica coordinadas por Ansel. No hay captura de aplicación validada en esta entrega. No se declara aceptación del dueño ni CI remota pasada.
