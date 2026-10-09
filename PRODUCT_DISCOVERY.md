# Descubrimiento de producto — Sauri

> **Nota de distribución:** Las imágenes originales de referencia se conservan fuera del repositorio. Los descriptores textuales de §3 son la única referencia visual versionada; los nombres indicados identifican recursos locales no incluidos.


> **Estado y autoridad.** Documento persistente del descubrimiento funcional compartido por la persona usuaria. Registra fielmente su intención y las referencias aportadas; **no es un `PRODUCT_BASELINE.md` aprobado**, no constituye aprobación de alcance ni define arquitectura, tecnología o criterios de aceptación de producto. Úsese como fuente de verdad del descubrimiento al preparar el documento final para los siguientes agentes. Si algo no está expresado aquí, no debe completarse por inferencia.

## 1. Alcance del descubrimiento

- **Expresado por la persona usuaria:** el descubrimiento funcional de Sauri parte desde cero. El usuario inicial es el usuario funcional. Sauri debe concebirse como una herramienta/plataforma interna de Summan, con potencial futuro de escalar a muchos usuarios. La forma concreta de ese escalamiento queda pendiente de revisión; no se han definido disponibilidad de identidades entre usuarios ni permisos (§7, 2026-10-09).
- **Contexto declarado por la persona usuaria:** la plataforma está autorizada y, antes de grabar, se pide permiso a los asistentes. Esta es la afirmación de la persona usuaria, no una verificación independiente ni una especificación de controles de consentimiento.

## 2. Lo expresado o decidido por la persona usuaria

### 2.1 Captura y llegada al portal

- **Flujo de captura bajo demanda (descubrimiento, no requisito aprobado):** el usuario hace clic en la extensión, elige la opción «grabar sesión», selecciona la pestaña de Google Meet en una ventana de Chrome que muestra todas las pestañas del navegador y, después de una cuenta regresiva cuya duración está definida en las preferencias del usuario, comienza la grabación. la persona usuaria expresa como expectativa que «se garantiza audio y video» (§7, 2026-10-09). No se especifican aquí otros pasos ni detalles de esa expectativa.
- **Ventana al elegir una nueva nota o grabación (inspiración, no requisito aprobado):** la persona usuaria quiere conversar sobre la ventana que aparece al pulsar ese botón y comparte como referencia otra app, donde se puede elegir una pestaña del navegador para grabar (§7, 2026-10-09). La imagen parece mostrar el selector de compartir de Chrome; no identifica el framework de la otra app ni decide qué debe ofrecer Sauri.
- **Selector de fuente (inspiración visual, no requisito aprobado):** la referencia `chrome-tab-share-selector.jpg` (referencia local no incluida en GitHub) muestra un diálogo para elegir entre “Chrome Tab”, “Window” y “Entire Screen”; en la pestaña de Chrome lista pestañas a la izquierda, un área de vista previa a la derecha y una opción “Share with tab audio”, además de “Cancel” y una acción de compartir deshabilitada mientras no se selecciona una fuente. Esta referencia no confirma tecnología, framework ni el comportamiento que la persona usuaria quiere para Sauri. (§7, 2026-10-09)
- **Expectativa confirmada al cerrar el selector sin seleccionar:** la persona usuaria indicó que basta con volver a hacer clic en el botón de grabación o de tomar nota de la extensión; no requiere otra acción para cerrar el selector (§7, 2026-10-09). Esto no aclara todavía qué ocurre después de ese nuevo clic.
- **Expectativa confirmada sobre la Barra de Control durante la grabación:** la persona usuaria respondió «Todas» a la pregunta de si debe permitir detener o pausar la grabación, añadir notas, o ambas cosas. La expectativa es que permita tanto pausar/detener como añadir notas durante la grabación. Esto registra lo esperado; no aprueba alcance ni define detalles adicionales de interacción.
- **Precisión posterior sobre cancelar, pausar y detener (descubrimiento, no alcance aprobado):** cancelar simplemente deja de grabar y no desencadena ninguna otra acción; pausar detiene temporalmente la captura y permite reanudar; detener finaliza la grabación y entonces esta se almacena en Sauri y se transcribe (§7, 2026-10-09). Esta aclaración posterior resuelve el comportamiento de esos controles, sin aprobar su implementación ni otro alcance.
- Desde una extensión de Google Meet, el usuario puede iniciar y detener la grabación.
- **Expectativa confirmada sobre preferencias e indicador:** la extensión tiene un menú de preferencias del usuario para centralizar lo que la persona usuaria ha pedido configurar; incluye definir si se muestra o se oculta el indicador flotante de grabación. La duración de la cuenta regresiva también está definida por preferencias en el flujo descrito arriba. La referencia `extension-recording-preferences-menu.jpg` muestra visualmente cuenta regresiva “3s”, resolución “720p” y “Barra de Control” apagada; esos valores/estados visibles no se convierten por sí solos en valores o ajustes confirmados.
- **Aclaración anterior de identidad y contenido del control:** la referencia `recording-floating-controls.jpg` se relacionó con el indicador configurable y con las expectativas previas de contador, cancelar/pausar/detener, selección de micrófono, movimiento por la pantalla y añadir notas (§7). La captura muestra contador, X, pausa, detener y selector de micrófono, pero no una acción de notas. Una precisión posterior establece que la persona usuaria no quiere controles visibles durante la captura; prevalece para la visibilidad, sin resolver qué controles siguen disponibles ni cómo se accede a las notas.
- **Precisión posterior sobre controles durante la captura:** ocultar el indicador es intencional porque la persona usuaria no necesita controlar la grabación mientras ocurre. Para terminar, deja de compartir la pestaña de Chrome que se está capturando, de forma análoga a compartir una pestaña en una reunión virtual. Esta precisión prevalece sobre inferir un control visible persistente de la referencia y no decide otros detalles técnicos (§7, 2026-10-09).
- **Notas de grabación:** la persona usuaria espera poder añadir notas desde el control flotante o desde la extensión; deben quedar en un apartado separado de la transcripción y asociadas a la misma grabación (§7, 2026-10-09). No se define cómo se accede a la opción del control flotante cuando el indicador está oculto, ni formato o edición. La composición del selector y sus controles/opciones queda para diseño si no está definida por las referencias o este registro; no se inventa.
- Al terminar la reunión y cerrar la pestaña, se abre el portal Sauri con la grabación y la transcripción.

### 2.2 Biblioteca de grabaciones

- El portal ofrece un historial/listado de grabaciones y permite seleccionar una sesión.
- Para una sesión, el usuario puede renombrarla, eliminarla y descargar el video y la transcripción.
- El listado se puede filtrar y ordenar; la selección de filtros se definirá en diseño según los metadatos disponibles, sin asumir desde ahora cuáles serán. El orden expresado es por fecha, con las más recientes primero.
- Se pueden editar los metadatos de compañía, proyecto y participantes.
- **Aclaración de alcance y objetivo futuro:** llevar inteligencia al CRM queda para una etapa futura, después de estabilizar la captura de reuniones, las transcripciones y la diarización; no forma parte del alcance actual. El agente de IA del CRM también queda fuera de Sauri. El cómo de una eventual integración se discutirá en el futuro; no se acuerdan campos ni mecanismos (§7, 2026-10-09).
- Hay tags predefinidos —por ejemplo, **GenAI**, **Digital Twin** y **Automatización**— y el usuario también puede crear tags.

### 2.3 Vista de una reunión

- La vista incluye un reproductor con controles habituales: avance, velocidad, resolución/calidad, pausar/detener, volumen y mute.
- Conforme se reproduce audio/video, se resalta el texto correspondiente. La persona usuaria puede elegir un párrafo/fragmento y activar un control para reproducir desde el tiempo asociado; minuto/segundo es la asociación propuesta. La expectativa funcional confirmada es la sincronización temporal y el salto desde el fragmento a su audio; el control, formato temporal y manejo específico del video quedan para diseño (§7, 2026-10-09).
- la persona usuaria considera ideal editar manualmente la transcripción para corregir errores por fallas de audio/ruido y espera que las correcciones se guarden. Es una expectativa deseada, no alcance definitivamente aprobado; las reglas de edición e historial quedan por definir (§7, 2026-10-09).
- A la derecha hay un panel con el resumen, que se puede copiar o descargar.
- **Composición del portal:** la persona usuaria afirma que ya informó cómo quiere el portal. Se conserva la visión previamente registrada y la referencia visual sin inventar ni sustituir la composición por otra; esta actualización no reconstruye detalles ausentes. La distribución descrita previamente (panel izquierdo con grabaciones, central con video y `summary`, derecho con transcripción) es una referencia de interfaz futura, no requisito aprobado; la captura de §3 muestra otra distribución y tampoco define alcance.

### 2.4 Resúmenes y plantillas

- El resumen debe identificar el tema principal, presentar argumentos o puntos clave y organizarlos de forma clara y estructurada.
- La intención expresada es que el usuario pueda definir, crear y editar su plantilla desde Perfil/Biblioteca, y elegir una plantilla predeterminada para los resúmenes.
- La biblioteca de plantillas tiene categorías y puede contener varias plantillas por categoría.
- Como propuesta inicial se mencionó **General > “Resumen básico”**.
- La imagen de la biblioteca inspira categorías, favoritos/predeterminadas y los ejemplos **“Reunión General”**, **“Planificación de Sprint”** y **“Lluvia de ideas”**. Los nombres de ejemplo y los controles que aparecen en la imagen no son requisitos confirmados por la persona usuaria.

### 2.5 Transcripción e identificación de hablantes

El documento preexistente conserva la frase: **“una transcripción correcta es importante, pero también los hablantes”.** La fuente literal y la fecha de ese mensaje no están disponibles en este contexto (§7); no se presenta como transcripción verificada. El resumen existente interpreta ambos aspectos como centrales.

- Al terminar la grabación, Sauri guarda el video e inicia la transcripción y la diarización/intento de identificación automática de hablantes. En el ejemplo actualizado de una reunión con tres asistentes del cliente y tres de Summan, intenta identificar a esas seis personas: si reconoce al hablante, muestra su nombre; si no reconoce una voz o duda de a quién corresponde, marca el segmento como **Speaker N**. El ejemplo es ilustrativo, no un límite de hablantes, y no garantiza identificaciones correctas (§7, 2026-10-09).
- Cuando termina ese proceso, la primera vez se presenta un modal para revisar los nombres. **Antecedente de un ejemplo previo de la persona usuaria:** con cinco personas, el sistema detectaba dos a partir de identificaciones anteriores y mostraba sus nombres; las otras tres, aún no identificadas, aparecían como **Speaker 1**, **Speaker 2** y **Speaker 3**. Para la reunión actual descrita aquí prevalece el ejemplo actualizado de seis asistentes.
- En el modal, el usuario puede reproducir un fragmento claro de audio de cada hablante y reemplazar **Speaker N** por el nombre real o etiqueta que elija. También puede corregir nombres identificados automáticamente.
- Después de revisar, la transcripción se muestra con los nombres correctos, como en la referencia visual.
- Si el usuario cierra el modal, se va o no termina la revisión, al volver a esa grabación en el portal el sistema detecta que la revisión sigue pendiente y vuelve a pedirla abriendo el modal. La revisión queda pendiente hasta completarse; no se plantea como una acción que pueda omitirse definitivamente.
- la persona usuaria espera que una persona identificada aparezca con su nombre y que quien no sea identificada conserve un identificador **Speaker N** hasta su revisión; las identificaciones ya definidas se reutilizan en el futuro.
- **Precisión sobre identificación y reutilización:** durante la diarización de grabación/audio, Sauri debe poder reutilizar identidades ya reconocidas pese a variaciones acústicas (por ejemplo, condiciones distintas de sonido o voz), mediante patrones/variaciones asociados a esa persona. El mecanismo técnico lo define el diseño: no se prescribe patrón de voz/ondas ni modelo específico. la persona usuaria considera tecnologías de punta y ML/DL si son necesarios para mejorar la identificación de todos los hablantes (§7, 2026-10-09).
- **Decisión confirmada:** si se corrige una identificación automática equivocada, esa corrección debe aplicarse al reconocimiento futuro de ese hablante en toda la plataforma Sauri, no solo a esa grabación (§7, 2026-10-09). Esta decisión define el resultado y su alcance de producto; no especifica implementación técnica, permisos, visibilidad entre usuarios ni política de datos.
- la persona usuaria define como necesidad actual que la identificación del hablante quede disponible para que él la use. Debe concebirse dentro de la plataforma interna de Summan y considerar el potencial futuro de escalar a muchos usuarios; el modelo concreto de escalamiento sigue abierto (§7, 2026-10-09).
- **Descubrimiento, no requisito aprobado:** tras revisar los hablantes, la persona usuaria no espera otra acción inmediata; espera encontrar luego esa grabación en la plataforma web de Sauri para buscarla, volver a ver el video, leer la transcripción o descargar el video o la transcripción (§7, 2026-10-09).

### 2.6 Recorrido narrativo para orientar el descubrimiento

El siguiente recorrido ordena lo expresado hasta ahora para que el equipo pueda razonar sobre la experiencia completa. **No es un requisito aprobado, diseño de solución, contrato de interfaz ni autorización para implementar.** Cada capacidad conserva su calificación de descubrimiento, expectativa, decisión o referencia; lo que no esté definido se mantiene como pregunta.

1. **Preparación de la extensión.** La persona usuaria abre las preferencias de la extensión. la persona usuaria espera que allí se configuren las preferencias que ha pedido, incluida la duración de la cuenta regresiva y si se muestra el indicador flotante. La captura `extension-recording-preferences-menu.jpg` inspira visualmente el menú y muestra “3s”, “720p” y “Barra de Control” apagada; esos valores/estados no son elecciones confirmadas. La opción de mostrar/ocultar sí se refiere al control flotante de `recording-floating-controls.jpg`. No se agregan a la lista de preferencias otros controles que solo aparezcan en imágenes.
2. **Inicio de una reunión virtual.** En el ejemplo conversado participan tres personas del cliente X y tres de Summan. El usuario inicia bajo demanda desde la extensión, elige «grabar sesión», selecciona la pestaña de Google Meet entre las pestañas de Chrome y espera la cuenta regresiva definida en preferencias. la persona usuaria espera que se garantice audio y video; esto registra su expectativa, no una garantía técnica comprobada. La imagen del selector de otra app inspira la selección de pestaña/fuente, pero no define que Sauri permita grabar ventanas o toda la pantalla.
3. **Captura durante la reunión.** La referencia `recording-floating-controls.jpg` sigue siendo inspiración visual, no una instrucción de mantener controles visibles. la persona usuaria aclara que ocultar el indicador es intencional porque no necesita controlar mientras graba; para terminar, deja de compartir la pestaña capturada. Las notas pueden añadirse desde el control flotante o la extensión y quedan separadas de la transcripción, asociadas a la grabación (§7). No se infiere cómo se accede a notas cuando el indicador está oculto ni se inventa una composición del selector; esos detalles quedan para diseño.
4. **Cierre y procesamiento.** Tras detener, la expectativa es almacenar la grabación e iniciar transcripción y diarización/intento de identificación. La referencia `processing-progress.jpg` muestra una pantalla de progreso, pero no fija etapas, porcentaje, refresco, duración ni estados de error de Sauri. No se supone una automatización o etapa adicional a las ya expresadas.
5. **Diarización y revisión humana.** El ejemplo de seis personas es ilustrativo, no límite. Sauri muestra un nombre si reconoce al hablante; si no reconoce una voz o duda de a quién corresponde, marca el segmento como `Speaker N`. Durante diarización de audio, espera reutilizar identidades ya reconocidas aun con variaciones acústicas, mediante patrones/variaciones asociados a esa persona. El diseño define el mecanismo, sin modelo ni técnica prescritos; se consideran tecnologías de punta y ML/DL si hacen falta para mejorar la identificación de todos los hablantes. En el flujo de revisión ya registrado, la persona puede oír un fragmento, asignar nombre/etiqueta y corregir nombres automáticos; la corrección debe influir en el reconocimiento futuro en toda Sauri. La revisión incompleta sigue pendiente y se vuelve a solicitar al regresar a la grabación.
6. **Llegada al portal web y consulta posterior.** la persona usuaria espera que, después de la revisión, la grabación esté en la plataforma web para buscarla, volver a ver el video, leer la transcripción o descargar ambos. La composición del portal ya informada por la persona usuaria se conserva en el registro previo; esta actualización no la sustituye ni añade una propuesta. `web-interface-future-layout.jpg` y `meeting-transcript-player.jpg` siguen siendo referencias visuales, no autorización para inferir su composición o controles como alcance.
7. **Relación entre video y transcripción.** Conforme se reproduce audio/video, se resalta el texto correspondiente; al elegir un párrafo/fragmento y activar un control, se espera reproducir desde el tiempo asociado. Minuto/segundo es la asociación propuesta; control, formato temporal y manejo del video quedan para diseño. la persona usuaria considera ideal corregir manualmente errores de transcripción causados por fallas de audio/ruido y espera que las correcciones se guarden; es expectativa deseada, no alcance definitivamente aprobado. Los filtros se definirán en diseño con base en metadatos guardados, sin proponer un catálogo arbitrario. La etapa CRM es futura, después de estabilizar captura, transcripción y diarización.

Este recorrido resume el registro acumulativo y no es un `PRODUCT_BASELINE.md` aprobado. La aprobación de alcance, las reglas de privacidad/consentimiento, los permisos y las decisiones de interfaz o interacción pendientes siguen en manos del proceso de descubrimiento.

## 3. Inspiración visual — no requisitos por sí sola

Las capturas originales se conservan localmente y no se incluyen en el repositorio. Esta sección conserva solo descripciones textuales de referencias de UI; sus controles, textos, estados y comportamientos no se consideran decisiones salvo donde el texto de la persona usuaria los confirma explícitamente en la sección 2.

| Archivo local | Qué muestra / aporta como inspiración |
| --- | --- |
| `template-library.jpg` (referencia local no incluida en GitHub) | Pantalla titulada “Template Library”: panel lateral de categorías y favoritos, una plantilla abierta con contenido de ejemplo, iconos de favorito/personalización y acciones para crear o usar una plantilla. Es referencia visual; los rótulos y controles no confirmados no son requisitos. |
| `preferences.jpg` (referencia local no incluida en GitHub) | Pantalla “Preferences” con selectores de idioma, opción de traducción automática, selección de plantilla de resumen, controles de eliminación de transcripciones/audio, notificación y tema; también muestra navegación de ajustes. Todo es inspiración visual, no preferencias confirmadas por la persona usuaria. |
| `meeting-transcript-player.jpg` (referencia local no incluida en GitHub) | Vista de una sesión con metadatos, acción para añadir tag, filas de transcripción con marcas de tiempo y hablantes, y controles de reproducción/comentario. La captura contiene texto y nombres de una reunión; no se transcriben aquí. Los elementos no confirmados siguen siendo inspiración, no requisitos. |
| `processing-progress.jpg` (referencia local no incluida en GitHub) | Pantalla de procesamiento con porcentaje, barra de progreso, lista de etapas textuales y botón “Refresh”. Las etapas y el porcentaje son contenido de la imagen, no una afirmación sobre algoritmo, arquitectura o etapas técnicas obligatorias. |
| `speaker-review.jpg` (referencia local no incluida en GitHub) | Modal “User Profiles” con tres filas de hablantes/perfiles, acciones de reproducción y edición, botón “Save” y cierre. Es referencia visual para la revisión descrita en §2.5; no confirma el número de hablantes ni otros detalles del ejemplo de la captura. |
| `web-interface-future-layout.jpg` (referencia local no incluida en GitHub) | Captura de una interfaz con lista de archivos/grabaciones a la izquierda, video y transcripciones en el panel central, y una pestaña/panel “Infografía” a la derecha. Se conserva como inspiración visual; la distribución que la persona usuaria imagina para Sauri está formulada en §2.3 y §7, y ni esta captura ni sus controles, textos o datos visibles aprueban requisitos o alcance. |
| `extension-microphone-input-menu.jpg` (referencia local no incluida en GitHub) | Barra superior con selector/toggle de “Pantalla + aud…” y un menú desplegado desde el control con icono de micrófono. El menú ofrece opciones de entrada como “MacBook Air Microphone (Built-in)”, una entrada identificada como micrófono de iPhone y “Default – MacBook Air Microphone (…)”. La captura permite concluir que se muestran opciones de dispositivo de micrófono; no muestra cómo se seleccionan, persisten ni afectan una grabación. |
| `extension-capture-mode-menu.jpg` (referencia local no incluida en GitHub) | Barra superior similar y menú con “Grabar pantalla de la pestaña + audio” y “Grabar solo audio de la pestaña”. Son modos/opciones visibles de captura; no se muestra el resultado de elegirlos ni qué significa “audio” en cada caso más allá del texto. |
| `extension-recording-preferences-menu.jpg` (referencia local no incluida en GitHub) | Menú de preferencias con “Cuenta regresiva” configurada visualmente en “3s”, “Resolución” en “720p” y “Barra de Control” con un interruptor apagado. la persona usuaria confirma que las preferencias de la extensión centralizan lo que pidió configurar e incluyen mostrar/ocultar el indicador flotante; esta es la referencia visual del menú. Los valores de ejemplo no son valores confirmados. |
| `recording-floating-controls.jpg` (referencia local no incluida en GitHub) | Barra flotante oscura con agarre punteado, contador `00:09`, botones con iconos de X, pausa y detener, y selector de micrófono. Es la referencia visual del indicador/control flotante; la expectativa de poder moverlo por la pantalla proviene de la formulación de la persona usuaria. |
| `extension-rec-notes-screen.jpg` (referencia local no incluida en GitHub) | Pantalla titulada “REC Notas”, con la misma barra superior de captura y un botón principal “+ Nueva nota REC”. Se aprecia una acción para crear una nota REC; no se muestra el flujo posterior, su relación con la grabación ni el contenido de una nota. |
| `chrome-tab-share-selector.jpg` (referencia local no incluida en GitHub) | Ventana titulada “Choose what to share with Sider: Chat with all AI: GPT-5, Claude, DeepSeek, Gemini, Grok” y texto “The site will be able to see the contents of your screen”. Está activa la pestaña “Chrome Tab”; también aparecen “Window” y “Entire Screen”, una lista de pestañas abiertas a la izquierda y un panel de vista previa a la derecha con “Select a tab to share”. Abajo se ve “Share with tab audio” activado y los botones “Cancel” y “Share with Audio” (este último deshabilitado). Inspira la selección de una pestaña/fuente y el control de audio; visualmente parece el selector de compartir de Chrome, pero no demuestra qué tecnología usa Sider ni establece requisitos para Sauri. |

## 4. Inferencias o propuestas no aprobadas

Esta sección delimita lo que **no** debe elevarse a decisión de la persona usuaria:

- Existe potencial futuro de escalar la herramienta interna a muchos usuarios en Summan, pero la forma concreta de hacerlo no está decidida. No se infiere disponibilidad o alcance de identidades entre usuarios ni permisos.
- No se eligieron tecnología, modelo o técnica para transcripción e identificación de hablantes. la persona usuaria espera tecnología de punta y que se use ML/DL si hace falta; esto expresa una expectativa de capacidad/calidad, no una selección técnica. La referencia visual de procesamiento no determina algoritmo, proveedor, arquitectura ni secuencia técnica.
- Los controles o ajustes visibles en las imágenes —incluidos idioma, traducción, retención, notificaciones, tema, selección de micrófono, modo de captura, cuenta regresiva, resolución, barra de control y notas REC— no constituyen capacidades confirmadas por sí mismos. la persona usuaria confirma que las preferencias de extensión centralizan lo que pidió configurar, incluido mostrar/ocultar el indicador flotante; el vínculo de ese indicador con el control de `recording-floating-controls.jpg` queda aclarado en §2.1 y §7. Los valores “3s” y “720p” de la captura no son valores confirmados.
- Los ejemplos adicionales de plantillas o controles de favoritos, personalización y selección que solo aparecen en la imagen no son requisitos confirmados. La categoría **General**, el ejemplo inicial **“Resumen básico”**, la capacidad de gestionar plantillas y elegir una predeterminada sí reflejan la intención expresada por la persona usuaria.
- No se infieren políticas de compartición de plantillas, permisos, retención de grabaciones/transcripciones, exportación adicional, idioma, ni analítica más allá de lo indicado en §2.
- Llevar inteligencia al CRM queda para una etapa futura, después de estabilizar la captura de reuniones, las transcripciones y la diarización; no forma parte del alcance actual. El agente de IA del CRM está fuera de Sauri. No hay integración, campos ni mecanismos acordados; los detalles mencionados antes sobre oportunidad, metadatos, URL del video y campos relacionales no son decisiones vigentes (§7, 2026-10-09).

## 5. Preguntas y puntos diferidos

Esta sección distingue las preguntas de descubrimiento aún abiertas de los asuntos asignados a diseño o a una etapa futura; estos últimos no son nuevas preguntas de producto para la persona usuaria. No preguntar si la revisión de hablantes puede omitirse o posponerse: la persona usuaria ya definió que queda pendiente y se vuelve a solicitar hasta completarse.

1. ¿Cómo se revisará la forma de escalar la plataforma interna a muchos usuarios en Summan, incluida la disponibilidad/alcance de identidades de hablantes entre usuarios y los permisos? No está decidido ahora.
2. **Pendiente de diseño técnico, no decisión de producto:** selección de tecnología/modelo para transcripción y diarización/identificación. la persona usuaria deja el mecanismo al diseño; considera tecnología de punta y ML/DL si hacen falta.
3. En la gestión de plantillas, ¿las plantillas y la selección predeterminada son personales o compartidas, y cómo se elige la predeterminada cuando hay varias categorías? la persona usuaria no precisó estas reglas.
4. **Pendiente de diseño técnico:** determinar cómo reconocer identidades previas ante variaciones acústicas y dudas, sin presumir una técnica específica. La expectativa de resultado es reutilizar identidades; las dudas se representan como `Speaker N`.
5. **Pendiente de diseño:** cómo se accede a notas desde el control flotante cuando el indicador está oculto. La acción esperada para terminar sí está definida: dejar de compartir la pestaña; no se inventan controles alternativos.
6. Al terminar la captura, ¿qué estado/feedback verá la persona durante el procesamiento, cuánto tarda y qué resultado se presenta antes de pasar a la grabación/transcripción disponibles en el portal? La referencia de progreso inspira la UI, pero no confirma estados, etapas o tiempos.
7. **Diferido a etapa futura:** cómo llevar inteligencia al CRM y qué campos/mecanismos requeriría, después de estabilizar captura, transcripciones y diarización. No hay integración acordada ni alcance CRM actual.
8. **Pendiente de diseño:** derivar filtros de grabaciones a partir de los metadatos guardados; no proponer un catálogo arbitrario.
9. **Pendiente de diseño:** definir la composición y los controles/opciones del selector sin exceder lo registrado o visible en las referencias. La referencia disponible no define por sí sola qué debe ofrecer Sauri.
10. Si la persona usuaria cierra el selector sin elegir y vuelve a pulsar «grabar» o «tomar nota» en la extensión, ¿espera que el selector se abra de nuevo para elegir una pestaña, o que el flujo continúe de otra manera? La respuesta actual confirma qué acción tomar tras cerrar, no el resultado del clic siguiente.
11. la persona usuaria indica que ya informó la composición deseada del portal. No se reconstruyen ni proponen aquí detalles adicionales ausentes del registro actual.
12. **Pendiente de diseño:** definir detalles de la edición manual y sus reglas; la expectativa deseada de corregir errores por audio/ruido y guardar los cambios queda registrada, sin aprobarse como alcance.
13. **Pendiente de diseño:** concretar el control de salto, formato de asociación temporal y manejo específico del video; la sincronización y el salto desde el fragmento a su audio ya están expresados como expectativa funcional.

## 6. Límite de uso para los siguientes agentes

Este registro preserva el descubrimiento; no autoriza implementar funcionalidades ni sustituye las decisiones pendientes. Los siguientes agentes deben separar este contexto de cualquier baseline aprobada, mantener las referencias visuales como inspiración y llevar las preguntas abiertas al proceso de decisión correspondiente sin rellenarlas por su cuenta.

## 7. Registro cronológico de formulaciones originales disponibles

### 2026-10-09 — Persistencia y fidelidad del descubrimiento

- **Resumen editorial heredado (no literal; expectativa de proceso, no requisito de producto):** la persona usuaria indicó que no quiere que se sinteticen sus ideas porque eso puede cambiar el producto; quiere que Cyrus mantenga dentro del proyecto un registro persistente de lo hablado/definido y use esa fuente para el documento final que usarán los siguientes agentes.
- **Decisión/expectativa confirmada:** preservar las formulaciones originales de la persona usuaria cuando estén disponibles; la interpretación actual permanece como índice y no reemplaza el original. Cyrus debe mantener el registro dentro del proyecto y usarlo como fuente del documento final para los siguientes agentes.
- **Contexto declarado de esta intervención:** la corrección solicitada no aprueba un `PRODUCT_BASELINE.md`, no pide implementar producto y limita los cambios al descubrimiento.
- **Ejemplos:** no se añadió ningún ejemplo funcional en esta intervención.
- **Preguntas abiertas:** no se resolvieron preguntas funcionales del descubrimiento.
- **Límite de recuperación:** en este contexto no están disponibles los mensajes originales anteriores de la conversación de descubrimiento ni sus fechas. El contenido previo de §§1–6 es un resumen ya creado; no se puede certificar como transcripción literal. La única cita literal anterior que el documento conserva es “una transcripción correcta es importante, pero también los hablantes”; su mensaje fuente y fecha no están disponibles aquí. No se reconstruyen ni se atribuyen otras citas. Las cinco imágenes locales se pudieron inspeccionar, pero no hay un manifiesto u originales externos que permita verificar su procedencia histórica; se confirma únicamente que estos cinco archivos presentes corresponden visualmente a las referencias inventariadas.

### Formulaciones fuente visibles en el contexto actual (sin fecha histórica atribuida)

Las siguientes citas sí aparecen literalmente en la instrucción de la persona usuaria visible en este contexto. Se conservan con su ortografía y errores originales; las etiquetas y notas entre corchetes son editoriales, no parte de las citas.

- **Formulación literal — expectativa de identificación de hablantes y uso de referencia visual:** “Si, si Sauri ya logra identificar un hablante con un nombre que ya habiamos definido, enotnces en vez de mostarlo con la etiqueta generica Speaker N, debe aparecer el nombre del usario. Yo te mostre una imagen de referencia. Cuando te pase imagnes de referencia deberias de tomar nota de lo que se muestra para en el futuro tratar de imitar las UI.”
- **Formulación literal — expectativa de fidelidad y persistencia del descubrimiento:** “No quiero disculpas, quiero que corrijas, no quiero que sintetices mis ideas, porque luego definimos el poducto como no es. Quiero que dentro del proyecto quede en persistenca de lo que hablamos y lo que se esta definiendo, esto Cyrus lo debe garantizar. Cyrus usara esa informacion persistida para crear el documento final de prudcot que usara el resto de los agentes o por lo menos el siguiente agente en el proceso.”

**Resumen recuperado/no literal — flujo de revisión de hablantes:** la instrucción actual identifica una formulación extensa de la persona usuaria sobre una sesión de cinco personas: detección de dos hablantes conocidos, presentación de los otros como `Speaker 1/2/3`, reproducción de fragmentos de audio, renombrado, transcripción con los nombres correctos y reaparición del modal si la revisión quedó incompleta. El texto fuente exacto de esa formulación no está visible aquí, por lo que esto no se presenta como cita ni se reconstruye.

**Resumen recuperado/no literal — otras áreas:** §§2.1–2.4 y §5 ya contienen resúmenes sobre captura desde Meet, llegada al portal, plantillas, resumen y transcripción; §1 contiene el contexto declarado sobre autorización y solicitud de permiso antes de grabar. La instrucción actual menciona esos temas, pero no muestra sus formulaciones fuente literales. Se conservan como resumen, sin convertirlos en citas.

**Referencias visuales:** los originales de las cinco capturas listadas en §3 se mantienen localmente y no se incluyen en este documento versionado. Las descripciones textuales de §3 son la referencia persistente; inspiran UI, pero no sustituyen formulaciones ni confirman por sí solas requisitos.

### 2026-10-09 — Plataforma interna e identificación de hablantes

- **Formulación literal — identificación/reutilización de hablantes y contexto de plataforma interna:** “Estaran para Sauri como plataforma, luego revisamos esa forma de escalar a otros usuarios.

Es decir, la plataforma debe cumplir con la identificacion del hablante y dejarlo listo para que yo lo pueda usar, pero pensado que en el futuro sera escalado a muchos usuarios en Summan.

Eso lo debemos pensar como una plataforma que sera usada como una herramienta interna.”
- **Decisión confirmada (nota editorial):** Sauri se piensa como herramienta/plataforma interna; la plataforma debe identificar al hablante y dejar el resultado listo para el uso inicial de la persona usuaria; se piensa para poder escalar a muchos usuarios de Summan.
- **Aspecto abierto (nota editorial):** la forma concreta de compartir o reutilizar identidades entre usuarios queda para revisión posterior. La posibilidad de escalar no define permisos, compartición ni arquitectura.

### 2026-10-09 — Alcance de corregir una identificación automática

- **Pregunta de Cyrus (formulación literal):** «Si corriges una identificación automática equivocada, ¿quieres que Sauri aplique esa corrección al reconocimiento futuro de ese hablante en toda la plataforma, o solo a esa grabación?»
- **Respuesta de la persona usuaria (formulación literal):** «Si».
- **Decisión confirmada (nota editorial):** la corrección de identificación debe aplicarse al reconocimiento futuro del hablante en toda la plataforma Sauri, no solo a esa grabación.
- **Límite de la decisión:** define el resultado y alcance de producto; no especifica implementación técnica, permisos, visibilidad entre usuarios ni política de datos.

### 2026-10-09 — Referencia visual para la interfaz web futura

- **Formulación literal — disposición imaginada:** “Así veo en el futuro la interfaz web de Sauri, un panel izquierdo con las grabaciones, panel central dividido en dos con el video y el summary, un panel derecho con la transcripción”.
- **Clasificación:** referencia/inspiración de una posible interfaz futura, no requisito aprobado ni compromiso de implementación.
- **Resumen fiel:** la persona usuaria imagina la lista de grabaciones a la izquierda, el video y el resumen en dos partes del panel central, y la transcripción en un panel derecho.
- **Evidencia visual:** `web-interface-future-layout.jpg` (referencia local no incluida en GitHub), copiada sin modificar desde la imagen adjunta. La captura muestra una composición visual de lista a la izquierda, video y transcripciones al centro y panel “Infografía” a la derecha; no se atribuyen sus datos, rótulos o controles a Sauri.

### 2026-10-09 — Posible valor futuro de la metadata para el CRM

- **Formulación literal — posibilidad expresada por la persona usuaria:** «yo creo que esa metadata nos puede ayudar en el futuro en la vinculacion de la transcripion de una sesion con una oportunidad en le CRM»
- **Pregunta literal de la persona usuaria:** «ya tienes claro eso?».
- **Clasificación:** posibilidad/valor futuro de la metadata del video o de la sesión para facilitar potencialmente la vinculación de la transcripción de una sesión con una oportunidad del CRM; no es una decisión de alcance inicial ni un requisito aprobado. No define campos ni integración.
- **Aporte adicional comunicado por la persona usuaria (la formulación literal no está disponible en este contexto):** el equipo comercial necesitaría más información sobre una oportunidad de cliente. A futuro, se integraría el CRM con agentes de IA generativa y una buena transcripción daría contexto al agente. Para asociar una transcripción con una oportunidad hacen falta campos relacionales; la persona usuaria imagina poder editar metadatos de la grabación, por ejemplo el ID y el nombre de la oportunidad, pero aún no define los campos. Mientras falten campos asociados al CRM, no se vincularían al CRM la URL del video ni el almacenamiento de la transcripción; cuando los campos estén completos, sí se vincularían.
- **Clasificación y límites:** intención/propuesta futura, no decisión aprobada ni alcance inicial. Los campos concretos y el comportamiento/UX de edición siguen por explorar; no se deriva una especificación de integración.

### 2026-10-09 — Aclaración sobre el CRM

- **Formulación literal de la persona usuaria:** “Como te informo, el agente de AI del CRM no es parte de este proyecto. Solo entender que la transcripion es importante llevarla al CRM. El como se discutira en el futuro.”
- **Aclaración de alcance confirmada:** el agente de IA del CRM queda fuera del alcance de Sauri.
- **Objetivo expresado, no decisión de implementación:** importa considerar que la transcripción debe poder llevarse al CRM. El cómo —integración, campos, mecanismos u otros detalles— se discutirá en el futuro.
- **Límite:** esto no constituye una integración acordada ni un requisito técnico o especificación. Esta aclaración prevalece sobre las posibilidades de agente y los detalles de vinculación/metadatos mencionados en el registro CRM anterior; esos detalles siguen sin decidirse.

### 2026-10-09 — Uso posterior a la revisión de hablantes

- **Formulación literal de la persona usuaria:** «nada, estaran en la plataforam web de Sauri para buscarla despues, ver el video de nuevo, leer la transcripion, descargar el video o la transcripcion.»
- **Clasificación:** descubrimiento sobre el uso posterior a la revisión de hablantes, no requisito aprobado. la persona usuaria no espera otra acción inmediata tras revisar; espera que la grabación esté luego en la plataforma web de Sauri para buscarla, volver a ver el video, leer la transcripción o descargar el video o la transcripción.
- **Pregunta abierta:** qué información o filtros necesitaría para encontrar una grabación después; aún no se respondió.

### 2026-10-09 — Flujo de grabación bajo demanda

- **Formulación literal de la persona usuaria:** «sera por demanda, el usuario puede dar click en la extension, saldra un menu done hay una opcion de grabar sesion, al hacer click con eso lo que pasa es que se muestra una ventana con todas las pestañas del navegador para que yo pueda seleccionarla, ahí selecciono la de meet, sale una cuenta regresiba definia por las preferencia del usuario y comienza a grabar. Se garantiza audio y video.»
- **Clasificación:** descubrimiento del flujo de captura bajo demanda, no requisito aprobado.
- **Expectativa declarada por la persona usuaria:** “Se garantiza audio y video.” Se registra como expectativa declarada, no como garantía verificada ni criterio aprobado.
- **Resumen fiel:** el usuario inicia desde la extensión, elige grabar sesión, selecciona una pestaña del navegador (la persona usuaria indica que selecciona la de Meet), espera una cuenta regresiva definida por sus preferencias y comienza la grabación.
- **Límite:** no se infieren más detalles del menú, selección de pestaña, preferencias, cuenta regresiva ni garantía.

### 2026-10-09 — Precisión del flujo de grabación bajo demanda

- **Formulación literal de la persona usuaria aportada en esta instrucción:** “el usuario hace clic en la extensión; aparece un menú con la opción «grabar sesión»; al elegirla, se muestra una ventana de Chrome con todas las pestañas del navegador para que seleccione la pestaña de Google Meet; luego aparece una cuenta regresiva, cuya duración está definida en las preferencias del usuario, y al terminar comienza la grabación.”
- **Expectativa literal de la persona usuaria:** «se garantiza audio y video».
- **Clasificación:** descubrimiento del flujo de captura bajo demanda y expectativa expresada; no es requisito aprobado ni autorización de implementación.
- **Límite:** “se garantiza audio y video” registra la expectativa de la persona usuaria, no una afirmación técnica verificada sobre el sistema actual. No se infieren otros detalles de la ventana, selección, preferencias, cuenta regresiva o garantía.

### 2026-10-09 — Referencias de controles de la extensión y visibilidad del indicador

- **Formulación literal de la persona usuaria:** «Yo desde las preferencias de la extension puedo definir si quiero que se muestre un indicador de grabacion o si no.»
- **Clasificación:** decisión/expectativa confirmada sobre la preferencia de visibilidad del indicador de grabación. Confirma que la persona usuaria puede optar por mostrarlo u ocultarlo desde las preferencias de la extensión; no define aún su aspecto, ubicación, momento/estados de aparición ni controles relacionados.
- **Referencias visuales aportadas en esta intervención (inspiración, no requisitos automáticos):**
  - `extension-microphone-input-menu.jpg` (referencia local no incluida en GitHub) muestra el selector de micrófono y una lista de fuentes, incluyendo una entrada de micrófono integrada, una entrada de iPhone y una opción predeterminada. No prueba persistencia de la elección ni comportamiento al grabar.
  - `extension-capture-mode-menu.jpg` (referencia local no incluida en GitHub) muestra “Grabar pantalla de la pestaña + audio” y “Grabar solo audio de la pestaña”. No prueba el resultado de seleccionar uno de los modos.
  - `extension-recording-preferences-menu.jpg` (referencia local no incluida en GitHub) muestra cuenta regresiva “3s”, resolución “720p” y “Barra de Control” apagada en el menú de preferencias. No se puede concluir que esa barra sea el indicador de grabación confirmado por la persona usuaria.
  - `extension-rec-notes-screen.jpg` (referencia local no incluida en GitHub) muestra el encabezado “REC Notas” y la acción “+ Nueva nota REC”; no deja ver el resultado de crear una nota ni su relación con la grabación.
- **Límite de interpretación:** aunque la preferencia del indicador queda confirmada por el texto, las referencias solo muestran visualmente una opción “Barra de Control”; no establecen que sea el mismo control. También quedan sin confirmar la mecánica, efecto y persistencia de las otras opciones visuales.
- **Pregunta abierta:** ¿“Barra de Control” es el indicador de grabación que se puede mostrar/ocultar, o es una función distinta?

### 2026-10-09 — Funciones esperadas de la Barra de Control durante la grabación

- **Formulación literal de la persona usuaria:** «Todas».
- **Contexto de la respuesta:** responde a la pregunta de si la Barra de Control durante la grabación debe permitir detenerla o pausarla, añadir notas, o ambas cosas.
- **Interpretación confirmada:** la persona usuaria espera ambas cosas: controles para pausar/detener la grabación y la posibilidad de añadir notas durante la grabación.
- **Límite:** no se especifican detalles adicionales de interacción ni se aprueba alcance de producto. La relación de la Barra de Control con el indicador configurable desde preferencias sigue abierta.

### 2026-10-09 — Controles esperados durante la grabación

- **Formulación literal de la persona usuaria:** «Muestra contador de grabacino, controles para para detener, pausar y cancelar, tambine seleccoinar microfono, debe permitir moverlo a cualquier parte de la pantalla».
- **Descubrimiento / expectativa, no decisión de alcance aprobada:** durante una grabación, la persona usuaria espera un contador de tiempo y un control flotante que permita detener, pausar y cancelar; seleccionar el micrófono; y moverse libremente a cualquier parte de la pantalla.
- **Lectura de la referencia visual:** la captura muestra el contador `00:09`, botones con iconos de X, pausa y detener, y un selector de micrófono. También muestra un agarre punteado en el borde izquierdo, que visualmente sugiere que el control puede arrastrarse, pero la imagen por sí sola no demuestra su comportamiento; la expectativa de poder moverlo por la pantalla proviene de la formulación de la persona usuaria.
- **Límite sobre “cancelar”:** no se infiere qué ocurre con la grabación, el archivo o cualquier dato ya capturado al cancelar; el comportamiento sigue abierto.
- **Referencia visual:** `recording-floating-controls.jpg` (referencia local no incluida en GitHub), copia sin modificar de la imagen compartida por la persona usuaria.
- **Contexto de producto:** esto registra una expectativa para la experiencia de captura, dentro de la definición todavía abierta de las funcionalidades generales de Sauri. No convierte la barra ni sus controles en alcance inicial aprobado.
- **Nota de actualización posterior:** la aclaración cronológica siguiente resuelve el límite que aquí se dejó abierto. Esta entrada conserva lo que se conocía entonces; para el entendimiento vigente, prevalece la aclaración posterior.

### 2026-10-09 — Precisión sobre cancelar, pausar y detener

- **Formulación literal de la persona usuaria:** «cancelar simplemente deja de grabar y no desencadena ninguna otra acción; pausar detiene temporalmente la captura y permite reanudar; detener finaliza la grabación y entonces se almacena en Sauri y se transcribe.»
- **Clasificación:** expectativa/descubrimiento sobre el comportamiento de los controles de grabación; no es alcance aprobado ni autorización para implementar.
- **Interpretación fiel:** cancelar solo deja de grabar y no produce otra acción; pausar detiene temporalmente la captura y permite reanudarla; detener finaliza la grabación, tras lo cual se almacena en Sauri y se transcribe.
- **Prevalencia:** esta aclaración posterior resuelve el límite sobre “cancelar” anotado en la entrada cronológica anterior y prevalece para describir el comportamiento esperado.

### 2026-10-09 — Referencia visual de selector de pestaña/ventana/pantalla

- **Formulación literal de la persona usuaria:** «Cyrus, hablemos sobre el menú que sale cuando se le da click al botón de nueva nota o grabación. En otra app al hacer esto genera esta ventana, no sé qué framework o tecnología usan, pero es la ventana que sale para seleccionar la pestaña del navegador para seleccionarla y grabar».
- **Clasificación:** referencia visual e inspiración para conversar sobre el menú/selector al iniciar «nueva nota o grabación»; no es un requisito aprobado ni una decisión sobre el comportamiento de Sauri.
- **Lectura visual:** la ventana dice “Choose what to share with Sider: Chat with all AI: GPT-5, Claude, DeepSeek, Gemini, Grok” y avisa que el sitio podrá ver el contenido de la pantalla. Ofrece “Chrome Tab” (activa), “Window” y “Entire Screen”; con la pestaña de Chrome activa, muestra una lista de pestañas abiertas a la izquierda y un panel de vista previa a la derecha que dice “Select a tab to share”. Abajo aparece “Share with tab audio” activado, y las acciones “Cancel” y “Share with Audio” (esta última deshabilitada sin una fuente seleccionada).
- **Límite:** no se infiere qué framework, API o tecnología lo genera ni que Sauri deba reproducirlo. La captura original se conserva localmente y no se incluye en este documento versionado.
- **Pregunta abierta:** ¿qué quiere la persona usuaria que Sauri ofrezca al elegir dónde grabar: limitarse a elegir la pestaña y ajustar el modo/fuente antes o después, o permitir elegir también fuente o modo de captura en esa misma ventana? La referencia no decide la respuesta.

### 2026-10-09 — Cerrar el selector sin elegir una pestaña

- **Formulación literal de la persona usuaria:** «simplemente dar click otra vez en el boton de grabacion o tomar nota de la extension».
- **Clasificación:** expectativa confirmada sobre cómo actuar después de cerrar el selector de pestaña sin seleccionar una; no es requisito aprobado ni autorización de implementación.
- **Interpretación fiel:** si se cierra el selector sin elegir una pestaña o ventana, no hace falta un aviso adicional; basta con volver a pulsar el botón de grabación o de tomar nota desde la extensión.
- **Pregunta abierta:** cuando la persona usuaria vuelve a pulsar grabar o tomar nota, ¿espera que el selector se abra otra vez para elegir una pestaña o ventana, o que la acción continúe de otra manera?
- **Nota de prevalencia posterior:** la aclaración de preferencias e indicador flotante añadida abajo resuelve la relación entre el indicador configurable y el control flotante de la captura; las otras preguntas de interacción del registro permanecen abiertas.

### 2026-10-09 — Precisión de diarización e indicador flotante

- **Formulación literal de la persona usuaria aportada en esta intervención:** “la diarización intenta identificar automáticamente a las seis personas y, si identifica al hablante, muestra su nombre; si no, un identificador Speaker N. La extensión tiene un menú de preferencias del usuario donde se configura todo lo que pidió configurable, incluido mostrar/ocultar el indicador flotante. Ese indicador debe reflejar todo lo ya hablado e incluir la imagen de referencia que el usuario aportó.”
- **Precisión confirmada sobre diarización:** en la escena de una reunión con tres asistentes del cliente y tres de Summan, Sauri intenta identificar automáticamente a las seis personas; muestra el nombre cuando identifica a una persona y `Speaker N` cuando no. Esta precisión reemplaza el alcance del ejemplo previo de cinco personas para narrar esta escena; no garantiza una identificación correcta ni define tecnología.
- **Precisión confirmada sobre preferencias y control flotante:** la extensión concentra en el menú de preferencias las opciones que la persona usuaria pidió configurar, incluyendo mostrar u ocultar el indicador flotante. El indicador es el control flotante de la referencia `recording-floating-controls.jpg`; recoge los elementos ya expresados: contador, cancelar/pausar/detener, selector de micrófono, movimiento por la pantalla y la expectativa de añadir notas durante la grabación. La captura no muestra una acción de notas; su ubicación/interacción no queda definida. La referencia de preferencias correspondiente es `extension-recording-preferences-menu.jpg`.
- **Límite:** las imágenes se mantienen como referencias visuales, no como fuente de requisitos adicionales. La cuenta regresiva está ligada a preferencias; los valores “3s” y “720p” que aparecen en la captura no se registran como elecciones de la persona usuaria. Queda pendiente qué pasa con los controles cuando se oculta el indicador. La adición no aprueba un baseline ni autoriza requisitos/implementación.

### 2026-10-09 — Precisiones sobre captura, diarización, notas, portal y CRM

- **Fuente y límite de recuperación:** estas precisiones se recibieron en una instrucción-resumen de esta sesión, no como el mensaje conversacional original. Se registran como paráfrasis comunicadas, no como citas literales; no se reconstruyen formulaciones ausentes.
- **Identificación de hablantes — expectativa:** si Sauri no reconoce una voz o duda de a quién corresponde, marca el segmento como `Speaker N`. El ejemplo de seis asistentes es ilustrativo, no un límite.
- **Reutilización e identificación — expectativa y límite técnico:** durante la diarización de grabación/audio, Sauri debe poder reutilizar identidades reconocidas cuando haya variaciones acústicas de esa persona, considerando múltiples patrones/variaciones asociadas. El diseño define el mecanismo; no se eligen patrón de voz/ondas ni modelo. la persona usuaria considera tecnologías de punta y ML/DL si son necesarios para mejorar la identificación de todos los hablantes.
- **Controles y finalización — expectativa confirmada:** ocultar el indicador es intencional porque la persona usuaria no necesita controlar durante la grabación. Para terminar, deja de compartir la pestaña de Chrome capturada, de forma análoga a compartir pestaña en una reunión virtual. No se infiere qué control u opción aparece en el selector más allá de lo ya registrado o visible en las referencias; cualquier detalle restante queda para diseño.
- **Notas — expectativa:** añadirlas desde el control flotante o desde la extensión; quedan en un apartado separado de la transcripción y asociadas a la misma grabación. No se especifica cómo usar la opción del control flotante si el indicador está oculto.
- **Transcripción — expectativa funcional confirmada y propuesta de formato:** durante reproducción de audio/video se resalta el texto correspondiente; se puede elegir un párrafo/fragmento y activar un control para reproducir desde el tiempo asociado. Minuto/segundo es la asociación temporal propuesta. El control, formato temporal y manejo específico del video quedan para diseño.
- **Edición de la transcripción — expectativa deseada, no alcance definitivamente aprobado:** la persona usuaria considera ideal corregir manualmente errores provocados por fallas de audio/ruido y espera que las correcciones se guarden.
- **Portal — límite de fidelidad:** la persona usuaria afirma que ya informó cómo quiere el portal. No se inventa ni sustituye esa composición por una propuesta; esta entrada no reconstruye detalles que no aparecen aquí.
- **Filtros — pendiente de diseño:** se definirán a partir de los metadatos guardados, sin proponer un catálogo arbitrario.
- **CRM — alcance futuro explícito:** integrar/trasladar inteligencia al CRM queda para una etapa posterior, después de estabilizar la captura de reuniones, las transcripciones y la diarización; no forma parte del alcance actual. No se acuerdan integración, campos ni mecanismos.
- **Límite de autoridad:** estos puntos documentan descubrimiento y expectativas, no aprueban el baseline, alcance inicial, arquitectura ni requisitos finales.
