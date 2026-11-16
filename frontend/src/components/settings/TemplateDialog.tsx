import { useId, useState } from "react";
import type { FormEvent } from "react";
import { createTemplate, updateTemplate } from "../../api";
import type { SummaryTemplate, TemplateCategory, TemplateInput } from "../../api";
import { copy } from "../../copy/es";
import { Button, Dialog, TextField } from "../ui";

/** Same limit as the API schema (`TemplateCreate.name`). */
const NAME_MAX_LENGTH = 128;

interface TemplateDialogProps {
  /** The template being edited, or null to create one. */
  template: SummaryTemplate | null;
  categories: TemplateCategory[];
  onClose: () => void;
  onSaved: (template: SummaryTemplate) => void;
}

type FieldErrors = { name?: string; instructions?: string };

function validate(name: string, instructions: string): FieldErrors {
  const errors: FieldErrors = {};
  const trimmed = name.trim();
  if (!trimmed) errors.name = copy.settings.templateDialog.nameRequired;
  else if (trimmed.length > NAME_MAX_LENGTH) errors.name = copy.settings.templateDialog.nameTooLong;
  if (!instructions.trim()) errors.instructions = copy.settings.templateDialog.instructionsRequired;
  return errors;
}

/** Creates or edits a template. Only the fields that changed are sent, so an untouched
 * instructions text never advances the template version. */
export function TemplateDialog({ template, categories, onClose, onSaved }: TemplateDialogProps) {
  const text = copy.settings.templateDialog;
  const ids = useId();
  const [name, setName] = useState(template?.name ?? "");
  const [categoryId, setCategoryId] = useState(template?.categoryId ?? "");
  const [instructions, setInstructions] = useState(template?.instructions ?? "");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validate(name, instructions);
    setErrors(found);
    if (found.name || found.instructions) return;

    const input: TemplateInput = { name: name.trim(), instructions, categoryId: categoryId || null };
    setSaving(true);
    setFailed(false);
    try {
      if (!template) {
        onSaved(await createTemplate(input));
      } else {
        const changes: Partial<TemplateInput> = {};
        if (input.name !== template.name) changes.name = input.name;
        if (input.instructions !== template.instructions) changes.instructions = input.instructions;
        if (input.categoryId !== template.categoryId) changes.categoryId = input.categoryId;
        if (Object.keys(changes).length === 0) {
          onClose();
          return;
        }
        onSaved(await updateTemplate(template.id, changes));
      }
    } catch {
      setFailed(true);
      setSaving(false);
    }
  }

  const instructionsId = `${ids}-instructions`;
  const instructionsHelpId = `${instructionsId}-help`;
  const instructionsErrorId = `${instructionsId}-error`;
  const categoryField = `${ids}-category`;

  return (
    <Dialog
      title={template ? text.editTitle : text.createTitle}
      closeLabel={text.close}
      onClose={saving ? () => undefined : onClose}
    >
      <form className="settings-form" onSubmit={submit} noValidate>
        <TextField
          label={text.name}
          value={name}
          error={errors.name}
          onChange={(event) => setName(event.target.value)}
          autoComplete="off"
        />
        <div className="ui-text-field">
          <label htmlFor={categoryField}>{text.category}</label>
          <select
            id={categoryField}
            className="ui-input"
            value={categoryId}
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="">{copy.settings.summaries.uncategorized}</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>{category.name}</option>
            ))}
          </select>
        </div>
        <div className="ui-text-field">
          <label htmlFor={instructionsId}>{text.instructions}</label>
          <textarea
            id={instructionsId}
            className="ui-input settings-textarea"
            rows={12}
            value={instructions}
            aria-invalid={errors.instructions ? true : undefined}
            aria-describedby={errors.instructions ? `${instructionsHelpId} ${instructionsErrorId}` : instructionsHelpId}
            onChange={(event) => setInstructions(event.target.value)}
          />
          <span id={instructionsHelpId} className="settings-help">{text.instructionsHelp}</span>
          {errors.instructions && (
            <span id={instructionsErrorId} className="ui-field-error" role="alert">{errors.instructions}</span>
          )}
        </div>
        {failed && <p className="ui-field-error" role="alert">{text.error}</p>}
        <div className="ui-dialog-actions">
          <Button variant="secondary" onClick={onClose} disabled={saving}>{text.cancel}</Button>
          <Button variant="primary" type="submit" disabled={saving}>
            {saving ? text.saving : template ? text.save : text.create}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
