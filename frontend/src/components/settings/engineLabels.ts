import type { EngineProcess, EngineProviderKind, LocalModel, LocalModelAvailability } from "@sauri/shared-types";
import { t } from "../../i18n";
import { formatDate, formatList, formatNumber } from "../../i18n/format";

/** Display names of the processes as a list ("Transcription, Speakers and Summaries"), in the order the API gave them. */
export function processList(processes: readonly EngineProcess[]): string {
  return formatList(processes.map((process) => t(`engines:processes.${process}`)));
}

const BYTES_PER_MB = 1_000_000;
const BYTES_PER_GB = 1_000_000_000;
const oneDecimal = (value: number) => formatNumber(value, { maximumFractionDigits: 1 });

/** File and disk sizes in the units the download page shows: MB below one GB, GB above. */
export function formatBytes(bytes: number): string {
  if (bytes >= BYTES_PER_GB) return `${oneDecimal(bytes / BYTES_PER_GB)} GB`;
  return `${oneDecimal(Math.max(Math.round(bytes / BYTES_PER_MB), bytes > 0 ? 1 : 0))} MB`;
}

/** Memory as people read it on the machine's spec sheet: whole gigabytes. */
export function formatMemory(gib: number): string {
  return `${Math.round(gib)} GB`;
}

/** When a model list was asked for: "today 03:08" for today, "Nov 16, 03:08" for another day. */
export function formatFetchedAt(iso: string, now: Date = new Date()): string {
  const moment = new Date(iso);
  const time = formatDate(moment, { hour: "2-digit", minute: "2-digit" });
  if (moment.toDateString() === now.toDateString()) return t("engines:catalog.today", { time });
  return t("engines:catalog.otherDay", { day: formatDate(moment, { day: "numeric", month: "short" }), time });
}

/** Kinds that run as a program on this computer: no key is asked for and the usual address is filled in. */
export function isLocalApp(kind: EngineProviderKind): boolean {
  return kind === "ollama" || kind === "lmstudio";
}

/** What this computer has of a model. Older answers carry only `state`, which maps onto the same three values. */
export function availabilityOf(model: LocalModel): LocalModelAvailability {
  if (model.availability) return model.availability;
  if (model.state === "installed" || model.state === "managed") return "installed";
  if (model.state === "unverified" || model.state === "corrupt") return "present_unverified";
  return "available";
}
