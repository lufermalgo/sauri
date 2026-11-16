import { useId, useState } from "react";
import type { FormEvent } from "react";
import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { EngineKindInfo, EngineProcess, EngineProvider, EngineProviderKind } from "@sauri/shared-types";
import {
  EnginesApiError,
  createEngineProvider,
  deleteEngineKey,
  getEngineProvider,
  putEngineKey,
  testEngineProvider,
  updateEngineProvider,
} from "../../api";
import { copy } from "../../copy/es";
import { Button, Dialog, Icon, TextField } from "../ui";
import { processList } from "./engineLabels";

const text = copy.engines.dialog;

/** Same limit as the API schema (`MAX_LABEL_CHARS`). */
const LABEL_MAX_LENGTH = 64;

type Outcome =
  | { tone: "ok"; latencyMs: number | null }
  | { tone: "fail"; cause: string }
  | { tone: "info"; text: string };

interface Fields {
  label?: string;
  baseUrl?: string;
  key?: string;
}

export function describeEngineError(error: unknown): string {
  const code = error instanceof EnginesApiError ? error.code : null;
  return (code && copy.engines.saveErrors[code]) || copy.engines.genericError;
}

interface ProviderDialogProps {
  /** The provider to manage, or `null` to link a new one. */
  provider: EngineProvider | null;
  kinds: EngineKindInfo[];
  /** Called with the provider as the API holds it after every step that changed it. */
  onChanged: (provider: EngineProvider) => void;
  onClose: () => void;
}

/** Links or manages one provider: name, address, key and connection test. A key is typed into a
 * password field that is never preloaded; once saved only its last four characters are shown. */
export function ProviderDialog({ provider, kinds, onChanged, onClose }: ProviderDialogProps) {
  const ids = useId();
  const linkable = kinds.filter((info) => info.linkable);
  const [current, setCurrent] = useState<EngineProvider | null>(provider);
  const [kind, setKind] = useState<EngineProviderKind>(provider?.kind ?? linkable[0]?.kind ?? "openai");
  const info = kinds.find((candidate) => candidate.kind === kind);
  const [label, setLabel] = useState(provider?.label ?? copy.engines.kinds[kind].label);
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? info?.default_base_url ?? "");
  const [enabled, setEnabled] = useState(provider?.enabled ?? true);
  const [keyInput, setKeyInput] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Fields>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const keyRequired = info?.key_required ?? true;
  const showKeyField = !current?.key_set || replacing;
  const servedBy = info?.capabilities.map((entry) => entry.capability) ?? [];
  const isLocalApp = kind === "ollama" || kind === "lmstudio";

  function chooseKind(next: EngineProviderKind) {
    const previous = kinds.find((candidate) => candidate.kind === kind);
    const nextInfo = kinds.find((candidate) => candidate.kind === next);
    // A name or address the person has not changed follows the type; one they typed is kept.
    if (label === copy.engines.kinds[kind].label || label === "") setLabel(copy.engines.kinds[next].label);
    if (baseUrl === (previous?.default_base_url ?? "")) setBaseUrl(nextInfo?.default_base_url ?? "");
    setKind(next);
    setKeyInput("");
    setErrors({});
  }

  function validate(): Fields {
    const problems: Fields = {};
    const trimmed = label.trim();
    if (!trimmed) problems.label = text.nameRequired;
    else if (trimmed.length > LABEL_MAX_LENGTH) problems.label = text.nameTooLong;
    if (!baseUrl.trim()) problems.baseUrl = text.baseUrlRequired;
    if (/\s/.test(keyInput.trim())) problems.key = text.keyInvalid;
    return problems;
  }

  /** Re-reads the provider after a key change: the API, not this screen, decides its state. */
  async function refresh(id: string): Promise<EngineProvider> {
    const fresh = await getEngineProvider(id);
    setCurrent(fresh);
    onChanged(fresh);
    return fresh;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problems = validate();
    setErrors(problems);
    if (problems.label || problems.baseUrl || problems.key) return;

    setBusy(true);
    setSaveError(null);
    setNote(null);
    setOutcome(null);
    let saved = current;
    try {
      if (!saved) {
        saved = await createEngineProvider({ kind, label: label.trim(), base_url: baseUrl.trim(), enabled });
        setCurrent(saved);
        onChanged(saved);
      } else {
        const changes: { label?: string; base_url?: string; enabled?: boolean } = {};
        if (label.trim() !== saved.label) changes.label = label.trim();
        if (baseUrl.trim() !== (saved.base_url ?? "")) changes.base_url = baseUrl.trim();
        if (enabled !== saved.enabled) changes.enabled = enabled;
        if (Object.keys(changes).length > 0) {
          const { reverted_processes: reverted, ...updated } = await updateEngineProvider(saved.id, changes);
          saved = updated;
          setCurrent(saved);
          onChanged(saved);
          if (reverted.length > 0) setNote(text.revertedByEdit(processList(reverted)));
        }
      }
      const typedKey = keyInput.trim();
      if (typedKey) {
        await putEngineKey(saved.id, typedKey);
        setKeyInput("");
        setReplacing(false);
        saved = await refresh(saved.id);
      }
    } catch (error) {
      setSaveError(describeEngineError(error));
      setBusy(false);
      return;
    }

    if (!saved.key_set && keyRequired) {
      setOutcome({ tone: "info", text: text.savedNoKey });
    } else {
      try {
        const result = await testEngineProvider(saved.id);
        setOutcome(
          result.ok
            ? { tone: "ok", latencyMs: result.latency_ms }
            : { tone: "fail", cause: copy.engines.causes[result.error_class ?? "provider_unavailable"] },
        );
      } catch (error) {
        setOutcome({ tone: "fail", cause: describeEngineError(error) });
      }
    }
    setBusy(false);
  }

  async function removeKey() {
    if (!current) return;
    setBusy(true);
    setSaveError(null);
    setNote(null);
    setOutcome(null);
    try {
      const state = await deleteEngineKey(current.id);
      await refresh(current.id);
      setNote(
        state.reverted_processes.length > 0
          ? text.keyRemovedReverted(processList(state.reverted_processes))
          : text.keyRemoved,
      );
      setConfirmingRemoval(false);
    } catch (error) {
      setSaveError(describeEngineError(error));
    }
    setBusy(false);
  }

  const revertsOnRemoval: EngineProcess[] = keyRequired && current ? current.used_by : [];
  const keyFieldId = `${ids}-key`;
  const closeIfIdle = busy ? () => undefined : onClose;

  return (
    <Dialog title={current ? text.editTitle : text.createTitle} closeLabel={text.close} onClose={closeIfIdle}>
      <form className="settings-form engines-form" onSubmit={submit} noValidate>
        {current ? (
          <p className="engines-fixed-type">
            <span className="engines-fixed-type-label">{text.typeFixed}</span>
            {copy.engines.kinds[kind].label}
          </p>
        ) : (
          <div className="ui-text-field">
            <label htmlFor={`${ids}-kind`}>{text.type}</label>
            <select
              id={`${ids}-kind`}
              className="ui-input"
              value={kind}
              disabled={busy}
              aria-describedby={`${ids}-kind-help`}
              onChange={(event) => chooseKind(event.target.value as EngineProviderKind)}
            >
              {linkable.map((entry) => (
                <option key={entry.kind} value={entry.kind}>{copy.engines.kinds[entry.kind].label}</option>
              ))}
            </select>
            <span id={`${ids}-kind-help`} className="settings-help">
              {copy.engines.kinds[kind].description}
              {servedBy.length > 0 && ` ${text.typeServes(processList(servedBy))}`}
            </span>
          </div>
        )}
        {isLocalApp && !current && <p className="settings-help">{text.localNote}</p>}

        <TextField
          label={text.name}
          value={label}
          error={errors.label}
          disabled={busy}
          onChange={(event) => setLabel(event.target.value)}
          autoComplete="off"
        />
        <TextField
          label={text.baseUrl}
          value={baseUrl}
          error={errors.baseUrl}
          disabled={busy}
          inputMode="url"
          spellCheck={false}
          autoComplete="off"
          aria-describedby={`${ids}-url-help`}
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <span id={`${ids}-url-help`} className="settings-help engines-field-help">{text.baseUrlHelp}</span>

        {current?.key_set && !replacing ? (
          <div className="engines-key" role="group" aria-label={text.key}>
            <span className="engines-key-label">{text.key}</span>
            <span className="engines-key-state">{text.keySaved(current.key_hint)}</span>
            {confirmingRemoval ? (
              <div className="engines-key-confirm">
                <p className="settings-help">
                  {text.removeKeyConfirm}
                  {revertsOnRemoval.length > 0 && ` ${text.removeKeyReverts(processList(revertsOnRemoval))}`}
                </p>
                <div className="engines-key-actions">
                  <Button variant="danger" size="sm" disabled={busy} onClick={removeKey}>{text.removeKey}</Button>
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => setConfirmingRemoval(false)}>
                    {text.removeKeyKeep}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="engines-key-actions">
                <Button variant="secondary" size="sm" disabled={busy} onClick={() => setReplacing(true)}>{text.replace}</Button>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmingRemoval(true)}>{text.removeKey}</Button>
              </div>
            )}
          </div>
        ) : (
          <>
            <TextField
              id={keyFieldId}
              label={current?.key_set ? text.keyNew : text.key}
              type="password"
              value={keyInput}
              error={errors.key}
              disabled={busy}
              autoComplete="new-password"
              autoCapitalize="off"
              spellCheck={false}
              aria-describedby={`${ids}-key-help`}
              onChange={(event) => setKeyInput(event.target.value)}
            />
            <span id={`${ids}-key-help`} className="settings-help engines-field-help">
              {keyRequired ? text.keyHelp : text.keyOptionalHelp}
            </span>
            {replacing && (
              <div className="engines-key-actions">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => {
                    setReplacing(false);
                    setKeyInput("");
                    setErrors((previous) => ({ ...previous, key: undefined }));
                  }}
                >
                  {text.cancelReplace}
                </Button>
              </div>
            )}
          </>
        )}

        <div className="settings-switch-row">
          <span id={`${ids}-enabled`} className="settings-switch-label">{text.enabled}</span>
          <button
            type="button"
            role="switch"
            className="settings-switch"
            aria-checked={enabled}
            aria-labelledby={`${ids}-enabled`}
            aria-describedby={`${ids}-enabled-help`}
            disabled={busy}
            onClick={() => setEnabled(!enabled)}
          >
            <span className="settings-switch-thumb" aria-hidden="true" />
          </button>
        </div>
        <span id={`${ids}-enabled-help`} className="settings-help engines-field-help">{text.enabledHelp}</span>

        {saveError && <p role="alert" className="ui-field-error engines-save-error">{saveError}</p>}
        <div role="status" className="engines-outcome-slot">
          {outcome && <OutcomeLine outcome={outcome} />}
          {note && <p className="settings-help">{note}</p>}
        </div>

        <div className="ui-dialog-actions">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {outcome || current ? text.done : text.cancel}
          </Button>
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? text.saving : text.saveAndTest}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** The test result: an icon and words, never color alone. */
function OutcomeLine({ outcome }: { outcome: Outcome }) {
  if (outcome.tone === "info") {
    return (
      <p className="engines-outcome engines-outcome--info">
        <Icon icon={Info} />
        <span>{outcome.text}</span>
      </p>
    );
  }
  if (outcome.tone === "ok") {
    return (
      <p className="engines-outcome engines-outcome--ok">
        <Icon icon={CircleCheck} />
        <span>
          <strong>{text.testOk}</strong>
          {outcome.latencyMs !== null && ` · ${text.latency(outcome.latencyMs)}`}
        </span>
      </p>
    );
  }
  return (
    <p className="engines-outcome engines-outcome--fail">
      <Icon icon={CircleAlert} />
      <span>
        <strong>{text.testFail}</strong>
        {` · ${outcome.cause}`}
      </span>
    </p>
  );
}
