// Feature: chrome-side-panel, Property 1: Formato de Marca_De_Tiempo_Formateada

/**
 * Property 1: Formato de Marca_De_Tiempo_Formateada
 * Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 3.9, 8.3, 10.3
 *
 * Para cualquier valor de milisegundos `ms`:
 * - ms en [0, 3_600_000) → "MM:SS" (dos dígitos cada uno, rango 00-59)
 * - ms >= 3_600_000 → "HH:MM:SS" (horas ≥ 2 dígitos)
 * - ms === 0 → "00:00"
 * - ms negativo, NaN, null, undefined → "--:--"
 * - Truncamiento: Math.floor(ms / 1000)
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { formatearMarcaDeTiempo } from "./tiempo";

/** Patrón MM:SS — exactamente dos dígitos para minutos y segundos */
const PATRON_MM_SS = /^\d{2}:\d{2}$/;
/** Patrón HH:MM:SS — dos o más dígitos para horas, exactamente dos para minutos y segundos */
const PATRON_HH_MM_SS = /^\d{2,}:\d{2}:\d{2}$/;

describe("formatearMarcaDeTiempo", () => {
  // ── Ejemplo fijo obligatorio (Req. 11.4) ────────────────────────────────────
  it("ms === 0 devuelve '00:00'", () => {
    expect(formatearMarcaDeTiempo(0)).toBe("00:00");
  });

  // ── Property: rango [0, 3_600_000) → formato MM:SS ──────────────────────────
  it("Property 1a — ms en [0, 3_600_000) produce 'MM:SS' con dígitos válidos (Req. 11.1, 11.3, 11.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 3_599_999 }),
        (ms) => {
          const resultado = formatearMarcaDeTiempo(ms);

          // Debe tener forma MM:SS
          expect(resultado).toMatch(PATRON_MM_SS);

          const [parteMM, parteSS] = resultado.split(":").map(Number);

          // Minutos: 0–59
          expect(parteMM).toBeGreaterThanOrEqual(0);
          expect(parteMM).toBeLessThanOrEqual(59);

          // Segundos: 0–59
          expect(parteSS).toBeGreaterThanOrEqual(0);
          expect(parteSS).toBeLessThanOrEqual(59);

          // Truncamiento: los segundos deben derivarse de Math.floor(ms / 1000)
          const totalSeg = Math.floor(ms / 1000);
          const segEsperado = totalSeg % 60;
          const minEsperado = Math.floor(totalSeg / 60) % 60;
          expect(parteSS).toBe(segEsperado);
          expect(parteMM).toBe(minEsperado);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property: ms >= 3_600_000 → formato HH:MM:SS ────────────────────────────
  it("Property 1b — ms >= 3_600_000 produce 'HH:MM:SS' con dígitos válidos (Req. 11.2, 11.3)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 3_600_000, max: 99 * 3_600_000 }),
        (ms) => {
          const resultado = formatearMarcaDeTiempo(ms);

          // Debe tener forma HH:MM:SS (horas ≥ 2 dígitos)
          expect(resultado).toMatch(PATRON_HH_MM_SS);

          const partes = resultado.split(":").map(Number);
          expect(partes).toHaveLength(3);
          const [hh, mm, ss] = partes;

          // Horas: ≥ 1
          expect(hh).toBeGreaterThanOrEqual(1);

          // Minutos: 0–59
          expect(mm).toBeGreaterThanOrEqual(0);
          expect(mm).toBeLessThanOrEqual(59);

          // Segundos: 0–59
          expect(ss).toBeGreaterThanOrEqual(0);
          expect(ss).toBeLessThanOrEqual(59);

          // Truncamiento correcto
          const totalSeg = Math.floor(ms / 1000);
          const segEsperado = totalSeg % 60;
          const minEsperado = Math.floor(totalSeg / 60) % 60;
          const horasEsperadas = Math.floor(totalSeg / 3600);
          expect(ss).toBe(segEsperado);
          expect(mm).toBe(minEsperado);
          expect(hh).toBe(horasEsperadas);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property: ms negativo → placeholder "--:--" ──────────────────────────────
  it("Property 1c — ms negativo produce '--:--' (Req. 11.5)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -10_000_000, max: -1 }),
        (ms) => {
          expect(formatearMarcaDeTiempo(ms)).toBe("--:--");
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Casos no disponibles: NaN, null, undefined → "--:--" ─────────────────────
  it("Property 1d — NaN produce '--:--' (Req. 11.5)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(formatearMarcaDeTiempo(NaN as any)).toBe("--:--");
  });

  it("Property 1e — null produce '--:--' (Req. 11.5)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(formatearMarcaDeTiempo(null as any)).toBe("--:--");
  });

  it("Property 1f — undefined produce '--:--' (Req. 11.5)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(formatearMarcaDeTiempo(undefined as any)).toBe("--:--");
  });

  // ── Property combinada: toda entrada válida produce exactamente MM:SS o HH:MM:SS
  it("Property 1g — toda entrada en [0, ∞) produce MM:SS o HH:MM:SS, nunca otro formato", () => {
    fc.assert(
      fc.property(
        fc.nat({ max: 99 * 3_600_000 }),
        (ms) => {
          const resultado = formatearMarcaDeTiempo(ms);
          const esMMSS = PATRON_MM_SS.test(resultado);
          const esHHMMSS = PATRON_HH_MM_SS.test(resultado);
          expect(esMMSS || esHHMMSS).toBe(true);

          // El umbral separa los dos formatos
          if (ms < 3_600_000) {
            expect(esMMSS).toBe(true);
          } else {
            expect(esHHMMSS).toBe(true);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
