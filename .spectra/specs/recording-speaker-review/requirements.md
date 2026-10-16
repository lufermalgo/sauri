# Requisitos — Procesamiento de grabaciones y revisión de hablantes

## Introducción

Después de guardar una grabación detenida, Sauri debe producir una transcripción e intentar identificar automáticamente a quienes hablan. La atribución debe distinguir lo que el sistema reconoce de lo que no puede atribuir con confianza: una persona reconocida aparece por su nombre; una voz desconocida o una atribución incierta permanece como `Speaker N` hasta que la persona usuaria la revise. La revisión humana permite escuchar evidencia de audio, asignar una identidad a hablantes sin identificar y corregir nombres automáticos incorrectos.

La revisión no se considera terminada si la persona usuaria la deja incompleta: se resuelve hablante por hablante, y solo alcanza Revisión_Completa cuando todo hablante presentado tiene una disposición explícita registrada (nombrar, corregir o confirmar la atribución). Al abandonar una revisión no completa, Sauri la mantiene como Revisión_Pendiente y vuelve a solicitarla al regresar a esa grabación, sin cerrarla como terminada. Las asociaciones de nombre/identidad guardadas por una persona usuaria son sus propios datos/preferencias y pueden ayudar al reconocimiento en grabaciones posteriores de esa misma persona usuaria. No se comparten con otras personas usuarias. Una corrección de identificación automática debe influir en reconocimientos futuros para esa misma persona usuaria, sin implicar compartición entre usuarios ni entrenamiento global.

**Idea fuerza:** la identificación automática debe ser explícita sobre la incertidumbre, permitir corrección humana informada y llevar esas correcciones a reconocimientos futuros.

**Alcance:** este documento cubre únicamente el procesamiento de una grabación almacenada para transcripción e identificación automática de hablantes, la presentación de nombres o `Speaker N`, y la revisión/corrección de esas atribuciones.

**Fuera de alcance:** captura y controles de grabación; biblioteca y metadatos; reproducción y sincronización multimedia general entre la grabación y la transcripción (sin excluir la reproducción del fragmento claro de audio de cada hablante para revisar sus atribuciones, incluida en el requisito 3.2); notas; edición del texto de la transcripción; resúmenes; progreso, tiempos y errores visibles del procesamiento; y cualquier otro módulo o capacidad. Las referencias visuales y el código existente no amplían este alcance.

**Límites abiertos:** no se seleccionan técnicas, modelos, umbrales de confianza ni criterios cuantitativos de calidad; el diseño técnico los deberá definir sin alterar los resultados observables aquí establecidos. Las asociaciones de nombre/identidad, etiquetas y datos de voz pertenecen a la persona usuaria que las guarda y no se comparten con otras personas usuarias; el despliegue multiusuario, la autenticación y los detalles de acceso siguen separados y no se especifican aquí. No se prescribe almacenamiento, gobernanza, política de acceso ni entrenamiento global.

**Autoridad y trazabilidad:** el alcance deriva del `PRODUCT_BASELINE.md` aprobado por Fer el 2026-10-16 para el contenido exacto del commit `f5ff445fd508983740cd6b5a89c08adafcbb9295` (blob `c43cad6515b01a52037ad9cd4e09010a40477fb4`), con la anotación de aprobación en el commit `b071a7c6d2c72613aa42543d15e47b81f4999077`, junto con las decisiones pertinentes de `PRODUCT_DISCOVERY.md` indicadas en cada requisito. El estado de desarrollo existente es evidencia del estado actual únicamente: no constituye aceptación de producto ni autorización para ampliar o conservar comportamiento sin evaluarlo frente a estos requisitos y evidencia.

## Glosario

- **Grabación_Almacenada**: grabación detenida y guardada en Sauri que es objeto de transcripción e identificación/revisión de hablantes.
- **Atribución_Incierta**: caso en que Sauri no reconoce una voz o duda de a qué persona corresponde; no equivale a una identidad confirmada.
- **Etiqueta_Speaker_N**: identificador `Speaker N` mostrado para una voz desconocida o una atribución incierta hasta su revisión humana.
- **Revisión_de_Hablantes**: revisión por la persona usuaria de las atribuciones de los hablantes de una grabación, incluida la escucha de fragmentos claros y la asignación o corrección de nombres/etiquetas.
- **Hablante_en_Revisión**: cada hablante incluido en la Revisión_de_Hablantes de una Grabación_Almacenada y presentado a la persona usuaria para revisarlo.
- **Disposición_por_Hablante**: resultado explícito del paso de la persona usuaria por un Hablante_en_Revisión: asignar un nombre o etiqueta donde había una Etiqueta_Speaker_N, corregir un nombre asignado automáticamente, o indicar que la atribución presentada es correcta. El mecanismo concreto para expresar cada disposición lo define el diseño; estos requisitos no lo prescriben.
- **Revisión_Completa**: estado de una Revisión_de_Hablantes en el que todo Hablante_en_Revisión tiene una Disposición_por_Hablante registrada.
- **Revisión_Pendiente**: estado de una Revisión_de_Hablantes que aún no alcanza Revisión_Completa.
- **Identidad_Establecida**: asociación de nombre/identidad de hablante guardada o definida previamente por una persona usuaria; pertenece a esa persona usuaria y puede reutilizarse para su reconocimiento futuro, pero no se comparte con otras personas usuarias.

## Requisitos

### Requisito 1: Procesamiento de una grabación almacenada

**Historia de Usuario:** Como persona usuaria de Sauri, quiero que una grabación almacenada se transcriba y se procese para identificar hablantes, para poder revisar el contenido con atribuciones de voz.

#### Criterios de Aceptación

1. WHEN una Grabación_Almacenada queda disponible para procesamiento, THE Sauri SHALL iniciar la transcripción y el intento de identificación automática de hablantes de esa grabación.
**Trazabilidad:** `PRODUCT_BASELINE.md` §§2, 4.B, 5 (capacidad “Recording storage, transcription, and automatic speaker identification”), 6; `PRODUCT_DISCOVERY.md` §§2.5, 2.6 paso 4 y paso 5, y §7 “Precisiones sobre captura, diarización, notas, portal y CRM” (2026-10-09). El ejemplo de seis asistentes es ilustrativo, no un máximo.

### Requisito 2: Representación fiel de la atribución

**Historia de Usuario:** Como persona usuaria, quiero distinguir los hablantes reconocidos de los no reconocidos o dudosos, para no confundir una conjetura del sistema con una identificación confirmada.

#### Criterios de Aceptación

1. WHEN Sauri reconoce a un hablante, THE Sauri SHALL mostrar el nombre asociado a esa identidad en lugar de una etiqueta genérica.
2. WHEN una voz es desconocida o su atribución es incierta, THE Sauri SHALL mostrar una Etiqueta_Speaker_N para esa atribución hasta que se revise, sin presentar como confirmada una identidad dudosa.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§2 (resultado deseado 2), 3 (“Honest attribution”), 4.B, 5, 6; `PRODUCT_DISCOVERY.md` §2.5, §2.6 paso 5 y §7 “Precisiones sobre captura, diarización, notas, portal y CRM” (2026-10-09).

### Requisito 3: Revisión humana de hablantes

**Historia de Usuario:** Como persona usuaria, quiero escuchar un fragmento claro y asignar o corregir el nombre de cada hablante, para revisar las atribuciones de la transcripción.

#### Criterios de Aceptación

1. WHEN termina el procesamiento inicial de una Grabación_Almacenada, THE Sauri SHALL solicitar a la persona usuaria que revise los nombres de los hablantes.
2. WHEN se presenta la Revisión_de_Hablantes, THE Sauri SHALL permitir reproducir un fragmento claro de audio de cada hablante incluido en la revisión.
3. WHEN la persona usuaria revisa una atribución con Etiqueta_Speaker_N, THE Sauri SHALL permitir reemplazarla por un nombre o etiqueta elegidos por la persona usuaria.
4. WHEN la persona usuaria revisa un nombre asignado automáticamente que es incorrecto, THE Sauri SHALL permitir corregirlo con el nombre o etiqueta elegidos por la persona usuaria.
5. WHEN la persona usuaria registra una Disposición_por_Hablante para un Hablante_en_Revisión, THE Sauri SHALL registrarla para ese hablante sin dar por dispuestos los demás Hablantes_en_Revisión de la misma Revisión_de_Hablantes.
6. WHEN todo Hablante_en_Revisión de una Grabación_Almacenada tiene una Disposición_por_Hablante registrada, THE Sauri SHALL tratar esa Revisión_de_Hablantes como Revisión_Completa y mostrar la transcripción con las atribuciones revisadas correspondientes.
7. WHILE exista al menos un Hablante_en_Revisión sin Disposición_por_Hablante registrada, THE Sauri SHALL tratar esa Revisión_de_Hablantes como Revisión_Pendiente y no como Revisión_Completa.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§2 (resultado deseado 3), 3 (“Human correction matters”), 4.B paso 3 (“For each speaker, the user can play a clear audio excerpt, replace `Speaker N` with a chosen name/label, or correct an automatically assigned name.”) y 4.B paso 4, 5, 6; `PRODUCT_DISCOVERY.md` §2.5, §2.6 paso 5 y §7 “Precisión de diarización e indicador flotante” (2026-10-09). No se derivan controles, diseño visual ni cantidad fija de hablantes de la imagen/modal de referencia; la forma de registrar cada Disposición_por_Hablante y de presentar los hablantes pendientes queda al diseño.

### Requisito 4: Persistencia de una revisión incompleta

**Historia de Usuario:** Como persona usuaria, quiero que Sauri recuerde una revisión de hablantes incompleta y vuelva a pedírmela cuando regrese a la grabación, para poder terminarla sin perder de vista atribuciones pendientes.

#### Criterios de Aceptación

1. WHEN la persona usuaria abandona una Revisión_de_Hablantes que aún no es Revisión_Completa, THE Sauri SHALL mantenerla como Revisión_Pendiente y conservar las Disposiciones_por_Hablante ya registradas junto con el conjunto de Hablantes_en_Revisión que aún no tienen una.
2. WHEN la persona usuaria regresa a una Grabación_Almacenada con Revisión_Pendiente, THE Sauri SHALL solicitar nuevamente esa Revisión_de_Hablantes y presentar los Hablantes_en_Revisión sin Disposición_por_Hablante registrada.
3. WHILE exista una Revisión_Pendiente, THE Sauri SHALL NOT tratarla como Revisión_Completa ni cerrarla como terminada, y SHALL NOT dar por revisados los Hablantes_en_Revisión sin Disposición_por_Hablante registrada.
4. WHEN la persona usuaria registra la Disposición_por_Hablante del último Hablante_en_Revisión pendiente, THE Sauri SHALL dejar de solicitar nuevamente esa Revisión_de_Hablantes al regresar a la grabación.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§3 (“Human correction matters”: “incomplete speaker review remains pending and is requested again when the user returns”), 4.B paso 3 y 4 (“If the user leaves before completing review, the review remains pending and is requested again on returning to the recording. It cannot be dismissed as complete without finishing.”), 5, 6; `PRODUCT_DISCOVERY.md` §2.5 y §2.6 paso 5.

### Requisito 5: Reutilización de identidades ante variación acústica

**Historia de Usuario:** Como persona usuaria, quiero que Sauri pueda reutilizar mis identidades ya establecidas aunque cambien las condiciones acústicas, para evitar tratar repetidamente como nuevas a personas ya reconocidas en mis grabaciones.

#### Criterios de Aceptación

1. WHEN una persona con Identidad_Establecida de la persona usuaria actual aparece en una Grabación_Almacenada posterior de esa misma persona usuaria con variaciones acústicas en su voz, THE Sauri SHALL mostrar el nombre previamente establecido para esa atribución; IF la atribución es incierta, THEN THE Sauri SHALL mostrar una Etiqueta_Speaker_N en lugar de asignar otra identidad.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§3 (“Human correction matters”), 4.B paso 5 y 9 (asociaciones por usuario y reutilización para esa misma persona usuaria); la decisión técnica abierta en §7 mantiene sin seleccionar el mecanismo. No se prescribe huella de voz, modelo ni otro mecanismo.

### Requisito 6: Efecto futuro de las correcciones

**Historia de Usuario:** Como persona usuaria, quiero que corregir una identificación automática equivocada influya en el reconocimiento de mis grabaciones futuras, para que la corrección no se limite a la grabación donde la hice.

#### Criterios de Aceptación

1. WHEN la persona usuaria corrige una identificación automática equivocada, THE Sauri SHALL permitir que esa corrección informe el reconocimiento futuro de ese hablante en grabaciones posteriores de esa misma persona usuaria, no solo en la grabación corregida.
2. THE Sauri SHALL NOT compartir con otras personas usuarias las asociaciones de nombre/identidad, etiquetas ni datos de voz guardados por una persona usuaria.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§2 (resultado deseado 3), 3 (“Human correction matters”), 4.B paso 5 y 9 (aclaración del 2026-10-16 sobre asociaciones por usuario, uso futuro para esa misma persona usuaria y ausencia de compartición entre usuarios). La influencia en reconocimientos futuros queda limitada a la misma persona usuaria; no se especifican aquí despliegue multiusuario, autenticación ni detalles de acceso, ni se autoriza entrenamiento global.
