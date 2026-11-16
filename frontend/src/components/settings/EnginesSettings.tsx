import { useCallback, useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { EngineKindInfo, EngineProvider } from "@sauri/shared-types";
import { deleteEngineProvider, getEngineCapabilities, listEngineProviders } from "../../api";
import { copy } from "../../copy/es";
import { Button, Card, ConfirmDialog, Icon, Skeleton, StatusBadge, useTooltip } from "../ui";
import { processList } from "./engineLabels";
import { ProviderDialog, describeEngineError } from "./ProviderDialog";
import "../../styles/engines.css";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; providers: EngineProvider[]; kinds: EngineKindInfo[] };

type OpenDialog = { kind: "provider"; provider: EngineProvider | null } | null;
type Notice = { kind: "success" | "error"; text: string } | null;

const text = copy.engines;

const BADGE_TONE = {
  active: "success",
  no_key: "progress",
  disabled: "neutral",
  unconfigured: "neutral",
} as const;

function IconAction({ icon, label, onClick, disabled }: { icon: LucideIcon; label: string; onClick: () => void; disabled?: boolean }) {
  const tip = useTooltip(label);
  return (
    <span className="engines-icon-action">
      <button
        type="button"
        className="ui-icon-button ui-icon-button--quiet"
        aria-label={label}
        disabled={disabled}
        {...tip.triggerProps}
        onClick={onClick}
      >
        <Icon icon={icon} />
      </button>
      {tip.tooltip}
    </span>
  );
}

/** Providers the person linked, as cards: state in words, the processes each one serves, and the
 * actions to manage, edit and delete it. Keys never reach this screen, only their last four characters. */
export function EnginesSettings() {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const [deleting, setDeleting] = useState<EngineProvider | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const toolbar = useRef<HTMLDivElement>(null);

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

  async function confirmDelete(provider: EngineProvider) {
    setDeleting(null);
    setPendingDelete(provider.id);
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
      setPendingDelete(null);
      // The card that held focus is gone or still there; either way focus returns to a stable control.
      toolbar.current?.querySelector("button")?.focus();
    }
  }

  const ready = load.status === "ready";

  return (
    <div className="settings-stack engines">
      <p className="settings-help">{text.help}</p>
      <div ref={toolbar} className="settings-toolbar">
        <Button
          variant="primary"
          disabled={!ready}
          onClick={() => setDialog({ kind: "provider", provider: null })}
        >
          <Icon icon={Plus} />
          {text.add}
        </Button>
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
      {load.status === "ready" && load.providers.length === 0 && (
        <div className="engines-empty">
          <h3 className="engines-empty-title">{text.emptyTitle}</h3>
          <p className="settings-help">{text.emptyBody}</p>
          <Button variant="secondary" onClick={() => setDialog({ kind: "provider", provider: null })}>
            <Icon icon={Plus} />
            {text.add}
          </Button>
        </div>
      )}
      {load.status === "ready" && load.providers.length > 0 && (
        <ul className="engines-grid" aria-label={text.listLabel}>
          {load.providers.map((provider) => (
            <li key={provider.id} className="engines-grid-item">
              <ProviderCard
                provider={provider}
                kinds={load.kinds}
                busy={pendingDelete === provider.id}
                onManage={() => setDialog({ kind: "provider", provider })}
                onDelete={() => setDeleting(provider)}
              />
            </li>
          ))}
        </ul>
      )}

      {dialog && load.status === "ready" && (
        <ProviderDialog
          provider={dialog.provider}
          kinds={load.kinds}
          onChanged={providerChanged}
          onClose={() => setDialog(null)}
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

interface ProviderCardProps {
  provider: EngineProvider;
  kinds: EngineKindInfo[];
  busy: boolean;
  onManage: () => void;
  onDelete: () => void;
}

function ProviderCard({ provider, kinds, busy, onManage, onDelete }: ProviderCardProps) {
  const titleId = `engines-card-${provider.id}`;
  const info = kinds.find((candidate) => candidate.kind === provider.kind);
  const serves = info?.capabilities.map((entry) => entry.capability) ?? [];
  const keyLine = provider.key_set
    ? text.card.keySaved(provider.key_hint)
    : info?.key_required === false
      ? text.card.keyOptional
      : text.card.keyMissing;

  return (
    <Card className="engines-card" aria-labelledby={titleId}>
      <div className="engines-card-head">
        <h3 id={titleId} className="engines-card-title">{provider.label}</h3>
        <StatusBadge tone={BADGE_TONE[provider.status]}>{text.statuses[provider.status]}</StatusBadge>
      </div>
      <p className="engines-card-kind">{text.kinds[provider.kind].label}</p>
      <ul className="engines-card-facts">
        <li>{provider.used_by.length > 0 ? text.card.usedBy(processList(provider.used_by)) : text.card.unused}</li>
        <li>{serves.length > 0 ? text.card.serves(processList(serves)) : text.card.servesNone}</li>
        <li>{keyLine}</li>
        {provider.base_url && <li className="engines-card-url">{provider.base_url}</li>}
      </ul>
      <div className="engines-card-actions">
        <Button variant="secondary" size="sm" aria-label={text.card.manageLabel(provider.label)} disabled={busy} onClick={onManage}>
          {text.card.manage}
        </Button>
        <span className="engines-card-icons">
          <IconAction icon={Pencil} label={text.card.edit(provider.label)} disabled={busy} onClick={onManage} />
          <IconAction icon={Trash2} label={text.card.remove(provider.label)} disabled={busy} onClick={onDelete} />
        </span>
      </div>
    </Card>
  );
}
