import { describe, expect, it } from "vitest";
import { MeetingOrigin, ProcessState, type MeetingListItem } from "@sauri/shared-types";
import { applyLibraryQuery, type LibraryQuery } from "./library-query";

function item(id: string, title: string, createdAt: string | null): MeetingListItem {
  return {
    id,
    meetLink: null,
    origin: MeetingOrigin.Link,
    processState: ProcessState.Completed,
    failureCause: null,
    createdAt,
    title,
  };
}

// Local-time timestamps (no zone suffix) keep the tests independent of the machine timezone.
const items = [
  item("a", "Caf\u00e9 sales", "2026-10-10T09:00:00"),
  item("b", "Zeta planning", "2026-10-12T23:30:00"),
  item("c", "Ángel retro", "2026-10-11T00:15:00"),
  item("d", "Sin fecha", null),
];

const base: LibraryQuery = { text: "", from: null, to: null, sort: "newest" };
const ids = (list: MeetingListItem[]) => list.map((entry) => entry.id);

describe("applyLibraryQuery", () => {
  it("returns every item newest first for an empty query, undated last", () => {
    expect(ids(applyLibraryQuery(items, base))).toEqual(["b", "c", "a", "d"]);
  });

  it("matches partially and ignoring case and accents", () => {
    expect(ids(applyLibraryQuery(items, { ...base, text: "cafe" }))).toEqual(["a"]);
    expect(ids(applyLibraryQuery(items, { ...base, text: "CAF\u00c9 S" }))).toEqual(["a"]);
    expect(ids(applyLibraryQuery(items, { ...base, text: "angel" }))).toEqual(["c"]);
    expect(ids(applyLibraryQuery(items, { ...base, text: "nada" }))).toEqual([]);
  });

  it("includes both ends of the local date range", () => {
    expect(ids(applyLibraryQuery(items, { ...base, from: "2026-10-11", to: "2026-10-12" }))).toEqual(["b", "c"]);
    expect(ids(applyLibraryQuery(items, { ...base, from: "2026-10-12", to: "2026-10-12" }))).toEqual(["b"]);
    expect(ids(applyLibraryQuery(items, { ...base, from: "2026-10-11" }))).toEqual(["b", "c"]);
    expect(ids(applyLibraryQuery(items, { ...base, to: "2026-10-10" }))).toEqual(["a"]);
  });

  it("excludes undated items when a date bound is active", () => {
    expect(ids(applyLibraryQuery(items, { ...base, from: "2000-01-01" }))).not.toContain("d");
  });

  it("sorts oldest first", () => {
    expect(ids(applyLibraryQuery(items, { ...base, sort: "oldest" }))).toEqual(["a", "c", "b", "d"]);
  });

  it("sorts by title with Spanish collation", () => {
    expect(ids(applyLibraryQuery(items, { ...base, sort: "title" }))).toEqual(["c", "a", "d", "b"]);
  });

  it("combines text, range and sort", () => {
    const result = applyLibraryQuery(items, { text: "e", from: "2026-10-10", to: "2026-10-11", sort: "title" });
    expect(ids(result)).toEqual(["c", "a"]);
  });

  it("does not mutate the input", () => {
    const snapshot = [...items];
    const result = applyLibraryQuery(items, { ...base, sort: "title" });
    expect(items).toEqual(snapshot);
    expect(result).not.toBe(items);
  });
});
