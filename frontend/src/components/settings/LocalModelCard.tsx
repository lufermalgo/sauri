import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, Plus, Terminal } from "lucide-react";
import type { CustomInstallRequest, EngineProcess, LocalHardware, LocalJob, LocalModel, LocalModelList } from "@sauri/shared-types";
import { LOCAL_DEFAULT_MODEL } from "@sauri/shared-types";
import {
  adoptLocalModels,
  cancelLocalJob,
  getEngineStatus,
  getLocalHardware,
  getLocalJob,
  installCustomModel,
  installLocalModel,
  isLocalMode,
  listLocalModels,
  removeLocalModel,
  verifyLocalModel,
} from "../../api";
import { Button, Card, ConfirmDialog, Icon, Menu, MenuItem, Skeleton, StatusBadge } from "../ui";
import { AddModelDialog } from "./AddModelDialog";
import type { Outcome } from "./AddModelDialog";
import { formatBytes, resolvedDefault } from "./engineLabels";
import { EngineLine, ModelRow, SupportLine } from "./LocalModelRow";
import type { RowContext } from "./LocalModelRow";
import { describeLocalError, diskSize, displayName, errorCode, fileName, installedRows, splitEntries } from "./localModelState";
import "../../styles/engines.css";
import "../../styles/local-models.css";
import { t, translateIfKnown, useT } from "../../i18n";

/** Wait between two looks at a running install or check; the host answers each look at once. */
export const JOB_POLL_INTERVAL_MS = 1000;
/** Consecutive failed looks after which the card stops asking and tells the person. */
const MAX_POLL_FAILURES = 5;
/** Looks at the catalog while files are still being recognized; after that the card stops asking. */
const MAX_VERIFY_LOOKS = 300;

/** Which native engine runs each process (ports and ids of `host-engine`'s status). */
const ENGINE_OF: Record<EngineProcess, string> = { transcription: "asr", diarization: "diar", summary: "llm" };

/** Adoption outcomes that leave a file on disk that is not confirmed as the catalog's. */
const ATTENTION_OUTCOMES = new Set(["present_unverified", "changed", "unreadable"]);

type Load =
  | { status: "loading" }
  | { status: "error"; hostDown: boolean }
  | { status: "ready"; hardware: LocalHardware; list: LocalModelList; engineRunning: boolean | null };

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
  /** The external-services row; the first-run welcome page leaves it out (local models only). */
  external?: ExternalChoice;
  /** Wait between looks at a running job; tests shorten it. */
  pollIntervalMs?: number;
}

/** The choice key `onUse` hands back: the model `local:default` runs now (the preferred one when it is ready, else
 * the catalog default) is `local:default`, any other `local:<id>`. */
export function choiceKeyOf(model: LocalModel, models: readonly LocalModel[] = [model]): string {
  const resolved = resolvedDefault(models, model.process);
  return (resolved ? resolved.id === model.id : model.default) ? LOCAL_DEFAULT_MODEL : `local:${model.id}`;
}

/** "En este equipo" for one process: only what this computer has (the models on disk, with their state, «Usar este»,
 * check and remove), the supporting files in one line each, and «Agregar», which suggests at most two models for this
 * computer and, for transcription and summaries, a model of the person's own. A running job is followed by short,
 * bounded looks that stop when the card goes away; everything updates in place, without reloading. */
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
  const [adding, setAdding] = useState(false);
  /** The job that downloads a model of the person's own and its file: the result names the file, not the catalog. */
  const customJob = useRef<{ id: string; name: string } | null>(null);
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
      const custom = finished.id === customJob.current?.id ? customJob.current : null;
      const id = custom?.name ?? finished.model_id;
      if (finished.state === "cancelled") setOutcome({ kind: "success", text: t("engines:local.outcome.cancelled") });
      else if (finished.state === "failed") {
        const cause = (finished.error && translateIfKnown(`engines:local.jobErrors.${finished.error}`)) || t("engines:local.errors.generic");
        setOutcome({ kind: "error", text: t("engines:local.outcome.failed", { cause }) });
      } else if (finished.type === "adopt") {
        setOutcome({ kind: "success", text: finished.result === "adopted" ? t("engines:local.adoption.done") : t("engines:local.adoption.nothing") });
      } else if (finished.type === "install") {
        setOutcome({ kind: "success", text: t(custom ? "engines:local.outcome.installedCustom" : "engines:local.outcome.installed", { id }) });
        // The new model is now a row of the card: the dialog has done its job.
        setAdding(false);
      } else if (finished.result === "corrupt") setOutcome({ kind: "error", text: t("engines:local.outcome.corrupt", { id }) });
      else setOutcome({ kind: "success", text: t("engines:local.outcome.verified", { id }) });
      if (custom) customJob.current = null;
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

  /** Starts a job; a refusal is told in words and, when another job runs, the screen picks that one up. */
  async function begin(modelId: string, request: () => Promise<LocalJob>): Promise<LocalJob | null> {
    setOutcome(null);
    setBusyModel(modelId);
    try {
      const started = await request();
      setJob(started);
      return started;
    } catch (error) {
      setOutcome({ kind: "error", text: describeLocalError(error) });
      if (errorCode(error) === "job_active") fetchAll();
      return null;
    } finally {
      setBusyModel(null);
    }
  }

  async function installCustom(request: CustomInstallRequest): Promise<LocalJob | null> {
    const started = await begin(request.repo, () => installCustomModel(request));
    if (started) customJob.current = { id: started.id, name: fileName(request.file) };
    return started;
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
      setOutcome({ kind: "success", text: t("engines:local.outcome.removed", { id: displayName(model) }) });
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
  const entries = load.status === "ready" ? splitEntries(load.list.models, process) : null;
  const context: RowContext | null = load.status === "ready" ? {
    process,
    models: load.list.models.filter((model) => model.process === process),
    hardware: load.hardware,
    recommendation: load.list.recommendations[process],
    job,
    cancelling,
    busy: busyModel !== null,
    choosing,
    externalActive: selection.external,
    savedKey: selection.key,
    onUse: (model) => onUse(choiceKeyOf(model, load.list.models)),
    onInstall: (model) => void begin(model.id, () => installLocalModel(model.id)),
    onVerify: (model) => void begin(model.id, () => verifyLocalModel(model.id)),
    onRemove: setPendingRemoval,
    onCancel: cancel,
  } : null;
  const rows = context && entries ? installedRows(entries.options, job, selection.external, selection.key) : [];
  const titleId = `engines-local-${process}`;

  return (
    <Card className="engines-local" aria-labelledby={titleId}>
      <div className="engines-local-head">
        <h3 id={titleId} className="engines-card-title">{t("engines:local.title")}</h3>
        {load.status === "ready" && (
          <div className="local-card-actions">
            {rows.length > 0 && (
              <Button variant="secondary" size="sm" aria-label={t(`engines:local.add.label.${process}`)} onClick={() => setAdding(true)}>
                <Icon icon={Plus} />
                {t("engines:local.add.open")}
              </Button>
            )}
            <Menu label={t("engines:local.cardMenu")} className="engines-local-menu">
              <MenuItem onSelect={() => void scan()} disabled={jobRunning} hint={jobRunning ? t("engines:local.busy") : undefined}>
                {t("engines:local.scan")}
              </MenuItem>
            </Menu>
          </div>
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

      {context && entries && (
        <>
          {load.status === "ready" && load.engineRunning === false && <EngineMissing process={process} />}
          <div role="status" className="engines-local-recognizing">
            {recognizing || job?.type === "adopt" ? t("engines:local.adoption.recognizing") : null}
          </div>
          {adoptionAttention && <p className="settings-help">{t("engines:local.adoption.attention")}</p>}

          {rows.length > 0 ? (
            <section className="engines-local-section" aria-label={t("engines:local.modelsTitle")}>
              {jobRunning && job.type !== "adopt" && <p className="settings-help">{t("engines:local.busy")}</p>}
              <ul className="engines-local-models" aria-label={t("engines:local.modelsTitle")}>
                {rows.map((model) => <ModelRow key={model.id} {...context} model={model} />)}
              </ul>
            </section>
          ) : (
            <section className="local-empty" aria-labelledby={`${titleId}-empty`}>
              <h4 id={`${titleId}-empty`} className="local-empty-title">{t(`engines:local.empty.title.${process}`)}</h4>
              <p className="settings-help">{t("engines:local.empty.body")}</p>
              <div>
                <Button variant="primary" onClick={() => setAdding(true)}>
                  <Icon icon={Plus} />
                  {t("engines:local.empty.action")}
                </Button>
              </div>
            </section>
          )}
          {entries.supporting.map((model) => <SupportLine key={model.id} {...context} model={model} />)}
          {entries.engines.map((model) => <EngineLine key={model.id} process={process} model={model} />)}
          {external && <ExternalGroup external={external} />}
        </>
      )}

      {/* While «Agregar» is open it shows the result itself: the card is behind the dialog. */}
      <div role="status" className="settings-notice">{!adding && outcome?.kind === "success" ? outcome.text : null}</div>
      {!adding && outcome?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{outcome.text}</p>}

      {adding && context && entries && (
        <AddModelDialog
          process={process}
          options={entries.options}
          hardware={context.hardware}
          recommendation={context.recommendation}
          job={job}
          cancelling={cancelling}
          busy={context.busy}
          outcome={outcome}
          onInstall={context.onInstall}
          onInstallCustom={installCustom}
          onCancel={cancel}
          onClose={() => setAdding(false)}
        />
      )}

      {pendingRemoval && (
        <ConfirmDialog
          title={t("engines:local.removeTitle")}
          body={<p>{t("engines:local.removeBody", { id: displayName(pendingRemoval), size: formatBytes(diskSize(pendingRemoval) ?? 0) })}</p>}
          confirmLabel={t("engines:local.removeConfirm")}
          cancelLabel={t("engines:local.removeCancel")}
          onConfirm={() => confirmRemoval(pendingRemoval)}
          onCancel={() => setPendingRemoval(null)}
        />
      )}
    </Card>
  );
}

/** The engine does not answer. In the desktop app the engines come with Sauri and start on their own, so the person
 * is told what they can do (reopen Sauri, then look at the logs); elsewhere it was never installed or is stopped, and
 * the portal names the tools this engine needs along with the command. */
function EngineMissing({ process, host = false }: { process: EngineProcess; host?: boolean }) {
  const { t } = useT();
  const engine = t(`engines:local.engineNames.${process}`);
  if (isLocalMode()) {
    return (
      <section className="engines-missing" aria-label={t("engines:local.engineMissing.desktopTitle")}>
        <h4 className="engines-missing-title">
          <Icon icon={CircleAlert} />
          {t("engines:local.engineMissing.desktopTitle")}
        </h4>
        <p>{host ? t("engines:local.engineMissing.desktopHostBody") : t("engines:local.engineMissing.desktopBody", { engine })}</p>
        <p className="settings-help">{t("engines:local.engineMissing.desktopWait")}</p>
      </section>
    );
  }
  return (
    <section className="engines-missing" aria-label={t("engines:local.engineMissing.title")}>
      <h4 className="engines-missing-title">
        <Icon icon={CircleAlert} />
        {t("engines:local.engineMissing.title")}
      </h4>
      <p>{host ? t("engines:local.engineMissing.hostBody") : t("engines:local.engineMissing.body", { engine })}</p>
      <p>{t("engines:local.engineMissing.installIntro")}</p>
      <p><code className="engines-command"><Icon icon={Terminal} size={14} />{t("engines:local.engineMissing.installCommand")}</code></p>
      <p className="settings-help">{t("engines:local.engineMissing.tools", { list: t(`engines:local.engineTools.${process}`) })}</p>
      <p className="settings-help">{t("engines:local.engineMissing.startIntro")} <code className="engines-command">{t("engines:local.engineMissing.startCommand")}</code></p>
    </section>
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
