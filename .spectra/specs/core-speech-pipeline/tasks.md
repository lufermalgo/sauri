# Plan de Implementación — Core de voz

## Estado y contrato

Ejecución por unidades de entrega (U1–U8). Cada unidad tiene su issue, su rama y su worktree desde `origin/main`, la implementa Codex con el protocolo de `~/Proyectos/sauri-orchestration/` y la valida, publica e integra el orquestador (Claude). Una unidad se cierra solo con: pruebas del backend/portal pertinentes en verde, `ruff` y `mypy` de los archivos tocados sin diagnósticos nuevos, `npm run typecheck` si toca TypeScript, diff revisado, PR integrado. Documentación terminada no es implementación ni aceptación de producto; la aceptación es del dueño tras U8.

Evidencia de origen (rutas privadas, no se copian al repo): `~/Proyectos/APX/evidence/codex-pipeline-argos-20261114/{pipeline.py,pipeline_steps.py,optimization/report.md}`, `codex-coreml-20261114/{report.md,script-final.py}`, `codex-speaker-evaluation` (`_tools/benchmark_coreml.py`). Codex las usa solo como referencia de invocación.

## Resumen de Fases

| Fase | Unidades | Descripción | Dependencias |
|------|----------|-------------|--------------|
| 1 | U1, U4, U6 | Diarización Senko; resumen y `llm-engine`; página de carga | Ninguna (paralelas) |
| 2 | U2 | ASR whisper.cpp con palabras e idioma | U1 (utilidades comunes) |
| 3 | U3 | Palabras, atribución y API de turnos | U2 |
| 4 | U5, U7 | Slot, resumen automático; turnos y resumen en el portal | U3 y U4 |
| 5 | U8 | Corrida real de aceptación y arquitectura | U1–U7 |

---

## Fase 1

### Unidad U1: Diarización con Senko y utilidades comunes de motor (PRIMER PR)

#### Tarea U1.1: Utilidades comunes
**Archivo:** `backend/engine-common/sauri_engine_common/{__init__,audio,keep_awake}.py`, `backend/tests/engine_common/test_audio.py`, `test_keep_awake.py`
**Acción:** Implementar `normalize_to_wav(source, dest, timeout_s=300) -> NormalizeReport(audio_ms, seconds)` con `ffmpeg -nostdin -v error -y -i {source} -vn -ac 1 -ar 16000 -c:a pcm_s16le {dest}` (sin `aresample`), y `KeepAwake` (contexto que lanza `caffeinate -i -w {os.getpid()}` y lo termina al salir; no cambia ajustes globales). Pruebas con un WAV sintético generado con `ffmpeg` (tono 440 Hz de 3 s): duración ±100 ms, mono 16 kHz, error categorizado `normalize_failed` ante archivo corrupto, `caffeinate` terminado al salir (proceso inexistente).
**Criterio de Completado:** `cd backend && uv run --extra dev pytest tests/engine_common -q` verde.
**Dependencias:** Ninguna

#### Tarea U1.2: Contrato v2 de diarización
**Archivo:** `backend/app/diarization/diarization_engine.py`, `backend/app/diarization/local_provider.py`, `backend/diar-engine/main.py` (motor de contenedor Linux), `backend/tests/diar_engine/`
**Acción:** Añadir `EngineInfo` y `contract_version` según el diseño §1/§3. `LocalProvider.diarize` exige `contract_version == 2` (si no, `EngineContractError`) y conserva `capabilities()`. El motor de contenedor (`main.py`, pyannote) devuelve el mismo esquema con `engine.name="pyannote"`; sigue funcional como respaldo Linux. Actualizar pruebas de contrato.
**Criterio de Completado:** `uv run --extra dev pytest tests/diar_engine tests/diarization -q` verde; una respuesta v1 es rechazada con `EngineContractError`.
**Dependencias:** Ninguna

#### Tarea U1.3: Adaptador nativo Senko
**Archivo:** `backend/diar-engine/native_main.py`, `_tools/native-engines.sh`, `backend/diar-engine/requirements-native.txt` (nuevo)
**Acción:** Reemplazar pyannote/MPS por Senko según diseño §3: `Diarizer(device="coreml", vad="pyannote", clustering="cpu", warmup=True, quiet=True)`, VAD con duración mínima 0, `diarize(wav_path, accurate=True, generate_colors=False)`, usar `raw_segments`, convertir a ms. Descargar el audio del object store como hoy, `normalize_to_wav`, ejecutar bajo `KeepAwake`, borrar temporales siempre. Mantener intactos token de motor, `X-Sauri-Recording-Capability`, `_validate_audio_ref` y rutas. `native-engines.sh`: añadir `backend/engine-common` al `PYTHONPATH` y usar el venv `~/.local/share/sauri/native-engines/diar-venv`.
**Criterio de Completado:** Con el venv instalado (T U1.4), un test `native` (`SAURI_RUN_NATIVE_TESTS=1 uv run --extra dev pytest tests/native/test_diar_native.py`) sobre un fixture sintético de 30 s devuelve contrato v2 válido, sin archivos temporales residuales, y `ruff`/`mypy` limpios en archivos tocados.
**Dependencias:** U1.1, U1.2

#### Tarea U1.4: Instalador de Senko
**Archivo:** `_tools/install-diar-engine.sh`, `Makefile` (`engines-install`), `docs/operations/local-deployment.md`
**Acción:** Crear el venv, instalar Senko desde `https://github.com/narcotic-sh/senko.git` en el commit `1bcb09041bfa170b4a5a4b0af92f66eff76204d5` y verificar el SHA-256 de los modelos descargados contra una lista fija en `_tools/engine-hashes.json` (tomar los valores de `~/.cache/sauri-coreml-benchmark/` y `senko-models.sha256.json` de la evidencia de Codex). Idempotente; falla si un hash no coincide.
**Criterio de Completado:** `make engines-install` en un entorno con el venv ya presente termina sin cambios y con código 0; con un hash alterado en el archivo, falla.
**Dependencias:** Ninguna

### Unidad U4: Resumen con proveedor compatible con OpenAI y `llm-engine`

#### Tarea U4.1: Pasajes y esquema con citas
**Archivo:** `backend/app/summaries/passages.py` (nuevo), `backend/app/summaries/engine.py`, `backend/tests/summaries/test_passages.py`
**Acción:** `build_passages(turns, window_ms=60_000)` según diseño §8; modelos `KeyPoint`, `PassageRef`, `CanonicalSummary` con `review_state="draft"`; función `validate_citations(summary, passages)` que descarta puntos sin fuente válida y lanza `SummaryInvalidError` si no queda ninguno. Pruebas de propiedades 8 y 9 con Hypothesis.
**Criterio de Completado:** `uv run --extra dev pytest tests/summaries/test_passages.py -q` verde, incluyendo que ningún turno se omite y que una cita a un pasaje inexistente se descarta.
**Dependencias:** Ninguna

#### Tarea U4.2: Cliente de chat compatible con OpenAI
**Archivo:** `backend/app/summaries/engine.py`, `backend/app/summaries/factory.py`, `backend/tests/summaries/`
**Acción:** Reemplazar `OllamaSummarizationEngine` por `OpenAICompatibleSummarizationEngine` (diseño §8): `POST {base_url}/chat/completions`, `temperature 0`, `response_format` JSON Schema con `enum` de ids de pasaje, `maxItems 2`, prompt de sistema con las prohibiciones del diseño; credencial desde `SUMMARIZATION_API_KEY_FILE`, nunca en logs. Migrar las pruebas de `test_engine*.py` al nuevo contrato (uso/tokens de `usage` de la respuesta, tiempo límite, cancelación). Actualizar `docker-compose.yml` y `.env.example` con las variables nuevas.
**Criterio de Completado:** `uv run --extra dev pytest tests/summaries -q` verde; ninguna línea de log contiene la credencial (test); `grep -rn "api/generate" backend/app` sin resultados.
**Dependencias:** U4.1

#### Tarea U4.3: Plantilla por defecto sembrada
**Archivo:** `backend/app/templates/`, `backend/alembic/versions/` (siguiente número libre), `backend/app/summaries/service.py`, `backend/tests/templates/`
**Acción:** Migración de datos que siembra la categoría "General" y la plantilla "Resultados clave" (instrucciones: tema principal; argumentos y puntos clave; presentación clara y estructurada) como predeterminada del sistema, marcada "propuesta del dueño 14/11/2026, editable". Quitar el `NotImplementedError` de `summaries/service.py` cuando no se pasa plantilla: usar la predeterminada.
**Criterio de Completado:** Pruebas verdes; `POST /meetings/{id}/summary-requests` sin plantilla explícita responde 202 y usa la predeterminada.
**Dependencias:** Ninguna

#### Tarea U4.4: `llm-engine` nativo e instalador
**Archivo:** `backend/llm-engine/native_main.py`, `_tools/install-llm-engine.sh`, `_tools/native-engines.sh`, `_tools/engine-hashes.json`, `backend/tests/llm_engine/`
**Acción:** Servicio FastAPI (puerto 8003) según diseño §9: autenticación por token de motor, `/v1/chat/completions` con arranque perezoso de `llama-server`, apagado a los 120 s sin uso y `KeepAwake` por petición. El instalador compila `llama.cpp` en el commit `af76639f728c69c74c873cc45f038aaa17afd09e` estático (`-DLLAMA_OPENSSL=OFF`, Metal) y descarga `unsloth/Qwen3.5-9B-GGUF` revisión `3885219b6810b007914f3a7950a8d1b469d598a5` verificando SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`. Registrar el indicador usado para desactivar el modo de razonamiento en `provenance.json`. Reutilizar las utilidades de U1.1 (si U1 aún no está integrado, copiar `keep_awake.py` solo para pruebas locales y rebasar al integrar).
**Criterio de Completado:** Prueba con un `llama-server` falso: arranque al primer uso, apagado por inactividad, 401 sin token. Con binario y modelo reales: `curl` autenticado devuelve JSON válido con el esquema.
**Dependencias:** U4.2

### Unidad U6: Página de carga en el portal

#### Tarea U6.1: `UploadView`
**Archivo:** `frontend/src/components/UploadView.tsx`, `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/UploadView.test.tsx`
**Acción:** Extraer la subida con XHR y progreso por bytes de `SpeakerRecognitionTestScreen` a una función `uploadWithProgress` en `api.ts` y crear `UploadView` con selector de archivo, botón «Subir y procesar», barra de progreso real, mensaje de error claro con «Reintentar» (el archivo seleccionado se conserva) y apertura de la reunión al terminar. Añadir la vista al conmutador de `App.tsx` y un enlace «Subir grabación» en la lista. Sin estilos Terra.
**Criterio de Completado:** `npm run typecheck && npm run test --workspace sauri-frontend` verdes, incluidas pruebas de progreso, error con reintento y apertura de la reunión.
**Dependencias:** Ninguna

---

## Fase 2

### Unidad U2: ASR con whisper.cpp, palabras e idioma configurable

#### Tarea U2.1: Contrato v2 de ASR e idioma
**Archivo:** `backend/app/transcription/asr_engine.py`, `local_provider.py`, `worker.py`, `backend/asr-engine/main.py`, `backend/app/config.py` (o el módulo de configuración vigente), `backend/tests/transcription/`, `backend/tests/asr_engine/`
**Acción:** Añadir `TranscriptionWord`, `EngineInfo` y `contract_version` según diseño §1; `LocalProvider` exige v2. Eliminar `"es-CO"` de worker, dataclasses y esquemas; leer `SAURI_DEFAULT_LANGUAGE` (por defecto `es`) y `language` opcional del mensaje. El motor de contenedor (faster-whisper) pasa a `word_timestamps=True` y devuelve palabras.
**Criterio de Completado:** `grep -rn "es-CO" backend/app backend/asr-engine` sin resultados; `uv run --extra dev pytest tests/transcription tests/asr_engine -q` verde.
**Dependencias:** U1.2

#### Tarea U2.2: Conversión de tokens GGML a palabras
**Archivo:** `backend/asr-engine/whisper_words.py` (nuevo), `backend/tests/asr_engine/test_whisper_words.py`
**Acción:** `words_from_ggml_json(doc, audio_ms)` según diseño §2, incluyendo la regla de reparación determinista y el conteo `inverted_words`. Pruebas de propiedades 4 y 5 con Hypothesis y un caso con un JSON `-ojf` real reducido (sin voz) con tokens invertidos.
**Criterio de Completado:** pruebas verdes; un segmento con texto y sin palabras lanza `no_word_timestamps`.
**Dependencias:** Ninguna

#### Tarea U2.3: Adaptador nativo whisper.cpp
**Archivo:** `backend/asr-engine/native_main.py`, `_tools/install-asr-engine.sh`, `_tools/engine-hashes.json`, `Makefile`
**Acción:** Reemplazar `mlx_whisper` por el subproceso de diseño §2 sobre el WAV normalizado (U1.1) y bajo `KeepAwake`; temporales siempre eliminados; tiempos por etapa en `diagnostics.stage_ms`. El instalador copia/descarga `ggml-large-v3-turbo-q5_0.bin` a `~/.local/share/sauri/models/` verificando 574 041 195 bytes y SHA-256 `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`, y verifica que `whisper-cli` exista.
**Criterio de Completado:** test `native` sobre un fixture sintético devuelve contrato v2; el motor responde `422 normalize_failed` ante archivo corrupto y no deja temporales.
**Dependencias:** U1.1, U2.1, U2.2

---

## Fase 3

### Unidad U3: Palabras, atribución por palabra y API de turnos

#### Tarea U3.1: Modelo y migración
**Archivo:** `backend/app/infra/models.py`, `backend/alembic/versions/` (siguiente número libre), `backend/tests/infra/`
**Acción:** Tablas `transcript_words` y `word_speaker_assignments` según «Modelos de Datos», con cascada, restricciones únicas e índices indicados; `retention/worker.py` borra ambas con el transcript.
**Criterio de Completado:** `alembic upgrade head` y `downgrade -1` limpios sobre PostgreSQL; prueba de retención verifica el borrado en cascada.
**Dependencias:** U2.1

#### Tarea U3.2: Funciones puras de atribución y agrupación
**Archivo:** `backend/app/diarization/word_attribution.py`, `backend/tests/diarization/test_word_attribution.py`
**Acción:** `attribute_words` y `group_words_into_turns` según diseño §6, reutilizando `_OverlapIndex` (extraerlo a un módulo compartido sin cambiar `assign_turns`; las pruebas de equivalencia existentes deben seguir idénticas). Propiedades 1, 2, 3 y 6.
**Criterio de Completado:** pruebas nuevas y `tests/diarization/test_assignment*` verdes; con un caso sintético que reproduce segmentos con huecos de 300 ms, ninguna palabra queda `unassigned`.
**Dependencias:** Ninguna

#### Tarea U3.3: Persistencia en workers
**Archivo:** `backend/app/transcription/worker.py`, `backend/app/diarization/worker.py`, `backend/app/diarization/repository.py`, `backend/tests/integration/`
**Acción:** Persistir `TranscriptWord` con el transcript; en diarización calcular `attribute_words` y guardar `WordSpeakerAssignment` dentro de `complete_revision`. Reentregas no duplican filas (propiedad 11). Sin palabras previas: comportamiento actual.
**Criterio de Completado:** prueba de integración con PostgreSQL real: subida simulada → palabras y asignaciones coherentes (`len(asignaciones) == len(palabras)`), reentrega del mismo mensaje no cambia conteos.
**Dependencias:** U3.1, U3.2

#### Tarea U3.4: API de turnos atribuidos
**Archivo:** `backend/app/meetings/router.py`, `packages/shared-types/src/index.ts`, `backend/tests/meetings/`
**Acción:** `GET /meetings/{id}/transcript` según diseño §10 (`presentation`, turnos por palabras, `has_ambiguous`), autorización y auditoría sin cambios. Corregir en el mismo cambio `GET /meetings/{id}/diarization` para filtrar por la revisión completa más reciente (hoy `scalar_one_or_none()` falla con varias revisiones).
**Criterio de Completado:** pruebas de API: transcript con palabras devuelve turnos que reconstruyen el texto; sin palabras devuelve `segments`; dos revisiones no producen error en `/diarization`.
**Dependencias:** U3.3

---

## Fase 4

### Unidad U5: Slot de motor y resumen automático

#### Tarea U5.1: `engine_slot`
**Archivo:** `backend/app/infra/engine_slot.py`, `backend/tests/infra/test_engine_slot.py`
**Acción:** Implementar según diseño §5 con `pg_try_advisory_lock` en conexión dedicada. Propiedad 10 con dos tareas concurrentes y con muerte simulada del titular (cierre de conexión).
**Criterio de Completado:** pruebas verdes contra PostgreSQL real.
**Dependencias:** Ninguna

#### Tarea U5.2: Uso del slot y disparo del resumen
**Archivo:** `backend/app/transcription/worker.py`, `backend/app/diarization/worker.py`, `backend/app/summaries/worker.py`, `backend/app/summaries/service.py`, `backend/tests/integration/`
**Acción:** Envolver las llamadas a motor (ASR, diarización, resumen) con `engine_slot`; tras `complete_revision` solicitar el resumen con la plantilla predeterminada (idempotente por reunión y revisión). Un fallo del disparo no cambia el estado de la reunión.
**Criterio de Completado:** prueba de integración con motores falsos: subida → transcript → diarización → resumen `draft` con citas válidas; dos reuniones simultáneas nunca tienen dos llamadas de motor activas a la vez.
**Dependencias:** U3.3, U4.2, U4.3, U5.1

### Unidad U7: Turnos por hablante y resumen en el portal

#### Tarea U7.1: Turnos atribuidos y estado real
**Archivo:** `frontend/src/components/TranscriptView.tsx`, `frontend/src/transcript-turns.ts`, `frontend/src/api.ts`, pruebas asociadas
**Acción:** Consumir `presentation` y los turnos de U3.4; etiqueta de hablante por turno (`Speaker N`), marca temporal y salto al tiempo al seleccionar; estado de procesamiento real (en cola, transcribiendo, identificando hablantes, completada, fallida con causa y «Reintentar»).
**Criterio de Completado:** `npm run typecheck && npm run test` verdes; prueba con fixture de turnos mixtos verifica etiquetas y salto.
**Dependencias:** U3.4, U6.1

#### Tarea U7.2: Panel de resumen
**Archivo:** `frontend/src/components/SummaryPanel.tsx`, `frontend/src/api.ts`, `packages/shared-types/src/index.ts`, pruebas asociadas
**Acción:** Pestaña «Resumen» con marca «Borrador», tema, puntos y fuentes; cada fuente salta al turno cuyo intervalo contiene `start_ms`; estados pendiente, generando, fallido (con «Reintentar») y vacío.
**Criterio de Completado:** pruebas verdes; en navegador, con un backend de desarrollo y datos sintéticos, la pestaña muestra el borrador y las citas saltan al turno correcto (captura).
**Dependencias:** U5.2, U7.1

---

## Fase 5

### Unidad U8: Aceptación y arquitectura

#### Tarea U8.1: Corrida real
**Archivo:** `.spectra/specs/core-speech-pipeline/acceptance-run.md`
**Acción:** En Condiciones_de_Referencia (Mac conectado a corriente, motores nativos arrancados con `make engines-up`, sin otras cargas), subir por el portal una grabación del dueño de ≥ 60 min y registrar: `Tiempo_Hasta_Transcripcion` por etapa, número de hablantes, % de palabras `unassigned`, duración del resumen, memoria y presión del host. Sin audio ni texto de transcripción en el archivo.
**Criterio de Completado:** archivo con los valores medidos frente a las metas (≤ 7 min, < 3 %); el dueño abre la reunión en el portal y ve transcripción con hablantes y resumen borrador.
**Dependencias:** U1–U7

#### Tarea U8.2: Actualizar arquitectura
**Archivo:** `docs/architecture/overview.md`, `docs/operations/local-deployment.md`
**Acción:** Registrar los motores nativos nuevos (puertos 8001–8003), el slot, el contrato v2, las alternativas descartadas y la evidencia, y el mapa de specs con `core-speech-pipeline`.
**Criterio de Completado:** documento revisado en el PR; sin afirmaciones de despliegue o aceptación no comprobadas.
**Dependencias:** U8.1
