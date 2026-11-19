import { useEffect, useState } from "react";
import { ArrowDown, LoaderCircle } from "lucide-react";
import { desktopBridge, type ServicesStatus, type UpdateStatus } from "../desktop-bridge";
import { useT } from "../i18n";
import { applyError } from "./settings/UpdateSettings";
import { Icon, StatusBadge } from "./ui";
import { usePushed } from "./usePushed";

/**
 * The desktop app's notices: the verified update waiting for a restart («↓ Sauri 0.1.4 ·
 * Reiniciar», the click is the confirmation), the engines still starting, and a service that did not start. In a
 * normal browser there is no bridge and nothing is shown. On a Mac they sit in the window's top bar, beside the
 * traffic lights (PortalShell); otherwise in a slim bar on top of the content.
 */
export function DesktopNotices() {
  const { t } = useT();
  const [bridge] = useState(desktopBridge);
  const updates = bridge?.updates;
  const [update, setUpdate] = usePushed<UpdateStatus>(updates?.status, updates?.onChange);
  const [services] = usePushed<ServicesStatus>(bridge?.getServicesStatus, bridge?.onServicesStatus);
  const [message, setMessage] = useState<string | null>(null);

  const version = update?.version;
  const showUpdate = Boolean(version) && (update?.state === "ready" || update?.state === "applying");
  useEffect(() => {
    if (!showUpdate) setMessage(null);
  }, [showUpdate]);

  if (!showUpdate && !services?.starting && !services?.problem) return null;

  async function install() {
    if (!updates) return;
    setMessage(null);
    try {
      const result = await updates.apply();
      setUpdate(result);
      // Refused (meetings in process, a folder it cannot write, a failed migration): say why, never fail silently.
      if (result.state === "ready" && result.error) setMessage(applyError(result));
    } catch {
      setMessage(t("settings:updates.errors.generic"));
    }
  }

  const applying = update?.state === "applying";
  return (
    <div className="shell-notices">
      {message && <p role="alert" className="shell-notice-message">{message}</p>}
      {services?.starting && (
        <StatusBadge tone="neutral" role="status" className="shell-notice-badge" title={t("shell:desktop.startingHint")}>
          <Icon icon={LoaderCircle} size={12} className="shell-notice-spin" />
          {t("shell:desktop.starting")}
          <span className="shell-sr-only"> {t("shell:desktop.startingHint")}</span>
        </StatusBadge>
      )}
      {services?.problem && (
        <StatusBadge tone="error" role="alert" dot className="shell-notice-badge" title={t("shell:desktop.problemHint")}>
          {t("shell:desktop.problem")}
          <span className="shell-sr-only"> {t("shell:desktop.problemHint")}</span>
        </StatusBadge>
      )}
      {showUpdate && version && (
        <button
          type="button"
          className="shell-notice-update"
          disabled={applying}
          aria-label={applying ? t("shell:desktop.updating", { version }) : t("shell:desktop.updateLabel", { version })}
          onClick={() => void install()}
        >
          <Icon icon={applying ? LoaderCircle : ArrowDown} size={14} className={applying ? "shell-notice-spin" : undefined} />
          {applying ? t("shell:desktop.updating", { version }) : t("shell:desktop.update", { version })}
        </button>
      )}
    </div>
  );
}
