# Plan de Implementación — Portal web mínimo de Sauri (tratamiento visual Terra)

> Escrito el 2026-11-14. **La implementación empieza solo después de que Fer revise este plan.** Documentación terminada no es código ni aceptación de producto.

## Estado y contrato

Cada unidad (`PV0`…`PV13`) es un issue, una rama y un worktree propios desde `origin/main` en `.worktrees/`, implementada por Codex o un subagente y revisada, verificada e integrada por el orquestador. Una unidad se cierra solo con:

- `cd frontend && npm run typecheck && npm run test && npm run build` en verde (si toca TypeScript del portal).
- Si toca backend: `cd backend && uv run --extra dev pytest <pruebas de la unidad>`, `uv run --extra dev ruff check <archivos>` y `uv run --extra dev mypy <archivos>` sin diagnósticos nuevos. Nunca ejecutar `test_pipeline_e2e.py` (borra la base compartida). PostgreSQL/RabbitMQ solo en instancias desechables `sauri-qa-*` en `127.0.0.1`, eliminadas al terminar; nunca el proyecto Compose `sauri` ni sus volúmenes.
- Si toca la extensión: `cd extension && npm run typecheck && npm run test && npm run build`.
- Recorrida en el navegador integrado contra `cd frontend && npm run dev` (http://localhost:5173) con datos sintéticos o del entorno local del dueño en solo lectura, con **captura de pantalla** adjunta al PR de cada pantalla tocada. La recorrida no sustituye las pruebas.
- Todo texto visible en español vive en `frontend/src/copy/`; el verificador de idioma (`.githooks/pre-commit`) pasa sin eludirse.
- Lo no ejecutado se reporta como `NO VERIFICADO`.

**Reglas que valen para todas las unidades** (no se repiten en cada tarea):

1. `docs/design/stitch/` es inspiración visual no normativa: se toman colores, tipografía, radios y sensación general; **no** sus textos, cifras, controles, estados ni composiciones (lista de exclusiones en su §8).
2. No se construye: búsqueda full-text entre reuniones, edición del texto de la transcripción, chat interactivo, métricas de tiempo de habla, tarjetas de conteos/KPI, paginación, selección múltiple, exportar CSV, archivar, «Copiar diagnóstico», insignias de seguridad o calidad, SSO/Google/Microsoft, «recordar dispositivo», «¿Olvidaste tu contraseña?», límites de formato/tamaño/duración en la carga, línea de pasos de procesamiento, velocidad o tiempo restante de subida, cancelar subida, supervivencia de la subida al cerrar la pestaña.
3. El estilo del login no cambia la llamada `login(email, password)`, la clave `sauri_token` en `localStorage`, el evento `sauri:unauthorized` ni ningún permiso.
4. Toda llamada HTTP pasa por `frontend/src/api.ts`.
5. Sin datos ficticios en pantalla: vacío solo con respuesta vacía real; los errores muestran el problema real en lenguaje claro.
6. Modo claro único (Terra no define modo oscuro). Sin dependencias de red externas en tiempo de ejecución (fuentes empaquetadas localmente; nada de CDN).

## Estado actual (verificado en `origin/main` 2191914, 2026-11-14)

**Lo que ya existe en el portal:**

- `frontend/src/App.tsx`: conmutador de vistas con `useState` (`list`, `transcript`, `upload`, `speaker-test`), sin router ni rutas en la URL; lee `?meetingId=` al cargar para abrir una reunión (lo usa la extensión, `extension/src/background.ts` `reviewDestination`). Puerta de acceso por `sauri_token`, cierre de sesión y retorno al login con `sauri:unauthorized`. Encabezado y botones con texto en inglés fijo («Commercial meeting intelligence platform», «Log out», «Back to meetings», «Open speaker recognition test»). En la lista también muestra `RegisterForm` (registrar un enlace de Google Meet, en inglés) y un acceso a `SpeakerRecognitionTestScreen` (pantalla de prueba).
- No hay ningún archivo CSS en `frontend/src/`; todo el estilo es inline (`style={{…}}`) y colores fijos. `frontend/index.html` tiene título «sauri».
- `components/SpeakerTestLogin.tsx`: correo y contraseña, llama `login()` y guarda `sauri_token`; textos en inglés («Sign in», «Log in», «Sign-in failed…»).
- `components/MeetingList.tsx`: tabla con título, fecha (formato `en`), estado con colores fijos y botón «Open»; orden más reciente primero dado por el backend (`order_by(created_at desc)`); sin búsqueda, filtros, orden, renombrar ni eliminar; textos en inglés.
- `components/UploadView.tsx` (core U6): selector de archivo `audio/*,video/*`, lectura de duración, «Subir y procesar», progreso real por bytes con `XMLHttpRequest` (`uploadWithProgress`), mensaje de error claro con «Reintentar» conservando archivo, `meeting_id` y clave de idempotencia; sin «Copiar diagnóstico». Al terminar abre la reunión con el `meeting_id` **generado localmente**: la respuesta de `POST /api/v1/ingestion/upload` es `{recording_id, state}` y no devuelve `meeting_id` (`backend/app/ingestion/router.py`, tres `return`). No envía `title`; el backend lo deriva del nombre del archivo (`resolve_upload_title`). Sin estilo.
- `components/TranscriptView.tsx` + `MeetingPlaybackView.tsx` + `PlaybackController.ts` (core U7/U9 y spec de reproducción): reproductor arriba con controles propios de pausa, reproducir, búsqueda, velocidad, volumen, silencio y calidad (cuando hay varias fuentes); turnos con hora, etiqueta de hablante coloreada y texto; resaltado y desplazamiento del turno activo; clic en un turno salta y reproduce; estado de procesamiento real (`ProcessingStatus`); revisión de hablantes debajo (escuchar, nombrar, confirmar, corregir; solo cambia la atribución). Pestañas actuales **«Transcripción» | «Resumen»** (no las aprobadas «Chat» | «Notas y resumen»). Textos en inglés fijos: «← Back to list», «Transcript», línea técnica «Language | Provider | Turns», etiquetas accesibles y errores del reproductor («Pause», «Seek», «Unable to load meeting media.»…).
- `components/SummaryPanel.tsx` (core U7.2): borrador con tema, puntos clave y fuentes que saltan al turno; estados pendiente/generando/fallido con «Reintentar»; vacío con «Generar resumen»; **«Copiar»**. **No hay descarga** del resumen.
- `frontend/src/copy/es.ts`: un solo objeto `copy` con `processing`, `transcript`, `speakerReview`, `summary`, `upload`.
- Backend disponible: `PATCH /api/v1/meetings/{id}` (renombrar, `{title}`), `DELETE /api/v1/meetings/{id}`, `GET /meetings/{id}/playback` (URLs de medios), `GET /meetings/{id}/transcript`, `GET /meetings/{id}/summary`. El cliente `api.ts` **no** tiene funciones de renombrar ni eliminar.
- No existen en backend ni portal: empresa, proyecto, participantes, etiquetas ni notas (`Meeting` solo tiene `title`, `meet_link`, `origin`, estado y fechas).
- Extensión: abre `PORTAL_URL?meetingId=…` cuando el procesamiento termina con éxito (`processing_succeeded`), no al detener la captura.

**Lo que este spec todavía exige:**

| Capacidad | Fase de producto | Unidad |
|---|---|---|
| Tokens Terra, hoja global, fuentes locales, textos por pantalla | Base | PV0 |
| Rutas `/`, `/upload`, `/meetings/:meetingId` (History API) y shell con navegación | Base | PV1 |
| Primitivas visuales compartidas | Base | PV2 |
| Login con estilo, misma autenticación | Fase 1 | PV3 |
| Biblioteca con estilo, estados cargando/vacío/error | Fase 1 | PV4 |
| Carga con estilo y apertura con `meeting_id` confirmado por el servidor | Fase 1 | PV5 |
| Vista de reunión: reproductor sobre transcripción y panel lateral «Notas y resumen» + «Chat» (solo pestaña) | Fase 1 | PV6 |
| Resumen descargable | Fase 1 | PV7 |
| Apertura automática al detener la captura / terminar Meet | Fase 1 | PV8 |
| Búsqueda, filtro por fecha y orden en la biblioteca | Fase 2 | PV9 |
| Renombrar y eliminar | Fase 2 | PV10 |
| Descargar video y transcripción | Fase 2 | PV11 |
| Empresa, proyecto, participantes y etiquetas (backend y portal) | Fase 2 | PV12, PV13 |

Renombrar hablantes desde la transcripción (Fase 2) ya está cubierto por la revisión de hablantes de core U9; aquí solo recibe estilo (PV6).

## Resumen de Fases

| Fase | Unidades | Descripción | Dependencias | Paralelas |
|------|----------|-------------|--------------|-----------|
| A | PV0 | Base visual Terra y textos por pantalla | Ninguna | — |
| B | PV1, PV2 | Router + shell; primitivas UI | PV0 | PV1 ∥ PV2 |
| C | PV3, PV4, PV5, PV6, PV7, PV8 | Fase 1 de producto: login, biblioteca, carga, reunión, resumen, apertura automática | PV1 y PV2 (PV8 solo PV1) | todas entre sí |
| D | PV9, PV10, PV11 | Fase 2: buscar/filtrar/ordenar; renombrar/eliminar; descargas | PV4 (PV9), PV6 (PV10), PV10 (PV11) | PV9 ∥ PV10; PV9 ∥ PV11 |
| E | PV12 → PV13 | Fase 2: metadatos y etiquetas | Adenda de diseño + respuesta del dueño (pregunta 4); PV9, PV10 | PV12 ∥ fase D |

Archivos por unidad (para que no se pisen): cada unidad edita solo su componente, su hoja `frontend/src/styles/<superficie>.css` y su módulo `frontend/src/copy/<superficie>.ts`. `frontend/src/api.ts` lo tocan PV5, PV10 y PV13 en funciones distintas; PV5 y PV10 no corren a la vez sobre el mismo bloque (PV5 cambia tipos de subida; PV10 añade funciones nuevas al final).

---

## Fase A: Base

### Unidad PV0: Base visual Terra y textos por pantalla

#### Tarea PV0.1: Hoja global con tokens Terra

**Archivo:** `frontend/src/index.css` (crear), `frontend/src/main.tsx`
**Acción:** Crear `index.css` con un bloque `:root` de tokens semánticos y estilos base, e importarlo en `main.tsx` (`import "./index.css";` antes de `App`). Tokens y valores:
```css
--color-primary: #4a7c59; --color-on-primary: #ffffff;
--color-primary-container: #78a886; --color-primary-fixed: #c8e8d0;
--color-secondary: #6b6358; --color-secondary-container: #f0e8db;
--color-tertiary: #705c30; --color-tertiary-container: #f4e7c7;
--color-surface: #faf6f0; --color-surface-lowest: #ffffff;
--color-surface-low: #f5f1ea; --color-surface-container: #f0ece4;
--color-surface-high: #eae6de; --color-on-surface: #2e3230;
--color-on-surface-variant: #4a4e4a; --color-outline: #74796e;
--color-outline-variant: #c4c8bc; --color-error: #b83230;
--color-error-container: #fce8e6; --color-on-error-container: #690005;
--color-highlight: #f4e7c7;            /* turno activo */
--speaker-1: #4a7c59; --speaker-2: #9a5b2e; --speaker-3: #3f6a8a;
--speaker-4: #7a4f7f; --speaker-5: #8a6d1f; --speaker-6: #2f7a74;
--speaker-unresolved: #74796e;
--radius-sm: 8px; --radius-md: 12px; --radius-xl: 16px; --radius-2xl: 20px; --radius-full: 9999px;
--shadow-card: 0 4px 20px rgba(46,50,48,0.06);
--font-heading: "Literata", Georgia, serif;
--font-body: "Nunito Sans", system-ui, sans-serif;
--font-mono: "JetBrains Mono", ui-monospace, monospace;
--space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-6: 24px; --space-8: 32px;
```
Estilos base: `body` con `background: var(--color-surface)`, `color: var(--color-on-surface)`, `font-family: var(--font-body)`, `line-height: 1.6`, `margin: 0`; `h1, h2, h3` con `var(--font-heading)`; `:focus-visible` con anillo `2px solid var(--color-primary)` y `outline-offset: 2px`; `button, input, select` heredan fuente. Sin manchas difuminadas de fondo en esta tarea (las añade el shell si se quiere, con CSS puro).
**Criterio de Completado:** `npm run build` incluye el CSS en `dist/assets/`; en el navegador el fondo de la página es `#faf6f0` y el texto del cuerpo usa Nunito Sans (comprobado con las herramientas del navegador); captura adjunta.
**Dependencias:** Ninguna

#### Tarea PV0.2: Fuentes empaquetadas localmente

**Archivo:** `frontend/package.json`, `package-lock.json`, `frontend/src/index.css`
**Acción:** Añadir como dependencias `@fontsource/literata`, `@fontsource/nunito-sans` y `@fontsource/jetbrains-mono` (versiones estables actuales, fijadas en el lockfile) e importar al inicio de `index.css` solo los pesos usados: Literata 600, Nunito Sans 400/600/700, JetBrains Mono 400. No usar Google Fonts ni otro CDN.
**Criterio de Completado:** con la red del navegador inspeccionada en la recorrida, ninguna petición sale a un dominio distinto de `localhost`; `npm run build` copia los `.woff2` a `dist/assets/`.
**Dependencias:** PV0.1

#### Tarea PV0.3: Partir los textos por superficie sin cambiar su uso

**Archivo:** `frontend/src/copy/es.ts`, `frontend/src/copy/processing.ts`, `copy/transcript.ts`, `copy/speakerReview.ts`, `copy/summary.ts`, `copy/upload.ts` (crear), `copy/shell.ts`, `copy/login.ts`, `copy/library.ts`, `copy/meeting.ts` (crear vacíos con `export const <name> = {} as const;`)
**Acción:** Mover cada bloque actual del objeto `copy` a su archivo (`export const processing = {…} as const;`, etc.) y dejar `es.ts` como composición: `export const copy = { processing, transcript, speakerReview, summary, upload, shell, login, library, meeting } as const;`. Los importadores siguen usando `copy.<bloque>.<clave>` sin cambios. Los archivos nuevos los rellenan las unidades siguientes, cada una solo el suyo.
**Criterio de Completado:** `npm run typecheck && npm run test` verdes sin tocar ningún componente; `git diff --stat` solo muestra archivos de `frontend/src/copy/`.
**Dependencias:** Ninguna

#### Tarea PV0.4: Título del documento

**Archivo:** `frontend/index.html`
**Acción:** Cambiar `<title>sauri</title>` por `<title>Sauri</title>`.
**Criterio de Completado:** la pestaña del navegador muestra «Sauri».
**Dependencias:** Ninguna

---

## Fase B: Router, shell y primitivas (PV1 ∥ PV2)

### Unidad PV1: Router mínimo con History API y shell del portal

#### Tarea PV1.1: Módulo de rutas

**Archivo:** `frontend/src/router.ts` (crear), `frontend/src/router.test.ts` (crear)
**Acción:** Implementar sin dependencias nuevas:
```ts
export type Route =
  | { name: "library" }
  | { name: "upload" }
  | { name: "meeting"; meetingId: string }
  | { name: "notFound" };
export function parseRoute(pathname: string, search: string): Route;
// "/" -> library; "/upload" -> upload; "/meetings/<id>" -> meeting (id con decodeURIComponent);
// "/" con ?meetingId=<id> -> meeting (compatibilidad con la extensión); otro -> notFound.
export function routePath(route: Route): string; // inverso; codifica el id con encodeURIComponent
export function navigate(route: Route, options?: { replace?: boolean }): void; // history.pushState/replaceState + dispatch "sauri:navigate"
export function useRoute(): Route; // hook: escucha "popstate" y "sauri:navigate"
```
Cuando `parseRoute` resuelve `?meetingId=`, `useRoute` reemplaza la URL por `/meetings/<id>` con `replaceState` (sin recargar). Ninguna ruta lleva tokens ni contenido.
**Criterio de Completado:** `npx vitest run src/router.test.ts` verde con casos: las cuatro rutas, ida y vuelta `parseRoute(routePath(r))`, id con caracteres especiales, `?meetingId=` reemplazado, botón atrás (`popstate`) actualiza el hook.
**Dependencias:** PV0

#### Tarea PV1.2: Renombrar los componentes de acceso y biblioteca

**Archivo:** `frontend/src/components/SpeakerTestLogin.tsx` → `LoginScreen.tsx`, `SpeakerTestLogin.test.tsx` → `LoginScreen.test.tsx`, `MeetingList.tsx` → `RecordingLibrary.tsx`, `MeetingList.test.tsx` → `RecordingLibrary.test.tsx`
**Acción:** `git mv` de los cuatro archivos; renombrar los componentes exportados (`LoginScreen`, `RecordingLibrary`) y sus importaciones. Sin otros cambios de comportamiento ni de estilo.
**Criterio de Completado:** `grep -rn "SpeakerTestLogin\|MeetingList\b" frontend/src` sin resultados (salvo el tipo `MeetingListItem`); pruebas verdes.
**Dependencias:** Ninguna

#### Tarea PV1.3: Shell del portal

**Archivo:** `frontend/src/components/PortalShell.tsx` (crear), `PortalShell.test.tsx` (crear), `frontend/src/styles/shell.css` (crear), `frontend/src/copy/shell.ts`
**Acción:** Barra superior con la marca «Sauri» (texto, `var(--font-heading)`), enlaces «Biblioteca» (`/`) y «Subir grabación» (`/upload`) que usan `navigate` (con `href` real para abrir en otra pestaña), y botón «Cerrar sesión» que llama el `onLogout` recibido. Marca el enlace activo con `aria-current="page"`. Debajo, `<main>` con ancho máximo 1200 px y `children`. Textos en `copy/shell.ts`. Nada más en la barra (sin búsqueda global, indicador «Sincronizado», menú de usuario ni pie de página del mock).
**Criterio de Completado:** prueba: los dos enlaces navegan sin recargar y «Cerrar sesión» llama `onLogout`; no existe ningún otro botón o enlace en la barra.
**Dependencias:** PV1.1, PV0.3

#### Tarea PV1.4: `App.tsx` con rutas

**Archivo:** `frontend/src/App.tsx`, `frontend/src/App.test.tsx`, `frontend/src/App.review-route.test.tsx`
**Acción:** Sustituir el estado `view` por `useRoute()`. Sin sesión: renderizar `LoginScreen` (conservando la ruta pedida para continuar tras entrar). Con sesión: `PortalShell` con `library` → `RecordingLibrary` (`onSelectMeeting` navega a `/meetings/:id`), `upload` → `UploadView` (`onUploaded(id)` navega a `/meetings/:id`, `onBack` a `/`), `meeting` → `TranscriptView` (`onBack` a `/`), `notFound` → mensaje de `copy.shell.notFound` con enlace a la biblioteca. Cerrar sesión mantiene el comportamiento actual (borra `sauri_token`) y navega a `/`. Retirar del portal `RegisterForm` y el acceso a `SpeakerRecognitionTestScreen` **solo si Fer lo aprueba (pregunta 2)**; si no, añadirlos como rutas `/register` y `/speaker-test` sin estilo nuevo. Quitar los textos fijos en inglés del encabezado.
**Criterio de Completado:** pruebas actualizadas y verdes: abrir `/?meetingId=m1` muestra la reunión m1 y la URL queda `/meetings/m1`; `/meetings/m1` sin sesión muestra el login y, tras entrar, la reunión m1; atrás del navegador vuelve a la biblioteca; un 401 (`sauri:unauthorized`) vuelve al login. En el navegador: recargar en `/upload` y en `/meetings/<id>` abre esa pantalla (Vite y `frontend/nginx.conf` ya sirven `index.html` para cualquier ruta). Capturas.
**Dependencias:** PV1.1, PV1.2, PV1.3

### Unidad PV2: Primitivas UI compartidas

#### Tarea PV2.1: Componentes base

**Archivo:** `frontend/src/components/ui/Button.tsx`, `Card.tsx`, `TextField.tsx`, `Tabs.tsx`, `StatusBadge.tsx`, `ConfirmDialog.tsx`, `ProgressBar.tsx`, `index.ts` (crear todos), `frontend/src/components/ui/ui.css` (crear)
**Acción:** Componentes sin texto propio (todo el texto llega por props):
- `Button`: `variant: "primary" | "secondary" | "ghost" | "danger"`, pasa el resto de props a `<button type="button">` por defecto; primario verde sólido radio 12 px, secundario crema con borde fino y texto verde; estado `disabled` visible.
- `Card`: `<section>` con fondo `--color-surface-lowest`, padding 24 px, borde `--color-outline-variant`, radio 16 px.
- `TextField`: `<label>` + `<input>` asociados por `id`; prop `error` muestra el texto con `role="alert"` y `aria-invalid`.
- `Tabs`: `tabs: {id, label}[]`, `activeId`, `onChange`, `panel` por pestaña; patrón WAI-ARIA (`role="tablist"`, `tab`, `tabpanel`, flechas izquierda/derecha, Inicio/Fin) igual al de `TranscriptView` actual.
- `StatusBadge`: píldora con `tone: "neutral" | "progress" | "success" | "error"`.
- `ConfirmDialog`: `<dialog>` modal con `title`, `body`, `confirmLabel`, `cancelLabel`, `onConfirm`, `onCancel`; foco inicial en cancelar; Escape cancela.
- `ProgressBar`: `<progress>` con `value` opcional (indeterminado si falta) y `label` accesible.
Estilos en `ui.css` usando solo tokens de `index.css`.
**Criterio de Completado:** `grep -n "#[0-9a-fA-F]\{3,6\}" frontend/src/components/ui/` sin resultados.
**Dependencias:** PV0.1

#### Tarea PV2.2: Pruebas de primitivas

**Archivo:** `frontend/src/components/ui/ui.test.tsx` (crear)
**Acción:** Probar: navegación por teclado y `aria-selected` de `Tabs`; `ConfirmDialog` llama `onConfirm` solo con el botón de confirmar y `onCancel` con Escape; `TextField` asocia la etiqueta y expone el error; `ProgressBar` sin `value` es indeterminado.
**Criterio de Completado:** `npx vitest run src/components/ui` verde.
**Dependencias:** PV2.1

---

## Fase C: Fase 1 de producto (PV3 ∥ PV4 ∥ PV5 ∥ PV6 ∥ PV7 ∥ PV8)

### Unidad PV3: Login con estilo, misma autenticación

#### Tarea PV3.1: Presentación del login

**Archivo:** `frontend/src/components/LoginScreen.tsx`, `frontend/src/styles/login.css` (crear), `frontend/src/copy/login.ts`
**Acción:** Tarjeta centrada (máx. 480 px) con la marca «Sauri», título «Iniciar sesión», campos «Correo» y «Contraseña» (`TextField`), botón primario «Entrar» / «Entrando…» mientras espera, y error «No se pudo iniciar sesión. Revisa tus datos e inténtalo de nuevo.» con `role="alert"`. Conservar sin cambios: `login(email, password)`, guardar `sauri_token`, limpiar la contraseña al entrar, `autoComplete`, `required`, deshabilitar mientras espera. No añadir campos, enlaces, avisos de sesión vencida, SSO ni insignias.
**Criterio de Completado:** captura del login en el navegador; `grep -n "Sign in\|Log in\|Email\|Password" frontend/src/components/LoginScreen.tsx` sin resultados.
**Dependencias:** PV1.2, PV2.1

#### Tarea PV3.2: Prueba de acceso preservado (Propiedad 1)

**Archivo:** `frontend/src/components/LoginScreen.test.tsx`
**Acción:** Actualizar las pruebas existentes a los textos nuevos y añadir: el envío llama `login` una sola vez con exactamente el correo y la contraseña escritos; tras éxito `localStorage.getItem("sauri_token")` es el `access_token` devuelto y se llama `onLogin`; tras fallo no se guarda token y aparece el error; no hay más campos que correo y contraseña.
**Criterio de Completado:** `npx vitest run src/components/LoginScreen.test.tsx` verde.
**Dependencias:** PV3.1

### Unidad PV4: Biblioteca con estilo (Fase 1)

#### Tarea PV4.1: Lista de grabaciones

**Archivo:** `frontend/src/components/RecordingLibrary.tsx`, `frontend/src/styles/library.css` (crear), `frontend/src/copy/library.ts`
**Acción:** Encabezado «Biblioteca de grabaciones» con botón secundario «Subir grabación» (navega a `/upload`). Sustituir la tabla por una lista de tarjetas (`Card`) en el orden recibido (más reciente primero): título (o «Sin título» si viene vacío), fecha y hora con `Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short" })`, `StatusBadge` con la etiqueta en español del estado (`queued` «En cola», `joining` «Uniéndose», `recording` «Grabando», `transcribing` «Transcribiendo», `completed` «Lista», `failed` «Con error») y la tarjeta entera abre la reunión (elemento `<button>` o enlace a `/meetings/:id`). Estados: «Cargando grabaciones…» (`role="status"`), vacío «Todavía no hay grabaciones.» con botón a `/upload`, error claro con botón «Reintentar» que vuelve a pedir la lista. Quitar los colores fijos `STATE_COLORS`. Sin conteos, paginación, miniaturas, plantillas ni acciones por fila.
**Criterio de Completado:** captura con varias grabaciones, captura vacía y captura de error (API detenida); `grep -n "#[0-9a-fA-F]\{3,6\}" frontend/src/components/RecordingLibrary.tsx` sin resultados.
**Dependencias:** PV1.4, PV2.1

#### Tarea PV4.2: Pruebas de biblioteca veraz (Propiedad 2)

**Archivo:** `frontend/src/components/RecordingLibrary.test.tsx`
**Acción:** Con `listMeetings` simulado: conserva el orden recibido; título vacío muestra «Sin título»; seleccionar llama `onSelectMeeting` con la reunión; lista vacía muestra el estado vacío; error muestra «Reintentar» y al pulsarlo vuelve a llamar `listMeetings`; no hay controles de búsqueda, filtros ni conteos en esta unidad.
**Criterio de Completado:** pruebas verdes.
**Dependencias:** PV4.1

### Unidad PV5: Carga con estilo y reunión confirmada por el servidor

#### Tarea PV5.1: La ingesta devuelve `meeting_id`

**Archivo:** `backend/app/ingestion/router.py`, `backend/tests/ingestion/test_upload_meeting_id.py` (crear)
**Acción:** En los tres `return` de `upload_recording` (reintento idempotente temprano, reintento tras carrera y éxito nuevo) añadir `"meeting_id": ingestion_data.meeting_id` junto a `recording_id` y `state`. Sin otros cambios.
**Criterio de Completado:** prueba nueva verde: subida nueva y reintento con la misma clave devuelven el mismo `meeting_id` enviado, la reunión creada tiene como título el nombre del archivo; `ruff` y `mypy` del archivo sin diagnósticos nuevos; `uv run --extra dev pytest tests/ingestion` verde.
**Dependencias:** Ninguna

#### Tarea PV5.2: El cliente usa el ID confirmado y envía el título

**Archivo:** `frontend/src/api.ts`, `frontend/src/api.test.ts`
**Acción:** `RecordingUploadData` añade `title: string`; `RecordingUploadResult` pasa a `{ meeting_id: string; recording_id: string; state: string }`; `uploadWithProgress` rechaza con `copy.upload.errors.invalidResponse` si la respuesta no trae `meeting_id` de tipo texto.
**Criterio de Completado:** pruebas de `api.test.ts` verdes, incluida una con respuesta sin `meeting_id` que termina en error.
**Dependencias:** PV5.1 (puede escribirse en paralelo; se integra después)

#### Tarea PV5.3: Presentación de la carga

**Archivo:** `frontend/src/components/UploadView.tsx`, `frontend/src/styles/upload.css` (crear), `frontend/src/copy/upload.ts`
**Acción:** Encabezado «Subir una grabación» con «Volver a la biblioteca». Zona `Card` con el botón «Elegir archivo» (input de archivo con etiqueta visible; mismo `accept`), y al elegir: nombre y tamaño del archivo (en MB, calculado de `file.size`), botón «Quitar» y botón primario «Subir y procesar». Enviar `title: file.name`. Durante la transferencia: `ProgressBar` con porcentaje solo si hay total, y los textos actuales de bytes/porcentaje/«esperando confirmación». Al terminar: navegar con `result.meeting_id` (no con el ID local). Error: tarjeta de error con el mensaje y «Reintentar» (conserva archivo, ID y clave). Sin lista de formatos ni tamaño máximo, sin campos de metadatos, sin pasos de procesamiento, sin velocidad, sin «Cancelar subida», sin «Copiar diagnóstico».
**Criterio de Completado:** capturas: archivo elegido, subiendo, error con reintento; en la recorrida, tras subir un archivo de prueba la URL es `/meetings/<meeting_id devuelto por el servidor>` y el título es el nombre del archivo.
**Dependencias:** PV1.4, PV2.1, PV5.2

#### Tarea PV5.4: Pruebas de carga (Propiedades 4, 5, 7, 9)

**Archivo:** `frontend/src/components/UploadView.test.tsx`
**Acción:** Añadir/ajustar: navega con el `meeting_id` de la respuesta aunque difiera del generado; un reintento reutiliza el mismo `meeting_id` e `idempotency_key`; el título enviado es el nombre del archivo; sin total no se muestra porcentaje; el error del servidor se muestra tal cual con «Reintentar»; no existe botón «Copiar diagnóstico» ni texto de formatos/tamaño máximo.
**Criterio de Completado:** pruebas verdes.
**Dependencias:** PV5.3

### Unidad PV6: Composición de la vista de reunión

#### Tarea PV6.1: Cabecera de la reunión

**Archivo:** `frontend/src/components/MeetingHeader.tsx` (crear), `frontend/src/copy/meeting.ts`
**Acción:** Componente con props `title: string | null`, `createdAt: string | null`, `onBack`: enlace «Volver a la biblioteca», título (`h1`, «Sin título» si falta) y fecha en formato `es`. `TranscriptView` obtiene título y fecha de la reunión con las funciones existentes de `api.ts` (si `getMeeting` no los devuelve, usar el elemento de `listMeetings` correspondiente; no añadir endpoints). Sin ID de grabación, duración, plantilla ni acciones (las añaden PV10/PV11).
**Criterio de Completado:** la reunión abierta muestra su título y fecha reales; prueba en `TranscriptView.test.tsx`.
**Dependencias:** PV1.4

#### Tarea PV6.2: Disposición reproductor-sobre-transcripción con panel lateral

**Archivo:** `frontend/src/components/TranscriptView.tsx`, `frontend/src/components/ChatTab.tsx` (crear), `frontend/src/styles/meeting.css` (crear), `frontend/src/copy/meeting.ts`
**Acción:** Rejilla de dos columnas en pantallas ≥ 1024 px (una sola columna debajo): columna izquierda con el reproductor arriba y la transcripción debajo, **siempre visible** (se eliminan las pestañas «Transcripción | Resumen»); columna derecha con `Tabs` de dos pestañas: «Notas y resumen» (activa por defecto, contiene `SummaryPanel`; las notas según la pregunta 1) y «Chat» (contiene `ChatTab`, que solo muestra el texto `copy.meeting.chatUnavailable` = «El chat con la grabación llegará en una fase posterior.» sin campo de texto ni botones). Turnos: hora en `var(--font-mono)`, etiqueta de hablante con `var(--speaker-N)` (sustituir `SPEAKER_COLORS` y `UNRESOLVED_SPEAKER_COLOR` por referencias a esos tokens), turno activo con fondo `var(--color-highlight)` y `aria-current`. La sección de revisión de hablantes conserva su comportamiento y pasa a una `Card` debajo de la transcripción. Mover a `copy/meeting.ts` «← Back to list» y «Transcript»; quitar la línea técnica «Language | Provider | Turns». Mantener el desplazamiento automático y el clic-para-reproducir.
**Criterio de Completado:** capturas a 1280 px y a 390 px de ancho; el turno activo se resalta y sigue la reproducción en la recorrida; `grep -n "#[0-9a-fA-F]\{3,6\}\|Back to list\|Provider" frontend/src/components/TranscriptView.tsx` sin resultados.
**Dependencias:** PV2.1, PV6.1

#### Tarea PV6.3: Reproductor con estilo y textos en español

**Archivo:** `frontend/src/components/MeetingPlaybackView.tsx`, `frontend/src/components/__tests__/MeetingPlaybackView.test.tsx`, `frontend/src/copy/meeting.ts`
**Acción:** Mover a `copy/meeting.ts` todas las etiquetas accesibles y mensajes en inglés del reproductor («Pause», «Play or resume playback», «Seek», «Playback speed», «Volume», «Mute»/«Unmute», «Video quality», «Meeting recording/audio/video», «Playback controls», «Playback failed», «Unable to load meeting media.», «Unable to reload meeting media. Playback has stopped.», «Speaker N»). Estilizar la barra de controles con `Button` y tokens; conservar exactamente los controles actuales (pausa, reproducir, búsqueda, velocidad, volumen, silencio, calidad). No añadir pantalla completa ni saltos de 10 s.
**Criterio de Completado:** pruebas del reproductor actualizadas a los textos nuevos y verdes, sin quitar ninguna aserción de comportamiento; `grep -n "\"[A-Z][a-z]" frontend/src/components/MeetingPlaybackView.tsx` no muestra textos visibles en inglés.
**Dependencias:** PV2.1

#### Tarea PV6.4: Pruebas de revisión sincronizada (Propiedad 3)

**Archivo:** `frontend/src/components/TranscriptView.test.tsx`
**Acción:** Ajustar las pruebas existentes a la nueva disposición y añadir: el reproductor aparece antes que la transcripción en el orden del documento; la transcripción es visible sin cambiar de pestaña; las pestañas laterales son exactamente «Notas y resumen» y «Chat», con «Notas y resumen» activa; la pestaña «Chat» no contiene `textbox` ni botones; cada turno tiene hora, etiqueta y texto; no hay controles para editar el texto de un turno.
**Criterio de Completado:** `npx vitest run src/components/TranscriptView.test.tsx` verde.
**Dependencias:** PV6.2, PV6.3

### Unidad PV7: Resumen descargable y con estilo

#### Tarea PV7.1: Descargar el resumen

**Archivo:** `frontend/src/components/SummaryPanel.tsx`, `frontend/src/styles/summary.css` (crear), `frontend/src/copy/summary.ts`
**Acción:** Junto a «Copiar», añadir «Descargar» que genera un archivo con el mismo texto plano que hoy se copia (tema y puntos clave tal como los devuelve `getMeetingSummary`), en el formato que decida Fer (pregunta 3; recomendado `.txt`), con nombre `resumen-<meetingId>.txt`, usando `Blob` + `URL.createObjectURL` + enlace temporal y revocando la URL. Estilizar el panel con `Card`/`Button`/`StatusBadge` («Borrador»). Sin regenerar extra, sin PDF, sin secciones fijas.
**Criterio de Completado:** en la recorrida, «Descargar» guarda un archivo cuyo contenido coincide con lo copiado; captura del panel.
**Dependencias:** PV2.1

#### Tarea PV7.2: Pruebas de resumen de fuente real (Propiedad 8)

**Archivo:** `frontend/src/components/SummaryPanel.test.tsx`
**Acción:** Con `getMeetingSummary` simulado: el `Blob` descargado contiene exactamente tema y puntos devueltos y ningún texto de la transcripción; sin resumen no hay botón «Descargar»; los estados existentes siguen igual.
**Criterio de Completado:** pruebas verdes.
**Dependencias:** PV7.1

### Unidad PV8: Abrir la reunión al detener la captura (extensión)

#### Tarea PV8.1: Disparador de apertura

**Archivo:** `extension/src/background.ts`, `extension/src/recording-db.ts`, pruebas junto a esos módulos
**Acción:** Según la respuesta de Fer a la pregunta 5 (recomendado: abrir en cuanto la subida queda confirmada), permitir que la apertura de `PORTAL_URL?meetingId=<id>` ocurra al estado `upload_succeeded` (además de `processing_succeeded`), una sola vez por sesión y sin duplicar pestañas (reutilizar `claimReviewLaunch` y la búsqueda por URL exacta). Comprobar en pruebas que detener la captura y el fin de la sesión de Meet (`meet-ended`) terminan en subida y apertura; si `meet-ended` no sube la grabación, documentarlo en el PR como hallazgo y abrir un bugfix aparte, sin ampliarlo aquí.
**Criterio de Completado:** `cd extension && npm run typecheck && npm run test && npm run build` verdes; prueba: tras `upload_succeeded` se abre una única pestaña con la URL esperada; en el navegador, con la extensión recargada y una pestaña de Meet nueva, detener una grabación corta abre la reunión en el portal (captura).
**Dependencias:** PV1.4 (el portal acepta `?meetingId=`), respuesta a la pregunta 5

---

## Fase D: Fase 2 de producto (PV9 ∥ PV10; PV11 tras PV10)

### Unidad PV9: Buscar, filtrar por fecha y ordenar

#### Tarea PV9.1: Función pura de consulta

**Archivo:** `frontend/src/library-query.ts` (crear), `frontend/src/library-query.test.ts` (crear)
**Acción:**
```ts
export type LibrarySort = "newest" | "oldest" | "title";
export interface LibraryQuery { text: string; from: string | null; to: string | null; sort: LibrarySort } // from/to "YYYY-MM-DD"
export function applyLibraryQuery(items: MeetingListItem[], query: LibraryQuery): MeetingListItem[];
```
`text` coincide de forma parcial, sin distinguir mayúsculas ni tildes (`normalize("NFD")` sin marcas), contra el título; PV13 añade empresa, proyecto y etiquetas. `from`/`to` filtran por `createdAt` en fecha local, ambos incluidos. Orden por defecto `newest`; `title` usa `localeCompare("es")`. Nunca consulta la transcripción.
**Criterio de Completado:** pruebas verdes: coincidencia parcial y sin tildes («reunion» encuentra «Reunión»), rango incluido, cada orden, consulta vacía devuelve la lista en orden `newest`, la función no muta la entrada.
**Dependencias:** Ninguna

#### Tarea PV9.2: Barra de búsqueda en la biblioteca

**Archivo:** `frontend/src/components/RecordingLibrary.tsx`, `frontend/src/components/RecordingLibrary.test.tsx`, `frontend/src/styles/library.css`, `frontend/src/copy/library.ts`
**Acción:** Sobre la lista: campo «Buscar por título» (placeholder sin ejemplos inventados), campos de fecha «Desde» y «Hasta», selector «Ordenar» (Más recientes / Más antiguas / Título) y botón «Limpiar» visible solo con algún criterio activo. Aplicar `applyLibraryQuery` en el cliente sobre la lista ya cargada. Sin resultados: «Ninguna grabación coincide con la búsqueda.» El texto del campo no menciona transcripciones.
**Criterio de Completado:** pruebas: escribir filtra, «Limpiar» restaura, cambiar orden reordena; captura con búsqueda activa.
**Dependencias:** PV4, PV9.1

### Unidad PV10: Renombrar y eliminar una grabación

#### Tarea PV10.1: Cliente HTTP

**Archivo:** `frontend/src/api.ts`, `frontend/src/api.test.ts`
**Acción:** Añadir al final `renameMeeting(meetingId: string, title: string): Promise<{ meetingId: string; title: string }>` sobre `PATCH /api/v1/meetings/{id}` con `{ title }`, y `deleteMeeting(meetingId: string): Promise<void>` sobre `DELETE /api/v1/meetings/{id}` (204), ambos con `getAuthHeaders()` y el manejo de errores común.
**Criterio de Completado:** pruebas de método, URL codificada, cuerpo y error 404/422.
**Dependencias:** Ninguna

#### Tarea PV10.2: Acciones en la cabecera de la reunión

**Archivo:** `frontend/src/components/MeetingHeader.tsx`, `frontend/src/components/MeetingHeader.test.tsx` (crear), `frontend/src/copy/meeting.ts`
**Acción:** Botón «Renombrar» que convierte el título en `TextField` con «Guardar» y «Cancelar» (título vacío o de más de 512 caracteres deshabilita «Guardar»); al guardar llama `renameMeeting` y muestra el título devuelto. Botón «Eliminar» (`variant="danger"`) que abre `ConfirmDialog` con «¿Eliminar esta grabación?» y «Se quitarán de Sauri la grabación, su transcripción y su resumen.»; al confirmar llama `deleteMeeting` y navega a `/`. Errores en lenguaje claro sin perder lo escrito. Sin prometer garantías de borrado ni recuperación.
**Criterio de Completado:** pruebas: renombrar muestra el nuevo título; cancelar no llama la API; eliminar sin confirmar no llama la API; confirmar llama `deleteMeeting` y navega a la biblioteca. En la recorrida (con una reunión de prueba propia, nunca una del dueño), renombrar y eliminar; capturas.
**Dependencias:** PV6.1, PV2.1, PV10.1

### Unidad PV11: Descargar video y transcripción

#### Tarea PV11.1: Exportación de la transcripción

**Archivo:** `frontend/src/transcript-export.ts` (crear), `frontend/src/transcript-export.test.ts` (crear)
**Acción:** `export function transcriptToText(turns: { timestampMs: number | null; speakerLabel: string; text: string }[]): string` que produce una línea por turno `[mm:ss] Hablante: texto` (`hh:mm:ss` si dura más de una hora), usando el nombre de hablante revisado que ya muestra la vista. Formato final según la pregunta 3.
**Criterio de Completado:** pruebas con turnos de ejemplo sintéticos, hablante sin resolver y reunión de más de una hora.
**Dependencias:** Ninguna

#### Tarea PV11.2: Botones de descarga

**Archivo:** `frontend/src/components/MeetingDownloads.tsx` (crear), `MeetingDownloads.test.tsx` (crear), `frontend/src/components/MeetingHeader.tsx` (montarlo: una línea), `frontend/src/components/TranscriptView.tsx` (pasar turnos y manifiesto: props), `frontend/src/copy/meeting.ts`
**Acción:** «Descargar video» (o «Descargar audio» si `video_presence` es `absent`) con un enlace `download` a la URL de la fuente principal del manifiesto de reproducción ya cargado; «Descargar transcripción» que genera `transcripcion-<meetingId>.txt` con `transcriptToText`. Deshabilitados mientras no hay manifiesto o turnos. Si en la recorrida el navegador reproduce el video en lugar de descargarlo (URL firmada de otro origen), documentarlo en el PR y añadir en esta unidad el encabezado `Content-Disposition: attachment` a la URL firmada de descarga en el backend, con su prueba.
**Criterio de Completado:** pruebas de habilitado/deshabilitado y del contenido descargado; en la recorrida se descargan el video y el `.txt` de una reunión de prueba (captura).
**Dependencias:** PV10.2 (comparte `MeetingHeader.tsx`), PV11.1

---

## Fase E: Metadatos y etiquetas (Fase 2)

> **Bloqueada** hasta (a) la respuesta de Fer a la pregunta 4 y (b) una adenda corta a `design.md` que fije el modelo de datos, porque el diseño aprobado deja esos contratos «para esa fase». La adenda la escribe el orquestador; esta sección solo fija el alcance de las unidades.

### Unidad PV12: Metadatos y etiquetas en el backend

#### Tarea PV12.1: Modelo, migración y API

**Archivo:** `backend/app/infra/models.py`, `backend/alembic/versions/<nueva>.py`, `backend/app/meetings/router.py`, `backend/app/meetings/service.py`, `backend/tests/meetings/test_meeting_metadata.py` (crear)
**Acción:** Según la adenda: columnas opcionales `company`, `project` y `participants` (texto) en `Meeting`; etiquetas por usuario (tabla propia con dueño) y relación reunión–etiqueta; etiquetas predefinidas sembradas según la pregunta 4; `PATCH /api/v1/meetings/{id}/metadata`, `GET /api/v1/tags`, `POST /api/v1/tags`, `PUT /api/v1/meetings/{id}/tags`; `GET /meetings` y `GET /meetings/{id}` devuelven los campos. Mismo control de dueño que renombrar/eliminar; un usuario nunca ve etiquetas de otro. Sin campos adicionales ni reglas de gobierno.
**Criterio de Completado:** pruebas contractuales verdes en una base desechable `sauri-qa-*`: guardar y leer metadatos; crear etiqueta y aplicarla; otro usuario recibe 404; migración sube y baja limpia; `ruff` y `mypy` sin diagnósticos nuevos.
**Dependencias:** adenda de diseño, pregunta 4

### Unidad PV13: Metadatos y etiquetas en el portal

#### Tarea PV13.1: Edición en la reunión

**Archivo:** `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/components/MeetingMetadata.tsx` (crear), `MeetingMetadata.test.tsx` (crear), `frontend/src/components/MeetingHeader.tsx` (montarlo), `frontend/src/copy/meeting.ts`
**Acción:** Funciones cliente para los cuatro endpoints de PV12. Bajo la cabecera: «Empresa», «Proyecto», «Participantes» (`TextField`) con «Guardar», y etiquetas como chips con «Quitar», selector de etiquetas existentes y «Crear etiqueta». Tras guardar se muestran los valores devueltos por el servidor.
**Criterio de Completado:** pruebas: guardar muestra lo guardado; crear y aplicar una etiqueta la muestra entre las aplicadas; captura.
**Dependencias:** PV12.1, PV10.2

#### Tarea PV13.2: Biblioteca con metadatos

**Archivo:** `frontend/src/library-query.ts`, `frontend/src/library-query.test.ts`, `frontend/src/components/RecordingLibrary.tsx`, `frontend/src/copy/library.ts`
**Acción:** La búsqueda de texto incluye empresa, proyecto y etiquetas; añadir filtros «Empresa», «Proyecto» y «Etiqueta» con los valores presentes en la lista cargada (no un catálogo fijo); la tarjeta muestra empresa · proyecto y las etiquetas.
**Criterio de Completado:** pruebas de la función con los nuevos campos y de los filtros; captura.
**Dependencias:** PV13.1, PV9.2

---

## Verificación final del spec

### Tarea V.1: Recorrida completa y privacidad de URLs (Propiedad 10)

**Archivo:** N/A (recorrida en el navegador integrado; evidencia en el PR de la última unidad integrada de cada fase)
**Acción:** Con la pila local levantada (revisar antes `docker compose -p sauri ps` y `make engines-status`): entrar, ver la biblioteca, buscar, subir un archivo de prueba, llegar a su reunión, reproducir y ver el turno activo, abrir «Notas y resumen» y «Chat», copiar y descargar el resumen, renombrar y eliminar la reunión de prueba. Revisar que ninguna URL ni título de pestaña contiene tokens ni texto de transcripción, y que no hay peticiones a dominios externos.
**Criterio de Completado:** capturas de cada pantalla y lista de lo verificado y lo `NO VERIFICADO`. No constituye aceptación del dueño.
**Dependencias:** PV3–PV8 para la Fase 1; PV9–PV13 para la Fase 2

## Preguntas para el dueño

1. **Notas dentro de «Notas y resumen».** Hoy Sauri no guarda notas en ningún sitio (ni la extensión ni el portal). *Recomiendo* que la pestaña muestre por ahora solo el resumen y que las notas aparezcan cuando se haga el trabajo de notas aparte; no inventamos un espacio vacío.
2. **Pantallas viejas del portal.** La página principal tiene hoy «Registrar reunión» (pegar un enlace de Meet, del sistema anterior) y un botón a una «prueba de reconocimiento de hablantes». *Recomiendo* quitarlos del menú del portal, porque no forman parte del alcance aprobado y confunden.
3. **Formato de las descargas.** El alcance pide descargar la transcripción y el resumen pero no dice en qué formato. *Recomiendo* texto simple (`.txt`), que abre en cualquier equipo; Word o PDF se pueden añadir después si los necesitas.
4. **Etiquetas iniciales.** *Recomiendo* que cada usuario empiece con «GenAI», «Digital Twin» y «Automatización» ya creadas, pueda crear las suyas, y que las etiquetas de cada persona sean solo suyas.
5. **Cuándo se abre sola la reunión.** Hoy la extensión abre la reunión cuando el procesamiento termina (minutos después). El alcance dice que se abra al detener la grabación. *Recomiendo* abrirla en cuanto la subida queda confirmada, mostrando «Transcribiendo…» mientras tanto.

## Decisiones aplicadas (2026-11-14)

El dueño delegó en el orquestador las preguntas abiertas y pidió empezar el rediseño. Se aplican las recomendaciones: (1) «Notas y resumen» muestra solo el resumen; (2) se retiran del portal «Registrar reunión» y la prueba de reconocimiento de hablantes; (3) las descargas son texto simple `.txt`; (5) la extensión abre la reunión cuando la subida queda confirmada. La Fase E (pregunta 4, etiquetas) queda para después.
