import type { EngineProcess, EngineProviderKind } from "@sauri/shared-types";
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

const clock = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", hour12: false });
const calendarDay = new Intl.DateTimeFormat("es", { day: "numeric", month: "short" });

/** When a model list was asked for: "hoy 03:08" for today, "16 nov, 03:08" for another day. */
export function formatFetchedAt(iso: string, now: Date = new Date()): string {
  const moment = new Date(iso);
  const time = clock.format(moment);
  if (moment.toDateString() === now.toDateString()) return copy.engines.catalog.today(time);
  return copy.engines.catalog.otherDay(calendarDay.format(moment), time);
}

/** Kinds that run as a program on this computer: no key is asked for and the usual address is filled in. */
export function isLocalApp(kind: EngineProviderKind): boolean {
  return kind === "ollama" || kind === "lmstudio";
}
