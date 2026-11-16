import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  clearAllSessionTokens,
  clearRefreshToken,
  clearRefreshTokenIf,
  clearSessionToken,
  clearSessionTokenIf,
  isSignInRequired,
  onSessionChanged,
  purgeLegacyToken,
  readRefreshToken,
  readSessionToken,
  restrictSessionStorageToTrustedContexts,
  setSignInRequired,
  storeRefreshToken,
  storeSessionCredentials,
  storeSessionToken,
} from "./session-token";

let session: Record<string, unknown>;
let local: Record<string, unknown>;
let areas: { sync: { remove: Mock; set: Mock }; local: { get: Mock; remove: Mock; set: Mock } };
let changeListeners: Array<(changes: Record<string, unknown>, area: string) => void>;
let setAccessLevel: Mock;

beforeEach(() => {
  session = {};
  local = {};
  changeListeners = [];
  setAccessLevel = vi.fn(async () => undefined);
  areas = {
    sync: { remove: vi.fn(async () => undefined), set: vi.fn(async () => undefined) },
    local: {
      get: vi.fn(async (key: string) => (key in local ? { [key]: local[key] } : {})),
      set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(local, values); }),
      remove: vi.fn(async (key: string) => { delete local[key]; }),
    },
  };
  vi.stubGlobal("chrome", {
    storage: {
      session: {
        get: vi.fn(async (key: string) => (key in session ? { [key]: session[key] } : {})),
        set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(session, values); }),
        remove: vi.fn(async (key: string) => { delete session[key]; }),
        setAccessLevel,
      },
      sync: areas.sync,
      local: areas.local,
      onChanged: {
        addListener: vi.fn((fn) => changeListeners.push(fn)),
        removeListener: vi.fn((fn) => { changeListeners = changeListeners.filter((item) => item !== fn); }),
      },
    },
  });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("session token storage", () => {
  it("round-trips the token through chrome.storage.session only", async () => {
    expect(await readSessionToken()).toBeUndefined();
    await storeSessionToken("token-1");
    expect(await readSessionToken()).toBe("token-1");
    expect(local).toEqual({});
    expect(areas.sync.set).not.toHaveBeenCalled();
    expect(areas.local.set).not.toHaveBeenCalled();
    await clearSessionToken();
    expect(await readSessionToken()).toBeUndefined();
  });

  it("ignores values that are not a non-empty string", async () => {
    for (const bad of ["", 7, null, {}, true]) {
      session = { sauriSessionToken: bad };
      expect(await readSessionToken()).toBeUndefined();
    }
  });

  it("signing in clears the pending sign-in prompt", async () => {
    await setSignInRequired();
    expect(await isSignInRequired()).toBe(true);
    await storeSessionToken("token-2");
    expect(await isSignInRequired()).toBe(false);
  });

  it("requests trusted-contexts-only access and survives an unsupported browser", async () => {
    await restrictSessionStorageToTrustedContexts();
    expect(setAccessLevel).toHaveBeenCalledWith({ accessLevel: "TRUSTED_CONTEXTS" });
    setAccessLevel.mockRejectedValueOnce(new Error("unsupported"));
    await expect(restrictSessionStorageToTrustedContexts()).resolves.toBeUndefined();
  });
});

describe("refresh token storage (survives a reload and a restart)", () => {
  it("lives only in chrome.storage.local: never in session or synced storage", async () => {
    await storeRefreshToken("refresh-1");
    expect(await readRefreshToken()).toBe("refresh-1");
    expect(local).toEqual({ sauriRefreshToken: "refresh-1" });
    expect(session).toEqual({});
    expect(areas.sync.set).not.toHaveBeenCalled();
    await clearRefreshToken();
    expect(await readRefreshToken()).toBeUndefined();
  });

  it("ignores values that are not a non-empty string", async () => {
    for (const bad of ["", 7, null, {}, true]) {
      local = { sauriRefreshToken: bad };
      expect(await readRefreshToken()).toBeUndefined();
    }
  });

  it("is removed only when it is still the one a rejection was about", async () => {
    await storeRefreshToken("new-refresh");
    expect(await clearRefreshTokenIf("old-refresh")).toBe(false);
    expect(await clearRefreshTokenIf(undefined)).toBe(false);
    expect(await readRefreshToken()).toBe("new-refresh");
    expect(await clearRefreshTokenIf("new-refresh")).toBe(true);
    expect(await readRefreshToken()).toBeUndefined();
  });

  it("storing credentials writes the refresh token before the access token, each in its own area", async () => {
    const order: string[] = [];
    areas.local.set.mockImplementation(async (values: Record<string, unknown>) => { order.push("local"); Object.assign(local, values); });
    const original = chrome.storage.session.set as Mock;
    original.mockImplementation(async (values: Record<string, unknown>) => { order.push("session"); Object.assign(session, values); });
    await storeSessionCredentials("access-1", "refresh-1");
    expect(order).toEqual(["local", "session"]);
    expect(session).toEqual({ sauriSessionToken: "access-1" });
    expect(local).toEqual({ sauriRefreshToken: "refresh-1" });
  });

  it("storing credentials without a refresh token drops a stale one", async () => {
    await storeRefreshToken("stale-refresh");
    await storeSessionCredentials("access-1");
    expect(await readRefreshToken()).toBeUndefined();
    expect(await readSessionToken()).toBe("access-1");
  });

  it("signing out removes both", async () => {
    await storeSessionCredentials("access-1", "refresh-1");
    await clearAllSessionTokens();
    expect(await readSessionToken()).toBeUndefined();
    expect(await readRefreshToken()).toBeUndefined();
  });

  it("a freshly loaded module instance sees the refresh token (a restarted service worker starts empty)", async () => {
    await storeRefreshToken("refresh-1");
    vi.resetModules();
    expect(await (await import("./session-token")).readRefreshToken()).toBe("refresh-1");
  });
});

describe("legacy token cleanup", () => {
  it("deletes the legacy key from synced and local storage and copies nothing", async () => {
    session = {};
    await purgeLegacyToken();
    expect(areas.sync.remove).toHaveBeenCalledWith("authToken");
    expect(areas.local.remove).toHaveBeenCalledWith("authToken");
    expect(areas.sync.set).not.toHaveBeenCalled();
    expect(areas.local.set).not.toHaveBeenCalled();
    expect(session).toEqual({});
  });

  it("keeps cleaning the other area when one fails", async () => {
    areas.sync.remove.mockRejectedValueOnce(new Error("sync unavailable"));
    await expect(purgeLegacyToken()).resolves.toBeUndefined();
    expect(areas.local.remove).toHaveBeenCalledWith("authToken");
  });
});

describe("session change notifications", () => {
  it("fires only for token or sign-in prompt changes in session storage", () => {
    const listener = vi.fn();
    const stop = onSessionChanged(listener);
    changeListeners.forEach((fn) => fn({ sauriState: {} }, "session"));
    changeListeners.forEach((fn) => fn({ sauriSessionToken: {} }, "local"));
    changeListeners.forEach((fn) => fn({ recordingSettings: {} }, "local"));
    expect(listener).not.toHaveBeenCalled();
    changeListeners.forEach((fn) => fn({ sauriRefreshToken: {} }, "local"));
    expect(listener).toHaveBeenCalledTimes(1);
    listener.mockClear();
    changeListeners.forEach((fn) => fn({ sauriSessionToken: {} }, "session"));
    changeListeners.forEach((fn) => fn({ sauriSignInRequired: {} }, "session"));
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
    expect(changeListeners).toHaveLength(0);
  });
});

describe("clearSessionTokenIf (a stale 401 must not sign the user out again, #1113)", () => {
  it("removes the token that the rejected request was sent with", async () => {
    await storeSessionToken("old-token");
    expect(await clearSessionTokenIf("old-token")).toBe(true);
    expect(await readSessionToken()).toBeUndefined();
  });

  it("keeps a newer token when the rejected one was already replaced by a new sign-in", async () => {
    await storeSessionToken("old-token");
    await storeSessionToken("fresh-token");
    expect(await clearSessionTokenIf("old-token")).toBe(false);
    expect(await readSessionToken()).toBe("fresh-token");
  });

  it("never removes a stored token on behalf of a request that carried none", async () => {
    await storeSessionToken("fresh-token");
    expect(await clearSessionTokenIf(undefined)).toBe(false);
    expect(await readSessionToken()).toBe("fresh-token");
  });
});

describe("every context re-reads the token from storage (page refresh, service worker restart)", () => {
  it("a freshly loaded module instance sees the token another instance stored", async () => {
    await storeSessionToken("shared-token");
    vi.resetModules(); // A refreshed panel or a restarted service worker starts with empty memory.
    const reloaded = await import("./session-token");
    expect(await reloaded.readSessionToken()).toBe("shared-token");
  });
});
