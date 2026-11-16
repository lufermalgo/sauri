import { useCallback, useEffect, useState } from "react";
import { FolderPlus, Plus } from "lucide-react";
import { listTemplateCategories, listTemplates, setDefaultTemplate } from "../../api";
import type { SummaryTemplate, TemplateCategory } from "../../api";
import { copy } from "../../copy/es";
import { Button, Icon, Skeleton, StatusBadge } from "../ui";
import { CategoryDialog } from "./CategoryDialog";
import { ProcessSettings } from "./ProcessSettings";
import { TemplateDialog } from "./TemplateDialog";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; templates: SummaryTemplate[]; categories: TemplateCategory[] };

type OpenDialog = { kind: "template"; template: SummaryTemplate | null } | { kind: "category" } | null;
type Notice = { kind: "success" | "error"; text: string } | null;

const text = copy.settings.summaries;

function withDefault(templates: SummaryTemplate[], defaultId: string | null): SummaryTemplate[] {
  return templates.map((template) => ({ ...template, isDefault: template.id === defaultId }));
}

/** Templates grouped by category, with the default marked. Editing, creating and choosing the
 * default all go through the templates API; there is no delete because the API has none. */
export function SummarySettings() {
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
      setNotice({ kind: "success", text: text.defaultSaved(template.name) });
    } catch {
      update((templates) => ({ templates: withDefault(templates, previousId) }));
      setNotice({ kind: "error", text: text.defaultError });
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
    setNotice({ kind: "success", text: copy.settings.summaries.templateSaved(saved.name) });
    setDialog(null);
  }

  function categoryCreated(category: TemplateCategory) {
    update((_templates, categories) => ({ categories: [...categories, category] }));
    setNotice({ kind: "success", text: copy.settings.summaries.categorySaved(category.name) });
    setDialog(null);
  }

  return (
    <div className="settings-stack">
      <ProcessSettings process="summary" />
      <section className="settings-stack" aria-labelledby="summary-templates-title">
      <h3 id="summary-templates-title" className="settings-group-title">{text.templatesTitle}</h3>
      <p className="settings-help">{text.help}</p>
      <div className="settings-toolbar">
        <Button variant="primary" disabled={load.status !== "ready"} onClick={() => setDialog({ kind: "template", template: null })}>
          <Icon icon={Plus} />
          {text.newTemplate}
        </Button>
        <Button variant="secondary" disabled={load.status !== "ready"} onClick={() => setDialog({ kind: "category" })}>
          <Icon icon={FolderPlus} />
          {text.newCategory}
        </Button>
      </div>
      <div role="status" className="settings-notice">{notice?.kind === "success" ? notice.text : null}</div>
      {notice?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{notice.text}</p>}

      {load.status === "loading" && (
        <div role="status" className="settings-loading">
          <p className="settings-help">{text.loading}</p>
          <Skeleton width="100%" height="4.5rem" radius="md" />
        </div>
      )}
      {load.status === "error" && (
        <div className="settings-load-error">
          <p role="alert" className="ui-field-error">{text.loadError}</p>
          <Button variant="secondary" onClick={fetchAll}>{text.retry}</Button>
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

      </section>

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
  const known = new Set(categories.map((category) => category.id));
  const uncategorized = templates.filter((template) => !template.categoryId || !known.has(template.categoryId));
  const groups = [
    ...categories.map((category) => ({
      id: category.id,
      title: category.name,
      items: templates.filter((template) => template.categoryId === category.id),
    })),
    ...(uncategorized.length > 0 ? [{ id: "uncategorized", title: text.uncategorized, items: uncategorized }] : []),
  ];

  if (groups.length === 0) return <p className="settings-help">{text.empty}</p>;

  return (
    <div className="settings-stack">
      {groups.map((group) => (
        <section key={group.id} className="settings-group" aria-labelledby={`settings-group-${group.id}`}>
          <h3 id={`settings-group-${group.id}`} className="settings-group-title">{group.title}</h3>
          {group.items.length === 0 ? (
            <p className="settings-help">{text.emptyCategory}</p>
          ) : (
            <ul className="settings-template-list">
              {group.items.map((template) => (
                <li key={template.id} className="settings-template">
                  <div className="settings-template-main">
                    <div className="settings-template-head">
                      <span className="settings-template-name">{template.name}</span>
                      {template.isDefault && <StatusBadge tone="success">{text.defaultBadge}</StatusBadge>}
                    </div>
                    {template.provenance && <p className="settings-template-note">{template.provenance}</p>}
                  </div>
                  <div className="settings-template-actions">
                    {!template.isDefault && (
                      <Button
                        variant="secondary"
                        size="sm"
                        aria-label={text.useAsDefaultLabel(template.name)}
                        disabled={pendingDefault !== null}
                        onClick={() => onMakeDefault(template)}
                      >
                        {text.useAsDefault}
                      </Button>
                    )}
                    <Button variant="secondary" size="sm" aria-label={text.editLabel(template.name)} onClick={() => onEdit(template)}>
                      {text.edit}
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
