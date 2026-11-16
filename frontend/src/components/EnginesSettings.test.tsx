// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type {
  EngineErrorClass,
  EngineKindInfo,
  EngineProcess,
  EngineProvider,
  EngineProviderKind,
} from "@sauri/shared-types";
import { copy } from "../copy/es";
import { EnginesSettings } from "./settings/EnginesSettings";

const text = copy.engines;
const dialogText = text.dialog;

const SECRET = "sk-test-0123456789abcdefWXYZ";
const SECRET_HINT = "WXYZ";

function kindInfo(kind: EngineProviderKind, overrides: Partial<EngineKindInfo> = {}): EngineKindInfo {
  const localApp = kind === "ollama" || kind === "lmstudio";
  return {
    kind,
    default_base_url: localApp ? `http://127.0.0.1:${kind === "ollama" ? 11434 : 1234}/v1` : `https://api.${kind}.example/v1`,
    key_required: !localApp && kind !== "openai_compatible",
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
  kindInfo("openai_compatible", { default_base_url: null }),
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

interface Call { method: string; path: string; body: Record<string, unknown> | null }

/** An in-memory stand-in for /api/v1/engines with the behaviors the screen depends on. */
function fakeBackend(initial: EngineProvider[]) {
  const providers = initial.map((item) => ({ ...item }));
  const calls: Call[] = [];
  const failing = new Set<string>();
  const probe = { ok: true, latency_ms: 120, error_class: null as EngineErrorClass | null, json_schema_ok: null };
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/engines", "") || "/";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, path, body });
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
  return { handler, calls, failing, providers, probe };
}

let backend: ReturnType<typeof fakeBackend>;

async function renderReady(initial: EngineProvider[]) {
  backend = fakeBackend(initial);
  vi.stubGlobal("fetch", backend.handler);
  render(<EnginesSettings />);
  await waitFor(() => expect(screen.getAllByRole("button", { name: text.add })[0]).toBeEnabled());
}

const writes = () => backend.calls.filter((call) => call.method !== "GET");
const card = (name: string) => screen.getByRole("heading", { level: 3, name }).closest("section")!;
const dialog = () => screen.getByRole("dialog");

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

describe("providers grid", () => {
  it("shows one card per provider with its state written as text", async () => {
    await renderReady([
      provider({ id: "p1", label: "Work OpenAI", used_by: ["summary", "transcription"] }),
      provider({ id: "p2", label: "No key yet", kind: "anthropic", key_set: false, key_hint: null, status: "no_key" }),
      provider({ id: "p3", label: "Paused", status: "disabled", enabled: false }),
      provider({ id: "p4", label: "Local Ollama", kind: "ollama", base_url: "http://127.0.0.1:11434/v1", key_set: false, key_hint: null }),
    ]);
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent))
      .toEqual(["Work OpenAI", "No key yet", "Paused", "Local Ollama"]);

    expect(within(card("Work OpenAI")).getByText(text.statuses.active)).toBeInTheDocument();
    expect(within(card("No key yet")).getByText(text.statuses.no_key)).toBeInTheDocument();
    expect(within(card("Paused")).getByText(text.statuses.disabled)).toBeInTheDocument();
    expect(within(card("Work OpenAI")).getByText(text.card.usedBy(`${text.processes.summary}, ${text.processes.transcription}`)))
      .toBeInTheDocument();
    expect(within(card("No key yet")).getByText(text.card.unused)).toBeInTheDocument();
    expect(within(card("Work OpenAI")).getByText(text.card.serves(`${text.processes.transcription}, ${text.processes.summary}`)))
      .toBeInTheDocument();
    expect(within(card("Local Ollama")).getByText(text.card.keyOptional)).toBeInTheDocument();
    expect(within(card("Work OpenAI")).getByText(text.card.keySaved("1234"))).toBeInTheDocument();
  });

  it("gives every card manage, edit and delete controls named after the provider", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    const scope = within(card("Work OpenAI"));
    expect(scope.getByRole("button", { name: text.card.manageLabel("Work OpenAI") })).toHaveTextContent(text.card.manage);
    expect(scope.getByRole("button", { name: text.card.edit("Work OpenAI") })).toBeInTheDocument();
    expect(scope.getByRole("button", { name: text.card.remove("Work OpenAI") })).toBeInTheDocument();
  });

  it("shows a loading state, then an empty state with a next action", async () => {
    backend = fakeBackend([]);
    vi.stubGlobal("fetch", backend.handler);
    render(<EnginesSettings />);
    expect(screen.getByText(text.loading)).toBeInTheDocument();
    expect(await screen.findByText(text.emptyTitle)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: text.add })).toHaveLength(2);
  });

  it("shows a load error that can be retried", async () => {
    backend = fakeBackend([provider({ id: "p1", label: "Work OpenAI" })]);
    vi.stubGlobal("fetch", backend.handler);
    backend.failing.add("GET /providers");
    render(<EnginesSettings />);
    expect(await screen.findByRole("alert")).toHaveTextContent(text.loadError);
    expect(screen.getByRole("button", { name: text.add })).toBeDisabled();

    backend.failing.clear();
    fireEvent.click(screen.getByRole("button", { name: text.retry }));
    expect(await screen.findByRole("heading", { level: 3, name: "Work OpenAI" })).toBeInTheDocument();
  });

  it("sends the stored token", async () => {
    await renderReady([]);
    const first = backend.handler.mock.calls[0];
    expect((first[1]?.headers as Record<string, string>).Authorization).toBe("Bearer synthetic-token");
  });
});

describe("adding a provider", () => {
  it("offers the types the API says can be linked, with the default address filled in", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    const select = within(dialog()).getByLabelText(dialogText.type) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      text.kinds.openai.label,
      text.kinds.anthropic.label,
      text.kinds.ollama.label,
      text.kinds.lmstudio.label,
      text.kinds.openai_compatible.label,
    ]);
    expect(within(dialog()).getByLabelText(dialogText.baseUrl)).toHaveValue("https://api.openai.example/v1");
    expect(within(dialog()).getByLabelText(dialogText.name)).toHaveValue(text.kinds.openai.label);

    fireEvent.change(select, { target: { value: "ollama" } });
    expect(within(dialog()).getByLabelText(dialogText.baseUrl)).toHaveValue("http://127.0.0.1:11434/v1");
    expect(within(dialog()).getByLabelText(dialogText.name)).toHaveValue(text.kinds.ollama.label);
    expect(within(dialog()).getByText(dialogText.localNote)).toBeInTheDocument();
    expect(within(dialog()).getByText(dialogText.keyOptionalHelp)).toBeInTheDocument();
  });

  it("keeps a name the person typed when the type changes", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.change(within(dialog()).getByLabelText(dialogText.name), { target: { value: "My account" } });
    fireEvent.change(within(dialog()).getByLabelText(dialogText.type), { target: { value: "anthropic" } });
    expect(within(dialog()).getByLabelText(dialogText.name)).toHaveValue("My account");
  });

  it("creates, stores the key, tests the connection and never renders the key", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    const keyField = within(dialog()).getByLabelText(dialogText.key) as HTMLInputElement;
    expect(keyField.type).toBe("password");
    expect(keyField).toHaveValue("");
    fireEvent.change(keyField, { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));

    expect(await within(dialog()).findByText(dialogText.testOk)).toBeInTheDocument();
    expect(within(dialog()).getByText(dialogText.latency(120), { exact: false })).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`))
      .toEqual(["POST /providers", "PUT /providers/p1/key", "POST /providers/p1/test"]);
    expect(writes()[0].body).toEqual({ kind: "openai", label: text.kinds.openai.label, base_url: "https://api.openai.example/v1", enabled: true });
    expect(JSON.stringify(writes()[0].body)).not.toContain(SECRET);
    expect(writes()[1].body).toEqual({ key: SECRET });

    // After saving, only the hint is shown; the typed value is gone from the page.
    expect(within(dialog()).getByText(dialogText.keySaved(SECRET_HINT))).toBeInTheDocument();
    expect(within(dialog()).queryByLabelText(dialogText.key, { selector: "input" })).toBeNull();
    expect(renderedKeyTraces(SECRET)).toEqual([]);
    expect(within(dialog()).getByRole("button", { name: dialogText.replace })).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: dialogText.removeKey })).toBeInTheDocument();

    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.done }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(card(text.kinds.openai.label)).getByText(text.card.keySaved(SECRET_HINT))).toBeInTheDocument();
    expect(renderedKeyTraces(SECRET)).toEqual([]);
  });

  it("names the cause in words when the connection does not respond", async () => {
    await renderReady([]);
    backend.probe.ok = false;
    backend.probe.error_class = "provider_auth";
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.change(within(dialog()).getByLabelText(dialogText.key), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));

    const result = await within(dialog()).findByText(dialogText.testFail);
    expect(result.closest("p")).toHaveTextContent(text.causes.provider_auth);
    expect(renderedKeyTraces(SECRET)).toEqual([]);
  });

  it("saves without testing when a provider that needs a key has none", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByText(dialogText.savedNoKey)).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["POST /providers"]);
    expect(within(card(text.kinds.openai.label)).getByText(text.statuses.no_key)).toBeInTheDocument();
  });

  it("tests a local program without any key", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.change(within(dialog()).getByLabelText(dialogText.type), { target: { value: "ollama" } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByText(dialogText.testOk)).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["POST /providers", "POST /providers/p1/test"]);
  });

  it("validates the name and the address before calling the API", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.change(within(dialog()).getByLabelText(dialogText.name), { target: { value: "  " } });
    fireEvent.change(within(dialog()).getByLabelText(dialogText.baseUrl), { target: { value: "" } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByText(dialogText.nameRequired)).toBeInTheDocument();
    expect(within(dialog()).getByText(dialogText.baseUrlRequired)).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("rejects a key with spaces locally and never sends it", async () => {
    await renderReady([]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.change(within(dialog()).getByLabelText(dialogText.key), { target: { value: "not a key" } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByText(dialogText.keyInvalid)).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("explains a duplicate name and keeps the dialog open", async () => {
    await renderReady([provider({ id: "p1", label: text.kinds.openai.label })]);
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByRole("alert")).toHaveTextContent(text.saveErrors.conflict);
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(1);
  });

  it("does not retry the creation when the key step fails after the provider was created", async () => {
    await renderReady([]);
    backend.failing.add("PUT /providers/p1/key");
    fireEvent.click(screen.getAllByRole("button", { name: text.add })[0]);
    fireEvent.change(within(dialog()).getByLabelText(dialogText.key), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByRole("alert")).toHaveTextContent(text.genericError);

    backend.failing.clear();
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));
    expect(await within(dialog()).findByText(dialogText.testOk)).toBeInTheDocument();
    expect(writes().filter((call) => call.method === "POST" && call.path === "/providers")).toHaveLength(1);
  });
});

describe("managing a provider", () => {
  it("never preloads the key: shows only the hint with replace and remove actions", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", key_hint: SECRET_HINT })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.manageLabel("Work OpenAI") }));
    expect(dialog()).toHaveAccessibleName(dialogText.editTitle);
    expect(within(dialog()).getByText(dialogText.keySaved(SECRET_HINT))).toBeInTheDocument();
    expect(dialog().querySelectorAll('input[type="password"]')).toHaveLength(0);
    expect(within(dialog()).getByLabelText(dialogText.name)).toHaveValue("Work OpenAI");
    expect(within(dialog()).getByLabelText(dialogText.baseUrl)).toHaveValue("https://api.openai.example/v1");
    expect(within(dialog()).queryByLabelText(dialogText.type)).toBeNull();
  });

  it("replaces the key through an empty password field", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.manageLabel("Work OpenAI") }));
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.replace }));
    const field = within(dialog()).getByLabelText(dialogText.keyNew) as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field).toHaveValue("");
    fireEvent.change(field, { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));

    expect(await within(dialog()).findByText(dialogText.testOk)).toBeInTheDocument();
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["PUT /providers/p1/key", "POST /providers/p1/test"]);
    expect(within(dialog()).getByText(dialogText.keySaved(SECRET_HINT))).toBeInTheDocument();
    expect(renderedKeyTraces(SECRET)).toEqual([]);
  });

  it("can cancel a replacement without touching the stored key", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.manageLabel("Work OpenAI") }));
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.replace }));
    fireEvent.change(within(dialog()).getByLabelText(dialogText.keyNew), { target: { value: SECRET } });
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.cancelReplace }));
    expect(within(dialog()).getByText(dialogText.keySaved("1234"))).toBeInTheDocument();
    expect(renderedKeyTraces(SECRET)).toEqual([]);
    expect(writes()).toEqual([]);
  });

  it("removes the key after listing the processes that go back to the local engine", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["summary"] })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.manageLabel("Work OpenAI") }));
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.removeKey }));
    expect(within(dialog()).getByText(dialogText.removeKeyConfirm, { exact: false }))
      .toHaveTextContent(dialogText.removeKeyReverts(text.processes.summary));
    expect(writes()).toEqual([]);

    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.removeKey }));
    await waitFor(() => expect(within(dialog()).getByText(dialogText.keyRemovedReverted(text.processes.summary))).toBeInTheDocument());
    expect(writes().map((call) => `${call.method} ${call.path}`)).toEqual(["DELETE /providers/p1/key"]);
    expect(within(dialog()).getByLabelText(dialogText.key)).toHaveValue("");
    expect(within(card("Work OpenAI")).getByText(text.statuses.no_key)).toBeInTheDocument();
  });

  it("edits only what changed and reports processes that went back to local", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["transcription"] })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.edit("Work OpenAI") }));
    fireEvent.click(within(dialog()).getByRole("switch", { name: dialogText.enabled }));
    fireEvent.click(within(dialog()).getByRole("button", { name: dialogText.saveAndTest }));

    await waitFor(() => expect(within(dialog()).getByText(dialogText.revertedByEdit(text.processes.transcription))).toBeInTheDocument());
    expect(writes()[0]).toEqual({ method: "PATCH", path: "/providers/p1", body: { enabled: false } });
    expect(within(card("Work OpenAI")).getByText(text.statuses.disabled)).toBeInTheDocument();
  });
});

describe("deleting a provider", () => {
  it("lists the processes that will go back to local and deletes on confirm", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI", used_by: ["summary", "transcription"] })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.remove("Work OpenAI") }));
    const confirm = screen.getByRole("dialog", { name: text.remove.title });
    const list = `${text.processes.summary}, ${text.processes.transcription}`;
    expect(within(confirm).getByText(text.remove.reverts(list))).toBeInTheDocument();
    expect(writes()).toEqual([]);

    fireEvent.click(within(confirm).getByRole("button", { name: text.remove.confirm }));
    await waitFor(() => expect(screen.queryByRole("heading", { level: 3, name: "Work OpenAI" })).toBeNull());
    expect(writes()).toEqual([{ method: "DELETE", path: "/providers/p1", body: null }]);
    expect(screen.getByText(text.remove.doneReverted("Work OpenAI", list))).toBeInTheDocument();
    expect(screen.getByText(text.emptyTitle)).toBeInTheDocument();
  });

  it("says nothing changes when no process uses the provider, and cancel deletes nothing", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    fireEvent.click(screen.getByRole("button", { name: text.card.remove("Work OpenAI") }));
    const confirm = screen.getByRole("dialog", { name: text.remove.title });
    expect(within(confirm).getByText(text.remove.noReverts)).toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: text.remove.cancel }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes()).toEqual([]);
    expect(screen.getByRole("heading", { level: 3, name: "Work OpenAI" })).toBeInTheDocument();
  });

  it("keeps the card and says so when the API refuses", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    backend.failing.add("DELETE /providers/p1");
    fireEvent.click(screen.getByRole("button", { name: text.card.remove("Work OpenAI") }));
    fireEvent.click(within(screen.getByRole("dialog", { name: text.remove.title })).getByRole("button", { name: text.remove.confirm }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.remove.failed);
    expect(screen.getByRole("heading", { level: 3, name: "Work OpenAI" })).toBeInTheDocument();
  });
});

describe("provider dialog focus", () => {
  it("moves focus in, keeps Tab inside, closes with Escape and returns focus to the opener", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    const opener = screen.getByRole("button", { name: text.card.manageLabel("Work OpenAI") });
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

  it("returns focus to the add button when the add dialog is closed", async () => {
    await renderReady([provider({ id: "p1", label: "Work OpenAI" })]);
    const add = screen.getByRole("button", { name: text.add });
    add.focus();
    fireEvent.click(add);
    expect(dialog().contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.activeElement).toBe(add);
  });
});
