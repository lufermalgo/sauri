import { useCallback, useEffect, useState } from "react";
import { CircleCheck, ExternalLink } from "lucide-react";
import type { EngineProcess, EngineProcessState } from "@sauri/shared-types";
import { getLocalStatus, listEngineProcesses, putEngineProcess } from "../../api";
import { desktopBridge } from "../../desktop-bridge";
import { LocalModelCard } from "../settings/LocalModelCard";
import { BrandLogo, Button, Icon, Skeleton } from "../ui";
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

/** First-run phase B: the recommended local models, then the Chrome extension. Ends by marking setup done. */
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

type ProcessLoad = { status: "loading" } | { status: "error" } | { status: "ready"; processes: EngineProcessState[] };

function ModelsStep({ onContinue, pollIntervalMs }: { onContinue: () => void; pollIntervalMs?: number }) {
  const { t } = useT();
  const [load, setLoad] = useState<ProcessLoad>({ status: "loading" });
  const [saving, setSaving] = useState<EngineProcess | null>(null);
  const [saveError, setSaveError] = useState(false);

  const read = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    listEngineProcesses().then(
      (processes) => current && setLoad({ status: "ready", processes }),
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, []);
  useEffect(() => read(), [read]);

  async function use(state: EngineProcessState, model: string) {
    setSaving(state.capability);
    setSaveError(false);
    try {
      const next = await putEngineProcess(state.capability, { provider_id: null, model, local_fallback: state.local_fallback });
      setLoad((previous) =>
        previous.status === "ready"
          ? { ...previous, processes: previous.processes.map((entry) => (entry.capability === next.capability ? next : entry)) }
          : previous);
    } catch {
      setSaveError(true);
    } finally {
      setSaving(null);
    }
  }

  return (
    <section className="welcome-section" aria-labelledby="welcome-models-title">
      <h2 id="welcome-models-title" className="welcome-section-title">{t("welcome:models.title")}</h2>
      <p className="settings-help">{t("welcome:models.intro")}</p>
      {load.status === "loading" && (
        <div role="status" className="settings-loading">
          <p className="settings-help">{t("welcome:models.loading")}</p>
          <Skeleton width="100%" height="4rem" radius="md" />
        </div>
      )}
      {load.status === "error" && (
        <div className="settings-load-error">
          <p role="alert" className="ui-field-error">{t("welcome:models.loadError")}</p>
          <Button variant="secondary" onClick={read}>{t("welcome:models.retry")}</Button>
        </div>
      )}
      {load.status === "ready" &&
        PROCESSES.map((process) => {
          const state = load.processes.find((entry) => entry.capability === process);
          if (!state) return null;
          return (
            <section key={process} className="welcome-process" aria-labelledby={`welcome-process-${process}`}>
              <h3 id={`welcome-process-${process}`} className="welcome-process-title">{t(`welcome:models.processes.${process}.title`)}</h3>
              <p className="settings-help">{t(`welcome:models.processes.${process}.help`)}</p>
              <LocalModelCard
                process={process}
                selection={{ external: state.provider_id !== null, key: state.model }}
                onUse={(key) => void use(state, key)}
                choosing={saving === process}
                pollIntervalMs={pollIntervalMs}
              />
            </section>
          );
        })}
      {saveError && <p role="alert" className="ui-field-error">{t("welcome:models.saveError")}</p>}
      <p className="settings-help">{t("welcome:models.later")}</p>
      <div className="welcome-actions">
        <Button variant="primary" onClick={onContinue}>{t("welcome:models.continue")}</Button>
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
