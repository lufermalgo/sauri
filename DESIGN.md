# Sistema de diseño de Sauri

> Contrato visual del portal web (`frontend/`) y de la extensión de Chrome (`extension/`).
> Identidad: paleta Terra (verde, marfil cálido, tierra) en modo claro y oscuro, tipografía del sistema, componentes sobrios y compactos.
> Estructura y reglas adaptadas de una especificación genérica de interfaz de trabajo; no se hereda ninguno de sus nombres, logos, conceptos de negocio ni su paleta neutra.

## 0. Propósito y cómo usarlo

- Este archivo es la referencia única de diseño. Si un valor de aquí y el código difieren, es un defecto del código (o de este documento): se corrige en el mismo PR.
- Las tablas de paleta (3.1) y de contraste (3.2) se leen en las pruebas `tokens.test.ts` de ambas aplicaciones. Cambiar un color exige cambiar el CSS y la tabla juntos; si no coinciden, las pruebas fallan.
- Todas las medidas son píxeles CSS. Los ratios de contraste son WCAG 2.x calculados sobre valores sólidos.
- Convención de etiquetas: **Regla** es obligatoria; **Decisión** documenta una elección del dueño o medida; **Pendiente** es una limitación conocida.

## 1. Lenguaje visual

Herramienta de trabajo, no página de marketing. Jerarquía por superficie, tamaño y peso; no por titulares enormes ni efectos.

- Modo claro: marfil cálido (`bg`) con tarjetas blancas. Modo oscuro: carbón verdoso cálido derivado de los mismos tonos Terra; nunca negro puro ni una inversión automática del claro.
- El verde Terra es la única acción principal. El color expresivo se concentra en estados, insignias e identidad de hablantes; no se extiende a títulos, bordes ni fondos.
- Bordes de 1px en tarjetas, listas y campos. Sombras solo en controles elevados, menús y diálogos. Las tarjetas se separan con borde, no con sombra.
- **No hacer:** gradientes, desenfoques de fondo (glassmorphism), sombras grandes por tarjeta, animaciones que muevan el contenido al pasar el cursor, varios botones primarios en un mismo grupo de acciones, mezclar familias de iconos.

## 2. Arquitectura de tokens

| Capa | Ejemplo | Responsabilidad |
|---|---|---|
| Semántico | `--ds-fg`, `--ds-accent`, `--ds-danger-text` | Contrato estable: nombra la función, no el color |
| Escala | `--ds-space-3`, `--ds-radius-md`, `--ds-text-sm` | Valores compartidos de espaciado, geometría y tipografía |
| Layout | `--ds-layout-max`, `--ds-target` | Medidas estructurales |

- **Un solo punto de entrada por aplicación:** `frontend/src/design/tokens.css` (importado desde `frontend/src/index.css`) y `extension/src/core/design/tokens.css` (importado desde `base.css`). El bloque de color es idéntico en ambos; las pruebas lo comparan con la tabla 3.1, de modo que no pueden divergir. Los dos archivos se mantienen por separado porque el portal y la extensión se compilan por separado.
- **Regla:** los componentes consumen `var(--ds-…)`. Prohibidos hexadecimales, `rgb()`/`hsl()` y nombres de fuentes en componentes. Excepción documentada: el color de la insignia del icono de la extensión (`chrome.action.setBadgeBackgroundColor`, API sin CSS) usa el valor claro de `recording`.
- Cada color se declara una vez con `light-dark(<claro>, <oscuro>)`; el navegador elige según `color-scheme`. No hay bloques duplicados claro/oscuro. Requiere Chrome 123 o superior (marzo de 2024).
- Parejas inseparables: `accent` + `accent-fg`, `danger` + `danger-fg`, `*-soft` + `*-soft-fg`. Se cambian juntas.
- `success` no tiene valor propio: es alias de `accent-text` / `accent-soft` / `accent-soft-fg` (en Terra éxito y acento son la misma familia; si divergen, se separa aquí).
- Violeta e información del documento de origen no tienen equivalente Terra y se omiten. No se inventan tonos nuevos.
- Los componentes usan roles (`ui-button--primary`, `ui-status-badge--error`), no colores.

## 3. Color

### 3.1 Paleta y mapeo Terra

Mapeo de roles: `accent` = primary `#4a7c59`; `accent-hover` = verde derivado `#3b6a49`; `accent-soft` = primary-fixed `#c8e8d0`; `accent-muted` = primary-container `#78a886`; `bg` = surface `#faf6f0`; `surface` = surface-lowest; `sidebar` = surface-low `#f5f1ea`; `fill` = surface-container; `fill-hover` = secondary-container; `fill-strong` = surface-high; `fg` = on-surface; `fg-muted` = on-surface-variant; `border` = outline-variant; `border-strong` = outline; `warning` = tertiary `#705c30` con `warning-soft` = tertiary-container; `danger` y `recording` = error `#b83230`. El oscuro es nuevo: mismos matices, luminosidad invertida con jerarquía propia (superficies de `#181b19` a `#272c29`, verde aclarado para la acción principal).

<!-- palette:start -->
| Token `--ds-…` | Claro | Oscuro | Uso |
|---|---|---|---|
| `bg` | `#faf6f0` | `#181b19` | Lienzo de página (Terra surface) |
| `surface` | `#ffffff` | `#1f2321` | Tarjetas, campos, contenido principal |
| `surface-raised` | `#ffffff` | `#272c29` | Menús, diálogos, barra del overlay |
| `sidebar` | `#f5f1ea` | `#1c201e` | Panel lateral, barra superior móvil y fondos de grupo suaves |
| `fill` | `#f0ece4` | `#262b28` | Pistas, fondos neutros |
| `fill-hover` | `#f0e8db` | `#2e3430` | Hover y botón secundario (Terra secondary-container) |
| `fill-strong` | `#eae6de` | `#373e3a` | Selección, pista de progreso |
| `fg` | `#2e3230` | `#ecebe6` | Texto principal |
| `fg-muted` | `#4a4e4a` | `#bfc2b8` | Texto secundario |
| `fg-subtle` | `#626860` | `#a9ad9f` | Metadatos y texto terciario; derivado, cumple 4.5:1 |
| `border` | `#c4c8bc` | `#353b37` | Divisores y bordes decorativos |
| `border-strong` | `#74796e` | `#707769` | Contorno de controles (3:1) |
| `accent` | `#4a7c59` | `#86bb95` | Relleno de la acción principal |
| `accent-hover` | `#3b6a49` | `#9bcaa8` | Hover de la acción principal |
| `accent-fg` | `#ffffff` | `#10201a` | Texto sobre accent |
| `accent-text` | `#3b6a49` | `#8fc29d` | Enlaces, iconos y texto de acento sobre superficies |
| `accent-soft` | `#c8e8d0` | `#243d2c` | Insignia de éxito, enlace activo, zona de arrastre |
| `accent-soft-fg` | `#1f4a2d` | `#bfe6cb` | Texto sobre accent-soft |
| `accent-muted` | `#78a886` | `#4f7d5d` | Decorativo (viñetas, barra indeterminada) |
| `focus` | `#3b6a49` | `#9bcaa8` | Anillo de foco |
| `warning` | `#705c30` | `#d9bd7a` | Progreso/aviso: bordes y texto sobre superficie (Terra tertiary) |
| `warning-soft` | `#f4e7c7` | `#3a3220` | Fondo de aviso y progreso |
| `warning-soft-fg` | `#4d3f1c` | `#f0e0b4` | Texto sobre warning-soft |
| `danger` | `#b83230` | `#c9433f` | Relleno de acciones destructivas |
| `danger-hover` | `#9d2a28` | `#b23a37` | Hover de danger |
| `danger-fg` | `#ffffff` | `#ffffff` | Texto sobre danger |
| `danger-text` | `#b83230` | `#ff9d97` | Texto y bordes de error sobre superficie |
| `danger-soft` | `#fce8e6` | `#43211f` | Fondo de error |
| `danger-soft-fg` | `#690005` | `#ffc9c4` | Texto sobre danger-soft |
| `recording` | `#b83230` | `#f2736d` | Punto de grabación |
| `highlight` | `#f4e7c7` | `#4a4022` | Turno activo y coincidencias |
| `on-speaker` | `#ffffff` | `#10201a` | Texto sobre avatares de hablante |
| `speaker-1` | `#4a7c59` | `#7fb58f` | Hablante 1 |
| `speaker-2` | `#9a5b2e` | `#d4955f` | Hablante 2 |
| `speaker-3` | `#3f6a8a` | `#7fb0d4` | Hablante 3 |
| `speaker-4` | `#7a4f7f` | `#c395c8` | Hablante 4 |
| `speaker-5` | `#8a6d1f` | `#cfae55` | Hablante 5 |
| `speaker-6` | `#2f7a74` | `#63bdb5` | Hablante 6 |
| `speaker-unresolved` | `#74796e` | `#a3a89b` | Hablante sin resolver |
| `scrim` | `rgb(46 50 48 / 0.45)` | `rgb(0 0 0 / 0.62)` | Velo de diálogos |
| `scrim-strong` | `rgb(32 36 33 / 0.78)` | `rgb(0 0 0 / 0.8)` | Velo de la cuenta regresiva (sobre cualquier página) |
| `on-scrim` | `#ffffff` | `#ffffff` | Texto sobre scrim-strong |
<!-- palette:end -->

Alfa: `scrim` y `scrim-strong` son colores con transparencia; el resultado depende de la superficie inferior. `scrim-strong` se mide sobre blanco puro (peor caso) en la prueba.

### 3.2 Contraste medido

Mínimos: 4.5:1 para texto normal, 3:1 para texto grande y elementos de interfaz (bordes de control, foco, indicadores). Grupos: `surfaces` = bg, surface, surface-raised, sidebar, fill, fill-hover, fill-strong; `page` = bg, surface, surface-raised, sidebar; `reading` = bg, surface; `base` = bg, surface, surface-raised, fill. Para un grupo se muestra el peor caso.

<!-- contrast:start -->
| Par (texto / fondo) | Mínimo | Claro | Oscuro | Nota |
|---|---:|---:|---:|---|
| `fg` / `surfaces` | 4.5 | 10.45 | 9.20 | peor caso del grupo |
| `fg-muted` / `surfaces` | 4.5 | 6.80 | 6.08 | peor caso del grupo |
| `fg-subtle` / `surfaces` | 4.5 | 4.60 | 4.79 | peor caso del grupo |
| `accent-text` / `surfaces` | 4.5 | 5.05 | 5.42 | peor caso del grupo |
| `danger-text` / `page` | 4.5 | 5.27 | 7.12 | peor caso del grupo |
| `danger-soft-fg` / `page` | 4.5 | 11.64 | 9.74 | peor caso del grupo |
| `warning` / `reading` | 4.5 | 5.98 | 8.72 | peor caso del grupo |
| `accent-fg` / `accent` | 4.5 | 4.86 | 7.68 |  |
| `accent-fg` / `accent-hover` | 4.5 | 6.28 | 9.17 |  |
| `accent-text` / `accent-soft` | 4.5 | 4.76 | 5.83 |  |
| `accent-soft-fg` / `accent-soft` | 4.5 | 7.66 | 8.66 |  |
| `warning-soft-fg` / `warning-soft` | 4.5 | 8.37 | 9.67 |  |
| `danger-fg` / `danger` | 4.5 | 5.94 | 4.82 |  |
| `danger-fg` / `danger-hover` | 4.5 | 7.51 | 5.91 |  |
| `danger-soft-fg` / `danger-soft` | 4.5 | 11.12 | 9.76 |  |
| `danger-text` / `danger-soft` | 4.5 | 5.04 | 7.13 |  |
| `fg` / `highlight` | 4.5 | 10.59 | 8.59 |  |
| `fg` / `accent-soft` | 4.5 | 9.85 | 9.89 |  |
| `fg` / `warning-soft` | 4.5 | 10.59 | 10.62 |  |
| `fg` / `danger-soft` | 4.5 | 11.04 | 11.92 |  |
| `speaker-1` / `reading` | 4.5 | 4.52 | 6.75 | peor caso del grupo |
| `speaker-2` / `reading` | 4.5 | 4.99 | 6.26 | peor caso del grupo |
| `speaker-3` / `reading` | 4.5 | 5.36 | 6.86 | peor caso del grupo |
| `speaker-4` / `reading` | 4.5 | 6.00 | 6.40 | peor caso del grupo |
| `speaker-5` / `reading` | 4.5 | 4.55 | 7.45 | peor caso del grupo |
| `speaker-6` / `reading` | 4.5 | 4.69 | 7.18 | peor caso del grupo |
| `speaker-unresolved` / `surface` | 4.5 | 4.47 | 6.54 | excepción (ver 3.3) |
| `on-speaker` / `speaker-1` | 4.5 | 4.86 | 7.16 |  |
| `on-speaker` / `speaker-2` | 4.5 | 5.37 | 6.65 |  |
| `on-speaker` / `speaker-3` | 4.5 | 5.77 | 7.29 |  |
| `on-speaker` / `speaker-4` | 4.5 | 6.46 | 6.80 |  |
| `on-speaker` / `speaker-5` | 4.5 | 4.90 | 7.91 |  |
| `on-speaker` / `speaker-6` | 4.5 | 5.05 | 7.62 |  |
| `on-speaker` / `speaker-unresolved` | 4.5 | 4.47 | 6.94 | excepción (ver 3.3) |
| `border-strong` / `base` | 3 | 3.79 | 3.06 | peor caso del grupo |
| `focus` / `base` | 3 | 5.33 | 7.72 | peor caso del grupo |
| `accent` / `base` | 3 | 4.13 | 6.46 | peor caso del grupo |
| `recording` / `base` | 3 | 5.04 | 5.04 | peor caso del grupo |
<!-- contrast:end -->

Medición adicional (prueba): `on-scrim` sobre `scrim-strong` compuesto sobre blanco puro supera 4.5:1 en ambos modos.

### 3.3 Excepciones conocidas

- `speaker-unresolved` (`#74796e`, decisión del dueño: los colores de hablantes no cambian) sobre `surface` en modo claro mide 4.47:1, 0.03 por debajo de 4.5. Se usa en la etiqueta secundaria «sin resolver», que además lleva texto explícito (`aria-label`), y como relleno de avatar con iniciales ocultas a lectores de pantalla. **Pendiente:** si el dueño autoriza oscurecerlo un paso, el cambio es solo ese token y su fila.
- `fg-subtle` se derivó para cumplir 4.5:1 en todas las superficies (el token equivalente del documento de origen medía 3.2:1 y se descartó).
- Los bordes decorativos (`border`, 1.6–1.7:1 sobre blanco) solo separan; el contorno de un control usa `border-strong` (≥3:1).

### 3.4 Tema

- **Regla:** sin `data-theme`, la interfaz sigue `prefers-color-scheme`. `<html data-theme="light">` o `"dark"` fuerza el modo. No se guarda ninguna preferencia nueva.
- Los diálogos nativos (`<dialog>`) y menús heredan el tema porque están dentro del documento.
- El overlay de Meet vive en un Shadow DOM de una página ajena: `overlay/recording.ts` incorpora `tokens.css` como texto en su hoja (`:host` en lugar de `:root`) y fija `color-scheme: light dark` en el anfitrión; sigue la preferencia del sistema, no el tema de Meet.

## 4. Tipografía

**Decisión (medida):** pila del sistema para toda la interfaz y para datos técnicos; se retiran Literata, Nunito Sans y JetBrains Mono.

```css
--ds-font-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--ds-font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
```

Mediciones (Chrome en macOS, 14px): con `font-variant-numeric: tabular-nums`, `00:00:00`, `11:11:11` y `88:88:88` miden lo mismo en `system-ui` (60.02px) y en la mono del sistema (67.43px), igual que JetBrains Mono (67.20px): los cronómetros no «bailan» sin fuente web. Peso descargado que se elimina: 84.8 KB en la primera carga del portal (5 archivos woff2 usados; 696 KB entre todos los subconjuntos publicados) y 604 KB de `.ttf` empaquetados en la extensión, más el parpadeo de cambio de fuente (`font-display: swap`). No se justifica una fuente de encabezados: la jerarquía se logra con tamaño y peso 600.

| Token | Tamaño | Uso |
|---|---:|---|
| `text-xs` | 12 | Metadatos, insignias, ayuda |
| `text-sm` | 13 | Etiquetas, texto secundario, tiempos |
| `text-md` | 14 | Base de la extensión; botones y filas densas |
| `text-base` | 16 | Base del portal; lectura de transcripción |
| `text-lg` | 18 | Títulos de tarjeta |
| `text-xl` | 20 | Títulos de sección |
| `text-2xl` | 24 | Título de pantalla en móvil |
| `text-3xl` | 30 | Título de pantalla en escritorio |

- Pesos: 400 cuerpo, 500 etiquetas, 600 botones, títulos y selección. No se usa 700/800 (en fuentes del sistema se ve pesado).
- Interlineado: `--ds-leading` 1.5; transcripción `--ds-leading-relaxed` 1.7.
- Cronómetros, marcas de tiempo y contadores: `font-variant-numeric: tabular-nums`. Mono solo para identificadores, rutas y cifras técnicas.
- Elipsis en títulos de una línea; nunca en errores. `overflow-wrap: anywhere` en cadenas largas.
- Etiquetas en minúscula inicial (sentence case); el único texto en mayúsculas es la etiqueta de sección del resumen.

## 5. Espaciado, geometría y elevación

| Token | Valor | Uso |
|---|---:|---|
| `space-1` | 4 | Separación mínima interna |
| `space-2` | 8 | Elementos relacionados |
| `space-3` | 12 | Filas y grupos |
| `space-4` | 16 | Inset de tarjeta compacta |
| `space-6` | 24 | Secciones y tarjetas |
| `space-8` | 32 | Márgenes de página |

- Radios: `xs` 4 (barras), `sm` 8 (campos, filas), `md` 12 (botones, menús), `lg` 16 (tarjetas), `xl` 20 (diálogos, zonas grandes), `pill` (insignias, interruptores, avatares).
- Bordes de 1px; el borde de acento de estado en tarjetas de lista mide 5–6px a la izquierda y siempre acompaña a un texto de estado.
- Sombras: `shadow-sm` (controles elevados, selector segmentado) y `shadow-md` (menús y diálogos). No hay más niveles.
- Objetivo táctil: `--ds-target` 44px para botones, campos, pestañas y filas de menú. Controles densos en línea (interruptor de 28px, botones del reproductor) miden al menos 24px y suben a 44px con puntero táctil (`@media (pointer: coarse)`).
- Capas: `z-sticky` 10 (panel lateral), `z-menu` 20. El overlay de Meet usa el máximo z-index porque convive con una página ajena.

## 6. Layout por superficie

**Portal.** Contenedor central de `--ds-layout-max` (1200) con 32px laterales (16 en móvil). Panel lateral izquierdo (fondo `sidebar`, borde derecho de 1px, sin transparencia ni desenfoque) y región de contenido con desplazamiento propio; el contenedor central y sus máximos de ancho no cambian.
- *Panel lateral:* 236px expandido; carril de 60px (solo iconos, con tooltip al pasar el cursor o enfocar) y botón `PanelLeft` para alternar. La elección se recuerda por dispositivo en `localStorage` (si el almacenamiento está bloqueado, solo dura la visita); bajo 1320px arranca contraído. Bajo 640px es un cajón fuera de pantalla que se abre desde una barra superior delgada: foco dentro al abrir y de vuelta al cerrar, Escape y velo lo cierran, `aria-expanded` en el botón. Contenido: «Biblioteca» (fila seleccionada con `accent-soft`) y, abajo, la tarjeta de perfil (avatar con iniciales, nombre con elipsis, correo en `fg-subtle`) con un menú de «Cerrar sesión» y el engranaje hacia `/settings`.
- *Biblioteca:* título, tarjeta de búsqueda, grupos por fecha y filas-tarjeta en una columna. Cada fila lleva borde izquierdo de estado, miniatura, título, tema, metadatos, insignia y chevron. La miniatura es un recuadro fijo de 96×54 (16:9, radio `sm`, borde `border`, fondo `fill`) con `object-fit: cover`, carga diferida y `alt` vacío (el título está al lado); sin imagen disponible, o si falla al cargar, muestra un icono Lucide (`Video`, o `AudioLines` si es solo audio) en `fg-subtle`.
- *Subir:* columna de máximo 880px; zona de arrastre con borde discontinuo 2px, un único botón primario.
- *Reunión:* sin enlace de regreso (el panel lateral lleva a la biblioteca). La tarjeta del reproductor abre con la cabecera de la reunión (título como único `h1`, insignia de estado, fecha, duración, hablantes y los iconos de acción a la derecha; en móvil las acciones pasan a su propia fila) y está siempre presente; la tarjeta de progreso va justo debajo. Una columna hasta 1023px; desde 1024px, rejilla 2fr/1fr con reproductor y transcripción a la izquierda y resumen/hablantes a la derecha. La transcripción son turnos de lectura (16px, interlineado 1.7) con avatar, hablante en su color y marca de tiempo.

**Panel lateral de la extensión.** Una columna de ancho variable (320–480px). Cabecera con marca e iconos de 44px, cuerpo con tarjetas de 16px de padding, acciones a todo el ancho (la principal con peso 1.4). Cronómetro de 40–56px con cifras tabulares.

**Página de permisos (opciones).** Columna de máximo 740px centrada, tarjeta con insignia de estado, pasos numerados y un solo botón de acción.

**Overlay de Meet.** Tres piezas fijas sobre la página: aviso superior centrado, cuenta regresiva a pantalla completa (velo `scrim-strong`, texto `on-scrim`) y barra flotante arrastrable abajo a la izquierda (superficie `surface-raised`, borde `border-strong`, `shadow-md`). Controles de 44px; el botón de detener usa `accent`; descartar usa `danger`.

## 7. Componentes

Los componentes del portal están en `frontend/src/components/ui/` y los de la extensión en `panel.css`; comparten medidas y estados.

- **Botones.** Altura mínima 44, padding 8/16, radio `md`, peso 600. Primario (`accent`/`accent-fg`, hover `accent-hover`), secundario (`fill-hover`, texto `accent-text`, borde `border`), fantasma (transparente), peligro (`danger`/`danger-fg`, hover `danger-hover`). Un primario por grupo; deshabilitado con opacidad 0.5. Sin sombra en hover: el hover es tonal.
- **Campos.** Altura mínima 44, borde `border-strong`, radio `sm`, fondo `surface`. Etiqueta visible siempre; el marcador de posición no la sustituye. Error: borde `danger-text`, texto de error asociado con `aria-describedby` y `aria-invalid="true"`.
- **Tarjetas.** `surface`, borde `border`, radio `lg`, padding 24 (16 en móvil), sin sombra. Si es clicable, el hover cambia el fondo a `bg` y el borde a `accent`; nada se desplaza.
- **Listas.** Filas-tarjeta separadas 12px; seleccionada y hover son estados distintos; texto largo con `overflow-wrap`.
- **Pestañas.** Subrayado de 2px en `accent`, texto `accent-text` en la activa, `aria-selected`; altura 44.
- **Insignias.** Pastilla con texto siempre presente: éxito (`accent-soft`/`accent-soft-fg`), progreso (`warning-soft`/`warning-soft-fg`), error (`danger-soft`/`danger-soft-fg`), neutral (`fill`/`fg-muted`).
- **Diálogos.** `<dialog>` nativo: borde, radio `lg`, `shadow-md`, velo `scrim`, título, acción secundaria antes de la principal, foco inicial dentro, cierre con Escape y retorno del foco al disparador. Para contenido con formulario o listas largas, `Dialog` (`ui/Dialog.tsx`): panel centrado `surface-raised` en un portal (anchos `sm` 28rem y `md` 34rem), cabecera fija con título y botón `X`, cuerpo con desplazamiento propio, resto de la página inerte y sin desplazamiento, foco atrapado, cierre con Escape, botón de cerrar o clic en el velo, y retorno del foco al disparador.
- **Menús.** Panel `surface`, borde, `shadow-md`, filas de 44px, hover `fill-hover`, elemento destructivo en `danger-text`, navegación por teclado.
- **Tooltips.** Solo texto breve, complemento (no reemplazo) del nombre accesible; sin botones dentro. Los iconos del carril del panel lateral usan CSS a partir de la etiqueta oculta. En el portal, `useTooltip` (`ui/Tooltip.tsx`, hoy en el disparador de `Menu` con `tooltip`) usa `role="tooltip"` enlazado con `aria-describedby`, aparece tras 400ms con el puntero o el foco de teclado y se cierra con Escape.
- **Avisos (toasts).** (Regla para cuando se creen.) Esquina inferior, `surface-raised`, borde y `shadow-md`; se anuncian con `role="status"` (error: `role="alert"`).
- **Progreso y pasos.** Barra de 12px, pista `fill-strong`, relleno `accent`. Sin estimación, la barra indeterminada pulsa en `accent-muted` (sin degradados). El paso actual se marca con número, contorno de acento y texto en negrita, no solo color.

## 8. Iconos

- Familia **Lucide**, lineal, heredan `currentColor`. Los componentes React usan `core/design/Icon.tsx` y el overlay `overlay/icons.ts`; ambos toman tamaño (18) y trazo (1.75) de `core/design/iconDefaults.ts`, un único punto de cambio. No se cambia la librería ni el trazo sin necesidad documentada.
- Escala: `icon-xs` 12, `icon-sm` 14, `icon-md` 16, `icon-lg` 18. Botón de icono: 44×44 con icono 16–18. En el portal, `.ui-icon-button` (primario `--primary` para la acción principal del grupo, `--quiet` para las secundarias).
- Decorativo: `aria-hidden="true"`; acción solo con icono: nombre accesible (`aria-label`).
- El color de un icono lo da el texto que lo rodea (`fg-muted`, `accent-text`, `danger-text`).

## 9. Estados, feedback y movimiento

| Estado | Regla |
|---|---|
| Hover | Cambio tonal; nunca escalar ni mover la tarjeta |
| Foco visible | Anillo de 2px `focus`, separación 2px, en ambos modos; nunca `outline: none` sin sustituto |
| Seleccionado | Fondo + peso o indicador + semántica (`aria-selected`/`aria-checked`) |
| Deshabilitado | Opacidad 0.5 y no activable; si no es obvio, se explica |
| Cargando | Misma geometría; esqueleto con pulso de opacidad (1.6s); sin degradado |
| Error | Mensaje útil + icono o texto + color; asociado al campo; nunca solo rojo |
| Vacío | Título, explicación y siguiente acción |

- Movimiento: transiciones de `--ds-duration` (150ms) con `--ds-ease` en color, fondo y borde; nunca `transition: all`. Con `prefers-reduced-motion` la duración pasa a 0 y se anulan las animaciones decorativas (pulsos, esqueletos, indicadores de grabación); el estado sigue comunicándose con texto.
- Grabación: el punto rojo pulsa solo si no hay reducción de movimiento y siempre va con la palabra «grabando» (u homóloga) en el texto.

## 10. Accesibilidad (requisitos)

1. Contraste: texto ≥4.5:1, texto grande y elementos de interfaz ≥3:1, en ambos modos (tabla 3.2, validada por prueba).
2. Foco visible en todo control interactivo, en ambos modos y superficies.
3. Objetivos táctiles de 44px (excepciones de la sección 5, siempre ≥24px).
4. El estado nunca se transmite solo con color (borde de estado + texto; paso con número; error con mensaje).
5. Formularios: etiqueta asociada, `aria-invalid` y `aria-describedby` hacia el error o la ayuda.
6. Diálogos: título, foco inicial, atrapar el foco, Escape y retorno del foco (el `<dialog>` nativo lo resuelve).
7. Reflujo: sin desplazamiento horizontal a 320px de ancho y con zoom del 200%. Tablas y código se desplazan dentro de su contenedor.
8. Movimiento reducido respetado; ninguna información depende de una animación.
9. Contenido dinámico (progreso, avisos) en regiones `role="status"` o `role="alert"`.
10. Nombre accesible en todo botón de icono; iconos decorativos ocultos.

## 11. Cómo cambiar la paleta

1. Editar los pares `claro, oscuro` de `--ds-*` en `frontend/src/design/tokens.css` y copiar el bloque al archivo de la extensión (mismas líneas de color).
2. Actualizar la tabla 3.1 y regenerar la 3.2 con los nuevos ratios.
3. Cambiar pares completos (`accent` + `accent-fg`, `*-soft` + `*-soft-fg`). No renombrar tokens por su color.
4. Ejecutar `npm run test` en `frontend/` y en `extension/`: la comparación con este documento y los contrastes deben pasar.
5. Revisar en el navegador ambos modos (portal: subir, biblioteca, reunión; extensión: panel, permisos, overlay) antes de integrar.

## 12. Aceptación y QA

- [ ] Sin hexadecimales, `rgb()`, `hsl()` ni nombres de fuente en componentes (la prueba lo vigila).
- [ ] Tabla 3.1 y 3.2 coinciden con el CSS de portal y extensión.
- [ ] Portal y extensión legibles en claro y oscuro; `data-theme` fuerza cada modo.
- [ ] Sin degradados, desenfoques ni sombras en tarjetas.
- [ ] Foco visible y navegación por teclado completa (pestañas, menú, diálogo).
- [ ] Anchos de 320, 480, 768, 1024 y 1440 sin desplazamiento horizontal global; zoom 200%.
- [ ] `prefers-reduced-motion` desactiva pulsos y esqueletos.
- [ ] Textos largos (títulos de reunión, nombres de hablante) hacen salto de línea sin romper el layout.
- [ ] Extensión cargada en Chrome real: panel, página de permisos y overlay en Meet en ambos modos (verificación manual del dueño).
