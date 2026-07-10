// Feature: chrome-side-panel, Property 3: Placeholder de título de Nota
// Feature: chrome-side-panel, Property 4: Formato de fecha de la Tarjeta_De_Nota
// Feature: chrome-side-panel, Property 5: Proyección de Notas a Tarjetas (biyección con campos requeridos)

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { tituloParaMostrar, formatearFechaNota, proyectarTarjetas, PLACEHOLDER_TITULO } from "./notas";
import type { NotaDTO } from "./types";

describe("tituloParaMostrar", () => {
  it("Property 3: título nulo/vacío/solo-espacios -> placeholder; en otro caso, título original (Req. 4.4, 7.5)", () => {
    fc.assert(
      fc.property(
        fc.option(fc.string(), { nil: null }),
        (titulo) => {
          const resultado = tituloParaMostrar(titulo);
          const esBlanco = titulo === null || titulo.trim().length === 0;
          if (esBlanco) {
            expect(resultado).toBe(PLACEHOLDER_TITULO);
          } else {
            expect(resultado).toBe(titulo);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("formatearFechaNota", () => {
  it("Property 4: produce patrón D/M, HH:MM (Req. 4.5)", () => {
    fc.assert(
      fc.property(
        fc.date({ min: new Date(2000, 0, 1), max: new Date(2099, 11, 31) }),
        (fecha) => {
          const resultado = formatearFechaNota(fecha.toISOString());
          expect(resultado).toMatch(/^\d{1,2}\/\d{1,2}, \d{2}:\d{2}$/);
          const [fechaParte, horaParte] = resultado.split(", ");
          const [d, m] = fechaParte.split("/").map(Number);
          expect(d).toBeGreaterThanOrEqual(1);
          expect(d).toBeLessThanOrEqual(31);
          expect(m).toBeGreaterThanOrEqual(1);
          expect(m).toBeLessThanOrEqual(12);
          const [hh, mm] = horaParte.split(":").map(Number);
          expect(hh).toBeGreaterThanOrEqual(0);
          expect(hh).toBeLessThanOrEqual(23);
          expect(mm).toBeGreaterThanOrEqual(0);
          expect(mm).toBeLessThanOrEqual(59);
          expect(horaParte.length).toBe(5); // HH:MM con dos dígitos cada uno
        }
      ),
      { numRuns: 100 }
    );
  });
});

const notaArb = fc.record({
  reunionId: fc.uuid(),
  titulo: fc.option(fc.string(), { nil: null }),
  estadoProceso: fc.constantFrom("en_cola", "grabando", "completado", "fallido"),
  creadaEn: fc.date({ min: new Date(2000, 0, 1), max: new Date(2099, 11, 31) }).map((d) => d.toISOString()),
});

describe("proyectarTarjetas", () => {
  it("Property 5: biyección por reunionId + título mostrable + fecha formateada (Req. 4.2, 4.3)", () => {
    fc.assert(
      fc.property(fc.array(notaArb, { maxLength: 25 }), (notas: NotaDTO[]) => {
        // reunionId únicos para verificar biyección estricta
        const idsUnicos = Array.from(new Set(notas.map((n) => n.reunionId)));
        const notasUnicas = idsUnicos.map((id) => notas.find((n) => n.reunionId === id)!);

        const tarjetas = proyectarTarjetas(notasUnicas);

        expect(tarjetas.length).toBe(notasUnicas.length);
        for (const nota of notasUnicas) {
          const tarjeta = tarjetas.find((t) => t.reunionId === nota.reunionId);
          expect(tarjeta).toBeDefined();
          expect(tarjeta!.tituloMostrado.length).toBeGreaterThan(0);
          expect(tarjeta!.fechaMostrada).toMatch(/^\d{1,2}\/\d{1,2}, \d{2}:\d{2}$/);
        }
      }),
      { numRuns: 100 }
    );
  });
});
