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

- Modo claro: marfil cálido (`bg`) con paneles blancos. Modo oscuro: carbón verdoso cálido derivado de los mismos tonos Terra; nunca negro puro ni una inversión automática del claro.
- El verde Terra es la única acción principal. El color expresivo se concentra en estados, insignias e identidad de hablantes; no se extiende a títulos, bordes ni fondos.
- Aspecto de aplicación de escritorio, no de página web: regiones planas (paneles) separadas por bordes de 1px, cada una con su cabecera y su scroll; sin tarjetas flotantes en las regiones principales (ver 5b y 6). Sombras solo en controles elevados, menús y diálogos.
- **No hacer:** gradientes, desenfoques de fondo (glassmorphism), sombras grandes por tarjeta, animaciones que muevan el contenido al pasar el cursor, varios botones primarios en un mismo grupo de acciones, mezclar familias de iconos.

## 2. Arquitectura de tokens

| Capa | Ejemplo | Responsabilidad |
|---|---|---|
| Semántico | `--ds-fg`, `--ds-accent`, `--ds-danger-text` | Contrato estable: nombra la función, no el color |
| Escala | `--ds-space-3`, `--ds-radius-md`, `--ds-text-sm` | Valores compartidos de espaciado, geometría y tipografía |
| Densidad y layout | `--ds-control-h-md`, `--ds-header-h`, `--ds-list-w`, `--ds-z-sticky` | Alturas de controles, geometría de paneles y capas (ver 5b). El portal no tiene ancho máximo de contenido: llena la ventana (ver 6) |

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

- **Regla:** sin `data-theme`, la interfaz sigue `prefers-color-scheme`. `<html data-theme="light">` o `"dark"` fuerza el modo. En el portal se elige en Configuración > Apariencia («Sistema», «Claro», «Oscuro»): se aplica al instante y se recuerda por dispositivo en `localStorage` (`sauri_theme`; «Sistema» quita el atributo). Un script en línea de `index.html` lo aplica antes del primer pintado para que no haya destello; si el almacenamiento está bloqueado, solo dura la visita. La extensión no tiene selector: sigue al sistema.
- Los diálogos nativos (`<dialog>`) y menús heredan el tema porque están dentro del documento.
- El overlay de Meet vive en un Shadow DOM de una página ajena: `overlay/recording.ts` incorpora `tokens.css` como texto en su hoja (`:host` en lugar de `:root`) y fija `color-scheme: light dark` en el anfitrión; sigue la preferencia del sistema, no el tema de Meet.

## 4. Tipografía

**Decisión (medida):** pila del sistema para toda la interfaz y para datos técnicos; se retiran Literata, Nunito Sans y JetBrains Mono.

```css
--ds-font-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
--ds-font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
```

Mediciones (Chrome en macOS, 14px; `text-md` es hoy también la base del portal): con `font-variant-numeric: tabular-nums`, `00:00:00`, `11:11:11` y `88:88:88` miden lo mismo en `system-ui` (60.02px) y en la mono del sistema (67.43px), igual que JetBrains Mono (67.20px): los cronómetros no «bailan» sin fuente web. Peso descargado que se elimina: 84.8 KB en la primera carga del portal (5 archivos woff2 usados; 696 KB entre todos los subconjuntos publicados) y 604 KB de `.ttf` empaquetados en la extensión, más el parpadeo de cambio de fuente (`font-display: swap`). No se justifica una fuente de encabezados: la jerarquía se logra con tamaño y peso 600.

| Token | Tamaño | Uso |
|---|---:|---|
| `text-2xs` | 11 | Insignias, marcas de tiempo, etiquetas de sección (mayúsculas) |
| `text-xs` | 12 | Metadatos, ayuda, hablante en la transcripción, tiempos en mono |
| `text-sm` | 13 | Texto secundario, filas de navegación, botones pequeños, resumen |
| `text-md` | 14 | Base de la interfaz del portal y de la extensión: campos, botones, transcripción |
| `text-base` | 14 | Alias de `text-md`: tamaño del cuerpo (`body`) |
| `text-lg` | 15 | Título de panel |
| `text-xl` | 16 | Título de pantalla o de reunión (máximo 18 en una pantalla de app) |
| `text-2xl` | 20 | Solo la pantalla de acceso |

- Pesos: 400 cuerpo, 500 etiquetas, 600 botones, títulos y selección. No se usa 700/800 (en fuentes del sistema se ve pesado).
- Interlineado: `--ds-leading` 1.45; transcripción `--ds-leading-relaxed` 1.55.
- Cronómetros, marcas de tiempo y contadores: `font-variant-numeric: tabular-nums`. Mono solo para identificadores, rutas y cifras técnicas.
- Elipsis en títulos de una línea; nunca en errores. `overflow-wrap: anywhere` en cadenas largas.
- Etiquetas en minúscula inicial (sentence case); el único texto en mayúsculas son las etiquetas de sección de 11px (resumen, grupos de la biblioteca y de ajustes).

## 5. Espaciado, geometría y elevación

| Token | Valor | Uso |
|---|---:|---|
| `space-1` | 4 | Separación mínima interna |
| `space-2` | 8 | Elementos relacionados |
| `space-3` | 12 | Padding de panel y de cabecera; filas y grupos |
| `space-4` | 16 | Padding de contenido de una pantalla de una columna |
| `space-6` | 24 | Solo la pantalla de acceso y estados vacíos amplios |
| `space-8` | 32 | Solo márgenes de diálogos y de la pantalla de acceso |

- Radios: `xs` 4 (barras, marcadores), `thumb` 6 (miniaturas, filas de lista), `sm` 8 (controles: botones, campos, iconos, filas de menú), `card` 10 (tarjetas de contenido secundario: ajustes, subida), `md` 12 (menús, popovers, diálogos), `lg` 16 y `xl` 20 (sin uso en pantallas de app), `pill` (insignias, interruptores, avatares). Los paneles tienen radio 0.
- Bordes de 1px; el borde de estado de una fila de lista mide 3px a la izquierda y siempre acompaña a una insignia con el texto del estado.
- Sombras: `shadow-sm` (controles elevados, selector segmentado) y `shadow-md` (menús y diálogos). No hay más niveles.
- Objetivo de puntero: las alturas de control de 5b (28–36px) cumplen WCAG 2.2 AA (24×24 mínimo). Solo con puntero táctil (`@media (pointer: coarse)`) los tokens de altura suben a 44px; los controles densos en línea (interruptor, botones del reproductor) suben su área activa a 44px con relleno o pseudoelemento.
- Capas: `z-sticky` 10 (panel lateral), `z-menu` 20. El overlay de Meet usa el máximo z-index porque convive con una página ajena.

## 5b. Densidad de escritorio

**Decisión del dueño:** el portal debe parecer una aplicación de escritorio, no una página: textos pequeños, poco aire entre elementos, regiones que llenan la ventana y se separan con una línea. Referencia de proporciones: la aplicación hermana APX (cuerpo 14px, controles de 28–34px, filas de 56–60px, regiones planas con scroll propio). Estas escalas mandan sobre cualquier valor mayor de otras secciones.

| Elemento | Valor | Token |
|---|---:|---|
| Texto de interfaz (cuerpo) | 14px, interlineado 1.45 | `text-base` / `text-md`, `leading` |
| Texto secundario | 13px | `text-sm` |
| Metadatos | 12px | `text-xs` |
| Micro (insignias, marcas de tiempo) | 11px | `text-2xs` |
| Título de panel | 15px / 600 | `text-lg` |
| Título de pantalla o de reunión | 16px / 600 (máximo 18) | `text-xl` |
| Etiqueta de sección | 11px / 600, mayúsculas, espaciado .04em, `fg-muted` | `text-2xs` |
| Tiempos y cifras | 12px (11px en la transcripción), mono, `tabular-nums` | `font-mono` |
| Botón sm / md / lg | 28 / 32 / 36 | `control-h-sm/md/lg` |
| Botón de icono sm / md | 30 / 32 | `icon-button-sm/md` |
| Campo, pestaña | 32 | `control-h-md` |
| Selector segmentado | 28 | `control-h-sm` |
| Fila de navegación | 32 (icono 16, texto 13/500) | `nav-row-h` |
| Fila de menú | 28 (texto 13) | `control-h-sm` |
| Cabecera de panel | 48 | `header-h` |
| Panel lateral expandido / carril | 220 / 60 | `sidebar-w`, `rail-w` |
| Lista (biblioteca) | 340 (plegable con una reunión abierta, ver 6) | `list-w` |
| Panel de notas de la reunión | 380 (400 desde 1100px de panel de detalle) | `side-w` |
| Padding de panel | 12–16 | `space-3`, `space-4` |
| Separación entre elementos | 2–12 | |

- **Regla:** ningún texto de pantalla de app supera 16px (18px como máximo en un título); 20px solo en la pantalla de acceso.
- **Regla:** 44px solo bajo `@media (pointer: coarse)`: los tokens de altura de control, de botón de icono y de fila de navegación pasan a 44px y todo componente que los lea se agranda solo. Las pruebas de `tokens.test.ts` fijan esta escala.
- **Regla:** las regiones principales son paneles planos (`surface` o `bg`), de radio 0, separados por `1px solid border`; cada uno con cabecera de 48px (`ui-pane-header`) y cuerpo con scroll propio (`ui-pane-body`). No hay tarjetas flotantes ni huecos de 24px entre secciones. Las tarjetas (`ui-card`, padding 16, radio 10) solo contienen contenido secundario dentro de una pantalla de una columna (ajustes, subida).
- Componentes: `ui-pane`, `ui-pane-header`, `ui-pane-title`, `ui-pane-body` y `ui-section-label` viven en `ui/ui.css`; la reunión y la biblioteca usan las clases de `styles/`.

## 6. Layout por superficie

**Portal: marco de aplicación de escritorio.** El portal es una app, no una página de aterrizaje: el contenido llena todo el ancho entre el panel lateral y el borde de la ventana. No hay contenedor central con ancho máximo (`--ds-layout-max` se eliminó) ni bandas vacías a los lados.
- *Marco y scroll:* la raíz del portal queda fija a la ventana (`position: fixed; inset: 0`, sin `100vh`, para que su tamaño no dependa de unidades de viewport ni del alto del documento). Dentro: panel lateral (`flex: none`) y **una región de contenido** (`flex: 1`, `min-width: 0`, `min-height: 0`, `overflow: hidden`, `position: relative`) que no se desplaza: cada vista la llena y reparte su altura en paneles, cada uno con su propio scroll vertical. El documento nunca se desplaza. Las vistas de una columna (subir, ajustes) usan `.app-view`: cabecera de 48px y cuerpo (`.app-view-body`) con scroll propio. El panel lateral solo desplaza su lista de enlaces (nunca la cuenta) y solo si no cabe; en carril no recorta los tooltips.
- *Sin márgenes de página:* no hay gutters globales; el padding lo define cada panel (12–16px, ver 5b). Ningún contenedor centra la página.
- *Qué puede tener ancho máximo:* solo el contenido interior de un formulario o de un texto largo, alineado a la izquierda y nunca centrando la página (contenido de subir y de cada categoría de ajustes: 720px). Excepción: la pantalla de acceso, que no está en el marco, centra una tarjeta de 400px.
- *Inicio de sesión:* única pantalla fuera del marco; sin tarjeta ni borde, una columna de 440px como máximo centrada sobre `bg` y alineada a la izquierda, siguiendo la referencia aprobada por el dueño (formulario de acceso moderno de página completa). De arriba abajo: recuadro de marca de 64px (`fill`, radio `xl`) con el isotipo de 40px (decorativo; el encabezado ya nombra el producto), encabezado «Bienvenido a Sauri» (2.5rem, 700, 2rem bajo 480px), una línea de subtítulo de 20px en `fg`, campos «Correo electrónico» y «Contraseña» de 64px de alto, radio `lg` (16) y texto de 18px, con el nombre del campo como marcador dentro (la etiqueta sigue en el DOM, oculta visualmente, para lectores de pantalla) y el botón de mostrar u ocultar la contraseña dentro del campo (`Eye`/`EyeOff`, nombre accesible «Mostrar contraseña»/«Ocultar contraseña»), y un botón primario de 64px a todo el ancho, deshabilitado hasta que ambos campos tienen texto, con «Iniciando sesión…» mientras espera. Por ser un formulario aislado, es la única excepción a 5b y a los límites de tamaño y peso (peso 700 y tamaños mayores) de esta sección. El error es un bloque `role="alert"` con icono y texto (mensaje uniforme del servidor, sin distinguir cuenta inexistente de clave errónea). Debajo, el área de proveedores externos (`LoginProviders`: separador «o» y un botón de contorno por proveedor, a todo el ancho, con su glifo) solo se pinta si hay al menos un proveedor habilitado; hoy no hay ninguno, así que no existe un botón «Continuar con Google» sin función. No hay «¿Olvidaste tu contraseña?», registro ni pie legal mientras el backend y el producto no los tengan.
- *Panel lateral:* 220px expandido; carril de 60px (solo iconos, con tooltip al pasar el cursor o enfocar) y botón `PanelLeft` para alternar. Filas de 32px con icono de 16px y texto de 13px/500; marca de 15px/600. La elección se recuerda por dispositivo en `localStorage` (si el almacenamiento está bloqueado, solo dura la visita); bajo 1320px arranca contraído. Bajo 640px es un cajón fuera de pantalla que se abre desde una barra superior delgada: foco dentro al abrir y de vuelta al cerrar, Escape y velo lo cierran, `aria-expanded` en el botón. Contenido: «Biblioteca» (fila seleccionada con `accent-soft`) y, abajo, la fila de perfil plana (avatar de 28px con iniciales, nombre con elipsis, correo en `fg-subtle`) con un menú de «Cerrar sesión» y el engranaje hacia `/settings`.
- *Configuración (`/settings`):* cabecera de 48px con el título («Configuración», 15px/600); debajo, navegación a la izquierda (panel de 208px con borde derecho) y la categoría elegida a la derecha, con scroll propio y contenido de hasta 720px alineado a la izquierda (texto de 14px). La navegación empieza con un campo «Buscar» (32px, radio 8, icono `Search`, botón de borrar) y sigue con grupos bajo etiquetas pequeñas apagadas (11px en mayúsculas, `role="group"` con `aria-labelledby`, no encabezados, para no competir con el título de la categoría): «General» (Cuenta, Apariencia), «Modelos» (Motores y modelos, Transcripción, Hablantes, Resúmenes); «Chat» queda reservada y no se lista ni se enruta. Filas de 32px con icono Lucide de 16px (`UserRound`, `Palette`, `Sparkles`, `Mic`, `UsersRound`, `FileText`); la activa con `accent-soft` y `aria-current="page"`. Direcciones: `/settings/cuenta`, `/apariencia`, `/motores`, `/transcripcion`, `/hablantes`, `/resumenes` (definidas en `router.ts`; son las mismas en todos los idiomas); `/settings` muestra «Cuenta» (en móvil, la lista), la antigua `/settings/grabacion` (sección retirada, sin ajustes) abre `/settings`, y cualquier otra dirección desconocida es «no encontrado». Búsqueda: coincidencia sin acentos ni mayúsculas sobre etiqueta, descripción y palabras clave (todas las palabras escritas deben aparecer); oculta los grupos vacíos, anuncia el número de resultados con `role="status"`, muestra «Sin resultados para «…»» si no hay coincidencias, Escape (o el botón) la borra, Intro abre el primer resultado y las flechas arriba/abajo recorren el campo y las filas; no cambia la categoría abierta ni la dirección. Las categorías sin pantalla propia muestran una línea «Próximamente: …» sin controles. Bajo 640px son dos pasos: la lista (con el buscador; filas-tarjeta de 36px con descripción y chevron, 44px con puntero táctil) y la categoría con un botón de regreso; el filtro se conserva al volver y el foco pasa al título de la categoría. Solo hay controles de opciones que el portal puede cambiar de verdad; lo que se configura en otro sitio (la extensión) se explica con texto, sin controles inertes. Selector de idioma («Idioma» / «Language»): tarjeta al inicio de «Apariencia», con el mismo grupo de opciones nativas (`radio`) segmentado, «Español» y «English» escritos en su propio idioma (`lang` en cada opción); el cambio es inmediato y se anuncia en la región `role="status"` en el idioma recién elegido. También aparece bajo el formulario del inicio de sesión. Selector de tema: grupo de opciones nativas (`radio`) con aspecto segmentado de 28px. Interruptor (`role="switch"`, 36×22px, sube a 44px de área táctil con puntero táctil) para «Iniciar con el panel plegado», que comparte la preferencia del panel lateral.
- *Biblioteca = lista y detalle (master–detail, como la bandeja de APX):* las rutas `/` y `/meetings/:id` comparten un espacio de trabajo (`LibraryWorkspace`). Desde 1100px de ventana muestra **dos paneles**: la lista (340px, fondo `bg`, borde derecho) y el detalle (resto, fondo `surface`); `/` muestra en el detalle una pista discreta y centrada («Elige una grabación…»; con la lista oculta, el estado vacío con botón descrito en los paneles secundarios) y `/meetings/:id` abre la reunión sin salir de la lista, con su fila marcada (`aria-current="true"`, fondo `fill-strong`). Bajo 1100px es de un paso: `/` muestra solo la lista a todo el ancho y `/meetings/:id` solo el detalle con un botón de regreso (flecha, nombre «Volver a las grabaciones») en su cabecera. La cabecera de la lista (48px) lleva el título (15px/600; `h1` solo cuando no hay reunión abierta, para que la pantalla tenga un único `h1`) y el botón primario compacto «Subir grabación» (28px); debajo, una barra de iconos de 40px (casilla de seleccionar todas, buscar, fechas, ordenar y, con filtros, limpiar; ver Menús y Popover en 7). Grupos por fecha (etiqueta de sección de 11px) y filas compactas de 56–68px: miniatura de 64×36 (16:9, radio 6, borde `border`, fondo `fill`, `object-fit: cover`, carga diferida y `alt` vacío; sin imagen, o si falla, icono Lucide de 16px: `Video` o `AudioLines` si es solo audio), título de 14px/500 en una línea con elipsis, insignia de estado de 11px a su derecha y metadatos de 12px (fecha · duración en mono · hablantes). Borde izquierdo de estado de 3px; hover tonal (`fill-hover`); abierta `fill-strong` con título en 600. Enter abre la fila. La fila **no** lleva el resumen: el «Asunto principal» (`summaryTopic`) sale como tooltip de la fila (500ms, hasta 320px, 6 líneas con elipsis); sin resumen no hay tooltip. En una fila con error, el tooltip empieza por la causa («No se detectó voz…» o «No se pudo procesar…») y la insignia sigue diciendo «Con error».
- *Paneles secundarios plegables:* patrón común (`useSecondaryPane(clave)`): cuando la sección abierta tiene un panel secundario junto al contenido, su elemento del panel lateral es un botón que lo oculta o muestra (`aria-expanded`, `aria-controls` con el `id` del panel, nombre accesible fijo, tooltip «Ocultar …» / «Mostrar …»; el foco se queda en el botón). La elección se recuerda por dispositivo y por panel (`localStorage`; con el almacenamiento bloqueado dura la visita). El panel oculto sigue montado (conserva búsqueda, scroll y selección), con `inert` y `aria-hidden`; la transición es de ancho y opacidad en `--ds-duration` (0 con movimiento reducido) y el contenido ocupa todo el ancho. Un elemento sin panel secundario que mostrar es un enlace normal, sin `aria-expanded`. Hoy hay dos: **Biblioteca** (lista; en `/` y en `/meetings/*` con ventana de 1100px o más, con o sin reunión abierta; `aria-controls="library-pane"`, `aria-current="page"`; tooltip «Ocultar biblioteca» / «Mostrar biblioteca»; clave `sauri_library_pane_hidden`; la elección se conserva en `/` y al abrir una reunión. Con la lista oculta y sin reunión abierta, el detalle muestra un estado vacío centrado (`h1` «Elige una grabación» y el botón primario «Mostrar biblioteca», que la devuelve y mueve el foco a la lista); sin elección guardada la lista arranca visible. Bajo 1100px es el enlace de siempre: desde otra sección apunta a la última reunión, si la hay) y **Configuración** (el engranaje del perfil; en cualquier ruta `/settings/*` desde 640px; `aria-controls="settings-pane"`, `aria-current="page"` se mantiene; tooltip «Ocultar categorías» / «Mostrar categorías»; clave `sauri_settings_pane_hidden`; la categoría abierta ocupa el ancho con su contenido de hasta 720px alineado a la izquierda; un enlace profundo que cambia de categoría conserva el estado; bajo 640px siguen los dos pasos y la elección no se aplica).
- *Última reunión explorada:* el portal recuerda por dispositivo la última reunión abierta (`localStorage`, clave `sauri_last_meeting_id`; se guarda cuando `/meetings/:id` se muestra y el servidor la reconoce; con el almacenamiento bloqueado no se recuerda nada ni se redirige). Regla: solo en el **arranque** de la sesión (primera resolución de la ruta tras abrir la app o tras iniciar sesión, y de nuevo tras cerrar sesión de forma explícita) y solo si la ruta es `/`, el portal sustituye `/` por `/meetings/<id>` con `replaceState` (sin entrada nueva de historial, así que Atrás no entra en bucle) antes del primer pintado, sin destello de la biblioteca vacía. Después, ir a `/` (cabecera de la lista, botón Atrás) nunca redirige; los enlaces directos (`/meetings/:id`, `/settings/...`, `/upload`) no se tocan. Si la reunión ya no existe (404, o la lista cargada no la incluye) se olvida y se muestra la biblioteca con su pista; borrar la reunión abierta también la olvida. «Biblioteca» desde otra sección (p. ej. Configuración) lleva a la última reunión o, si no hay, a `/`.
- *Acciones de fila:* a la derecha de cada fila, un botón «⋯» de 30px (`ui-icon-button--ghost`, nombre «Acciones de «título»») con un menú: «Renombrar» (el título pasa a un campo en la fila: Enter guarda, Escape cancela, el error sale en la fila), «Descargar transcripción» (el mismo `<título>.txt` que la cabecera del detalle; deshabilitado con explicación si la grabación no está lista), «Descargar resumen» (`<título> - resumen.txt`, el mismo texto que el botón «Descargar» del panel de resumen; deshabilitado con «Aún no hay resumen» mientras la lista no informe un resumen), «Descargar video» (`<título>.<ext>` según el tipo del archivo; «Descargar audio» con icono `AudioLines` si la grabación es solo audio; deshabilitado con explicación si no está lista), un separador y «Eliminar» (peligro; diálogo de confirmación; si era la abierta, se vuelve a `/` y se olvida como última reunión). Iconos Lucide: `Pencil`, `FileText`, `ScrollText`, `Video`/`AudioLines`, `Trash2`. `MenuSeparator` (`role="separator"`, 1px `border`) separa grupos y las flechas lo saltan. La descarga de video guarda el archivo por flujo (sin cargarlo en memoria) con el selector de archivos del navegador cuando existe y el almacén de objetos permite el origen del portal; si no, abre el enlace firmado en otra pestaña y lo dice en la fila. Mientras guarda, una línea `role="status"` bajo la fila muestra el avance. Aparece con hover, foco, fila abierta o seleccionada y siempre con puntero táctil. El menú se abre hacia arriba si abajo no cabe dentro del panel con scroll. La lista es una sola parada de Tab: la fila activa lleva el foco de tabulación y las flechas, Inicio y Fin mueven entre filas.
- *Selección múltiple y acciones en bloque:* patrón elegido: lista (`ul`) con **casilla nativa por fila** (nombre «Seleccionar «título»»), no `listbox`/`aria-multiselectable` ni cuadrícula, porque la fila contiene controles interactivos (abrir, casilla, menú) que un `option` no admite; el estado va en `checked` y el recuento en una región `role="status"`. La casilla (sobre la miniatura) aparece con hover y foco y siempre en modo selección o con puntero táctil; Mayús+clic selecciona un rango en el orden mostrado, Ctrl/Cmd+clic alterna, clic normal abre. La casilla de la barra de iconos selecciona o deselecciona **solo las filas visibles** (con búsqueda, solo las filtradas) y muestra estado indeterminado. Con una o más seleccionadas, la cabecera y la barra de iconos se sustituyen por la barra de acciones: «N seleccionadas» y «Cancelar» (48px), y debajo «Seleccionar todas», «Descargar transcripciones» (icono `FileText`), «Descargar resúmenes» (icono `ScrollText`) y «Eliminar» (40px); Escape también limpia. La selección se guarda por id: sobrevive a las actualizaciones de la lista y pierde lo que desaparece. Eliminar pide confirmación con el recuento y «no se puede deshacer»; después un diálogo `Dialog` modal muestra el avance («Eliminando 3 de 12…»), de a una grabación (concurrencia 1), sigue si una falla y termina con un resumen («Se eliminaron 10; 2 no se pudieron eliminar») con «Reintentar» para las fallidas, que siguen seleccionadas; Escape o cerrar durante el avance detienen el resto. Descargar baja un `.txt` por grabación lista (transcripciones) o con resumen (resúmenes), de a una, pide confirmación desde 6 y avisa de las omitidas. No hay descarga de video en bloque: los archivos son demasiado grandes. El foco vuelve a la cabecera de la lista.
- *Subir:* cabecera de 48px (botón «← Volver» pequeño y título); debajo, la introducción de 13px y una zona de arrastre del tamaño de su contenido (no gigante; borde discontinuo 2px, radio 10, un único botón primario de 32px), de hasta 720px y alineada a la izquierda. Las tarjetas de archivo, progreso y error tienen el mismo ancho.
- *Reunión (detalle):* tira de cabecera (56px mínimo): título como único `h1` (16px/600, una línea con elipsis y el título completo en `title`), junto al título un lápiz (`Pencil` de 16px, visible con hover o foco en escritorio y siempre con puntero táctil) y debajo los metadatos de 12px (insignia de estado, fecha, duración, hablantes). *Renombrar en línea:* el lápiz, el doble clic en el título y «Renombrar» del menú «…» convierten el título en un campo que hereda su tipografía y su posición (sin etiqueta visible, sin botones, sin cambio de alto ni de ancho; fondo `fill` y subrayado de 2px `focus`; nombre accesible «Título de la reunión»), con el texto entero seleccionado; Enter o salir del campo guardan si cambió y no está vacío (pendiente: campo al 60 % de opacidad y de solo lectura); Escape, un nombre vacío o un fallo devuelven el título anterior, y el aviso («El nombre no puede quedar vacío…», `role="status"`; o el error, `role="alert"`) flota bajo la cabecera 5 s sin mover nada; el foco vuelve al lápiz si se cerró con teclado y a la derecha los iconos de acción de 30px (hablantes con punto de aviso, descargar, «…»); en panel estrecho las acciones pasan a su propia fila. Si hay trabajo en curso, una tira de proceso compacta bajo la cabecera (pasos numerados de 20px en una línea, titular de 14px, explicación de 13px, barra de 8px y cifras de 12px). El cuerpo son **paneles**, no una página larga: cuando el panel de detalle mide 760px o más (consulta de contenedor, no de ventana) hay dos paneles separados por 1px, el izquierdo flexible con el **reproductor arriba** (video con `max-height: 42vh`, controles de 28px, línea de oradores de 24px de alto con leyenda de 12px) y debajo la **transcripción con scroll propio** (cabecera de 40px con «Transcripción» y el interruptor «Seguir la reproducción»), y el derecho fijo de 380px (400 desde 1100px de detalle) con las pestañas «Notas y resumen» y «Chat» (32px, subrayado) y su propio scroll. Bajo 760px de detalle se apila (reproductor, pestañas, transcripción) y se desplaza como una sola página dentro de la región. Turnos de la transcripción: ocupan todo el ancho del panel (sin ancho máximo; el texto, la fila del hablante y los resaltados se estiran con él); texto de 14px con interlineado 1.55, hablante de 12px/600 en su color, tiempo de 11px en mono, relleno 6px 10px, hover tonal, turno activo con `highlight` y borde izquierdo del hablante; avatar de 24px. Resumen: cuerpo de 13px, etiquetas de sección de 11px, viñetas con separación de 6px, bloque de progreso compacto.

**Panel lateral de la extensión.** Una columna de ancho variable (320–480px). Cabecera con marca e iconos de 44px, cuerpo con tarjetas de 16px de padding, acciones a todo el ancho (la principal con peso 1.4). Cronómetro de 40–56px con cifras tabulares. (La densidad de escritorio de 5b es del portal; la extensión conserva sus medidas táctiles.) El botón de ajustes (`SlidersHorizontal`) de la fila de controles abre un popover no modal (`role="dialog"`, 300px como máximo, alineado a la derecha bajo el botón) con «Cuenta regresiva» y «Resolución» (selectores nativos con tokens), «Barra de control» y «Avisar si el micrófono está apagado» (interruptores `role="switch"`); cada cambio se guarda al instante y Escape, un clic fuera o salir con Tab lo cierran. Durante una grabación, cuenta regresiva y resolución se bloquean (valen para la siguiente) y la barra de control se aplica al momento.

**Página de permisos (opciones).** Columna de máximo 740px centrada, tarjeta con insignia de estado, pasos numerados y un solo botón de acción.

**Overlay de Meet.** Tres piezas fijas sobre la página: aviso superior centrado, cuenta regresiva a pantalla completa (velo `scrim-strong`, texto `on-scrim`) y barra flotante arrastrable abajo a la izquierda (superficie `surface-raised`, borde `border-strong`, `shadow-md`). Controles de 44px; el botón de detener usa `accent`; descartar usa `danger`.

## 7. Componentes

Los componentes del portal están en `frontend/src/components/ui/` y los de la extensión en `panel.css`; comparten medidas y estados.

- **Botones.** Altura sm 28 / md 32 (por defecto) / lg 36 (`size` en `Button`; 44 con puntero táctil), padding horizontal 12 (16 en lg), texto 14 (13 en sm), radio `sm`, peso 500. Primario (`accent`/`accent-fg`, hover `accent-hover`), secundario (`fill-hover`, texto `accent-text`, borde `border`), fantasma (transparente), peligro (`danger`/`danger-fg`, hover `danger-hover`). Un primario por grupo; deshabilitado con opacidad 0.5. Sin sombra en hover: el hover es tonal.
- **Campos.** Altura mínima 32 (44 con puntero táctil), texto 14, borde `border-strong`, radio `sm`, fondo `surface`. Etiqueta de 13px/500 en `fg-muted`, visible siempre; el marcador de posición no la sustituye. Error: borde `danger-text`, texto de error asociado con `aria-describedby` y `aria-invalid="true"`.
- **Tarjetas.** Solo para contenido secundario dentro de una pantalla de una columna (ajustes, subida; las regiones principales son paneles, ver 5b). `surface`, borde `border`, radio `card` (10), padding 16, sin sombra. Si es clicable, el hover cambia el fondo a `bg` y el borde a `accent`; nada se desplaza.
- **Listas.** Filas planas de 56–68px separadas 2px dentro de un panel; abierta (`fill-strong`, `aria-current`), marcada para acciones en bloque (`accent-soft` más casilla marcada) y hover (`fill-hover`) son estados distintos; el título lleva elipsis de una línea y el texto largo de contenido, `overflow-wrap`.
- **Pestañas.** Estilo subrayado: altura 32, texto 14/500, indicador de 2px en `accent`, texto `accent-text` y peso 600 en la activa, borde inferior de 1px en la lista, `aria-selected`; sin relleno.
- **Insignias.** Pastilla de 20px con texto de 11px/600 siempre presente: éxito (`accent-soft`/`accent-soft-fg`), progreso (`warning-soft`/`warning-soft-fg`), error (`danger-soft`/`danger-soft-fg`), neutral (`fill`/`fg-muted`). Variante `dot` de `StatusBadge`: punto de 6px (`currentColor`, decorativo) antes del texto; se usa en los estados de proveedor («● Activo», «● Apagado») y del catálogo («● Disponible», «● No responde»). «Sin configurar» va sin punto. El estado siempre está escrito.
- **Tarjeta de proveedor.** Catálogo precargado en Configuración > Motores y modelos (réplica de la forma de APX, con la paleta Terra y copy propio): una `Card` por cada tipo que `/capabilities` marca `linkable` (rejilla de mínimo 17rem, separación `space-3`; `chatgpt_plan` no se muestra). Orden: proveedores activos, «Sin clave», apagados, tipos «Sin configurar» y, al final, la ficha punteada «+ Agregar proveedor» (no hay estado vacío ni botón primario). Cabecera: marca circular de 36px (`ProviderLogo`), nombre en 600, tipo en `text-xs` si el nombre difiere e insignia con punto. Cuerpo en filas clave/valor (`dl`, etiqueta `fg-subtle`, valor en mono si es técnico): «Dirección», «Clave» (`••••1234`, «No hace falta» en Ollama/LM Studio, «—»), «Modelos» («N disponibles», «Sin lista», «—» si no se pidió), más «Usado en: …». Pie: interruptor «Activo» (`role="switch"`, nombre «Activo» + nombre del proveedor), lápiz y papelera con nombre accesible. Apagado: `Card` con `dimmed` (fondo `bg`, texto `fg-muted`, marca sin relleno; nunca baja de `fg-subtle`, por eso no usa opacidad). «Sin configurar»: `dimmed` + `dashed` (borde `border-strong` discontinuo), una ayuda («Pega una clave para usar sus modelos.») y «Configurar»; sin papelera ni interruptor. Encender un proveedor es inmediato y no envía nada; apagar uno que usan procesos pide confirmación (esos procesos vuelven al motor local). Una clave nunca se muestra: solo `••••1234` (los últimos cuatro caracteres que informa la API). **Logotipos:** pequeños identificadores de proveedor (36px en tarjetas, 22px en fichas, selectores y catálogo), siempre junto al nombre y decorativos (`aria-hidden`). Son los trazos monocromos de simple-icons (CC0) en `frontend/src/assets/providers/logos.ts`, dibujados con `currentColor` para seguir el tema, sin ficheros ni red en tiempo de ejecución; el proveedor sin trazo (OpenAI, Groq, AssemblyAI, servidor compatible) usa un monograma en el mismo círculo. Las marcas son de sus dueños y se usan solo para identificar al proveedor (uso nominativo), sin implicar afiliación; no van en la extensión ni en `brand/`. El diálogo de proveedor usa fichas con logo (`radiogroup`, selección con contorno `accent`, texto 600 y `accent-soft`), ayuda bajo cada campo, validación en línea (el botón principal «Guardar y probar conexión» queda inactivo hasta que el formulario es válido), sin campo de clave en Ollama/LM Studio y la clave guardada como marcador de posición («••••1234 — Guardada — escribe una nueva para reemplazarla») con «Quitar clave» como enlace secundario que lista los procesos que volverían al local. El resultado de «Guardar y probar conexión» es un bloque con icono y texto («Responde» / «No responde» y la causa), nunca solo color. El catálogo «Modelos» (debajo de los proveedores) tiene buscador, «Actualizar» y una fila plegable por proveedor activo con clave (botón con `aria-expanded`): logo, nombre, «N modelos · pedida hoy HH:MM», insignia «Disponible» / «No responde» con la causa en texto, y al expandir la lista nombre + id en mono con scroll propio.
- **Selector de motor por proceso.** En Configuración > Transcripción, Hablantes y Resúmenes: tarjeta «Hoy usa: …» con insignia «Local» o «Externo» y una línea que dice qué sale del equipo; debajo, `ModelPicker`: un botón con aspecto de campo (logo, motor y modelo en mono) que abre un popover no modal (`role="dialog"`) con buscador, una lista `listbox` agrupada («En este equipo» con «Local (recomendado)» y los modelos instalados con su peso y la marca «Activo» (el que sirve el proceso ahora), y un grupo por proveedor activo, con clave y compatible, con su logo), la marca «En uso» (con `aria-selected`) y «Sugerido» en texto, «Volver a pedir» por grupo, nombre de modelo manual si el proveedor no entrega lista, y el pie «Volver al local». El catálogo de cada proveedor se pide al abrir (`listEngineModels`). Teclado: flecha abajo en el botón abre; en el buscador flecha abajo entra en la lista; flechas, Inicio y Fin recorren las opciones; Escape cierra primero el popover y devuelve el foco al botón. Elegir un modelo del proveedor ya en uso se guarda al instante; elegir otro proveedor externo **no guarda**: abre el aviso de privacidad (`Dialog`, «Cancelar» antes de «Aceptar y usar», con las advertencias de doble envío y calidad no validada) y solo guarda al aceptar; volver a local se guarda al elegirlo. Debajo, el interruptor de respaldo local y las advertencias (bloque `warning-soft` con icono `TriangleAlert` y texto, nunca solo color).
- **Tarjeta de modelos locales.** Una por proceso (Transcripción, Hablantes, Resúmenes), debajo de «Hoy usa» y del selector: `Card` «En este equipo» con la frase de hardware en lenguaje llano (más la razón de la recomendación y sus cautelas, en `text-sm`), el menú «…» de la tarjeta («Buscar instalados») y una fila compacta por opción local (borde de 1px, radio `thumb`, fondo `bg`; la activa, `accent-soft` con borde izquierdo de 3px). Cada fila dice en texto: nombre y peso, insignias de estado («Instalado» y «● Activo ahora», «Disponible para instalar», «Presente sin verificar» con su motivo en una frase, «Verificando…»), «Instalado a mano» (archivo fuera de la carpeta de Sauri: nunca se borra), «Recomendado para tu equipo» y la marca «Medido»/«Propuesta», una línea de descripción (motor y memoria mínima) y, a la derecha, la acción de la fila: «Usar este» (instalado y no activo; guarda al instante la elección local, sin aviso), «Instalar» con el espacio que necesita (inactivo con el motivo si no cabe en el disco) o «Verificar». El avance es un `ProgressBar` con una frase en `role="status"` que cambia solo por porcentaje entero y «Cancelar». «Verificar» y «Quitar» viven en un menú «…» por fila; «Quitar» pide confirmación y queda bloqueado con el motivo escrito en el menú mientras un proceso lo use o si es un archivo instalado a mano. Los motores administrados (Senko) no se descargan: instalado dice «Motor de hablantes de Sauri · Instalado · Activo ahora»; sin instalar muestra el comando. Los archivos de apoyo (detector de voz) son una línea «Detector de voz (apoyo)», no una opción. Mientras el servicio reconoce lo que ya había en el equipo, un `role="status"` dice «Reconociendo lo que ya tienes instalado…». Al final, el grupo «Servicios externos» pone la opción externa junto a las locales y abre el selector de motor (el aviso de privacidad sigue allí). El aviso «Motor no instalado» es un bloque `warning-soft` con el comando en `code` y las herramientas que necesita.
- **Diálogos.** `<dialog>` nativo: padding 16, borde, radio `md`, `shadow-md`, velo `scrim`, título, acción secundaria antes de la principal, foco inicial dentro, cierre con Escape y retorno del foco al disparador. Para contenido con formulario o listas largas, `Dialog` (`ui/Dialog.tsx`): panel centrado `surface-raised` en un portal (anchos `sm` 28rem y `md` 34rem), cabecera fija (título de 16px y botón `X` de 30px) con relleno de 8/16, cuerpo de relleno 12/16 con desplazamiento propio, resto de la página inerte y sin desplazamiento, foco atrapado, cierre con Escape, botón de cerrar o clic en el velo, y retorno del foco al disparador.
- **Menús.** Panel `surface`, borde, `shadow-md`, filas de 28px con texto de 13px (44px con puntero táctil), hover `fill-hover`, elemento destructivo en `danger-text`, navegación por teclado; un elemento deshabilitado puede explicar por qué con `hint` (título nativo y descripción). Una elección única usa `role="menuitemradio"` con `aria-checked` y una marca `Check` en la opción activa (`MenuItem checked`).
- **Popover.** `Popover` (`ui/Popover.tsx`): panel no modal `role="dialog"` para formularios pequeños (p. ej. rango de fechas). Enter, Espacio o Flecha abajo lo abren y el foco pasa a su primer control; Escape lo cierra y devuelve el foco al disparador; un clic fuera o salir con Tab lo cierra sin quitar el foco. El panel se desplaza para quedar dentro del viewport.
- **Icono con punto de aviso.** `ui-icon-button--alert` (botón fantasma de 30px) pinta un punto `danger` de 6px arriba a la derecha con anillo de 2px del color de la superficie; el punto es decorativo y el estado va en el nombre accesible y el tooltip («Hablantes: 3 sin nombre»). Sin pendientes no hay punto. Lo usa la cabecera de la reunión para los hablantes: icono `UsersRound` a la izquierda de Descargar, con un `Popover` que muestra el mensaje y abre la revisión de hablantes.
- **Barra de iconos de filtros.** Botones `ui-icon-button--ghost` de 30px con nombre accesible y tooltip que incluyen el estado actual. Un control con valor distinto del predeterminado usa `ui-icon-button--active` (relleno `accent-soft` y punto de acento: forma, no solo color). La búsqueda se despliega en línea, conserva el foco, se cierra con Escape o con su botón `X` (borrando el término) y, si tiene texto, permanece abierta; mientras la búsqueda está abierta el campo llena la barra (28px de alto) y los demás iconos se ocultan.
- **Tooltips.** Solo texto breve, complemento (no reemplazo) del nombre accesible; sin botones dentro. Los iconos del carril del panel lateral usan CSS a partir de la etiqueta oculta. En el portal, `useTooltip` (`ui/Tooltip.tsx`, hoy en el disparador de `Menu` con `tooltip`) usa `role="tooltip"` enlazado con `aria-describedby`, aparece tras 400ms con el puntero o el foco de teclado y se cierra con Escape. Para texto largo (el resumen de una fila de la biblioteca) la variante `ui-tooltip--wrap` espera 500ms, mide hasta 320px, parte líneas (6 como máximo, con elipsis) y se coloca fija junto al disparador para no quedar recortada por el scroll del panel.
- **Avisos (toasts).** (Regla para cuando se creen.) Esquina inferior, `surface-raised`, borde y `shadow-md`; se anuncian con `role="status"` (error: `role="alert"`).
- **Progreso y pasos.** Barra de 8px, pista `fill-strong`, relleno `accent`. Sin estimación, la barra indeterminada pulsa en `accent-muted` (sin degradados). El paso actual se marca con número, contorno de acento y texto en negrita, no solo color.

## 8. Iconos

- Familia **Lucide**, lineal, heredan `currentColor`. Los componentes React usan `core/design/Icon.tsx` y el overlay `overlay/icons.ts`; ambos toman tamaño (18) y trazo (1.75) de `core/design/iconDefaults.ts`, un único punto de cambio. No se cambia la librería ni el trazo sin necesidad documentada.
- Escala: `icon-xs` 12, `icon-sm` 14, `icon-md` 16, `icon-lg` 18. Botón de icono: 30×30 (32 en `--md`; 44 con puntero táctil) con icono de 16px. En el portal, `.ui-icon-button` (primario `--primary` para la acción principal del grupo, `--quiet` para las secundarias).
- Decorativo: `aria-hidden="true"`; acción solo con icono: nombre accesible (`aria-label`).
- El color de un icono lo da el texto que lo rodea (`fg-muted`, `accent-text`, `danger-text`).

## 8b. Marca

- El isotipo de Sauri (dos mitades verdes separadas por una diagonal, con un rombo al centro) y el logo horizontal viven en `brand/`; las reglas de uso, la variante pequeña (32px o menos) y el espacio libre están en `brand/README.md`.
- Sus dos verdes (`#4a7c59`, `#78a886`) son fijos en todos los temas y no forman parte de la paleta de la sección 3: no se convierten en tokens ni se recolorean.
- En la interfaz se dibuja con `BrandMark` (`frontend/src/components/ui/BrandMark.tsx` en el portal, `extension/src/core/design/BrandMark.tsx` en la extensión), decorativo junto al nombre «Sauri» visible; con `title` expone ese nombre. En el carril del portal queda solo el isotipo.

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
3. Objetivos de puntero: ≥24×24 con ratón (las alturas de 5b, de 28 a 36px) y 44px con puntero táctil (`pointer: coarse`).
4. El estado nunca se transmite solo con color (borde de estado + texto; paso con número; error con mensaje).
5. Formularios: etiqueta asociada, `aria-invalid` y `aria-describedby` hacia el error o la ayuda.
6. Diálogos: título, foco inicial, atrapar el foco, Escape y retorno del foco (el `<dialog>` nativo lo resuelve).
7. Reflujo: sin desplazamiento horizontal a 320px de ancho y con zoom del 200%. Tablas y código se desplazan dentro de su contenedor.
8. Movimiento reducido respetado; ninguna información depende de una animación.
9. Contenido dinámico (progreso, avisos) en regiones `role="status"` o `role="alert"`.
10. Nombre accesible en todo botón de icono; iconos decorativos ocultos.

## 10b. Idioma y textos (ES/EN)

El portal está en español (idioma por defecto, fuente de verdad y respaldo) e inglés. Pila: `i18next` + `react-i18next`, un espacio de nombres por área, plurales nativos de i18next (`_one` / `_other`), claves tipadas y formatos de `Intl`. Se eligió porque es la pila estándar de React, resuelve plurales por idioma sin escribir condiciones a mano, tipa las claves desde los archivos en español (una clave mal escrita falla `tsc`) y permite cargar el inglés bajo demanda.

**Dónde viven los textos.** `frontend/src/locales/<idioma>/<área>.json` (`es` y `en`; áreas: `shell`, `login`, `library`, `meeting`, `processing`, `speakerReview`, `summary`, `transcript`, `upload`, `settings`, `engines`, `language`). El español define la forma: el inglés debe tener las mismas claves y las mismas variables. Los nombres de proveedores y los identificadores técnicos no se traducen. El inglés escribe «Sauri» igual que el español.

**Cómo agregar un texto nuevo.**
1. Agrega la clave en `locales/es/<área>.json` y su traducción en `locales/en/<área>.json` (frases cortas, mismo tono; no repitas el texto en el componente).
2. Úsala con `const { t } = useT();` y `t("área:ruta.clave")` (hook de `src/i18n`, que se actualiza al cambiar de idioma). Fuera de un componente, `import { t } from "../i18n"`.
3. Variables: `{{nombre}}` y se pasan como `t("área:clave", { nombre })`. Plurales: dos claves `clave_one` y `clave_other` con `{{count}}` y se llama con `{ count }` (no escribas `count === 1 ? … : …`).
4. Fechas, números y listas: `formatDate`, `formatNumber`, `formatList` de `src/i18n/format.ts` (usan `Intl` con el idioma activo); nunca `toLocaleString("es")` ni formatos escritos a mano. Las horas de reproducción `mm:ss` no se traducen.
5. Los códigos que envía el backend (causas de fallo, errores de guardado) se traducen con una clave por código; un código desconocido muestra la frase genérica (`translateIfKnown`).
6. `npm run i18n:check` (también corre dentro de `npm test`) falla si falta una clave en algún idioma, si las variables o las formas de plural difieren, o si un `.ts`/`.tsx` fuera de `locales` y de las pruebas contiene texto en español (marca `i18n-ignore` en la línea para las pocas excepciones, p. ej. los nombres de idioma o las direcciones URL).

**Cómo agregar un idioma.** Crea `locales/<código>/` con todos los archivos, agrégalo a `SUPPORTED_LANGUAGES` y `LANGUAGE_NAMES` (`src/i18n/languages.ts`), carga su paquete bajo demanda en `loadLanguage` (`src/i18n/index.ts`) y añade `matchLanguage` para su código. `i18n:check` valida lo demás.

**Elección del idioma.** Primero la preferencia guardada (`localStorage`, clave `sauri_language`); si no hay, el primer idioma de `navigator.languages` que sea `es*` o `en*`; si ninguno, español. Se aplica antes del primer pintado, fija `<html lang>` y el título de la pestaña, y la elección se guarda solo en el navegador. El paquete en inglés se descarga solo cuando se necesita.

**Pendiente (otra unidad).** Los textos que construye el backend (mensajes de error, causas de fallo del resumen, avisos de motores, etiquetas «Hablante N») y la extensión se traducirán después, con las mismas convenciones.

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
- [ ] Densidad de escritorio (5b): cuerpo 14px, ningún texto de pantalla sobre 16px, controles de 28–36px, regiones planas con borde de 1px y scroll propio.
- [ ] Biblioteca: lista de 340px + detalle desde 1100px; un paso bajo 1100px con botón de regreso; lista plegable desde el panel lateral también en `/` (estado vacío con «Mostrar biblioteca») y reapertura de la última reunión al arrancar; categorías de Configuración plegables desde el engranaje.
- [ ] Biblioteca: resumen solo como tooltip, menú «⋯» por fila y selección múltiple con acciones en bloque, con teclado y lector de pantalla.
- [ ] Foco visible y navegación por teclado completa (pestañas, menú, diálogo).
- [ ] Anchos de 320, 480, 768, 1024 y 1440 sin desplazamiento horizontal global; zoom 200%.
- [ ] `prefers-reduced-motion` desactiva pulsos y esqueletos.
- [ ] Textos largos (títulos de reunión, nombres de hablante) hacen salto de línea sin romper el layout.
- [ ] Extensión cargada en Chrome real: panel, página de permisos y overlay en Meet en ambos modos (verificación manual del dueño).
