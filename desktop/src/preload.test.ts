import { describe, expect, it, vi } from "vitest";
import { PORTAL_CHANNELS } from "./shared/portal-api.ts";

const exposed: Record<string, unknown> = {};
const invoke = vi.fn(async () => undefined);
vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld: (name: string, api: unknown) => (exposed[name] = api) },
  ipcRenderer: { invoke },
}));

describe("portal preload", () => {
  it("exposes only the three whitelisted calls, each on its own channel", async () => {
    await import("./preload.ts");
    expect(Object.keys(exposed)).toEqual(["sauriDesktop"]);
    const api = exposed.sauriDesktop as Record<string, (...args: unknown[]) => Promise<unknown>>;
    expect(Object.keys(api).sort()).toEqual(["getPaths", "markSetupDone", "relocate"]);
    await api.getPaths();
    await api.relocate("models");
    await api.markSetupDone();
    expect(invoke.mock.calls).toEqual([
      [PORTAL_CHANNELS.getPaths],
      [PORTAL_CHANNELS.relocate, "models"],
      [PORTAL_CHANNELS.markSetupDone],
    ]);
  });
});
