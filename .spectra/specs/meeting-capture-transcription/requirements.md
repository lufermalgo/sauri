# Requirements Document

## Introduction

Este documento define los requerimientos del primer módulo de **sauri**, la plataforma interna de inteligencia de reuniones comerciales de Summan. El módulo se denomina **Captura y Transcripción de Reuniones** y constituye el MVP del proyecto.

El propósito del módulo es permitir que sauri se incorpore como asistente a una reunión de Google Meet, capture el audio y el video de la sesión y produzca una transcripción en español (Colombia) del contenido, persistida y asociada a la reunión correspondiente. La transcripción se genera a partir de la pista de audio de la grabación de sesión, incluye marcas de tiempo y, cuando el motor de transcripción lo provea, separación temporal básica de turnos de habla, sin asignar identidad nominal a los hablantes.

El alcance se limita a la captura de audio y video, y la generación de la transcripción. Quedan **explícitamente fuera de alcance** de este módulo: la identificación nominal de hablantes, la generación de notas o resúmenes con IA, la integración con el CRM, la biblioteca/búsqueda y la analítica comercial. Esas capacidades corresponden a módulos posteriores y solo se mencionan aquí como contexto.

Asimismo, quedan **explícitamente fuera de alcance** de este módulo la experiencia de reproducción y visualización de la Grabacion_De_Sesion, la lectura enriquecida sincronizada de la Transcripcion y la compartición de sesiones grabadas con otros usuarios. Esas capacidades corresponden a un módulo posterior de biblioteca/visualización. Este módulo se limita a unir el Asistente_De_Reunion, capturar audio y video, generar y persistir la Transcripcion, gestionar estados y errores del proceso, y dejar los datos accesibles únicamente mediante acceso autenticado y autorizado.

El módulo se diseña para ser portable entre proveedores de nube, ejecutable en contenedores Docker tanto en desarrollo local como en producción, y con un motor de transcripción intercambiable que pueda sustituirse por un procesamiento local en el futuro sin reescribir el sistema.

## Glossary

- **sauri**: Plataforma interna de Summan para captura, transcripción e inteligencia de reuniones comerciales.
- **Asistente_De_Reunion**: Componente de sauri que se une a una reunión de Google Meet como participante para capturar su audio.
- **Servicio_De_Reuniones**: Componente de sauri responsable de registrar reuniones, programar y disparar la unión del Asistente_De_Reunion, y orquestar los estados del proceso.
- **Motor_ASR**: Componente abstracto de reconocimiento automático del habla (Automatic Speech Recognition) que convierte audio en texto. Es intercambiable mediante una interfaz común.
- **Proveedor_De_Transcripcion**: Implementación concreta del Motor_ASR (por ejemplo, un servicio externo o un modelo local), seleccionable por configuración.
- **Transcripcion**: Documento de texto en español resultante de procesar el audio de una reunión, con marcas de tiempo.
- **Turno_De_Habla**: Segmento temporal continuo de audio hablado delimitado por marcas de tiempo, sin identidad nominal asociada.
- **Reunion**: Registro en sauri que representa una sesión de Google Meet, con su enlace, metadatos y estado de procesamiento.
- **Estado_De_Proceso**: Estado del ciclo de vida de la captura y transcripción de una Reunion. Valores: en cola, uniéndose, grabando, transcribiendo, completado, fallido.
- **Usuario_Comercial**: Miembro del equipo comercial de Summan autorizado para usar sauri.
- **Grabacion_De_Sesion**: Contenedor de la grabación de una reunión capturada por el Asistente_De_Reunion, compuesto por una Pista_De_Audio y una Pista_De_Video, asociado a una única Reunion.
- **Grabacion_De_Audio**: Pista de audio de la Grabacion_De_Sesion, a partir de la cual se genera la Transcripcion.
- **Pista_De_Video**: Pista de video de la Grabacion_De_Sesion.
- **Participante**: Persona presente en la reunión de Google Meet.
- **Notificacion_De_Grabacion**: Aviso de que la reunión está siendo grabada/transcrita por sauri.

## Requirements

### Requerimiento 1: Unión del asistente a una reunión de Google Meet

**Historia de usuario:** Como Usuario_Comercial, quiero que sauri se una a mi reunión de Google Meet, para que pueda capturar y transcribir su contenido sin que yo tenga que grabar manualmente.

#### Criterios de Aceptación

1. WHEN un Usuario_Comercial registra una Reunion proporcionando un enlace válido de Google Meet, THE Servicio_De_Reuniones SHALL crear un registro de Reunion con Estado_De_Proceso "en cola".
2. WHEN un Usuario_Comercial solicita manualmente la unión a una Reunion en cola, THE Servicio_De_Reuniones SHALL instruir al Asistente_De_Reunion para unirse al enlace de Google Meet asociado.
3. WHEN una Reunion en cola tiene una hora de inicio programada proveniente de una invitación de calendario, THE Servicio_De_Reuniones SHALL disparar la unión del Asistente_De_Reunion en la hora de inicio programada.
4. WHEN el Asistente_De_Reunion inicia el proceso de unión a una reunión de Google Meet, THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "uniéndose".
5. WHEN el Asistente_De_Reunion es admitido en la reunión de Google Meet, THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "grabando".
6. IF el Asistente_De_Reunion no logra unirse a la reunión de Google Meet dentro de los 120 segundos posteriores al intento de unión, THEN THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "fallido" y registrar la causa "no pudo unirse".
7. THE Servicio_De_Reuniones SHALL aceptar como entrada de Reunion al menos un enlace de Google Meet, un identificador de invitación de calendario, o una solicitud manual con enlace de Google Meet.

### Requerimiento 2: Captura del audio y el video de la reunión

**Historia de usuario:** Como Usuario_Comercial, quiero que sauri capture el audio y el video de la reunión mientras está en curso, para que el contenido de la sesión quede disponible para transcripción y para usos posteriores.

#### Criterios de Aceptación

1. WHILE el Estado_De_Proceso de una Reunion es "grabando", THE Asistente_De_Reunion SHALL capturar la Pista_De_Audio y la Pista_De_Video de la reunión de Google Meet asociada.
2. WHEN la reunión de Google Meet finaliza o el Asistente_De_Reunion es retirado de la reunión, THE Asistente_De_Reunion SHALL finalizar la Grabacion_De_Sesion y persistir la Pista_De_Audio y la Pista_De_Video asociadas a la Reunion.
3. THE Asistente_De_Reunion SHALL asociar cada Grabacion_De_Sesion a una única Reunion mediante el identificador de la Reunion.
4. IF la captura de audio o de video se interrumpe antes de finalizar la reunión, THEN THE Servicio_De_Reuniones SHALL conservar las pistas capturadas hasta el punto de interrupción y registrar la interrupción en la Reunion.
5. WHEN el Asistente_De_Reunion finaliza la Grabacion_De_Sesion, THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "transcribiendo".

### Requerimiento 3: Generación y persistencia de la transcripción en español

**Historia de usuario:** Como Usuario_Comercial, quiero obtener una transcripción en español del contenido hablado de la reunión, para que pueda consultar lo que se dijo sin volver a escuchar el audio.

#### Criterios de Aceptación

1. WHEN el Estado_De_Proceso de una Reunion cambia a "transcribiendo", THE Servicio_De_Reuniones SHALL enviar la Grabacion_De_Audio de la Grabacion_De_Sesion al Motor_ASR para su procesamiento.
2. THE Motor_ASR SHALL producir una Transcripcion del contenido hablado configurada con español de Colombia como idioma prioritario.
3. THE Servicio_De_Reuniones SHALL persistir la Transcripcion asociada a la Reunion mediante el identificador de la Reunion.
4. THE Transcripcion SHALL incluir marcas de tiempo que indiquen el momento, relativo al inicio de la Grabacion_De_Audio, en que ocurre cada segmento de texto.
5. WHERE el Motor_ASR provee separación de turnos, THE Transcripcion SHALL registrar cada Turno_De_Habla con sus marcas de tiempo de inicio y fin, sin asignar identidad nominal.
6. WHEN la Transcripcion ha sido persistida completamente, THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "completado".
7. IF el Motor_ASR no produce ningún texto a partir de una Grabacion_De_Audio con contenido hablado, THEN THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "fallido" y registrar la causa "fallo del motor".

### Requerimiento 4: Gestión de estados y manejo de errores del proceso

**Historia de usuario:** Como Usuario_Comercial, quiero ver el estado del proceso de cada reunión y conocer las causas de fallo, para que pueda saber si la transcripción estará disponible y actuar cuando algo falle.

#### Criterios de Aceptación

1. THE Servicio_De_Reuniones SHALL mantener para cada Reunion un Estado_De_Proceso con uno de los valores: "en cola", "uniéndose", "grabando", "transcribiendo", "completado", "fallido".
2. WHEN el Estado_De_Proceso de una Reunion cambia, THE Servicio_De_Reuniones SHALL registrar el nuevo estado junto con su marca de tiempo.
3. IF la reunión de Google Meet asociada a una Reunion en cola es cancelada antes de la unión, THEN THE Servicio_De_Reuniones SHALL cambiar el Estado_De_Proceso de la Reunion a "fallido" y registrar la causa "reunión cancelada".
4. WHEN el Estado_De_Proceso de una Reunion cambia a "fallido", THE Servicio_De_Reuniones SHALL registrar una causa de fallo seleccionada entre "no pudo unirse", "reunión cancelada" y "fallo del motor".
5. WHEN un Usuario_Comercial consulta una Reunion, THE Servicio_De_Reuniones SHALL exponer el Estado_De_Proceso actual y, si aplica, la causa de fallo registrada.

### Requerimiento 5: Abstracción e intercambiabilidad del motor de transcripción

**Historia de usuario:** Como responsable técnico de sauri, quiero que el motor de transcripción sea una pieza enchufable y abstraída, para que en el futuro pueda conectar un modelo de transcripción local sin reescribir el sistema.

#### Criterios de Aceptación

1. THE Servicio_De_Reuniones SHALL interactuar con el Motor_ASR únicamente a través de una interfaz común que sea independiente del Proveedor_De_Transcripcion concreto.
2. THE sauri SHALL permitir seleccionar el Proveedor_De_Transcripcion activo mediante configuración, sin modificar el código del Servicio_De_Reuniones.
3. WHERE se configura un Proveedor_De_Transcripcion de procesamiento local, THE sauri SHALL procesar la Grabacion_De_Audio sin enviarla a un servicio externo.
4. WHERE se configura un Proveedor_De_Transcripcion de procesamiento externo, THE sauri SHALL enviar la Grabacion_De_Audio al servicio externo configurado para su procesamiento.
5. WHEN se sustituye el Proveedor_De_Transcripcion activo por otro que implemente la interfaz común, THE Servicio_De_Reuniones SHALL continuar produciendo Transcripciones sin cambios en su código.

### Requerimiento 6: Privacidad, consentimiento y retención de datos

**Historia de usuario:** Como responsable de cumplimiento de Summan, quiero que sauri notifique la grabación a los participantes y aplique reglas de retención de datos, para que el tratamiento de datos personales cumpla con la normativa colombiana.

#### Criterios de Aceptación

1. WHEN el Asistente_De_Reunion es admitido en una reunión de Google Meet, THE sauri SHALL emitir una Notificacion_De_Grabacion visible para los Participantes indicando que la reunión está siendo grabada y transcrita por sauri.
2. THE sauri SHALL conservar cada Grabacion_De_Sesion y cada Transcripcion durante un periodo de retención configurable.
3. WHEN el periodo de retención configurado para una Grabacion_De_Sesion o una Transcripcion expira, THE sauri SHALL eliminar el dato correspondiente, incluyendo la Pista_De_Audio y la Pista_De_Video de la Grabacion_De_Sesion.
4. THE sauri SHALL tratar las Grabaciones_De_Sesion y las Transcripciones como datos personales sujetos a la normativa de protección de datos de Colombia.
5. THE sauri SHALL registrar la emisión de la Notificacion_De_Grabacion asociada a la Reunion.
6. WHERE se configura el periodo de retención, THE sauri SHALL aplicar dicho periodo a la Grabacion_De_Sesion completa para acotar el impacto de almacenamiento de la Pista_De_Video.

### Requerimiento 7: Seguridad de los datos capturados

**Historia de usuario:** Como responsable de seguridad de Summan, quiero que la grabación completa (audio y video) y las transcripciones estén protegidas en reposo y en tránsito, para que la información comercial sensible no quede expuesta.

#### Criterios de Aceptación

1. THE sauri SHALL cifrar cada Grabacion_De_Sesion y cada Transcripcion en reposo.
2. WHEN sauri transmite una Grabacion_De_Sesion o una Transcripcion entre componentes o hacia un Proveedor_De_Transcripcion, THE sauri SHALL usar un canal cifrado en tránsito.
3. THE sauri SHALL restringir el acceso a las Grabaciones_De_Sesion y a las Transcripciones a los Usuarios_Comerciales autorizados.
4. IF una solicitud de acceso a una Grabacion_De_Sesion o a una Transcripcion proviene de un usuario no autorizado, THEN THE sauri SHALL denegar el acceso y registrar el intento.

### Requerimiento 8: Portabilidad de despliegue

**Historia de usuario:** Como responsable técnico de sauri, quiero que el sistema sea portable entre nubes y ejecutable en contenedores, para que pueda desplegarse en GCP o AWS y correr localmente sin reescritura.

#### Criterios de Aceptación

1. THE sauri SHALL empaquetar sus componentes ejecutables en contenedores Docker.
2. THE sauri SHALL ejecutarse en un entorno de desarrollo local mediante contenedores Docker sobre macOS.
3. THE sauri SHALL desplegarse tanto en GCP como en AWS sin depender de APIs propietarias exclusivas de un único proveedor de nube.
4. WHERE una capacidad de infraestructura es provista de forma específica por un proveedor de nube, THE sauri SHALL acceder a dicha capacidad a través de una abstracción que permita una implementación equivalente en el otro proveedor de nube.

### Requerimiento 9: Acceso del equipo comercial

**Historia de usuario:** Como Usuario_Comercial de Summan, quiero acceder a sauri de forma autenticada, para que solo el equipo comercial autorizado pueda registrar reuniones y consultar transcripciones.

#### Criterios de Aceptación

1. WHEN un usuario intenta acceder a sauri, THE sauri SHALL autenticar al usuario antes de permitir el registro de Reuniones o la consulta de Transcripciones.
2. IF un usuario no autenticado intenta registrar una Reunion o consultar una Transcripcion, THEN THE sauri SHALL denegar la operación.
3. THE sauri SHALL permitir el registro de Reuniones y la consulta de Transcripciones únicamente a Usuarios_Comerciales autorizados.
