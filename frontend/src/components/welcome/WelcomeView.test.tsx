// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { LocalJob } from "@sauri/shared-types";
import { answerEnginesApi } from "../engineApiStub";
import { EXTENSION_STORE_URL, WelcomeView } from "./WelcomeView";
import { DIAR, LARGE_LLM, PARAKEET, SMALL_LLM, VAD, WHISPER, desktopListing, localProcess, withInstalled } from "./welcomeFixtures";
import { t } from "../../i18n";

const POLL_MS = 10;

interface Host {
  calls: string[];
  paired: boolean[];
  /** Ids the next install of which fails once with this code. */
  failOnce?: Record<string, string>;
  /** A job the host is already running when the page opens (the startup check). */
  startupJob?: boolean;
  memory?: 8 | 16 | 24;
}

/** A fake core: installs finish after two looks and the listing then shows the file as installed. */
function stubHost(host: Host) {
  const installed = new Set<string>();
  const jobs = new Map<string, { job: LocalJob; looks: number }>();
  let active: string | null = host.startupJob ? "startup" : null;
  if (host.startupJob) {
    jobs.set("startup", { job: { id: "startup", model_id: "", type: "adopt", state: "running", bytes_done: 0, bytes_total: 1, error: null, result: null }, looks: 0 });
  }
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    host.calls.push(`${method} ${url.pathname}`);
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
    if (url.pathname === "/api/v1/local/status") {
      const paired = host.paired.length > 1 ? host.paired.shift()! : host.paired[0];
      return json({ ready: true, processing: 0, version: "test", mode: "local", extension_paired: paired });
    }
    if (url.pathname.endsWith("/local/models")) return json({ ...withInstalled(desktopListing(host.memory ?? 16), [...installed]), active_job: active });
    const install = url.pathname.match(/\/local\/models\/([^/]+)\/install$/);
    if (install && method === "POST") {
      if (active) return json({ detail: "job_active", job_id: active }, 409);
      const id = `job-${jobs.size + 1}`;
      const job: LocalJob = { id, model_id: install[1], type: "install", state: "running", bytes_done: 0, bytes_total: 100, error: null, result: null };
      jobs.set(id, { job, looks: 0 });
      active = id;
      return json(job);
    }
    const look = url.pathname.match(/\/local\/jobs\/([^/]+)$/);
    if (look) {
      const entry = jobs.get(look[1])!;
      entry.looks += 1;
      if (entry.looks >= 2 && entry.job.state === "running") {
        active = null;
        const failure = host.failOnce?.[entry.job.model_id];
        if (failure) {
          delete host.failOnce![entry.job.model_id];
          entry.job = { ...entry.job, state: "failed", error: failure };
        } else {
          if (entry.job.model_id) installed.add(entry.job.model_id);
          entry.job = { ...entry.job, state: "done", bytes_done: 100, result: "installed" };
        }
      } else if (entry.job.state === "running") {
        entry.job = { ...entry.job, bytes_done: 50 };
      }
      return json(entry.job);
    }
    if (url.pathname.endsWith("/engines/processes/summary") && method === "PUT") {
      const body = JSON.parse(String(init?.body)) as { model: string };
      return json({ ...localProcess("summary"), model: body.model });
    }
    return answerEnginesApi(url.pathname) ?? new Response("{}", { status: 404 });
  }));
  return installed;
}

const installs = (host: Host) => host.calls.filter((call) => call.startsWith("POST") && call.endsWith("/install"));

beforeEach(() => {
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => (key === "sauri_token" ? "synthetic-token" : null),
    setItem: () => undefined,
    removeItem: () => undefined,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete window.sauriDesktop;
});

describe("WelcomeView", () => {
  it("installs the plan for this Mac on its own, with one progress, then waits for the extension and marks setup done", async () => {
    const host: Host = { calls: [], paired: [false, false, true] };
    const installed = stubHost(host);
    const markSetupDone = vi.fn(async () => undefined);
    window.sauriDesktop = { markSetupDone, getPaths: vi.fn(), relocate: vi.fn() };
    const onFinished = vi.fn();
    render(<WelcomeView onFinished={onFinished} pollIntervalMs={POLL_MS} />);

    expect(screen.getByText(t("welcome:step", { n: 1 }))).toBeInTheDocument();
    const continueButton = screen.getByRole("button", { name: t("welcome:models.continue") });
    expect(continueButton).toBeDisabled();
    expect(await screen.findByText(t("welcome:models.installing", { what: t("welcome:models.items.transcription"), n: 1, count: 5 }))).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: t("welcome:models.progressLabel") })).toBeInTheDocument();
    // No choice to make: no install buttons, no model names, no list of options.
    expect(screen.queryAllByRole("button").map((button) => button.textContent)).toEqual([t("welcome:models.continue")]);
    expect(screen.queryByText(new RegExp(PARAKEET))).toBeNull();

    expect(await screen.findByText(t("welcome:models.ready"))).toBeInTheDocument();
    expect(installs(host).map((call) => call.split("/").at(-2))).toEqual([PARAKEET, WHISPER, VAD, LARGE_LLM, DIAR]);
    expect([...installed]).toEqual([PARAKEET, WHISPER, VAD, LARGE_LLM, DIAR]);
    // On 16 GB every process already runs its recommended model with `local:default`: nothing to save.
    expect(host.calls.some((call) => call.startsWith("PUT"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.continue") }));
    expect(screen.getByText(t("welcome:step", { n: 2 }))).toBeInTheDocument();
    const store = screen.getByRole("link", { name: t("welcome:extension.install") });
    expect(store).toHaveAttribute("href", EXTENSION_STORE_URL);
    expect(store).toHaveAttribute("rel", "noopener noreferrer");
    expect(await screen.findByText(t("welcome:extension.waiting"))).toBeInTheDocument();
    expect(await screen.findByText(t("welcome:extension.paired"))).toBeInTheDocument();
    const looks = host.calls.filter((call) => call === "GET /api/v1/local/status").length;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 5));
    // Once paired it stops asking.
    expect(host.calls.filter((call) => call === "GET /api/v1/local/status").length).toBe(looks);

    fireEvent.click(screen.getByRole("button", { name: t("welcome:finish") }));
    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
    expect(markSetupDone).toHaveBeenCalledTimes(1);
  });

  it("saves the lighter summary model on an 8 GB Mac", async () => {
    const host: Host = { calls: [], paired: [false], memory: 8 };
    stubHost(host);
    render(<WelcomeView onFinished={vi.fn()} pollIntervalMs={POLL_MS} />);
    expect(await screen.findByText(t("welcome:models.ready"))).toBeInTheDocument();
    expect(installs(host).map((call) => call.split("/").at(-2))).toEqual([PARAKEET, WHISPER, VAD, SMALL_LLM, DIAR]);
    expect(host.calls).toContain("PUT /api/v1/engines/processes/summary");
  });

  it("waits for a job the core is already running, then installs", async () => {
    const host: Host = { calls: [], paired: [false], startupJob: true };
    stubHost(host);
    render(<WelcomeView onFinished={vi.fn()} pollIntervalMs={POLL_MS} />);
    expect(await screen.findByText(t("welcome:models.waiting"))).toBeInTheDocument();
    expect(await screen.findByText(t("welcome:models.ready"))).toBeInTheDocument();
    expect(installs(host)).toHaveLength(5);
  });

  it("says plainly when the download fails without internet, keeps what finished and retries the rest", async () => {
    const host: Host = { calls: [], paired: [false], failOnce: { [LARGE_LLM]: "download_failed" } };
    const installed = stubHost(host);
    render(<WelcomeView onFinished={vi.fn()} pollIntervalMs={POLL_MS} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(t("welcome:models.failed.offline"));
    expect([...installed]).toEqual([PARAKEET, WHISPER, VAD]);
    expect(screen.getByRole("button", { name: t("welcome:models.skip") })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.retry") }));
    expect(await screen.findByText(t("welcome:models.ready"))).toBeInTheDocument();
    // The retry downloads only what was missing.
    expect(installs(host).map((call) => call.split("/").at(-2))).toEqual([PARAKEET, WHISPER, VAD, LARGE_LLM, LARGE_LLM, DIAR]);
  });

  it("can continue without finishing when the core cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    render(<WelcomeView onFinished={vi.fn()} pollIntervalMs={POLL_MS} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(t("welcome:models.failed.host"));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.skip") }));
    expect(screen.getByText(t("welcome:step", { n: 2 }))).toBeInTheDocument();
  });

  it("can finish without the extension, and in a normal browser without the desktop bridge", async () => {
    const host: Host = { calls: [], paired: [false] };
    stubHost(host);
    const onFinished = vi.fn();
    render(<WelcomeView onFinished={onFinished} pollIntervalMs={POLL_MS} />);
    await screen.findByText(t("welcome:models.ready"));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.continue") }));
    expect(await screen.findByText(t("welcome:extension.waiting"))).toBeInTheDocument();
    expect(screen.getByText(t("welcome:extension.later"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("welcome:back") }));
    expect(screen.getByText(t("welcome:step", { n: 1 }))).toBeInTheDocument();
    // Coming back finds everything installed and does not download again.
    await screen.findByText(t("welcome:models.ready"));
    expect(installs(host)).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.continue") }));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:finish") }));
    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
  });

  it("keeps the person on the page when the app cannot save the finished setup", async () => {
    stubHost({ calls: [], paired: [true] });
    window.sauriDesktop = { markSetupDone: vi.fn(async () => Promise.reject(new Error("ipc"))), getPaths: vi.fn(), relocate: vi.fn() };
    const onFinished = vi.fn();
    render(<WelcomeView onFinished={onFinished} pollIntervalMs={POLL_MS} />);
    await screen.findByText(t("welcome:models.ready"));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.continue") }));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:finish") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("welcome:finishError"));
    expect(onFinished).not.toHaveBeenCalled();
  });
});
