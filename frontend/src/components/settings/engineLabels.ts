import type { EngineProcess } from "@sauri/shared-types";
import { copy } from "../../copy/es";

/** Comma separated display names of the processes, in the order the API gave them. */
export function processList(processes: readonly EngineProcess[]): string {
  return processes.map((process) => copy.engines.processes[process]).join(", ");
}

const BYTES_PER_MB = 1_000_000;
const BYTES_PER_GB = 1_000_000_000;
const decimals = new Intl.NumberFormat("es", { maximumFractionDigits: 1 });

/** File and disk sizes in the units the download page shows: MB below one GB, GB above. */
export function formatBytes(bytes: number): string {
  if (bytes >= BYTES_PER_GB) return `${decimals.format(bytes / BYTES_PER_GB)} GB`;
  return `${decimals.format(Math.max(Math.round(bytes / BYTES_PER_MB), bytes > 0 ? 1 : 0))} MB`;
}

/** Memory as people read it on the machine's spec sheet: whole gigabytes. */
export function formatMemory(gib: number): string {
  return `${Math.round(gib)} GB`;
}
