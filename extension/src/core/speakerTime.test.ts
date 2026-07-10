// Feature: chrome-side-panel, Property 14: Cálculo y cobertura del Tiempo_De_Habla

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { calcularTiempoDeHabla } from "./speakerTime";
import type { TurnoDeHablaDTO, AsignacionDeHablanteDTO, HablanteDTO } from "./types";

const hablanteArb = fc.record({
  id: fc.uuid(),
  etiqueta: fc.string({ minLength: 1 }),
  orden: fc.integer({ min: 1, max: 20 }),
});

describe("calcularTiempoDeHabla", () => {
  it("Property 14: una entrada por hablante (incl. tiempo 0) y suma correcta (fin-inicio) (Req. 10.1, 10.2)", () => {
    fc.assert(
      fc.property(
        fc.array(hablanteArb, { maxLength: 6 }).map((hs) => {
          const ids = Array.from(new Set(hs.map((h) => h.id)));
          return ids.map((id) => hs.find((h) => h.id === id)!);
        }),
        fc.array(
          fc.record({
            id: fc.uuid(),
            inicioMs: fc.integer({ min: 0, max: 1000 }),
            finMs: fc.integer({ min: 0, max: 2000 }),
            orden: fc.integer({ min: 0, max: 30 }),
          }),
          { maxLength: 15 }
        ),
        (hablantes: HablanteDTO[], turnosCrudos) => {
          const turnos: TurnoDeHablaDTO[] = turnosCrudos.map((t) => ({
            ...t,
            texto: "x",
            finMs: Math.max(t.finMs, t.inicioMs),
          }));

          // Asigna cada turno a un hablante aleatorio (o ninguno) de forma determinista por índice
          const asignaciones: AsignacionDeHablanteDTO[] = turnos
            .map((t, i) =>
              hablantes.length > 0 && i % 2 === 0
                ? { turnoId: t.id, hablanteId: hablantes[i % hablantes.length].id }
                : null
            )
            .filter((a): a is AsignacionDeHablanteDTO => a !== null);

          const entradas = calcularTiempoDeHabla(turnos, asignaciones, hablantes);

          expect(entradas.length).toBe(hablantes.length);

          for (const hablante of hablantes) {
            const entrada = entradas.find((e) => e.hablante.id === hablante.id);
            expect(entrada).toBeDefined();

            const turnoIdsDeHablante = new Set(
              asignaciones.filter((a) => a.hablanteId === hablante.id).map((a) => a.turnoId)
            );
            const esperado = turnos
              .filter((t) => turnoIdsDeHablante.has(t.id))
              .reduce((acc, t) => acc + (t.finMs - t.inicioMs), 0);

            expect(entrada!.tiempoMs).toBe(esperado);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
