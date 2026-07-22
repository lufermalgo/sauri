/**
 * Example-based test: focus ring contrast (RED)
 * Validates: Requirement 12.4
 *
 * Verifies that the focus tokens exported by tokens.ts meet a WCAG contrast
 * ratio >= 3:1 and that AVATAR_PALETTE is a non-empty array.
 *
 * This test MUST FAIL (RED) because tokens.ts doesn't exist yet.
 */

import { describe, it, expect } from "vitest";
import { FOCUS_RING_COLOR, SURFACE_COLOR, AVATAR_PALETTE } from "./tokens";

// ---------------------------------------------------------------------------
// Helper: WCAG 2.x relative luminance calculation
// https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
// ---------------------------------------------------------------------------

/**
 * Converts an sRGB color channel (0-255) to its linear component.
 */
function linearChannel(c8bit: number): number {
  const c = c8bit / 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/**
 * Parses a hexadecimal color (#RRGGBB or #RGB) and returns [r, g, b] in 0-255.
 * Throws if the format isn't recognized.
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
  throw new Error(`Unrecognized hexadecimal color: "${hex}"`);
}

/**
 * Calculates the WCAG relative luminance of a hexadecimal color.
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
 * Calculates the WCAG contrast ratio between two hexadecimal colors.
 * Always returns a value >= 1.
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

describe("Design_System – focus tokens (Req. 12.4)", () => {
  it("FOCUS_RING_COLOR is defined and is a valid hexadecimal color", () => {
    expect(FOCUS_RING_COLOR).toBeDefined();
    expect(typeof FOCUS_RING_COLOR).toBe("string");
    // Must be parseable as hex; parseHex throws if it isn't
    expect(() => parseHex(FOCUS_RING_COLOR)).not.toThrow();
  });

  it("SURFACE_COLOR is defined and is a valid hexadecimal color", () => {
    expect(SURFACE_COLOR).toBeDefined();
    expect(typeof SURFACE_COLOR).toBe("string");
    expect(() => parseHex(SURFACE_COLOR)).not.toThrow();
  });

  it("the contrast between FOCUS_RING_COLOR and SURFACE_COLOR is >= 3:1 (Req. 12.4)", () => {
    const ratio = contrastRatio(FOCUS_RING_COLOR, SURFACE_COLOR);
    expect(ratio).toBeGreaterThanOrEqual(3.0);
  });

  it("AVATAR_PALETTE is a non-empty array", () => {
    expect(Array.isArray(AVATAR_PALETTE)).toBe(true);
    expect(AVATAR_PALETTE.length).toBeGreaterThan(0);
  });
});
