import { useCallback, useEffect, useState } from "react";
import { HardDrive } from "lucide-react";
import { desktopBridge, type FolderKind, type FolderUsage, type RelocateResult, type SauriDesktop } from "../../desktop-bridge";
import { Button, Card, Icon, Skeleton } from "../ui";
import { formatBytes } from "./engineLabels";
import { t, useT } from "../../i18n";

type Load = { status: "loading" } | { status: "error" } | { status: "ready"; folders: FolderUsage[] };
type Outcome = { kind: "success" | "error"; text: string } | null;

function kindName(kind: FolderKind): string {
  return t(`settings:storage.kinds.${kind}.label`);
}

/** The sentence for a finished move; null when the person closed the folder dialog. */
export function relocateMessage(result: RelocateResult): Outcome {
  if (result.ok) {
    const key = result.previousTrashed ? "settings:storage.movedTrashed" : "settings:storage.moved";
    return { kind: "success", text: t(key, { kind: kindName(result.kind), path: result.path }) };
  }
  switch (result.reason) {
    case "cancelled":
      return null;
    case "processing":
      return { kind: "error", text: t("settings:storage.errors.processing", { count: result.count ?? 0 }) };
    case "no_space":
      return {
        kind: "error",
        text: t("settings:storage.errors.no_space", { needed: formatBytes(result.neededBytes ?? 0), free: formatBytes(result.freeBytes ?? 0) }),
      };
    default:
      return {
        kind: "error",
        text: t(`settings:storage.errors.${result.reason}`, { detail: result.detail ?? "" }),
      };
  }
}

/** Each user folder with the space it takes and the free space of its disk; «Cambiar» asks the desktop app. */
export function StorageSettings() {
  const bridge = desktopBridge();
  return bridge ? <DesktopStorage bridge={bridge} /> : <BrowserOnly />;
}

function BrowserOnly() {
  const { t } = useT();
  return (
    <div className="settings-stack">
      <Card className="settings-card" aria-labelledby="settings-storage-browser">
        <h3 id="settings-storage-browser" className="settings-card-title">{t("settings:storage.browserOnly")}</h3>
        <p className="settings-help">{t("settings:storage.browserOnlyHelp")}</p>
      </Card>
    </div>
  );
}

function DesktopStorage({ bridge }: { bridge: SauriDesktop }) {
  const { t } = useT();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [moving, setMoving] = useState<FolderKind | null>(null);
  const [outcome, setOutcome] = useState<Outcome>(null);

  const read = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    bridge.getPaths().then(
      (folders) => current && setLoad({ status: "ready", folders }),
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, [bridge]);

  useEffect(() => read(), [read]);

  async function change(kind: FolderKind) {
    setOutcome(null);
    setMoving(kind);
    try {
      setOutcome(relocateMessage(await bridge.relocate(kind)));
    } catch {
      setOutcome({ kind: "error", text: t("settings:storage.errors.generic") });
    } finally {
      setMoving(null);
      read();
    }
  }

  return (
    <div className="settings-stack">
      <p className="settings-help">{t("settings:storage.intro")}</p>
      {load.status === "loading" && (
        <div role="status" className="settings-loading">
          <p className="settings-help">{t("settings:storage.loading")}</p>
          <Skeleton width="100%" height="4rem" radius="md" />
        </div>
      )}
      {load.status === "error" && (
        <div className="settings-load-error">
          <p role="alert" className="ui-field-error">{t("settings:storage.loadError")}</p>
          <Button variant="secondary" onClick={read}>{t("settings:storage.retry")}</Button>
        </div>
      )}
      {load.status === "ready" &&
        load.folders.map((folder) => {
          const titleId = `settings-storage-${folder.kind}`;
          return (
            <Card key={folder.kind} className="settings-card settings-storage" aria-labelledby={titleId}>
              <div className="settings-storage-row">
                <Icon icon={HardDrive} />
                <div className="settings-storage-text">
                  <h3 id={titleId} className="settings-card-title">{kindName(folder.kind)}</h3>
                  <p className="settings-help">{t(`settings:storage.kinds.${folder.kind}.hint`)}</p>
                  <code className="settings-storage-path">{folder.path}</code>
                  {folder.usedBytes === null ? (
                    <p className="ui-field-error">{t("settings:storage.missing")}</p>
                  ) : (
                    <p className="settings-help">
                      {t("settings:storage.used", { size: formatBytes(folder.usedBytes) })}
                      {folder.freeBytes !== null && ` · ${t("settings:storage.free", { size: formatBytes(folder.freeBytes) })}`}
                    </p>
                  )}
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  aria-label={t("settings:storage.changeLabel", { kind: kindName(folder.kind).toLowerCase() })}
                  disabled={moving !== null}
                  onClick={() => void change(folder.kind)}
                >
                  {t("settings:storage.change")}
                </Button>
              </div>
            </Card>
          );
        })}
      <div role="status" className="settings-notice">
        {moving ? t("settings:storage.moving") : outcome?.kind === "success" ? outcome.text : null}
      </div>
      {outcome?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{outcome.text}</p>}
    </div>
  );
}
