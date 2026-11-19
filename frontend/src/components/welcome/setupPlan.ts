import type { EngineProcess, EngineProcessState, LocalModel, LocalModelList } from "@sauri/shared-types";
import { choiceKeyOf } from "../settings/LocalModelCard";
import { availabilityOf } from "../settings/engineLabels";

/** One file the first run still has to put on this Mac. */
export interface PlanItem {
  id: string;
  process: EngineProcess;
  /** What the download weighs, for the overall progress and the estimate. */
  bytes: number;
}

/** What to do next with a planned entry, from its current state in the listing. */
export type PlanAction = "install" | "verify" | "done";

/**
 * The host's setup plan (the recommended model of each process and what it needs to run, in order), minus what is
 * already installed. The plan itself comes from host-engine's recommendation; nothing is chosen here.
 */
export function pendingItems(list: LocalModelList): PlanItem[] {
  const planned = list.setup_plan ?? Object.values(list.recommendations).flatMap((rec) => (rec?.model_id ? [rec.model_id] : []));
  return planned.flatMap((id) => {
    const model = list.models.find((entry) => entry.id === id);
    if (!model || actionFor(model) === "done") return [];
    return [{ id, process: model.process, bytes: model.size ?? 0 }];
  });
}

/**
 * Install what is missing or damaged; check a file that is present but not yet checked (the host refuses to
 * download over it). A managed engine has nothing to download: it comes with the app.
 */
export function actionFor(model: LocalModel): PlanAction {
  if (model.kind === "managed_engine" || availabilityOf(model) === "installed") return "done";
  if (availabilityOf(model) === "present_unverified" && model.state === "unverified" && !model.reason && model.kind !== "component") {
    return "verify";
  }
  return "install";
}

/**
 * The choice each local process must save so it runs its recommended model: `local:default` when that is what the
 * default resolves to (Parakeet, the 9B), `local:<id>` otherwise (the 4B on an 8 GB Mac). Processes served by an
 * external provider, or already on the right choice, are left alone.
 */
export function recommendedChoices(list: LocalModelList, processes: readonly EngineProcessState[]): EngineProcessState[] {
  return processes.flatMap((state) => {
    if (state.provider_id !== null) return [];
    const id = list.recommendations[state.capability]?.model_id;
    const model = id ? list.models.find((entry) => entry.id === id) : undefined;
    if (!model) return [];
    const key = choiceKeyOf(model, list.models);
    return key === state.model ? [] : [{ ...state, model: key }];
  });
}
