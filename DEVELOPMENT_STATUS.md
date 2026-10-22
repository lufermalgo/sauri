# Estado de desarrollo de Sauri

- **Revisión:** 2026-10-08
- **Checkout revisado:** `feature/agent-context-policy-cleanup` · commit `828494497d5b4e24821eee615df04b440e9e372f`
- **Alcance:** código fuente, configuración y cableado de backend y frontend web. No se ejecutaron la aplicación ni las pruebas.

## Actualización: spike de motores nativos en Mac (2026-10-22)

En el checkout de este spike se verificó un host arm64 Apple M3 y que `whisper-cli 1.9.2 --version`
inicializa backend Metal. Esto no demuestra inferencia. Existe una caché MLX de
`mlx-community/whisper-large-v3-turbo` (snapshot `a4aaeec…`); no se inspeccionó su contenido. No se
encontró un modelo whisper.cpp en las ubicaciones comunes revisadas. Los Python locales inspeccionados
no tienen MLX, `mlx-whisper`, torch ni pyannote; tampoco se encontró caché pyannote en el Hub por
defecto. No se instalaron paquetes, no se midió su tamaño, no se ejecutó MPS ni se inició Compose.

El Compose de este spike mantiene API, worker, PostgreSQL, MinIO y RabbitMQ; sus URLs locales apuntan
a procesos del host vía `host.docker.internal` (ASR 8001, diarización 8002). No se verificó que los
motores nativos dispongan de servidores HTTP compatibles con `/transcribe` y `/diarize`, ni se probó
la integración. En consecuencia, la configuración es un punto de conexión esperado, no evidencia de
que el pipeline se ejecute. Para completar el spike hacen falta el clip autorizado disponible en el
entorno del dueño, las dependencias/cachés ya instaladas, endpoints compatibles ejecutándose en el
host y evidencia de MPS/Metal real. No copiar tokens, modelos ni datos de audio/transcripción al
repositorio o logs.

## Evaluación ejecutiva

El repositorio contiene un **prototipo técnico/MVP en desarrollo**, con una base de backend sustancial y una interfaz web mínima. Hay rutas, persistencia, colas y workers implementados en código; esto no demuestra que el flujo integrado funcione en un entorno desplegado. La web solo cubre registro/listado de reuniones y consulta de transcripciones. No hay evidencia aquí de aceptación del producto ni de preparación para producción.

## Backend: implementación observada

- FastAPI registra rutas de autenticación, ingestión y reuniones, además de `/health` (`backend/app/main.py`). Las rutas de reuniones incluyen alta/listado/consulta, cambio de título, borrado, solicitud de unión, transcripción y diarización (`backend/app/meetings/router.py`).
- La ingestión valida metadatos, guarda medios en almacenamiento de objetos y publica trabajo de transcripción; los servicios usan PostgreSQL/SQLAlchemy y la cola RabbitMQ (`backend/app/ingestion/`, `backend/app/infra/`).
- El worker procesa transcripción, persiste segmentos y programa diarización; el worker de retención elimina registros expirados (`backend/app/worker.py`, `backend/app/transcription/worker.py`, `backend/app/diarization/worker.py`, `backend/app/retention/worker.py`).
- Hay autenticación JWT local y control de acceso básico por usuario comercial (`backend/app/auth/`). El propio router describe el login como no integrado con el IdP de Summan (`backend/app/auth/router.py`).
- Existen proveedores local y cloud para ASR; el factory de diarización solo acepta `local` (`backend/app/transcription/factory.py`, `backend/app/diarization/factory.py`).

## Frontend web: implementación observada

- SPA React/Vite con formulario de registro de enlace Meet, listado/estado de reuniones y vista de transcripción (`frontend/src/App.tsx`, `frontend/src/components/`, `frontend/src/api.ts`).
- El cliente envía un JWT leído de `localStorage`, pero el frontend no ofrece una pantalla/flujo de inicio de sesión para obtenerlo. La vista web no presenta diarización ni funcionalidades administrativas o analíticas.
- `frontend/package.json` define scripts de build, typecheck y test; que existan no significa que se hayan ejecutado ni que estén pasando.

## Brechas e integración

1. **Diarización no está cableada en Compose.** `app.worker` se suscribe al trabajo de diarización y el factory requiere `DIARIZATION_LOCAL_URL`, pero `docker-compose.yml` no define un servicio de diarización ni configura esa variable en el worker. El código del motor requiere además un token de Hugging Face para cargar el modelo (`backend/diar-engine/main.py`). No se verificó ejecución.
2. **La aplicación web no está incluida en Compose.** El archivo define API, worker, PostgreSQL, MinIO, RabbitMQ y ASR, no un servicio frontend. La publicación/servido de la web requiere configuración aparte.
3. **Autenticación operativa incompleta para uso real.** El login es local y no usa el IdP de Summan. Compose proporciona por defecto un `JWT_SECRET` de desarrollo; debe sustituirse por un secreto gestionado antes de cualquier despliegue no local. Aunque Compose establece `AUTH_DISABLED=true`, el bypass del código solo se activa con `APP_ENV=test`, por lo que esa variable sola no demuestra que la autenticación esté desactivada.
4. **Revisar autorización por propietario antes de uso multiusuario.** Listado, renombrado y borrado filtran/comprueban `created_by`; las rutas de consulta individual, transcript, diarización y solicitud de unión requieren JWT, pero no comprueban que la reunión pertenezca al usuario autenticado (`backend/app/meetings/router.py`).
5. **No existe baseline de producto verificable en este checkout.** No se encontró `PRODUCT_BASELINE.md` ni `.spectra/specs/`; por tanto, esta revisión no puede establecer alcance aprobado ni aceptación de producto. La presencia del código no sustituye esa decisión.

## Evidencia y límites de validación

- **Inspeccionado:** fuentes backend y frontend indicadas arriba, `docker-compose.yml`, `backend/pyproject.toml`, `backend/Dockerfile`, scripts de `frontend/package.json`, migraciones y archivos de prueba existentes.
- **Pruebas:** no ejecutadas, conforme al alcance de inspección. Los archivos de prueba muestran cobertura prevista, no resultados actuales.
- **Runtime/despliegue:** no se levantaron contenedores ni servicios y no se probaron credenciales, migraciones, llamadas API ni flujo navegador → API → workers. Estado operativo no verificado.
- **Aceptación:** no se encontró baseline ni registro de aceptación de producto; no se afirma que el producto esté aceptado.

## Próximos pasos priorizados

1. Definir y aprobar `PRODUCT_BASELINE.md`; convertir el alcance acordado en criterios comprobables antes de priorizar nuevas capacidades.
2. Cerrar la brecha de diarización: decidir si se soportará local/cloud, completar configuración de servicio y variables, y verificar el recorrido de extremo a extremo.
3. Resolver autorización de propietario para cada ruta de reunión y revisar los controles con pruebas específicas antes de exponer datos entre usuarios.
4. Completar el flujo web de autenticación/obtención del JWT y documentar cómo se sirve/configura el frontend por entorno.
5. Validar desde una configuración limpia: migraciones, pruebas backend y frontend, servicios Compose, integración completa y despliegue objetivo. Registrar comandos, versiones, resultados y limitaciones; no inferirlos de este inventario.

**Implicación de seguridad y privacidad:** las reuniones incluyen medios y transcripciones sensibles; no usar este estado de fuente como autorización para desplegar o procesar datos reales sin verificar autenticación, propiedad, secretos, retención y configuración del entorno.

---

## Plan de entrega por fases y disposición del backlog — 2026-10-22 (v2)

**Snapshot y autoridad.** Este plan ordena el trabajo según la instrucción de Fer del 2026-10-22 registrada en la tarjeta `task_57a01459db35401e`: P1, recorrido end-to-end en el Mac de Fer (captura desde Chrome; cierre de pestaña o Stop; motores nativos; portal web con transcripción y hablantes); P2, resúmenes y plantillas; P3, pulido del portal. No agrega criterios de producto, rendimiento ni calidad. Snapshot de repo: `origin/main` `e03c97cebb754bc3e6eb0b9bcdb1eafcf1e76bb6`; inventario de issues consultado alrededor de 15:03 UTC y cola/gates de PR refrescados alrededor de 15:25 UTC el 2026-10-22. Las recomendaciones “mantener”, “diferir” y “reconciliar” son propuestas de priorización, no cierres, cambios de alcance ni aceptación de producto.

### Secuencia propuesta

| Fase | Incluye / disposición | Compuerta de salida (sin umbral inventado) |
|---|---|---|
| P1 — recorrido end-to-end en Mac | Prioridad: cerrar primero los bloqueos de migración/Compose y autorización; completar captura/extensión, procesamiento, atribución/corrección y experiencia web de transcripción/reproducción. Mantener las pruebas de seguridad, QA y el ensayo Mac como gates, no como sustitutos de aceptación del producto. | En el Mac autorizado, recorrer la captura y el procesamiento, y revisar transcripción y hablantes en el portal; registrar evidencia reproducible y límites. No declarar aprobado hasta la revisión de Fer del resultado real. |
| P2 — resumen y plantillas | Mantener el spec existente, sin adelantarlo por encima del recorrido P1. Preservar las tareas RED antes de GREEN y separar el trabajo habilitador de cualquier generación real bloqueada por decisiones de motor, datos o costo. | P1 probado; decisiones de propiedad/default/categoría de plantillas y proveedor/residencia/costo de generación resueltas por el dueño cuando afecten privacidad, costo o comportamiento. |
| P3 — pulido del portal | No iniciar un rediseño amplio ni búsqueda/metadatos por inferencia. Continuar solo con elementos ya aprobados y especificados; cualquier alcance nuevo requiere baseline y spec aprobados. | Revisión del portal tras P1/P2 y priorización explícita del dueño para los detalles todavía abiertos. |

### Inventario de specs en el checkout

| Spec | Estado de artefactos en `origin/main` | Fase / recomendación |
|---|---|---|
| `extension-capture-preferences` | `requirements.md` existe; diseño y tareas pendientes. | P1, mantener como entrada de captura. Alinear el diseño con el cierre de pestaña **y** Stop pedido por Fer; no asumir que el cierre de la pestaña Meet equivale a detener el tab-sharing. |
| `recording-speaker-review` | requirements/design/tasks; issues abiertos vinculados más abajo. | P1, mantener. Priorizar los gates de ownership, corrección e identidad per-user; ninguna política de voz o retención se amplía aquí. |
| `meeting-review-playback` | requirements/design/tasks; issues abiertos vinculados más abajo. | P1, mantener para la revisión web/transcript/speaker playback y su prueba de navegador. |
| `alembic-version-id-width` | bugfix/design/tasks completos en el repo; issues abiertos #490–#493. | P1, prerequisito técnico al flujo de persistencia; reconciliar la implementación con PR #531 antes de abrir trabajo redundante. |
| `bugfix-migration-009-lineage` | bugfix/design/tasks y evidencia presentes; #407 sigue abierto. | Reconciliar contra PR #531; recomendar marcar el trabajo separado como obsoleto solo después de verificar el merge y que la cobertura del objetivo quedó absorbida. No cerrar issue/card aquí. |
| `meeting-summaries-templates` | requirements/design/tasks; issues abiertos #269–#295 y #420. | P2, mantener en espera de P1 y de las decisiones pendientes identificadas en el spec (ownership/default/category y binding del proveedor donde corresponda). |
| `recording-notes` | requirements/design, sin `tasks.md`. | Fuera de las tres fases tal como las fijó esta solicitud. Dejar aparcado, no borrarlo: el baseline vigente incluye notas, pero esta orden no las prioriza; Fer debe decidir si quedan dentro o fuera del plan. |
| `recording-library-metadata` | requirements solamente; design/tasks pendientes. | Aparcar fuera del plan de producto inmediato. Mantener solo lo que sea prerequisite demostrado del portal; búsqueda, tags y metadata no se introducen por inferencia. Solicitar decisión antes de reactivarlo. |
| `fix-backend-lint-type-baseline` | bugfix/design/tasks; varias issues/PRs abiertos. | Mantenimiento paralelo no bloqueante cuando no compita por archivos ni cupo de publicación. No adelantarlo sobre P1 ni confundirlo con valor de producto. |

### PRs abiertos observados

`gh pr list --state open --base main` devolvió **8 PRs**: #533, #531, #530, #528, #527, #526, #525 y #513. El límite operativo actualizado por Fer es **8**; los ocho slots están ocupados, por lo que un PR para este plan sería el noveno y no se debe abrir todavía. Estado observado: #533 `UNSTABLE` (Backend lint/tests pendiente; Web/extension checks passed); #531 `CLEAN` y sus dos checks CI pasan, pero Nia dejó QA `BLOCKED` por el intento E2E de upload `http=0`; #530, #528, #527, #526, #525 y #513 aparecen `CLEAN` en GitHub. Además, el PR #533 ya modifica `DEVELOPMENT_STATUS.md`, el mismo archivo que modifica este plan: después de resolver #533 habrá que reconciliar la rama del plan con `main` antes de abrir su PR. No cierro ni recomiendo cerrar ningún PR sin autorización. Para liberar el slot: recomendar a Fer mergear uno listo (por ejemplo #526 o #513, ambos con gates registrados) o, si confirma que quedó sustituido, autorizar expresamente el cierre de #530. El segundo camino puede perder un cambio todavía útil de Compose; requiere comparar #533 con #530 y no se ejecutará sin autorización.

| PR | Head (abreviado) | Alcance visto | Disposición propuesta |
|---|---|---|---|
| #533 | `a0909be` | Spike docs/config Mac nativo para #532. Web/extension CI pasó; Backend lint/tests sigue pendiente; GitHub marca `UNSTABLE`. | Mantener en P1; completar el check y gates definidos para este spike; no abrir otro PR aún. |
| #531 | `34fb0d2` | Converge migración de recibos; `Closes #493`; checks CI pasaron. Nia QA `BLOCKED`: E2E upload `http=0`, el entorno/candidato no quedó establecido. | Mantener como prerequisito P1, pero no marcarlo listo para merge/flujo real hasta resolver la evidencia de E2E. No duplicar #407. |
| #530 | `ca79103` | Cablea diarization en Compose para #529. Nia `PASS`, Zev `NO_ACTIONABLE_FINDINGS`, ambos checks CI verdes; el ensayo con grabación sigue bloqueado por esquema/migración. | Mantener salvo que Fer confirme que #533 lo sustituye; pedir comparación antes de recomendar obsoleto. No cerrar sin autorización. |
| #528 | `f31c143` | Enmienda de baseline portal; el card `task_a08baf81140a4073` espera aprobación de Fer del snapshot exacto. | Esperar esa decisión; no afirmar que el baseline de portal ya se incorporó ni cerrar el card. |
| #527 | `29df0e7` | Autorización/auditoría de acceso al speaker review; issue #524, card `task_b39399c88bbd418f` done. Nia `PASS`, Zev `NO_ACTIONABLE_FINDINGS` en este head; PR abierto. | Gate P1 satisfecho técnicamente; conservar para merge humano, sin reabrir el card. |
| #526 | `db61f5d` | Frontend playback/transcript; #304. CI, Nia `PASS` y Zev `NO_ACTIONABLE_FINDINGS` en este head; PR abierto. | Mantener en P1; listo para decisión de merge humana, respetando el cupo. |
| #525 | `fbc280b` | Limpieza de lint para #349; PR abierto, verificaciones focalizadas pasaron. | Mantenimiento; postergar su turno de publicación/merge detrás de P1. |
| #513 | `67cc231` | Corrige imagen Compose para #512; Nia `PASS`, sin gate Zev requerido; CI y smoke test registrados en la tarjeta. | Mantener como prerequisito operativo; listo para decisión humana de merge, respetando el cupo. |

### Disposición de todos los issues abiertos de GitHub

La consulta de `gh issue list --state open --limit 200` devolvió **108** issues. Se listan todos por grupo de milestone; cada número es trazable a su issue en `lufermalgo/sauri`. Los issues de tareas Spectra conservan además su card en el `tasks.md` de la spec cuando allí aparece el enlace. “Reconciliar” significa comparar evidencia y solicitar a Fer la resolución del duplicado; no se cerró nada.

| Grupo / issues abiertos (todos) | Disposición propuesta |
|---|---|
| P1 / captura, revisión y playback: #532, #529, #524, #504, #502, #501, #500, #493, #492, #491, #490, #411, #407, #308, #307, #304, #253, #252, #250, #249, #248, #246, #241, #240, #237 | Mantener y ordenar por dependencias P1; #532 es spike/config, no implementación de producto; #407 reconciliar después de #531; #411/#524/#504 y #253 son seguridad/aislamiento obligatorios antes de usar datos reales; #500–#502 son habilitadores de prueba. |
| P2 / summaries-templates: #420, #295, #294, #293, #292, #291, #290, #289, #288, #287, #286, #285, #284, #283, #282, #281, #280, #279, #278, #277, #276, #275, #274, #273, #270, #269 | Mantener en el milestone P2, no adelantar a P1. Resolver gates de plantilla/proveedor antes de ejecutar tareas dependientes; mantener RED→GREEN. #420 se trata como habilitador P2 salvo que el diseño confirme prerequisito anterior. |
| Portal/biblioteca fuera de fases aprobadas: #227, #226, #225, #224, #223, #222, #221, #220, #219, #218, #217, #216, #215, #214, #212, #211, #210, #209, #208, #207, #206, #205, #204, #203, #202, #201, #200, #199, #198, #197, #196, #195, #194, #193, #192, #191, #189, #188 | Aparcar; no ejecutar búsqueda, tags, filtros ni metadata como parte de P3 sin confirmar scope. No cerrar: mapear qué capacidades son prerequisites reales de reabrir una grabación y solicitar decisión del dueño sobre el resto. |
| Mantenimiento/backend lint: #522, #360, #354, #350, #349, #348, #346, #343, #339, #337, #266, #265, #262, #228 | Mantener en carril de mantenimiento, tras no afectar seguridad/estabilidad P1 y sujeto al cupo. #522 es flakiness de test, no criterio de producto; evitar publicación concurrente sobre los mismos archivos. |
| Políticas/documentación/infra no funcional: #518, #515, #512, #505, #498 | Mantener donde habiliten el trabajo (image/config, validación o control del límite); publicar de a uno y solo tras recuperar cupo. #505 aporta verificación, no reemplaza prueba Mac. |
| Bugfix de linaje migration 009: #407 | Ya aparece en el grupo P1; reconciliar contra #531, no duplicar; mantener abierto hasta que Fer autorice el cierre de cualquier issue obsoleto. |

**Control de cobertura:** conteos por milestone: speaker-review 10; biblioteca 38; sin milestone 9; alembic-version-id-width 4; migration-009-lineage 1; lint 14; playback 6; summaries-templates 26; total 108. #407 aparece deliberadamente citado también en la nota de reconciliación, pero solo cuenta una vez en el total y en el grupo P1.

### Board APX, ejecución paralela y cuello de publicación

La consulta de `task_list(state=open, limit=200)` mostró las 35 tarjetas recientes individualmente y agrupó otras 82 en un resumen (backlog 66, review 11, todo 5); la herramienta no expone paginación ni devolvió los 82 IDs/títulos/estados, por lo que no se puede certificar desde esta consulta una lista individual exhaustiva de todas las tarjetas. No inferí que un issue abierto equivalga a un card abierto. Tarjetas verificadas individualmente incluyen `task_57a01459db35401e` (este plan), `task_0cf1633eb39f4813` (#532 spike, con Imre), `task_a08baf81140a4073` (baseline #528, espera confirmación de Fer), `task_8fb3bb8e18dc4583` (#304 playback), `task_16c458c020924ae0` (#493), `task_573e2dced5d642e8` (plan migration), `task_63a4b48b4fad4f1f` (#513), `task_91e1dcf149424a27` (#530, done), `task_b39399c88bbd418f` (#527, done) y `task_3783b01e7ee246a0` (cola de publicación). Los otros IDs de tareas aprobadas quedan trazados en los `tasks.md` bajo las specs arriba; Ansel debe resolver el inventario de tarjetas agregadas antes de archivar o cerrar cards. No se cerró ni se reasignó ningún otro card.

**Capacidad recomendada:** dos developers **en total**, contando a Imre: Imre + **un agente developer adicional** (no dos adicionales ni un “clone” del agente). Es una propuesta de capacidad, no una asignación. El trabajo de Imre para #532 está publicado como PR #533 y en revisión; si requiere correcciones, atender primero ese candidato. Hasta confirmar la disponibilidad real de Imre, no despachar un segundo carril que dependa de él; el agente adicional puede tomar frontend playback/E2E (`frontend/`, sin compartir archivos con backend). Con disponibilidad confirmada, los dos carriles aislados pueden ser backend pipeline/speaker-review frente a frontend, serializando tareas del mismo módulo/tabla/migración. No iniciar simultáneamente el carril Compose (`docker-compose.yml`, `.env.example`, `README.md`, `Makefile`) con cambios de #530 en esos mismos archivos; comparar #533 con #530 antes de asignar trabajo de Compose. No sumar un tercer agente en paralelo por ahora. Con 8 PRs abiertos y máximo 8, el número de **nuevos PR permitidos es 0**; pueden avanzar únicamente tareas autorizadas sin publicar hasta que Fer libere un slot. El throttle se verifica justo antes de cada PR.

### Decisiones que requieren a Fer (no resueltas por este plan)

1. Qué evento exacto es “tab close”: cierre de la pestaña Meet, fin del tab-sharing/captura, o cualquiera; definir precedencia frente a Stop y evitar dos procesamientos del mismo recording.
2. Selección/criterio de los motores nativos de ASR y diarización, referencia válida para evaluar transcript/speaker quality, clip autorizado y cualquier límite de costo/tiempo. El issue #532 y su card son spike, no resultado ni threshold aprobado.
3. Aprobación del snapshot exacto de #528 y su incorporación antes de tratar los cambios del portal como baseline vigente (el card seguía esperando respuesta en la consulta).
4. Ownership/default/category de plantillas y proveedor/ubicación/costo de resumen antes de tareas que generen contenido real.
5. Confirmar si notas y biblioteca/metadatos/search quedan en backlog futuro, se priorizan dentro de P3 o se retiran; no cerrar issues sin esa decisión.
6. Condiciones de acceso a datos, consentimiento, retención/borrado y credenciales/token del motor en la prueba Mac. El plan no autoriza copiar audio/transcripts/tokens a Git/APX; usar solo el medio sintético o autorizado según el gate aprobado.
7. La cola actual es #533, #531, #530, #528, #527, #526, #525 y #513: ocho PRs abiertos contra un límite de ocho; el PR del plan sería #9. Para cumplir el pedido de publicarlo sin exceder el cap, Fer debe liberar un slot: recomendar mergear un PR listo (por ejemplo #526 o #513) o autorizar explícitamente el cierre de #530 si confirma que #533 lo reemplaza. Mientras no haya esa decisión, la rama del plan queda publicada pero sin PR; no cerrar/mergear nada como agente.

**Resumen de disposición:** mantener P1 como prioridad; reservar P2 y aparcar P3 adicional hasta cumplir sus gates; mantener mantenimiento en carril no bloqueante; reconciliar duplicados (sobre todo #407/#531); dejar biblioteca/notas sin decisión, no declararlas obsoletas; y pedir la aprobación del snapshot #528 donde ya está registrada. Este documento es un ordenamiento de trabajo, no un nuevo baseline, requisito, diseño, aceptación de producto ni autorización para iniciar comportamiento fuera de las specs aprobadas.
