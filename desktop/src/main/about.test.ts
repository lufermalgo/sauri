import { describe, expect, it } from "vitest";
import { aboutPanel } from "./about.ts";
import type { ServiceSummary } from "./services.ts";

const URL = "http://localhost:8000/";
const IDLE = { starting: false, problem: false };

const SUMMARY: ServiceSummary[] = [
  { name: "postgres", state: "ready", failed: false },
  { name: "api", state: "ready", failed: false },
  { name: "asr-engine", state: "starting", failed: false },
  { name: "diar-engine", state: "restarting", failed: true },
  { name: "worker", state: "stopped", failed: false },
  { name: "llm-engine", blocked: "models_missing" },
  { name: "host-engine", blocked: "component_missing" },
];

describe("aboutPanel", () => {
  it("names the app, its version and the year", () => {
    const panel = aboutPanel("es", { version: "0.1.4", year: 2026, portalUrl: URL, summary: [], status: IDLE });
    expect(panel.applicationName).toBe("Sauri");
    expect(panel.applicationVersion).toBe("0.1.4");
    expect(panel.copyright).toBe("© 2026 Sauri");
  });

  it("lists the portal address and one line per service, in Spanish", () => {
    const panel = aboutPanel("es", { version: "0.1.4", year: 2026, portalUrl: URL, summary: SUMMARY, status: IDLE });
    expect(panel.credits.split("\n")).toEqual([
      `Portal: ${URL} (en marcha)`,
      "",
      "Servicios:",
      "postgres: en marcha",
      "api: en marcha",
      "asr-engine: arrancando",
      "diar-engine: falló",
      "worker: detenido",
      "llm-engine: esperando modelo",
      "host-engine: esperando un componente",
    ]);
  });

  it("is translated to English", () => {
    const panel = aboutPanel("en", { version: "0.1.4", year: 2026, portalUrl: URL, summary: SUMMARY, status: IDLE });
    expect(panel.credits).toContain(`Portal: ${URL} (running)`);
    expect(panel.credits).toContain("diar-engine: failed");
    expect(panel.credits).toContain("llm-engine: waiting for a model");
  });

  it("says the portal is starting while the API is on its first start, and stopped without it", () => {
    const starting: ServiceSummary[] = [{ name: "api", state: "starting", failed: false }];
    const status = { starting: true, problem: false };
    const input = { version: "0.1.4", year: 2026, portalUrl: URL };
    expect(aboutPanel("es", { ...input, summary: starting, status }).credits).toMatch(/^Portal: .+ \(arrancando\)$/m);
    expect(aboutPanel("es", { ...input, summary: [], status: IDLE }).credits).toBe(`Portal: ${URL} (detenido)`);
  });
});
