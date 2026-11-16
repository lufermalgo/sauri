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
import { isLocalApp, processList } from "./engineLabels";
import { ProviderLogo } from "./ProviderLogo";

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

/** Fields the person has left after typing in them: an empty field is only reported then. */
type Touched = { label: boolean; baseUrl: boolean };

const ADDRESS_PATTERN = /^https?:\/\/\S+$/i;

export function describeEngineError(error: unknown): string {
  const code = error instanceof EnginesApiError ? error.code : null;
  return (code && copy.engines.saveErrors[code]) || copy.engines.genericError;
}

interface ProviderDialogProps {
  /** The provider to manage, or `null` to link a new one. */
  provider: EngineProvider | null;
  /** Kind preselected when linking a new provider (the "Configurar" button of a card). */
  initialKind?: EngineProviderKind;
  kinds: EngineKindInfo[];
  /** Every linked provider; the API refuses a repeated name, this says so while typing. */
  linked: { id: string; label: string }[];
  /** Called with the provider as the API holds it after every step that changed it. */
  onChanged: (provider: EngineProvider) => void;
  onClose: () => void;
}

/** Links or edits one provider in a single dialog: kind chips with their logo, name, address, key and the
 * on/off switch. A key is typed into a password field that is never preloaded; once saved only its last
 * four characters appear, as the field's placeholder. the primary button saves and tests the connection in one go. */
export function ProviderDialog({ provider, initialKind, kinds, linked, onChanged, onClose }: ProviderDialogProps) {
  const ids = useId();
  const linkable = kinds.filter((info) => info.linkable);
  const [current, setCurrent] = useState<EngineProvider | null>(provider);
  const [kind, setKind] = useState<EngineProviderKind>(provider?.kind ?? initialKind ?? linkable[0]?.kind ?? "openai");
  const info = kinds.find((candidate) => candidate.kind === kind);
  const [label, setLabel] = useState(provider?.label ?? copy.engines.kinds[kind].label);
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? info?.default_base_url ?? "");
  const [enabled, setEnabled] = useState(provider?.enabled ?? true);
  const [keyInput, setKeyInput] = useState("");
  const [touched, setTouched] = useState<Touched>({ label: false, baseUrl: false });
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const keyRequired = info?.key_required ?? true;
  const localApp = isLocalApp(kind);
  const servedBy = info?.capabilities.map((entry) => entry.capability) ?? [];

  /** What is wrong with each field right now; empty fields are reported once the person has left them. */
  const errors: Fields = {};
  const trimmedLabel = label.trim();
  if (!trimmedLabel) {
    if (touched.label) errors.label = text.nameRequired;
  } else if (trimmedLabel.length > LABEL_MAX_LENGTH) errors.label = text.nameTooLong;
  else if (linked.some((other) => other.id !== current?.id && other.label.trim().toLowerCase() === trimmedLabel.toLowerCase())) errors.label = text.nameDuplicate;
  const trimmedUrl = baseUrl.trim();
  if (!trimmedUrl) {
    if (touched.baseUrl) errors.baseUrl = text.baseUrlRequired;
  } else if (!ADDRESS_PATTERN.test(trimmedUrl)) errors.baseUrl = text.baseUrlInvalid;
  if (/\s/.test(keyInput.trim())) errors.key = text.keyInvalid;
  const valid = trimmedLabel !== "" && trimmedUrl !== "" && !errors.label && !errors.baseUrl && !errors.key;

  function chooseKind(next: EngineProviderKind) {
    const previous = kinds.find((candidate) => candidate.kind === kind);
    const nextInfo = kinds.find((candidate) => candidate.kind === next);
    // A name or address the person has not changed follows the type; one they typed is kept.
    if (label === copy.engines.kinds[kind].label || label === "") setLabel(copy.engines.kinds[next].label);
    if (baseUrl === (previous?.default_base_url ?? "")) setBaseUrl(nextInfo?.default_base_url ?? "");
    setKind(next);
    setKeyInput("");
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
    if (!valid || busy) return;

    setBusy(true);
    setSaveError(null);
    setNote(null);
    setOutcome(null);
    let saved = current;
    try {
      if (!saved) {
        saved = await createEngineProvider({ kind, label: trimmedLabel, base_url: trimmedUrl, enabled });
        setCurrent(saved);
        onChanged(saved);
      } else {
        const changes: { label?: string; base_url?: string; enabled?: boolean } = {};
        if (trimmedLabel !== saved.label) changes.label = trimmedLabel;
        if (trimmedUrl !== (saved.base_url ?? "")) changes.base_url = trimmedUrl;
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
  const closeIfIdle = busy ? () => undefined : onClose;
  const typeHelp = `${copy.engines.kinds[kind].description}${servedBy.length > 0 ? ` ${text.typeServes(processList(servedBy))}` : ""}`;
  const urlHelp = kind === "openai_compatible" ? text.baseUrlCompatibleHelp : text.baseUrlHelp;

  return (
    <Dialog title={current ? text.editTitle : text.createTitle} closeLabel={text.close} onClose={closeIfIdle}>
      <form className="settings-form engines-form" onSubmit={submit} noValidate>
        {!current && <p className="settings-help">{text.createIntro}</p>}
        {current ? (
          <div className="engines-fixed-type">
            <span className="engines-fixed-type-label">{text.typeFixed}</span>
            <span className="engines-chip engines-chip--static">
              <ProviderLogo kind={kind} name={copy.engines.kinds[kind].label} size="sm" />
              {copy.engines.kinds[kind].label}
            </span>
          </div>
        ) : (
          <div className="engines-kind">
            <span id={`${ids}-kind`} className="engines-fixed-type-label">{text.type}</span>
            <div role="radiogroup" aria-labelledby={`${ids}-kind`} aria-describedby={`${ids}-kind-help`} className="engines-chips">
              {linkable.map((entry) => (
                <label key={entry.kind} className="engines-chip">
                  <input
                    type="radio"
                    name={`${ids}-kind`}
                    value={entry.kind}
                    checked={entry.kind === kind}
                    disabled={busy}
                    onChange={() => chooseKind(entry.kind)}
                  />
                  <ProviderLogo kind={entry.kind} name={copy.engines.kinds[entry.kind].label} size="sm" />
                  {copy.engines.kinds[entry.kind].label}
                </label>
              ))}
            </div>
            <span id={`${ids}-kind-help`} className="settings-help">{typeHelp}</span>
          </div>
        )}
        {localApp && !current && <p className="settings-help">{text.localNote}</p>}

        <div className="engines-field">
          <TextField
            label={text.name}
            value={label}
            error={errors.label}
            disabled={busy}
            aria-describedby={`${ids}-name-help`}
            onChange={(event) => setLabel(event.target.value)}
            onBlur={() => setTouched((previous) => ({ ...previous, label: true }))}
            autoComplete="off"
          />
          <span id={`${ids}-name-help`} className="settings-help">{text.nameHelp}</span>
        </div>
        <div className="engines-field">
          <TextField
            label={text.baseUrl}
            value={baseUrl}
            error={errors.baseUrl}
            disabled={busy}
            inputMode="url"
            spellCheck={false}
            autoComplete="off"
            placeholder={text.baseUrlPlaceholder}
            aria-describedby={`${ids}-url-help`}
            onChange={(event) => setBaseUrl(event.target.value)}
            onBlur={() => setTouched((previous) => ({ ...previous, baseUrl: true }))}
          />
          <span id={`${ids}-url-help`} className="settings-help">{urlHelp}</span>
        </div>

        {!localApp && (
          <div className="engines-field">
            <TextField
              label={text.key}
              type="password"
              value={keyInput}
              error={errors.key}
              disabled={busy}
              autoComplete="new-password"
              autoCapitalize="off"
              spellCheck={false}
              placeholder={current?.key_set ? text.keySavedPlaceholder(current.key_hint) : text.keyPlaceholder}
              aria-describedby={`${ids}-key-help`}
              onChange={(event) => setKeyInput(event.target.value)}
            />
            <span id={`${ids}-key-help`} className="settings-help">{keyRequired ? text.keyHelp : text.keyOptionalHelp}</span>
            {current?.key_set &&
              (confirmingRemoval ? (
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
                  <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmingRemoval(true)}>
                    {text.removeKey}
                  </Button>
                </div>
              ))}
          </div>
        )}

        <div className="engines-field">
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
          <span id={`${ids}-enabled-help`} className="settings-help">{text.enabledHelp}</span>
        </div>

        {saveError && <p role="alert" className="ui-field-error engines-save-error">{saveError}</p>}
        <div role="status" className="engines-outcome-slot">
          {outcome && <OutcomeLine outcome={outcome} />}
          {note && <p className="settings-help">{note}</p>}
        </div>

        <div className="ui-dialog-actions">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {outcome || current ? text.done : text.cancel}
          </Button>
          <Button variant="primary" type="submit" disabled={busy || !valid}>
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
