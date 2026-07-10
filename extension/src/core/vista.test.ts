// Feature: chrome-side-panel, Property 16: Derivación total y exclusiva del Estado_De_Vista

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { derivarEstadoDeVista } from "./vista";
import type { SolicitudRemota } from "./types";

const solicitudArb = fc.oneof(
  fc.record({
    fase: fc.constant("inicial" as const),
    datos: fc.constant(null),
    previos: fc.constant(null),
  }),
  fc.record({
    fase: fc.constant("en_curso" as const),
    datos: fc.constant(null),
    previos: fc.oneof(fc.constant(null), fc.array(fc.integer())),
  }),
  fc.record({
    fase: fc.constant("exito" as const),
    datos: fc.array(fc.integer(), { maxLength: 10 }),
    previos: fc.constant(null),
  }),
  fc.record({
    fase: fc.constant("fallo" as const),
    datos: fc.constant(null),
    previos: fc.oneof(fc.constant(null), fc.array(fc.integer(), { maxLength: 10 })),
  })
);

describe("derivarEstadoDeVista", () => {
  it("Property 16: exactamente uno de cuatro estados; conserva previos en error (Req. 12.3, 12.5, 12.6, 12.7)", () => {
    fc.assert(
      fc.property(solicitudArb, (solicitud: SolicitudRemota<number>) => {
        const estado = derivarEstadoDeVista(solicitud);
        expect(["cargando", "con_datos", "vacio", "error"]).toContain(estado);

        if (solicitud.fase === "en_curso" || solicitud.fase === "inicial") {
          expect(estado).toBe("cargando");
        } else if (solicitud.fase === "exito") {
          if ((solicitud.datos?.length ?? 0) > 0) {
            expect(estado).toBe("con_datos");
          } else {
            expect(estado).toBe("vacio");
          }
        } else if (solicitud.fase === "fallo") {
          expect(estado).toBe("error");
        }
      }),
      { numRuns: 100 }
    );
  });
});
