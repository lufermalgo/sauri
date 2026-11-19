import { describe, expect, it } from "vitest";
import { ICON_SIZE, type IconState, iconPixels } from "./tray-icon.ts";

const STATES: IconState[] = ["starting", "ready", "processing", "error"];

function alpha(state: IconState): number[] {
  const pixels = iconPixels(state);
  return Array.from({ length: ICON_SIZE * ICON_SIZE }, (_, i) => pixels[i * 4 + 3]);
}

describe("iconPixels", () => {
  it("is a 36x36 BGRA bitmap, black with alpha only (template image)", () => {
    for (const state of STATES) {
      const pixels = iconPixels(state);
      expect(pixels.length).toBe(ICON_SIZE * ICON_SIZE * 4);
      for (let i = 0; i < pixels.length; i += 4) expect([pixels[i], pixels[i + 1], pixels[i + 2]]).toEqual([0, 0, 0]);
    }
  });

  it("draws something visible in every state, never filling the whole canvas", () => {
    for (const state of STATES) {
      const covered = alpha(state).filter((a) => a > 0).length;
      expect(covered).toBeGreaterThan(100);
      expect(covered).toBeLessThan(ICON_SIZE * ICON_SIZE * 0.8);
    }
  });

  it("tells the four states apart by shape", () => {
    const shapes = STATES.map((state) => alpha(state).join(","));
    expect(new Set(shapes).size).toBe(STATES.length);
  });

  it("keeps the diamond at the isotype centre in every state and the isotype out of the badge corner when ready", () => {
    for (const state of STATES) expect(alpha(state)[15 * ICON_SIZE + 15]).toBeGreaterThan(200);
    const ready = alpha("ready");
    // Bottom-right corner of the canvas is empty: the isotype is 30 px of the 36.
    expect(ready[35 * ICON_SIZE + 35]).toBe(0);
  });

  it("starting is the outlined isotype: lighter than ready, with a hollow middle half", () => {
    const sum = (state: IconState) => alpha(state).reduce((a, b) => a + b, 0);
    expect(sum("starting")).toBeLessThan(sum("ready"));
    expect(alpha("starting")[8 * ICON_SIZE + 8]).toBe(0);
    expect(alpha("ready")[8 * ICON_SIZE + 8]).toBeGreaterThan(200);
  });

  it("processing draws a hollow ring badge and error a solid badge with a knocked-out mark", () => {
    const processing = alpha("processing");
    const error = alpha("error");
    expect(processing[28 * ICON_SIZE + 28]).toBe(0); // ring centre empty
    expect(processing[28 * ICON_SIZE + 34]).toBeGreaterThan(200); // ring edge (r ~6)
    expect(error[28 * ICON_SIZE + 33]).toBeGreaterThan(200); // solid badge body
    expect(error[26 * ICON_SIZE + 28]).toBe(0); // "!" bar knocked out
  });
});
