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
  | "provider_model_unavailable"
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

/**
 * Body of `POST /providers/{id}/test`; `capability` picks the transport to try. With `summary` the API tests the model
 * chosen for the summary (when it is this provider's) with the real summary schema.
 */
export interface EngineProbeIn {
  capability?: EngineProcess;
}

export interface EngineProbeResult {
  ok: boolean;
  latency_ms: number | null;
  error_class: EngineErrorClass | null;
  /** `false` only when the provider refused the summary schema (incompatible); `null` when it was not decided. */
  json_schema_ok: boolean | null;
  /** Why the schema check was not decided: `provider_timeout` means slow, `provider_model_unavailable` a model the account cannot use. */
  schema_error_class: EngineErrorClass | null;
  /** The model the schema check used. */
  schema_model: string | null;
}

/** Why the last ChatGPT sign-in did not end connected. */
export type EngineAccountError = "code_expired" | "access_denied" | "login_failed" | "session_expired";

/** The code to type at the verification address while a sign-in is in progress. */
export interface EngineAccountPending {
  user_code: string;
  verification_url: string;
  expires_at: string;
  interval_s: number;
  slow_down: boolean;
}

/** The ChatGPT account behind a provider of kind `chatgpt_plan`. Never carries a token. */
export interface EngineAccount {
  state: "disconnected" | "pending" | "connected";
  /** The account's email, or its id when the sign-in names no email. */
  account: string | null;
  plan: string | null;
  pending: EngineAccountPending | null;
  error: EngineAccountError | null;
  /** Processes sent back to the local engine by disconnecting. */
  reverted_processes: EngineProcess[];
}

export interface EngineModel {
  id: string;
  label: string | null;
  /** The processes this model can serve and Sauri offers for its provider's type. */
  serves: EngineProcess[];
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
  /** The processes the provider can serve, from the models it lists, within the pairs Sauri offers. */
  serves: EngineProcess[];
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
  /** ISO date of the check; null when the owner chose to offer the pair before it was verified live. */
  verified_on: string | null;
}

export interface EngineKindInfo {
  kind: EngineProviderKind;
  default_base_url: string | null;
  key_required: boolean;
  /** "account": no key; the person signs in with their account from the card (the ChatGPT plan). */
  auth: "key" | "account";
  /** False while the kind cannot be linked. */
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

/**
 * What this computer has of a model, apart from how it got there:
 * `installed` (hash-verified, or a managed engine that is present), `present_unverified` (the file is
 * there but was not verified, or differs from the catalog; see `reason`) or `available` (can be installed).
 */
export type LocalModelAvailability = "installed" | "available" | "present_unverified";

/** Where the file lives: the models directory, the engine's legacy location (never moved) or a managed engine's environment. */
export type LocalModelLocation = "models_dir" | "legacy" | "managed";

/** Why a present file was not adopted as installed. */
export type LocalModelReason = "size_mismatch" | "hash_mismatch";

/** What installing a model that is not installed still needs. */
export interface LocalModelInstallNeeds {
  method: "download" | "managed_command";
  /** Command that installs a managed engine (`method: "managed_command"`). */
  managed_by: string | null;
  download_bytes: number | null;
  /** Free space an install needs (download plus headroom). */
  disk_required_bytes: number | null;
  fits_on_disk: boolean | null;
}

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
  /** Fields below come with adoption of models installed by hand; always present from the API. */
  availability?: LocalModelAvailability;
  /** True for the one model serving its process now (the chosen one, else the installed catalog default). Never set on `auxiliary` files. */
  active?: boolean;
  /** True when removal is blocked because a process runs it (chosen, default, or an auxiliary file). */
  in_use?: boolean;
  /** Where the file is; null when nothing is present. A `legacy` file is never removed by Sauri. */
  location?: LocalModelLocation | null;
  /** Why a present file was not adopted; null otherwise. */
  reason?: LocalModelReason | null;
  /** True while an adoption run is still going to check this file. */
  verifying?: boolean;
  /** `hash` for catalog files; `presence` for a managed engine (found, never hashed). */
  verified_by?: "hash" | "presence";
  /** What is needed to install it; null when already installed. */
  install?: LocalModelInstallNeeds | null;
}

/** How the last adoption run judged each present file: `adopted`, `present_unverified`, `changed`, `unreadable` or `write_failed`. */
export interface LocalAdoption {
  job_id: string;
  outcomes: Record<string, string>;
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
  /** Id of the model serving each process now, or null when none is installed. */
  active?: Partial<Record<EngineProcess, string | null>>;
  /** Result of the last adoption run since the host started; null before the first one. */
  adoption?: LocalAdoption | null;
}

export type LocalJobType = "install" | "verify" | "adopt";

export type LocalJobState = "running" | "done" | "failed" | "cancelled";

export interface LocalJob {
  id: string;
  model_id: string;
  type: LocalJobType;
  state: LocalJobState;
  bytes_done: number;
  bytes_total: number;
  /** Stable failure code, for example `hash_mismatch`. */
  error: string | null;
  /** `installed`, `verified` or `corrupt` once the job is done; `adopted` or `nothing_adopted` for adoption. */
  result: string | null;
  /** Adoption jobs only: the outcome per model id so far. */
  outcomes?: Record<string, string>;
}
