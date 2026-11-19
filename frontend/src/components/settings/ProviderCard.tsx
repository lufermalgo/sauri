import { useId } from "react";
import type { LucideIcon } from "lucide-react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import type { EngineAccount, EngineKindInfo, EngineProvider } from "@sauri/shared-types";
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

/** What the card knows of the ChatGPT account behind an account provider (asked once when the screen opens). */
export type AccountView = { status: "loading" } | { status: "ready"; account: EngineAccount } | { status: "failed" };

function accountLine(view: AccountView | undefined): string {
  if (!view || view.status === "loading") return t("engines:account.checking");
  if (view.status === "failed") return t("engines:account.notConnected");
  if (view.account.state === "connected") return t("engines:account.connectedAs", { who: view.account.account ?? "ChatGPT" });
  return view.account.error === "session_expired" ? t("engines:account.errors.session_expired") : t("engines:account.notConnected");
}

function keyLine(provider: EngineProvider, info: EngineKindInfo | undefined): string {
  if (provider.key_set) return provider.key_hint ? t("engines:card.keyShown", { hint: provider.key_hint }) : t("engines:card.keySaved");
  return info?.key_required === false && isLocalApp(provider.kind) ? t("engines:card.keyNotNeeded") : t("engines:card.keyNone");
}

/** What the provider can do for Sauri: read from the models it listed, or, when its type serves nothing yet, said so. */
function servesLine(info: EngineKindInfo | undefined, catalog: CatalogEntry | undefined): string | null {
  if (info && info.capabilities.length === 0) return t("engines:card.servesNone");
  // An account provider lists models only while signed in; the offered pairs still say what it is for.
  if (info?.auth === "account" && catalog?.status !== "ready") {
    return t("engines:card.serves", { list: processList(info.capabilities.map((entry) => entry.capability)) });
  }
  if (catalog?.status !== "ready") return null;
  return catalog.serves.length > 0 ? t("engines:card.serves", { list: processList(catalog.serves) }) : t("engines:card.servesNone");
}

function modelsLine(catalog: CatalogEntry | undefined, byAccount: boolean): string {
  if (!catalog) return t("engines:card.modelsNotAsked");
  if (catalog.status === "loading") return t("engines:card.modelsLoading");
  if (catalog.status === "failed" && byAccount) return t("engines:account.modelsFailed");
  if (catalog.status === "failed" || catalog.models.length === 0) return t("engines:card.modelsNoList");
  return t("engines:card.modelsCount", { count: catalog.models.length });
}

interface ProviderCardProps {
  provider: EngineProvider;
  kinds: EngineKindInfo[];
  /** What the provider answered when asked for its models, if it was asked. */
  catalog: CatalogEntry | undefined;
  busy: boolean;
  /** The ChatGPT account state, for providers that sign in with an account instead of a key. */
  account?: AccountView;
  onToggle: (enabled: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

/** A provider the person linked: logo and name, state in words, address, key hint and model count,
 * the processes using it, and an on/off switch with edit and delete. Off providers are dimmed. */
export function ProviderCard({
  provider, kinds, catalog, busy, account, onToggle, onEdit, onDelete, onConnect, onDisconnect,
}: ProviderCardProps) {
  const { t } = useT();
  const titleId = `engines-card-${provider.id}`;
  const switchLabelId = `${titleId}-switch`;
  const info = kinds.find((candidate) => candidate.kind === provider.kind);
  const kindLabel = t(`engines:kinds.${provider.kind}.label`);
  const dimmed = provider.status === "disabled";
  const serves = servesLine(info, catalog);
  const byAccount = info?.auth === "account";
  const connected = account?.status === "ready" && account.account.state === "connected";

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
          <dt>{byAccount ? t("engines:account.row") : t("engines:card.key")}</dt>
          <dd className={provider.key_set && !byAccount ? "engines-kv-mono" : undefined}>
            {byAccount ? accountLine(account) : keyLine(provider, info)}
          </dd>
        </div>
        <div>
          <dt>{t("engines:card.models")}</dt>
          <dd>{modelsLine(catalog, byAccount)}</dd>
        </div>
      </dl>
      {serves && <p className="engines-card-usage">{serves}</p>}
      <p className="engines-card-usage">{provider.used_by.length > 0 ? t("engines:card.usedBy", { list: processList(provider.used_by) }) : t("engines:card.unused")}</p>
      {byAccount && <p className="engines-card-usage">{t("engines:account.unofficial")}</p>}
      <div className="engines-card-actions">
        {byAccount && (
          <Button
            variant={connected ? "ghost" : "secondary"}
            size="sm"
            disabled={busy || !account || account.status === "loading"}
            aria-label={
              connected
                ? t("engines:account.disconnectLabel", { name: provider.label })
                : t("engines:account.connectLabel", { name: provider.label })
            }
            onClick={connected ? onDisconnect : onConnect}
          >
            {connected ? t("engines:account.disconnect") : t("engines:account.connect")}
          </Button>
        )}
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

/** The last tile of the grid: the one way to link a provider, of any kind. Its hint says what can be added. */
export function AddProviderCard({ onAdd, disabled }: { onAdd: () => void; disabled?: boolean }) {
  const { t } = useT();
  const ids = useId();
  return (
    <button
      type="button"
      className="engines-add-card"
      disabled={disabled}
      aria-labelledby={`${ids}-label`}
      aria-describedby={`${ids}-hint`}
      onClick={onAdd}
    >
      <span className="engines-add-card-label">
        <Icon icon={Plus} />
        <span id={`${ids}-label`}>{t("engines:add")}</span>
      </span>
      <span id={`${ids}-hint`} className="engines-add-card-hint">{t("engines:addHint")}</span>
    </button>
  );
}
