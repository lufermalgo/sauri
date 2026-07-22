// Feature: chrome-side-panel, Property 1: Formatted timestamp format

/**
 * Property 1: Formatted timestamp format
 * Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 3.9, 8.3, 10.3
 *
 * For any millisecond value `ms`:
 * - ms in [0, 3_600_000) → "MM:SS" (two digits each, range 00-59)
 * - ms >= 3_600_000 → "HH:MM:SS" (hours >= 2 digits)
 * - ms === 0 → "00:00"
 * - negative, NaN, null, undefined ms → "--:--"
 * - Truncation: Math.floor(ms / 1000)
 */

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { formatTimestamp } from "./time";

/** MM:SS pattern — exactly two digits for minutes and seconds */
const MM_SS_PATTERN = /^\d{2}:\d{2}$/;
/** HH:MM:SS pattern — two or more digits for hours, exactly two for minutes and seconds */
const HH_MM_SS_PATTERN = /^\d{2,}:\d{2}:\d{2}$/;

describe("formatTimestamp", () => {
  // ── Mandatory fixed example (Req. 11.4) ────────────────────────────────────
  it("ms === 0 returns '00:00'", () => {
    expect(formatTimestamp(0)).toBe("00:00");
  });

  // ── Property: range [0, 3_600_000) → MM:SS format ──────────────────────────
  it("Property 1a — ms in [0, 3_600_000) produces 'MM:SS' with valid digits (Req. 11.1, 11.3, 11.4)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 3_599_999 }),
        (ms) => {
          const result = formatTimestamp(ms);

          // Must have MM:SS shape
          expect(result).toMatch(MM_SS_PATTERN);

          const [mmPart, ssPart] = result.split(":").map(Number);

          // Minutes: 0-59
          expect(mmPart).toBeGreaterThanOrEqual(0);
          expect(mmPart).toBeLessThanOrEqual(59);

          // Seconds: 0-59
          expect(ssPart).toBeGreaterThanOrEqual(0);
          expect(ssPart).toBeLessThanOrEqual(59);

          // Truncation: seconds must derive from Math.floor(ms / 1000)
          const totalSec = Math.floor(ms / 1000);
          const expectedSec = totalSec % 60;
          const expectedMin = Math.floor(totalSec / 60) % 60;
          expect(ssPart).toBe(expectedSec);
          expect(mmPart).toBe(expectedMin);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property: ms >= 3_600_000 → HH:MM:SS format ────────────────────────────
  it("Property 1b — ms >= 3_600_000 produces 'HH:MM:SS' with valid digits (Req. 11.2, 11.3)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 3_600_000, max: 99 * 3_600_000 }),
        (ms) => {
          const result = formatTimestamp(ms);

          // Must have HH:MM:SS shape (hours >= 2 digits)
          expect(result).toMatch(HH_MM_SS_PATTERN);

          const parts = result.split(":").map(Number);
          expect(parts).toHaveLength(3);
          const [hh, mm, ss] = parts;

          // Hours: >= 1
          expect(hh).toBeGreaterThanOrEqual(1);

          // Minutes: 0-59
          expect(mm).toBeGreaterThanOrEqual(0);
          expect(mm).toBeLessThanOrEqual(59);

          // Seconds: 0-59
          expect(ss).toBeGreaterThanOrEqual(0);
          expect(ss).toBeLessThanOrEqual(59);

          // Correct truncation
          const totalSec = Math.floor(ms / 1000);
          const expectedSec = totalSec % 60;
          const expectedMin = Math.floor(totalSec / 60) % 60;
          const expectedHours = Math.floor(totalSec / 3600);
          expect(ss).toBe(expectedSec);
          expect(mm).toBe(expectedMin);
          expect(hh).toBe(expectedHours);
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Property: negative ms → placeholder "--:--" ──────────────────────────────
  it("Property 1c — negative ms produces '--:--' (Req. 11.5)", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: -10_000_000, max: -1 }),
        (ms) => {
          expect(formatTimestamp(ms)).toBe("--:--");
        }
      ),
      { numRuns: 100 }
    );
  });

  // ── Unavailable cases: NaN, null, undefined → "--:--" ─────────────────────
  it("Property 1d — NaN produces '--:--' (Req. 11.5)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(formatTimestamp(NaN as any)).toBe("--:--");
  });

  it("Property 1e — null produces '--:--' (Req. 11.5)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(formatTimestamp(null as any)).toBe("--:--");
  });

  it("Property 1f — undefined produces '--:--' (Req. 11.5)", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(formatTimestamp(undefined as any)).toBe("--:--");
  });

  // ── Combined property: every valid input produces exactly MM:SS or HH:MM:SS
  it("Property 1g — every input in [0, ∞) produces MM:SS or HH:MM:SS, never another format", () => {
    fc.assert(
      fc.property(
        fc.nat({ max: 99 * 3_600_000 }),
        (ms) => {
          const result = formatTimestamp(ms);
          const isMMSS = MM_SS_PATTERN.test(result);
          const isHHMMSS = HH_MM_SS_PATTERN.test(result);
          expect(isMMSS || isHHMMSS).toBe(true);

          // The threshold separates the two formats
          if (ms < 3_600_000) {
            expect(isMMSS).toBe(true);
          } else {
            expect(isHHMMSS).toBe(true);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
