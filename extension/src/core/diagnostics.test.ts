import { afterEach, describe, expect, it, vi } from "vitest";
import { DIAGNOSTICS_KEY, DIAGNOSTICS_LIMIT, logDiagnostic } from "./diagnostics";

afterEach(() => { vi.unstubAllGlobals(); });

function stubStorage() {
  const store: Record<string, unknown> = {};
  vi.stubGlobal("chrome", { storage: { local: {
    get: vi.fn(async (key: string) => ({ [key]: store[key] })),
    set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(store, values); }),
  } } });
  return store;
}

describe("capture diagnostics", () => {
  it("stores the newest entries only", async () => {
    const store = stubStorage();
    for (let i = 0; i < DIAGNOSTICS_LIMIT + 5; i++) void logDiagnostic("event", String(i));
    await logDiagnostic("last");
    const entries = store[DIAGNOSTICS_KEY] as { event: string; detail?: string }[];
    expect(entries).toHaveLength(DIAGNOSTICS_LIMIT);
    expect(entries.at(-1)?.event).toBe("last");
    expect(entries[0].detail).toBe("6");
  });

  it("never throws when storage fails", async () => {
    vi.stubGlobal("chrome", { storage: { local: { get: vi.fn(async () => { throw new Error("denied"); }), set: vi.fn() } } });
    await expect(logDiagnostic("event")).resolves.toBeUndefined();
  });
});
