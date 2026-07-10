// Feature: chrome-side-panel, Property 6: Orden de Notas (no creciente por fecha, total y repetible)
// Feature: chrome-side-panel, Property 10: Orden de Intervenciones por (inicio_ms, orden)
// Feature: chrome-side-panel, Property 15: Orden de la Vista_Tiempo_De_Habla

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { ordenarNotas, ordenarIntervenciones, ordenarTiempoDeHabla } from "./orden";
import type { NotaDTO, IntervencionDTO, EntradaTiempoDeHabla } from "./types";

const fechaBase = new Date(2024, 0, 1).getTime();

const notaArb = fc.record({
  reunionId: fc.uuid(),
  titulo: fc.constant<string | null>(null),
  estadoProceso: fc.constant("completado"),
  creadaEn: fc.integer({ min: 0, max: 20 }).map((i) => new Date(fechaBase + i * 3_600_000).toISOString()),
});

describe("ordenarNotas", () => {
  it("Property 6: desc. por fecha, desempate asc. por reunionId, total e idempotente (Req. 4.6)", () => {
    fc.assert(
      fc.property(fc.array(notaArb, { maxLength: 30 }), (notas: NotaDTO[]) => {
        const ordenado = ordenarNotas(notas);
        expect(ordenado.length).toBe(notas.length);

        for (let i = 0; i < ordenado.length - 1; i++) {
          const a = ordenado[i];
          const b = ordenado[i + 1];
          const fa = new Date(a.creadaEn!).getTime();
          const fb = new Date(b.creadaEn!).getTime();
          if (fa === fb) {
            expect(a.reunionId <= b.reunionId).toBe(true);
          } else {
            expect(fa).toBeGreaterThanOrEqual(fb);
          }
        }

        // Idempotencia
        expect(ordenarNotas(ordenado)).toEqual(ordenado);
      }),
      { numRuns: 100 }
    );
  });
});

const intervencionArb = fc.record({
  turnoId: fc.uuid(),
  texto: fc.string(),
  inicioMs: fc.integer({ min: 0, max: 10 }),
  finMs: fc.integer({ min: 0, max: 100000 }),
  orden: fc.integer({ min: 0, max: 10 }),
  hablante: fc.constant(null),
});

describe("ordenarIntervenciones", () => {
  it("Property 10: asc. por (inicio_ms, orden), total e idempotente (Req. 8.2)", () => {
    fc.assert(
      fc.property(fc.array(intervencionArb, { maxLength: 30 }), (intervenciones: IntervencionDTO[]) => {
        const ordenado = ordenarIntervenciones(intervenciones);
        expect(ordenado.length).toBe(intervenciones.length);
        for (let i = 0; i < ordenado.length - 1; i++) {
          const a = ordenado[i];
          const b = ordenado[i + 1];
          if (a.inicioMs === b.inicioMs) {
            expect(a.orden).toBeLessThanOrEqual(b.orden);
          } else {
            expect(a.inicioMs).toBeLessThanOrEqual(b.inicioMs);
          }
        }
        expect(ordenarIntervenciones(ordenado)).toEqual(ordenado);
      }),
      { numRuns: 100 }
    );
  });
});

const entradaArb = fc.record({
  hablante: fc.record({
    id: fc.uuid(),
    etiqueta: fc.string(),
    orden: fc.integer({ min: 0, max: 10 }),
  }),
  tiempoMs: fc.integer({ min: 0, max: 10 }),
});

describe("ordenarTiempoDeHabla", () => {
  it("Property 15: no creciente por tiempo, desempate asc. por orden, total e idempotente (Req. 10.4)", () => {
    fc.assert(
      fc.property(fc.array(entradaArb, { maxLength: 30 }), (entradas: EntradaTiempoDeHabla[]) => {
        const ordenado = ordenarTiempoDeHabla(entradas);
        expect(ordenado.length).toBe(entradas.length);
        for (let i = 0; i < ordenado.length - 1; i++) {
          const a = ordenado[i];
          const b = ordenado[i + 1];
          if (a.tiempoMs === b.tiempoMs) {
            expect(a.hablante.orden).toBeLessThanOrEqual(b.hablante.orden);
          } else {
            expect(a.tiempoMs).toBeGreaterThanOrEqual(b.tiempoMs);
          }
        }
        expect(ordenarTiempoDeHabla(ordenado)).toEqual(ordenado);
      }),
      { numRuns: 100 }
    );
  });
});
