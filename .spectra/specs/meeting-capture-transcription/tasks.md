# Implementation Plan: Captura y Transcripción de Reuniones (sauri)

## Overview

Plan de implementación incremental y atómico para el módulo MVP de sauri, alineado con el **stack mixto** confirmado en `design.md`:

- **Backend y workers — Python + FastAPI.** API HTTP (REST/JSON) y workers asíncronos en Python. Tipado con **mypy**, linting/estilo con **ruff**. Persistencia con **SQLAlchemy** sobre **PostgreSQL** (migraciones con Alembic). La cola de trabajos se consume con un worker Python. PBT del backend con **Hypothesis** (mínimo **100 iteraciones** por propiedad).
- **Extensión de Chrome (fuente de captura principal) — TypeScript sobre Manifest V3.** Lógica de captura (service worker, documento offscreen, content script) en TS; UI del panel lateral en **React** con **Vite + CRXJS**. Pruebas con **Vitest/Jest** y e2e con **Playwright**. PBT del lado cliente con **fast-check** cuando aplique una propiedad del lado cliente.
- **App web (frontend SPA) — TypeScript + React (Vite).** Comparte los tipos del dominio/contrato del API con la extensión (paquete de tipos compartido).
- **Motor_ASR local — contenedor propio basado en faster-whisper**, detrás de la interfaz `Motor_ASR`; el proveedor en la nube es una alternativa seleccionable por configuración.

Convenciones de prueba (TDD + PBT):
- Cada una de las **15 propiedades de correctitud** del diseño se implementa con un **único** test de propiedad en su sub-tarea individual (marcada opcional con `*`).
- Las propiedades del **backend** usan **Hypothesis**; las del **lado cliente** usan **fast-check**. Ambas con **mínimo 100 iteraciones** (`max_examples=100` en Hypothesis; `numRuns: 100` en fast-check).
- Cada test de propiedad se etiqueta con un comentario en el formato exacto:
  `Feature: meeting-capture-transcription, Property {n}: {texto de la propiedad}`
- Las sub-tareas marcadas con `*` (tests) son opcionales para un MVP rápido pero recomendadas; las tareas sin `*` son obligatorias.
- El orden de-arriesga temprano: el **SPIKE/PoC de captura por extensión** (Tarea 2) valida la pieza de mayor riesgo antes de construir el resto del pipeline.

Componentes propios de sauri: la extensión de Chrome y su capa de captura son piezas propias de este proyecto; ningún producto externo se usa como base ni inspiración.

## Tasks

- [x] 1. Configurar estructura del proyecto y tooling base (stack mixto)
  - [x] 1.1 Inicializar backend Python (FastAPI) y tooling de calidad
    - Crear `backend/` con módulos `reuniones`, `ingesta`, `transcripcion`, `retencion`, `auth`, `infra`
    - Configurar `pyproject.toml`, **mypy** (tipado estricto) y **ruff** (lint/estilo) como gates de PR
    - Configurar **pytest** + **Hypothesis** (PBT) y esqueleto de **SQLAlchemy** + Alembic
    - _Requirements: 8.1_
  - [x] 1.2 Inicializar extensión (TS/MV3) y frontend (TS/React) con tipos compartidos
    - Crear `extension/` (Manifest V3, **Vite + CRXJS**, React para el panel lateral) y `frontend/` (React + Vite)
    - Crear paquete `packages/shared-types` con los tipos del dominio/contrato del API compartidos por extensión y web
    - Configurar TypeScript estricto, comando de typecheck del proyecto (gate de PR), **Vitest/Jest**, **Playwright** y **fast-check**
    - _Requirements: 8.1_
  - [x] 1.3 Definir esqueleto de Docker Compose local sobre macOS
    - Declarar servicios placeholder: `api` (FastAPI), `worker` (Python), `postgres`, almacenamiento S3-local (MinIO), broker de cola (RabbitMQ/Redis), `asr-engine` (faster-whisper)
    - Definir variables de entorno para selección de implementaciones por configuración
    - _Requirements: 8.1, 8.2_

- [x] 2. SPIKE/PoC: validar captura A/V por extensión de Chrome contra backend local
  - [x] 2.1 PoC de carga de extensión MV3 (TS) y detección de Google Meet
    - Cargar la extensión como *unpacked*; detectar la pestaña de Meet por atributos ARIA con variantes español/inglés en el content script (TypeScript)
    - Resolver restricciones MV3 mínimas: gesto de usuario para `tabCapture`, service worker efímero con estado en `chrome.storage.session`
    - _Requirements: 2.1_
  - [x] 2.2 PoC de captura audio+video de la pestaña y subida de archivo de prueba al backend local
    - Capturar A/V vía `chrome.tabCapture.getMediaStreamId` + documento offscreen (TS) con `MediaRecorder` (`video/webm` codecs vp8/opus), con loopback de audio (`AudioContext.destination`)
    - Endpoint temporal mínimo en backend **FastAPI** que reciba un multipart de prueba y confirme la recepción
    - Documentar hallazgos y riesgos de viabilidad para informar las tareas siguientes
    - _Requirements: 2.1, 2.2_

- [x] 3. Checkpoint - validar viabilidad de captura
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implementar modelo de datos y persistencia relacional (Python/SQLAlchemy)
  - [x] 4.1 Definir modelos SQLAlchemy y migraciones de las entidades de dominio
    - Modelos + migraciones Alembic para `Reunion`, `EstadoHistorial`, `Grabacion_De_Sesion`, `Transcripcion`, `Turno_De_Habla/Segmento`, `Notificacion_De_Grabacion`, `RegistroDeAcceso`
    - Restricción única `reunion_id` en `Grabacion_De_Sesion` (1:1) y `clave_idempotencia` única
    - _Requirements: 2.3, 3.3, 4.1_
  - [x]* 4.2 Escribir property test de integridad referencial 1:1 (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 6: Integridad referencial 1:1**
    - Cada Grabacion_De_Sesion referencia exactamente una Reunion y ninguna Reunion tiene más de una; cada Transcripcion referencia su Reunion
    - Hypothesis, mínimo 100 iteraciones (`max_examples=100`)
    - **Validates: Requirements 2.2, 2.3, 3.3**
  - [x] 4.3 Implementar repositorios de persistencia y referencias a objetos
    - Repositorios SQLAlchemy que guardan referencias (`audio_ref`/`video_ref`) y metadatos; los blobs viven en el `AlmacenDeObjetos`
    - _Requirements: 2.2, 3.3_

- [x] 5. Implementar máquina de estados y orquestación del Servicio_De_Reuniones (Python)
  - [x] 5.1 Implementar `aplicar_evento` como función pura de transición
    - Transiciones exactas del diagrama; eventos inválidos se descartan sin efecto; estados terminales inmutables; cada transición válida inserta una fila en `EstadoHistorial` con marca de tiempo; toda transición a `fallido` exige `causa_fallo` válida
    - _Requirements: 1.4, 1.5, 2.5, 3.6, 4.1, 4.2, 4.4_
  - [x]* 5.2 Escribir property test de integridad de la máquina de estados (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 3: Integridad de la máquina de estados**
    - Solo transiciones válidas; estado en el conjunto permitido; terminales inmutables; una entrada de historial por transición válida. Hypothesis con generadores de secuencias de eventos (incl. inválidos), mínimo 100 iteraciones
    - **Validates: Requirements 1.4, 1.5, 2.5, 3.6, 4.1, 4.2**
  - [x]* 5.3 Escribir property test de causa de fallo válida (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 4: Toda transición a "fallido" registra una causa válida**
    - timeout>120s ⇒ no pudo unirse; cancelación desde en cola ⇒ reunión cancelada; ASR sin texto ⇒ fallo del motor. Mínimo 100 iteraciones
    - **Validates: Requirements 1.6, 3.7, 4.3, 4.4**
  - [x] 5.4 Implementar `registrar_reunion` aceptando los tres tipos de entrada
    - Acepta enlace de Meet, identificador de invitación de calendario o solicitud manual con enlace; crea Reunion en estado `en cola`; rechaza entradas inválidas
    - _Requirements: 1.1, 1.7_
  - [x]* 5.5 Escribir property test de estado inicial "en cola" (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 1: Registro de Reunion inicia en "en cola"**
    - Mínimo 100 iteraciones
    - **Validates: Requirements 1.1**
  - [x]* 5.6 Escribir property test de aceptación de tipos de entrada (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 2: Aceptación de tipos de entrada de Reunion**
    - Acepta los tres tipos válidos, rechaza el resto. Mínimo 100 iteraciones
    - **Validates: Requirements 1.7**
  - [x] 5.7 Implementar `consultar_reunion` exponiendo estado y causa de fallo
    - Devuelve el último estado del `EstadoHistorial`; incluye `causa_fallo` si y solo si el estado es `fallido`
    - _Requirements: 4.5_
  - [x]* 5.8 Escribir property test de consistencia de consulta de estado (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 5: Consistencia de la consulta de estado**
    - Mínimo 100 iteraciones
    - **Validates: Requirements 4.5**
  - [x] 5.9 Implementar `solicitar_union` y `programar_union_por_calendario`
    - Unión manual encola trabajo de unión; disparo por `hora_inicio_programada`
    - _Requirements: 1.2, 1.3_
  - [x]* 5.10 Escribir unit tests de disparadores de unión (pytest)
    - Unión manual encola trabajo (1.2); disparo por hora con reloj simulado (1.3)
    - _Requirements: 1.2, 1.3_

- [x] 6. Checkpoint - dominio y persistencia
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implementar abstracciones de infraestructura cloud-agnósticas (Python)
  - [x] 7.1 Definir interfaz `AlmacenDeObjetos` e implementación local (S3-compatible/MinIO)
    - Operaciones `guardar`, `obtener`, `eliminar`, `url_temporal_de_lectura`; implementación local para Docker Compose
    - _Requirements: 8.3, 8.4, 6.3_
  - [x] 7.2 Definir interfaz `ColaDeTrabajos` e implementación local (broker)
    - `publicar`/`suscribir` con entrega al-menos-una-vez, reintentos y dead-letter (RabbitMQ/Redis local)
    - _Requirements: 8.3, 8.4_
  - [x]* 7.3 Escribir property test de conformidad de adaptadores (contract testing, Hypothesis)
    - **Feature: meeting-capture-transcription, Property 13: Conformidad de adaptadores de infraestructura**
    - Round-trip `guardar`→`obtener`; `eliminar` deja indisponible; mensaje publicado se entrega al suscriptor; contrato observable idéntico entre implementaciones (suite ejecutada contra cada impl./fake). Mínimo 100 iteraciones
    - **Validates: Requirements 8.3, 8.4**

- [x] 8. Implementar módulo Auth (autenticación y autorización, FastAPI)
  - [x] 8.1 Implementar `autenticar` y `autorizar` con auditoría de denegaciones
    - OIDC/JWT como dependencia FastAPI; ninguna operación de registro/consulta sin autenticación; acceso restringido a Usuarios_Comerciales autorizados; registrar denegaciones en `RegistroDeAcceso`
    - _Requirements: 7.3, 7.4, 9.1, 9.2, 9.3_
  - [x]* 8.2 Escribir property test de control de acceso y auditoría (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 10: Control de acceso y auditoría**
    - Acceso concedido si y solo si autenticado y autorizado; toda denegación genera exactamente una entrada con `resultado = denegado`. Mínimo 100 iteraciones
    - **Validates: Requirements 7.3, 7.4, 9.1, 9.2, 9.3**

- [x] 9. Implementar módulo de Ingesta con clave de idempotencia (FastAPI)
  - [x] 9.1 Implementar endpoint `subir_grabacion` multipart autenticado
    - Recibe A/V multipart + `clave_idempotencia` + `metadatos_consentimiento`; exige auth; persiste `Grabacion_De_Sesion` en `AlmacenDeObjetos`; registra `Notificacion_De_Grabacion`; transiciona a `transcribiendo`; encola trabajo de transcripción
    - _Requirements: 2.2, 6.5, 9.1, 9.2_
  - [x] 9.2 Implementar idempotencia por `clave_idempotencia`
    - Reintentos de subida con la misma clave crean a lo sumo una Grabacion y encolan a lo sumo un trabajo
    - _Requirements: 2.3, 4.1, 4.2_
  - [x]* 9.3 Escribir property test de idempotencia de manejadores e ingesta (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 14: Idempotencia de los manejadores del pipeline y de la ingesta**
    - Reprocesar un mensaje o reintentar subida con la misma clave produce el mismo estado final, sin duplicar Grabaciones/Transcripciones/transiciones. Mínimo 100 iteraciones
    - **Validates: Requirements 2.3, 4.1, 4.2**
  - [x]* 9.4 Escribir unit test del registro de Notificacion_De_Grabacion (pytest)
    - La ingesta persiste el registro auditable de consentimiento asociado a la Reunion (6.5)
    - _Requirements: 6.5_

- [x] 10. Implementar Motor_ASR intercambiable y worker de transcripción (Python)
  - [x] 10.1 Definir interfaz común `Motor_ASR` y fábrica por configuración
    - `transcribir(audio_ref, opciones)` y `capacidades()`; la fábrica selecciona el proveedor por variable de entorno sin tocar el `Servicio_De_Reuniones`
    - _Requirements: 5.1, 5.2, 5.5_
  - [x] 10.2 Implementar proveedor en la nube (canal cifrado)
    - Envía el audio al servicio externo configurado por canal cifrado (TLS)
    - _Requirements: 5.4, 7.2_
  - [x] 10.3 Implementar proveedor local basado en faster-whisper
    - Contenedor `asr-engine` propio; procesa la `Grabacion_De_Audio` sin enviarla a un servicio externo
    - _Requirements: 5.3_
  - [x] 10.4 Implementar worker de transcripción que produce la Transcripcion
    - Worker Python que consume la cola; invoca el `Motor_ASR` con `idioma_prioritario = es-CO`; persiste Transcripcion y segmentos/turnos con marcas de tiempo relativas; transiciona a `completado`; si no hay texto pese a audio hablado, transiciona a `fallido` con causa `fallo del motor`
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7_
  - [x]* 10.5 Escribir property test del invariante temporal de la Transcripcion (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 7: Invariante temporal de la Transcripcion**
    - `0 <= inicio_ms <= fin_ms <= duracion_segundos*1000`; segmentos ordenados sin solape; sin identidad nominal. Mínimo 100 iteraciones
    - **Validates: Requirements 3.4, 3.5**
  - [x]* 10.6 Escribir property test del idioma es-CO (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 8: Idioma de transcripción es-CO**
    - Las opciones fijan es-CO prioritario y la Transcripcion registra es-CO. Mínimo 100 iteraciones
    - **Validates: Requirements 3.2**
  - [x]* 10.7 Escribir property test de intercambiabilidad del Motor_ASR (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 9: Intercambiabilidad del Motor_ASR**
    - Cualquier proveedor conforme (con/sin turnos, local/externo) produce Transcripcion válida (cumple Property 7) sin cambios en el `Servicio_De_Reuniones`. Contract/model-based testing con fakes conformes. Mínimo 100 iteraciones
    - **Validates: Requirements 5.5**

- [x] 11. Checkpoint - pipeline servidor (ingesta + transcripción)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Implementar módulo de Retención y worker de borrado (Python)
  - [x] 12.1 Implementar cálculo de expiración configurable
    - `expira_en = creada_en + periodo` para `Grabacion_De_Sesion` y `Transcripcion`
    - _Requirements: 6.2, 6.6_
  - [x]* 12.2 Escribir property test del cálculo del periodo de retención (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 11: Cálculo del periodo de retención**
    - Mínimo 100 iteraciones
    - **Validates: Requirements 6.2**
  - [x] 12.3 Implementar worker de borrado por retención
    - Worker programado que elimina datos con `expira_en <= now`; al borrar la Grabacion expira audio + video y la Transcripcion asociada; conserva el resto
    - _Requirements: 6.3, 6.6_
  - [x]* 12.4 Escribir property test de borrado por retención del dato completo (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 12: Borrado por retención del dato completo**
    - Mínimo 100 iteraciones
    - **Validates: Requirements 6.3, 6.6**

- [x] 13. Implementar interfaz `Asistente_De_Reunion` y verificar intercambiabilidad (backend Python)
  - [x] 13.1 Definir contrato de ingesta/origen y manejo de `origen_captura` en el backend
    - Contrato común que el `Asistente_De_Reunion` cumple al entregar una `Grabacion_De_Sesion`; el campo `origen_captura` (`extension_chrome` | `bot_servidor`) no altera el pipeline posterior
    - _Requirements: 2.1, 2.2_
  - [x]* 13.2 Escribir property test de intercambiabilidad de la fuente de captura (Hypothesis)
    - **Feature: meeting-capture-transcription, Property 15: Intercambiabilidad de la fuente de captura**
    - Con fakes de `Asistente_De_Reunion` (extensión y bot servidor): una grabación ingerida produce el mismo flujo (almacenar → transcribir → persistir) y los mismos estados, independientemente del origen. Mínimo 100 iteraciones
    - **Validates: Requirements 2.1, 2.2**

- [x] 14. Adaptar la extensión de Chrome de sauri (TypeScript/MV3 + React)
  - [x] 14.1 Adaptar la capa de captura a video continuo (documento offscreen, TS)
    - Solicitar la pista de video del `tabStream`, componer un stream audio+video, `mimeType` `video/webm` codecs vp8/vp9+opus; mantener loopback de audio; troceo `timeslice` 5 s y persistencia de chunks en IndexedDB ensamblados por `sessionId`
    - _Requirements: 2.1, 2.2_
  - [x] 14.2 Implementar modos de captura seleccionables
    - Modo "pantalla + audio de la pestaña" y modo "solo audio de la pestaña"; ajustar las pistas compuestas y el `mimeType` del Blob según el modo
    - _Requirements: 2.1_
  - [x] 14.3 Implementar selección de micrófono y mezcla con el audio de la pestaña
    - Enumerar dispositivos de entrada, permitir seleccionar el micrófono y mezclar su pista con el audio de la pestaña vía `AudioContext` antes de grabar
    - _Requirements: 2.1_
  - [x] 14.4 Implementar ajustes de resolución de video y cuenta regresiva previa (panel React)
    - Selector de resolución aplicado a las `constraints` de la pista de video; cuenta regresiva configurable antes de iniciar la grabación, en el panel lateral React (Vite + CRXJS)
    - _Requirements: 2.1_
  - [x] 14.5 Implementar subida HTTP multipart autenticada al backend (TS)
    - Reemplazar el tramo final por subida multipart (audio+video) al endpoint de ingesta; añadir `host_permissions` del dominio del backend; esquema de autenticación ligado al acceso del Usuario_Comercial
    - _Requirements: 2.2, 9.1, 9.2_
  - [x] 14.6 Implementar cola de subida idempotente en IndexedDB (TS)
    - Cola con estados `pending/processing/done/failed`, `retryCount`, recuperación por `chrome.alarms` y `onStartup`; reintenta la subida con la misma `clave_idempotencia` sin duplicar
    - _Requirements: 2.3, 4.1_
  - [x] 14.7 Emitir y registrar la Notificacion_De_Grabacion (TS)
    - Banner de consentimiento en Shadow DOM + badge REC al iniciar captura; la subida transporta la marca de emisión para su registro auditable en el backend
    - _Requirements: 6.1, 6.5_
  - [x]* 14.8 Escribir tests de la capa de captura de la extensión (Vitest)
    - Tests del documento offscreen (composición A/V, modos de captura, mezcla de micrófono, `mimeType`) y del panel (resolución, cuenta regresiva)
    - _Requirements: 2.1, 2.2_
  - [x]* 14.9 Escribir property test de idempotencia de la cola de subida (fast-check, lado cliente)
    - **Feature: meeting-capture-transcription, Property 14: Idempotencia de los manejadores del pipeline y de la ingesta**
    - Faceta cliente: para toda secuencia de reintentos sobre la cola de IndexedDB con la misma `clave_idempotencia`, la extensión emite a lo sumo una subida efectiva (sin duplicar). fast-check, `numRuns: 100`
    - **Validates: Requirements 2.3, 4.1**

- [x] 15. Implementar frontend SPA mínimo autenticado (TypeScript + React/Vite)
  - [x] 15.1 Implementar registro de reunión, lista con estado y vista de transcripción
    - Cliente SPA delgado que consume el API usando los tipos compartidos; flujo autenticado; muestra `Estado_De_Proceso` y causa de fallo
    - _Requirements: 9.1, 9.2, 4.5_
  - [x]* 15.2 Escribir tests de componentes del frontend (Vitest)
    - Render de lista con estados y vista de transcripción; manejo de flujo no autenticado
    - _Requirements: 9.1, 9.2, 4.5_

- [x] 16. Checkpoint - clientes (extensión + web)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Integración y wiring del sistema completo
  - [x] 17.1 Cablear API FastAPI, módulos y workers sobre las abstracciones
    - Exponer rutas de registro/consulta/ingesta; suscribir workers de transcripción y retención a la cola; aplicar TLS en tránsito y cifrado en reposo a nivel de bucket/DB
    - _Requirements: 4.5, 7.1, 7.2, 8.3, 8.4_
  - [x] 17.2 Completar Docker Compose local equivalente a producción
    - Conectar `api` + `worker` (Python), PostgreSQL, MinIO (S3-local), broker y `asr-engine` (faster-whisper local o proveedor nube por config); la extensión apunta al endpoint de ingesta local
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [x]* 17.3 Escribir tests de integración del pipeline end-to-end (pytest + Docker)
    - Subida multipart autenticada (incl. reentrega con misma `clave_idempotencia`), transcripción y persistencia con dependencias en contenedores locales; adaptador ASR local sin llamadas externas (5.3) y adaptador externo enviando audio (5.4)
    - _Requirements: 2.2, 5.3, 5.4, 6.1_
  - [x]* 17.4 Escribir test e2e de captura → ingesta de la extensión (Playwright)
    - Flujo automatizado: cargar extensión, detectar Meet mockeado, capturar A/V y subir al endpoint de ingesta local; verificar transición a `transcribiendo`
    - _Requirements: 2.1, 2.2_

- [x] 18. Checkpoint final - sistema integrado
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las sub-tareas marcadas con `*` son opcionales (tests) y pueden omitirse para un MVP rápido; las tareas sin `*` son obligatorias.
- Backend y workers se implementan en **Python/FastAPI/SQLAlchemy/PostgreSQL**; sus tests de propiedad usan **Hypothesis** (`max_examples=100`). La extensión y la app web se implementan en **TypeScript/React/Vite/CRXJS**; sus tests usan **Vitest/Jest**, **Playwright** (e2e) y **fast-check** (`numRuns: 100`) para propiedades del lado cliente.
- Cada tarea referencia cláusulas de requerimiento específicas; los tests de propiedad referencian además la propiedad de correctitud del diseño con la etiqueta `Feature: meeting-capture-transcription, Property {n}: {texto}`.
- Cobertura de las 15 propiedades: P1→5.5, P2→5.6, P3→5.2, P4→5.3, P5→5.8, P6→4.2, P7→10.5, P8→10.6, P9→10.7, P10→8.2, P11→12.2, P12→12.4, P13→7.3, P14→9.3 (backend) y 14.9 (faceta cliente, fast-check), P15→13.2.
- El SPIKE (Tarea 2) de-arriesga la captura por extensión antes de construir el resto del pipeline.
- Alcance del módulo: captura A/V + ingesta + transcripción + persistencia + estados/errores + acceso autenticado + retención + seguridad/privacidad. Quedan fuera: identificación de hablantes, notas IA, CRM, biblioteca/reproductor y analítica.
- Cumplimiento (Colombia, Ley 1581): el registro de consentimiento (`Notificacion_De_Grabacion`) es persistente y auditable en el backend.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["4.1", "7.1", "7.2", "8.1", "14.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "5.1", "7.3", "8.2", "10.1", "14.2", "14.4", "14.7"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "10.2", "10.3", "12.1", "13.1", "14.3", "14.5"] },
    { "id": 6, "tasks": ["5.5", "5.6", "5.7", "9.1", "10.4", "12.2", "12.3", "13.2", "14.6", "15.1"] },
    { "id": 7, "tasks": ["5.8", "5.9", "9.2", "9.4", "10.5", "10.6", "10.7", "12.4", "14.8", "14.9", "15.2"] },
    { "id": 8, "tasks": ["5.10", "9.3", "17.1"] },
    { "id": 9, "tasks": ["17.2"] },
    { "id": 10, "tasks": ["17.3", "17.4"] }
  ]
}
```
