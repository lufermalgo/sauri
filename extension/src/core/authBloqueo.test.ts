// Feature: chrome-side-panel, Property 20: Bloqueo de autenticación por intentos fallidos

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { estaBloqueado } from "./authBloqueo";
import type { IntentoDeAutenticacion } from "./types";

const intentoArb = fc.record({
  exito: fc.boolean(),
  enMs: fc.integer({ min: 0, max: 1_000_000 }),
});

describe("estaBloqueado", () => {
  it("Property 20: verdadero sii >=5 fallos consecutivos y <60s desde el 5to (Req. 13.6)", () => {
    fc.assert(
      fc.property(
        fc.array(intentoArb, { minLength: 0, maxLength: 15 }).map((arr) =>
          [...arr].sort((a, b) => a.enMs - b.enMs)
        ),
        fc.integer({ min: 0, max: 1_100_000 }),
        (intentos: IntentoDeAutenticacion[], ahora) => {
          const resultado = estaBloqueado(intentos, ahora);

          // Cálculo de referencia: fallos consecutivos al final de la secuencia
          let consecutivos = 0;
          for (let i = intentos.length - 1; i >= 0; i--) {
            if (!intentos[i].exito) consecutivos++;
            else break;
          }

          if (consecutivos < 5) {
            expect(resultado).toBe(false);
          } else {
            const quintoDesdeElFinal = intentos[intentos.length - 5].enMs;
            const dentroDeVentana = ahora - quintoDesdeElFinal < 60_000;
            expect(resultado).toBe(dentroDeVentana);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
