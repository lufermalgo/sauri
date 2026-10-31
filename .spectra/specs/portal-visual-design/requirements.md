# Requisitos — Portal web mínimo de Sauri

## Introducción

El alcance aprobado de Sauri incluye un portal web para encontrar grabaciones, volver a una reunión y revisar sus medios y transcripción, además de un flujo separado para incorporar una grabación existente mediante carga manual. El portal también puede recibir tratamiento visual en la pantalla de acceso existente, pero ese trabajo no define autenticación nueva ni cambia políticas de acceso.

Este documento traduce únicamente ese alcance a requisitos verificables. La línea base distingue capacidades confirmadas de detalles aún abiertos: por ejemplo, no fija los límites de elegibilidad de archivos ni el catálogo de filtros, y establece que terminar la transferencia no equivale a terminar el procesamiento.

**Idea fuerza:** la interfaz debe hacer visibles las capacidades aprobadas y sus límites sin presentar propuestas visuales, datos ficticios o estados no confirmados como producto.

**Alcance:** presentación visual de la autenticación ya existente; biblioteca de grabaciones; vista de reunión con reproductor y transcripción; carga manual de archivos con progreso veraz, resultado y recuperación de error.

**Fuera de alcance:** cambiar autenticación, permisos, política de acceso, consentimiento, retención o garantías de eliminación; búsqueda full-text entre reuniones; edición del texto de la transcripción; límites de formato/tamaño/duración no aprobados; chat interactivo y métricas de tiempo de habla (Phase 2); diagnósticos distintos de la condición explícita de no incluir secretos ni contenido de transcripción; las pantallas Terra no respaldadas por la línea base. `design/stitch/README.md` y sus recursos son inspiración visual no normativa, no requisitos ni autorización para reproducir sus textos, controles, estados, datos o composiciones.

## Glosario

- **Biblioteca_De_Grabaciones**: vista web donde el usuario encuentra y selecciona grabaciones existentes.
- **Vista_De_Reunion**: portal de una grabación seleccionada, con el reproductor sobre la transcripción y un panel lateral con pestañas aprobadas.
- **Carga_Manual**: selección y transferencia de un archivo local desde el portal, separada de la captura automática de la extensión Chrome.
- **Elegibilidad_De_Carga**: reglas de producto que determinan si un archivo local seleccionado puede ofrecerse para carga; formatos, tamaño y duración no están definidos aquí.
- **Finalizacion_De_Carga**: confirmación de que la transferencia del archivo concluyó, que no implica finalización de transcripción u otro procesamiento.

## Requisitos

### Requisito 1: Tratamiento visual del acceso existente

**Historia de Usuario:** Como usuario de Sauri, quiero que la pantalla de acceso existente tenga un tratamiento visual coherente con el portal, para usar la entrada actual sin que el rediseño altere su funcionamiento o sus permisos.

**Trazabilidad:** `PRODUCT_BASELINE.md` (snapshot aprobado con enmienda autorizada, §4, párrafo posterior a §4.D; §6, restricción confirmada y no-objetivos), blob `2337a46b2ba78ef4364e23a86df9918db621c881`. La referencia visual de Stitch excluye expresamente la experiencia de login como alcance y no puede definirla (`design/stitch/README.md`, §3).

#### Criterios de Aceptación

1. THE portal login visual treatment SHALL apply only to the existing authentication experience.
2. WHEN the login receives visual styling, THE portal SHALL NOT change authentication behavior, access policy, or permissions.
3. THE requirements SHALL NOT derive login fields, labels, error/loading/expired-session states, recovery flows, provider integrations, security claims, or branding from the Stitch mock.

### Requisito 2: Encontrar grabaciones en la biblioteca

**Historia de Usuario:** Como usuario, quiero encontrar grabaciones previas en la biblioteca web, para volver a una sesión guardada.

**Trazabilidad:** `PRODUCT_BASELINE.md` §4.C.1 y §5 (biblioteca confirmada; full-text excluido; campos de filtro derivados de metadatos disponibles).

#### Criterios de Aceptación

1. THE Biblioteca_De_Grabaciones SHALL present recordings ordered newest first.
2. THE Biblioteca_De_Grabaciones SHALL support search, filtering, and sorting of recordings.
3. WHEN filters are offered, THE Biblioteca_De_Grabaciones SHALL derive their fields from available metadata and SHALL NOT imply an approved arbitrary filter catalogue.
4. THE Biblioteca_De_Grabaciones SHALL NOT provide or imply full-text search across meetings.
5. THE requirements SHALL NOT prescribe mock counts, example customer data, specific filter values, pagination, summary cards, or processing-state controls absent from the approved baseline.

### Requisito 3: Administrar una grabación y sus metadatos

**Historia de Usuario:** Como usuario, quiero seleccionar una grabación, administrar sus artefactos y editar sus metadatos y etiquetas, para retomar, organizar o llevarme el material de una sesión.

**Trazabilidad:** `PRODUCT_BASELINE.md` §4.C.2–3 y §5 (selección, renombrado, eliminación, descarga de video/transcripción, edición de metadatos de empresa/proyecto/participantes y uso de etiquetas predefinidas o creadas por el usuario confirmados; garantías de eliminación, formatos de exportación, gobierno de etiquetas y campos adicionales no especificados).

#### Criterios de Aceptación

1. WHEN the user selects a recording in the Biblioteca_De_Grabaciones, THE portal SHALL make that recording available for review in its Vista_De_Reunion.
2. THE portal SHALL support renaming and deleting a selected recording.
3. THE portal SHALL support downloading the selected recording's video and transcript.
4. WHEN the user edits company, project, or participant metadata for a recording and saves the changes, THE portal SHALL show the saved values for that recording.
5. THE portal SHALL allow the user to apply predefined tags to a recording.
6. WHEN the user creates a tag and applies it to a recording, THE portal SHALL show that tag among the tags applied to that recording.
7. THE requirements SHALL NOT add deletion guarantees, export formats, bulk actions, archival behavior, tag-governance rules, or metadata fields beyond company, project, and participants unless established by the baseline.

### Requisito 4: Revisar medios y transcripción de una reunión

**Historia de Usuario:** Como usuario, quiero revisar el medio junto con su transcripción atribuida a hablantes, para navegar entre lo que escucho y lo que leo.

**Trazabilidad:** `PRODUCT_BASELINE.md` §4.C.4–5, §5 y §6 (composición confirmada; detalles de control, timestamp, colores y video específicos para diseño; nombres de pestañas adicionales abiertos).

#### Criterios de Aceptación

1. THE Vista_De_Reunion SHALL place the media player above the transcript.
2. FOR EACH transcript turn, THE Vista_De_Reunion SHALL present a timestamp, a colored speaker label, and the turn text.
3. WHEN media playback advances, THE Vista_De_Reunion SHALL highlight the corresponding transcript passage and scroll the transcript to follow it.
4. WHEN the user selects a transcript passage, THE Vista_De_Reunion SHALL start media playback at its linked time.
5. WHEN the user edits a speaker name from the transcript, THE portal SHALL change speaker attribution only and SHALL NOT offer manual transcript-text editing.
6. THE initial side-panel composition SHALL include Chat and Notes/Summary tabs; THE Chat tab SHALL NOT provide interactive chat-with-the-recording in this scope.
7. THE portal SHALL keep notes and summaries distinct from the transcript. THE requirements SHALL NOT prescribe exact controls, timestamp format, colors, additional tabs, a fixed summary format, or video-specific behavior.

### Requisito 5: Seleccionar y preparar una carga manual elegible

**Historia de Usuario:** Como usuario, quiero seleccionar un archivo local elegible desde el portal, para añadir una grabación existente sin iniciar una captura de la extensión.

**Trazabilidad:** `PRODUCT_BASELINE.md` §4.D.1–2, §5 y §6 (carga manual confirmada y separada de captura; Elegibilidad_De_Carga abierta; sin límites inferibles).

#### Criterios de Aceptación

1. THE Carga_Manual SHALL allow the user to select a local recording file through the web portal, separately from Chrome extension capture.
2. WHEN a selected file satisfies the Elegibilidad_De_Carga rules established by product, THE portal SHALL offer «Subir y procesar».
3. THE requirements SHALL NOT define or infer file formats, size or duration limits, or other eligibility rules from Stitch examples or implementation details.
4. THE design and implementation SHALL treat unresolved Elegibilidad_De_Carga rules as a prerequisite to specifying which files qualify; they SHALL NOT invent defaults.

### Requisito 6: Informar transferencia, resultado y fallo recuperable

**Historia de Usuario:** Como usuario, quiero entender si mi archivo se está transfiriendo, cuándo terminó la carga y cómo recuperarme de un fallo, para distinguir una transferencia de un procesamiento terminado y poder reintentar.

**Trazabilidad:** `PRODUCT_BASELINE.md` §4.D.3–5, §5, §6 y §7.12–13; la referencia `design/stitch/README.md` §4b no puede ampliar esos límites.

#### Criterios de Aceptación

1. WHILE the file is being transferred, THE portal SHALL show a progress bar reflecting upload progress.
2. WHEN Finalizacion_De_Carga occurs, THE portal SHALL NOT present it as proof that transcription or other processing has completed.
3. WHEN the upload finishes, THE portal SHALL provide a link to the resulting meeting or open that meeting; its initial title SHALL default to the selected filename.
4. IF the upload fails, THEN THE portal SHALL explain the problem in clear language, offer «Reintentar» and «Copiar diagnóstico», and retain the selected file for retry.
5. WHEN diagnostic content is copied, THE copied diagnostics SHALL NOT contain secrets or transcript content.
6. THE requirements SHALL NOT specify other diagnostic fields, unrelated personal or meeting data, upload-survival/retry guarantees after closing the tab or a network interruption, processing progress/timing, or invented speed/quality claims.

## Dependencias y límites upstream

- Fuente del alcance: baseline aprobado en #528 (commit `4953b3b4b8a058fd4738342307cc50bfd66814f1`) y enmienda de carga manual aprobada por Fer para el snapshot exacto de #665 (commit `85b603ada14996842d913cfbbed4bcffe9fe54c5`, blob `2337a46b2ba78ef4364e23a86df9918db621c881`). La enmienda está publicada en PR #665, aún abierta; cualquier promoción/publicación del baseline depende de que Fer la incorpore.
- Referencia visual: `design/stitch/README.md` y seis recursos en `origin/main` `29002a98de8a3c9cd882e05887e221cfeed184bd`; solo inspiración no normativa. Su §8 enumera exclusiones y los §§0 y 10 niegan que la referencia autorice alcance o aceptación visual.
- No se afirma aceptación de producto, implementación, conformidad visual ni estado runtime.
