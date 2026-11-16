import type { MeetingListItem } from "@sauri/shared-types";
import { compareText } from "./i18n/format";

/** How the library is ordered: by when the recording was made, by when Sauri processed it, or by title. */
export type LibrarySort = "recordedNewest" | "recordedOldest" | "processedNewest" | "processedOldest" | "title";

/** Which date the list shows, groups by and filters on. */
export type LibraryDateField = "recorded" | "processed";

export const DEFAULT_LIBRARY_SORT: LibrarySort = "recordedNewest";

/** The date a sort is about; a title sort keeps the recording date for the cards, groups and calendar. */
export function sortDateField(sort: LibrarySort): LibraryDateField {
  return sort === "processedNewest" || sort === "processedOldest" ? "processed" : "recorded";
}

/** Newest-first date sorts are the ones shown under "Today / This week / Earlier" headings. */
export function isGroupedSort(sort: LibrarySort): boolean {
  return sort === "recordedNewest" || sort === "processedNewest";
}

/** The ISO date of a recording for the chosen field; the recording date falls back to the processed one. */
export function meetingDate(item: MeetingListItem, field: LibraryDateField): string | null {
  return field === "processed" ? item.createdAt : item.recordedAt ?? item.createdAt;
}

export interface LibraryQuery {
  text: string;
  /** Inclusive lower bound, local date "YYYY-MM-DD". */
  from: string | null;
  /** Inclusive upper bound, local date "YYYY-MM-DD". */
  to: string | null;
  sort: LibrarySort;
}

function fold(value: string): string {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Local calendar date ("YYYY-MM-DD") of an ISO timestamp, or null when missing or invalid. */
function localDate(createdAt: string | null): string | null {
  if (!createdAt) return null;
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function dateTime(item: MeetingListItem, field: LibraryDateField): number | null {
  const iso = meetingDate(item, field);
  if (!iso) return null;
  const time = new Date(iso).getTime();
  return Number.isNaN(time) ? null : time;
}

function compareByDate(
  left: MeetingListItem, right: MeetingListItem, field: LibraryDateField, direction: 1 | -1,
): number {
  const a = dateTime(left, field);
  const b = dateTime(right, field);
  if (a === null && b === null) return 0;
  if (a === null) return 1; // items without a date always go last
  if (b === null) return -1;
  return (a - b) * direction;
}

/** Filters and sorts the library list. Pure: never mutates the input array. */
export function applyLibraryQuery(
  items: MeetingListItem[],
  query: LibraryQuery,
): MeetingListItem[] {
  const needle = fold(query.text.trim());
  const field = sortDateField(query.sort);
  const filtered = items.filter((item) => {
    if (needle && !fold(item.title).includes(needle)) return false;
    if (query.from || query.to) {
      const date = localDate(meetingDate(item, field));
      if (date === null) return false;
      if (query.from && date < query.from) return false;
      if (query.to && date > query.to) return false;
    }
    return true;
  });

  // Array.prototype.sort is stable, so ties keep the input order.
  switch (query.sort) {
    case "recordedOldest":
    case "processedOldest":
      return filtered.sort((a, b) => compareByDate(a, b, field, 1));
    case "title":
      return filtered.sort((a, b) => compareText(a.title, b.title));
    case "recordedNewest":
    case "processedNewest":
    default:
      return filtered.sort((a, b) => compareByDate(a, b, field, -1));
  }
}
