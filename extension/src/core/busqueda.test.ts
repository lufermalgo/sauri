// Feature: chrome-side-panel, Property 7: Filtro de Notas como conjunción de búsqueda y criterio
// Feature: chrome-side-panel, Property 8: Búsqueda de Notas inactiva con texto en blanco
// Feature: chrome-side-panel, Property 12: Coincidencias del Buscador_De_Transcripcion
// Feature: chrome-side-panel, Property 13: Búsqueda de transcripción inactiva con texto en blanco

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { filtrarNotas, coincidenciasDeTranscripcion, LIMITE_BUSQUEDA_NOTAS, LIMITE_BUSQUEDA_TRANSCRIPCION } from "./busqueda";
import type { NotaDTO, IntervencionDTO } from "./types";

const notaArb = fc.record({
  reunionId: fc.uuid(),
  titulo: fc.string({ minLength: 1, maxLength: 20 }),
  estadoProceso: fc.constantFrom("en_cola", "grabando", "completado", "fallido"),
  creadaEn: fc.constant(new Date(2024, 0, 1).toISOString()),
});

describe("filtrarNotas", () => {
  it("Property 7: conjunción de título normalizado y criterio de estado (Req. 5.1, 5.2, 5.3)", () => {
    fc.assert(
      fc.property(
        fc.array(notaArb, { maxLength: 20 }),
        fc.string({ maxLength: 10 }),
        fc.constantFrom("en_cola", "grabando", "completado", "fallido"),
        (notas: NotaDTO[], texto, estado) => {
          const resultado = filtrarNotas(notas, texto, { estadoProceso: estado });
          const textoNorm = texto.trim().toLowerCase();

          for (const nota of resultado) {
            const tituloNorm = (nota.titulo ?? "").trim().toLowerCase();
            expect(tituloNorm.includes(textoNorm)).toBe(true);
            expect(nota.estadoProceso).toBe(estado);
          }

          // Ninguna excluida satisface ambos predicados
          const excluidas = notas.filter((n) => !resultado.includes(n));
          for (const nota of excluidas) {
            const tituloNorm = (nota.titulo ?? "").trim().toLowerCase();
            const cumpleTexto = tituloNorm.includes(textoNorm);
            const cumpleEstado = nota.estadoProceso === estado;
            expect(cumpleTexto && cumpleEstado).toBe(false);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("Property 8: texto en blanco -> no excluye ninguna Nota por título (Req. 5.4, 5.6)", () => {
    fc.assert(
      fc.property(
        fc.array(notaArb, { maxLength: 20 }),
        fc.constantFrom("", "   ", "\t", "  \n "),
        (notas: NotaDTO[], textoBlanco) => {
          const resultado = filtrarNotas(notas, textoBlanco, {});
          expect(resultado.length).toBe(notas.length);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("trunca la búsqueda a 100 caracteres (Req. 5.7)", () => {
    const textoLargo = "a".repeat(150);
    expect(() => filtrarNotas([], textoLargo, {})).not.toThrow();
    expect(LIMITE_BUSQUEDA_NOTAS).toBe(100);
  });
});

const intervencionArb = fc.record({
  turnoId: fc.uuid(),
  texto: fc.string({ minLength: 1, maxLength: 30 }),
  inicioMs: fc.integer({ min: 0, max: 100000 }),
  finMs: fc.integer({ min: 0, max: 100000 }),
  orden: fc.integer({ min: 0, max: 30 }),
  hablante: fc.constant(null),
});

describe("coincidenciasDeTranscripcion", () => {
  it("Property 12: coincidencias case-insensitive, primera por menor inicio_ms, orden inalterado (Req. 9.1, 9.2, 9.4)", () => {
    fc.assert(
      fc.property(
        fc.array(intervencionArb, { maxLength: 20 }),
        fc.string({ minLength: 1, maxLength: 10 }).filter((s) => s.trim().length > 0),
        (intervenciones: IntervencionDTO[], texto) => {
          const resultado = coincidenciasDeTranscripcion(intervenciones, texto);

          // El orden/conjunto de intervenciones mostradas no cambia
          expect(resultado.intervenciones).toEqual(intervenciones);

          const textoNorm = texto.toLowerCase();
          const idsCoincidentes = new Set(
            intervenciones.filter((i) => i.texto.toLowerCase().includes(textoNorm)).map((i) => i.turnoId)
          );
          expect(new Set(resultado.turnoIdsCoincidentes)).toEqual(idsCoincidentes);

          if (idsCoincidentes.size > 0) {
            const coincidentes = intervenciones.filter((i) => idsCoincidentes.has(i.turnoId));
            const minInicio = Math.min(...coincidentes.map((i) => i.inicioMs));
            const primera = intervenciones.find((i) => i.turnoId === resultado.primeraCoincidenciaId);
            expect(primera).toBeDefined();
            expect(primera!.inicioMs).toBe(minInicio);
          } else {
            expect(resultado.primeraCoincidenciaId).toBeNull();
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("Property 13: texto en blanco -> cero coincidencias, orden original conservado (Req. 9.3)", () => {
    fc.assert(
      fc.property(
        fc.array(intervencionArb, { maxLength: 20 }),
        fc.constantFrom("", "   ", "\t"),
        (intervenciones: IntervencionDTO[], textoBlanco) => {
          const resultado = coincidenciasDeTranscripcion(intervenciones, textoBlanco);
          expect(resultado.turnoIdsCoincidentes.length).toBe(0);
          expect(resultado.primeraCoincidenciaId).toBeNull();
          expect(resultado.intervenciones).toEqual(intervenciones);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("trunca la búsqueda a 200 caracteres (Req. 9.5)", () => {
    expect(LIMITE_BUSQUEDA_TRANSCRIPCION).toBe(200);
  });
});
