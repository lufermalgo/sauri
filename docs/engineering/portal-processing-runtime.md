# Candidato combinado de seguimiento — #892 / PR #894

## Autorización y alcance

Ansel autorizó el 13/11/2026 conectar técnicamente API y portal al entorno de prueba solicitado por Fer, conservando servicios, datos y configuración. Merge reservado a Fer. No instalar #893 (muestras pendientes de decisión de privacidad); no crear cargas, samples, migraciones ni ejecutar grabaciones privadas. La prueba autenticada APX queda pendiente de login autorizado por Fer.

## Identificación exacta del runtime previo

No se usó HEAD `baea619` del worktree de referencia como sustituto de la API real:

- API activa `sauri-core-api:bcc52de`, imagen `sha256:a0e535de7af6126a8e5436c379836be3eedaa4cdbd838e062a6c365131d79875`.
- Los **61 módulos Python** de `/app/app` se contrastaron por SHA-256 contra Git `bcc52deb6061aaa9fe36bfcb1ede302ce3dfb2aa`: **cero diferencias**. Incluye la API generacional #850/#652/#653 y sus controles.
- Portal activo `sauri-core-portal:issue880`, imagen `sha256:fef9a16a0aa7860dca333d2dd708cd15bc02e96e28a3f310f2707198e70db48f`.
- Se reconstruyó el frontend de `7e8d2969b6858ed69dda2f1bb892055dcc7fbdff` con `VITE_API_BASE_URL=''`: **index.html y bundle JS coinciden byte a byte** con los servidos por esa imagen (`3b297dad...` y `ebd8282b...`, asset `index-D2igwM6v.js`). No se asumió correspondencia por nombre de tag.
- Nuevo worktree/rama: `.worktrees/qa-portal-processing-runtime-20261113`, `qa/portal-processing-runtime-20261113`, base exacta `bcc52de`. Se preservó el árbol frontend identificado arriba y se aplicó el indicador de #894. No se editó ningún worktree activo ajeno ni el checkout raíz.

## Resolución de compatibilidad

La advertencia original de #894 sobre `scalar_one_or_none` era correcta para su base `41ab5f4`, **pero ese defecto no está en la API activa `bcc52de`**. El candidato conserva sin reemplazar la selección generacional existente: `processing_revision` de atribución completada y `latest_attempt` separados. No se duplica otro fix ni se cambia atribución.

Se agregó una regresión HTTP de ambas rutas juntas con tres revisiones y estados pending/in_progress/failed/not_reconstructible/completed. El seguimiento siempre toma la revisión vigente; una atribución completada anterior no declara ready la revisión nueva. Se mantienen los tests de autorización y speaker-review del candidato activo.

El parche directo de la pantalla de carga no aplicaba sobre el portal #880. Se resolvió en el worktree nuevo, preservando explícitamente:

- medio de metadatos oculto;
- transcripción parcial disponible mientras se esperan hablantes, sin declararla lista;
- enlace existente de playback solo al confirmar resultado vigente listo;
- revisión humana separada y errores terminales sin ocultar transcripción parcial;
- respuesta atrasada de subida no asociada a otro archivo;
- playback, agrupación y atribución del portal activo, sin cambios en sus archivos de producción.

Un único polling de procesamiento sustituye el polling ASR/diar de la pantalla de prueba. La carga de contenido parcial conserva 404 de diarización como todavía no reservada, pero no oculta otros fallos de consulta. La lectura del resultado listo verifica transcript y latest_attempt de la ejecución confirmada antes de mostrarlo listo.

## Validación técnica combinada

Comandos desde el nuevo worktree, usando el venv backend ya existente:

```sh
cd backend
$PY -m pytest tests/meetings/test_processing.py tests/meetings/test_diarization_endpoint.py tests/meetings/test_speaker_review_resume.py tests/speaker_review/test_generation_api.py tests/transcription/test_worker.py tests/diarization/test_worker.py tests/integration/test_pipeline_e2e.py -q
$BIN/ruff check app/meetings/processing.py app/meetings/router.py tests/meetings/test_processing.py tests/speaker_review/test_generation_api.py
$BIN/mypy app/meetings/processing.py app/meetings/router.py tests/meetings/test_processing.py tests/speaker_review/test_generation_api.py
cd ../frontend
npm run test
npm run typecheck
VITE_API_BASE_URL='' npm run build
```

Resultados: backend **85 passed, 2 skipped**; frontend **136 passed / 12 archivos**; typecheck/build y mypy pasan. Ruff y `git diff --check` pasan tras corregir longitud de una aserción nueva. No se repitió la suite global base ni se presentaron fixtures como procesamiento MLX/pyannote real.

## Preflight y rollback preparados

Proyecto verificado por labels: `sauri-local-qa-04d47768cad6`, portal `127.0.0.1:15273`, API `127.0.0.1:18100`. Se identificaron los mismos dos Compose, `qa.env` y working directory de los contenedores reales. `docker compose config --format json` se procesó sin mostrar ni exportar secretos: variables explícitas, redes, puertos, imágenes y ausencia de mounts de API/portal coinciden con el runtime.

Snapshot saneado de los seis contenedores guardado en scratch: IDs, inicio, imágenes, redes, puertos, mounts, labels y digest del entorno (sin valores). Se crearon únicamente tags rollback locales:

- `sauri-qa-894-api-rollback:20261113` → imagen API previa indicada arriba.
- `sauri-qa-894-portal-rollback:20261113` → imagen portal previa indicada arriba.

Overlays separados en scratch: `processing-candidate.override.yml` y `processing-rollback.override.yml`, solo image/pull_policy para API y portal. Ningún archivo de configuración original fue modificado. Despliegue previsto exclusivamente con `up -d --no-deps --no-build api portal`; sin down, -v, rebuild de worker ni reinicio de motores. La ejecución y su evidencia se incorporarán después de construir y comprobar las imágenes combinadas.
