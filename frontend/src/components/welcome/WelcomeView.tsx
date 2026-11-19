import { useEffect, useState } from "react";
import { CircleCheck, ExternalLink } from "lucide-react";
import type { EngineProcess, LocalJob, LocalModelList } from "@sauri/shared-types";
import {
  EnginesApiError,
  getLocalJob,
  getLocalStatus,
  installLocalModel,
  listEngineProcesses,
  listLocalModels,
  putEngineProcess,
  verifyLocalModel,
} from "../../api";
import { desktopBridge } from "../../desktop-bridge";
import { JOB_POLL_INTERVAL_MS } from "../settings/LocalModelCard";
import { formatBytes } from "../settings/engineLabels";
import { BrandLogo, Button, Icon, ProgressBar } from "../ui";
import { actionFor, pendingItems, recommendedChoices } from "./setupPlan";
import "../../styles/settings.css";
import "../../styles/welcome.css";
import { useT } from "../../i18n";

/**
 * The extension's Chrome Web Store listing. The store assigns the id when the extension is published (U10); until
 * then the build sets it with `VITE_SAURI_EXTENSION_STORE_URL`, and the store's home page stands in.
 */
export const EXTENSION_STORE_URL: string =
  import.meta.env.VITE_SAURI_EXTENSION_STORE_URL || "https://chromewebstore.google.com/";

/** How often the extension step asks whether the extension has paired. */
export const PAIRING_POLL_MS = 3000;

const PROCESSES: readonly EngineProcess[] = ["transcription", "diarization", "summary"];

type Step = "models" | "extension";

interface WelcomeViewProps {
  /** Called once setup is saved as done (or right away in a normal browser). */
  onFinished: () => void;
  /** Wait between looks at a running install and at the pairing; tests shorten it. */
  pollIntervalMs?: number;
}

/** First-run phase B: the recommended local models, installed on their own, then the Chrome extension. Ends by marking setup done. */
export function WelcomeView({ onFinished, pollIntervalMs }: WelcomeViewProps) {
  const { t } = useT();
  const [step, setStep] = useState<Step>("models");
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState(false);

  async function finish() {
    setFinishing(true);
    setFinishError(false);
    try {
      await desktopBridge()?.markSetupDone();
      onFinished();
    } catch {
      setFinishError(true);
    } finally {
      setFinishing(false);
    }
  }

  return (
    <main className="welcome" aria-labelledby="welcome-title">
      <div className="welcome-frame">
        <header className="welcome-header">
          <BrandLogo />
          <p className="welcome-step">{t("welcome:step", { n: step === "models" ? 1 : 2 })}</p>
          <h1 id="welcome-title" className="welcome-title">{t("welcome:title")}</h1>
          <p className="settings-help">{t("welcome:intro")}</p>
        </header>
        {step === "models" ? (
          <ModelsStep pollIntervalMs={pollIntervalMs} onContinue={() => setStep("extension")} />
        ) : (
          <ExtensionStep
            pollIntervalMs={pollIntervalMs ?? PAIRING_POLL_MS}
            finishing={finishing}
            finishError={finishError}
            onBack={() => setStep("models")}
            onFinish={() => void finish()}
          />
        )}
      </div>
    </main>
  );
}

type Failure = "offline" | "disk" | "unavailable" | "host" | "generic";

type Phase =
  | { kind: "preparing" }
  | { kind: "waiting" }
  | { kind: "working"; action: "install" | "verify"; process: EngineProcess; n: number; count: number; done: number; total: number }
  | { kind: "saving" }
  | { kind: "ready"; noLocal: EngineProcess[] }
  | { kind: "failed"; failure: Failure; needed?: number; free?: number };

/** Consecutive failed looks at a running job after which the install is reported as lost. */
const MAX_POLL_FAILURES = 5;
/** Attempts on one planned file: a job another screen started first, or a check that leads to a download. */
const MAX_ATTEMPTS = 3;
const NETWORK_ERRORS = new Set(["download_failed", "connection_lost"]);

class Stopped extends Error {}

class InstallFailed extends Error {
  constructor(readonly code: string | null, readonly figures: Readonly<Record<string, unknown>> = {}) {
    super(code ?? "failed");
  }
}

function failureOf(error: unknown): Phase {
  const code = error instanceof InstallFailed || error instanceof EnginesApiError ? error.code : null;
  const figures = error instanceof InstallFailed || error instanceof EnginesApiError ? error.figures : {};
  if (code === "insufficient_disk" && typeof figures.needed_bytes === "number" && typeof figures.free_bytes === "number") {
    return { kind: "failed", failure: "disk", needed: figures.needed_bytes, free: figures.free_bytes };
  }
  if (code && NETWORK_ERRORS.has(code)) return { kind: "failed", failure: "offline" };
  if (code === "component_not_published") return { kind: "failed", failure: "unavailable" };
  if (code === "host_unavailable" || !(error instanceof InstallFailed || error instanceof EnginesApiError)) {
    return { kind: "failed", failure: "host" };
  }
  return { kind: "failed", failure: "generic" };
}

/**
 * First-run models, with no choice to make: installs host-engine's setup plan for this Mac (the recommended model of
 * each process and what it needs to run) one file at a time, then saves the choice each process needs to run it.
 * Every download goes through the same host routes as Settings (pinned hashes, allowed hosts only).
 */
function ModelsStep({ onContinue, pollIntervalMs = JOB_POLL_INTERVAL_MS }: { onContinue: () => void; pollIntervalMs?: number }) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>({ kind: "preparing" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    const check = <T,>(value: T): T => {
      if (stopped) throw new Stopped();
      return value;
    };
    const pause = () => new Promise((resolve) => setTimeout(resolve, pollIntervalMs));

    /** Follows a job until it ends; `onLook` sees each running state. */
    async function follow(job: LocalJob, onLook: (job: LocalJob) => void): Promise<LocalJob> {
      let current = job;
      let failures = 0;
      while (current.state === "running") {
        onLook(current);
        await pause();
        check(null);
        try {
          current = check(await getLocalJob(current.id));
          failures = 0;
        } catch (error) {
          if (error instanceof Stopped) throw error;
          failures += 1;
          if (failures >= MAX_POLL_FAILURES) throw new InstallFailed(null);
        }
      }
      return current;
    }

    /** Waits for a job this screen did not start (the startup check of installed files, or Settings). */
    async function settle(list: LocalModelList): Promise<LocalModelList> {
      if (!list.active_job) return list;
      setPhase({ kind: "waiting" });
      await follow(check(await getLocalJob(list.active_job)), () => undefined);
      return check(await listLocalModels());
    }

    async function run() {
      setPhase({ kind: "preparing" });
      let list = await settle(check(await listLocalModels()));
      const items = pendingItems(list);
      const total = items.reduce((sum, item) => sum + item.bytes, 0);
      let done = 0;
      for (const [index, item] of items.entries()) {
        for (let tries = 0; tries < MAX_ATTEMPTS; tries += 1) {
          const model = list.models.find((entry) => entry.id === item.id);
          const action = model ? actionFor(model) : "done";
          if (action === "done") break;
          const show = (job: LocalJob | null) => {
            const share = job && job.bytes_total > 0 ? Math.min(1, job.bytes_done / job.bytes_total) * item.bytes : 0;
            setPhase({ kind: "working", action, process: item.process, n: index + 1, count: items.length, done: done + share, total });
          };
          show(null);
          let job: LocalJob;
          try {
            job = check(await (action === "install" ? installLocalModel(item.id) : verifyLocalModel(item.id)));
          } catch (error) {
            if (!(error instanceof EnginesApiError) || error.code !== "job_active") throw error;
            list = await settle(check(await listLocalModels()));
            continue;
          }
          const finished = await follow(job, show);
          if (finished.state === "failed") throw new InstallFailed(finished.error);
          if (finished.state === "cancelled") throw new InstallFailed(null);
          list = check(await listLocalModels());
        }
        const after = list.models.find((entry) => entry.id === item.id);
        if (!after || actionFor(after) !== "done") throw new InstallFailed(null);
        done += item.bytes;
      }
      setPhase({ kind: "saving" });
      const processes = check(await listEngineProcesses());
      for (const state of recommendedChoices(list, processes)) {
        check(await putEngineProcess(state.capability, { provider_id: null, model: state.model, local_fallback: state.local_fallback }));
      }
      const noLocal = PROCESSES.filter((process) => list.recommendations[process] && !list.recommendations[process]?.model_id);
      setPhase({ kind: "ready", noLocal });
    }

    run().catch((error: unknown) => {
      if (!(error instanceof Stopped)) setPhase(failureOf(error));
    });
    return () => {
      stopped = true;
    };
  }, [attempt, pollIntervalMs]);

  const busy = phase.kind !== "ready" && phase.kind !== "failed";
  return (
    <section className="welcome-section" aria-labelledby="welcome-models-title" aria-busy={busy}>
      <h2 id="welcome-models-title" className="welcome-section-title">{t("welcome:models.title")}</h2>
      <p className="settings-help">{t("welcome:models.intro")}</p>
      <div role="status" className="welcome-install">
        {phase.kind === "preparing" && <p>{t("welcome:models.preparing")}</p>}
        {phase.kind === "waiting" && <p>{t("welcome:models.waiting")}</p>}
        {phase.kind === "saving" && <p>{t("welcome:models.saving")}</p>}
        {phase.kind === "working" && (
          <p>
            {t(phase.action === "install" ? "welcome:models.installing" : "welcome:models.checking", {
              what: t(`welcome:models.items.${phase.process}`),
              n: phase.n,
              count: phase.count,
            })}
          </p>
        )}
        {phase.kind === "ready" && (
          <p className="welcome-install-ready">
            <Icon icon={CircleCheck} />
            {t("welcome:models.ready")}
          </p>
        )}
      </div>
      {busy && (
        <ProgressBar
          label={t("welcome:models.progressLabel")}
          value={phase.kind === "working" ? Math.floor((phase.done / Math.max(phase.total, 1)) * 100) : undefined}
          valueText={phase.kind === "working" ? `${Math.floor((phase.done / Math.max(phase.total, 1)) * 100)} %` : undefined}
        />
      )}
      {phase.kind === "working" && (
        <p className="settings-help">
          {t("welcome:models.bytes", { done: formatBytes(phase.done), total: formatBytes(phase.total) })}
          {" · "}
          {t("welcome:models.estimate", { size: formatBytes(phase.total) })}
        </p>
      )}
      {phase.kind === "ready" && phase.noLocal.map((process) => (
        <p key={process} className="settings-help">
          {t("welcome:models.noLocal", { process: t(`welcome:models.processes.${process}.title`) })}
        </p>
      ))}
      {phase.kind === "failed" && (
        <>
          <p role="alert" className="ui-field-error">
            {phase.failure === "disk"
              ? t("welcome:models.failed.disk", { needed: formatBytes(phase.needed ?? 0), free: formatBytes(phase.free ?? 0) })
              : t(`welcome:models.failed.${phase.failure}`)}
          </p>
          <p className="settings-help">{t("welcome:models.skipHelp")}</p>
        </>
      )}
      {phase.kind === "ready" && <p className="settings-help">{t("welcome:models.later")}</p>}
      <div className="welcome-actions">
        {phase.kind === "failed" && (
          <>
            <Button variant="ghost" onClick={onContinue}>{t("welcome:models.skip")}</Button>
            <Button variant="primary" onClick={() => setAttempt((value) => value + 1)}>{t("welcome:models.retry")}</Button>
          </>
        )}
        {phase.kind !== "failed" && (
          <Button variant="primary" disabled={phase.kind !== "ready"} onClick={onContinue}>{t("welcome:models.continue")}</Button>
        )}
      </div>
    </section>
  );
}

type Pairing = "checking" | "paired" | "waiting" | "error";

interface ExtensionStepProps {
  pollIntervalMs: number;
  finishing: boolean;
  finishError: boolean;
  onBack: () => void;
  onFinish: () => void;
}

function ExtensionStep({ pollIntervalMs, finishing, finishError, onBack, onFinish }: ExtensionStepProps) {
  const { t } = useT();
  const [pairing, setPairing] = useState<Pairing>("checking");

  // Asks until the extension pairs; the first answer comes at once.
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const look = async () => {
      try {
        const status = await getLocalStatus();
        if (stopped) return;
        setPairing(status.extension_paired ? "paired" : "waiting");
        if (status.extension_paired) return;
      } catch {
        if (stopped) return;
        setPairing("error");
      }
      timer = setTimeout(look, pollIntervalMs);
    };
    void look();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [pollIntervalMs]);

  return (
    <section className="welcome-section" aria-labelledby="welcome-extension-title">
      <h2 id="welcome-extension-title" className="welcome-section-title">{t("welcome:extension.title")}</h2>
      <p className="settings-help">{t("welcome:extension.intro")}</p>
      <p>
        <a className="ui-button ui-button--secondary ui-button--md welcome-store-link" href={EXTENSION_STORE_URL} target="_blank" rel="noopener noreferrer">
          {t("welcome:extension.install")}
          <Icon icon={ExternalLink} size={14} />
        </a>
      </p>
      <p className="settings-help">{t("welcome:extension.how")}</p>
      <div role="status" className={`welcome-pairing welcome-pairing--${pairing}`}>
        {pairing === "paired" && (
          <>
            <Icon icon={CircleCheck} />
            {t("welcome:extension.paired")}
          </>
        )}
        {pairing === "waiting" && t("welcome:extension.waiting")}
        {pairing === "error" && t("welcome:extension.statusError")}
      </div>
      {pairing !== "paired" && <p className="settings-help">{t("welcome:extension.later")}</p>}
      {finishError && <p role="alert" className="ui-field-error">{t("welcome:finishError")}</p>}
      <div className="welcome-actions">
        <Button variant="ghost" onClick={onBack}>{t("welcome:back")}</Button>
        <Button variant="primary" disabled={finishing} onClick={onFinish}>{t("welcome:finish")}</Button>
      </div>
    </section>
  );
}
