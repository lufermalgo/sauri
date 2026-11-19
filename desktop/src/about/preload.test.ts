import { describe, expect, it, vi } from "vitest";
import { ABOUT_CHANNELS } from "../shared/about-api.ts";

const exposed: Record<string, unknown> = {};
const invoke = vi.fn(async () => ({ title: "About Sauri" }));
const on = vi.fn();
vi.mock("electron", () => ({
  contextBridge: { exposeInMainWorld: (name: string, api: unknown) => (exposed[name] = api) },
  ipcRenderer: { invoke, on },
}));

describe("about preload", () => {
  it("exposes only reading the view and listening for a new one", async () => {
    await import("./preload.ts");
    expect(Object.keys(exposed)).toEqual(["sauriAbout"]);
    const api = exposed.sauriAbout as { view: () => Promise<unknown>; onChange: (listener: (view: unknown) => void) => void };
    expect(Object.keys(api).sort()).toEqual(["onChange", "view"]);
    await expect(api.view()).resolves.toEqual({ title: "About Sauri" });
    expect(invoke).toHaveBeenCalledWith(ABOUT_CHANNELS.view);

    const listener = vi.fn();
    api.onChange(listener);
    expect(on).toHaveBeenCalledWith(ABOUT_CHANNELS.changed, expect.any(Function));
    const handler = on.mock.calls[0][1] as (event: unknown, view: unknown) => void;
    handler({ sender: "ipc-event" }, { title: "Acerca de Sauri" });
    expect(listener).toHaveBeenCalledWith({ title: "Acerca de Sauri" });
  });
});
