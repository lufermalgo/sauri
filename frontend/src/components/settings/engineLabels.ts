import type { EngineProcess } from "@sauri/shared-types";
import { copy } from "../../copy/es";

/** Comma separated display names of the processes, in the order the API gave them. */
export function processList(processes: readonly EngineProcess[]): string {
  return processes.map((process) => copy.engines.processes[process]).join(", ");
}
