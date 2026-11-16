// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LAST_MEETING_STORAGE_KEY, forgetLastMeeting, readLastMeetingId, rememberLastMeeting } from "./last-meeting";

function createLocalStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

beforeEach(() => { vi.stubGlobal("localStorage", createLocalStorage()); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("last explored recording", () => {
  it("remembers, reads and forgets the id under its own key", () => {
    expect(readLastMeetingId()).toBeNull();
    rememberLastMeeting("a");
    expect(localStorage.getItem(LAST_MEETING_STORAGE_KEY)).toBe("a");
    expect(readLastMeetingId()).toBe("a");
    forgetLastMeeting("a");
    expect(readLastMeetingId()).toBeNull();
  });

  it("forgets only the recording it was asked about", () => {
    rememberLastMeeting("b");
    forgetLastMeeting("a");
    expect(readLastMeetingId()).toBe("b");
  });

  it("treats an empty value as nothing remembered", () => {
    localStorage.setItem(LAST_MEETING_STORAGE_KEY, "");
    expect(readLastMeetingId()).toBeNull();
  });

  it("does nothing, and does not throw, when storage is blocked", () => {
    const fail = () => { throw new DOMException("blocked", "SecurityError"); };
    vi.stubGlobal("localStorage", { getItem: fail, setItem: fail, removeItem: fail });
    expect(() => rememberLastMeeting("a")).not.toThrow();
    expect(readLastMeetingId()).toBeNull();
    expect(() => forgetLastMeeting("a")).not.toThrow();
  });
});
