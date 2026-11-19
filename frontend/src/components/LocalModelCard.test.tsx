// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { EngineProcess, LocalAdoption, LocalJob, LocalModel, LocalRecommendation } from "@sauri/shared-types";
import { detectLocalSession } from "../api";
import { LocalModelCard } from "./settings/LocalModelCard";
import type { ExternalChoice, LocalSelection } from "./settings/LocalModelCard";
import { setLanguage, t } from "../i18n";

const POLL_MS = 10;
const JOB_ID = "a".repeat(32);

/** An installed, hash-verified model in the models directory; tests override what differs. */
function model(overrides: Partial<LocalModel> & Pick<LocalModel, "id">): LocalModel {
  return {
    process: "transcription", kind: "model", engine: "whisper.cpp", size: 574_041_195, min_ram_gib: 8, requires: ["metal"],
    status: "measured", default: false, managed_by: null, recommended: false, in_use_by: [], state: "installed",
    installed_size: 574_041_195, installed_at: null,
    availability: "installed", active: false, in_use: false, location: "models_dir", reason: null, verifying: false,
    verified_by: "hash", install: null,
    ...overrides,
  };
}

/** A model that is not on the computer yet. */
function available(overrides: Partial<LocalModel> & Pick<LocalModel, "id">): LocalModel {
  return model({
    state: "not_installed", installed_size: null, availability: "available", location: null, verified_by: undefined,
    install: { method: "download", managed_by: null, download_bytes: overrides.size ?? 574_041_195, disk_required_bytes: 688_849_434, fits_on_disk: true },
    ...overrides,
  });
}

const PARAKEET_ID = "parakeet-tdt-0.6b-v3-ultra-coreml";
const TURBO = model({ id: "whisper-turbo", default: true, recommended: true, active: true, in_use: true, in_use_by: ["transcription"] });
const SMALL = available({ id: "whisper-small", size: 190_085_487, status: "proposal", min_ram_gib: 4, requires: [] });
const SMALL_INSTALLED = model({ id: "whisper-small", size: 190_085_487, status: "proposal", min_ram_gib: 4, requires: [], installed_size: 190_085_487 });
const TINY = available({ id: "whisper-tiny", size: 75_000_000, min_ram_gib: 2, requires: [] });
const HUGE = available({ id: "whisper-huge", size: 3_000_000_000, min_ram_gib: 64 });
const PARAKEET = available({ id: PARAKEET_ID, engine: "fluidaudio", size: 632_314_500, preferred: true, needs: "fluidaudio-cli" });
const VAD = model({ id: "silero-vad", kind: "auxiliary", size: 2_000_000, installed_size: 2_000_000, in_use: true });
const FLUIDAUDIO = model({
  id: "fluidaudio-cli", kind: "managed_engine", engine: "fluidaudio", size: null, installed_size: null, state: "managed",
  location: "managed", verified_by: "presence", managed_by: "scripts/engines/install-parakeet-engine.sh",
});
const SENKO = model({
  id: "senko-coreml", process: "diarization", kind: "managed_engine", engine: "senko", size: null, installed_size: null,
  state: "managed", location: "managed", verified_by: "presence", managed_by: "scripts/engines/install-diar-engine.sh",
  active: true, in_use: true, in_use_by: ["diarization"],
});
const RUNTIME = available({
  id: "diar-runtime", process: "diarization", kind: "component", engine: "senko", size: 251_532_143, min_ram_gib: 0, requires: [],
  default: true, recommended: true, version: "0.1.0",
  install: { method: "download", managed_by: null, download_bytes: 251_532_143, disk_required_bytes: 301_838_572, fits_on_disk: true, source_available: true },
});
const QWEN_9B = model({ id: "qwen-9b", process: "summary", engine: "llama.cpp", size: 5_680_522_464, installed_size: 5_680_522_464, min_ram_gib: 16, default: true, active: true, in_use: true, in_use_by: ["summary"] });
const QWEN_4B = available({ id: "qwen-4b", process: "summary", engine: "llama.cpp", size: 2_740_937_888, min_ram_gib: 8 });

const RESOLVED = {
  repo: "someone/tiny-gguf",
  revision: "0123456789abcdef0123456789abcdef01234567",
  license: "apache-2.0",
  files: [{ path: "tiny-q4_k_m.gguf", size: 1_200_000_000, sha256: "f".repeat(64) }],
};

interface Call { method: string; path: string; body: unknown }

interface Options {
  engineState?: string;
  hostDown?: boolean;
  recommendations?: Partial<Record<EngineProcess, LocalRecommendation>>;
  adoption?: LocalAdoption | null;
}

const defaultRecommendation = (process: EngineProcess, modelId: string | null): LocalRecommendation => ({
  process, model_id: modelId, status: "measured", reason_key: "fits", reason_params: { memory_gib: 24, min_ram_gib: 8 }, warnings: [],
});

function fakeBackend(models: LocalModel[], options: Options = {}) {
  const catalog = models.map((entry) => ({ ...entry }));
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
  const job = { current: null as LocalJob | null };
  /** Answers of the job route, in order; the last one repeats. */
  const jobAnswers: Partial<LocalJob>[] = [];
  let lookups = 0;
  const refusals = new Map<string, Response>();
  const resolve = { answer: json(RESOLVED) };

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/engines", "");
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, path, body });
    const refused = refusals.get(`${method} ${path}`);
    if (refused) return refused.clone();
    if (options.hostDown && path.startsWith("/local")) return json({ detail: "host_unavailable" }, 503);

    if (path === "/local/hardware") return json({ arch: "arm64", system: "Darwin", memory_gib: 24, cores: 10, metal: true, macos_major: 15, disk_free_bytes: 120e9 });
    if (path === "/status") return json({ engines: [{ id: "asr", port: 8001, state: options.engineState ?? "running" }], secret_store: null });
    if (path === "/local/models") {
      return json({
        catalog_version: 1, models: catalog, active_job: job.current?.state === "running" ? job.current.id : null,
        active: Object.fromEntries(catalog.filter((entry) => entry.active).map((entry) => [entry.process, entry.id])),
        adoption: options.adoption ?? null,
        recommendations: options.recommendations ?? {
          transcription: defaultRecommendation("transcription", "whisper-turbo"),
          summary: defaultRecommendation("summary", "qwen-9b"),
          diarization: defaultRecommendation("diarization", "diar-runtime"),
        },
      });
    }
    if (path === "/local/adopt" && method === "POST") {
      job.current = { id: "b".repeat(32), model_id: "", type: "adopt", state: "running", bytes_done: 0, bytes_total: 0, error: null, result: null };
      return json(job.current, 202);
    }
    if (path === "/local/custom/resolve" && method === "POST") return resolve.answer.clone();
    if (path === "/local/custom/install" && method === "POST") {
      job.current = { id: JOB_ID, model_id: "custom-0123456789abcdef", type: "install", state: "running", bytes_done: 0, bytes_total: 1000, error: null, result: null };
      catalog.push(available({
        id: "custom-0123456789abcdef", process: body.process, engine: "llama.cpp", size: 1_200_000_000, min_ram_gib: 0, requires: [],
        custom: true, origin: { repo: body.repo, revision: body.revision, file: body.file },
      } as Partial<LocalModel> & { id: string }));
      return json(job.current, 202);
    }
    const start = /^\/local\/models\/([^/]+)\/(install|verify)$/.exec(path);
    if (start && method === "POST") {
      job.current = { id: JOB_ID, model_id: start[1], type: start[2] as "install" | "verify", state: "running", bytes_done: 0, bytes_total: 1000, error: null, result: null };
      return json(job.current, 202);
    }
    if (/^\/local\/jobs\/[0-9a-f]{32}\/cancel$/.test(path) && method === "POST") {
      job.current = { ...job.current!, state: "cancelled" };
      return json(job.current);
    }
    if (/^\/local\/jobs\/[0-9a-f]{32}$/.test(path)) {
      const answer = jobAnswers[Math.min(lookups, jobAnswers.length - 1)] ?? {};
      lookups += 1;
      job.current = { ...job.current!, ...answer };
      const target = catalog.find((entry) => entry.id === job.current!.model_id);
      if (target && job.current.state === "done" && job.current.type === "install") {
        Object.assign(target, { state: "installed", availability: "installed", installed_size: target.size, install: null, location: "models_dir", verified_by: "hash" });
      }
      if (target && job.current.state === "done" && job.current.type === "verify" && job.current.result === "verified") {
        Object.assign(target, { state: "installed", availability: "installed", reason: null, verified_by: "hash" });
      }
      return json(job.current);
    }
    const removal = /^\/local\/models\/([^/]+)$/.exec(path);
    if (removal && method === "DELETE") {
      const target = catalog.find((entry) => entry.id === removal[1])!;
      Object.assign(target, { state: "not_installed", availability: "available", installed_size: null, location: null });
      return new Response(null, { status: 204 });
    }
    return json({ detail: "unexpected" }, 404);
  });
  return { handler, calls, jobAnswers, refusals, catalog, job, json, resolve };
}

let backend: ReturnType<typeof fakeBackend>;

const LOCAL_SELECTION: LocalSelection = { external: false, key: "local:default" };

interface Props {
  process?: EngineProcess;
  selection?: LocalSelection;
  external?: Partial<ExternalChoice>;
  onModelsChange?: (models: LocalModel[]) => void;
  onUse?: (key: string) => void;
  choosing?: boolean;
}

function cardProps(props: Props) {
  return {
    process: props.process ?? "transcription",
    selection: props.selection ?? LOCAL_SELECTION,
    onModelsChange: props.onModelsChange,
    onUse: props.onUse ?? vi.fn(),
    choosing: props.choosing,
    external: { current: null, hasProviders: true, onChoose: vi.fn(), onSetup: vi.fn(), ...props.external },
    pollIntervalMs: POLL_MS,
  };
}

/** Renders the card and waits until the catalog is on screen. */
async function renderCard(models: LocalModel[], options: Options = {}, props: Props = {}) {
  backend = fakeBackend(models, options);
  vi.stubGlobal("fetch", backend.handler);
  const view = render(<LocalModelCard {...cardProps(props)} />);
  await screen.findByRole("button", { name: t("engines:local.cardMenu") });
  return view;
}

const row = (name: string) => screen.getByRole("listitem", { name });
const shownRows = () => within(screen.getByRole("list", { name: t("engines:local.modelsTitle") })).getAllByRole("listitem").map((item) => item.getAttribute("aria-labelledby"));
const tagsOf = (name: string) => Array.from(row(name).querySelectorAll(".ui-status-badge")).map((badge) => badge.textContent);
const jobLooks = () => backend.calls.filter((call) => call.path.startsWith("/local/jobs/") && call.method === "GET").length;
const catalogReads = () => backend.calls.filter((call) => call.path === "/local/models" && call.method === "GET").length;
const menuItem = (name: string | RegExp) => screen.getByRole("menuitem", { name });

function openRowMenu(name: string) {
  fireEvent.click(within(row(name)).getByRole("button", { name: t("engines:local.moreLabel", { name }) }));
}

/** Opens the row menu and returns the names of its items, in order. */
function rowMenuItems(name: string): string[] {
  openRowMenu(name);
  return within(screen.getByRole("menu")).getAllByRole("menuitem").map((item) => item.textContent ?? "");
}

function closeMenu() {
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
}

/** Opens «Detalles» of a row and returns the dialog. */
function openDetails(name: string): HTMLElement {
  openRowMenu(name);
  fireEvent.click(menuItem(t("engines:local.details.open")));
  return screen.getByRole("dialog", { name: t("engines:local.details.title", { name }) });
}

/** Opens «Agregar» (the header button, or the empty state's) and returns the dialog. */
function openAdd(process: EngineProcess = "transcription"): HTMLElement {
  const header = screen.queryByRole("button", { name: t(`engines:local.add.label.${process}`) });
  fireEvent.click(header ?? screen.getByRole("button", { name: t("engines:local.empty.action") }));
  return screen.getByRole("dialog", { name: t(`engines:local.add.title.${process}`) });
}

const suggestionNames = (dialog: HTMLElement) =>
  within(within(dialog).getByRole("region", { name: t("engines:local.add.suggested") })).getAllByRole("listitem").map((item) => item.getAttribute("aria-labelledby"));

/** From «Agregar», opens «Otro modelo», types `source` and searches. */
function searchCustom(dialog: HTMLElement, source: string) {
  fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.add.other") }));
  fireEvent.change(within(dialog).getByLabelText(t("engines:local.custom.label")), { target: { value: source } });
  fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.custom.search") }));
}

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => (key === "sauri_token" ? "synthetic-token" : null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("only what this computer has", () => {
  it("lists only the installed models of the process, with their size on disk and state", async () => {
    const summary = model({ id: "qwen-9b", process: "summary", engine: "llama.cpp" });
    await renderCard([TURBO, SMALL, PARAKEET, summary, SENKO]);
    expect(shownRows()).toEqual(["engines-model-transcription-whisper-turbo"]);
    expect(tagsOf("whisper-turbo")).toEqual([t("engines:local.tags.active")]);
    expect(within(row("whisper-turbo")).getByText("574 MB")).toBeInTheDocument();
    expect(within(row("whisper-turbo")).getByText(t("engines:local.short.whisper"))).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "whisper-small" })).toBeNull();
    expect(screen.queryByText(t("engines:local.states.available"))).toBeNull();
  });

  it("keeps the voice detector and Parakeet's engine as one supporting line each, never as rows", async () => {
    const parakeet = model({ ...PARAKEET, state: "installed", availability: "installed", installed_size: 632_314_500, install: null, needs_ready: true });
    await renderCard([TURBO, parakeet, FLUIDAUDIO, VAD]);
    expect(shownRows()).toEqual(["engines-model-transcription-whisper-turbo", `engines-model-transcription-${PARAKEET_ID}`]);
    expect(screen.getByText(t("engines:local.auxiliaryLine", { name: "silero-vad", state: t("engines:local.states.installed") }))).toBeInTheDocument();
    const engine = t("engines:local.managedTitle.transcription");
    expect(screen.getByText(t("engines:local.engineLine", { name: engine, state: t("engines:local.states.installed") }))).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: engine })).toBeNull();
    expect(screen.queryByRole("listitem", { name: "silero-vad" })).toBeNull();
  });

  it("offers «Usar este» on an installed model that is not active, tagged «Instalado», with check and remove in its menu", async () => {
    const onUse = vi.fn();
    await renderCard([TURBO, SMALL_INSTALLED], {}, { onUse });
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.installed")]);
    expect(within(row("whisper-small")).getByText(t("engines:local.short.whisperLight"))).toBeInTheDocument();
    expect(rowMenuItems("whisper-small")).toEqual([t("engines:local.verify"), t("engines:local.remove"), t("engines:local.details.open")]);
    closeMenu();
    fireEvent.click(within(row("whisper-small")).getByRole("button", { name: t("engines:local.useLabel", { name: "whisper-small" }) }));
    expect(onUse).toHaveBeenCalledWith("local:whisper-small");
    expect(within(row("whisper-turbo")).queryByRole("button", { name: t("engines:local.useLabel", { name: "whisper-turbo" }) })).toBeNull();
  });

  it("chooses the catalog default through local:default", async () => {
    const onUse = vi.fn();
    await renderCard([{ ...TURBO, active: false, in_use: false, in_use_by: [] }, SMALL_INSTALLED], {}, { onUse, selection: { external: false, key: "local:whisper-small" } });
    fireEvent.click(screen.getByRole("button", { name: t("engines:local.useLabel", { name: "whisper-turbo" }) }));
    expect(onUse).toHaveBeenCalledWith("local:default");
  });

  it("disables «Usar este» while a choice is being saved", async () => {
    await renderCard([TURBO, SMALL_INSTALLED], {}, { choosing: true });
    expect(screen.getByRole("button", { name: t("engines:local.useLabel", { name: "whisper-small" }) })).toBeDisabled();
  });

  it("shows no model as active while an external provider serves the process, and offers the local ones", async () => {
    await renderCard([TURBO], {}, { selection: { external: true, key: "gpt-a" }, external: { current: "Work OpenAI, gpt-a" } });
    expect(tagsOf("whisper-turbo")).toEqual([t("engines:local.tags.installed")]);
    expect(screen.getByRole("button", { name: t("engines:local.useLabel", { name: "whisper-turbo" }) })).toBeEnabled();
    const group = screen.getByRole("region", { name: t("engines:local.external.title") });
    expect(within(group).getByText("Work OpenAI, gpt-a")).toBeInTheDocument();
  });

  it("shows a file that is there but not checked as «Por verificar», with the reason in plain words and «Verificar»", async () => {
    const odd = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", reason: "size_mismatch", verified_by: undefined, size: 190_085_487 });
    await renderCard([TURBO, odd]);
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.unverified")]);
    expect(within(row("whisper-small")).getByText(t("engines:local.unverifiedReason.size_mismatch"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("engines:local.useLabel", { name: "whisper-small" }) })).toBeNull();
    expect(rowMenuItems("whisper-small")).toEqual([t("engines:local.verify"), t("engines:local.remove"), t("engines:local.details.open")]);
  });

  it("says «Verificando…» while a file is being checked", async () => {
    const checking = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", verifying: true, verified_by: undefined });
    await renderCard([TURBO, checking]);
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.verifying")]);
    expect(rowMenuItems("whisper-small")).toEqual([t("engines:local.details.open")]);
  });

  it("lists the active model first, then the installed ones, then the files that need attention", async () => {
    const base = model({ id: "whisper-base", size: 142_000_000 });
    const odd = model({ id: "whisper-odd", state: "unverified", availability: "present_unverified", verified_by: undefined });
    await renderCard([SMALL, odd, base, TURBO]);
    expect(shownRows()).toEqual([
      "engines-model-transcription-whisper-turbo",
      "engines-model-transcription-whisper-base",
      "engines-model-transcription-whisper-odd",
    ]);
  });

  it("follows the saved choice: a pinned model goes first and is the active one", async () => {
    await renderCard([{ ...TURBO, active: false }, SMALL_INSTALLED], {}, { selection: { external: false, key: "local:whisper-small" } });
    expect(shownRows()[0]).toBe("engines-model-transcription-whisper-small");
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.active")]);
    expect(tagsOf("whisper-turbo")).toEqual([t("engines:local.tags.installed")]);
  });

  it("shows the speaker engine as the model of the speakers process, under its plain name", async () => {
    await renderCard([SENKO], {}, { process: "diarization" });
    const name = t("engines:local.managedTitle.diarization");
    expect(tagsOf(name)).toEqual([t("engines:local.tags.active")]);
    expect(rowMenuItems(name)).toEqual([t("engines:local.details.open")]);
    fireEvent.click(menuItem(t("engines:local.details.open")));
    expect(within(screen.getByRole("dialog")).getByText(t("engines:local.managedInstalled"))).toBeInTheDocument();
  });

  it("shows a model of the person's own with «Personalizado» and where it came from", async () => {
    const own = model({
      id: "custom-0123456789abcdef", process: "summary", engine: "llama.cpp", size: 1_200_000_000, installed_size: 1_200_000_000, min_ram_gib: 0,
      status: "proposal", custom: true, origin: { repo: "someone/tiny-gguf", revision: RESOLVED.revision, file: "models/tiny-q4_k_m.gguf" },
    });
    await renderCard([QWEN_9B, own], {}, { process: "summary" });
    expect(tagsOf("tiny-q4_k_m.gguf")).toEqual([t("engines:local.tags.installed"), t("engines:local.tags.custom")]);
    expect(within(row("tiny-q4_k_m.gguf")).getByText(t("engines:local.custom.origin", { repo: "someone/tiny-gguf", revision: "0123456" }))).toBeInTheDocument();
    const details = openDetails("tiny-q4_k_m.gguf");
    expect(within(details).getByText("custom-0123456789abcdef")).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.custom.originDetail", { repo: "someone/tiny-gguf", revision: RESOLVED.revision }))).toBeInTheDocument();
    expect(within(details).queryByText(t("engines:local.details.rating"))).toBeNull();
  });

  it("keeps the recommendation, the license and the computer under «Detalles»", async () => {
    const parakeet = model({
      ...PARAKEET, state: "installed", availability: "installed", installed_size: 632_314_500, install: null, needs_ready: true,
      license: "CC-BY-4.0", attribution: "Parakeet-TDT-0.6B-v3 by NVIDIA (CC-BY-4.0)", recommended: true, active: true, in_use: true, in_use_by: ["transcription"],
    });
    await renderCard([parakeet, FLUIDAUDIO], { recommendations: { transcription: defaultRecommendation("transcription", PARAKEET_ID) } });
    const details = openDetails(PARAKEET_ID);
    expect(within(details).getByText(t("engines:local.recommended"))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.reasons.fitsMinimum", { memory: "24 GB", minimum: 8 }))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.license", { license: "CC BY 4.0", attribution: "Parakeet-TDT-0.6B-v3 by NVIDIA (CC-BY-4.0)" }))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.metalYes"))).toBeInTheDocument();
  });

  it("does not call Parakeet active, nor offer it, while its engine is missing", async () => {
    const parakeet = model({ ...PARAKEET, state: "installed", availability: "installed", install: null, needs_ready: false });
    const engine = model({ ...FLUIDAUDIO, state: "not_installed", availability: "available", location: null, verified_by: undefined });
    await renderCard([parakeet, TURBO, engine]);
    expect(tagsOf(PARAKEET_ID)).toEqual([t("engines:local.tags.installed")]);
    expect(within(row(PARAKEET_ID)).getByText(t("engines:local.short.needsEngine"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("engines:local.useLabel", { name: PARAKEET_ID }) })).toBeNull();
  });

  it("hands the catalog to the screen so installed models can be chosen", async () => {
    const onModelsChange = vi.fn();
    await renderCard([TURBO, SMALL_INSTALLED], {}, { onModelsChange });
    expect(onModelsChange.mock.calls[0][0].map((entry: LocalModel) => entry.id)).toEqual(["whisper-turbo", "whisper-small"]);
  });
});

describe("empty state", () => {
  it("says there is no model yet and offers «Agregar un modelo» as the main action", async () => {
    await renderCard([SMALL, TINY]);
    expect(screen.getByRole("heading", { name: t("engines:local.empty.title.transcription") })).toBeInTheDocument();
    expect(screen.getByText(t("engines:local.empty.body"))).toBeInTheDocument();
    const add = screen.getByRole("button", { name: t("engines:local.empty.action") });
    expect(add).toHaveClass("ui-button--primary");
    expect(screen.queryByRole("button", { name: t("engines:local.add.label.transcription") })).toBeNull();
    expect(screen.queryByRole("list", { name: t("engines:local.modelsTitle") })).toBeNull();
    fireEvent.click(add);
    expect(screen.getByRole("dialog", { name: t("engines:local.add.title.transcription") })).toBeInTheDocument();
  });

  it("shows the empty state again after the only model is removed, without reloading", async () => {
    await renderCard([{ ...SMALL_INSTALLED, default: true }]);
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.remove")));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.removeConfirm") }));
    expect(await screen.findByRole("heading", { name: t("engines:local.empty.title.transcription") })).toBeInTheDocument();
    expect(screen.getByText(t("engines:local.outcome.removed", { id: "whisper-small" }))).toBeInTheDocument();
  });
});

describe("«Agregar»", () => {
  it("suggests at most two models this computer supports, the recommended one first, each with size, reason and «Instalar»", async () => {
    await renderCard([TURBO, SMALL, TINY, HUGE, PARAKEET, FLUIDAUDIO], {
      recommendations: {
        transcription: { ...defaultRecommendation("transcription", PARAKEET_ID), reason_params: { memory_gib: 24, min_ram_gib: 8 } },
      },
    });
    const dialog = openAdd();
    expect(suggestionNames(dialog)).toEqual([`local-add-transcription-${PARAKEET_ID}`, "local-add-transcription-whisper-small"]);
    const first = within(dialog).getByRole("listitem", { name: PARAKEET_ID });
    expect(within(first).getByText(t("engines:local.tags.recommended"))).toBeInTheDocument();
    expect(within(first).getByText("632 MB")).toBeInTheDocument();
    expect(within(first).getByText(t("engines:local.reasons.fitsMinimum", { memory: "24 GB", minimum: 8 }))).toBeInTheDocument();
    expect(within(first).getByRole("button", { name: t("engines:local.installLabel", { id: PARAKEET_ID }) })).toHaveClass("ui-button--primary");
    const second = within(dialog).getByRole("listitem", { name: "whisper-small" });
    expect(within(second).getByText(t("engines:local.short.whisperLight"))).toBeInTheDocument();
    expect(within(second).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) })).toHaveClass("ui-button--secondary");
    expect(within(dialog).queryByText("whisper-huge")).toBeNull();
    expect(within(dialog).getAllByRole("button").filter((button) => button.classList.contains("ui-button--primary"))).toHaveLength(1);
  });

  it("never suggests a managed engine nor a component that cannot be downloaded yet", async () => {
    const unpublished = { ...RUNTIME, install: { ...RUNTIME.install!, source_available: false } };
    const senkoMissing = { ...SENKO, state: "not_installed" as const, availability: "available" as const, active: false, in_use: false, in_use_by: [], location: null };
    await renderCard([senkoMissing, unpublished], {}, { process: "diarization" });
    const dialog = openAdd("diarization");
    expect(within(dialog).queryByRole("region", { name: t("engines:local.add.suggested") })).toBeNull();
    expect(within(dialog).getByText(t("engines:local.add.allInstalled"))).toBeInTheDocument();
    expect(within(dialog).getByText(t("engines:local.managedHow", { command: "bash scripts/engines/install-diar-engine.sh" }))).toBeInTheDocument();
  });

  it("offers «Otro modelo» for transcription and summaries, never for speakers", async () => {
    await renderCard([TURBO, SMALL]);
    expect(within(openAdd()).getByRole("button", { name: t("engines:local.add.other") })).toBeInTheDocument();
    cleanup();
    await renderCard([QWEN_9B, QWEN_4B], {}, { process: "summary" });
    expect(within(openAdd("summary")).getByRole("button", { name: t("engines:local.add.other") })).toBeInTheDocument();
    cleanup();
    await renderCard([SENKO, RUNTIME], {}, { process: "diarization" });
    const speakers = openAdd("diarization");
    expect(suggestionNames(speakers)).toEqual(["local-add-diarization-diar-runtime"]);
    expect(within(speakers).queryByRole("button", { name: t("engines:local.add.other") })).toBeNull();
    expect(within(speakers).queryByRole("region", { name: t("engines:local.add.otherTitle") })).toBeNull();
  });

  it("says when nothing else fits this computer and still offers «Otro modelo»", async () => {
    await renderCard([TURBO, HUGE]);
    const dialog = openAdd();
    expect(within(dialog).getByText(t("engines:local.add.noneFits"))).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: t("engines:local.add.other") })).toBeInTheDocument();
  });

  it("says when every suggested model is already installed", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    expect(within(openAdd()).getByText(t("engines:local.add.allInstalled"))).toBeInTheDocument();
  });

  it("disables «Instalar» with the reason when the model does not fit on the disk", async () => {
    const tight = available({
      id: "whisper-small", size: 190_085_487, min_ram_gib: 4, requires: [],
      install: { method: "download", managed_by: null, download_bytes: 190_085_487, disk_required_bytes: 230_000_000, fits_on_disk: false },
    });
    await renderCard([TURBO, tight]);
    const dialog = openAdd();
    expect(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) })).toBeDisabled();
    expect(within(dialog).getByText(t("engines:local.notEnoughSpace", { size: "230 MB" }))).toBeInTheDocument();
  });

  it("shows the download's progress in the dialog, then closes it and lists the new model", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 250 }, { bytes_done: 600 }, { state: "done", bytes_done: 1000, result: "installed" });
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    expect(await within(dialog).findByRole("progressbar", { name: t("engines:local.progressLabel", { id: "whisper-small" }) })).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByText(t("engines:local.installing", { id: "whisper-small", percent: 25 }))).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText(t("engines:local.outcome.installed", { id: "whisper-small" }))).toBeInTheDocument();
    await waitFor(() => expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.installed")]));
    expect(backend.calls).toContainEqual({ method: "POST", path: "/local/models/whisper-small/install", body: null });
  });

  it("keeps the download going as a row with its progress when the dialog is closed", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 100 });
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    await within(dialog).findByRole("progressbar");
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.add.close") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.installing")]);
    expect(within(row("whisper-small")).getByRole("progressbar")).toBeInTheDocument();
    expect(within(row("whisper-small")).getByRole("button", { name: t("engines:local.cancelLabel", { id: "whisper-small" }) })).toBeEnabled();
  });

  it("cancels a download from the dialog", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 100 });
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    fireEvent.click(await within(dialog).findByRole("button", { name: t("engines:local.cancelLabel", { id: "whisper-small" }) }));
    expect(await within(dialog).findByText(t("engines:local.outcome.cancelled"))).toBeInTheDocument();
    expect(backend.calls.some((call) => call.method === "POST" && call.path.endsWith("/cancel"))).toBe(true);
    expect(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) })).toBeEnabled();
  });

  it("explains a refusal for lack of disk inside the dialog", async () => {
    await renderCard([TURBO, SMALL]);
    backend.refusals.set("POST /local/models/whisper-small/install", backend.json({ detail: "insufficient_disk", needed_bytes: 688_849_434, free_bytes: 300_000_000 }, 507));
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t("engines:local.insufficientDisk", { needed: "689 MB", free: "300 MB" }));
  });

  it("explains an invalid download and leaves the model to install again", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ state: "failed", error: "hash_mismatch" });
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t("engines:local.jobErrors.hash_mismatch"));
    expect(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) })).toBeEnabled();
  });

  it("is a modal dialog that closes with Escape and gives the focus back to «Agregar»", async () => {
    await renderCard([TURBO, SMALL]);
    const trigger = screen.getByRole("button", { name: t("engines:local.add.label.transcription") });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: t("engines:local.add.title.transcription") });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });
});

describe("«Otro modelo» from Hugging Face", () => {
  it("finds the repository, shows its file, size and license, installs it and lists it as «Personalizado»", async () => {
    await renderCard([QWEN_9B, QWEN_4B], {}, { process: "summary" });
    backend.jobAnswers.push({ bytes_done: 500 }, { state: "done", bytes_done: 1000, result: "installed" });
    const dialog = openAdd("summary");
    searchCustom(dialog, "https://huggingface.co/someone/tiny-gguf");
    expect(await within(dialog).findByText(t("engines:local.custom.found", { repo: "someone/tiny-gguf", revision: "0123456" }))).toBeInTheDocument();
    expect(backend.calls).toContainEqual({ method: "POST", path: "/local/custom/resolve", body: { process: "summary", source: "https://huggingface.co/someone/tiny-gguf" } });
    expect(within(dialog).getByText(t("engines:local.custom.license", { license: "Apache 2.0" }))).toBeInTheDocument();
    expect(within(dialog).getByText(t("engines:local.custom.oneFile", { file: "tiny-q4_k_m.gguf", size: "1,2 GB" }))).toBeInTheDocument();
    expect(within(dialog).getByText(t("engines:local.custom.safety"))).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.custom.install", { size: "1,2 GB" }) }));
    expect(await within(dialog).findByRole("progressbar", { name: t("engines:local.progressLabel", { id: "tiny-q4_k_m.gguf" }) })).toBeInTheDocument();
    expect(backend.calls).toContainEqual({
      method: "POST", path: "/local/custom/install",
      body: { process: "summary", repo: "someone/tiny-gguf", revision: RESOLVED.revision, file: "tiny-q4_k_m.gguf" },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText(t("engines:local.outcome.installedCustom", { id: "tiny-q4_k_m.gguf" }))).toBeInTheDocument();
    await waitFor(() => expect(tagsOf("tiny-q4_k_m.gguf")).toEqual([t("engines:local.tags.installed"), t("engines:local.tags.custom")]));
  });

  it("lets the person choose a file when there are several, seeing each size", async () => {
    await renderCard([TURBO]);
    backend.resolve.answer = backend.json({
      ...RESOLVED, repo: "someone/whisper-ggml", license: null,
      files: [{ path: "ggml-small.bin", size: 190_000_000, sha256: "a".repeat(64) }, { path: "models/ggml-medium.bin", size: 1_500_000_000, sha256: "b".repeat(64) }],
    });
    backend.jobAnswers.push({ bytes_done: 1 });
    const dialog = openAdd();
    searchCustom(dialog, "someone/whisper-ggml");
    const files = await within(dialog).findByRole("group", { name: t("engines:local.custom.filesLegend") });
    expect(within(files).getAllByRole("radio").map((radio) => radio.closest("label")?.textContent)).toEqual(["ggml-small.bin190 MB", "ggml-medium.bin1,5 GB"]);
    expect(within(files).getByRole("radio", { name: /ggml-small\.bin/ })).toBeChecked();
    expect(within(dialog).getByText(t("engines:local.custom.noLicense"))).toBeInTheDocument();
    fireEvent.click(within(files).getByRole("radio", { name: /ggml-medium\.bin/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.custom.install", { size: "1,5 GB" }) }));
    await waitFor(() => expect(backend.calls.some((call) => call.path === "/local/custom/install")).toBe(true));
    expect(backend.calls.find((call) => call.path === "/local/custom/install")?.body).toEqual({
      process: "transcription", repo: "someone/whisper-ggml", revision: RESOLVED.revision, file: "models/ggml-medium.bin",
    });
  });

  it("asks for a name before searching", async () => {
    await renderCard([TURBO]);
    const dialog = openAdd();
    searchCustom(dialog, "   ");
    const field = within(dialog).getByLabelText(t("engines:local.custom.label"));
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(expect.stringContaining(t("engines:local.custom.errors.empty")));
    expect(backend.calls.some((call) => call.path === "/local/custom/resolve")).toBe(false);
  });

  it.each([
    ["host_not_allowed", 400, "transcription", "engines:local.custom.errors.host_not_allowed"],
    ["not_found", 404, "transcription", "engines:local.custom.errors.not_found"],
    ["invalid_source", 400, "summary", "engines:local.custom.errors.invalid_source"],
    ["gated", 403, "summary", "engines:local.custom.errors.gated"],
    ["no_compatible_files", 422, "transcription", "engines:local.custom.errors.no_compatible_files.transcription"],
    ["no_compatible_files", 422, "summary", "engines:local.custom.errors.no_compatible_files.summary"],
    ["unreachable", 502, "summary", "engines:local.custom.errors.unreachable"],
    ["host_unavailable", 503, "summary", "engines:local.errors.host_unavailable"],
    ["something_new", 500, "summary", "engines:local.custom.errors.generic"],
  ] as const)("explains «%s» (%s) for %s in plain words and offers no download", async (code, status, process, key) => {
    const models = process === "summary" ? [QWEN_9B] : [TURBO];
    await renderCard(models, {}, { process });
    backend.resolve.answer = backend.json({ detail: code }, status);
    const dialog = openAdd(process);
    searchCustom(dialog, "https://example.com/model.gguf");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t(key));
    expect(within(dialog).getByLabelText(t("engines:local.custom.label"))).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).queryByRole("button", { name: /^Instalar|^Install/ })).toBeNull();
    expect(backend.calls.some((call) => call.path === "/local/custom/install")).toBe(false);
  });

  it("explains a refusal when the repository changed before the download started", async () => {
    await renderCard([QWEN_9B], {}, { process: "summary" });
    backend.refusals.set("POST /local/custom/install", backend.json({ detail: "revision_changed" }, 409));
    const dialog = openAdd("summary");
    searchCustom(dialog, "someone/tiny-gguf");
    fireEvent.click(await within(dialog).findByRole("button", { name: t("engines:local.custom.install", { size: "1,2 GB" }) }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(t("engines:local.errors.revision_changed"));
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("goes back to the suggestions", async () => {
    await renderCard([TURBO, SMALL]);
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.add.other") }));
    expect(within(dialog).getByLabelText(t("engines:local.custom.label"))).toHaveFocus();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.custom.back") }));
    expect(suggestionNames(dialog)).toEqual(["local-add-transcription-whisper-small"]);
    expect(within(dialog).getByRole("button", { name: t("engines:local.add.other") })).toHaveFocus();
  });
});

describe("check and remove", () => {
  it("checks a file from the row menu and shows it installed in place, without reloading", async () => {
    const odd = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", verified_by: undefined, size: 190_085_487 });
    await renderCard([TURBO, odd]);
    backend.jobAnswers.push({ bytes_done: 400 }, { state: "done", result: "verified", bytes_done: 1000 });
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.verify")));
    expect(await screen.findByText(t("engines:local.verifying", { id: "whisper-small", percent: 0 }))).toBeInTheDocument();
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.verifying")]);
    expect(await screen.findByText(t("engines:local.outcome.verified", { id: "whisper-small" }))).toBeInTheDocument();
    await waitFor(() => expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.installed")]));
    expect(backend.calls.filter((call) => call.path === "/local/hardware")).toHaveLength(1);
  });

  it("reports a damaged file after checking", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    backend.jobAnswers.push({ state: "done", result: "corrupt", bytes_done: 1000 });
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.verify")));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:local.outcome.corrupt", { id: "whisper-small" }));
  });

  it("blocks removal while a process uses the model, and says which", async () => {
    await renderCard([TURBO]);
    openRowMenu("whisper-turbo");
    const remove = menuItem(t("engines:local.remove"));
    const reason = t("engines:local.removeBlocked", { list: t("engines:processes.transcription") });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAttribute("title", reason);
    expect(within(screen.getByRole("menu")).getByText(reason)).toBeInTheDocument();
    fireEvent.click(remove);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("never removes a model installed by hand, and says Sauri does not delete it", async () => {
    await renderCard([TURBO, { ...SMALL_INSTALLED, location: "legacy" }]);
    openRowMenu("whisper-small");
    const remove = menuItem(t("engines:local.remove"));
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAttribute("title", t("engines:local.manualNote"));
  });

  it("asks before removing, removes after the confirmation and drops the row", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.remove")));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(t("engines:local.removeBody", { id: "whisper-small", size: "190 MB" }))).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.removeCancel") }));
    expect(backend.calls.some((call) => call.method === "DELETE")).toBe(false);
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.remove")));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.removeConfirm") }));
    expect(await screen.findByText(t("engines:local.outcome.removed", { id: "whisper-small" }))).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("listitem", { name: "whisper-small" })).toBeNull());
  });

  it("explains a refusal from the host when the model became in use meanwhile", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    backend.refusals.set("DELETE /local/models/whisper-small", backend.json({ detail: "model_in_use", processes: ["transcription"] }, 409));
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.remove")));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.removeConfirm") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:local.modelInUse", { list: t("engines:processes.transcription") }));
  });

  it("replaces an older speaker runtime by installing the new version from its menu", async () => {
    const older = { ...RUNTIME, state: "unverified" as const, availability: "present_unverified" as const, reason: "outdated" as const, location: "models_dir" as const };
    await renderCard([older], {}, { process: "diarization" });
    const name = t("engines:local.managedTitle.diarization");
    expect(within(row(name)).getByText(t("engines:local.unverifiedReason.outdated"))).toBeInTheDocument();
    backend.jobAnswers.push({ state: "done", bytes_done: 1000, result: "installed" });
    openRowMenu(name);
    fireEvent.click(menuItem(t("engines:local.install")));
    expect(await screen.findByText(t("engines:local.outcome.installed", { id: "diar-runtime" }))).toBeInTheDocument();
  });
});

describe("jobs", () => {
  it("picks up a download that was already running when the screen opened", async () => {
    backend = fakeBackend([TURBO, SMALL]);
    backend.job.current = { id: JOB_ID, model_id: "whisper-small", type: "install", state: "running", bytes_done: 500, bytes_total: 1000, error: null, result: null };
    backend.jobAnswers.push({ bytes_done: 500 });
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({})} />);
    expect(await screen.findByRole("progressbar", { name: t("engines:local.progressLabel", { id: "whisper-small" }) })).toBeInTheDocument();
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.installing")]);
  });

  it("stops asking about the job when the card goes away", async () => {
    const view = await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 100 });
    fireEvent.click(within(openAdd()).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    await waitFor(() => expect(jobLooks()).toBeGreaterThanOrEqual(2));
    view.unmount();
    const looksAtUnmount = jobLooks();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 8));
    expect(jobLooks()).toBeLessThanOrEqual(looksAtUnmount + 1);
  });

  it("gives up after repeated failed looks instead of asking forever", async () => {
    await renderCard([TURBO, SMALL]);
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    await within(dialog).findByRole("progressbar");
    backend.refusals.set(`GET /local/jobs/${JOB_ID}`, backend.json({ detail: "host_unavailable" }, 503));
    expect(await within(dialog).findByText(t("engines:local.outcome.lost"))).toBeInTheDocument();
    const looks = jobLooks();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 6));
    expect(jobLooks()).toBe(looks);
  });

  it("disables every other install while one job runs", async () => {
    await renderCard([TURBO, SMALL, TINY]);
    backend.jobAnswers.push({ bytes_done: 100 });
    const dialog = openAdd();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-small" }) }));
    await within(dialog).findByRole("progressbar");
    expect(within(dialog).getByRole("button", { name: t("engines:local.installLabel", { id: "whisper-tiny" }) })).toBeDisabled();
  });
});

describe("engines and models already there", () => {
  it("tells the engine is not installed, with the command and the tools it needs", async () => {
    await renderCard([TURBO], { engineState: "stopped" });
    const missing = screen.getByRole("region", { name: t("engines:local.engineMissing.title") });
    expect(within(missing).getByText(t("engines:local.engineMissing.installCommand"))).toBeInTheDocument();
  });

  it("says so when the service that manages models does not answer", async () => {
    backend = fakeBackend([TURBO], { hostDown: true });
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({})} />);
    const missing = await screen.findByRole("region", { name: t("engines:local.engineMissing.title") });
    expect(within(missing).getByText(t("engines:local.engineMissing.hostBody"))).toBeInTheDocument();
  });

  it("says what it is doing while files are recognized, then shows them as installed", async () => {
    const checking = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", verifying: true, verified_by: undefined });
    await renderCard([TURBO, checking]);
    expect(screen.getByText(t("engines:local.adoption.recognizing"))).toBeInTheDocument();
    Object.assign(backend.catalog[1], { verifying: false, state: "installed", availability: "installed", verified_by: "hash" });
    await waitFor(() => expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.installed")]));
    expect(screen.queryByText(t("engines:local.adoption.recognizing"))).toBeNull();
    const reads = catalogReads();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 6));
    expect(catalogReads()).toBe(reads);
  });

  it("explains calmly when a file could not be confirmed", async () => {
    const odd = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", reason: "hash_mismatch", verified_by: undefined });
    await renderCard([TURBO, odd], { adoption: { job_id: "c".repeat(32), outcomes: { "whisper-small": "present_unverified" } } });
    expect(screen.getByText(t("engines:local.adoption.attention"))).toBeInTheDocument();
  });

  it("looks for installed models from the card menu, and follows the run", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 0 }, { state: "done", result: "adopted" });
    fireEvent.click(screen.getByRole("button", { name: t("engines:local.cardMenu") }));
    fireEvent.click(menuItem(t("engines:local.scan")));
    expect(await screen.findByText(t("engines:local.adoption.recognizing"))).toBeInTheDocument();
    expect(await screen.findByText(t("engines:local.adoption.done"))).toBeInTheDocument();
  });
});

describe("inside the desktop app", () => {
  async function localMode(on: boolean) {
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!on) return new Response("{}", { status: 404 });
      return String(input).endsWith("/local/me") ? json({ name: "Ana", email: "ana@sauri.local" }) : json({ mode: "local", ready: true });
    }));
    await detectLocalSession();
  }

  beforeEach(() => localMode(true));
  afterEach(() => localMode(false));

  const noTerminal = () => {
    for (const text of [/make engines/, /bash /, /Homebrew/, /terminal/i]) expect(screen.queryByText(text)).toBeNull();
  };

  it("tells the person to reopen Sauri when an engine does not answer, without terminal commands", async () => {
    await renderCard([TURBO], { engineState: "stopped" });
    expect(screen.getByRole("region", { name: t("engines:local.engineMissing.desktopTitle") })).toBeInTheDocument();
    noTerminal();
  });

  it("never asks to run an install script for Parakeet's engine", async () => {
    const parakeet = model({ ...PARAKEET, state: "installed", availability: "installed", install: null, needs_ready: false });
    const engine = model({ ...FLUIDAUDIO, state: "not_installed", availability: "available", location: null });
    await renderCard([parakeet, TURBO, engine]);
    expect(within(row(PARAKEET_ID)).getByText(t("engines:local.needsEngineDesktop"))).toBeInTheDocument();
    expect(screen.getByText(t("engines:local.managedDesktop"))).toBeInTheDocument();
    noTerminal();
  });
});

describe("in English", () => {
  beforeEach(() => setLanguage("en", { persist: false }));
  afterEach(() => setLanguage("es", { persist: false }));

  it("shows the same rows and dialog in English", async () => {
    await renderCard([TURBO, SMALL_INSTALLED, TINY]);
    expect(tagsOf("whisper-turbo")).toEqual(["Active"]);
    expect(tagsOf("whisper-small")).toEqual(["Installed"]);
    expect(screen.getByRole("button", { name: "Use this one: whisper-small" })).toHaveTextContent("Use this one");
    const dialog = openAdd();
    expect(dialog).toHaveAccessibleName("Add a transcription model");
    expect(within(dialog).getByRole("button", { name: "Install “whisper-tiny”" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Find another model…" })).toBeInTheDocument();
  });
});
