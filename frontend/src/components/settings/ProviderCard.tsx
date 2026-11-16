import type { LucideIcon } from "lucide-react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { EngineKindInfo, EngineProvider, EngineProviderKind } from "@sauri/shared-types";
import { Button, Card, Icon, StatusBadge, useTooltip } from "../ui";
import { isLocalApp, processList } from "./engineLabels";
import { ProviderLogo } from "./ProviderLogo";
import type { CatalogEntry } from "./useModelCatalogs";
import { t, useT } from "../../i18n";

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
  if (provider.key_set) return provider.key_hint ? t("engines:card.keyShown", { hint: provider.key_hint }) : t("engines:card.keySaved");
  return info?.key_required === false && isLocalApp(provider.kind) ? t("engines:card.keyNotNeeded") : t("engines:card.keyNone");
}

/** What the provider can do for Sauri: read from the models it listed, or, when its type serves nothing yet, said so. */
function servesLine(info: EngineKindInfo | undefined, catalog: CatalogEntry | undefined): string | null {
  if (info && info.capabilities.length === 0) return t("engines:card.servesNone");
  if (catalog?.status !== "ready") return null;
  return catalog.serves.length > 0 ? t("engines:card.serves", { list: processList(catalog.serves) }) : t("engines:card.servesNone");
}

function modelsLine(provider: EngineProvider, catalog: CatalogEntry | undefined): string {
  if (!catalog) return t("engines:card.modelsNotAsked");
  if (catalog.status === "loading") return t("engines:card.modelsLoading");
  if (catalog.status === "failed" || catalog.models.length === 0) return t("engines:card.modelsNoList");
  return t("engines:card.modelsCount", { count: catalog.models.length });
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
  const { t } = useT();
  const titleId = `engines-card-${provider.id}`;
  const switchLabelId = `${titleId}-switch`;
  const info = kinds.find((candidate) => candidate.kind === provider.kind);
  const kindLabel = t(`engines:kinds.${provider.kind}.label`);
  const dimmed = provider.status === "disabled";
  const serves = servesLine(info, catalog);

  return (
    <Card className="engines-card" dimmed={dimmed} aria-labelledby={titleId}>
      <div className="engines-card-head">
        <ProviderLogo kind={provider.kind} name={kindLabel} />
        <div className="engines-card-names">
          <h4 id={titleId} className="engines-card-title">{provider.label}</h4>
          {provider.label !== kindLabel && <p className="engines-card-kind">{kindLabel}</p>}
        </div>
        <StatusBadge tone={BADGE_TONE[provider.status]} dot>{t(`engines:statuses.${provider.status}`)}</StatusBadge>
      </div>
      <dl className="engines-kv">
        <div>
          <dt>{t("engines:card.address")}</dt>
          <dd className="engines-kv-mono" title={provider.base_url ?? undefined}>{provider.base_url ?? t("engines:card.noAddress")}</dd>
        </div>
        <div>
          <dt>{t("engines:card.key")}</dt>
          <dd className={provider.key_set ? "engines-kv-mono" : undefined}>{keyLine(provider, info)}</dd>
        </div>
        <div>
          <dt>{t("engines:card.models")}</dt>
          <dd>{modelsLine(provider, catalog)}</dd>
        </div>
      </dl>
      {serves && <p className="engines-card-usage">{serves}</p>}
      <p className="engines-card-usage">{provider.used_by.length > 0 ? t("engines:card.usedBy", { list: processList(provider.used_by) }) : t("engines:card.unused")}</p>
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
          <span id={switchLabelId}>{t("engines:card.active")}</span>
        </span>
        <span className="engines-card-icons">
          <IconAction icon={Pencil} label={t("engines:card.edit", { name: provider.label })} disabled={busy} onClick={onEdit} />
          <IconAction icon={Trash2} label={t("engines:card.remove", { name: provider.label })} disabled={busy} onClick={onDelete} />
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
  if (isLocalApp(kind)) return t("engines:card.unconfiguredLocal");
  return kind === "openai_compatible" ? t("engines:card.unconfiguredCompatible") : t("engines:card.unconfiguredKey");
}

/** A kind Sauri can link that the person has not set up: dashed and dimmed, with one way forward and
 * no delete, because there is nothing to delete yet. */
export function UnconfiguredCard({ info, onConfigure }: UnconfiguredCardProps) {
  const { t } = useT();
  const titleId = `engines-kind-${info.kind}`;
  const label = t(`engines:kinds.${info.kind}.label`);
  return (
    <Card className="engines-card" dimmed dashed aria-labelledby={titleId}>
      <div className="engines-card-head">
        <ProviderLogo kind={info.kind} name={label} />
        <div className="engines-card-names">
          <h4 id={titleId} className="engines-card-title">{label}</h4>
        </div>
        <StatusBadge tone="neutral">{t("engines:statuses.unconfigured")}</StatusBadge>
      </div>
      <p className="engines-card-help">{unconfiguredHelp(info.kind)}</p>
      <div className="engines-card-actions">
        <Button variant="secondary" size="sm" aria-label={t("engines:card.configureLabel", { name: label })} onClick={onConfigure}>
          {t("engines:card.configure")}
        </Button>
      </div>
    </Card>
  );
}

/** The last tile of the grid: the way to link a provider of any kind. */
export function AddProviderCard({ onAdd }: { onAdd: () => void }) {
  const { t } = useT();
  return (
    <button type="button" className="engines-add-card" onClick={onAdd}>
      <Icon icon={Plus} />
      {t("engines:add")}
    </button>
  );
}
