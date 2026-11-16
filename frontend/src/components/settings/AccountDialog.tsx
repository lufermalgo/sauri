import { useEffect, useState } from "react";
import { CircleAlert, CircleCheck, ExternalLink } from "lucide-react";
import type { EngineAccount, EngineProvider } from "@sauri/shared-types";
import { pollEngineAccount, startEngineAccount } from "../../api";
import { useT } from "../../i18n";
import { Button, Dialog, Icon } from "../ui";
import { describeEngineError } from "./ProviderDialog";

type Step =
  | { step: "starting" }
  | { step: "waiting"; account: EngineAccount }
  | { step: "done"; who: string }
  | { step: "failed"; message: string };

const clock = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", hour12: false });

interface AccountDialogProps {
  provider: EngineProvider;
  /** Called once the account is connected, so the card can say so. */
  onConnected: () => void;
  onClose: () => void;
}

/** Signs in with the ChatGPT account: shows the code to type, a button that opens the verification page in a new
 * tab, and asks the API once per interval until the account is connected, the code runs out or it is refused.
 * Closing the dialog stops asking; nothing is saved until OpenAI confirms. */
export function AccountDialog({ provider, onConnected, onClose }: AccountDialogProps) {
  const { t } = useT();
  const [step, setStep] = useState<Step>({ step: "starting" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const pause = (seconds: number) => new Promise<void>((resolve) => (timer = setTimeout(resolve, seconds * 1000)));

    async function run() {
      setStep({ step: "starting" });
      try {
        let account = await startEngineAccount(provider.id);
        while (alive) {
          if (account.state === "connected") {
            setStep({ step: "done", who: account.account ?? "" });
            onConnected();
            return;
          }
          if (account.state !== "pending" || !account.pending) {
            setStep({
              step: "failed",
              message: account.error ? t(`engines:account.errors.${account.error}`) : t("engines:account.dialog.startFailed"),
            });
            return;
          }
          setStep({ step: "waiting", account });
          await pause(account.pending.interval_s);
          if (!alive) return;
          account = await pollEngineAccount(provider.id);
        }
      } catch (error) {
        if (alive) setStep({ step: "failed", message: `${t("engines:account.dialog.startFailed")} ${describeEngineError(error)}` });
      }
    }

    void run();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
    // `onConnected` only refreshes the card; a new identity must not restart the sign-in.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider.id, attempt]);

  return (
    <Dialog title={t("engines:account.dialog.title")} closeLabel={t("engines:account.dialog.close")} onClose={onClose}>
      <div className="settings-form engines-form engines-account">
        {step.step === "starting" && <p role="status" className="settings-help">{t("engines:account.dialog.starting")}</p>}
        {step.step === "waiting" && step.account.pending && (
          <>
            <p className="settings-help">{t("engines:account.dialog.stepOpen")}</p>
            <a
              className="ui-button ui-button--primary ui-button--md engines-account-open"
              href={step.account.pending.verification_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Icon icon={ExternalLink} />
              {t("engines:account.dialog.openPage")}
            </a>
            <p className="settings-help">{t("engines:account.dialog.stepCode")}</p>
            <p className="engines-account-code" aria-label={step.account.pending.user_code}>
              {step.account.pending.user_code}
            </p>
            <p className="settings-help">{t("engines:account.dialog.expires", { time: clock.format(new Date(step.account.pending.expires_at)) })}</p>
            <p role="status" className="settings-help">
              {step.account.pending.slow_down ? t("engines:account.dialog.slowDown") : t("engines:account.dialog.waiting")}
            </p>
          </>
        )}
        {step.step === "done" && (
          <p role="status" className="engines-outcome engines-outcome--ok">
            <Icon icon={CircleCheck} />
            {t("engines:account.dialog.connected", { who: step.who })}
          </p>
        )}
        {step.step === "failed" && (
          <p role="alert" className="engines-outcome engines-outcome--fail">
            <Icon icon={CircleAlert} />
            {step.message}
          </p>
        )}
        <div className="ui-dialog-actions">
          {step.step === "failed" && (
            <Button variant="secondary" onClick={() => setAttempt((count) => count + 1)}>{t("engines:account.dialog.retry")}</Button>
          )}
          <Button variant={step.step === "done" ? "primary" : "secondary"} onClick={onClose}>
            {step.step === "done" ? t("engines:account.dialog.done") : t("engines:account.dialog.cancel")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
