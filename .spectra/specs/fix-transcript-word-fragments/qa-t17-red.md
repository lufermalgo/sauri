# T17 / #656 — RED de fidelidad de playback

Base: `8373670`. Spec aprobada: bugfix `9fed8e2`, design `bc18206`, tasks `122b6a7`. Solo tests sintéticos; no producción ni medios del dueño.

## Ejecución observada (13/11/2026 UTC)

Desde frontend:
- `npm run test -- src/components/__tests__/MeetingPlaybackView.test.tsx src/components/__tests__/PlaybackController.test.ts`: baseline **27 PASS**.
- Mismo comando con seis casos adicionales: **4 FAIL conductuales / 29 PASS**. Los cuatro fallos pertenecen a la vista: no existe la fila `Synthetic first synthetic second` ni su control Play; continúa renderizando fragmentos originales. Sin errores de importación/setup.
- `npm run typecheck`: PASS.
- `git diff --check`: PASS.

Se usan `groupTranscriptTurns` y `createPlaybackIntervals` productivos, sin crear DOM agrupado artificial ni mock del controller. Dos fuentes `[0,100]` y `[200,300]` generan una fila y dos intervalos exactos; se exige highlight de esa fila en ambos subintervalos, ausencia de highlight en 100/150/300, y Play en 0 tras estar en el segundo intervalo. Se conserva overlap `[0,100]/[50,300]`, texto sin tiempos sin Play, y ausencia de texto inventado.

Las dos pruebas adicionales del controller pasan y fijan intervalos originales, gap nulo, orden en overlaps, ausencia de mutación y descarte de timing inválido sin inventar texto. La falla corresponde al seam de integración de vista, no al agrupador ni al reloj.

## Contrato para GREEN T18

Se propone `presentationTurns` como input separado de render, pasado junto a `passages` que conserva exclusivamente los intervalos originales (incluye `presentationTurnId`). Es un seam local de prueba derivado del diseño §5, no una modificación de producción ni un API público aprobado adicional. Se utiliza spread tipado estructuralmente, sin casts `any`, `ts-ignore` ni debilitamiento de typecheck; la vista actual ignora ese input y por eso el RED es conductual. T18 puede ajustar el nombre local de la prop conservando estas expectativas y la separación de filas/intervalos.

**NO INTEGRAR este RED aislado.** T18 depende de T2 y T16; T16 requiere T14. Preservar este commit como primera evidencia RED del PR hasta GREEN. Fer integra el candidato final, luego de revisión de Ansel. Esto no acredita UI running, audio real, calidad del motor ni aceptación de producto. No se utilizó Docker ni se generaron recursos temporales externos; node_modules es enlace a dependencias ya existentes.
