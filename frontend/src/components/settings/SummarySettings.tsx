import { useCallback, useEffect, useState } from "react";
import { FolderPlus, Plus } from "lucide-react";
import { listTemplateCategories, listTemplates, setDefaultTemplate } from "../../api";
import type { SummaryTemplate, TemplateCategory } from "../../api";
import { Button, Icon, Skeleton, StatusBadge, Tabs } from "../ui";
import { CategoryDialog } from "./CategoryDialog";
import { ProcessSettings } from "./ProcessSettings";
import { TemplateDialog } from "./TemplateDialog";
import { useT } from "../../i18n";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; templates: SummaryTemplate[]; categories: TemplateCategory[] };

type SummaryTab = "models" | "templates";

/** The tab last chosen, kept while the person moves around Settings in this session; «Modelos» comes first. */
let lastTab: SummaryTab = "models";

type OpenDialog = { kind: "template"; template: SummaryTemplate | null } | { kind: "category" } | null;
type Notice = { kind: "success" | "error"; text: string } | null;

function withDefault(templates: SummaryTemplate[], defaultId: string | null): SummaryTemplate[] {
  return templates.map((template) => ({ ...template, isDefault: template.id === defaultId }));
}

/** Summaries in two tabs: «Modelos» (the engine and the local models of the process) and «Plantillas» (templates
 * grouped by category, with the default marked). Editing, creating and choosing the default all go through the
 * templates API; there is no delete because the API has none. */
export function SummarySettings() {
  const { t } = useT();
  const [tab, setTab] = useState<SummaryTab>(lastTab);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [pendingDefault, setPendingDefault] = useState<string | null>(null);

  const fetchAll = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    Promise.all([listTemplates(), listTemplateCategories()]).then(
      ([templates, categories]) => current && setLoad({ status: "ready", templates, categories }),
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => fetchAll(), [fetchAll]);

  function update(change: (templates: SummaryTemplate[], categories: TemplateCategory[]) => Partial<{
    templates: SummaryTemplate[];
    categories: TemplateCategory[];
  }>) {
    setLoad((previous) =>
      previous.status === "ready" ? { ...previous, ...change(previous.templates, previous.categories) } : previous);
  }

  /** Optimistic: the mark moves at once and goes back if the API refuses. */
  async function makeDefault(template: SummaryTemplate) {
    if (load.status !== "ready" || pendingDefault) return;
    const previousId = load.templates.find((item) => item.isDefault)?.id ?? null;
    setNotice(null);
    setPendingDefault(template.id);
    update((templates) => ({ templates: withDefault(templates, template.id) }));
    try {
      await setDefaultTemplate(template.id);
      setNotice({ kind: "success", text: t("settings:summaries.defaultSaved", { name: template.name }) });
    } catch {
      update((templates) => ({ templates: withDefault(templates, previousId) }));
      setNotice({ kind: "error", text: t("settings:summaries.defaultError") });
    } finally {
      setPendingDefault(null);
    }
  }

  function templateSaved(saved: SummaryTemplate) {
    update((templates) => {
      const exists = templates.some((template) => template.id === saved.id);
      const merged = exists
        ? templates.map((template) => (template.id === saved.id ? saved : template))
        : [...templates, saved];
      return { templates: saved.isDefault ? withDefault(merged, saved.id) : merged };
    });
    setNotice({ kind: "success", text: t("settings:summaries.templateSaved", { name: saved.name }) });
    setDialog(null);
  }

  function categoryCreated(category: TemplateCategory) {
    update((_templates, categories) => ({ categories: [...categories, category] }));
    setNotice({ kind: "success", text: t("settings:summaries.categorySaved", { name: category.name }) });
    setDialog(null);
  }

  const templatesPanel = (
    <div className="settings-stack">
      <p className="settings-help">{t("settings:summaries.help")}</p>
      <div className="settings-toolbar">
        <Button variant="primary" disabled={load.status !== "ready"} onClick={() => setDialog({ kind: "template", template: null })}>
          <Icon icon={Plus} />
          {t("settings:summaries.newTemplate")}
        </Button>
        <Button variant="secondary" disabled={load.status !== "ready"} onClick={() => setDialog({ kind: "category" })}>
          <Icon icon={FolderPlus} />
          {t("settings:summaries.newCategory")}
        </Button>
      </div>
      <div role="status" className="settings-notice">{notice?.kind === "success" ? notice.text : null}</div>
      {notice?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{notice.text}</p>}

      {load.status === "loading" && (
        <div role="status" className="settings-loading">
          <p className="settings-help">{t("settings:summaries.loading")}</p>
          <Skeleton width="100%" height="4.5rem" radius="md" />
        </div>
      )}
      {load.status === "error" && (
        <div className="settings-load-error">
          <p role="alert" className="ui-field-error">{t("settings:summaries.loadError")}</p>
          <Button variant="secondary" onClick={fetchAll}>{t("settings:summaries.retry")}</Button>
        </div>
      )}
      {load.status === "ready" && (
        <TemplateGroups
          templates={load.templates}
          categories={load.categories}
          pendingDefault={pendingDefault}
          onMakeDefault={makeDefault}
          onEdit={(template) => setDialog({ kind: "template", template })}
        />
      )}
    </div>
  );

  return (
    <div className="settings-stack">
      <Tabs
        aria-label={t("settings:summaries.tabsLabel")}
        activeId={tab}
        onChange={(id) => {
          lastTab = id as SummaryTab;
          setTab(lastTab);
        }}
        tabs={[
          { id: "models", label: t("settings:summaries.tabModels"), panel: <ProcessSettings process="summary" /> },
          { id: "templates", label: t("settings:summaries.tabTemplates"), panel: templatesPanel },
        ]}
      />

      {dialog?.kind === "template" && load.status === "ready" && (
        <TemplateDialog
          template={dialog.template}
          categories={load.categories}
          onClose={() => setDialog(null)}
          onSaved={templateSaved}
        />
      )}
      {dialog?.kind === "category" && <CategoryDialog onClose={() => setDialog(null)} onCreated={categoryCreated} />}
    </div>
  );
}

interface TemplateGroupsProps {
  templates: SummaryTemplate[];
  categories: TemplateCategory[];
  pendingDefault: string | null;
  onMakeDefault: (template: SummaryTemplate) => void;
  onEdit: (template: SummaryTemplate) => void;
}

function TemplateGroups({ templates, categories, pendingDefault, onMakeDefault, onEdit }: TemplateGroupsProps) {
  const { t } = useT();
  const known = new Set(categories.map((category) => category.id));
  const uncategorized = templates.filter((template) => !template.categoryId || !known.has(template.categoryId));
  const groups = [
    ...categories.map((category) => ({
      id: category.id,
      title: category.name,
      items: templates.filter((template) => template.categoryId === category.id),
    })),
    ...(uncategorized.length > 0 ? [{ id: "uncategorized", title: t("settings:summaries.uncategorized"), items: uncategorized }] : []),
  ];

  if (groups.length === 0) return <p className="settings-help">{t("settings:summaries.empty")}</p>;

  return (
    <div className="settings-stack">
      {groups.map((group) => (
        <section key={group.id} className="settings-group" aria-labelledby={`settings-group-${group.id}`}>
          <h3 id={`settings-group-${group.id}`} className="settings-group-title">{group.title}</h3>
          {group.items.length === 0 ? (
            <p className="settings-help">{t("settings:summaries.emptyCategory")}</p>
          ) : (
            <ul className="settings-template-list">
              {group.items.map((template) => (
                <li key={template.id} className="settings-template">
                  <div className="settings-template-main">
                    <div className="settings-template-head">
                      <span className="settings-template-name">{template.name}</span>
                      {template.isDefault && <StatusBadge tone="success">{t("settings:summaries.defaultBadge")}</StatusBadge>}
                    </div>
                    {template.provenance && <p className="settings-template-note">{template.provenance}</p>}
                  </div>
                  <div className="settings-template-actions">
                    {!template.isDefault && (
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={t("settings:summaries.useAsDefaultLabel", { name: template.name })}
                        disabled={pendingDefault !== null}
                        onClick={() => onMakeDefault(template)}
                      >
                        {t("settings:summaries.useAsDefault")}
                      </Button>
                    )}
                    <Button variant="secondary" size="sm" aria-label={t("settings:summaries.editLabel", { name: template.name })} onClick={() => onEdit(template)}>
                      {t("settings:summaries.edit")}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}
