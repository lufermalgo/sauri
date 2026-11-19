// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { EngineProcess, LocalAdoption, LocalJob, LocalModel } from "@sauri/shared-types";
import { detectLocalSession } from "../api";
import { LocalModelCard } from "./settings/LocalModelCard";
import type { ExternalChoice, LocalSelection } from "./settings/LocalModelCard";
import { setLanguage, t } from "../i18n";

const POLL_MS = 10;

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
    install: { method: "download", managed_by: null, download_bytes: 574_041_195, disk_required_bytes: 688_849_434, fits_on_disk: true },
    ...overrides,
  });
}

const TURBO = model({ id: "whisper-turbo", default: true, recommended: true, active: true, in_use: true, in_use_by: ["transcription"] });
const SMALL = available({ id: "whisper-small", size: 190_085_487, status: "proposal", min_ram_gib: 4, requires: [] });
const SMALL_INSTALLED = model({ id: "whisper-small", size: 190_085_487, status: "proposal", min_ram_gib: 4, requires: [], installed_size: 190_085_487 });
const VAD = model({ id: "silero-vad", kind: "auxiliary", size: 2_000_000, installed_size: 2_000_000, in_use: true });
const SENKO = model({
  id: "senko-coreml", process: "diarization", kind: "managed_engine", engine: "senko", size: null, installed_size: null,
  state: "managed", location: "managed", verified_by: "presence", managed_by: "scripts/engines/install-diar-engine.sh",
  active: true, in_use: true, in_use_by: ["diarization"],
});

interface Call { method: string; path: string }

interface Options {
  engineState?: string;
  hostDown?: boolean;
  recommendation?: object;
  adoption?: LocalAdoption | null;
}

function fakeBackend(models: LocalModel[], options: Options = {}) {
  const catalog = models.map((entry) => ({ ...entry }));
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
  const job = { current: null as LocalJob | null };
  /** Answers of the job route, in order; the last one repeats. */
  const jobAnswers: Partial<LocalJob>[] = [];
  let lookups = 0;
  const refusals = new Map<string, Response>();

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/engines", "");
    calls.push({ method, path });
    const refused = refusals.get(`${method} ${path}`);
    if (refused) return refused.clone();
    if (options.hostDown && path.startsWith("/local")) return json({ detail: "host_unavailable" }, 503);

    if (path === "/local/hardware") return json({ arch: "arm64", system: "Darwin", memory_gib: 24, cores: 10, metal: true, disk_free_bytes: 120e9 });
    if (path === "/status") return json({ engines: [{ id: "asr", port: 8001, state: options.engineState ?? "running" }], secret_store: null });
    if (path === "/local/models") {
      return json({
        catalog_version: 1, models: catalog, active_job: job.current?.state === "running" ? job.current.id : null,
        active: Object.fromEntries(catalog.filter((entry) => entry.active).map((entry) => [entry.process, entry.id])),
        adoption: options.adoption ?? null,
        recommendations: {
          transcription: options.recommendation ?? {
            process: "transcription", model_id: "whisper-turbo", status: "measured", reason_key: "fits",
            reason_params: { memory_gib: 24, min_ram_gib: 8 }, warnings: [],
          },
        },
      });
    }
    if (path === "/local/adopt" && method === "POST") {
      job.current = {
        id: "b".repeat(32), model_id: "", type: "adopt", state: "running", bytes_done: 0, bytes_total: 0, error: null, result: null,
      };
      return json(job.current, 202);
    }
    const start = /^\/local\/models\/([^/]+)\/(install|verify)$/.exec(path);
    if (start && method === "POST") {
      job.current = {
        id: "a".repeat(32), model_id: start[1], type: start[2] as "install" | "verify", state: "running",
        bytes_done: 0, bytes_total: 1000, error: null, result: null,
      };
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
      if (job.current.state === "done" && job.current.type === "install") {
        const target = catalog.find((entry) => entry.id === job.current!.model_id)!;
        Object.assign(target, { state: "installed", availability: "installed", installed_size: target.size, install: null, location: "models_dir" });
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
  return { handler, calls, jobAnswers, refusals, catalog, job, json };
}

let backend: ReturnType<typeof fakeBackend>;

const LOCAL_SELECTION: LocalSelection = { external: false, key: "local:default" };

interface Props {
  process?: EngineProcess;
  selection?: LocalSelection;
  external?: Partial<ExternalChoice>;
  onModelsChange?: (models: LocalModel[]) => void;
  onUse?: (key: string) => void;
}

function cardProps(props: Props) {
  return {
    process: props.process ?? "transcription",
    selection: props.selection ?? LOCAL_SELECTION,
    onModelsChange: props.onModelsChange,
    onUse: props.onUse ?? vi.fn(),
    external: { current: null, hasProviders: true, onChoose: vi.fn(), onSetup: vi.fn(), ...props.external },
    pollIntervalMs: POLL_MS,
  };
}

async function renderCard(models: LocalModel[], options: Options = {}, props: Props = {}) {
  backend = fakeBackend(models, options);
  vi.stubGlobal("fetch", backend.handler);
  const view = render(<LocalModelCard {...cardProps(props)} />);
  await screen.findByRole("list", { name: t("engines:local.modelsTitle") });
  return view;
}

const row = (name: string) => screen.getByRole("listitem", { name });
const jobLooks = () => backend.calls.filter((call) => call.path.startsWith("/local/jobs/") && call.method === "GET").length;
const catalogReads = () => backend.calls.filter((call) => call.path === "/local/models" && call.method === "GET").length;

function openRowMenu(name: string) {
  fireEvent.click(within(row(name)).getByRole("button", { name: t("engines:local.moreLabel", { name }) }));
}

const menuItem = (name: string | RegExp) => screen.getByRole("menuitem", { name });
const queryMenuItem = (name: string | RegExp) => screen.queryByRole("menuitem", { name });
const INSTALL = () => new RegExp(`^${t("engines:local.install")}`);

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

function installFromMenu(name: string) {
  openRowMenu(name);
  fireEvent.click(menuItem(INSTALL()));
}

const shownOrder = () => screen.getAllByRole("listitem").map((item) => item.getAttribute("aria-labelledby"));
const tagsOf = (name: string) => Array.from(row(name).querySelectorAll(".ui-status-badge")).map((badge) => badge.textContent);

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

describe("hardware and recommendation", () => {
  it("describes the computer in one line and keeps the rest under «Detalles»", async () => {
    await renderCard([TURBO, SMALL]);
    expect(screen.getByText(t("engines:local.hardwareShort", { chip: t("engines:local.chipAppleSilicon"), memory: "24 GB", free: "120 GB" }))).toBeInTheDocument();
    expect(screen.queryByText(t("engines:local.metalYes"))).toBeNull();
    expect(screen.queryByText(t("engines:local.reasons.fitsMinimum", { memory: "24 GB", minimum: 8 }))).toBeNull();
    const details = openDetails("whisper-turbo");
    expect(within(details).getByText(t("engines:local.hardware", { chip: t("engines:local.chipAppleSilicon"), memory: "24 GB", count: 10, free: "120 GB" }))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.metalYes"))).toBeInTheDocument();
  });

  it("keeps the recommendation, its reason and the measured mark in «Detalles», not as badges", async () => {
    await renderCard([TURBO, SMALL]);
    expect(within(row("whisper-turbo")).queryByText(t("engines:local.recommended"))).toBeNull();
    expect(within(row("whisper-turbo")).queryByText(t("engines:local.marks.measured"))).toBeNull();
    const turbo = openDetails("whisper-turbo");
    expect(within(turbo).getByText(t("engines:local.recommended"))).toBeInTheDocument();
    expect(within(turbo).getByText(`${t("engines:local.marks.measured")}. ${t("engines:local.markHelp.measured")}`)).toBeInTheDocument();
    expect(within(turbo).getByText(t("engines:local.reasons.fitsMinimum", { memory: "24 GB", minimum: 8 }))).toBeInTheDocument();
    fireEvent.click(within(turbo).getByRole("button", { name: t("engines:local.details.close") }));
    const small = openDetails("whisper-small");
    expect(within(small).getByText(`${t("engines:local.marks.proposal")}. ${t("engines:local.markHelp.proposal")}`)).toBeInTheDocument();
    expect(within(small).queryByText(t("engines:local.recommended"))).toBeNull();
  });

  it("lists the cautions of a proposal in the details of the recommended model", async () => {
    await renderCard([TURBO, SMALL], {
      recommendation: {
        process: "transcription", model_id: "whisper-small", status: "proposal", reason_key: "reduced",
        reason_params: { memory_gib: 4, min_ram_gib: 4, better_id: "whisper-turbo", limited_by: "memory" },
        warnings: ["unmeasured_proposal", "lower_quality_expected"],
      },
    });
    expect(screen.queryByText(t("engines:local.warnings.unmeasured_proposal"))).toBeNull();
    const details = openDetails("whisper-small");
    expect(within(details).getByText(t("engines:local.warnings.unmeasured_proposal"))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.warnings.lower_quality_expected"))).toBeInTheDocument();
  });

  it("says on the card why no local model fits, since no model carries the reason", async () => {
    await renderCard([SMALL], {
      recommendation: {
        process: "transcription", model_id: null, status: null, reason_key: "no_local_model",
        reason_params: { memory_gib: 2, min_ram_gib: 4, needs: "memory" }, warnings: ["suggest_external_provider"],
      },
    });
    expect(screen.getByText(`${t("engines:local.noRecommendation")} ${t("engines:local.reasons.noModelMemory", { memory: "2 GB", minimum: 4 })}`)).toBeInTheDocument();
    expect(screen.getByText(t("engines:local.warnings.suggest_external_provider"))).toBeInTheDocument();
  });

  it("tells the engine is not installed, with the command and the tools it needs", async () => {
    await renderCard([TURBO], { engineState: "stopped" });
    const missing = screen.getByRole("region", { name: t("engines:local.engineMissing.title") });
    expect(within(missing).getByText(t("engines:local.engineMissing.installCommand"))).toBeInTheDocument();
    expect(within(missing).getByText(t("engines:local.engineMissing.tools", { list: t("engines:local.engineTools.transcription") }))).toBeInTheDocument();
  });

  it("says so when the service that manages models does not answer", async () => {
    backend = fakeBackend([TURBO], { hostDown: true });
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({})} />);
    const missing = await screen.findByRole("region", { name: t("engines:local.engineMissing.title") });
    expect(within(missing).getByText(t("engines:local.engineMissing.hostBody"))).toBeInTheDocument();
    expect(within(missing).getByText(t("engines:local.engineMissing.startCommand"))).toBeInTheDocument();
  });

  it("hands the catalog to the screen so installed models can be chosen", async () => {
    const onModelsChange = vi.fn();
    await renderCard([TURBO, SMALL_INSTALLED], {}, { onModelsChange });
    expect(onModelsChange.mock.calls[0][0].map((entry: LocalModel) => entry.id)).toEqual(["whisper-turbo", "whisper-small"]);
  });
});

describe("what each option is", () => {
  it("shows the active model with the single tag «Activo», and its size and catalog check under «Detalles»", async () => {
    await renderCard([TURBO, SMALL]);
    expect(tagsOf("whisper-turbo")).toEqual([t("engines:local.tags.active")]);
    const turbo = row("whisper-turbo");
    expect(within(turbo).getByText(t("engines:local.short.whisper"))).toBeInTheDocument();
    expect(within(turbo).queryByText("574 MB")).toBeNull();
    expect(within(turbo).queryByText(new RegExp(t("engines:local.verifiedBy.hash")))).toBeNull();
    expect(within(turbo).queryByText(/whisper\.cpp/)).toBeNull();
    expect(rowMenuItems("whisper-turbo")).toEqual([t("engines:local.verify"), t("engines:local.remove"), t("engines:local.details.open")]);
    closeMenu();
    const details = openDetails("whisper-turbo");
    expect(within(details).getByText("574 MB")).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.verifiedBy.hash"))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.descriptionMinRam", { engine: "whisper.cpp", minRam: 8 }))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.inUse", { list: "Transcripción" }))).toBeInTheDocument(); // spanish-sample-data
  });

  it("offers an installed model that is not active with «Usar este» in its menu, and gives it no tag", async () => {
    const onUse = vi.fn();
    await renderCard([TURBO, SMALL_INSTALLED], {}, { onUse });
    expect(tagsOf("whisper-small")).toEqual([]);
    expect(within(row("whisper-small")).getByText(t("engines:local.short.whisperLight"))).toBeInTheDocument();
    openRowMenu("whisper-small");
    fireEvent.click(menuItem(t("engines:local.use")));
    expect(onUse).toHaveBeenCalledWith("local:whisper-small");
  });

  it("chooses the catalog default through local:default", async () => {
    const onUse = vi.fn();
    await renderCard([{ ...TURBO, active: false, in_use: false, in_use_by: [] }, SMALL_INSTALLED], {}, { onUse });
    openRowMenu("whisper-turbo");
    fireEvent.click(menuItem(t("engines:local.use")));
    expect(onUse).toHaveBeenCalledWith("local:default");
  });

  it("disables «Usar este» while a choice is being saved", async () => {
    backend = fakeBackend([TURBO, SMALL_INSTALLED]);
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({})} choosing />);
    await screen.findByRole("list", { name: t("engines:local.modelsTitle") });
    openRowMenu("whisper-small");
    expect(menuItem(t("engines:local.use"))).toHaveAttribute("aria-disabled", "true");
  });

  it("shows an installed model as available again to use when an external provider is the one active", async () => {
    await renderCard([TURBO], {}, { selection: { external: true, key: "gpt-a" }, external: { current: "Work OpenAI, gpt-a" } });
    expect(tagsOf("whisper-turbo")).toEqual([]);
    openRowMenu("whisper-turbo");
    expect(menuItem(t("engines:local.use"))).toBeInTheDocument();
    closeMenu();
    const group = screen.getByRole("region", { name: t("engines:local.external.title") });
    expect(within(group).getByText("Work OpenAI, gpt-a")).toBeInTheDocument();
    expect(within(group).getByText(t("engines:local.states.active"))).toBeInTheDocument();
  });

  it("offers an available model with the tag «Disponible» and «Instalar» with the space it needs in its menu", async () => {
    await renderCard([TURBO, SMALL]);
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.available")]);
    expect(within(row("whisper-small")).queryByText("190 MB")).toBeNull();
    expect(rowMenuItems("whisper-small")).toEqual([t("engines:local.installWithSize", { size: "689 MB" }), t("engines:local.details.open")]);
    expect(menuItem(t("engines:local.installWithSize", { size: "689 MB" }))).not.toHaveAttribute("aria-disabled");
    closeMenu();
    const details = openDetails("whisper-small");
    expect(within(details).getByText(`190 MB · ${t("engines:local.spaceNeeded", { size: "689 MB" })}`)).toBeInTheDocument();
  });

  it("disables «Instalar» with the reason when the model does not fit on the disk", async () => {
    const tight = available({
      id: "whisper-small",
      install: { method: "download", managed_by: null, download_bytes: 190_085_487, disk_required_bytes: 230_000_000, fits_on_disk: false },
    });
    await renderCard([TURBO, tight]);
    const reason = t("engines:local.notEnoughSpace", { size: "230 MB" });
    expect(within(row("whisper-small")).getByText(reason)).toBeInTheDocument();
    openRowMenu("whisper-small");
    const install = menuItem(INSTALL());
    expect(install).toHaveAttribute("aria-disabled", "true");
    expect(install).toHaveAttribute("title", reason);
    expect(within(screen.getByRole("menu")).getByText(reason)).toBeInTheDocument();
    fireEvent.click(install);
    expect(backend.calls.some((call) => call.path.endsWith("/install"))).toBe(false);
  });

  it("shows a file that is there but not verified, with the reason in plain words and «Verificar»", async () => {
    const odd = model({
      id: "whisper-small", state: "unverified", availability: "present_unverified", reason: "size_mismatch", verified_by: undefined,
      location: "legacy", size: 190_085_487,
    });
    await renderCard([TURBO, odd]);
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.states.unverified")]);
    expect(within(row("whisper-small")).getByText(t("engines:local.unverifiedReason.size_mismatch"))).toBeInTheDocument();
    openRowMenu("whisper-small");
    expect(menuItem(t("engines:local.verify"))).not.toHaveAttribute("aria-disabled");
    expect(queryMenuItem(t("engines:local.use"))).toBeNull();
  });

  it("says «Verificando…» while the file is being checked", async () => {
    const checking = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", verifying: true, verified_by: undefined });
    await renderCard([TURBO, checking]);
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.states.verifying")]);
    expect(rowMenuItems("whisper-small")).toEqual([t("engines:local.details.open")]);
  });

  it("says a model was installed by hand in its details", async () => {
    await renderCard([{ ...TURBO, location: "legacy" }]);
    expect(within(row("whisper-turbo")).queryByText(t("engines:local.manual"))).toBeNull();
    const details = openDetails("whisper-turbo");
    expect(within(details).getByText(new RegExp(t("engines:local.manual")))).toBeInTheDocument();
  });

  it("keeps the voice detector as one supporting line, not as a choice", async () => {
    await renderCard([TURBO, VAD]);
    expect(screen.getByText(t("engines:local.auxiliaryLine", { name: "silero-vad", state: t("engines:local.states.installed") }))).toBeInTheDocument();
    expect(screen.queryByRole("listitem", { name: "silero-vad" })).toBeNull();
    expect(screen.queryByRole("button", { name: t("engines:local.useLabel", { name: "silero-vad" }) })).toBeNull();
  });

  it("offers to install the voice detector when it is missing", async () => {
    await renderCard([TURBO, available({ id: "silero-vad", kind: "auxiliary", size: 2_000_000 })]);
    expect(screen.getByText(t("engines:local.auxiliaryLine", { name: "silero-vad", state: t("engines:local.states.available") }))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("engines:local.installLabel", { id: "silero-vad" }) })).toBeEnabled();
  });

  it("lists the active model first, then the installed ones, then files to check, then the ones to install", async () => {
    const base = model({ id: "whisper-base", size: 142_000_000 });
    const odd = model({ id: "whisper-odd", state: "unverified", availability: "present_unverified", verified_by: undefined });
    const tiny = available({ id: "whisper-tiny", size: 75_000_000 });
    await renderCard([SMALL, tiny, odd, base, TURBO]);
    expect(shownOrder()).toEqual([
      "engines-model-transcription-whisper-turbo",
      "engines-model-transcription-whisper-base",
      "engines-model-transcription-whisper-odd",
      "engines-model-transcription-whisper-small",
      "engines-model-transcription-whisper-tiny",
    ]);
  });

  it("follows the saved choice: a pinned model goes first", async () => {
    await renderCard([{ ...TURBO, active: false }, SMALL_INSTALLED], {}, { selection: { external: false, key: "local:whisper-small" } });
    expect(shownOrder()[0]).toBe("engines-model-transcription-whisper-small");
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.active")]);
    expect(tagsOf("whisper-turbo")).toEqual([]);
  });

  it("opens the menu from the keyboard and returns focus to it when «Detalles» closes", async () => {
    await renderCard([TURBO]);
    const trigger = within(row("whisper-turbo")).getByRole("button", { name: t("engines:local.moreLabel", { name: "whisper-turbo" }) });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(menuItem(t("engines:local.verify"))).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "End" });
    expect(menuItem(t("engines:local.details.open"))).toHaveFocus();
    fireEvent.click(menuItem(t("engines:local.details.open")));
    const dialog = screen.getByRole("dialog", { name: t("engines:local.details.title", { name: "whisper-turbo" }) });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("groups the options by process: only the models of this process are listed", async () => {
    const summary = model({ id: "qwen-9b", process: "summary", engine: "llama.cpp" });
    await renderCard([TURBO, summary, SENKO]);
    expect(screen.getAllByRole("listitem").map((item) => item.getAttribute("aria-labelledby"))).toEqual(["engines-model-transcription-whisper-turbo"]);
  });
});

describe("external choice beside the local ones", () => {
  it("offers the external choice in the same card and hands it to the engine selector", async () => {
    const onChoose = vi.fn();
    await renderCard([TURBO], {}, { external: { onChoose } });
    const group = screen.getByRole("region", { name: t("engines:local.external.title") });
    expect(within(group).getByText(t("engines:local.external.help"))).toBeInTheDocument();
    fireEvent.click(within(group).getByRole("button", { name: t("engines:local.external.choose") }));
    expect(onChoose).toHaveBeenCalledOnce();
  });

  it("points to the provider setup when no provider can serve the process", async () => {
    const onSetup = vi.fn();
    await renderCard([TURBO], {}, { external: { hasProviders: false, onSetup } });
    fireEvent.click(screen.getByRole("button", { name: t("engines:local.external.setup") }));
    expect(onSetup).toHaveBeenCalledOnce();
  });
});

describe("install", () => {
  it("follows the download with a status region, then shows the model installed", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push(
      { bytes_done: 250 },
      { bytes_done: 600 },
      { state: "done", bytes_done: 1000, result: "installed" },
    );
    installFromMenu("whisper-small");
    const status = await screen.findByText(t("engines:local.installing", { id: "whisper-small", percent: 0 }));
    expect(status).toHaveAttribute("role", "status");
    expect(screen.getByRole("progressbar", { name: t("engines:local.progressLabel", { id: "whisper-small" }) })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(t("engines:local.installing", { id: "whisper-small", percent: 25 }))).toBeInTheDocument());
    expect(await screen.findByText(t("engines:local.outcome.installed", { id: "whisper-small" }))).toBeInTheDocument();
    await waitFor(() => expect(tagsOf("whisper-small")).toEqual([]));
    expect(screen.queryByRole("progressbar")).toBeNull();
    openRowMenu("whisper-small");
    expect(menuItem(t("engines:local.use"))).toBeInTheDocument();
  });

  it("keeps other installs closed while one job runs", async () => {
    await renderCard([TURBO, SMALL, available({ id: "whisper-base", size: 142_000_000 })]);
    backend.jobAnswers.push({ bytes_done: 100 });
    installFromMenu("whisper-small");
    await screen.findByRole("progressbar");
    openRowMenu("whisper-base");
    expect(menuItem(INSTALL())).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText(t("engines:local.busy"))).toBeInTheDocument();
  });

  it("cancels the download", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 100 });
    installFromMenu("whisper-small");
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.cancelLabel", { id: "whisper-small" }) }));
    expect(await screen.findByText(t("engines:local.outcome.cancelled"))).toBeInTheDocument();
    expect(backend.calls.some((call) => call.method === "POST" && call.path.endsWith("/cancel"))).toBe(true);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.available")]);
  });

  it("explains an invalid hash and leaves the model available", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ state: "failed", error: "hash_mismatch" });
    installFromMenu("whisper-small");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(t("engines:local.jobErrors.hash_mismatch"));
    expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.available")]);
  });

  it("states how much space is missing when the host refuses for lack of disk", async () => {
    await renderCard([TURBO, SMALL]);
    backend.refusals.set("POST /local/models/whisper-small/install", backend.json({
      detail: "insufficient_disk", needed_bytes: 688_849_434, free_bytes: 300_000_000,
    }, 507));
    installFromMenu("whisper-small");
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:local.insufficientDisk", { needed: "689 MB", free: "300 MB" }));
    expect(screen.queryByRole("progressbar")).toBeNull();
    openRowMenu("whisper-small");
    expect(menuItem(INSTALL())).not.toHaveAttribute("aria-disabled");
  });

  it("stops asking about the job when the card goes away", async () => {
    const view = await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 100 });
    installFromMenu("whisper-small");
    await waitFor(() => expect(jobLooks()).toBeGreaterThanOrEqual(2));
    view.unmount();
    const looksAtUnmount = jobLooks();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 8));
    expect(jobLooks()).toBeLessThanOrEqual(looksAtUnmount + 1);
  });

  it("gives up after repeated failed looks instead of asking forever", async () => {
    await renderCard([TURBO, SMALL]);
    installFromMenu("whisper-small");
    await screen.findByRole("progressbar");
    backend.refusals.set(`GET /local/jobs/${"a".repeat(32)}`, backend.json({ detail: "host_unavailable" }, 503));
    expect(await screen.findByText(t("engines:local.outcome.lost"))).toBeInTheDocument();
    const looks = jobLooks();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 6));
    expect(jobLooks()).toBe(looks);
  });

  it("picks up a download that was already running when the screen opened", async () => {
    backend = fakeBackend([TURBO, SMALL]);
    backend.job.current = {
      id: "a".repeat(32), model_id: "whisper-small", type: "install", state: "running", bytes_done: 500, bytes_total: 1000, error: null, result: null,
    };
    backend.jobAnswers.push({ bytes_done: 500 });
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({})} />);
    expect(await screen.findByRole("progressbar", { name: t("engines:local.progressLabel", { id: "whisper-small" }) })).toBeInTheDocument();
  });
});

describe("the speaker runtime as a downloadable component", () => {
  const runtime = (overrides: Partial<LocalModel> = {}) =>
    available({
      id: "diar-runtime", process: "diarization", kind: "component", engine: "senko", size: 251_532_143, min_ram_gib: 0,
      default: true, recommended: true, version: "0.1.0",
      install: {
        method: "download", managed_by: null, download_bytes: 251_532_143, disk_required_bytes: 1_161_762_376,
        fits_on_disk: true, source_available: true,
      },
      ...overrides,
    });
  const title = () => t("engines:local.managedTitle.diarization");

  it("installs it like a model, under the engine's plain name", async () => {
    await renderCard([runtime()], {}, { process: "diarization" });
    expect(within(row(title())).getByText(t("engines:local.short.speakers"))).toBeInTheDocument();
    const details = openDetails(title());
    expect(within(details).getByText(t("engines:local.componentHow"))).toBeInTheDocument();
    expect(within(details).getByText("diar-runtime")).toBeInTheDocument();
    fireEvent.click(within(details).getByRole("button", { name: t("engines:local.details.close") }));
    backend.jobAnswers.push({ state: "done", bytes_done: 1000, result: "installed" });
    installFromMenu(title());
    expect(await screen.findByText(t("engines:local.outcome.installed", { id: "diar-runtime" }))).toBeInTheDocument();
    expect(backend.calls).toContainEqual({ method: "POST", path: "/local/models/diar-runtime/install" });
  });

  it("says it is not available yet, without an install button, when there is no download place", async () => {
    const unpublished = runtime({
      install: {
        method: "download", managed_by: null, download_bytes: 251_532_143, disk_required_bytes: 1_161_762_376,
        fits_on_disk: true, source_available: false,
      },
    });
    await renderCard([unpublished], {}, { process: "diarization" });
    expect(within(row(title())).getByText(t("engines:local.short.unpublished"))).toBeInTheDocument();
    expect(tagsOf(title())).toEqual([]);
    expect(rowMenuItems(title())).toEqual([t("engines:local.details.open")]);
  });

  it("offers to install the new version over an older one", async () => {
    const older = runtime({ state: "unverified", availability: "present_unverified", reason: "outdated", location: "models_dir" });
    await renderCard([older], {}, { process: "diarization" });
    expect(within(row(title())).getByText(t("engines:local.unverifiedReason.outdated"))).toBeInTheDocument();
    openRowMenu(title());
    expect(menuItem(INSTALL())).not.toHaveAttribute("aria-disabled");
  });
});

describe("verify and remove", () => {
  it("verifies from the row menu and reports an intact file", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    backend.jobAnswers.push({ state: "done", result: "verified", bytes_done: 1000 });
    openRowMenu("whisper-small");
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.verify") }));
    expect(await screen.findByText(t("engines:local.outcome.verified", { id: "whisper-small" }))).toBeInTheDocument();
  });

  it("reports a damaged file after verifying", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    backend.jobAnswers.push({ state: "done", result: "corrupt", bytes_done: 1000 });
    openRowMenu("whisper-small");
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.verify") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:local.outcome.corrupt", { id: "whisper-small" }));
  });

  it("blocks removal while a process uses the model, and says which", async () => {
    await renderCard([TURBO]);
    openRowMenu("whisper-turbo");
    const remove = screen.getByRole("menuitem", { name: t("engines:local.remove") });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAttribute("title", t("engines:local.removeBlocked", { list: "Transcripción" })); // spanish-sample-data
    expect(within(screen.getByRole("menu")).getByText(t("engines:local.removeBlocked", { list: "Transcripción" }))).toBeInTheDocument(); // spanish-sample-data
    fireEvent.click(remove);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("never removes a model installed by hand, and says Sauri does not delete it", async () => {
    await renderCard([TURBO, { ...SMALL_INSTALLED, location: "legacy" }]);
    openRowMenu("whisper-small");
    const remove = screen.getByRole("menuitem", { name: t("engines:local.remove") });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAttribute("title", t("engines:local.manualNote"));
    expect(within(screen.getByRole("menu")).getByText(t("engines:local.manualNote"))).toBeInTheDocument();
  });

  it("explains a refusal from the host when the model became in use meanwhile", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    backend.refusals.set("DELETE /local/models/whisper-small", backend.json({ detail: "model_in_use", processes: ["transcription"] }, 409));
    openRowMenu("whisper-small");
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.remove") }));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.removeConfirm") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:local.modelInUse", { list: "Transcripción" })); // spanish-sample-data
  });

  it("explains a legacy refusal from the host", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    backend.refusals.set("DELETE /local/models/whisper-small", backend.json({ detail: "legacy_location" }, 409));
    openRowMenu("whisper-small");
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.remove") }));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.removeConfirm") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:local.manualNote"));
  });

  it("lets an installed model that no process uses be removed", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    openRowMenu("whisper-small");
    const remove = menuItem(t("engines:local.remove"));
    expect(remove).not.toHaveAttribute("aria-disabled");
    expect(remove).not.toHaveAttribute("title");
  });

  it("asks before removing, and removes only after the confirmation", async () => {
    await renderCard([TURBO, SMALL_INSTALLED]);
    openRowMenu("whisper-small");
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.remove") }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(t("engines:local.removeBody", { id: "whisper-small", size: "190 MB" }))).toBeInTheDocument();
    expect(backend.calls.some((call) => call.method === "DELETE")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:local.removeCancel") }));
    expect(backend.calls.some((call) => call.method === "DELETE")).toBe(false);

    openRowMenu("whisper-small");
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.remove") }));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.removeConfirm") }));
    expect(await screen.findByText(t("engines:local.outcome.removed", { id: "whisper-small" }))).toBeInTheDocument();
    await waitFor(() => expect(tagsOf("whisper-small")).toEqual([t("engines:local.tags.available")]));
  });
});

describe("models that were already there", () => {
  it("says what it is doing while files are recognized, then shows them as installed", async () => {
    const checking = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", verifying: true, verified_by: undefined });
    await renderCard([TURBO, checking]);
    expect(screen.getByText(t("engines:local.adoption.recognizing"))).toBeInTheDocument();
    Object.assign(backend.catalog[1], { verifying: false, state: "installed", availability: "installed", verified_by: "hash" });
    await waitFor(() => expect(tagsOf("whisper-small")).toEqual([]));
    expect(screen.queryByText(t("engines:local.adoption.recognizing"))).toBeNull();
  });

  it("stops looking at the catalog once nothing is being recognized", async () => {
    const checking = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", verifying: true, verified_by: undefined });
    await renderCard([TURBO, checking]);
    Object.assign(backend.catalog[1], { verifying: false });
    await waitFor(() => expect(screen.queryByText(t("engines:local.adoption.recognizing"))).toBeNull());
    const reads = catalogReads();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 6));
    expect(catalogReads()).toBe(reads);
  });

  it("explains calmly when a file could not be confirmed", async () => {
    const odd = model({ id: "whisper-small", state: "unverified", availability: "present_unverified", reason: "hash_mismatch", verified_by: undefined });
    await renderCard([TURBO, odd], { adoption: { job_id: "c".repeat(32), outcomes: { "whisper-small": "present_unverified", "whisper-turbo": "adopted" } } });
    expect(screen.getByText(t("engines:local.adoption.attention"))).toBeInTheDocument();
  });

  it("says nothing about it when every file was recognized", async () => {
    await renderCard([TURBO], { adoption: { job_id: "c".repeat(32), outcomes: { "whisper-turbo": "adopted" } } });
    expect(screen.queryByText(t("engines:local.adoption.attention"))).toBeNull();
  });

  it("looks for installed models only from the card menu, and follows the run", async () => {
    await renderCard([TURBO, SMALL]);
    expect(screen.queryByRole("button", { name: t("engines:local.scan") })).toBeNull();
    backend.jobAnswers.push({ bytes_done: 0 }, { state: "done", result: "adopted" });
    fireEvent.click(screen.getByRole("button", { name: t("engines:local.cardMenu") }));
    fireEvent.click(screen.getByRole("menuitem", { name: t("engines:local.scan") }));
    expect(await screen.findByText(t("engines:local.adoption.recognizing"))).toBeInTheDocument();
    expect(await screen.findByText(t("engines:local.adoption.done"))).toBeInTheDocument();
    expect(backend.calls.some((call) => call.method === "POST" && call.path === "/local/adopt")).toBe(true);
  });
});

describe("managed engines", () => {
  it("shows the speaker engine as installed and active now, with no download button", async () => {
    backend = fakeBackend([SENKO]);
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({ process: "diarization" })} />);
    await screen.findByRole("list", { name: t("engines:local.modelsTitle") });
    const name = t("engines:local.managedTitle.diarization");
    expect(tagsOf(name)).toEqual([t("engines:local.tags.active")]);
    expect(rowMenuItems(name)).toEqual([t("engines:local.details.open")]);
    fireEvent.click(menuItem(t("engines:local.details.open")));
    const details = screen.getByRole("dialog", { name: t("engines:local.details.title", { name }) });
    expect(within(details).getByText(`${t("engines:local.states.installed")} · ${t("engines:local.states.active")}`)).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.verifiedBy.presence"))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.managedInstalled"))).toBeInTheDocument();
  });

  it("shows the command that installs the engine when it is missing", async () => {
    const missing = {
      ...SENKO, state: "not_installed" as const, availability: "available" as const, active: false, in_use: false, in_use_by: [],
      location: null, verified_by: undefined,
      install: { method: "managed_command" as const, managed_by: "scripts/engines/install-diar-engine.sh", download_bytes: null, disk_required_bytes: null, fits_on_disk: null },
    };
    backend = fakeBackend([missing]);
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({ process: "diarization" })} />);
    await screen.findByRole("list", { name: t("engines:local.modelsTitle") });
    const name = t("engines:local.managedTitle.diarization");
    expect(within(row(name)).getByText(t("engines:local.short.managedHow"))).toBeInTheDocument();
    expect(tagsOf(name)).toEqual([t("engines:local.tags.available")]);
    expect(rowMenuItems(name)).toEqual([t("engines:local.details.open")]);
    fireEvent.click(menuItem(t("engines:local.details.open")));
    expect(within(screen.getByRole("dialog")).getByText(t("engines:local.managedHow", { command: "bash scripts/engines/install-diar-engine.sh" }))).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });
});

describe("Parakeet as the preferred transcription model", () => {
  const PARAKEET_ID = "parakeet-tdt-0.6b-v3-ultra-coreml";
  const parakeet = (overrides: Partial<LocalModel> = {}) => model({
    id: PARAKEET_ID, engine: "fluidaudio", size: 632_314_500, installed_size: 632_314_500, min_ram_gib: 8,
    preferred: true, needs: "fluidaudio-cli", needs_ready: true, license: "CC-BY-4.0",
    attribution: "Parakeet-TDT-0.6B-v3 by NVIDIA (CC-BY-4.0)", active: true, in_use: true, in_use_by: ["transcription"],
    ...overrides,
  });
  const whisper = (overrides: Partial<LocalModel> = {}) => model({ ...TURBO, active: false, ...overrides });

  it("marks Parakeet active with a short note, and keeps the long note and the CC-BY-4.0 attribution under «Detalles»", async () => {
    await renderCard([whisper(), parakeet()]);
    expect(shownOrder()).toEqual([`engines-model-transcription-${PARAKEET_ID}`, "engines-model-transcription-whisper-turbo"]);
    expect(tagsOf(PARAKEET_ID)).toEqual([t("engines:local.tags.active")]);
    const card = row(PARAKEET_ID);
    expect(within(card).getByText(t("engines:local.short.parakeet"))).toBeInTheDocument();
    expect(within(card).queryByText(t("engines:local.modelNotes.parakeet"))).toBeNull();
    expect(within(card).queryByText(/CC-BY-4.0/)).toBeNull();
    const details = openDetails(PARAKEET_ID);
    expect(within(details).getByText(t("engines:local.modelNotes.parakeet"))).toBeInTheDocument();
    expect(within(details).getByText(t("engines:local.license", { license: "CC-BY-4.0", attribution: "Parakeet-TDT-0.6B-v3 by NVIDIA (CC-BY-4.0)" }))).toBeInTheDocument();
  });

  it("shows an installed Whisper beside Parakeet as an ordinary alternative: no tag, a plain note and «Usar este»", async () => {
    const onUse = vi.fn();
    await renderCard([parakeet(), whisper({ in_use: false, in_use_by: [] })], {}, { onUse });
    expect(tagsOf("whisper-turbo")).toEqual([]);
    const card = row("whisper-turbo");
    expect(within(card).getByText(t("engines:local.short.whisper"))).toBeInTheDocument();
    expect(within(card).queryByText(/Respaldo|Fallback/)).toBeNull();
    expect(rowMenuItems("whisper-turbo")).toEqual([
      t("engines:local.use"), t("engines:local.verify"), t("engines:local.remove"), t("engines:local.details.open"),
    ]);
    expect(menuItem(t("engines:local.remove"))).not.toHaveAttribute("aria-disabled");
    fireEvent.click(menuItem(t("engines:local.details.open")));
    const details = screen.getByRole("dialog");
    expect(within(details).getByText(t("engines:local.modelNotes.whisper"))).toBeInTheDocument();
    expect(within(details).queryByText(/Respaldo|respaldo|Fallback|fallback/)).toBeNull();
    fireEvent.click(within(details).getByRole("button", { name: t("engines:local.details.close") }));
    openRowMenu("whisper-turbo");
    fireEvent.click(menuItem(t("engines:local.use")));
    expect(onUse).toHaveBeenCalledWith("local:whisper-turbo");
  });

  it("goes back to the recommended choice from Whisper: Parakeet is local:default, Whisper is pinned by its id", async () => {
    const onUse = vi.fn();
    await renderCard([parakeet({ active: false, in_use: false, in_use_by: [] }), whisper({ active: true })], {}, { onUse, selection: { external: false, key: "local:whisper-turbo" } });
    // Pinned to Whisper: Whisper is the active one, listed first, and Parakeet is offered.
    expect(shownOrder()[0]).toBe("engines-model-transcription-whisper-turbo");
    expect(tagsOf("whisper-turbo")).toEqual([t("engines:local.tags.active")]);
    openRowMenu(PARAKEET_ID);
    fireEvent.click(menuItem(t("engines:local.use")));
    expect(onUse).toHaveBeenCalledWith("local:default");
  });

  const fluidaudio = (overrides: Partial<LocalModel> = {}) => model({
    id: "fluidaudio-cli", kind: "managed_engine", engine: "fluidaudio", size: null, installed_size: null, state: "managed",
    location: "managed", verified_by: "presence", managed_by: "scripts/engines/install-parakeet-engine.sh", ...overrides,
  });

  it("shows Parakeet's engine as one supporting line, never as a model to use", async () => {
    const onUse = vi.fn();
    await renderCard([parakeet(), whisper(), fluidaudio()], {}, { onUse });
    const name = t("engines:local.managedTitle.transcription");
    expect(screen.queryByRole("listitem", { name })).toBeNull();
    expect(screen.queryByRole("button", { name: t("engines:local.useLabel", { name }) })).toBeNull();
    expect(screen.getByText(t("engines:local.engineLine", { name, state: t("engines:local.states.installed") }))).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").map((item) => item.getAttribute("aria-labelledby"))).toEqual([
      `engines-model-transcription-${PARAKEET_ID}`, "engines-model-transcription-whisper-turbo",
    ]);
  });

  it("does not call Parakeet active, nor offer it, while its engine is missing, and says how to install the engine", async () => {
    const engine = model({
      id: "fluidaudio-cli", kind: "managed_engine", engine: "fluidaudio", size: null, installed_size: null, state: "not_installed",
      availability: "available", location: null, verified_by: undefined, managed_by: "scripts/engines/install-parakeet-engine.sh",
      install: { method: "managed_command", managed_by: "scripts/engines/install-parakeet-engine.sh", download_bytes: null, disk_required_bytes: null, fits_on_disk: null },
    });
    await renderCard([parakeet({ needs_ready: false, active: false }), whisper({ active: true }), engine]);
    expect(tagsOf(PARAKEET_ID)).toEqual([]);
    expect(within(row(PARAKEET_ID)).getByText(t("engines:local.short.needsEngine"))).toBeInTheDocument();
    expect(tagsOf("whisper-turbo")).toEqual([t("engines:local.tags.active")]);
    openRowMenu(PARAKEET_ID);
    expect(queryMenuItem(t("engines:local.use"))).toBeNull();
    fireEvent.click(menuItem(t("engines:local.details.open")));
    expect(within(screen.getByRole("dialog")).getByText(t("engines:local.needsEngine", { command: "bash scripts/engines/install-parakeet-engine.sh" }))).toBeInTheDocument();
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

  it("tells the person to reopen Sauri and where the logs are when an engine does not answer, without terminal commands", async () => {
    await renderCard([TURBO], { engineState: "stopped" });
    const missing = screen.getByRole("region", { name: t("engines:local.engineMissing.desktopTitle") });
    expect(within(missing).getByText(t("engines:local.engineMissing.desktopBody", { engine: t("engines:local.engineNames.transcription") }))).toBeInTheDocument();
    expect(within(missing).getByText(t("engines:local.engineMissing.desktopWait"))).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: t("engines:local.engineMissing.title") })).toBeNull();
    noTerminal();
  });

  it("says the same when the service that manages models does not answer", async () => {
    backend = fakeBackend([TURBO], { hostDown: true });
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard {...cardProps({})} />);
    const missing = await screen.findByRole("region", { name: t("engines:local.engineMissing.desktopTitle") });
    expect(within(missing).getByText(t("engines:local.engineMissing.desktopHostBody"))).toBeInTheDocument();
    noTerminal();
  });

  it("never asks to run an install script for Parakeet's engine or the speaker engine", async () => {
    const parakeet = model({ id: "parakeet-tdt-0.6b-v3-ultra-coreml", engine: "fluidaudio", preferred: true, needs: "fluidaudio-cli", needs_ready: false });
    const engine = model({
      id: "fluidaudio-cli", kind: "managed_engine", engine: "fluidaudio", size: null, installed_size: null, state: "not_installed",
      availability: "available", location: null, managed_by: "scripts/engines/install-parakeet-engine.sh",
      install: { method: "managed_command", managed_by: "scripts/engines/install-parakeet-engine.sh", download_bytes: null, disk_required_bytes: null, fits_on_disk: null },
    });
    await renderCard([parakeet, TURBO, engine]);
    expect(within(row(parakeet.id)).getByText(t("engines:local.needsEngineDesktop"))).toBeInTheDocument();
    expect(screen.getByText(t("engines:local.managedDesktop"))).toBeInTheDocument();
    noTerminal();
    cleanup();
    const senko = { ...SENKO, state: "not_installed" as const, availability: "available" as const, active: false, in_use: false, in_use_by: [],
      location: null, install: { method: "managed_command" as const, managed_by: "scripts/engines/install-diar-engine.sh", download_bytes: null, disk_required_bytes: null, fits_on_disk: null } };
    await renderCard([senko], {}, { process: "diarization" });
    expect(screen.getByText(t("engines:local.managedDesktop"))).toBeInTheDocument();
    noTerminal();
  });
});

describe("in English", () => {
  beforeEach(() => setLanguage("en", { persist: false }));
  afterEach(() => setLanguage("es", { persist: false }));

  it("shows the same card with English tags, menu and details", async () => {
    await renderCard([TURBO, SMALL]);
    expect(tagsOf("whisper-turbo")).toEqual(["Active"]);
    expect(tagsOf("whisper-small")).toEqual(["Available"]);
    expect(screen.getByText("Mac with an Apple chip, 24 GB of memory, 120 GB free.")).toBeInTheDocument();
    expect(rowMenuItems("whisper-small")).toEqual(["Install (needs 689 MB)", "Details"]);
    fireEvent.click(menuItem("Details"));
    expect(screen.getByRole("dialog", { name: "Details of “whisper-small”" })).toBeInTheDocument();
  });
});
