# Plan de Implementación — Preferencias y controles de captura de la extensión

> **Estado:** redactado el 2026-11-14 a partir de `requirements.md` y `design.md` de esta spec. **No autoriza implementación:** el dueño debe revisar diseño y plan antes de abrir issues. Cada unidad de entrega es un issue, una rama y un worktree propios desde `origin/main` (`AGENTS.md`); implementa Codex o un subagente, el orquestador revisa el diff, ejecuta las pruebas por su cuenta e integra.

## Reglas comunes a todas las unidades

- **TDD:** cada unidad empieza por su tarea de pruebas (RED). RED válido = el comando llega a las aserciones y falla por comportamiento ausente; un error de importación o de infraestructura no cuenta. Se registra el comando y la salida en el PR.
- **Verificación mínima por unidad** (desde `extension/`): `npm run typecheck` y `npm run test` sin fallos nuevos (las suites existentes de `background.*`, `offscreen.capture`, `upload-queue.*`, `recording-db.*`, `content.*` y `panel/**` deben seguir en verde), más `npm run build` si toca manifiesto, Vite o páginas. Lo que no se ejecute se reporta como `NO VERIFICADO`.
- **No se tocan:** el contrato de ingesta (`POST /api/v1/ingestion/upload` y su `IngestionData`), la cola de subida (`upload-queue.ts`), la reconciliación de procesamiento y el lanzamiento de revisión de `background.ts`, ni el aviso de grabación (`show-consent-banner`).
- **Sin datos reales:** las pruebas usan medios sintéticos (`src/fixtures/synthetic-av.webm`) y páginas sintéticas; la comprobación manual usa una reunión de prueba propia del dueño.

## Resumen de Fases

| Fase / Unidad | Descripción | Tareas | Dependencias | En paralelo con |
|---|---|---|---|---|
| U0 | Prueba técnica en Chrome real (decide D3, D4, D7, D9) | 0.1 – 0.2 | Ninguna | U1, U2 |
| U1 | Preferencias: núcleo, almacén y formulario | 1.1 – 1.5 | Ninguna (1.5 bloqueada por P1) | U0, U2 (tras 1.2) |
| U2 | Máquina de estados, mensajes y posición (núcleo puro) | 2.1 – 2.4 | Tarea 1.2 (solo el tipo `CapturePreferences`) | U0, U1 (desde 1.3) |
| U3 | Offscreen: fuente, cuenta atrás, pausa, cancelar, micrófono | 3.1 – 3.4 | U0, U2 | U4, U5, U6 |
| U4 | Service worker, registro durable y manifiesto | 4.1 – 4.5 | U0, U1 (1.3), U2 | U3, U5, U6 |
| U5 | Panel lateral: selector y estado | 5.1 – 5.2 | U0, U2 | U3, U4, U6 |
| U6 | Indicador flotante y cuenta atrás en la pestaña | 6.1 – 6.4 | U0, U2 | U3, U4, U5 |
| U7 | Entrada de notas desde el indicador | 7.1 – 7.2 | U6; `recording-notes` T8 y T10 | — |
| U8 | Integración extremo a extremo y comprobación manual | 8.1 – 8.3 | U1 – U6 (U7 si ya está) | — |

Total: 31 tareas: 11 solo de pruebas (RED), 4 que combinan RED y GREEN en el mismo archivo nuevo (1.3, 1.4, 2.3, 2.4), 2 de evidencia técnica (U0) y el resto de implementación y cierre. Las unidades U3–U6 tocan archivos disjuntos; solo U4 modifica `manifest.json` y `background.ts`.

### Puntos bloqueados por decisiones del dueño

- **P1 (opciones y valor por defecto de la cuenta atrás; indicador activado por defecto):** bloquea solo la Tarea 1.5 (fijar las constantes). El resto de U1 se construye y prueba con valores arbitrarios inyectados.
- **P2 (qué hacer con lo grabado y las notas al cancelar):** bloquea solo la Tarea 4.5. Mientras tanto, cancelar deja los trozos en el equipo sin enviarlos.
- **P3 (permiso `desktopCapture`):** bloquea integrar U4 (manifiesto) y U5 si U0 elige A1.
- **P4 (notas con el indicador oculto, pregunta abierta de la línea base):** no bloquea ninguna tarea; ninguna tarea crea un acceso oculto a notas.
- **P5 (efecto de cambiar el micrófono a mitad de grabación):** bloquea solo el criterio de aceptación de la Tarea 3.4 en el indicador; el grafo fijo (3.3) se construye igual porque también lo necesita la pausa.

---

## Fase U0: Prueba técnica en Chrome real

### Tarea 0.1: Comprobar los mecanismos condicionados del diseño

**Archivo:** rama desechable `spike/extension-capture-source` (no se integra); evidencia en `.spectra/specs/extension-capture-preferences/spike-capture-source.md` (nuevo).
**Acción:** Con la extensión desempaquetada en Chrome estable y una reunión de Meet de prueba, comprobar y anotar con capturas y versión de Chrome:
1. A1: `chrome.desktopCapture.chooseDesktopMedia(["tab","audio"], cb)` desde el panel lateral muestra solo pestañas; el `streamId` se consume en el offscreen con `chromeMediaSource: "desktop"`; hay una pista de audio y una de vídeo; Chrome muestra la barra «Dejar de compartir» y al pulsarla la pista de vídeo emite `ended` en el offscreen.
2. Si A1 falla: A2 (`getDisplayMedia` en offscreen con motivo `DISPLAY_MEDIA`) con los mismos puntos.
3. D4: el content script llama a `setCaptureHandleConfig` y el offscreen lee el mismo `handle` con `getCaptureHandle()`; comprobar si Meet sobrescribe el handle (repetir tras unirse a la llamada y tras presentar).
4. Audio local: si la pestaña sigue sonando sin reenvío por `AudioContext` (decide `monitorTabAudio`).
5. D7: grabación de 30 s con una pausa de 10 s; `ffprobe` del archivo ensamblado da 20 ± 0,5 s y audio y vídeo siguen alineados (aplaudir frente a cámara antes y después de la pausa).
6. D9: un `iframe` de `src/indicator/index.html` (en `web_accessible_resources` con `use_dynamic_url`) carga dentro de un shadow DOM en Meet sin error de CSP en la consola.
7. Bandera de Playwright que autoselecciona la pestaña para el selector elegido (`--auto-select-desktop-capture-source=<título>` u otra).

**Criterio de Completado:** `spike-capture-source.md` contiene para cada punto «funciona / no funciona», la evidencia (captura o salida de `ffprobe`) y la versión de Chrome, y una conclusión: candidato elegido (A1, A2 o B), `monitorTabAudio` verdadero o falso, iframe o respaldo de D9. Si la conclusión es B o el respaldo de D9, el orquestador lo comunica al dueño antes de abrir U3–U6.

**Dependencias:** Ninguna.

---

### Tarea 0.2: Ajustar el diseño a la evidencia

**Archivo:** `.spectra/specs/extension-capture-preferences/design.md`
**Acción:** Sustituir «condicionada a U0» en D3, D4, D7 y D9 por la decisión tomada y enlazar `spike-capture-source.md`. Si se eligió un candidato distinto de A1, actualizar el `CaptureSourceToken` usado y el manifiesto previsto en el componente 12.

**Criterio de Completado:** `grep -n "condicionada a U0" .spectra/specs/extension-capture-preferences/design.md` no devuelve resultados y el PR de la evidencia incluye este cambio.

**Dependencias:** Tarea 0.1.

---

## Fase U1: Preferencias

### Tarea 1.1: RED de lectura y validación de preferencias (Propiedad 7)

**Archivo:** `extension/src/core/capture-preferences.test.ts` (nuevo)
**Acción:** Pruebas unitarias y fast-check (`numRuns: 200`) sobre `parseCapturePreferences(raw, options, defaults)` con `options` y `defaults` generados (`fc.uniqueArray(fc.integer({ min: 0, max: 600 }), { minLength: 1 })`): (a) para `fc.anything()` devuelve un objeto con `version: 1`, `countdownSeconds ∈ options` y `showFloatingIndicator` booleano; (b) ida y vuelta por `JSON.stringify/parse` de una preferencia válida devuelve la misma; (c) un campo inválido se sustituye por el del valor por defecto sin perder el otro campo válido; (d) `version: 2` devuelve `defaults`.

**Criterio de Completado:** `cd extension && npx vitest run src/core/capture-preferences.test.ts` falla en las aserciones porque el módulo no exporta la función todavía (stub que lanza `not implemented`, no error de importación).

**Dependencias:** Ninguna.

---

### Tarea 1.2: GREEN de `capture-preferences.ts`

**Archivo:** `extension/src/core/capture-preferences.ts` (nuevo)
**Acción:** Implementar `CAPTURE_PREFERENCES_KEY = "capturePreferences"`, la interfaz `CapturePreferences` y `parseCapturePreferences` exactamente como en `design.md` §Componentes 1. Exportar `COUNTDOWN_OPTIONS_SECONDS` y `DEFAULT_CAPTURE_PREFERENCES` como constantes con un comentario `// Owner decision P1 pending (extension-capture-preferences)`; su contenido lo fija la Tarea 1.5.

**Criterio de Completado:** `npx vitest run src/core/capture-preferences.test.ts` pasa; `npm run typecheck` sin errores.

**Dependencias:** Tarea 1.1.

---

### Tarea 1.3: RED + GREEN del almacén `chrome.storage.local` (Propiedad 6, parte de almacén)

**Archivo:** `extension/src/preferences-store.test.ts` (nuevo), `extension/src/preferences-store.ts` (nuevo)
**Acción:** Primero las pruebas, con `chrome.storage.local` simulado: `loadCapturePreferences` devuelve el valor parseado; `saveCapturePreferences` rechaza (`Promise` rechazada, sin escribir) una cuenta atrás fuera de las opciones; nunca se llama a `chrome.storage.sync`; `onCapturePreferencesChanged` solo reacciona a `areaName === "local"` y a la clave `capturePreferences`, y devuelve una función que quita el oyente. Después la implementación según `design.md` §Componentes 2.

**Criterio de Completado:** RED registrado antes de la implementación; luego `npx vitest run src/preferences-store.test.ts` pasa y una aserción comprueba que `chrome.storage.sync.set` no se llamó.

**Dependencias:** Tarea 1.2.

---

### Tarea 1.4: RED + GREEN del formulario en la página de opciones

**Archivo:** `extension/src/options/CapturePreferencesForm.test.tsx` (nuevo), `extension/src/options/CapturePreferencesForm.tsx` (nuevo), `extension/src/options/OptionsApp.tsx`
**Acción:** Pruebas con React Testing Library: un `combobox` con nombre accesible de cuenta atrás que lista las opciones inyectadas; un `checkbox` con nombre accesible para mostrar el indicador; cambiar cualquiera llama a `saveCapturePreferences` con el valor nuevo y muestra confirmación en `role="status"`; un error de guardado se muestra en `role="alert"` y no cambia el control. Implementar el formulario con tokens de `core/design/tokens.ts` y montarlo en `OptionsApp.tsx` debajo de la sección de micrófono, que no cambia.

**Criterio de Completado:** RED registrado; luego `npx vitest run src/options` pasa, `npm run typecheck` y `npm run build` pasan.

**Dependencias:** Tarea 1.3.

---

### Tarea 1.5: Fijar opciones y valores por defecto (bloqueada por P1)

**Archivo:** `extension/src/core/capture-preferences.ts`, `extension/src/core/capture-preferences.test.ts`
**Acción:** Con la respuesta del dueño a P1, rellenar `COUNTDOWN_OPTIONS_SECONDS` y `DEFAULT_CAPTURE_PREFERENCES`, quitar el comentario de pendiente y añadir una prueba que fije esos valores y que `DEFAULT_CAPTURE_PREFERENCES.countdownSeconds ∈ COUNTDOWN_OPTIONS_SECONDS`.

**Criterio de Completado:** La prueba nueva pasa; `grep -n "P1 pending" extension/src` no devuelve resultados; en la página de opciones construida aparecen exactamente las opciones decididas (captura de pantalla en el PR).

**Dependencias:** Tarea 1.2; respuesta del dueño a P1.

---

## Fase U2: Núcleo puro de la sesión

### Tarea 2.1: RED de la máquina de estados (Propiedades 1, 2, 4, 5 en modelo, 6)

**Archivo:** `extension/src/core/capture-session.test.ts` (nuevo), `extension/src/core/capture-session.property.test.ts` (nuevo)
**Acción:** Unitarias para cada flecha del diagrama de estados de `design.md` y para que todo evento no listado devuelva el mismo objeto (`toBe`). fast-check (`numRuns: 200`, secuencias de hasta 40 eventos con instantes crecientes): P1 fases válidas e invariantes de `segmentStartedAt`/`countdownEndsAt`; P2 `recording` solo tras `start_requested → source_acquired → countdown_elapsed`; P4 `elapsedRecordingMs` monótona, constante en `paused` y igual a la suma de tramos; P5 (modelo) desde `recording|paused`, cualquier orden de `stop/sharing_ended/tab_closed/cancel` lleva a un único estado de cierre (`stopping` o `cancelling`) y los eventos posteriores son no-ops; P6 `preferences` no cambia entre `start_requested` y la vuelta a `idle`. Unitarias de `shouldShowIndicator` (tabla de verdad: preferencia × fase × pestaña).

**Criterio de Completado:** `npx vitest run src/core/capture-session` llega a las aserciones y falla contra un stub.

**Dependencias:** Tarea 1.2 (solo el tipo `CapturePreferences`).

---

### Tarea 2.2: GREEN de `capture-session.ts`

**Archivo:** `extension/src/core/capture-session.ts` (nuevo)
**Acción:** Implementar tipos, `IDLE_SESSION`, `applyCaptureSessionEvent` (tabla de transiciones como en `core/capture.ts`), `elapsedRecordingMs` y `shouldShowIndicator` según `design.md` §Componentes 4, más `toPanelCaptureState(phase): CaptureState` (`recording|paused → "recording"`, `stopping|cancelling → "stopping"`, resto `"idle"`).

**Criterio de Completado:** `npx vitest run src/core/capture-session` pasa; `src/core/capture.test.ts` sigue pasando sin cambios.

**Dependencias:** Tarea 2.1.

---

### Tarea 2.3: RED + GREEN de mensajes y remitentes (Propiedad 10)

**Archivo:** `extension/src/core/capture-messages.property.test.ts` (nuevo), `extension/src/core/capture-messages.ts` (nuevo)
**Acción:** Pruebas fast-check sobre `isExtensionContextSender(sender, runtimeId, origin)` con remitentes generados (`id` propio o ajeno; `url` de la extensión, de `https://meet.google.com/…`, de otra web o ausente; con o sin `tab`): verdadero si y solo si `id === runtimeId` y `url` empieza por `origin`. Unitarias de `isCaptureControlMessage` para cada tipo de `CaptureControlMessage` y para los tipos de `ContentReport` (falso). Después implementar los tipos y las dos funciones según `design.md` §Componentes 5.

**Criterio de Completado:** RED registrado; luego `npx vitest run src/core/capture-messages.property.test.ts` pasa.

**Dependencias:** Tarea 2.2 (tipos compartidos).

---

### Tarea 2.4: RED + GREEN de la posición del indicador (Propiedad 11)

**Archivo:** `extension/src/core/indicator-position.property.test.ts` (nuevo), `extension/src/core/indicator-position.ts` (nuevo)
**Acción:** fast-check: para posición, tamaño y ventana generados (ventana ≥ tamaño + 16), `clampIndicatorPosition` deja el rectángulo dentro de la ventana con margen 8, es idempotente y no mueve una posición válida; `DEFAULT_INDICATOR_POSITION` es válida para toda ventana generada. Implementar después.

**Criterio de Completado:** RED registrado; luego la suite pasa con `numRuns: 200`.

**Dependencias:** Ninguna.

---

## Fase U3: Documento offscreen

### Tarea 3.1: RED de adquisición, cuenta atrás y continuidad de medios (Propiedades 3 y 8)

**Archivo:** `extension/src/offscreen.session.test.ts` (nuevo)
**Acción:** Con `MediaRecorder`, `AudioContext`, `getUserMedia`, `getCaptureHandle` y `chrome.runtime` simulados (patrón de `offscreen.capture.test.ts`) y `vi.useFakeTimers()`: `offscreen-acquire` sin pista de audio o de vídeo emite `capture-source-rejected` y para todas las pistas; con fuente válida emite `capture-source-acquired` con el `captureHandle` leído; `recorder.start` no se llama antes de `countdownMs` ni antes de que `capture-countdown-elapsed` reciba `{ ok: true }`, y nunca si la respuesta es `{ ok: false }` o llega `offscreen-cancel`; el `ended` de la pista de vídeo emite `capture-sharing-ended` (y en cuenta atrás, limpia el temporizador sin grabar). P8 con fast-check sobre secuencias de `offscreen-pause|resume|set-mic`: una instancia de `MediaRecorder`, `requestData` antes de cada `pause`, llamadas alternas, la pista de audio entregada a `MediaRecorder` no cambia. `offscreen-cancel` durante la grabación hace `stop()` y emite `capture-cancelled`, nunca `recording-stopped`. `offscreen-status` devuelve sesión, estado de la grabadora y `countdownEndsAt`.

**Criterio de Completado:** `npx vitest run src/offscreen.session.test.ts` llega a las aserciones y falla; `src/offscreen.capture.test.ts` se ejecuta y se registra su estado previo.

**Dependencias:** Tarea 2.3; Tarea 0.2 (fuente elegida).

---

### Tarea 3.2: RED del grafo de audio (Propiedad 8, pista fija)

**Archivo:** `extension/src/capture-graph.test.ts` (nuevo)
**Acción:** Con `AudioContext` simulado: `recordingStream` tiene exactamente una pista de audio (la del destino de mezcla) y la de vídeo de la pestaña, también sin micrófono; `setMicrophone(a)`, `setMicrophone(b)`, `setMicrophone(null)` desconectan y paran la pista anterior y no cambian `recordingStream.getTracks()`; un `getUserMedia` rechazado mantiene el micrófono anterior y propaga el error; el `ended` de la pista del micrófono llama al oyente de `onMicrophoneLost` y desconecta el nodo; con `monitorTabAudio: true` la fuente de pestaña se conecta a `audioContext.destination`, con `false` no; `dispose()` para todas las pistas propias y cierra el contexto.

**Criterio de Completado:** `npx vitest run src/capture-graph.test.ts` llega a las aserciones y falla.

**Dependencias:** Tarea 0.2 (valor de `monitorTabAudio`).

---

### Tarea 3.3: GREEN de `capture-graph.ts`

**Archivo:** `extension/src/capture-graph.ts` (nuevo)
**Acción:** Implementar `createCaptureGraph` según `design.md` §Componentes 6.

**Criterio de Completado:** `npx vitest run src/capture-graph.test.ts` pasa.

**Dependencias:** Tarea 3.2.

---

### Tarea 3.4: GREEN del offscreen

**Archivo:** `extension/src/offscreen.ts`, `extension/src/offscreen.capture.test.ts` (solo adaptar el arranque al nuevo comando si la prueba depende de `start-recording`; no debilitar aserciones)
**Acción:** Implementar los comandos de `design.md` §Componentes 7 usando `createCaptureGraph`; enumerar micrófonos tras adquirir la fuente y emitir `capture-mics`; emitir `capture-mic-lost`. Conservar `storeChunk`, `settleCapture`, el ensamblado, `recording-stopped`, `recording-error` y `stop-recording` (válido también desde pausa). Retirar el comando `start-recording` solo cuando U4 deje de enviarlo (coordinar en el mismo tren de integración; si U4 no está integrado, mantenerlo).

**Criterio de Completado:** `npx vitest run src/offscreen.session.test.ts src/offscreen.capture.test.ts src/capture-graph.test.ts` pasa; `npm run typecheck`, `npm run test` y `npm run build` pasan. El efecto en vivo del cambio de micrófono se acepta solo tras la respuesta a P5.

**Dependencias:** Tareas 3.1, 3.3.

---

## Fase U4: Service worker, registro durable y manifiesto

### Tarea 4.1: RED del estado `cancelled` y del disparador «dejar de compartir»

**Archivo:** `extension/src/recording-db.cancel.test.ts` (nuevo), `extension/src/core/recording-completion.test.ts`
**Acción:** Con `fake-indexeddb`: `cancelCapture` pasa `capturing → cancelled` y devuelve `true`; devuelve `false` y no cambia nada desde `finalizing`, `upload_pending` o con `captureError`; un registro `cancelled` no aparece en `getPendingFinalizations`, `getProcessingCompletions` ni `getPendingReviewLaunches`, y `getCapturingCompletion(tabId)` ya no lo devuelve; `claimCompletion(id, "sharing-stopped")` guarda `trigger: "sharing_stopped"` y un segundo `claimCompletion` con `"stop"` o `"captured-tab-close"` devuelve `false`. `DB_VERSION` sigue siendo 2 y un fixture v2 existente se abre sin migración.

**Criterio de Completado:** `npx vitest run src/recording-db.cancel.test.ts src/core/recording-completion.test.ts` llega a las aserciones nuevas y falla; las existentes siguen pasando.

**Dependencias:** Ninguna.

---

### Tarea 4.2: GREEN de `recording-db.ts` y `recording-completion.ts`

**Archivo:** `extension/src/recording-db.ts`, `extension/src/core/recording-completion.ts`
**Acción:** Añadir `"cancelled"` al estado, `"sharing_stopped"` al disparador guardado, `"sharing-stopped"` a `CompletionTrigger` y `cancelCapture` como transacción `completionTransaction("readwrite", …)`.

**Criterio de Completado:** Tarea 4.1 pasa; `npx vitest run src/recording-db src/core/recording-completion` y `npm run typecheck` pasan.

**Dependencias:** Tarea 4.1.

---

### Tarea 4.3: RED de la orquestación en el service worker (Propiedades 5, 6, 10, 12)

**Archivo:** `extension/src/background.capture-session.test.ts` (nuevo)
**Acción:** Con `chrome.*` simulado como en `background.recording-completion.test.ts` y `fake-indexeddb`: `capture-begin` con fase distinta de `idle` responde `{ ok: false }` y no envía `offscreen-acquire`; congela las preferencias leídas de `chrome.storage.local` y una escritura posterior no cambia la sesión en curso pero sí la siguiente (P6); `capture-source-acquired` con handle desconocido o pestaña no Meet envía `offscreen-cancel` y deja `lastError: "not_meet_tab"` sin registro; `capture-countdown-elapsed` crea el `RecordingCompletion` antes de responder `{ ok: true }`; `capture-sharing-ended`, `stop-capture` y `tabs.onRemoved` en cualquier orden producen un solo `stop-recording` (P5) y el mismo camino de subida que «Detener» con el indicador oculto (P12); `capture-cancelled` deja el registro en `cancelled`, limpia la insignia y no llama a `enqueueUpload` ni a `chrome.tabs.create`; un `CaptureControlMessage` cuyo `sender.url` es de Meet, o cuyo `sessionId` o `tab.id` no coincide, no cambia estado ni envía nada al offscreen, mientras que el mismo mensaje desde el iframe del indicador (`sender.url` de la extensión, `tab.id === capturedTabId`) sí (P10); `indicator-sync` se envía a la pestaña capturada solo cuando `shouldShowIndicator` cambia; al arrancar con `phase ≠ idle` y sin offscreen, aplica `failure("offscreen_unavailable")` y `settleCapture(id, true)`.

**Criterio de Completado:** `npx vitest run src/background.capture-session.test.ts` llega a las aserciones y falla; las suites `background.*.test.ts` existentes se ejecutan y se registra su estado.

**Dependencias:** Tareas 1.3, 2.2, 2.3, 4.2.

---

### Tarea 4.4: GREEN de `background.ts` y del manifiesto

**Archivo:** `extension/src/background.ts`, `extension/manifest.json`, `extension/src/manifest.test.ts`, `extension/vite.config.ts`
**Acción:** Implementar `design.md` §Componentes 8 sin cambiar `uploadRecording`, `processUploadQueue`, `reconcileProcessing` ni `reconcileReviewLaunches`. Sustituir la validación `if (_sender.tab && [...])` por `isExtensionContextSender` para los mensajes de control, conservando el rechazo actual de `recording-stopped`, `recording-error` y `capture-video-presence` desde pestañas. Manifiesto según §Componentes 12: permiso del candidato elegido en U0 (si es `desktopCapture`, tras la respuesta a P3), retirar `tabCapture` y `activeTab` si `grep -rn "tabCapture\|activeTab" extension/src --include=*.ts` ya no los usa, entrada de `web_accessible_resources` del indicador con `use_dynamic_url: true` y `matches` solo de Meet. Añadir la entrada `indicator` a `vite.config.ts`. Ampliar `manifest.test.ts`: sin nuevos `host_permissions`, la entrada del indicador solo para `https://meet.google.com/*`.

**Criterio de Completado:** `npx vitest run src/background src/manifest.test.ts` pasa; `npm run typecheck`, `npm run test` y `npm run build` pasan; `dist/manifest.json` contiene la entrada del indicador.

**Dependencias:** Tarea 4.3; Tarea 0.2; respuesta a P3 si aplica.

---

### Tarea 4.5: Disposición de lo grabado al cancelar (bloqueada por P2)

**Archivo:** `extension/src/background.ts`, `extension/src/background.capture-session.test.ts`
**Acción:** Con la respuesta del dueño a P2, aplicar la disposición en el manejador de `capture-cancelled` (p. ej. `clearSession(sessionId)` si se decide borrar) y, de acuerdo con `recording-notes`, la de las notas pendientes de esa sesión. Primero la prueba que fija el comportamiento decidido.

**Criterio de Completado:** La prueba nueva falla antes y pasa después; la decisión del dueño está citada en el PR.

**Dependencias:** Tarea 4.4; respuesta del dueño a P2; para notas, `recording-notes` T8.

---

## Fase U5: Panel lateral

### Tarea 5.1: RED del inicio con selector y del estado visible

**Archivo:** `extension/src/panel/SidePanelApp.test.tsx`, `extension/src/panel/components/CaptureControls.test.tsx`
**Acción:** Pruebas: pulsar grabar llama al selector del candidato elegido dentro del manejador de clic y, con un `streamId`, envía `capture-begin` con el micrófono seleccionado; con un `streamId` vacío envía `capture-selection-cancelled` y no cambia a grabando (Req 2.2); con `captureSession.phase === "countdown"` muestra los segundos restantes a partir de `countdownEndsAt`; en `paused` muestra «en pausa» y el temporizador no avanza (temporizadores falsos); `lastError` se muestra en `role="alert"`; no aparecen botones de pausar ni cancelar en el panel. Las pruebas existentes del panel siguen pasando.

**Criterio de Completado:** Las pruebas nuevas llegan a las aserciones y fallan.

**Dependencias:** Tareas 2.2, 2.3, 0.2.

---

### Tarea 5.2: GREEN del panel

**Archivo:** `extension/src/panel/SidePanelApp.tsx`, `extension/src/panel/components/CaptureControls.tsx`
**Acción:** Implementar `design.md` §Componentes 10; el temporizador usa `elapsedRecordingMs` y el estado del panel se deriva con `toPanelCaptureState`.

**Criterio de Completado:** `npx vitest run src/panel` pasa; `npm run typecheck`, `npm run test` y `npm run build` pasan.

**Dependencias:** Tarea 5.1.

---

## Fase U6: Indicador flotante

### Tarea 6.1: RED del host en el content script (Propiedad 9)

**Archivo:** `extension/src/indicator/host.test.ts` (nuevo), `extension/src/content.preservation.test.ts`
**Acción:** En jsdom: `indicator-sync { visible: true }` crea un único `#sauri-indicator-host` en `document.documentElement` con shadow root cerrado y un `iframe` cuyo `src` es `chrome.runtime.getURL("src/indicator/index.html")`; `visible: false` lo elimina; mensajes repetidos no duplican; al cargar envía `indicator-query`; arrastrar el asa (Pointer Events) y las flechas del teclado mueven el host y al soltar envían `indicator-moved` con una posición limitada a la ventana; `resize` vuelve a limitarla; `countdown-overlay` muestra y retira la superposición con un único anuncio `aria-live="polite"`; `indicator/host.ts` no llama a `document.querySelector` ni a `querySelectorAll` (espía); el content script no envía ningún `CaptureControlMessage`. Las pruebas de detección y del aviso existentes en `content.preservation.test.ts` siguen pasando.

**Criterio de Completado:** `npx vitest run src/indicator/host.test.ts` llega a las aserciones y falla.

**Dependencias:** Tareas 2.3, 2.4, 0.2 (iframe o respaldo).

---

### Tarea 6.2: GREEN del host y del content script

**Archivo:** `extension/src/indicator/host.ts` (nuevo), `extension/src/content.ts`
**Acción:** Implementar `design.md` §Componentes 11 (host). En `content.ts`, solo importar el host, enrutar `indicator-sync`, `countdown-overlay` y `capture-handle-refresh`, y fijar el Capture Handle al cargar (D4). No cambiar la detección de reunión ni el aviso.

**Criterio de Completado:** `npx vitest run src/indicator src/content` pasa; `npm run typecheck` pasa.

**Dependencias:** Tarea 6.1.

---

### Tarea 6.3: RED de la página del indicador (controles y accesibilidad)

**Archivo:** `extension/src/indicator/IndicatorApp.test.tsx` (nuevo)
**Acción:** Con `chrome.storage.session` y `chrome.runtime` simulados: muestra temporizador `role="timer"` calculado con `elapsedRecordingMs` (congelado en pausa); botón Pausar en `recording` y Reanudar en `paused`, cada uno envía su mensaje con el `sessionId` vigente; Detener envía `stop-capture`; Cancelar pide una confirmación en línea y solo entonces envía `capture-cancel`; el `select` de micrófono lista `micOptions` más «Sin micrófono» y envía `capture-set-mic`; `capture-mic-lost` muestra un aviso; todos los controles tienen nombre accesible y son alcanzables con Tab; con `phase` fuera de `recording|paused` no muestra controles.

**Criterio de Completado:** `npx vitest run src/indicator/IndicatorApp.test.tsx` llega a las aserciones y falla.

**Dependencias:** Tareas 2.2, 2.3.

---

### Tarea 6.4: GREEN de la página del indicador

**Archivo:** `extension/src/indicator/IndicatorApp.tsx`, `extension/src/indicator/index.tsx`, `extension/src/indicator/index.html` (nuevos)
**Acción:** Implementar según `design.md` §Componentes 11 y §Accesibilidad con los tokens existentes (`tokens.css`), objetivos de 32 × 32 px y `prefers-reduced-motion`. Sin botón de notas (lo añade U7).

**Criterio de Completado:** `npx vitest run src/indicator` pasa; `npm run typecheck`, `npm run test` y `npm run build` pasan (requiere la entrada de Vite de la Tarea 4.4; si U4 no está integrado, el build se verifica en U8).

**Dependencias:** Tarea 6.3.

---

## Fase U7: Entrada de notas desde el indicador

### Tarea 7.1: RED de la entrada de notas en el indicador visible

**Archivo:** `extension/src/indicator/IndicatorNotes.test.tsx` (nuevo)
**Acción:** Con el `RecordingNoteInput` y `addRecordingNote` de `recording-notes` (sus tareas T8 y T10): el botón Notas solo aparece con el indicador visible y `phase ∈ {recording, paused}` (Req 3.9); abre la entrada de notas dentro del iframe de la extensión; la nota se guarda con el destino `pending_capture` de la sesión vigente; el texto nunca se envía al content script ni al DOM de Meet (espía de `chrome.tabs.sendMessage` y del host). No se añade ningún acceso a notas con el indicador oculto (P4).

**Criterio de Completado:** `npx vitest run src/indicator/IndicatorNotes.test.tsx` llega a las aserciones y falla.

**Dependencias:** Tarea 6.4; `recording-notes` T8 y T10 integradas.

---

### Tarea 7.2: GREEN de la entrada de notas

**Archivo:** `extension/src/indicator/IndicatorNotes.tsx` (nuevo), `extension/src/indicator/IndicatorApp.tsx`
**Acción:** Montar el botón Notas y el área expandida (iframe 320 × 260 px, comunicado al host con `indicator-sync`) reutilizando el componente de `recording-notes`; no crear un segundo almacén de notas.

**Criterio de Completado:** `npx vitest run src/indicator` pasa; `npm run typecheck`, `npm run test` y `npm run build` pasan.

**Dependencias:** Tarea 7.1.

---

## Fase U8: Integración y validación

### Tarea 8.1: Prueba extremo a extremo de controles de captura

**Archivo:** `extension/tests/e2e/capture-controls.spec.ts` (nuevo), `extension/tests/e2e/global-setup.ts` (solo si hace falta pasar la bandera de autoselección)
**Acción:** Con la extensión construida, Chrome lanzado con la bandera de autoselección hallada en U0 y una página sintética servida en `https://meet.google.com/sauri-e2e` mediante `context.route`: (1) guardar preferencias en la página de opciones y comprobar que la siguiente sesión las usa; (2) no existe ningún trozo en IndexedDB antes de que venza la cuenta atrás; (3) pausar 3 s y reanudar desde el iframe del indicador: el temporizador queda congelado y la sesión sigue; (4) cancelar: registro `cancelled` y ninguna petición a `/api/v1/ingestion/upload`; (5) indicador oculto: no existe `#sauri-indicator-host` y, al parar la pista compartida, el registro sigue el mismo camino que «Detener» hasta la ingesta del backend desechable de `global-setup.ts`.

**Criterio de Completado:** `cd extension && npm run build && npm run test:e2e -- capture-controls` pasa con Docker Desktop activo; `capture-to-ingestion.spec.ts` sigue pasando. Si el entorno no lo permite, se reporta `NO VERIFICADO` con el motivo.

**Dependencias:** U1–U6 integradas.

---

### Tarea 8.2: Comprobación manual en Chrome real con capturas

**Archivo:** `.spectra/specs/extension-capture-preferences/validation.md` (nuevo; capturas fuera del repositorio, en la carpeta privada del dueño, con su ruta citada)
**Acción:** Con `extension/dist` desempaquetada y una reunión de Meet de prueba: cambiar preferencias; grabar eligiendo la pestaña en el selector de Chrome; ver la cuenta atrás; con indicador visible, moverlo con ratón y teclado, pausar, reanudar, cambiar de micrófono, detener y comprobar que la grabación llega al portal y se transcribe; repetir con cancelar; con indicador oculto, terminar con «Dejar de compartir» y comprobar el mismo resultado; recargar la pestaña durante la grabación y ver que el indicador vuelve.

**Criterio de Completado:** `validation.md` lista cada paso con resultado, versión de Chrome, commit probado y la referencia de su captura; ningún paso queda sin resultado.

**Dependencias:** Tarea 8.1 (o U1–U6 integradas si 8.1 quedó `NO VERIFICADO`).

---

### Tarea 8.3: Cierre de la spec

**Archivo:** `.spectra/README.md`, `.spectra/specs/extension-capture-preferences/.config.spectra`
**Acción:** Actualizar el estado de la spec en el índice con lo integrado, lo verificado y lo pendiente (preguntas del dueño sin responder, U7 si depende de `recording-notes`). No declarar aceptación de producto: esa la da el dueño.

**Criterio de Completado:** El índice refleja el estado real y enlaza `validation.md`.

**Dependencias:** Tarea 8.2.

---

## Correspondencia propiedades → tareas de prueba

| Propiedad (`design.md`) | Tarea de prueba |
|---|---|
| 1 Clausura de la máquina | 2.1 |
| 2 Sin grabación sin selección | 2.1, 4.3, 8.1 |
| 3 Cuenta atrás antes de grabar | 3.1, 8.1 |
| 4 Temporizador honesto | 2.1, 5.1, 6.3 |
| 5 Un único desenlace | 2.1, 4.1, 4.3, 8.1 |
| 6 Preferencias congeladas | 1.3, 2.1, 4.3, 8.1 |
| 7 Lectura total de preferencias | 1.1 |
| 8 Continuidad de medios | 3.1, 3.2, 0.1 (duración real) |
| 9 Visibilidad del indicador | 2.1, 6.1, 8.1 |
| 10 Confianza del remitente | 2.3, 4.3 |
| 11 Posición siempre visible | 2.4, 6.1 |
| 12 Modo oculto termina al dejar de compartir | 4.3, 8.1, 8.2 |

## Preguntas para el dueño

1. **¿Qué opciones de cuenta atrás y cuál por defecto? ¿El indicador viene activado?** Recomiendo 0, 3, 5 y 10 segundos, 3 por defecto, e indicador activado.
2. **Al cancelar, ¿qué hacemos con lo ya grabado y las notas de esa grabación?** Recomiendo borrarlo del equipo al momento y no enviar nada.
3. **¿Aceptas el permiso nuevo de Chrome para usar su propio selector de pestañas y su botón «Dejar de compartir»?** Recomiendo aceptarlo; solo se ofrecerán pestañas y se retiran dos permisos actuales.
4. **Con el indicador oculto, ¿cómo llegar a las notas?** Sigue abierto; recomiendo usar el panel lateral mientras lo decides, sin crear un control oculto.
5. **¿El cambio de micrófono a mitad de grabación se aplica al instante?** Recomiendo que sí, sin recordarlo para la próxima vez.
