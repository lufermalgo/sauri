# Plan de Implementación — Motores y modelos

## Estado y contrato

Ejecución por unidades de entrega (U1–U10). Cada unidad tiene su issue (se crea al iniciarla; todas parten de #1050), su rama y su worktree desde `origin/main` en `.worktrees/`, la implementa Codex o un subagente con el protocolo de `~/Proyectos/sauri-orchestration/`, y Claude revisa el diff, ejecuta las pruebas por su cuenta e integra. Una unidad se cierra solo con: pruebas pertinentes en verde, `ruff` y `mypy` sin diagnósticos nuevos en lo tocado, `npm run typecheck` y `npm run test` si toca TypeScript, `bash scripts/dev/check_english_only.py` sobre lo staged, diff revisado, PR integrado y `docs/architecture/overview.md` actualizado cuando cambie la arquitectura (regla de `AGENTS.md`). Documentación terminada no es implementación ni aceptación; la aceptación es del dueño tras U10.

**Reglas transversales de todas las unidades**
- Nunca se envía audio ni texto de reuniones a un proveedor real en pruebas automáticas: solo servidores simulados en `127.0.0.1`. Las pruebas con proveedores reales ocurren únicamente en U10, con claves del dueño y material suyo.
- Nunca se usan ni se tocan el proyecto Docker `sauri` ni sus volúmenes; las pruebas con PostgreSQL y RabbitMQ usan instancias desechables (`sauri_qa_*`, `sauri-qa-*`) en `127.0.0.1`.
- Las pruebas del llavero real usan un servicio de prueba (`sauri-test-<uuid>`) que se elimina al terminar y solo con `SAURI_RUN_NATIVE_TESTS=1`; no se toca el servicio `sauri` del dueño.
- Textos de usuario solo en `frontend/src/copy/` y `backend/app/copy/`; identificadores en inglés.
- Ningún archivo, registro, evidencia ni mensaje de commit contiene claves, audio o transcripciones.

## Resumen de Fases

| Fase | Unidades | Descripción | Dependencias |
|------|----------|-------------|--------------|
| 1 | U1 | Fundamentos del anfitrión: secretos, contrato de ruta, errores, `host-engine` | Ninguna |
| 2 | U2, U6 | Registro de proveedores y API; gestión de modelos locales | U1 (U6 usa el router de U2 solo para su proxy) |
| 3 | U3, U4, U7 | Resumen externo; transcripción externa; navegación y pantalla «Motores y modelos» | U1, U2 |
| 4 | U5, U8 | Hablantes externos; selectores por proceso, aviso de privacidad y procedencia | U4; U2, U6, U7 |
| 5 | U9 | Plan de ChatGPT (Codex) | U3, U7 y verificación legal del dueño (bloqueada) |
| 6 | U10 | Aceptación con proveedores reales y arquitectura | U3–U8 (U9 si se desbloquea) |

---

## Fase 1

### Unidad U1: Secretos, contrato de ruta y `host-engine`

#### Tarea U1.1: Almacén de secretos
**Archivo:** `backend/engine-common/sauri_engine_common/secrets.py`, `backend/tests/engine_common/test_secrets.py`
**Acción:** Implementar `SecretRecord` (con `__repr__` que oculta la clave), `SecretStore` (puerto), `KeychainSecretStore` (`/usr/bin/security`: `put` envía `add-generic-password -U -s sauri -a <ref> -w <json>` por entrada estándar con `security -i`, nunca por `argv`; `get` con `find-generic-password -w`; `delete`), `FileSecretStore` (`~/.config/sauri/secrets/`, carpeta 0700, archivo 0600, escritura atómica) y `default_secret_store()`. `key_hint(key)` devuelve los últimos 4 solo si `len(key) >= 12`. Validar `ref` con `[A-Za-z0-9._/-]{1,200}`. Las excepciones llevan código y nunca el valor.
**Criterio de Completado:** `cd backend && uv run --extra dev pytest tests/engine_common/test_secrets.py -q` verde (Propiedades 3 y 4 con claves aleatorias sobre `FileSecretStore`; permisos 0600/0700; reemplazo; borrado; `key_hint`). Con `SAURI_RUN_NATIVE_TESTS=1` en el Mac, un ciclo `put/get/delete` real con servicio de prueba, y comprobación de que la clave no aparece en `ps -ww` durante `put` (**NO VERIFICADO hasta ejecutarlo**; si el llavero pide autorización a procesos lanzados con `nohup`, documentar la solución o el uso del archivo como alternativa).
**Dependencias:** Ninguna

#### Tarea U1.2: Contrato de ruta y errores clasificados
**Archivo:** `backend/engine-common/sauri_engine_common/route.py`, `backend/engine-common/sauri_engine_common/external/errors.py`, `backend/tests/engine_common/test_route.py`, `test_errors.py`
**Acción:** Implementar `Route`, `RouteTimeouts`, `encode_route` (base64url de JSON compacto, máximo 4 KiB), `decode_route` (`None` = motor local), `validate_route` (matriz, consentimiento, origen vinculado, HTTPS salvo loopback) y `ProviderError` con la tabla de clases de `design.md` («Manejo de Errores»); `classify(status, body_hint, exc)` total. Sin cabecera, las pasarelas siguen su camino actual.
**Criterio de Completado:** pruebas verdes con Hypothesis para Propiedades 5, 6 (parte de pasarela) y 11; `decode_route` rechaza cabeceras mayores de 4 KiB, versión desconocida y proceso no soportado.
**Dependencias:** Tarea U1.1

#### Tarea U1.3: Servicio `host-engine` (esqueleto, secretos y estado)
**Archivo:** `backend/host-engine/native_main.py`, `backend/host-engine/requirements-native.txt`, `scripts/engines/install-host-engine.sh`, `scripts/engines/native-engines.sh`, `scripts/engines/ensure-native-engine-credentials.sh`, `Makefile`, `docker-compose.yml`, `.env.example`, `backend/tests/host_engine/`
**Acción:** FastAPI en `127.0.0.1:8005` con autenticación `management_token` (comparación en tiempo constante; `503` si el archivo falta): `GET /health`, `PUT|DELETE /v1/secrets/{ref}` (el cuerpo `{key, origin}` nunca se registra; la respuesta lleva solo `key_hint`), `GET /v1/engines/status`. `ensure-native-engine-credentials.sh` genera una vez `~/.config/sauri/management_token` (0600). `native-engines.sh` agrega el objetivo `host` (puerto 8005, entorno virtual propio, `PYTHONPATH` con `backend/engine-common`) y `make engines-*` lo incluye. `docker-compose.yml`: monta `management_token` de solo lectura **únicamente** en `api` y agrega `HOST_ENGINE_URL=http://host.docker.internal:8005`; el worker no lo recibe.
**Criterio de Completado:** pruebas del servicio verdes (401 sin token, 401 con el token de motor, no existe ninguna ruta que devuelva un secreto, el cuerpo de `PUT` no aparece en registros capturados); `make engines-status` muestra el servicio `host`; `docker compose -p sauri config` (solo lectura) confirma que el montaje existe solo en `api`; ningún puerto nuevo escucha fuera de `127.0.0.1`.
**Dependencias:** Tareas U1.1, U1.2

#### Tarea U1.4: Documentar la arquitectura
**Archivo:** `docs/architecture/overview.md`, `docs/operations/local-deployment.md`, `.spectra/README.md`
**Acción:** Agregar `host-engine` (:8005), el token de administración, el almacén de secretos y la regla «el worker no recibe claves» a la tabla de componentes y a «Seguridad local»; indicar el estado de `model-engines` en el índice de specs.
**Criterio de Completado:** revisión del diff sin afirmaciones de despliegue o aceptación no comprobadas.
**Dependencias:** Tarea U1.3

---

## Fase 2

### Unidad U2: Registro de proveedores, configuración por proceso y API

#### Tarea U2.1: Modelo de datos y migración
**Archivo:** `backend/app/infra/models.py`, `backend/alembic/versions/<siguiente número libre>_engine_providers.py`, `backend/tests/engines/test_models.py`
**Acción:** Tablas `engine_providers`, `engine_process_settings`, `engine_privacy_consents` y columnas nullable `engine_name`, `engine_model`, `engine_external` en `transcripts`, `diarizations` y `meeting_summaries`, según `design.md` («Modelos de Datos»). Índice único parcial del consentimiento vigente; clave primaria `(owner_id, capability)`. `downgrade` conserva datos de reuniones.
**Criterio de Completado:** `uv run --extra dev pytest tests/engines/test_models.py -q` verde sobre PostgreSQL desechable (`alembic upgrade head` y `downgrade -1`); sin columnas de claves ni contenido.
**Dependencias:** Ninguna (la fase 1 no bloquea el esquema; se integra tras U1)

#### Tarea U2.2: Matriz de compatibilidad y avisos
**Archivo:** `backend/app/engines/capability_matrix.py`, `backend/app/copy/engine_notices_es.py`, `backend/tests/engines/test_matrix.py`
**Acción:** Implementar la matriz de `design.md` (tabla del §7) con `verified_on` y notas; avisos por proceso y proveedor con `notice_version` (audio completo para transcripción y hablantes; texto de la transcripción más instrucciones de plantilla para resumen; dirección del proveedor; condiciones ajenas a Sauri; «se cobra en tu cuenta»). Pares con `verified_on = None` no se ofrecen.
**Criterio de Completado:** pruebas de Propiedad 6 y de que cada aviso nombra proceso, proveedor, dirección y contiene la frase de cobro; revisión de lenguaje sin tecnicismos.
**Dependencias:** Ninguna

#### Tarea U2.3: Servicio, API y cliente del anfitrión
**Archivo:** `backend/app/engines/{router.py,schemas.py,service.py,host_client.py}`, `backend/app/main.py`, `packages/shared-types/src/engines.ts`, `backend/tests/engines/test_api.py`
**Acción:** Endpoints de `design.md` §8 (proveedores, clave, prueba, modelos, procesos, aviso, estado). `PUT /providers/{id}/key` toma el origen de la URL base del proveedor y llama a `host-engine`; la respuesta solo lleva `key_set` y `key_hint`. `PUT /processes/{capability}` valida la matriz (422), exige `notice_version` vigente y crea o revoca consentimiento y devuelve a local los procesos de un proveedor apagado o eliminado (Requisito 3.2). Aislamiento por propietario (404 ajeno).
**Criterio de Completado:** pruebas con PostgreSQL desechable y `host-engine` falso: Propiedades 2 (parte de API), 3, 6, 17; ninguna respuesta contiene la clave; la eliminación del proveedor deja sus procesos en local.
**Dependencias:** Tareas U1.3, U2.1, U2.2

#### Tarea U2.4: Prueba de conexión, catálogo de modelos y descubrimiento
**Archivo:** `backend/host-engine/providers.py`, `backend/host-engine/native_main.py`, `backend/tests/host_engine/test_providers.py`
**Acción:** `POST /v1/providers/probe` y `POST /v1/providers/models` con caché de 24 h y `refresh`, filtro por proceso (descartar embeddings, voz y modelos no de chat), modelo «Auto» por tipo, comprobación de `json_schema` con una petición mínima para chat, y `GET /v1/discover/local` (Ollama 11434, LM Studio 1234). Verificar la ruta `/v1` de Ollama contra la versión instalada y registrar el resultado.
**Criterio de Completado:** pruebas con servidores falsos: «Responde/No responde» con causa y latencia, caché y refresco, filtro, esquema aceptado o rechazado, descubrimiento; ninguna salida contiene la clave.
**Dependencias:** Tarea U1.3

### Unidad U6: Gestión de modelos locales

#### Tarea U6.1: Catálogo versionado y recomendación
**Archivo:** `scripts/engines/model-catalog.json`, `backend/engine-common/sauri_engine_common/recommend.py`, `backend/tests/engine_common/test_recommend.py`, `backend/tests/engine_common/test_catalog.py`
**Acción:** Crear el catálogo con los modelos de `design.md` §10: fijar la `revision` de cada archivo contra el repositorio de origen y volver a verificar tamaño y SHA-256 (los valores de `design.md` se tomaron de la rama `main`, no de una revisión fija), más Senko como motor gestionado. `recommend(hardware, catalog)` pura con motivo y marca `measured|proposal`. Verificar con los binarios instalados que `--reasoning-budget 0` y el modo sin razonamiento funcionan con Qwen3.5-4B (si no, retirar el 4B del catálogo y registrarlo).
**Criterio de Completado:** pruebas verdes de Propiedades 9 y 16 (el catálogo coincide con `engine-hashes.json`); tabla de decisión documentada en el docstring con ejemplos 8, 16 y 24 GiB.
**Dependencias:** Ninguna

#### Tarea U6.2: Hardware e instalación con hash
**Archivo:** `backend/host-engine/hardware.py`, `backend/host-engine/local_models.py`, `backend/host-engine/native_main.py`, `backend/tests/host_engine/test_local_models.py`
**Acción:** `GET /v1/hardware` (`platform.machine()`, `sysctl hw.memsize`, `os.cpu_count()`, `shutil.disk_usage`), `GET /v1/local/models`, `POST .../install`, `GET /v1/local/jobs/{id}`, `POST .../cancel`, `POST .../verify`, `DELETE`. Descarga a `.part` con reanudación por `Range`, SHA-256 incremental, comprobación de espacio (`size × 1,2`), `os.replace`, manifiesto con `mtime_ns`, un solo trabajo activo, «Quitar» rechazado si el modelo está en uso.
**Criterio de Completado:** pruebas de Propiedad 10 (hash alterado, corte, cancelación, disco insuficiente simulado, doble instalación → 409); el archivo final solo existe con hash válido.
**Dependencias:** Tareas U1.3, U6.1

#### Tarea U6.3: Uso del modelo elegido por las pasarelas y proxy en la API
**Archivo:** `backend/asr-engine/asr_assets.py`, `backend/asr-engine/native_main.py`, `backend/llm-engine/native_main.py`, `backend/app/engines/local_router.py`, `backend/tests/{asr_engine,llm_engine,engines}/`
**Acción:** Las pasarelas aceptan `local:<id>` (vía `X-Sauri-Route`), resuelven el archivo del catálogo y lo validan por manifiesto, tamaño y `mtime_ns`; el LLM reinicia `llama-server` si el modelo pedido difiere y usa `--alias <id>`. Sin cabecera, el modelo por defecto actual. `local_router.py` expone en la API el proxy de `/local/*` a `host-engine`.
**Criterio de Completado:** pruebas con `whisper-cli` y `llama-server` falsos: cambio de modelo entre dos peticiones, modelo no instalado → `model_not_installed`, sin cabecera nada cambia; `SAURI_RUN_NATIVE_TESTS=1` valida con los binarios reales instalados.
**Dependencias:** Tareas U1.2, U2.3, U6.2

---

## Fase 3

### Unidad U3: Resumen externo (pasarela LLM y worker)

#### Tarea U3.1: Adaptadores de chat y adaptación de esquema
**Archivo:** `backend/engine-common/sauri_engine_common/external/{chat_openai.py,chat_anthropic.py,schema.py}`, `backend/tests/engine_common/test_chat_adapters.py`
**Acción:** `openai-chat` (flujo, `response_format` JSON Schema, `provider.require_parameters` para OpenRouter, sin seguir redirecciones) y `anthropic-messages` (`output_config.format`, quitar `maxItems`/`minItems > 1`/límites de longitud, cabecera de versión fijada tomando el valor de la documentación vigente). Ambos agregan el flujo y devuelven la forma de chat de OpenAI con `usage`. Confirmar con una clave real de prueba del dueño la forma de Gemini (ruta compatible con OpenAI frente a la nativa) antes de ofrecerlo; si no hay clave, queda `verified_on = None`.
**Criterio de Completado:** pruebas contra servidores falsos: respuesta válida, JSON inválido, citas inexistentes (rechazo local, Propiedad 13), 429 con `Retry-After`, 5xx, corte; ninguna clave en registros ni excepciones (Propiedad 4).
**Dependencias:** Tareas U1.2, U2.2

#### Tarea U3.2: Pasarela LLM con rutas externas y cancelación
**Archivo:** `backend/llm-engine/native_main.py`, `backend/tests/llm_engine/`
**Acción:** `POST /v1/chat/completions` acepta `X-Sauri-Route`: sin cabecera o local, flujo actual; externa: `validate_route`, lectura del secreto, adaptador, tarea vigía de desconexión, tiempos por ruta, errores en `{"error": {code, retryable, retry_after_s}}`. En rutas externas no toma el candado de `llama-server`.
**Criterio de Completado:** pruebas: 401 sin token; ruta externa sin consentimiento → `consent_missing` sin conexión saliente; cerrar el cliente cierra el flujo hacia el proveedor en ≤ 2 s (Propiedad 12); `llama-server` local sigue funcionando sin cabecera.
**Dependencias:** Tarea U3.1

#### Tarea U3.3: Worker de resumen: resolver ruta, respaldo y procedencia
**Archivo:** `backend/app/engines/routing.py`, `backend/app/summaries/{engine.py,factory.py,worker.py}`, `backend/app/infra/models.py`, `backend/tests/{engines,summaries,integration}/`
**Acción:** `resolve_route` y `call_with_fallback`; el cliente de resumen recibe la ruta y envía la cabecera; las clases de error pasan a `failure_cause` con textos de `backend/app/copy/`; el respaldo local aplica solo a clases transitorias; se guardan `engine_name/model/external` del resumen. Alinear reintentos y solicitud única con lo que resuelva #1045 (no redefinirlos aquí).
**Criterio de Completado:** pruebas de integración con PostgreSQL desechable: Propiedades 1, 2, 14 y 15 (sin fila de configuración el worker se comporta como hoy; consentimiento faltante; respaldo; reintento sin duplicar); `grep -rn "SUMMARIZATION_API_KEY_FILE" backend/app` solo en compatibilidad documentada o eliminado, y la clave ya no se monta en el worker.
**Dependencias:** Tareas U2.3, U3.2

### Unidad U4: Transcripción externa

#### Tarea U4.1: Preparación de audio para proveedores
**Archivo:** `backend/engine-common/sauri_engine_common/external/audio_prep.py`, `backend/tests/engine_common/test_audio_prep.py`
**Acción:** Compresión Opus mono tras `normalize_to_wav`, división en tramos en pausas de voz con la lógica de `asr_vad` cuando haya límite de tamaño o duración, desfase por tramo y limpieza de temporales; `audio_too_large` si no es posible dividir.
**Criterio de Completado:** pruebas con audio sintético (tono con silencios, sin voces reales): suma de duraciones ±100 ms, tiempos con desfase correctos, ningún temporal residual, 60 min sintéticos pesan menos de 25 MB tras comprimir (medido y registrado).
**Dependencias:** Tarea U1.2

#### Tarea U4.2: Adaptadores de transcripción
**Archivo:** `backend/engine-common/sauri_engine_common/external/{asr_openai_audio.py,asr_assemblyai.py,asr_deepgram.py}`, `backend/tests/engine_common/test_asr_adapters.py`
**Acción:** `openai-audio` (Groq y compatibles: `verbose_json` con `timestamp_granularities[]=word`), `assemblyai` (subida, creación, sondeo con tope de 1200 s, borrado o cancelación del trabajo remoto) y `deepgram` (`/v1/listen`). Todos devuelven palabras con tiempos o `no_word_timestamps`; el idioma sale de la configuración; confirmar con claves de prueba del dueño soporte de español y límites reales (**NO VERIFICADO**; sin clave, `verified_on = None`).
**Criterio de Completado:** pruebas con servidores falsos con las formas documentadas: Propiedades 7 y 12, 429, 5xx, tramos con desfase, cancelación que borra el trabajo remoto simulado.
**Dependencias:** Tarea U4.1

#### Tarea U4.3: Pasarela ASR con rutas externas y worker
**Archivo:** `backend/asr-engine/native_main.py`, `backend/app/transcription/{asr_engine.py,local_provider.py,worker.py}`, `backend/tests/{asr_engine,integration}/`
**Acción:** `POST /transcribe` acepta `X-Sauri-Route`; ruta externa → mismo cuerpo v2 con `engine = {name, model, device: "remote"}`; `TranscriptionOptions.route`; el worker resuelve la ruta, aplica el respaldo y guarda la procedencia. `/transcribe` mantiene capacidad por grabación y `_validate_audio_ref`.
**Criterio de Completado:** prueba de integración con motor falso externo: subida → transcripción externa → atribución por palabra → reunión completada; fallo transitorio con respaldo local activo usa Motor_Local y registra la procedencia real; Propiedades 1, 2, 14, 15.
**Dependencias:** Tareas U2.3, U4.2

### Unidad U7: Navegación de configuración y «Motores y modelos»

#### Tarea U7.1: Navegación con grupos y buscador
**Archivo:** `frontend/src/router.ts`, `frontend/src/copy/settings.ts`, `frontend/src/components/SettingsView.tsx`, `frontend/src/styles/settings.css`, `frontend/src/components/SettingsView.test.tsx`, `frontend/src/router.test.ts`
**Acción:** Agregar categorías `engines`, `transcription`, `speakers` y el modelo de grupos (`general`, `models`, `recording`); `chat` reservada y no enrutada; campo de búsqueda con coincidencia sin acentos sobre etiqueta, descripción y palabras clave; mensaje de «sin resultados»; flujo de dos pasos en móvil. Las categorías nuevas se renderizan con un marcador hasta U7.2/U8; las URL existentes no cambian.
**Criterio de Completado:** `npm run typecheck && npm run test` verdes (rutas antiguas intactas, grupos, filtro por «claves»/«whisper»/«privacidad», `aria-current`, objetivo de 44 px); revisión en el navegador integrado a 320, 768 y 1440 px en claro y oscuro.
**Dependencias:** Ninguna

#### Tarea U7.2: Pantalla «Motores y modelos» y diálogo de proveedor
**Archivo:** `frontend/src/components/settings/{EnginesSettings.tsx,ProviderDialog.tsx}`, `frontend/src/api.ts`, `frontend/src/copy/engines.ts`, `frontend/src/styles/engines.css`, pruebas asociadas
**Acción:** Rejilla de tarjetas (nombre, tipo, estado con texto, procesos que usa, «Administrar», editar/eliminar), «Agregar proveedor» con los tipos de la matriz y detección de Ollama/LM Studio, diálogo con clave tipo contraseña sin precarga («Guardada ••••1234», «Reemplazar», «Quitar clave»), URL base editable y «Guardar y probar conexión» con resultado y causa; confirmación al eliminar con la lista de procesos que volverán a local; estados de carga, error y vacío. Solo componentes de `ui/` y tokens `--ds-*`; sin logos de marca.
**Criterio de Completado:** pruebas de interfaz (la clave nunca se renderiza tras guardar; el estado se comunica con texto; el diálogo cumple foco, Escape y retorno); `npm run typecheck && npm run test` verdes; captura en el navegador integrado contra la API real con `host-engine` falso.
**Dependencias:** Tareas U2.3, U7.1

---

## Fase 4

### Unidad U5: Hablantes externos

#### Tarea U5.1: Adaptadores de hablantes
**Archivo:** `backend/engine-common/sauri_engine_common/external/{diar_assemblyai.py,diar_deepgram.py,speakers.py}`, `backend/tests/engine_common/test_diar_adapters.py`
**Acción:** Convertir palabras o tramos etiquetados en `SpeakerSegment` (unión de palabras consecutivas con la misma etiqueta, sin filtro de duración, `speaker_count` = etiquetas distintas), descartar el texto del proveedor, mismas reglas de audio, tiempos y cancelación que U4. Confirmar con claves de prueba del dueño el español y los límites (**NO VERIFICADO**).
**Criterio de Completado:** pruebas de Propiedades 8 y 12; ninguna salida ni registro contiene texto del proveedor.
**Dependencias:** Tareas U4.1, U4.2

#### Tarea U5.2: Pasarela de hablantes y worker
**Archivo:** `backend/diar-engine/native_main.py`, `backend/app/diarization/{diarization_engine.py,local_provider.py,worker.py,factory.py}`, `backend/tests/{diar_engine,integration}/`
**Acción:** `POST /diarize` acepta `X-Sauri-Route`; `DiarizationOptions.route`; el worker resuelve ruta, aplica respaldo local (Senko) y guarda procedencia; el factory deja de rechazar rutas externas solo cuando existe una ruta con consentimiento. Con configuración vacía el comportamiento es el actual.
**Criterio de Completado:** integración: transcripción local + hablantes externos simulados → atribución por palabra → turnos; respaldo a Senko con registro de procedencia; sin duplicados al reintentar.
**Dependencias:** Tareas U4.3, U5.1

### Unidad U8: Selectores por proceso, aviso de privacidad y procedencia

#### Tarea U8.1: Selector de motor y modelo con aviso
**Archivo:** `frontend/src/components/settings/{ProcessSettings.tsx,PrivacyNoticeDialog.tsx}`, `frontend/src/components/SettingsView.tsx`, `frontend/src/components/settings/SummarySettings.tsx`, `frontend/src/copy/engines.ts`, pruebas asociadas
**Acción:** Transcripción, Hablantes y Resúmenes muestran «Hoy usa: …», selector con «Local (recomendado)» primero, modelos locales instalados y modelos de cada proveedor activo compatible (catálogo en vivo, «Volver a pedir», entrada manual si falla), interruptor «Si el proveedor falla, usar el modelo local», y el aviso de privacidad antes de guardar un cambio a proveedor externo; volver a local no pide confirmación. Advertencias de doble envío (mismo proveedor en transcripción y hablantes) y de calidad no validada para hablantes externos. En Resúmenes, la elección va antes de las plantillas existentes.
**Criterio de Completado:** pruebas de interfaz de los flujos (cancelar el aviso no guarda; aceptar guarda con la versión; cambio de modelo en el mismo proveedor no repite el aviso; volver a local); `npm run typecheck && npm run test` verdes.
**Dependencias:** Tareas U2.3, U7.2 (U6.3 para modelos locales instalados)

#### Tarea U8.2: Tarjeta de modelos locales
**Archivo:** `frontend/src/components/settings/LocalModelCard.tsx`, `frontend/src/copy/engines.ts`, `frontend/src/api.ts`, pruebas asociadas
**Acción:** Hardware en lenguaje claro, recomendación con motivo y marca «medido»/«propuesta», «Instalar» con espacio requerido, progreso por consulta periódica (`role="status"`), «Cancelar», «Verificar», «Quitar» con confirmación y bloqueo si está en uso, mensaje de «Motor no instalado» con el comando y herramientas faltantes.
**Criterio de Completado:** pruebas de interfaz con API simulada (progreso, cancelación, hash inválido, disco insuficiente, modelo en uso); captura en el navegador integrado con `host-engine` real y descarga simulada de un archivo pequeño.
**Dependencias:** Tareas U6.3, U8.1

#### Tarea U8.3: Procedencia en la reunión
**Archivo:** `backend/app/meetings/router.py`, `packages/shared-types/src/`, `frontend/src/components/{MeetingHeader.tsx,SummaryPanel.tsx}`, `frontend/src/copy/meeting.ts`, pruebas asociadas
**Acción:** Exponer `engine_name`, `engine_model`, `engine_external` de transcripción, hablantes y resumen y mostrarlos en una línea discreta («Transcrito con whisper.cpp · local»; «Resumen con <modelo> · externo»); filas anteriores: «motor local anterior». Si el respaldo local actuó, mostrar el motivo.
**Criterio de Completado:** pruebas de API y de interfaz; sin contenido de reuniones en los nuevos campos.
**Dependencias:** Tareas U3.3, U4.3, U5.2

---

## Fase 5

### Unidad U9: Plan de ChatGPT (Codex) — BLOQUEADA hasta la confirmación legal del dueño

#### Tarea U9.0: Verificación legal y técnica previa
**Archivo:** `.spectra/specs/model-engines/legal-check.md`
**Acción:** El dueño confirma por escrito que el uso del plan de ChatGPT por esta aplicación local cumple los términos de OpenAI (documento «Sign in with ChatGPT» para aplicaciones locales: vista previa; formulario de interés para aplicaciones de pago o alojadas remotamente). Un agente comprueba contra la documentación vigente: ruta y parámetros de la API de Respuestas, modelos disponibles, soporte de `text.format = json_schema`, refresco del token de actualización y cuotas del plan. Resultado: «oficial viable», «solo clave de API» o «no ofrecer».
**Criterio de Completado:** el archivo registra la decisión con fecha y fuentes; sin ella, no se escribe código de U9.1–U9.3.
**Dependencias:** Decisión del dueño

#### Tarea U9.1: Flujo de inicio de sesión en `host-engine`
**Archivo:** `backend/host-engine/chatgpt_auth.py`, `backend/host-engine/native_main.py`, `backend/tests/host_engine/test_chatgpt_auth.py`
**Acción:** Autorización con PKCE (`state`, `nonce`, S256), callback temporal en `http://127.0.0.1:<puerto>/auth/callback` (nunca `localhost`), registro dinámico con `ext_agent_host_id` estable (`urn:uuid` guardado junto al secreto), canje de código, validación del token de identidad y de los alcances, almacenamiento como un solo secreto con escritura atómica; `invalid_grant` reinicia el flujo. Rutas `POST /v1/oauth/chatgpt/{start,status,logout}`.
**Criterio de Completado:** pruebas con servidor de autorización falso (flujo completo, `state` incorrecto, alcance faltante, `invalid_grant`); el token nunca aparece en respuestas ni registros; la tarjeta indica vista previa y consumo de la cuota del plan.
**Dependencias:** Tarea U9.0, U1.3

#### Tarea U9.2: Adaptador `chatgpt-responses` y tarjeta
**Archivo:** `backend/engine-common/sauri_engine_common/external/chat_responses.py`, `frontend/src/components/settings/ProviderDialog.tsx`, `backend/app/engines/capability_matrix.py`, pruebas asociadas
**Acción:** Adaptador con `store: false`, `stream: true`, renovación antes de vencer y **guardado del token de actualización nuevo antes de usarlo**, traducción a la forma de chat y esquema JSON según el resultado de U9.0; tarjeta «Codex (plan de ChatGPT)» con «Conectar» y estado; `verified_on` solo tras la prueba con el plan real. Si U9.0 resolvió «solo clave de API», este tipo no se ofrece y se documenta el uso de OpenAI con clave.
**Criterio de Completado:** pruebas con servidor falso (rotación del token, vencimiento, 401 con renovación, cierre del flujo); con el plan real del dueño, un resumen válido con citas (evidencia sin contenido).
**Dependencias:** Tareas U9.1, U3.2, U7.2

---

## Fase 6

### Unidad U10: Aceptación y arquitectura

#### Tarea U10.1: Preparación con el dueño
**Archivo:** `.spectra/specs/model-engines/acceptance-run.md`
**Acción:** El dueño vincula, desde la pantalla «Motores y modelos», al menos un proveedor por proceso con sus propias claves (resumen: uno de chat; transcripción y hablantes: AssemblyAI, Deepgram o Groq según su cuenta; opcional Codex si U9 se desbloqueó) y elige una grabación suya de al menos 10 minutos. Se registran los proveedores elegidos sin claves.
**Criterio de Completado:** archivo con la lista de proveedores y procesos por probar y la confirmación del dueño de que acepta el envío de esa grabación.
**Dependencias:** Tareas U3.3, U4.3, U5.2, U8.2

#### Tarea U10.2: Recorrido real con proveedores
**Archivo:** `.spectra/specs/model-engines/acceptance-run.md`
**Acción:** Con motores nativos arrancados y sin otras cargas, procesar la grabación (a) todo local, (b) cada proceso con su proveedor externo, (c) un fallo provocado (clave rechazada, proveedor inalcanzable con respaldo local activo, cancelación desde el portal) y (d) la instalación de un modelo local desde el botón en el equipo del dueño. Registrar por caso: procedencia, tiempo por etapa, resultado, clase de error, uso informado, y que ninguna clave aparece en registros (`grep` sobre los registros de `~/.local/state/sauri/native-engines/` y de los contenedores). Sin audio ni texto de reuniones en el archivo.
**Criterio de Completado:** archivo con resultados; el dueño abre las reuniones en el portal, ve la procedencia correcta y acepta o rechaza cada proveedor; comparación de hablantes externos frente a Senko con su criterio.
**Dependencias:** Tarea U10.1

#### Tarea U10.3: Actualizar arquitectura y alcance
**Archivo:** `docs/architecture/overview.md`, `docs/operations/local-deployment.md`, `docs/product/baseline.md`, `AGENTS.md`, `.spectra/README.md`
**Acción:** Registrar el estado verificado de proveedores, el flujo de secretos y consentimiento, los motores gestionados por la interfaz y la decisión del dueño sobre privacidad por proceso (16/11/2026) en la sección de privacidad y gobernanza del baseline; ajustar la frase de `AGENTS.md` «Nada sale de la máquina… solo si el dueño lo configura» para referirse al consentimiento por proceso; actualizar el índice de specs.
**Criterio de Completado:** revisión del diff sin afirmaciones de aceptación ni despliegue no comprobadas; cambios de baseline marcados como aprobados solo si el dueño los confirmó.
**Dependencias:** Tarea U10.2
