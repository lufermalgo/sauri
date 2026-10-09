# Descubrimiento de producto — Sauri

> **Nota de distribución:** Las imágenes originales de referencia se conservan fuera del repositorio. Los descriptores textuales de §3 son la única referencia visual versionada; los nombres indicados identifican recursos locales no incluidos.


> **Estado y autoridad.** Documento persistente del descubrimiento funcional del Usuario funcional. Registra fielmente su intención y las referencias aportadas; **no es un `PRODUCT_BASELINE.md` aprobado**, no constituye aprobación de alcance ni define arquitectura, tecnología o criterios de aceptación de producto. Úsese como fuente de verdad del descubrimiento al preparar el documento final para los siguientes agentes. Si algo no está expresado aquí, no debe completarse por inferencia.

## 1. Alcance del descubrimiento

- **Expresado por el Usuario funcional:** el descubrimiento funcional de Sauri parte desde cero y se formula desde la experiencia del Usuario funcional. Sauri debe concebirse como una herramienta/plataforma interna de Summan, con potencial futuro de escalar a muchos usuarios. La forma concreta de ese escalamiento queda pendiente de revisión; no se han definido disponibilidad de identidades entre usuarios ni permisos (§7, 2026-10-09).
- **Contexto declarado por el Usuario funcional:** la plataforma está autorizada y, antes de grabar, se pide permiso a los asistentes. Esta es la afirmación del Usuario funcional, no una verificación independiente ni una especificación de controles de consentimiento.

## 2. Expectativas y decisiones comunicadas por el Usuario funcional

### 2.1 Captura y llegada al portal

- **Flujo de captura bajo demanda (descubrimiento, no requisito aprobado):** el usuario hace clic en la extensión, elige la opción «grabar sesión», selecciona la pestaña de Google Meet en una ventana de Chrome que muestra todas las pestañas del navegador y, después de una cuenta regresiva cuya duración está definida en las preferencias del usuario, comienza la grabación. El Usuario funcional expresa como expectativa que «se garantiza audio y video» (§7, 2026-10-09). No se especifican aquí otros pasos ni detalles de esa expectativa.
- **Ventana al elegir una nueva nota o grabación (inspiración, no requisito aprobado):** el Usuario funcional quiere conversar sobre la ventana que aparece al pulsar ese botón y comparte como referencia otra app, donde se puede elegir una pestaña del navegador para grabar (§7, 2026-10-09). La imagen parece mostrar el selector de compartir de Chrome; no identifica el framework de la otra app ni decide qué debe ofrecer Sauri.
- **Selector de fuente (inspiración visual, no requisito aprobado):** la referencia `chrome-tab-share-selector.jpg` (referencia local no incluida en GitHub) muestra un diálogo para elegir entre “Chrome Tab”, “Window” y “Entire Screen”; en la pestaña de Chrome lista pestañas a la izquierda, un área de vista previa a la derecha y una opción “Share with tab audio”, además de “Cancel” y una acción de compartir deshabilitada mientras no se selecciona una fuente. Esta referencia no confirma tecnología, framework ni el comportamiento que el Usuario funcional quiere para Sauri. (§7, 2026-10-09)
- **Expectativa confirmada al cerrar el selector sin seleccionar:** el Usuario funcional indicó que basta con volver a hacer clic en el botón de grabación o de tomar nota de la extensión; no requiere otra acción para cerrar el selector (§7, 2026-10-09). Esto no aclara todavía qué ocurre después de ese nuevo clic.
- **Expectativa confirmada sobre la Barra de Control durante la grabación:** el Usuario funcional respondió «Todas» a la pregunta de si debe permitir detener o pausar la grabación, añadir notas, o ambas cosas. La expectativa es que permita tanto pausar/detener como añadir notas durante la grabación. Esto registra lo esperado; no aprueba alcance ni define detalles adicionales de interacción.
- **Precisión posterior sobre cancelar, pausar y detener (descubrimiento, no alcance aprobado):** cancelar simplemente deja de grabar y no desencadena ninguna otra acción; pausar detiene temporalmente la captura y permite reanudar; detener finaliza la grabación y entonces esta se almacena en Sauri y se transcribe (§7, 2026-10-09). Esta aclaración posterior resuelve el comportamiento de esos controles, sin aprobar su implementación ni otro alcance.
- Desde una extensión de Google Meet, el usuario puede iniciar y detener la grabación.
- **Decisión/expectativa confirmada:** desde las preferencias de la extensión, el Usuario funcional puede definir si quiere que se muestre o no un indicador de grabación. Formulación literal disponible en esta intervención: «Yo desde las preferencias de la extension puedo definir si quiero que se muestre un indicador de grabacion o si no.» Esto confirma la opción de visibilidad, pero no el diseño, ubicación, estados ni equivalencia con otros controles de las referencias.
- Al terminar la reunión y cerrar la pestaña, se abre el portal Sauri con la grabación y la transcripción.

### 2.2 Biblioteca de grabaciones

- El portal ofrece un historial/listado de grabaciones y permite seleccionar una sesión.
- Para una sesión, el usuario puede renombrarla, eliminarla y descargar el video y la transcripción.
- El listado se puede filtrar por fechas y ordenar por fecha, con las más recientes primero.
- Se pueden editar los metadatos de compañía, proyecto y participantes.
- **Aclaración de alcance y objetivo futuro:** el agente de IA del CRM queda fuera del alcance de Sauri. Sí importa considerar que la transcripción debe poder llevarse al CRM; cómo hacerlo —incluidos integración, campos, mecanismos u otros detalles— se discutirá en el futuro (§7, 2026-10-09). Esto no acuerda una integración ni sus especificaciones.
- Hay tags predefinidos —por ejemplo, **GenAI**, **Digital Twin** y **Automatización**— y el usuario también puede crear tags.

### 2.3 Vista de una reunión

- La vista incluye un reproductor con controles habituales: avance, velocidad, resolución/calidad, pausar/detener, volumen y mute.
- Debajo del reproductor aparece la transcripción, sincronizada con la reproducción y con el fragmento actual resaltado.
- A la derecha hay un panel con el resumen, que se puede copiar o descargar.
- **Referencia de interfaz futura (inspiración, no requisito aprobado):** el Usuario funcional describe un panel izquierdo con las grabaciones, un panel central dividido entre video y resumen (`summary`), y un panel derecho con la transcripción (§7, 2026-10-09). La captura enlazada en §3 muestra visualmente otra distribución —video y transcripciones en el centro, y un panel de “Infografía” a la derecha—; se conserva como referencia visual, no como definición de alcance.

### 2.4 Resúmenes y plantillas

- El resumen debe identificar el tema principal, presentar argumentos o puntos clave y organizarlos de forma clara y estructurada.
- La intención expresada es que el usuario pueda definir, crear y editar su plantilla desde Perfil/Biblioteca, y elegir una plantilla predeterminada para los resúmenes.
- La biblioteca de plantillas tiene categorías y puede contener varias plantillas por categoría.
- Como propuesta inicial se mencionó **General > “Resumen básico”**.
- La imagen de la biblioteca inspira categorías, favoritos/predeterminadas y los ejemplos **“Reunión General”**, **“Planificación de Sprint”** y **“Lluvia de ideas”**. Los nombres de ejemplo y los controles que aparecen en la imagen no son requisitos confirmados por el Usuario funcional.

### 2.5 Transcripción e identificación de hablantes

El documento preexistente conserva la frase: **“una transcripción correcta es importante, pero también los hablantes”.** La fuente literal y la fecha de ese mensaje no están disponibles en este contexto (§7); no se presenta como transcripción verificada. El resumen existente interpreta ambos aspectos como centrales.

- Al terminar la grabación, Sauri guarda el video e inicia la transcripción y la identificación automática de hablantes mediante algún modelo/ML. La tecnología no está elegida.
- Cuando termina ese proceso, la primera vez se presenta un modal para revisar los nombres. Ejemplo del Usuario funcional: si hay cinco personas, el sistema detecta dos a partir de identificaciones anteriores y muestra sus nombres; las otras tres, aún no identificadas, aparecen como **Speaker 1**, **Speaker 2** y **Speaker 3**.
- En el modal, el usuario puede reproducir un fragmento claro de audio de cada hablante y reemplazar **Speaker N** por el nombre real o etiqueta que elija. También puede corregir nombres identificados automáticamente.
- Después de revisar, la transcripción se muestra con los nombres correctos, como en la referencia visual.
- Si el usuario cierra el modal, se va o no termina la revisión, al volver a esa grabación en el portal el sistema detecta que la revisión sigue pendiente y vuelve a pedirla abriendo el modal. La revisión queda pendiente hasta completarse; no se plantea como una acción que pueda omitirse definitivamente.
- El Usuario funcional confirmó que, si Sauri ya reconoce a un hablante con un nombre definido antes, debe mostrar ese nombre en lugar de **Speaker N**. El Usuario funcional espera que las identificaciones ya definidas se reutilicen en el futuro.
- **Decisión confirmada:** si se corrige una identificación automática equivocada, esa corrección debe aplicarse al reconocimiento futuro de ese hablante en toda la plataforma Sauri, no solo a esa grabación (§7, 2026-10-09). Esta decisión define el resultado y su alcance de producto; no especifica implementación técnica, permisos, visibilidad entre usuarios ni política de datos.
- El Usuario funcional define como necesidad actual que la identificación del hablante quede disponible para que el Usuario funcional la use. Debe concebirse dentro de la plataforma interna de Summan y considerar el potencial futuro de escalar a muchos usuarios; el modelo concreto de escalamiento sigue abierto (§7, 2026-10-09).
- **Descubrimiento, no requisito aprobado:** tras revisar los hablantes, el Usuario funcional no espera otra acción inmediata; espera encontrar luego esa grabación en la plataforma web de Sauri para buscarla, volver a ver el video, leer la transcripción o descargar el video o la transcripción (§7, 2026-10-09).

## 3. Inspiración visual — no requisitos por sí sola

Las capturas originales se conservan localmente y no se incluyen en el repositorio. Esta sección conserva solo descripciones textuales de referencias de UI; sus controles, textos, estados y comportamientos no se consideran decisiones salvo donde el texto del Usuario funcional los confirma explícitamente en la sección 2.

| Archivo local | Qué muestra / aporta como inspiración |
| --- | --- |
| `template-library.jpg` (referencia local no incluida en GitHub) | Pantalla titulada “Template Library”: panel lateral de categorías y favoritos, una plantilla abierta con contenido de ejemplo, iconos de favorito/personalización y acciones para crear o usar una plantilla. Es referencia visual; los rótulos y controles no confirmados no son requisitos. |
| `preferences.jpg` (referencia local no incluida en GitHub) | Pantalla “Preferences” con selectores de idioma, opción de traducción automática, selección de plantilla de resumen, controles de eliminación de transcripciones/audio, notificación y tema; también muestra navegación de ajustes. Todo es inspiración visual, no preferencias confirmadas por el Usuario funcional. |
| `meeting-transcript-player.jpg` (referencia local no incluida en GitHub) | Vista de una sesión con metadatos, acción para añadir tag, filas de transcripción con marcas de tiempo y hablantes, y controles de reproducción/comentario. La captura contiene texto y nombres de una reunión; no se transcriben aquí. Los elementos no confirmados siguen siendo inspiración, no requisitos. |
| `processing-progress.jpg` (referencia local no incluida en GitHub) | Pantalla de procesamiento con porcentaje, barra de progreso, lista de etapas textuales y botón “Refresh”. Las etapas y el porcentaje son contenido de la imagen, no una afirmación sobre algoritmo, arquitectura o etapas técnicas obligatorias. |
| `speaker-review.jpg` (referencia local no incluida en GitHub) | Modal “User Profiles” con tres filas de hablantes/perfiles, acciones de reproducción y edición, botón “Save” y cierre. Es referencia visual para la revisión descrita en §2.5; no confirma el número de hablantes ni otros detalles del ejemplo de la captura. |
| `web-interface-future-layout.jpg` (referencia local no incluida en GitHub) | Captura de una interfaz con lista de archivos/grabaciones a la izquierda, video y transcripciones en el panel central, y una pestaña/panel “Infografía” a la derecha. Se conserva como inspiración visual; la distribución que el Usuario funcional imagina para Sauri está formulada en §2.3 y §7, y ni esta captura ni sus controles, textos o datos visibles aprueban requisitos o alcance. |
| `extension-microphone-input-menu.jpg` (referencia local no incluida en GitHub) | Barra superior con selector/toggle de “Pantalla + aud…” y un menú desplegado desde el control con icono de micrófono. El menú ofrece opciones de entrada como “MacBook Air Microphone (Built-in)”, una entrada identificada como micrófono de iPhone y “Default – MacBook Air Microphone (…)”. La captura permite concluir que se muestran opciones de dispositivo de micrófono; no muestra cómo se seleccionan, persisten ni afectan una grabación. |
| `extension-capture-mode-menu.jpg` (referencia local no incluida en GitHub) | Barra superior similar y menú con “Grabar pantalla de la pestaña + audio” y “Grabar solo audio de la pestaña”. Son modos/opciones visibles de captura; no se muestra el resultado de elegirlos ni qué significa “audio” en cada caso más allá del texto. |
| `extension-recording-preferences-menu.jpg` (referencia local no incluida en GitHub) | Menú de preferencias con “Cuenta regresiva” configurada visualmente en “3s”, “Resolución” en “720p” y “Barra de Control” con un interruptor que aparece apagado. La captura muestra etiquetas, valores/estado y jerarquía del menú, pero no confirma qué cambia cada opción ni que “Barra de Control” sea el indicador de grabación mencionado por el Usuario funcional. |
| `extension-rec-notes-screen.jpg` (referencia local no incluida en GitHub) | Pantalla titulada “REC Notas”, con la misma barra superior de captura y un botón principal “+ Nueva nota REC”. Se aprecia una acción para crear una nota REC; no se muestra el flujo posterior, su relación con la grabación ni el contenido de una nota. |
| `chrome-tab-share-selector.jpg` (referencia local no incluida en GitHub) | Ventana titulada “Choose what to share with Sider: Chat with all AI: GPT-5, Claude, DeepSeek, Gemini, Grok” y texto “The site will be able to see the contents of your screen”. Está activa la pestaña “Chrome Tab”; también aparecen “Window” y “Entire Screen”, una lista de pestañas abiertas a la izquierda y un panel de vista previa a la derecha con “Select a tab to share”. Abajo se ve “Share with tab audio” activado y los botones “Cancel” y “Share with Audio” (este último deshabilitado). Inspira la selección de una pestaña/fuente y el control de audio; visualmente parece el selector de compartir de Chrome, pero no demuestra qué tecnología usa Sider ni establece requisitos para Sauri. |

## 4. Inferencias o propuestas no aprobadas

Esta sección delimita lo que **no** debe elevarse a decisión del Usuario funcional:

- Existe potencial futuro de escalar la herramienta interna a muchos usuarios en Summan, pero la forma concreta de hacerlo no está decidida. No se infiere disponibilidad o alcance de identidades entre usuarios ni permisos.
- La tecnología/modelo para transcripción e identificación de hablantes no se eligió. La referencia visual de procesamiento no determina algoritmo, proveedor, arquitectura ni secuencia técnica.
- Los controles o ajustes visibles en las imágenes —incluidos idioma, traducción, retención, notificaciones, tema, selección de micrófono, modo de captura, cuenta regresiva, resolución, barra de control y notas REC— son inspiración visual, no capacidades confirmadas por sí mismos. La expectativa de que la Barra de Control permita pausar/detener y añadir notas durante la grabación está confirmada por separado en §2.1 y §7; la preferencia opcional de visibilidad de un indicador de grabación también está confirmada en §2.1, pero no se ha confirmado si ese indicador es la misma Barra de Control.
- Los ejemplos adicionales de plantillas o controles de favoritos, personalización y selección que solo aparecen en la imagen no son requisitos confirmados. La categoría **General**, el ejemplo inicial **“Resumen básico”**, la capacidad de gestionar plantillas y elegir una predeterminada sí reflejan la intención expresada por el Usuario funcional.
- No se infieren políticas de compartición de plantillas, permisos, retención de grabaciones/transcripciones, exportación adicional, idioma, ni analítica más allá de lo indicado en §2.
- El agente de IA del CRM está fuera del alcance de Sauri. La transcripción debe poder llevarse al CRM, pero el cómo —integración, campos, mecanismos u otros detalles— queda para discusión futura; no es una integración acordada ni un requisito especificado (§7, 2026-10-09). Los detalles mencionados antes sobre oportunidad, metadatos, URL del video y campos relacionales no deben tratarse como decisiones vigentes de implementación.

## 5. Preguntas realmente abiertas

Estas preguntas no tienen respuesta en el contexto disponible. No preguntar si la revisión de hablantes puede omitirse o posponerse: el Usuario funcional ya definió que queda pendiente y se vuelve a solicitar hasta completarse.

1. En la referencia de preferencias aparece un interruptor “Barra de Control” apagado. ¿La Barra de Control que permite pausar/detener y añadir notas es también el indicador de grabación cuya visibilidad se configura en preferencias, o son elementos distintos? La preferencia de visibilidad y las funciones de la barra ya están confirmadas por separado; su relación sigue abierta.
2. ¿Cómo se revisará la forma de escalar la plataforma interna a muchos usuarios en Summan, incluida la disponibilidad/alcance de identidades de hablantes entre usuarios y los permisos? No está decidido ahora.
3. ¿Qué tecnología/modelo se seleccionará para transcripción e identificación automática de hablantes? El Usuario funcional no eligió una.
4. En la gestión de plantillas, ¿las plantillas y la selección predeterminada son personales o compartidas, y cómo se elige la predeterminada cuando hay varias categorías? El Usuario funcional no precisó estas reglas.
5. Para reutilizar identificaciones futuras, ¿cómo se determina que una voz corresponde a una identidad ya definida y cómo se resuelven coincidencias dudosas? El Usuario funcional confirmó el resultado esperado, no el mecanismo ni las reglas de ambigüedad.
6. Para llevar la transcripción al CRM, ¿qué forma tendría y qué campos, mecanismos u otros detalles serían necesarios? El Usuario funcional indicó que se discutirá en el futuro; no hay una integración acordada ni especificada.
7. Al buscar después una grabación en la plataforma web, ¿qué información o filtros necesitaría el Usuario funcional para encontrarla?
8. Al iniciar «nueva nota o grabación», ¿qué quiere el Usuario funcional que Sauri ofrezca al elegir dónde grabar? La referencia de otra app muestra una ventana de selección con Chrome Tab, Window y Entire Screen, además de una opción de audio de pestaña. Sigue abierto si Sauri debe limitarse a elegir la pestaña y ajustar el modo/fuente antes o después, o si el Usuario funcional quiere que esa misma ventana permita elegir también fuente o modo de captura. La referencia no decide la respuesta.
9. Si el Usuario funcional cierra el selector sin elegir y vuelve a pulsar «grabar» o «tomar nota» en la extensión, ¿espera que el selector se abra de nuevo para elegir una pestaña, o que el flujo continúe de otra manera? La respuesta actual confirma qué acción tomar tras cerrar, no el resultado del clic siguiente.

## 6. Límite de uso para los siguientes agentes

Este registro preserva el descubrimiento; no autoriza implementar funcionalidades ni sustituye las decisiones pendientes. Los siguientes agentes deben separar este contexto de cualquier baseline aprobada, mantener las referencias visuales como inspiración y llevar las preguntas abiertas al proceso de decisión correspondiente sin rellenarlas por su cuenta.

## 7. Registro cronológico de formulaciones originales disponibles

### 2026-10-09 — Persistencia y fidelidad del descubrimiento

- **Resumen editorial heredado (no literal; expectativa de proceso, no requisito de producto):** el Usuario funcional indicó que no quiere que se sinteticen sus ideas porque eso puede cambiar el producto; quiere que Cyrus mantenga dentro del proyecto un registro persistente de lo hablado/definido y use esa fuente para el documento final que usarán los siguientes agentes.
- **Decisión/expectativa confirmada:** preservar las formulaciones originales del Usuario funcional cuando estén disponibles; la interpretación actual permanece como índice y no reemplaza el original. Cyrus debe mantener el registro dentro del proyecto y usarlo como fuente del documento final para los siguientes agentes.
- **Contexto declarado de esta intervención:** la corrección solicitada no aprueba un `PRODUCT_BASELINE.md`, no pide implementar producto y limita los cambios al descubrimiento.
- **Ejemplos:** no se añadió ningún ejemplo funcional en esta intervención.
- **Preguntas abiertas:** no se resolvieron preguntas funcionales del descubrimiento.
- **Límite de recuperación:** en este contexto no están disponibles los mensajes originales anteriores de la conversación de descubrimiento ni sus fechas. El contenido previo de §§1–6 es un resumen ya creado; no se puede certificar como transcripción literal. La única cita literal anterior que el documento conserva es “una transcripción correcta es importante, pero también los hablantes”; su mensaje fuente y fecha no están disponibles aquí. No se reconstruyen ni se atribuyen otras citas. Las cinco imágenes locales se pudieron inspeccionar, pero no hay un manifiesto u originales externos que permita verificar su procedencia histórica; se confirma únicamente que estos cinco archivos presentes corresponden visualmente a las referencias inventariadas.

### Formulaciones fuente visibles en el contexto actual (sin fecha histórica atribuida)

Las siguientes citas sí aparecen literalmente en la instrucción del Usuario funcional visible en este contexto. Se conservan con su ortografía y errores originales; las etiquetas y notas entre corchetes son editoriales, no parte de las citas.

- **Formulación literal — expectativa de identificación de hablantes y uso de referencia visual:** “Si, si Sauri ya logra identificar un hablante con un nombre que ya habiamos definido, enotnces en vez de mostarlo con la etiqueta generica Speaker N, debe aparecer el nombre del usario. Yo te mostre una imagen de referencia. Cuando te pase imagnes de referencia deberias de tomar nota de lo que se muestra para en el futuro tratar de imitar las UI.”
- **Formulación literal — expectativa de fidelidad y persistencia del descubrimiento:** “No quiero disculpas, quiero que corrijas, no quiero que sintetices mis ideas, porque luego definimos el poducto como no es. Quiero que dentro del proyecto quede en persistenca de lo que hablamos y lo que se esta definiendo, esto Cyrus lo debe garantizar. Cyrus usara esa informacion persistida para crear el documento final de prudcot que usara el resto de los agentes o por lo menos el siguiente agente en el proceso.”

**Resumen recuperado/no literal — flujo de revisión de hablantes:** la instrucción actual identifica una formulación extensa del Usuario funcional sobre una sesión de cinco personas: detección de dos hablantes conocidos, presentación de los otros como `Speaker 1/2/3`, reproducción de fragmentos de audio, renombrado, transcripción con los nombres correctos y reaparición del modal si la revisión quedó incompleta. El texto fuente exacto de esa formulación no está visible aquí, por lo que esto no se presenta como cita ni se reconstruye.

**Resumen recuperado/no literal — otras áreas:** §§2.1–2.4 y §5 ya contienen resúmenes sobre captura desde Meet, llegada al portal, plantillas, resumen y transcripción; §1 contiene el contexto declarado sobre autorización y solicitud de permiso antes de grabar. La instrucción actual menciona esos temas, pero no muestra sus formulaciones fuente literales. Se conservan como resumen, sin convertirlos en citas.

**Referencias visuales:** los originales de las cinco capturas listadas en §3 se mantienen localmente y no se incluyen en este documento versionado. Las descripciones textuales de §3 son la referencia persistente; inspiran UI, pero no sustituyen formulaciones ni confirman por sí solas requisitos.

### 2026-10-09 — Plataforma interna e identificación de hablantes

- **Formulación literal — identificación/reutilización de hablantes y contexto de plataforma interna:** “Estaran para Sauri como plataforma, luego revisamos esa forma de escalar a otros usuarios.

Es decir, la plataforma debe cumplir con la identificacion del hablante y dejarlo listo para que yo lo pueda usar, pero pensado que en el futuro sera escalado a muchos usuarios en Summan.

Eso lo debemos pensar como una plataforma que sera usada como una herramienta interna.”
- **Decisión confirmada (nota editorial):** Sauri se piensa como herramienta/plataforma interna; la plataforma debe identificar al hablante y dejar el resultado listo para el uso inicial del Usuario funcional; se piensa para poder escalar a muchos usuarios de Summan.
- **Aspecto abierto (nota editorial):** la forma concreta de compartir o reutilizar identidades entre usuarios queda para revisión posterior. La posibilidad de escalar no define permisos, compartición ni arquitectura.

### 2026-10-09 — Alcance de corregir una identificación automática

- **Pregunta de Cyrus (formulación literal):** «Si corriges una identificación automática equivocada, ¿quieres que Sauri aplique esa corrección al reconocimiento futuro de ese hablante en toda la plataforma, o solo a esa grabación?»
- **Respuesta del Usuario funcional (formulación literal):** «Si».
- **Decisión confirmada (nota editorial):** la corrección de identificación debe aplicarse al reconocimiento futuro del hablante en toda la plataforma Sauri, no solo a esa grabación.
- **Límite de la decisión:** define el resultado y alcance de producto; no especifica implementación técnica, permisos, visibilidad entre usuarios ni política de datos.

### 2026-10-09 — Referencia visual para la interfaz web futura

- **Formulación literal — disposición imaginada:** “Así veo en el futuro la interfaz web de Sauri, un panel izquierdo con las grabaciones, panel central dividido en dos con el video y el summary, un panel derecho con la transcripción”.
- **Clasificación:** referencia/inspiración de una posible interfaz futura, no requisito aprobado ni compromiso de implementación.
- **Resumen fiel:** el Usuario funcional imagina la lista de grabaciones a la izquierda, el video y el resumen en dos partes del panel central, y la transcripción en un panel derecho.
- **Evidencia visual:** `web-interface-future-layout.jpg` (referencia local no incluida en GitHub), copiada sin modificar desde la imagen adjunta. La captura muestra una composición visual de lista a la izquierda, video y transcripciones al centro y panel “Infografía” a la derecha; no se atribuyen sus datos, rótulos o controles a Sauri.

### 2026-10-09 — Posible valor futuro de la metadata para el CRM

- **Formulación literal — posibilidad expresada por el Usuario funcional:** «yo creo que esa metadata nos puede ayudar en el futuro en la vinculacion de la transcripion de una sesion con una oportunidad en le CRM»
- **Pregunta literal del Usuario funcional:** «ya tienes claro eso?».
- **Clasificación:** posibilidad/valor futuro de la metadata del video o de la sesión para facilitar potencialmente la vinculación de la transcripción de una sesión con una oportunidad del CRM; no es una decisión de alcance inicial ni un requisito aprobado. No define campos ni integración.
- **Aporte adicional comunicado por el Usuario funcional (la formulación literal no está disponible en este contexto):** el equipo comercial necesitaría más información sobre una oportunidad de cliente. A futuro, se integraría el CRM con agentes de IA generativa y una buena transcripción daría contexto al agente. Para asociar una transcripción con una oportunidad hacen falta campos relacionales; el Usuario funcional imagina poder editar metadatos de la grabación, por ejemplo el ID y el nombre de la oportunidad, pero aún no define los campos. Mientras falten campos asociados al CRM, no se vincularían al CRM la URL del video ni el almacenamiento de la transcripción; cuando los campos estén completos, sí se vincularían.
- **Clasificación y límites:** intención/propuesta futura, no decisión aprobada ni alcance inicial. Los campos concretos y el comportamiento/UX de edición siguen por explorar; no se deriva una especificación de integración.

### 2026-10-09 — Aclaración sobre el CRM

- **Formulación literal del Usuario funcional:** “Como te informo, el agente de AI del CRM no es parte de este proyecto. Solo entender que la transcripion es importante llevarla al CRM. El como se discutira en el futuro.”
- **Aclaración de alcance confirmada:** el agente de IA del CRM queda fuera del alcance de Sauri.
- **Objetivo expresado, no decisión de implementación:** importa considerar que la transcripción debe poder llevarse al CRM. El cómo —integración, campos, mecanismos u otros detalles— se discutirá en el futuro.
- **Límite:** esto no constituye una integración acordada ni un requisito técnico o especificación. Esta aclaración prevalece sobre las posibilidades de agente y los detalles de vinculación/metadatos mencionados en el registro CRM anterior; esos detalles siguen sin decidirse.

### 2026-10-09 — Uso posterior a la revisión de hablantes

- **Formulación literal del Usuario funcional:** «nada, estaran en la plataforam web de Sauri para buscarla despues, ver el video de nuevo, leer la transcripion, descargar el video o la transcripcion.»
- **Clasificación:** descubrimiento sobre el uso posterior a la revisión de hablantes, no requisito aprobado. El Usuario funcional no espera otra acción inmediata tras revisar; espera que la grabación esté luego en la plataforma web de Sauri para buscarla, volver a ver el video, leer la transcripción o descargar el video o la transcripción.
- **Pregunta abierta:** qué información o filtros necesitaría para encontrar una grabación después; aún no se respondió.

### 2026-10-09 — Flujo de grabación bajo demanda

- **Formulación literal del Usuario funcional:** «sera por demanda, el usuario puede dar click en la extension, saldra un menu done hay una opcion de grabar sesion, al hacer click con eso lo que pasa es que se muestra una ventana con todas las pestañas del navegador para que yo pueda seleccionarla, ahí selecciono la de meet, sale una cuenta regresiba definia por las preferencia del usuario y comienza a grabar. Se garantiza audio y video.»
- **Clasificación:** descubrimiento del flujo de captura bajo demanda, no requisito aprobado.
- **Expectativa declarada por el Usuario funcional:** “Se garantiza audio y video.” Se registra como expectativa declarada, no como garantía verificada ni criterio aprobado.
- **Resumen fiel:** el usuario inicia desde la extensión, elige grabar sesión, selecciona una pestaña del navegador (el Usuario funcional indica que selecciona la de Meet), espera una cuenta regresiva definida por sus preferencias y comienza la grabación.
- **Límite:** no se infieren más detalles del menú, selección de pestaña, preferencias, cuenta regresiva ni garantía.

### 2026-10-09 — Precisión del flujo de grabación bajo demanda

- **Formulación literal del Usuario funcional aportada en esta instrucción:** “el usuario hace clic en la extensión; aparece un menú con la opción «grabar sesión»; al elegirla, se muestra una ventana de Chrome con todas las pestañas del navegador para que seleccione la pestaña de Google Meet; luego aparece una cuenta regresiva, cuya duración está definida en las preferencias del usuario, y al terminar comienza la grabación.”
- **Expectativa literal del Usuario funcional:** «se garantiza audio y video».
- **Clasificación:** descubrimiento del flujo de captura bajo demanda y expectativa expresada; no es requisito aprobado ni autorización de implementación.
- **Límite:** “se garantiza audio y video” registra la expectativa del Usuario funcional, no una afirmación técnica verificada sobre el sistema actual. No se infieren otros detalles de la ventana, selección, preferencias, cuenta regresiva o garantía.

### 2026-10-09 — Referencias de controles de la extensión y visibilidad del indicador

- **Formulación literal del Usuario funcional:** «Yo desde las preferencias de la extension puedo definir si quiero que se muestre un indicador de grabacion o si no.»
- **Clasificación:** decisión/expectativa confirmada sobre la preferencia de visibilidad del indicador de grabación. Confirma que la persona usuaria puede optar por mostrarlo u ocultarlo desde las preferencias de la extensión; no define aún su aspecto, ubicación, momento/estados de aparición ni controles relacionados.
- **Referencias visuales aportadas en esta intervención (inspiración, no requisitos automáticos):**
  - `extension-microphone-input-menu.jpg` (referencia local no incluida en GitHub) muestra el selector de micrófono y una lista de fuentes, incluyendo una entrada de micrófono integrada, una entrada de iPhone y una opción predeterminada. No prueba persistencia de la elección ni comportamiento al grabar.
  - `extension-capture-mode-menu.jpg` (referencia local no incluida en GitHub) muestra “Grabar pantalla de la pestaña + audio” y “Grabar solo audio de la pestaña”. No prueba el resultado de seleccionar uno de los modos.
  - `extension-recording-preferences-menu.jpg` (referencia local no incluida en GitHub) muestra cuenta regresiva “3s”, resolución “720p” y “Barra de Control” apagada en el menú de preferencias. No se puede concluir que esa barra sea el indicador de grabación confirmado por el Usuario funcional.
  - `extension-rec-notes-screen.jpg` (referencia local no incluida en GitHub) muestra el encabezado “REC Notas” y la acción “+ Nueva nota REC”; no deja ver el resultado de crear una nota ni su relación con la grabación.
- **Límite de interpretación:** aunque la preferencia del indicador queda confirmada por el texto, las referencias solo muestran visualmente una opción “Barra de Control”; no establecen que sea el mismo control. También quedan sin confirmar la mecánica, efecto y persistencia de las otras opciones visuales.
- **Pregunta abierta:** ¿“Barra de Control” es el indicador de grabación que se puede mostrar/ocultar, o es una función distinta?

### 2026-10-09 — Funciones esperadas de la Barra de Control durante la grabación

- **Formulación literal del Usuario funcional:** «Todas».
- **Contexto de la respuesta:** responde a la pregunta de si la Barra de Control durante la grabación debe permitir detenerla o pausarla, añadir notas, o ambas cosas.
- **Interpretación confirmada:** el Usuario funcional espera ambas cosas: controles para pausar/detener la grabación y la posibilidad de añadir notas durante la grabación.
- **Límite:** no se especifican detalles adicionales de interacción ni se aprueba alcance de producto. La relación de la Barra de Control con el indicador configurable desde preferencias sigue abierta.

### 2026-10-09 — Controles esperados durante la grabación

- **Formulación literal del Usuario funcional:** «Muestra contador de grabacino, controles para para detener, pausar y cancelar, tambine seleccoinar microfono, debe permitir moverlo a cualquier parte de la pantalla».
- **Descubrimiento / expectativa, no decisión de alcance aprobada:** durante una grabación, el Usuario funcional espera un contador de tiempo y un control flotante que permita detener, pausar y cancelar; seleccionar el micrófono; y moverse libremente a cualquier parte de la pantalla.
- **Lectura de la referencia visual:** la captura muestra el contador `00:09`, botones con iconos de X, pausa y detener, y un selector de micrófono. También muestra un agarre punteado en el borde izquierdo, que visualmente sugiere que el control puede arrastrarse, pero la imagen por sí sola no demuestra su comportamiento; la expectativa de poder moverlo por la pantalla proviene de la formulación del Usuario funcional.
- **Límite sobre “cancelar”:** no se infiere qué ocurre con la grabación, el archivo o cualquier dato ya capturado al cancelar; el comportamiento sigue abierto.
- **Referencia visual:** `recording-floating-controls.jpg` (referencia local no incluida en GitHub), copia sin modificar de la imagen compartida por el Usuario funcional.
- **Contexto de producto:** esto registra una expectativa para la experiencia de captura, dentro de la definición todavía abierta de las funcionalidades generales de Sauri. No convierte la barra ni sus controles en alcance inicial aprobado.
- **Nota de actualización posterior:** la aclaración cronológica siguiente resuelve el límite que aquí se dejó abierto. Esta entrada conserva lo que se conocía entonces; para el entendimiento vigente, prevalece la aclaración posterior.

### 2026-10-09 — Precisión sobre cancelar, pausar y detener

- **Formulación literal del Usuario funcional:** «cancelar simplemente deja de grabar y no desencadena ninguna otra acción; pausar detiene temporalmente la captura y permite reanudar; detener finaliza la grabación y entonces se almacena en Sauri y se transcribe.»
- **Clasificación:** expectativa/descubrimiento sobre el comportamiento de los controles de grabación; no es alcance aprobado ni autorización para implementar.
- **Interpretación fiel:** cancelar solo deja de grabar y no produce otra acción; pausar detiene temporalmente la captura y permite reanudarla; detener finaliza la grabación, tras lo cual se almacena en Sauri y se transcribe.
- **Prevalencia:** esta aclaración posterior resuelve el límite sobre “cancelar” anotado en la entrada cronológica anterior y prevalece para describir el comportamiento esperado.

### 2026-10-09 — Referencia visual de selector de pestaña/ventana/pantalla

- **Formulación literal del Usuario funcional:** «Cyrus, hablemos sobre el menú que sale cuando se le da click al botón de nueva nota o grabación. En otra app al hacer esto genera esta ventana, no sé qué framework o tecnología usan, pero es la ventana que sale para seleccionar la pestaña del navegador para seleccionarla y grabar».
- **Clasificación:** referencia visual e inspiración para conversar sobre el menú/selector al iniciar «nueva nota o grabación»; no es un requisito aprobado ni una decisión sobre el comportamiento de Sauri.
- **Lectura visual:** la ventana dice “Choose what to share with Sider: Chat with all AI: GPT-5, Claude, DeepSeek, Gemini, Grok” y avisa que el sitio podrá ver el contenido de la pantalla. Ofrece “Chrome Tab” (activa), “Window” y “Entire Screen”; con la pestaña de Chrome activa, muestra una lista de pestañas abiertas a la izquierda y un panel de vista previa a la derecha que dice “Select a tab to share”. Abajo aparece “Share with tab audio” activado, y las acciones “Cancel” y “Share with Audio” (esta última deshabilitada sin una fuente seleccionada).
- **Límite:** no se infiere qué framework, API o tecnología lo genera ni que Sauri deba reproducirlo. La captura original se conserva localmente y no se incluye en este documento versionado.
- **Pregunta abierta:** ¿qué quiere el Usuario funcional que Sauri ofrezca al elegir dónde grabar: limitarse a elegir la pestaña y ajustar el modo/fuente antes o después, o permitir elegir también fuente o modo de captura en esa misma ventana? La referencia no decide la respuesta.

### 2026-10-09 — Cerrar el selector sin elegir una pestaña

- **Formulación literal del Usuario funcional:** «simplemente dar click otra vez en el boton de grabacion o tomar nota de la extension».
- **Clasificación:** expectativa confirmada sobre cómo actuar después de cerrar el selector de pestaña sin seleccionar una; no es requisito aprobado ni autorización de implementación.
- **Interpretación fiel:** si se cierra el selector sin elegir una pestaña o ventana, no hace falta un aviso adicional; basta con volver a pulsar el botón de grabación o de tomar nota desde la extensión.
- **Pregunta abierta:** cuando el Usuario funcional vuelve a pulsar grabar o tomar nota, ¿espera que el selector se abra otra vez para elegir una pestaña o ventana, o que la acción continúe de otra manera?
