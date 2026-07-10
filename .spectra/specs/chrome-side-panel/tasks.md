# Implementation Plan: Side Panel de Chrome y Vista de Detalle de Transcripción

## Overview

Plan de implementación incremental del módulo de experiencia de usuario (Side_Panel + Vista_De_Detalle) sobre las capacidades ya construidas por los Milestones 1–3. El módulo **consume** transcripción y diarización desde la API; **no** las recalcula (Req. 14.1, 14.2). Se sigue disciplina TDD estricta **RED → GREEN → REFACTOR** (AGENTS.md §3): cada tarea de prueba se escribe y ejecuta **antes** de su tarea de implementación correspondiente, debe fallar primero, y **nunca** se marca como opcional (`*`).

El módulo abarca **dos frentes con dos runners distintos**, ambos verificados en la Tarea 1:

- **Frontend (`extension/`)**: Vite + `@crxjs/vite-plugin` + React + TypeScript. Pruebas con `vitest` y propiedades con `fast-check` (ambos ya en `extension/package.json` → `devDependencies`). Validación: `npm run typecheck` (`tsc --noEmit`) y `npm test` (`vitest run`) según los scripts existentes.
- **Backend (`backend/`)**: FastAPI + `pytest` (+ Hypothesis donde aplique), reutilizando `backend/tests/conftest.py`.

Las **20 Correctness Properties** del diseño se implementan **una por sub-tarea de prueba** con `fast-check`, mínimo **100 iteraciones** (`fc.assert(fc.property(...), { numRuns: 100 })`), cada una con la etiqueta obligatoria como comentario:
`// Feature: chrome-side-panel, Property {N}: {texto de la propiedad}`.

Todas las propiedades ejercitan **funciones puras** del núcleo compartido (`extension/src/core/`). El render de componentes, el cableado de APIs de Chrome y los contratos HTTP se cubren con pruebas por ejemplo, de integración o de humo (también obligatorias, también RED antes de GREEN).

### Alcance (decisión tomada y vigente)

Las **4 brechas de backend** identificadas en `design.md` están **EN ALCANCE** en este plan:

1. **Nuevo endpoint** `GET /api/v1/reuniones/{id}/diarizacion` (hablantes + asignaciones) — Tarea 13.1/13.2.
2. **Exponer el `id`** de cada `Turno_De_Habla` en `GET /api/v1/reuniones/{id}/transcripcion` (cambio aditivo) — Tarea 13.3/13.4.
3. **Campo `titulo`** (nullable) en `GET /api/v1/reuniones/` (cambio aditivo) — Tarea 13.5/13.6.
4. **Autenticación real**: `POST /api/v1/auth/login` emitiendo JWT con `crear_token` (`backend/app/auth/token.py`), respaldado por un almacén **mínimo** de usuarios autorizados (entidad nueva `Usuario` semillada — **NO** integración con IdP). El bypass `AUTH_DISABLED` se **restringe al entorno de test** (no se elimina del todo) — Tareas 13.7–13.12.

El **resumen con LLM queda FUERA de alcance**: solo se reserva estructuralmente el `Espacio_De_Resumen` con un indicador estático "próximamente" (Req. 7.2, 7.3), sin lógica de generación.

Lenguajes de implementación (definidos por el diseño y el stack existente): **TypeScript** en `extension/`, **Python** en `backend/`.

## Tasks

- [x] 1. Verificar runners de prueba y crear la estructura de paquetes
  - **Frontend**: ejecutar `npm run typecheck` y `npm test` (`vitest run`) en `extension/` para confirmar que `tsc`, `vitest` y `fast-check` funcionan; si algo no corre, dejarlo operativo antes de continuar (AGENTS.md §3: las tareas de implementación no pueden avanzar sin runner).
  - **Backend**: ejecutar `pytest` desde `backend/` (usando `backend/.venv`) para confirmar que el runner y `backend/tests/conftest.py` funcionan.
  - Crear el esqueleto del núcleo compartido `extension/src/core/` (subcarpetas `api/` y `design/`) y de la Vista_De_Detalle `extension/src/detail/`, sin lógica, asegurando que `vitest` y `tsc` descubren los nuevos archivos.
  - _Requisitos: infraestructura de pruebas (AGENTS.md §3)_

- [ ] 2. Sistema_De_Diseno (tokens compartidos)
  - [ ] 2.1 Escribir prueba por ejemplo del contraste del anillo de foco (RED)
    - Verificar que los pares de tokens definidos para el indicador de foco (`--anillo-foco` / `--color-foco`) cumplen una relación de contraste ≥ 3:1 respecto a los colores adyacentes, calculada sobre los valores de `PALETA_AVATAR`/superficie del Sistema_De_Diseno. Ejecutar y confirmar que falla (tokens aún inexistentes).
    - _Requisitos: 12.4_
  - [~] 2.2 Implementar `core/design/tokens.ts` y `core/design/tokens.css` (GREEN)
    - Definir los tokens de color, tipografía, espaciado, radios, elevaciones, `PALETA_AVATAR` y `--anillo-foco`, expuestos como variables CSS y objeto TS, aplicables al Side_Panel y a la Vista_De_Detalle.
    - Ejecutar 2.1 hasta verde; refactorizar manteniéndola verde.
    - _Requisitos: 12.1, 12.2, 12.4_

- [ ] 3. Núcleo: formato de tiempo y avatar de hablante
  - [-] 3.1 Escribir prueba de propiedad de `formatearMarcaDeTiempo` (RED)
    - **Property 1: Formato de Marca_De_Tiempo_Formateada**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 3.9, 8.3, 10.3**
    - Generadores: enteros en `[0, 3_600_000)`, `[3_600_000, ...)`, `0`, negativos y no disponibles (`NaN`/`null`). Confirmar que falla.
  - [~] 3.2 Implementar `core/tiempo.ts` (GREEN)
    - `formatearMarcaDeTiempo(ms)` según la lógica determinista del diseño (trunca a segundos, "MM:SS"/"HH:MM:SS", placeholder "--:--").
    - Ejecutar 3.1 hasta verde; refactorizar.
    - _Requisitos: 11.1, 11.2, 11.3, 11.4, 11.5_
  - [-] 3.3 Escribir prueba de propiedad de avatar determinista (RED)
    - **Property 2: Avatar determinista (iniciales y color cíclico)**
    - **Validates: Requirements 8.4**
    - Generadores: etiquetas arbitrarias y `orden` positivos grandes para verificar ciclicidad sobre `PALETA_AVATAR`. Confirmar que falla.
  - [~] 3.4 Implementar `core/hablantes.ts` (GREEN)
    - `inicialesDeEtiqueta(etiqueta)` (≤ 2 caracteres) y `colorDeAvatar(orden)` cíclico sobre `PALETA_AVATAR` (de `core/design/tokens.ts`).
    - Ejecutar 3.3 hasta verde; refactorizar.
    - _Requisitos: 8.4_

- [ ] 4. Núcleo: título, fecha y proyección de Notas (`core/notas.ts`)
  - [-] 4.1 Escribir prueba de propiedad del placeholder de título (RED)
    - **Property 3: Placeholder de título de Nota**
    - **Validates: Requirements 4.4, 7.5**
    - Generadores: títulos nulos, vacíos, solo-espacios y no vacíos. Confirmar que falla.
  - [ ] 4.2 Escribir prueba de propiedad del formato de fecha (RED)
    - **Property 4: Formato de fecha de la Tarjeta_De_Nota**
    - **Validates: Requirements 4.5**
    - Generadores: instantes válidos; verificar patrón `"D/M, HH:MM"` (D sin relleno, M sin relleno, HH 00–23 dos dígitos, MM 00–59 dos dígitos). Confirmar que falla.
  - [~] 4.3 Escribir prueba de propiedad de proyección de Notas a Tarjetas (RED)
    - **Property 5: Proyección de Notas a Tarjetas (biyección con campos requeridos)**
    - **Validates: Requirements 4.2, 4.3**
    - Generadores: historiales arbitrarios; verificar cardinalidad 1:1 por `reunionId` y presencia de título mostrable + fecha formateada. Confirmar que falla.
  - [~] 4.4 Implementar `core/notas.ts` (GREEN)
    - `tituloParaMostrar(titulo)`, `formatearFechaNota(creadaEn)` y `proyectarTarjetas(notas)` como funciones puras.
    - Ejecutar 4.1, 4.2 y 4.3 hasta verde; refactorizar.
    - _Requisitos: 4.2, 4.3, 4.4, 4.5, 7.5_

- [ ] 5. Núcleo: ordenamientos deterministas (`core/orden.ts`)
  - [~] 5.1 Escribir prueba de propiedad de orden de Notas (RED)
    - **Property 6: Orden de Notas (no creciente por fecha, total y repetible)**
    - **Validates: Requirements 4.6**
    - Generadores: listas con fechas repetidas; verificar orden desc. por fecha, desempate por `reunionId` asc., totalidad e idempotencia. Confirmar que falla.
  - [~] 5.2 Escribir prueba de propiedad de orden de Intervenciones (RED)
    - **Property 10: Orden de Intervenciones por (inicio_ms, orden)**
    - **Validates: Requirements 8.2**
    - Generadores: turnos con `inicio_ms` repetidos; verificar orden asc. por `(inicio_ms, orden)`, totalidad e idempotencia. Confirmar que falla.
  - [~] 5.3 Escribir prueba de propiedad de orden de la Vista_Tiempo_De_Habla (RED)
    - **Property 15: Orden de la Vista_Tiempo_De_Habla**
    - **Validates: Requirements 10.4**
    - Generadores: entradas con tiempos repetidos; verificar orden no creciente por tiempo, desempate por `orden` asc., totalidad e idempotencia. Confirmar que falla.
  - [~] 5.4 Implementar `core/orden.ts` (GREEN)
    - `ordenarNotas`, `ordenarIntervenciones` y `ordenarTiempoDeHabla` con comparadores totales.
    - Ejecutar 5.1, 5.2 y 5.3 hasta verde; refactorizar.
    - _Requisitos: 4.6, 8.2, 10.4_

- [ ] 6. Núcleo: mapeo de Intervenciones y atribución de Hablante (`core/intervenciones.ts`)
  - [~] 6.1 Escribir prueba de propiedad de mapeo de Turnos a Intervenciones (RED)
    - **Property 9: Mapeo de Turnos a Intervenciones (biyección y preservación)**
    - **Validates: Requirements 8.1, 8.5, 14.2**
    - Generadores: transcripciones arbitrarias; verificar 1:1 por `turnoId` y preservación de `texto/inicio_ms/fin_ms/orden`. Confirmar que falla.
  - [~] 6.2 Escribir prueba de propiedad de atribución de Hablante (RED)
    - **Property 11: Atribución de Hablante a la Intervencion**
    - **Validates: Requirements 8.3, 8.7**
    - Generadores: turnos con y sin `Asignacion_De_Hablante`; verificar etiqueta/avatar del hablante asignado o placeholder "hablante no identificado", preservando texto y marca de tiempo. Confirmar que falla.
  - [~] 6.3 Implementar `core/intervenciones.ts` (GREEN)
    - `mapearIntervenciones(transcripcion)` y `atribuirHablante(turno, asignaciones, hablantes)` como proyección de lectura (sin modificar datos, Req. 14.2).
    - Ejecutar 6.1 y 6.2 hasta verde; refactorizar.
    - _Requisitos: 8.1, 8.3, 8.5, 8.7, 14.2_

- [ ] 7. Núcleo: filtros de búsqueda (`core/busqueda.ts`)
  - [~] 7.1 Escribir prueba de propiedad de filtro de Notas como conjunción (RED)
    - **Property 7: Filtro de Notas como conjunción de búsqueda y criterio**
    - **Validates: Requirements 5.1, 5.2, 5.3**
    - Generadores: historiales, textos con mayúsculas/espacios y criterios de filtro; verificar conjunción título∩criterio y que ninguna excluida satisface ambos. Confirmar que falla.
  - [~] 7.2 Escribir prueba de propiedad de búsqueda de Notas inactiva con texto en blanco (RED)
    - **Property 8: Búsqueda de Notas inactiva con texto en blanco**
    - **Validates: Requirements 5.4, 5.6**
    - Generadores: textos vacíos/solo-espacios; verificar que no se excluye ninguna Nota por título. Confirmar que falla.
  - [~] 7.3 Escribir prueba de propiedad de coincidencias de transcripción (RED)
    - **Property 12: Coincidencias del Buscador_De_Transcripcion**
    - **Validates: Requirements 9.1, 9.2, 9.4**
    - Generadores: intervenciones y textos con mayúsculas/espacios; verificar coincidencias case-insensitive, primera por menor `inicio_ms`, y conjunto/orden de intervenciones inalterado. Confirmar que falla.
  - [~] 7.4 Escribir prueba de propiedad de búsqueda de transcripción inactiva con texto en blanco (RED)
    - **Property 13: Búsqueda de transcripción inactiva con texto en blanco**
    - **Validates: Requirements 9.3**
    - Generadores: textos vacíos/solo-espacios; verificar cero coincidencias y orden original conservado. Confirmar que falla.
  - [~] 7.5 Escribir pruebas por ejemplo de los límites de longitud de búsqueda (RED)
    - Verificar el truncamiento/acotación a 100 caracteres en `filtrarNotas` (Req. 5.7) y a 200 caracteres en `coincidenciasDeTranscripcion` (Req. 9.5). Confirmar que fallan.
    - _Requisitos: 5.7, 9.5_
  - [~] 7.6 Implementar `core/busqueda.ts` (GREEN)
    - `filtrarNotas(notas, texto, filtro)` (normaliza trim+minúsculas, conjunción, límite 100) y `coincidenciasDeTranscripcion(intervenciones, texto)` (case-insensitive, conserva orden, límite 200).
    - Ejecutar 7.1–7.5 hasta verde; refactorizar.
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 9.1, 9.2, 9.3, 9.4, 9.5_

- [ ] 8. Núcleo: cálculo del Tiempo_De_Habla (`core/speakerTime.ts`)
  - [~] 8.1 Escribir prueba de propiedad de cálculo y cobertura del Tiempo_De_Habla (RED)
    - **Property 14: Cálculo y cobertura del Tiempo_De_Habla**
    - **Validates: Requirements 10.1, 10.2**
    - Generadores: turnos, asignaciones y hablantes generados conjuntamente, incluyendo hablantes sin turnos (tiempo 0) y turnos sin asignación; verificar una entrada por hablante y suma `(fin_ms - inicio_ms)` correcta. Confirmar que falla.
  - [~] 8.2 Implementar `core/speakerTime.ts` (GREEN)
    - `calcularTiempoDeHabla(turnos, asignaciones, hablantes)` incluyendo hablantes con tiempo 0.
    - Ejecutar 8.1 hasta verde; refactorizar.
    - _Requisitos: 10.1, 10.2_

- [ ] 9. Núcleo: derivación del Estado_De_Vista (`core/vista.ts`)
  - [~] 9.1 Escribir prueba de propiedad de derivación total y exclusiva del Estado_De_Vista (RED)
    - **Property 16: Derivación total y exclusiva del Estado_De_Vista**
    - **Validates: Requirements 4.7, 4.8, 4.9, 6.4, 6.6, 7.6, 8.8, 8.9, 8.10, 10.5, 10.6, 10.7, 12.3, 12.5, 12.6, 12.7, 14.3, 14.4, 14.5**
    - Generadores: `SolicitudRemota` en todas sus fases, con colecciones vacías y no vacías; verificar que retorna exactamente uno de los cuatro estados y conserva `previos` en `error`. Confirmar que falla.
  - [~] 9.2 Implementar `core/vista.ts` (GREEN)
    - `derivarEstadoDeVista(solicitud)` según la tabla del diseño.
    - Ejecutar 9.1 hasta verde; refactorizar.
    - _Requisitos: 12.3, 12.5, 12.6, 12.7_

- [ ] 10. Núcleo: máquina de Estado_De_Captura (`core/captura.ts`)
  - [~] 10.1 Escribir prueba de propiedad de la máquina de Estado_De_Captura (RED)
    - **Property 17: Máquina de Estado_De_Captura**
    - **Validates: Requirements 2.4, 3.3, 3.4, 3.5**
    - Generadores: todos los pares (`Estado_De_Captura`, evento), incluidos pares inválidos; verificar transiciones válidas y conservación del estado en el resto. Confirmar que falla.
  - [~] 10.2 Escribir prueba de propiedad de habilitación del Boton_Nueva_Nota (RED)
    - **Property 18: Habilitación del Boton_Nueva_Nota según el Estado_De_Captura**
    - **Validates: Requirements 2.5**
    - Generadores: los tres `Estado_De_Captura`; verificar deshabilitado sii `grabando`/`deteniendo`. Confirmar que falla.
  - [~] 10.3 Implementar `core/captura.ts` (GREEN)
    - `aplicarEventoCaptura(estado, evento)` y `botonNuevaNotaHabilitado(estado)` como funciones puras.
    - Ejecutar 10.1 y 10.2 hasta verde; refactorizar.
    - _Requisitos: 2.4, 2.5, 3.3, 3.4, 3.5_

- [ ] 11. Núcleo: URL de la Vista_De_Detalle y bloqueo de autenticación
  - [~] 11.1 Escribir prueba de propiedad del round-trip del reunion_id (RED)
    - **Property 19: Round-trip del reunion_id en la URL de la Vista_De_Detalle**
    - **Validates: Requirements 6.2**
    - Generadores: `reunion_id` arbitrarios; verificar que construir la URL y leer el query devuelve el mismo identificador. Confirmar que falla.
  - [~] 11.2 Implementar `core/detailUrl.ts` (GREEN)
    - `construirUrlDetalle(reunionId)` y `leerReunionId(url)` como funciones puras.
    - Ejecutar 11.1 hasta verde; refactorizar.
    - _Requisitos: 6.2_
  - [~] 11.3 Escribir prueba de propiedad del bloqueo por intentos fallidos (RED)
    - **Property 20: Bloqueo de autenticación por intentos fallidos**
    - **Validates: Requirements 13.6**
    - Generadores: secuencias de intentos (éxitos/fallos) con marcas de tiempo dentro y fuera de la ventana de 60 s; verificar `estaBloqueado` verdadero sii ≥ 5 fallos consecutivos y < 60 s desde el quinto. Confirmar que falla.
  - [~] 11.4 Implementar `core/authBloqueo.ts` (GREEN)
    - `estaBloqueado(intentos, ahora)` como función pura determinista.
    - Ejecutar 11.3 hasta verde; refactorizar.
    - _Requisitos: 13.6_

- [~] 12. Checkpoint - Asegurar que todas las pruebas del núcleo pasan
  - Asegurar que todas las pruebas pasan (`npm run typecheck` + `npm test` en `extension/`); preguntar al usuario si surgen dudas.

- [ ] 13. Brechas de backend (FastAPI + pytest, en `backend/`)
  - [~] 13.1 Escribir prueba del contrato de `GET /reuniones/{id}/diarizacion` (RED)
    - En `backend/tests/`, siguiendo el patrón del endpoint de transcripción: verificar `200` con `{diarizacion_id, reunion_id, estado_diarizacion, num_hablantes, hablantes[], asignaciones[]}`, `404` si la Reunion no existe o no tiene Diarizacion, y exigencia de autenticación (`Depends(obtener_usuario_actual)`). Confirmar que falla (endpoint inexistente).
    - _Requisitos: 6.3, 14.1_
  - [~] 13.2 Implementar el endpoint `GET /reuniones/{id}/diarizacion` (GREEN)
    - Añadir el schema de respuesta en `backend/app/reuniones/schemas.py` y la ruta en `backend/app/reuniones/router.py`, recuperando `Hablantes` + `Asignaciones_De_Hablante` con `selectinload`; `404` cuando no hay Diarizacion.
    - Ejecutar 13.1 hasta verde; refactorizar.
    - _Requisitos: 6.3, 8.3, 10.1, 10.2, 14.1, 14.2_
  - [~] 13.3 Escribir prueba del `id` de Turno en `GET /reuniones/{id}/transcripcion` (RED)
    - Verificar que cada elemento de `segmentos` incluye `"id"` (id del `TurnoDeHabla`), sin romper los campos existentes (cambio aditivo). Confirmar que falla.
    - _Requisitos: 8.1, 14.1, 14.2_
  - [~] 13.4 Exponer el `id` del Turno por segmento (GREEN)
    - Añadir `id` al schema de segmento en `backend/app/reuniones/schemas.py` y a la serialización en `router.py`, manteniendo compatibilidad.
    - Ejecutar 13.3 hasta verde; refactorizar.
    - _Requisitos: 8.1, 14.1, 14.2_
  - [~] 13.5 Escribir prueba del campo `titulo` en `GET /reuniones/` (RED)
    - Verificar que cada elemento del historial incluye `"titulo": str | null` (por ahora `null`), sin romper los campos existentes. Confirmar que falla.
    - _Requisitos: 4.3, 4.4_
  - [~] 13.6 Añadir el campo `titulo` (nullable) al historial (GREEN)
    - Añadir `titulo` (nullable, valor `null`) al schema de listado en `backend/app/reuniones/schemas.py` y al `router.py`, sin generar títulos (fuera de alcance).
    - Ejecutar 13.5 hasta verde; refactorizar.
    - _Requisitos: 4.3, 4.4_
  - [~] 13.7 Escribir prueba del modelo `Usuario` y su migración (RED)
    - Verificar el modelo `Usuario` (tabla nueva, p. ej. `usuarios`) y la migración Alembic correspondiente sobre la base de prueba: `upgrade()`/`downgrade()` crea/elimina la tabla con sus restricciones (email único), siguiendo las convenciones de `backend/app/infra/models.py`. Confirmar que falla.
    - _Requisitos: 13.1, 13.2_
  - [~] 13.8 Implementar el modelo `Usuario`, su migración y la semilla mínima (GREEN)
    - Añadir el modelo `Usuario` a `backend/app/infra/models.py` (almacén mínimo de usuarios autorizados, con hash de contraseña — **no** IdP), crear la migración Alembic en `backend/alembic/versions/`, y proveer una semilla mínima determinista de usuarios autorizados.
    - Ejecutar 13.7 hasta verde; refactorizar.
    - _Requisitos: 13.1, 13.2, 13.3_
  - [~] 13.9 Escribir prueba de `POST /auth/login` (RED)
    - En `backend/tests/`: verificar `200` con `{access_token (JWT), token_type: "bearer", expires_in}` para credenciales válidas (token verificable con la utilidad de `token.py`, claims `sub/email/...`), y `401` para credenciales inválidas. Confirmar que falla (router inexistente).
    - _Requisitos: 13.2, 13.3_
  - [~] 13.10 Implementar el Servicio_De_Autenticacion `POST /auth/login` (GREEN)
    - Crear el router de auth en `backend/app/auth/` que valida credenciales contra `Usuario` y emite el JWT con `crear_token` (`backend/app/auth/token.py`); registrarlo en `backend/app/main.py` (que hoy solo registra `ingesta_router` y `reuniones_router`).
    - Ejecutar 13.9 hasta verde; refactorizar.
    - _Requisitos: 13.2, 13.3, 13.5_
  - [~] 13.11 Escribir prueba de la restricción de `AUTH_DISABLED` al entorno de test (RED)
    - Verificar que el bypass `AUTH_DISABLED` de `backend/app/auth/dependencies.py` solo es efectivo en entorno de test y que, fuera de test, los endpoints exigen un JWT válido (la firma de `obtener_usuario_actual` no cambia). Confirmar que falla.
    - _Requisitos: 13.1, 13.4_
  - [~] 13.12 Restringir el bypass `AUTH_DISABLED` al entorno de test (GREEN)
    - Modificar `backend/app/auth/dependencies.py` para acotar la rama de bypass exclusivamente al entorno de test, conservando la protección por JWT en el resto de entornos.
    - Ejecutar 13.11 hasta verde; refactorizar.
    - _Requisitos: 13.1, 13.4_
  - [~] 13.13 Checkpoint backend - Asegurar que todo `pytest` pasa
    - Asegurar que todas las pruebas pasan (`pytest` en `backend/`); preguntar al usuario si surgen dudas.

- [ ] 14. Cliente_De_API compartido (`core/api/client.ts`)
  - [~] 14.1 Escribir prueba de integración del header, almacenamiento y `401` (RED)
    - Con `fetch` y `chrome.storage` simulados: verificar que cada solicitud adjunta `Authorization: Bearer {sesion}` leída de `chrome.storage` (Req. 13.1, 13.3, 14.1) y que un `401` descarta la sesión y dispara la re-autenticación (Req. 13.4). Confirmar que falla.
    - _Requisitos: 13.1, 13.3, 13.4, 14.1_
  - [~] 14.2 Escribir prueba de integración del timeout y el reintento (RED)
    - Verificar el `timeout` de 10 s vía `AbortController` que deriva en fallo (Req. 14.4) y que el reintento re-emite la solicitud (Req. 14.5), conservando datos previos (Req. 4.9, 6.6). Confirmar que falla.
    - _Requisitos: 4.9, 6.6, 14.4, 14.5_
  - [~] 14.3 Escribir prueba por ejemplo de la política de transporte cifrado (RED)
    - Verificar que el cliente exige `https://` para el backend en producción y solo admite `http://localhost` en desarrollo, sin transmitir la sesión por canal no cifrado. Confirmar que falla.
    - _Requisitos: 13.5_
  - [~] 14.4 Implementar `core/api/client.ts` (GREEN)
    - `listarReuniones`, `obtenerTranscripcion`, `obtenerDiarizacion` y `login` contra `BACKEND_URL`, con header Bearer desde `chrome.storage`, `AbortController` (10 s), manejo de `401` y validación de transporte. Mapea respuestas a los DTO del diseño (`NotaDTO`, `TranscripcionDTO`, `DiarizacionDTO`).
    - Ejecutar 14.1, 14.2 y 14.3 hasta verde; refactorizar.
    - _Requisitos: 13.1, 13.3, 13.4, 13.5, 14.1, 14.4, 14.5_

- [ ] 15. Side_Panel (`extension/src/panel/`, manifest y background)
  - [~] 15.1 Escribir prueba de integración del manifiesto y la apertura del Side_Panel (RED)
    - Aserción sobre `extension/manifest.json`: permiso `"sidePanel"` y `side_panel.default_path` presentes, `action.default_popup` ausente (Req. 1.2). Con `chrome.sidePanel`/`chrome.storage.session` simulados: apertura al clic ≤ 2 s (Req. 1.1) e indicación de error con reintento si falla (Req. 1.7). Confirmar que falla.
    - _Requisitos: 1.1, 1.2, 1.7_
  - [~] 15.2 Migrar el manifiesto y el background a `chrome.sidePanel` (GREEN)
    - Migrar `extension/manifest.json` (añadir `"sidePanel"`, `side_panel.default_path`, eliminar `action.default_popup`) y registrar `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true })` en `extension/src/background.ts`, con manejo de error de apertura.
    - Ejecutar 15.1 hasta verde; refactorizar.
    - _Requisitos: 1.1, 1.2, 1.7_
  - [~] 15.3 Escribir prueba por ejemplo del Encabezado_Panel y el Boton_Nueva_Nota (RED)
    - Render: título "REC Notas" (Req. 2.1), botón "+ Nueva nota REC" con estilo primario (Req. 2.2, 2.3), deshabilitado según `Estado_De_Captura` (usa `botonNuevaNotaHabilitado`, Req. 2.5), y mensaje de error si el inicio falla (Req. 2.6). Confirmar que falla.
    - _Requisitos: 2.1, 2.2, 2.3, 2.5, 2.6_
  - [~] 15.4 Implementar `Encabezado_Panel` y `Boton_Nueva_Nota` (GREEN)
    - Componente que usa tokens del Sistema_De_Diseno y `core/captura.ts`; inicia el flujo de grabación (Req. 2.4) y refleja el estado.
    - Ejecutar 15.3 hasta verde; refactorizar.
    - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - [~] 15.5 Escribir prueba por ejemplo de los Controles_De_Captura (RED)
    - Render: Selector_De_Fuente_De_Audio (≥ "Pantalla + audio", Req. 3.1, 3.2), Toggle_De_Captura, Selector_De_Microfono con estado vacío sin micrófonos (Req. 3.7), Boton_De_Ajustes (Req. 3.8), indicador de grabación con cronómetro "MM:SS" usando `formatearMarcaDeTiempo` (Req. 3.9) y error de inicio (Req. 3.10). Confirmar que falla.
    - _Requisitos: 3.1, 3.2, 3.7, 3.8, 3.9, 3.10_
  - [~] 15.6 Implementar `Controles_De_Captura` (GREEN)
    - Componente que reutiliza la enumeración de micrófonos y la lógica de captura existentes, comunica `start-capture`/`stop-capture` al background y aplica las transiciones de `core/captura.ts` (Req. 3.3, 3.4, 3.5).
    - Ejecutar 15.5 hasta verde; refactorizar.
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_
  - [~] 15.7 Escribir prueba por ejemplo de la Lista_De_Notas, Tarjeta_De_Nota, Buscador y Filtro (RED)
    - Render: una Tarjeta_De_Nota por Nota con título (o placeholder) y fecha "D/M, HH:MM" (Req. 4.2–4.5), orden (Req. 4.6), Estados_De_Vista cargando/vacío/error con reintento (Req. 4.7–4.9) usando `derivarEstadoDeVista`, y búsqueda/filtro con debounce 300 ms y estado "vacío" sin resultados (Req. 5.1–5.6). Confirmar que falla.
    - _Requisitos: 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [~] 15.8 Implementar `Lista_De_Notas`, `Tarjeta_De_Nota`, `Buscador_De_Notas` y `Filtro_De_Notas` (GREEN)
    - Componentes que consumen `Cliente_De_API.listarReuniones` (Req. 4.1), aplican `core/notas.ts`, `core/orden.ts`, `core/busqueda.ts` y `core/vista.ts`; la Tarjeta abre la Vista_De_Detalle vía `core/detailUrl.ts` (Req. 6.1).
    - Ejecutar 15.7 hasta verde; refactorizar.
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1_
  - [~] 15.9 Escribir prueba por ejemplo de la Vista_De_Autenticacion (RED)
    - Verificar que, sin Sesion_De_Usuario vigente, se presenta el flujo de login y se bloquea la Lista_De_Notas (Req. 13.2); que un login válido almacena la sesión (Req. 13.3); que el bloqueo por intentos (Req. 13.6, vía `estaBloqueado`) y la indisponibilidad del servicio (Req. 13.7) se reflejan en la UI. Confirmar que falla.
    - _Requisitos: 13.2, 13.6, 13.7_
  - [~] 15.10 Implementar la `Vista_De_Autenticacion` (GREEN)
    - Componente que usa `Cliente_De_API.login` y `core/authBloqueo.ts`, almacena la sesión en `chrome.storage` (Req. 13.3) y re-presenta el flujo ante `401` (Req. 13.4).
    - Ejecutar 15.9 hasta verde; refactorizar.
    - _Requisitos: 13.2, 13.3, 13.4, 13.6, 13.7_
  - [~] 15.11 Escribir prueba por ejemplo del layout responsivo y la persistencia (RED)
    - Verificar el render conjunto de Encabezado + Controles + Lista (Req. 1.4); sin recorte horizontal entre 320–600 px y `overflow-x` por debajo de 320 px (Req. 1.5, 1.6); y la persistencia del `Estado_De_Captura` desde `chrome.storage.session` al re-montar el panel (Req. 1.3). Confirmar que falla.
    - _Requisitos: 1.3, 1.4, 1.5, 1.6_
  - [~] 15.12 Componer el Side_Panel y aplicar el layout responsivo (GREEN)
    - Cablear `App.tsx` componiendo Encabezado, Controles, Lista y Vista_De_Autenticacion; aplicar contenedores fluidos y `overflow-x`; reflejar el estado desde `chrome.storage.session` (`chrome.storage.onChanged`).
    - Ejecutar 15.11 hasta verde; refactorizar.
    - _Requisitos: 1.3, 1.4, 1.5, 1.6_

- [ ] 16. Vista_De_Detalle (`extension/src/detail/`)
  - [~] 16.1 Escribir prueba por ejemplo de la navegación y el reunionId inválido (RED)
    - Verificar que seleccionar una Tarjeta abre `detail.html?reunionId=ID` en una pestaña (Req. 6.1, 6.2, usando `core/detailUrl.ts`) y que un `reunionId` ausente/inválido produce Estado_De_Vista "error" sin emitir solicitudes (Req. 6.5). Confirmar que falla.
    - _Requisitos: 6.1, 6.2, 6.5_
  - [~] 16.2 Implementar la entrada de la Vista_De_Detalle y su cableado (GREEN)
    - Crear `extension/src/detail/` (HTML + React), registrar la entrada en `extension/vite.config.ts` y en `extension/manifest.json` (`web_accessible_resources`); leer `reunionId` del query y orquestar las solicitudes (Req. 6.3).
    - Ejecutar 16.1 hasta verde; refactorizar.
    - _Requisitos: 6.1, 6.2, 6.3, 6.5_
  - [~] 16.3 Escribir prueba por ejemplo de la estructura de la Vista_De_Detalle y el Espacio_De_Resumen (RED)
    - Verificar el render simultáneo de título de Nota (o placeholder, Req. 7.5), Espacio_De_Resumen con indicador estático "próximamente" no interactivo (Req. 7.2, 7.3) y Panel_De_Transcripcion (Req. 7.1), con tokens consistentes (Req. 7.4). Confirmar que falla.
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [~] 16.4 Implementar el layout de la Vista_De_Detalle y el Espacio_De_Resumen (GREEN)
    - Componente raíz que aplica el Sistema_De_Diseno y reserva el Espacio_De_Resumen sin invocar generación de IA.
    - Ejecutar 16.3 hasta verde; refactorizar.
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [~] 16.5 Escribir prueba por ejemplo del Panel_De_Transcripcion y sus estados (RED)
    - Verificar una Intervencion por Turno ordenadas por `(inicio_ms, orden)` (Req. 8.1, 8.2), etiqueta/avatar/marca/texto (Req. 8.3), texto preservado (Req. 8.5), scroll vertical (Req. 8.6), caso sin diarización con placeholder (Req. 8.7), y Estados_De_Vista cargando/vacío/error con reintento (Req. 8.8, 8.9, 8.10, 6.4, 6.6, 14.3). Confirmar que falla.
    - _Requisitos: 6.4, 6.6, 8.1, 8.2, 8.3, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 14.3_
  - [~] 16.6 Implementar el `Panel_De_Transcripcion` y la `Intervencion` (GREEN)
    - Componentes que consumen `Cliente_De_API.obtenerTranscripcion`/`obtenerDiarizacion` y usan `core/intervenciones.ts`, `core/orden.ts`, `core/hablantes.ts`, `core/tiempo.ts` y `core/vista.ts`; regiones con Estado_De_Vista independiente (Req. 14.3).
    - Ejecutar 16.5 hasta verde; refactorizar.
    - _Requisitos: 6.3, 6.4, 6.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 14.1, 14.2, 14.3, 14.4, 14.5_
  - [~] 16.7 Escribir prueba por ejemplo del Buscador_De_Transcripcion (RED)
    - Verificar resaltado case-insensitive ≤ 500 ms (Req. 9.1), desplazamiento a la primera coincidencia por `inicio_ms` (Req. 9.2), limpieza de resaltados con texto en blanco (Req. 9.3), indicación de ausencia de coincidencias (Req. 9.4) y límite de 200 caracteres (Req. 9.5), usando `coincidenciasDeTranscripcion`. Confirmar que falla.
    - _Requisitos: 9.1, 9.2, 9.3, 9.4, 9.5_
  - [~] 16.8 Implementar el `Buscador_De_Transcripcion` (GREEN)
    - Componente que aplica `core/busqueda.ts` sobre las Intervenciones y gestiona el resaltado/desplazamiento sin alterar el orden.
    - Ejecutar 16.7 hasta verde; refactorizar.
    - _Requisitos: 9.1, 9.2, 9.3, 9.4, 9.5_
  - [~] 16.9 Escribir prueba por ejemplo de la Vista_Tiempo_De_Habla (RED)
    - Verificar una entrada por Hablante (incluidos los de tiempo 0) con etiqueta/avatar/tiempo formateado (Req. 10.1, 10.3), orden por tiempo desc. y desempate por `orden` (Req. 10.4), y Estados_De_Vista vacío/cargando/error (Req. 10.5, 10.6, 10.7), usando `calcularTiempoDeHabla` y `core/orden.ts`. Confirmar que falla.
    - _Requisitos: 10.1, 10.3, 10.4, 10.5, 10.6, 10.7_
  - [~] 16.10 Implementar la `Vista_Tiempo_De_Habla` (GREEN)
    - Componente que consume la diarización vía `Cliente_De_API`, aplica `core/speakerTime.ts`, `core/orden.ts`, `core/hablantes.ts` y `core/tiempo.ts`, y gestiona su Estado_De_Vista de forma independiente.
    - Ejecutar 16.9 hasta verde; refactorizar.
    - _Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [~] 17. Checkpoint final - Asegurar que todas las pruebas pasan
  - Asegurar que todas las pruebas pasan: `npm run typecheck` + `npm test` en `extension/` y `pytest` en `backend/`; preguntar al usuario si surgen dudas.

## Notes

- Disciplina TDD estricta (AGENTS.md §3): toda tarea de prueba (propiedad, ejemplo o integración) es **obligatoria** y **nunca** se marca con `*`; se escribe y ejecuta antes de su implementación y debe fallar primero (RED), luego pasar (GREEN) y mantenerse verde tras refactorizar.
- Cada una de las 20 Correctness Properties es una sub-tarea de prueba **separada**, anotada con su número de propiedad y los requisitos que valida.
- Las pruebas de propiedad usan `fast-check` con mínimo **100 iteraciones** (`{ numRuns: 100 }`) y la etiqueta `// Feature: chrome-side-panel, Property {N}: ...`.
- Cada tarea referencia los requisitos que satisface para trazabilidad (mapa 1:1 spec ↔ milestone, AGENTS.md §13).
- La Tarea 1 verifica **ambos** runners (frontend `vitest`/`tsc`, backend `pytest`); las tareas de implementación no avanzan sin runner operativo.
- Las 4 brechas de backend (Tarea 13) están en alcance: endpoint de diarización, `id` de Turno, campo `titulo` y autenticación real con `Usuario` semillado; el bypass `AUTH_DISABLED` se restringe al entorno de test.
- El resumen con LLM queda fuera de alcance: el Espacio_De_Resumen es estructural (Tareas 16.3/16.4).
- Validación final (Tarea 17) conforme a AGENTS.md §5: `tsc --noEmit` + `vitest run` en `extension/` y `pytest` en `backend/`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "3.3", "4.1", "4.2", "4.3", "5.1", "5.2", "5.3", "6.1", "6.2", "7.1", "7.2", "7.3", "7.4", "7.5", "8.1", "9.1", "10.1", "10.2", "11.1", "11.3", "13.1", "13.3", "13.5", "13.7", "13.9", "13.11", "14.1", "14.2", "14.3"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.4", "5.4", "6.3", "7.6", "8.2", "9.2", "10.3", "11.2", "11.4", "13.2", "13.8"] },
    { "id": 3, "tasks": ["3.4", "13.4", "13.10", "14.4"] },
    { "id": 4, "tasks": ["13.6", "13.12"] },
    { "id": 5, "tasks": ["15.1", "15.3", "15.5", "15.7", "15.9", "15.11", "16.1", "16.3", "16.5", "16.7", "16.9"] },
    { "id": 6, "tasks": ["15.2", "15.4", "15.6", "15.8", "15.10", "16.4", "16.6", "16.8", "16.10"] },
    { "id": 7, "tasks": ["15.12", "16.2"] }
  ]
}
```
