import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import en from "../locales/en.json";
import es from "../locales/es.json";
import { aboutView, formatUptime, isRepositoryUrl, REPOSITORY_URL } from "./about.ts";
import type { ServiceSummary } from "./services.ts";

const URL = "http://localhost:41750/";
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const SUMMARY: ServiceSummary[] = [
  { name: "postgres", state: "ready", failed: false },
  { name: "api", state: "ready", failed: false },
  { name: "asr-engine", state: "starting", failed: false },
  { name: "diar-engine", state: "restarting", failed: true },
  { name: "worker", state: "stopped", failed: false },
  { name: "llm-engine", blocked: "models_missing" },
  { name: "host-engine", blocked: "component_missing" },
];

const INPUT = {
  version: "0.2.1",
  year: 2026,
  portalUrl: URL,
  summary: SUMMARY,
  uptimeMs: 2 * HOUR + 34 * MINUTE,
  electron: "44.10.2",
  system: { version: "26.1", arch: "arm64" },
};

const desktop = path.resolve(import.meta.dirname, "..", "..");

describe("aboutView", () => {
  it("names the app, its version and the year", () => {
    const view = aboutView("es", { ...INPUT, summary: [] });
    expect(view.title).toBe("Acerca de Sauri");
    expect(view.badge).toBe("Sauri 0.2.1");
    expect(view.copyright).toMatch(/^© 2026 Sauri\./);
    expect(view.tagline).toContain("Todo se procesa en tu Mac");
  });

  it("lists every service by its friendly name and state, in Spanish and in order", () => {
    const view = aboutView("es", INPUT);
    expect(view.services.items).toEqual([
      { name: "Transcripción", state: "iniciando", tone: "busy" },
      { name: "Hablantes", state: "con error", tone: "error" },
      { name: "Resúmenes", state: "esperando modelo", tone: "waiting" },
      { name: "Base de datos", state: "en marcha", tone: "ok" },
      { name: "Procesamiento", state: "detenido", tone: "off" },
      { name: "Modelos", state: "esperando un componente", tone: "waiting" },
    ]);
    expect(view.web).toEqual({ label: "Servicio web", value: "http://localhost:41750", state: "en marcha", tone: "ok" });
  });

  it("is translated to English", () => {
    const view = aboutView("en", INPUT);
    expect(view.lang).toBe("en");
    expect(view.title).toBe("About Sauri");
    expect(view.services.items.map((item) => `${item.name}: ${item.state}`)).toEqual([
      "Transcription: starting",
      "Speakers: error",
      "Summaries: waiting for a model",
      "Database: running",
      "Processing: stopped",
      "Models: waiting for a component",
    ]);
    expect(view.details).toEqual([
      { label: "Active for", value: "2 h 34 min" },
      { label: "Electron version", value: "44.10.2" },
      { label: "System", value: "macOS 26.1 · Apple silicon" },
    ]);
  });

  it("shows the details in Spanish", () => {
    expect(aboutView("es", INPUT).details).toEqual([
      { label: "Activo hace", value: "2 h 34 min" },
      { label: "Versión de Electron", value: "44.10.2" },
      { label: "Sistema", value: "macOS 26.1 · Apple silicon" },
    ]);
  });

  it("says the web service is starting while the API is on its first start, and stopped without it", () => {
    const starting: ServiceSummary[] = [{ name: "api", state: "starting", failed: false }];
    expect(aboutView("es", { ...INPUT, summary: starting }).web).toMatchObject({ state: "iniciando", tone: "busy" });
    expect(aboutView("es", { ...INPUT, summary: [] }).web).toMatchObject({ state: "detenido", tone: "off" });
    const failed: ServiceSummary[] = [{ name: "api", state: "restarting", failed: true }];
    expect(aboutView("en", { ...INPUT, summary: failed }).web).toMatchObject({ state: "error", tone: "error" });
  });

  it("has an empty list (with its own text) before any service exists, and keeps unknown services by name", () => {
    const view = aboutView("es", { ...INPUT, summary: [] });
    expect(view.services.items).toEqual([]);
    expect(view.services.empty).toBe("Aún no hay servicios iniciados");
    const other = aboutView("en", { ...INPUT, summary: [{ name: "new-engine", state: "ready", failed: false }] });
    expect(other.services.items).toEqual([{ name: "new-engine", state: "running", tone: "ok" }]);
  });

  it("links to the public repository", () => {
    const view = aboutView("en", INPUT);
    expect(view.repository.url).toBe("https://github.com/lufermalgo/sauri");
    expect(view.repository.text).toBe("github.com/lufermalgo/sauri");
    expect(isRepositoryUrl(view.repository.url)).toBe(true);
  });
});

describe("formatUptime", () => {
  it("counts minutes with the right plural, then hours and days", () => {
    expect(formatUptime("es", 0)).toBe("menos de un minuto");
    expect(formatUptime("es", 59_999)).toBe("menos de un minuto");
    expect(formatUptime("es", MINUTE)).toBe("1 minuto");
    expect(formatUptime("es", 12 * MINUTE)).toBe("12 minutos");
    expect(formatUptime("es", HOUR)).toBe("1 h");
    expect(formatUptime("es", 2 * HOUR + 5 * MINUTE)).toBe("2 h 5 min");
    expect(formatUptime("es", DAY)).toBe("1 día");
    expect(formatUptime("es", 3 * DAY + 4 * HOUR + 59 * MINUTE)).toBe("3 días 4 h");
    expect(formatUptime("en", 30_000)).toBe("less than a minute");
    expect(formatUptime("en", MINUTE)).toBe("1 minute");
    expect(formatUptime("en", 45 * MINUTE)).toBe("45 minutes");
    expect(formatUptime("en", DAY + 2 * HOUR)).toBe("1 day 2 h");
    expect(formatUptime("en", 2 * DAY)).toBe("2 days");
  });

  it("never shows a negative time", () => {
    expect(formatUptime("en", -5 * MINUTE)).toBe("less than a minute");
  });
});

describe("isRepositoryUrl", () => {
  it("accepts only the public repository over https", () => {
    expect(isRepositoryUrl(REPOSITORY_URL)).toBe(true);
    expect(isRepositoryUrl(`${REPOSITORY_URL}/`)).toBe(true);
    for (const url of [
      "http://github.com/lufermalgo/sauri",
      "https://github.com/lufermalgo/sauri/issues",
      "https://github.com/lufermalgo/sauri-app",
      "https://github.com.evil.example/lufermalgo/sauri",
      "https://evil.example/https://github.com/lufermalgo/sauri",
      "https://user:pass@github.com/lufermalgo/sauri",
      "https://github.com:8443/lufermalgo/sauri",
      "https://github.com/lufermalgo/sauri?x=1",
      "https://github.com/lufermalgo/sauri#readme",
      "file:///etc/passwd",
      "javascript:alert(1)",
      "not a url",
      "",
    ]) {
      expect(isRepositoryUrl(url), url).toBe(false);
    }
  });
});

describe("about texts", () => {
  it("has the same keys in Spanish and English, none of them empty", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
    for (const [key, value] of [...Object.entries(es), ...Object.entries(en)]) expect(value.trim(), key).not.toBe("");
  });

  it("uses the same placeholders in both languages", () => {
    const vars = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
    for (const key of Object.keys(es) as (keyof typeof es)[]) expect(vars(en[key]), key).toEqual(vars(es[key]));
  });
});

describe("about window files", () => {
  it("draws the same isotype as brand/sauri-isotype.svg", () => {
    const shapes = (file: string) =>
      [...fs.readFileSync(file, "utf8").matchAll(/<(polygon|rect)\b[^>]*>/g)].map((match) => {
        const tag = match[0];
        const attr = (name: string) => tag.match(new RegExp(`\\s${name}="([^"]*)"`))?.[1] ?? "";
        return { fill: attr("fill").toUpperCase(), points: attr("points"), rx: attr("rx"), width: attr("width") };
      });
    expect(shapes(path.join(desktop, "src/about/index.html"))).toEqual(
      shapes(path.join(desktop, "..", "brand", "sauri-isotype.svg")),
    );
  });

  it("allows no remote content, inline script or style in the page", () => {
    const html = fs.readFileSync(path.join(desktop, "src/about/index.html"), "utf8");
    const csp = html.match(/http-equiv="Content-Security-Policy"\s+content="([^"]+)"/)?.[1] ?? "";
    expect(csp).toContain("default-src 'none'");
    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain("connect-src 'none'");
    expect(csp).not.toMatch(/unsafe|https?:/);
    expect(html).not.toMatch(/<script>|\son\w+=|style="/);
  });

  it("turns the animation off when the person asks for reduced motion", () => {
    const css = fs.readFileSync(path.join(desktop, "src/about/about.css"), "utf8");
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/\.half,\s*\.spark,\s*\.dot--busy\s*\{\s*animation: none;/);
    expect(reduced).toMatch(/\.ring\s*\{\s*display: none;/);
  });
});
