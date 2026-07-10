// Feature: chrome-side-panel, Property 2: Avatar determinista (iniciales y color cíclico)

/**
 * Property 2: Avatar determinista (iniciales y color cíclico)
 * Validates: Requirements 8.4
 *
 * Para cualquier Etiqueta_De_Hablante:
 * - inicialesDeEtiqueta(etiqueta) devuelve a lo sumo 2 caracteres
 *
 * Para cualquier orden entero positivo:
 * - colorDeAvatar(orden) es determinista: misma entrada → mismo resultado
 * - colorDeAvatar(orden) pertenece a PALETA_AVATAR
 * - Ciclicidad: colorDeAvatar(orden) === colorDeAvatar(orden + PALETA_AVATAR.length)
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { inicialesDeEtiqueta, colorDeAvatar, PALETA_AVATAR } from "./hablantes";

describe("inicialesDeEtiqueta", () => {
  // ── Property 2a: a lo sumo 2 caracteres para cualquier string ───────────────
  it("Property 2a — devuelve a lo sumo 2 caracteres para cualquier etiqueta (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.string(),
        (etiqueta) => {
          const resultado = inicialesDeEtiqueta(etiqueta);
          expect(resultado.length).toBeLessThanOrEqual(2);
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("colorDeAvatar", () => {
  // ── Property 2b: determinismo — misma entrada → mismo resultado ──────────────
  it("Property 2b — es determinista: misma entrada produce el mismo color (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (orden) => {
          const resultado1 = colorDeAvatar(orden);
          const resultado2 = colorDeAvatar(orden);
          expect(resultado1).toBe(resultado2);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property 2c: el color pertenece a PALETA_AVATAR ──────────────────────────
  it("Property 2c — el color retornado pertenece a PALETA_AVATAR (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (orden) => {
          const resultado = colorDeAvatar(orden);
          expect(PALETA_AVATAR).toContain(resultado);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property 2d: ciclicidad — colorDeAvatar(orden) === colorDeAvatar(orden + PALETA_AVATAR.length)
  it("Property 2d — es cíclico: colorDeAvatar(orden) === colorDeAvatar(orden + PALETA_AVATAR.length) (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (orden) => {
          const colorBase = colorDeAvatar(orden);
          const colorCiclico = colorDeAvatar(orden + PALETA_AVATAR.length);
          expect(colorBase).toBe(colorCiclico);
        }
      ),
      { numRuns: 100 }
    );
  });
});
