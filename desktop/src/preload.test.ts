import { describe, expect, it, vi } from "vitest";
import { PORTAL_CHANNELS } from "./shared/portal-api.ts";

const exposed: Record<string, unknown> = {};
const invoke = vi.fn(async () => undefined);
type Handler = (event: unknown, payload: unknown) => void;
const listeners = new Map<string, Set<Handler>>();
vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld: (name: string, api: unknown) => (exposed[name] = api) },
  ipcRenderer: {
    invoke,
    on: (channel: string, handler: Handler) => {
      if (!listeners.has(channel)) listeners.set(channel, new Set());
      listeners.get(channel)?.add(handler);
    },
    removeListener: (channel: string, handler: Handler) => listeners.get(channel)?.delete(handler),
  },
}));

function emit(channel: string, payload: unknown): void {
  for (const handler of listeners.get(channel) ?? []) handler({ sender: "ipc-event" }, payload);
}

describe("portal preload", () => {
  it("exposes only the whitelisted calls, each on its own channel", async () => {
    await import("./preload.ts");
    expect(Object.keys(exposed)).toEqual(["sauriDesktop"]);
    const api = exposed.sauriDesktop as Record<string, (...args: unknown[]) => Promise<unknown>>;
    expect(Object.keys(api).sort()).toEqual([
      "getLocale",
      "getPaths",
      "getServicesStatus",
      "getWindowState",
      "markSetupDone",
      "onRelocateProgress",
      "onServicesStatus",
      "onWindowState",
      "relocate",
      "titleBar",
      "updates",
    ]);
    const updates = api.updates as unknown as Record<string, (...args: unknown[]) => Promise<unknown>>;
    expect(Object.keys(updates).sort()).toEqual(["apply", "check", "onChange", "setAutoCheck", "status"]);
    await api.getPaths();
    await api.relocate("models");
    await api.markSetupDone();
    await api.getLocale();
    await updates.status();
    await updates.check();
    await updates.apply();
    await updates.setAutoCheck("yes");
    await api.getServicesStatus();
    await api.getWindowState();
    expect(invoke.mock.calls).toEqual([
      [PORTAL_CHANNELS.getPaths],
      [PORTAL_CHANNELS.relocate, "models"],
      [PORTAL_CHANNELS.markSetupDone],
      [PORTAL_CHANNELS.getLocale],
      [PORTAL_CHANNELS.updateStatus],
      [PORTAL_CHANNELS.updateCheck],
      [PORTAL_CHANNELS.updateApply],
      [PORTAL_CHANNELS.updateAutoCheck, false],
      [PORTAL_CHANNELS.servicesStatus],
      [PORTAL_CHANNELS.windowState],
    ]);
  });

  it("tells the portal before it paints whether macOS draws the traffic lights over its top bar", async () => {
    await import("./preload.ts");
    const { titleBar } = exposed.sauriDesktop as { titleBar: unknown };
    expect(titleBar).toBe(process.platform === "darwin" ? "inset" : "native");
  });

  it("listens only on the progress channel, passes checked copies without the IPC event, and stops on request", async () => {
    await import("./preload.ts");
    const api = exposed.sauriDesktop as { onRelocateProgress: (listener: (value: unknown) => void) => () => void };
    const seen: unknown[] = [];
    const stop = api.onRelocateProgress((value) => seen.push(value));
    expect([...listeners.keys()]).toEqual([PORTAL_CHANNELS.relocateProgress]);
    emit(PORTAL_CHANNELS.relocateProgress, { kind: "models", phase: "copying", bytesDone: 2, bytesTotal: 6, extra: "x" });
    emit(PORTAL_CHANNELS.relocateProgress, { kind: "models", phase: "rm -rf" });
    emit(PORTAL_CHANNELS.relocateProgress, { kind: "secrets", phase: "copying" });
    emit(PORTAL_CHANNELS.relocateProgress, "copying");
    emit(PORTAL_CHANNELS.relocateProgress, { kind: "database", phase: "verifying", bytesDone: 9, bytesTotal: Number.NaN });
    expect(seen).toEqual([
      { kind: "models", phase: "copying", bytesDone: 2, bytesTotal: 6 },
      { kind: "database", phase: "verifying" },
    ]);
    stop();
    emit(PORTAL_CHANNELS.relocateProgress, { kind: "models", phase: "trashing" });
    expect(seen).toHaveLength(2);
    expect(listeners.get(PORTAL_CHANNELS.relocateProgress)?.size).toBe(0);
  });

  it("passes checked copies of the updater's state, without the IPC event", async () => {
    await import("./preload.ts");
    const updates = (exposed.sauriDesktop as { updates: { onChange: (listener: (value: unknown) => void) => () => void } }).updates;
    const seen: unknown[] = [];
    const stop = updates.onChange((value) => seen.push(value));
    emit(PORTAL_CHANNELS.updateChanged, { state: "ready", current: "0.1.3", version: "0.1.4", autoCheck: true, percent: -1, extra: "x" });
    emit(PORTAL_CHANNELS.updateChanged, { state: "explode", current: "0.1.3", autoCheck: true });
    emit(PORTAL_CHANNELS.updateChanged, { state: "ready", current: 3, autoCheck: true });
    emit(PORTAL_CHANNELS.updateChanged, { state: "ready", current: "0.1.3", version: "0.1.4", autoCheck: false, error: "processing", count: 2 });
    expect(seen).toEqual([
      { state: "ready", current: "0.1.3", version: "0.1.4", autoCheck: true },
      { state: "ready", current: "0.1.3", version: "0.1.4", autoCheck: false, error: "processing", count: 2 },
    ]);
    stop();
    expect(listeners.get(PORTAL_CHANNELS.updateChanged)?.size).toBe(0);
  });

  it("passes checked copies of the services status, without the IPC event", async () => {
    await import("./preload.ts");
    const api = exposed.sauriDesktop as { onServicesStatus: (listener: (value: unknown) => void) => () => void };
    const seen: unknown[] = [];
    const stop = api.onServicesStatus((value) => seen.push(value));
    emit(PORTAL_CHANNELS.servicesChanged, { starting: true, problem: false, names: ["worker"] });
    emit(PORTAL_CHANNELS.servicesChanged, { starting: "yes", problem: false });
    emit(PORTAL_CHANNELS.servicesChanged, null);
    expect(seen).toEqual([{ starting: true, problem: false }]);
    stop();
    expect(listeners.get(PORTAL_CHANNELS.servicesChanged)?.size).toBe(0);
  });

  it("passes checked copies of the window's full screen state, false included, without the IPC event", async () => {
    await import("./preload.ts");
    const api = exposed.sauriDesktop as { onWindowState: (listener: (value: unknown) => void) => () => void };
    const seen: unknown[] = [];
    const stop = api.onWindowState((value) => seen.push(value));
    emit(PORTAL_CHANNELS.windowChanged, { fullScreen: true, bounds: { x: 0 } });
    emit(PORTAL_CHANNELS.windowChanged, { fullScreen: "yes" });
    emit(PORTAL_CHANNELS.windowChanged, true);
    emit(PORTAL_CHANNELS.windowChanged, { fullScreen: false });
    expect(seen).toEqual([{ fullScreen: true }, { fullScreen: false }]);
    stop();
    expect(listeners.get(PORTAL_CHANNELS.windowChanged)?.size).toBe(0);
  });
});
