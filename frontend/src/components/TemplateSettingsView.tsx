import { useEffect, useState, type FormEvent } from "react";
import type { SummaryTemplate, TemplateCategory } from "@sauri/shared-types";
import {
  createCategory, createTemplate, listCategories, listTemplates,
  setDefaultTemplate, updateTemplate,
} from "../api";

export function TemplateSettingsView() {
  const [templates, setTemplates] = useState<SummaryTemplate[]>([]);
  const [categories, setCategories] = useState<TemplateCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [categoryName, setCategoryName] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([listTemplates(), listCategories()]).then(([ownTemplates, ownCategories]) => {
      if (active) {
        setTemplates(ownTemplates);
        setCategories(ownCategories);
        setLoading(false);
      }
    }).catch(() => {
      if (active) { setError("Could not load template settings."); setLoading(false); }
    });
    return () => { active = false; };
  }, []);

  function resetEditor() {
    setEditing(null);
    setName("");
    setInstructions("");
    setCategoryId("");
  }

  function edit(template: SummaryTemplate) {
    setEditing(template.id);
    setName(template.name);
    setInstructions(template.instructions);
    setCategoryId(template.categoryId ?? "");
    setError(null);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const input = { name, instructions, categoryId: categoryId || null };
      if (editing) await updateTemplate(editing, input);
      else await createTemplate(input);
      setTemplates(await listTemplates());
      resetEditor();
    } catch {
      setError("Could not save template. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function addCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await createCategory(categoryName);
      setCategories(await listCategories());
      setCategoryId(created.id);
      setCategoryName("");
    } catch {
      setError("Could not create category. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function chooseDefault(id: string) {
    setBusy(true);
    setError(null);
    try {
      await setDefaultTemplate(id);
      setTemplates(await listTemplates());
    } catch {
      setError("Could not set the default template. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Template settings">
      <h2>Personal summary templates</h2>
      {loading && <p>Loading templates…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && templates.length === 0 && <p>No templates yet. Create your first template below.</p>}
      <ul>
        {templates.map((template) => (
          <li key={template.id}>
            <span>{template.name}</span>{" "}
            {template.isDefault && <strong>Default</strong>}{" "}
            <button type="button" disabled={busy} onClick={() => edit(template)}>Edit</button>{" "}
            {!template.isDefault && (
              <button type="button" disabled={busy} onClick={() => void chooseDefault(template.id)}>
                Set as default
              </button>
            )}
          </li>
        ))}
      </ul>
      <h3>{editing ? "Edit template" : "Create template"}</h3>
      <form onSubmit={(event) => void save(event)}>
        <label htmlFor="template-name">Template name</label>
        <input id="template-name" value={name} required maxLength={128}
          onChange={(event) => setName(event.target.value)} />
        <label htmlFor="template-instructions">Instructions</label>
        <textarea id="template-instructions" value={instructions}
          onChange={(event) => setInstructions(event.target.value)} />
        <label htmlFor="template-category">Category (optional)</label>
        <select id="template-category" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
          <option value="">No category</option>
          {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
        </select>
        <button type="submit" disabled={busy}>{editing ? "Save template" : "Create template"}</button>
        {editing && <button type="button" onClick={resetEditor} disabled={busy}>Cancel edit</button>}
      </form>
      <h3>Create category</h3>
      <form onSubmit={(event) => void addCategory(event)}>
        <label htmlFor="category-name">Category name</label>
        <input id="category-name" value={categoryName} required maxLength={128}
          onChange={(event) => setCategoryName(event.target.value)} />
        <button type="submit" disabled={busy}>Create category</button>
      </form>
    </section>
  );
}
