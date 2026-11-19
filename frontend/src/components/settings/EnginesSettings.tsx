import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EngineKindInfo, EngineProvider, EngineProviderKind } from "@sauri/shared-types";
import {
  createEngineProvider,
  deleteEngineProvider,
  disconnectEngineAccount,
  getEngineAccount,
  getEngineCapabilities,
  listEngineProviders,
  updateEngineProvider,
} from "../../api";
import { Button, ConfirmDialog, Skeleton } from "../ui";
import { processList } from "./engineLabels";
import { AccountDialog } from "./AccountDialog";
import { ModelsCatalog } from "./ModelsCatalog";
import { ProviderDialog, describeEngineError } from "./ProviderDialog";
import { AddProviderCard, ProviderCard } from "./ProviderCard";
import type { AccountView } from "./ProviderCard";
import { AddProviderDialog } from "./AddProviderDialog";
import { useModelCatalogs } from "./useModelCatalogs";
import "../../styles/engines.css";
import { useT } from "../../i18n";

type Load =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; providers: EngineProvider[]; kinds: EngineKindInfo[] };

type OpenDialog = { provider: EngineProvider | null; kind: EngineProviderKind } | null;
type Notice = { kind: "success" | "error"; text: string } | null;

/** Cards are listed by state: working ones first, then incomplete, then off. */
const STATE_ORDER: Record<EngineProvider["status"], number> = { active: 0, no_key: 1, disabled: 2, unconfigured: 3 };

/** Only what the person linked: one card per provider they set up (on or off) and a last tile, «Agregar
 * proveedor», that lists every kind Sauri can link. Keys never reach this screen, only their last four
 * characters. Below, the models each active provider offers. */
export function EnginesSettings() {
  const { t } = useT();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [adding, setAdding] = useState(false);
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const [deleting, setDeleting] = useState<EngineProvider | null>(null);
  const [turningOff, setTurningOff] = useState<EngineProvider | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [accounts, setAccounts] = useState<Record<string, AccountView>>({});
  const [signingIn, setSigningIn] = useState<EngineProvider | null>(null);
  const [disconnecting, setDisconnecting] = useState<EngineProvider | null>(null);
  const grid = useRef<HTMLUListElement>(null);

  const fetchAll = useCallback(() => {
    let current = true;
    setLoad({ status: "loading" });
    Promise.all([listEngineProviders(), getEngineCapabilities()]).then(
      ([providers, capabilities]) => current && setLoad({ status: "ready", providers, kinds: capabilities.kinds }),
      () => current && setLoad({ status: "error" }),
    );
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => fetchAll(), [fetchAll]);

  const ready = load.status === "ready";

  /** Asks the API who is signed in for a provider that uses an account (never a token, only the label). */
  const loadAccount = useCallback((providerId: string) => {
    setAccounts((previous) => ({ ...previous, [providerId]: { status: "loading" } }));
    getEngineAccount(providerId).then(
      (account) => setAccounts((previous) => ({ ...previous, [providerId]: { status: "ready", account } })),
      () => setAccounts((previous) => ({ ...previous, [providerId]: { status: "failed" } })),
    );
  }, []);

  const accountIds = ready
    ? load.providers
        .filter((provider) => load.kinds.find((info) => info.kind === provider.kind)?.auth === "account")
        .map((provider) => provider.id)
        .join("|")
    : "";
  useEffect(() => {
    accountIds.split("|").filter(Boolean).forEach(loadAccount);
  }, [accountIds, loadAccount]);

  // An account provider lists its models only while its account is connected, and as soon as it is.
  const connectedIds = Object.entries(accounts)
    .filter(([, view]) => view.status === "ready" && view.account.state === "connected")
    .map(([id]) => id)
    .join("|");
  const connectedAccounts = useMemo(() => new Set(connectedIds.split("|").filter(Boolean)), [connectedIds]);
  const catalogs = useModelCatalogs(ready ? load.providers : [], ready ? load.kinds : [], ready, connectedAccounts);

  /** Replaces a provider with the version the API returned, or appends a new one. */
  function providerChanged(changed: EngineProvider) {
    setLoad((previous) => {
      if (previous.status !== "ready") return previous;
      const exists = previous.providers.some((provider) => provider.id === changed.id);
      return {
        ...previous,
        providers: exists
          ? previous.providers.map((provider) => (provider.id === changed.id ? changed : provider))
          : [...previous.providers, changed],
      };
    });
  }

  async function setEnabled(provider: EngineProvider, enabled: boolean) {
    setTurningOff(null);
    setPending(provider.id);
    setNotice(null);
    try {
      const { reverted_processes: reverted, ...updated } = await updateEngineProvider(provider.id, { enabled });
      providerChanged(updated);
      setNotice({
        kind: "success",
        text: enabled
          ? t("engines:turnOff.turnedOn", { name: provider.label })
          : reverted.length > 0
            ? t("engines:turnOff.doneReverted", { name: provider.label, list: processList(reverted) })
            : t("engines:turnOff.done", { name: provider.label }),
      });
    } catch (error) {
      setNotice({ kind: "error", text: `${t("engines:turnOff.failed")} ${describeEngineError(error)}` });
    } finally {
      setPending(null);
    }
  }

  /** Turning on sends nothing, so it is immediate; turning off sends processes back to local, so it asks. */
  function toggle(provider: EngineProvider, enabled: boolean) {
    if (!enabled && provider.used_by.length > 0) setTurningOff(provider);
    else void setEnabled(provider, enabled);
  }

  async function confirmDelete(provider: EngineProvider) {
    setDeleting(null);
    setPending(provider.id);
    setNotice(null);
    try {
      const { reverted_processes: reverted } = await deleteEngineProvider(provider.id);
      setLoad((previous) =>
        previous.status === "ready"
          ? { ...previous, providers: previous.providers.filter((item) => item.id !== provider.id) }
          : previous);
      setNotice({
        kind: "success",
        text: reverted.length > 0
          ? t("engines:remove.doneReverted", { name: provider.label, list: processList(reverted) })
          : t("engines:remove.done", { name: provider.label }),
      });
    } catch (error) {
      setNotice({ kind: "error", text: `${t("engines:remove.failed")} ${describeEngineError(error)}` });
    } finally {
      setPending(null);
      // The card that held focus is gone or still there; either way focus returns to a stable control.
      grid.current?.querySelector<HTMLElement>(".engines-add-card")?.focus();
    }
  }

  /** An account kind creates its provider (fixed name and address) and opens the sign-in. */
  async function connectNew(info: EngineKindInfo) {
    setPending(info.kind);
    setNotice(null);
    try {
      const created = await createEngineProvider({
        kind: info.kind,
        label: t(`engines:kinds.${info.kind}.label`),
        base_url: info.default_base_url ?? undefined,
        enabled: true,
      });
      providerChanged(created);
      setSigningIn(created);
    } catch (error) {
      setNotice({ kind: "error", text: `${t("engines:account.createFailed")} ${describeEngineError(error)}` });
    } finally {
      setPending(null);
    }
  }

  async function confirmDisconnect(provider: EngineProvider) {
    setDisconnecting(null);
    setPending(provider.id);
    setNotice(null);
    try {
      const done = await disconnectEngineAccount(provider.id);
      const { reverted_processes: reverted } = done;
      setAccounts((previous) => ({ ...previous, [provider.id]: { status: "ready", account: done } }));
      setLoad((previous) =>
        previous.status === "ready"
          ? {
              ...previous,
              providers: previous.providers.map((item) =>
                item.id === provider.id ? { ...item, used_by: item.used_by.filter((name) => !reverted.includes(name)) } : item,
              ),
            }
          : previous);
      setNotice({
        kind: "success",
        text: reverted.length > 0
          ? t("engines:account.disconnectedReverted", { name: provider.label, list: processList(reverted) })
          : t("engines:account.disconnected", { name: provider.label }),
      });
    } catch (error) {
      setNotice({ kind: "error", text: `${t("engines:account.disconnectFailed")} ${describeEngineError(error)}` });
    } finally {
      setPending(null);
    }
  }

  /** A kind chosen in the «Agregar» list: an account kind creates its provider and opens the sign-in;
   * any other opens the set-up dialog for that kind. */
  function chooseKind(kind: EngineProviderKind) {
    setAdding(false);
    const info = ready ? load.kinds.find((candidate) => candidate.kind === kind) : undefined;
    if (info?.auth === "account") void connectNew(info);
    else setDialog({ provider: null, kind });
  }

  const providers = ready ? [...load.providers].sort((a, b) => STATE_ORDER[a.status] - STATE_ORDER[b.status]) : [];
  // An account kind signs in once per computer, so it is offered only while it is not linked yet.
  const addable = ready
    ? load.kinds.filter((info) =>
        info.linkable && !(info.auth === "account" && load.providers.some((provider) => provider.kind === info.kind)))
    : [];

  return (
    <div className="settings-stack engines">
      <div className="engines-intro">
        <p className="settings-help">{t("engines:subtitle")}</p>
        <p className="settings-help">{t("engines:help")}</p>
      </div>

      <section className="engines-section" aria-labelledby="engines-providers-title">
        <div className="engines-section-head">
          <h3 id="engines-providers-title" className="engines-section-title">{t("engines:providersTitle")}</h3>
          <p className="settings-help">{t("engines:providersHelp")}</p>
        </div>
        <div role="status" className="settings-notice">{notice?.kind === "success" ? notice.text : null}</div>
        {notice?.kind === "error" && <p role="alert" className="ui-field-error settings-notice">{notice.text}</p>}

        {load.status === "loading" && (
          <div role="status" className="settings-loading">
            <p className="settings-help">{t("engines:loading")}</p>
            <div className="engines-grid" aria-hidden="true">
              <Skeleton width="100%" height="9rem" radius="md" />
              <Skeleton width="100%" height="9rem" radius="md" />
            </div>
          </div>
        )}
        {load.status === "error" && (
          <div className="settings-load-error">
            <p role="alert" className="ui-field-error">{t("engines:loadError")}</p>
            <Button variant="secondary" onClick={fetchAll}>{t("engines:retry")}</Button>
          </div>
        )}
        {load.status === "ready" && providers.length === 0 && <p className="engines-empty">{t("engines:empty")}</p>}
        {load.status === "ready" && (
          <ul ref={grid} className="engines-grid" aria-label={t("engines:listLabel")}>
            {providers.map((provider) => (
              <li key={provider.id} className="engines-grid-item">
                <ProviderCard
                  provider={provider}
                  kinds={load.kinds}
                  catalog={catalogs.entries[provider.id]}
                  busy={pending === provider.id}
                  account={accounts[provider.id]}
                  onToggle={(enabled) => toggle(provider, enabled)}
                  onEdit={() => setDialog({ provider, kind: provider.kind })}
                  onDelete={() => setDeleting(provider)}
                  onConnect={() => setSigningIn(provider)}
                  onDisconnect={() => setDisconnecting(provider)}
                />
              </li>
            ))}
            <li className="engines-grid-item">
              <AddProviderCard disabled={addable.some((info) => info.kind === pending)} onAdd={() => setAdding(true)} />
            </li>
          </ul>
        )}
      </section>

      {load.status === "ready" && (
        <ModelsCatalog
          providers={catalogs.targets}
          canTurnOn={providers.some((provider) => provider.status !== "active")}
          entries={catalogs.entries}
          refreshing={catalogs.refreshing}
          onRefresh={() => void catalogs.refreshAll()}
        />
      )}

      {adding && load.status === "ready" && (
        <AddProviderDialog kinds={addable} onChoose={chooseKind} onClose={() => setAdding(false)} />
      )}
      {dialog && load.status === "ready" && (
        <ProviderDialog
          provider={dialog.provider}
          kind={dialog.kind}
          kinds={load.kinds}
          linked={load.providers}
          onChanged={providerChanged}
          onClose={() => setDialog(null)}
        />
      )}
      {signingIn && (
        <AccountDialog
          provider={signingIn}
          onConnected={() => loadAccount(signingIn.id)}
          onClose={() => setSigningIn(null)}
        />
      )}
      {disconnecting && (
        <ConfirmDialog
          title={t("engines:account.disconnectDialog.title")}
          body={
            <>
              <p>{t("engines:account.disconnectDialog.body", { name: disconnecting.label })}</p>
              {disconnecting.used_by.length > 0 && (
                <p>{t("engines:account.disconnectDialog.reverts", { list: processList(disconnecting.used_by) })}</p>
              )}
            </>
          }
          confirmLabel={t("engines:account.disconnectDialog.confirm")}
          cancelLabel={t("engines:account.disconnectDialog.cancel")}
          onConfirm={() => void confirmDisconnect(disconnecting)}
          onCancel={() => setDisconnecting(null)}
        />
      )}
      {turningOff && (
        <ConfirmDialog
          title={t("engines:turnOff.title")}
          body={
            <>
              <p>{t("engines:turnOff.body", { name: turningOff.label })}</p>
              <p>{t("engines:turnOff.reverts", { list: processList(turningOff.used_by) })}</p>
            </>
          }
          confirmLabel={t("engines:turnOff.confirm")}
          cancelLabel={t("engines:turnOff.cancel")}
          onConfirm={() => void setEnabled(turningOff, false)}
          onCancel={() => setTurningOff(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={t("engines:remove.title")}
          body={
            <>
              <p>{t("engines:remove.body", { name: deleting.label })}</p>
              <p>{deleting.used_by.length > 0 ? t("engines:remove.reverts", { list: processList(deleting.used_by) }) : t("engines:remove.noReverts")}</p>
            </>
          }
          confirmLabel={t("engines:remove.confirm")}
          cancelLabel={t("engines:remove.cancel")}
          onConfirm={() => confirmDelete(deleting)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
