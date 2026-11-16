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
import { navigate } from "../../router";
import { Button, Card, Icon, Skeleton, StatusBadge } from "../ui";
import { availabilityOf, resolvedDefault, formatBytes, processList } from "./engineLabels";
import { LocalModelCard } from "./LocalModelCard";
import { ModelPicker } from "./ModelPicker";
import type { ModelPickerHandle, PickerGroup, PickerOption } from "./ModelPicker";
import { PrivacyNoticeDialog } from "./PrivacyNoticeDialog";
import { describeEngineError } from "./ProviderDialog";
import "../../styles/engines.css";
import { t, useT } from "../../i18n";

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

/** A model list as the picker holds it: `list` stays while it is being asked for again. */
type PickerCatalog =
  | { status: "loading"; list?: EngineModelList }
  | { status: "ready"; list: EngineModelList }
  | { status: "failed" };

/** A choice of external provider waiting for the person to read and accept the privacy notice. */
interface PendingChoice {
  providerId: string;
  model: string;
  fallback: boolean;
  data: EnginePrivacyNotice;
  accepting: boolean;
  error: string | null;
}

function servesProcess(kinds: EngineKindInfo[], kind: EngineProvider["kind"], process: EngineProcess): boolean {
  return kinds.find((info) => info.kind === kind)?.capabilities.some((entry) => entry.capability === process) ?? false;
}

function localName(model: string): string {
  return model === LOCAL_DEFAULT_MODEL ? t("engines:process.localName") : t("engines:process.localModelName", { id: model.slice(LOCAL_PREFIX.length) });
}

interface ProcessSettingsProps {
  process: EngineProcess;
}

/** Engine and model of one process: what it uses today, the picker (local first, then each active
 * provider with its live model catalog), the fallback switch and the local models. Choosing a different
 * external provider is saved only after the person accepts the privacy notice; a model of the provider
 * already in use is saved at once, and going back to a local model too. */
export function ProcessSettings({ process }: ProcessSettingsProps) {
  const { t } = useT();
  const ids = useId();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingChoice | null>(null);
  const [catalogs, setCatalogs] = useState<Record<string, PickerCatalog>>({});
  const [refreshing, setRefreshing] = useState<Record<string, boolean>>({});
  const pickerRef = useRef<ModelPickerHandle>(null);

  const fetchAll = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    setCatalogs({});
    Promise.all([listEngineProcesses(), listEngineProviders(), getEngineCapabilities()]).then(
      ([processes, providers, capabilities]) => {
        if (!current) return;
        const known = processes.some((entry) => entry.capability === process);
        setLoad(known ? { status: "ready", processes, providers, kinds: capabilities.kinds } : { status: "error" });
      },
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, [process]);

  useEffect(() => fetchAll(), [fetchAll]);

  /** Asks a provider for its models; the previous list stays on screen while the new one is on its way. */
  const loadCatalog = useCallback(
    (providerId: string, refresh: boolean) => {
      setCatalogs((previous) => {
        const before = previous[providerId];
        return { ...previous, [providerId]: { status: "loading", list: before && "list" in before ? before.list : undefined } };
      });
      if (refresh) setRefreshing((previous) => ({ ...previous, [providerId]: true }));
      listEngineModels(providerId, process, refresh)
        .then(
          (list) => setCatalogs((previous) => ({ ...previous, [providerId]: { status: "ready", list } })),
          () => setCatalogs((previous) => ({ ...previous, [providerId]: { status: "failed" } })),
        )
        .finally(() => setRefreshing((previous) => ({ ...previous, [providerId]: false })));
    },
    [process],
  );

  if (load.status === "loading") {
    return (
      <div role="status" className="settings-loading">
        <p className="settings-help">{t("engines:process.loading")}</p>
        <Skeleton width="100%" height="4.5rem" radius="md" />
      </div>
    );
  }
  if (load.status === "error") {
    return (
      <div className="settings-load-error">
        <p role="alert" className="ui-field-error">{t("engines:process.loadError")}</p>
        <Button variant="secondary" onClick={fetchAll}>{t("engines:process.retry")}</Button>
      </div>
    );
  }

  const saved = load.processes.find((entry) => entry.capability === process)!;
  const savedExternal = saved.provider_id !== null;
  const eligible = load.providers.filter(
    (provider) => provider.enabled && provider.status === "active" && servesProcess(load.kinds, provider.kind, process),
  );
  // Linked and working, but the type does not serve this process: say why instead of leaving it out silently.
  const notServed = load.providers
    .filter((provider) => provider.enabled && provider.status === "active" && !servesProcess(load.kinds, provider.kind, process))
    .map((provider) => {
      const serves = load.kinds.find((info) => info.kind === provider.kind)?.capabilities.map((entry) => entry.capability) ?? [];
      return {
        id: provider.id,
        note: serves.length > 0
          ? t("engines:process.notServedBy", { provider: provider.label, process: t(`engines:processes.${process}`), only: processList(serves) })
          : t("engines:process.notServedAtAll", { provider: provider.label }),
      };
    });
  // `local:default` is the preferred model when it is ready (Parakeet), else the catalog default (Whisper); every
  // other installed model is listed by its id so the person can pin it and come back to the recommended one.
  const defaultModel = resolvedDefault(localModels, process);
  const installed = localModels.filter(
    (model) => model.process === process && model.kind === "model" && model.id !== defaultModel?.id && availabilityOf(model) === "installed",
  );

  function applyState(next: EngineProcessState) {
    setLoad((previous) =>
      previous.status === "ready"
        ? { ...previous, processes: previous.processes.map((entry) => (entry.capability === next.capability ? next : entry)) }
        : previous);
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
    if (!savedExternal && value === saved.model) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      applyState(await putChoice(null, value, saved.local_fallback));
      setMessage(t("engines:process.savedLocal"));
    } catch (failure) {
      setError(`${t("engines:process.saveFailed")} ${describeEngineError(failure)}`);
    } finally {
      setBusy(false);
    }
  }

  /** Reads the notice for a provider and holds the choice until the person accepts it. Nothing is saved here. */
  async function showNotice(providerId: string, model: string, fallback: boolean, outdated = false): Promise<void> {
    try {
      const data = await getEnginePrivacyNotice(process, providerId);
      setPending({
        providerId, model, fallback, data, accepting: false,
        error: outdated ? t("engines:saveErrors.notice_outdated") : null,
      });
    } catch (failure) {
      setError(`${t("engines:process.saveFailed")} ${describeEngineError(failure)}`);
    }
  }

  async function commitExternal(providerId: string, model: string, fallback: boolean, noticeVersion?: number) {
    try {
      const next = await putChoice(providerId, model, fallback, noticeVersion);
      applyState(next);
      setPending(null);
      setMessage(t("engines:process.saved", { name: t("engines:process.externalName", { provider: next.provider_label ?? providerId, model: next.model }) }));
    } catch (failure) {
      const code = failure instanceof EnginesApiError ? failure.code : null;
      if (code === "notice_required" || code === "notice_outdated") {
        // The consent is missing or the notice changed: the person reads the current one first.
        await showNotice(providerId, model, fallback, code === "notice_outdated");
      } else if (noticeVersion === undefined) {
        setError(`${t("engines:process.saveFailed")} ${describeEngineError(failure)}`);
      } else {
        setPending((current) => current && { ...current, accepting: false, error: describeEngineError(failure) });
      }
    }
  }

  /** A model of a provider. The provider already in use needs no new consent; any other asks first. */
  async function chooseExternal(providerId: string, model: string) {
    if (providerId === saved.provider_id && model === saved.model) return;
    setError(null);
    setMessage(null);
    setBusy(true);
    if (providerId === saved.provider_id) await commitExternal(providerId, model, saved.local_fallback);
    else await showNotice(providerId, model, true);
    setBusy(false);
  }

  async function accept() {
    if (!pending) return;
    setPending({ ...pending, accepting: true, error: null });
    await commitExternal(pending.providerId, pending.model, pending.fallback, pending.data.notice_version);
    setPending((current) => current && { ...current, accepting: false });
  }

  async function toggleFallback() {
    if (!saved.provider_id) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      applyState(await putChoice(saved.provider_id, saved.model, !saved.local_fallback));
      setMessage(t("engines:process.fallbackSaved"));
    } catch (failure) {
      setError(`${t("engines:process.saveFailed")} ${describeEngineError(failure)}`);
    } finally {
      setBusy(false);
    }
  }

  function groupFor(provider: EngineProvider): PickerGroup {
    const entry = catalogs[provider.id];
    const list = entry && "list" in entry ? entry.list : undefined;
    const inUseHere = (model: string) => saved.provider_id === provider.id && saved.model === model;
    const options: PickerOption[] = (list?.models ?? []).map((model) => ({
      key: model.id,
      label: model.label ?? model.id,
      detail: model.label ? model.id : undefined,
      suggested: model.id === list?.starter,
      inUse: inUseHere(model.id),
    }));
    if (saved.provider_id === provider.id && !options.some((option) => option.key === saved.model)) {
      options.unshift({ key: saved.model, label: saved.model, inUse: true });
    }
    const failed = entry?.status === "failed" || (list !== undefined && entry?.status !== "loading" && (list.manual_entry || list.models.length === 0));
    let note: string | undefined;
    if (entry?.status === "failed") note = t("engines:process.modelsFailed");
    else if (list?.error_class) note = `${t("engines:process.modelsFailed")} ${t(`engines:causes.${list.error_class}`)}`;
    else if (entry?.status === "ready" && list && list.models.length === 0) note = t("engines:process.modelsEmpty");
    return {
      id: provider.id,
      label: provider.label,
      logo: { kind: provider.kind, name: t(`engines:kinds.${provider.kind}.label`) },
      options,
      state: entry?.status ?? "loading",
      note,
      onRefresh: () => loadCatalog(provider.id, true),
      refreshing: refreshing[provider.id] === true || entry?.status === "loading",
      refreshLabel: t("engines:process.modelsRefreshLabel", { provider: provider.label }),
      manual: failed ? { onSubmit: (model) => void chooseExternal(provider.id, model) } : undefined,
    };
  }

  const localOptions: PickerOption[] = [
    {
      key: LOCAL_DEFAULT_MODEL,
      label: t("engines:process.localRecommended"),
      detail: defaultModel?.size ? formatBytes(defaultModel.size) : undefined,
      inUse: !savedExternal && saved.model === LOCAL_DEFAULT_MODEL,
    },
    ...installed.map((model) => {
      const key = `${LOCAL_PREFIX}${model.id}`;
      const inUse = !savedExternal && saved.model === key;
      return { key, label: model.id, detail: formatBytes(model.size ?? 0), inUse, tag: model.active && !inUse ? t("engines:process.activeTag") : undefined };
    }),
  ];
  if (!savedExternal && !localOptions.some((option) => option.key === saved.model)) {
    localOptions.push({ key: saved.model, label: saved.model.slice(LOCAL_PREFIX.length), inUse: true });
  }
  const groups: PickerGroup[] = [{ id: "local", label: t("engines:process.localGroup"), options: localOptions }, ...eligible.map(groupFor)];

  const savedName = savedExternal ? t("engines:process.externalName", { provider: saved.provider_label ?? "", model: saved.model }) : localName(saved.model);
  const savedKind = load.providers.find((provider) => provider.id === saved.provider_id)?.kind ?? saved.provider_kind;
  const current = savedExternal
    ? {
        title: saved.provider_label ?? "",
        detail: saved.model,
        logo: savedKind ? { kind: savedKind, name: t(`engines:kinds.${savedKind}.label`) } : undefined,
      }
    : saved.model === LOCAL_DEFAULT_MODEL
      ? { title: t("engines:process.localRecommended") }
      : { title: t("engines:process.badgeLocal"), detail: saved.model.slice(LOCAL_PREFIX.length) };

  /** Warnings that apply to sending this process to `providerId`, as the person is about to decide or has decided. */
  function warningsFor(providerId: string | null, providerName: string): string[] {
    if (!providerId) return [];
    const notes: string[] = [];
    const other = AUDIO_PAIR[process];
    const otherProviderId = other ? load.status === "ready" ? load.processes.find((entry) => entry.capability === other)?.provider_id ?? null : null : null;
    if (other && providerId === otherProviderId) notes.push(t("engines:process.doubleSend", { provider: providerName, other: t(`engines:process.otherProcess.${other}`) }));
    if (process === "diarization") notes.push(t("engines:process.speakersUnvalidated"));
    return notes;
  }
  const savedWarnings = warningsFor(saved.provider_id, saved.provider_label ?? "");
  const pendingProvider = pending ? load.providers.find((provider) => provider.id === pending.providerId) : undefined;
  const pickerHelpId = `${ids}-picker-help`;

  return (
    <div className="settings-stack engines-process">
      <p className="settings-help">{t(`engines:process.help.${process}`)}</p>

      <Card className="engines-current" aria-label={t("engines:process.currentTitle")}>
        <p className="engines-current-line">
          <strong>{t("engines:process.current", { name: savedName })}</strong>
          <StatusBadge tone={savedExternal ? "progress" : "success"}>
            {savedExternal ? t("engines:process.badgeExternal") : t("engines:process.badgeLocal")}
          </StatusBadge>
        </p>
        <p className="settings-help">
          {savedExternal ? t("engines:process.leaves", { provider: saved.provider_label ?? "", what: t(`engines:process.sends.${process}`) }) : t("engines:process.staysHere")}
        </p>
      </Card>

      <div className="engines-selector">
        <ModelPicker
          ref={pickerRef}
          label={t("engines:process.engineLabel")}
          describedBy={pickerHelpId}
          current={current}
          groups={groups}
          disabled={busy}
          onOpenChange={(open) => {
            if (open) eligible.forEach((provider) => loadCatalog(provider.id, false));
          }}
          onSelect={(groupId, key) => {
            if (groupId === "local") void chooseLocal(key);
            else void chooseExternal(groupId, key);
          }}
          footer={(close) => (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy || (!savedExternal && saved.model === LOCAL_DEFAULT_MODEL)}
              onClick={() => {
                close();
                void chooseLocal(LOCAL_DEFAULT_MODEL);
              }}
            >
              {t("engines:process.backToLocal")}
            </Button>
          )}
        />
        <span id={pickerHelpId} className="settings-help">{t("engines:process.engineHelp")}</span>

        {eligible.length === 0 && <p className="settings-help">{t("engines:process.noProviders")}</p>}
        {notServed.map((entry) => (
          <p key={entry.id} className="settings-help">{entry.note}</p>
        ))}

        {savedExternal && (
          <>
            <div className="settings-switch-row">
              <span id={`${ids}-fallback`} className="settings-switch-label">{t("engines:process.fallback")}</span>
              <button
                type="button"
                role="switch"
                className="settings-switch"
                aria-checked={saved.local_fallback}
                aria-labelledby={`${ids}-fallback`}
                aria-describedby={`${ids}-fallback-help`}
                disabled={busy}
                onClick={toggleFallback}
              >
                <span className="settings-switch-thumb" aria-hidden="true" />
              </button>
            </div>
            <span id={`${ids}-fallback-help`} className="settings-help">{t("engines:process.fallbackHelp")}</span>
          </>
        )}

        {savedWarnings.map((warning) => (
          <p key={warning} role="note" className="engines-warning">
            <Icon icon={TriangleAlert} />
            <span>{warning}</span>
          </p>
        ))}

        <div role="status" className="settings-notice">{message}</div>
        {error && <p role="alert" className="ui-field-error settings-notice">{error}</p>}
      </div>

      <LocalModelCard
        process={process}
        selection={{ external: savedExternal, key: saved.model }}
        onModelsChange={setLocalModels}
        onUse={(key) => void chooseLocal(key)}
        choosing={busy}
        external={{
          current: savedExternal ? savedName : null,
          hasProviders: eligible.length > 0,
          onChoose: () => pickerRef.current?.open(),
          onSetup: () => navigate({ name: "settings", category: "engines" }),
        }}
      />

      {pending && (
        <PrivacyNoticeDialog
          notice={pending.data}
          warnings={warningsFor(pending.providerId, pendingProvider?.label ?? pending.data.provider_name)}
          busy={pending.accepting}
          error={pending.error}
          onAccept={accept}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}
