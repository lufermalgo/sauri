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
import { copy } from "../copy/es";
import { ProcessSettings } from "./settings/ProcessSettings";

const text = copy.engines.process;
const noticeText = copy.engines.notice;

function kindInfo(kind: EngineProviderKind, processes: EngineProcess[]): EngineKindInfo {
  return {
    kind,
    default_base_url: `https://api.${kind}.example/v1`,
    key_required: true,
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
    p1: { models: [{ id: "gpt-a", label: null }, { id: "gpt-b", label: null }], starter: "gpt-a", from_cache: true, fetched_at: null, manual_entry: false, error_class: null },
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

async function renderReady(process: EngineProcess, setup: Setup = {}) {
  backend = fakeBackend(setup);
  vi.stubGlobal("fetch", backend.handler);
  render(<ProcessSettings process={process} />);
  await screen.findByLabelText(text.engineLabel);
}

const engineSelect = () => screen.getByLabelText(text.engineLabel) as HTMLSelectElement;
const writes = () => backend.calls.filter((call) => call.method === "PUT");
const choose = (value: string) => fireEvent.change(engineSelect(), { target: { value } });

async function pickProvider(value: string) {
  choose(value);
  await screen.findByLabelText(text.model);
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

describe("what a process uses today", () => {
  it("says it uses the local engine and that nothing leaves the computer", async () => {
    await renderReady("transcription");
    expect(screen.getByText(text.current(text.localName))).toBeInTheDocument();
    expect(screen.getByText(text.badgeLocal)).toBeInTheDocument();
    expect(screen.getByText(text.staysHere)).toBeInTheDocument();
  });

  it("names the provider, the model and what is sent when the process is external", async () => {
    await renderReady("summary", {
      processes: [localState("transcription"), localState("diarization"), {
        ...localState("summary"), provider_id: "p1", provider_kind: "openai", provider_label: "Work OpenAI", model: "gpt-b", configured: true,
      }],
      consents: ["summary:p1"],
    });
    expect(screen.getByText(text.current(text.externalName("Work OpenAI", "gpt-b")))).toBeInTheDocument();
    expect(screen.getByText(text.badgeExternal)).toBeInTheDocument();
    expect(screen.getByText(text.leaves("Work OpenAI", text.sends.summary))).toBeInTheDocument();
  });
});

describe("engine and model selector", () => {
  it("lists the local recommendation first, then installed local models, then compatible providers", async () => {
    await renderReady("transcription", {
      models: [
        localModel({ id: "whisper-turbo", process: "transcription", default: true, state: "installed", size: 574_000_000 }),
        localModel({ id: "whisper-small", process: "transcription", state: "installed" }),
        localModel({ id: "whisper-base", process: "transcription", state: "not_installed" }),
        localModel({ id: "qwen-4b", process: "summary", engine: "llama.cpp", state: "installed" }),
      ],
    });
    await screen.findByRole("option", { name: new RegExp("whisper-small") });
    const labels = within(engineSelect()).getAllByRole("option").map((option) => option.textContent);
    expect(labels[0]).toBe(text.localRecommended);
    expect(labels[1]).toContain("whisper-small");
    // Not installed, other process and the default model (already "Local (recomendado)") are not repeated.
    expect(labels.join("|")).not.toMatch(/whisper-base|qwen-4b|whisper-turbo/);
    // Anthropic does not serve transcription, so it is not offered; both OpenAI and Deepgram are.
    expect(labels.slice(-2)).toEqual(["Work OpenAI", "Deepgram"]);
  });

  it("offers only what /capabilities says each provider can serve, nothing hardcoded", async () => {
    await renderReady("diarization", { providers: [provider("p1", "Work OpenAI", "openai")] });
    expect(within(engineSelect()).getAllByRole("option")).toHaveLength(1);
    expect(screen.getByText(text.noProviders)).toBeInTheDocument();
  });

  it("does not offer providers that are off or without a key", async () => {
    await renderReady("transcription", {
      providers: [provider("p1", "Off", "openai", { enabled: false, status: "disabled" }), provider("p2", "No key", "deepgram", { status: "no_key", key_set: false })],
    });
    expect(within(engineSelect()).getAllByRole("option")).toHaveLength(1);
  });

  it("starts a new choice with the provider's suggested model and its cached catalog", async () => {
    await renderReady("transcription");
    await pickProvider("provider:p1");
    const model = screen.getByLabelText(text.model) as HTMLSelectElement;
    await waitFor(() => expect(model.value).toBe("gpt-a"));
    expect(within(model).getByRole("option", { name: text.modelStarter("gpt-a") })).toBeInTheDocument();
    expect(screen.getByText(text.modelsCached)).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it("asks the provider again on «Volver a pedir»", async () => {
    await renderReady("transcription");
    await pickProvider("provider:p1");
    fireEvent.click(screen.getByRole("button", { name: text.modelsRefresh }));
    await waitFor(() =>
      expect(backend.calls.some((call) => call.path === "/providers/p1/models" && call.search.includes("refresh=true"))).toBe(true));
  });

  it("lets the person type the model when the list cannot be had, and saves that name", async () => {
    await renderReady("transcription");
    choose("provider:p2"); // Deepgram: the fake gives no catalog
    const field = await screen.findByLabelText(text.manualModel);
    expect(screen.getByText(new RegExp(text.modelsFailed))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: text.save })).toBeDisabled();
    fireEvent.change(field, { target: { value: "nova-3" } });
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    fireEvent.click(await screen.findByRole("button", { name: noticeText.accept }));
    await waitFor(() => expect(writes()[0].body).toMatchObject({ provider_id: "p2", model: "nova-3" }));
  });
});

describe("privacy notice before an external provider", () => {
  it("shows the notice from the API and saves nothing until it is accepted", async () => {
    await renderReady("transcription");
    await pickProvider("provider:p1");
    await waitFor(() => expect((screen.getByLabelText(text.model) as HTMLSelectElement).value).toBe("gpt-a"));
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Notice title" })).toBeInTheDocument();
    expect(within(dialog).getByText("Usage is billed to your account.")).toBeInTheDocument();
    expect(within(dialog).getByText(noticeText.address("https://api.openai.example/v1"))).toBeInTheDocument();
    expect(writes()).toHaveLength(0);
  });

  it("saves nothing when the notice is cancelled, and today's engine does not change", async () => {
    await renderReady("transcription");
    await pickProvider("provider:p1");
    await waitFor(() => expect((screen.getByLabelText(text.model) as HTMLSelectElement).value).toBe("gpt-a"));
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    fireEvent.click(await screen.findByRole("button", { name: noticeText.cancel }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toHaveLength(0);
    expect(screen.getByText(text.current(text.localName))).toBeInTheDocument();
    expect(screen.getByText(text.unsaved)).toBeInTheDocument();
  });

  it("saves with the notice version once it is accepted", async () => {
    await renderReady("transcription");
    await pickProvider("provider:p1");
    await waitFor(() => expect((screen.getByLabelText(text.model) as HTMLSelectElement).value).toBe("gpt-a"));
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    fireEvent.click(await screen.findByRole("button", { name: noticeText.accept }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(writes()).toHaveLength(1);
    expect(writes()[0]).toMatchObject({
      path: "/processes/transcription",
      body: { provider_id: "p1", model: "gpt-a", local_fallback: true, notice_version: 1 },
    });
    expect(await screen.findByText(text.current(text.externalName("Work OpenAI", "gpt-a")))).toBeInTheDocument();
    expect(screen.getByText(text.badgeExternal)).toBeInTheDocument();
  });

  it("does not repeat the notice when only the model of the same provider changes", async () => {
    await renderReady("transcription", {
      processes: [{
        ...localState("transcription"), provider_id: "p1", provider_kind: "openai", provider_label: "Work OpenAI", model: "gpt-a", configured: true,
      }, localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    expect(engineSelect().value).toBe("provider:p1");
    const model = await screen.findByLabelText(text.model);
    fireEvent.change(model, { target: { value: "gpt-b" } });
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ provider_id: "p1", model: "gpt-b", local_fallback: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(backend.calls.some((call) => call.path.endsWith("/notice"))).toBe(false);
    expect(await screen.findByText(text.current(text.externalName("Work OpenAI", "gpt-b")))).toBeInTheDocument();
  });

  it("shows the notice if the API says consent is missing for a same-provider save", async () => {
    await renderReady("transcription", {
      processes: [{
        ...localState("transcription"), provider_id: "p1", provider_kind: "openai", provider_label: "Work OpenAI", model: "gpt-a", configured: true,
      }, localState("diarization"), localState("summary")],
      consents: [], // the stored consent is gone (for example the notice version moved on)
    });
    fireEvent.change(await screen.findByLabelText(text.model), { target: { value: "gpt-b" } });
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(writes()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: noticeText.accept }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1].body).toMatchObject({ notice_version: 1, model: "gpt-b" });
  });

  it("goes back to the local engine at once, without a notice or a confirmation", async () => {
    await renderReady("transcription", {
      processes: [{
        ...localState("transcription"), provider_id: "p1", provider_kind: "openai", provider_label: "Work OpenAI", model: "gpt-a", configured: true,
      }, localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    choose("local:default");
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ provider_id: null, model: "local:default", local_fallback: true });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(backend.calls.some((call) => call.path.endsWith("/notice"))).toBe(false);
    expect(await screen.findByText(text.current(text.localName))).toBeInTheDocument();
    expect(screen.getByText(text.staysHere)).toBeInTheDocument();
  });

  it("saves an installed local model as local:<id>", async () => {
    await renderReady("transcription", {
      models: [localModel({ id: "whisper-small", process: "transcription", state: "installed" })],
    });
    await screen.findByRole("option", { name: new RegExp("whisper-small") });
    choose("local:whisper-small");
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toMatchObject({ provider_id: null, model: "local:whisper-small" });
    expect(await screen.findByText(text.current(text.localModelName("whisper-small")))).toBeInTheDocument();
  });

  it("reports a refused save inside the notice and keeps today's engine", async () => {
    await renderReady("transcription");
    backend.failing.add("PUT /processes/transcription");
    await pickProvider("provider:p1");
    await waitFor(() => expect((screen.getByLabelText(text.model) as HTMLSelectElement).value).toBe("gpt-a"));
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    fireEvent.click(await screen.findByRole("button", { name: noticeText.accept }));
    expect(await within(screen.getByRole("dialog")).findByRole("alert")).toHaveTextContent(copy.engines.genericError);
    expect(screen.getByText(text.current(text.localName))).toBeInTheDocument();
  });
});

describe("fallback switch and warnings", () => {
  const external = (capability: EngineProcess, id = "p1", label = "Work OpenAI", kind: EngineProviderKind = "openai"): EngineProcessState => ({
    ...localState(capability), provider_id: id, provider_kind: kind, provider_label: label, model: "m", configured: true,
  });

  it("appears only for an external route and saves at once when nothing else is pending", async () => {
    await renderReady("transcription");
    expect(screen.queryByRole("switch")).toBeNull();
    cleanup();
    await renderReady("transcription", {
      processes: [external("transcription"), localState("diarization"), localState("summary")],
      consents: ["transcription:p1"],
    });
    const toggle = screen.getByRole("switch", { name: text.fallback });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0].body).toEqual({ provider_id: "p1", model: "m", local_fallback: false });
    await waitFor(() => expect(screen.getByRole("switch", { name: text.fallback })).not.toBeChecked());
  });

  it("warns about the double send when speakers already use the same provider", async () => {
    await renderReady("transcription", {
      processes: [localState("transcription"), external("diarization", "p2", "Deepgram", "deepgram"), localState("summary")],
      consents: ["diarization:p2"],
    });
    expect(screen.queryByText(copy.engines.process.doubleSend("Deepgram", text.otherProcess.diarization))).toBeNull();
    choose("provider:p2");
    expect(await screen.findByText(text.doubleSend("Deepgram", text.otherProcess.diarization))).toBeInTheDocument();
  });

  it("marks external speakers as quality not validated", async () => {
    await renderReady("diarization", {
      providers: [provider("p2", "Deepgram", "deepgram")],
      processes: [localState("transcription"), localState("diarization"), localState("summary")],
    });
    expect(screen.queryByText(text.speakersUnvalidated)).toBeNull();
    choose("provider:p2");
    expect(await screen.findByText(text.speakersUnvalidated)).toBeInTheDocument();
  });
});

describe("loading and failure", () => {
  it("offers to retry when the configuration cannot be loaded", async () => {
    backend = fakeBackend();
    backend.failing.add("GET /processes");
    vi.stubGlobal("fetch", backend.handler);
    render(<ProcessSettings process="summary" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.loadError);
    backend.failing.clear();
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    expect(await screen.findByLabelText(text.engineLabel)).toBeInTheDocument();
  });
});
