# Estado de desarrollo de Sauri

- **Revisión:** 2026-10-08
- **Checkout revisado:** `feature/agent-context-policy-cleanup` · commit `828494497d5b4e24821eee615df04b440e9e372f`
- **Alcance:** código fuente, configuración y cableado de backend y frontend web. No se ejecutaron la aplicación ni las pruebas.

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
