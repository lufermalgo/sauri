import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import type { DesktopUpdates, UpdateStatus } from "../../desktop-bridge";
import { Button, Card, Icon, ProgressBar } from "../ui";
import { t, translateIfKnown, useT } from "../../i18n";

/** How often the card looks again while a check, a download or an apply is running. */
export const UPDATE_POLL_MS = 1000;
const WORKING = new Set(["checking", "downloading", "applying"]);

/** The app's updates (design D12): the automatic-check switch, «Buscar ahora» and «Reiniciar y actualizar». */
export function UpdateSettings({ updates, pollIntervalMs = UPDATE_POLL_MS }: { updates: DesktopUpdates; pollIntervalMs?: number }) {
  const { t } = useT();
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [failed, setFailed] = useState(false);

  const read = useCallback(() => {
    updates.status().then(setStatus, () => setFailed(true));
  }, [updates]);
  useEffect(() => read(), [read]);

  const working = status !== null && WORKING.has(status.state);
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(read, pollIntervalMs);
    return () => clearInterval(timer);
  }, [working, read, pollIntervalMs]);

  async function act(action: () => Promise<UpdateStatus>) {
    setFailed(false);
    try {
      setStatus(await action());
    } catch {
      setFailed(true);
    }
  }

  const titleId = "settings-updates-title";
  return (
    <Card className="settings-card" aria-labelledby={titleId}>
      <div className="settings-storage-row">
        <Icon icon={RefreshCw} />
        <div className="settings-storage-text">
          <h3 id={titleId} className="settings-card-title">{t("settings:updates.title")}</h3>
          {status === null ? (
            <p className="settings-help">{failed ? t("settings:updates.loadError") : t("settings:updates.loading")}</p>
          ) : (
            <UpdateBody status={status} />
          )}
        </div>
      </div>
      {status !== null && status.state !== "disabled" && (
        <>
          <label className="settings-help">
            <input
              type="checkbox"
              checked={status.autoCheck}
              onChange={(event) => void act(() => updates.setAutoCheck(event.currentTarget.checked))}
            />{" "}
            {t("settings:updates.auto")}
          </label>
          <div className="welcome-actions">
            {status.state === "ready" ? (
              <Button variant="primary" onClick={() => void act(() => updates.apply())}>
                {t("settings:updates.apply", { version: status.version ?? "" })}
              </Button>
            ) : (
              <Button variant="secondary" disabled={working} onClick={() => void act(() => updates.check())}>
                {t("settings:updates.check")}
              </Button>
            )}
          </div>
        </>
      )}
      {failed && status !== null && <p role="alert" className="ui-field-error">{t("settings:updates.loadError")}</p>}
    </Card>
  );
}

function UpdateBody({ status }: { status: UpdateStatus }) {
  const { t } = useT();
  const current = <p className="settings-help">{t("settings:updates.current", { version: status.current })}</p>;
  switch (status.state) {
    case "disabled":
      return <>{current}<p className="settings-help">{t("settings:updates.disabled")}</p></>;
    case "checking":
      return <>{current}<p role="status" className="settings-help">{t("settings:updates.checking")}</p></>;
    case "downloading":
      return (
        <>
          {current}
          <p role="status" className="settings-help">{t("settings:updates.downloading", { version: status.version ?? "", percent: status.percent ?? 0 })}</p>
          <ProgressBar label={t("settings:updates.progressLabel")} value={status.percent ?? 0} valueText={`${status.percent ?? 0} %`} />
        </>
      );
    case "up_to_date":
      return <>{current}<p role="status" className="settings-help">{t("settings:updates.upToDate")}</p></>;
    case "applying":
      return <>{current}<p role="status" className="settings-help">{t("settings:updates.applying", { version: status.version ?? "" })}</p></>;
    case "ready":
      return (
        <>
          {current}
          <p className="settings-help">{t("settings:updates.ready", { version: status.version ?? "" })}</p>
          {status.error && <p role="alert" className="ui-field-error">{applyError(status)}</p>}
        </>
      );
    case "error":
      return (
        <>
          {current}
          <p role="alert" className="ui-field-error">{t("settings:updates.checkFailed")}</p>
        </>
      );
    default:
      return current;
  }
}

/** Why the last «Reiniciar y actualizar» did not happen. */
export function applyError(status: UpdateStatus): string {
  if (status.error === "processing") return t("settings:updates.errors.processing", { count: status.count ?? 0 });
  if (status.error === "not_writable") return t("settings:updates.errors.not_writable", { path: status.manualZip ?? "" });
  return (status.error && translateIfKnown(`settings:updates.errors.${status.error}`)) || t("settings:updates.errors.generic");
}
