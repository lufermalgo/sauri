// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { EngineAccount, EngineKindInfo, EngineModelList, EngineProcess, EngineProvider } from "@sauri/shared-types";
import { copy } from "../copy/es";
import { EnginesSettings } from "./settings/EnginesSettings";

const text = copy.engines;
const account = text.account;

const PLAN_KIND: EngineKindInfo = {
  kind: "chatgpt_plan",
  default_base_url: "https://chatgpt.com/backend-api/codex",
  key_required: false,
  auth: "account",
  linkable: true,
  capabilities: [{ capability: "summary", transport: "chatgpt-responses", verified_on: null }],
};

const DISCONNECTED: EngineAccount = { state: "disconnected", account: null, plan: null, pending: null, error: null, reverted_processes: [] };
const PENDING: EngineAccount = {
  ...DISCONNECTED,
  state: "pending",
  pending: {
    user_code: "ABCD-1234",
    verification_url: "https://auth.openai.com/codex/device",
    expires_at: "2027-01-15T08:15:00Z",
    interval_s: 5,
    slow_down: false,
  },
};
const CONNECTED: EngineAccount = { ...DISCONNECTED, state: "connected", account: "owner@example.com", plan: "plus" };

const PLAN_MODELS: EngineModelList = {
  models: [{ id: "gpt-5", label: "GPT-5", serves: ["summary"] }],
  starter: "gpt-5",
  from_cache: false,
  fetched_at: new Date().toISOString(),
  manual_entry: false,
  error_class: null,
  serves: ["summary"],
};

function planProvider(overrides: Partial<EngineProvider> = {}): EngineProvider {
  return {
    id: "plan1",
    kind: "chatgpt_plan",
    label: "ChatGPT (plan)",
    base_url: "https://chatgpt.com/backend-api/codex",
    enabled: true,
    status: "active",
    key_set: false,
    key_hint: null,
    key_set_at: null,
    used_by: [],
    created_at: "2026-11-16T10:00:00Z",
    updated_at: "2026-11-16T10:00:00Z",
    ...overrides,
  };
}

interface Call { method: string; path: string; body: Record<string, unknown> | null }

function fakeBackend(initial: EngineProvider[], state: { account: EngineAccount; polls: EngineAccount[]; models: EngineModelList }) {
  const providers = initial.map((item) => ({ ...item }));
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const path = url.pathname.replace("/api/v1/engines", "") || "/";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, path, body });
    if (path === "/capabilities") return json({ notice_versions: { transcription: 1, diarization: 1, summary: 1 }, kinds: [PLAN_KIND] });
    if (method === "GET" && path === "/providers") return json(providers);
    if (method === "POST" && path === "/providers") {
      const created = planProvider({ id: "plan-new", label: String(body?.label), base_url: String(body?.base_url) });
      providers.push(created);
      return json(created, 201);
    }
    if (path.endsWith("/models")) return json(state.models);
    if (path.endsWith("/account") && method === "GET") return json(state.account);
    if (path.endsWith("/account/start")) {
      state.account = PENDING;
      return json(PENDING);
    }
    if (path.endsWith("/account/poll")) {
      if (state.polls.length > 0) state.account = state.polls.shift()!;
      return json(state.account);
    }
    if (path.endsWith("/account") && method === "DELETE") {
      const reverted: EngineProcess[] = providers[0]?.used_by ?? [];
      state.account = DISCONNECTED;
      if (providers[0]) providers[0].used_by = [];
      return json({ ...DISCONNECTED, reverted_processes: reverted });
    }
    return json({ detail: "unexpected" }, 404);
  });
  return { handler, calls };
}

let backend: ReturnType<typeof fakeBackend>;

async function renderReady(initial: EngineProvider[], accountState: EngineAccount, polls: EngineAccount[] = []) {
  backend = fakeBackend(initial, { account: accountState, polls, models: PLAN_MODELS });
  vi.stubGlobal("fetch", backend.handler);
  render(<EnginesSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: text.add })).toBeEnabled());
}

const card = (name: string) => screen.getByRole("heading", { level: 4, name }).closest("section")!;

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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ChatGPT (plan) card", () => {
  it("offers the connect button, says what it serves and that it needs no key", async () => {
    await renderReady([], DISCONNECTED);
    const tile = within(card(text.kinds.chatgpt_plan.label));
    expect(tile.getByText(account.unconfigured, { exact: false })).toBeInTheDocument();
    expect(tile.getByRole("button", { name: account.connectLabel(text.kinds.chatgpt_plan.label) })).toHaveTextContent(account.connect);
    expect(tile.queryByText(text.card.key)).toBeNull();
  });

  it("shows the connected account, what it serves, its models and the disconnect button", async () => {
    await renderReady([planProvider()], CONNECTED);
    const tile = within(card("ChatGPT (plan)"));
    expect(await tile.findByText(account.connectedAs("owner@example.com"))).toBeInTheDocument();
    expect(tile.getByText(text.card.serves(text.processes.summary))).toBeInTheDocument();
    expect(await tile.findByText(text.card.modelsCount(1))).toBeInTheDocument();
    expect(tile.getByRole("button", { name: account.disconnectLabel("ChatGPT (plan)") })).toBeInTheDocument();
    expect(tile.getByText(account.unofficial)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toMatch(/access_token|refresh_token/);
  });

  it("while signed out it still says what it serves and offers to connect", async () => {
    await renderReady([planProvider()], { ...DISCONNECTED, error: "session_expired" });
    const tile = within(card("ChatGPT (plan)"));
    expect(await tile.findByText(account.errors.session_expired)).toBeInTheDocument();
    expect(tile.getByText(text.card.serves(text.processes.summary))).toBeInTheDocument();
    expect(tile.getByRole("button", { name: account.connectLabel("ChatGPT (plan)") })).toBeEnabled();
  });
});

describe("signing in", () => {
  it("creates the provider, shows the code and a button that opens the page in a new tab, polls until connected", async () => {
    await renderReady([], DISCONNECTED, [PENDING, CONNECTED]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(card(text.kinds.chatgpt_plan.label)).getByRole("button", { name: account.connectLabel(text.kinds.chatgpt_plan.label) }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("ABCD-1234")).toBeInTheDocument();
    const open = within(dialog).getByRole("link", { name: account.dialog.openPage });
    expect(open).toHaveAttribute("href", "https://auth.openai.com/codex/device");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(backend.calls.find((call) => call.method === "POST" && call.path === "/providers")?.body).toEqual({
      kind: "chatgpt_plan",
      label: "ChatGPT (plan)",
      base_url: "https://chatgpt.com/backend-api/codex",
      enabled: true,
    });
    const polls = () => backend.calls.filter((call) => call.path.endsWith("/account/poll")).length;
    expect(polls()).toBe(0); // it waits the interval before the first check
    await act(() => vi.advanceTimersByTimeAsync(5000));
    await waitFor(() => expect(polls()).toBe(1));
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(await within(dialog).findByText(account.dialog.connected("owner@example.com"))).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(20000));
    expect(polls()).toBe(2); // polling stopped once connected
    fireEvent.click(within(dialog).getByRole("button", { name: account.dialog.done }));
    expect(await within(card("ChatGPT (plan)")).findByText(account.connectedAs("owner@example.com"))).toBeInTheDocument();
  });

  it("says why when the code runs out and offers another one", async () => {
    await renderReady([planProvider()], DISCONNECTED, [{ ...DISCONNECTED, error: "code_expired" }]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(card("ChatGPT (plan)")).getByRole("button", { name: account.connectLabel("ChatGPT (plan)") }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("ABCD-1234");
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(await within(dialog).findByText(account.errors.code_expired)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: account.dialog.retry })).toBeInTheDocument();
  });

  it("stops asking when the dialog is closed", async () => {
    await renderReady([planProvider()], DISCONNECTED, [PENDING]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(card("ChatGPT (plan)")).getByRole("button", { name: account.connectLabel("ChatGPT (plan)") }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("ABCD-1234");
    fireEvent.click(within(dialog).getByRole("button", { name: account.dialog.cancel }));
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(backend.calls.filter((call) => call.path.endsWith("/account/poll"))).toHaveLength(0);
  });
});

describe("disconnecting", () => {
  it("asks first, then forgets the account and says which processes went back to local", async () => {
    await renderReady([planProvider({ used_by: ["summary"] })], CONNECTED);
    const tile = within(card("ChatGPT (plan)"));
    fireEvent.click(await tile.findByRole("button", { name: account.disconnectLabel("ChatGPT (plan)") }));
    const confirm = within(await screen.findByRole("dialog"));
    expect(confirm.getByText(account.disconnectDialog.reverts(text.processes.summary))).toBeInTheDocument();
    fireEvent.click(confirm.getByRole("button", { name: account.disconnectDialog.confirm }));
    expect(
      await screen.findByText(account.disconnectedReverted("ChatGPT (plan)", text.processes.summary)),
    ).toBeInTheDocument();
    expect(await tile.findByText(account.notConnected)).toBeInTheDocument();
  });
});
