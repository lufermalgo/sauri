# Especificación de interfaz de Sauri (extraída de Google Stitch)

- **Fuente:** proyecto Stitch "Sauri Meeting Intelligence Platform" (`projects/10424886024545918390`).
- **Sistema de diseño usado:** "Terra" (`assets/14831859670672193485`).
- **Extraída:** 2026-10-30.
- **Archivos de referencia en esta carpeta:**
  - `login`, `biblioteca`, `subir`, `reunion`, `hablantes` y `plantillas` en versión `.html` (código exacto de Stitch, con clases Tailwind) y `.jpg` (captura).
  - `*.txt`: texto visible de cada pantalla, en orden.
  - `project.json` y `design_systems.json`: tokens completos.

## 0. Cómo usar esta especificación

**Estas pantallas son la referencia visual aprobada por Fer.** Definen estructura, estilo, textos y estados.

**Conflicto con el producto:** el mock inventa datos y funciones que no son producto real. Donde contradice `PRODUCT_BASELINE.md`, **manda la línea base**. Los puntos están en la sección 8. Regla: nada de cifras de adorno, nada de funciones sin respaldo en la línea base.

**Orden de verdad:** `PRODUCT_BASELINE.md` > esta especificación > el HTML de Stitch.

**El HTML de Stitch no se copia tal cual.** Trae Tailwind por CDN y imágenes de ejemplo. Se usa como guía de clases, espaciado y estructura, y se implementa en React con los tokens de la sección 1.

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
- Menú de usuario: nombre ("Fer (Summan)"), rol, **Diagnóstico**, **Cerrar sesión**.

**Pie:** derechos de autor y enlaces Privacidad y Ética, Documentación y Soporte.

## 3. Inicio de sesión (`login`)

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
- Indicador "Diagnóstico de red / Conectando…" (opcional, ver sección 7).

## 4. Biblioteca de grabaciones (`biblioteca`)

**Encabezado:**
- Título "Biblioteca de Grabaciones" y la descripción "Historial centralizado de reuniones procesadas…".
- Botón "Filtros avanzados".
- Botón "Subir grabación manual".

**Tarjetas de resumen:** cuatro, con total, listas, en procesamiento y requieren atención. Son solo una idea visual (ver sección 8).

**Barra de búsqueda y filtros:**
- Búsqueda por título, participante, cliente o palabras clave.
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
  - **Transcribiendo:** barra de avance con porcentaje y botón "Ver diagnóstico en vivo".
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
- **Error:** "No pudimos completar el procesamiento", motivo en lenguaje simple, "No se perdió tu archivo", botones **Reintentar** y **Copiar diagnóstico**. El código técnico va en el diagnóstico copiado y no se impone al usuario.

**Fuera de la línea base (no construir):**
- "Procesamiento seguro y privado" como insignia.
- "Transcripción 100% limpia" y otras cifras de calidad.
- La velocidad de carga en MB/s es opcional: solo si el sistema la puede medir de verdad.

**Requisito funcional que el mock no muestra:** la subida debe sobrevivir a un cierre de pestaña o a un corte de red sin perder el archivo, y debe reintentarse.

## 5. Reunión (`reunion`): video, transcripción y resumen

**Cabecera:**
- ID de la grabación, fecha, duración y plantilla usada.
- Acciones: **Copiar diagnóstico**, **Descargar video**, **Descargar transcripción**, **Eliminar**.
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
   - Chips de hablantes con su porcentaje de habla.
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
  - Estructura del resumen:
    1. Objetivo y contexto central.
    2. Acuerdos y puntos clave de decisión.
    3. Próximos pasos y responsables, cada uno con responsable y fecha.
  - **Notas de la reunión:** las capturadas durante la llamada, cada una con hora y minuto; campo "Escribe una nota rápida y presiona Enter…" y botón **Guardar**.
- **Chat con la grabación:** pestaña visible, marcada "Fase 2 – Próximamente". No funciona.

**Ventanas emergentes:**
- **Diagnóstico copiado:** confirma que el diagnóstico se copió al portapapeles. Botón "Entendido".
- **¿Eliminar grabación?:** "Esta acción eliminará permanentemente el video, la transcripción completa… No se puede deshacer." Botones "Cancelar" y "Sí, eliminar".

**Estados que se deben implementar:**
- Video no carga: mensaje claro; la transcripción sigue disponible.
- Resumen generándose, con error y listo.
- Sin hablantes identificados.

## 6. Revisión de hablantes (`hablantes`)

**Cabecera:** título "Revisión y Asignación de Hablantes", explicación, y botón "Copiar diagnóstico JSON".

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

## 8. Qué NO construir (contradice la línea base o la decisión del proyecto)

| Elemento del mock | Por qué se descarta |
|---|---|
| "Generado con Whisper Large v3 + Claude 3.5 Sonnet", "Sauri-Instruct v3" | El proveedor de resumen decidido por Fer es **Ollama local**. No se nombra ningún modelo en pantalla. |
| "99.4% certeza", "Precisión LLM", "Tasa de Fidelidad", "Ahorro Promedio 38 min", "DER 3.8%" | Cifras inventadas. La línea base no define umbrales de precisión. |
| Texto sobre huellas biométricas, "ECAPA-TDNN", "AES-256 Tenant-Isolated", "Zero-Trust", "TLS 1.3" | Afirmaciones técnicas y de seguridad sin respaldo. |
| Acceso con Google Workspace y Microsoft SSO, "Recordar dispositivo" | La autenticación de varios usuarios es una decisión abierta. |
| Menú de configuración: General, Diarización, Directivas de IA, Integraciones, Miembros y Permisos, Retención | No están en la línea base. Solo se implementa **Plantillas de resumen**. |
| Descargar lote, Exportar CSV, Archivar, selección múltiple | No están en la línea base. |
| "Minuta enviada por correo", estado "En vivo" | No están en la línea base. |
| Importar JSON de plantillas | No está en la línea base. |
| Botón "Simular error" | Es de la maqueta. |
| Fechas y datos de ejemplo (Grupo Éxito, Bancolombia, etc.) | Son solo ejemplos. |

## 9. Observabilidad pedida por Fer

El mock ya incluye un botón **"Copiar diagnóstico"** en la reunión y en la revisión de hablantes. Se implementa en todas las pantallas con carga: subida, biblioteca y reunión.

**Contenido del diagnóstico:**
- ID de sesión y de la reunión.
- Estado de cada paso del procesamiento.
- Errores recientes de la interfaz.
- Hora y versión de la aplicación.

**No incluye** ninguna contraseña, token ni contenido de la transcripción.

## 10. Criterios de aceptación visual

1. Cada pantalla coincide con su captura `.jpg` en estructura, jerarquía, colores y tipografía.
2. Todos los botones y textos del mock que no están en la sección 8 están presentes y legibles.
3. Contraste mínimo WCAG AA en todo texto.
4. Funciona en escritorio de 1280 px o más.
5. Estados vacío, cargando y error implementados en las seis pantallas.
6. Ninguna cifra ni afirmación de la sección 8 aparece en pantalla.
