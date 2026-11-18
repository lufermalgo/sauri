import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { isAlive, RotatingLog, type ServiceSpec, Supervisor, type SupervisorOptions } from "./supervisor.ts";

let dir: string;
const running: Supervisor[] = [];

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "sauri-supervisor-"));
});

afterEach(async () => {
  await Promise.all(running.splice(0).map((supervisor) => supervisor.stop()));
  fs.rmSync(dir, { recursive: true, force: true });
});

function node(script: string, extra: Partial<ServiceSpec> = {}): ServiceSpec {
  return {
    name: "probe",
    command: process.execPath,
    args: ["-e", script],
    env: { PATH: process.env.PATH ?? "" },
    logFile: path.join(dir, "probe.log"),
    ...extra,
  };
}

function supervise(spec: ServiceSpec, options: Partial<SupervisorOptions> = {}): Supervisor {
  const supervisor = new Supervisor(spec, { healthIntervalMs: 20, readyAfterMs: 100, ...options });
  running.push(supervisor);
  return supervisor;
}

function delays(supervisor: Supervisor, count: number): Promise<number[]> {
  return new Promise((resolve) => {
    const seen: number[] = [];
    supervisor.on("restart-scheduled", (delay: number) => {
      seen.push(delay);
      if (seen.length === count) resolve(seen);
    });
  });
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("Supervisor", () => {
  it("restarts a crashing service with a doubling wait capped at the maximum", async () => {
    const supervisor = supervise(node("process.exit(3)"), { initialBackoffMs: 20, maxBackoffMs: 80 });
    const seen = delays(supervisor, 5);
    await supervisor.start();
    expect(await seen).toEqual([20, 40, 80, 80, 80]);
    expect(supervisor.restarts).toBeGreaterThanOrEqual(5);
    const log = fs.readFileSync(path.join(dir, "probe.log"), "utf8");
    expect(log).toContain("probe exited (code 3)");
  });

  it("resets the wait after a run longer than the stable time", async () => {
    const supervisor = supervise(node("setTimeout(() => process.exit(1), 120)"), {
      initialBackoffMs: 10,
      maxBackoffMs: 1000,
      stableMs: 50,
    });
    const seen = delays(supervisor, 3);
    await supervisor.start();
    expect(await seen).toEqual([10, 10, 10]);
  });

  it("flags repeated crashes as failed and clears the flag once the service answers again", async () => {
    const counter = path.join(dir, "attempts");
    const script = `
      const fs = require("node:fs");
      const n = fs.existsSync(${JSON.stringify(counter)}) ? Number(fs.readFileSync(${JSON.stringify(counter)}, "utf8")) : 0;
      fs.writeFileSync(${JSON.stringify(counter)}, String(n + 1));
      if (n < 3) process.exit(1);
      console.log("serving");
      setInterval(() => {}, 1000);
    `;
    const supervisor = supervise(node(script), {
      initialBackoffMs: 10,
      maxBackoffMs: 20,
      maxFailures: 3,
      // Longer than a crashing run, so a crash is never mistaken for readiness.
      readyAfterMs: 800,
    });
    let failedEvents = 0;
    supervisor.on("failed", () => {
      failedEvents += 1;
    });
    await supervisor.start();
    expect(await supervisor.waitReady(5000)).toBe(true);
    expect(failedEvents).toBe(1);
    expect(supervisor.failed).toBe(false);
    expect(supervisor.restarts).toBe(3);
    expect(fs.readFileSync(path.join(dir, "probe.log"), "utf8")).toContain("serving");
  });

  it("is ready only when its health check answers", async () => {
    let healthy = false;
    const supervisor = supervise(node("setInterval(() => {}, 1000)", { health: async () => healthy }));
    await supervisor.start();
    expect(await supervisor.waitReady(150)).toBe(false);
    healthy = true;
    expect(await supervisor.waitReady(2000)).toBe(true);
  });

  it("stops the service, forcing it when it ignores the stop signal, and removes its PID file", async () => {
    const pidFile = path.join(dir, "probe.pid");
    const supervisor = supervise(
      node('process.on("SIGTERM", () => {}); setInterval(() => {}, 1000)', { pidFile, stopTimeoutMs: 300 }),
    );
    await supervisor.start();
    expect(await supervisor.waitReady(2000)).toBe(true);
    const pid = supervisor.pid as number;
    expect(fs.readFileSync(pidFile, "utf8").trim()).toBe(String(pid));
    await supervisor.stop();
    expect(isAlive(pid)).toBe(false);
    expect(fs.existsSync(pidFile)).toBe(false);
    expect(supervisor.state).toBe("stopped");
  });

  it("ends a copy left by a previous session only when its command line matches", async () => {
    const marker = `sauri-stale-${process.pid}`;
    const pidFile = path.join(dir, "probe.pid");
    const stranger = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)", "other"], { detached: true, stdio: "ignore" });
    fs.writeFileSync(pidFile, `${stranger.pid}\n`);
    const first = supervise(node("setInterval(() => {}, 1000)", { pidFile, processMarker: marker }));
    await first.start();
    await sleep(100);
    expect(isAlive(stranger.pid as number)).toBe(true);
    await first.stop();
    process.kill(stranger.pid as number, "SIGKILL");

    const stale = spawn(process.execPath, ["-e", "setInterval(() => {}, 1000)", marker], { detached: true, stdio: "ignore" });
    fs.writeFileSync(pidFile, `${stale.pid}\n`);
    const second = supervise(node("setInterval(() => {}, 1000)", { pidFile, processMarker: marker }));
    await second.start();
    await sleep(100);
    expect(isAlive(stale.pid as number)).toBe(false);
  });
});

describe("RotatingLog", () => {
  it("rotates to .1 before passing the size limit and keeps writing", () => {
    const file = path.join(dir, "service.log");
    const log = new RotatingLog(file, 100);
    log.write("a".repeat(60));
    log.write("b".repeat(60));
    log.write("c".repeat(30));
    log.close();
    expect(fs.readFileSync(`${file}.1`, "utf8")).toBe("a".repeat(60));
    expect(fs.readFileSync(file, "utf8")).toBe("b".repeat(60) + "c".repeat(30));
  });

  it("rotates an oversized log left by a previous run when it opens", () => {
    const file = path.join(dir, "service.log");
    fs.writeFileSync(file, "x".repeat(150));
    const log = new RotatingLog(file, 100);
    log.write("fresh");
    log.close();
    expect(fs.statSync(`${file}.1`).size).toBe(150);
    expect(fs.readFileSync(file, "utf8")).toBe("fresh");
  });

  it("drops output that arrives after it was closed", () => {
    const file = path.join(dir, "service.log");
    const log = new RotatingLog(file, 100);
    log.close();
    expect(() => log.write("late")).not.toThrow();
    expect(fs.readFileSync(file, "utf8")).toBe("");
  });

  it("rotates the log of a chatty supervised service at the limit", async () => {
    const supervisor = supervise(node('process.stdout.write("z".repeat(400)); setInterval(() => {}, 1000)'), {
      rotateBytes: 256,
    });
    await supervisor.start();
    await sleep(300);
    await supervisor.stop();
    const total = fs.statSync(path.join(dir, "probe.log")).size + fs.statSync(path.join(dir, "probe.log.1")).size;
    expect(total).toBeGreaterThanOrEqual(400);
    expect(fs.statSync(path.join(dir, "probe.log.1")).size).toBeLessThanOrEqual(400);
  });
});
