# T16 / #655 — corrección del contrato PUT de hablantes

13/11/2026. Base: PR861 `50c9625`; backend de contraste: PR850 `bcc52de`.

## Hallazgo y alcance

En revisión del stack encontré que `DispositionInput` requiere `idempotency_key` en el JSON, mientras `submitSpeakerDisposition` solo lo enviaba en un header. Las pruebas mock de frontend confirmaban un cuerpo incompatible: guardar `named` o `corrected` habría fallado con 422 antes del servicio. Es una corrección técnica del adapter GET/PUT ya incluido en T16, no una nueva política ni funcionalidad. Se conservan autorización, versión esperada, labels y snapshot completo.

## Cambio

Generar una única clave UUID y enviarla tanto en el cuerpo requerido por el backend como en el header existente. Regresión comprueba ambos transportes y su igualdad, para `named` y `corrected`.

## Evidencia ejecutada

- Antes de corregir: `npm run test --workspace frontend -- src/api.test.ts`: 2 failed, 16 passed. Fallan exactamente por la ausencia de `idempotency_key` en JSON.
- Después: `npm run test --workspace frontend -- src/transcript-turns.test.ts src/components/TranscriptView.test.tsx src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts src/api.test.ts`: 87 passed, 5 archivos. Advertencias preexistentes de jsdom `HTMLMediaElement.pause` no implementado; no se ocultaron ni alteraron.
- `npm run typecheck`: PASS en extension/frontend/shared-types.
- `git diff --check`: PASS.
- Python con `DispositionInput` real del worktree backend de PR850 y venv del proyecto: `model_validate` rechaza el cuerpo antiguo específicamente por `idempotency_key` ausente y acepta el cuerpo corregido. No hubo conexión a servicios ni cambios de DB.

## Límites y cierre

Sin runtime/Docker ni datos reales. No hice recorrido interactivo ni envío HTTP autenticado contra el stack: integración UI **UNVERIFIED**. Este resultado no reemplaza gates T14/T19/T20, no resuelve #248 ni las decisiones de privacidad #253/#246. Candidato apilado sobre #861, sin merge. Fer conserva integración; Ansel principal maneja entorno y prueba del video real en paralelo. No hay recursos temporales Docker creados para limpiar.
