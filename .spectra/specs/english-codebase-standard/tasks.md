# Plan de Implementación — English Codebase Standard

Todas las tablas de mapeo español→inglés citadas en las tareas están definidas en [design.md](design.md) § Componentes e Interfaces (secciones 1–14) — esa es la fuente de verdad para cada rename; las tareas no repiten cada fila, citan la sección exacta a aplicar. Cada tarea de rename de producción usa `git mv` cuando cambia el nombre de archivo/carpeta (Decisión de Diseño "Renombrar archivos con `git mv`").

## Resumen de Fases

| Fase | Descripción | Tareas | Dependencias |
|---|---|---|---|
| 1 | Herramienta de verificación de idioma (`check_english_only.py`) | 1.1 – 1.4 | Ninguna |
| 2 | Migración de base de datos + modelos ORM | 2.1 – 2.8 | Fase 1 |
| 3 | `packages/shared-types` | 3.1 – 3.3 | Fase 2 |
| 4 | `backend/app/auth/` | 4.1 – 4.10 | Fase 2 |
| 5 | `backend/app/ingestion/` (was `ingesta/`) | 5.1 – 5.7 | Fase 2, 4 |
| 6 | `backend/app/meetings/` (was `reuniones/`) | 6.1 – 6.8 | Fase 2, 4, 5 |
| 7 | `backend/app/transcription/` (was `transcripcion/`) | 7.1 – 7.9 | Fase 6 |
| 8 | `backend/app/diarization/` (was `diarizacion/`) | 8.1 – 8.12 | Fase 7 |
| 9 | `backend/app/retention/` (was `retencion/`) | 9.1 – 9.5 | Fase 2 |
| 10 | `backend/app/infra/` (colas, almacenamiento) + `worker.py` | 10.1 – 10.7 | Fase 8, 9 |
| 11 | `extension/src/core/` | 11.1 – 11.15 | Fase 3, 6 |
| 12 | `extension/src/panel/` | 12.1 – 12.7 | Fase 11 |
| 13 | `extension/src/detail/` | 13.1 – 13.7 | Fase 11 |
| 14 | Archivos de nivel superior de la extensión + migración IndexedDB | 14.1 – 14.6 | Fase 12, 13 |
| 15 | `frontend/src/` | 15.1 – 15.6 | Fase 3, 6 |
| 16 | Documentación de gobernanza (`CLAUDE.md`, `AGENTS.md`) | 16.1 – 16.3 | Fase 1 |
| 17 | Verificación final de cierre | 17.1 – 17.5 | Todas las anteriores |

---

## Fase 1: Herramienta de verificación de idioma

### Tarea 1.1: Escribir el test que falla para `check_english_only.py` (RED)

**Archivo:** `backend/tests/test_check_english_only.py` (crear)
**Acción:** Escribir un test que invoque el script (aún no existente) `_tools/check_english_only.py` como subproceso o como módulo importado, contra un archivo temporal que contenga un identificador retirado del Domain_Term_Mapping (por ejemplo `def obtener_reunion():`) y otro que contenga un identificador válido en inglés (`def get_meeting():`). El test espera que el escaneo reporte exactamente 1 coincidencia (la línea con `obtener_reunion`) y 0 coincidencias para el archivo en inglés.

**Criterio de Completado:**
`cd backend && pytest tests/test_check_english_only.py -v` falla con `ModuleNotFoundError` o `FileNotFoundError` porque `_tools/check_english_only.py` no existe todavía.

**Dependencias:** Ninguna

---

### Tarea 1.2: Implementar `_tools/check_english_only.py` (GREEN)

**Archivo:** `_tools/check_english_only.py` (crear)
**Acción:** Implementar un script Python que:
- Recibe una lista de rutas de archivo (por argumento o vía `git diff --cached --name-only` cuando se ejecuta con `--staged`).
- Excluye por convención de ruta: `.spectra/specs/**`, `backend/tests/**/fixtures/**`, cualquier línea que contenga el comentario `# spanish-sample-data`.
- Busca, por línea, dos tipos de patrón: (a) caracteres acentuados/ñ en identificadores (`[a-zA-Z_][a-zA-Z0-9_]*[áéíóúñÁÉÍÓÚÑ][a-zA-Z0-9_]*`), y (b) una lista de términos retirados mantenida como constante `RETIRED_SPANISH_TERMS` en el propio script, poblada con las columnas "Español" de las tablas de `design.md` § Componentes e Interfaces (mínimo: `reunion`, `hablante`, `transcripcion`, `diarizacion`, `grabacion`, `usuario`, `obtener_`, `crear_`, `listar_`, `eliminar_`, `renombrar_`, `solicitar_`, `estado_proceso`, `causa_fallo`, `es_comercial`).
- Imprime `archivo:línea: <coincidencia>` por cada hallazgo y termina con código de salida `1` si hubo alguno, `0` si no.

**Criterio de Completado:**
`cd backend && pytest tests/test_check_english_only.py -v` pasa.

**Dependencias:** Tarea 1.1

---

### Tarea 1.3: Enganchar el chequeo a `.githooks/pre-commit`

**Archivo:** `.githooks/pre-commit`
**Acción:** Añadir, después del bloqueo de commits directos a `main` ya existente, una invocación de `python3 _tools/check_english_only.py --staged`; si el script sale con código `1`, imprimir los hallazgos y salir con `1` (bloqueando el commit), con el mismo mensaje de escape hatch `git commit --no-verify` que ya usa el hook.

**Criterio de Completado:**
Con un archivo en staging que contenga `def obtener_reunion():`, `git commit -m "test"` es rechazado por el hook mostrando el hallazgo; `git commit --no-verify -m "test"` lo permite.

**Dependencias:** Tarea 1.2

---

### Tarea 1.4: Añadir el target `make check-english`

**Archivo:** `Makefile`
**Acción:** Añadir un target `check-english` que ejecute `python3 _tools/check_english_only.py $(git ls-files 'backend/**' 'extension/src/**' 'frontend/src/**' 'packages/shared-types/**')` (escaneo completo, no solo staged), documentado junto a los demás targets existentes (`up`, `build`, `migrate`, etc.).

**Criterio de Completado:**
`make check-english` se ejecuta desde la raíz del repo y termina reportando la lista actual de hallazgos (se espera que sea larga hasta que se completen las Fases 2–15; no debe fallar por errores de shell/Python).

**Dependencias:** Tarea 1.2

---

## Fase 2: Migración de base de datos + modelos ORM

### Tarea 2.1: Escribir el test que falla para la migración de esquema (RED)

**Archivo:** `backend/tests/test_migration.py` (extender el archivo existente)
**Acción:** Añadir un test que, sobre una base de datos SQLite en memoria con el esquema anterior a la migración (usar `alembic upgrade` hasta la revisión `006_add_titulo_reunion` y sembrar una fila en `reuniones` con datos conocidos), ejecute `alembic upgrade head` y verifique: (a) la tabla `meetings` existe y contiene la misma fila con las columnas nuevas (`meet_link`, `process_state`, etc.) y los mismos valores; (b) la tabla `reuniones` ya no existe; (c) el valor de `process_state` fue traducido de `"en_cola"` a `"queued"`. Añadir un segundo test que ejecute `alembic downgrade -1` después y verifique que la tabla `reuniones` reaparece con la fila y el valor `"en_cola"` restaurado.

**Criterio de Completado:**
`cd backend && pytest tests/test_migration.py -v -k rename_schema_to_english` falla porque la revisión de migración aún no existe.

**Dependencias:** Fase 1

---

### Tarea 2.2: Crear el archivo de migración y renombrar tablas/columnas (GREEN, parte 1)

**Archivo:** `backend/alembic/versions/007_rename_schema_to_english.py` (crear, siguiendo la numeración secuencial existente)
**Acción:** Implementar `upgrade()` con `op.rename_table` y `op.alter_column` para las 11 tablas y todas sus columnas en español, exactamente según design.md § Componentes e Interfaces → "1. Esquema de base de datos (`backend/app/infra/models.py`)" — tabla de clases/tablas y tabla de columnas por tabla.

**Criterio de Completado:**
El archivo compila (`python3 -c "import ast; ast.parse(open('backend/alembic/versions/007_rename_schema_to_english.py').read())"` no lanza) y `revision`/`down_revision` apuntan correctamente a `006_add_titulo_reunion`.

**Dependencias:** Tarea 2.1

---

### Tarea 2.3: Traducir los literales de estado/evento almacenados (GREEN, parte 2)

**Archivo:** `backend/alembic/versions/007_rename_schema_to_english.py`
**Acción:** En `upgrade()`, después de los renames de tabla/columna, añadir sentencias `op.execute("UPDATE ... SET ... = '<inglés>' WHERE ... = '<español>'")` para cada literal de la tabla design.md § Componentes e Interfaces → "1. Esquema de base de datos" → "Literales de estado/evento" (estados y causas de `meetings.process_state`/`failure_cause`, estados y causas de `diarizations.diarization_state`/`failure_cause`, `meetings.origin`, `session_recordings.capture_origin`, `access_log.result`).

**Criterio de Completado:**
Revisión manual: cada fila de la tabla de literales en design.md tiene una sentencia `UPDATE` correspondiente en `upgrade()`.

**Dependencias:** Tarea 2.2

---

### Tarea 2.4: Renombrar constraints e índices (GREEN, parte 3)

**Archivo:** `backend/alembic/versions/007_rename_schema_to_english.py`
**Acción:** Añadir a `upgrade()` los renames de constraint listados en design.md (`uq_grabacion_reunion_id`→`uq_session_recording_meeting_id`, etc., seis en total) usando `op.execute("ALTER TABLE ... RENAME CONSTRAINT ... TO ...")` (Postgres) o el equivalente de `naming_convention` de SQLAlchemy si el dialecto de test es SQLite.

**Criterio de Completado:**
Los seis constraints de design.md § Componentes e Interfaces → "1." → "Constraints/índices" tienen su rename correspondiente en el archivo.

**Dependencias:** Tarea 2.3

---

### Tarea 2.5: Implementar `downgrade()` simétrico (GREEN, parte 4)

**Archivo:** `backend/alembic/versions/007_rename_schema_to_english.py`
**Acción:** Implementar `downgrade()` revirtiendo, en orden inverso, cada operación de `upgrade()`: primero los renames de constraint, luego los `UPDATE` de literales (inglés→español), luego los `alter_column`/`rename_table` (inglés→español).

**Criterio de Completado:**
`cd backend && pytest tests/test_migration.py -v -k rename_schema_to_english` pasa (Propiedad 1 de design.md — preservación de datos en upgrade y downgrade).

**Dependencias:** Tarea 2.4

---

### Tarea 2.6: Renombrar clases y columnas en `models.py`

**Archivo:** `backend/app/infra/models.py`
**Acción:** Renombrar las 11 clases, sus `__tablename__`, sus columnas y sus `relationship()`/`ForeignKey()`/`UniqueConstraint()` exactamente según design.md § Componentes e Interfaces → "1. Esquema de base de datos", incluyendo los `back_populates` cruzados (`Transcript.turns`, `SpeechTurn.transcript`, `Diarization.speakers`, `Diarization.assignments`, `SpeakerAssignment.diarization`, `SpeakerAssignment.speaker`). Traducir también los docstrings de cada clase.

**Criterio de Completado:**
`cd backend && mypy app/infra/models.py` pasa sin errores nuevos, y `python3 -c "from app.infra.models import Meeting, StateHistory, SessionRecording, Transcript, SpeechTurn, RecordingNotice, AccessLog, Diarization, Speaker, SpeakerAssignment, User"` no lanza `ImportError`.

**Dependencias:** Tarea 2.5

---

### Tarea 2.7: Actualizar fixtures y conftest de tests de infraestructura

**Archivo:** `backend/tests/conftest.py`, `backend/tests/infra/`
**Acción:** Actualizar cualquier fixture o helper (`_crear_reunion_en_db` y equivalentes) que construya instancias de los modelos ORM renombrados, usando los nuevos nombres de clase/columna. Renombrar el propio helper (`_crear_reunion_en_db`→`_create_meeting_in_db`).

**Criterio de Completado:**
`cd backend && pytest tests/infra -v` pasa.

**Dependencias:** Tarea 2.6

---

### Tarea 2.8: Ejecutar `make check-english` acotado a `infra/`

**Archivo:** N/A (verificación)
**Acción:** Ejecutar `python3 _tools/check_english_only.py backend/app/infra/models.py backend/alembic/versions/007_rename_schema_to_english.py`.

**Criterio de Completado:**
El script reporta 0 hallazgos para esos dos archivos (los `UPDATE ... = '<español>'` del downgrade son valores de cadena esperados, no identificadores — deben quedar excluidos por el patrón de identificador del script; si el script los marca como falso positivo, ajustar la Tarea 1.2 antes de continuar).

**Dependencias:** Tarea 2.6

---

## Fase 3: `packages/shared-types`

### Tarea 3.1: Reescribir `packages/shared-types/src/index.ts`

**Archivo:** `packages/shared-types/src/index.ts`
**Acción:** Reemplazar el contenido completo por el bloque de design.md § Modelos de Datos → "`packages/shared-types/src/index.ts` (estado final)": enums `ProcessState`, `FailureCause`, `MeetingOrigin`, `CaptureOrigin` con valores en inglés con guion bajo (corrigiendo el desajuste de espacios/tildes preexistente), e interfaces `Meeting`, `SessionRecording`, `Transcript`, `SpeechTurn` con campos en camelCase inglés.

**Criterio de Completado:**
`npm run typecheck -w @sauri/shared-types` pasa sin errores.

**Dependencias:** Fase 2

---

### Tarea 3.2: Actualizar tests de `shared-types` si existen

**Archivo:** `packages/shared-types/` (buscar `*.test.ts`)
**Acción:** Si existen tests que referencien los enums/interfaces antiguos, actualizarlos a los nombres y valores nuevos de la Tarea 3.1.

**Criterio de Completado:**
`npm run test -w @sauri/shared-types` pasa (o "no hay tests en este paquete" si efectivamente no existen — confirmar con `find packages/shared-types -name '*.test.ts'`).

**Dependencias:** Tarea 3.1

---

### Tarea 3.3: Verificar consumidores rotos por el cambio de tipo (aún no actualizados)

**Archivo:** N/A (verificación)
**Acción:** Ejecutar `npm run typecheck -w extension` y `npm run typecheck -w frontend`.

**Criterio de Completado:**
Ambos comandos fallan en este punto (esperado — `extension/` y `frontend/` todavía importan los nombres antiguos de `shared-types` y se corrigen en las Fases 11–15). Confirmar que los errores reportados son exclusivamente sobre símbolos de `@sauri/shared-types`, no otros errores preexistentes no relacionados.

**Dependencias:** Tarea 3.1

---

## Fase 4: `backend/app/auth/`

### Tarea 4.1: Renombrar `audit.py`

**Archivo:** `backend/app/auth/audit.py`
**Acción:** `registrar_acceso`→`record_access`; parámetros `usuario_id`→`user_id`, `recurso`→`resource`, `resultado`→`result`; literales `"permitido"`/`"denegado"`→`"allowed"`/`"denied"`. Actualizar la llamada a `RegistroDeAcceso`/`AccessLog` con los nuevos nombres de columna de la Fase 2.

**Criterio de Completado:**
`cd backend && mypy app/auth/audit.py` pasa.

**Dependencias:** Fase 2

---

### Tarea 4.2: Renombrar `authorization.py`

**Archivo:** `backend/app/auth/authorization.py`
**Acción:** `verificar_autorizacion`→`verify_authorization`; `requerir_comercial`→`require_sales`; toda referencia a `usuario.es_comercial`→`user.is_sales`; mensaje de error `"Acceso restringido a usuarios comerciales autorizados"`→`"Access restricted to authorized sales users"`.

**Criterio de Completado:**
`cd backend && mypy app/auth/authorization.py` pasa.

**Dependencias:** Tarea 4.1

---

### Tarea 4.3: Renombrar `dependencies.py`

**Archivo:** `backend/app/auth/dependencies.py`
**Acción:** `_bypass_activo`→`_bypass_active`; `obtener_usuario_actual`→`get_current_user`; referencias a `es_comercial`/`nombre`→`is_sales`/`name`.

**Criterio de Completado:**
`cd backend && mypy app/auth/dependencies.py` pasa.

**Dependencias:** Tarea 4.2

---

### Tarea 4.4: Renombrar `passwords.py`

**Archivo:** `backend/app/auth/passwords.py`
**Acción:** `_ALGORITMO`→`_ALGORITHM`; variables locales `sal`→`salt`, `derivado`→`derived`, `iteraciones`→`iterations`, `esperado`→`expected`.

**Criterio de Completado:**
`cd backend && pytest tests/auth -v -k password` pasa (verifica que el cambio de nombres locales no alteró el algoritmo).

**Dependencias:** Tarea 4.3

---

### Tarea 4.5: Renombrar `schemas.py`

**Archivo:** `backend/app/auth/schemas.py`
**Acción:** `UsuarioAutenticado`→`AuthenticatedUser`; campos `nombre`→`name`, `es_comercial`→`is_sales`.

**Criterio de Completado:**
`cd backend && mypy app/auth/schemas.py` pasa.

**Dependencias:** Tarea 4.4

---

### Tarea 4.6: Renombrar `seed.py`

**Archivo:** `backend/app/auth/seed.py`
**Acción:** `_password_semilla`→`_seed_password`; `sembrar_usuarios`→`seed_users`; `USUARIOS_SEMILLA`→`SEED_USERS`; campos de los datos semilla `nombre`→`name`, `es_comercial`→`is_sales`.

**Criterio de Completado:**
`cd backend && mypy app/auth/seed.py` pasa.

**Dependencias:** Tarea 4.5

---

### Tarea 4.7: Renombrar `token.py` y `router.py`

**Archivo:** `backend/app/auth/token.py`, `backend/app/auth/router.py`
**Acción:** En `token.py`: `crear_token`→`create_token`; parámetros `usuario_id`,`nombre`,`es_comercial`→`user_id`,`name`,`is_sales`; claims del JWT `nombre`,`es_comercial`→`name`,`is_sales` (claim `sub` sin cambio). En `router.py`: traducir el docstring que menciona `Servicio_De_Autenticacion`→`Authentication_Service`; la función `login` no cambia de nombre.

**Criterio de Completado:**
`cd backend && mypy app/auth/token.py app/auth/router.py` pasa.

**Dependencias:** Tarea 4.6

---

### Tarea 4.8: Actualizar tests de `auth/`

**Archivo:** `backend/tests/auth/`
**Acción:** Renombrar (`git mv`) y actualizar el contenido de los tests del módulo para usar los símbolos, campos y claims JWT nuevos de las Tareas 4.1–4.7. Renombrar `test_usuario_model.py`→`test_user_model.py` y `test_control_acceso_property.py`→`test_access_control_property.py`.

**Criterio de Completado:**
`cd backend && pytest tests/auth -v` pasa con el mismo número de tests que antes del rename.

**Dependencias:** Tarea 4.7

---

### Tarea 4.9: Verificar comportamiento sin cambios en tokens ya emitidos (Manejo de Errores)

**Archivo:** `backend/tests/auth/test_token.py` (o el archivo de test de `token.py` tras el rename de la Tarea 4.8)
**Acción:** Añadir un test que construya un JWT a mano con los claims antiguos (`es_comercial`, `nombre`) y verifique que `get_current_user` (o la función de decodificación) lo rechaza de forma estándar (401 / excepción de validación), documentando el comportamiento decidido en design.md § Manejo de Errores → "Token JWT firmado antes del despliegue".

**Criterio de Completado:**
`cd backend && pytest tests/auth -v -k old_token` pasa.

**Dependencias:** Tarea 4.8

---

### Tarea 4.10: `check-english` acotado a `auth/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py backend/app/auth/*.py backend/tests/auth/*.py`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 4.9

---

## Fase 5: `backend/app/ingestion/` (was `ingesta/`)

### Tarea 5.1: Renombrar el paquete

**Archivo:** `backend/app/ingesta/` → `backend/app/ingestion/`
**Acción:** `git mv backend/app/ingesta backend/app/ingestion`.

**Criterio de Completado:**
`ls backend/app/ingestion` lista `__init__.py`, `router.py`, `service.py`, `repository.py`, `schemas.py`; `backend/app/ingesta` ya no existe.

**Dependencias:** Fase 2, Fase 4

---

### Tarea 5.2: Renombrar `schemas.py`

**Archivo:** `backend/app/ingestion/schemas.py`
**Acción:** `DatosIngesta`→`IngestionData`; campos `reunion_id`→`meeting_id`, `clave_idempotencia`→`idempotency_key`, `origen_captura`→`capture_origin` (valores literales `"extension_chrome"`/`"bot_servidor"`→`"chrome_extension"`/`"server_bot"`), `duracion_segundos`→`duration_seconds`, `interrumpida`→`interrupted`, `notificacion_emitida_en`→`notice_issued_at`, `titulo`→`title`, `enlace_meet`→`meet_link`.

**Criterio de Completado:**
`cd backend && mypy app/ingestion/schemas.py` pasa.

**Dependencias:** Tarea 5.1

---

### Tarea 5.3: Renombrar `repository.py`

**Archivo:** `backend/app/ingestion/repository.py`
**Acción:** `GrabacionRepository`→`RecordingRepository`; `crear`→`create`, `obtener_por_reunion`→`get_by_meeting`, `existe_por_clave_idempotencia`→`exists_by_idempotency_key`.

**Criterio de Completado:**
`cd backend && mypy app/ingestion/repository.py` pasa.

**Dependencias:** Tarea 5.2

---

### Tarea 5.4: Renombrar `service.py`

**Archivo:** `backend/app/ingestion/service.py`
**Acción:** `procesar_ingesta`→`process_ingestion`; variables locales `existente`,`ahora`,`reunion`,`grabacion`,`notificacion`→`existing`,`now`,`meeting`,`recording`,`notice`; literal de estado `"grabando"`→`"recording"`, origen `"manual"` sin cambio de valor.

**Criterio de Completado:**
`cd backend && mypy app/ingestion/service.py` pasa.

**Dependencias:** Tarea 5.3

---

### Tarea 5.5: Renombrar `router.py`

**Archivo:** `backend/app/ingestion/router.py`
**Acción:** Tag `"ingesta"`→`"ingestion"`; ruta `/subir`→`/upload`; `_obtener_almacen`→`_get_object_store`, `_obtener_cola`→`_get_queue`, `subir_grabacion`→`upload_recording`; variables `datos_dict`,`datos_ingesta`,`almacen`,`cola`,`audio_content`,`audio_key`,`audio_ref`,`video_content`,`video_key`,`video_ref`,`grabacion`,`es_nueva`,`resultado_transicion`→`data_dict`,`ingestion_data`,`object_store`,`queue`,`audio_content`,`audio_key`,`audio_ref`,`video_content`,`video_key`,`video_ref`,`recording`,`is_new`,`transition_result`; literal `"duplicado_idempotente"`→`"idempotent_duplicate"`; mensaje de error `"Datos de ingesta inválidos: {exc}"`→`"Invalid ingestion data: {exc}"`.

**Criterio de Completado:**
`cd backend && mypy app/ingestion/router.py` pasa.

**Dependencias:** Tarea 5.4

---

### Tarea 5.6: Actualizar import en `main.py` y tests de `ingestion/`

**Archivo:** `backend/app/main.py`, `backend/tests/ingesta/` → `backend/tests/ingestion/`
**Acción:** En `main.py`, cambiar `from app.ingesta.router import router as ingesta_router` por `from app.ingestion.router import router as ingestion_router` y `app.include_router(ingesta_router)` por `app.include_router(ingestion_router)`. `git mv backend/tests/ingesta backend/tests/ingestion` y actualizar el contenido de los tests a los nuevos símbolos/rutas/campos.

**Criterio de Completado:**
`cd backend && pytest tests/ingestion -v` pasa.

**Dependencias:** Tarea 5.5

---

### Tarea 5.7: `check-english` acotado a `ingestion/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py backend/app/ingestion/*.py backend/tests/ingestion/*.py`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 5.6

---

## Fase 6: `backend/app/meetings/` (was `reuniones/`)

### Tarea 6.1: Renombrar el paquete

**Archivo:** `backend/app/reuniones/` → `backend/app/meetings/`
**Acción:** `git mv backend/app/reuniones backend/app/meetings`.

**Criterio de Completado:**
`ls backend/app/meetings` lista `__init__.py`, `router.py`, `service.py`, `repository.py`, `schemas.py`, `state_machine.py`; `backend/app/reuniones` ya no existe.

**Dependencias:** Fase 2, Fase 4, Fase 5

---

### Tarea 6.2: Renombrar `state_machine.py`

**Archivo:** `backend/app/meetings/state_machine.py`
**Acción:** Por design.md § Componentes e Interfaces → "2. `meetings/`": `ESTADOS`→`STATES`, `ESTADOS_TERMINALES`→`TERMINAL_STATES`, `CAUSAS_FALLO_VALIDAS`→`VALID_FAILURE_CAUSES`, `TRANSICIONES_VALIDAS`→`VALID_TRANSITIONS`, `EVENTO_A_CAUSA`→`EVENT_TO_CAUSE`; dataclass `ResultadoTransicion`(`exitosa`,`nuevo_estado`,`causa_fallo`)→`TransitionResult`(`successful`,`new_state`,`failure_cause`); `aplicar_evento`→`apply_event`. Traducir todos los literales de estado/evento/causa según design.md § "Literales de estado/evento".

**Criterio de Completado:**
`cd backend && mypy app/meetings/state_machine.py` pasa.

**Dependencias:** Tarea 6.1

---

### Tarea 6.3: Property test — equivalencia de la máquina de estados (Propiedad 2)

**Archivo:** `backend/tests/meetings/test_state_machine_property.py` (renombrar desde `backend/tests/reuniones/test_state_machine_property.py`)
**Acción:** Añadir (junto a los tests existentes ya renombrados) un test basado en hypothesis que, para todo par (estado, evento) válido bajo los literales antiguos, compare el resultado de `apply_event` con literales nuevos contra el resultado que producía `aplicar_evento` con literales antiguos bajo el mapeo de design.md, verificando isomorfismo (mismo éxito/fracaso, mismo estado siguiente bajo el mapeo).

**Criterio de Completado:**
`cd backend && pytest tests/meetings/test_state_machine_property.py -v` pasa con `max_examples=100` (perfil `sauri` de `conftest.py`).

**Dependencias:** Tarea 6.2

---

### Tarea 6.4: Renombrar `repository.py`

**Archivo:** `backend/app/meetings/repository.py`
**Acción:** `ReunionRepository`→`MeetingRepository`; `crear`→`create`, `obtener_por_id`→`get_by_id`, `actualizar_estado`→`update_state`.

**Criterio de Completado:**
`cd backend && mypy app/meetings/repository.py` pasa.

**Dependencias:** Tarea 6.2

---

### Tarea 6.5: Renombrar `schemas.py`

**Archivo:** `backend/app/meetings/schemas.py`
**Acción:** `_validar_enlace_meet`→`_validate_meet_link`; `EntradaReunionEnlace`→`LinkMeetingInput`, `EntradaReunionCalendario`→`CalendarMeetingInput`, `EntradaReunionManual`→`ManualMeetingInput`, tipo `EntradaReunion`→`MeetingInput`; método `validar_enlace`→`validate_link`; campos `enlace_meet`→`meet_link`, `id_invitacion_calendario`→`calendar_invite_id`, `hora_inicio_programada`→`scheduled_start_time`; mensaje de error `"El enlace debe comenzar con 'https://meet.google.com/'"`→`"The link must start with 'https://meet.google.com/'"`.

**Criterio de Completado:**
`cd backend && mypy app/meetings/schemas.py` pasa.

**Dependencias:** Tarea 6.4

---

### Tarea 6.6: Renombrar `service.py`

**Archivo:** `backend/app/meetings/service.py`
**Acción:** `registrar_transicion`→`record_transition`, `registrar_reunion`→`register_meeting`, `consultar_reunion`→`get_meeting`, `renombrar_reunion`→`rename_meeting`, `eliminar_reunion`→`delete_meeting`, `solicitar_union`→`request_join`, `programar_union_por_calendario`→`schedule_join_by_calendar`; variables locales `resultado`,`reunion`,`evento`,`historial`,`ahora`,`reunion_id`,`modelo`,`origen`,`entrada`,`datos_validacion`,`nuevo_titulo`,`almacen`,`grabacion`,`cola`→`result`,`meeting`,`event`,`history`,`now`,`meeting_id`,`model`,`origin`,`input`,`validation_data`,`new_title`,`object_store`,`recording`,`queue`; literales de origen `"invitacion_calendario"`/`"enlace"`/`"manual"`→`"calendar_invite"`/`"link"`/`"manual"`.

**Criterio de Completado:**
`cd backend && mypy app/meetings/service.py` pasa.

**Dependencias:** Tarea 6.5

---

### Tarea 6.7: Renombrar `router.py` y actualizar `main.py`

**Archivo:** `backend/app/meetings/router.py`, `backend/app/main.py`
**Acción:** En `router.py`: tag `"reuniones"`→`"meetings"`; `_obtener_cola`→`_get_queue`, `_obtener_almacen`→`_get_object_store`, `crear_reunion`→`create_meeting`, `listar_reuniones`→`list_meetings`, `renombrar_reunion_endpoint`→`rename_meeting_endpoint`, `eliminar_reunion_endpoint`→`delete_meeting_endpoint`, `obtener_reunion`→`get_meeting`, `solicitar_union_endpoint`→`request_join_endpoint`, `obtener_transcripcion`→`get_transcript`, `obtener_diarizacion`→`get_diarization`; `EntradaRenombrar`→`RenameInput` (campo `titulo`→`title`); rutas `/solicitar-union`→`/request-join`, `/transcripcion`→`/transcript`, `/diarizacion`→`/diarization`; mensaje de error `"Reunión no encontrada: {id}"`→`"Meeting not found: {id}"`. En `main.py`: `from app.reuniones.router import router as reuniones_router`→`from app.meetings.router import router as meetings_router`, `app.include_router(reuniones_router)`→`app.include_router(meetings_router)`.

**Criterio de Completado:**
`cd backend && mypy app/meetings/router.py app/main.py` pasa.

**Dependencias:** Tarea 6.6

---

### Tarea 6.8: Actualizar tests de `meetings/` y `check-english`

**Archivo:** `backend/tests/reuniones/` → `backend/tests/meetings/`
**Acción:** `git mv backend/tests/reuniones backend/tests/meetings`; actualizar el contenido de todos los archivos (incluyendo `test_disparadores_union.py`→`test_join_triggers.py`, `test_historial_titulo.py`→`test_title_history.py`, `test_consultar_reunion_property.py`→`test_get_meeting_property.py`, `test_registrar_reunion_property.py`→`test_register_meeting_property.py`) a los símbolos/rutas/campos nuevos. Ejecutar `python3 _tools/check_english_only.py backend/app/meetings/*.py backend/tests/meetings/*.py`.

**Criterio de Completado:**
`cd backend && pytest tests/meetings -v` pasa; `check_english_only.py` reporta 0 hallazgos.

**Dependencias:** Tarea 6.7, Tarea 6.3

---

## Fase 7: `backend/app/transcription/` (was `transcripcion/`)

### Tarea 7.1: Renombrar el paquete

**Archivo:** `backend/app/transcripcion/` → `backend/app/transcription/`
**Acción:** `git mv backend/app/transcripcion backend/app/transcription`, y dentro: `git mv backend/app/transcription/motor_asr.py backend/app/transcription/asr_engine.py`, `git mv backend/app/transcription/proveedor_local.py backend/app/transcription/local_provider.py`, `git mv backend/app/transcription/proveedor_nube.py backend/app/transcription/cloud_provider.py`.

**Criterio de Completado:**
`ls backend/app/transcription` lista `asr_engine.py`, `local_provider.py`, `cloud_provider.py`, `factory.py`, `repository.py`, `worker.py`, `__init__.py`.

**Dependencias:** Fase 6

---

### Tarea 7.2: Renombrar `asr_engine.py`

**Archivo:** `backend/app/transcription/asr_engine.py`
**Acción:** `MotorASR`→`ASREngine`; `OpcionesTranscripcion`(`idioma_prioritario`)→`TranscriptionOptions`(`preferred_language`); `SegmentoTranscripcion`(`texto`,`inicio_ms`,`fin_ms`)→`TranscriptionSegment`(`text`,`start_ms`,`end_ms`); `ResultadoTranscripcion`(`segmentos`,`idioma`,`soporta_turnos`)→`TranscriptionResult`(`segments`,`language`,`supports_turns`); `CapacidadesASR`(`soporta_turnos`,`es_local`)→`ASRCapabilities`(`supports_turns`,`is_local`); métodos abstractos `transcribir`/`capacidades`→`transcribe`/`capabilities`.

**Criterio de Completado:**
`cd backend && mypy app/transcription/asr_engine.py` pasa.

**Dependencias:** Tarea 7.1

---

### Tarea 7.3: Renombrar `factory.py`

**Archivo:** `backend/app/transcription/factory.py`
**Acción:** `crear_motor_asr`→`create_asr_engine`; actualizar el import de `MotorASR`→`ASREngine` y de `ProveedorLocal`/`ProveedorNube`→`LocalProvider`/`CloudProvider`. Los env vars `ASR_PROVIDER`/`ASR_LOCAL_URL` no cambian.

**Criterio de Completado:**
`cd backend && mypy app/transcription/factory.py` pasa.

**Dependencias:** Tarea 7.2

---

### Tarea 7.4: Renombrar `local_provider.py` y `cloud_provider.py`

**Archivo:** `backend/app/transcription/local_provider.py`, `backend/app/transcription/cloud_provider.py`
**Acción:** `ProveedorLocal`→`LocalProvider` (implementa `ASREngine`). `ErrorServicioExterno`→`ExternalServiceError`; `ProveedorNube`→`CloudProvider`; `_parsear_y_validar_respuesta`→`_parse_and_validate_response`; env vars `ASR_CLOUD_API_KEY`/`ASR_CLOUD_ENDPOINT` sin cambio.

**Criterio de Completado:**
`cd backend && mypy app/transcription/local_provider.py app/transcription/cloud_provider.py` pasa.

**Dependencias:** Tarea 7.3

---

### Tarea 7.5: Renombrar `repository.py`

**Archivo:** `backend/app/transcription/repository.py`
**Acción:** `TranscripcionRepository`→`TranscriptRepository`; `crear`→`create`, `obtener_por_reunion`→`get_by_meeting`.

**Criterio de Completado:**
`cd backend && mypy app/transcription/repository.py` pasa.

**Dependencias:** Tarea 7.4

---

### Tarea 7.6: Renombrar `worker.py`

**Archivo:** `backend/app/transcription/worker.py`
**Acción:** `_procesar_transcripcion`→`_process_transcription`, `iniciar_worker`→`start_worker`; topic `"transcribir"`→`"transcribe"` (el topic `"diarizar"`/`"diarize"` referenciado aquí se corrige en la Fase 8, mantener sincronizado); variables `manejador`,`motor`,`opciones`,`resultado`,`transcripcion_creada`→`handler`,`engine`,`options`,`result`,`transcript_created`; literales de evento `"grabacion_subida"`,`"transcripcion_completada"`,`"fallo_motor"`→`"recording_uploaded"`,`"transcription_completed"`,`"engine_failed"`.

**Criterio de Completado:**
`cd backend && mypy app/transcription/worker.py` pasa.

**Dependencias:** Tarea 7.5

---

### Tarea 7.7: Actualizar `worker.py` de nivel superior (import de transcripción)

**Archivo:** `backend/app/worker.py`
**Acción:** Actualizar los imports de `app.transcripcion.worker`→`app.transcription.worker` y de `iniciar_worker`→`start_worker` (con el alias que corresponda para distinguirlo del `start_worker` de diarización, p. ej. `start_transcription_worker as start_worker` en el import, o alias en el import como ya hace el código actual).

**Criterio de Completado:**
`cd backend && mypy app/worker.py` pasa (los imports de diarización/retención se completan en las Fases 8 y 9; se acepta que `worker.py` quede en un estado intermedio verificado nuevamente en la Fase 10).

**Dependencias:** Tarea 7.6

---

### Tarea 7.8: Actualizar tests de `transcription/`

**Archivo:** `backend/tests/transcripcion/` → `backend/tests/transcription/`
**Acción:** `git mv backend/tests/transcripcion backend/tests/transcription`; actualizar contenido de `test_factory.py`, `test_proveedor_local.py`→`test_local_provider.py`, `test_proveedor_nube.py`→`test_cloud_provider.py`, `test_factory_property.py`, `test_proveedor_local_property.py`→`test_local_provider_property.py`, `test_proveedor_nube_property.py`→`test_cloud_provider_property.py`, `test_meeting_capture_property.py`, y cualquier otro archivo del módulo, a los símbolos nuevos.

**Criterio de Completado:**
`cd backend && pytest tests/transcription -v` pasa.

**Dependencias:** Tarea 7.7

---

### Tarea 7.9: `check-english` acotado a `transcription/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py backend/app/transcription/*.py backend/tests/transcription/*.py`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 7.8

---

## Fase 8: `backend/app/diarization/` (was `diarizacion/`)

### Tarea 8.1: Renombrar el paquete

**Archivo:** `backend/app/diarizacion/` → `backend/app/diarization/`
**Acción:** `git mv backend/app/diarizacion backend/app/diarization`, y dentro: `git mv .../asignacion.py .../assignment.py`, `git mv .../estado.py .../state.py`, `git mv .../etiquetado.py .../labeling.py`, `git mv .../motor_diarizacion.py .../diarization_engine.py`, `git mv .../proveedor_local.py .../local_provider.py`, `git mv .../proveedor_nube.py .../cloud_provider.py`.

**Criterio de Completado:**
`ls backend/app/diarization` lista `assignment.py`, `state.py`, `labeling.py`, `diarization_engine.py`, `local_provider.py`, `cloud_provider.py`, `factory.py`, `repository.py`, `worker.py`, `__init__.py`.

**Dependencias:** Fase 7

---

### Tarea 8.2: Renombrar `diarization_engine.py`

**Archivo:** `backend/app/diarization/diarization_engine.py`
**Acción:** `MotorDiarizacion`→`DiarizationEngine`; `OpcionesDiarizacion`(`duracion_ms`)→`DiarizationOptions`(`duration_ms`); `SegmentoDeHablante`(`etiqueta_cruda`,`inicio_ms`,`fin_ms`)→`SpeakerSegment`(`raw_label`,`start_ms`,`end_ms`); `ResultadoDiarizacion`(`segmentos`,`num_hablantes`)→`DiarizationResult`(`segments`,`speaker_count`); `CapacidadesDiarizacion`(`es_local`,`nombre_proveedor`)→`DiarizationCapabilities`(`is_local`,`provider_name`); métodos abstractos `diarizar`/`capacidades`→`diarize`/`capabilities`.

**Criterio de Completado:**
`cd backend && mypy app/diarization/diarization_engine.py` pasa.

**Dependencias:** Tarea 8.1

---

### Tarea 8.3: Renombrar `state.py`

**Archivo:** `backend/app/diarization/state.py`
**Acción:** `aplicar_evento_diarizacion`→`apply_diarization_event`; `ResultadoTransicionDiarizacion`→`DiarizationTransitionResult`; estados `pendiente`/`en_proceso`/`completada`/`fallida`→`pending`/`in_progress`/`completed`/`failed`; eventos `iniciar_proceso`/`diarizacion_completada`/`fallo_motor`→`start_process`/`diarization_completed`/`engine_failed`; causa `fallo_del_motor`→`engine_failure`.

**Criterio de Completado:**
`cd backend && mypy app/diarization/state.py` pasa.

**Dependencias:** Tarea 8.2

---

### Tarea 8.4: Property test — equivalencia de la máquina de estados de diarización (parte de Propiedad 2)

**Archivo:** `backend/tests/diarizacion/test_estado_property.py` → `backend/tests/diarization/test_state_property.py`
**Acción:** Igual que la Tarea 6.3 pero para `apply_diarization_event`: comparar contra el comportamiento de `aplicar_evento_diarizacion` bajo el mapeo de estados/eventos de la Tarea 8.3.

**Criterio de Completado:**
`cd backend && pytest tests/diarization/test_state_property.py -v` pasa con `max_examples=100`.

**Dependencias:** Tarea 8.3

---

### Tarea 8.5: Renombrar `assignment.py`

**Archivo:** `backend/app/diarization/assignment.py`
**Acción:** `asignar_turnos`→`assign_turns`; variables `segmentos_por_etiqueta`,`mejor_hablante`,`mejor_solape`→`segments_by_label`,`best_speaker`,`best_overlap`.

**Criterio de Completado:**
`cd backend && mypy app/diarization/assignment.py` pasa.

**Dependencias:** Tarea 8.2

---

### Tarea 8.6: Property test — equivalencia de `assign_turns` (Propiedad 3)

**Archivo:** `backend/tests/diarizacion/test_asignacion_property.py` → `backend/tests/diarization/test_assignment_property.py`
**Acción:** Verificar que, para entradas equivalentes (turnos/segmentos/hablantes con los nuevos nombres de campo pero mismos valores), `assign_turns` asigna el mismo `speaker_id` por turno que `asignar_turnos` asignaba antes del rename para la entrada español-equivalente.

**Criterio de Completado:**
`cd backend && pytest tests/diarization/test_assignment_property.py -v` pasa.

**Dependencias:** Tarea 8.5

---

### Tarea 8.7: Renombrar `labeling.py`

**Archivo:** `backend/app/diarization/labeling.py`
**Acción:** Dataclass `Hablante`(`etiqueta_cruda`,`etiqueta`,`orden`)→`Speaker`(`raw_label`,`label`,`sequence`); `etiquetar_hablantes`→`label_speakers`; literal de formato `f"Hablante {i}"`→`f"Speaker {i}"`.

**Criterio de Completado:**
`cd backend && mypy app/diarization/labeling.py` pasa.

**Dependencias:** Tarea 8.2

---

### Tarea 8.8: Renombrar `factory.py`

**Archivo:** `backend/app/diarization/factory.py`
**Acción:** `crear_motor_diarizacion`→`create_diarization_engine`; actualizar imports de `MotorDiarizacion`/`ProveedorLocal`/`ProveedorNube`→`DiarizationEngine`/`LocalProvider`/`CloudProvider`. Env vars `DIARIZATION_PROVIDER`/`DIARIZATION_LOCAL_URL` sin cambio.

**Criterio de Completado:**
`cd backend && mypy app/diarization/factory.py` pasa.

**Dependencias:** Tarea 8.2

---

### Tarea 8.9: Renombrar `local_provider.py` y `cloud_provider.py`

**Archivo:** `backend/app/diarization/local_provider.py`, `backend/app/diarization/cloud_provider.py`
**Acción:** `ProveedorLocal`→`LocalProvider` (implementa `DiarizationEngine`), literal `nombre_proveedor` `"diar-engine-local"` sin cambio de valor. `ErrorServicioExterno`→`ExternalServiceError`, `ProveedorNube`→`CloudProvider`, `_parsear_y_validar_respuesta`→`_parse_and_validate_response`, literal `nombre_proveedor` `"diarization-cloud"` sin cambio de valor. Env vars `DIARIZATION_CLOUD_API_KEY`/`DIARIZATION_CLOUD_ENDPOINT` sin cambio.

**Criterio de Completado:**
`cd backend && mypy app/diarization/local_provider.py app/diarization/cloud_provider.py` pasa.

**Dependencias:** Tarea 8.8

---

### Tarea 8.10: Renombrar `repository.py` y `worker.py`

**Archivo:** `backend/app/diarization/repository.py`, `backend/app/diarization/worker.py`
**Acción:** En `repository.py`: `DiarizacionRepository`→`DiarizationRepository`; `crear`→`create`, `obtener_por_reunion`→`get_by_meeting`. En `worker.py`: `_procesar_diarizacion`→`_process_diarization`, `iniciar_worker`→`start_worker`; topic `"diarizar"`→`"diarize"`; variables `hablantes_dominio`,`asignaciones_dominio`,`hablantes_orm`,`hablante_id_por_etiqueta`,`asignaciones_orm`,`ahora_utc`→`domain_speakers`,`domain_assignments`,`orm_speakers`,`speaker_id_by_label`,`orm_assignments`,`utc_now`.

**Criterio de Completado:**
`cd backend && mypy app/diarization/repository.py app/diarization/worker.py` pasa.

**Dependencias:** Tarea 8.9, Tarea 8.7

---

### Tarea 8.11: Actualizar `worker.py` de nivel superior (import de diarización) y tests de `diarization/`

**Archivo:** `backend/app/worker.py`, `backend/tests/diarizacion/` → `backend/tests/diarization/`
**Acción:** En `worker.py`, completar el import de `app.diarizacion.worker`→`app.diarization.worker` y `iniciar_worker_diarizacion`→`start_diarization_worker` (con el alias que ya usaba el código para distinguirlo del worker de transcripción). `git mv backend/tests/diarizacion backend/tests/diarization`, renombrando también `test_etiquetado_property.py`→`test_labeling_property.py`, `test_motor_diarizacion_property.py`→`test_diarization_engine_property.py`, `test_diarizacion_endpoint.py`→`test_diarization_endpoint.py` (ya en inglés salvo contenido), `test_adaptadores_conformidad_property.py`→`test_adapters_conformance_property.py`, `test_transcripcion_turno_id.py`→`test_transcript_turn_id.py`, actualizando el contenido de todos a los símbolos nuevos.

**Criterio de Completado:**
`cd backend && mypy app/worker.py && pytest tests/diarization -v` pasa.

**Dependencias:** Tarea 8.10, Tarea 8.6, Tarea 8.4

---

### Tarea 8.12: `check-english` acotado a `diarization/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py backend/app/diarization/*.py backend/tests/diarization/*.py`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 8.11

---

## Fase 9: `backend/app/retention/` (was `retencion/`)

### Tarea 9.1: Renombrar el paquete

**Archivo:** `backend/app/retencion/` → `backend/app/retention/`
**Acción:** `git mv backend/app/retencion backend/app/retention`; dentro, `git mv .../expiracion.py .../expiration.py`.

**Criterio de Completado:**
`ls backend/app/retention` lista `config.py`, `expiration.py`, `worker.py`, `__init__.py`.

**Dependencias:** Fase 2

---

### Tarea 9.2: Renombrar `config.py` y `expiration.py`

**Archivo:** `backend/app/retention/config.py`, `backend/app/retention/expiration.py`
**Acción:** `obtener_periodo_retencion`→`get_retention_period` (env var `RETENTION_DAYS` sin cambio). `calcular_expiracion`→`calculate_expiration`; `aplicar_retencion`→`apply_retention`.

**Criterio de Completado:**
`cd backend && mypy app/retention/config.py app/retention/expiration.py` pasa.

**Dependencias:** Tarea 9.1

---

### Tarea 9.3: Renombrar `worker.py`

**Archivo:** `backend/app/retention/worker.py`
**Acción:** `ejecutar_borrado_retencion`→`run_retention_deletion`; `iniciar_worker_retencion`→`start_retention_worker`; variables `grabaciones_borradas`,`transcripciones_borradas`,`grabaciones_expiradas`,`transcripciones_independientes`→`deleted_recordings`,`deleted_transcripts`,`expired_recordings`,`orphan_transcripts`.

**Criterio de Completado:**
`cd backend && mypy app/retention/worker.py` pasa.

**Dependencias:** Tarea 9.2

---

### Tarea 9.4: Actualizar tests de `retention/`

**Archivo:** `backend/tests/retencion/` → `backend/tests/retention/`
**Acción:** `git mv backend/tests/retencion backend/tests/retention`; renombrar y actualizar `test_borrado_retencion_property.py`→`test_retention_deletion_property.py`, `test_expiracion_property.py`→`test_expiration_property.py`, y demás archivos, a los símbolos nuevos.

**Criterio de Completado:**
`cd backend && pytest tests/retention -v` pasa.

**Dependencias:** Tarea 9.3

---

### Tarea 9.5: `check-english` acotado a `retention/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py backend/app/retention/*.py backend/tests/retention/*.py`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 9.4

---

## Fase 10: `backend/app/infra/` (colas, almacenamiento) + `worker.py` de nivel superior

### Tarea 10.1: Renombrar `queue.py`

**Archivo:** `backend/app/infra/queue.py`
**Acción:** `ColaDeTrabajos`(ABC)→`JobQueue`; `publicar`/`suscribir`/`conectar`/`desconectar`→`publish`/`subscribe`/`connect`/`disconnect`; parámetros `tema`,`mensaje`,`manejador`→`topic`,`message`,`handler`; `crear_cola_de_trabajos`→`create_job_queue`.

**Criterio de Completado:**
`cd backend && mypy app/infra/queue.py` pasa.

**Dependencias:** Fase 8, Fase 9

---

### Tarea 10.2: Renombrar `queue_rabbitmq.py`

**Archivo:** `backend/app/infra/queue_rabbitmq.py`
**Acción:** `ColaDeRabbitMQ`→`RabbitMQJobQueue`; `_leer_max_retries`→`_read_max_retries`; `_contar_reintentos`→`_count_retries`; `_leer_dlx_exchange`→`_read_dlx_exchange`; header `x-sauri-reintentos`→`x-sauri-retries`; `_TEMA_A_ENV_RETRIES`→`_TOPIC_TO_ENV_RETRIES` con claves `"transcribir"`/`"diarizar"`→`"transcribe"`/`"diarize"`. Env vars `ASR_MAX_RETRIES`,`DIARIZATION_MAX_RETRIES`,`QUEUE_DLX_EXCHANGE` sin cambio.

**Criterio de Completado:**
`cd backend && mypy app/infra/queue_rabbitmq.py` pasa.

**Dependencias:** Tarea 10.1

---

### Tarea 10.3: Renombrar `object_store.py` y `object_store_s3.py`

**Archivo:** `backend/app/infra/object_store.py`, `backend/app/infra/object_store_s3.py`
**Acción:** `AlmacenDeObjetos`(ABC)→`ObjectStore`; `guardar`/`obtener`/`eliminar`/`url_temporal_de_lectura`→`save`/`get`/`delete`/`temporary_read_url`; parámetros `clave`,`contenido`,`referencia`→`key`,`content`,`reference`; `crear_almacen_de_objetos`→`create_object_store`. `AlmacenDeObjetosS3`→`S3ObjectStore`.

**Criterio de Completado:**
`cd backend && mypy app/infra/object_store.py app/infra/object_store_s3.py` pasa.

**Dependencias:** Tarea 10.1

---

### Tarea 10.4: Limpiar duplicados en `database.py`

**Archivo:** `backend/app/infra/database.py`
**Acción:** Eliminar las funciones duplicadas en español `crear_engine`/`crear_session`, dejando únicamente `create_engine`/`create_session_factory` (ya existentes en inglés). Actualizar cualquier caller que aún use los nombres en español.

**Criterio de Completado:**
`cd backend && grep -rn "crear_engine\|crear_session" backend/app/` no devuelve resultados.

**Dependencias:** Tarea 10.3

---

### Tarea 10.5: Actualizar `worker.py` de nivel superior (imports finales)

**Archivo:** `backend/app/worker.py`
**Acción:** Completar los imports restantes: `crear_almacen_de_objetos`→`create_object_store`, `crear_cola_de_trabajos`→`create_job_queue`; variables `cola`,`almacen`,`retencion_task`→`queue`,`object_store`,`retention_task`. Traducir los comentarios ("Iniciando worker de sauri..."→"Starting sauri worker...", "Señal de shutdown recibida..."→"Shutdown signal received...").

**Criterio de Completado:**
`cd backend && mypy app/worker.py` pasa.

**Dependencias:** Tarea 10.2, Tarea 10.4

---

### Tarea 10.6: Actualizar tests de `infra/` (colas y almacenamiento)

**Archivo:** `backend/tests/infra/`, `backend/tests/test_queue.py`, `backend/tests/test_worker.py`
**Acción:** Actualizar el contenido de los tests para usar `JobQueue`, `RabbitMQJobQueue`, `ObjectStore`, `S3ObjectStore` y los nuevos nombres de método/parámetro.

**Criterio de Completado:**
`cd backend && pytest tests/infra tests/test_queue.py tests/test_worker.py -v` pasa.

**Dependencias:** Tarea 10.5

---

### Tarea 10.7: Verificación completa del backend

**Archivo:** N/A (verificación)
**Acción:** Ejecutar la suite completa de backend y el chequeo de idioma sobre todo `backend/`.

**Criterio de Completado:**
`cd backend && pytest -v` pasa en su totalidad; `cd backend && mypy app` pasa sin errores; `python3 _tools/check_english_only.py $(git ls-files 'backend/**/*.py')` reporta 0 hallazgos.

**Dependencias:** Tarea 10.6, Fase 3

---

## Fase 11: `extension/src/core/`

### Tarea 11.1: Renombrar `types.ts`

**Archivo:** `extension/src/core/types.ts`
**Acción:** Traducir todos los tipos y sus campos según design.md § Componentes e Interfaces → "10. `extension/src/core/`" → tabla `types.ts`: `EstadoDeCaptura`→`CaptureState`, `EventoCaptura`→`CaptureEvent`, `EstadoDeVista`→`ViewState`, `SolicitudRemota`→`RemoteRequest`, `NotaDTO`→`NoteDTO`, `TarjetaDeNota`→`NoteCard`, `FiltroDeNotas`→`NotesFilter`, `TurnoDeHablaDTO`→`SpeechTurnDTO`, `TranscripcionDTO`→`TranscriptDTO`, `HablanteDTO`→`SpeakerDTO`, `AsignacionDeHablanteDTO`→`SpeakerAssignmentDTO`, `DiarizacionDTO`→`DiarizationDTO`, `IntervencionDTO`→`InterventionDTO`, `EntradaTiempoDeHabla`→`SpeakingTimeEntry`, `IntentoDeAutenticacion`→`AuthAttempt`, con todos sus campos traducidos (`reunionId`→`meetingId`, `titulo`→`title`, `estadoProceso`→`processState`, etc., según la misma tabla).

**Criterio de Completado:**
`npm run typecheck -w extension` sigue reportando errores (esperado — los consumidores de estos tipos se actualizan en las tareas siguientes de esta fase), pero ninguno de esos errores se origina en `types.ts` mismo.

**Dependencias:** Fase 3, Fase 6

---

### Tarea 11.2: Renombrar `authBloqueo.ts`→`authLock.ts`

**Archivo:** `extension/src/core/authBloqueo.ts` → `extension/src/core/authLock.ts`
**Acción:** `git mv`; `MAX_FALLOS_CONSECUTIVOS`→`MAX_CONSECUTIVE_FAILURES`, `VENTANA_BLOQUEO_MS`→`LOCKOUT_WINDOW_MS`, `estaBloqueado`→`isLocked`; usar el tipo `AuthAttempt` de la Tarea 11.1.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `authLock.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.3: Renombrar `busqueda.ts`→`search.ts`

**Archivo:** `extension/src/core/busqueda.ts` → `extension/src/core/search.ts`
**Acción:** `git mv`; `LIMITE_BUSQUEDA_NOTAS`→`NOTES_SEARCH_LIMIT`, `LIMITE_BUSQUEDA_TRANSCRIPCION`→`TRANSCRIPT_SEARCH_LIMIT`, `filtrarNotas`→`filterNotes`, `coincidenciasDeTranscripcion`→`transcriptMatches`, `ResultadoBusquedaTranscripcion`(`intervenciones`,`turnoIdsCoincidentes`,`primeraCoincidenciaId`)→`TranscriptSearchResult`(`interventions`,`matchingTurnIds`,`firstMatchId`), `normalizar`→`normalize`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `search.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.4: Renombrar `captura.ts`→`capture.ts`

**Archivo:** `extension/src/core/captura.ts` → `extension/src/core/capture.ts`
**Acción:** `git mv`; `aplicarEventoCaptura`→`applyCaptureEvent`, `botonNuevaNotaHabilitado`→`newNoteButtonEnabled`, `TRANSICIONES`→`TRANSITIONS`; estados `inactiva`/`grabando`/`deteniendo`→`idle`/`recording`/`stopping`; eventos `iniciar`/`detener`/`finalizada`→`start`/`stop`/`finished`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `capture.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.5: Renombrar `hablantes.ts`→`speakers.ts`

**Archivo:** `extension/src/core/hablantes.ts` → `extension/src/core/speakers.ts`
**Acción:** `git mv`; `PALETA_AVATAR`→`AVATAR_PALETTE` (mover/consolidar con `core/design/tokens.ts` según la Tarea 11.9 si aplica); `inicialesDeEtiqueta`→`labelInitials`, `colorDeAvatar`→`avatarColor`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `speakers.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.6: Renombrar `intervenciones.ts`→`interventions.ts`

**Archivo:** `extension/src/core/intervenciones.ts` → `extension/src/core/interventions.ts`
**Acción:** `git mv`; `ETIQUETA_HABLANTE_NO_IDENTIFICADO`→`UNIDENTIFIED_SPEAKER_LABEL` (valor `"Hablante no identificado"`→`"Unidentified speaker"`), `atribuirHablante`→`attributeSpeaker`, `mapearIntervenciones`→`mapInterventions`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `interventions.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.7: Renombrar `notas.ts`→`notes.ts`

**Archivo:** `extension/src/core/notas.ts` → `extension/src/core/notes.ts`
**Acción:** `git mv`; `PLACEHOLDER_TITULO`→`TITLE_PLACEHOLDER` (valor `"Nota sin título"`→`"Untitled note"`), `tituloParaMostrar`→`displayTitle`, `formatearFechaNota`→`formatNoteDate`, `proyectarTarjetas`→`projectCards`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `notes.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.8: Renombrar `orden.ts`→`order.ts` y `tiempo.ts`→`time.ts`

**Archivo:** `extension/src/core/orden.ts` → `extension/src/core/order.ts`; `extension/src/core/tiempo.ts` → `extension/src/core/time.ts`
**Acción:** `git mv` ambos; en `order.ts`: `ordenarNotas`→`sortNotes`, `ordenarIntervenciones`→`sortInterventions`, `ordenarTiempoDeHabla`→`sortSpeakingTime`. En `time.ts`: `PLACEHOLDER_NO_DISPONIBLE`→`NOT_AVAILABLE_PLACEHOLDER`, `UNA_HORA_MS`→`ONE_HOUR_MS`, `formatearMarcaDeTiempo`→`formatTimestamp` (`pad2` sin cambio).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `order.ts` ni `time.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.9: Renombrar `vista.ts`→`view.ts`

**Archivo:** `extension/src/core/vista.ts` → `extension/src/core/view.ts`
**Acción:** `git mv`; `derivarEstadoDeVista`→`deriveViewState`; estados `inicial`/`en_curso`/`exito`/`fallo`→`initial`/`in_progress`/`success`/`failure`; resultados `cargando`/`con_datos`/`vacio`→`loading`/`withData`/`empty` (`error` sin cambio).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `view.ts`.

**Dependencias:** Tarea 11.1

---

### Tarea 11.10: Renombrar `detailUrl.ts` y `speakerTime.ts` (sin cambio de nombre de archivo)

**Archivo:** `extension/src/core/detailUrl.ts`, `extension/src/core/speakerTime.ts`
**Acción:** En `detailUrl.ts`: `PARAM_REUNION_ID`(valor `"reunionId"`)→`PARAM_MEETING_ID`(valor `"meetingId"`), `construirUrlDetalle`→`buildDetailUrl`, `leerReunionId`→`readMeetingId`. En `speakerTime.ts`: `calcularTiempoDeHabla`→`calculateSpeakingTime`, `turnosPorId`→`turnsById`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en estos dos archivos.

**Dependencias:** Tarea 11.1

---

### Tarea 11.11: Renombrar `core/api/client.ts`

**Archivo:** `extension/src/core/api/client.ts`
**Acción:** `BACKEND_URL_DEFECTO`→`DEFAULT_BACKEND_URL`; `CLAVE_SESION`→`SESSION_KEY`; `ErrorSesionInvalida`→`InvalidSessionError`; `ErrorTransporteNoSeguro`→`InsecureTransportError`; `ErrorNoEncontrado`→`NotFoundError`; `validarTransporte`→`validateTransport`; `leerSesion`→`readSession`; `descartarSesion`→`discardSession`; `almacenarSesion`→`storeSession`; `solicitar`→`request`; `listarReuniones`→`listMeetings`; `obtenerTranscripcion`→`getTranscript`; `obtenerDiarizacion`→`getDiarization`; `renombrarReunion`→`renameMeeting`; `eliminarReunion`→`deleteMeeting`. Actualizar las rutas invocadas a `/meetings`, `/meetings/{id}/request-join`, `/meetings/{id}/transcript`, `/meetings/{id}/diarization`, `/meetings/upload` (Fase 5–6 backend).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `client.ts`.

**Dependencias:** Tarea 11.1, Fase 6, Fase 5

---

### Tarea 11.12: Renombrar `core/design/tokens.ts`

**Archivo:** `extension/src/core/design/tokens.ts`
**Acción:** `COLOR_TOKENS` claves `fondo`→`background`, `superficie`→`surface`, `superficieAlterna`→`surfaceAlt`, `primario`→`primary`, `texto`→`text`, `textoTenue`→`textMuted`, `grabando`→`recording`, `foco`→`focus`; `TYPOGRAPHY_TOKENS` claves `fuenteBase`→`baseFont`, `textoSm`/`textoBase`/`textoLg`/`textoXl`→`textSm`/`textBase`/`textLg`/`textXl`, `pesoRegular`/`pesoMedio`/`pesoSemibold`→`weightRegular`/`weightMedium`/`weightSemibold`; `SPACING_TOKENS` claves `esp1`–`esp6`→`space1`–`space6`; `RADIUS_TOKENS` claves `radioSm`/`radioMd`/`radioLg`→`radiusSm`/`radiusMd`/`radiusLg`; `ELEVATION_TOKENS` claves `sombraSm`/`sombraMd`→`shadowSm`/`shadowMd`; `PALETA_AVATAR`→`AVATAR_PALETTE`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `tokens.ts`.

**Dependencias:** Tarea 11.5

---

### Tarea 11.13: Actualizar los `index.ts` de barril (`core/index.ts`, `core/api/index.ts`, `core/design/index.ts`)

**Archivo:** `extension/src/core/index.ts`, `extension/src/core/api/index.ts`, `extension/src/core/design/index.ts`
**Acción:** Actualizar las rutas de re-export a los nuevos nombres de archivo de las Tareas 11.2–11.12; traducir el comentario `"Cliente_De_API compartido"`→`"Shared API client"`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en los tres archivos de barril.

**Dependencias:** Tarea 11.11, Tarea 11.12

---

### Tarea 11.14: Renombrar y actualizar los tests de `core/`

**Archivo:** `extension/src/core/*.test.ts`
**Acción:** Para cada archivo de test pareado con un archivo renombrado en las Tareas 11.2–11.12 (incluye `authBloqueo.test.ts`→`authLock.test.ts`, `busqueda.test.ts`→`search.test.ts`, `captura.test.ts`→`capture.test.ts`, `hablantes.test.ts`→`speakers.test.ts`, `intervenciones.test.ts`→`interventions.test.ts`, `notas.test.ts`→`notes.test.ts`, `orden.test.ts`→`order.test.ts`, `tiempo.test.ts`→`time.test.ts`, `vista.test.ts`→`view.test.ts`): `git mv` y actualizar el contenido a los símbolos nuevos, incluyendo los literales de estado usados en las aserciones (`en_cola`→`queued`, etc., ya establecidos en la Fase 6).

**Criterio de Completado:**
`npm run test -w extension -- core` pasa con el mismo número de tests que antes del rename.

**Dependencias:** Tarea 11.13

---

### Tarea 11.15: `check-english` acotado a `core/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py extension/src/core/**/*.ts`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 11.14

---

## Fase 12: `extension/src/panel/`

### Tarea 12.1: Renombrar `ControlesDeCaptura.tsx`→`CaptureControls.tsx`

**Archivo:** `extension/src/panel/components/ControlesDeCaptura.tsx` → `CaptureControls.tsx`
**Acción:** `git mv`; componente `ControlesDeCaptura`→`CaptureControls`; props `ControlesDeCapturaProps`→`CaptureControlsProps` (`estadoDeCaptura`→`captureState`, `microfonos`→`microphones`, `microfonoSeleccionado`→`selectedMicrophone`, `onSeleccionarMicrofono`→`onSelectMicrophone`, `onToggleCaptura`→`onToggleCapture`, `onAbrirAjustes`→`onOpenSettings`, `tiempoTranscurridoMs`→`elapsedTimeMs`, `errorInicio`→`startError`, `errorMicrofono`→`microphoneError`); `formatearCronometro`→`formatStopwatch`; `FUENTES_DE_AUDIO`→`AUDIO_SOURCES`. Usar `CaptureState`/`CaptureEvent` de `core/types.ts` (Tarea 11.1).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `CaptureControls.tsx`.

**Dependencias:** Fase 11

---

### Tarea 12.2: Renombrar `EncabezadoPanel.tsx`→`PanelHeader.tsx`

**Archivo:** `extension/src/panel/components/EncabezadoPanel.tsx` → `PanelHeader.tsx`
**Acción:** `git mv`; componente `EncabezadoPanel`→`PanelHeader`; props `EncabezadoPanelProps`→`PanelHeaderProps` (`estadoDeCaptura`→`captureState`, `onNuevaNota`→`onNewNote`, `errorInicio`→`startError`); `habilitado`→`enabled`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `PanelHeader.tsx`.

**Dependencias:** Fase 11

---

### Tarea 12.3: Renombrar `ListaDeNotas.tsx`→`NotesList.tsx` (código y texto de interfaz)

**Archivo:** `extension/src/panel/components/ListaDeNotas.tsx` → `NotesList.tsx`
**Acción:** `git mv`; componente `ListaDeNotas`→`NotesList`; props `ListaDeNotasProps`→`NotesListProps` (`estado`→`state`, `notas`→`notes`, `onReintentar`→`onRetry`, `onAbrirNota`→`onOpenNote`, `onEliminarNota`→`onDeleteNote`, `onRenombrarNota`→`onRenameNote`); vars `textoInput`→`inputText`, `textoDebounced`→`debouncedText`, `filtro`→`filter`, `renombrandoId`→`renamingId`, `tituloEditado`→`editedTitle`; fns `iniciarRenombrar`→`startRename`, `confirmarRenombrar`→`confirmRename`, `confirmarEliminar`→`confirmDelete`. Texto de interfaz (Requisito 5): `placeholder="Buscar notas..."`→`"Search notes..."`; `"Aún no tienes notas. Crea tu primera nota para empezar."`→`"You don't have any notes yet. Create your first note to get started."`; `"No se encontraron notas que coincidan con la búsqueda."`→`"No notes matched your search."`. Literales de `<option>` de filtro de estado `en_cola`/`grabando`/`transcribiendo`/`completado`/`fallido`→`queued`/`recording`/`transcribing`/`completed`/`failed` (ya establecidos en la Fase 6).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `NotesList.tsx`; revisión visual manual (Fase 17) confirma el texto en inglés.

**Dependencias:** Fase 11

---

### Tarea 12.4: Renombrar `VistaDeAutenticacion.tsx`→`AuthView.tsx`

**Archivo:** `extension/src/panel/components/VistaDeAutenticacion.tsx` → `AuthView.tsx`
**Acción:** `git mv`; componente `VistaDeAutenticacion`→`AuthView`; props `VistaDeAutenticacionProps`→`AuthViewProps` (`indisponible`→`unavailable`, `sesionExpirada`→`sessionExpired`); vars `intentos`→`attempts`, `bloqueado`→`locked`. Usar `isLocked`/`AuthAttempt` de `core/authLock.ts` (Tarea 11.2).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `AuthView.tsx`.

**Dependencias:** Tarea 11.2

---

### Tarea 12.5: Actualizar `SidePanelApp.tsx`

**Archivo:** `extension/src/panel/SidePanelApp.tsx`
**Acción:** `estadoDeCaptura`→`captureState`; actualizar los imports de los cuatro componentes renombrados (Tareas 12.1–12.4) y el literal de estado `"grabando"`→`"recording"`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `SidePanelApp.tsx`.

**Dependencias:** Tarea 12.1, Tarea 12.2, Tarea 12.3, Tarea 12.4

---

### Tarea 12.6: Renombrar y actualizar tests de `panel/`

**Archivo:** `extension/src/panel/components/*.test.tsx`, `extension/src/panel/SidePanelApp.test.tsx`
**Acción:** `git mv` cada test pareado a los nombres nuevos (`ControlesDeCaptura.test.tsx`→`CaptureControls.test.tsx`, etc.) y actualizar contenido/aserciones a los símbolos y texto en inglés de las Tareas 12.1–12.5.

**Criterio de Completado:**
`npm run test -w extension -- panel` pasa con el mismo número de tests que antes del rename.

**Dependencias:** Tarea 12.5

---

### Tarea 12.7: `check-english` acotado a `panel/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py extension/src/panel/**/*.tsx`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 12.6

---

## Fase 13: `extension/src/detail/`

### Tarea 13.1: Renombrar `BuscadorDeTranscripcion.tsx`→`TranscriptSearch.tsx`

**Archivo:** `extension/src/detail/BuscadorDeTranscripcion.tsx` → `TranscriptSearch.tsx`
**Acción:** `git mv`; componente `BuscadorDeTranscripcion`→`TranscriptSearch`; props (`intervenciones`→`interventions`, `onResultado`→`onResult`); vars `texto`→`text`, `sinCoincidencias`→`noMatches`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `TranscriptSearch.tsx`.

**Dependencias:** Fase 11

---

### Tarea 13.2: Renombrar `EspacioDeResumen.tsx`→`SummarySpace.tsx`

**Archivo:** `extension/src/detail/EspacioDeResumen.tsx` → `SummarySpace.tsx`
**Acción:** `git mv`; componente `EspacioDeResumen`→`SummarySpace`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `SummarySpace.tsx`.

**Dependencias:** Fase 11

---

### Tarea 13.3: Renombrar `PanelDeTranscripcion.tsx`→`TranscriptPanel.tsx`

**Archivo:** `extension/src/detail/PanelDeTranscripcion.tsx` → `TranscriptPanel.tsx`
**Acción:** `git mv`; componente `PanelDeTranscripcion`→`TranscriptPanel`; props `PanelDeTranscripcionProps`→`TranscriptPanelProps`; var `refsPorTurno`→`refsByTurn`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `TranscriptPanel.tsx`.

**Dependencias:** Fase 11

---

### Tarea 13.4: Renombrar `VistaTiempoDeHabla.tsx`→`SpeakingTimeView.tsx`

**Archivo:** `extension/src/detail/VistaTiempoDeHabla.tsx` → `SpeakingTimeView.tsx`
**Acción:** `git mv`; componente `VistaTiempoDeHabla`→`SpeakingTimeView`; props `VistaTiempoDeHablaProps`→`SpeakingTimeViewProps`; var `ordenadas`→`sorted`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `SpeakingTimeView.tsx`.

**Dependencias:** Fase 11

---

### Tarea 13.5: Actualizar `DetailApp.tsx`

**Archivo:** `extension/src/detail/DetailApp.tsx`
**Acción:** `reunionId`→`meetingId`, `solicitudTranscripcion`→`transcriptRequest`, `solicitudDiarizacion`→`diarizationRequest`, `asignaciones`→`assignments`, `resultadoBusqueda`→`searchResult`, `cargarTranscripcion`→`loadTranscript`, `cargarDiarizacion`→`loadDiarization`, `turnos`→`turns`, `hablantes`→`speakers`, `intervenciones`→`interventions`, `entradasTiempoDeHabla`→`speakingTimeEntries`, `estadoTranscripcion`→`transcriptState`, `estadoDiarizacion`→`diarizationState`; consts `SOLICITUD_INICIAL`→`INITIAL_REQUEST`, `SIN_TURNOS`→`NO_TURNS`, `SIN_HABLANTES`→`NO_SPEAKERS`; actualizar imports a los cuatro componentes renombrados (Tareas 13.1–13.4) y a `readMeetingId` (Tarea 11.10).

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `DetailApp.tsx`.

**Dependencias:** Tarea 13.1, Tarea 13.2, Tarea 13.3, Tarea 13.4

---

### Tarea 13.6: Renombrar y actualizar tests de `detail/`

**Archivo:** `extension/src/detail/*.test.tsx`
**Acción:** `git mv` cada test pareado a los nombres nuevos y actualizar contenido/aserciones, incluyendo el mock corregido `estado_diarizacion: "completado"`→`diarizationState: "completed"` en `DetailApp.test.tsx` señalado en el inventario del diseño (era un valor de tipo Reunion usado incorrectamente en un mock de Diarizacion).

**Criterio de Completado:**
`npm run test -w extension -- detail` pasa con el mismo número de tests que antes del rename.

**Dependencias:** Tarea 13.5

---

### Tarea 13.7: `check-english` acotado a `detail/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py extension/src/detail/**/*.tsx`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 13.6

---

## Fase 14: Archivos de nivel superior de la extensión + migración IndexedDB

### Tarea 14.1: Escribir el test que falla para la migración de IndexedDB (RED, Propiedad 6)

**Archivo:** `extension/src/upload-queue.property.test.ts` (extender)
**Acción:** Añadir un test que abra la base de datos IndexedDB en versión 1 con uno o más registros `UploadJob` usando los campos antiguos (`claveIdempotencia`, `titulo`, `enlaceMeet`), luego dispare la apertura en versión 2 (aún no implementada) y espere que los mismos registros existan con los campos nuevos (`idempotencyKey`, `title`, `meetLink`) poblados con los mismos valores.

**Criterio de Completado:**
`npm run test -w extension -- upload-queue.property` falla porque la migración `onupgradeneeded` a versión 2 no existe todavía.

**Dependencias:** Fase 12, Fase 13

---

### Tarea 14.2: Implementar la migración de IndexedDB (GREEN, Propiedad 6)

**Archivo:** `extension/src/recording-db.ts`, `extension/src/upload-queue.ts`
**Acción:** En `recording-db.ts`, subir `DB_VERSION` a `2` e implementar en `onupgradeneeded` la copia de los valores de `claveIdempotencia`/`titulo`/`enlaceMeet` a `idempotencyKey`/`title`/`meetLink` para cada registro existente antes de crear el nuevo índice `"idempotencyKey"` y eliminar el índice `"claveIdempotencia"`, según el esqueleto de design.md § Modelos de Datos → "Migración de esquema de IndexedDB". En `upload-queue.ts`, renombrar la interfaz `UploadJob` (`claveIdempotencia`,`titulo`,`enlaceMeet`→`idempotencyKey`,`title`,`meetLink`) y el tipo `EnqueueUploadInput`.

**Criterio de Completado:**
`npm run test -w extension -- upload-queue.property` pasa (Propiedad 6 de design.md).

**Dependencias:** Tarea 14.1

---

### Tarea 14.3: Actualizar `background.ts`

**Archivo:** `extension/src/background.ts`
**Acción:** Función `uploadRecording(mimeType, sessionId, notificationEmittedAt, titulo, enlaceMeet)` → parámetros `title`, `meetLink`; claves del payload enviado a `/meetings/upload` traducidas según design.md § Componentes e Interfaces → "13.": `reunion_id`→`meeting_id`, `clave_idempotencia`→`idempotency_key`, `origen_captura`→`capture_origin`, `duracion_segundos`→`duration_seconds`, `interrumpida`→`interrupted`, `notificacion_emitida_en`→`notice_issued_at`, `titulo`→`title`, `enlace_meet`→`meet_link`; literal `"extension_chrome"`→`"chrome_extension"`.

**Criterio de Completado:**
`npm run typecheck -w extension` no reporta errores originados en `background.ts`.

**Dependencias:** Tarea 14.2, Fase 5

---

### Tarea 14.4: Actualizar `content.ts` (texto de interfaz visible a participantes)

**Archivo:** `extension/src/content.ts`
**Acción:** Traducir el aviso mostrado en el DOM de Google Meet: `"sauri está grabando esta reunión"`→`"sauri is recording this meeting"` (Requisito 5.1). Traducir los comentarios del archivo.

**Criterio de Completado:**
`grep -n "está grabando" extension/src/content.ts` no devuelve resultados; `grep -n "is recording this meeting" extension/src/content.ts` sí.

**Dependencias:** Ninguna

---

### Tarea 14.5: Actualizar `offscreen.ts` y comentarios restantes

**Archivo:** `extension/src/offscreen.ts`
**Acción:** Traducir los comentarios en español (p. ej. "Captura Pista_De_Audio + Pista_De_Video"→"Capture Audio_Track + Video_Track" usando ya los términos en inglés de esta spec).

**Criterio de Completado:**
`python3 _tools/check_english_only.py extension/src/offscreen.ts` reporta 0 hallazgos.

**Dependencias:** Ninguna

---

### Tarea 14.6: Actualizar tests de nivel superior y `check-english` de la extensión completa

**Archivo:** `extension/src/background.exploration.test.ts`, `extension/src/content.exploration.test.ts`, `extension/src/content.preservation.test.ts`, `extension/src/offscreen.capture.test.ts`, `extension/src/manifest.test.ts`, `extension/src/upload-queue.preservation.test.ts`, `extension/tests/e2e/capture-to-ingesta.spec.ts`
**Acción:** Actualizar el contenido de estos tests a los símbolos, payloads y texto de interfaz nuevos de las Tareas 14.2–14.5 y de las Fases 11–13. Renombrar `extension/tests/e2e/capture-to-ingesta.spec.ts`→`capture-to-ingestion.spec.ts` y actualizar sus literales de estado (`en_cola`/`grabando`/etc.→`queued`/`recording`/etc.).

**Criterio de Completado:**
`npm run test -w extension` pasa en su totalidad; `npm run test:e2e --if-present` pasa; `python3 _tools/check_english_only.py $(git ls-files 'extension/src/**' 'extension/tests/**')` reporta 0 hallazgos.

**Dependencias:** Tarea 14.3, Tarea 14.4, Tarea 14.5, Fase 11, Fase 12, Fase 13

---

## Fase 15: `frontend/src/`

### Tarea 15.1: Actualizar `api.ts`

**Archivo:** `frontend/src/api.ts`
**Acción:** `registrarReunion`→`registerMeeting`; `listarReuniones`→`listMeetings`; `obtenerTranscripcion`→`getTranscript`. Actualizar las llamadas para usar las rutas nuevas (`/meetings`, etc.) y los tipos de `@sauri/shared-types` de la Fase 3.

**Criterio de Completado:**
`npm run typecheck -w frontend` no reporta errores originados en `api.ts`.

**Dependencias:** Fase 3, Fase 6

---

### Tarea 15.2: Renombrar `ReunionList.tsx`→`MeetingList.tsx`

**Archivo:** `frontend/src/components/ReunionList.tsx` → `MeetingList.tsx`
**Acción:** `git mv`; componente `ReunionList`→`MeetingList`; `ESTADO_COLORS`→`STATE_COLORS` (claves de `ProcessState`, Fase 3); vars `reuniones`/`setReuniones`→`meetings`/`setMeetings`; import de `listarReuniones`→`listMeetings` (Tarea 15.1).

**Criterio de Completado:**
`npm run typecheck -w frontend` no reporta errores originados en `MeetingList.tsx`.

**Dependencias:** Tarea 15.1

---

### Tarea 15.3: Renombrar `TranscripcionView.tsx`→`TranscriptView.tsx`

**Archivo:** `frontend/src/components/TranscripcionView.tsx` → `TranscriptView.tsx`
**Acción:** `git mv`; componente `TranscripcionView`→`TranscriptView`; props `TranscripcionViewProps`→`TranscriptViewProps` (`reunionId`→`meetingId`); import de `obtenerTranscripcion`→`getTranscript` (Tarea 15.1).

**Criterio de Completado:**
`npm run typecheck -w frontend` no reporta errores originados en `TranscriptView.tsx`.

**Dependencias:** Tarea 15.1

---

### Tarea 15.4: Actualizar `RegisterForm.tsx` y `App.tsx`

**Archivo:** `frontend/src/components/RegisterForm.tsx`, `frontend/src/App.tsx`
**Acción:** En `RegisterForm.tsx`: state `enlaceMeet`/`setEnlaceMeet`→`meetLink`/`setMeetLink`; import de `registrarReunion`→`registerMeeting`. En `App.tsx`: variante de tipo `View` `"transcripcion"`→`"transcript"`; `handleSelectReunion`→`handleSelectMeeting`; actualizar imports a `MeetingList`/`TranscriptView` (Tareas 15.2–15.3).

**Criterio de Completado:**
`npm run typecheck -w frontend` pasa sin errores en todo el paquete.

**Dependencias:** Tarea 15.2, Tarea 15.3

---

### Tarea 15.5: Actualizar tests de `frontend/`

**Archivo:** `frontend/src/**/*.test.tsx` (los dos archivos de test existentes)
**Acción:** Actualizar el contenido a los símbolos/rutas nuevos de las Tareas 15.1–15.4.

**Criterio de Completado:**
`npm run test -w frontend` pasa.

**Dependencias:** Tarea 15.4

---

### Tarea 15.6: `check-english` acotado a `frontend/`

**Archivo:** N/A (verificación)
**Acción:** `python3 _tools/check_english_only.py frontend/src/**/*`

**Criterio de Completado:**
0 hallazgos.

**Dependencias:** Tarea 15.5

---

## Fase 16: Documentación de gobernanza

### Tarea 16.1: Actualizar `CLAUDE.md`

**Archivo:** `CLAUDE.md`
**Acción:** Sustituir el párrafo "Domain code, comments, and docstrings are written in Spanish... because this mirrors the ubiquitous language used with the business" por una descripción del English_Codebase_Standard: todo el código (dominio incluido) se escribe en inglés; `Transcript_Content` (el texto transcrito real) permanece en español porque refleja el idioma hablado en las reuniones; el texto de interfaz de usuario es en inglés por defecto. Referenciar el Domain_Term_Mapping de `design.md` de esta spec como fuente de los nombres de entidad canónicos (`Meeting`, `Speaker`, `Transcript`, `Diarization`, etc.), reemplazando los ejemplos en español (`Reunion`, `estado_proceso`, `Motor_ASR`, `Proveedor_De_Transcripcion`) por sus equivalentes en inglés (`Meeting`, `process_state`, `ASREngine`, `TranscriptionProvider`) en la sección "Project overview" y en cualquier otra mención del glosario de dominio en el archivo.

**Criterio de Completado:**
`grep -n "written in Spanish" CLAUDE.md` no devuelve resultados; el archivo menciona explícitamente que `Transcript_Content` permanece en español.

**Dependencias:** Fase 1

---

### Tarea 16.2: Actualizar `AGENTS.md`

**Archivo:** `AGENTS.md`
**Acción:** Revisar si `AGENTS.md` referencia identificadores de dominio en español fuera de ejemplos genéricos de proceso (el contenido leído durante el diseño de esta spec no mostró referencias a `Reunion`/`es_comercial`/etc., solo reglas de proceso genéricas en inglés) y, si se encuentra alguna, actualizarla al equivalente en inglés del Domain_Term_Mapping.

**Criterio de Completado:**
`python3 _tools/check_english_only.py AGENTS.md` reporta 0 hallazgos.

**Dependencias:** Fase 1

---

### Tarea 16.3: Añadir una nota de convención al README si referencia el glosario de dominio

**Archivo:** `README.md`
**Acción:** Si `README.md` usa términos de dominio en español (revisar la tabla de roadmap y cualquier descripción de módulo mencionada en `CLAUDE.md` § "Project overview"), actualizarlos a sus equivalentes en inglés del Domain_Term_Mapping.

**Criterio de Completado:**
`python3 _tools/check_english_only.py README.md` reporta 0 hallazgos, o el archivo no contenía términos de dominio para empezar (confirmar con una lectura previa).

**Dependencias:** Fase 1

---

## Fase 17: Verificación final de cierre

### Tarea 17.1: Typecheck y build completos

**Archivo:** N/A (verificación)
**Acción:** Ejecutar desde la raíz del repo `npm run typecheck` (fan-out a `extension`, `frontend`, `packages/shared-types`) y `npm run build` en cada workspace.

**Criterio de Completado:**
Ambos comandos terminan con código de salida `0` y cero errores reportados (Propiedad 7 de design.md).

**Dependencias:** Fase 10, Fase 14, Fase 15

---

### Tarea 17.2: Suite completa de tests

**Archivo:** N/A (verificación)
**Acción:** Ejecutar `cd backend && pytest` (suite completa) y, desde la raíz, `npm run test` (fan-out) y `npm run test:e2e --if-present`.

**Criterio de Completado:**
Las tres suites pasan en su totalidad, con el mismo número total de tests que existía antes de iniciar esta spec (ningún test se perdió en el proceso de rename).

**Dependencias:** Tarea 17.1

---

### Tarea 17.3: `mypy` estricto sobre todo el backend

**Archivo:** N/A (verificación)
**Acción:** `cd backend && mypy .`

**Criterio de Completado:**
Cero errores reportados.

**Dependencias:** Tarea 17.2

---

### Tarea 17.4: Escaneo de idioma sobre el repositorio completo

**Archivo:** N/A (verificación)
**Acción:** `make check-english` (escaneo completo, no acotado por fase).

**Criterio de Completado:**
0 hallazgos en `backend/`, `extension/src/`, `frontend/src/`, `packages/shared-types/` (Propiedad 5 de design.md). Los hallazgos legítimamente excluidos (Transcript_Content, fixtures marcados, `.spectra/specs/` Legacy_Specs) no cuentan como fallo.

**Dependencias:** Tarea 17.3

---

### Tarea 17.5: Smoke test manual end-to-end

**Archivo:** N/A (verificación manual)
**Acción:** Con `make up` levantando el stack completo: (1) iniciar sesión en la extensión y verificar que el texto de la UI está en inglés; (2) unirse a una reunión de Google Meet de prueba y verificar que el aviso de grabación dice "sauri is recording this meeting"; (3) subir una grabación y verificar en la vista de detalle que la transcripción (en español, sin cambios) se muestra correctamente atribuida a hablantes con las etiquetas "Speaker 1", "Speaker 2", etc.; (4) verificar en las herramientas de red del navegador que las peticiones usan las rutas `/meetings/...` y payloads con campos en inglés.

**Criterio de Completado:**
Los cuatro pasos se completan sin errores visibles y sin texto mixto español/inglés en la interfaz (fuera del contenido transcrito, que permanece en español por diseño).

**Dependencias:** Tarea 17.4
