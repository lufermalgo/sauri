# Plan de Implementación — enmienda de seguimiento mínimo

Solo R7–11, #892, task_5d2838ff10c446ed. No sustituye tareas/aprobaciones de diseño visual anterior. Responsable: portal-processing-indicator; integración reservada a Fer, sin merge.

## Resumen de Fases
| Fase | Tareas | Dependencias |
|---|---|---|
| Contrato backend | 1.1–1.2 | autorización acotada |
| Portal | 2.1–2.2 | 1.2 |
| Validación y entrega | 3.1–3.2 | 1–2 |

## Fase 1: Contrato backend
### Tarea 1.1: Probar proyección y autorización (P1–P3)
**Archivo:** `backend/tests/meetings/test_processing.py`
**Acción:** Probar ASR parcial, diarización pendiente/activa/fallida/completa, tiempos ausentes, recovery, revisión antigua y rechazo no-owner/no-sales/no-token.
**Criterio de Completado:** pytest del archivo pasa y el snapshot no contiene medios ni texto.
**Dependencias:** Ninguna.
### Tarea 1.2: Lectura del estado real
**Archivo:** `backend/app/meetings/processing.py`, `backend/app/meetings/router.py`
**Acción:** Agregar GET processing autorizado y proyección del claim, transcript y última revisión correspondiente. Sin migración ni cambio de motores ni del estado de negocio.
**Criterio de Completado:** Tests 1.1 pasan; ASR solo nunca produce ready.
**Dependencias:** 1.1.

## Fase 2: Portal mínimo
### Tarea 2.1: Indicador reusable y polling
**Archivo:** `frontend/src/api.ts`, `frontend/src/components/ProcessingIndicator.tsx`
**Acción:** Consultar GET cada 2000 ms sin solapar, distinguir fallo de consulta, limpiar timers y respuestas antiguas, permitir reintentar solo lectura; etiquetas españolas sin porcentaje/ETA. Exponer callback ready confirmado.
**Criterio de Completado:** Tests Vitest cubren P4/P5 y ready no se invoca con snapshot viejo o parcial.
**Dependencias:** 1.2.
### Tarea 2.2: Conectar carga y reapertura
**Archivo:** `frontend/src/components/SpeakerRecognitionTestScreen.tsx`, `frontend/src/App.tsx`
**Acción:** Reemplazar fin prematuro por ready real y añadir indicador al abrir reunión existente, sin tocar playback/atribución; informar subida indeterminada.
**Criterio de Completado:** Subida y consulta fallida no muestran listo; reunión se consulta sin subir archivo nuevo.
**Dependencias:** 2.1.

## Fase 3: Validación y entrega
### Tarea 3.1: Regresiones y comandos
**Archivo:** `backend/tests/meetings/test_processing.py`, `frontend/src/components/ProcessingIndicator.test.tsx`
**Acción:** Ejecutar pytest relevante, ruff/mypy del backend y npm test/typecheck/build del frontend; revisar diff. Registrar fallos previos sin ocultarlos.
**Criterio de Completado:** Evidencia de comandos con resultado y límites.
**Dependencias:** 1.2, 2.2.
### Tarea 3.2: Validación real coordinada y PR sin merge
**Archivo:** `docs/engineering/portal-processing-indicator.md`
**Acción:** Documentar conexión exacta del candidato sin cambiar datos/cuenta. Publicar commit y PR #892; Ansel coordina APX contra carga/proceso real autorizado, sin duplicar privados.
**Criterio de Completado:** PR vinculado, sin merge; evidencia APX real o límite explícito pendiente, no mocks como validación real.
**Dependencias:** 3.1.


## Inventario de ejecución (2026-11-13)
- [x] 1.1–1.2: proyección y autorización implementadas; tests backend pasan.
- [x] 2.1–2.2: polling reusable, estados separados y carga/reapertura conectados. Se conserva acceso al contenido parcial existente (no se declara listo), refrescado al confirmarse ejecución nueva; no se modifica playback.
- [x] 3.1: 192 backend pertinentes pasan / 3 skips, 106 frontend pasan, typecheck/build y ruff/mypy de archivos modificados pasan; deuda global contrastada con base y documentada.
- [~] 3.2: PR borrador #894 publicado (código 8bb2c17), sin merge; prueba APX de procesamiento real y captura del indicador pendientes de coordinación de Ansel, login y conexión del candidato. No se declara aceptación ni validación visible.

Dependencia detectada: lectura `/diarization` multirrevisión de #653; no se duplica ni se modifica atribución. Instrucciones y evidencia: `docs/engineering/portal-processing-indicator.md`.
