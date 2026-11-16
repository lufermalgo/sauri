import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, Terminal } from "lucide-react";
import type {
  EngineProcess,
  LocalHardware,
  LocalJob,
  LocalModel,
  LocalModelList,
  LocalRecommendation,
} from "@sauri/shared-types";
import { LOCAL_DEFAULT_MODEL } from "@sauri/shared-types";
import {
  EnginesApiError,
  adoptLocalModels,
  cancelLocalJob,
  getEngineStatus,
  getLocalHardware,
  getLocalJob,
  installLocalModel,
  listLocalModels,
  removeLocalModel,
  verifyLocalModel,
} from "../../api";
import { Button, Card, ConfirmDialog, Icon, Menu, MenuItem, ProgressBar, Skeleton, StatusBadge } from "../ui";
import { availabilityOf, formatBytes, formatMemory, processList, resolvedDefault } from "./engineLabels";
import "../../styles/engines.css";
import { t, translateIfKnown, useT } from "../../i18n";

/** Wait between two looks at a running install or check; the host answers each look at once. */
export const JOB_POLL_INTERVAL_MS = 1000;
/** Consecutive failed looks after which the card stops asking and tells the person. */
const MAX_POLL_FAILURES = 5;
/** Looks at the catalog while files are still being recognized; after that the card stops asking. */
const MAX_VERIFY_LOOKS = 300;
/** Same factor as the host's disk check (`DISK_HEADROOM_PERCENT`): the file plus 20 % of room. */
const DISK_HEADROOM = 1.2;

/** Which native engine runs each process (ports and ids of `host-engine`'s status). */
const ENGINE_OF: Record<EngineProcess, string> = { transcription: "asr", diarization: "diar", summary: "llm" };

/** Adoption outcomes that leave a file on disk that is not confirmed as the catalog's. */
const ATTENTION_OUTCOMES = new Set(["present_unverified", "changed", "unreadable"]);

type RowState = "active" | "installed" | "available" | "unverified" | "verifying" | "installing" | "corrupt";

const STATE_TONE: Record<RowState, "neutral" | "progress" | "success" | "error"> = {
  active: "success",
  installed: "success",
  available: "neutral",
  unverified: "progress",
  verifying: "progress",
  installing: "progress",
  corrupt: "error",
};

type Load =
  | { status: "loading" }
  | { status: "error"; hostDown: boolean }
  | { status: "ready"; hardware: LocalHardware; list: LocalModelList; engineRunning: boolean | null };

type Outcome = { kind: "success" | "error"; text: string } | null;

function errorCode(error: unknown): string | null {
  return error instanceof EnginesApiError ? error.code : null;
}

function figure(error: unknown, name: string): number | null {
  const value = error instanceof EnginesApiError ? error.figures[name] : undefined;
  return typeof value === "number" ? value : null;
}

function describeLocalError(error: unknown): string {
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

function percentOf(job: LocalJob): number {
  return job.bytes_total > 0 ? Math.min(100, Math.floor((job.bytes_done / job.bytes_total) * 100)) : 0;
}

function reasonText(recommendation: LocalRecommendation, hardware: LocalHardware): string {
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

/** What the process saved: a provider (`external`) or a local model, and the key it was saved under. */
export interface LocalSelection {
  external: boolean;
  /** `local:default`, `local:<id>` or the provider's model; changes whenever the choice is saved. */
  key: string;
}

/** The «Servicios externos» row group: the external choice beside the local ones. The privacy notice and
 * the provider list live in the engine selector, which `onChoose` opens. */
export interface ExternalChoice {
  /** «Provider, model» while an external provider serves the process; null while it runs here. */
  current: string | null;
  /** True when an active provider with a key can serve this process. */
  hasProviders: boolean;
  onChoose: () => void;
  onSetup: () => void;
}

interface LocalModelCardProps {
  process: EngineProcess;
  selection: LocalSelection;
  /** Called with the catalog every time it is read, so the engine selector can offer installed models. */
  onModelsChange?: (models: LocalModel[]) => void;
  /** Sets this local model as the one the process uses (saved at once, no privacy notice). */
  onUse: (choiceKey: string) => void;
  /** True while the screen is saving a choice. */
  choosing?: boolean;
  external: ExternalChoice;
  /** Wait between looks at a running job; tests shorten it. */
  pollIntervalMs?: number;
}

/** The choice key `onUse` hands back: the model `local:default` runs now (the preferred one when it is ready, else
 * the catalog default) is `local:default`, any other `local:<id>`. */
export function choiceKeyOf(model: LocalModel, models: readonly LocalModel[] = [model]): string {
  const resolved = resolvedDefault(models, model.process);
  return (resolved ? resolved.id === model.id : model.default) ? LOCAL_DEFAULT_MODEL : `local:${model.id}`;
}

/** "En este equipo" for one process: the computer in plain words and, for each local option, whether it is
 * installed, active now or can still be installed, with install (progress and cancel), verify and remove.
 * Models installed by hand are shown like any other. A running job is followed by short, bounded looks that
 * stop when the card goes away. */
export function LocalModelCard({
  process,
  selection,
  onModelsChange,
  onUse,
  choosing = false,
  external,
  pollIntervalMs = JOB_POLL_INTERVAL_MS,
}: LocalModelCardProps) {
  const { t } = useT();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [job, setJob] = useState<LocalJob | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<LocalModel | null>(null);
  const [busyModel, setBusyModel] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const onModelsChangeRef = useRef(onModelsChange);
  onModelsChangeRef.current = onModelsChange;

  const adopt = useCallback((list: LocalModelList) => {
    onModelsChangeRef.current?.(list.models);
    return list;
  }, []);

  const fetchAll = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    Promise.all([
      getLocalHardware(),
      listLocalModels(),
      getEngineStatus().then(
        (status) => status.engines.find((engine) => engine.id === ENGINE_OF[process])?.state === "running",
        () => null,
      ),
    ]).then(
      ([hardware, list, engineRunning]) => {
        if (!current) return;
        adopt(list);
        setLoad({ status: "ready", hardware, list, engineRunning });
        // A job started before this screen opened keeps going: pick it up.
        if (list.active_job) {
          getLocalJob(list.active_job).then(
            (running) => current && running.state === "running" && setJob(running),
            () => undefined,
          );
        }
      },
      (error) => current && setLoad({ status: "error", hostDown: errorCode(error) === "host_unavailable" }),
    );
    return () => {
      current = false;
    };
  }, [process, adopt]);

  useEffect(() => fetchAll(), [fetchAll]);

  /** Re-reads the catalog after something changed on disk, keeping the hardware already shown. */
  const reloadModels = useCallback(async () => {
    try {
      const list = adopt(await listLocalModels());
      setLoad((previous) => (previous.status === "ready" ? { ...previous, list } : previous));
    } catch {
      // The old list stays on screen; the next action reports a failure if the host is really gone.
    }
  }, [adopt]);

  // The saved choice changed (here or in the selector): which model is active now changes with it.
  const selectionKey = `${selection.external}|${selection.key}`;
  const firstSelection = useRef(selectionKey);
  useEffect(() => {
    if (selectionKey !== firstSelection.current) {
      firstSelection.current = selectionKey;
      void reloadModels();
    }
  }, [selectionKey, reloadModels]);

  const finishJob = useCallback(
    (finished: LocalJob) => {
      setJob(null);
      setCancelling(false);
      const id = finished.model_id;
      if (finished.state === "cancelled") setOutcome({ kind: "success", text: t("engines:local.outcome.cancelled") });
      else if (finished.state === "failed") {
        const cause = (finished.error && translateIfKnown(`engines:local.jobErrors.${finished.error}`)) || t("engines:local.errors.generic");
        setOutcome({ kind: "error", text: t("engines:local.outcome.failed", { cause }) });
      } else if (finished.type === "adopt") {
        setOutcome({ kind: "success", text: finished.result === "adopted" ? t("engines:local.adoption.done") : t("engines:local.adoption.nothing") });
      } else if (finished.type === "install") setOutcome({ kind: "success", text: t("engines:local.outcome.installed", { id }) });
      else if (finished.result === "corrupt") setOutcome({ kind: "error", text: t("engines:local.outcome.corrupt", { id }) });
      else setOutcome({ kind: "success", text: t("engines:local.outcome.verified", { id }) });
      void reloadModels();
    },
    [reloadModels],
  );
  const finishJobRef = useRef(finishJob);
  finishJobRef.current = finishJob;

  const runningJobId = job?.state === "running" ? job.id : null;
  useEffect(() => {
    if (!runningJobId) return;
    let stopped = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const look = async () => {
      try {
        const next = await getLocalJob(runningJobId);
        if (stopped) return;
        failures = 0;
        if (next.state === "running") setJob(next);
        else {
          finishJobRef.current(next);
          return;
        }
      } catch {
        if (stopped) return;
        failures += 1;
        if (failures >= MAX_POLL_FAILURES) {
          setJob(null);
          setOutcome({ kind: "error", text: t("engines:local.outcome.lost") });
          return;
        }
      }
      timer = setTimeout(look, pollIntervalMs);
    };
    timer = setTimeout(look, pollIntervalMs);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runningJobId, pollIntervalMs]);

  // Files found at startup are checked in the background: look at the catalog until none is left.
  const recognizing = load.status === "ready" && load.list.models.some((model) => model.verifying === true);
  useEffect(() => {
    if (!recognizing || runningJobId) return;
    let looks = 0;
    const timer = setInterval(() => {
      looks += 1;
      if (looks > MAX_VERIFY_LOOKS) clearInterval(timer);
      else void reloadModels();
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [recognizing, runningJobId, pollIntervalMs, reloadModels]);

  async function start(model: LocalModel, action: "install" | "verify") {
    setOutcome(null);
    setBusyModel(model.id);
    try {
      setJob(await (action === "install" ? installLocalModel(model.id) : verifyLocalModel(model.id)));
    } catch (error) {
      setOutcome({ kind: "error", text: describeLocalError(error) });
      if (errorCode(error) === "job_active") fetchAll();
    } finally {
      setBusyModel(null);
    }
  }

  async function scan() {
    setOutcome(null);
    try {
      setJob(await adoptLocalModels());
    } catch (error) {
      setOutcome({ kind: "error", text: describeLocalError(error) });
      if (errorCode(error) === "job_active") fetchAll();
    }
  }

  async function cancel() {
    if (!job) return;
    setCancelling(true);
    try {
      finishJob(await cancelLocalJob(job.id));
    } catch (error) {
      setCancelling(false);
      // The job may have ended on its own just before; the next look settles it.
      setOutcome({ kind: "error", text: describeLocalError(error) });
    }
  }

  async function confirmRemoval(model: LocalModel) {
    setPendingRemoval(null);
    setOutcome(null);
    setBusyModel(model.id);
    try {
      await removeLocalModel(model.id);
      setOutcome({ kind: "success", text: t("engines:local.outcome.removed", { id: model.id }) });
    } catch (error) {
      setOutcome({ kind: "error", text: describeLocalError(error) });
    } finally {
      setBusyModel(null);
      void reloadModels();
    }
  }

  const jobRunning = job?.state === "running";
  const adoptionAttention =
    load.status === "ready" &&
    load.list.models.some(
      (model) => model.process === process && ATTENTION_OUTCOMES.has(load.list.adoption?.outcomes[model.id] ?? ""),
    );

  return (
    <Card className="engines-local" aria-labelledby={`engines-local-${process}`}>
      <div className="engines-local-head">
        <h3 id={`engines-local-${process}`} className="engines-card-title">{t("engines:local.title")}</h3>
        {load.status === "ready" && (
          <Menu label={t("engines:local.cardMenu")} className="engines-local-menu">
            <MenuItem onSelect={() => void scan()} disabled={jobRunning} hint={jobRunning ? t("engines:local.busy") : undefined}>
              {t("engines:local.scan")}
            </MenuItem>
          </Menu>
        )}
      </div>

      {load.status === "loading" && (
        <div role="status" className="settings-loading">
          <p className="settings-help">{t("engines:local.loading")}</p>
          <Skeleton width="100%" height="4rem" radius="md" />
        </div>
      )}
      {load.status === "error" && (
        <div className="settings-load-error">
          {load.hostDown ? <EngineMissing process={process} host /> : (
            <p role="alert" className="ui-field-error">{t("engines:local.loadError")}</p>
          )}
          <Button variant="secondary" onClick={fetchAll}>{t("engines:local.retry")}</Button>
        </div>
      )}

      {load.status === "ready" && (
        <>
          <HardwareSummary hardware={load.hardware} recommendation={load.list.recommendations[process]} />
          {load.engineRunning === false && <EngineMissing process={process} />}
          <div role="status" className="engines-local-recognizing">
            {recognizing || job?.type === "adopt" ? t("engines:local.adoption.recognizing") : null}
          </div>
          {adoptionAttention && <p className="settings-help">{t("engines:local.adoption.attention")}</p>}
          <ModelList
            process={process}
            models={load.list.models.filter((model) => model.process === process)}
            job={job}
            cancelling={cancelling}
            busyModel={busyModel}
            choosing={choosing}
            externalActive={selection.external}
            savedKey={selection.key}
            onUse={(model) => onUse(choiceKeyOf(model, load.list.models))}
            onInstall={(model) => start(model, "install")}
            onVerify={(model) => start(model, "verify")}
            onRemove={setPendingRemoval}
            onCancel={cancel}
          />
          <ExternalGroup external={external} />
        </>
      )}

      <div role="status" className="settings-notice">{outcome?.kind === "success" ? outcome.text : null}</div>
      {outcome?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{outcome.text}</p>}

      {pendingRemoval && (
        <ConfirmDialog
          title={t("engines:local.removeTitle")}
          body={<p>{t("engines:local.removeBody", { id: pendingRemoval.id, size: formatBytes(pendingRemoval.installed_size ?? pendingRemoval.size ?? 0) })}</p>}
          confirmLabel={t("engines:local.removeConfirm")}
          cancelLabel={t("engines:local.removeCancel")}
          onConfirm={() => confirmRemoval(pendingRemoval)}
          onCancel={() => setPendingRemoval(null)}
        />
      )}
    </Card>
  );
}

/** «Mac with Apple silicon chip», «Mac with Intel processor» or the system name and architecture. */
function chipName(arch: string, system: string): string {
  if (system === "Darwin") return arch === "arm64" ? t("engines:local.chipAppleSilicon") : t("engines:local.chipIntelMac");
  return t("engines:local.chipOther", { system: system || t("engines:local.chipUnknownSystem"), arch });
}

function HardwareSummary({ hardware, recommendation }: { hardware: LocalHardware; recommendation: LocalRecommendation | undefined }) {
  const { t } = useT();
  const warnings = recommendation?.warnings ?? [];
  return (
    <section className="engines-local-section" aria-label={t("engines:local.hardwareTitle")}>
      <p>
        {t("engines:local.hardware", {
          chip: chipName(hardware.arch, hardware.system),
          memory: formatMemory(hardware.memory_gib),
          count: hardware.cores,
          free: formatBytes(hardware.disk_free_bytes),
        })}
      </p>
      <p className="settings-help">{hardware.metal ? t("engines:local.metalYes") : t("engines:local.metalNo")}</p>
      {recommendation && (
        <p className="settings-help">
          {recommendation.model_id ? "" : `${t("engines:local.noRecommendation")} `}
          {reasonText(recommendation, hardware)}
        </p>
      )}
      {warnings.length > 0 && (
        <ul className="engines-local-warnings">
          {warnings.map((warning) => (
            <li key={warning}>{translateIfKnown(`engines:local.warnings.${warning}`) ?? warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The engine does not answer: either it was never installed or it is stopped. The portal cannot tell
 * which tools are missing, so it names the ones this engine needs along with the command. */
function EngineMissing({ process, host = false }: { process: EngineProcess; host?: boolean }) {
  const { t } = useT();
  return (
    <section className="engines-missing" aria-label={t("engines:local.engineMissing.title")}>
      <h4 className="engines-missing-title">
        <Icon icon={CircleAlert} />
        {t("engines:local.engineMissing.title")}
      </h4>
      <p>{host ? t("engines:local.engineMissing.hostBody") : t("engines:local.engineMissing.body", { engine: t(`engines:local.engineNames.${process}`) })}</p>
      <p>{t("engines:local.engineMissing.installIntro")}</p>
      <p><code className="engines-command"><Icon icon={Terminal} size={14} />{t("engines:local.engineMissing.installCommand")}</code></p>
      <p className="settings-help">{t("engines:local.engineMissing.tools", { list: t(`engines:local.engineTools.${process}`) })}</p>
      <p className="settings-help">{t("engines:local.engineMissing.startIntro")} <code className="engines-command">{t("engines:local.engineMissing.startCommand")}</code></p>
    </section>
  );
}

interface ModelListProps {
  process: EngineProcess;
  models: LocalModel[];
  job: LocalJob | null;
  cancelling: boolean;
  busyModel: string | null;
  choosing: boolean;
  externalActive: boolean;
  /** The saved choice (`local:default` or `local:<id>`): what is active follows it, not the host's guess. */
  savedKey: string;
  onUse: (model: LocalModel) => void;
  onInstall: (model: LocalModel) => void;
  onVerify: (model: LocalModel) => void;
  onRemove: (model: LocalModel) => void;
  onCancel: () => void;
}

/** The options of the process (models and managed engines), then the supporting files in one line each. */
function ModelList(props: ModelListProps) {
  const { t } = useT();
  const { process, models, job } = props;
  const options = models.filter((model) => model.kind !== "auxiliary");
  const supporting = models.filter((model) => model.kind === "auxiliary");
  const jobRunning = job?.state === "running" && job.type !== "adopt";
  return (
    <section className="engines-local-section" aria-label={t("engines:local.modelsTitle")}>
      {options.length === 0 && <p className="settings-help">{t("engines:local.noModels")}</p>}
      {jobRunning && <p className="settings-help">{t("engines:local.busy")}</p>}
      <ul className="engines-local-models" aria-label={t("engines:local.modelsTitle")}>
        {options.map((model) => <ModelRow key={model.id} {...props} model={model} />)}
      </ul>
      {supporting.map((model) => <SupportLine key={model.id} {...props} model={model} idPrefix={`engines-model-${process}`} />)}
    </section>
  );
}

type RowProps = ModelListProps & { model: LocalModel };

function stateOf(model: LocalModel, running: LocalJob | null, externalActive: boolean, savedKey: string): RowState {
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

function unverifiedText(model: LocalModel): string {
  const reason = model.reason ?? (model.state === "corrupt" ? "hash_mismatch" : null);
  return translateIfKnown(`engines:local.unverifiedReason.${reason ?? "generic"}`) ?? t("engines:local.unverifiedReason.generic");
}

/** The reason removal is not offered, or null when it is. */
function removalBlock(model: LocalModel): string | null {
  if (model.location === "legacy") return t("engines:local.manualNote");
  const inUse = model.in_use ?? model.in_use_by.length > 0;
  if (!inUse) return null;
  return model.in_use_by.length > 0 ? t("engines:local.removeBlocked", { list: processList(model.in_use_by) }) : t("engines:local.removeBlockedGeneric");
}

/** The plain-language note of a model (key of `engines:local.modelNotes`), by the engine that runs it. */
function modelNoteKey(model: LocalModel): "parakeet" | "whisper" | null {
  if (model.engine === "fluidaudio" && model.kind === "model") return "parakeet";
  if (model.engine === "whisper.cpp" && model.kind === "model" && model.process === "transcription") return "whisper";
  return null;
}

function ModelRow(props: RowProps) {
  const { t } = useT();
  const { process, model, job, cancelling, busyModel, choosing, externalActive, savedKey, onUse, onInstall, onVerify, onRemove, onCancel } = props;
  const jobRunning = job?.state === "running";
  const running = jobRunning && job.model_id === model.id ? job : null;
  const state = stateOf(model, running, externalActive, savedKey);
  const blocked = jobRunning || busyModel !== null;
  const managed = model.kind === "managed_engine" || model.state === "managed" || model.install?.method === "managed_command";
  const name = (model.kind === "managed_engine" && translateIfKnown(`engines:local.managedTitle.${process}`)) || model.id;
  const titleId = `engines-model-${process}-${model.id}`;
  const size = model.size ?? model.installed_size;
  const installed = availabilityOf(model) === "installed";
  const command = model.install?.managed_by ?? model.managed_by;
  const needed = model.install?.disk_required_bytes ?? (model.size !== null ? Math.ceil(model.size * DISK_HEADROOM) : null);
  const noRoom = model.install?.fits_on_disk === false;
  const removal = removalBlock(model);
  const inUse = model.in_use ?? model.in_use_by.length > 0;
  const siblings = props.models;
  const noteKey = modelNoteKey(model);
  const isFallback = model.default && siblings.some((other) => other.preferred === true);
  const engineEntry = model.needs ? siblings.find((other) => other.id === model.needs) : undefined;
  const missingEngine = installed && model.needs_ready === false;

  return (
    <li
      className={`engines-local-row${state === "active" ? " engines-local-row--active" : ""}`}
      aria-labelledby={titleId}
    >
      <div className="engines-local-row-main">
        <div className="engines-local-row-head">
          <span id={titleId} className="engines-local-model-name">{name}</span>
          {size !== null && <span className="engines-local-size">{formatBytes(size)}</span>}
        </div>
        <div className="engines-local-badges">
          {state === "active" && <StatusBadge tone="success">{t("engines:local.states.installed")}</StatusBadge>}
          <StatusBadge tone={STATE_TONE[state]} dot={state === "active"}>{t(`engines:local.states.${state}`)}</StatusBadge>
          {model.location === "legacy" && <StatusBadge tone="neutral">{t("engines:local.manual")}</StatusBadge>}
          {model.recommended && <StatusBadge tone="success">{t("engines:local.recommended")}</StatusBadge>}
          {isFallback && <StatusBadge tone="neutral">{t("engines:local.fallbackBadge")}</StatusBadge>}
          {model.kind !== "managed_engine" && (
            <StatusBadge tone={model.status === "measured" ? "success" : "progress"}>{t(`engines:local.marks.${model.status}`)}</StatusBadge>
          )}
        </div>
        <p className="settings-help">
          {managed && installed ? t("engines:local.managedInstalled") : (model.min_ram_gib > 0 ? t("engines:local.descriptionMinRam", { engine: model.engine, minRam: model.min_ram_gib }) : t("engines:local.description", { engine: model.engine }))}
          {installed && model.verified_by && ` ${t(`engines:local.verifiedBy.${model.verified_by}`)}`}
        </p>
        {noteKey && <p className="settings-help">{t(`engines:local.modelNotes.${noteKey}`)}</p>}
        {missingEngine && (
          <p className="settings-help">
            {t("engines:local.needsEngine", { command: `bash ${engineEntry?.managed_by ?? engineEntry?.install?.managed_by ?? "scripts/engines/install-parakeet-engine.sh"}` })}
          </p>
        )}
        {model.license && model.attribution && (
          <p className="settings-help">{t("engines:local.license", { license: model.license, attribution: model.attribution })}</p>
        )}
        {(state === "unverified" || state === "corrupt") && <p className="settings-help">{unverifiedText(model)}</p>}
        {inUse && model.in_use_by.length > 0 && state !== "available" && (
          <p className="settings-help">{t("engines:local.inUse", { list: processList(model.in_use_by) })}</p>
        )}
        {managed && !installed && !running && command && <p className="settings-help">{t("engines:local.managedHow", { command: `bash ${command}` })}</p>}
        {noRoom && !running && needed !== null && (
          <p id={`${titleId}-room`} className="settings-help">{t("engines:local.notEnoughSpace", { size: formatBytes(needed) })}</p>
        )}
      </div>

      {!running && (
        <div className="engines-local-row-actions">
          {state === "installed" && !missingEngine && (
            <Button variant="secondary" size="sm" aria-label={t("engines:local.useLabel", { name })} disabled={choosing || blocked} onClick={() => onUse(model)}>
              {t("engines:local.use")}
            </Button>
          )}
          {state === "available" && !managed && (
            <>
              {needed !== null && !noRoom && <span className="settings-help">{t("engines:local.spaceNeeded", { size: formatBytes(needed) })}</span>}
              <Button
                variant="primary"
                size="sm"
                aria-label={t("engines:local.installLabel", { id: name })}
                aria-describedby={noRoom ? `${titleId}-room` : undefined}
                disabled={blocked || noRoom}
                onClick={() => onInstall(model)}
              >
                {t("engines:local.install")}
              </Button>
            </>
          )}
          {(state === "unverified" || state === "corrupt") && (
            <Button variant="secondary" size="sm" aria-label={t("engines:local.verifyLabel", { id: name })} disabled={blocked} onClick={() => onVerify(model)}>
              {t("engines:local.verify")}
            </Button>
          )}
          {!managed && availabilityOf(model) !== "available" && state !== "verifying" && (
            <Menu label={t("engines:local.moreLabel", { name })}>
              <MenuItem onSelect={() => onVerify(model)} disabled={blocked}>{t("engines:local.verify")}</MenuItem>
              <MenuItem tone="danger" onSelect={() => onRemove(model)} disabled={blocked || removal !== null} hint={removal ?? undefined}>
                {t("engines:local.remove")}
              </MenuItem>
              {removal && <p role="presentation" className="engines-local-menu-note">{removal}</p>}
            </Menu>
          )}
        </div>
      )}

      {running && <JobProgress job={running} cancelling={cancelling} onCancel={onCancel} />}
    </li>
  );
}

/** A file that supports the process (voice detection): one line, not a choice. Offers to install it when missing. */
function SupportLine({ model, job, busyModel, cancelling, onInstall, onCancel, idPrefix }: RowProps & { idPrefix: string }) {
  const { t } = useT();
  const jobRunning = job?.state === "running";
  const running = jobRunning && job.model_id === model.id ? job : null;
  const availability = availabilityOf(model);
  const name = model.id;
  const state = running ? t("engines:local.states.installing") : availability === "installed" ? t("engines:local.states.installed") : availability === "available" ? t("engines:local.states.available") : t("engines:local.states.unverified");
  const canInstall = availability === "available" && !running;
  return (
    <div className="engines-local-support" id={`${idPrefix}-${model.id}`}>
      <p className="settings-help">{t("engines:local.auxiliaryLine", { name, state })}</p>
      {canInstall && (
        <Button variant="secondary" size="sm" aria-label={t("engines:local.installLabel", { id: name })} disabled={jobRunning || busyModel !== null} onClick={() => onInstall(model)}>
          {t("engines:local.install")}
        </Button>
      )}
      {running && <JobProgress job={running} cancelling={cancelling} onCancel={onCancel} />}
    </div>
  );
}

function ExternalGroup({ external }: { external: ExternalChoice }) {
  const { t } = useT();
  const titleId = "engines-external-title";
  return (
    <section className="engines-local-section engines-local-external" aria-labelledby={titleId}>
      <h4 id={titleId} className="settings-group-title">{t("engines:local.external.title")}</h4>
      <div className={`engines-local-row${external.current ? " engines-local-row--active" : ""}`}>
        <div className="engines-local-row-main">
          {external.current && (
            <div className="engines-local-badges">
              <span className="engines-local-model-name">{external.current}</span>
              <StatusBadge tone="success" dot>{t("engines:local.states.active")}</StatusBadge>
            </div>
          )}
          <p className="settings-help">{t("engines:local.external.help")}</p>
        </div>
        <div className="engines-local-row-actions">
          <Button variant="secondary" size="sm" onClick={external.hasProviders ? external.onChoose : external.onSetup}>
            {external.hasProviders ? t("engines:local.external.choose") : t("engines:local.external.setup")}
          </Button>
        </div>
      </div>
    </section>
  );
}

function JobProgress({ job, cancelling, onCancel }: { job: LocalJob; cancelling: boolean; onCancel: () => void }) {
  const { t } = useT();
  const percent = percentOf(job);
  const sentence = job.type === "install" ? t("engines:local.installing", { id: job.model_id, percent }) : t("engines:local.verifying", { id: job.model_id, percent });
  return (
    <div className="engines-local-progress">
      <p role="status">{sentence}</p>
      <ProgressBar label={t("engines:local.progressLabel", { id: job.model_id })} value={percent} valueText={`${percent} %`} />
      <p className="settings-help">{t("engines:local.bytes", { done: formatBytes(job.bytes_done), total: formatBytes(job.bytes_total) })}</p>
      <Button variant="secondary" size="sm" aria-label={t("engines:local.cancelLabel", { id: job.model_id })} disabled={cancelling} onClick={onCancel}>
        {cancelling ? t("engines:local.cancelling") : t("engines:local.cancel")}
      </Button>
    </div>
  );
}
