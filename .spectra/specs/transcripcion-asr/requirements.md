# Requirements Document

## Introduction

Este documento define los requerimientos del segundo módulo de **sauri**, la plataforma interna de inteligencia de reuniones comerciales de Summan. El módulo se denomina **Transcripción (ASR)** y corresponde al Milestone 2 de la hoja de ruta del producto.

El Milestone 1 (Captura de audio desde Google Meet vía extensión de Chrome y pipeline de carga al backend) está completo y fusionado: las grabaciones se suben y almacenan en el Almacen_De_Objetos, se persiste un registro de Grabacion_De_Sesion en PostgreSQL, y la carga deja la Reunion en estado "grabando". Este módulo toma esa Grabacion_De_Audio y produce la Transcripcion.

El propósito del módulo es consumir grabaciones encoladas, ejecutar el reconocimiento automático del habla (ASR) mediante un Motor_ASR intercambiable (un Proveedor_Local basado en faster-whisper o un Proveedor_Nube externo), producir una Transcripcion con segmentos y marcas de tiempo, persistirla asociada a la Reunion, y actualizar el Estado_De_Proceso de la Reunion. El módulo cubre la selección del motor por configuración, la segmentación con marcas de tiempo, el manejo de idioma prioritario (español de Colombia), el comportamiento de error y reintentos, las transiciones de estado y la persistencia transaccional.

Este módulo construye sobre la estructura ya existente en `backend/app/transcripcion/` (factory.py, motor_asr.py, proveedor_local.py, proveedor_nube.py, repository.py, worker.py) y el servicio `backend/asr-engine/` (Dockerfile + main.py), alineando los requerimientos con dicha estructura en lugar de inventar una nueva. Reutiliza las abstracciones de Cola_De_Trabajos (RabbitMQ) y Almacen_De_Objetos (MinIO/S3) provistas en `backend/app/infra/`.

Quedan **explícitamente fuera de alcance** de este módulo: la identificación nominal de hablantes, la generación de notas o resúmenes con IA, la integración con el CRM, la biblioteca/búsqueda, la analítica comercial, y la experiencia de reproducción o lectura enriquecida de la Transcripcion. La captura de audio y video pertenece al Milestone 1 y aquí solo se asume como insumo.

## Glossary

- **sauri**: Plataforma interna de Summan para captura, transcripción e inteligencia de reuniones comerciales.
- **Servicio_De_Reuniones**: Componente de sauri responsable de registrar reuniones y orquestar las transiciones del Estado_De_Proceso. Provee `registrar_transicion` y la máquina de estados.
- **Worker_De_Transcripcion**: Componente de sauri que se suscribe al tema "transcribir" de la Cola_De_Trabajos, ejecuta la transcripción y persiste el resultado. Implementado en `backend/app/transcripcion/worker.py`.
- **Motor_ASR**: Componente abstracto de reconocimiento automático del habla (Automatic Speech Recognition) que convierte audio en texto. Define la interfaz común `transcribir(audio_ref, opciones)` y `capacidades()`.
- **Proveedor_De_Transcripcion**: Implementación concreta del Motor_ASR seleccionable por configuración. Sus variantes son el Proveedor_Local y el Proveedor_Nube.
- **Proveedor_Local**: Implementación del Motor_ASR que procesa el audio mediante el Servicio_ASR_Local sin enviarlo a servicios externos.
- **Proveedor_Nube**: Implementación del Motor_ASR que envía el audio a un servicio ASR externo a través de un canal cifrado.
- **Fabrica_De_Motor**: Función `crear_motor_asr` que construye el Proveedor_De_Transcripcion activo según la variable de configuración ASR_PROVIDER. Implementada en `backend/app/transcripcion/factory.py`.
- **Servicio_ASR_Local**: Servicio HTTP propio (contenedor `asr-engine`) basado en faster-whisper que expone `POST /transcribe`. Implementado en `backend/asr-engine/main.py`.
- **Cola_De_Trabajos**: Abstracción de mensajería con entrega al-menos-una-vez, reintentos y dead-letter, provista en `backend/app/infra/queue.py`.
- **Almacen_De_Objetos**: Abstracción de almacenamiento de objetos (MinIO/S3) donde reside la Grabacion_De_Audio, provista en `backend/app/infra/`.
- **Repositorio_De_Transcripcion**: Componente que persiste la Transcripcion junto con sus Turnos_De_Habla en una única transacción. Implementado en `backend/app/transcripcion/repository.py`.
- **Mensaje_De_Transcripcion**: Mensaje encolado en el tema "transcribir" con la forma `{"reunion_id": str, "audio_ref": str}`.
- **Grabacion_De_Sesion**: Contenedor de la grabación de una reunión, asociado a una única Reunion, que incluye la referencia a la Grabacion_De_Audio.
- **Grabacion_De_Audio**: Pista de audio referenciada por `audio_ref` en el Almacen_De_Objetos, a partir de la cual se genera la Transcripcion.
- **Transcripcion**: Resultado en texto del procesamiento del audio, asociado a una Reunion, con idioma, proveedor, indicador de soporte de turnos y marca de creación.
- **Turno_De_Habla**: Segmento temporal de texto dentro de una Transcripcion, con `texto`, `inicio_ms`, `fin_ms` y `orden`, sin identidad nominal asociada.
- **Segmento_De_Transcripcion**: Unidad de texto con marcas de tiempo relativas (`inicio_ms`, `fin_ms`) producida por el Motor_ASR antes de persistirse como Turno_De_Habla.
- **Resultado_De_Transcripcion**: Objeto producido por el Motor_ASR que contiene la lista de Segmentos_De_Transcripcion, el idioma y el indicador de soporte de turnos.
- **Reunion**: Registro que representa una sesión de Google Meet, con su Estado_De_Proceso.
- **Estado_De_Proceso**: Estado del ciclo de vida de la Reunion. Valores: "en_cola", "uniendose", "grabando", "transcribiendo", "completado", "fallido".
- **Causa_De_Fallo**: Motivo registrado cuando el Estado_De_Proceso es "fallido". Valor relevante para este módulo: "fallo_del_motor".
- **Idioma_Prioritario**: Idioma configurado como preferente para la transcripción. Valor por defecto: "es-CO".

## Requirements

### Requirement 1: Consumo de grabaciones encoladas

**User Story:** Como responsable técnico de sauri, quiero que el Worker_De_Transcripcion consuma las grabaciones encoladas, para que cada Grabacion_De_Audio cargada se procese automáticamente sin intervención manual.

#### Acceptance Criteria

1. WHEN el Worker_De_Transcripcion inicia su ejecución, THE Worker_De_Transcripcion SHALL suscribirse al tema "transcribir" de la Cola_De_Trabajos.
2. WHEN el Worker_De_Transcripcion recibe un Mensaje_De_Transcripcion del tema "transcribir", THE Worker_De_Transcripcion SHALL extraer del mensaje el identificador `reunion_id` y la referencia `audio_ref`.
3. IF un Mensaje_De_Transcripcion no contiene un `reunion_id` no vacío o no contiene un `audio_ref` no vacío, THEN THE Worker_De_Transcripcion SHALL terminar el procesamiento del mensaje sin lanzar una excepción y sin persistir una Transcripcion.
4. IF un Mensaje_De_Transcripcion referencia un `reunion_id` que no corresponde a ninguna Reunion existente, THEN THE Worker_De_Transcripcion SHALL terminar el procesamiento del mensaje sin lanzar una excepción y sin persistir una Transcripcion.
5. WHEN el Worker_De_Transcripcion completa el procesamiento de un Mensaje_De_Transcripcion sin lanzar una excepción, THE Cola_De_Trabajos SHALL confirmar el mensaje mediante ack.
6. IF el procesamiento de un Mensaje_De_Transcripcion lanza una excepción, THEN THE Cola_De_Trabajos SHALL rechazar el mensaje mediante nack sin reencolar.
7. WHERE el dead-letter está configurado, IF el procesamiento de un Mensaje_De_Transcripcion lanza una excepción, THEN THE Cola_De_Trabajos SHALL derivar el mensaje al dead-letter.

### Requirement 2: Selección del Proveedor_De_Transcripcion por configuración

**User Story:** Como responsable técnico de sauri, quiero seleccionar el Proveedor_De_Transcripcion activo mediante configuración, para que pueda alternar entre procesamiento local y en la nube sin modificar el código del Worker_De_Transcripcion.

#### Acceptance Criteria

1. THE Fabrica_De_Motor SHALL construir exactamente un Proveedor_De_Transcripcion activo a partir del valor de la variable de configuración ASR_PROVIDER, evaluado sin distinción entre mayúsculas y minúsculas y sin considerar los espacios al inicio o al final del valor.
2. WHERE la variable ASR_PROVIDER tiene el valor "local", THE Fabrica_De_Motor SHALL construir un Proveedor_Local configurado con la URL definida en la variable ASR_LOCAL_URL.
3. WHERE la variable ASR_PROVIDER tiene el valor "cloud", THE Fabrica_De_Motor SHALL construir un Proveedor_Nube.
4. WHERE la variable ASR_PROVIDER no está definida o contiene una cadena vacía, THE Fabrica_De_Motor SHALL construir un Proveedor_Local configurado con la URL definida en la variable ASR_LOCAL_URL como valor por defecto.
5. IF la variable ASR_PROVIDER tiene un valor distinto de "local" y "cloud", THEN THE Fabrica_De_Motor SHALL rechazar la construcción sin instanciar ningún Proveedor_De_Transcripcion y señalar un error de configuración que indique el valor inválido recibido.
6. IF se selecciona un Proveedor_Local (por el valor "local" o por defecto) y la variable ASR_LOCAL_URL no está definida o contiene una cadena vacía, THEN THE Fabrica_De_Motor SHALL rechazar la construcción sin instanciar ningún Proveedor_De_Transcripcion y señalar un error de configuración que indique la ausencia de la URL local.
7. THE Worker_De_Transcripcion SHALL interactuar con el Proveedor_De_Transcripcion construido únicamente a través de la interfaz común del Motor_ASR.

### Requirement 3: Procesamiento local sin envío externo

**User Story:** Como responsable de cumplimiento de Summan, quiero que el Proveedor_Local procese la Grabacion_De_Audio sin enviarla a servicios externos, para que los datos sensibles permanezcan dentro de la infraestructura propia de sauri.

#### Acceptance Criteria

1. WHEN el Proveedor_Local recibe una solicitud de transcripción, THE Proveedor_Local SHALL enviar la referencia `audio_ref` y el Idioma_Prioritario al Servicio_ASR_Local mediante una solicitud `POST /transcribe` y esperar la respuesta durante un máximo de 300 segundos.
2. THE Proveedor_Local SHALL procesar la Grabacion_De_Audio sin enviarla a ningún servicio externo a la infraestructura de sauri.
3. WHEN el Servicio_ASR_Local responde con éxito, THE Servicio_ASR_Local SHALL devolver una estructura que contenga una lista de cero o más segmentos, donde cada segmento incluye `text`, `start_ms` y `end_ms`, junto con el idioma detectado.
4. WHEN el Servicio_ASR_Local responde con una estructura válida de segmentos, THE Proveedor_Local SHALL convertir cada segmento de la respuesta en un Segmento_De_Transcripcion con su `texto`, `inicio_ms` y `fin_ms`.
5. IF el Servicio_ASR_Local responde con un código de estado HTTP de error, THEN THE Proveedor_Local SHALL señalar un fallo de transcripción al Worker_De_Transcripcion sin persistir segmentos parciales.
6. IF el Servicio_ASR_Local no responde dentro de 300 segundos o no es alcanzable, THEN THE Proveedor_Local SHALL abortar el procesamiento y señalar un fallo de transcripción al Worker_De_Transcripcion.
7. IF el Servicio_ASR_Local responde sin la lista de segmentos esperada, THEN THE Proveedor_Local SHALL señalar un fallo de transcripción al Worker_De_Transcripcion sin generar Segmentos_De_Transcripcion inválidos.

### Requirement 4: Procesamiento en la nube con canal cifrado

**User Story:** Como responsable de seguridad de Summan, quiero que el Proveedor_Nube transmita el audio por un canal cifrado, para que la información comercial no quede expuesta al usar un servicio ASR externo.

#### Acceptance Criteria

1. WHEN el Proveedor_Nube transmite la Grabacion_De_Audio a un servicio ASR externo, THE Proveedor_Nube SHALL usar un canal cifrado en tránsito mediante HTTPS.
2. IF el endpoint configurado para el Proveedor_Nube no usa el esquema HTTPS, THEN THE Proveedor_Nube SHALL rechazar la inicialización sin transmitir ninguna Grabacion_De_Audio y señalar un error de configuración que indique el esquema no soportado.
3. THE Proveedor_Nube SHALL autenticar la solicitud al servicio ASR externo mediante la credencial definida en la variable ASR_CLOUD_API_KEY.
4. IF la variable ASR_CLOUD_API_KEY no está definida o está vacía al inicializar el Proveedor_Nube, THEN THE Proveedor_Nube SHALL rechazar la inicialización sin transmitir ninguna Grabacion_De_Audio y señalar un error de configuración que indique la ausencia de la credencial.
5. WHEN el servicio ASR externo responde con segmentos de transcripción, THE Proveedor_Nube SHALL convertir cada segmento en un Segmento_De_Transcripcion con su `texto` no vacío, su `inicio_ms` y su `fin_ms` como enteros no negativos donde `fin_ms` es mayor o igual a `inicio_ms`.
6. IF el servicio ASR externo no responde dentro de 30 segundos, responde con un error o devuelve una respuesta sin segmentos válidos, THEN THE Proveedor_Nube SHALL abortar el procesamiento, conservar la Grabacion_De_Audio sin modificar y señalar un error de transcripción que indique la falla del servicio externo.

### Requirement 5: Segmentación y marcas de tiempo

**User Story:** Como Usuario_Comercial, quiero que la Transcripcion incluya segmentos con marcas de tiempo, para que pueda ubicar en el audio el momento en que se dijo cada fragmento.

#### Acceptance Criteria

1. THE Resultado_De_Transcripcion SHALL contener una lista de Segmentos_De_Transcripcion ordenada de forma ascendente por su marca de tiempo de inicio `inicio_ms`.
2. THE Segmento_De_Transcripcion SHALL incluir una marca de tiempo de inicio `inicio_ms` y una marca de tiempo de fin `fin_ms`, ambas expresadas como números enteros de milisegundos no negativos (mayores o iguales a 0) relativos al inicio de la Grabacion_De_Audio.
3. THE Segmento_De_Transcripcion SHALL tener una marca de tiempo de fin `fin_ms` mayor o igual que su marca de tiempo de inicio `inicio_ms`.
4. THE Segmento_De_Transcripcion SHALL tener una marca de tiempo de fin `fin_ms` menor o igual que la duración total en milisegundos de la Grabacion_De_Audio.
5. WHEN el Worker_De_Transcripcion persiste los Segmentos_De_Transcripcion como Turnos_De_Habla, THE Worker_De_Transcripcion SHALL asignar a cada Turno_De_Habla un valor de `orden` entero que comience en 1 para el primer Segmento_De_Transcripcion y se incremente en 1 por cada segmento siguiente, preservando la secuencia ascendente por `inicio_ms` del Resultado_De_Transcripcion.
6. IF el Resultado_De_Transcripcion no contiene ningún Segmento_De_Transcripcion (lista vacía), THEN THE Worker_De_Transcripcion SHALL persistir cero Turnos_De_Habla y conservar el Resultado_De_Transcripcion como válido sin generar error.

### Requirement 6: Manejo del idioma prioritario

**User Story:** Como Usuario_Comercial, quiero que la transcripción se genere en español de Colombia, para que el texto refleje el idioma hablado en las reuniones comerciales de Summan.

#### Acceptance Criteria

1. WHEN el Worker_De_Transcripcion invoca al Motor_ASR, THE Worker_De_Transcripcion SHALL indicar el Idioma_Prioritario configurado, usando "es-CO" como valor por defecto cuando no exista una configuración explícita.
2. WHEN el Motor_ASR recibe una solicitud de transcripción con un Idioma_Prioritario, THE Motor_ASR SHALL utilizar ese Idioma_Prioritario como idioma preferente al procesar la Grabacion_De_Audio.
3. WHEN el Worker_De_Transcripcion persiste una Transcripcion, THE Worker_De_Transcripcion SHALL registrar como idioma de la Transcripcion el idioma reportado por el Motor_ASR en el Resultado_De_Transcripcion.
4. IF el Resultado_De_Transcripcion no reporta un idioma, THEN THE Worker_De_Transcripcion SHALL registrar el Idioma_Prioritario como idioma de la Transcripcion.

### Requirement 7: Persistencia transaccional de la Transcripcion

**User Story:** Como responsable técnico de sauri, quiero que la Transcripcion y sus Turnos_De_Habla se persistan de forma atómica y asociados a la Reunion, para que no queden transcripciones parciales o huérfanas.

#### Acceptance Criteria

1. WHEN el Motor_ASR produce un Resultado_De_Transcripcion con al menos un Segmento_De_Transcripcion, THE Worker_De_Transcripcion SHALL persistir exactamente una Transcripcion asociada a la Reunion identificada por `reunion_id`, de modo que no exista más de una Transcripcion por Reunion.
2. IF el Resultado_De_Transcripcion no contiene ningún Segmento_De_Transcripcion, THEN THE Worker_De_Transcripcion SHALL abstenerse de persistir una Transcripcion y registrar el resultado como sin contenido transcribible.
3. WHEN el Worker_De_Transcripcion persiste una Transcripcion, THE Repositorio_De_Transcripcion SHALL guardar la Transcripcion y la totalidad de sus Turnos_De_Habla dentro de una única transacción, confirmándola solo si todos los registros se escriben con éxito.
4. IF la transacción de persistencia de la Transcripcion o de cualquiera de sus Turnos_De_Habla falla, THEN THE Repositorio_De_Transcripcion SHALL revertir la transacción completa de forma que no quede ninguna Transcripcion ni Turno_De_Habla parcial asociado a la Reunion, y propagar un indicador de fallo al Worker_De_Transcripcion.
5. WHEN el Worker_De_Transcripcion persiste una Transcripcion, THE Worker_De_Transcripcion SHALL registrar el Proveedor_De_Transcripcion utilizado y el indicador de soporte de turnos declarado por el Motor_ASR.
6. WHERE el Motor_ASR declara soporte de turnos en sus capacidades, THE Transcripcion SHALL registrar cada Turno_De_Habla con sus marcas de tiempo `inicio_ms` y `fin_ms`, sin asignar identidad nominal.
7. WHEN un componente consulta la Transcripcion de una Reunion por su identificador y existe una Transcripcion asociada, THE Repositorio_De_Transcripcion SHALL recuperar dicha Transcripcion junto con sus Turnos_De_Habla.
8. IF un componente consulta la Transcripcion de una Reunion por su identificador y no existe ninguna Transcripcion asociada, THEN THE Repositorio_De_Transcripcion SHALL devolver un resultado vacío que indique la ausencia de Transcripcion, sin generar error.

### Requirement 8: Transiciones de estado de la Reunion

**User Story:** Como Usuario_Comercial, quiero que el estado de la Reunion refleje el avance y el resultado de la transcripción, para que pueda saber si la Transcripcion está disponible o si el proceso falló.

#### Acceptance Criteria

1. WHEN el Worker_De_Transcripcion inicia el procesamiento de una Grabacion_De_Audio cuyo Estado_De_Proceso actual es "grabando", THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "transcribiendo".
2. WHEN el Worker_De_Transcripcion persiste exitosamente una Transcripcion con al menos un Segmento_De_Transcripcion y el Estado_De_Proceso actual es "transcribiendo", THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "completado".
3. IF el Motor_ASR no produce ningún Segmento_De_Transcripcion a partir de la Grabacion_De_Audio, THEN THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "fallido", registrar la Causa_De_Fallo "fallo_del_motor" y no persistir ninguna Transcripcion para esa Reunion.
4. WHEN el Estado_De_Proceso de una Reunion cambia, THE Servicio_De_Reuniones SHALL registrar el estado anterior, el nuevo estado y la marca de tiempo de la transición expresada en UTC.
5. IF el Estado_De_Proceso actual de la Reunion no admite la transición solicitada, THEN THE Servicio_De_Reuniones SHALL rechazar la transición, conservar sin cambios el Estado_De_Proceso actual y devolver al solicitante un error que indique la transición inválida.

### Requirement 9: Manejo de errores y reintentos del procesamiento

**User Story:** Como responsable técnico de sauri, quiero que los fallos transitorios de transcripción se reintenten de forma acotada, para que un error temporal del motor no descarte de forma permanente una grabación procesable.

#### Acceptance Criteria

1. IF el Motor_ASR señala un fallo durante el procesamiento de un Mensaje_De_Transcripcion, THEN THE Worker_De_Transcripcion SHALL propagar el fallo a la Cola_De_Trabajos junto con una indicación de error que permita aplicar la política de reintentos, sin persistir ninguna Transcripcion para ese mensaje.
2. WHILE el número de reintentos acumulados de un Mensaje_De_Transcripcion sea menor que el máximo configurado (rango permitido de 0 a 10 reintentos, valor por defecto 3), THE Cola_De_Trabajos SHALL volver a encolar el mensaje para reprocesamiento.
3. WHERE la derivación a dead-letter está configurada, WHEN la Cola_De_Trabajos alcanza el máximo configurado de reintentos para un Mensaje_De_Transcripcion, THE Cola_De_Trabajos SHALL derivar el mensaje a la cola dead-letter.
4. IF la derivación a dead-letter no está configurada y la Cola_De_Trabajos alcanza el máximo configurado de reintentos para un Mensaje_De_Transcripcion, THEN THE Cola_De_Trabajos SHALL descartar el mensaje registrando el agotamiento de reintentos mediante una indicación de error.
5. WHILE un Mensaje_De_Transcripcion se reintenta, THE Worker_De_Transcripcion SHALL garantizar que exista como máximo una (1) Transcripcion persistida para el mismo `reunion_id`.
6. IF el procesamiento de un Mensaje_De_Transcripcion falla después de iniciar la persistencia, THEN THE Repositorio_De_Transcripcion SHALL revertir la transacción dejando la Reunion sin Transcripcion parcial y propagar una indicación de error que habilite el reintento.
