// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { EngineAccount, EngineKindInfo, EngineModelList, EngineProcess, EngineProvider } from "@sauri/shared-types";
import { t } from "../i18n";
import { processList } from "./settings/engineLabels";
import { EnginesSettings } from "./settings/EnginesSettings";

const PLAN = "Codex (plan ChatGPT)";
const NAME = { name: PLAN };

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
    label: PLAN,
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

function fakeBackend(initial: EngineProvider[], state: { account: EngineAccount; polls: EngineAccount[]; models: EngineModelList; modelsStatus?: number }) {
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
    if (path.endsWith("/models")) return state.modelsStatus ? json({ detail: "host_unavailable" }, state.modelsStatus) : json(state.models);
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

async function renderReady(
  initial: EngineProvider[], accountState: EngineAccount, polls: EngineAccount[] = [], modelsStatus?: number,
) {
  backend = fakeBackend(initial, { account: accountState, polls, models: PLAN_MODELS, modelsStatus });
  vi.stubGlobal("fetch", backend.handler);
  render(<EnginesSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: t("engines:add") })).toBeEnabled());
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

describe("Codex (plan ChatGPT) card", () => {
  it("offers the connect button, says what it serves and that it needs no key", async () => {
    await renderReady([], DISCONNECTED);
    const tile = within(card(PLAN));
    expect(tile.getByText(t("engines:account.unconfigured"), { exact: false })).toBeInTheDocument();
    expect(tile.getByRole("button", { name: t("engines:account.connectLabel", NAME) })).toHaveTextContent(t("engines:account.connect"));
    expect(tile.queryByText(t("engines:card.key"))).toBeNull();
  });

  it("shows the connected account, what it serves, its models and the disconnect button", async () => {
    await renderReady([planProvider()], CONNECTED);
    const tile = within(card(PLAN));
    expect(await tile.findByText(t("engines:account.connectedAs", { who: "owner@example.com" }))).toBeInTheDocument();
    expect(tile.getByText(t("engines:card.serves", { list: processList(["summary"]) }))).toBeInTheDocument();
    expect(await tile.findByText(t("engines:card.modelsCount", { count: 1 }))).toBeInTheDocument();
    expect(tile.getByRole("button", { name: t("engines:account.disconnectLabel", NAME) })).toBeInTheDocument();
    expect(tile.getByText(t("engines:account.unofficial"))).toBeInTheDocument();
    expect(document.body.innerHTML).not.toMatch(/access_token|refresh_token/);
  });

  it("asks the account for its models when the card opens connected, for the summary process", async () => {
    await renderReady([planProvider()], CONNECTED);
    expect(await within(card(PLAN)).findByText(t("engines:card.modelsCount", { count: 1 }))).toBeInTheDocument();
    const asked = backend.calls.filter((call) => call.path.endsWith("/models"));
    expect(asked).toHaveLength(1);
    expect(asked[0]?.path).toBe("/providers/plan1/models");
  });

  it("says why the models could not be read instead of «no list»", async () => {
    await renderReady([planProvider()], CONNECTED, [], 502);
    const tile = within(card(PLAN));
    expect(await tile.findByText(t("engines:account.modelsFailed"))).toBeInTheDocument();
    expect(tile.queryByText(t("engines:card.modelsNoList"))).toBeNull();
  });

  it("does not ask for models while the account is not connected", async () => {
    await renderReady([planProvider()], DISCONNECTED);
    const tile = within(card(PLAN));
    expect(await tile.findByText(t("engines:account.notConnected"))).toBeInTheDocument();
    expect(tile.getByText(t("engines:card.modelsNotAsked"))).toBeInTheDocument();
    expect(backend.calls.filter((call) => call.path.endsWith("/models"))).toHaveLength(0);
  });

  it("while signed out it still says what it serves and offers to connect", async () => {
    await renderReady([planProvider()], { ...DISCONNECTED, error: "session_expired" });
    const tile = within(card(PLAN));
    expect(await tile.findByText(t("engines:account.errors.session_expired"))).toBeInTheDocument();
    expect(tile.getByText(t("engines:card.serves", { list: processList(["summary"]) }))).toBeInTheDocument();
    expect(tile.getByRole("button", { name: t("engines:account.connectLabel", NAME) })).toBeEnabled();
  });
});

describe("signing in", () => {
  it("creates the provider, shows the code and a button that opens the page in a new tab, polls until connected", async () => {
    await renderReady([], DISCONNECTED, [PENDING, CONNECTED]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(card(PLAN)).getByRole("button", { name: t("engines:account.connectLabel", NAME) }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("ABCD-1234")).toBeInTheDocument();
    const open = within(dialog).getByRole("link", { name: t("engines:account.dialog.openPage") });
    expect(open).toHaveAttribute("href", "https://auth.openai.com/codex/device");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(backend.calls.find((call) => call.method === "POST" && call.path === "/providers")?.body).toEqual({
      kind: "chatgpt_plan",
      label: PLAN,
      base_url: "https://chatgpt.com/backend-api/codex",
      enabled: true,
    });
    const polls = () => backend.calls.filter((call) => call.path.endsWith("/account/poll")).length;
    expect(polls()).toBe(0); // it waits the interval before the first check
    await act(() => vi.advanceTimersByTimeAsync(5000));
    await waitFor(() => expect(polls()).toBe(1));
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(await within(dialog).findByText(t("engines:account.dialog.connected", { who: "owner@example.com" }))).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(20000));
    expect(polls()).toBe(2); // polling stopped once connected
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:account.dialog.done") }));
    expect(await within(card(PLAN)).findByText(t("engines:account.connectedAs", { who: "owner@example.com" }))).toBeInTheDocument();
    // Connected: the card asks the account for its models right away, without reloading the screen.
    expect(await within(card(PLAN)).findByText(t("engines:card.modelsCount", { count: 1 }))).toBeInTheDocument();
    expect(backend.calls.some((call) => call.path === "/providers/plan-new/models")).toBe(true);
  });

  it("says why when the code runs out and offers another one", async () => {
    await renderReady([planProvider()], DISCONNECTED, [{ ...DISCONNECTED, error: "code_expired" }]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(card(PLAN)).getByRole("button", { name: t("engines:account.connectLabel", NAME) }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("ABCD-1234");
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(await within(dialog).findByText(t("engines:account.errors.code_expired"))).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: t("engines:account.dialog.retry") })).toBeInTheDocument();
  });

  it("stops asking when the dialog is closed", async () => {
    await renderReady([planProvider()], DISCONNECTED, [PENDING]);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(within(card(PLAN)).getByRole("button", { name: t("engines:account.connectLabel", NAME) }));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("ABCD-1234");
    fireEvent.click(within(dialog).getByRole("button", { name: t("engines:account.dialog.cancel") }));
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(backend.calls.filter((call) => call.path.endsWith("/account/poll"))).toHaveLength(0);
  });
});

describe("disconnecting", () => {
  it("asks first, then forgets the account and says which processes went back to local", async () => {
    await renderReady([planProvider({ used_by: ["summary"] })], CONNECTED);
    const tile = within(card(PLAN));
    fireEvent.click(await tile.findByRole("button", { name: t("engines:account.disconnectLabel", NAME) }));
    const confirm = within(await screen.findByRole("dialog"));
    expect(confirm.getByText(t("engines:account.disconnectDialog.reverts", { list: processList(["summary"]) }))).toBeInTheDocument();
    fireEvent.click(confirm.getByRole("button", { name: t("engines:account.disconnectDialog.confirm") }));
    expect(
      await screen.findByText(t("engines:account.disconnectedReverted", { name: PLAN, list: processList(["summary"]) })),
    ).toBeInTheDocument();
    expect(await tile.findByText(t("engines:account.notConnected"))).toBeInTheDocument();
  });
});
