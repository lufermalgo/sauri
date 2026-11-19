import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DESKTOP_URL, isHealth, LEGACY_URL, sauriHealth } from "../test-backend";

let session: Record<string, unknown>;
/** What answers /health on each port; a missing port refuses the connection. */
let answers: Record<string, () => Response>;

beforeEach(() => {
  vi.resetModules();
  session = {};
  answers = {};
  vi.stubGlobal("chrome", { storage: { session: {
    get: vi.fn(async (key: string) => ({ [key]: session[key] })),
    set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(session, values); }),
    remove: vi.fn(async (key: string) => { delete session[key]; }),
  } } });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const answer = answers[new URL(url).origin];
    if (!answer || !isHealth(url)) throw new TypeError("connection refused");
    return answer();
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

const probes = () => vi.mocked(fetch).mock.calls.map(([url]) => String(url));

describe("local app discovery", () => {
  it("finds the desktop app on 41750 and remembers it for the browser session", async () => {
    answers[DESKTOP_URL] = sauriHealth;
    answers[LEGACY_URL] = sauriHealth;
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBe(DESKTOP_URL);
    expect(session.sauriBackendUrl).toBe(DESKTOP_URL);
    expect(fetch).toHaveBeenCalledWith(`${DESKTOP_URL}/health`, expect.objectContaining({ credentials: "omit", cache: "no-store", redirect: "error" }));
  });

  it("reuses the remembered address in another page without probing again", async () => {
    session.sauriBackendUrl = DESKTOP_URL;
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBe(DESKTOP_URL);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("falls back to 8000 for an app that still runs there, signed or from before the signature", async () => {
    answers[LEGACY_URL] = sauriHealth;
    let backend = await import("./backend");
    expect(await backend.resolveBackendUrl()).toBe(LEGACY_URL);
    expect(probes()).toEqual([`${DESKTOP_URL}/health`, `${LEGACY_URL}/health`]);

    vi.resetModules();
    session = {};
    answers[LEGACY_URL] = () => new Response(JSON.stringify({ status: "ok" }));
    backend = await import("./backend");
    expect(await backend.resolveBackendUrl()).toBe(LEGACY_URL);
  });

  it("finds nothing when no app answers and remembers nothing", async () => {
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBeNull();
    expect(session.sauriBackendUrl).toBeUndefined();
  });

  it.each([
    ["an unsigned health answer", () => new Response(JSON.stringify({ status: "ok" }))],
    ["another service's signature", () => new Response(JSON.stringify({ status: "ok", service: "other" }))],
    ["a page that is not JSON", () => new Response("<html>dev server</html>")],
    ["an error", () => new Response("{}", { status: 503 })],
  ])("skips another program on 41750 that gives %s", async (_label, answer) => {
    answers[DESKTOP_URL] = answer;
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBeNull();
    answers[LEGACY_URL] = sauriHealth;
    const fresh = await import("./backend");
    expect(await fresh.discoverBackendUrl()).toBe(LEGACY_URL);
  });

  it("does not take another program on 8000 for an old Sauri app", async () => {
    answers[LEGACY_URL] = () => new Response(JSON.stringify({ status: "ok", uptime: 12 }));
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBeNull();
  });

  it("ignores a remembered value that is not a candidate", async () => {
    session.sauriBackendUrl = "https://example.invalid";
    answers[DESKTOP_URL] = sauriHealth;
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBe(DESKTOP_URL);
  });

  it("looks again after the remembered address is forgotten (the app moved to the new port)", async () => {
    session.sauriBackendUrl = LEGACY_URL;
    answers[DESKTOP_URL] = sauriHealth;
    const { forgetBackendUrl, resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBe(LEGACY_URL);
    await forgetBackendUrl();
    expect(session.sauriBackendUrl).toBeUndefined();
    expect(await resolveBackendUrl()).toBe(DESKTOP_URL);
  });

  it("still works where session storage is unavailable", async () => {
    vi.stubGlobal("chrome", {});
    answers[DESKTOP_URL] = sauriHealth;
    const { resolveBackendUrl } = await import("./backend");
    expect(await resolveBackendUrl()).toBe(DESKTOP_URL);
  });
});
