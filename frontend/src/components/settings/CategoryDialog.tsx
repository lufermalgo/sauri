import { useState } from "react";
import type { FormEvent } from "react";
import { createTemplateCategory } from "../../api";
import type { TemplateCategory } from "../../api";
import { copy } from "../../copy/es";
import { Button, Dialog, TextField } from "../ui";

/** Same limit as the API schema (`CategoryCreate.name`). */
const NAME_MAX_LENGTH = 128;

interface CategoryDialogProps {
  onClose: () => void;
  onCreated: (category: TemplateCategory) => void;
}

/** Creates a template category. The API has no rename or delete for categories. */
export function CategoryDialog({ onClose, onCreated }: CategoryDialogProps) {
  const text = copy.settings.categoryDialog;
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string | undefined>();
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    const problem = !trimmed ? text.nameRequired : trimmed.length > NAME_MAX_LENGTH ? text.nameTooLong : undefined;
    setNameError(problem);
    if (problem) return;

    setSaving(true);
    setFailed(false);
    try {
      onCreated(await createTemplateCategory(trimmed));
    } catch {
      setFailed(true);
      setSaving(false);
    }
  }

  return (
    <Dialog title={text.title} closeLabel={text.close} size="sm" onClose={saving ? () => undefined : onClose}>
      <form className="settings-form" onSubmit={submit} noValidate>
        <TextField
          label={text.name}
          value={name}
          error={nameError}
          onChange={(event) => setName(event.target.value)}
          autoComplete="off"
        />
        {failed && <p className="ui-field-error" role="alert">{text.error}</p>}
        <div className="ui-dialog-actions">
          <Button variant="secondary" onClick={onClose} disabled={saving}>{text.cancel}</Button>
          <Button variant="primary" type="submit" disabled={saving}>{saving ? text.saving : text.create}</Button>
        </div>
      </form>
    </Dialog>
  );
}
