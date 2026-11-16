import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EngineErrorClass, EngineKindInfo, EngineModel, EngineModelList, EngineProcess, EngineProvider } from "@sauri/shared-types";
import { listEngineModels } from "../../api";

/** What one provider answered when asked for its models, across every process it can serve. */
export type CatalogEntry =
  | { status: "loading" }
  | { status: "ready"; models: EngineModel[]; fetchedAt: string | null; serves: EngineProcess[] }
  | { status: "failed"; cause: EngineErrorClass };

/** Providers whose lists are requested: switched on, with their key where one is needed, and able to
 * serve at least one process. A provider without a key is never asked, so nothing leaves without one.
 * One that signs in with an account is asked only once that account is connected (`connectedAccounts`). */
export function catalogProviders(
  providers: EngineProvider[],
  kinds: EngineKindInfo[],
  connectedAccounts: ReadonlySet<string> = new Set(),
): EngineProvider[] {
  return providers.filter((provider) => {
    const info = kinds.find((candidate) => candidate.kind === provider.kind);
    if (provider.status !== "active" || (info?.capabilities.length ?? 0) === 0) return false;
    return info?.auth !== "account" || connectedAccounts.has(provider.id);
  });
}

const PROCESS_ORDER: EngineProcess[] = ["transcription", "diarization", "summary"];

function merge(lists: PromiseSettledResult<EngineModelList>[]): CatalogEntry {
  const answered = lists.flatMap((result) => (result.status === "fulfilled" && !result.value.error_class ? [result.value] : []));
  if (answered.length === 0) {
    const cause = lists.flatMap((result) => (result.status === "fulfilled" ? [result.value.error_class] : []))[0];
    return { status: "failed", cause: cause ?? "provider_unavailable" };
  }
  const seen = new Map<string, EngineModel>();
  for (const list of answered) for (const model of list.models) if (!seen.has(model.id)) seen.set(model.id, model);
  const dates = answered.flatMap((list) => (list.fetched_at ? [list.fetched_at] : [])).sort();
  const serves = PROCESS_ORDER.filter((process) => answered.some((list) => list.serves.includes(process)));
  return { status: "ready", models: Array.from(seen.values()), fetchedAt: dates[dates.length - 1] ?? null, serves };
}

/** Model lists of the given providers, asked once each (the API keeps them a day) and again on `refreshAll`. */
export function useModelCatalogs(
  providers: EngineProvider[],
  kinds: EngineKindInfo[],
  enabled: boolean,
  connectedAccounts: ReadonlySet<string> = new Set(),
) {
  const [entries, setEntries] = useState<Record<string, CatalogEntry>>({});
  const [refreshing, setRefreshing] = useState(false);
  const asked = useRef(new Set<string>());
  const generation = useRef(0);

  const targets = useMemo(() => catalogProviders(providers, kinds, connectedAccounts), [providers, kinds, connectedAccounts]);
  const signature = targets.map((provider) => provider.id).join("|");

  const request = useCallback(
    async (provider: EngineProvider, refresh: boolean, run: number) => {
      const capabilities = kinds.find((info) => info.kind === provider.kind)?.capabilities ?? [];
      const results = await Promise.allSettled(
        capabilities.map((entry) => listEngineModels(provider.id, entry.capability, refresh)),
      );
      if (run === generation.current) setEntries((previous) => ({ ...previous, [provider.id]: merge(results) }));
    },
    [kinds],
  );

  useEffect(() => {
    if (!enabled) return;
    const run = generation.current;
    // A provider that stopped being a target (its account was disconnected) is asked again when it returns.
    const current = new Set(targets.map((provider) => provider.id));
    const dropped = Array.from(asked.current).filter((id) => !current.has(id));
    dropped.forEach((id) => asked.current.delete(id));
    if (dropped.length > 0) {
      setEntries((previous) => Object.fromEntries(Object.entries(previous).filter(([id]) => !dropped.includes(id))));
    }
    const fresh = targets.filter((provider) => !asked.current.has(provider.id));
    fresh.forEach((provider) => asked.current.add(provider.id));
    if (fresh.length === 0) return;
    setEntries((previous) => ({
      ...previous,
      ...Object.fromEntries(fresh.map((provider) => [provider.id, { status: "loading" } as const])),
    }));
    fresh.forEach((provider) => void request(provider, false, run));
  }, [signature, enabled, request]);

  const refreshAll = useCallback(async () => {
    const run = ++generation.current;
    setRefreshing(true);
    await Promise.all(targets.map((provider) => request(provider, true, run)));
    if (run === generation.current) setRefreshing(false);
  }, [targets, request]);

  return { entries, refreshing, refreshAll, targets };
}
