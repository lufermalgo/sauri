// Feature: chrome-side-panel, Property 19: Round-trip del reunion_id en la URL de la Vista_De_Detalle

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { construirUrlDetalle, leerReunionId } from "./detailUrl";

describe("construirUrlDetalle / leerReunionId", () => {
  it("Property 19: round-trip conserva el reunion_id exacto (Req. 6.2)", () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 40 }).filter((s) => s.trim().length > 0),
        (reunionId) => {
          const url = construirUrlDetalle(reunionId);
          const leido = leerReunionId(url);
          expect(leido).toBe(reunionId);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("leerReunionId devuelve null si no hay parámetro", () => {
    expect(leerReunionId("detail.html")).toBeNull();
  });
});
