// One supervised child process: spawn, readiness through its health check, restart with a growing wait
// (1 s to 30 s) after a crash, and a log rotated at 20 MB. Follows APX's core-process.ts.
import { type ChildProcess, execFile, spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import path from "node:path";

export const ROTATE_BYTES = 20 * 1024 * 1024;

/** Appends to a log file and rotates it to `<file>.1` before it would pass `maxBytes`. */
export class RotatingLog {
  private fd: number;
  private size: number;
  private closed = false;

  constructor(
    readonly file: string,
    readonly maxBytes = ROTATE_BYTES,
  ) {
    fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
    this.size = fs.statSync(file, { throwIfNoEntry: false })?.size ?? 0;
    if (this.size >= maxBytes) this.rotate(false);
    this.fd = fs.openSync(file, "a", 0o600);
  }

  private rotate(open = true): void {
    fs.renameSync(this.file, `${this.file}.1`);
    this.size = 0;
    if (open) this.fd = fs.openSync(this.file, "a", 0o600);
  }

  /** Output that arrives after the service stopped (a helper still holding the pipe) is dropped. */
  write(chunk: string | Buffer): void {
    if (this.closed) return;
    const data = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
    if (this.size > 0 && this.size + data.length > this.maxBytes) {
      fs.closeSync(this.fd);
      this.rotate();
    }
    fs.writeSync(this.fd, data);
    this.size += data.length;
  }

  line(text: string): void {
    this.write(`${new Date().toISOString()} [desktop] ${text}\n`);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    fs.closeSync(this.fd);
  }
}

export interface ServiceSpec {
  name: string;
  command: string;
  args: string[];
  cwd?: string;
  env: Record<string, string>;
  logFile: string;
  /** Records the child's PID so a copy left behind by a crashed app can be ended on the next start. */
  pidFile?: string;
  /** Text a left-behind process's command line must contain before it is signalled (never a stranger). */
  processMarker?: string;
  /** Resolves true once the service answers. Without one, the service is ready once it stays up `readyAfterMs`. */
  health?: () => Promise<boolean>;
  readyAfterMs?: number;
  stopSignal?: NodeJS.Signals;
  stopTimeoutMs?: number;
  /** Signal the whole process group (helpers included). PostgreSQL wants only its postmaster signalled. */
  killGroup?: boolean;
}

export interface SupervisorOptions {
  initialBackoffMs: number;
  maxBackoffMs: number;
  /** A run longer than this resets the wait to its initial value. */
  stableMs: number;
  rotateBytes: number;
  failureWindowMs: number;
  maxFailures: number;
  healthIntervalMs: number;
  readyAfterMs: number;
}

export const DEFAULT_OPTIONS: SupervisorOptions = {
  initialBackoffMs: 1000,
  maxBackoffMs: 30_000,
  stableMs: 60_000,
  rotateBytes: ROTATE_BYTES,
  failureWindowMs: 10 * 60_000,
  maxFailures: 5,
  healthIntervalMs: 300,
  readyAfterMs: 1000,
};

export type ServiceState = "idle" | "starting" | "ready" | "restarting" | "stopped";

export function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function commandLine(pid: number): Promise<string> {
  return new Promise((resolve) => {
    execFile("/bin/ps", ["-p", String(pid), "-o", "command="], (error, stdout) => resolve(error ? "" : stdout));
  });
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function signal(pid: number, sig: NodeJS.Signals, group: boolean): void {
  try {
    process.kill(group ? -pid : pid, sig);
  } catch {
    // already gone
  }
}

/** Ends a copy of this service left running by an app that died without stopping it. */
export async function reapStale(spec: ServiceSpec, log: RotatingLog): Promise<void> {
  if (!spec.pidFile || !fs.existsSync(spec.pidFile)) return;
  const pid = Number(fs.readFileSync(spec.pidFile, "utf8").trim());
  if (Number.isInteger(pid) && pid > 1 && isAlive(pid)) {
    const command = await commandLine(pid);
    if (spec.processMarker && command.includes(spec.processMarker)) {
      log.line(`ending ${spec.name} left running by a previous session (PID ${pid})`);
      const group = spec.killGroup !== false;
      signal(pid, spec.stopSignal ?? "SIGTERM", group);
      const until = Date.now() + (spec.stopTimeoutMs ?? 10_000);
      while (isAlive(pid) && Date.now() < until) await sleep(100);
      if (isAlive(pid)) signal(pid, "SIGKILL", group);
    }
  }
  fs.rmSync(spec.pidFile, { force: true });
}

export class Supervisor extends EventEmitter {
  readonly options: SupervisorOptions;
  private child: ChildProcess | undefined;
  private log: RotatingLog | undefined;
  private retry: NodeJS.Timeout | undefined;
  private backoff: number;
  private failures: number[] = [];
  private stopping: Promise<void> | undefined;
  private current: ServiceState = "idle";
  /** Five crashes inside ten minutes: shown as an error until the service answers again. */
  failed = false;
  restarts = 0;

  constructor(
    readonly spec: ServiceSpec,
    options: Partial<SupervisorOptions> = {},
  ) {
    super();
    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.backoff = this.options.initialBackoffMs;
  }

  get state(): ServiceState {
    return this.current;
  }

  get pid(): number | undefined {
    return this.child?.pid;
  }

  private setState(state: ServiceState): void {
    if (state === this.current) return;
    this.current = state;
    this.emit("state", state);
  }

  async start(): Promise<void> {
    if (this.current !== "idle") return;
    this.log = new RotatingLog(this.spec.logFile, this.options.rotateBytes);
    await reapStale(this.spec, this.log);
    this.spawnChild();
  }

  private spawnChild(): void {
    if (this.stopping || !this.log) return;
    const log = this.log;
    const startedAt = Date.now();
    this.setState("starting");
    log.line(`starting ${this.spec.name}`);
    const child = spawn(this.spec.command, this.spec.args, {
      cwd: this.spec.cwd,
      env: this.spec.env,
      stdio: ["ignore", "pipe", "pipe"],
      detached: true,
    });
    this.child = child;
    child.stdout?.on("data", (chunk: Buffer) => log.write(chunk));
    child.stderr?.on("data", (chunk: Buffer) => log.write(chunk));
    if (child.pid && this.spec.pidFile) fs.writeFileSync(this.spec.pidFile, `${child.pid}\n`, { mode: 0o600 });
    let finished = false;
    const done = (code: number | null, sig: NodeJS.Signals | null) => {
      if (finished) return;
      finished = true;
      if (this.spec.pidFile) fs.rmSync(this.spec.pidFile, { force: true });
      this.emit("exit", code, sig);
      if (this.stopping) return;
      log.line(`${this.spec.name} exited (code ${code ?? "none"}${sig ? `, signal ${sig}` : ""})`);
      this.scheduleRestart(Date.now() - startedAt);
    };
    child.once("exit", done);
    child.once("error", (error) => {
      log.line(`${this.spec.name} could not start: ${error.message}`);
      done(null, null);
    });
    void this.watchReady(child);
  }

  private async watchReady(child: ChildProcess): Promise<void> {
    const health = this.spec.health;
    const alive = () => this.child === child && child.exitCode === null && child.signalCode === null;
    if (!health) {
      await sleep(this.spec.readyAfterMs ?? this.options.readyAfterMs);
      if (alive() && !this.stopping) this.markReady();
      return;
    }
    while (alive() && !this.stopping) {
      if (await health().catch(() => false)) {
        if (alive() && !this.stopping) this.markReady();
        return;
      }
      await sleep(this.options.healthIntervalMs);
    }
  }

  private markReady(): void {
    if (this.failed) this.log?.line(`${this.spec.name} recovered`);
    this.failed = false;
    this.setState("ready");
  }

  private scheduleRestart(ranForMs: number): void {
    const now = Date.now();
    if (ranForMs > this.options.stableMs) this.backoff = this.options.initialBackoffMs;
    this.failures = [...this.failures.filter((at) => now - at < this.options.failureWindowMs), now];
    if (this.failures.length >= this.options.maxFailures && !this.failed) {
      this.failed = true;
      this.log?.line(`${this.spec.name} failed ${this.failures.length} times in a row; still retrying`);
      this.emit("failed");
    }
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, this.options.maxBackoffMs);
    this.restarts += 1;
    this.setState("restarting");
    this.emit("restart-scheduled", delay);
    this.retry = setTimeout(() => this.spawnChild(), delay);
  }

  /** True once the service is ready; false if it is not ready within `timeoutMs` or it is stopped. */
  waitReady(timeoutMs: number): Promise<boolean> {
    if (this.current === "ready") return Promise.resolve(true);
    return new Promise((resolve) => {
      const onState = (state: ServiceState) => {
        if (state !== "ready" && state !== "stopped") return;
        finish(state === "ready");
      };
      const timer = setTimeout(() => finish(false), timeoutMs);
      const finish = (value: boolean) => {
        clearTimeout(timer);
        this.off("state", onState);
        resolve(value);
      };
      this.on("state", onState);
    });
  }

  stop(): Promise<void> {
    if (this.stopping) return this.stopping;
    clearTimeout(this.retry);
    const child = this.child;
    const log = this.log;
    this.stopping = new Promise<void>((resolve) => {
      const close = () => {
        log?.line(`${this.spec.name} stopped`);
        log?.close();
        this.setState("stopped");
        resolve();
      };
      if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return close();
      const pid = child.pid;
      const group = this.spec.killGroup !== false;
      const force = setTimeout(() => signal(pid, "SIGKILL", group), this.spec.stopTimeoutMs ?? 10_000);
      child.once("exit", () => {
        clearTimeout(force);
        // Helpers in the service's group must not outlive it.
        if (group) signal(pid, "SIGKILL", true);
        close();
      });
      signal(pid, this.spec.stopSignal ?? "SIGTERM", group);
    });
    return this.stopping;
  }
}

export async function httpHealth(url: string, headers: Record<string, string> = {}): Promise<boolean> {
  try {
    const response = await fetch(url, { headers, signal: AbortSignal.timeout(1500) });
    return response.ok;
  } catch {
    return false;
  }
}

export function commandHealth(command: string, args: string[], env: Record<string, string>): Promise<boolean> {
  return new Promise((resolve) => {
    execFile(command, args, { env, timeout: 3000 }, (error) => resolve(!error));
  });
}
