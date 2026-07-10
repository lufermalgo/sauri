// Feature: chrome-side-panel, Property 17: Máquina de Estado_De_Captura
// Feature: chrome-side-panel, Property 18: Habilitación del Boton_Nueva_Nota según el Estado_De_Captura

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { aplicarEventoCaptura, botonNuevaNotaHabilitado } from "./captura";
import type { EstadoDeCaptura, EventoCaptura } from "./types";

const ESTADOS: EstadoDeCaptura[] = ["inactiva", "grabando", "deteniendo"];
const EVENTOS: EventoCaptura[] = ["iniciar", "detener", "finalizada", "fallo_inicio"];

const TRANSICIONES_VALIDAS: Record<string, EstadoDeCaptura> = {
  "inactiva:iniciar": "grabando",
  "grabando:detener": "deteniendo",
  "deteniendo:finalizada": "inactiva",
};

describe("aplicarEventoCaptura", () => {
  it("Property 17: transiciones válidas según la tabla; resto conserva el estado (Req. 2.4, 3.3, 3.4, 3.5)", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...ESTADOS),
        fc.constantFrom(...EVENTOS),
        (estado, evento) => {
          const resultado = aplicarEventoCaptura(estado, evento);
          const clave = `${estado}:${evento}`;
          if (TRANSICIONES_VALIDAS[clave]) {
            expect(resultado).toBe(TRANSICIONES_VALIDAS[clave]);
          } else {
            expect(resultado).toBe(estado);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("botonNuevaNotaHabilitado", () => {
  it("Property 18: deshabilitado sii grabando/deteniendo (Req. 2.5)", () => {
    fc.assert(
      fc.property(fc.constantFrom(...ESTADOS), (estado) => {
        const habilitado = botonNuevaNotaHabilitado(estado);
        expect(habilitado).toBe(estado === "inactiva");
      }),
      { numRuns: 100 }
    );
  });
});
