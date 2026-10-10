# Requisitos — Procesamiento de grabaciones y revisión de hablantes

## Introducción

Después de guardar una grabación detenida, Sauri debe producir una transcripción e intentar identificar automáticamente a quienes hablan. La atribución debe distinguir lo que el sistema reconoce de lo que no puede atribuir con confianza: una persona reconocida aparece por su nombre; una voz desconocida o una atribución incierta permanece como `Speaker N` hasta que la persona usuaria la revise. La revisión humana permite escuchar evidencia de audio, asignar una identidad a hablantes sin identificar y corregir nombres automáticos incorrectos.

La revisión no se considera terminada si la persona usuaria la deja incompleta. Al regresar a esa grabación, Sauri vuelve a solicitar la revisión pendiente. Las identidades ya establecidas deben poder reutilizarse pese a variaciones acústicas, y una corrección de identificación automática debe influir en el reconocimiento futuro en toda Sauri.

**Idea fuerza:** la identificación automática debe ser explícita sobre la incertidumbre, permitir corrección humana informada y llevar esas correcciones a reconocimientos futuros.

**Alcance:** este documento cubre únicamente el procesamiento de una grabación almacenada para transcripción e identificación automática de hablantes, la presentación de nombres o `Speaker N`, y la revisión/corrección de esas atribuciones.

**Fuera de alcance:** captura y controles de grabación; biblioteca y metadatos; reproducción y sincronización multimedia general entre la grabación y la transcripción (sin excluir la reproducción del fragmento claro de audio de cada hablante para revisar sus atribuciones, incluida en el requisito 3.2); notas; edición del texto de la transcripción; resúmenes; progreso, tiempos y errores visibles del procesamiento; y cualquier otro módulo o capacidad. Las referencias visuales y el código existente no amplían este alcance.

**Límites abiertos:** no se seleccionan técnicas, modelos, umbrales de confianza ni criterios cuantitativos de calidad; el diseño técnico los deberá definir sin alterar los resultados observables aquí establecidos. La disponibilidad de identidades entre usuarios, su compartición y los permisos/accesos siguen abiertos y no se autorizan por estos requisitos. La expectativa de reutilización y efecto futuro no decide cómo se almacenan o gobiernan los datos de identidad.

**Autoridad y trazabilidad:** el alcance deriva del `PRODUCT_BASELINE.md` marcado como aprobado en este checkout (HEAD `3cdb3ea1404d2b25a9ec4a0ee56c7e51b9b22e9d`, blob `fc498d2f0b79b780725238be388b61b908381811`), cuyo encabezado atribuye la aprobación al contenido publicado en `d738e78` (blob `6c6a3c3e7d7c761dc307d2313e8d3e899ce7ae13`), junto con las decisiones pertinentes de `PRODUCT_DISCOVERY.md` indicadas en cada requisito. El estado de desarrollo existente es evidencia del estado actual únicamente: no constituye aceptación de producto ni autorización para ampliar o conservar comportamiento sin evaluarlo frente a estos requisitos y evidencia.

## Glosario

- **Grabación_Almacenada**: grabación detenida y guardada en Sauri que es objeto de transcripción e identificación/revisión de hablantes.
- **Atribución_Incierta**: caso en que Sauri no reconoce una voz o duda de a qué persona corresponde; no equivale a una identidad confirmada.
- **Etiqueta_Speaker_N**: identificador `Speaker N` mostrado para una voz desconocida o una atribución incierta hasta su revisión humana.
- **Revisión_de_Hablantes**: revisión por la persona usuaria de las atribuciones de los hablantes de una grabación, incluida la escucha de fragmentos claros y la asignación o corrección de nombres/etiquetas.
- **Revisión_Pendiente**: estado de una Revisión_de_Hablantes que la persona usuaria aún no ha completado.
- **Identidad_Establecida**: identidad de hablante definida mediante una identificación previa o una corrección/asignación humana.

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
5. WHEN la persona usuaria completa la revisión de una grabación, THE Sauri SHALL mostrar la transcripción con las atribuciones revisadas correspondientes.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§2 (resultado deseado 3), 3 (“Human correction matters”), 4.B, 5, 6; `PRODUCT_DISCOVERY.md` §2.5, §2.6 paso 5 y §7 “Precisión de diarización e indicador flotante” (2026-10-09). No se derivan controles, diseño visual ni cantidad fija de hablantes de la imagen/modal de referencia.

### Requisito 4: Persistencia de una revisión incompleta

**Historia de Usuario:** Como persona usuaria, quiero que Sauri recuerde una revisión de hablantes incompleta y vuelva a pedírmela cuando regrese a la grabación, para poder terminarla sin perder de vista atribuciones pendientes.

#### Criterios de Aceptación

1. WHEN la persona usuaria abandona la Revisión_de_Hablantes antes de completarla, THE Sauri SHALL mantener esa revisión como Revisión_Pendiente.
2. WHEN la persona usuaria regresa a una grabación con Revisión_Pendiente, THE Sauri SHALL solicitar nuevamente la revisión de hablantes pendiente.
3. WHILE exista una Revisión_Pendiente, THE Sauri SHALL NOT tratarla como completada.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§3 (“Human correction matters”), 4.B pasos 3–4, 5, 6; `PRODUCT_DISCOVERY.md` §2.5 y §2.6 paso 5.

### Requisito 5: Reutilización de identidades ante variación acústica

**Historia de Usuario:** Como persona usuaria, quiero que Sauri pueda reutilizar identidades ya establecidas aunque cambien las condiciones acústicas, para evitar tratar repetidamente como nuevas a personas ya reconocidas.

#### Criterios de Aceptación

1. WHEN una persona con Identidad_Establecida aparece en una Grabación_Almacenada posterior con variaciones acústicas en su voz, THE Sauri SHALL mostrar el nombre previamente establecido para esa atribución; IF la atribución es incierta, THEN THE Sauri SHALL mostrar una Etiqueta_Speaker_N en lugar de asignar otra identidad.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§3 (“Human correction matters”), 4.B paso 5, 5, 6 y 7 (decisión técnica abierta 2); `PRODUCT_DISCOVERY.md` §2.5, §2.6 paso 5, §7 “Plataforma interna e identificación de hablantes” y §7 “Precisiones sobre captura, diarización, notas, portal y CRM” (2026-10-09). No se prescribe huella de voz, modelo ni otro mecanismo.

### Requisito 6: Efecto futuro de las correcciones

**Historia de Usuario:** Como persona usuaria, quiero que corregir una identificación automática equivocada influya en reconocimientos futuros en Sauri, para que la corrección no se limite a la grabación donde la hice.

#### Criterios de Aceptación

1. WHEN la persona usuaria corrige una identificación automática equivocada, THE Sauri SHALL aplicar esa corrección al reconocimiento futuro de ese hablante en toda la plataforma Sauri, no solo en la grabación corregida.

**Trazabilidad:** `PRODUCT_BASELINE.md` §§2 (resultado deseado 3), 3 (“Human correction matters”), 4.B paso 5, 5, 6 y 7 (decisión abierta 1); `PRODUCT_DISCOVERY.md` §2.5, §7 “Alcance de corregir una identificación automática” (decisión confirmada, 2026-10-09) y §7 “Plataforma interna e identificación de hablantes”. La influencia futura en Sauri está definida; identidad entre usuarios y permisos no.
