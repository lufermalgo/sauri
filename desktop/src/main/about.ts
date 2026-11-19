// «About Sauri» window: version, the web service address, what each service is doing right now, how long the app has
// been open and the system it runs on. Everything here is plain data: main.ts builds the window and sends this view.
import { type Locale, type MessageKey, plural, t } from "../i18n.ts";
import type { AboutTone, AboutView } from "../shared/about-api.ts";
import { DEFAULT_RELEASES_REPO } from "./releases.ts";
import type { ServiceSummary } from "./services.ts";

/** The public repository the window links to; it opens in the default browser, never inside the window. */
export const REPOSITORY_URL = `https://github.com/${DEFAULT_RELEASES_REPO}`;

/** Fixed size of the window (it cannot be resized). */
export const ABOUT_WINDOW_SIZE = { width: 720, height: 520 } as const;

export interface AboutInput {
  version: string;
  year: number;
  portalUrl: string;
  summary: ServiceSummary[];
  /** Milliseconds since the app started. */
  uptimeMs: number;
  electron: string;
  /** macOS version (`process.getSystemVersion()`) and `process.arch`. */
  system: { version: string; arch: string };
}

type StateKey = Extract<MessageKey, `about.state.${string}`>;

const TONES: Record<StateKey, AboutTone> = {
  "about.state.running": "ok",
  "about.state.starting": "busy",
  "about.state.waitingModel": "waiting",
  "about.state.waiting": "waiting",
  "about.state.stopped": "off",
  "about.state.failed": "error",
};

/** Friendly names, in the order the window lists them; the API is the «web service» line, not part of the list. */
const SERVICE_NAMES: [string, MessageKey][] = [
  ["asr-engine", "about.name.transcription"],
  ["diar-engine", "about.name.speakers"],
  ["llm-engine", "about.name.summaries"],
  ["postgres", "about.name.database"],
  ["worker", "about.name.processing"],
  ["host-engine", "about.name.models"],
];

export function serviceState(item: ServiceSummary): StateKey {
  if ("blocked" in item) return item.blocked === "models_missing" ? "about.state.waitingModel" : "about.state.waiting";
  if (item.failed) return "about.state.failed";
  if (item.state === "ready") return "about.state.running";
  if (item.state === "stopped") return "about.state.stopped";
  return "about.state.starting";
}

/** The web service is the API: stopped until it exists. */
function webState(summary: ServiceSummary[]): StateKey {
  const api = summary.find((item) => item.name === "api");
  return api ? serviceState(api) : "about.state.stopped";
}

/** «less than a minute», «12 minutes», «2 h 34 min», «3 days 4 h» (and the same in Spanish). */
export function formatUptime(locale: Locale, ms: number): string {
  const minutes = Math.floor(Math.max(0, ms) / 60_000);
  if (minutes < 1) return t(locale, "about.uptime.lessThanMinute");
  if (minutes < 60) return plural(locale, "about.uptime.minutes", minutes);
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest === 0 ? t(locale, "about.uptime.hours", { hours }) : t(locale, "about.uptime.hoursMinutes", { hours, minutes: rest });
  }
  const days = plural(locale, "about.uptime.days", Math.floor(hours / 24));
  const rest = hours % 24;
  return rest === 0 ? days : `${days} ${t(locale, "about.uptime.hours", { hours: rest })}`;
}

/** Only the public repository, over https, with no other host, port, credentials, query or fragment. */
export function isRepositoryUrl(value: string): boolean {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  const expected = new URL(REPOSITORY_URL);
  return (
    url.protocol === "https:" &&
    url.host === expected.host &&
    url.username === "" &&
    url.password === "" &&
    url.search === "" &&
    url.hash === "" &&
    (url.pathname === expected.pathname || url.pathname === `${expected.pathname}/`)
  );
}

function architecture(locale: Locale, arch: string): string {
  return arch === "arm64" ? t(locale, "about.arch.arm64") : arch;
}

/** What the window shows, every text translated. */
export function aboutView(locale: Locale, input: AboutInput): AboutView {
  const known = new Map(SERVICE_NAMES);
  const order = (name: string) => {
    const index = SERVICE_NAMES.findIndex(([service]) => service === name);
    return index === -1 ? SERVICE_NAMES.length : index;
  };
  const items = input.summary
    .filter((item) => item.name !== "api")
    .sort((a, b) => order(a.name) - order(b.name))
    .map((item) => {
      const key = known.get(item.name);
      const state = serviceState(item);
      return { name: key ? t(locale, key) : item.name, state: t(locale, state), tone: TONES[state] };
    });
  const web = webState(input.summary);
  const repository = new URL(REPOSITORY_URL);
  return {
    lang: locale,
    title: t(locale, "menu.about"),
    badge: t(locale, "about.badge", { version: input.version }),
    tagline: t(locale, "about.tagline"),
    web: {
      label: t(locale, "about.row.web"),
      value: input.portalUrl.replace(/\/$/, ""),
      state: t(locale, web),
      tone: TONES[web],
    },
    services: { label: t(locale, "about.row.services"), empty: t(locale, "about.services.none"), items },
    details: [
      { label: t(locale, "about.row.uptime"), value: formatUptime(locale, input.uptimeMs) },
      { label: t(locale, "about.row.electron"), value: input.electron },
      {
        label: t(locale, "about.row.system"),
        value: t(locale, "about.system", { version: input.system.version, arch: architecture(locale, input.system.arch) }),
      },
    ],
    credits: t(locale, "about.credits"),
    repository: { url: REPOSITORY_URL, text: `${repository.host}${repository.pathname}`, label: t(locale, "about.repository") },
    copyright: t(locale, "about.copyright", { year: input.year }),
  };
}
