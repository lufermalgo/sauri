// «About Sauri» panel: version, the portal address and what each service is doing right now.
import { type Locale, type MessageKey, t } from "../i18n.ts";
import type { ServicesStatus } from "../shared/portal-api.ts";
import type { ServiceSummary } from "./services.ts";

export interface AboutInput {
  version: string;
  year: number;
  portalUrl: string;
  summary: ServiceSummary[];
  status: ServicesStatus;
}

export interface AboutPanel {
  applicationName: string;
  applicationVersion: string;
  copyright: string;
  credits: string;
}

type StateKey = Extract<MessageKey, `about.state.${string}`>;

function serviceState(item: ServiceSummary): StateKey {
  if ("blocked" in item) return item.blocked === "models_missing" ? "about.state.waitingModel" : "about.state.waiting";
  if (item.failed) return "about.state.failed";
  if (item.state === "ready") return "about.state.running";
  if (item.state === "stopped") return "about.state.stopped";
  return "about.state.starting";
}

function portalState(summary: ServiceSummary[], status: ServicesStatus): StateKey {
  const api = summary.find((item) => item.name === "api");
  if (api && "state" in api && api.state === "ready") return "about.state.running";
  return api && status.starting ? "about.state.starting" : "about.state.stopped";
}

/** The options for `app.setAboutPanelOptions`, read when the user opens the panel. */
export function aboutPanel(locale: Locale, input: AboutInput): AboutPanel {
  const portal = t(locale, "about.portal", {
    url: input.portalUrl,
    state: t(locale, portalState(input.summary, input.status)),
  });
  const services = input.summary.map((item) =>
    t(locale, "about.service", { name: item.name, state: t(locale, serviceState(item)) }),
  );
  const lines = services.length > 0 ? [portal, "", t(locale, "about.services"), ...services] : [portal];
  return {
    applicationName: t(locale, "app.name"),
    applicationVersion: input.version,
    copyright: t(locale, "about.copyright", { year: input.year }),
    credits: lines.join("\n"),
  };
}
