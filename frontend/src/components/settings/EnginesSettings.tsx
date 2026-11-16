import { useCallback, useEffect, useRef, useState } from "react";
import type { EngineKindInfo, EngineProvider, EngineProviderKind } from "@sauri/shared-types";
import {
  deleteEngineProvider,
  getEngineCapabilities,
  listEngineProviders,
  updateEngineProvider,
} from "../../api";
import { copy } from "../../copy/es";
import { Button, ConfirmDialog, Skeleton } from "../ui";
import { processList } from "./engineLabels";
import { ModelsCatalog } from "./ModelsCatalog";
import { ProviderDialog, describeEngineError } from "./ProviderDialog";
import { AddProviderCard, ProviderCard, UnconfiguredCard } from "./ProviderCard";
import { useModelCatalogs } from "./useModelCatalogs";
import "../../styles/engines.css";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; providers: EngineProvider[]; kinds: EngineKindInfo[] };

type OpenDialog = { provider: EngineProvider | null; kind?: EngineProviderKind } | null;
type Notice = { kind: "success" | "error"; text: string } | null;

const text = copy.engines;

/** Cards are listed by state: working ones first, then incomplete, then off. */
const STATE_ORDER: Record<EngineProvider["status"], number> = { active: 0, no_key: 1, disabled: 2, unconfigured: 3 };

/** Everything Sauri can link, preloaded: the providers the person set up (on, off), one dashed card per
 * kind not set up yet, and a last tile to add any provider. Keys never reach this screen, only their last
 * four characters. Below, the models each active provider offers. */
export function EnginesSettings() {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const [deleting, setDeleting] = useState<EngineProvider | null>(null);
  const [turningOff, setTurningOff] = useState<EngineProvider | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const grid = useRef<HTMLUListElement>(null);

  const fetchAll = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    Promise.all([listEngineProviders(), getEngineCapabilities()]).then(
      ([providers, capabilities]) => current && setLoad({ status: "ready", providers, kinds: capabilities.kinds }),
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => fetchAll(), [fetchAll]);

  const ready = load.status === "ready";
  const catalogs = useModelCatalogs(ready ? load.providers : [], ready ? load.kinds : [], ready);

  /** Replaces a provider with the version the API returned, or appends a new one. */
  function providerChanged(changed: EngineProvider) {
    setLoad((previous) => {
      if (previous.status !== "ready") return previous;
      const exists = previous.providers.some((provider) => provider.id === changed.id);
      return {
        ...previous,
        providers: exists
          ? previous.providers.map((provider) => (provider.id === changed.id ? changed : provider))
          : [...previous.providers, changed],
      };
    });
  }

  async function setEnabled(provider: EngineProvider, enabled: boolean) {
    setTurningOff(null);
    setPending(provider.id);
    setNotice(null);
    try {
      const { reverted_processes: reverted, ...updated } = await updateEngineProvider(provider.id, { enabled });
      providerChanged(updated);
      setNotice({
        kind: "success",
        text: enabled
          ? text.turnOff.turnedOn(provider.label)
          : reverted.length > 0
            ? text.turnOff.doneReverted(provider.label, processList(reverted))
            : text.turnOff.done(provider.label),
      });
    } catch (error) {
      setNotice({ kind: "error", text: `${text.turnOff.failed} ${describeEngineError(error)}` });
    } finally {
      setPending(null);
    }
  }

  /** Turning on sends nothing, so it is immediate; turning off sends processes back to local, so it asks. */
  function toggle(provider: EngineProvider, enabled: boolean) {
    if (!enabled && provider.used_by.length > 0) setTurningOff(provider);
    else void setEnabled(provider, enabled);
  }

  async function confirmDelete(provider: EngineProvider) {
    setDeleting(null);
    setPending(provider.id);
    setNotice(null);
    try {
      const { reverted_processes: reverted } = await deleteEngineProvider(provider.id);
      setLoad((previous) =>
        previous.status === "ready"
          ? { ...previous, providers: previous.providers.filter((item) => item.id !== provider.id) }
          : previous);
      setNotice({
        kind: "success",
        text: reverted.length > 0
          ? text.remove.doneReverted(provider.label, processList(reverted))
          : text.remove.done(provider.label),
      });
    } catch (error) {
      setNotice({ kind: "error", text: `${text.remove.failed} ${describeEngineError(error)}` });
    } finally {
      setPending(null);
      // The card that held focus is gone or still there; either way focus returns to a stable control.
      grid.current?.querySelector<HTMLElement>(".engines-add-card")?.focus();
    }
  }

  const providers = ready ? [...load.providers].sort((a, b) => STATE_ORDER[a.status] - STATE_ORDER[b.status]) : [];
  const notSetUp = ready
    ? load.kinds.filter((info) => info.linkable && !load.providers.some((provider) => provider.kind === info.kind))
    : [];

  return (
    <div className="settings-stack engines">
      <div className="engines-intro">
        <p className="settings-help">{text.subtitle}</p>
        <p className="settings-help">{text.help}</p>
      </div>

      <section className="engines-section" aria-labelledby="engines-providers-title">
        <div className="engines-section-head">
          <h3 id="engines-providers-title" className="engines-section-title">{text.providersTitle}</h3>
          <p className="settings-help">{text.providersHelp}</p>
        </div>
        <div role="status" className="settings-notice">{notice?.kind === "success" ? notice.text : null}</div>
        {notice?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{notice.text}</p>}

        {load.status === "loading" && (
          <div role="status" className="settings-loading">
            <p className="settings-help">{text.loading}</p>
            <div className="engines-grid" aria-hidden="true">
              <Skeleton width="100%" height="9rem" radius="md" />
              <Skeleton width="100%" height="9rem" radius="md" />
            </div>
          </div>
        )}
        {load.status === "error" && (
          <div className="settings-load-error">
            <p role="alert" className="ui-field-error">{text.loadError}</p>
            <Button variant="secondary" onClick={fetchAll}>{text.retry}</Button>
          </div>
        )}
        {load.status === "ready" && (
          <ul ref={grid} className="engines-grid" aria-label={text.listLabel}>
            {providers.map((provider) => (
              <li key={provider.id} className="engines-grid-item">
                <ProviderCard
                  provider={provider}
                  kinds={load.kinds}
                  catalog={catalogs.entries[provider.id]}
                  busy={pending === provider.id}
                  onToggle={(enabled) => toggle(provider, enabled)}
                  onEdit={() => setDialog({ provider })}
                  onDelete={() => setDeleting(provider)}
                />
              </li>
            ))}
            {notSetUp.map((info) => (
              <li key={info.kind} className="engines-grid-item">
                <UnconfiguredCard info={info} onConfigure={() => setDialog({ provider: null, kind: info.kind })} />
              </li>
            ))}
            <li className="engines-grid-item">
              <AddProviderCard onAdd={() => setDialog({ provider: null })} />
            </li>
          </ul>
        )}
      </section>

      {load.status === "ready" && (
        <ModelsCatalog
          providers={catalogs.targets}
          entries={catalogs.entries}
          refreshing={catalogs.refreshing}
          onRefresh={() => void catalogs.refreshAll()}
        />
      )}

      {dialog && load.status === "ready" && (
        <ProviderDialog
          provider={dialog.provider}
          initialKind={dialog.kind}
          kinds={load.kinds}
          linked={load.providers}
          onChanged={providerChanged}
          onClose={() => setDialog(null)}
        />
      )}
      {turningOff && (
        <ConfirmDialog
          title={text.turnOff.title}
          body={
            <>
              <p>{text.turnOff.body(turningOff.label)}</p>
              <p>{text.turnOff.reverts(processList(turningOff.used_by))}</p>
            </>
          }
          confirmLabel={text.turnOff.confirm}
          cancelLabel={text.turnOff.cancel}
          onConfirm={() => void setEnabled(turningOff, false)}
          onCancel={() => setTurningOff(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={text.remove.title}
          body={
            <>
              <p>{text.remove.body(deleting.label)}</p>
              <p>{deleting.used_by.length > 0 ? text.remove.reverts(processList(deleting.used_by)) : text.remove.noReverts}</p>
            </>
          }
          confirmLabel={text.remove.confirm}
          cancelLabel={text.remove.cancel}
          onConfirm={() => confirmDelete(deleting)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
