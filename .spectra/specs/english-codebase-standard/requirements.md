# Requirements Document — English Codebase Standard

## Introduction

sauri se construyó module por module en español: la mayoría de las clases de dominio, tablas y columnas de base de datos, rutas de API, archivos y nombres de función usan sustantivos en español (`Reunion`, `Hablante`, `Transcripcion`, `usuarios`, `/solicitar-union`), mientras que otras partes del mismo código — sobre todo en `extension/src/core/` y en acrónimos técnicos (`ASR`, `Motor_ASR`, `speakerTime.ts`, `detailUrl.ts`) — ya están en inglés. El resultado es Spanglish inconsistente dentro del mismo módulo e incluso del mismo archivo: `extension/src/core/` mezcla `busqueda.ts`, `hablantes.ts`, `notas.ts`, `tiempo.ts` junto a `speakerTime.ts`, `detailUrl.ts`, `types.ts`. Un desarrollador o un agente de IA que navegue el repositorio no puede predecir en qué idioma estará el siguiente identificador, lo que aumenta el costo cognitivo, genera nombres híbridos (`grabaciones_de_sesion`, `AsignacionDeHablante`) y dificulta el onboarding.

Esta inconsistencia es una decisión no intencional, distinta de la documentada en `CLAUDE.md`, que hasta ahora establece que "domain code, comments, and docstrings are written in Spanish... because this mirrors the ubiquitous language used with the business". Esta spec **reemplaza** esa directriz: el lenguaje ubicuo de sauri pasa a expresarse en inglés en todo el código — incluyendo los sustantivos de dominio (`Reunion` → `Meeting`, `Hablante` → `Speaker`) —, y `CLAUDE.md` debe actualizarse en consecuencia como parte de esta spec.

**Idea fuerza:** El código de sauri —clases, tablas, columnas, rutas de API, archivos, funciones, variables, comentarios y texto de interfaz— se escribe en inglés de manera uniforme, para que el idioma deje de ser una variable a adivinar y el proyecto quede preparado para incorporar español como un idioma de localización explícito y opcional, no como el idioma por defecto del código.

**Scope:** Este documento define los requisitos para: (1) un estándar de nomenclatura en inglés aplicable a todo el código del monorepo (`backend/`, `extension/`, `frontend/`, `packages/shared-types/`); (2) la traducción de los sustantivos de dominio existentes (modelos, tablas, columnas, rutas de API, módulos) según un glosario de mapeo español→inglés; (3) migraciones de base de datos que renombren el esquema existente sin perder datos; (4) la actualización de comentarios, docstrings y texto de interfaz de usuario; (5) la actualización de `CLAUDE.md` para reflejar el nuevo estándar; y (6) un mecanismo de verificación que detecte regresiones a español en código nuevo.

**No-scope:** Esta spec **no** implementa soporte multi-idioma (i18n/l10n) para que los usuarios finales vean la interfaz en español — eso corresponde a una spec posterior de "compatibilidad con español" que se construirá sobre esta base en inglés. Esta spec tampoco traduce el **contenido** generado por los motores de ASR/diarización (el texto transcrito de `Transcript.text` permanece en español porque refleja el idioma real hablado en las reuniones de Summan), ni reescribe retroactivamente los documentos de specs previos ya cerrados en `.spectra/specs/` (quedan como registro histórico), ni modifica el idioma de los mensajes de commit o del propio proceso de Spectra.

## Glosario

- **English_Codebase_Standard**: El conjunto de reglas de nomenclatura definidas en este documento, exigible a todo identificador, archivo, tabla, columna, ruta de API y texto de interfaz nuevo o modificado en el monorepo.
- **Domain_Term_Mapping**: La tabla de correspondencia español→inglés para los sustantivos de dominio existentes, definida en el Requisito 2. Es la fuente de verdad para renombrar clases, tablas, columnas y módulos.
- **User_Facing_Text**: Cualquier cadena de texto que un usuario final vea en la extensión de Chrome o en el frontend web (labels, placeholders, mensajes de estado, textos vacíos, tooltips).
- **Transcript_Content**: El texto producido por el Motor_ASR o el Motor_De_Diarizacion a partir del audio de una reunión (`Transcript.text`, segmentos de hablante). Es contenido de negocio, no código, y permanece en el idioma real hablado en la reunión (español, Colombia).
- **Schema_Rename_Migration**: Una migración de Alembic que renombra tablas y/o columnas existentes usando `op.rename_table` / `op.alter_column`, preservando los datos existentes y con una función `downgrade()` que revierte el cambio.
- **Language_Regression_Check**: El mecanismo automatizado (script o paso de CI) que detecta identificadores, nombres de archivo o comentarios en español en código nuevo o modificado dentro de `backend/app/`, `extension/src/`, `frontend/src/` y `packages/shared-types/`.
- **Legacy_Spec**: Un documento `requirements.md`/`design.md`/`tasks.md` dentro de `.spectra/specs/` creado antes de esta spec, cuyo glosario usa los sustantivos de dominio en español previos al Domain_Term_Mapping.

## Requisitos

### Requisito 1: Estándar de nomenclatura en inglés

**Historia de Usuario:** Como desarrollador o agente de IA que trabaja en sauri, quiero que todo identificador de código esté en inglés de forma consistente, para no tener que adivinar en qué idioma está nombrada cada clase, archivo o función.

#### Criterios de Aceptación

1. THE English_Codebase_Standard SHALL require that all class names, function/method names, variable names, file names, module/package names, database table and column names, and API route paths in `backend/`, `extension/src/`, `frontend/src/`, and `packages/shared-types/` be written in English.
2. THE English_Codebase_Standard SHALL require that all code comments and docstrings in those same directories be written in English.
3. WHEN a Spanish domain term has an established mapping in the Domain_Term_Mapping, THE English_Codebase_Standard SHALL require use of the mapped English term exactly as defined — not an ad hoc translation.
4. THE English_Codebase_Standard SHALL NOT apply to Transcript_Content, to sample/fixture data in tests that intentionally represents Spanish-language meeting audio or transcripts, or to `.spectra/specs/` Legacy_Specs.
5. WHERE a third-party identifier (library name, external API field, HTTP header) is inherently in another language, THE English_Codebase_Standard SHALL NOT require renaming it.

### Requisito 2: Traducción del dominio existente (backend)

**Historia de Usuario:** Como desarrollador, quiero que los modelos, tablas y módulos de dominio existentes se traduzcan a inglés según un mapeo único, para que el código nuevo y el existente hablen el mismo lenguaje ubicuo.

#### Criterios de Aceptación

1. THE Domain_Term_Mapping SHALL define, at minimum, the following entity translations for `backend/app/infra/models.py`: `Reunion`→`Meeting`, `EstadoHistorial`→`StateHistory`, `GrabacionDeSesion`→`SessionRecording`, `Transcripcion`→`Transcript`, `TurnoDeHabla`→`SpeechTurn`, `NotificacionDeGrabacion`→`RecordingNotice`, `RegistroDeAcceso`→`AccessLog`, `Diarizacion`→`Diarization`, `Hablante`→`Speaker`, `AsignacionDeHablante`→`SpeakerAssignment`, `Usuario`→`User`.
2. THE Domain_Term_Mapping SHALL define corresponding table-name translations: `reuniones`→`meetings`, `estado_historial`→`state_history`, `grabaciones_de_sesion`→`session_recordings`, `transcripciones`→`transcripts`, `turnos_de_habla`→`speech_turns`, `notificaciones_de_grabacion`→`recording_notices`, `registro_de_acceso`→`access_log`, `diarizaciones`→`diarizations`, `hablantes`→`speakers`, `asignaciones_de_hablante`→`speaker_assignments`, `usuarios`→`users`.
3. THE Domain_Term_Mapping SHALL define Spanish column-name translations for each renamed table (e.g. `nombre`→`name`, `es_comercial`→`is_sales`, `creado_en`→`created_at`, `inicio_ms`→`start_ms`, `fin_ms`→`end_ms`, `orden`→`sequence`, `titulo`→`title`) covering every Spanish column identified in the current schema.
4. THE Domain_Term_Mapping SHALL define module/package translations: `backend/app/reuniones/`→`backend/app/meetings/`, `backend/app/ingesta/`→`backend/app/ingestion/`, `backend/app/transcripcion/`→`backend/app/transcription/`, `backend/app/diarizacion/`→`backend/app/diarization/`, `backend/app/retencion/`→`backend/app/retention/`.
5. WHEN a backend module is renamed, THE renamed module SHALL preserve its existing internal layout (`router.py` → `service.py` → `repository.py` → `schemas.py`) and its behavior, verified by the module's existing test suite passing unmodified in intent (tests are relocated/renamed, not behaviorally changed).
6. THE Domain_Term_Mapping SHALL translate API route paths accordingly, including at minimum: `/reuniones`→`/meetings`, `POST /subir`→`POST /upload`, `POST /{id}/solicitar-union`→`POST /{id}/request-join`, `GET /{id}/transcripcion`→`GET /{id}/transcript`, `GET /{id}/diarizacion`→`GET /{id}/diarization`.
7. THE Domain_Term_Mapping SHALL be recorded as a single reference table in the design document produced from this spec, so implementation tasks can cite it instead of re-deriving translations independently.

### Requisito 3: Migración de base de datos sin pérdida de datos

**Historia de Usuario:** Como desarrollador, quiero que el esquema de base de datos se renombre mediante migraciones reversibles, para no perder los datos existentes en los entornos locales y de desarrollo al pasar los nombres a inglés.

#### Criterios de Aceptación

1. THE Schema_Rename_Migration SHALL be implemented as new Alembic revision file(s) under `backend/alembic/versions/`, following the existing sequential numbering convention (next available number after `006_add_titulo_reunion.py`).
2. THE Schema_Rename_Migration SHALL use `op.rename_table` and `op.alter_column` (not `drop_table`/`create_table`) for every renamed table and column, so existing row data is preserved.
3. THE Schema_Rename_Migration SHALL implement a `downgrade()` function that reverses every rename performed in `upgrade()`, consistent with existing migrations in this repository.
4. THE Schema_Rename_Migration SHALL update every SQLAlchemy model in `backend/app/infra/models.py`, and every raw SQL/ORM query referencing the old table or column names, to use the new English names in the same change.
5. IF a foreign key, index, or unique constraint name embeds the old Spanish table/column name (e.g. `uq_usuario_email`), THEN THE Schema_Rename_Migration SHALL rename that constraint/index to use the English equivalent as well.

### Requisito 4: Extensión de Chrome y frontend en inglés

**Historia de Usuario:** Como desarrollador que trabaja en la extensión o el frontend, quiero que los nombres de archivo, funciones y variables estén en inglés, para que el código de cliente use la misma convención que el backend.

#### Criterios de Aceptación

1. THE English_Codebase_Standard SHALL apply the Domain_Term_Mapping to file names under `extension/src/core/`, translating at minimum: `authBloqueo.ts`→`authLock.ts`, `busqueda.ts`→`search.ts`, `captura.ts`→`capture.ts`, `hablantes.ts`→`speakers.ts`, `intervenciones.ts`→`interventions.ts`, `notas.ts`→`notes.ts`, `orden.ts`→`order.ts`, `tiempo.ts`→`time.ts`, `vista.ts`→`view.ts`, along with their paired test files (preserving the existing `*.exploration.test.ts` / `*.preservation.test.ts` naming convention where present).
2. THE English_Codebase_Standard SHALL apply the same renaming to React components under `extension/src/panel/components/` whose names are in Spanish (e.g. `ListaDeNotas.tsx`→`NotesList.tsx`), including their internal function/prop names.
3. THE English_Codebase_Standard SHALL apply equivalent renaming to any Spanish-named files, functions, or types under `frontend/src/` and `packages/shared-types/`.
4. WHEN a renamed file or function is imported elsewhere in the monorepo, THE rename SHALL update every import path and reference in the same change, so the project continues to build (`npm run typecheck`) and pass its existing test suite.

### Requisito 5: Texto de interfaz de usuario en inglés

**Historia de Usuario:** Como usuario de sauri, quiero que la interfaz de la extensión y del frontend esté en inglés por defecto, para que el idioma de la aplicación sea consistente con el del código que la implementa, dejando el español como una opción de localización futura.

#### Criterios de Aceptación

1. THE User_Facing_Text SHALL be written in English for every label, placeholder, button, tooltip, empty-state message, and status message currently in Spanish (e.g. `extension/src/panel/components/ListaDeNotas.tsx`'s `"Buscar notas..."`, `"Aún no tienes notas..."`, `"No se encontraron notas..."`).
2. THE User_Facing_Text SHALL NOT be hard-coded in a way that assumes English is the only supported language forever: string literals SHALL be defined as plain English text now, without introducing an i18n/translation-key framework in this spec — that framework is explicitly deferred to the follow-up Spanish-compatibility spec.
3. THE English_Codebase_Standard SHALL NOT change User_Facing_Text that displays Transcript_Content itself (the transcript text shown to the user remains in Spanish, since it reflects what was actually said in the meeting).

### Requisito 6: Actualización de la documentación gobernante

**Historia de Usuario:** Como desarrollador o agente de IA que lee `CLAUDE.md` al iniciar una sesión, quiero que la guía del proyecto refleje el nuevo estándar de inglés, para no recibir instrucciones contradictorias sobre en qué idioma escribir el código.

#### Criterios de Aceptación

1. THE `CLAUDE.md` file SHALL be updated to remove the statement that "domain code, comments, and docstrings are written in Spanish... because this mirrors the ubiquitous language used with the business", replacing it with a description of the English_Codebase_Standard and a reference to the Domain_Term_Mapping.
2. THE updated `CLAUDE.md` SHALL state explicitly that User_Facing_Text is in English by default and that Transcript_Content remains in Spanish, to avoid ambiguity for future contributors.
3. WHERE `AGENTS.md` or other governance docs reference the old Spanish domain terms (e.g. `Reunion`, `es_comercial`), THE documentation update SHALL update those references to the new English terms.

### Requisito 7: Verificación de no regresión al español

**Historia de Usuario:** Como mantenedor del proyecto, quiero un mecanismo que detecte código nuevo escrito en español, para que el estándar de inglés no se erosione con el tiempo.

#### Criterios de Aceptación

1. THE Language_Regression_Check SHALL scan new or modified files under `backend/app/`, `extension/src/`, `frontend/src/`, and `packages/shared-types/` for common Spanish-only patterns (accented characters in identifiers, a defined list of Spanish stopwords/domain nouns superseded by the Domain_Term_Mapping) and report matches.
2. THE Language_Regression_Check SHALL exclude Transcript_Content, test fixtures explicitly marked as Spanish sample data, and `.spectra/specs/` Legacy_Specs from its scan.
3. WHEN the Language_Regression_Check finds a match, THE check SHALL report the file and line without blocking unrelated work — the design phase SHALL determine whether it runs as a CI step, a pre-commit hook, or a manual `make`/`npm` script, consistent with this repository's existing `.githooks/` enforcement pattern.

### Requisito 8: Migración de specs y pruebas existentes

**Historia de Usuario:** Como desarrollador que continúa un módulo ya construido, quiero que las pruebas existentes se actualicen junto con el código que renombran, para que la suite de pruebas siga siendo la fuente de verdad del comportamiento tras el renombramiento.

#### Criterios de Aceptación

1. WHEN a class, table, column, file, or route is renamed per the Domain_Term_Mapping, THE corresponding test file(s) SHALL be updated (renamed and/or edited) in the same change so the full test suite (`pytest`, `npm run test`) passes after the rename.
2. THE renaming effort SHALL NOT alter test behavior or assertions beyond what is required by the rename itself — this is a mechanical rename, not a behavioral refactor.
3. THE spec execution SHALL be organized, in the design/tasks phase, by module (`meetings`/`reuniones`, `ingestion`/`ingesta`, `transcription`/`transcripcion`, `diarization`/`diarizacion`, `retention`/`retencion`, extension `core/`, extension `panel/`) so each module can be renamed and validated independently within this single spec, reducing the risk of a single unreviewable mega-change.

### Requisito 9: Exclusiones explícitas

**Historia de Usuario:** Como desarrollador, quiero límites claros sobre lo que esta spec no cubre, para evitar scope creep y evitar romper el contenido real de las reuniones grabadas.

#### Criterios de Aceptación

1. THE spec SHALL NOT implement Spanish-language UI support, translation files, or an i18n framework — that is deferred to a follow-up spec.
2. THE spec SHALL NOT translate or alter Transcript_Content or any other business data generated by the ASR/diarization engines.
3. THE spec SHALL NOT rewrite `.spectra/specs/` Legacy_Specs (`meeting-capture-transcription`, `identificacion-hablantes`, `transcripcion-asr`, `chrome-side-panel`, `detection-oscillation-fix`, `base64-upload-fix`) — their existing Spanish glossaries remain as historical record of decisions made under the previous convention.
4. THE spec SHALL NOT rewrite past git history, commit messages, or already-merged pull request descriptions.
5. THE spec SHALL NOT require that future Spectra process documents (requirements/design/tasks conversations with the user) be written in English — this spec governs the application codebase, not the spec-writing process itself.
