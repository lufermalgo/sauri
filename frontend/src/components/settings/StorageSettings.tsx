import { useCallback, useEffect, useRef, useState } from "react";
import { HardDrive, LoaderCircle } from "lucide-react";
import {
  desktopBridge,
  type FolderKind,
  type FolderUsage,
  type RelocateProgress,
  type RelocateResult,
  type SauriDesktop,
} from "../../desktop-bridge";
import { UpdateSettings } from "./UpdateSettings";
import { Button, Card, Icon, ProgressBar, Skeleton } from "../ui";
import { formatBytes } from "./engineLabels";
import { t, useT } from "../../i18n";

type Load = { status: "loading" } | { status: "error" } | { status: "ready"; folders: FolderUsage[] };
type Outcome = { kind: "success" | "error"; text: string } | null;
/** Where the time estimate starts counting: the first byte count of the copy. */
type CopyStart = { at: number; bytes: number };

/** Only after this long copying is the remaining time estimated, so the first seconds do not mislead. */
export const ESTIMATE_AFTER_MS = 5000;
const COPY_PHASES = new Set<RelocateProgress["phase"]>(["preparing", "copying", "verifying"]);

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

/** The sentence of a move's step, in the person's words; the byte counts are shown apart. */
export function progressText(progress: RelocateProgress): string {
  if (progress.phase === "restarting") {
    return t(progress.kind === "database" ? "settings:storage.progress.restartingDatabase" : "settings:storage.progress.restarting");
  }
  return t(`settings:storage.progress.${progress.phase}`);
}

/** "2,1 GB de 6,4 GB" while copying, or null when the size is not known yet. */
export function progressBytes(progress: RelocateProgress): string | null {
  if (progress.bytesTotal === undefined || progress.bytesDone === undefined || progress.bytesTotal <= 0) return null;
  return t("settings:storage.progress.bytes", { done: formatBytes(progress.bytesDone), total: formatBytes(progress.bytesTotal) });
}

/** About how long the copy still takes, from its pace so far; null while there is not enough to tell. */
export function remainingText(progress: RelocateProgress, start: CopyStart | null, now: number): string | null {
  if (progress.phase !== "copying" || !start || progress.bytesDone === undefined || progress.bytesTotal === undefined) return null;
  const elapsed = now - start.at;
  const copied = progress.bytesDone - start.bytes;
  if (elapsed < ESTIMATE_AFTER_MS || copied <= 0) return null;
  const seconds = ((progress.bytesTotal - progress.bytesDone) * elapsed) / copied / 1000;
  if (seconds < 60) return t("settings:storage.progress.lessThanMinute");
  return t("settings:storage.progress.minutesLeft", { count: Math.round(seconds / 60) });
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
  const [progress, setProgress] = useState<RelocateProgress | null>(null);
  const [remaining, setRemaining] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<{ folder: FolderKind; message: Outcome } | null>(null);
  const movingRef = useRef<FolderKind | null>(null);
  const copyStart = useRef<CopyStart | null>(null);

  useEffect(() => {
    if (!bridge.onRelocateProgress) return;
    return bridge.onRelocateProgress((next) => {
      if (next.kind !== movingRef.current) return;
      const now = Date.now();
      if (next.phase !== "copying") copyStart.current = null;
      else if (!copyStart.current) copyStart.current = { at: now, bytes: next.bytesDone ?? 0 };
      setProgress(next);
      setRemaining(remainingText(next, copyStart.current, now));
    });
  }, [bridge]);

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
    movingRef.current = kind;
    copyStart.current = null;
    setMoving(kind);
    // The app answers with its first step at once; until then the card already says something is happening.
    setProgress(bridge.onRelocateProgress ? { kind, phase: "preparing" } : null);
    setRemaining(null);
    try {
      setOutcome({ folder: kind, message: relocateMessage(await bridge.relocate(kind)) });
    } catch {
      setOutcome({ folder: kind, message: { kind: "error", text: t("settings:storage.errors.generic") } });
    } finally {
      movingRef.current = null;
      setMoving(null);
      setProgress(null);
      setRemaining(null);
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
          const message = outcome?.folder === folder.kind ? outcome.message : null;
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
                  {moving === folder.kind && <MoveProgress kind={folder.kind} progress={progress} remaining={remaining} />}
                  {moving === null && message?.kind === "success" && (
                    <p role="status" className="settings-storage-done">{message.text}</p>
                  )}
                  {moving === null && message?.kind === "error" && (
                    <p role="alert" className="ui-field-error">{message.text}</p>
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
      {bridge.updates && <UpdateSettings updates={bridge.updates} />}
    </div>
  );
}

/** What the card of the folder being moved shows: the step, a bar when the size is known, and a reassurance. */
function MoveProgress({ kind, progress, remaining }: { kind: FolderKind; progress: RelocateProgress | null; remaining: string | null }) {
  const { t } = useT();
  // An app without progress events: one sentence for the whole move.
  const text = progress ? progressText(progress) : t("settings:storage.moving");
  const bytes = progress ? progressBytes(progress) : null;
  const waitsForWindow = progress?.phase === "choosing" || progress?.phase === "confirm_trash";
  // Until the copy is verified the old folder is the one in use, whatever happens.
  const beforeSwitch = !progress || COPY_PHASES.has(progress.phase);
  const percent =
    progress?.bytesTotal && progress.bytesDone !== undefined ? Math.round((progress.bytesDone / progress.bytesTotal) * 100) : null;
  return (
    <div className="settings-storage-progress">
      <p className="settings-storage-phase">
        {!waitsForWindow && <span className="settings-storage-spinner"><Icon icon={LoaderCircle} size={16} /></span>}
        <span role="status" aria-live="polite">{text}</span>
        {bytes && <span className="settings-storage-bytes">{bytes}</span>}
      </p>
      {percent !== null && (
        <ProgressBar label={t("settings:storage.progress.label", { kind: kindName(kind).toLowerCase() })} value={percent} valueText={bytes ?? `${percent} %`} />
      )}
      {remaining && <p className="settings-help">{remaining}</p>}
      {beforeSwitch && <p className="settings-help">{t("settings:storage.progress.keepOpen")}</p>}
    </div>
  );
}
