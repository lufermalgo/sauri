# Requisitos — Despliegue local integrado de Sauri

## Introducción

Fer confirmó el 12-11-2026 que los servicios centrales de Sauri deben ejecutarse en Docker y los motores de audio directamente en su Mac para utilizar la GPU. Compose ya incluye API, worker, PostgreSQL, almacenamiento S3 y RabbitMQ, pero no el servidor del portal. La auditoría comprobó infraestructura aislada, no el recorrido de grabación completo.

**Idea fuerza:** abrir el portal y utilizar las conexiones reales de Sauri desde un despliegue local reproducible, conservando datos y sin confundir arranque de servicios con procesamiento terminado.

**Autoridad:** conversación APX `th_0eb2f9523cf04772`, mensajes de Fer del 12-11-2026 a las 18:46, 19:10, 19:22 y 19:25 UTC; tarea `task_9e74a2d278d648ad`; arquitectura central `docs/architecture/overview.md` integrada por PR #817. Fase aprobada por Fer mediante merge del PR #819 el 12-11-2026 a las 22:14 UTC, commit `392a958eac37f156d0bbdc0ea6619deafefe0d20`, confirmado en APX. Esta aprobación permite elaborar el diseño; no demuestra implementación ni aceptación de producto.

**No duplicación:** `chrome-recording-completion` conserva captura/carga/apertura; `meeting-review-playback` conserva reproducción y autorización; `portal-visual-design` excluye cambios Compose en su diseño. Ninguna de ellas especifica el despliegue del servidor web. Esta spec cubre esa conexión operativa, no reescribe sus comportamientos.

**Alcance:** servidor del portal junto al núcleo Docker, conexiones reales del navegador a API y medios, distinción de disponibilidad de motores y preservación de recursos durante validación local.

**Exclusiones:** rediseño visual; cuentas nuevas, Google u otro proveedor de identidad; exposición a Internet o despliegue multiusuario; cambios de políticas de acceso, retención o consentimiento; migración de MinIO a RustFS; descarga/duplicación de modelos; nuevas funciones de captura, transcripción o reproducción; limpieza global del equipo.

## Glosario

- **Despliegue_Local:** conjunto de servicios de Sauri ejecutados en el Mac del dueño, con los motores nativos separados.
- **Portal_Web:** aplicación existente que permite iniciar sesión y consultar/reproducir reuniones autorizadas.
- **Núcleo_Docker:** servidor del portal, API, worker, PostgreSQL, almacén S3 y RabbitMQ.
- **Motores_Nativos:** adaptadores existentes de transcripción MLX Whisper y diarización pyannote/MPS ejecutados fuera de Docker.
- **Entorno_Aislado:** recursos y datos sintéticos identificados como exclusivos de una validación, sin reutilizar volúmenes del dueño.

## Requisitos

### Requisito 1: Acceso al portal desde el despliegue

**Historia de Usuario:** Como usuario de Sauri, quiero abrir el portal al levantar la plataforma, sin ejecutar otro servidor manualmente.

#### Criterios de aceptación

1. WHEN se inicia el Despliegue_Local con la configuración requerida, THE Núcleo_Docker SHALL servir el Portal_Web en una dirección local documentada.
2. WHEN se abre o recarga el Portal_Web, THE Despliegue_Local SHALL entregar la aplicación construida y sus recursos sin requerir el servidor de desarrollo de Vite.
3. THE Despliegue_Local SHALL conservar los Motores_Nativos fuera de Docker.

### Requisito 2: Conexiones reales y acceso autorizado

**Historia de Usuario:** Como usuario, quiero consultar y reproducir mis reuniones desde ese portal, sin que un enlace interno de Docker impida acceder a mis archivos.

#### Criterios de aceptación

1. WHEN el Portal_Web solicita una operación existente de API, THE Despliegue_Local SHALL dirigirla a la API real configurada, conservando su autenticación y autorización.
2. WHEN la API entrega un enlace temporal autorizado de medios, THE Despliegue_Local SHALL permitir que el navegador acceda a ese enlace según el contrato de reproducción existente, incluidas lecturas parciales y origen permitido.
3. THE Despliegue_Local SHALL NOT inyectar tokens de usuarios, contraseñas ni credenciales de almacenamiento en los archivos estáticos del Portal_Web.
4. IF una operación o un medio no está disponible, THEN THE Portal_Web SHALL conservar el manejo de error real existente, sin responder con contenido de demostración ni indicar éxito ficticio.

### Requisito 3: Disponibilidad de infraestructura y motores diferenciada

**Historia de Usuario:** Como responsable de Sauri, quiero saber si la plataforma está disponible y si puede procesar audio, sin interpretar un contenedor iniciado como una transcripción exitosa.

#### Criterios de aceptación

1. THE Despliegue_Local SHALL documentar y permitir comprobar por separado acceso al portal, conexión a API/datos/almacenamiento/cola y acceso desde el worker a los Motores_Nativos.
2. IF los Motores_Nativos están detenidos, THEN THE Despliegue_Local SHALL NOT declarar validada la inferencia ni la disponibilidad de transcripciones nuevas.
3. THE Despliegue_Local SHALL conservar los contratos HTTP y controles de credenciales existentes para los Motores_Nativos.

### Requisito 4: Preservación y limpieza acotada

**Historia de Usuario:** Como dueño del equipo, quiero que las pruebas no borren mis grabaciones ni acumulen despliegues desechables.

#### Criterios de aceptación

1. WHEN se valida el despliegue, THE Entorno_Aislado SHALL utilizar recursos propios identificables y datos sintéticos sin modificar los volúmenes del dueño.
2. WHEN termina la validación, THE Entorno_Aislado SHALL retirar sus recursos temporales creados en esa ejecución, comprobando su propiedad antes de eliminarlos.
3. THE Despliegue_Local SHALL NOT ejecutar limpieza global, borrar recursos ajenos ni eliminar datos existentes como condición de arranque.

### Requisito 5: Evidencia y límites de entrega

**Historia de Usuario:** Como dueño del producto, quiero saber qué funciona de verdad y qué falta comprobar.

#### Criterios de aceptación

1. WHEN se presenta la entrega, THE Despliegue_Local SHALL incluir evidencia de navegación real del portal servido por Docker y pruebas de API/medios en el Entorno_Aislado.
2. THE Despliegue_Local SHALL registrar por separado configuración, pruebas automatizadas, recorrido integrado, inferencia real y aceptación del dueño; ninguna de ellas sustituirá a las otras.

No se requieren decisiones nuevas de identidad, retención, gasto o publicación externa para satisfacer estos requisitos. El diseño deberá elegir valores locales concretos y comprobar puertos/conflictos antes de iniciar servicios, sin trasladar esas elecciones técnicas al dueño.
