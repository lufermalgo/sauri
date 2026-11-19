// Phase A hardware check (Requirement 2): Apple silicon and the minimum macOS block the setup; memory and free
// space below what the model catalog recommends only warn, with the missing figure.
import fs from "node:fs";
import os from "node:os";

const GIB = 1024 ** 3;
/** Free space reserved on top of the downloads, like host-engine's 120 % rule. */
const DISK_MARGIN = 1.2;

export interface CatalogModel {
  id: string;
  process: string;
  kind: string;
  /** The engine that runs it; an auxiliary file (the voice detector) serves the models of its own engine only. */
  engine?: string;
  size?: number;
  min_ram_gib: number;
  min_macos?: number;
  rank: number;
  default?: boolean;
  preferred?: boolean;
}

export interface HardwareInput {
  arch: string;
  macosVersion: string;
  memoryBytes: number;
  diskFreeBytes: number;
  minimumMacos: string;
  models: CatalogModel[];
  /** Downloadable components fetched during setup (the speaker runtime), in bytes. */
  componentsBytes: number;
}

export type HardwareProblem = { code: "arch"; arch: string } | { code: "macos"; version: string; minimum: string };
export type HardwareWarning =
  | { code: "memory_lighter"; gib: number; needed: number; missing: number }
  | { code: "memory_none"; gib: number; needed: number; process: string }
  | { code: "disk_low"; neededBytes: number; missingBytes: number };

export interface HardwareReport {
  arch: string;
  macosVersion: string;
  memoryGib: number;
  diskFreeBytes: number;
  neededBytes: number;
  problems: HardwareProblem[];
  warnings: HardwareWarning[];
}

function major(version: string): number {
  return Number.parseInt(version.split(".")[0] ?? "", 10) || 0;
}

/** The model each process would get: the best-ranked one that fits in memory and in this macOS. */
export function chooseModels(models: CatalogModel[], memoryGib: number, macosMajor: number): Map<string, CatalogModel | null> {
  const chosen = new Map<string, CatalogModel | null>();
  for (const model of models.filter((entry) => entry.kind === "model")) {
    if (!chosen.has(model.process)) chosen.set(model.process, null);
    const fits = model.min_ram_gib <= memoryGib && (model.min_macos ?? 0) <= macosMajor;
    const current = chosen.get(model.process);
    if (fits && (!current || model.rank > current.rank)) chosen.set(model.process, model);
  }
  return chosen;
}

export function checkHardware(input: HardwareInput): HardwareReport {
  const memoryGib = Math.round((input.memoryBytes / GIB) * 10) / 10;
  const macosMajor = major(input.macosVersion);
  const problems: HardwareProblem[] = [];
  if (input.arch !== "arm64") problems.push({ code: "arch", arch: input.arch });
  if (macosMajor < major(input.minimumMacos)) {
    problems.push({ code: "macos", version: input.macosVersion, minimum: input.minimumMacos });
  }
  const warnings: HardwareWarning[] = [];
  const models = input.models.filter((entry) => entry.kind === "model");
  const chosen = chooseModels(input.models, memoryGib, macosMajor);
  let downloads = input.componentsBytes;
  for (const [process, model] of chosen) {
    const candidates = models.filter((entry) => entry.process === process);
    if (!model) {
      const needed = Math.min(...candidates.map((entry) => entry.min_ram_gib));
      warnings.push({ code: "memory_none", gib: memoryGib, needed, process });
      continue;
    }
    // One model per process, like host-engine's setup plan: no second model is installed behind it.
    downloads += model.size ?? 0;
    // Plus the auxiliary files of its own engine (the voice detector comes with Whisper, not with Parakeet).
    for (const entry of input.models) {
      if (entry.kind === "auxiliary" && entry.default && entry.process === process && entry.engine === model.engine) {
        downloads += entry.size ?? 0;
      }
    }
  }
  const fullNeed = Math.max(0, ...models.map((entry) => entry.min_ram_gib));
  if (fullNeed > memoryGib && !warnings.some((warning) => warning.code === "memory_none")) {
    warnings.push({ code: "memory_lighter", gib: memoryGib, needed: fullNeed, missing: Math.ceil(fullNeed - memoryGib) });
  }
  const neededBytes = Math.ceil(downloads * DISK_MARGIN);
  if (input.diskFreeBytes < neededBytes) {
    warnings.push({ code: "disk_low", neededBytes, missingBytes: neededBytes - input.diskFreeBytes });
  }
  return {
    arch: input.arch,
    macosVersion: input.macosVersion,
    memoryGib,
    diskFreeBytes: input.diskFreeBytes,
    neededBytes,
    problems,
    warnings,
  };
}

/** Free bytes on the disk holding `dir` (or its nearest existing parent). */
export function freeBytes(dir: string): number {
  const stats = fs.statfsSync(dir);
  return stats.bavail * stats.bsize;
}

/** macOS version as the system reports it ("27.2"). Darwin 20+ maps to macOS (major - 9). */
export function macosVersion(): string {
  const getter = (process as NodeJS.Process & { getSystemVersion?: () => string }).getSystemVersion;
  if (getter) return getter();
  return `${Math.max(0, major(os.release()) - 9)}.0`;
}
