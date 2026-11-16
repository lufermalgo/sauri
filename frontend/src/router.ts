import { useLayoutEffect, useState } from "react";
import { copy } from "./copy/es";

/** Portal routes. The path is the only source of truth; no tokens or content in the URL. */
export type Route =
  | { name: "library" }
  | { name: "upload" }
  | { name: "settings"; category?: SettingsCategory }
  | { name: "meeting"; meetingId: string }
  | { name: "notFound" };

/** Settings categories; the URL slugs are product copy (see `copy.settings.categories`). */
export const SETTINGS_CATEGORIES = [
  "account",
  "appearance",
  "engines",
  "transcription",
  "speakers",
  "summaries",
] as const;
export type SettingsCategory = (typeof SETTINGS_CATEGORIES)[number];

/** Navigation groups, in display order; the group labels are product copy (`copy.settings.groups`). */
export const SETTINGS_GROUPS = [
  { id: "general", categories: ["account", "appearance"] },
  { id: "models", categories: ["engines", "transcription", "speakers", "summaries"] },
] as const satisfies ReadonlyArray<{ id: string; categories: readonly SettingsCategory[] }>;
export type SettingsGroupId = (typeof SETTINGS_GROUPS)[number]["id"];

/** Reserved for a later chat category: declared so its name is not reused, but not routed or listed. */
export const RESERVED_SETTINGS_CATEGORIES = ["chat"] as const;

/** Category shown on wide screens when the URL names none. */
export const DEFAULT_SETTINGS_CATEGORY: SettingsCategory = "account";

/** Event dispatched by `navigate` so mounted `useRoute` hooks re-read the location. */
export const NAVIGATE_EVENT = "sauri:navigate";

const MEETING_PREFIX = "/meetings/";
const SETTINGS_PATH = "/settings";
const SETTINGS_PREFIX = "/settings/";
const NOT_FOUND_PATH = "/not-found";

/** Slugs of removed categories: an old link still opens Settings (on the default category) instead of "not found". */
const REMOVED_SETTINGS_SLUGS: readonly string[] = ["grabacion"]; // spanish-sample-data i18n-ignore: a shipped URL slug

function settingsRoute(slug: string): Route {
  if (REMOVED_SETTINGS_SLUGS.includes(slug)) return { name: "settings" };
  const category = SETTINGS_CATEGORIES.find((name) => copy.settings.categories[name].slug === slug);
  return category ? { name: "settings", category } : { name: "notFound" };
}

function meetingRoute(rawId: string): Route {
  if (!rawId || rawId.includes("/")) return { name: "notFound" };
  try {
    const meetingId = decodeURIComponent(rawId);
    return meetingId ? { name: "meeting", meetingId } : { name: "notFound" };
  } catch {
    return { name: "notFound" };
  }
}

/**
 * Maps a location to a route.
 * `/` -> library, `/upload` -> upload, `/settings` -> settings, `/settings/<category slug>` -> settings
 * with that category, `/meetings/<id>` -> meeting,
 * `/?meetingId=<id>` -> meeting (the extension opens this form), anything else -> notFound.
 */
export function parseRoute(pathname: string, search: string): Route {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (path === "" || path === "/") {
    const legacyId = new URLSearchParams(search).get("meetingId");
    return legacyId ? { name: "meeting", meetingId: legacyId } : { name: "library" };
  }
  if (path === "/upload") return { name: "upload" };
  if (path === SETTINGS_PATH) return { name: "settings" };
  if (path.startsWith(SETTINGS_PREFIX)) return settingsRoute(path.slice(SETTINGS_PREFIX.length));
  if (path.startsWith(MEETING_PREFIX)) return meetingRoute(path.slice(MEETING_PREFIX.length));
  return { name: "notFound" };
}

/** Inverse of `parseRoute` for path-only routes; the meeting id is URL-encoded. */
export function routePath(route: Route): string {
  switch (route.name) {
    case "library":
      return "/";
    case "upload":
      return "/upload";
    case "settings":
      return route.category
        ? `${SETTINGS_PREFIX}${copy.settings.categories[route.category].slug}`
        : SETTINGS_PATH;
    case "meeting":
      return `${MEETING_PREFIX}${encodeURIComponent(route.meetingId)}`;
    case "notFound":
      return NOT_FOUND_PATH;
  }
}

/** Changes the URL without reloading and notifies mounted `useRoute` hooks. */
export function navigate(route: Route, options: { replace?: boolean } = {}): void {
  const path = routePath(route);
  if (options.replace) {
    window.history.replaceState(null, "", path);
  } else {
    window.history.pushState(null, "", path);
  }
  window.dispatchEvent(new Event(NAVIGATE_EVENT));
}

function readLocation(): Route {
  return parseRoute(window.location.pathname, window.location.search);
}

function isLegacyMeetingUrl(route: Route): boolean {
  return (
    route.name === "meeting" &&
    window.location.pathname === "/" &&
    new URLSearchParams(window.location.search).has("meetingId")
  );
}

/**
 * Current route, kept in sync with `popstate` (browser back/forward) and `sauri:navigate`.
 * A legacy `/?meetingId=<id>` URL is rewritten to `/meetings/<id>` with `replaceState`.
 */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(readLocation);

  // A layout effect, so the listeners exist before the layout effects of the components above it:
  // a `navigate` made there (the start redirect) reaches this hook before the first paint.
  useLayoutEffect(() => {
    const sync = () => {
      const current = readLocation();
      if (isLegacyMeetingUrl(current) && current.name === "meeting") {
        window.history.replaceState(null, "", routePath(current));
      }
      setRoute(current);
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener(NAVIGATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(NAVIGATE_EVENT, sync);
    };
  }, []);

  return route;
}
