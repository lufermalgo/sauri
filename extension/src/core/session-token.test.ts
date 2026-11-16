import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import {
  clearSessionToken,
  isSignInRequired,
  onSessionChanged,
  purgeLegacyToken,
  readSessionToken,
  restrictSessionStorageToTrustedContexts,
  setSignInRequired,
  storeSessionToken,
} from "./session-token";

let session: Record<string, unknown>;
let areas: { sync: { remove: Mock; set: Mock }; local: { remove: Mock; set: Mock } };
let changeListeners: Array<(changes: Record<string, unknown>, area: string) => void>;
let setAccessLevel: Mock;

beforeEach(() => {
  session = {};
  changeListeners = [];
  setAccessLevel = vi.fn(async () => undefined);
  areas = {
    sync: { remove: vi.fn(async () => undefined), set: vi.fn(async () => undefined) },
    local: { remove: vi.fn(async () => undefined), set: vi.fn(async () => undefined) },
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
    expect(listener).not.toHaveBeenCalled();
    changeListeners.forEach((fn) => fn({ sauriSessionToken: {} }, "session"));
    changeListeners.forEach((fn) => fn({ sauriSignInRequired: {} }, "session"));
    expect(listener).toHaveBeenCalledTimes(2);
    stop();
    expect(changeListeners).toHaveLength(0);
  });
});
