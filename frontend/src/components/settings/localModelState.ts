import type { EngineProcess, LocalHardware, LocalJob, LocalModel, LocalRecommendation } from "@sauri/shared-types";
import { LOCAL_DEFAULT_MODEL } from "@sauri/shared-types";
import { EnginesApiError } from "../../api";
import { t, translateIfKnown } from "../../i18n";
import type { LocalModelWithOrigin } from "./customModelsApi";
import { availabilityOf, formatBytes, formatMemory, processList } from "./engineLabels";

/** Same factor as the host's disk check (`DISK_HEADROOM_PERCENT`): the file plus 20 % of room. */
export const DISK_HEADROOM = 1.2;
/** At most this many suggestions in «Agregar»: the person sees reasonable options, not the catalog. */
export const MAX_SUGGESTIONS = 2;

export type RowState = "active" | "installed" | "available" | "unverified" | "verifying" | "installing" | "corrupt";

export type Tone = "neutral" | "progress" | "success" | "error";

export function errorCode(error: unknown): string | null {
  return error instanceof EnginesApiError ? error.code : null;
}

function figure(error: unknown, name: string): number | null {
  const value = error instanceof EnginesApiError ? error.figures[name] : undefined;
  return typeof value === "number" ? value : null;
}

export function describeLocalError(error: unknown): string {
  const code = errorCode(error);
  if (code === "insufficient_disk") {
    const needed = figure(error, "needed_bytes");
    const free = figure(error, "free_bytes");
    if (needed !== null && free !== null) return t("engines:local.insufficientDisk", { needed: formatBytes(needed), free: formatBytes(free) });
  }
  if (code === "model_in_use") {
    const processes = error instanceof EnginesApiError ? error.figures.processes : null;
    if (Array.isArray(processes)) return t("engines:local.modelInUse", { list: processList(processes as EngineProcess[]) });
  }
  return (code && translateIfKnown(`engines:local.errors.${code}`)) || t("engines:local.errors.generic");
}

export function percentOf(job: LocalJob): number {
  return job.bytes_total > 0 ? Math.min(100, Math.floor((job.bytes_done / job.bytes_total) * 100)) : 0;
}

export function reasonText(recommendation: LocalRecommendation, hardware: LocalHardware): string {
  const params = recommendation.reason_params;
  const memory = formatMemory(typeof params.memory_gib === "number" ? params.memory_gib : hardware.memory_gib);
  const minimum = Number(params.min_ram_gib ?? 0);
  switch (recommendation.reason_key) {
    case "fits":
      return minimum > 0 ? t("engines:local.reasons.fitsMinimum", { memory, minimum }) : t("engines:local.reasons.fits", { memory });
    case "reduced": {
      const limited = params.limited_by === "metal" ? t("engines:local.limits.metal")
        : params.limited_by === "macos" ? t("engines:local.limits.macos") : t("engines:local.limits.memory");
      return t("engines:local.reasons.reduced", { memory, better: String(params.better_id ?? ""), limit: limited });
    }
    case "no_local_model":
      if (params.needs === "macos") return t("engines:local.reasons.noModelMacos");
      return params.needs === "metal" ? t("engines:local.reasons.noModelMetal") : t("engines:local.reasons.noModelMemory", { memory, minimum });
    default:
      return t("engines:local.reasons.generic");
  }
}

/** «Mac with Apple silicon chip», «Mac with Intel processor» or the system name and architecture. */
export function chipName(arch: string, system: string): string {
  if (system === "Darwin") return arch === "arm64" ? t("engines:local.chipAppleSilicon") : t("engines:local.chipIntelMac");
  return t("engines:local.chipOther", { system: system || t("engines:local.chipUnknownSystem"), arch });
}

/** A managed engine comes with its engine and is never downloaded from Settings. */
export function isManaged(model: LocalModel): boolean {
  return model.kind === "managed_engine" || model.state === "managed" || model.install?.method === "managed_command";
}

/** The entries of one process, split the way the screen shows them. `options` are a choice of their own: models
 * and the process's own engine (the speaker engine). Supporting files (voice detection) and the engine another
 * model runs on (Parakeet's FluidAudio) are one line each, never a row nor a suggestion. */
export function splitEntries(models: readonly LocalModel[], process: EngineProcess) {
  const own = models.filter((model) => model.process === process);
  const dependencies = new Set(own.flatMap((model) => (model.needs ? [model.needs] : [])));
  return {
    options: own.filter((model) => model.kind !== "auxiliary" && !dependencies.has(model.id)),
    supporting: own.filter((model) => model.kind === "auxiliary"),
    engines: own.filter((model) => dependencies.has(model.id)),
  };
}

export function stateOf(model: LocalModel, running: LocalJob | null, externalActive: boolean, savedKey: string): RowState {
  if (running?.type === "install") return "installing";
  if (running?.type === "verify" || model.verifying === true) return "verifying";
  const availability = availabilityOf(model);
  if (availability === "available") return "available";
  if (availability === "present_unverified") return model.state === "corrupt" ? "corrupt" : "unverified";
  // A pinned model (`local:<id>`) is the active one; with `local:default` the host says which one it resolves to.
  const pinned = savedKey.startsWith("local:") && savedKey !== LOCAL_DEFAULT_MODEL;
  const active = pinned ? savedKey === `local:${model.id}` : (model.active ?? model.in_use_by.includes(model.process));
  return active && !externalActive && model.needs_ready !== false ? "active" : "installed";
}

/** Place of a state in the list: the active model, then the installed ones, then the files that need attention. */
const STATE_RANK: Record<RowState, number> = {
  active: 0,
  installed: 1,
  unverified: 2,
  corrupt: 2,
  verifying: 2,
  installing: 2,
  available: 3,
};

/** The rows of a process in the order they are shown; the catalog order breaks ties, so the list does not jump
 * around. A running job does not move its row: the order reads the files, not the job. */
export function orderOptions(options: readonly LocalModel[], externalActive: boolean, savedKey: string): LocalModel[] {
  const rank = (model: LocalModel) => STATE_RANK[stateOf(model, null, externalActive, savedKey)];
  return options
    .map((model, index) => ({ model, index, rank: rank(model) }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((entry) => entry.model);
}

/** What the person has of a process: present on disk (verified or not), or being downloaded right now. */
export function installedRows(options: readonly LocalModel[], job: LocalJob | null, externalActive: boolean, savedKey: string): LocalModel[] {
  const downloading = job?.state === "running" && job.type === "install" ? job.model_id : null;
  return orderOptions(
    options.filter((model) => availabilityOf(model) !== "available" || model.verifying === true || model.id === downloading),
    externalActive,
    savedKey,
  );
}

/** True when this computer meets what the model asks for: memory, Metal and the macOS version. */
export function fitsHardware(model: LocalModel, hardware: LocalHardware): boolean {
  if (model.min_ram_gib > hardware.memory_gib) return false;
  if (model.requires.includes("metal") && !hardware.metal) return false;
  if (model.min_macos && hardware.macos_major && hardware.macos_major < model.min_macos) return false;
  return true;
}

/** Catalog entries that could be added: not on the computer, downloadable from here (not a managed engine, not an
 * unpublished component) and supported by this hardware. */
export function addable(options: readonly LocalModel[]): LocalModel[] {
  return options.filter((model) => availabilityOf(model) === "available" && !isManaged(model) && model.install?.source_available !== false);
}

/** At most two suggestions for this computer, the recommended one first, then in catalog order. */
export function suggestionsFor(
  options: readonly LocalModel[],
  hardware: LocalHardware,
  recommendation: LocalRecommendation | undefined,
): LocalModel[] {
  const recommended = (model: LocalModel) => recommendation?.model_id === model.id || model.recommended;
  return addable(options)
    .filter((model) => fitsHardware(model, hardware))
    .map((model, index) => ({ model, index, rank: recommended(model) ? 0 : 1 }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .slice(0, MAX_SUGGESTIONS)
    .map((entry) => entry.model);
}

/** The space an install needs: what the host says, else the download plus the same headroom. */
export function spaceNeeded(model: LocalModel): number | null {
  return model.install?.disk_required_bytes ?? (model.size !== null ? Math.ceil(model.size * DISK_HEADROOM) : null);
}

/** The size the model takes on disk once installed. */
export function diskSize(model: LocalModel): number | null {
  return model.installed_size ?? model.size;
}

/** The last part of a file path, which is what people recognize on Hugging Face. */
export function fileName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** The name a person reads: engines and components by their plain name, a model of the person's own by its file
 * (its id is a hash), other models by their id. */
export function displayName(model: LocalModel): string {
  const source = originOf(model);
  if (isCustom(model) && source) return fileName(source.file);
  const titled = model.kind === "managed_engine" || model.kind === "component";
  return (titled && translateIfKnown(`engines:local.managedTitle.${model.process}`)) || model.id;
}

export function isCustom(model: LocalModel): model is LocalModelWithOrigin & { custom: true } {
  return (model as LocalModelWithOrigin).custom === true;
}

export function originOf(model: LocalModel) {
  return (model as LocalModelWithOrigin).origin ?? null;
}

/** First characters of a commit, as people see them on Hugging Face. */
export function shortRevision(revision: string): string {
  return revision.slice(0, 7);
}

export function unverifiedText(model: LocalModel): string {
  const reason = model.reason ?? (model.state === "corrupt" ? "hash_mismatch" : null);
  return translateIfKnown(`engines:local.unverifiedReason.${reason ?? "generic"}`) ?? t("engines:local.unverifiedReason.generic");
}

/** The reason removal is not offered, or null when it is. */
export function removalBlock(model: LocalModel): string | null {
  if (model.location === "legacy") return t("engines:local.manualNote");
  const inUse = model.in_use ?? model.in_use_by.length > 0;
  if (!inUse) return null;
  return model.in_use_by.length > 0 ? t("engines:local.removeBlocked", { list: processList(model.in_use_by) }) : t("engines:local.removeBlockedGeneric");
}

/** The plain-language note of a model (key of `engines:local.modelNotes`), by the engine that runs it. */
export function modelNoteKey(model: LocalModel): "parakeet" | "whisper" | null {
  if (isCustom(model)) return null;
  if (model.engine === "fluidaudio" && model.kind === "model") return "parakeet";
  if (model.engine === "whisper.cpp" && model.kind === "model" && model.process === "transcription") return "whisper";
  return null;
}

/** What a model is good for, in one short line. */
export function shortNote(model: LocalModel, siblings: readonly LocalModel[]): string {
  if (model.kind === "model" && model.process === "transcription") {
    if (model.engine === "fluidaudio") return t("engines:local.short.parakeet");
    if (model.engine === "whisper.cpp") {
      const reference = siblings.find((other) => other.default && other.kind === "model" && other.process === model.process);
      const lighter = !model.default && reference?.size && model.size !== null && model.size < reference.size;
      return t(lighter ? "engines:local.short.whisperLight" : "engines:local.short.whisper");
    }
  }
  if (model.kind === "model" && model.process === "summary" && model.min_ram_gib > 0) {
    return t(model.default ? "engines:local.short.summaryFull" : "engines:local.short.summaryLight", { minRam: model.min_ram_gib });
  }
  if (model.process === "diarization") return t("engines:local.short.speakers");
  return model.min_ram_gib > 0
    ? t("engines:local.descriptionMinRam", { engine: model.engine, minRam: model.min_ram_gib })
    : t("engines:local.description", { engine: model.engine });
}

/** The single state tag of an installed row; it is always written, never only a color. */
export function tagOf(state: RowState): { tone: Tone; text: string } | null {
  switch (state) {
    case "active":
      return { tone: "success", text: t("engines:local.tags.active") };
    case "installed":
      return { tone: "neutral", text: t("engines:local.tags.installed") };
    case "unverified":
      return { tone: "progress", text: t("engines:local.tags.unverified") };
    case "verifying":
      return { tone: "progress", text: t("engines:local.tags.verifying") };
    case "installing":
      return { tone: "progress", text: t("engines:local.tags.installing") };
    case "corrupt":
      return { tone: "error", text: t("engines:local.tags.corrupt") };
    default:
      return null;
  }
}
