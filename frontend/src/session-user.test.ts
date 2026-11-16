// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readSessionUser, userInitials } from "./session-user";

function token(payload: unknown): string {
  const body = btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(payload))))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `header.${body}.signature`;
}

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  });
});

afterEach(() => { vi.unstubAllGlobals(); });

describe("readSessionUser", () => {
  it("reads name and email from the token claims, including non-ASCII names", () => {
    localStorage.setItem("sauri_token", token({ sub: "u1", name: "Zoë Çelik", email: "zoe@example.test" }));
    expect(readSessionUser()).toEqual({ name: "Zoë Çelik", email: "zoe@example.test" });
  });

  it("keeps only the claims that are present", () => {
    localStorage.setItem("sauri_token", token({ name: "  ", email: "only@example.test" }));
    expect(readSessionUser()).toEqual({ name: null, email: "only@example.test" });
  });

  it.each([
    ["no token", null],
    ["an opaque token", "synthetic-token"],
    ["an undecodable payload", "a.%%%.c"],
    ["a payload that is not an object", token("text")],
    ["a payload without claims", token({ sub: "u1" })],
  ])("returns null for %s", (_label, stored) => {
    if (stored) localStorage.setItem("sauri_token", stored);
    expect(readSessionUser()).toBeNull();
  });

  it("returns null when storage is blocked", () => {
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); } });
    expect(readSessionUser()).toBeNull();
  });
});

describe("userInitials", () => {
  it.each([
    [{ name: "Ana Maria Perez", email: null }, "AP"],
    [{ name: "Ana", email: "x@example.test" }, "A"],
    [{ name: null, email: "luis.fer@example.test" }, "LF"],
    [{ name: null, email: "admin@example.test" }, "A"],
    [{ name: "élan vital", email: null }, "ÉV"],
  ])("derives initials for %o", (user, expected) => {
    expect(userInitials(user)).toBe(expected);
  });
});
