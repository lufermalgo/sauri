// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { LocalJob, LocalModel } from "@sauri/shared-types";
import { answerEnginesApi } from "../engineApiStub";
import { EXTENSION_STORE_URL, WelcomeView } from "./WelcomeView";
import { t } from "../../i18n";

const POLL_MS = 10;

const TURBO_AVAILABLE: LocalModel = {
  id: "whisper-turbo", process: "transcription", kind: "model", engine: "whisper.cpp", size: 574_041_195, min_ram_gib: 8,
  requires: ["metal"], status: "measured", default: true, managed_by: null, recommended: true, in_use_by: [],
  state: "not_installed", installed_size: null, installed_at: null, availability: "available", active: false, in_use: false,
  location: null, reason: null, verifying: false,
  install: { method: "download", managed_by: null, download_bytes: 574_041_195, disk_required_bytes: 688_849_434, fits_on_disk: true },
};

const TURBO_INSTALLED: LocalModel = {
  ...TURBO_AVAILABLE, state: "installed", installed_size: 574_041_195, availability: "installed", location: "models_dir",
  verified_by: "hash", install: null, active: true, in_use: true, in_use_by: ["transcription"],
};

function job(state: LocalJob["state"], done: number): LocalJob {
  return { id: "job-1", model_id: "whisper-turbo", type: "install", state, bytes_done: done, bytes_total: 100, error: null, result: state === "done" ? "installed" : null };
}

interface Api {
  calls: string[];
  paired: boolean[];
}

function stubApi(api: Api) {
  let installed = false;
  let looks = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    api.calls.push(`${method} ${url.pathname}`);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url.pathname === "/api/v1/local/status") {
      const paired = api.paired.length > 1 ? api.paired.shift()! : api.paired[0];
      return json({ ready: true, processing: 0, version: "test", mode: "local", extension_paired: paired });
    }
    if (url.pathname.endsWith("/local/models")) {
      return json({
        catalog_version: 1, models: [installed ? TURBO_INSTALLED : TURBO_AVAILABLE],
        recommendations: { transcription: { model_id: "whisper-turbo", reason_key: "fits", reason_params: { memory_gib: 16 }, warnings: [] } },
        active_job: null, active: {}, adoption: null,
      });
    }
    if (url.pathname.endsWith("/local/models/whisper-turbo/install") && method === "POST") return json(job("running", 0));
    if (url.pathname.endsWith("/local/jobs/job-1")) {
      looks += 1;
      if (looks < 2) return json(job("running", 50));
      installed = true;
      return json(job("done", 100));
    }
    return answerEnginesApi(url.pathname) ?? new Response("{}", { status: 404 });
  }));
}

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
  it("installs a recommended model with progress, then waits for the extension and marks setup done", async () => {
    const api: Api = { calls: [], paired: [false, false, true] };
    stubApi(api);
    const markSetupDone = vi.fn(async () => undefined);
    window.sauriDesktop = { markSetupDone, getPaths: vi.fn(), relocate: vi.fn() };
    const onFinished = vi.fn();
    render(<WelcomeView onFinished={onFinished} pollIntervalMs={POLL_MS} />);

    expect(screen.getByText(t("welcome:step", { n: 1 }))).toBeInTheDocument();
    for (const process of ["transcription", "diarization", "summary"] as const) {
      expect(await screen.findByRole("heading", { level: 3, name: t(`welcome:models.processes.${process}.title`) })).toBeInTheDocument();
    }
    // Local models only: the external-services row of Settings is not part of the welcome.
    expect(screen.queryByText(t("engines:local.external.title"))).toBeNull();

    const transcription = screen.getByRole("region", { name: t("welcome:models.processes.transcription.title") });
    fireEvent.click(await within(transcription).findByRole("button", { name: t("engines:local.installLabel", { id: "whisper-turbo" }) }));
    expect(await within(transcription).findByText(t("engines:local.installing", { id: "whisper-turbo", percent: 50 }))).toBeInTheDocument();
    expect(await within(transcription).findByText(t("engines:local.outcome.installed", { id: "whisper-turbo" }))).toBeInTheDocument();
    expect(api.calls).toContain("POST /api/v1/engines/local/models/whisper-turbo/install");

    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.continue") }));
    expect(screen.getByText(t("welcome:step", { n: 2 }))).toBeInTheDocument();
    const store = screen.getByRole("link", { name: t("welcome:extension.install") });
    expect(store).toHaveAttribute("href", EXTENSION_STORE_URL);
    expect(store).toHaveAttribute("rel", "noopener noreferrer");
    expect(await screen.findByText(t("welcome:extension.waiting"))).toBeInTheDocument();
    expect(await screen.findByText(t("welcome:extension.paired"))).toBeInTheDocument();
    const looks = api.calls.filter((call) => call === "GET /api/v1/local/status").length;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 5));
    // Once paired it stops asking.
    expect(api.calls.filter((call) => call === "GET /api/v1/local/status").length).toBe(looks);

    fireEvent.click(screen.getByRole("button", { name: t("welcome:finish") }));
    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
    expect(markSetupDone).toHaveBeenCalledTimes(1);
  });

  it("can finish without the extension, and in a normal browser without the desktop bridge", async () => {
    const api: Api = { calls: [], paired: [false] };
    stubApi(api);
    const onFinished = vi.fn();
    render(<WelcomeView onFinished={onFinished} pollIntervalMs={POLL_MS} />);
    fireEvent.click(await screen.findByRole("button", { name: t("welcome:models.continue") }));
    expect(await screen.findByText(t("welcome:extension.waiting"))).toBeInTheDocument();
    expect(screen.getByText(t("welcome:extension.later"))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("welcome:back") }));
    expect(screen.getByText(t("welcome:step", { n: 1 }))).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: t("welcome:models.continue") }));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:finish") }));
    await waitFor(() => expect(onFinished).toHaveBeenCalledTimes(1));
  });

  it("keeps the person on the page when the app cannot save the finished setup", async () => {
    stubApi({ calls: [], paired: [true] });
    window.sauriDesktop = { markSetupDone: vi.fn(async () => Promise.reject(new Error("ipc"))), getPaths: vi.fn(), relocate: vi.fn() };
    const onFinished = vi.fn();
    render(<WelcomeView onFinished={onFinished} pollIntervalMs={POLL_MS} />);
    fireEvent.click(await screen.findByRole("button", { name: t("welcome:models.continue") }));
    fireEvent.click(screen.getByRole("button", { name: t("welcome:finish") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("welcome:finishError"));
    expect(onFinished).not.toHaveBeenCalled();
  });
});
