# Requirements Document

## Introduction

Este documento define los requerimientos del módulo **Side Panel de Chrome y Vista de Detalle de Transcripción** de **sauri**, la plataforma interna de inteligencia de reuniones comerciales de Summan.

El módulo aporta la experiencia de usuario (UX) de captura y consulta sobre las capacidades ya construidas por los módulos previos: el Milestone 1 (Captura de reuniones), el Milestone 2 (Transcripción/ASR) y el Milestone 3 (Identificación de hablantes/diarización). Esos módulos producen y persisten la Reunion, la Transcripcion (con Turnos_De_Habla) y la Diarizacion (con Hablantes anónimos "Hablante N" y Asignaciones_De_Hablante). Este módulo **no** vuelve a generar transcripción ni diarización: las **consume** a través de la API del backend para presentarlas.

El propósito del módulo es doble:

1. **Side Panel de la extensión de Chrome**: reemplazar el popup actual (`action.default_popup`) por un Side_Panel persistente que ofrezca un Encabezado_Panel con la acción primaria de iniciar una grabación, un bloque de Controles_De_Captura (selección de fuente de audio, activación de captura, selección de micrófono y acceso a ajustes), y una Lista_De_Notas ("Mis Notas") que muestre el historial de grabaciones como Tarjetas_De_Nota con búsqueda y filtro.
2. **Vista de Detalle web**: al seleccionar una Nota del historial, abrir una Vista_De_Detalle en una página web que presente la Transcripcion con identificación de hablantes (Panel_De_Transcripcion), incluyendo búsqueda dentro de la transcripción y una Vista_Tiempo_De_Habla ("Speaker Time"). La Vista_De_Detalle reserva un Espacio_De_Resumen estructural para el resumen con IA que se implementará en un módulo posterior.

El módulo también aborda la deuda técnica del bypass de autenticación: hoy el backend acepta el bypass `AUTH_DISABLED` para desarrollo local (`backend/app/auth/dependencies.py`), por lo que la extensión no implementa un flujo de login. Este módulo define el flujo de autenticación real de la extensión contra el backend.

Quedan **explícitamente fuera de alcance** de este módulo: la generación del resumen o notas con IA (solo se reserva el Espacio_De_Resumen sin implementarlo), la generación de transcripción y de diarización (pertenecen a los Milestones 2 y 3), la identificación nominal de hablantes (la diarización entrega etiquetas anónimas "Hablante N"), la integración con el CRM, la analítica comercial y la administración. La estética visual de alta gama se traduce en este documento a requisitos verificables sobre un Sistema_De_Diseno consistente y sobre estados de interfaz explícitos, no en juicios subjetivos de apariencia.

## Glossary

- **sauri**: Plataforma interna de Summan para captura, transcripción e inteligencia de reuniones comerciales.
- **Usuario_Comercial**: Miembro del equipo comercial de Summan autorizado para usar sauri.
- **Extension_Sauri**: Extensión de Chrome Manifest V3 de sauri que captura reuniones de Google Meet.
- **Side_Panel**: Panel lateral de Chrome (API `chrome.sidePanel`) que aloja la interfaz de captura e historial de la Extension_Sauri, reemplazando el popup actual.
- **Encabezado_Panel**: Región superior del Side_Panel que muestra el título "REC Notas" y el Boton_Nueva_Nota.
- **Boton_Nueva_Nota**: Acción primaria del Encabezado_Panel, etiquetada "+ Nueva nota REC", que inicia el flujo de una nueva grabación.
- **Controles_De_Captura**: Conjunto de controles del Side_Panel compuesto por el Selector_De_Fuente_De_Audio, el Toggle_De_Captura, el Selector_De_Microfono y el Boton_De_Ajustes.
- **Selector_De_Fuente_De_Audio**: Control que permite elegir la fuente de audio a capturar (por ejemplo, "Pantalla + audio").
- **Toggle_De_Captura**: Control de dos estados que activa o detiene la captura de la grabación en curso.
- **Selector_De_Microfono**: Control que permite elegir el dispositivo de micrófono de entrada entre los micrófonos disponibles.
- **Boton_De_Ajustes**: Control que abre la Vista_De_Ajustes de la Extension_Sauri.
- **Vista_De_Ajustes**: Vista de configuración de la Extension_Sauri abierta desde el Boton_De_Ajustes.
- **Estado_De_Captura**: Estado del ciclo de vida de la captura en el Side_Panel. Valores: "inactiva", "grabando", "deteniendo".
- **Nota**: Representación en la interfaz de una Reunion grabada por sauri junto con su Grabacion_De_Sesion y los datos derivados (Transcripcion y Diarizacion cuando existen). En la interfaz se denomina "nota REC".
- **Lista_De_Notas**: Sección "Mis Notas" del Side_Panel que presenta el historial de Notas como Tarjetas_De_Nota.
- **Tarjeta_De_Nota**: Elemento de la Lista_De_Notas que representa una Nota, mostrando su título y su fecha y hora de creación.
- **Buscador_De_Notas**: Control de texto del Side_Panel que filtra las Tarjetas_De_Nota de la Lista_De_Notas por coincidencia de texto.
- **Filtro_De_Notas**: Control del Side_Panel que restringe las Tarjetas_De_Nota visibles según un criterio seleccionable (por ejemplo, rango de fecha o Estado_De_Proceso).
- **Vista_De_Detalle**: Página web de sauri que muestra el contenido de una Nota seleccionada, incluyendo el Espacio_De_Resumen y el Panel_De_Transcripcion.
- **Espacio_De_Resumen**: Región estructural reservada en la Vista_De_Detalle destinada al resumen con IA de un módulo posterior, sin lógica de generación en este módulo.
- **Panel_De_Transcripcion**: Región de la Vista_De_Detalle que presenta la Transcripcion con identificación de hablantes como una secuencia de Intervenciones.
- **Intervencion**: Unidad visual del Panel_De_Transcripcion que representa un Turno_De_Habla con su Asignacion_De_Hablante, mostrando la Etiqueta_De_Hablante, el Avatar_De_Hablante, la marca de tiempo y el texto.
- **Avatar_De_Hablante**: Indicador visual de un Hablante compuesto por sus iniciales derivadas de la Etiqueta_De_Hablante y un color de fondo asignado de forma determinista por Hablante.
- **Marca_De_Tiempo_Formateada**: Representación legible de una marca de tiempo en milisegundos relativa al inicio de la Grabacion_De_Audio, con formato "MM:SS" cuando es menor a una hora y "HH:MM:SS" en caso contrario.
- **Buscador_De_Transcripcion**: Control de texto de la Vista_De_Detalle que localiza y resalta coincidencias dentro del texto de las Intervenciones del Panel_De_Transcripcion.
- **Vista_Tiempo_De_Habla**: Vista de la Vista_De_Detalle, denominada "Speaker Time", que muestra el tiempo total de habla por Hablante.
- **Tiempo_De_Habla**: Suma, para un Hablante, de la duración (`fin_ms` menos `inicio_ms`) de los Turnos_De_Habla atribuidos a ese Hablante mediante sus Asignaciones_De_Hablante.
- **Sistema_De_Diseno**: Conjunto de tokens de diseño (color, tipografía, espaciado, radios y elevaciones) y componentes reutilizables aplicados de forma consistente al Side_Panel y a la Vista_De_Detalle.
- **Estado_De_Vista**: Estado de presentación de una región de datos. Valores: "cargando", "con_datos", "vacio", "error".
- **Cliente_De_API**: Componente de la Extension_Sauri y de la Vista_De_Detalle que realiza solicitudes autenticadas a la API del backend de sauri.
- **Servicio_De_Autenticacion**: Componente de sauri que valida las credenciales del Usuario_Comercial y emite la Sesion_De_Usuario.
- **Sesion_De_Usuario**: Credencial vigente (token) que autoriza al Usuario_Comercial a consumir la API de sauri desde la Extension_Sauri y la Vista_De_Detalle.
- **Reunion**: Registro que representa una sesión de Google Meet con su Estado_De_Proceso. Definido por el Milestone 1.
- **Estado_De_Proceso**: Estado del ciclo de vida de la Reunion. Valores: "en_cola", "uniendose", "grabando", "transcribiendo", "completado", "fallido". Gestionado por los Milestones 1 y 2.
- **Grabacion_De_Sesion**: Contenedor de la grabación de una Reunion, con `audio_ref` y `duracion_segundos`. Definido por el Milestone 1.
- **Grabacion_De_Audio**: Pista de audio referenciada por `audio_ref`, base temporal de las marcas de tiempo. Definida por el Milestone 1.
- **Transcripcion**: Resultado del Milestone 2 asociado 1:1 a una Reunion, compuesto por Turnos_De_Habla. Insumo de este módulo.
- **Turno_De_Habla**: Segmento temporal de texto de una Transcripcion, con `texto`, `inicio_ms`, `fin_ms` y `orden`. Producido por el Milestone 2 sin identidad de hablante.
- **Diarizacion**: Resultado del Milestone 3 asociado 1:1 a una Reunion y a su Transcripcion, que agrupa los Hablantes y las Asignaciones_De_Hablante. Insumo de este módulo.
- **Hablante**: Hablante anónimo distinto detectado en una Diarizacion, con su Etiqueta_De_Hablante y un `orden`, sin identidad nominal. Definido por el Milestone 3.
- **Etiqueta_De_Hablante**: Etiqueta anónima legible asignada a un Hablante con el formato "Hablante N", donde N es un entero positivo consecutivo. Definida por el Milestone 3.
- **Asignacion_De_Hablante**: Vínculo que atribuye exactamente un Turno_De_Habla a exactamente un Hablante. Definida por el Milestone 3.

## Requirements

### Requirement 1: Apertura del Side Panel de la extensión

**User Story:** Como Usuario_Comercial, quiero abrir sauri como un panel lateral persistente en Chrome, para que la captura y el historial permanezcan visibles mientras trabajo en otras pestañas.

#### Acceptance Criteria

1. WHEN el Usuario_Comercial activa el icono de acción de la Extension_Sauri, THE Extension_Sauri SHALL abrir el Side_Panel mediante la API `chrome.sidePanel` en un máximo de 2 segundos.
2. THE Extension_Sauri SHALL declarar el permiso "sidePanel" en su manifiesto Manifest V3.
3. WHILE el Side_Panel está abierto, THE Side_Panel SHALL permanecer visible al cambiar entre pestañas del navegador y conservar el Estado_De_Captura en curso sin reiniciar la grabación.
4. WHEN el Side_Panel se renderiza, THE Side_Panel SHALL mostrar el Encabezado_Panel, los Controles_De_Captura y la Lista_De_Notas.
5. WHILE el ancho disponible del Side_Panel está entre 320 y 600 píxeles inclusive, THE Side_Panel SHALL presentar el Encabezado_Panel, los Controles_De_Captura y la Lista_De_Notas sin recorte horizontal de su contenido.
6. WHILE el ancho disponible del Side_Panel es menor a 320 píxeles, THE Side_Panel SHALL habilitar el desplazamiento horizontal para evitar la pérdida de contenido de los Controles_De_Captura y de la Lista_De_Notas.
7. IF la apertura del Side_Panel mediante `chrome.sidePanel` falla, THEN THE Extension_Sauri SHALL presentar una indicación de error y ofrecer una acción para reintentar la apertura.

### Requirement 2: Encabezado y acción de nueva nota

**User Story:** Como Usuario_Comercial, quiero un encabezado con una acción destacada para crear una nota, para que pueda iniciar una nueva grabación de inmediato.

#### Acceptance Criteria

1. THE Encabezado_Panel SHALL mostrar el título "REC Notas".
2. THE Encabezado_Panel SHALL mostrar el Boton_Nueva_Nota etiquetado "+ Nueva nota REC".
3. THE Encabezado_Panel SHALL presentar el Boton_Nueva_Nota aplicando el estilo de acción primaria del Sistema_De_Diseno.
4. WHILE el Estado_De_Captura es "inactiva", WHEN el Usuario_Comercial activa el Boton_Nueva_Nota, THE Side_Panel SHALL iniciar el flujo de una nueva grabación y establecer el Estado_De_Captura en "grabando".
5. WHILE el Estado_De_Captura es "grabando" o "deteniendo", THE Side_Panel SHALL deshabilitar el Boton_Nueva_Nota para impedir el inicio de una segunda grabación simultánea.
6. IF el Usuario_Comercial activa el Boton_Nueva_Nota y el inicio de la nueva grabación falla, THEN THE Side_Panel SHALL conservar el Estado_De_Captura en "inactiva" y presentar un mensaje de error que indique que la grabación no pudo iniciarse.

### Requirement 3: Controles de captura

**User Story:** Como Usuario_Comercial, quiero seleccionar la fuente de audio y el micrófono y activar la captura desde el panel, para que pueda controlar la grabación sin salir de la interfaz.

#### Acceptance Criteria

1. THE Controles_De_Captura SHALL mostrar el Selector_De_Fuente_De_Audio, el Toggle_De_Captura, el Selector_De_Microfono y el Boton_De_Ajustes.
2. THE Selector_De_Fuente_De_Audio SHALL ofrecer al menos la opción "Pantalla + audio" como fuente de captura.
3. WHILE el Estado_De_Captura es "inactiva", WHEN el Usuario_Comercial activa el Toggle_De_Captura, THE Side_Panel SHALL iniciar la captura usando la fuente seleccionada en el Selector_De_Fuente_De_Audio y el dispositivo seleccionado en el Selector_De_Microfono, y establecer el Estado_De_Captura en "grabando".
4. WHILE el Estado_De_Captura es "grabando", WHEN el Usuario_Comercial activa el Toggle_De_Captura, THE Side_Panel SHALL detener la captura en curso y establecer el Estado_De_Captura en "deteniendo".
5. WHILE el Estado_De_Captura es "deteniendo", WHEN la captura en curso finaliza su detención, THE Side_Panel SHALL establecer el Estado_De_Captura en "inactiva".
6. WHEN el Usuario_Comercial abre el Selector_De_Microfono, THE Selector_De_Microfono SHALL listar los dispositivos de micrófono de entrada disponibles para el navegador.
7. IF no existe ningún dispositivo de micrófono de entrada disponible, THEN THE Selector_De_Microfono SHALL presentar un estado vacío que indique la ausencia de micrófonos sin bloquear el resto de los Controles_De_Captura.
8. WHEN el Usuario_Comercial activa el Boton_De_Ajustes, THE Side_Panel SHALL abrir la Vista_De_Ajustes de la Extension_Sauri.
9. WHILE el Estado_De_Captura es "grabando", THE Side_Panel SHALL mostrar un indicador de grabación activa y el tiempo transcurrido de la grabación en curso en formato "MM:SS", actualizado al menos cada segundo y acumulando los minutos transcurridos.
10. IF el inicio de la captura falla, THEN THE Side_Panel SHALL conservar el Estado_De_Captura en "inactiva" y presentar una indicación de error que señale que la captura no pudo iniciarse.

### Requirement 4: Historial de notas

**User Story:** Como Usuario_Comercial, quiero ver mis grabaciones previas como tarjetas con título y fecha, para que pueda reconocer y elegir una nota del historial.

#### Acceptance Criteria

1. WHEN el Side_Panel carga la Lista_De_Notas, THE Cliente_De_API SHALL solicitar al backend el historial de Notas correspondiente exclusivamente al Usuario_Comercial autenticado.
2. THE Lista_De_Notas SHALL presentar exactamente una Tarjeta_De_Nota por cada Nota del historial recuperado.
3. THE Tarjeta_De_Nota SHALL mostrar el título de la Nota y su fecha y hora de creación.
4. IF una Nota del historial no tiene título, THEN THE Tarjeta_De_Nota SHALL mostrar un título de marcador de posición en lugar de un título vacío.
5. THE Tarjeta_De_Nota SHALL presentar la fecha y hora de creación de la Nota con el formato "D/M, HH:MM", donde D es el día del mes (1 a 31), M es el mes (1 a 12), HH son las horas en formato de 24 horas (00 a 23) con dos dígitos y MM son los minutos (00 a 59) con dos dígitos.
6. THE Lista_De_Notas SHALL ordenar las Tarjetas_De_Nota de la más reciente a la más antigua según la fecha y hora de creación de cada Nota y, ante fechas de creación idénticas, SHALL aplicar un orden determinista y repetible.
7. WHILE el Cliente_De_API espera la respuesta del historial, THE Lista_De_Notas SHALL presentar el Estado_De_Vista "cargando".
8. IF el historial recuperado no contiene ninguna Nota, THEN THE Lista_De_Notas SHALL presentar el Estado_De_Vista "vacio" con un mensaje que invite a crear la primera nota.
9. IF la solicitud del historial no obtiene respuesta dentro de 10 segundos o falla, THEN THE Lista_De_Notas SHALL presentar el Estado_De_Vista "error" con una acción para reintentar la carga, conservando las Tarjetas_De_Nota previamente mostradas si existían.

### Requirement 5: Búsqueda y filtro del historial

**User Story:** Como Usuario_Comercial, quiero buscar y filtrar mis notas, para que pueda encontrar una grabación específica en un historial extenso.

#### Acceptance Criteria

1. WHEN el Usuario_Comercial deja de escribir durante 300 milisegundos en el Buscador_De_Notas, THE Lista_De_Notas SHALL mostrar únicamente las Tarjetas_De_Nota cuyo título contenga el texto ingresado, ignorando los espacios iniciales y finales y evaluado sin distinción entre mayúsculas y minúsculas.
2. WHEN el Usuario_Comercial selecciona un criterio en el Filtro_De_Notas (rango de fecha o Estado_De_Proceso), THE Lista_De_Notas SHALL mostrar únicamente las Tarjetas_De_Nota que satisfagan el criterio seleccionado.
3. WHILE el Buscador_De_Notas contiene texto y el Filtro_De_Notas tiene un criterio activo, THE Lista_De_Notas SHALL mostrar únicamente las Tarjetas_De_Nota que satisfagan simultáneamente la búsqueda de título y el criterio del filtro.
4. WHEN el Usuario_Comercial borra el texto del Buscador_De_Notas y restablece el Filtro_De_Notas, THE Lista_De_Notas SHALL mostrar de nuevo todas las Tarjetas_De_Nota del historial recuperado.
5. IF la combinación de búsqueda y filtro no produce ninguna Tarjeta_De_Nota coincidente, THEN THE Lista_De_Notas SHALL presentar el Estado_De_Vista "vacio" con un mensaje de ausencia de resultados, conservando el texto de búsqueda y el criterio de filtro aplicados.
6. IF el contenido del Buscador_De_Notas está vacío o se compone únicamente de espacios, THEN THE Lista_De_Notas SHALL tratar la búsqueda de título como inactiva y no excluir Tarjetas_De_Nota por coincidencia de texto.
7. THE Buscador_De_Notas SHALL limitar el texto de búsqueda ingresado a un máximo de 100 caracteres.

### Requirement 6: Navegación a la vista de detalle

**User Story:** Como Usuario_Comercial, quiero abrir una grabación del historial, para que pueda ver su contenido en una página de detalle.

#### Acceptance Criteria

1. WHEN el Usuario_Comercial selecciona una Tarjeta_De_Nota de la Lista_De_Notas, THE Side_Panel SHALL abrir la Vista_De_Detalle de la Nota correspondiente en una pestaña del navegador.
2. WHEN el Side_Panel abre la Vista_De_Detalle, THE Side_Panel SHALL transmitir el identificador de la Reunion asociada a la Nota seleccionada a la Vista_De_Detalle.
3. WHEN la Vista_De_Detalle se carga con un identificador de Reunion, THE Cliente_De_API SHALL solicitar al backend la Transcripcion y la Diarizacion de esa Reunion.
4. WHILE el Cliente_De_API espera la respuesta de la Transcripcion y la Diarizacion, THE Panel_De_Transcripcion SHALL presentar el Estado_De_Vista "cargando".
5. IF la Vista_De_Detalle se carga sin un identificador de Reunion válido, THEN THE Vista_De_Detalle SHALL presentar el Estado_De_Vista "error" indicando que la nota solicitada no existe.
6. IF la solicitud de la Transcripcion y la Diarizacion falla, THEN THE Vista_De_Detalle SHALL presentar el Estado_De_Vista "error" con una acción para reintentar la carga, conservando el identificador de Reunion recibido.

### Requirement 7: Estructura de la vista de detalle y espacio de resumen reservado

**User Story:** Como Usuario_Comercial, quiero que la vista de detalle tenga un lugar previsto para el resumen y la transcripción, para que la información esté organizada cuando el resumen con IA se incorpore más adelante.

#### Acceptance Criteria

1. WHEN la Vista_De_Detalle se renderiza, THE Vista_De_Detalle SHALL presentar simultáneamente el título de la Nota, el Espacio_De_Resumen y el Panel_De_Transcripcion.
2. THE Vista_De_Detalle SHALL reservar el Espacio_De_Resumen como una región estructural sin invocar ninguna generación de resumen con IA.
3. WHILE la generación de resumen con IA no esté habilitada, THE Espacio_De_Resumen SHALL mostrar un indicador estático y no interactivo de "resumen disponible próximamente", sin desencadenar ninguna acción.
4. THE Vista_De_Detalle SHALL aplicar el Sistema_De_Diseno de forma consistente con el Side_Panel en color, tipografía y espaciado.
5. IF la Nota no tiene título, THEN THE Vista_De_Detalle SHALL mostrar un título de marcador de posición en lugar de un título vacío.
6. IF la Reunion no tiene Transcripcion disponible, THEN THE Panel_De_Transcripcion SHALL presentar el Estado_De_Vista "vacio" indicando que la transcripción no está disponible para esa Nota.

### Requirement 8: Transcripción con identificación de hablantes

**User Story:** Como Usuario_Comercial, quiero ver la transcripción con cada intervención atribuida a un hablante, para que pueda entender quién dijo qué durante la reunión.

#### Acceptance Criteria

1. WHEN la Vista_De_Detalle recibe la Transcripcion y la Diarizacion de una Reunion, THE Panel_De_Transcripcion SHALL presentar una Intervencion por cada Turno_De_Habla de la Transcripcion.
2. THE Panel_De_Transcripcion SHALL ordenar las Intervenciones de forma ascendente por la marca de tiempo de inicio `inicio_ms` del Turno_De_Habla y, ante valores de `inicio_ms` idénticos, de forma ascendente por el `orden` del Turno_De_Habla.
3. THE Intervencion SHALL mostrar la Etiqueta_De_Hablante del Hablante atribuido al Turno_De_Habla por su Asignacion_De_Hablante, el Avatar_De_Hablante, la Marca_De_Tiempo_Formateada del `inicio_ms` y el texto del Turno_De_Habla.
4. THE Avatar_De_Hablante SHALL mostrar un máximo de dos caracteres de iniciales derivados de la Etiqueta_De_Hablante y un color de fondo asignado de forma determinista a partir del `orden` del Hablante, reutilizando colores de forma cíclica cuando hay más Hablantes que colores disponibles, de modo que un mismo Hablante presente siempre el mismo color dentro de la misma Vista_De_Detalle.
5. THE Panel_De_Transcripcion SHALL conservar sin modificar el texto de cada Turno_De_Habla recibido de la Transcripcion.
6. WHILE el contenido de las Intervenciones excede la altura visible del Panel_De_Transcripcion, THE Panel_De_Transcripcion SHALL habilitar el desplazamiento vertical sobre la secuencia de Intervenciones.
7. IF la Reunion tiene Transcripcion pero no tiene Diarizacion disponible, THEN THE Panel_De_Transcripcion SHALL presentar cada Intervencion con el texto y la Marca_De_Tiempo_Formateada del Turno_De_Habla y una Etiqueta_De_Hablante de marcador de posición que indique hablante no identificado.
8. IF la Reunion no tiene Transcripcion disponible, THEN THE Panel_De_Transcripcion SHALL presentar el Estado_De_Vista "vacio" indicando que la transcripción no está disponible para esa Nota.
9. WHILE el Cliente_De_API espera la respuesta de la Transcripcion o de la Diarizacion, THE Panel_De_Transcripcion SHALL presentar el Estado_De_Vista "cargando".
10. IF la solicitud de la Transcripcion o de la Diarizacion falla, THEN THE Panel_De_Transcripcion SHALL presentar el Estado_De_Vista "error" con una acción para reintentar la carga.

### Requirement 9: Búsqueda dentro de la transcripción

**User Story:** Como Usuario_Comercial, quiero buscar texto dentro de la transcripción, para que pueda localizar rápidamente un fragmento de la reunión.

#### Acceptance Criteria

1. WHEN el Usuario_Comercial modifica el contenido del Buscador_De_Transcripcion a un texto con al menos un carácter distinto de espacio, THE Panel_De_Transcripcion SHALL resaltar, en un máximo de 500 milisegundos, las coincidencias del texto ingresado dentro del texto de las Intervenciones, evaluadas sin distinción entre mayúsculas y minúsculas.
2. WHEN el Buscador_De_Transcripcion produce al menos una coincidencia, THE Panel_De_Transcripcion SHALL desplazar la vista hasta la primera Intervencion con coincidencia en orden ascendente por `inicio_ms`, conservando el resaltado del resto de coincidencias.
3. WHEN el contenido del Buscador_De_Transcripcion queda vacío o compuesto únicamente de espacios, THE Panel_De_Transcripcion SHALL eliminar todos los resaltados y conservar el orden original de las Intervenciones.
4. IF el texto ingresado en el Buscador_De_Transcripcion no coincide con ninguna Intervencion, THEN THE Buscador_De_Transcripcion SHALL indicar la ausencia de coincidencias sin alterar las Intervenciones mostradas.
5. THE Buscador_De_Transcripcion SHALL limitar el texto de búsqueda ingresado a un máximo de 200 caracteres.

### Requirement 10: Vista de tiempo de habla (Speaker Time)

**User Story:** Como Usuario_Comercial, quiero ver cuánto habló cada participante, para que pueda valorar la participación durante la reunión.

#### Acceptance Criteria

1. WHEN el Usuario_Comercial abre la Vista_Tiempo_De_Habla, THE Vista_Tiempo_De_Habla SHALL presentar el Estado_De_Vista "con_datos" con una entrada por cada Hablante de la Diarizacion, incluidos los Hablantes con Tiempo_De_Habla igual a 0, mostrando su Etiqueta_De_Hablante, su Avatar_De_Hablante y su Tiempo_De_Habla.
2. THE Vista_Tiempo_De_Habla SHALL calcular el Tiempo_De_Habla de cada Hablante como la suma de la duración (`fin_ms` menos `inicio_ms`) de los Turnos_De_Habla atribuidos a ese Hablante mediante sus Asignaciones_De_Hablante.
3. THE Vista_Tiempo_De_Habla SHALL presentar el Tiempo_De_Habla de cada Hablante como una Marca_De_Tiempo_Formateada.
4. THE Vista_Tiempo_De_Habla SHALL ordenar las entradas de mayor a menor Tiempo_De_Habla y, ante valores de Tiempo_De_Habla idénticos, de forma ascendente por el `orden` del Hablante.
5. IF la Reunion no tiene Diarizacion disponible, THEN THE Vista_Tiempo_De_Habla SHALL presentar el Estado_De_Vista "vacio" indicando que el tiempo de habla no está disponible para esa Nota.
6. WHILE el Cliente_De_API espera la respuesta de la Diarizacion, THE Vista_Tiempo_De_Habla SHALL presentar el Estado_De_Vista "cargando".
7. IF la solicitud de la Diarizacion falla, THEN THE Vista_Tiempo_De_Habla SHALL presentar el Estado_De_Vista "error" con una acción para reintentar la carga.

### Requirement 11: Formato de marcas de tiempo

**User Story:** Como Usuario_Comercial, quiero ver marcas de tiempo legibles, para que pueda ubicar cada intervención en la duración de la reunión.

#### Acceptance Criteria

1. WHEN el Panel_De_Transcripcion o la Vista_Tiempo_De_Habla presenta una marca de tiempo en milisegundos mayor o igual a 0 y menor a 3600000 milisegundos, THE Marca_De_Tiempo_Formateada SHALL expresarse con el formato "MM:SS" usando dos dígitos para los minutos en el rango 00 a 59 y dos dígitos para los segundos en el rango 00 a 59.
2. WHEN el Panel_De_Transcripcion o la Vista_Tiempo_De_Habla presenta una marca de tiempo en milisegundos mayor o igual a 3600000 milisegundos, THE Marca_De_Tiempo_Formateada SHALL expresarse con el formato "HH:MM:SS" usando al menos dos dígitos para las horas rellenados con ceros a la izquierda, dos dígitos para los minutos en el rango 00 a 59 y dos dígitos para los segundos en el rango 00 a 59.
3. THE Marca_De_Tiempo_Formateada SHALL truncar los milisegundos a segundos completos descartando la fracción de segundo.
4. IF la marca de tiempo en milisegundos es 0, THEN THE Marca_De_Tiempo_Formateada SHALL expresarse como "00:00".
5. IF la marca de tiempo en milisegundos es negativa o no está disponible, THEN THE Marca_De_Tiempo_Formateada SHALL expresarse como un marcador de posición que indique que la marca de tiempo no está disponible, sin presentar un valor numérico de tiempo.

### Requirement 12: Sistema de diseño consistente y estados de interfaz

**User Story:** Como Usuario_Comercial, quiero una interfaz coherente y con retroalimentación clara en cada situación, para que la experiencia sea predecible y de alta calidad.

#### Acceptance Criteria

1. THE Sistema_De_Diseno SHALL definir tokens de color, tipografía, espaciado, radios y elevaciones aplicados al Side_Panel y a la Vista_De_Detalle.
2. THE Side_Panel y la Vista_De_Detalle SHALL renderizar los componentes compartidos (botones, tarjetas, campos de búsqueda y avatares) a partir de los tokens del Sistema_De_Diseno.
3. WHERE una región presenta datos remotos, THE región SHALL presentar en todo momento exactamente uno de los Estados_De_Vista ("cargando", "con_datos", "vacio", "error"), siendo los cuatro estados visualmente distinguibles entre sí.
4. WHEN un control interactivo recibe foco mediante el teclado, THE control SHALL exponer un indicador de foco visible, derivado de los tokens del Sistema_De_Diseno, con una relación de contraste de al menos 3:1 respecto a los colores adyacentes.
5. WHILE una región que presenta datos remotos tiene una solicitud en curso sin respuesta, THE región SHALL presentar el Estado_De_Vista "cargando".
6. WHEN la solicitud de datos remotos de una región se completa con éxito, THE región SHALL presentar el Estado_De_Vista "con_datos" si la respuesta contiene al menos un elemento, o el Estado_De_Vista "vacio" si la respuesta no contiene elementos.
7. IF la solicitud de datos remotos de una región falla, THEN THE región SHALL presentar el Estado_De_Vista "error", indicar al Usuario_Comercial que la carga no fue exitosa y conservar la posibilidad de reintentar la solicitud sin recargar la región completa.

### Requirement 13: Autenticación de la extensión

**User Story:** Como responsable de seguridad de Summan, quiero que la extensión autentique al usuario contra el backend, para que el acceso a las grabaciones y transcripciones deje de depender del bypass de desarrollo.

#### Acceptance Criteria

1. WHILE el Usuario_Comercial tiene una Sesion_De_Usuario vigente, WHEN el Cliente_De_API realiza una solicitud al backend de sauri, THE Cliente_De_API SHALL incluir esa Sesion_De_Usuario en la solicitud.
2. IF el Usuario_Comercial no tiene una Sesion_De_Usuario vigente al abrir el Side_Panel, THEN THE Side_Panel SHALL presentar el flujo de autenticación contra el Servicio_De_Autenticacion y bloquear el acceso a la Lista_De_Notas hasta que la autenticación se complete con éxito.
3. WHEN el Servicio_De_Autenticacion valida las credenciales del Usuario_Comercial, THE Extension_Sauri SHALL almacenar la Sesion_De_Usuario resultante en el almacenamiento de la extensión para solicitudes posteriores.
4. IF el backend responde que la Sesion_De_Usuario es inválida o ha expirado, THEN THE Side_Panel SHALL descartar la Sesion_De_Usuario almacenada, indicar al Usuario_Comercial que la sesión expiró y volver a presentar el flujo de autenticación.
5. THE Extension_Sauri SHALL transmitir la Sesion_De_Usuario al backend únicamente a través de un canal cifrado en tránsito.
6. IF el Servicio_De_Autenticacion rechaza las credenciales del Usuario_Comercial 5 veces consecutivas, THEN THE Side_Panel SHALL bloquear nuevos intentos de autenticación durante al menos 60 segundos e indicar el bloqueo al Usuario_Comercial.
7. IF el Servicio_De_Autenticacion no responde dentro de 30 segundos, THEN THE Side_Panel SHALL indicar la indisponibilidad del servicio y conservar al Usuario_Comercial sin Sesion_De_Usuario almacenada.

### Requirement 14: Consumo de datos de transcripción y diarización

**User Story:** Como responsable técnico de sauri, quiero que el módulo consuma los datos ya producidos por los módulos previos, para que la interfaz no recalcule transcripción ni diarización.

#### Acceptance Criteria

1. THE Cliente_De_API SHALL obtener la Transcripcion, los Turnos_De_Habla y la Diarizacion de una Reunion exclusivamente mediante solicitudes a la API del backend de sauri, sin derivar estos datos de ninguna otra fuente.
2. THE Side_Panel y la Vista_De_Detalle SHALL presentar la Transcripcion, los Turnos_De_Habla, la Diarizacion y las Asignaciones_De_Hablante tal como los entrega la API del backend, sin generarlos, modificarlos ni recalcularlos.
3. WHILE el Cliente_De_API espera la respuesta de la solicitud de la Transcripcion o de la Diarizacion, THE Vista_De_Detalle SHALL presentar el Estado_De_Vista "cargando" en la región de datos correspondiente: el Panel_De_Transcripcion para la Transcripcion y la Vista_Tiempo_De_Habla para la Diarizacion.
4. IF la solicitud de la Transcripcion o de la Diarizacion falla por error de red, por respuesta de error del backend o por ausencia de respuesta dentro de 10 segundos, THEN THE Vista_De_Detalle SHALL presentar el Estado_De_Vista "error" en la región de datos correspondiente, con una indicación del fallo y una acción para reintentar la carga.
5. WHEN el Usuario_Comercial activa la acción para reintentar la carga, THE Cliente_De_API SHALL emitir nuevamente la solicitud de la Transcripcion o de la Diarizacion correspondiente y THE Vista_De_Detalle SHALL presentar el Estado_De_Vista "cargando" en esa región de datos.
