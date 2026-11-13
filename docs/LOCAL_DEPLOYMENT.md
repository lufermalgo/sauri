# Despliegue local y validación aislada

Spec: `.spectra/specs/local-platform-deployment/`; issue padre #818; U1 #827/PR #829, U2 #830/PR #832, U3 #833/PR #836, U4 #837. U1–U4 están integradas en `main` por Fer; #840 corresponde al merge `f7614d6` (13/11/2026 01:56 UTC). La revalidación integrada se registra abajo: integración no equivale a inferencia ni a aceptación de producto.

## Qué se ejecuta dónde

- Docker: portal construido (Nginx), API, worker, PostgreSQL, RustFS/S3 y RabbitMQ.
- Chrome: extensión MV3; no vive en Docker.
- Mac: motores HTTP nativos MLX Whisper y pyannote/MPS. No son servicios Compose. Una URL o `/health` no demuestra inferencia ni GPU.
- PostgreSQL guarda datos/propiedad; S3 guarda audio/video; RabbitMQ transporta trabajos, no es el archivo de las grabaciones.

El portal se sirve en `http://127.0.0.1:5173` por defecto (`PORTAL_PORT`). `/api/` pasa a la API sin reemplazar su autenticación. Los medios se leen directamente con enlaces S3 temporales firmados, usando `OBJECT_STORE_PUBLIC_ENDPOINT` accesible desde el navegador; nunca se reescribe una URL después de firmarla. El almacenamiento conserva nombres históricos MinIO aunque su imagen sea RustFS; esto no migra datos anteriores (#543).

## Requisitos y arranque

Docker Desktop activo y Docker Compose con soporte de `!override` para QA. La imagen del portal usa Node 22 y Nginx con digests fijados; no necesita Vite ni Node en el host para servirla. Node >=20 es requisito de desarrollo frontend/extensión, no del runtime Nginx. Python >=3.11 en el host ejecuta la herramienta QA; `--connections` requiere además `ffmpeg` en PATH para crear dos segundos audiovisuales sintéticos. No descarga modelos.

Las variables privadas deben estar configuradas mediante un archivo privado de entorno o el mecanismo de secretos autorizado; no guardar sus valores en Git, capturas ni evidencias:

- `QUEUE_MESSAGE_SIGNING_KEY`: firma de trabajos, mínimo 32 bytes.
- `SPEAKER_EXCERPT_ACTIVE_KEY_ID` y `SPEAKER_EXCERPT_KEYRING`: identificador y llavero versionado AES-256. Formato del llavero: pares `id:base64`, separados por comas; **no JSON**.
- `JWT_SECRET`: firma de sesiones. No usar el valor local predeterminado como evidencia de seguridad multiusuario.
- `AUTH_DISABLED=false` en validación. El bypass heredado solo opera con `APP_ENV=test`; no se habilita en este procedimiento.
- `OBJECT_STORE_PUBLIC_ENDPOINT`: dirección S3 accesible desde el navegador, por defecto `http://localhost:9000`.

`make up` preserva volúmenes, verifica credenciales nativas, detiene API/worker del proyecto seleccionado antes de migrar, inicia infraestructura, asegura el bucket, ejecuta Alembic y arranca API/worker/portal. `make build` construye primero las imágenes. No aplicarlos sobre datos personales sin la coordinación y respaldo acordados. El portal se incluye al final; éxito exige HTTP 200 tanto estático como de API con un plazo común de 60 segundos. El mensaje final no acredita inferencia.

Las credenciales nativas residen en `~/.config/sauri/engine_token` y `recording_capability_key` (0600), preservadas si existen y montadas de solo lectura en el worker. `make engines-status` comprueba procesos, no acceso desde Docker. `make engines-up` es una acción separada; las validaciones aisladas no la ejecutan ni modifican los procesos de Fer.

## Procedimiento QA sin datos personales

Usar una carpeta temporal externa al repositorio, por ejemplo la carpeta scratch de APX. No se selecciona el proyecto principal por defecto.

1. `python3 _tools/validate-local-platform.py create --directory /ruta/temporal/externa` genera una carpeta privada y muestra la ruta del `inventory.json`.
2. `python3 _tools/validate-local-platform.py check --inventory /ruta/inventory.json` construye/inicia exclusivamente ese proyecto y verifica HTTP estático/API. **Es solo salud HTTP**, no conexiones de datos.
3. Añadir `--connections` para DB/S3/cola, dos usuarios con login real, carga audiovisual real, comparación API/proxy, propiedad, rangos S3/CORS/firma y controles de conectividad nativa. El worker QA se detiene antes de subir el medio para no enviar trabajos a los motores de Fer. No se simula procesamiento terminado.
4. `--hold-seconds N` conserva el entorno por un máximo de 900 segundos para una revisión en navegador; al vencer el plazo también se elimina automáticamente. Sin esa opción no deja servicios esperando.
5. `--controlled-failure` provoca un error después del arranque: debe terminar con salida no cero y eliminar sus recursos. No es un fallo inesperado ni una prueba de éxito funcional.
6. `python3 _tools/validate-local-platform.py cleanup --inventory /ruta/inventory.json` permite repetir/verificar limpieza tras éxito, error o interrupción.

Cada ejecución tiene runId aleatorio, nombre Compose exacto, puertos registrados y volúmenes propios. Publica solo en loopback; ante conflicto selecciona otro bloque sin detener al ocupante. El worker monta únicamente claves sintéticas de esa ejecución. El volumen RabbitMQ se declara explícitamente en el override QA para evitar el volumen anónimo generado por su imagen. No se alteran los montajes persistentes del Compose personal.

El inventario y sus etiquetas deben coincidir antes de borrar un ID. Ante ambigüedad, inventario ausente, daemon inaccesible o recursos no registrados, se rechaza la limpieza; no anunciar éxito. Conservar el inventario para investigar, nunca reemplazarlo por un borrado por prefijo o `prune`.

`--connections` instala herramientas pytest únicamente en `/tmp/qa-test-tools` del contenedor desechable, sin cambiar dependencias de aplicación ni el host. Reutiliza `tests/infra/test_object_store_browser_endpoint.py` y `tests/meetings/test_playback_storage_integration.py`. Configura CORS solo en el bucket QA con el origen exacto del portal y GET/HEAD/Range, sin bucket público ni comodín. Esto no configura una política para datos personales.

Los archivos `qa.env`, `connections-private.json` (sesiones y enlaces temporales) son privados; no adjuntarlos a issues ni PRs. Las evidencias públicas deben limitarse a estados, comandos, IDs sintéticos y resultados. `connections.txt`, `engines.json`, métricas e inventario no deben incluir claves ni enlaces firmados completos.

## Disponibilidad y evidencia: qué significa cada control

| Capa | Control | Qué no acredita |
|---|---|---|
| Configuración | Compose efectivo y puertos/montajes propios | Servicio iniciado |
| Portal | `/portal-health` y navegador con assets construidos | API, datos ni permisos |
| API | `/api-health` proxifica `/health` | PostgreSQL/S3/cola saludables |
| Datos | Escritura/lectura de dos usuarios QA en PostgreSQL | Aceptación multiusuario de producto |
| Archivos | Escritura/lectura, carga real y tres rangos exactos 206, CORS y firma alterada denegada | Transcripción |
| Cola | Publish/consume/ack de un mensaje sintético firmado | Trabajo de inferencia terminado |
| Autorización | Usuario A/B/anónimo, API directa y proxy con mismo resultado | Cambio de política de acceso |
| Motores | GET `/health` desde un worker QA de una sola ejecución | Credenciales compatibles, inferencia, dispositivo GPU |
| Inferencia | Se registra separada como no verificada cuando no se ejecuta | No debe reemplazarse por un doble |
| Navegador | Abrir, consultar, reproducir y buscar en medio real | Captura Chrome ni aceptación de Fer |
| Integración | SHA remoto con merge y repetición aislada | Aceptación de producto |

Estado observado de U3: commit `e07c1ce` publicado en PR #836; 14 tests, ciclo Docker normal/fallo provocado y limpieza repetida sobre ese commit PASS. Cero contenedores/volúmenes al terminar; ambos controles remotos PASS. Merges reservados a Fer.

Estado observado inicial de U4 #837: DB/S3/cola, login de dos usuarios, carga real, comparación proxy/directo, denegación usuario B/anónimo y rangos/CORS/firma PASS en entornos sintéticos eliminados al finalizar. La comprobación visual autenticada permanece pendiente: el navegador APX fue reportado bajo control del dueño. Ni esto ni la integración de #703 (merge remoto verificado; ya no es draft) acredita por sí solo captura completa o inferencia. Ejecución `d63af4d2cec2`: tres pruebas reutilizadas PASS (0.12 s); ambos motores no alcanzables desde worker (`ConnectError`). `make engines-status` indicó ambos detenidos y GET locales a 8001/8002 devolvieron conexión fallida (HTTP 000). No se iniciaron ni alteraron. Preflight nativo sin red: dependencias instaladas, snapshot MLX encontrado; `snapshot_download(local_files_only=True)` para `pyannote/speaker-diarization-3.1` devolvió `LocalEntryNotFoundError`. No se descargó ningún modelo ni se leyó la credencial HF. Completar separación de hablantes requiere disponer de ese modelo y preparar el entorno nativo compatible; no se amplía la exclusión de descargas de esta spec. Ese era el estado anterior al recorrido del 13/11; el resultado actualizado está debajo.

### Recorrido APX del 13/11 y regresión de redirecciones

El navegador detectó un defecto real: `GET /api/v1/meetings` sin barra final respondía 307 con `Location: http://127.0.0.1/api/v1/meetings/`, perdiendo el puerto. La biblioteca mostraba `Failed to fetch`. Se corrigió el proxy para preservar `$http_host`, no `$host`. La comprobación contra FastAPI real reprodujo `Proxy redirect lost public origin` antes del cambio y pasó después; ahora exige la autoridad pública completa. No se cambia autenticación, CORS ni rutas de aplicación.

En la ejecución aislada `e4ddeee1678f`, portal construido en `127.0.0.1:15273`, se observó biblioteca autenticada, detalle, retorno, recarga/reapertura y reproducción real desde S3. Login de dos usuarios y errores 401/422 se comprobaron por API; para el recorrido se restauró mediante herramienta APX una sesión QA ya emitida por ese login. **No se tecleó contraseña ni se comprobó el envío manual del formulario de login.** El logout sí se pulsó y devolvió la pantalla de acceso. Recargar una ruta de detalle sirve la SPA y vuelve a la biblioteca: la UI existente mantiene la selección en memoria, no ofrece enlaces profundos persistentes.

Fer autorizó usar archivos `.webm` de Downloads. Se extrajo un fragmento privado de 10,288 s (~1,25 MB), sin modificar el original. MLX Whisper ejecutado directamente y sin red sobre el snapshot local produjo cuatro segmentos reales; reportó dispositivo predeterminado `Device(gpu, 0)`. No se midió utilización GPU ni se probó el endpoint HTTP nativo. El fragmento se subió por la API y el resultado real de ASR se importó como datos QA con proveedor `qa-direct-mlx-not-worker`, **sin marcar la reunión completed**. Esto permite validar lectura/reproducción, no demuestra que el worker haya procesado la grabación. No se publican el clip, texto, fotogramas, sesiones ni URLs firmadas en GitHub.

El navegador decodificó 294 frames de 1280×652, llegó a 10,288 s, `readyState=4`, sin error de medio; una segunda reproducción elevó el contador a 588. Se comprobó cambio a 1,5× y salto temporal al fragmento de 2 s. Esto no acredita búsqueda textual: el portal no presenta ese control. Al borrar exclusivamente el objeto QA y reabrir, apareció `Unable to reload meeting media. Playback has stopped.`, sin éxito ficticio. API de transcripción/playback devolvió 200; diarización/revisión 404 reales, sin sustituirlos por respuestas simuladas.

**Límites existentes:** sin transcripción, el detalle muestra el error 404 y no abre el reproductor; con motores detenidos esto impide revisar una carga nueva desde esa pantalla. Es comportamiento de la UI existente, no un fallo de proxy ni algo corregido por esta spec de despliegue. La inferencia integral, diarización, credenciales HTTP nativas, captura Chrome y aceptación de Fer siguen pendientes. La prueba directa MLX no elimina el bloqueo pyannote documentado arriba. Capturas privadas guardadas en la carpeta scratch de APX; la captura de biblioteca no contiene material de la reunión.

### Cierre de validación del candidato

Código publicado `35137ad` repetido en ejecución nueva `957299eaaed9`: validación de conexiones reales PASS, tres pruebas S3 PASS, limpieza automática y repetida verified. La ejecución visual `e4ddeee1678f` también terminó exit 0 con limpieza verificada. Inspección externa por etiquetas de ambas ejecuciones y del primer intento: cero contenedores, redes y volúmenes propios. No equivale a afirmar que no existan recursos de otros trabajos. CI de `35137ad`: backend PASS (1m30s), web/extensión PASS (2m1s), run43347460781. La actualización posterior es exclusivamente documental; no cambia código probado. PR #840 listo para el merge reservado a Fer una vez terminen los controles de esa actualización; integración y aceptación siguen pendientes.

### Revalidación integrada y corrección del diagnóstico de modelos — 13/11

U1–U4 ya están integradas: #840 merge `f7614d6`. Las menciones anteriores a candidato/no integrado describen los controles previos, no el estado remoto actual. Sobre `bb24e51`, run QA `be619c597080`: 15 tests host, conexiones DB/S3/cola firmada, login API de dos usuarios, proxy/directo, propietario/tercero/anónimo, carga multipart y tres rangos/CORS/firma PASS; 3 pruebas S3 PASS. Frontend 94 tests/typecheck/build, extensión 256 tests/typecheck/build y backend 16 tests de autorización PASS. Cleanup automático y repetido, con inspección externa por etiqueta: cero contenedores, redes y volúmenes propios. No se tocó el entorno personal.

El navegador APX mostró login tanto en el portal Docker como en la ruta de reunión; no se completó la sesión en esa ejecución. **La reproducción autenticada del integrado no quedó repetida**; se conserva como evidencia distinta el recorrido anterior del candidato #840. T5.3 permanece abierta.

Sobre el merge posterior #843 `fbe72b4`: `npm ci`, typechecks de los tres workspaces, 256 tests de extensión y los 5 E2E configurados PASS. API y autorización reales; captura, medios y procesamiento sintéticos, sin acreditar captura Chrome ni inferencia. Inspección externa: cero recursos `sauri-e2e-*`. #844 `e718170` solo agrega documentación respecto a ese candidato; no se atribuyen las pruebas a un SHA distinto del ejecutado.

**Corrección del bloqueo pyannote:** `LocalEntryNotFoundError` en Hugging Face no demuestra ausencia en toda la Mac. A pedido de Fer, el 13/11 02:45 UTC se encontró la configuración `speaker-diarization-3.1` y los pesos de sus modelos dependientes en la caché Torch local, descargados el 22/10. La conclusión anterior de modelo ausente queda retirada; no hace falta autorizar una descarga o enmienda por ese motivo. Nahuel comprobó carga offline de `SpeakerDiarization` y ejecución de inferencia en MPS con el venv nativo (Python 3.11.12, pyannote.audio 3.3.2, torch/torchaudio 2.5.1, huggingface-hub 0.24.7). Usó copia temporal de caché, `HF_HUB_OFFLINE=1`, HOME/cachés auxiliares aislados y sockets bloqueados. El WAV sintético de 12 segundos produjo 0 turnos: demuestra ejecución, NO calidad de separación de voces. Manifiestos SHA-256 de la caché original sin diferencias; copia y audio eliminados, sin servicios, tokens ni Docker. También quedó probado el adaptador real `backend/diar-engine/native_main.py` con S3 QA real (RustFS aislado), sin entorno ni credenciales del dueño: `/health` 200; `/diarize` sin bearer 401, sin capability 403 y con bearer/capability HMAC válidos 200 (`segments: []`, `num_speakers: 0`). Se leyó un WAV sintético de 384.044 bytes desde S3; esto acredita contrato y ejecución, no calidad vocal. Caché copiada/offline y conexiones limitadas a localhost. Se eliminaron contenedor/almacenamiento QA, modelos/audio/secretos y listeners; inventario Docker antes/después idéntico (0 contenedores, 3 redes, 19 volúmenes), caché original intacta. También se ejecutó la función productiva `app.diarization.worker._process_diarization` desde el venv backend en el host, con PostgreSQL QA migrado (`alembic upgrade head`, salida 0), S3 real y motor nativo real: creó el proveedor local y credenciales de request; persistió 1 diarización `completed`, proveedor `diar-engine-local`, 0 hablantes/0 asignaciones, y reunión conservó `completed`. Tono sintético: NO acredita calidad vocal. Infraestructura QA eliminada y caché original intacta. Quedó validado también RabbitMQ → `app.worker.main` en Docker → motor nativo del host → S3/PostgreSQL QA: mensaje `diarize` firmado y persistente publicado mediante `create_job_queue().publish`, consumido y confirmado, fila `completed` con proveedor `diar-engine-local`, cola `diarize` final 0 pendientes/0 sin confirmar; reunión conservó `completed`. Docker alcanzó `/health` mediante `host.docker.internal` (HTTP 200). Migraciones y prueba terminaron con salida 0. Se usó imagen worker existente sin construir/descargar, con copia readonly del código productivo actual sobre `/app/app`: acredita código/entrypoint ejecutados, NO contenido de una imagen distribuida. Primer intento RabbitMQ falló por diagnóstico prematuro que interfería con su cookie; se corrigió la espera y pasó. Recursos propios eliminados en cada intento; inventario final idéntico, sin listeners/directorios QA ni cambios en caché. Tono sintético/0 hablantes NO acredita calidad vocal. Continúa pendiente transcripción real, habla real y recorrido integral de producto (captura/UI/aceptación). No habilita iniciar procesos personales, cambiar cachés ni descargar modelos. La inferencia integral y aceptación siguen no verificadas.

## Recuperación y espacio de disco

- Fallo de bucket/migración/API: el arranque termina no cero; investigar la etapa, sin borrar datos para conseguir un verde.
- Puerto ocupado: elegir otro puerto o bloque QA; no matar al ocupante.
- QA interrumpido: repetir `cleanup` con su inventario, comprobar que Docker esté accesible y revisar IDs/etiquetas antes de intervenir. Un inventario con `cleanup: verified` no sustituye una inspección externa de residuos.
- `make down` conserva datos del proyecto seleccionado. **`make clean` elimina datos y no es parte del arranque ni de estas pruebas.**
- Las pruebas retiran contenedores, redes y volúmenes exclusivamente temporales. Las imágenes compartidas y build cache se conservan según el diseño; medir con `docker system df`, no atribuir cifras globales solo a Sauri ni ejecutar limpieza global. La eliminación de imágenes antiguas/datos personales requiere una autorización específica vigente.

Cambios de tecnología, límites, datos o permisos deben mantener sincronizados este documento, `ARCHITECTURE.md` y la spec. Documentación aprobada, implementación, publicación, merge, recorrido, inferencia y aceptación son estados diferentes.
