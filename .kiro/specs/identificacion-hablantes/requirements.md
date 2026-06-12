# Requirements Document

## Introduction

Este documento define los requerimientos del tercer módulo de **sauri**, la plataforma interna de inteligencia de reuniones comerciales de Summan. El módulo se denomina **Identificación de hablantes (diarización)** y corresponde al Milestone 3 de la hoja de ruta del producto.

El Milestone 1 (captura de audio+video desde Google Meet) y el Milestone 2 (Transcripción/ASR) están completos y fusionados. El Milestone 2 produce, a partir de la Grabacion_De_Audio, una Transcripcion asociada a la Reunion compuesta por Turnos_De_Habla (cada uno con `texto`, `inicio_ms`, `fin_ms` y `orden`), explícitamente **sin identidad nominal**, y deja la Reunion en estado "completado".

El propósito de este módulo es agregar la **diarización**: determinar "quién dijo qué" segmentando la Transcripcion ya producida por hablante. El módulo consume una Grabacion_De_Audio y la Transcripcion existente de una Reunion, ejecuta un Motor_De_Diarizacion intercambiable (un Proveedor_Local basado en un motor de diarización propio o un Proveedor_Nube externo) que detecta los segmentos temporales atribuidos a cada hablante anónimo, etiqueta a los hablantes de forma anónima y estable, asigna cada Turno_De_Habla al Hablante que más habló durante ese turno, y persiste la Diarizacion asociada a la Reunion. El módulo cubre la selección del motor por configuración, la detección de segmentos de hablante con marcas de tiempo, el etiquetado anónimo y ordenado de hablantes, la asignación de turnos a hablantes por solape temporal, la persistencia transaccional, el ciclo de vida del Estado_De_Diarizacion, y el comportamiento de error y reintentos.

Este módulo construye sobre las abstracciones ya existentes en `backend/app/infra/` (Cola_De_Trabajos en RabbitMQ, Almacen_De_Objetos en MinIO/S3, modelos ORM de Reunion, Transcripcion y Turno_De_Habla) y reutiliza el patrón de proveedor intercambiable, fábrica por configuración y worker encolado introducido por el módulo de Transcripción (`backend/app/transcripcion/`). La diarización integra la Transcripcion ya persistida del Milestone 2 sin reemplazarla ni modificar sus Turnos_De_Habla.

**Decisión de integración con la gestión de reuniones:** el módulo de Transcripción deja la Reunion en el estado terminal "completado" del Estado_De_Proceso. Este módulo **no modifica** el Estado_De_Proceso de la Reunion; rastrea el avance y resultado de la diarización mediante un Estado_De_Diarizacion propio de la entidad Diarizacion. La Diarizacion se asocia a la Reunion y a su Transcripcion, de modo que los módulos posteriores (Notas e inteligencia, Analítica comercial) consuman la atribución de hablantes cuando el Estado_De_Diarizacion sea "completada".

Quedan **explícitamente fuera de alcance** de este módulo: la identificación nominal de hablantes (asociar un Hablante anónimo con la identidad real de una persona), la generación de notas o resúmenes con IA, la integración con el CRM, la búsqueda y la analítica comercial. La captura pertenece al Milestone 1 y la transcripción al Milestone 2; ambas se asumen aquí como insumo.

## Glossary

- **sauri**: Plataforma interna de Summan para captura, transcripción e inteligencia de reuniones comerciales.
- **Modulo_De_Diarizacion**: Conjunto de componentes de sauri responsables de la identificación de hablantes sobre una Transcripcion existente.
- **Worker_De_Diarizacion**: Componente de sauri que se suscribe al tema "diarizar" de la Cola_De_Trabajos, ejecuta la diarización y persiste el resultado.
- **Motor_De_Diarizacion**: Componente abstracto que analiza una Grabacion_De_Audio y produce los segmentos temporales atribuidos a cada hablante. Define la interfaz común `diarizar(audio_ref, opciones)` y `capacidades()`.
- **Proveedor_De_Diarizacion**: Implementación concreta del Motor_De_Diarizacion seleccionable por configuración. Sus variantes son el Proveedor_Local y el Proveedor_Nube.
- **Proveedor_Local**: Implementación del Motor_De_Diarizacion que procesa el audio mediante el Servicio_De_Diarizacion_Local sin enviarlo a servicios externos.
- **Proveedor_Nube**: Implementación del Motor_De_Diarizacion que envía el audio a un servicio de diarización externo a través de un canal cifrado.
- **Fabrica_De_Diarizacion**: Función `crear_motor_diarizacion` que construye el Proveedor_De_Diarizacion activo según la variable de configuración DIARIZATION_PROVIDER.
- **Servicio_De_Diarizacion_Local**: Servicio HTTP propio (contenedor `diar-engine`) que expone `POST /diarize`.
- **Cola_De_Trabajos**: Abstracción de mensajería con entrega al-menos-una-vez, reintentos y dead-letter, provista en `backend/app/infra/queue.py`.
- **Almacen_De_Objetos**: Abstracción de almacenamiento de objetos (MinIO/S3) donde reside la Grabacion_De_Audio.
- **Repositorio_De_Diarizacion**: Componente que persiste la Diarizacion junto con sus Hablantes y Asignaciones_De_Hablante en una única transacción.
- **Mensaje_De_Diarizacion**: Mensaje encolado en el tema "diarizar" con la forma `{"reunion_id": str}`.
- **Reunion**: Registro que representa una sesión de Google Meet, con su Estado_De_Proceso. Definido por el Milestone 1.
- **Estado_De_Proceso**: Estado del ciclo de vida de la Reunion gestionado por los Milestones 1 y 2. Valores: "en_cola", "uniendose", "grabando", "transcribiendo", "completado", "fallido".
- **Grabacion_De_Sesion**: Contenedor de la grabación de una Reunion, asociado 1:1, que incluye `audio_ref` y `duracion_segundos`.
- **Grabacion_De_Audio**: Pista de audio referenciada por `audio_ref` en el Almacen_De_Objetos, a partir de la cual se ejecuta la diarización.
- **Duracion_De_Grabacion**: Duración total de la Grabacion_De_Audio expresada en milisegundos, equivalente a `Grabacion_De_Sesion.duracion_segundos` multiplicado por 1000.
- **Transcripcion**: Resultado en texto del Milestone 2, asociado 1:1 a una Reunion, compuesto por Turnos_De_Habla. Insumo de este módulo.
- **Turno_De_Habla**: Segmento temporal de texto dentro de una Transcripcion, con `texto`, `inicio_ms`, `fin_ms` y `orden`. Producido por el Milestone 2 sin identidad de hablante.
- **Diarizacion**: Resultado del Modulo_De_Diarizacion asociado 1:1 a una Reunion y a su Transcripcion, que agrupa los Hablantes detectados, las Asignaciones_De_Hablante, el proveedor utilizado, el Estado_De_Diarizacion y la marca de creación.
- **Segmento_De_Hablante**: Unidad temporal producida por el Motor_De_Diarizacion con una Etiqueta_De_Hablante_Cruda, `inicio_ms` y `fin_ms`, que indica que un hablante estuvo activo en ese intervalo.
- **Resultado_De_Diarizacion**: Objeto producido por el Motor_De_Diarizacion que contiene la lista de Segmentos_De_Hablante y el número de hablantes detectados.
- **Etiqueta_De_Hablante_Cruda**: Identificador opaco de hablante tal como lo reporta el Motor_De_Diarizacion (por ejemplo, "SPEAKER_00"), sin significado de orden ni identidad nominal.
- **Hablante**: Hablante anónimo distinto detectado en una Diarizacion, con una Etiqueta_De_Hablante asignada por sauri y un `orden`, sin identidad nominal.
- **Etiqueta_De_Hablante**: Etiqueta anónima legible asignada por sauri a un Hablante con el formato "Hablante N", donde N es un entero positivo consecutivo.
- **Asignacion_De_Hablante**: Vínculo que atribuye exactamente un Turno_De_Habla a exactamente un Hablante.
- **Solape_Temporal**: Cantidad de milisegundos en que el intervalo `[inicio_ms, fin_ms]` de un Turno_De_Habla coincide con el intervalo de un Segmento_De_Hablante.
- **Estado_De_Diarizacion**: Estado del ciclo de vida de la Diarizacion. Valores: "pendiente", "en_proceso", "completada", "fallida".
- **Causa_De_Fallo_Diarizacion**: Motivo registrado cuando el Estado_De_Diarizacion es "fallida". Valor relevante para este módulo: "fallo_del_motor".
- **Capacidades_De_Diarizacion**: Declaración del Proveedor_De_Diarizacion sobre si es local y otros metadatos del motor.

## Requirements

### Requirement 1: Consumo de solicitudes de diarización encoladas

**User Story:** Como responsable técnico de sauri, quiero que el Worker_De_Diarizacion consuma las solicitudes de diarización encoladas, para que cada Transcripcion disponible se procese automáticamente sin intervención manual.

#### Acceptance Criteria

1. WHEN el Worker_De_Diarizacion inicia su ejecución, THE Worker_De_Diarizacion SHALL suscribirse al tema "diarizar" de la Cola_De_Trabajos.
2. WHEN una Transcripcion asociada a una Reunion queda persistida y disponible, THE Modulo_De_Diarizacion SHALL encolar un Mensaje_De_Diarizacion que contenga el `reunion_id` en el tema "diarizar".
3. WHEN el Worker_De_Diarizacion recibe un Mensaje_De_Diarizacion del tema "diarizar", THE Worker_De_Diarizacion SHALL extraer del mensaje el identificador `reunion_id`.
4. IF un Mensaje_De_Diarizacion no contiene un `reunion_id` no vacío, THEN THE Worker_De_Diarizacion SHALL terminar el procesamiento del mensaje sin lanzar una excepción y sin persistir una Diarizacion.
5. IF un Mensaje_De_Diarizacion referencia un `reunion_id` que no corresponde a ninguna Reunion existente, THEN THE Worker_De_Diarizacion SHALL terminar el procesamiento del mensaje sin lanzar una excepción y sin persistir una Diarizacion.
6. IF un Mensaje_De_Diarizacion referencia una Reunion que no tiene una Transcripcion asociada, THEN THE Worker_De_Diarizacion SHALL terminar el procesamiento del mensaje sin lanzar una excepción y sin persistir una Diarizacion.
7. WHEN el Worker_De_Diarizacion completa el procesamiento de un Mensaje_De_Diarizacion sin lanzar una excepción, THE Cola_De_Trabajos SHALL confirmar el mensaje mediante ack.
8. IF el procesamiento de un Mensaje_De_Diarizacion lanza una excepción, THEN THE Cola_De_Trabajos SHALL rechazar el mensaje mediante nack sin reencolar de forma inmediata.
9. WHERE el dead-letter está configurado, IF el procesamiento de un Mensaje_De_Diarizacion lanza una excepción, THEN THE Cola_De_Trabajos SHALL derivar el mensaje al dead-letter.

### Requirement 2: Selección del Proveedor_De_Diarizacion por configuración

**User Story:** Como responsable técnico de sauri, quiero seleccionar el Proveedor_De_Diarizacion activo mediante configuración, para que pueda alternar entre procesamiento local y en la nube sin modificar el código del Worker_De_Diarizacion.

#### Acceptance Criteria

1. THE Fabrica_De_Diarizacion SHALL construir exactamente un Proveedor_De_Diarizacion activo a partir del valor de la variable de configuración DIARIZATION_PROVIDER, evaluado sin distinción entre mayúsculas y minúsculas y sin considerar los espacios al inicio o al final del valor.
2. WHERE la variable DIARIZATION_PROVIDER tiene el valor "local", THE Fabrica_De_Diarizacion SHALL construir un Proveedor_Local configurado con la URL definida en la variable DIARIZATION_LOCAL_URL.
3. WHERE la variable DIARIZATION_PROVIDER tiene el valor "cloud", THE Fabrica_De_Diarizacion SHALL construir un Proveedor_Nube.
4. WHERE la variable DIARIZATION_PROVIDER no está definida o contiene una cadena vacía, THE Fabrica_De_Diarizacion SHALL construir un Proveedor_Local configurado con la URL definida en la variable DIARIZATION_LOCAL_URL como valor por defecto.
5. IF la variable DIARIZATION_PROVIDER tiene un valor distinto de "local" y "cloud", THEN THE Fabrica_De_Diarizacion SHALL rechazar la construcción sin instanciar ningún Proveedor_De_Diarizacion y señalar un error de configuración que indique el valor inválido recibido.
6. IF se selecciona un Proveedor_Local y la variable DIARIZATION_LOCAL_URL no está definida o contiene una cadena vacía, THEN THE Fabrica_De_Diarizacion SHALL rechazar la construcción sin instanciar ningún Proveedor_De_Diarizacion y señalar un error de configuración que indique la ausencia de la URL local.
7. THE Worker_De_Diarizacion SHALL interactuar con el Proveedor_De_Diarizacion construido únicamente a través de la interfaz común del Motor_De_Diarizacion.

### Requirement 3: Procesamiento local sin envío externo

**User Story:** Como responsable de cumplimiento de Summan, quiero que el Proveedor_Local procese la Grabacion_De_Audio sin enviarla a servicios externos, para que los datos sensibles permanezcan dentro de la infraestructura propia de sauri.

#### Acceptance Criteria

1. WHEN el Proveedor_Local recibe una solicitud de diarización, THE Proveedor_Local SHALL enviar la referencia `audio_ref` al Servicio_De_Diarizacion_Local mediante una solicitud `POST /diarize` y esperar la respuesta durante un máximo de 600 segundos.
2. THE Proveedor_Local SHALL procesar la Grabacion_De_Audio sin enviarla a ningún servicio externo a la infraestructura de sauri.
3. WHEN el Servicio_De_Diarizacion_Local responde con éxito, THE Servicio_De_Diarizacion_Local SHALL devolver una estructura que contenga una lista de cero o más segmentos, donde cada segmento incluye `speaker`, `start_ms` y `end_ms`.
4. WHEN el Servicio_De_Diarizacion_Local responde con una estructura válida de segmentos, THE Proveedor_Local SHALL convertir cada segmento de la respuesta en un Segmento_De_Hablante con su Etiqueta_De_Hablante_Cruda, su `inicio_ms` y su `fin_ms`.
5. IF el Servicio_De_Diarizacion_Local responde con un código de estado HTTP de error, THEN THE Proveedor_Local SHALL señalar un fallo de diarización al Worker_De_Diarizacion sin producir Segmentos_De_Hablante parciales.
6. IF el Servicio_De_Diarizacion_Local no responde dentro de 600 segundos o no es alcanzable, THEN THE Proveedor_Local SHALL abortar el procesamiento y señalar un fallo de diarización al Worker_De_Diarizacion.
7. IF el Servicio_De_Diarizacion_Local responde sin la lista de segmentos esperada, THEN THE Proveedor_Local SHALL señalar un fallo de diarización al Worker_De_Diarizacion sin generar Segmentos_De_Hablante inválidos.

### Requirement 4: Procesamiento en la nube con canal cifrado

**User Story:** Como responsable de seguridad de Summan, quiero que el Proveedor_Nube transmita el audio por un canal cifrado, para que la información comercial no quede expuesta al usar un servicio de diarización externo.

#### Acceptance Criteria

1. WHEN el Proveedor_Nube transmite la Grabacion_De_Audio a un servicio de diarización externo, THE Proveedor_Nube SHALL usar un canal cifrado en tránsito mediante HTTPS.
2. IF el endpoint configurado en la variable DIARIZATION_CLOUD_ENDPOINT no usa el esquema HTTPS, THEN THE Proveedor_Nube SHALL rechazar la inicialización sin transmitir ninguna Grabacion_De_Audio y señalar un error de configuración que indique el esquema no soportado.
3. THE Proveedor_Nube SHALL autenticar la solicitud al servicio de diarización externo mediante la credencial definida en la variable DIARIZATION_CLOUD_API_KEY.
4. IF la variable DIARIZATION_CLOUD_API_KEY no está definida o está vacía al inicializar el Proveedor_Nube, THEN THE Proveedor_Nube SHALL rechazar la inicialización sin transmitir ninguna Grabacion_De_Audio y señalar un error de configuración que indique la ausencia de la credencial.
5. WHEN el servicio de diarización externo responde con segmentos de hablante, THE Proveedor_Nube SHALL convertir cada segmento en un Segmento_De_Hablante con su Etiqueta_De_Hablante_Cruda no vacía, su `inicio_ms` y su `fin_ms` como enteros no negativos donde `fin_ms` es mayor o igual a `inicio_ms`.
6. IF el servicio de diarización externo no responde dentro de 120 segundos, responde con un error o devuelve una respuesta sin segmentos válidos, THEN THE Proveedor_Nube SHALL abortar el procesamiento, conservar la Grabacion_De_Audio sin modificar y señalar un error de diarización que indique la falla del servicio externo.

### Requirement 5: Detección de segmentos de hablante con marcas de tiempo

**User Story:** Como Usuario_Comercial, quiero que la diarización detecte intervalos de tiempo atribuidos a cada hablante, para que se pueda determinar en qué momentos habló cada participante.

#### Acceptance Criteria

1. THE Resultado_De_Diarizacion SHALL contener una lista de Segmentos_De_Hablante ordenada de forma ascendente por su marca de tiempo de inicio `inicio_ms`.
2. THE Segmento_De_Hablante SHALL incluir una marca de tiempo de inicio `inicio_ms` y una marca de tiempo de fin `fin_ms`, ambas expresadas como números enteros de milisegundos no negativos (mayores o iguales a 0) relativos al inicio de la Grabacion_De_Audio.
3. THE Segmento_De_Hablante SHALL tener una marca de tiempo de fin `fin_ms` mayor o igual que su marca de tiempo de inicio `inicio_ms`.
4. THE Segmento_De_Hablante SHALL tener una marca de tiempo de fin `fin_ms` menor o igual que la Duracion_De_Grabacion.
5. THE Resultado_De_Diarizacion SHALL reportar un número de hablantes detectados igual a la cantidad de Etiquetas_De_Hablante_Cruda distintas presentes en su lista de Segmentos_De_Hablante.

### Requirement 6: Etiquetado anónimo y ordenado de hablantes

**User Story:** Como responsable de cumplimiento de Summan, quiero que los hablantes se etiqueten de forma anónima y consistente, para que la diarización no introduzca datos personales antes del módulo de identificación nominal.

#### Acceptance Criteria

1. WHEN el Worker_De_Diarizacion procesa un Resultado_De_Diarizacion, THE Worker_De_Diarizacion SHALL crear exactamente un Hablante por cada Etiqueta_De_Hablante_Cruda distinta presente en los Segmentos_De_Hablante.
2. WHEN el Worker_De_Diarizacion asigna las Etiquetas_De_Hablante, THE Worker_De_Diarizacion SHALL ordenar los Hablantes según la marca de tiempo `inicio_ms` del primer Segmento_De_Hablante en que aparece cada Etiqueta_De_Hablante_Cruda, asignar un `orden` consecutivo que comience en 1 y se incremente en 1, y asignar la Etiqueta_De_Hablante con el formato "Hablante N" donde N es el `orden`.
3. THE Hablante SHALL registrarse sin ningún campo de identidad nominal ni dato personal del participante.
4. IF dos o más Etiquetas_De_Hablante_Cruda comparten la misma marca de tiempo `inicio_ms` de su primer Segmento_De_Hablante, THEN THE Worker_De_Diarizacion SHALL desempatar el orden de los Hablantes de forma determinista mediante el orden lexicográfico ascendente de la Etiqueta_De_Hablante_Cruda.

### Requirement 7: Asignación de Turnos_De_Habla a Hablantes

**User Story:** Como Usuario_Comercial, quiero saber qué hablante pronunció cada turno de la transcripción, para entender quién dijo qué durante la reunión.

#### Acceptance Criteria

1. WHERE la Diarizacion tiene al menos un Hablante, WHEN el Worker_De_Diarizacion procesa los Turnos_De_Habla de la Transcripcion, THE Worker_De_Diarizacion SHALL crear exactamente una Asignacion_De_Hablante por cada Turno_De_Habla, vinculándolo al Hablante cuyo Solape_Temporal acumulado con el Turno_De_Habla sea máximo.
2. IF un Turno_De_Habla presenta el mismo Solape_Temporal máximo con dos o más Hablantes, o presenta Solape_Temporal cero con todos los Hablantes, THEN THE Worker_De_Diarizacion SHALL asignar el Turno_De_Habla al Hablante de menor `orden` entre los candidatos.
3. WHEN el Worker_De_Diarizacion produce las Asignaciones_De_Hablante, THE Worker_De_Diarizacion SHALL conservar sin modificar el `texto`, el `inicio_ms`, el `fin_ms` y el `orden` de cada Turno_De_Habla de la Transcripcion existente.
4. IF la Transcripcion no contiene ningún Turno_De_Habla, THEN THE Worker_De_Diarizacion SHALL persistir cero Asignaciones_De_Hablante y conservar el Resultado_De_Diarizacion como válido sin generar error.
5. IF el Resultado_De_Diarizacion no contiene ningún Segmento_De_Hablante, THEN THE Worker_De_Diarizacion SHALL persistir una Diarizacion con cero Hablantes y cero Asignaciones_De_Hablante, y registrar el resultado como sin hablantes detectados.

### Requirement 8: Persistencia transaccional de la Diarizacion

**User Story:** Como responsable técnico de sauri, quiero que la Diarizacion, sus Hablantes y sus Asignaciones_De_Hablante se persistan de forma atómica y asociados a la Reunion, para que no queden diarizaciones parciales o huérfanas.

#### Acceptance Criteria

1. WHEN el Worker_De_Diarizacion persiste una Diarizacion, THE Worker_De_Diarizacion SHALL persistir exactamente una Diarizacion asociada a la Reunion identificada por `reunion_id`, de modo que no exista más de una Diarizacion por Reunion.
2. WHEN el Worker_De_Diarizacion persiste una Diarizacion, THE Repositorio_De_Diarizacion SHALL guardar la Diarizacion, la totalidad de sus Hablantes y la totalidad de sus Asignaciones_De_Hablante dentro de una única transacción, confirmándola solo si todos los registros se escriben con éxito.
3. IF la transacción de persistencia de la Diarizacion, de cualquiera de sus Hablantes o de cualquiera de sus Asignaciones_De_Hablante falla, THEN THE Repositorio_De_Diarizacion SHALL revertir la transacción completa de forma que no quede ningún registro parcial asociado a la Reunion, y propagar un indicador de fallo al Worker_De_Diarizacion.
4. WHEN el Worker_De_Diarizacion persiste una Diarizacion, THE Worker_De_Diarizacion SHALL registrar el Proveedor_De_Diarizacion utilizado y el número de Hablantes detectados, consistentes con las Capacidades_De_Diarizacion declaradas por el Motor_De_Diarizacion.
5. WHEN un componente consulta la Diarizacion de una Reunion por su identificador y existe una Diarizacion asociada, THE Repositorio_De_Diarizacion SHALL recuperar dicha Diarizacion junto con sus Hablantes y sus Asignaciones_De_Hablante.
6. IF un componente consulta la Diarizacion de una Reunion por su identificador y no existe ninguna Diarizacion asociada, THEN THE Repositorio_De_Diarizacion SHALL devolver un resultado vacío que indique la ausencia de Diarizacion, sin generar error.

### Requirement 9: Ciclo de vida del Estado_De_Diarizacion

**User Story:** Como Usuario_Comercial, quiero conocer el avance y el resultado de la diarización de una reunión, para saber si la atribución de hablantes está disponible o si el proceso falló.

#### Acceptance Criteria

1. WHEN el Worker_De_Diarizacion inicia el procesamiento de un Mensaje_De_Diarizacion para una Reunion con Transcripcion existente, THE Worker_De_Diarizacion SHALL establecer el Estado_De_Diarizacion de la Diarizacion en "en_proceso".
2. WHEN el Worker_De_Diarizacion persiste exitosamente una Diarizacion, THE Worker_De_Diarizacion SHALL establecer el Estado_De_Diarizacion de la Diarizacion en "completada".
3. IF el Motor_De_Diarizacion señala un fallo durante el procesamiento, THEN THE Worker_De_Diarizacion SHALL establecer el Estado_De_Diarizacion de la Diarizacion en "fallida" y registrar la Causa_De_Fallo_Diarizacion "fallo_del_motor".
4. WHEN el Estado_De_Diarizacion de una Diarizacion cambia, THE Worker_De_Diarizacion SHALL registrar la marca de tiempo del cambio expresada en UTC.
5. THE Modulo_De_Diarizacion SHALL conservar sin cambios el Estado_De_Proceso de la Reunion durante todo el procesamiento de la diarización.

### Requirement 10: Manejo de errores y reintentos del procesamiento

**User Story:** Como responsable técnico de sauri, quiero que los fallos transitorios de diarización se reintenten de forma acotada, para que un error temporal del motor no descarte de forma permanente una transcripción procesable.

#### Acceptance Criteria

1. IF el Motor_De_Diarizacion señala un fallo durante el procesamiento de un Mensaje_De_Diarizacion, THEN THE Worker_De_Diarizacion SHALL propagar el fallo a la Cola_De_Trabajos junto con una indicación de error que permita aplicar la política de reintentos, sin persistir una Diarizacion en estado "completada" para ese mensaje.
2. WHILE el número de reintentos acumulados de un Mensaje_De_Diarizacion sea menor que el máximo configurado en la variable DIARIZATION_MAX_RETRIES (rango permitido de 0 a 10 reintentos, valor por defecto 3), THE Cola_De_Trabajos SHALL volver a encolar el mensaje para reprocesamiento.
3. WHERE la derivación a dead-letter está configurada, WHEN la Cola_De_Trabajos alcanza el máximo configurado de reintentos para un Mensaje_De_Diarizacion, THE Cola_De_Trabajos SHALL derivar el mensaje a la cola dead-letter.
4. IF la derivación a dead-letter no está configurada y la Cola_De_Trabajos alcanza el máximo configurado de reintentos para un Mensaje_De_Diarizacion, THEN THE Cola_De_Trabajos SHALL descartar el mensaje registrando el agotamiento de reintentos mediante una indicación de error.
5. WHILE un Mensaje_De_Diarizacion se reintenta, THE Worker_De_Diarizacion SHALL garantizar que exista como máximo una (1) Diarizacion persistida para el mismo `reunion_id`.
6. IF el procesamiento de un Mensaje_De_Diarizacion falla después de iniciar la persistencia, THEN THE Repositorio_De_Diarizacion SHALL revertir la transacción dejando la Reunion sin Diarizacion parcial y propagar una indicación de error que habilite el reintento.
