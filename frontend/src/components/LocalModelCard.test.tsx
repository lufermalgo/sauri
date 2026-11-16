// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { LocalJob, LocalModel } from "@sauri/shared-types";
import { copy } from "../copy/es";
import { LocalModelCard } from "./settings/LocalModelCard";

const text = copy.engines.local;
const POLL_MS = 10;

function model(overrides: Partial<LocalModel> & Pick<LocalModel, "id">): LocalModel {
  return {
    process: "transcription", kind: "model", engine: "whisper.cpp", size: 574_041_195, min_ram_gib: 8, requires: ["metal"],
    status: "measured", default: false, managed_by: null, recommended: false, in_use_by: [], state: "not_installed",
    installed_size: null, installed_at: null, ...overrides,
  };
}

const TURBO = model({ id: "whisper-turbo", default: true, recommended: true });
const SMALL = model({ id: "whisper-small", size: 190_085_487, status: "proposal", min_ram_gib: 4, requires: [] });

interface Call { method: string; path: string }

function fakeBackend(models: LocalModel[], options: { engineState?: string; hostDown?: boolean; recommendation?: object } = {}) {
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
        recommendations: {
          transcription: options.recommendation ?? {
            process: "transcription", model_id: "whisper-turbo", status: "measured", reason_key: "fits",
            reason_params: { memory_gib: 24, min_ram_gib: 8 }, warnings: [],
          },
        },
      });
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
        Object.assign(target, { state: "installed", installed_size: target.size });
      }
      return json(job.current);
    }
    const removal = /^\/local\/models\/([^/]+)$/.exec(path);
    if (removal && method === "DELETE") {
      const target = catalog.find((entry) => entry.id === removal[1])!;
      Object.assign(target, { state: "not_installed", installed_size: null });
      return new Response(null, { status: 204 });
    }
    return json({ detail: "unexpected" }, 404);
  });
  return { handler, calls, jobAnswers, refusals, catalog, job, json };
}

let backend: ReturnType<typeof fakeBackend>;

async function renderCard(models: LocalModel[], options: Parameters<typeof fakeBackend>[1] = {}, props: { onModelsChange?: (models: LocalModel[]) => void } = {}) {
  backend = fakeBackend(models, options);
  vi.stubGlobal("fetch", backend.handler);
  const view = render(<LocalModelCard process="transcription" pollIntervalMs={POLL_MS} {...props} />);
  await screen.findByRole("heading", { name: text.modelsTitle });
  return view;
}

const row = (id: string) => screen.getByRole("listitem", { name: id });
const jobLooks = () => backend.calls.filter((call) => call.path.startsWith("/local/jobs/") && call.method === "GET").length;

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
  it("describes the computer in plain words", async () => {
    await renderCard([TURBO, SMALL]);
    expect(screen.getByText(text.hardware(text.chip("arm64", "Darwin"), "24 GB", 10, "120 GB"))).toBeInTheDocument();
    expect(screen.getByText(text.metalYes)).toBeInTheDocument();
  });

  it("gives the recommended model with its reason and the measured mark", async () => {
    await renderCard([TURBO, SMALL]);
    const section = screen.getByRole("region", { name: text.recommendationTitle });
    expect(within(section).getByText("whisper-turbo")).toBeInTheDocument();
    expect(within(section).getByText(text.marks.measured)).toBeInTheDocument();
    expect(within(section).getByText(text.reasons.fits("24 GB", 8))).toBeInTheDocument();
  });

  it("marks a proposal and lists the cautions that come with it", async () => {
    await renderCard([TURBO, SMALL], {
      recommendation: {
        process: "transcription", model_id: "whisper-small", status: "proposal", reason_key: "reduced",
        reason_params: { memory_gib: 4, min_ram_gib: 4, better_id: "whisper-turbo", limited_by: "memory" },
        warnings: ["unmeasured_proposal", "lower_quality_expected"],
      },
    });
    const section = screen.getByRole("region", { name: text.recommendationTitle });
    expect(within(section).getByText(text.marks.proposal)).toBeInTheDocument();
    expect(within(section).getByText(text.warnings.unmeasured_proposal)).toBeInTheDocument();
    expect(within(section).getByText(text.warnings.lower_quality_expected)).toBeInTheDocument();
  });

  it("tells the engine is not installed, with the command and the tools it needs", async () => {
    await renderCard([TURBO], { engineState: "stopped" });
    const missing = screen.getByRole("region", { name: text.engineMissing.title });
    expect(within(missing).getByText(text.engineMissing.installCommand)).toBeInTheDocument();
    expect(within(missing).getByText(text.engineMissing.tools(text.engineTools.transcription))).toBeInTheDocument();
  });

  it("says so when the service that manages models does not answer", async () => {
    backend = fakeBackend([TURBO], { hostDown: true });
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard process="transcription" pollIntervalMs={POLL_MS} />);
    const missing = await screen.findByRole("region", { name: text.engineMissing.title });
    expect(within(missing).getByText(text.engineMissing.hostBody)).toBeInTheDocument();
    expect(within(missing).getByText(text.engineMissing.startCommand)).toBeInTheDocument();
  });

  it("hands the catalog to the screen so installed models can be chosen", async () => {
    const onModelsChange = vi.fn();
    await renderCard([TURBO, { ...SMALL, state: "installed" }], {}, { onModelsChange });
    expect(onModelsChange.mock.calls[0][0].map((entry: LocalModel) => entry.id)).toEqual(["whisper-turbo", "whisper-small"]);
  });
});

describe("install", () => {
  it("asks for the space it needs before anything is downloaded", async () => {
    await renderCard([TURBO]);
    expect(within(row("whisper-turbo")).getByText(text.spaceNeeded("689 MB"))).toBeInTheDocument();
  });

  it("follows the download with a status region, then shows the model installed", async () => {
    await renderCard([TURBO]);
    backend.jobAnswers.push(
      { bytes_done: 250 },
      { bytes_done: 600 },
      { state: "done", bytes_done: 1000, result: "installed" },
    );
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    const status = await screen.findByText(text.installing("whisper-turbo", 0));
    expect(status).toHaveAttribute("role", "status");
    expect(screen.getByRole("progressbar", { name: text.progressLabel("whisper-turbo") })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(text.installing("whisper-turbo", 25))).toBeInTheDocument());
    expect(await screen.findByText(text.outcome.installed("whisper-turbo"))).toBeInTheDocument();
    await waitFor(() => expect(within(row("whisper-turbo")).getByText(text.states.installed)).toBeInTheDocument());
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("keeps other installs and removals closed while one job runs", async () => {
    await renderCard([TURBO, SMALL]);
    backend.jobAnswers.push({ bytes_done: 100 });
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    await screen.findByRole("progressbar");
    expect(screen.getByRole("button", { name: text.installLabel("whisper-small") })).toBeDisabled();
    expect(screen.getByText(text.busy)).toBeInTheDocument();
  });

  it("cancels the download", async () => {
    await renderCard([TURBO]);
    backend.jobAnswers.push({ bytes_done: 100 });
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    fireEvent.click(await screen.findByRole("button", { name: text.cancelLabel("whisper-turbo") }));
    expect(await screen.findByText(text.outcome.cancelled)).toBeInTheDocument();
    expect(backend.calls.some((call) => call.method === "POST" && call.path.endsWith("/cancel"))).toBe(true);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(within(row("whisper-turbo")).getByText(text.states.not_installed)).toBeInTheDocument();
  });

  it("explains an invalid hash and leaves the model not installed", async () => {
    await renderCard([TURBO]);
    backend.jobAnswers.push({ state: "failed", error: "hash_mismatch" });
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(text.jobErrors.hash_mismatch);
    expect(within(row("whisper-turbo")).getByText(text.states.not_installed)).toBeInTheDocument();
  });

  it("states how much space is missing when the disk is too small", async () => {
    await renderCard([TURBO]);
    backend.refusals.set("POST /local/models/whisper-turbo/install", backend.json({
      detail: "insufficient_disk", needed_bytes: 688_849_434, free_bytes: 300_000_000,
    }, 507));
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.insufficientDisk("689 MB", "300 MB"));
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByRole("button", { name: text.installLabel("whisper-turbo") })).toBeEnabled();
  });

  it("stops asking about the job when the card goes away", async () => {
    const view = await renderCard([TURBO]);
    backend.jobAnswers.push({ bytes_done: 100 });
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    await waitFor(() => expect(jobLooks()).toBeGreaterThanOrEqual(2));
    view.unmount();
    const looksAtUnmount = jobLooks();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 8));
    expect(jobLooks()).toBeLessThanOrEqual(looksAtUnmount + 1);
  });

  it("gives up after repeated failed looks instead of asking forever", async () => {
    await renderCard([TURBO]);
    fireEvent.click(screen.getByRole("button", { name: text.installLabel("whisper-turbo") }));
    await screen.findByRole("progressbar");
    backend.refusals.set(`GET /local/jobs/${"a".repeat(32)}`, backend.json({ detail: "host_unavailable" }, 503));
    expect(await screen.findByText(text.outcome.lost)).toBeInTheDocument();
    const looks = jobLooks();
    await new Promise((resolve) => setTimeout(resolve, POLL_MS * 6));
    expect(jobLooks()).toBe(looks);
  });
});

describe("verify and remove", () => {
  const INSTALLED = { state: "installed" as const, installed_size: 574_041_195 };

  it("verifies and reports an intact file", async () => {
    await renderCard([{ ...TURBO, ...INSTALLED }]);
    backend.jobAnswers.push({ state: "done", result: "verified", bytes_done: 1000 });
    fireEvent.click(screen.getByRole("button", { name: text.verifyLabel("whisper-turbo") }));
    expect(await screen.findByText(text.outcome.verified("whisper-turbo"))).toBeInTheDocument();
  });

  it("reports a damaged file after verifying", async () => {
    await renderCard([{ ...TURBO, ...INSTALLED }]);
    backend.jobAnswers.push({ state: "done", result: "corrupt", bytes_done: 1000 });
    fireEvent.click(screen.getByRole("button", { name: text.verifyLabel("whisper-turbo") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.outcome.corrupt("whisper-turbo"));
  });

  it("blocks removal while a process uses the model, and says which", async () => {
    await renderCard([{ ...TURBO, ...INSTALLED, in_use_by: ["transcription"] }]);
    const remove = screen.getByRole("button", { name: text.removeLabel("whisper-turbo") });
    expect(remove).toBeDisabled();
    expect(within(row("whisper-turbo")).getByText(text.removeBlocked("Transcripción"))).toBeInTheDocument(); // spanish-sample-data
    expect(remove).toHaveAccessibleDescription(text.removeBlocked("Transcripción")); // spanish-sample-data
  });

  it("explains a refusal from the host when the model became in use meanwhile", async () => {
    await renderCard([{ ...SMALL, ...INSTALLED }]);
    backend.refusals.set("DELETE /local/models/whisper-small", backend.json({ detail: "model_in_use", processes: ["transcription"] }, 409));
    fireEvent.click(screen.getByRole("button", { name: text.removeLabel("whisper-small") }));
    fireEvent.click(await screen.findByRole("button", { name: text.removeConfirm }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.modelInUse("Transcripción")); // spanish-sample-data
  });

  it("asks before removing, and removes only after the confirmation", async () => {
    await renderCard([{ ...SMALL, ...INSTALLED }]);
    fireEvent.click(screen.getByRole("button", { name: text.removeLabel("whisper-small") }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(text.removeBody("whisper-small", "574 MB"))).toBeInTheDocument();
    expect(backend.calls.some((call) => call.method === "DELETE")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: text.removeCancel }));
    expect(backend.calls.some((call) => call.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: text.removeLabel("whisper-small") }));
    fireEvent.click(await screen.findByRole("button", { name: text.removeConfirm }));
    expect(await screen.findByText(text.outcome.removed("whisper-small"))).toBeInTheDocument();
    await waitFor(() => expect(within(row("whisper-small")).getByText(text.states.not_installed)).toBeInTheDocument());
  });
});

describe("managed engines", () => {
  it("shows the command that installs a model that ships with its engine, with no download button", async () => {
    const senko = model({
      id: "senko-coreml", process: "diarization", kind: "managed_engine", engine: "senko", size: null,
      managed_by: "scripts/engines/install-diar-engine.sh", state: "managed",
    });
    backend = fakeBackend([senko]);
    vi.stubGlobal("fetch", backend.handler);
    render(<LocalModelCard process="diarization" pollIntervalMs={POLL_MS} />);
    await screen.findByRole("heading", { name: text.modelsTitle });
    expect(screen.getByText(text.managedHow("bash scripts/engines/install-diar-engine.sh"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: text.install })).toBeNull();
  });
});
