// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  EngineKindInfo,
  EngineProcess,
  EngineProcessState,
  EngineProvider,
  EngineProviderKind,
  LocalModel,
} from "@sauri/shared-types";
import { ProcessSettings } from "./settings/ProcessSettings";
import { t } from "../i18n";


function kindInfo(kind: EngineProviderKind, processes: EngineProcess[]): EngineKindInfo {
  return {
    kind,
    default_base_url: `https://api.${kind}.example/v1`,
    key_required: true,
    auth: "key",
    linkable: true,
    capabilities: processes.map((capability) => ({ capability, transport: "openai-chat", verified_on: "2026-11-16" })),
  };
}

const KINDS: EngineKindInfo[] = [
  kindInfo("openai", ["transcription", "summary"]),
  kindInfo("deepgram", ["transcription", "diarization"]),
  kindInfo("anthropic", ["summary"]),
];

function provider(id: string, label: string, kind: EngineProviderKind, overrides: Partial<EngineProvider> = {}): EngineProvider {
  return {
    id, kind, label,
    base_url: `https://api.${kind}.example/v1`,
    enabled: true, status: "active", key_set: true, key_hint: "1234", key_set_at: null,
    used_by: [], created_at: "2026-11-16T10:00:00Z", updated_at: "2026-11-16T10:00:00Z",
    ...overrides,
  };
}

function localState(capability: EngineProcess): EngineProcessState {
  return {
    capability, provider_id: null, provider_kind: null, provider_label: null, model: "local:default",
    local_fallback: true, configured: false, version: 0, updated_at: null, notice_version: null,
  };
}

function localModel(overrides: Partial<LocalModel> & Pick<LocalModel, "id" | "process">): LocalModel {
  return {
    kind: "model", engine: "whisper.cpp", size: 190_000_000, min_ram_gib: 4, requires: [], status: "proposal",
    default: false, managed_by: null, recommended: false, in_use_by: [], state: "not_installed",
    installed_size: null, installed_at: null, ...overrides,
  };
}

interface Call { method: string; path: string; search: string; body: Record<string, unknown> | null }

interface Setup {
  providers?: EngineProvider[];
  processes?: EngineProcessState[];
  models?: LocalModel[];
  /** Providers that already hold consent for the process they serve. */
  consents?: string[];
}

function fakeBackend(setup: Setup = {}) {
  const providers = setup.providers ?? [provider("p1", "Work OpenAI", "openai"), provider("p2", "Deepgram", "deepgram")];
  const processes = (setup.processes ?? (["transcription", "diarization", "summary"] as const).map(localState)).map((entry) => ({ ...entry }));
  const consents = new Set(setup.consents ?? []);
  const calls: Call[] = [];
  const failing = new Set<string>();
  const catalogs: Record<string, unknown> = {
    p1: { models: [{ id: "gpt-a", label: null, serves: ["summary"] }, { id: "gpt-b", label: null, serves: ["summary"] }], starter: "gpt-a", from_cache: true, fetched_at: null, manual_entry: false, error_class: null, serves: ["summary"] },
  };
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/engines", "") || "/";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, path, search: url.search, body });
    if (failing.has(`${method} ${path}`)) return json({ detail: "boom" }, 500);

    if (path === "/capabilities") return json({ notice_versions: { transcription: 1, diarization: 1, summary: 1 }, kinds: KINDS });
    if (path === "/providers") return json(providers);
    if (path === "/processes") return json(processes);
    if (path === "/local/hardware") return json({ arch: "arm64", system: "Darwin", memory_gib: 16, cores: 8, metal: true, disk_free_bytes: 100e9 });
    if (path === "/local/models") {
      return json({ catalog_version: 1, models: setup.models ?? [], recommendations: {}, active_job: null });
    }
    if (path === "/status") return json({ engines: [{ id: "asr", port: 8001, state: "running" }, { id: "diar", port: 8002, state: "running" }, { id: "llm", port: 8003, state: "running" }], secret_store: null });

    const models = /^\/providers\/([^/]+)\/models$/.exec(path);
    if (models && method === "GET") {
      return json(catalogs[models[1]] ?? { models: [], starter: null, from_cache: false, fetched_at: null, manual_entry: true, error_class: "provider_unavailable" });
    }
    const notice = /^\/processes\/([^/]+)\/notice$/.exec(path);
    if (notice && method === "GET") {
      const providerId = url.searchParams.get("provider_id")!;
      const owner = providers.find((item) => item.id === providerId)!;
      return json({
        capability: notice[1], provider_id: providerId, provider_kind: owner.kind, provider_name: owner.label,
        address: owner.base_url, notice_version: 1, title: "Notice title",
        paragraphs: ["Content of the meetings will be sent.", "Usage is billed to your account."],
      });
    }
    const put = /^\/processes\/([^/]+)$/.exec(path);
    if (put && method === "PUT") {
      const capability = put[1] as EngineProcess;
      const index = processes.findIndex((entry) => entry.capability === capability);
      const providerId = body?.provider_id as string | null;
      if (providerId && !consents.has(`${capability}:${providerId}`)) {
        if (body?.notice_version === undefined) return json({ detail: "notice_required" }, 422);
        consents.add(`${capability}:${providerId}`);
      }
      const owner = providers.find((item) => item.id === providerId);
      processes[index] = {
        ...processes[index], provider_id: providerId, provider_kind: owner?.kind ?? null, provider_label: owner?.label ?? null,
        model: String(body?.model), local_fallback: body?.local_fallback !== false, configured: true,
        version: processes[index].version + 1, notice_version: providerId ? 1 : null,
      };
      return json(processes[index]);
    }
    return json({ detail: "unexpected" }, 404);
  });
  return { handler, calls, failing, catalogs };
}

let backend: ReturnType<typeof fakeBackend>;

const TRIGGER = new RegExp(t("engines:process.engineLabel"));

async function renderReady(process: EngineProcess, setup: Setup = {}) {
  backend = fakeBackend(setup);
  vi.stubGlobal("fetch", backend.handler);
  render(<ProcessSettings process={process} />);
  await screen.findByRole("button", { name: TRIGGER });
}

const trigger = () => screen.getByRole("button", { name: TRIGGER });
const writes = () => backend.calls.filter((call) => call.method === "PUT");
const panel = () => screen.getByRole("dialog", { name: t("engines:process.pickerPanel") });

function openPicker() {
  fireEvent.click(trigger());
  return panel();
}

/** Opens the picker and clicks the option whose name matches. */
async function pick(name: RegExp | string) {
  if (!screen.queryByRole("dialog", { name: t("engines:process.pickerPanel") })) openPicker();
  fireEvent.click(await screen.findByRole("option", { name }));
}

beforeEach(() => {
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

const external = (capability: EngineProcess, id = "p1", label = "Work OpenAI", kind: EngineProviderKind = "openai", model = "gpt-a"): EngineProcessState => ({
  ...localState(capability), provider_id: id, provider_kind: kind, provider_label: label, model, configured: true,
});

describe("what a process uses today", () => {
  it("says it uses the local engine and that nothing leaves the computer", async () => {
    await renderReady("transcription");
    expect(screen.getByText(t("engines:process.current", { name: t("engines:process.localName") }))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.badgeLocal"))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.staysHere"))).toBeInTheDocument();
    expect(trigger()).toHaveTextContent(t("engines:process.localRecommended"));
  });

  it("names the provider, the model and what is sent when the process is external", async () => {
    await renderReady("summary", {
      processes: [localState("transcription"), localState("diarization"), external("summary", "p1", "Work OpenAI", "openai", "gpt-b")],
      consents: ["summary:p1"],
    });
    expect(screen.getByText(t("engines:process.current", { name: t("engines:process.externalName", { provider: "Work OpenAI", model: "gpt-b" }) }))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.badgeExternal"))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.leaves", { provider: "Work OpenAI", what: t("engines:process.sends.summary") }))).toBeInTheDocument();
    expect(trigger()).toHaveTextContent("Work OpenAI");
    expect(trigger()).toHaveTextContent("gpt-b");
  });
});

describe("engine and model picker", () => {
  it("is a popover button that opens a named dialog with search, and reports its state", async () => {
    await renderReady("transcription");
    expect(trigger()).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    openPicker();
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(within(panel()).getByRole("searchbox", { name: t("engines:process.pickerSearch") })).toHaveFocus();
    expect(within(panel()).getByRole("listbox", { name: t("engines:process.pickerList") })).toBeInTheDocument();
  });

  it("lists the local recommendation and installed models first, then one group per compatible provider", async () => {
    await renderReady("transcription", {
      models: [
        localModel({ id: "whisper-turbo", process: "transcription", default: true, state: "installed", size: 574_000_000 }),
        localModel({ id: "whisper-small", process: "transcription", state: "installed" }),
        localModel({ id: "whisper-base", process: "transcription", state: "not_installed" }),
        localModel({ id: "qwen-4b", process: "summary", engine: "llama.cpp", state: "installed" }),
      ],
    });
    await waitFor(() => expect(backend.calls.some((call) => call.path === "/local/models")).toBe(true));
    openPicker();
    await screen.findByRole("option", { name: /whisper-small/ });
    await screen.findByRole("option", { name: /gpt-a/ });
    const groups = within(panel()).getAllByRole("group").map((group) => group.getAttribute("aria-labelledby"));
    expect(groups).toHaveLength(3);
    const names = within(panel()).getAllByRole("group").map((group) => within(group).queryAllByRole("option").map((item) => item.textContent));
    expect(names[0][0]).toContain(t("engines:process.localRecommended"));
    expect(names[0][1]).toContain("whisper-small");
    expect(names[0][1]).toContain("190 MB");
    // Not installed, another process and the default model (already «Local (recomendado)») are not repeated.
    expect(names[0].join("|")).not.toMatch(/whisper-base|qwen-4b|whisper-turbo/);
    expect(within(panel()).getByText("Work OpenAI")).toBeInTheDocument();
    expect(within(panel()).getByText("Deepgram")).toBeInTheDocument();
    // Anthropic does not serve transcription, so it has no group.
    expect(within(panel()).queryByText(/Anthropic/)).toBeNull();
  });

  it("offers only providers that are on, hold a key and serve the process, as /capabilities says", async () => {
    await renderReady("diarization", { providers: [provider("p1", "Work OpenAI", "openai")] });
    openPicker();
    expect(within(panel()).getAllByRole("group")).toHaveLength(1);
    expect(screen.getByText(t("engines:process.noProviders"))).toBeInTheDocument();
    cleanup();

    await renderReady("transcription", {
      providers: [provider("p1", "Off", "openai", { enabled: false, status: "disabled" }), provider("p2", "No key", "deepgram", { status: "no_key", key_set: false })],
    });
    openPicker();
    expect(within(panel()).getAllByRole("group")).toHaveLength(1);
    expect(backend.calls.some((call) => call.path.startsWith("/providers/"))).toBe(false);
  });

  it("asks the providers for their live catalog when it opens, and marks the suggested and the one in use", async () => {
    await renderReady("transcription", {
      processes: [external("transcription", "p1", "Work OpenAI", "openai", "gpt-b"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    expect(backend.calls.some((call) => call.path === "/providers/p1/models")).toBe(false);
    openPicker();
    const suggested = await screen.findByRole("option", { name: /gpt-a/ });
    expect(suggested).toHaveTextContent(t("engines:process.suggested"));
    expect(suggested).toHaveAttribute("aria-selected", "false");
    const inUse = screen.getByRole("option", { name: /gpt-b/ });
    expect(inUse).toHaveTextContent(t("engines:process.inUse"));
    expect(inUse).toHaveAttribute("aria-selected", "true");
    expect(backend.calls.filter((call) => call.path === "/providers/p1/models")[0].search).toBe("?capability=transcription");
  });

  it("filters the options with the search box and says when nothing matches", async () => {
    await renderReady("transcription");
    openPicker();
    await screen.findByRole("option", { name: /gpt-a/ });
    const search = within(panel()).getByRole("searchbox");
    fireEvent.change(search, { target: { value: "gpt-b" } });
    expect(within(panel()).getAllByRole("option")).toHaveLength(1);
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(within(panel()).queryAllByRole("option")).toHaveLength(0);
    expect(within(panel()).getByText(t("engines:process.noMatches"))).toBeInTheDocument();
  });

  it("asks the provider again on «Volver a pedir»", async () => {
    await renderReady("transcription");
    openPicker();
    await screen.findByRole("option", { name: /gpt-a/ });
    fireEvent.click(within(panel()).getByRole("button", { name: t("engines:process.modelsRefreshLabel", { provider: "Work OpenAI" }) }));
    await waitFor(() =>
      expect(backend.calls.some((call) => call.path === "/providers/p1/models" && call.search.includes("refresh=true"))).toBe(true));
  });

  it("lets the person type the model when the list cannot be had, and asks for consent before saving it", async () => {
    await renderReady("transcription");
    openPicker();
    const field = await screen.findByLabelText(t("engines:process.manualModel")); // Deepgram: the fake gives no catalog
    expect(within(panel()).getByText(new RegExp(t("engines:process.modelsFailed")))).toBeInTheDocument();
    expect(within(panel()).getByRole("button", { name: t("engines:process.manualModelUse") })).toBeDisabled();
    fireEvent.change(field, { target: { value: "nova-3" } });
    fireEvent.click(within(panel()).getByRole("button", { name: t("engines:process.manualModelUse") }));
    fireEvent.click(await screen.findByRole("button", { name: t("engines:notice.accept") }));
    await waitFor(() => expect(writes()[0].body).toMatchObject({ provider_id: "p2", model: "nova-3", notice_version: 1 }));
  });

  it("moves through the options with the arrow keys and back to the search box", async () => {
    await renderReady("transcription");
    openPicker();
    await screen.findByRole("option", { name: /gpt-a/ });
    const search = within(panel()).getByRole("searchbox");
    const options = within(panel()).getAllByRole("option");
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(options[0]).toHaveFocus();
    fireEvent.keyDown(options[0], { key: "ArrowDown" });
    expect(options[1]).toHaveFocus();
    fireEvent.keyDown(options[1], { key: "End" });
    expect(options[options.length - 1]).toHaveFocus();
    fireEvent.keyDown(options[options.length - 1], { key: "Home" });
    expect(options[0]).toHaveFocus();
    fireEvent.keyDown(options[0], { key: "ArrowUp" });
    expect(search).toHaveFocus();
  });

  it("opens with ArrowDown on the trigger and closes with Escape, returning focus to it", async () => {
    await renderReady("transcription");
    trigger().focus();
    fireEvent.keyDown(trigger(), { key: "ArrowDown" });
    const search = within(panel()).getByRole("searchbox");
    expect(search).toHaveFocus();
    fireEvent.keyDown(search, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(writes()).toHaveLength(0);
  });

  it("closes on a click outside without choosing anything", async () => {
    await renderReady("transcription");
    openPicker();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toHaveLength(0);
  });
});

describe("privacy notice before an external provider", () => {
  it("shows the notice from the API after choosing a model and saves nothing until it is accepted", async () => {
    await renderReady("transcription");
    await pick(/gpt-a/);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Notice title" })).toBeInTheDocument();
    expect(within(dialog).getByText("Usage is billed to your account.")).toBeInTheDocument();
    expect(within(dialog).getByText(t("engines:notice.address", { address: "https://api.openai.example/v1" }))).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
    expect(screen.getByText(t("engines:process.current", { name: t("engines:process.localName") }))).toBeInTheDocument();
  });

  it("asks for the notice in the portal's language", async () => {
    await renderReady("transcription");
    await pick(/gpt-a/);
    await screen.findByRole("dialog");
    expect(backend.calls.find((call) => call.path.endsWith("/notice"))?.search).toContain("lang=es");
  });

  it("saves nothing when the notice is cancelled, and today's engine does not change", async () => {
    await renderReady("transcription");
    await pick(/gpt-a/);
    fireEvent.click(await screen.findByRole("button", { name: t("engines:notice.cancel") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toHaveLength(0);
    expect(screen.getByText(t("engines:process.current", { name: t("engines:process.localName") }))).toBeInTheDocument();
    expect(trigger()).toHaveTextContent(t("engines:process.localRecommended"));
  });

  it("saves with the notice version once it is accepted", async () => {
    await renderReady("transcription");
    await pick(/gpt-a/);
    fireEvent.click(await screen.findByRole("button", { name: t("engines:notice.accept") }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({
      path: "/processes/transcription",
      body: { provider_id: "p1", model: "gpt-a", local_fallback: true, notice_version: 1 },
    });
    expect(await screen.findByText(t("engines:process.current", { name: t("engines:process.externalName", { provider: "Work OpenAI", model: "gpt-a" }) }))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.badgeExternal"))).toBeInTheDocument();
  });

  it("asks again for a model of a different provider than the one in use", async () => {
    await renderReady("transcription", {
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    openPicker();
    fireEvent.change(await screen.findByLabelText(t("engines:process.manualModel")), { target: { value: "nova-3" } });
    fireEvent.click(within(panel()).getByRole("button", { name: t("engines:process.manualModelUse") }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it("does not repeat the notice when only the model of the same provider changes, and saves at once", async () => {
    await renderReady("transcription", {
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    await pick(/gpt-b/);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ provider_id: "p1", model: "gpt-b", local_fallback: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(backend.calls.some((call) => call.path.endsWith("/notice"))).toBe(false);
    expect(await screen.findByText(t("engines:process.current", { name: t("engines:process.externalName", { provider: "Work OpenAI", model: "gpt-b" }) }))).toBeInTheDocument();
  });

  it("shows the notice if the API says consent is missing for a same-provider save", async () => {
    await renderReady("transcription", {
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: [], // the stored consent is gone (for example the notice version moved on)
    });
    await pick(/gpt-b/);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(writes()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: t("engines:notice.accept") }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1].body).toMatchObject({ notice_version: 1, model: "gpt-b" });
  });

  it("goes back to the local engine at once from the footer, without a notice or a confirmation", async () => {
    await renderReady("transcription", {
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    openPicker();
    fireEvent.click(within(panel()).getByRole("button", { name: t("engines:process.backToLocal") }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ provider_id: null, model: "local:default", local_fallback: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(backend.calls.some((call) => call.path.endsWith("/notice"))).toBe(false);
    expect(await screen.findByText(t("engines:process.current", { name: t("engines:process.localName") }))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.staysHere"))).toBeInTheDocument();
  });

  it("goes back to local at once when «Local (recomendado)» is chosen in the list", async () => {
    await renderReady("transcription", {
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    await pick(new RegExp(t("engines:process.localRecommended").replace(/[()]/g, "\\$&")));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ provider_id: null, model: "local:default" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("disables «Volver al local» while the local default is already in use", async () => {
    await renderReady("transcription");
    openPicker();
    expect(within(panel()).getByRole("button", { name: t("engines:process.backToLocal") })).toBeDisabled();
  });

  it("saves an installed local model as local:<id>", async () => {
    await renderReady("transcription", {
      models: [localModel({ id: "whisper-small", process: "transcription", state: "installed" })],
    });
    await waitFor(() => expect(backend.calls.some((call) => call.path === "/local/models")).toBe(true));
    await pick(/whisper-small/);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ provider_id: null, model: "local:whisper-small" });
    expect(await screen.findByText(t("engines:process.current", { name: t("engines:process.localModelName", { id: "whisper-small" }) }))).toBeInTheDocument();
  });

  it("reports a refused save inside the notice and keeps today's engine", async () => {
    await renderReady("transcription");
    backend.failing.add("PUT /processes/transcription");
    await pick(/gpt-a/);
    fireEvent.click(await screen.findByRole("button", { name: t("engines:notice.accept") }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(t("engines:genericError"));
    expect(screen.getByText(t("engines:process.current", { name: t("engines:process.localName") }))).toBeInTheDocument();
  });
});

const SMALL_INSTALLED = localModel({
  id: "whisper-small", process: "transcription", state: "installed", availability: "installed", active: false, in_use: false,
  location: "models_dir", verified_by: "hash", install: null, installed_size: 190_000_000,
});
const TURBO_ACTIVE = localModel({
  id: "whisper-turbo", process: "transcription", default: true, state: "installed", availability: "installed", active: true, in_use: true,
  in_use_by: ["transcription"], location: "legacy", verified_by: "hash", install: null, size: 574_000_000, installed_size: 574_000_000,
});

describe("local options of the process", () => {
  it("shows the local card of each process with only its own models", async () => {
    const models = [
      TURBO_ACTIVE,
      SMALL_INSTALLED,
      localModel({ id: "qwen-9b", process: "summary", engine: "llama.cpp", state: "installed", availability: "installed", active: true, in_use: true }),
    ];
    await renderReady("summary", { models });
    const card = await screen.findByRole("heading", { name: t("engines:local.title") });
    expect(card).toBeInTheDocument();
    await screen.findByRole("listitem", { name: "qwen-9b" });
    expect(screen.queryByRole("listitem", { name: "whisper-small" })).toBeNull();
    expect(screen.getByRole("listitem", { name: "qwen-9b" })).toHaveTextContent(t("engines:local.states.active"));
  });

  it("saves a local model at once with «Usar este», without a privacy notice, and re-reads which one is active", async () => {
    await renderReady("transcription", { models: [TURBO_ACTIVE, SMALL_INSTALLED] });
    const small = await screen.findByRole("listitem", { name: "whisper-small" });
    const readsBefore = backend.calls.filter((call) => call.path === "/local/models").length;
    fireEvent.click(within(small).getByRole("button", { name: t("engines:local.useLabel", { name: "whisper-small" }) }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ provider_id: null, model: "local:whisper-small" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(backend.calls.some((call) => call.path.endsWith("/notice"))).toBe(false);
    expect(await screen.findByText(t("engines:process.savedLocal"))).toBeInTheDocument();
    await waitFor(() => expect(backend.calls.filter((call) => call.path === "/local/models").length).toBeGreaterThan(readsBefore));
  });

  it("shows no model as active while an external provider serves the process, and offers the local ones", async () => {
    await renderReady("transcription", {
      models: [TURBO_ACTIVE],
      processes: [external("transcription", "p1", "Work OpenAI", "openai", "gpt-a"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    const turbo = await screen.findByRole("listitem", { name: "whisper-turbo" });
    expect(within(turbo).queryByText(t("engines:local.states.active"))).toBeNull();
    const group = screen.getByRole("region", { name: t("engines:local.external.title") });
    expect(within(group).getByText(t("engines:process.externalName", { provider: "Work OpenAI", model: "gpt-a" }))).toBeInTheDocument();
    expect(within(group).getByText(t("engines:local.states.active"))).toBeInTheDocument();
  });

  it("opens the engine selector from «Elegir un proveedor externo…» and still asks for the notice before saving", async () => {
    await renderReady("transcription", { models: [TURBO_ACTIVE] });
    fireEvent.click(await screen.findByRole("button", { name: t("engines:local.external.choose") }));
    expect(panel()).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
    fireEvent.click(await screen.findByRole("option", { name: /gpt-a/ }));
    expect(await screen.findByRole("dialog", { name: "Notice title" })).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it("says why a working provider is not offered for a process its type does not serve", async () => {
    await renderReady("transcription", { providers: [provider("p3", "Claude", "anthropic")] });
    expect(screen.getByText(t("engines:process.notServedBy", { provider: "Claude", process: t("engines:processes.transcription"), only: t("engines:processes.summary") }))).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.noProviders"))).toBeInTheDocument();
    cleanup();
    // A provider that does serve the process needs no such note.
    await renderReady("summary", { providers: [provider("p3", "Claude", "anthropic")] });
    expect(screen.queryByText(/no sirve para/)).toBeNull();
  });

  it("points to the provider setup when no provider can serve the process", async () => {
    await renderReady("diarization", { providers: [], models: [] });
    expect(await screen.findByRole("button", { name: t("engines:local.external.setup") })).toBeInTheDocument();
    expect(screen.getByText(t("engines:process.noProviders"))).toBeInTheDocument();
  });

  it("shows size and the active tag of the local models in the selector", async () => {
    await renderReady("transcription", {
      models: [TURBO_ACTIVE, SMALL_INSTALLED, localModel({ ...SMALL_INSTALLED, id: "whisper-base", active: true })],
    });
    await screen.findByRole("listitem", { name: "whisper-small" });
    openPicker();
    const group = within(panel()).getAllByRole("group")[0];
    const options = within(group).getAllByRole("option");
    expect(options[0]).toHaveTextContent(t("engines:process.localRecommended"));
    expect(options[0]).toHaveTextContent("574 MB");
    expect(options[0]).toHaveTextContent(t("engines:process.inUse"));
    const base = within(group).getByRole("option", { name: /whisper-base/ });
    expect(base).toHaveTextContent("190 MB");
    expect(base).toHaveTextContent(t("engines:process.activeTag"));
    expect(within(group).getByRole("option", { name: /whisper-small/ })).not.toHaveTextContent(t("engines:process.activeTag"));
  });

  it("offers Parakeet as the recommended local choice and Whisper as a model that can be pinned, and back", async () => {
    const parakeet = localModel({
      id: "parakeet-ultra", process: "transcription", engine: "fluidaudio", state: "installed", availability: "installed",
      size: 632_000_000, preferred: true, needs: "fluidaudio-cli", needs_ready: true,
    });
    await renderReady("transcription", { models: [parakeet, { ...TURBO_ACTIVE, active: false }] });
    await screen.findByRole("listitem", { name: "parakeet-ultra" });
    openPicker();
    const group = within(panel()).getAllByRole("group")[0];
    const options = within(group).getAllByRole("option");
    expect(options[0]).toHaveTextContent(t("engines:process.localRecommended"));
    expect(options[0]).toHaveTextContent("632 MB");
    // Whisper is no longer the recommended entry: it is listed by its id, so it can be chosen on purpose.
    expect(within(group).getByRole("option", { name: /whisper-turbo/ })).toBeInTheDocument();
    expect(within(group).queryByRole("option", { name: /parakeet-ultra/ })).toBeNull();
  });

  it("never renders a key or secret, only what the API returns for display", async () => {
    const leaky = provider("p1", "Work OpenAI", "openai", { key_hint: "1234", ...({ key: "sk-LIVE-SECRET-9999", api_key: "sk-LIVE-SECRET-9999" } as object) });
    await renderReady("transcription", {
      providers: [leaky],
      models: [TURBO_ACTIVE],
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    await screen.findByRole("listitem", { name: "whisper-turbo" });
    openPicker();
    await screen.findByRole("option", { name: /gpt-a/ });
    expect(document.body.textContent).not.toContain("SECRET");
    expect(document.body.innerHTML).not.toContain("SECRET");
  });
});

describe("fallback switch and warnings", () => {
  it("appears only for an external route and saves at once", async () => {
    await renderReady("transcription");
    expect(screen.queryByRole("switch")).toBeNull();
    cleanup();
    await renderReady("transcription", {
      processes: [external("transcription", "p1", "Work OpenAI", "openai", "m"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    const toggle = screen.getByRole("switch", { name: t("engines:process.fallback") });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ provider_id: "p1", model: "m", local_fallback: false });
    await waitFor(() => expect(screen.getByRole("switch", { name: t("engines:process.fallback") })).not.toBeChecked());
  });

  it("warns about the double send, in the notice, when speakers already use the same provider", async () => {
    await renderReady("transcription", {
      processes: [localState("transcription"), external("diarization", "p2", "Deepgram", "deepgram", "nova-3"), localState("summary")],
      consents: ["diarization:p2"],
    });
    expect(screen.queryByText(t("engines:process.doubleSend", { provider: "Deepgram", other: t("engines:process.otherProcess.diarization") }))).toBeNull();
    openPicker();
    fireEvent.change(await screen.findByLabelText(t("engines:process.manualModel")), { target: { value: "nova-3" } });
    fireEvent.click(within(panel()).getByRole("button", { name: t("engines:process.manualModelUse") }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(t("engines:process.doubleSend", { provider: "Deepgram", other: t("engines:process.otherProcess.diarization") }))).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it("keeps showing the double send after it is saved", async () => {
    await renderReady("transcription", {
      processes: [external("transcription", "p2", "Deepgram", "deepgram", "nova-3"), external("diarization", "p2", "Deepgram", "deepgram", "nova-3"), localState("summary")],
      consents: ["diarization:p2", "transcription:p2"],
    });
    expect(screen.getByText(t("engines:process.doubleSend", { provider: "Deepgram", other: t("engines:process.otherProcess.diarization") }))).toBeInTheDocument();
  });

  it("marks external speakers as quality not validated, in the notice and once saved", async () => {
    await renderReady("diarization", { providers: [provider("p2", "Deepgram", "deepgram")] });
    expect(screen.queryByText(t("engines:process.speakersUnvalidated"))).toBeNull();
    openPicker();
    fireEvent.change(await screen.findByLabelText(t("engines:process.manualModel")), { target: { value: "nova-3" } });
    fireEvent.click(within(panel()).getByRole("button", { name: t("engines:process.manualModelUse") }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(t("engines:process.speakersUnvalidated"))).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:notice.accept") }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText(t("engines:process.speakersUnvalidated"))).toBeInTheDocument();
  });
});

describe("loading and failure", () => {
  it("offers to retry when the configuration cannot be loaded", async () => {
    backend = fakeBackend();
    backend.failing.add("GET /processes");
    vi.stubGlobal("fetch", backend.handler);
    render(<ProcessSettings process="summary" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:process.loadError"));
    backend.failing.clear();
    fireEvent.click(screen.getByRole("button", { name: t("engines:process.retry") }));
    expect(await screen.findByRole("button", { name: TRIGGER })).toBeInTheDocument();
  });
});
