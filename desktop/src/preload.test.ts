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
    expect(Object.keys(api).sort()).toEqual(["getLocale", "getPaths", "markSetupDone", "onRelocateProgress", "relocate", "updates"]);
    const updates = api.updates as unknown as Record<string, (...args: unknown[]) => Promise<unknown>>;
    expect(Object.keys(updates).sort()).toEqual(["apply", "check", "setAutoCheck", "status"]);
    await api.getPaths();
    await api.relocate("models");
    await api.markSetupDone();
    await api.getLocale();
    await updates.status();
    await updates.check();
    await updates.apply();
    await updates.setAutoCheck("yes");
    expect(invoke.mock.calls).toEqual([
      [PORTAL_CHANNELS.getPaths],
      [PORTAL_CHANNELS.relocate, "models"],
      [PORTAL_CHANNELS.markSetupDone],
      [PORTAL_CHANNELS.getLocale],
      [PORTAL_CHANNELS.updateStatus],
      [PORTAL_CHANNELS.updateCheck],
      [PORTAL_CHANNELS.updateApply],
      [PORTAL_CHANNELS.updateAutoCheck, false],
    ]);
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
});
