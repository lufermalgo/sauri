// The contract between the «About Sauri» window (renderer), its preload and the main process. The main process sends
// every text already translated; the window only lays it out.
import type { Locale } from "../i18n.ts";

export const ABOUT_CHANNELS = {
  view: "sauri-about:view",
  changed: "sauri-about:changed",
} as const;

/** The color of a status dot; the state is always written next to it as text too. */
export type AboutTone = "ok" | "busy" | "waiting" | "off" | "error";

export interface AboutLine {
  label: string;
  value: string;
}

export interface AboutService {
  name: string;
  state: string;
  tone: AboutTone;
}

export interface AboutView {
  lang: Locale;
  /** Window title. */
  title: string;
  /** «Sauri 0.2.1» */
  badge: string;
  tagline: string;
  web: AboutLine & { state: string; tone: AboutTone };
  services: { label: string; empty: string; items: AboutService[] };
  /** Active for, Electron version, system. */
  details: AboutLine[];
  credits: string;
  repository: { url: string; text: string; label: string };
  copyright: string;
}

export interface AboutApi {
  /** The current view; the window asks again every few seconds so «Active for» keeps counting. */
  view(): Promise<AboutView>;
  /** Called with a new view each time a service changes state or the language changes. */
  onChange(listener: (view: AboutView) => void): void;
}
