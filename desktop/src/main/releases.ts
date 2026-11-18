// The download place (design D13): one public GitHub repository whose Releases carry the app (.zip + .sha256) and
// the downloadable components. The owner approved lufermalgo/sauri-app on 2026-11-18. SAURI_RELEASES_REPO overrides
// it; an empty or malformed value turns the updater and component downloads off.
//
// Only that repository's release downloads, GitHub's release-asset host and its Releases API are ever asked;
// loopback is accepted only with SAURI_ALLOW_LOOPBACK_DOWNLOADS=1 (tests). Nothing about the user is sent.

/** owner/repo of the download place (design D13). */
export const DEFAULT_RELEASES_REPO = "lufermalgo/sauri-app";

const REPO = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/;
const LOOPBACK_BASE = /^http:\/\/127\.0\.0\.1:\d{1,5}$/;
/** Where github.com sends a release download today (checked 2026-11-18: a 302 to this host). */
export const RELEASE_ASSET_HOSTS = ["release-assets.githubusercontent.com"];

export function releasesRepo(env: NodeJS.ProcessEnv = process.env): string {
  const value = (env.SAURI_RELEASES_REPO ?? DEFAULT_RELEASES_REPO).trim();
  return REPO.test(value) ? value : "";
}

export function loopbackAllowed(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.SAURI_ALLOW_LOOPBACK_DOWNLOADS === "1";
}

/** The test switches the host engine needs to download a component from a loopback server; empty otherwise. */
export function loopbackDownloadEnv(env: NodeJS.ProcessEnv = process.env): Record<string, string> {
  if (!loopbackAllowed(env)) return {};
  const base = (env.SAURI_RELEASES_BASE_URL ?? "").replace(/\/$/, "");
  return LOOPBACK_BASE.test(base) ? { SAURI_ALLOW_LOOPBACK_DOWNLOADS: "1", SAURI_RELEASES_BASE_URL: base } : {};
}

export interface ReleaseSource {
  repo: string;
  /** GitHub's Releases API for the repository, or a test feed on loopback. */
  feedUrl: string;
  loopback: boolean;
}

/** Where the updater looks, or null while there is no download place (the updater then stays off). */
export function releaseSource(env: NodeJS.ProcessEnv = process.env): ReleaseSource | null {
  const repo = releasesRepo(env);
  if (!repo) return null;
  const loopback = loopbackAllowed(env);
  const feed = env.SAURI_UPDATE_FEED_URL;
  if (feed) {
    try {
      const url = new URL(feed);
      if (loopback && url.protocol === "http:" && url.hostname === "127.0.0.1") return { repo, feedUrl: url.href, loopback };
    } catch {
      // An unusable override falls back to GitHub.
    }
  }
  return { repo, feedUrl: `https://api.github.com/repos/${repo}/releases?per_page=20`, loopback };
}

/** True when `raw` may be fetched: the feed, a release download of the repository, or GitHub's asset host. */
export function allowedUrl(source: ReleaseSource, raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (url.username || url.password) return false;
  const releasePath = url.pathname.startsWith(`/${source.repo}/releases/download/`) && !url.pathname.includes("..");
  if (url.protocol === "https:" && (url.port === "" || url.port === "443")) {
    if (url.hostname === "github.com") return releasePath;
    if (url.hostname === "api.github.com") return url.pathname === `/repos/${source.repo}/releases`;
    return RELEASE_ASSET_HOSTS.includes(url.hostname);
  }
  if (source.loopback && url.protocol === "http:" && url.hostname === "127.0.0.1") {
    return releasePath || url.href === source.feedUrl;
  }
  return false;
}
