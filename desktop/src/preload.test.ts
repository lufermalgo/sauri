import { describe, expect, it, vi } from "vitest";
import { PORTAL_CHANNELS } from "./shared/portal-api.ts";

const exposed: Record<string, unknown> = {};
const invoke = vi.fn(async () => undefined);
vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld: (name: string, api: unknown) => (exposed[name] = api) },
  ipcRenderer: { invoke },
}));

describe("portal preload", () => {
  it("exposes only the whitelisted calls, each on its own channel", async () => {
    await import("./preload.ts");
    expect(Object.keys(exposed)).toEqual(["sauriDesktop"]);
    const api = exposed.sauriDesktop as Record<string, (...args: unknown[]) => Promise<unknown>>;
    expect(Object.keys(api).sort()).toEqual(["getLocale", "getPaths", "markSetupDone", "relocate", "updates"]);
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
});
