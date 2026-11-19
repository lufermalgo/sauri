import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { appPaths, defaultFolders } from "./paths.ts";
import { portPlan } from "./ports.ts";
import type { RotatingLog, ServiceSpec } from "./supervisor.ts";

// The Core's start order and reporting, with supervisors the test settles by hand (no process is started).
const fakes = vi.hoisted(() => ({ all: [] as Array<{ spec: { name: string }; settle(ready: boolean): void; startError?: Error }>, failStart: new Set<string>() }));

vi.mock("./supervisor.ts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./supervisor.ts")>();
  const { EventEmitter } = await import("node:events");
  class FakeSupervisor extends EventEmitter {
    state = "idle";
    failed = false;
    private resolveReady: ((ready: boolean) => void) | undefined;
    constructor(readonly spec: ServiceSpec) {
      super();
      fakes.all.push(this);
    }
    async start(): Promise<void> {
      if (fakes.failStart.has(this.spec.name)) throw new Error("cannot spawn");
      this.state = "starting";
    }
    waitReady(): Promise<boolean> {
      if (this.state === "ready") return Promise.resolve(true);
      return new Promise((resolve) => {
        this.resolveReady = resolve;
      });
    }
    settle(ready: boolean): void {
      if (ready) {
        this.state = "ready";
        this.emit("state", "ready");
      }
      this.resolveReady?.(ready);
    }
    async stop(): Promise<void> {
      this.state = "stopped";
      this.emit("state", "stopped");
      this.resolveReady?.(false);
    }
  }
  return { ...actual, Supervisor: FakeSupervisor };
});

const { Core } = await import("./services.ts");

let dir: string;
let core: InstanceType<typeof Core>;
const lines: string[] = [];

const started = () => fakes.all.map((fake) => fake.spec.name);
const fake = (name: string) => {
  const found = fakes.all.find((item) => item.spec.name === name);
  if (!found) throw new Error(`${name} was not started`);
  return found;
};
const failedNames = () => core.summary().flatMap((item) => ("failed" in item && item.failed ? [item.name] : []));

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-core-"));
  const paths = appPaths({ dev: true, home: dir });
  const ctx = {
    layout: { runtimeDir: path.join(dir, "runtime"), sourceRoot: path.join(dir, "src"), portalDir: path.join(dir, "portal") },
    paths,
    folders: defaultFolders(paths),
    ports: portPlan(18200),
    localUserId: "6f1c2a52-3b2e-4a55-9d5b-1d2f3e4a5b6c",
  };
  fakes.all.length = 0;
  fakes.failStart.clear();
  lines.length = 0;
  core = new Core(ctx, { line: (text: string) => lines.push(text) } as unknown as RotatingLog);
});

afterEach(() => fs.rmSync(dir, { recursive: true, force: true }));

describe("Core background start", () => {
  it("starts the engines first and the worker only once every engine has answered", async () => {
    const background = core.startBackground();
    await vi.waitFor(() => expect(started()).toEqual(["host-engine", "llm-engine"]));
    expect(core.portalStatus()).toEqual({ starting: true, problem: false });
    fake("host-engine").settle(true);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(started()).not.toContain("worker");
    fake("llm-engine").settle(true);
    await vi.waitFor(() => expect(started()).toContain("worker"));
    expect(core.portalStatus().starting).toBe(true);
    fake("worker").settle(true);
    await background;
    expect(core.portalStatus()).toEqual({ starting: false, problem: false });
    expect(lines).toContain("parakeet cli not verified");
  });

  it("reports a worker that is not ready in time until it answers, without throwing", async () => {
    const changes = vi.fn();
    core.on("change", changes);
    const background = core.startBackground();
    await vi.waitFor(() => expect(started()).toHaveLength(2));
    fake("host-engine").settle(true);
    fake("llm-engine").settle(true);
    await vi.waitFor(() => expect(started()).toContain("worker"));
    fake("worker").settle(false);
    await background;
    expect(failedNames()).toEqual(["worker"]);
    expect(core.portalStatus()).toEqual({ starting: false, problem: true });
    changes.mockClear();
    fake("worker").settle(true);
    expect(failedNames()).toEqual([]);
    expect(core.portalStatus().problem).toBe(false);
    expect(changes).toHaveBeenCalled();
  });

  it("logs and reports an engine whose start throws, and still starts the worker", async () => {
    fakes.failStart.add("llm-engine");
    const background = core.startBackground();
    await vi.waitFor(() => expect(started()).toHaveLength(2));
    fake("host-engine").settle(true);
    await vi.waitFor(() => expect(started()).toContain("worker"));
    fake("worker").settle(true);
    await background;
    expect(failedNames()).toEqual(["llm-engine"]);
    expect(lines).toContain("llm-engine could not start: cannot spawn");
  });

  it("starts nothing more after a stop, and reports nothing of the stopped start", async () => {
    const background = core.startBackground();
    await vi.waitFor(() => expect(started()).toHaveLength(2));
    await core.stop();
    await background;
    expect(started()).not.toContain("worker");
    expect(core.portalStatus()).toEqual({ starting: false, problem: false });
  });
});
