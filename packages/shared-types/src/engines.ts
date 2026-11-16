/**
 * Wire types of the engines API (`/api/v1/engines`): providers the user linked, the engine chosen for
 * each process, privacy notices and the connection test. Mirrors `backend/app/engines/schemas.py`.
 *
 * No type here can carry a provider key: the API returns `keySet` and `keyHint` (last four characters of
 * a key of 12 or more) only. `KeyIn` is the single request body that holds one, and it is write-only.
 * Field names are the API's own (snake_case); dates are ISO 8601 strings.
 */

/** The processes the user can route; `chat` is reserved and never offered. */
export type EngineProcess = "transcription" | "diarization" | "summary";

export type EngineProviderKind =
  | "openai"
  | "anthropic"
  | "gemini"
  | "openrouter"
  | "ollama"
  | "lmstudio"
  | "openai_compatible"
  | "chatgpt_plan"
  | "assemblyai"
  | "deepgram"
  | "groq";

/** Text shown in the portal comes from its copy module: `Activo`, `Sin clave`, `Apagado`, `Sin configurar`. */
export type EngineProviderStatus = "active" | "no_key" | "disabled" | "unconfigured";

/** Closed set of classified provider errors (design.md, "Manejo de Errores"). */
export type EngineErrorClass =
  | "provider_auth"
  | "provider_quota"
  | "provider_rate_limited"
  | "provider_timeout"
  | "provider_unavailable"
  | "provider_bad_request"
  | "provider_invalid_output"
  | "provider_context_exceeded"
  | "provider_unsupported"
  | "audio_too_large"
  | "no_word_timestamps"
  | "consent_missing"
  | "origin_mismatch"
  | "secret_unavailable";

/** Model the local engine uses when the user has not picked one. Any other local model is `local:<id>`. */
export const LOCAL_DEFAULT_MODEL = "local:default";

export interface EngineProvider {
  id: string;
  kind: EngineProviderKind;
  label: string;
  base_url: string | null;
  enabled: boolean;
  status: EngineProviderStatus;
  key_set: boolean;
  key_hint: string | null;
  key_set_at: string | null;
  used_by: EngineProcess[];
  created_at: string;
  updated_at: string;
}

/** Answer of PATCH: the provider plus the processes the edit sent back to the local engine. */
export interface EngineProviderUpdated extends EngineProvider {
  reverted_processes: EngineProcess[];
}

export interface EngineProviderCreate {
  kind: EngineProviderKind;
  /** 1 to 64 characters, unique per owner. */
  label: string;
  /** Defaults per kind; required for `openai_compatible`. https, or http on loopback for local servers. */
  base_url?: string;
  enabled?: boolean;
}

export interface EngineProviderUpdate {
  label?: string;
  /** A different origin is refused with `key_bound_to_origin` while a key is stored. */
  base_url?: string;
  enabled?: boolean;
}

/** Write-only request body of `PUT /providers/{id}/key`. 1 to 2048 printable ASCII characters, no spaces. */
export interface EngineKeyIn {
  key: string;
}

export interface EngineKeyState {
  key_set: boolean;
  key_hint: string | null;
  /** Processes sent back to the local engine because the key was removed. */
  reverted_processes: EngineProcess[];
}

/** Answer of `DELETE /providers/{id}`. */
export interface EngineProviderDeleted {
  reverted_processes: EngineProcess[];
}

/** Body of `POST /providers/{id}/test`; `capability` picks the transport to try. */
export interface EngineProbeIn {
  capability?: EngineProcess;
}

export interface EngineProbeResult {
  ok: boolean;
  latency_ms: number | null;
  error_class: EngineErrorClass | null;
  json_schema_ok: boolean | null;
}

export interface EngineModel {
  id: string;
  label: string | null;
}

export interface EngineModelList {
  models: EngineModel[];
  /** The model a new choice starts with ("Auto"); always one of `models`. */
  starter: string | null;
  from_cache: boolean;
  fetched_at: string | null;
  /** True when the list is empty or failed: let the user type the model name. */
  manual_entry: boolean;
  error_class: EngineErrorClass | null;
}

/** Body of `PUT /processes/{capability}`. `provider_id: null` selects a local model (`local:<id>`). */
export interface EngineProcessChoice {
  provider_id: string | null;
  model: string;
  local_fallback: boolean;
  /** Required when the provider has no current consent for this process; must equal the served version. */
  notice_version?: number;
}

export interface EngineProcessState {
  capability: EngineProcess;
  provider_id: string | null;
  provider_kind: EngineProviderKind | null;
  provider_label: string | null;
  model: string;
  local_fallback: boolean;
  /** False while the owner has never chosen: everything runs on the local engine. */
  configured: boolean;
  version: number;
  updated_at: string | null;
  /** Notice version the current consent covers, or null when the process is local. */
  notice_version: number | null;
}

export interface EnginePrivacyNotice {
  capability: EngineProcess;
  provider_id: string;
  provider_kind: EngineProviderKind;
  provider_name: string;
  /** Origin the data would be sent to. */
  address: string;
  notice_version: number;
  title: string;
  paragraphs: string[];
}

export interface EngineCapability {
  capability: EngineProcess;
  transport: string;
  /** ISO date of the documentation check; pairs without one are not listed. */
  verified_on: string;
}

export interface EngineKindInfo {
  kind: EngineProviderKind;
  default_base_url: string | null;
  key_required: boolean;
  /** False while the kind cannot be linked yet (the ChatGPT plan waits for a legal check). */
  linkable: boolean;
  /** Processes the kind can serve and that are verified; may be empty for a linkable kind. */
  capabilities: EngineCapability[];
}

export interface EngineCapabilities {
  notice_versions: Record<EngineProcess, number>;
  kinds: EngineKindInfo[];
}

export interface EngineHostState {
  id: string;
  port: number;
  state: string;
}

export interface EngineStatus {
  engines: EngineHostState[];
  secret_store: string | null;
}

// --- Local models (`/api/v1/engines/local`): hardware, catalog, installs and their jobs ---

/** What the local model recommendation reads from this computer (`GET /local/hardware`). */
export interface LocalHardware {
  arch: string;
  system: string;
  memory_gib: number;
  cores: number;
  /** Metal acceleration: Apple silicon on macOS. */
  metal: boolean;
  disk_free_bytes: number;
}

/** Catalog mark: `measured` by the team with real recordings, or an unmeasured `proposal`. */
export type LocalModelMark = "measured" | "proposal";

/** `auxiliary` supports a model of its process (voice detection); `managed_engine` ships with its engine. */
export type LocalModelKind = "model" | "auxiliary" | "managed_engine";

/** State of the files on disk; `managed` has no download and `installing` is an install in progress. */
export type LocalModelState =
  | "not_installed"
  | "installing"
  | "installed"
  | "unverified"
  | "corrupt"
  | "managed";

export interface LocalModel {
  id: string;
  process: EngineProcess;
  kind: LocalModelKind;
  engine: string;
  /** Download size in bytes; null for a managed engine. */
  size: number | null;
  min_ram_gib: number;
  requires: string[];
  status: LocalModelMark;
  /** The model a process runs when none is chosen (`local:default`). */
  default: boolean;
  /** Command that installs a managed engine. */
  managed_by: string | null;
  recommended: boolean;
  in_use_by: EngineProcess[];
  state: LocalModelState;
  installed_size: number | null;
  installed_at: string | null;
}

/** Why a model is (or is not) recommended: a copy key plus its parameters, never a sentence. */
export interface LocalRecommendation {
  process: EngineProcess;
  model_id: string | null;
  status: LocalModelMark | null;
  reason_key: string;
  reason_params: Record<string, string | number | boolean | null>;
  warnings: string[];
}

export interface LocalModelList {
  catalog_version: number;
  models: LocalModel[];
  recommendations: Partial<Record<EngineProcess, LocalRecommendation>>;
  /** Id of the install or verification running now, if any (one at a time). */
  active_job: string | null;
}

export type LocalJobState = "running" | "done" | "failed" | "cancelled";

export interface LocalJob {
  id: string;
  model_id: string;
  type: "install" | "verify";
  state: LocalJobState;
  bytes_done: number;
  bytes_total: number;
  /** Stable failure code, for example `hash_mismatch`. */
  error: string | null;
  /** `installed`, `verified` or `corrupt` once the job is done. */
  result: string | null;
}
