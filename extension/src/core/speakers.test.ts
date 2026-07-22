// Feature: chrome-side-panel, Property 2: Deterministic avatar (initials and cyclic color)

/**
 * Property 2: Deterministic avatar (initials and cyclic color)
 * Validates: Requirements 8.4
 *
 * For any speaker label:
 * - labelInitials(label) returns at most 2 characters
 *
 * For any positive integer sequence:
 * - avatarColor(sequence) is deterministic: same input → same result
 * - avatarColor(sequence) belongs to AVATAR_PALETTE
 * - Cyclicity: avatarColor(sequence) === avatarColor(sequence + AVATAR_PALETTE.length)
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { labelInitials, avatarColor, AVATAR_PALETTE } from "./speakers";

describe("labelInitials", () => {
  // ── Property 2a: at most 2 characters for any string ───────────────
  it("Property 2a — returns at most 2 characters for any label (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.string(),
        (label) => {
          const result = labelInitials(label);
          expect(result.length).toBeLessThanOrEqual(2);
        }
      ),
      { numRuns: 100 }
    );
  });
});

describe("avatarColor", () => {
  // ── Property 2b: determinism — same input → same result ──────────────
  it("Property 2b — is deterministic: same input produces the same color (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (sequence) => {
          const result1 = avatarColor(sequence);
          const result2 = avatarColor(sequence);
          expect(result1).toBe(result2);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property 2c: the color belongs to AVATAR_PALETTE ──────────────────────────
  it("Property 2c — the returned color belongs to AVATAR_PALETTE (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (sequence) => {
          const result = avatarColor(sequence);
          expect(AVATAR_PALETTE).toContain(result);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property 2d: cyclicity — avatarColor(sequence) === avatarColor(sequence + AVATAR_PALETTE.length)
  it("Property 2d — is cyclic: avatarColor(sequence) === avatarColor(sequence + AVATAR_PALETTE.length) (Req. 8.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (sequence) => {
          const baseColor = avatarColor(sequence);
          const cyclicColor = avatarColor(sequence + AVATAR_PALETTE.length);
          expect(baseColor).toBe(cyclicColor);
        }
      ),
      { numRuns: 100 }
    );
  });
});
