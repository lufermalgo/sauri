import { useCallback, useEffect, useId, useRef, useState } from "react";
import { TriangleAlert } from "lucide-react";
import type {
  EngineKindInfo,
  EngineModelList,
  EnginePrivacyNotice,
  EngineProcess,
  EngineProcessState,
  EngineProvider,
  LocalModel,
} from "@sauri/shared-types";
import { LOCAL_DEFAULT_MODEL } from "@sauri/shared-types";
import {
  EnginesApiError,
  getEngineCapabilities,
  getEnginePrivacyNotice,
  listEngineModels,
  listEngineProcesses,
  listEngineProviders,
  putEngineProcess,
} from "../../api";
import { copy } from "../../copy/es";
import { navigate } from "../../router";
import { Button, Card, Icon, Skeleton, StatusBadge, TextField } from "../ui";
import { formatBytes } from "./engineLabels";
import { LocalModelCard } from "./LocalModelCard";
import { PrivacyNoticeDialog } from "./PrivacyNoticeDialog";
import { describeEngineError } from "./ProviderDialog";
import "../../styles/engines.css";

const text = copy.engines.process;

const PROVIDER_PREFIX = "provider:";
const LOCAL_PREFIX = "local:";
/** The two processes that send the whole recording to a provider, so one provider on both sends it twice. */
const AUDIO_PAIR: Partial<Record<EngineProcess, EngineProcess>> = {
  transcription: "diarization",
  diarization: "transcription",
};

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; processes: EngineProcessState[]; providers: EngineProvider[]; kinds: EngineKindInfo[] };

/** What the selector shows before it is saved: `target` is a select value (`local:...` or `provider:<id>`). */
interface Draft {
  target: string;
  /** Model of the external provider; empty until the catalog gives a starter. */
  model: string;
  fallback: boolean;
}

type NoticeState = { data: EnginePrivacyNotice; accepting: boolean; error: string | null } | null;

function targetOf(state: EngineProcessState): string {
  return state.provider_id ? `${PROVIDER_PREFIX}${state.provider_id}` : state.model;
}

function draftOf(state: EngineProcessState): Draft {
  return { target: targetOf(state), model: state.provider_id ? state.model : "", fallback: state.local_fallback };
}

function providerIdOf(target: string): string | null {
  return target.startsWith(PROVIDER_PREFIX) ? target.slice(PROVIDER_PREFIX.length) : null;
}

function servesProcess(kinds: EngineKindInfo[], kind: EngineProvider["kind"], process: EngineProcess): boolean {
  return kinds.find((info) => info.kind === kind)?.capabilities.some((entry) => entry.capability === process) ?? false;
}

function localName(model: string): string {
  return model === LOCAL_DEFAULT_MODEL ? text.localName : text.localModelName(model.slice(LOCAL_PREFIX.length));
}

interface ProcessSettingsProps {
  process: EngineProcess;
}

/** Engine and model of one process: what it uses today, the selector (local first, then each active
 * provider with its live model catalog), the fallback switch and the local models. A change to an
 * external provider is saved only after the person accepts the privacy notice. */
export function ProcessSettings({ process }: ProcessSettingsProps) {
  const ids = useId();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState>(null);

  const fetchAll = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    Promise.all([listEngineProcesses(), listEngineProviders(), getEngineCapabilities()]).then(
      ([processes, providers, capabilities]) => {
        if (!current) return;
        const own = processes.find((entry) => entry.capability === process);
        setDraft(own ? draftOf(own) : null);
        setLoad(own ? { status: "ready", processes, providers, kinds: capabilities.kinds } : { status: "error" });
      },
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, [process]);

  useEffect(() => fetchAll(), [fetchAll]);

  if (load.status === "loading") {
    return (
      <div role="status" className="settings-loading">
        <p className="settings-help">{text.loading}</p>
        <Skeleton width="100%" height="4.5rem" radius="md" />
      </div>
    );
  }
  if (load.status === "error" || !draft) {
    return (
      <div className="settings-load-error">
        <p role="alert" className="ui-field-error">{text.loadError}</p>
        <Button variant="secondary" onClick={fetchAll}>{text.retry}</Button>
      </div>
    );
  }

  const saved = load.processes.find((entry) => entry.capability === process)!;
  const savedTarget = targetOf(saved);
  const draftProviderId = providerIdOf(draft.target);
  const draftProvider = load.providers.find((provider) => provider.id === draftProviderId);
  const savedExternal = saved.provider_id !== null;
  const routeDirty = draft.target !== savedTarget || (draftProviderId !== null && draft.model !== saved.model);
  const dirty = routeDirty || (draftProviderId !== null && draft.fallback !== saved.local_fallback);

  const eligible = load.providers.filter(
    (provider) => provider.enabled && provider.status === "active" && servesProcess(load.kinds, provider.kind, process),
  );
  const providerOptions = eligible.map((provider) => ({ id: provider.id, label: provider.label }));
  if (saved.provider_id && !providerOptions.some((option) => option.id === saved.provider_id)) {
    providerOptions.push({ id: saved.provider_id, label: saved.provider_label ?? saved.provider_id });
  }
  const installed = localModels.filter(
    (model) => model.process === process && model.kind === "model" && !model.default && model.state === "installed",
  );
  const localOptions = installed.map((model) => ({
    value: `${LOCAL_PREFIX}${model.id}`,
    label: text.localInstalled(model.id, formatBytes(model.size ?? 0)),
  }));
  if (!savedExternal && saved.model !== LOCAL_DEFAULT_MODEL && !localOptions.some((option) => option.value === saved.model)) {
    localOptions.push({ value: saved.model, label: localName(saved.model) });
  }

  function applyState(next: EngineProcessState) {
    setLoad((previous) =>
      previous.status === "ready"
        ? { ...previous, processes: previous.processes.map((entry) => (entry.capability === next.capability ? next : entry)) }
        : previous);
    setDraft(draftOf(next));
  }

  function putChoice(provider: string | null, model: string, fallback: boolean, noticeVersion?: number) {
    return putEngineProcess(process, {
      provider_id: provider,
      model,
      local_fallback: fallback,
      ...(noticeVersion === undefined ? {} : { notice_version: noticeVersion }),
    });
  }

  /** Back to a local model: saved at once, no confirmation; the API revokes the provider's consent. */
  async function chooseLocal(value: string) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      applyState(await putChoice(null, value, saved.local_fallback));
      setMessage(text.savedLocal);
    } catch (failure) {
      setError(`${text.saveFailed} ${describeEngineError(failure)}`);
    } finally {
      setBusy(false);
    }
  }

  function chooseTarget(value: string) {
    setError(null);
    setMessage(null);
    if (value === savedTarget) {
      setDraft(draftOf(saved));
    } else if (value.startsWith(LOCAL_PREFIX)) {
      void chooseLocal(value);
    } else {
      const sameProvider = providerIdOf(value) === saved.provider_id;
      setDraft({ target: value, model: sameProvider ? saved.model : "", fallback: sameProvider ? saved.local_fallback : true });
    }
  }

  async function showNotice(providerId: string): Promise<boolean> {
    try {
      setNotice({ data: await getEnginePrivacyNotice(process, providerId), accepting: false, error: null });
      return true;
    } catch (failure) {
      setError(`${text.saveFailed} ${describeEngineError(failure)}`);
      return false;
    }
  }

  async function commitExternal(providerId: string, noticeVersion?: number) {
    try {
      const next = await putChoice(providerId, draft!.model.trim(), draft!.fallback, noticeVersion);
      applyState(next);
      setNotice(null);
      setMessage(text.saved(text.externalName(next.provider_label ?? providerId, next.model)));
    } catch (failure) {
      const code = failure instanceof EnginesApiError ? failure.code : null;
      if (code === "notice_required" || code === "notice_outdated") {
        // The consent is missing or the notice changed: the person reads the current one first.
        if (await showNotice(providerId) && code === "notice_outdated") {
          setNotice((current) => current && { ...current, error: copy.engines.saveErrors.notice_outdated });
        }
      } else if (noticeVersion === undefined) {
        setError(`${text.saveFailed} ${describeEngineError(failure)}`);
      } else {
        setNotice((current) => current && { ...current, accepting: false, error: describeEngineError(failure) });
      }
    }
  }

  async function save() {
    if (!draftProviderId || !draft!.model.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    // A different provider needs the person's consent first; a model change within the same one does not.
    if (draftProviderId !== saved.provider_id) await showNotice(draftProviderId);
    else await commitExternal(draftProviderId);
    setBusy(false);
  }

  async function accept() {
    if (!notice || !draftProviderId) return;
    setNotice({ ...notice, accepting: true, error: null });
    await commitExternal(draftProviderId, notice.data.notice_version);
    setNotice((current) => current && { ...current, accepting: false });
  }

  async function toggleFallback() {
    const next = !draft!.fallback;
    setDraft({ ...draft!, fallback: next });
    if (routeDirty || !saved.provider_id) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      applyState(await putChoice(saved.provider_id, saved.model, next));
      setMessage(text.fallbackSaved);
    } catch (failure) {
      setDraft((current) => current && { ...current, fallback: !next });
      setError(`${text.saveFailed} ${describeEngineError(failure)}`);
    } finally {
      setBusy(false);
    }
  }

  const savedName = savedExternal ? text.externalName(saved.provider_label ?? "", saved.model) : localName(saved.model);
  const other = AUDIO_PAIR[process];
  const otherProviderId = other ? load.processes.find((entry) => entry.capability === other)?.provider_id ?? null : null;
  const doubleSend = other !== undefined && draftProviderId !== null && draftProviderId === otherProviderId;
  const providerName = draftProvider?.label ?? saved.provider_label ?? "";
  const selectId = `${ids}-engine`;

  return (
    <div className="settings-stack engines-process">
      <p className="settings-help">{text.help[process]}</p>

      <Card className="engines-current" aria-label={text.currentTitle}>
        <p className="engines-current-line">
          <strong>{text.current(savedName)}</strong>
          <StatusBadge tone={savedExternal ? "progress" : "success"}>
            {savedExternal ? text.badgeExternal : text.badgeLocal}
          </StatusBadge>
        </p>
        <p className="settings-help">
          {savedExternal ? text.leaves(saved.provider_label ?? "", text.sends[process]) : text.staysHere}
        </p>
      </Card>

      <div className="engines-selector">
        <div className="ui-text-field">
          <label htmlFor={selectId}>{text.engineLabel}</label>
          <select
            id={selectId}
            className="ui-input"
            value={draft.target}
            disabled={busy}
            aria-describedby={`${selectId}-help`}
            onChange={(event) => chooseTarget(event.target.value)}
          >
            <optgroup label={text.localGroup}>
              <option value={LOCAL_DEFAULT_MODEL}>{text.localRecommended}</option>
              {localOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </optgroup>
            {providerOptions.length > 0 && (
              <optgroup label={text.providersGroup}>
                {providerOptions.map((option) => (
                  <option key={option.id} value={`${PROVIDER_PREFIX}${option.id}`}>{option.label}</option>
                ))}
              </optgroup>
            )}
          </select>
          <span id={`${selectId}-help`} className="settings-help">{text.engineHelp}</span>
        </div>

        {providerOptions.length === 0 && (
          <div className="engines-no-providers">
            <p className="settings-help">{text.noProviders}</p>
            <Button variant="secondary" size="sm" onClick={() => navigate({ name: "settings", category: "engines" })}>
              {text.goToEngines}
            </Button>
          </div>
        )}

        {draftProviderId && (
          <ExternalModelPicker
            key={draftProviderId}
            process={process}
            providerId={draftProviderId}
            value={draft.model}
            disabled={busy}
            onChange={(model) => setDraft((current) => current && { ...current, model })}
          />
        )}

        {draftProviderId && (
          <>
            <div className="settings-switch-row">
              <span id={`${ids}-fallback`} className="settings-switch-label">{text.fallback}</span>
              <button
                type="button"
                role="switch"
                className="settings-switch"
                aria-checked={draft.fallback}
                aria-labelledby={`${ids}-fallback`}
                aria-describedby={`${ids}-fallback-help`}
                disabled={busy}
                onClick={toggleFallback}
              >
                <span className="settings-switch-thumb" aria-hidden="true" />
              </button>
            </div>
            <span id={`${ids}-fallback-help`} className="settings-help">{text.fallbackHelp}</span>
          </>
        )}

        {doubleSend && other && (
          <p role="note" className="engines-warning">
            <Icon icon={TriangleAlert} />
            <span>{text.doubleSend(providerName, text.otherProcess[other])}</span>
          </p>
        )}
        {process === "diarization" && draftProviderId && (
          <p role="note" className="engines-warning">
            <Icon icon={TriangleAlert} />
            <span>{text.speakersUnvalidated}</span>
          </p>
        )}

        {dirty && (
          <div className="engines-save-row">
            <p className="settings-help">{text.unsaved}</p>
            <div className="engines-key-actions">
              <Button variant="primary" disabled={busy || !draftProviderId || !draft.model.trim()} onClick={save}>
                {busy ? text.saving : text.save}
              </Button>
              <Button variant="secondary" disabled={busy} onClick={() => setDraft(draftOf(saved))}>{text.discard}</Button>
            </div>
          </div>
        )}
        <div role="status" className="settings-notice">{message}</div>
        {error && <p role="alert" className="ui-field-error settings-notice">{error}</p>}
      </div>

      <LocalModelCard process={process} onModelsChange={setLocalModels} />

      {notice && (
        <PrivacyNoticeDialog
          notice={notice.data}
          busy={notice.accepting}
          error={notice.error}
          onAccept={accept}
          onCancel={() => setNotice(null)}
        />
      )}
    </div>
  );
}

type Catalog =
  | { status: "loading" }
  | { status: "ready"; list: EngineModelList }
  | { status: "failed" };

interface ExternalModelPickerProps {
  process: EngineProcess;
  providerId: string;
  value: string;
  disabled: boolean;
  onChange: (model: string) => void;
}

/** Model of an external provider: its live catalog (kept 24 hours; "Volver a pedir" asks again) or, when
 * the provider gives no list or fails, a text field for the model name. */
function ExternalModelPicker({ process, providerId, value, disabled, onChange }: ExternalModelPickerProps) {
  const id = useId();
  const [catalog, setCatalog] = useState<Catalog>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [requests, setRequests] = useState(0);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const valueRef = useRef(value);
  valueRef.current = value;

  useEffect(() => {
    let current = true;
    setRefreshing(true);
    listEngineModels(providerId, process, requests > 0)
      .then(
        (list) => {
          if (!current) return;
          setCatalog({ status: "ready", list });
          // A new choice starts with the provider's suggested model ("Auto").
          if (!valueRef.current) onChangeRef.current(list.starter ?? list.models[0]?.id ?? "");
        },
        () => current && setCatalog({ status: "failed" }),
      )
      .finally(() => current && setRefreshing(false));
    return () => {
      current = false;
    };
  }, [providerId, process, requests]);

  if (catalog.status === "loading") return <p role="status" className="settings-help">{text.modelsLoading}</p>;

  const list = catalog.status === "ready" ? catalog.list : null;
  const manual = !list || list.manual_entry || list.models.length === 0;
  let note: string;
  if (!list) note = text.modelsFailed;
  else if (list.error_class) note = `${text.modelsFailed} ${copy.engines.causes[list.error_class]}`;
  else if (list.models.length === 0) note = text.modelsEmpty;
  else note = list.from_cache ? text.modelsCached : text.modelsFresh;

  return (
    <div className="engines-model">
      {manual || !list ? (
        <>
          <TextField
            id={`${id}-model`}
            label={text.manualModel}
            value={value}
            disabled={disabled}
            autoComplete="off"
            spellCheck={false}
            aria-describedby={`${id}-note`}
            onChange={(event) => onChange(event.target.value)}
          />
          <span className="settings-help">{text.manualModelHelp}</span>
        </>
      ) : (
        <div className="ui-text-field">
          <label htmlFor={`${id}-model`}>{text.model}</label>
          <select
            id={`${id}-model`}
            className="ui-input"
            value={value}
            disabled={disabled}
            aria-describedby={`${id}-note`}
            onChange={(event) => onChange(event.target.value)}
          >
            {value && !list.models.some((model) => model.id === value) && <option value={value}>{value}</option>}
            {list.models.map((model) => (
              <option key={model.id} value={model.id}>
                {model.id === list.starter ? text.modelStarter(model.label ?? model.id) : (model.label ?? model.id)}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="engines-model-meta">
        <span id={`${id}-note`} className="settings-help">{note}</span>
        <Button variant="ghost" size="sm" disabled={disabled || refreshing} onClick={() => setRequests((count) => count + 1)}>
          {refreshing ? text.modelsRefreshing : text.modelsRefresh}
        </Button>
      </div>
    </div>
  );
}
