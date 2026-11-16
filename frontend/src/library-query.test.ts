import { describe, expect, it } from "vitest";
import { MeetingOrigin, ProcessState, type MeetingListItem } from "@sauri/shared-types";
import {
  applyLibraryQuery, DEFAULT_LIBRARY_SORT, isGroupedSort, meetingDate, sortDateField, type LibraryQuery,
} from "./library-query";

function item(id: string, title: string, createdAt: string | null, recordedAt?: string | null): MeetingListItem {
  return {
    id,
    meetLink: null,
    origin: MeetingOrigin.Link,
    processState: ProcessState.Completed,
    failureCause: null,
    createdAt,
    ...(recordedAt === undefined ? {} : { recordedAt }),
    title,
    durationSeconds: null,
    speakerCount: null,
    summaryTopic: null,
    thumbnailUrl: null,
    mediaKind: null,
  };
}

// Local-time timestamps (no zone suffix) keep the tests independent of the machine timezone.
const items = [
  item("a", "Caf\u00e9 sales", "2026-10-10T09:00:00"),
  item("b", "Zeta planning", "2026-10-12T23:30:00"),
  item("c", "Ángel retro", "2026-10-11T00:15:00"),
  item("d", "Sin fecha", null),
];

const base: LibraryQuery = { text: "", from: null, to: null, sort: "processedNewest" };
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
    expect(ids(applyLibraryQuery(items, { ...base, sort: "processedOldest" }))).toEqual(["a", "c", "b", "d"]);
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

// "old" was uploaded last but recorded first; "legacy" has no recording date (an older backend).
const recorded = [
  item("old", "Old video", "2026-11-16T09:00:00", "2025-06-01T10:00:00"),
  item("mid", "Mid video", "2026-11-10T09:00:00", "2026-11-09T18:00:00"),
  item("new", "New video", "2026-11-12T09:00:00", "2026-11-12T08:00:00"),
  item("legacy", "Legacy video", "2026-11-11T09:00:00"),
  item("nodate", "No date", null, null),
];

describe("recording date and processed date", () => {
  it("defaults to the recording date, newest first", () => {
    expect(DEFAULT_LIBRARY_SORT).toBe("recordedNewest");
    expect(ids(applyLibraryQuery(recorded, { ...base, sort: DEFAULT_LIBRARY_SORT }))).toEqual(
      ["new", "legacy", "mid", "old", "nodate"],
    );
  });

  it("sorts by recording date, oldest first, undated last", () => {
    expect(ids(applyLibraryQuery(recorded, { ...base, sort: "recordedOldest" }))).toEqual(
      ["old", "mid", "legacy", "new", "nodate"],
    );
  });

  it("sorts by processed date in both directions, ignoring the recording date", () => {
    expect(ids(applyLibraryQuery(recorded, { ...base, sort: "processedNewest" }))).toEqual(
      ["old", "new", "legacy", "mid", "nodate"],
    );
    expect(ids(applyLibraryQuery(recorded, { ...base, sort: "processedOldest" }))).toEqual(
      ["mid", "legacy", "new", "old", "nodate"],
    );
  });

  it("falls back to the processed date when there is no recording date", () => {
    expect(meetingDate(recorded[3], "recorded")).toBe("2026-11-11T09:00:00");
    expect(meetingDate(recorded[3], "processed")).toBe("2026-11-11T09:00:00");
    expect(meetingDate(recorded[0], "recorded")).toBe("2025-06-01T10:00:00");
    expect(meetingDate(recorded[0], "processed")).toBe("2026-11-16T09:00:00");
  });

  it("filters the calendar range by the date field of the sort", () => {
    const range = { from: "2026-11-16", to: "2026-11-16" };
    expect(ids(applyLibraryQuery(recorded, { ...base, ...range, sort: "processedNewest" }))).toEqual(["old"]);
    expect(ids(applyLibraryQuery(recorded, { ...base, ...range, sort: "recordedNewest" }))).toEqual([]);
    const june = { from: "2025-06-01", to: "2025-06-01" };
    expect(ids(applyLibraryQuery(recorded, { ...base, ...june, sort: "recordedNewest" }))).toEqual(["old"]);
    // A title sort keeps the recording date for the calendar.
    expect(ids(applyLibraryQuery(recorded, { ...base, ...june, sort: "title" }))).toEqual(["old"]);
  });

  it("knows which date each sort is about and which sorts are grouped by day", () => {
    expect(sortDateField("recordedNewest")).toBe("recorded");
    expect(sortDateField("recordedOldest")).toBe("recorded");
    expect(sortDateField("title")).toBe("recorded");
    expect(sortDateField("processedNewest")).toBe("processed");
    expect(sortDateField("processedOldest")).toBe("processed");
    expect(["recordedNewest", "processedNewest"].every((sort) => isGroupedSort(sort as never))).toBe(true);
    expect(["recordedOldest", "processedOldest", "title"].some((sort) => isGroupedSort(sort as never))).toBe(false);
  });
});
