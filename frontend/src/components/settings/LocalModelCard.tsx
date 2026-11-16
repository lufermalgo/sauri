import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, Terminal } from "lucide-react";
import type {
  EngineProcess,
  LocalHardware,
  LocalJob,
  LocalModel,
  LocalModelList,
  LocalModelState,
  LocalRecommendation,
} from "@sauri/shared-types";
import {
  EnginesApiError,
  cancelLocalJob,
  getEngineStatus,
  getLocalHardware,
  getLocalJob,
  installLocalModel,
  listLocalModels,
  removeLocalModel,
  verifyLocalModel,
} from "../../api";
import { copy } from "../../copy/es";
import { Button, Card, ConfirmDialog, Icon, ProgressBar, Skeleton, StatusBadge } from "../ui";
import { formatBytes, formatMemory, processList } from "./engineLabels";
import "../../styles/engines.css";

const text = copy.engines.local;

/** Wait between two looks at a running install or check; the host answers each look at once. */
export const JOB_POLL_INTERVAL_MS = 1000;
/** Consecutive failed looks after which the card stops asking and tells the person. */
const MAX_POLL_FAILURES = 5;
/** Same factor as the host's disk check (`DISK_HEADROOM_PERCENT`): the file plus 20 % of room. */
const DISK_HEADROOM = 1.2;

/** Which native engine runs each process (ports and ids of `host-engine`'s status). */
const ENGINE_OF: Record<EngineProcess, string> = { transcription: "asr", diarization: "diar", summary: "llm" };

const STATE_TONE: Record<LocalModelState, "neutral" | "progress" | "success" | "error"> = {
  not_installed: "neutral",
  installing: "progress",
  installed: "success",
  unverified: "progress",
  corrupt: "error",
  managed: "neutral",
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
    if (needed !== null && free !== null) return text.insufficientDisk(formatBytes(needed), formatBytes(free));
  }
  if (code === "model_in_use") {
    const processes = error instanceof EnginesApiError ? error.figures.processes : null;
    if (Array.isArray(processes)) return text.modelInUse(processList(processes as EngineProcess[]));
  }
  return (code && text.errors[code]) || text.errors.generic;
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
      return text.reasons.fits(memory, minimum);
    case "reduced": {
      const limited = params.limited_by === "metal" ? text.limits.metal : text.limits.memory;
      return text.reasons.reduced(memory, String(params.better_id ?? ""), limited);
    }
    case "no_local_model":
      return params.needs === "metal" ? text.reasons.noModelMetal : text.reasons.noModelMemory(memory, minimum);
    default:
      return text.reasons.generic;
  }
}

interface LocalModelCardProps {
  process: EngineProcess;
  /** Called with the catalog every time it is read, so the engine selector can offer installed models. */
  onModelsChange?: (models: LocalModel[]) => void;
  /** Wait between looks at a running job; tests shorten it. */
  pollIntervalMs?: number;
}

/** The computer in plain words, the model recommended for this process and the local models of this
 * process with install (with progress and cancel), verify and remove. A running job is followed by
 * short, bounded looks that stop when the card goes away. */
export function LocalModelCard({ process, onModelsChange, pollIntervalMs = JOB_POLL_INTERVAL_MS }: LocalModelCardProps) {
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

  const finishJob = useCallback(
    (finished: LocalJob) => {
      setJob(null);
      setCancelling(false);
      const id = finished.model_id;
      if (finished.state === "cancelled") setOutcome({ kind: "success", text: text.outcome.cancelled });
      else if (finished.state === "failed") {
        const cause = (finished.error && text.jobErrors[finished.error]) || text.errors.generic;
        setOutcome({ kind: "error", text: text.outcome.failed(cause) });
      } else if (finished.type === "install") setOutcome({ kind: "success", text: text.outcome.installed(id) });
      else if (finished.result === "corrupt") setOutcome({ kind: "error", text: text.outcome.corrupt(id) });
      else setOutcome({ kind: "success", text: text.outcome.verified(id) });
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
          setOutcome({ kind: "error", text: text.outcome.lost });
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
      setOutcome({ kind: "success", text: text.outcome.removed(model.id) });
    } catch (error) {
      setOutcome({ kind: "error", text: describeLocalError(error) });
    } finally {
      setBusyModel(null);
      void reloadModels();
    }
  }

  return (
    <Card className="engines-local" aria-labelledby={`engines-local-${process}`}>
      <h3 id={`engines-local-${process}`} className="engines-card-title">{text.title}</h3>
      <p className="settings-help">{text.help}</p>

      {load.status === "loading" && (
        <div role="status" className="settings-loading">
          <p className="settings-help">{text.loading}</p>
          <Skeleton width="100%" height="4rem" radius="md" />
        </div>
      )}
      {load.status === "error" && (
        <div className="settings-load-error">
          {load.hostDown ? <EngineMissing process={process} host /> : (
            <p role="alert" className="ui-field-error">{text.loadError}</p>
          )}
          <Button variant="secondary" onClick={fetchAll}>{text.retry}</Button>
        </div>
      )}

      {load.status === "ready" && (
        <>
          <HardwareSummary hardware={load.hardware} />
          {load.engineRunning === false && <EngineMissing process={process} />}
          <Recommendation recommendation={load.list.recommendations[process]} hardware={load.hardware} />
          <ModelList
            process={process}
            models={load.list.models.filter((model) => model.process === process)}
            job={job}
            cancelling={cancelling}
            busyModel={busyModel}
            onInstall={(model) => start(model, "install")}
            onVerify={(model) => start(model, "verify")}
            onRemove={setPendingRemoval}
            onCancel={cancel}
          />
        </>
      )}

      <div role="status" className="settings-notice">{outcome?.kind === "success" ? outcome.text : null}</div>
      {outcome?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{outcome.text}</p>}

      {pendingRemoval && (
        <ConfirmDialog
          title={text.removeTitle}
          body={<p>{text.removeBody(pendingRemoval.id, formatBytes(pendingRemoval.installed_size ?? pendingRemoval.size ?? 0))}</p>}
          confirmLabel={text.removeConfirm}
          cancelLabel={text.removeCancel}
          onConfirm={() => confirmRemoval(pendingRemoval)}
          onCancel={() => setPendingRemoval(null)}
        />
      )}
    </Card>
  );
}

function HardwareSummary({ hardware }: { hardware: LocalHardware }) {
  return (
    <section className="engines-local-section" aria-label={text.hardwareTitle}>
      <h4 className="settings-group-title">{text.hardwareTitle}</h4>
      <p>
        {text.hardware(
          text.chip(hardware.arch, hardware.system),
          formatMemory(hardware.memory_gib),
          hardware.cores,
          formatBytes(hardware.disk_free_bytes),
        )}
      </p>
      <p className="settings-help">{hardware.metal ? text.metalYes : text.metalNo}</p>
    </section>
  );
}

function Recommendation({ recommendation, hardware }: { recommendation: LocalRecommendation | undefined; hardware: LocalHardware }) {
  return (
    <section className="engines-local-section" aria-label={text.recommendationTitle}>
      <h4 className="settings-group-title">{text.recommendationTitle}</h4>
      {!recommendation && <p className="settings-help">{text.noRecommendation}</p>}
      {recommendation && (
        <>
          <p className="engines-local-recommended">
            {recommendation.model_id ? <strong>{recommendation.model_id}</strong> : <span>{text.noRecommendation}</span>}
            {recommendation.status && (
              <StatusBadge tone={recommendation.status === "measured" ? "success" : "progress"}>
                {text.marks[recommendation.status]}
              </StatusBadge>
            )}
          </p>
          {recommendation.status && <p className="settings-help">{text.markHelp[recommendation.status]}</p>}
          <p>{reasonText(recommendation, hardware)}</p>
          {recommendation.warnings.length > 0 && (
            <ul className="engines-local-warnings">
              {recommendation.warnings.map((warning) => (
                <li key={warning}>{text.warnings[warning as keyof typeof text.warnings] ?? warning}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

/** The engine does not answer: either it was never installed or it is stopped. The portal cannot tell
 * which tools are missing, so it names the ones this engine needs along with the command. */
function EngineMissing({ process, host = false }: { process: EngineProcess; host?: boolean }) {
  const missing = text.engineMissing;
  return (
    <section className="engines-missing" aria-label={missing.title}>
      <h4 className="engines-missing-title">
        <Icon icon={CircleAlert} />
        {missing.title}
      </h4>
      <p>{host ? missing.hostBody : missing.body(text.engineNames[process])}</p>
      <p>{missing.installIntro}</p>
      <p><code className="engines-command"><Icon icon={Terminal} size={14} />{missing.installCommand}</code></p>
      <p className="settings-help">{missing.tools(text.engineTools[process])}</p>
      <p className="settings-help">{missing.startIntro} <code className="engines-command">{missing.startCommand}</code></p>
    </section>
  );
}

interface ModelListProps {
  process: EngineProcess;
  models: LocalModel[];
  job: LocalJob | null;
  cancelling: boolean;
  busyModel: string | null;
  onInstall: (model: LocalModel) => void;
  onVerify: (model: LocalModel) => void;
  onRemove: (model: LocalModel) => void;
  onCancel: () => void;
}

function ModelList({ process, models, job, cancelling, busyModel, onInstall, onVerify, onRemove, onCancel }: ModelListProps) {
  const jobRunning = job?.state === "running";
  return (
    <section className="engines-local-section" aria-label={text.modelsTitle}>
      <h4 className="settings-group-title">{text.modelsTitle}</h4>
      {models.length === 0 && <p className="settings-help">{text.noModels}</p>}
      {jobRunning && <p className="settings-help">{text.busy}</p>}
      <ul className="engines-local-models">
        {models.map((model) => {
          const running = jobRunning && job.model_id === model.id ? job : null;
          const state: LocalModelState = running?.type === "install" ? "installing" : model.state;
          const blocked = jobRunning || busyModel !== null;
          const inUse = model.in_use_by.length > 0;
          const titleId = `engines-model-${process}-${model.id}`;
          return (
            <li key={model.id} className="engines-local-model" aria-labelledby={titleId}>
              <div className="engines-card-head">
                <span id={titleId} className="engines-local-model-name">{model.id}</span>
                <StatusBadge tone={STATE_TONE[state]}>{text.states[state]}</StatusBadge>
                <StatusBadge tone={model.status === "measured" ? "success" : "progress"}>{text.marks[model.status]}</StatusBadge>
                {model.kind === "auxiliary" && <StatusBadge tone="neutral">{text.auxiliary}</StatusBadge>}
                {model.recommended && <StatusBadge tone="success">{text.recommended}</StatusBadge>}
              </div>
              <p className="settings-help">
                {text.engineMeta(model.engine)}
                {model.size !== null && ` · ${text.size(formatBytes(model.size))}`}
                {model.installed_size !== null && ` · ${text.installedSize(formatBytes(model.installed_size))}`}
              </p>
              {inUse && <p className="settings-help">{text.inUse(processList(model.in_use_by))}</p>}

              {running && <JobProgress job={running} cancelling={cancelling} onCancel={onCancel} />}

              {!running && model.state === "managed" && (
                <p className="settings-help">{text.managedHow(model.managed_by ? `bash ${model.managed_by}` : copy.engines.local.engineMissing.installCommand)}</p>
              )}
              {!running && model.state !== "managed" && (
                <div className="engines-local-actions">
                  {model.state === "not_installed" && (
                    <>
                      <Button variant="primary" size="sm" aria-label={text.installLabel(model.id)} disabled={blocked} onClick={() => onInstall(model)}>
                        {text.install}
                      </Button>
                      {model.size !== null && (
                        <span className="settings-help">{text.spaceNeeded(formatBytes(Math.ceil(model.size * DISK_HEADROOM)))}</span>
                      )}
                    </>
                  )}
                  {(model.state === "installed" || model.state === "unverified" || model.state === "corrupt") && (
                    <>
                      <Button variant="secondary" size="sm" aria-label={text.verifyLabel(model.id)} disabled={blocked} onClick={() => onVerify(model)}>
                        {text.verify}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={text.removeLabel(model.id)}
                        aria-describedby={inUse ? `${titleId}-blocked` : undefined}
                        disabled={blocked || inUse}
                        onClick={() => onRemove(model)}
                      >
                        {text.remove}
                      </Button>
                    </>
                  )}
                </div>
              )}
              {inUse && model.state !== "not_installed" && model.state !== "managed" && (
                <p id={`${titleId}-blocked`} className="settings-help">{text.removeBlocked(processList(model.in_use_by))}</p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function JobProgress({ job, cancelling, onCancel }: { job: LocalJob; cancelling: boolean; onCancel: () => void }) {
  const percent = percentOf(job);
  const sentence = job.type === "install" ? text.installing(job.model_id, percent) : text.verifying(job.model_id, percent);
  return (
    <div className="engines-local-progress">
      <p role="status">{sentence}</p>
      <ProgressBar label={text.progressLabel(job.model_id)} value={percent} valueText={`${percent} %`} />
      <p className="settings-help">{text.bytes(formatBytes(job.bytes_done), formatBytes(job.bytes_total))}</p>
      <Button variant="secondary" size="sm" aria-label={text.cancelLabel(job.model_id)} disabled={cancelling} onClick={onCancel}>
        {cancelling ? text.cancelling : text.cancel}
      </Button>
    </div>
  );
}
