// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  EngineErrorClass,
  EngineKindInfo,
  EngineModelList,
  EngineProcess,
  EngineProvider,
  EngineProviderKind,
} from "@sauri/shared-types";
import { EnginesSettings } from "./settings/EnginesSettings";
import { t } from "../i18n";
import { processList } from "./settings/engineLabels";


const SECRET = "sk-test-0123456789abcdefWXYZ";
const SECRET_HINT = "WXYZ";

function kindInfo(kind: EngineProviderKind, overrides: Partial<EngineKindInfo> = {}): EngineKindInfo {
  const localApp = kind === "ollama" || kind === "lmstudio";
  return {
    kind,
    default_base_url: localApp ? `http://127.0.0.1:${kind === "ollama" ? 11434 : 1234}/v1` : `https://api.${kind}.example/v1`,
    key_required: !localApp && kind !== "openai_compatible",
    auth: "key",
    linkable: true,
    capabilities: [{ capability: "summary", transport: "openai-chat", verified_on: "2026-11-16" }],
    ...overrides,
  };
}

const KINDS: EngineKindInfo[] = [
  kindInfo("openai", {
    capabilities: [
      { capability: "transcription", transport: "openai-audio", verified_on: "2026-11-16" },
      { capability: "summary", transport: "openai-chat", verified_on: "2026-11-16" },
    ],
  }),
  kindInfo("anthropic"),
  kindInfo("ollama"),
  kindInfo("lmstudio"),
  kindInfo("openai_compatible", { default_base_url: null, key_required: false }),
  kindInfo("chatgpt_plan", { default_base_url: null, linkable: false, capabilities: [] }),
];

function provider(overrides: Partial<EngineProvider> & Pick<EngineProvider, "id" | "label">): EngineProvider {
  return {
    kind: "openai",
    base_url: "https://api.openai.example/v1",
    enabled: true,
    status: "active",
    key_set: true,
    key_hint: "1234",
    key_set_at: "2026-11-16T10:00:00Z",
    used_by: [],
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-16T10:00:00Z",
    ...overrides,
  };
}

interface Call { method: string; path: string; search: string; body: Record<string, unknown> | null }

/** An in-memory stand-in for /api/v1/engines with the behaviors the screen depends on. */
function fakeBackend(initial: EngineProvider[]) {
  const providers = initial.map((item) => ({ ...item }));
  const calls: Call[] = [];
  const failing = new Set<string>();
  const catalogs: Record<string, EngineModelList> = {};
  const probe = {
    ok: true,
    latency_ms: 120,
    error_class: null as EngineErrorClass | null,
    json_schema_ok: null as boolean | null,
    schema_error_class: null as EngineErrorClass | null,
    schema_model: null as string | null,
  };
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/engines", "") || "/";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, path, search: url.search, body });
    if (failing.has(`${method} ${path}`)) return json({ detail: "boom" }, 500);

    if (method === "GET" && path === "/capabilities") {
      return json({ notice_versions: { transcription: 1, diarization: 1, summary: 1 }, kinds: KINDS });
    }
    if (method === "GET" && path === "/providers") return json(providers);
    if (method === "POST" && path === "/providers") {
      if (providers.some((item) => item.label === body?.label)) return json({ detail: "conflict" }, 409);
      const kind = body?.kind as EngineProviderKind;
      const created = provider({
        id: `p${providers.length + 1}`,
        kind,
        label: String(body?.label),
        base_url: String(body?.base_url),
        enabled: body?.enabled !== false,
        status: KINDS.find((info) => info.kind === kind)?.key_required === false ? "active" : "no_key",
        key_set: false,
        key_hint: null,
        key_set_at: null,
      });
      providers.push(created);
      return json(created, 201);
    }
    const listing = /^\/providers\/([^/]+)\/models$/.exec(path);
    if (method === "GET" && listing) {
      return json(catalogs[listing[1]] ?? { models: [], starter: null, from_cache: false, fetched_at: null, manual_entry: true, error_class: "provider_unavailable" });
    }
    const match = /^\/providers\/([^/]+)(\/key|\/test)?$/.exec(path);
    const target = match ? providers.find((item) => item.id === match[1]) : undefined;
    if (!match || !target) return json({ detail: "not_found" }, 404);
    const [, , suffix] = match;

    if (method === "GET" && !suffix) return json(target);
    if (method === "PATCH" && !suffix) {
      const reverted: EngineProcess[] = body && "enabled" in body && body.enabled === false ? [...target.used_by] : [];
      Object.assign(target, body);
      if (reverted.length > 0) target.used_by = [];
      target.status = target.enabled ? (target.key_set ? "active" : "no_key") : "disabled";
      return json({ ...target, reverted_processes: reverted });
    }
    if (method === "DELETE" && !suffix) {
      providers.splice(providers.indexOf(target), 1);
      return json({ reverted_processes: target.used_by });
    }
    if (method === "PUT" && suffix === "/key") {
      const key = String(body?.key);
      Object.assign(target, { key_set: true, key_hint: key.length >= 12 ? key.slice(-4) : null, status: "active" });
      return json({ key_set: true, key_hint: target.key_hint, reverted_processes: [] });
    }
    if (method === "DELETE" && suffix === "/key") {
      const reverted = [...target.used_by];
      Object.assign(target, { key_set: false, key_hint: null, status: "no_key", used_by: [] });
      return json({ key_set: false, key_hint: null, reverted_processes: reverted });
    }
    if (method === "POST" && suffix === "/test") return json(probe);
    return json({ detail: "unexpected" }, 404);
  });
  return { handler, calls, failing, providers, probe, catalogs };
}

let backend: ReturnType<typeof fakeBackend>;

const GOOD_CATALOG: EngineModelList = {
  models: [{ id: "gpt-a", label: null, serves: ["summary"] }, { id: "gpt-b", label: "GPT B", serves: ["summary"] }],
  starter: "gpt-a",
  from_cache: false,
  fetched_at: new Date().toISOString(),
  manual_entry: false,
  error_class: null,
  serves: ["summary"],
};

async function renderReady(initial: EngineProvider[], prepare?: (fake: ReturnType<typeof fakeBackend>) => void) {
  backend = fakeBackend(initial);
  prepare?.(backend);
  vi.stubGlobal("fetch", backend.handler);
  render(<EnginesSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: t("engines:add") })).toBeEnabled());
}

const writes = () => backend.calls.filter((call) => call.method !== "GET").map(({ search: _search, ...call }) => call);
const card = (name: string) => screen.getByRole("heading", { level: 4, name }).closest("section")!;
const cardNames = () => screen.getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent);
const dialog = () => screen.getByRole("dialog");
/** The state badge of a card (its «Activo» switch label reads the same). */
const badge = (name: string) => card(name).querySelector(".ui-status-badge")!;
const openAdd = () => fireEvent.click(screen.getByRole("button", { name: t("engines:add") }));
const addList = () => screen.getByRole("dialog", { name: t("engines:addDialog.title") });
/** «Agregar proveedor», then a kind from the list: opens the set-up dialog for that kind. */
function addKind(kind: EngineProviderKind) {
  openAdd();
  fireEvent.click(within(addList()).getByRole("button", { name: t(`engines:kinds.${kind}.label`) }));
}

/** Everything a person or a screen reader could see of a key: text, field values and attributes. */
function renderedKeyTraces(secret: string): string[] {
  const traces: string[] = [];
  if (document.body.textContent?.includes(secret)) traces.push("text");
  if (document.body.innerHTML.includes(secret)) traces.push("markup");
  for (const input of Array.from(document.querySelectorAll("input, textarea"))) {
    if ((input as HTMLInputElement).value.includes(secret)) traces.push("field value");
  }
  return traces;
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

describe("what a provider serves", () => {
  it("says it plainly on the card: from the listed models, or that its type serves nothing yet", async () => {
    await renderReady(
      [
        provider({ id: "p1", label: "Work OpenAI" }),
        provider({ id: "p2", label: "Soon", kind: "chatgpt_plan", key_set: false, key_hint: null }),
      ],
      (fake) => {
        fake.catalogs.p1 = { ...GOOD_CATALOG, serves: ["transcription", "summary"] };
      },
    );
    const work = within(card("Work OpenAI"));
    expect(await work.findByText(t("engines:card.serves", { list: processList(["transcription", "summary"]) }))).toBeInTheDocument();
    expect(within(card("Soon")).getByText(t("engines:card.servesNone"))).toBeInTheDocument();
  });
});

describe("linked provider cards", () => {
  it("lists only the linked providers, by state, then one «Agregar» tile", async () => {
    await renderReady([
      provider({ id: "p1", label: "Paused", kind: "anthropic", status: "disabled", enabled: false }),
      provider({ id: "p2", label: "Work OpenAI" }),
    ]);
    expect(cardNames()).toEqual(["Work OpenAI", "Paused"]);
    expect(screen.queryByText(t("engines:statuses.unconfigured"))).toBeNull();
    expect(document.querySelector(".ui-card--dashed")).toBeNull();
    expect(screen.queryByText(t("engines:empty"))).toBeNull();
    const items = screen.getAllByRole("listitem").filter((item) => item.classList.contains("engines-grid-item"));
    expect(items).toHaveLength(3);
    const add = within(items[2]).getByRole("button", { name: t("engines:add") });
    expect(add).toHaveAccessibleDescription(t("engines:addHint"));
    expect(screen.getAllByRole("button", { name: t("engines:add") })).toHaveLength(1);
  });

  it("with nothing linked, says everything stays on the Mac and shows only the «Agregar» tile", async () => {
    await renderReady([]);
    expect(screen.queryAllByRole("heading", { level: 4 })).toHaveLength(0);
    expect(screen.getByText(t("engines:empty"))).toBeInTheDocument();
    const items = screen.getAllByRole("listitem").filter((item) => item.classList.contains("engines-grid-item"));
    expect(items).toHaveLength(1);
    expect(within(items[0]).getByRole("button", { name: t("engines:add") })).toBeInTheDocument();
  });

  it("writes every state as text, with key hint, address and model count in rows", async () => {
    await renderReady(
      [
        provider({ id: "p1", label: "Work OpenAI", used_by: ["summary", "transcription"] }),
        provider({ id: "p2", label: "No key yet", kind: "anthropic", key_set: false, key_hint: null, status: "no_key" }),
        provider({ id: "p3", label: "Paused", kind: "lmstudio", status: "disabled", enabled: false, key_set: false, key_hint: null, base_url: "http://127.0.0.1:1234/v1" }),
        provider({ id: "p4", label: "Local Ollama", kind: "ollama", base_url: "http://127.0.0.1:11434/v1", key_set: false, key_hint: null }),
      ],
      (fake) => { fake.catalogs.p1 = GOOD_CATALOG; },
    );
    const work = within(card("Work OpenAI"));
    expect(badge("Work OpenAI")).toHaveTextContent(t("engines:statuses.active"));
    expect(work.getByText(t("engines:card.usedBy", { list: processList(["summary", "transcription"]) }))).toBeInTheDocument();
    expect(work.getByText("https://api.openai.example/v1")).toBeInTheDocument();
    expect(work.getByText(t("engines:card.keyShown", { hint: "1234" }))).toBeInTheDocument();
    expect(await work.findByText(t("engines:card.modelsCount", { count: 2 }))).toBeInTheDocument();
    // What the provider can do for Sauri comes from the models it listed.
    expect(work.getByText(t("engines:card.serves", { list: t("engines:processes.summary") }))).toBeInTheDocument();

    expect(within(card("No key yet")).getByText(t("engines:statuses.no_key"))).toBeInTheDocument();
    // Key and models are both "—": no key saved, and nothing was asked.
    expect(within(card("No key yet")).getAllByText(t("engines:card.keyNone"))).toHaveLength(2);
    expect(within(card("No key yet")).getByText(t("engines:card.unused"))).toBeInTheDocument();
    // A provider without a key is never asked for its models.
    expect(backend.calls.some((call) => call.path.startsWith("/providers/p2/models"))).toBe(false);

    expect(within(card("Paused")).getByText(t("engines:statuses.disabled"))).toBeInTheDocument();
    expect(card("Paused")).toHaveClass("ui-card--dimmed");
    expect(card("Paused")).not.toHaveClass("ui-card--dashed");
    expect(within(card("Local Ollama")).getByText(t("engines:card.keyNotNeeded"))).toBeInTheDocument();
  });

  it("gives every card an on/off switch, edit and delete named after the provider", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    const scope = within(card("Work OpenAI"));
    expect(scope.getByRole("switch", { name: `${t("engines:card.active")} Work OpenAI` })).toBeChecked();
    expect(scope.getByRole("button", { name: t("engines:card.edit", { name: "Work OpenAI" }) })).toBeInTheDocument();
    expect(scope.getByRole("button", { name: t("engines:card.remove", { name: "Work OpenAI" }) })).toBeInTheDocument();
    expect(scope.queryByText("Administrar")).toBeNull();
  });

  it("shows a loading state", async () => {
    backend = fakeBackend([]);
    vi.stubGlobal("fetch", backend.handler);
    render(<EnginesSettings />);
    expect(screen.getByText(t("engines:loading"))).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: t("engines:add") })).toBeInTheDocument();
  });

  it("shows a load error that can be retried", async () => {
    backend = fakeBackend([provider({ id: "p1", label: "Work OpenAI" })]);
    vi.stubGlobal("fetch", backend.handler);
    backend.failing.add("GET /providers");
    render(<EnginesSettings />);
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:loadError"));
    expect(screen.queryByRole("button", { name: t("engines:add") })).toBeNull();

    backend.failing.clear();
    fireEvent.click(screen.getByRole("button", { name: t("engines:retry") }));
    expect(await screen.findByRole("heading", { level: 4, name: "Work OpenAI" })).toBeInTheDocument();
  });

  it("sends the stored token", async () => {
    await renderReady([]);
    const first = backend.handler.mock.calls[0];
    expect((first[1]?.headers as Record<string, string>).Authorization).toBe("Bearer synthetic-token");
  });
});

describe("turning a provider on and off", () => {
  it("turns off a provider no process uses at once, dimming its card", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    fireEvent.click(within(card("Work OpenAI")).getByRole("switch"));
    await waitFor(() => expect(card("Work OpenAI")).toHaveClass("ui-card--dimmed"));
    expect(writes()).toEqual([{ method: "PATCH", path: "/providers/p1", body: { enabled: false } }]);
    expect(within(card("Work OpenAI")).getByText(t("engines:statuses.disabled"))).toBeInTheDocument();
    expect(screen.getByText(t("engines:turnOff.done", { name: "Work OpenAI" }))).toBeInTheDocument();
  });

  it("asks before turning off a provider a process uses, and lists what goes back to local", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["transcription"] })]);
    fireEvent.click(within(card("Work OpenAI")).getByRole("switch"));
    const confirm = screen.getByRole("dialog", { name: t("engines:turnOff.title") });
    expect(within(confirm).getByText(t("engines:turnOff.reverts", { list: t("engines:processes.transcription") }))).toBeInTheDocument();
    expect(writes()).toEqual([]);

    fireEvent.click(within(confirm).getByRole("button", { name: t("engines:turnOff.cancel") }));
    expect(writes()).toEqual([]);

    fireEvent.click(within(card("Work OpenAI")).getByRole("switch"));
    fireEvent.click(within(screen.getByRole("dialog", { name: t("engines:turnOff.title") })).getByRole("button", { name: t("engines:turnOff.confirm") }));
    expect(await screen.findByText(t("engines:turnOff.doneReverted", { name: "Work OpenAI", list: t("engines:processes.transcription") }))).toBeInTheDocument();
    expect(writes()).toEqual([{ method: "PATCH", path: "/providers/p1", body: { enabled: false } }]);
    expect(within(card("Work OpenAI")).getByText(t("engines:card.unused"))).toBeInTheDocument();
  });

  it("turns on without asking and says that this sends nothing", async () => {
    await renderReady([provider({ id: "p1", label: "Paused", status: "disabled", enabled: false })]);
    const toggle = within(card("Paused")).getByRole("switch");
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(await screen.findByText(t("engines:turnOff.turnedOn", { name: "Paused" }))).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toEqual([{ method: "PATCH", path: "/providers/p1", body: { enabled: true } }]);
    expect(badge("Paused")).toHaveTextContent(t("engines:statuses.active"));
  });

  it("keeps the provider as it was and says so when the API refuses", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    backend.failing.add("PATCH /providers/p1");
    fireEvent.click(within(card("Work OpenAI")).getByRole("switch"));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:turnOff.failed"));
    expect(badge("Work OpenAI")).toHaveTextContent(t("engines:statuses.active"));
  });
});

describe("models catalog", () => {
  it("has one collapsible row per active provider with its count, time and state in words", async () => {
    await renderReady(
      [
        provider({ id: "p1", label: "Work OpenAI" }),
        provider({ id: "p2", label: "Down", kind: "anthropic" }),
        provider({ id: "p3", label: "No key yet", kind: "anthropic", key_set: false, key_hint: null, status: "no_key" }),
      ],
      (fake) => { fake.catalogs.p1 = GOOD_CATALOG; },
    );
    const list = await screen.findByRole("list", { name: t("engines:catalog.listLabel") });
    await waitFor(() => expect(within(list).getByText(t("engines:catalog.available"))).toBeInTheDocument());
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText(new RegExp(`2 modelos · pedida hoy \\d{2}:\\d{2}`))).toBeInTheDocument();
    await waitFor(() => expect(within(rows[1]).getByText(t("engines:catalog.unreachable"))).toBeInTheDocument());
    expect(within(rows[1]).getByText(t("engines:causes.provider_unavailable"))).toBeInTheDocument();
    expect(screen.getByText(t("engines:catalog.help"))).toBeInTheDocument();
  });

  it("expands a row to show readable names and their ids, and collapses it again", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })], (fake) => { fake.catalogs.p1 = GOOD_CATALOG; });
    const toggle = await screen.findByRole("button", { name: t("engines:catalog.expand", { name: "Work OpenAI" }) });
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const models = screen.getByRole("list", { name: t("engines:catalog.modelsOf", { name: "Work OpenAI" }) });
    expect(within(models).getByText("GPT B")).toBeInTheDocument();
    expect(within(models).getByText("gpt-b")).toBeInTheDocument();
    expect(within(models).getByText("gpt-a")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByRole("list", { name: t("engines:catalog.modelsOf", { name: "Work OpenAI" }) })).toBeNull();
  });

  it("filters the models of every provider with the search box", async () => {
    await renderReady(
      [provider({ id: "p1", label: "Work OpenAI" }), provider({ id: "p2", label: "Claude", kind: "anthropic" })],
      (fake) => {
        fake.catalogs.p1 = GOOD_CATALOG;
        fake.catalogs.p2 = { ...GOOD_CATALOG, models: [{ id: "claude-x", label: null, serves: ["summary"] }], starter: null };
      },
    );
    await waitFor(() => expect(screen.getAllByText(t("engines:catalog.available"))).toHaveLength(2));
    fireEvent.change(screen.getByRole("searchbox", { name: t("engines:catalog.search") }), { target: { value: "claude" } });
    const list = screen.getByRole("list", { name: t("engines:catalog.listLabel") });
    expect(within(list).getAllByRole("listitem", { name: "" }).length).toBeGreaterThan(0);
    expect(within(list).queryByText("Work OpenAI")).toBeNull();
    expect(within(list).getByText("claude-x")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: t("engines:catalog.search") }), { target: { value: "zzz" } });
    expect(screen.getByText(t("engines:catalog.noMatches"))).toBeInTheDocument();
  });

  it("asks every provider again with «Actualizar»", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })], (fake) => { fake.catalogs.p1 = GOOD_CATALOG; });
    await waitFor(() => expect(screen.getByText(t("engines:catalog.available"))).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: t("engines:catalog.refresh") }));
    await waitFor(() =>
      expect(backend.calls.some((call) => call.path === "/providers/p1/models" && call.search.includes("refresh=true"))).toBe(true));
  });

  it("explains how to get a list when no provider is active", async () => {
    await renderReady([]);
    expect(screen.getByText(t("engines:catalog.empty"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("engines:catalog.refresh") })).toBeDisabled();
  });
});

describe("the «Agregar» list", () => {
  it("lists the kinds the API says can be linked, each with its logo, name and where it runs and what it serves", async () => {
    await renderReady([]);
    openAdd();
    const list = within(addList()).getByRole("list", { name: t("engines:addDialog.listLabel") });
    const options = within(list).getAllByRole("button");
    // In the API's order; chatgpt_plan is not linkable in this setup, so it is not offered.
    const kinds = ["openai", "anthropic", "ollama", "lmstudio", "openai_compatible"] as const;
    expect(options).toHaveLength(kinds.length);
    kinds.forEach((kind, index) => expect(options[index]).toHaveAccessibleName(t(`engines:kinds.${kind}.label`)));
    expect(within(list).queryByRole("button", { name: t("engines:kinds.chatgpt_plan.label") })).toBeNull();
    for (const option of options) {
      const logo = option.querySelector(".engines-logo")!;
      expect(logo).toHaveAttribute("aria-hidden", "true");
      expect(logo.querySelector("svg")).not.toBeNull();
    }
    const openai = within(list).getByRole("button", { name: t("engines:kinds.openai.label") });
    expect(openai).toHaveAccessibleDescription(
      t("engines:addDialog.line", { where: t("engines:addDialog.where.cloud"), serves: processList(["transcription", "summary"]) }),
    );
    expect(within(list).getByRole("button", { name: t("engines:kinds.ollama.label") })).toHaveAccessibleDescription(
      t("engines:addDialog.line", { where: t("engines:addDialog.where.local"), serves: processList(["summary"]) }),
    );
    expect(within(list).getByRole("button", { name: t("engines:kinds.openai_compatible.label") })).toHaveAccessibleDescription(
      t("engines:addDialog.line", { where: t("engines:addDialog.where.server"), serves: processList(["summary"]) }),
    );
    expect(writes()).toEqual([]);
  });

  it("moves focus in, keeps Tab inside, closes with Escape and returns focus to the tile", async () => {
    await renderReady([]);
    const add = screen.getByRole("button", { name: t("engines:add") });
    add.focus();
    fireEvent.click(add);
    const panel = addList();
    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(panel.contains(document.activeElement)).toBe(true);
    const tabbables = Array.from(panel.querySelectorAll<HTMLElement>("button:not(:disabled)"));
    const last = tabbables[tabbables.length - 1];
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(tabbables[0]);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(add);
  });

  it("closes with its close button without adding anything", async () => {
    await renderReady([]);
    openAdd();
    fireEvent.click(within(addList()).getByRole("button", { name: t("engines:addDialog.close") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toEqual([]);
  });

  it("opens the set-up dialog of the chosen kind, with its type fixed and the usual address filled in", async () => {
    await renderReady([]);
    addKind("ollama");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(dialog()).toHaveAccessibleName(t("engines:dialog.createTitle", { name: t("engines:kinds.ollama.label") }));
    expect(within(dialog()).queryByRole("radiogroup")).toBeNull();
    expect(within(dialog()).getByLabelText(t("engines:dialog.baseUrl"))).toHaveValue("http://127.0.0.1:11434/v1");
    expect(within(dialog()).getByLabelText(t("engines:dialog.name"))).toHaveValue(t("engines:kinds.ollama.label"));
    expect(within(dialog()).getByText(t("engines:dialog.localNote"))).toBeInTheDocument();
    // Local programs have no key: the field is not there at all.
    expect(within(dialog()).queryByLabelText(t("engines:dialog.key"))).toBeNull();
  });

  it("returns focus to the tile when the set-up dialog opened from the list is closed", async () => {
    await renderReady([]);
    const add = screen.getByRole("button", { name: t("engines:add") });
    add.focus();
    fireEvent.click(add);
    fireEvent.click(within(addList()).getByRole("button", { name: t("engines:kinds.anthropic.label") }));
    expect(dialog().contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(add);
  });

  it("keeps offering a kind already linked, proposing a name that is still free", async () => {
    await renderReady([provider({ id: "p1", label: t("engines:kinds.openai.label") })]);
    addKind("openai");
    expect(within(dialog()).getByLabelText(t("engines:dialog.name"))).toHaveValue(`${t("engines:kinds.openai.label")} 2`);
    expect(within(dialog()).queryByText(t("engines:dialog.nameDuplicate"))).toBeNull();
  });
});

describe("adding a provider", () => {
  it("shows the kind it adds, with what it is and what it can serve", async () => {
    await renderReady([]);
    addKind("openai");
    expect(dialog()).toHaveAccessibleName(t("engines:dialog.createTitle", { name: t("engines:kinds.openai.label") }));
    expect(within(dialog()).getByText(t("engines:kinds.openai.label"), { selector: ".engines-chip" })).toBeInTheDocument();
    expect(within(dialog()).getByText(
      `${t("engines:kinds.openai.description")} ${t("engines:dialog.typeServes", { list: processList(["transcription", "summary"]) })}`,
    )).toBeInTheDocument();
    expect(within(dialog()).getByLabelText(t("engines:dialog.baseUrl"))).toHaveValue("https://api.openai.example/v1");
    expect(within(dialog()).getByLabelText(t("engines:dialog.key"))).toBeInTheDocument();
  });

  it("explains every field with a line of help", async () => {
    await renderReady([]);
    addKind("openai");
    expect(within(dialog()).getByText(t("engines:dialog.nameHelp"))).toBeInTheDocument();
    expect(within(dialog()).getByText(t("engines:dialog.baseUrlHelp"))).toBeInTheDocument();
    expect(within(dialog()).getByText(t("engines:dialog.keyHelp"))).toBeInTheDocument();
    expect(within(dialog()).getByText(t("engines:dialog.enabledHelp"))).toBeInTheDocument();
    expect(within(dialog()).getByLabelText(t("engines:dialog.key"))).toHaveAttribute("placeholder", t("engines:dialog.keyPlaceholder"));
  });

  it("creates, stores the key, tests the connection and never renders the key", async () => {
    await renderReady([]);
    addKind("openai");
    const keyField = within(dialog()).getByLabelText(t("engines:dialog.key")) as HTMLInputElement;
    expect(keyField.type).toBe("password");
    expect(keyField).toHaveValue("");
    fireEvent.change(keyField, { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));

    expect(await within(dialog()).findByText(t("engines:dialog.testOk"))).toBeInTheDocument();
    expect(within(dialog()).getByText(t("engines:dialog.latency", { ms: 120 }), { exact: false })).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`))
      .toEqual(["POST /providers", "PUT /providers/p1/key", "POST /providers/p1/test"]);
    expect(writes()[0].body).toEqual({ kind: "openai", label: t("engines:kinds.openai.label"), base_url: "https://api.openai.example/v1", enabled: true });
    expect(JSON.stringify(writes()[0].body)).not.toContain(SECRET);
    expect(writes()[1].body).toEqual({ key: SECRET });

    // After saving, only the hint is shown, in the field's placeholder; the typed value is gone.
    const saved = within(dialog()).getByLabelText(t("engines:dialog.key")) as HTMLInputElement;
    expect(saved).toHaveValue("");
    expect(saved).toHaveAttribute("placeholder", t("engines:dialog.keySavedPlaceholderHint", { hint: SECRET_HINT }));
    expect(renderedKeyTraces(SECRET)).toEqual([]);
    expect(within(dialog()).getByRole("button", { name: t("engines:dialog.removeKey") })).toBeInTheDocument();

    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.done") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(card(t("engines:kinds.openai.label"))).getByText(t("engines:card.keyShown", { hint: SECRET_HINT }))).toBeInTheDocument();
    expect(renderedKeyTraces(SECRET)).toEqual([]);
  });

  it("asks the API to test the summary with the real format and says what it found", async () => {
    await renderReady([]);
    backend.probe.json_schema_ok = true;
    backend.probe.schema_model = "model-a";
    addKind("openai");
    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.key")), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByText(t("engines:dialog.testSchemaOk", { model: "model-a" }))).toBeInTheDocument();
    expect(writes().find((call) => call.path === "/providers/p1/test")?.body).toEqual({ capability: "summary" });
  });

  it.each([
    ["incompatible", { json_schema_ok: false, schema_error_class: "provider_bad_request" as const }, () => t("engines:dialog.testSchemaIncompatible", { model: "model-b" })],
    ["slow", { json_schema_ok: null, schema_error_class: "provider_timeout" as const }, () => t("engines:dialog.testSchemaSlow", { model: "model-b" })],
    ["unavailable", { json_schema_ok: null, schema_error_class: "provider_model_unavailable" as const }, () => t("engines:dialog.testSchemaUnavailable", { model: "model-b" })],
  ])("tells a %s model apart when the connection itself responds", async (_name, found, expected) => {
    await renderReady([]);
    Object.assign(backend.probe, found, { schema_model: "model-b" });
    addKind("openai");
    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.key")), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByText(expected())).toBeInTheDocument();
    expect(within(dialog()).getByText(t("engines:dialog.testOk"))).toBeInTheDocument();
  });

  it("names the cause in words when the connection does not respond", async () => {
    await renderReady([]);
    backend.probe.ok = false;
    backend.probe.error_class = "provider_auth";
    addKind("openai");
    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.key")), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));

    const result = await within(dialog()).findByText(t("engines:dialog.testFail"));
    expect(result.closest("p")).toHaveTextContent(t("engines:causes.provider_auth"));
    expect(renderedKeyTraces(SECRET)).toEqual([]);
  });

  it("saves without testing when a provider that needs a key has none", async () => {
    await renderReady([]);
    addKind("openai");
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByText(t("engines:dialog.savedNoKey"))).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["POST /providers"]);
    expect(within(card(t("engines:kinds.openai.label"))).getByText(t("engines:statuses.no_key"))).toBeInTheDocument();
  });

  it("tests a local program without any key", async () => {
    await renderReady([]);
    addKind("ollama");
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByText(t("engines:dialog.testOk"))).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["POST /providers", "POST /providers/p1/test"]);
  });

  it("keeps the primary button off until the form is valid, with the reason written under the field", async () => {
    await renderReady([provider({ id: "p1", label: "Taken" })]);
    addKind("openai");
    const primary = () => within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") });
    expect(primary()).toBeEnabled();

    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.name")), { target: { value: "  " } });
    fireEvent.blur(within(dialog()).getByLabelText(t("engines:dialog.name")));
    expect(within(dialog()).getByText(t("engines:dialog.nameRequired"))).toBeInTheDocument();
    expect(primary()).toBeDisabled();

    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.name")), { target: { value: "taken" } });
    expect(within(dialog()).getByText(t("engines:dialog.nameDuplicate"))).toBeInTheDocument();
    expect(within(dialog()).getByLabelText(t("engines:dialog.name"))).toHaveAttribute("aria-invalid", "true");
    expect(primary()).toBeDisabled();

    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.name")), { target: { value: "Mine" } });
    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.baseUrl")), { target: { value: "ftp://nope" } });
    expect(within(dialog()).getByText(t("engines:dialog.baseUrlInvalid"))).toBeInTheDocument();
    expect(primary()).toBeDisabled();

    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.baseUrl")), { target: { value: "" } });
    fireEvent.blur(within(dialog()).getByLabelText(t("engines:dialog.baseUrl")));
    expect(within(dialog()).getByText(t("engines:dialog.baseUrlRequired"))).toBeInTheDocument();
    expect(primary()).toBeDisabled();
    expect(writes()).toEqual([]);
  });

  it("rejects a key with spaces locally and never sends it", async () => {
    await renderReady([]);
    addKind("openai");
    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.key")), { target: { value: "not a key" } });
    expect(within(dialog()).getByText(t("engines:dialog.keyInvalid"))).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") })).toBeDisabled();
    expect(writes()).toEqual([]);
  });

  it("explains a name the API refuses and keeps the dialog open", async () => {
    await renderReady([]);
    addKind("openai");
    // The screen did not know about this name (another tab created it), so the API answers.
    backend.providers.push(provider({ id: "px", label: t("engines:kinds.openai.label") }));
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByRole("alert")).toHaveTextContent(t("engines:saveErrors.conflict"));
  });

  it("does not retry the creation when the key step fails after the provider was created", async () => {
    await renderReady([]);
    backend.failing.add("PUT /providers/p1/key");
    addKind("openai");
    fireEvent.change(within(dialog()).getByLabelText(t("engines:dialog.key")), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByRole("alert")).toHaveTextContent(t("engines:genericError"));

    backend.failing.clear();
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));
    expect(await within(dialog()).findByText(t("engines:dialog.testOk"))).toBeInTheDocument();
    expect(writes().filter((call) => call.method === "POST" && call.path === "/providers")).toHaveLength(1);
  });
});

describe("editing a provider", () => {
  const edit = (name: string) => fireEvent.click(screen.getByRole("button", { name: t("engines:card.edit", { name }) }));

  it("never preloads the key: shows only the hint in the placeholder, with the kind fixed", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", key_hint: SECRET_HINT })]);
    edit("Work OpenAI");
    expect(dialog()).toHaveAccessibleName(t("engines:dialog.editTitle"));
    const field = within(dialog()).getByLabelText(t("engines:dialog.key")) as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("placeholder", t("engines:dialog.keySavedPlaceholderHint", { hint: SECRET_HINT }));
    expect(within(dialog()).getByLabelText(t("engines:dialog.name"))).toHaveValue("Work OpenAI");
    expect(within(dialog()).getByLabelText(t("engines:dialog.baseUrl"))).toHaveValue("https://api.openai.example/v1");
    expect(within(dialog()).queryByRole("radiogroup")).toBeNull();
    expect(within(dialog()).getByText(t("engines:kinds.openai.label"))).toBeInTheDocument();
  });

  it("does not count its own name as a duplicate", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    edit("Work OpenAI");
    expect(within(dialog()).queryByText(t("engines:dialog.nameDuplicate"))).toBeNull();
    expect(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") })).toBeEnabled();
  });

  it("replaces the key by typing a new one in the same field", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    edit("Work OpenAI");
    const field = within(dialog()).getByLabelText(t("engines:dialog.key")) as HTMLInputElement;
    fireEvent.change(field, { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));

    expect(await within(dialog()).findByText(t("engines:dialog.testOk"))).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["PUT /providers/p1/key", "POST /providers/p1/test"]);
    expect(within(dialog()).getByLabelText(t("engines:dialog.key"))).toHaveValue("");
    expect(within(dialog()).getByLabelText(t("engines:dialog.key"))).toHaveAttribute("placeholder", t("engines:dialog.keySavedPlaceholderHint", { hint: SECRET_HINT }));
    expect(renderedKeyTraces(SECRET)).toEqual([]);
  });

  it("removes the key after listing the processes that go back to the local engine", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["summary"] })]);
    edit("Work OpenAI");
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.removeKey") }));
    expect(within(dialog()).getByText(t("engines:dialog.removeKeyConfirm"), { exact: false }))
      .toHaveTextContent(t("engines:dialog.removeKeyReverts", { list: t("engines:processes.summary") }));
    expect(writes()).toEqual([]);

    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.removeKey") }));
    await waitFor(() => expect(within(dialog()).getByText(t("engines:dialog.keyRemovedReverted", { list: t("engines:processes.summary") }))).toBeInTheDocument());
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["DELETE /providers/p1/key"]);
    expect(within(dialog()).getByLabelText(t("engines:dialog.key"))).toHaveAttribute("placeholder", t("engines:dialog.keyPlaceholder"));
    expect(within(card("Work OpenAI")).getByText(t("engines:statuses.no_key"))).toBeInTheDocument();
  });

  it("can keep the key after asking to remove it", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    edit("Work OpenAI");
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.removeKey") }));
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.removeKeyKeep") }));
    expect(within(dialog()).getByRole("button", { name: t("engines:dialog.removeKey") })).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("edits only what changed and reports processes that went back to local", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["transcription"] })]);
    edit("Work OpenAI");
    fireEvent.click(within(dialog()).getByRole("switch", { name: t("engines:dialog.enabled") }));
    fireEvent.click(within(dialog()).getByRole("button", { name: t("engines:dialog.saveAndTest") }));

    await waitFor(() => expect(within(dialog()).getByText(t("engines:dialog.revertedByEdit", { list: t("engines:processes.transcription") }))).toBeInTheDocument());
    expect(writes()[0]).toEqual({ method: "PATCH", path: "/providers/p1", body: { enabled: false } });
    expect(within(card("Work OpenAI")).getByText(t("engines:statuses.disabled"))).toBeInTheDocument();
  });
});

describe("deleting a provider", () => {
  it("lists the processes that will go back to local and deletes on confirm", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["summary", "transcription"] })]);
    fireEvent.click(screen.getByRole("button", { name: t("engines:card.remove", { name: "Work OpenAI" }) }));
    const confirm = screen.getByRole("dialog", { name: t("engines:remove.title") });
    const list = processList(["summary", "transcription"]);
    expect(within(confirm).getByText(t("engines:remove.reverts", { list }))).toBeInTheDocument();
    expect(writes()).toEqual([]);

    fireEvent.click(within(confirm).getByRole("button", { name: t("engines:remove.confirm") }));
    await waitFor(() => expect(screen.queryByRole("heading", { level: 4, name: "Work OpenAI" })).toBeNull());
    expect(writes()).toEqual([{ method: "DELETE", path: "/providers/p1", body: null }]);
    expect(screen.getByText(t("engines:remove.doneReverted", { name: "Work OpenAI", list }))).toBeInTheDocument();
    // No card stands in for it: the screen is back to its empty state, with focus on the «Agregar» tile.
    expect(screen.queryAllByRole("heading", { level: 4 })).toHaveLength(0);
    expect(screen.getByText(t("engines:empty"))).toBeInTheDocument();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: t("engines:add") }));
  });

  it("says nothing changes when no process uses the provider, and cancel deletes nothing", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    fireEvent.click(screen.getByRole("button", { name: t("engines:card.remove", { name: "Work OpenAI" }) }));
    const confirm = screen.getByRole("dialog", { name: t("engines:remove.title") });
    expect(within(confirm).getByText(t("engines:remove.noReverts"))).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: t("engines:remove.cancel") }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toEqual([]);
    expect(screen.getByRole("heading", { level: 4, name: "Work OpenAI" })).toBeInTheDocument();
  });

  it("keeps the card and says so when the API refuses", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    backend.failing.add("DELETE /providers/p1");
    fireEvent.click(screen.getByRole("button", { name: t("engines:card.remove", { name: "Work OpenAI" }) }));
    fireEvent.click(within(screen.getByRole("dialog", { name: t("engines:remove.title") })).getByRole("button", { name: t("engines:remove.confirm") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("engines:remove.failed"));
    expect(screen.getByRole("heading", { level: 4, name: "Work OpenAI" })).toBeInTheDocument();
  });
});

describe("provider dialog focus", () => {
  it("moves focus in, keeps Tab inside, closes with Escape and returns focus to the opener", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    const opener = screen.getByRole("button", { name: t("engines:card.edit", { name: "Work OpenAI" }) });
    opener.focus();
    fireEvent.click(opener);

    const panel = dialog();
    expect(panel.contains(document.activeElement)).toBe(true);

    const tabbables = Array.from(panel.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled)"));
    const last = tabbables[tabbables.length - 1];
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(tabbables[0]);
    fireEvent.keyDown(tabbables[0], { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});
