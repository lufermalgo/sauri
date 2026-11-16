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

describe("manifest.json — recording any browser tab with least privilege", () => {
  it("describes a generic tab recorder, not a Meet-only tool", () => {
    expect(manifest.description).toMatch(/cualquier pesta/);
    expect(manifest.description).not.toMatch(/meet/i);
    expect(manifest.action.default_title).not.toMatch(/meet/i);
  });

  it("adds no host permission: only Meet (static script) and the local backend", () => {
    expect(manifest.host_permissions).toEqual(["https://meet.google.com/*", "http://localhost:8000/*"]);
    expect(manifest.optional_host_permissions).toBeUndefined();
    expect(manifest.permissions).not.toContain("<all_urls>");
  });

  it("keeps the static content script on Meet only and injects other tabs on demand", () => {
    expect(manifest.content_scripts).toEqual([{ matches: ["https://meet.google.com/*"], js: ["src/content.ts"] }]);
    // On-demand injection into the recorded tab relies on these two, granted by the user's gesture.
    expect(manifest.permissions).toEqual(expect.arrayContaining(["scripting", "activeTab", "tabs"]));
  });
});

describe("manifest.json — minimal exposure to web pages", () => {
  it("declares no new permissions (only the ones the recorder already needs)", () => {
    expect([...manifest.permissions].sort()).toEqual(
      ["activeTab", "alarms", "notifications", "offscreen", "scripting", "sidePanel", "storage", "tabCapture", "tabs"],
    );
  });

  it("declares no web_accessible_resources: extension pages are opened by the extension itself", () => {
    // The detail page is never fetched by a website, and the overlay is injected with
    // chrome.scripting.executeScript({ files }), which needs no web-accessible entry. CRXJS adds
    // the Meet content script chunks it needs at build time (see build/minimal-war.ts).
    expect(manifest.web_accessible_resources).toBeUndefined();
  });
});

describe("manifest.json — brand icons", () => {
  const SIZES = ["16", "32", "48", "128"];

  it("declares the isotype at 16, 32, 48 and 128 px for the extension and the toolbar action", () => {
    expect(Object.keys(manifest.icons).sort()).toEqual([...SIZES].sort());
    expect(manifest.action.default_icon).toEqual(manifest.icons);
  });

  it.each(SIZES)("ships a %s px PNG with the declared size", (size) => {
    const file = path.resolve(__dirname, "..", "public", manifest.icons[size]);
    const png = fs.readFileSync(file);
    expect(png.subarray(1, 4).toString()).toBe("PNG");
    expect(png.readUInt32BE(16)).toBe(Number(size));
    expect(png.readUInt32BE(20)).toBe(Number(size));
  });
});

describe("manifest.json — brand name", () => {
  it("writes the product name as «Sauri» in the name and the toolbar title (never lowercase)", () => {
    expect(manifest.name).toBe("Sauri");
    expect(manifest.action.default_title).toMatch(/^Sauri\b/);
    expect(manifest.action.default_title).not.toMatch(/\bsauri\b/);
  });

  it("uses «Sauri» in the title of every extension page", () => {
    for (const page of ["panel", "options", "detail"]) {
      const html = fs.readFileSync(path.resolve(__dirname, page, "index.html"), "utf-8");
      expect(html).toMatch(/<title>Sauri\b/);
    }
  });
});
