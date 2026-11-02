# Especificación de interfaz de Sauri (extraída de Google Stitch)

- **Fuente:** proyecto Stitch "Sauri Meeting Intelligence Platform" (`projects/10424886024545918390`).
- **Sistema de diseño usado:** "Terra" (`assets/14831859670672193485`).
- **Extraída:** 2026-10-30.
- **Archivos de referencia en esta carpeta:**
  - HTML por pantalla y sus capturas originales: `login.html` / `login.jpg`, `biblioteca.html` / `biblioteca.png`, `subir.html` / `subir.png`, `reunion.html` / `reunion.jpg`, `hablantes.html` / `hablantes.png` y `plantillas.html` / `plantillas.png`. Las extensiones de captura reflejan el formato real decodificado.
  - `*.txt`: texto visible de cada pantalla, en orden.
  - `project.json` y `design_systems.json`: tokens completos.

## 0. Cómo usar esta especificación

**Las seis pantallas son exploratorias y no fueron aprobadas como especificación de interfaz ni como autorización de implementación.** Las capturas y HTML son referencias visuales no vinculantes; solo el alcance expresamente confirmado en el snapshot aprobado de `PRODUCT_BASELINE.md` puede guiar producto. Los textos, controles, estados, datos y composiciones no confirmados deben omitirse o esperar una decisión explícita.

**Conflicto con el producto:** el mock inventa datos y funciones que no son producto real. Donde contradice `PRODUCT_BASELINE.md`, **manda la línea base**. Los puntos están en la sección 8. Regla: nada de cifras de adorno, nada de funciones sin respaldo en la línea base.

**Orden de autoridad:** snapshot aprobado de `PRODUCT_BASELINE.md` > decisiones de producto posteriores aprobadas > estas referencias de Stitch (solo inspiración). Este README no agrega requisitos.

**El HTML y las descripciones siguientes son material de referencia no normativo, no instrucciones de implementación.** Traen contenido inventado y pueden sugerir capacidades, controles, datos y tratamientos no aprobados. No derivar requisitos de sus verbos imperativos, títulos, tokens visuales o ejemplos. Cualquier uso de estilos también requiere alcance visual aprobado.

## 1. Sistema de diseño: Terra ("Rooted Warmth")

Calmo, cálido, humano. Tonos tierra, formas suaves. Nada de neón ni blanco clínico.

### Color (modo claro único)

| Token | Valor | Uso |
|---|---|---|
| `primary` | `#4a7c59` | Acciones, navegación, foco |
| `on-primary` | `#ffffff` | Texto sobre primario |
| `primary-container` | `#78a886` | Relleno suave verde |
| `primary-fixed` | `#c8e8d0` | Fondos de chip y selección |
| `primary-fixed-dim` | `#8ecf9e` | Acento verde claro |
| `on-primary-container` | `#173621` (login) / `#d8f0de` (sistema) | Texto sobre contenedor primario |
| `secondary` | `#6b6358` | Texto y bordes secundarios |
| `secondary-container` | `#f0e8db` | Botón secundario, fondos crema |
| `tertiary` | `#705c30` | Acentos ámbar, insignias |
| `tertiary-container` | `#f4e7c7` (en pantallas) | Avisos suaves |
| `surface` / `background` | `#faf6f0` | Fondo de página (crema) |
| `surface-container-lowest` | `#ffffff` | Tarjetas |
| `surface-container-low` | `#f5f1ea` | Bloques secundarios |
| `surface-container` | `#f0ece4` | Barras y fondos de campo |
| `surface-container-high` / `highest` | `#eae6de` / `#e4e0d8` | Capas más altas |
| `on-surface` | `#2e3230` | Texto principal |
| `on-surface-variant` | `#4a4e4a` | Texto secundario |
| `outline` / `outline-variant` | `#74796e` / `#c4c8bc` | Bordes (variante con opacidad baja) |
| `error` | `#b83230` | Error |
| `error-container` / `on-error-container` | `#fce8e6` / `#690005` | Fondo y texto de error |

**Nota:** los valores de la tabla salen del `tailwind.config` de cada pantalla. Si un valor difiere entre pantallas, manda el del sistema Terra en `design_systems.json`.

El fondo no es plano. Hay tres manchas difuminadas (verde, ámbar y crema) detrás del contenido, como en el login.

### Tipografía

- **Títulos:** Literata (serif). Se usa en `h1`/`h2`.
- **Cuerpo y etiquetas:** Nunito Sans.
- **Datos técnicos** (hora, versión, ID): JetBrains Mono.
- **Tamaños** en los mocks: 10, 11, 13, 14, 15, 16, 18, 20, 24, 28 y 36 px.
- **Interlineado:** cómodo, 1.6 o más en el cuerpo.

### Forma y elevación

- **Radios:** base 8 px, `md` y `lg` 12 px, `xl` 16 px, `2xl` 20 px, píldoras `full`.
- **Botón primario:** verde sólido, radio 12 px. **Secundario:** crema con texto verde y borde fino.
- **Tarjetas:** relleno crema o blanco, relleno interno de 24 px, borde `outline-variant` a baja opacidad.
- **Sombra:** solo `0 4px 20px rgba(46,50,48,0.06)`. Se prefiere separar por tono antes que por sombra.
- **Campos:** fondo crema, radio redondeado, anillo de foco verde suave.

### Iconos

Material Symbols Outlined. Los nombres exactos están en los `.txt` (por ejemplo `history_toggle_off`, `record_voice_over`, `play_circle`).

### Reglas transversales

- Objetivos táctiles grandes y espaciado generoso.
- Sin esquinas duras ni contrastes violentos.
- Las imágenes deben verse naturales y cálidas.
- Texto sobre fondo: contraste mínimo WCAG AA. El texto de 10 y 11 px solo para metadatos, nunca para acciones.

## 2. Estructura común (todas menos el login)

**Barra superior fija:**
- Logo "Sauri".
- Navegación: **Biblioteca de grabaciones**, **Revisión de hablantes**, **Plantillas de resumen** (en el mock de hablantes y plantillas aparece "Configuración").
- Búsqueda global ("Buscar grabaciones…", atajo ⌘K).
- Indicador "Sincronizado".
- Botón **Subir grabación**.
- El menú mock de usuario muestra nombre, rol, **Diagnóstico** y **Cerrar sesión**. Son elementos ilustrativos no vinculantes: diagnóstico está expresamente excluido mientras su gobernanza esté pendiente; la experiencia de autenticación/cierre de sesión sigue sin decisión.

**Pie:** derechos de autor y enlaces Privacidad y Ética, Documentación y Soporte.

## 3. Inicio de sesión (`login`) — exploratorio, fuera de alcance

La autenticación, el inicio de sesión, la recuperación de credenciales, las sesiones y su experiencia siguen sin decisión. La captura `login.jpg` y su HTML son únicamente exploración visual: no implementar ni especificar esos flujos, estados, textos, controles o marca corporativa desde este documento.

<!-- Contenido de la maqueta conservado como referencia no normativa; no es especificación. -->

**Disposición:** tarjeta centrada de 480 px de ancho máximo, con encabezado fijo.

**Contenido de arriba abajo:**
1. **Aviso de sesión vencida** (cerrable con una X): "Sesión finalizada por inactividad. Por tu seguridad Summan, la sesión anterior expiró. Ingresa nuevamente para reanudar tus transcripciones." Solo aparece cuando la sesión expiró.
2. **Tarjeta de acceso:** título "Acceso a plataforma" y la frase "Inteligencia conversacional, separación de hablantes y minutas automatizadas de Summan."
3. **Mensaje de error:** "Correo o contraseña incorrectos. Verifica tus credenciales corporativas o solicita restablecimiento a IT Summan." Aparece solo si falla el acceso.
4. **Campo "Correo corporativo Summan"**, con el sufijo `@summan.com` y el ejemplo "ej. fer@summan.com".
5. **Campo "Contraseña"**, con el ojo para mostrar u ocultar y el enlace "¿Olvidaste tu contraseña?".
6. **Botón "Entrar a la plataforma"**, con flecha. Tiene estado de carga (icono girando). Se deshabilita mientras carga.

**Estados que se deben implementar:**
- Normal.
- Cargando.
- Error de credenciales.
- Sesión vencida.

**Fuera de la línea base (no construir):**
- Casilla "Recordar dispositivo de confianza (14d)".
- Botones "Continuar con Google Workspace" y "Microsoft Enterprise SSO".
- Insignias "SSO Enterprise", "AUDIO AI ENGINE v2.4" y "Cluster Activo".
- Textos de cifrado y "Zero-Trust".
- Botón "Simular error" (es de maqueta).
- Diagnóstico de red/estado de conexión y cualquier control de diagnóstico: excluidos; la captura es solo mock y cualquier instrumentación requiere una decisión de privacidad y gobernanza.

## 4. Biblioteca de grabaciones (`biblioteca`)

**Encabezado:**
- Título "Biblioteca de Grabaciones" y la descripción "Historial centralizado de reuniones procesadas…".
- Botón "Filtros avanzados".
- Botón "Subir grabación manual".

**Tarjetas de resumen:** cuatro, con total, listas, en procesamiento y requieren atención. Son solo una idea visual (ver sección 8).

**Barra de búsqueda y filtros:**
- Búsqueda: solo la capacidad expresamente respaldada por la línea base; la búsqueda de texto completo en reuniones queda excluida.
- Filtros: **Cliente**, **Proyecto**, **Estado** (Lista, Transcribiendo, Identificando hablantes, Subiendo, Con error), **Rango de fechas**.
- Etiquetas de tema como chips: `#GenAI`, `#DigitalTwin`, `#CloudArchitecture`, `#Finanzas`, con X para quitar, y "Limpiar filtros".

**Orden:** "Más recientes primero".

**Lista de reuniones.** Cada fila trae:
- Miniatura, o un icono de audio si no hay video.
- Duración en una esquina.
- Título, con lápiz para renombrar.
- Línea de datos: empresa • proyecto • fecha y hora.
- Participantes.
- Plantilla de resumen usada.
- **Insignia de estado:**
  - **Lista:** botón "Abrir reunión", descargar, copiar y menú "más".
  - **Identificando hablantes** (voces pendientes): aviso "2 voces pendientes" y botón "Revisar hablantes".
  - **Transcribiendo:** la maqueta muestra una barra de avance y un botón de diagnóstico en vivo. El control/diagnóstico está excluido hasta que se apruebe su manejo de privacidad y gobernanza; la maqueta no autoriza implementarlo.
  - **Con error:** motivo en lenguaje claro, nota de que no se perdió el archivo original y botón "Reintentar procesamiento".

**Paginación:** "Mostrando 1 – 5 de 42 grabaciones registradas", con Anterior, números y Siguiente.

**Reglas de visualización:**
- Una reunión que se procesa avanza sola sin recargar la página.
- Si el título viene vacío, se muestra el nombre del archivo.
- Eliminar siempre pide confirmación.

**Selección múltiple, "Descargar lote", "Exportar CSV" y "Archivar":** no están en la línea base. Quedan fuera del primer corte.

## 4b. Subir grabación (`subir`): carga manual de archivos

Esta pantalla no estaba en el primer mock. Se generó después en Stitch con el sistema Terra. Es una pantalla propia, que se abre con el botón "Subir grabación" de la barra superior y de la biblioteca.

**Cabecera:** migas "Biblioteca de grabaciones / Subir grabación", título "Subir una grabación" y la frase "Sube un video o audio de una reunión. Sauri lo transcribe, identifica a los hablantes y genera el resumen."

**1. Zona para soltar el archivo:**
- Borde punteado, icono de nube, texto "Arrastra aquí tu archivo o elígelo desde tu equipo" y botón **Elegir archivo**.
- Debajo: "Formatos: WebM, MP4, MOV, MKV, WAV, MP3, M4A. Tamaño máximo: 4 GB."
- El límite de 4 GB y la lista de formatos son **propuestas**. Antes de cerrarlos, el equipo los contrasta con lo que el backend acepta de verdad.

**2. Archivo elegido:**
- Tarjeta con el nombre, el tamaño, la **duración detectada** y el tipo (video o audio).
- Botón **Quitar** y botón primario **Subir y procesar**.
- El botón aparece en cuanto hay un archivo válido, incluso antes de terminar de detectar la duración.
- Si el archivo no es válido o no se puede leer, mensaje claro con la razón.

**3. Datos de la reunión (opcionales):**
- **Título:** por defecto el nombre del archivo.
- **Empresa**, **Proyecto**, **Participantes** y **Etiquetas** (chips con X y botón "+ Agregar etiqueta").
- **Plantilla de resumen:** lista desplegable con la predeterminada marcada.
- Se pueden editar ahora o después, en la pantalla de la reunión.

**4. Estados (tarjetas):**
- **Subiendo:** barra de progreso con porcentaje, "MB de MB", velocidad y tiempo restante, aviso de que puede mantener la pestaña abierta, y botón **Cancelar subida**.
- **Línea de pasos:** Subida, Transcripción, Hablantes, Resumen, cada uno Pendiente, En curso, Listo o Con error, con una frase corta del paso actual.
- **Terminado:** "Tu reunión está lista", resumen corto de qué se generó y botón primario **Abrir reunión**. Se abre sola la reunión al terminar.
- **Error:** el mock muestra un mensaje y acciones de reintento y copia de diagnóstico. La copia de diagnóstico, su contenido/códigos y cualquier garantía sobre ellos están excluidos mientras no haya una decisión aprobada de privacidad/gobernanza.

**Fuera de la línea base (no construir):**
- "Procesamiento seguro y privado" como insignia.
- "Transcripción 100% limpia" y otras cifras de calidad.
- La velocidad de carga en MB/s es opcional: solo si el sistema la puede medir de verdad.

**Propuesta no aprobada:** que una carga manual sobreviva al cierre de pestaña o a un corte de red sin perder el archivo y se reintente no está autorizado por la línea base. No tratarlo como requisito ni implementarlo sin aprobación explícita del producto.

## 5. Reunión (`reunion`): video, transcripción y resumen

**Cabecera:**
- ID de la grabación, fecha, duración y plantilla usada.
- Acciones que aparecen en el mock: descargar video, descargar transcripción y eliminar. **Copiar diagnóstico** también aparece en el mock, pero queda expresamente excluido hasta una decisión aprobada de privacidad/gobernanza.
- Título editable en línea, con lápiz.
- Metadatos editables: **Empresa**, **Proyecto**, **Participantes**, **Etiquetas** (con botón "+" para agregar).

**Zona izquierda, de arriba abajo:**

1. **Reproductor.** Controles:
   - pausa y reproducción;
   - retroceder 10 s y adelantar 10 s;
   - volumen;
   - tiempo actual y total;
   - velocidades **0.75x, 1x, 1.25x, 1.5x, 2x**;
   - calidad ("HD 1080p");
   - pantalla completa.
   Debajo, "Hablante actual" mientras se reproduce.

2. **Transcripción interactiva.**
   - Título "Transcripción Interactiva Diarizada" y el número de turnos.
   - Aviso: "Edición de nombre actualiza automáticamente todos los turnos del hablante para este usuario."
   - Filtro por palabra clave.
   - Chips de hablantes. No mostrar métricas o porcentajes de tiempo de habla; talk-time y métricas asociadas son Phase 2 / fuera del alcance inicial.
   - **Cada turno:**
     - nombre del hablante con su color y lápiz para renombrar;
     - botón con la hora (por ejemplo 00:11:05), que lleva el video a ese punto;
     - texto completo del turno.
   - El turno que se reproduce se resalta y muestra "En reproducción".
   - Un hablante sin identificar muestra "Sin identificar – Renombrar".
   - La transcripción sigue al video con desplazamiento automático.

**Panel derecho, con pestañas:**

- **Notas y Resumen** (activa):
  - **Resumen IA** con botones "Copiar resumen" y "Descargar (MD/PDF)", y un botón para regenerar.
  - La estructura, el formato, la regeneración y las acciones del resumen no quedan definidos por esta maqueta; siguen el alcance que se apruebe expresamente. No inferir un formato fijo de tres secciones ni campos obligatorios.
  - **Notas de la reunión:** las capturadas durante la llamada, cada una con hora y minuto; campo "Escribe una nota rápida y presiona Enter…" y botón **Guardar**.
- **Chat con la grabación:** pestaña visible, marcada "Fase 2 – Próximamente". No funciona.

**Ventanas emergentes:**
- **Confirmación de diagnóstico copiado:** aparece solo en el mock y no se autoriza; no implementar controles, copia ni confirmaciones de diagnóstico sin decisión aprobada de privacidad/gobernanza.
- **¿Eliminar grabación?:** "Esta acción eliminará permanentemente el video, la transcripción completa… No se puede deshacer." Botones "Cancelar" y "Sí, eliminar".

**Estados que se deben implementar:**
- Video no carga: mensaje claro; la transcripción sigue disponible.
- Resumen generándose, con error y listo.
- Sin hablantes identificados.

## 6. Revisión de hablantes (`hablantes`)

**Cabecera:** la captura incluye título y explicación; también muestra un botón "Copiar diagnóstico JSON" que es mock-only y queda excluido hasta una decisión aprobada de privacidad/gobernanza.

**Banner "Revisión Obligatoria":** "Esta reunión contiene voces pendientes de asignación" y el contador de pendientes.

**Datos de la reunión:** título, fecha, duración, número de hablantes detectados y enlace "Ver transcripción cruda".

**Una tarjeta por hablante:**
- **Confirmado:** muestra "Validado", sus iniciales y la marca de confirmación.
- **Autodetectado:** nombre propuesto, con aviso de dónde se había visto antes. Tiene un campo con el nombre sugerido y el botón **Confirmar**.
- **Desconocido:** se muestra como `Speaker N`, con su porcentaje de participación. Tiene un campo "Escribe o selecciona quién es…", sugerencias de contactos y "Nuevo contacto", y la nota "Los nombres son privados en tu cuenta de Sauri."
- **En todos:** botón de reproducir una **muestra de audio** (con su rango de tiempo y duración) para que el usuario escuche antes de nombrar.

**Barra de avance:** "2 de 4 hablantes confirmados (50%)".
- Regla visible: requiere el 100% para archivar como lista. Si el usuario sale, queda pendiente.
- Botones: **Guardar borrador y salir** y **Confirmar todos y actualizar transcripción**.

**Fuera de la línea base (no construir):** los paneles "Algoritmo Acústico", "Gobernanza de Datos" y "Retroactividad" son texto de adorno, con cifras inventadas.

## 7. Plantillas de resumen (`plantillas`)

**Navegación lateral:** "Configuración del Sistema" con varias secciones. En la línea base solo existe **Plantillas de Resumen** (ver sección 8).

**Cabecera:** título, descripción y botones "Importar JSON", "+ Nueva plantilla" y "Guardar cambios".

**Pestañas de categoría:** Todas, Comercial y Ventas, Técnica y Arquitectura, Sprints y Operaciones, 1-on-1s. Más "Ordenar por".

**Tarjeta de plantilla:**
- Categoría.
- Nombre.
- Icono.
- Descripción.
- Lista numerada de las secciones que genera la IA.
- Casilla **"Usar por defecto"** (la predeterminada lleva estrella).
- Acciones: **Editar estructura**, duplicar y menú "más".

**Ejemplo de plantillas del mock:**
- Propuesta Comercial Estándar, con 5 secciones.
- Revisión Técnica y Arquitectura Cloud, con 4 secciones.
- Minuta Ejecutiva y Acuerdos Rápidos, con 3 secciones.

**Importar JSON y los bloques de "Directivas de Extracción Personalizadas" y "Reglas globales de LLM" no están en la línea base.** Quedan fuera del primer corte.

## 8. Exclusiones explícitas y elementos no autorizados

Todo contenido de las maquetas que no esté afirmativamente respaldado por el snapshot aprobado de `PRODUCT_BASELINE.md` queda fuera de alcance. Esta lista es ilustrativa, no exhaustiva; conservar algo en las capturas/HTML no lo convierte en requisito. No implementar ni presentar como hecho ninguna capacidad, dato, métrica, promesa, estado, control o texto no confirmado.

| Elemento del mock | Por qué se descarta |
|---|---|
| Proveedor, modelo, Ollama u otra tecnología de generación | La elección del proveedor/método sigue abierta. No prescribir Ollama ni ningún otro proveedor o modelo en interfaz ni en especificación. |
| "99.4% certeza", "Precisión LLM", "Tasa de Fidelidad", "Ahorro Promedio 38 min", "DER 3.8%" | Cifras inventadas. La línea base no define umbrales de precisión. |
| Texto sobre huellas biométricas, "ECAPA-TDNN", "AES-256 Tenant-Isolated", "Zero-Trust", "TLS 1.3" | Afirmaciones técnicas y de seguridad sin respaldo. |
| Login, autenticación, sesión, expiración, recuperación, Google/Microsoft SSO, recordar dispositivo y textos de credenciales | La autenticación y su experiencia siguen abiertas; la maqueta no define ninguna UX. |
| Menú de configuración: General, Diarización, Directivas de IA, Integraciones, Miembros y Permisos, Retención | No usar esta maqueta para afirmar qué pantallas o módulos están aprobados; el alcance lo determina exclusivamente el snapshot aprobado de la línea base. |
| Descargar lote, Exportar CSV, Archivar, selección múltiple | No están en la línea base. |
| Búsqueda full-text; porcentajes de tiempo de habla; compartir/exportar métricas de talk-time; chat interactivo | Búsqueda full-text y talk-time/share son fuera del alcance inicial (Phase 2 donde corresponda); no insinuar que están disponibles. |
| Diagnósticos, telemetría, logs, contenido/campos copiados o garantías de privacidad | Requieren definición de privacidad y gobernanza; no recopilar ni prometer nada desde esta referencia. |
| Diseño fijo del resumen, incluidas exactamente tres secciones o campos/fechas obligatorios | La estructura del resumen sigue abierta; no fijarla con la maqueta. |
| Cantidades o estados de plantillas/reuniones, incluyendo “8 activas”, “12 operativas”, “42 grabaciones” y cualquier conteo | Datos de maqueta fabricados; no son cifras ni objetivos de producto. |
| Controles y acciones de mock no confirmados (incluye contadores, botones, badges, filtros, exportación, edición y estados) | Excluir todos los controles sin respaldo explícito, incluso si no aparecen individualmente en esta tabla. |
| Aprobación de seis pantallas o conformidad/aceptación visual | No existe aprobación de las seis pantallas. La inspiración visual no constituye aceptación de producto ni autorización para construir. |
| Importar JSON de plantillas | No está en la línea base. |
| Botón "Simular error" | Es de la maqueta. |
| Fechas y datos de ejemplo (Grupo Éxito, Bancolombia, etc.) | Son solo ejemplos. |

## 9. Diagnósticos — decisión pendiente

La presencia del botón **"Copiar diagnóstico"** en algunos mocks no es un requerimiento. La recolección, contenido, exposición, retención y controles de diagnóstico requieren decisión de privacidad/gobernanza. Esta referencia no autoriza instrumentación, captura, copia ni garantías de exclusión de datos sensibles. No añadir funciones ni promesas de diagnóstico hasta que se apruebe su alcance y manejo de datos.

## 10. Criterios de uso de estas referencias

Este documento no establece criterios de aceptación visual ni autoriza construir las seis pantallas. No se exige coincidencia con capturas, breakpoints, estados, WCAG targets ni contenido de mock; no se da por aprobada ninguna pantalla. Cualquier futura implementación requiere un alcance aprobado que identifique expresamente pantallas, controles, estados, datos de ejemplo, accesibilidad y aceptación. Toda afirmación o conteo de maqueta debe tratarse como dato ficticio y no mostrarse como dato real.
