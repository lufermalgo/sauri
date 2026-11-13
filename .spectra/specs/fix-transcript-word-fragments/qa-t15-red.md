# T15 / #654 — evidencia RED del adapter y vista por generación

Fecha: 2026-11-13 UTC. Base: `e718170343156c0dbab805f7fab1ee5d32c8811c`.
Spec: bugfix `9fed8e2`, design `bc18206`, tasks `122b6a7` aprobados.
Ejecutor: Ansel, worktree/rama aislados `feature/issue-654-transcript-turns-t15`.

## Alcance

Solo pruebas sintéticas en `frontend/src/api.test.ts` y `frontend/src/components/TranscriptView.test.tsx`. Sin cambios de producción, shared-types, modelos, Compose o datos del dueño. T15 es independiente; T16 no se implementa ni integra antes de T14 y T2. Nahuel ejecuta T9/T10 por separado en backend.

## Comandos observados

Desde `frontend/`:

- `npm ci`: salida 0. Informa 10 vulnerabilidades (3 moderate, 5 high, 2 critical); no se ejecutó audit fix ni se alteraron dependencias.
- Antes de editar, `npm run test -- src/api.test.ts src/components/TranscriptView.test.tsx`: salida 0, 2 archivos / 30 pruebas PASS.
- Después de editar, `npm run typecheck`: salida 0.
- `npm run test -- src/api.test.ts src/components/TranscriptView.test.tsx`: salida 1, 2 archivos, **15 fallos / 32 pases / 47 pruebas**. Los 30 casos previos siguen pasando; de 17 nuevos, 15 fallan y 2 pasan.
- `git diff --check`: salida 0.

## Fallos conductuales reproducidos

1. GET review omite el mapa completo de etiquetas y usa `version` en vez del contrato `expected_version`; PUT named/corrected devuelve wire sin adaptar.
2. La vista ignora `labelsBySpeakerId`, pierde el nombre cuando el item ya no está pendiente y después de recarga; lee nombres desde `review.items`.
3. Una review histórica con speaker key coincidente contamina la etiqueta de la generación activa.
4. Assignments NULL/cero/negativos y IDs sin speaker válido se agrupan indebidamente: se ve texto unido donde las expectativas exigen fragmentos separados y `Speaker N`.
5. No se expone el estado terminal `not_reconstructible` ni su presentación fragmentada.
6. Ante un intento posterior pending/failed se conserva el texto, pero no el nombre válido del mapa de la generación completada.
7. Tras Name/Correct, el item desaparece de pendientes y el nombre vuelve a `Speaker 1` en lugar de conservarse desde el mapa.

Son fallos de expectativas/DOM observado, no importaciones, compilación ni setup. Los dos controles nuevos verdes comprueban conservación del payload diarization (revisión/overlap/latest_attempt) y visibilidad de fuentes durante carga/fallo de transporte. El revision_id numérico wire se normaliza a revisionId string conforme al adapter existente; no se inventa un processingRevision adicional en review.

## Límites y cierre

RED no es una entrega funcional, no corrige todavía lo visto por Fer y no se debe fusionar solo ni presentar como PR listo. PR draft conserva las pruebas para la unidad GREEN T16 (#655), dependiente del contrato API T14. No se solicita merge al dueño de esta pieza roja.

No hubo cambios visibles de producto ni recursos Docker creados por esta unidad; no corresponde afirmar recorrido de navegador, audio real, calidad de voces o aceptación. La suite existente emite avisos jsdom de HTMLMediaElement.pause: no representa reproducción real. Logs íntegros y typecheck adjuntos a la tarea APX de T15. Mantener issue #654 abierto hasta validar el conjunto RED→GREEN.
