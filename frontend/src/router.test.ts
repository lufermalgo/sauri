// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { navigate, parseRoute, routePath, useRoute, type Route } from "./router";

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("parseRoute", () => {
  it("resolves every route", () => {
    expect(parseRoute("/", "")).toEqual({ name: "library" });
    expect(parseRoute("/upload", "")).toEqual({ name: "upload" });
    expect(parseRoute("/settings", "")).toEqual({ name: "settings" });
    expect(parseRoute("/settings/", "")).toEqual({ name: "settings" });
    expect(parseRoute("/settings/extra", "")).toEqual({ name: "notFound" });
    expect(parseRoute("/meetings/m1", "")).toEqual({ name: "meeting", meetingId: "m1" });
    expect(parseRoute("/anything-else", "")).toEqual({ name: "notFound" });
  });

  it("treats a trailing slash like the plain path", () => {
    expect(parseRoute("/upload/", "")).toEqual({ name: "upload" });
    expect(parseRoute("/meetings/m1/", "")).toEqual({ name: "meeting", meetingId: "m1" });
  });

  it("maps ?meetingId= on / to the meeting route", () => {
    expect(parseRoute("/", "?meetingId=m9")).toEqual({ name: "meeting", meetingId: "m9" });
    expect(parseRoute("/", "?meetingId=")).toEqual({ name: "library" });
    expect(parseRoute("/upload", "?meetingId=m9")).toEqual({ name: "upload" });
  });

  it("rejects malformed meeting paths", () => {
    expect(parseRoute("/meetings/", "")).toEqual({ name: "notFound" });
    expect(parseRoute("/meetings/a/b", "")).toEqual({ name: "notFound" });
    expect(parseRoute("/meetings/%E0%A4%A", "")).toEqual({ name: "notFound" });
  });
});

describe("routePath", () => {
  const routes: Route[] = [
    { name: "library" },
    { name: "upload" },
    { name: "settings" },
    { name: "meeting", meetingId: "m1" },
    { name: "notFound" },
  ];

  it.each(routes)("round-trips %o", (route) => {
    expect(parseRoute(routePath(route), "")).toEqual(route);
  });

  it("encodes special characters in the meeting id", () => {
    const route: Route = { name: "meeting", meetingId: "a b/c?d#é%" };
    const path = routePath(route);
    expect(path).toBe("/meetings/a%20b%2Fc%3Fd%23%C3%A9%25");
    expect(parseRoute(path, "")).toEqual(route);
  });
});

describe("useRoute", () => {
  it("reads the current location", () => {
    window.history.replaceState(null, "", "/upload");
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "upload" });
  });

  it("follows navigate()", () => {
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "library" });

    act(() => navigate({ name: "meeting", meetingId: "m2" }));
    expect(result.current).toEqual({ name: "meeting", meetingId: "m2" });
    expect(window.location.pathname).toBe("/meetings/m2");

    act(() => navigate({ name: "upload" }, { replace: true }));
    expect(result.current).toEqual({ name: "upload" });
    expect(window.location.pathname).toBe("/upload");
  });

  it("replaces ?meetingId= with /meetings/<id> without adding history", () => {
    window.history.replaceState(null, "", "/?meetingId=m1");
    const lengthBefore = window.history.length;
    const { result } = renderHook(() => useRoute());
    expect(result.current).toEqual({ name: "meeting", meetingId: "m1" });
    expect(window.location.pathname).toBe("/meetings/m1");
    expect(window.location.search).toBe("");
    expect(window.history.length).toBe(lengthBefore);
  });

  it("updates on popstate (browser back button)", () => {
    const { result } = renderHook(() => useRoute());
    act(() => navigate({ name: "upload" }));
    expect(result.current).toEqual({ name: "upload" });

    act(() => {
      window.history.replaceState(null, "", "/");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(result.current).toEqual({ name: "library" });
  });
});
