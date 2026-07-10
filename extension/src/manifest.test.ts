// Prueba de integración: migración del manifiesto a chrome.sidePanel (Req. 1.1, 1.2, 1.7)
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const manifest = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../manifest.json"), "utf-8")
);

describe("manifest.json — migración a chrome.sidePanel (Req. 1.2)", () => {
  it("declara el permiso 'sidePanel'", () => {
    expect(manifest.permissions).toContain("sidePanel");
  });

  it("declara side_panel.default_path", () => {
    expect(manifest.side_panel).toBeDefined();
    expect(typeof manifest.side_panel.default_path).toBe("string");
    expect(manifest.side_panel.default_path.length).toBeGreaterThan(0);
  });

  it("no declara action.default_popup (el popup se reemplaza por el Side_Panel)", () => {
    expect(manifest.action?.default_popup).toBeUndefined();
  });
});
