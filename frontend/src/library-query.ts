import type { MeetingListItem } from "@sauri/shared-types";
import { compareText } from "./i18n/format";

export type LibrarySort = "newest" | "oldest" | "title";

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

function createdTime(item: MeetingListItem): number | null {
  if (!item.createdAt) return null;
  const time = new Date(item.createdAt).getTime();
  return Number.isNaN(time) ? null : time;
}

function compareByDate(left: MeetingListItem, right: MeetingListItem, direction: 1 | -1): number {
  const a = createdTime(left);
  const b = createdTime(right);
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
  const filtered = items.filter((item) => {
    if (needle && !fold(item.title).includes(needle)) return false;
    if (query.from || query.to) {
      const date = localDate(item.createdAt);
      if (date === null) return false;
      if (query.from && date < query.from) return false;
      if (query.to && date > query.to) return false;
    }
    return true;
  });

  // Array.prototype.sort is stable, so ties keep the input order.
  switch (query.sort) {
    case "oldest":
      return filtered.sort((a, b) => compareByDate(a, b, 1));
    case "title":
      return filtered.sort((a, b) => compareText(a.title, b.title));
    case "newest":
    default:
      return filtered.sort((a, b) => compareByDate(a, b, -1));
  }
}
