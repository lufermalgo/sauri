// Feature: chrome-side-panel, Property 9: Mapeo de Turnos a Intervenciones (biyección y preservación)
// Feature: chrome-side-panel, Property 11: Atribución de Hablante a la Intervencion

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { mapearIntervenciones, atribuirHablante, ETIQUETA_HABLANTE_NO_IDENTIFICADO } from "./intervenciones";
import type { TranscripcionDTO, TurnoDeHablaDTO, HablanteDTO, AsignacionDeHablanteDTO } from "./types";

const turnoArb = fc.record({
  id: fc.uuid(),
  texto: fc.string(),
  inicioMs: fc.integer({ min: 0, max: 100000 }),
  finMs: fc.integer({ min: 0, max: 100000 }),
  orden: fc.integer({ min: 0, max: 100 }),
});

describe("mapearIntervenciones", () => {
  it("Property 9: biyección por turnoId y preservación de campos (Req. 8.1, 8.5, 14.2)", () => {
    fc.assert(
      fc.property(fc.array(turnoArb, { maxLength: 30 }), (segmentosCrudos: TurnoDeHablaDTO[]) => {
        const idsUnicos = Array.from(new Set(segmentosCrudos.map((s) => s.id)));
        const segmentos = idsUnicos.map((id) => segmentosCrudos.find((s) => s.id === id)!);

        const transcripcion: TranscripcionDTO = {
          transcripcionId: "t1",
          reunionId: "r1",
          segmentos,
        };

        const intervenciones = mapearIntervenciones(transcripcion);
        expect(intervenciones.length).toBe(segmentos.length);
        for (const turno of segmentos) {
          const intervencion = intervenciones.find((i) => i.turnoId === turno.id);
          expect(intervencion).toBeDefined();
          expect(intervencion!.texto).toBe(turno.texto);
          expect(intervencion!.inicioMs).toBe(turno.inicioMs);
          expect(intervencion!.finMs).toBe(turno.finMs);
          expect(intervencion!.orden).toBe(turno.orden);
        }
      }),
      { numRuns: 100 }
    );
  });
});

const hablanteArb = fc.record({
  id: fc.uuid(),
  etiqueta: fc.string({ minLength: 1 }),
  orden: fc.integer({ min: 1, max: 20 }),
});

describe("atribuirHablante", () => {
  it("Property 11: con asignación -> hablante asignado; sin asignación -> placeholder; texto/tiempo preservados (Req. 8.3, 8.7)", () => {
    fc.assert(
      fc.property(
        turnoArb,
        fc.array(hablanteArb, { maxLength: 5 }),
        fc.boolean(),
        (turno: TurnoDeHablaDTO, hablantes: HablanteDTO[], conAsignacion: boolean) => {
          const hablanteElegido = hablantes[0];
          const asignaciones: AsignacionDeHablanteDTO[] =
            conAsignacion && hablanteElegido
              ? [{ turnoId: turno.id, hablanteId: hablanteElegido.id }]
              : [];

          const intervencion = atribuirHablante(turno, asignaciones, hablantes);

          expect(intervencion.texto).toBe(turno.texto);
          expect(intervencion.inicioMs).toBe(turno.inicioMs);
          expect(intervencion.finMs).toBe(turno.finMs);

          if (conAsignacion && hablanteElegido) {
            expect(intervencion.hablante).not.toBeNull();
            expect(intervencion.hablante!.id).toBe(hablanteElegido.id);
            expect(intervencion.hablante!.etiqueta).toBe(hablanteElegido.etiqueta);
          } else {
            expect(intervencion.hablante).toBeNull();
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it("placeholder 'hablante no identificado' está definido", () => {
    expect(ETIQUETA_HABLANTE_NO_IDENTIFICADO.length).toBeGreaterThan(0);
  });
});
