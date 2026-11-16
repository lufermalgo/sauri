import { useId, useState } from "react";
import { ChevronDown, RefreshCw, Search } from "lucide-react";
import type { EngineModel, EngineProvider } from "@sauri/shared-types";
import { Button, Icon, StatusBadge } from "../ui";
import { formatFetchedAt } from "./engineLabels";
import { ProviderLogo } from "./ProviderLogo";
import type { CatalogEntry } from "./useModelCatalogs";
import { useT } from "../../i18n";

function matches(model: EngineModel, query: string): boolean {
  return model.id.toLowerCase().includes(query) || (model.label ?? "").toLowerCase().includes(query);
}

interface ModelsCatalogProps {
  /** Active providers that can serve a process: the only ones asked for their models. */
  providers: EngineProvider[];
  entries: Record<string, CatalogEntry>;
  refreshing: boolean;
  onRefresh: () => void;
}

/** What each active provider offers, as the provider itself listed it: one collapsible row per provider
 * with how many models, when they were asked for and whether it answered; a search across all of them. */
export function ModelsCatalog({ providers, entries, refreshing, onRefresh }: ModelsCatalogProps) {
  const { t } = useT();
  const ids = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const needle = query.trim().toLowerCase();

  function toggle(id: string) {
    setOpen((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  const visible = providers.filter((provider) => {
    const entry = entries[provider.id];
    if (!needle || !entry) return true;
    return entry.status === "ready" && entry.models.some((model) => matches(model, needle));
  });

  return (
    <section className="engines-section" aria-labelledby={`${ids}-title`}>
      <div className="engines-section-head">
        <h3 id={`${ids}-title`} className="engines-section-title">{t("engines:catalog.title")}</h3>
        <p className="settings-help">{t("engines:catalog.help")}</p>
      </div>
      <div className="engines-catalog-tools">
        <label className="engines-search">
          <span className="engines-search-label">{t("engines:catalog.search")}</span>
          <span className="engines-search-field">
            <Icon icon={Search} />
            <input
              type="search"
              className="ui-input"
              value={query}
              placeholder={t("engines:catalog.searchPlaceholder")}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setQuery(event.target.value)}
            />
          </span>
        </label>
        <Button variant="secondary" disabled={refreshing || providers.length === 0} onClick={onRefresh}>
          <Icon icon={RefreshCw} />
          {refreshing ? t("engines:catalog.refreshing") : t("engines:catalog.refresh")}
        </Button>
      </div>

      {providers.length === 0 && <p className="settings-help">{t("engines:catalog.empty")}</p>}
      {providers.length > 0 && visible.length === 0 && <p role="status" className="settings-help">{t("engines:catalog.noMatches")}</p>}
      {visible.length > 0 && (
        <ul className="engines-catalog" aria-label={t("engines:catalog.listLabel")}>
          {visible.map((provider) => {
            const entry = entries[provider.id] ?? { status: "loading" as const };
            const expanded = open.has(provider.id) || (needle !== "" && entry.status === "ready");
            const panelId = `${ids}-${provider.id}`;
            const models = entry.status === "ready" ? entry.models.filter((model) => !needle || matches(model, needle)) : [];
            return (
              <li key={provider.id} className="engines-catalog-row">
                <button
                  type="button"
                  className="engines-catalog-head"
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  aria-label={t("engines:catalog.expand", { name: provider.label })}
                  disabled={entry.status !== "ready"}
                  onClick={() => toggle(provider.id)}
                >
                  <Icon icon={ChevronDown} className="engines-catalog-chevron" />
                  <ProviderLogo kind={provider.kind} name={t(`engines:kinds.${provider.kind}.label`)} size="sm" />
                  <span className="engines-catalog-names">
                    <span className="engines-catalog-name">{provider.label}</span>
                    <span className="engines-catalog-meta">
                      {entry.status === "loading" && t("engines:catalog.loading")}
                      {entry.status === "failed" && t(`engines:causes.${entry.cause}`)}
                      {entry.status === "ready" &&
                        (entry.models.length > 0
                          ? t("engines:catalog.summary", { count: entry.models.length, when: entry.fetchedAt ? formatFetchedAt(entry.fetchedAt) : t("engines:catalog.now") })
                          : t("engines:catalog.summaryNone"))}
                    </span>
                  </span>
                  {entry.status === "ready" && <StatusBadge tone="success" dot>{t("engines:catalog.available")}</StatusBadge>}
                  {entry.status === "failed" && <StatusBadge tone="error" dot>{t("engines:catalog.unreachable")}</StatusBadge>}
                </button>
                <div id={panelId} hidden={!expanded} className="engines-catalog-body">
                  {expanded && (
                    models.length > 0 ? (
                      <ul className="engines-catalog-models" tabIndex={0} aria-label={t("engines:catalog.modelsOf", { name: provider.label })}>
                        {models.map((model) => (
                          <li key={model.id}>
                            {model.label && <span className="engines-model-name">{model.label}</span>}
                            <code className="engines-model-id">{model.id}</code>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="settings-help">{t("engines:catalog.noList")}</p>
                    )
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
