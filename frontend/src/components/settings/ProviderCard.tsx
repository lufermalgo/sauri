import type { LucideIcon } from "lucide-react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { EngineKindInfo, EngineProvider, EngineProviderKind } from "@sauri/shared-types";
import { copy } from "../../copy/es";
import { Button, Card, Icon, StatusBadge, useTooltip } from "../ui";
import { isLocalApp, processList } from "./engineLabels";
import { ProviderLogo } from "./ProviderLogo";
import type { CatalogEntry } from "./useModelCatalogs";

const text = copy.engines.card;

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

function keyLine(provider: EngineProvider, info: EngineKindInfo | undefined): string {
  if (provider.key_set) return text.keyShown(provider.key_hint);
  return info?.key_required === false && isLocalApp(provider.kind) ? text.keyNotNeeded : text.keyNone;
}

function modelsLine(provider: EngineProvider, catalog: CatalogEntry | undefined): string {
  if (!catalog) return text.modelsNotAsked;
  if (catalog.status === "loading") return text.modelsLoading;
  if (catalog.status === "failed" || catalog.models.length === 0) return text.modelsNoList;
  return text.modelsCount(catalog.models.length);
}

interface ProviderCardProps {
  provider: EngineProvider;
  kinds: EngineKindInfo[];
  /** What the provider answered when asked for its models, if it was asked. */
  catalog: CatalogEntry | undefined;
  busy: boolean;
  onToggle: (enabled: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}

/** A provider the person linked: logo and name, state in words, address, key hint and model count,
 * the processes using it, and an on/off switch with edit and delete. Off providers are dimmed. */
export function ProviderCard({ provider, kinds, catalog, busy, onToggle, onEdit, onDelete }: ProviderCardProps) {
  const titleId = `engines-card-${provider.id}`;
  const switchLabelId = `${titleId}-switch`;
  const info = kinds.find((candidate) => candidate.kind === provider.kind);
  const kindLabel = copy.engines.kinds[provider.kind].label;
  const dimmed = provider.status === "disabled";

  return (
    <Card className="engines-card" dimmed={dimmed} aria-labelledby={titleId}>
      <div className="engines-card-head">
        <ProviderLogo kind={provider.kind} name={kindLabel} />
        <div className="engines-card-names">
          <h4 id={titleId} className="engines-card-title">{provider.label}</h4>
          {provider.label !== kindLabel && <p className="engines-card-kind">{kindLabel}</p>}
        </div>
        <StatusBadge tone={BADGE_TONE[provider.status]} dot>{copy.engines.statuses[provider.status]}</StatusBadge>
      </div>
      <dl className="engines-kv">
        <div>
          <dt>{text.address}</dt>
          <dd className="engines-kv-mono" title={provider.base_url ?? undefined}>{provider.base_url ?? text.noAddress}</dd>
        </div>
        <div>
          <dt>{text.key}</dt>
          <dd className={provider.key_set ? "engines-kv-mono" : undefined}>{keyLine(provider, info)}</dd>
        </div>
        <div>
          <dt>{text.models}</dt>
          <dd>{modelsLine(provider, catalog)}</dd>
        </div>
      </dl>
      <p className="engines-card-usage">{provider.used_by.length > 0 ? text.usedBy(processList(provider.used_by)) : text.unused}</p>
      <div className="engines-card-actions">
        <span className="engines-card-switch">
          <button
            type="button"
            role="switch"
            className="settings-switch"
            aria-checked={provider.enabled}
            aria-labelledby={`${switchLabelId} ${titleId}`}
            disabled={busy}
            onClick={() => onToggle(!provider.enabled)}
          >
            <span className="settings-switch-thumb" aria-hidden="true" />
          </button>
          <span id={switchLabelId}>{text.active}</span>
        </span>
        <span className="engines-card-icons">
          <IconAction icon={Pencil} label={text.edit(provider.label)} disabled={busy} onClick={onEdit} />
          <IconAction icon={Trash2} label={text.remove(provider.label)} disabled={busy} onClick={onDelete} />
        </span>
      </div>
    </Card>
  );
}

interface UnconfiguredCardProps {
  info: EngineKindInfo;
  onConfigure: () => void;
}

function unconfiguredHelp(kind: EngineProviderKind): string {
  if (isLocalApp(kind)) return text.unconfiguredLocal;
  return kind === "openai_compatible" ? text.unconfiguredCompatible : text.unconfiguredKey;
}

/** A kind Sauri can link that the person has not set up: dashed and dimmed, with one way forward and
 * no delete, because there is nothing to delete yet. */
export function UnconfiguredCard({ info, onConfigure }: UnconfiguredCardProps) {
  const titleId = `engines-kind-${info.kind}`;
  const label = copy.engines.kinds[info.kind].label;
  return (
    <Card className="engines-card" dimmed dashed aria-labelledby={titleId}>
      <div className="engines-card-head">
        <ProviderLogo kind={info.kind} name={label} />
        <div className="engines-card-names">
          <h4 id={titleId} className="engines-card-title">{label}</h4>
        </div>
        <StatusBadge tone="neutral">{copy.engines.statuses.unconfigured}</StatusBadge>
      </div>
      <p className="engines-card-help">{unconfiguredHelp(info.kind)}</p>
      <div className="engines-card-actions">
        <Button variant="secondary" size="sm" aria-label={text.configureLabel(label)} onClick={onConfigure}>
          {text.configure}
        </Button>
      </div>
    </Card>
  );
}

/** The last tile of the grid: the way to link a provider of any kind. */
export function AddProviderCard({ onAdd }: { onAdd: () => void }) {
  return (
    <button type="button" className="engines-add-card" onClick={onAdd}>
      <Icon icon={Plus} />
      {copy.engines.add}
    </button>
  );
}
