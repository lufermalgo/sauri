/**
 * Prueba por ejemplo: contraste del anillo de foco (RED)
 * Validates: Requirement 12.4
 *
 * Verifica que los tokens de foco exportados por tokens.ts cumplen
 * una relación de contraste WCAG ≥ 3:1 y que PALETA_AVATAR es un array no vacío.
 *
 * Esta prueba DEBE FALLAR (RED) porque tokens.ts aún no existe.
 */

import { describe, it, expect } from "vitest";
import { FOCUS_RING_COLOR, SURFACE_COLOR, PALETA_AVATAR } from "./tokens";

// ---------------------------------------------------------------------------
// Helper: cálculo de luminancia relativa WCAG 2.x
// https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
// ---------------------------------------------------------------------------

/**
 * Convierte un canal de color sRGB (0–255) a su componente lineal.
 */
function linearChannel(c8bit: number): number {
  const c = c8bit / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/**
 * Parsea un color hexadecimal (#RRGGBB o #RGB) y devuelve [r, g, b] en 0–255.
 * Lanza si el formato no es reconocido.
 */
function parseHex(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  if (h.length === 3) {
    return [
      parseInt(h[0] + h[0], 16),
      parseInt(h[1] + h[1], 16),
      parseInt(h[2] + h[2], 16),
    ];
  }
  if (h.length === 6) {
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
    ];
  }
  throw new Error(`Color hexadecimal no reconocido: "${hex}"`);
}

/**
 * Calcula la luminancia relativa WCAG de un color hexadecimal.
 */
function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return (
    0.2126 * linearChannel(r) +
    0.7152 * linearChannel(g) +
    0.0722 * linearChannel(b)
  );
}

/**
 * Calcula la relación de contraste WCAG entre dos colores hexadecimales.
 * Siempre devuelve un valor >= 1.
 */
function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relativeLuminance(hex1);
  const l2 = relativeLuminance(hex2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Sistema_De_Diseno – tokens de foco (Req. 12.4)", () => {
  it("FOCUS_RING_COLOR está definido y es un color hexadecimal válido", () => {
    expect(FOCUS_RING_COLOR).toBeDefined();
    expect(typeof FOCUS_RING_COLOR).toBe("string");
    // Debe ser parseable como hex; parseHex lanza si no lo es
    expect(() => parseHex(FOCUS_RING_COLOR)).not.toThrow();
  });

  it("SURFACE_COLOR está definido y es un color hexadecimal válido", () => {
    expect(SURFACE_COLOR).toBeDefined();
    expect(typeof SURFACE_COLOR).toBe("string");
    expect(() => parseHex(SURFACE_COLOR)).not.toThrow();
  });

  it("el contraste entre FOCUS_RING_COLOR y SURFACE_COLOR es >= 3:1 (Req. 12.4)", () => {
    const ratio = contrastRatio(FOCUS_RING_COLOR, SURFACE_COLOR);
    expect(ratio).toBeGreaterThanOrEqual(3.0);
  });

  it("PALETA_AVATAR es un array no vacío", () => {
    expect(Array.isArray(PALETA_AVATAR)).toBe(true);
    expect(PALETA_AVATAR.length).toBeGreaterThan(0);
  });
});
