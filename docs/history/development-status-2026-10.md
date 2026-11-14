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
5. **No existe baseline de producto verificable en este checkout.** No se encontró `docs/product/baseline.md` ni `.spectra/specs/`; por tanto, esta revisión no puede establecer alcance aprobado ni aceptación de producto. La presencia del código no sustituye esa decisión.

## Evidencia y límites de validación

- **Inspeccionado:** fuentes backend y frontend indicadas arriba, `docker-compose.yml`, `backend/pyproject.toml`, `backend/Dockerfile`, scripts de `frontend/package.json`, migraciones y archivos de prueba existentes.
- **Pruebas:** no ejecutadas, conforme al alcance de inspección. Los archivos de prueba muestran cobertura prevista, no resultados actuales.
- **Runtime/despliegue:** no se levantaron contenedores ni servicios y no se probaron credenciales, migraciones, llamadas API ni flujo navegador → API → workers. Estado operativo no verificado.
- **Aceptación:** no se encontró baseline ni registro de aceptación de producto; no se afirma que el producto esté aceptado.

## Próximos pasos priorizados

1. Definir y aprobar `docs/product/baseline.md`; convertir el alcance acordado en criterios comprobables antes de priorizar nuevas capacidades.
2. Cerrar la brecha de diarización: decidir si se soportará local/cloud, completar configuración de servicio y variables, y verificar el recorrido de extremo a extremo.
3. Resolver autorización de propietario para cada ruta de reunión y revisar los controles con pruebas específicas antes de exponer datos entre usuarios.
4. Completar el flujo web de autenticación/obtención del JWT y documentar cómo se sirve/configura el frontend por entorno.
5. Validar desde una configuración limpia: migraciones, pruebas backend y frontend, servicios Compose, integración completa y despliegue objetivo. Registrar comandos, versiones, resultados y limitaciones; no inferirlos de este inventario.

**Implicación de seguridad y privacidad:** las reuniones incluyen medios y transcripciones sensibles; no usar este estado de fuente como autorización para desplegar o procesar datos reales sin verificar autenticación, propiedad, secretos, retención y configuración del entorno.

---

## Plan de entrega por fases y disposición del backlog — 2026-10-22 (v2)

**Snapshot y autoridad.** Este plan ordena el trabajo según la instrucción de Fer del 2026-10-22 registrada en la tarjeta `task_57a01459db35401e`: P1, recorrido end-to-end en el Mac de Fer (captura desde Chrome; cierre de pestaña o Stop; motores nativos; portal web con transcripción y hablantes); P2, resúmenes y plantillas; P3, pulido del portal. No agrega criterios de producto, rendimiento ni calidad. Snapshot reconciliado tras los merges de #533 y #513: `origin/main` `8277e51b6e7b04c1912ab06d461afdba2d861777` (2026-10-22). Inventario de issues y PRs refrescado el 2026-10-22 después de esos merges; las recomendaciones “mantener”, “diferir” y “reconciliar” son propuestas de priorización, no cierres, cambios de alcance ni aceptación de producto.

### Secuencia propuesta

| Fase | Incluye / disposición | Compuerta de salida (sin umbral inventado) |
|---|---|---|
| P1 — recorrido end-to-end en Mac | Prioridad: cerrar primero los bloqueos de migración/Compose y autorización; completar captura/extensión, procesamiento, atribución/corrección y experiencia web de transcripción/reproducción. La finalización por **Stop** ya está confirmada por el baseline: detiene y guarda la grabación e inicia la transcripción. El disparador adicional es cerrar la pestaña Meet; requiere alinear/actualizar baseline y specs antes de implementarse. Si Stop y cierre de pestaña coinciden, el diseño debe evitar doble procesamiento. Mantener las pruebas de seguridad, QA y el ensayo Mac como gates, no como sustitutos de aceptación del producto. | En el Mac autorizado, recorrer la captura y el procesamiento, y revisar transcripción y hablantes en el portal; registrar evidencia reproducible y límites. No declarar aprobado hasta la revisión de Fer del resultado real. |
| P2 — resumen y plantillas | Resúmenes y plantillas son alcance confirmado en el baseline; mantener el spec existente, sin adelantarlo por encima del recorrido P1. Preservar las tareas RED antes de GREEN y separar el trabajo habilitador de cualquier generación real bloqueada por decisiones operativas de motor, datos o costo. | P1 probado; resolver ownership/default/category de plantillas y proveedor/residencia/costo de generación antes de las tareas que dependan de esas decisiones. |
| P3 — portal, notas y biblioteca | Diferir por secuenciación, sin declarar fuera de alcance: notas, biblioteca, búsqueda, metadatos y tags son capacidades confirmadas por el baseline. No iniciar trabajo sin specs aprobadas ni ampliar el plan inmediato por inferencia; cualquier cambio de alcance requiere enmienda del baseline. | Revisión del portal tras P1/P2 y priorización de secuencia para los elementos todavía no planificados. |

### Inventario de specs en el checkout

| Spec | Estado de artefactos en `origin/main` | Fase / recomendación |
|---|---|---|
| `extension-capture-preferences` | `requirements.md` existe; diseño y tareas pendientes. | P1, mantener como entrada de captura. Stop ya está confirmado por el baseline como acción que finaliza y procesa la grabación; el cierre de la pestaña Meet es el disparador adicional pedido por Fer y requiere alinear/aprobar baseline y spec antes de implementarse. El diseño debe evitar doble procesamiento si coinciden ambos eventos. |
| `recording-speaker-review` | requirements/design/tasks; issues abiertos vinculados más abajo. | P1, mantener. Priorizar los gates de ownership, corrección e identidad per-user; ninguna política de voz o retención se amplía aquí. |
| `meeting-review-playback` | requirements/design/tasks; issues abiertos vinculados más abajo. | P1, mantener para la revisión web/transcript/speaker playback y su prueba de navegador. |
| `alembic-version-id-width` | bugfix/design/tasks completos en el repo; issues abiertos #490–#493. | P1, prerequisito técnico al flujo de persistencia; reconciliar la implementación con PR #531 antes de abrir trabajo redundante. |
| `bugfix-migration-009-lineage` | bugfix/design/tasks y evidencia presentes; #407 sigue abierto. | Reconciliar contra PR #531; recomendar marcar el trabajo separado como obsoleto solo después de verificar el merge y que la cobertura del objetivo quedó absorbida. No cerrar issue/card aquí. |
| `meeting-summaries-templates` | requirements/design/tasks; issues abiertos #269–#295 y #420. | P2, mantener como alcance confirmado por el baseline, en espera de P1 y de las decisiones operativas pendientes identificadas en el spec (ownership/default/category y binding del proveedor donde corresponda). |
| `recording-notes` | requirements/design, sin `tasks.md`. | Alcance confirmado por el baseline, diferido en la secuencia; completar design/tasks cuando se priorice, sin pedir decisión de inclusión/exclusión. |
| `recording-library-metadata` | requirements solamente; design/tasks pendientes. | Alcance confirmado por el baseline (biblioteca, búsqueda, metadatos y tags), diferido en la secuencia; no retirar sin enmienda de alcance. |
| `fix-backend-lint-type-baseline` | bugfix/design/tasks; varias issues/PRs abiertos. | Mantenimiento paralelo no bloqueante cuando no compita por archivos ni cupo de publicación. No adelantarlo sobre P1 ni confundirlo con valor de producto. |

### PRs observados (cinco abiertos y un antecedente fusionado)

La captura del inventario, tomada antes de abrir esta PR (#535) el 2026-10-22, registró **5 PRs abiertos**: #531, #528, #527, #526 y #525. La instrucción operativa vigente fija un máximo de **3 PRs abiertos**; por lo tanto, las capturas históricas de 5 PRs (antes de #535), 6 (inmediatamente después de abrir #535 a las 20:17 UTC) y 7 (tras abrir #536 a las 20:23:06 UTC; consulta de las 20:23:51 UTC) documentan cantidades observadas que excedían ese máximo, no slots disponibles ni autorización para publicar. Verificar el conteo vigente y recuperar un cupo antes de cualquier publicación. #533 se fusionó el 2026-10-22 en `b0250f3f158dbe3cb489d9510fd39b8689edddbe`; su sección de factibilidad quedó incorporada en este archivo. El resultado documenta host/caché/configuración y limitaciones; no demuestra inferencia ni integración ejecutada. #513 se fusionó el 2026-10-22 en `8277e51b6e7b04c1912ab06d461afdba2d861777`, que es el `main` vigente con el que esta rama ya se sincronizó. #531 tiene CI `CLEAN`; el cuerpo publicado registra QA PASS en el head `34fb0d25ef079c89157e25bb0fcf82822d5679ab` para upgrade/downgrade/re-upgrade PostgreSQL 16; el flujo E2E de upload sigue sin evidencia reproducible en el body. #528 sigue abierto, pero Fer aprobó el snapshot exacto `f31c1437d002a49849fc577446290ab83d29a584`; falta el merge humano. #527, #526 y #525 permanecen abiertos. #530 está cerrado sin merge y fue supersedido por #533; #532 se cerró al fusionarse #533; #512 se cerró al fusionarse #513. #529 permanece abierta. No cierro ni recomiendo cerrar ningún PR o issue sin autorización.

| PR | Head (abreviado) | Alcance visto | Disposición propuesta |
|---|---|---|---|
| #531 | `34fb0d2` | Converge migración de recibos; `Closes #493`; checks CI `CLEAN`. El cuerpo publicado registra QA PASS para upgrade/downgrade/re-upgrade PostgreSQL 16; no afirma un E2E de upload exitoso. | Mantener como prerequisito P1; no duplicar #407. Verificar cualquier gate E2E pendiente antes de tratar el flujo integrado como validado. |
| #528 | `f31c143` | Enmienda de baseline del portal; Fer aprobó el snapshot exacto según `task_a08baf81140a4073`, pero el PR sigue abierto. | Mantener pendiente de merge humano; aprobación exacta no equivale a incorporación en `main`. |
| #527 | `29df0e7` | Autorización/auditoría de acceso al speaker review; issue #524, card `task_b39399c88bbd418f` done. Nia `PASS`, Zev `NO_ACTIONABLE_FINDINGS` en este head; PR abierto. | Gate P1 satisfecho técnicamente; conservar para merge humano, sin reabrir el card. |
| #526 | `db61f5d` | Frontend playback/transcript; #304. CI, Nia `PASS` y Zev `NO_ACTIONABLE_FINDINGS` en este head; PR abierto. | Mantener en P1; listo para decisión de merge humana, respetando el cupo. |
| #525 | `fbc280b` | Limpieza de lint para #349; PR abierto, verificaciones focalizadas pasaron. | Mantenimiento; postergar su turno de publicación/merge detrás de P1. |
| #513 | `67cc231` | Corrige imagen Compose para #512; Nia `PASS`, CI y smoke test registrados en la tarjeta. PR fusionado el 2026-10-22; #512 cerrada. | Incorporado a `main` en `8277e51`; no requiere acción adicional en este plan. |

### Disposición de todos los issues abiertos de GitHub

La consulta de `gh issue list --state open --limit 200` devolvió **107** issues. Se listan todos por grupo de milestone; cada número es trazable a su issue en `lufermalgo/sauri`. Los issues de tareas Spectra conservan además su card en el `tasks.md` de la spec cuando allí aparece el enlace. “Reconciliar” significa comparar evidencia y solicitar a Fer la resolución del duplicado; no se cerró nada.

| Grupo / issues abiertos (todos) | Disposición propuesta |
|---|---|
| P1 / captura, revisión y playback: #529, #524, #504, #502, #501, #500, #493, #492, #491, #490, #411, #407, #308, #307, #304, #253, #252, #250, #249, #248, #246, #241, #240, #237 | Mantener y ordenar por dependencias P1; #532 ya está cerrado tras el spike de configuración de #533, que no demostró inferencia ni integración; #407 reconciliar después de #531; #411/#524/#504 y #253 son seguridad/aislamiento obligatorios antes de usar datos reales; #500–#502 son habilitadores de prueba. |
| P2 / summaries-templates: #420, #295, #294, #293, #292, #291, #290, #289, #288, #287, #286, #285, #284, #283, #282, #281, #280, #279, #278, #277, #276, #275, #274, #273, #270, #269 | Mantener en el milestone P2, no adelantar a P1. Resolver gates de plantilla/proveedor antes de ejecutar tareas dependientes; mantener RED→GREEN. #420 se trata como habilitador P2 salvo que el diseño confirme prerequisito anterior. |
| Portal/biblioteca (alcance aprobado, secuencia diferida): #227, #226, #225, #224, #223, #222, #221, #220, #219, #218, #217, #216, #215, #214, #212, #211, #210, #209, #208, #207, #206, #205, #204, #203, #202, #201, #200, #199, #198, #197, #196, #195, #194, #193, #192, #191, #189, #188 | Diferir según secuencia, no retirar ni pedir decisión de inclusión/exclusión: biblioteca, búsqueda, filtros, metadatos y tags tienen alcance aprobado; la enmienda portal #528 está aprobada en su snapshot pero aún no fusionada. Ejecutar cuando se prioricen y haya specs aprobadas. |
| Mantenimiento/backend lint: #522, #360, #354, #350, #349, #348, #346, #343, #339, #337, #266, #265, #262, #228 | Mantener en carril de mantenimiento, tras no afectar seguridad/estabilidad P1 y sujeto al cupo. #522 es flakiness de test, no criterio de producto; evitar publicación concurrente sobre los mismos archivos. |
| Políticas/documentación/infra no funcional: #534, #518, #515, #505, #498 | #534 da trazabilidad a esta actualización del plan y permanece abierta hasta el PR; mantener los demás issues donde habiliten el trabajo (image/config, validación o control del límite), publicando de a uno y solo tras recuperar cupo. #512 ya cerró con #513. #505 aporta verificación, no reemplaza prueba Mac. |
| Bugfix de linaje migration 009: #407 | Ya aparece en el grupo P1; reconciliar contra #531, no duplicar; mantener abierto hasta que Fer autorice el cierre de cualquier issue obsoleto. |

**Control de cobertura:** conteos por milestone: speaker-review 10; biblioteca 38; sin milestone 8; alembic-version-id-width 4; migration-009-lineage 1; lint 14; playback 6; summaries-templates 26; total 107. #407 aparece deliberadamente citado también en la nota de reconciliación, pero solo cuenta una vez en el total y en el grupo P1.

### Tablero de tareas, ejecución paralela y cuello de publicación

La consulta del tablero de tareas enumera tarjetas individuales por estado; Zoya confirmó que esta es la vista adecuada para revisar los IDs, sin inferir que un issue abierto equivalga a un card abierto. Entre las tarjetas relevantes verificadas están `task_57a01459db35401e` (este plan), `task_0cf1633eb39f4813` (#532, spike cerrado junto con #533), `task_a08baf81140a4073` (baseline #528, snapshot aprobado por Fer pero PR sin merge), `task_8fb3bb8e18dc4583` (#304 playback), `task_16c458c020924ae0` (#493), `task_573e2dced5d642e8` (plan migration), `task_63a4b48b4fad4f1f` (#513), `task_91e1dcf149424a27` (#530, done), `task_b39399c88bbd418f` (#527, done) y `task_3783b01e7ee246a0` (cola de publicación). No se cerró, reabrió ni reasignó ninguna tarjeta. La lista de tareas no sustituye las referencias explícitas a `tasks.md` ni una revisión de relación issue-card.

**Capacidad recomendada:** dos developers **en total**, contando a Imre: Imre + **un agente developer adicional** (no dos adicionales ni un “clone” del agente). Es una propuesta de capacidad, no una asignación. El trabajo de Imre para #532 se publicó en #533 y ya está fusionado; la parte de infraestructura/Compose asociada a #512 también se incorporó por #513. Hasta confirmar la disponibilidad real de Imre, no despachar un segundo carril que dependa de él; el agente adicional puede tomar frontend playback/E2E (`frontend/`, sin compartir archivos con backend). Con disponibilidad confirmada, los dos carriles aislados pueden ser backend pipeline/speaker-review frente a frontend, serializando tareas del mismo módulo/tabla/migración. #533 ya se fusionó con cambios en `docker-compose.yml`, `.env.example`, `README.md` y `Makefile`; revisar `main` vigente antes de asignar otro carril Compose para evitar duplicar o contradecir ese trabajo. No sumar un tercer agente en paralelo por ahora. El máximo operativo es de 3 PRs abiertos. Las capturas históricas registraron 5 PRs antes de #535, 6 tras abrir #535 a las 20:17 UTC y 7 tras abrir #536 a las 20:23:06 UTC (consulta de las 20:23:51 UTC); son cantidades observadas por encima del máximo, no slots disponibles. Verificar el conteo vigente y recuperar un cupo antes de abrir cualquier PR; el throttle se aplica justo antes de cada publicación.

### Decisiones que requieren a Fer (no resueltas por este plan)

1. Stop ya está aprobado en el baseline: detiene la grabación, la guarda e inicia la transcripción. El único comportamiento adicional solicitado es finalizar al cerrar la pestaña Meet, que requiere alinear y aprobar baseline/spec antes de implementarlo. Diseño debe definir la interacción con Stop y evitar doble procesamiento si ambos eventos coinciden.
2. Selección/criterio de los motores nativos de ASR y diarización, referencia válida para evaluar transcript/speaker quality, clip autorizado y cualquier límite de costo/tiempo. El spike #532/#533 dejó configuración y límites documentados, pero no ejecutó inferencia ni integración, y no aprobó thresholds.
3. #528: Fer aprobó el snapshot exacto `f31c1437d002a49849fc577446290ab83d29a584`; falta el merge humano antes de tratar la enmienda como parte de `main`.
4. Ownership/default/category de plantillas y proveedor/ubicación/costo de resumen antes de tareas que generen contenido real.
5. Notas y biblioteca/metadatos/búsqueda/tags son alcance confirmado y quedan diferidos por secuencia; definir su priorización operativa al planificar, sin presentarlo como decisión de inclusión/exclusión ni retirarlos sin enmienda de baseline.
6. Condiciones de acceso a datos, consentimiento, retención/borrado y credenciales/token del motor en la prueba Mac. El plan no autoriza copiar audio/transcripts/tokens a Git; usar solo el medio sintético o autorizado según el gate aprobado.
7. En la captura pre-publicación de #535, la cola constaba de #531, #528, #527, #526 y #525: cinco PRs abiertos. Inmediatamente después de la apertura de #535 a las 20:17 UTC eran seis; tras abrir #536 a las 20:23:06 UTC, la consulta del 2026-10-22 a las 20:23:51 UTC devuelve siete. Esas son cantidades observadas, todas por encima del máximo operativo de 3 PRs abiertos; no representan slots disponibles. #533 y #513 están fusionadas; sus issues #532 y #512 están cerradas. #530 permanece cerrada sin merge y supersedida por #533; #529 continúa abierta. #534 sigue abierta hasta que se fusione el PR de trazabilidad. Verificar el conteo vigente y recuperar un cupo antes de otra publicación.

**Resumen de disposición:** mantener P1 como prioridad; conservar resúmenes/plantillas en P2 y diferir notas, biblioteca, búsqueda, metadatos y tags por secuencia, no por falta de alcance aprobado; mantener mantenimiento en carril no bloqueante; reconciliar duplicados (sobre todo #407/#531); reflejar #530 cerrada sin merge y supersedida por #533, #532 y #512 cerradas tras los merges de #533/#513, y #529 aún abierta; reconocer que Fer aprobó el snapshot #528, pendiente de merge, y que #534 da trazabilidad a este plan. Este documento es un ordenamiento de trabajo, no un nuevo baseline, requisito, diseño, aceptación de producto ni autorización para iniciar comportamiento fuera de las specs aprobadas.
