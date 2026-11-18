import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { type CatalogModel, checkHardware, type HardwareInput } from "./hardware.ts";

const repo = path.resolve(import.meta.dirname, "..", "..", "..");
const catalog = JSON.parse(fs.readFileSync(path.join(repo, "scripts/engines/model-catalog.json"), "utf8")) as {
  models: CatalogModel[];
};
const GIB = 1024 ** 3;

const input = (change: Partial<HardwareInput> = {}): HardwareInput => ({
  arch: "arm64",
  macosVersion: "15.3",
  memoryBytes: 32 * GIB,
  diskFreeBytes: 500e9,
  minimumMacos: "14.0",
  models: catalog.models,
  componentsBytes: 716.6e6,
  ...change,
});

describe("hardware check", () => {
  it("passes a recent Apple silicon Mac with room for the recommended models", () => {
    const report = checkHardware(input());
    expect(report.problems).toEqual([]);
    expect(report.warnings).toEqual([]);
    // Parakeet + Qwen 9B + the voice detector + the speaker runtime, with the 20 % margin.
    expect(report.neededBytes).toBe(Math.ceil((632314500 + 5680522464 + 885098 + 716.6e6) * 1.2));
  });

  it("blocks an Intel Mac and a macOS older than the minimum", () => {
    expect(checkHardware(input({ arch: "x64" })).problems).toEqual([{ code: "arch", arch: "x64" }]);
    expect(checkHardware(input({ macosVersion: "13.6" })).problems).toEqual([
      { code: "macos", version: "13.6", minimum: "14.0" },
    ]);
  });

  it("warns with the missing memory when only lighter models fit", () => {
    const report = checkHardware(input({ memoryBytes: 8 * GIB }));
    expect(report.problems).toEqual([]);
    expect(report.warnings).toEqual([{ code: "memory_lighter", gib: 8, needed: 16, missing: 8 }]);
  });

  it("warns when no summary model fits at all", () => {
    const report = checkHardware(input({ memoryBytes: 4 * GIB }));
    expect(report.warnings).toContainEqual({ code: "memory_none", gib: 4, needed: 8, process: "summary" });
  });

  it("warns with the missing space when the disk is too small", () => {
    const report = checkHardware(input({ diskFreeBytes: 1e9 }));
    expect(report.warnings).toEqual([
      { code: "disk_low", neededBytes: report.neededBytes, missingBytes: report.neededBytes - 1e9 },
    ]);
  });
});
