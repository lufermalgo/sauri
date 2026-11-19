/** Test fixtures: the desktop app's model listing as host-engine sends it, for an 8, 16 or 24 GB Mac. */
import type { EngineProcess, EngineProcessState, LocalModel, LocalModelList, LocalRecommendation } from "@sauri/shared-types";

function entry(id: string, process: EngineProcess, size: number | null, extra: Partial<LocalModel> = {}): LocalModel {
  return {
    id, process, kind: "model", engine: "synthetic", size, min_ram_gib: 0, requires: [], status: "measured",
    default: false, managed_by: null, recommended: false, in_use_by: [], state: "not_installed", installed_size: null,
    installed_at: null, availability: "available", active: false, in_use: false, location: null, reason: null,
    verifying: false, needs_ready: true,
    install: { method: "download", managed_by: null, download_bytes: size, disk_required_bytes: size, fits_on_disk: true },
    ...extra,
  };
}

export const PARAKEET = "parakeet-tdt-0.6b-v3-ultra-coreml";
export const WHISPER = "whisper-large-v3-turbo-q5_0";
export const VAD = "silero-vad-v6.2.0";
export const SMALL_LLM = "qwen3.5-4b-q4_k_m";
export const LARGE_LLM = "qwen3.5-9b-q4_k_m";
export const DIAR = "diar-runtime";

/** What host-engine's `setup_plan` answers for each memory size (see `recommend.setup_plan` and its tests). */
export function desktopListing(memoryGib: 8 | 16 | 24): LocalModelList {
  const summary = memoryGib >= 16 ? LARGE_LLM : SMALL_LLM;
  const models = [
    entry(WHISPER, "transcription", 574_041_195, { default: true }),
    entry(PARAKEET, "transcription", 632_314_500, { preferred: true, needs: "fluidaudio-cli" }),
    entry("fluidaudio-cli", "transcription", null, {
      kind: "managed_engine", state: "managed", availability: "installed", location: "managed", install: null,
      managed_by: "scripts/engines/install-parakeet-engine.sh",
    }),
    entry(VAD, "transcription", 885_098, { kind: "auxiliary", default: true }),
    entry(LARGE_LLM, "summary", 5_680_522_464, { default: true, min_ram_gib: 16 }),
    entry(SMALL_LLM, "summary", 2_740_937_888, { min_ram_gib: 8 }),
    entry(DIAR, "diarization", 251_532_143, { kind: "component", default: true }),
  ].map((model) => ({ ...model, recommended: [PARAKEET, summary, DIAR].includes(model.id) }));
  const rec = (process: EngineProcess, model_id: string): LocalRecommendation => ({
    process, model_id, status: "measured", reason_key: "fits", reason_params: { memory_gib: memoryGib }, warnings: [],
  });
  return {
    catalog_version: 1,
    models,
    recommendations: { transcription: rec("transcription", PARAKEET), summary: rec("summary", summary), diarization: rec("diarization", DIAR) },
    setup_plan: [PARAKEET, WHISPER, VAD, summary, DIAR],
    active_job: null,
    active: {},
    adoption: null,
  };
}

/** A listing where the given ids are installed and verified. */
export function withInstalled(list: LocalModelList, ids: readonly string[]): LocalModelList {
  return {
    ...list,
    models: list.models.map((model) =>
      ids.includes(model.id)
        ? { ...model, state: "installed", availability: "installed", installed_size: model.size, location: "models_dir", install: null }
        : model),
  };
}

export function localProcess(capability: EngineProcess, model = "local:default"): EngineProcessState {
  return {
    capability, provider_id: null, provider_kind: null, provider_label: null, model, local_fallback: true,
    configured: false, version: 0, updated_at: null, notice_version: null,
  };
}
