import { useId, useState } from "react";
import type { FormEvent } from "react";
import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { EngineKindInfo, EngineProbeResult, EngineProcess, EngineProvider, EngineProviderKind } from "@sauri/shared-types";
import {
  EnginesApiError,
  createEngineProvider,
  deleteEngineKey,
  getEngineProvider,
  putEngineKey,
  testEngineProvider,
  updateEngineProvider,
} from "../../api";
import { Button, Dialog, Icon, TextField } from "../ui";
import { isLocalApp, processList } from "./engineLabels";
import { ProviderLogo } from "./ProviderLogo";
import { t, translateIfKnown, useT } from "../../i18n";

/** Same limit as the API schema (`MAX_LABEL_CHARS`). */
const LABEL_MAX_LENGTH = 64;

type Outcome =
  | { tone: "ok"; latencyMs: number | null; schema?: { tone: "ok" | "warn"; text: string } }
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
  return (code && translateIfKnown(`engines:saveErrors.${code}`)) || t("engines:genericError");
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
  const { t } = useT();
  const ids = useId();
  // An account kind is linked from its own card («Conectar con ChatGPT»), not from the key-and-address form.
  const linkable = kinds.filter((info) => info.linkable && info.auth !== "account");
  const [current, setCurrent] = useState<EngineProvider | null>(provider);
  const [kind, setKind] = useState<EngineProviderKind>(provider?.kind ?? initialKind ?? linkable[0]?.kind ?? "openai");
  const info = kinds.find((candidate) => candidate.kind === kind);
  const [label, setLabel] = useState(provider?.label ?? t(`engines:kinds.${kind}.label`));
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
  const byAccount = info?.auth === "account";
  const servedBy = info?.capabilities.map((entry) => entry.capability) ?? [];

  /** What is wrong with each field right now; empty fields are reported once the person has left them. */
  const errors: Fields = {};
  const trimmedLabel = label.trim();
  if (!trimmedLabel) {
    if (touched.label) errors.label = t("engines:dialog.nameRequired");
  } else if (trimmedLabel.length > LABEL_MAX_LENGTH) errors.label = t("engines:dialog.nameTooLong");
  else if (linked.some((other) => other.id !== current?.id && other.label.trim().toLowerCase() === trimmedLabel.toLowerCase())) errors.label = t("engines:dialog.nameDuplicate");
  const trimmedUrl = baseUrl.trim();
  if (!trimmedUrl) {
    if (touched.baseUrl) errors.baseUrl = t("engines:dialog.baseUrlRequired");
  } else if (!ADDRESS_PATTERN.test(trimmedUrl)) errors.baseUrl = t("engines:dialog.baseUrlInvalid");
  if (/\s/.test(keyInput.trim())) errors.key = t("engines:dialog.keyInvalid");
  const valid = trimmedLabel !== "" && trimmedUrl !== "" && !errors.label && !errors.baseUrl && !errors.key;

  function chooseKind(next: EngineProviderKind) {
    const previous = kinds.find((candidate) => candidate.kind === kind);
    const nextInfo = kinds.find((candidate) => candidate.kind === next);
    // A name or address the person has not changed follows the type; one they typed is kept.
    if (label === t(`engines:kinds.${kind}.label`) || label === "") setLabel(t(`engines:kinds.${next}.label`));
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
          if (reverted.length > 0) setNote(t("engines:dialog.revertedByEdit", { list: processList(reverted) }));
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

    if (byAccount) {
      setOutcome({ tone: "info", text: t("engines:account.notNeeded") });
    } else if (!saved.key_set && keyRequired) {
      setOutcome({ tone: "info", text: t("engines:dialog.savedNoKey") });
    } else {
      try {
        // A provider that writes summaries is also tested with the model chosen for them and the real summary format.
        const result = await testEngineProvider(saved.id, servedBy.includes("summary") ? "summary" : undefined);
        setOutcome(
          result.ok
            ? { tone: "ok", latencyMs: result.latency_ms, schema: schemaOutcome(result) }
            : { tone: "fail", cause: t(`engines:causes.${result.error_class ?? "provider_unavailable"}`) },
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
          ? t("engines:dialog.keyRemovedReverted", { list: processList(state.reverted_processes) })
          : t("engines:dialog.keyRemoved"),
      );
      setConfirmingRemoval(false);
    } catch (error) {
      setSaveError(describeEngineError(error));
    }
    setBusy(false);
  }

  const revertsOnRemoval: EngineProcess[] = keyRequired && current ? current.used_by : [];
  const closeIfIdle = busy ? () => undefined : onClose;
  const typeHelp = `${t(`engines:kinds.${kind}.description`)}${servedBy.length > 0 ? ` ${t("engines:dialog.typeServes", { list: processList(servedBy) })}` : ""}`;
  const urlHelp = kind === "openai_compatible" ? t("engines:dialog.baseUrlCompatibleHelp") : t("engines:dialog.baseUrlHelp");

  return (
    <Dialog title={current ? t("engines:dialog.editTitle") : t("engines:dialog.createTitle")} closeLabel={t("engines:dialog.close")} onClose={closeIfIdle}>
      <form className="settings-form engines-form" onSubmit={submit} noValidate>
        {!current && <p className="settings-help">{t("engines:dialog.createIntro")}</p>}
        {current ? (
          <div className="engines-fixed-type">
            <span className="engines-fixed-type-label">{t("engines:dialog.typeFixed")}</span>
            <span className="engines-chip engines-chip--static">
              <ProviderLogo kind={kind} name={t(`engines:kinds.${kind}.label`)} size="sm" />
              {t(`engines:kinds.${kind}.label`)}
            </span>
          </div>
        ) : (
          <div className="engines-kind">
            <span id={`${ids}-kind`} className="engines-fixed-type-label">{t("engines:dialog.type")}</span>
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
                  <ProviderLogo kind={entry.kind} name={t(`engines:kinds.${entry.kind}.label`)} size="sm" />
                  {t(`engines:kinds.${entry.kind}.label`)}
                </label>
              ))}
            </div>
            <span id={`${ids}-kind-help`} className="settings-help">{typeHelp}</span>
          </div>
        )}
        {localApp && !current && <p className="settings-help">{t("engines:dialog.localNote")}</p>}

        <div className="engines-field">
          <TextField
            label={t("engines:dialog.name")}
            value={label}
            error={errors.label}
            disabled={busy}
            aria-describedby={`${ids}-name-help`}
            onChange={(event) => setLabel(event.target.value)}
            onBlur={() => setTouched((previous) => ({ ...previous, label: true }))}
            autoComplete="off"
          />
          <span id={`${ids}-name-help`} className="settings-help">{t("engines:dialog.nameHelp")}</span>
        </div>
        {!byAccount && (
        <div className="engines-field">
          <TextField
            label={t("engines:dialog.baseUrl")}
            value={baseUrl}
            error={errors.baseUrl}
            disabled={busy}
            inputMode="url"
            spellCheck={false}
            autoComplete="off"
            placeholder={t("engines:dialog.baseUrlPlaceholder")}
            aria-describedby={`${ids}-url-help`}
            onChange={(event) => setBaseUrl(event.target.value)}
            onBlur={() => setTouched((previous) => ({ ...previous, baseUrl: true }))}
          />
          <span id={`${ids}-url-help`} className="settings-help">{urlHelp}</span>
        </div>
        )}

        {!localApp && !byAccount && (
          <div className="engines-field">
            <TextField
              label={t("engines:dialog.key")}
              type="password"
              value={keyInput}
              error={errors.key}
              disabled={busy}
              autoComplete="new-password"
              autoCapitalize="off"
              spellCheck={false}
              placeholder={current?.key_set ? (current.key_hint ? t("engines:dialog.keySavedPlaceholderHint", { hint: current.key_hint }) : t("engines:dialog.keySavedPlaceholder")) : t("engines:dialog.keyPlaceholder")}
              aria-describedby={`${ids}-key-help`}
              onChange={(event) => setKeyInput(event.target.value)}
            />
            <span id={`${ids}-key-help`} className="settings-help">{keyRequired ? t("engines:dialog.keyHelp") : t("engines:dialog.keyOptionalHelp")}</span>
            {current?.key_set &&
              (confirmingRemoval ? (
                <div className="engines-key-confirm">
                  <p className="settings-help">
                    {t("engines:dialog.removeKeyConfirm")}
                    {revertsOnRemoval.length > 0 && ` ${t("engines:dialog.removeKeyReverts", { list: processList(revertsOnRemoval) })}`}
                  </p>
                  <div className="engines-key-actions">
                    <Button variant="danger" size="sm" disabled={busy} onClick={removeKey}>{t("engines:dialog.removeKey")}</Button>
                    <Button variant="secondary" size="sm" disabled={busy} onClick={() => setConfirmingRemoval(false)}>
                      {t("engines:dialog.removeKeyKeep")}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="engines-key-actions">
                  <Button variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmingRemoval(true)}>
                    {t("engines:dialog.removeKey")}
                  </Button>
                </div>
              ))}
          </div>
        )}

        <div className="engines-field">
          <div className="settings-switch-row">
            <span id={`${ids}-enabled`} className="settings-switch-label">{t("engines:dialog.enabled")}</span>
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
          <span id={`${ids}-enabled-help`} className="settings-help">{t("engines:dialog.enabledHelp")}</span>
        </div>

        {saveError && <p role="alert" className="ui-field-error engines-save-error">{saveError}</p>}
        <div role="status" className="engines-outcome-slot">
          {outcome && <OutcomeLine outcome={outcome} />}
          {note && <p className="settings-help">{note}</p>}
        </div>

        <div className="ui-dialog-actions">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {outcome || current ? t("engines:dialog.done") : t("engines:dialog.cancel")}
          </Button>
          <Button variant="primary" type="submit" disabled={busy || !valid}>
            {busy ? t("engines:dialog.saving") : t("engines:dialog.saveAndTest")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/** What the summary-format check of a working connection says; nothing when it was not run or decided nothing. */
function schemaOutcome(result: EngineProbeResult): { tone: "ok" | "warn"; text: string } | undefined {
  const model = result.schema_model;
  if (!model) return undefined;
  if (result.json_schema_ok === true) return { tone: "ok", text: t("engines:dialog.testSchemaOk", { model }) };
  // Incompatible (the provider refused the format) is told apart from slow and from a model the account cannot use.
  if (result.json_schema_ok === false) return { tone: "warn", text: t("engines:dialog.testSchemaIncompatible", { model }) };
  if (result.schema_error_class === "provider_timeout") return { tone: "warn", text: t("engines:dialog.testSchemaSlow", { model }) };
  if (result.schema_error_class === "provider_model_unavailable") return { tone: "warn", text: t("engines:dialog.testSchemaUnavailable", { model }) };
  if (result.schema_error_class) {
    return { tone: "warn", text: t("engines:dialog.testSchemaUnknown", { model, cause: t(`engines:causes.${result.schema_error_class}`) }) };
  }
  return undefined;
}

/** The test result: an icon and words, never color alone. */
function OutcomeLine({ outcome }: { outcome: Outcome }) {
  const { t } = useT();
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
      <>
        <p className="engines-outcome engines-outcome--ok">
          <Icon icon={CircleCheck} />
          <span>
            <strong>{t("engines:dialog.testOk")}</strong>
            {outcome.latencyMs !== null && ` · ${t("engines:dialog.latency", { ms: outcome.latencyMs })}`}
          </span>
        </p>
        {outcome.schema && (
          <p className={`engines-outcome engines-outcome--${outcome.schema.tone}`}>
            <Icon icon={outcome.schema.tone === "ok" ? CircleCheck : CircleAlert} />
            <span>{outcome.schema.text}</span>
          </p>
        )}
      </>
    );
  }
  return (
    <p className="engines-outcome engines-outcome--fail">
      <Icon icon={CircleAlert} />
      <span>
        <strong>{t("engines:dialog.testFail")}</strong>
        {` · ${outcome.cause}`}
      </span>
    </p>
  );
}
