// Integration test: manifest migration to chrome.sidePanel (Req. 1.1, 1.2, 1.7)
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const manifest = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../manifest.json"), "utf-8")
);

describe("manifest.json — migration to chrome.sidePanel (Req. 1.2)", () => {
  it("declares the 'sidePanel' permission", () => {
    expect(manifest.permissions).toContain("sidePanel");
  });

  it("declares side_panel.default_path", () => {
    expect(manifest.side_panel).toBeDefined();
    expect(typeof manifest.side_panel.default_path).toBe("string");
    expect(manifest.side_panel.default_path.length).toBeGreaterThan(0);
  });

  it("does not declare action.default_popup (the popup is replaced by the Side_Panel)", () => {
    expect(manifest.action?.default_popup).toBeUndefined();
  });

  it("declares options_page (microphone permission in a full tab, not the side panel)", () => {
    expect(typeof manifest.options_page).toBe("string");
    expect(manifest.options_page.length).toBeGreaterThan(0);
  });
});
