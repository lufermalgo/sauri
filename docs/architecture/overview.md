# Arquitectura de Sauri

Estado: dirección confirmada por Fer el 12-11-2026 (conversación del 12-11-2026, 19:10–19:25 UTC). Inventario contrastado con `origin/main` `c19b4ae`. Este documento distingue configuración, implementación y validación; no declara aceptación de producto ni reemplaza las specs.

## Decisiones y límites

- Núcleo de servicios en Docker; transcripción y diarización nativas en el Mac para aprovechar Apple GPU. No se trasladan los motores a Docker/CPU: esa alternativa pierde la aceleración prevista en este Mac. No es una limitación universal de Docker.
- La extensión vive en Chrome. El portal React se construye con Vite y se sirve mediante Nginx en Docker, añadido al candidato de local-platform-deployment (#829 → #832 → #836 → U4 #837). El runtime no usa Vite ni expone fuentes. Mantener publicación/merge/recorrido/aceptación separados; los PR de despliegue no se consideran integrados por existir. Ver [operación y QA](docs/operations/local-deployment.md).
- PostgreSQL almacena datos estructurados y propiedad de las reuniones. Un almacén S3 guarda medios; RabbitMQ entrega trabajos a los procesadores. No guardar videos en PostgreSQL ni usar la cola como archivo durable de grabaciones.
- Compose actualmente usa RustFS, aunque el servicio, volumen y variables conservan nombres MinIO. No renombrar ni migrar volúmenes existentes para limpiar nomenclatura. La compatibilidad real con datos anteriores requiere evidencia separada: issue #543 sigue abierto.
- Se conserva la autenticación y autorización existentes. `AUTH_DISABLED=true`, valor predeterminado del Compose local, **no demuestra aislamiento entre cuentas**. La validación de propiedad debe ejecutarse con autenticación activa y dos identidades sintéticas; no habilitar un despliegue multiusuario ni cambiar política de acceso como parte de esta reconciliación.

## Componentes y conexiones

| Componente | Tecnología actual | Ubicación | Contrato / responsabilidad |
|---|---|---|---|
| Captura | Chrome MV3, TypeScript, React | Chrome | Capturar medios autorizados; persistencia local y cola de carga |
| Portal | React/TypeScript construido con Vite, servido por Nginx | Navegador y Docker `portal` en candidato #818 | Consultar reuniones vía proxy API y reproducir enlaces S3 autorizados |
| API | Python, FastAPI, SQLAlchemy | Docker `api` | Ingestión y acceso a reuniones del usuario |
| Procesadores | Python | Docker `worker` | Consumir trabajos y coordinar motores |
| Datos | PostgreSQL 16 | Docker `postgres`, volumen `pgdata` | Reuniones, estados, transcripciones, hablantes y propiedad |
| Archivos | RustFS compatible con S3 | Docker `minio`, volumen `minio-data` | Audio/video y enlaces firmados para acceso temporal |
| Cola | RabbitMQ 3 | Docker `rabbitmq` | Trabajos asíncronos firmados |
| Transcripción | MLX Whisper `large-v3-turbo` (se reemplaza por whisper.cpp `large-v3-turbo` Q5_0 en la unidad U2 de `core-speech-pipeline`) | Host Mac, puerto 8001 | `POST /transcribe`; `backend/asr-engine/native_main.py` |
| Diarización | Senko (CoreML), contrato v2 | Host Mac, puerto 8002 | `POST /diarize`; `backend/diar-engine/native_main.py` |
| Resumen | `llm-engine` + `llama-server` (llama.cpp) con Qwen3.5-9B, o un proveedor compatible con OpenAI configurado explícitamente | Host Mac, puerto 8003 (llama-server interno en 8004) | `POST /v1/chat/completions`; `backend/llm-engine/native_main.py` |

## Entorno local con Docker Desktop

En el Mac, los servicios de Sauri corren en **Docker Desktop** como el proyecto de Compose **`sauri`** (`docker-compose.yml` de la raíz). Los motores de IA no van en Docker: corren nativos en el Mac para usar Metal/CoreML, y los contenedores los alcanzan por `host.docker.internal`.

| Servicio (Compose) | Puerto en el Mac | Datos |
|---|---|---|
| `portal` (Nginx con el portal construido) | `127.0.0.1:5173` (`PORTAL_PORT`) | — |
| `api` (FastAPI) | `127.0.0.1:8000` | — |
| `worker` (transcripción, diarización, resumen, retención, miniaturas de la biblioteca con `ffmpeg` estático) | — | — |
| `postgres` (PostgreSQL 16) | `127.0.0.1:5432` | volumen `sauri_pgdata` |
| `minio` (RustFS, compatible S3; conserva el nombre MinIO) | `127.0.0.1:9000` (API) y `127.0.0.1:9001` (consola) | volumen `sauri_minio-data` |
| `rabbitmq` (RabbitMQ 3 con consola de administración) | `127.0.0.1:5672` y `127.0.0.1:15672` | volumen `sauri_rabbitmq-data` |
| Motores nativos (fuera de Docker) | `127.0.0.1` `8001` ASR, `8002` diarización, `8003` resumen | modelos en `~/.local/share/sauri/`, credenciales en `~/.config/sauri/` |

Comandos: `make up` (levanta el proyecto `sauri`), `make logs`, `make down`; `make engines-install`, `make engines-up`, `make engines-status`, `make engines-down` para los motores nativos. Instalación paso a paso en `docs/operations/installation-notes.md`.

Reglas del entorno local:
- Hay **un solo entorno principal**, el proyecto `sauri`, y sus volúmenes guardan los datos reales del dueño: nunca se borran ni se recrean sin su autorización.
- Las pruebas que necesitan PostgreSQL o RabbitMQ usan bases o contenedores **desechables** con otro nombre (bases `sauri_qa_*`/`sauri_t11_*`, contenedores `sauri-qa-*`), sin publicar puertos fuera de `127.0.0.1`, y se eliminan al terminar.
- Antes de diagnosticar o probar, se revisa el estado real con `docker compose -p sauri ps` y `make engines-status`; un servicio configurado no demuestra que esté corriendo.

```mermaid
graph LR
  E[Extensión Chrome] --> A[API Docker]
  P[Portal React servido por Nginx Docker] -->|proxy API| A
  P -->|enlaces firmados y Range| S
  A --> D[PostgreSQL Docker]
  A --> S[S3 RustFS Docker]
  A --> Q[RabbitMQ Docker]
  Q --> W[Worker Docker]
  W --> D
  W --> S
  W --> T[ASR nativo :8001]
  W --> H[Senko nativo :8002]
  W --> L[llm-engine nativo :8003]
```

La configuración de API/worker apunta a `host.docker.internal:8001`, `:8002` y `:8003`. Los motores implementan HTTP y controles de credenciales/capacidad por grabación. Su arranque, accesibilidad desde Docker y uso efectivo de GPU deben comprobarse juntos; tener una URL o un modelo configurado no demuestra inferencia. Credenciales fuera del repositorio en `~/.config/sauri`, montadas de solo lectura al worker; modelos compartidos en caché, nunca copiados al repositorio.

## Procesamiento sin repeticiones y regeneración explícita (#1053)

**Regla.** Una etapa cuya salida ya existe (transcripción de la grabación, revisión de hablantes, resumen) nunca se vuelve a calcular por un disparador automático: ni al refrescar o reabrir la página, ni al reiniciar API o worker, ni por reentregas o reconexiones de la cola, ni al guardar un nombre de hablante, cambiar la plantilla por defecto, reenviar la subida o por la retención. Solo una petición explícita del usuario crea trabajo nuevo.

**Cómo se garantiza.**
- Cada mensaje de la cola lleva una generación de procesamiento y se consume una sola vez (`meeting_processing_claims`). Los workers descartan, con una línea `reason=stage_complete`/`fenced`, cualquier mensaje de una etapa ya completa, salvo que traiga una operación de regeneración vigente (reclamo `recovery` con `operation_id`).
- El resumen automático solo existe como primer resumen de una transcripción (id determinista); cuando ya hay cualquier solicitud o resumen, el camino automático no crea otro. El outbox solo reenvía solicitudes `pending`/`running`.
- Una operación de regeneración abre una generación nueva: los mensajes de generaciones anteriores quedan descartados.

**API** (dueño de la reunión; cabecera opcional `Idempotency-Key`):
- `POST /api/v1/meetings/{id}/regenerate` con `{"stage": "transcription" | "speakers" | "summary", "template_id"?, "cascade"?}` responde 202 con `operation_id`, `stage`, `status`, `requested_at`, `replaces` (etapas que se recalculan) y `stale` (salidas posteriores que quedan visibles pero desactualizadas). `cascade` (por defecto `false`) encadena las etapas siguientes, una a la vez. Etapa desconocida: 422. Otra operación o procesamiento en curso: 409 `operation_active`/`processing_active` (con la operación activa). Grabación no disponible: 409 `media_unavailable`.
- `GET /api/v1/meetings/{id}/regenerate/latest` y `GET .../regenerate/{operation_id}` consultan el estado (`accepted`, `running`, `succeeded`, `failed`, con `failure_cause`).
- `GET /api/v1/meetings/{id}` agrega, solo cuando aplica, `stale_stages` y `active_operation`. `GET .../speaker-review?revision_id=N` lee una revisión anterior.

**Reglas por etapa.** *Resumen:* misma aceptación que `/summary-requests`; el resumen anterior sigue visible hasta que el nuevo termina bien. *Hablantes:* nueva revisión sobre la misma transcripción; un nombre se arrastra a la nueva revisión solo si ambos hablantes son la mejor coincidencia mutua y comparten al menos 70 % del tiempo de voz de cada uno; si no, la revisión nueva queda pendiente de revisión y la anterior sigue accesible. No se regenera el resumen. *Transcripción:* se reemplaza el contenido de la misma transcripción; la detección de hablantes previa se re-atribuye por tiempo y queda marcada como desactualizada junto con el resumen; la reunión pasa a `transcribing` mientras corre y vuelve a `completed` al terminar, también si falla (se conservan las salidas previas y se guarda `failure_cause`).

**Auditoría.** Tabla `regeneration_operations` (etapa, solicitante, `requested_at`, `started_at`, `finished_at`, estado, causa de fallo, detalle sin contenido). Una reunión admite una sola operación activa (índice único parcial). Un barrido del worker marca como fallidas (`stale_operation`) las ejecuciones que superan `SUMMARY_STALE_AFTER_SECONDS` (75 min por defecto).

## Seguridad local

- **Puertos solo locales.** Todo puerto publicado (portal 5173, API 8000, PostgreSQL 5432, RustFS 9000/9001, RabbitMQ 5672/15672) escucha únicamente en `127.0.0.1`; otras máquinas de la red no los alcanzan. Los motores nativos (8001 ASR, 8002 diarización, 8003 pasarela LLM, 8004 llama-server) también.
- **Sin credenciales fijas.** `scripts/engines/ensure-native-engine-credentials.sh` (invocado por `make build`/`make up` mediante `scripts/platform/compose-bringup.sh`) genera una vez valores al azar en archivos privados (0600, carpeta 0700) bajo `~/.config/sauri/`: `engine_token`, `recording_capability_key`, `queue_signing_key`, `admin_password`, `database_password`, `queue_password`, `object_store_access_key`, `object_store_secret_key` y `jwt_secret`. Nunca se versionan ni se imprimen.
- **Patrón `*_FILE`.** Los contenedores reciben esos archivos de solo lectura en `/run/secrets/<nombre>` y los leen con `DATABASE_PASSWORD_FILE`, `QUEUE_BROKER_PASSWORD_FILE`, `OBJECT_STORE_ACCESS_KEY_FILE`, `OBJECT_STORE_SECRET_KEY_FILE` y `JWT_SECRET_FILE` (PostgreSQL: `POSTGRES_PASSWORD_FILE`; RustFS: `RUSTFS_ACCESS_KEY_FILE`/`RUSTFS_SECRET_KEY_FILE`). Las URL de conexión no llevan contraseña. Los motores ASR y diarización leen las llaves del almacén desde `~/.config/sauri/`.
- Migración de instalaciones existentes, rotación de valores y reinicio de motores: ver `docs/operations/local-deployment.md`.

## Mapa de especificaciones del primer recorrido

| Tramo | Fuente existente | Estado contrastado / pendiente |
|---|---|---|
| Captura y preferencias | `.spectra/specs/extension-capture-preferences/requirements.md` | Solo requirements en main; no inventar diseño/tareas aprobados |
| Finalización, carga y apertura de revisión | `.spectra/specs/chrome-recording-completion/{requirements,design,tasks}.md` | Tres documentos presentes; PR #703 MERGED (head `191c8aa`, verificado durante U4). No inferir de ese merge captura real, recorrido integrado ni aceptación; revisar cada issue antes de abrir trabajo |
| Reproducción | `.spectra/specs/meeting-review-playback/` | Diseño, tareas y registro de aceptación separados; API `/api/v1/meetings/{meeting_id}/playback` implementada, falta comprobar recorrido integrado |
| Biblioteca y metadatos | `.spectra/specs/recording-library-metadata/` | Main contiene requirements/config; discrepancias documentales ya registradas en #701, #715, #716. Reusar esos issues, no duplicarlos |
| Fallos de carga existentes | #606 y pruebas `extension/src/background.upload-retry.test.ts`, `upload-queue.*test.ts` | Inspeccionar correcciones existentes antes de iniciar otra; una prueba con dobles no acredita carga real |

La spec de finalización exige abrir revisión **después de procesamiento exitoso y activos protegidos disponibles**. El avance inicial de guardar/reproducir no autoriza suprimir esa condición ni anunciar transcripción terminada. Primero validar almacenamiento y reproducción como capacidades reales; conservar el comportamiento aprobado de apertura automática hasta que una enmienda funcional sea aprobada.

## Evidencia y brechas

Una auditoría previa verificó aisladamente escrituras/lecturas PostgreSQL, migraciones, objetos S3 con lectura parcial firmada, envío/recepción RabbitMQ y arranque API/worker. Se retiraron recursos sintéticos de esa auditoría. **No acredita inferencia, captura real Chrome, propiedad con autenticación activa ni recorrido completo.**

U4 #837 repitió en entorno nuevo y autenticado escrituras/lecturas PostgreSQL/S3, mensaje firmado publish/consume/ack, login real de dos usuarios sintéticos, carga audiovisual por API/proxy y permisos A/B/anónimo; tres rangos del enlace firmado con bytes/Content-Range/CORS exactos y firma alterada denegada. También pasaron las tres pruebas existentes de endpoint público y playback con S3 real. Entorno eliminado al terminar. El recorrido del 13/11 comprobó biblioteca autenticada, reproducción S3 real, salto temporal, velocidad, recarga, error ante medio ausente y logout; además detectó y corrigió una redirección que perdía el puerto del portal. Ver detalles y límites en `docs/operations/local-deployment.md`: sesión QA emitida por login API y restaurada mediante la herramienta de navegador, no envío manual del formulario. Con un fragmento autorizado de Downloads, una llamada directa y offline a MLX produjo cuatro segmentos reales (dispositivo predeterminado reportado GPU); se importó ese resultado como datos QA sin marcar la reunión completed para revisar la lectura/reproducción. No demuestra worker, endpoint nativo HTTP, utilización GPU medida ni diarización. El worker QA no alcanzó los motores (`ConnectError`); los procesos nativos seguían detenidos y pyannote no estaba en la caché local. La UI existente sin transcript muestra 404 y no abre el reproductor. Estos resultados son del candidato, no del merge de #840 ni aceptación de producto.

Orden de ejecución: reconciliar especificaciones y aprobaciones → reparar conexiones concretas con pruebas → publicar e integrar unidades → validar captura/carga/propiedad/reproducción → validar transcripción y hablantes sobre ese recorrido. No reemplazar funcionalidad con rutas de demostración o datos simulados; los datos sintéticos son únicamente fixtures de prueba.

## Preservación y mantenimiento

No ejecutar `docker system prune`, eliminar volúmenes ni limpiar recursos ajenos. Identificar proyecto, propiedad, datos y autorización antes de retirar recursos existentes. La auditoría inicial midió un volumen principal de aproximadamente 2,426 GB; es un dato histórico, no un inventario vigente ni autorización de borrado. Las mediciones globales de Docker pueden incluir otros recursos: verificar siempre su estado y la autorización actual. QA retira contenedores/redes/volúmenes propios al finalizar; no ejecuta limpieza global de imágenes compartidas ni cache.

Todo cambio arquitectónico debe actualizar este documento y la spec afectada en la misma entrega, indicando motivo, alternativas descartadas, impacto de despliegue/datos y evidencia. Registrar decisiones de producto, privacidad, gasto o seguridad aprobadas por Fer; decisiones técnicas no amplían esas autorizaciones. `docs/product/baseline.md` sigue siendo la autoridad de producto, y las fases SDD conservan sus aprobaciones separadas de implementación, merge y aceptación.

## Modos de captura de la extensión (#994)

- **«Record» / Grabar (principal):** selector nativo con `getDisplayMedia` dentro
  del offscreen, según la [guía de Chrome](https://developer.chrome.com/docs/extensions/how-to/web-platform/screen-capture).
  Cancelar no cambia el estado previo ni crea sesión. Sin audio se liberan las
  pistas y se pide volver a elegir con «Share tab audio» activado. Se rechazan
  ventanas/monitores por `displaySurface`; ante `TypeError` se reintenta una vez
  sin opciones opcionales, conservando esa validación. No hay loopback: se pide
  `suppressLocalAudioPlayback: false` para evitar audio duplicado.
- **«Record this tab» / Grabar esta pestaña (atajo):** `tabCapture.getMediaStreamId`
  del worker obtiene la pestaña activa; el offscreen consume el ID con fuente
  `tab` e incluye audio. Aquí sí hay loopback al destino local del AudioContext,
  porque esta API silencia la pestaña. Se conservan `tabCapture` y `activeTab`;
  abrir el panel desde `action.onClicked` concede acceso a esa pestaña. Si falta
  ese permiso, se explica cómo volver a invocar la extensión, sin sesión huérfana.
  El atajo se deshabilita en páginas internas/extensiones/tienda; admite páginas
  web HTTP(S). Cambiar de pestaña no concede automáticamente otro `activeTab`.

Ambos modos usan offscreen con razones `DISPLAY_MEDIA` y `USER_MEDIA`: el siguiente
inicio recrea documentos inactivos para actualizar razones, nunca capturas vivas.
`pickerSource` registra `picker` o `current-tab` en el estado de sesión, sin contenido
personal adicional. Comparten MediaRecorder, mezcla de micrófono solo para el
archivo, WebM, IndexedDB y subida. La identidad durable se crea después de obtener
los medios válidos. `audio_only` excluye video del archivo, pero conserva su pista
fuente para detectar `ended`, usando el cierre durable de `captured-tab-close`.
Cerrar la pestaña de origen también finaliza; en el selector puede ser distinta de
la elegida. Solo Meet recibe consulta de título y banner. Otros orígenes conservan
`provider: "meet"` por falta de proveedor genérico, sin título/enlace de Meet.

Con micrófono configurado, el panel consulta su permiso antes de cualquiera de los
modos. Si no está concedido, o el offscreen recibe `NotAllowedError` del micrófono,
no inicia MediaRecorder: abre la página de opciones existente y pide autorizarlo
allí y volver a pulsar Record. El panel enumera dispositivos sin pedir permiso por
su cuenta; los dispositivos sin ID visible usan el micrófono predeterminado, no se
convierten silenciosamente en una captura sin micrófono.
**NO VERIFICADO en Chrome del dueño:** ambos inicios, permisos, selector, audio
local sin silencio/eco y recorrido real; los mocks no sustituyen aceptación.

### Lista de prueba manual para el dueño

1. Construir y recargar la extensión; abrir Meet en una pestaña nueva e invocar
   el panel desde el icono de la extensión, con sesión iniciada en Sauri.
2. Con micrófono sin permiso, probar cada botón: debe abrir opciones sin grabar.
   Autorizar con «Enable microphone», volver a Meet y pulsar Record otra vez.
3. Probar «Record»: ver el estado de selección sin contador; elegir una pestaña
   (también distinta del origen) con audio activado y hablar por el micrófono.
4. Verificar audio local una sola vez; usar «Dejar de compartir». El portal debe
   abrir la reunión y reproducir video, audio de pestaña y voz.
5. Probar Cancelar y desmarcar audio: ninguno debe crear sesión; el segundo debe
   explicar cómo activar «Share tab audio». Reintentar con audio activado.
6. Probar «Record this tab»: inicio sin selector, audio local audible una sola vez,
   micrófono en el archivo; cerrar esa pestaña y comprobar subida/apertura del portal.
   Repetir deteniendo la captura y con `audio_only` en ambos modos.
7. Comprobar atajo deshabilitado en `chrome://settings`, y ambos modos desde una web
   no-Meet sin banner. Reabrir el panel durante una captura: no debe iniciar otra ni
   destruir la actual. Reinvocar el icono si se cambia de pestaña para usar el atajo.
