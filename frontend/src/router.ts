import { useEffect, useState } from "react";

/** Portal routes. The path is the only source of truth; no tokens or content in the URL. */
export type Route =
  | { name: "library" }
  | { name: "upload" }
  | { name: "settings" }
  | { name: "meeting"; meetingId: string }
  | { name: "notFound" };

/** Event dispatched by `navigate` so mounted `useRoute` hooks re-read the location. */
export const NAVIGATE_EVENT = "sauri:navigate";

const MEETING_PREFIX = "/meetings/";
const NOT_FOUND_PATH = "/not-found";

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
 * `/` -> library, `/upload` -> upload, `/settings` -> settings, `/meetings/<id>` -> meeting,
 * `/?meetingId=<id>` -> meeting (the extension opens this form), anything else -> notFound.
 */
export function parseRoute(pathname: string, search: string): Route {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (path === "" || path === "/") {
    const legacyId = new URLSearchParams(search).get("meetingId");
    return legacyId ? { name: "meeting", meetingId: legacyId } : { name: "library" };
  }
  if (path === "/upload") return { name: "upload" };
  if (path === "/settings") return { name: "settings" };
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
      return "/settings";
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

  useEffect(() => {
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
