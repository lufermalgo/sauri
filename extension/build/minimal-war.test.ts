import { describe, expect, it } from "vitest";
import { EXTENSION_INJECTED_FILES, minimizeWebAccessibleResources } from "./minimal-war";

const meetEntry = { matches: ["https://meet.google.com/*"], resources: ["assets/content.js"], use_dynamic_url: false };
const overlayEntry = { matches: ["http://*/*", "https://*/*"], resources: ["src/overlay/entry.js"], use_dynamic_url: false };

describe("minimizeWebAccessibleResources", () => {
  it("removes the extension-injected overlay and keeps the Meet entry untouched", () => {
    const result = minimizeWebAccessibleResources({ name: "x", web_accessible_resources: [meetEntry, overlayEntry] });
    expect(result.web_accessible_resources).toEqual([meetEntry]);
    expect(result.name).toBe("x");
  });

  it("drops the whole field when nothing remains", () => {
    expect(minimizeWebAccessibleResources({ web_accessible_resources: [overlayEntry] })).not.toHaveProperty("web_accessible_resources");
  });

  it("keeps other resources of a mixed entry", () => {
    const mixed = { matches: ["https://meet.google.com/*"], resources: ["src/overlay/entry.js", "assets/a.js"] };
    expect(minimizeWebAccessibleResources({ web_accessible_resources: [mixed] }).web_accessible_resources).toEqual([
      { matches: ["https://meet.google.com/*"], resources: ["assets/a.js"] },
    ]);
  });

  it.each(["<all_urls>", "*://*/*", "http://*/*", "https://*/*"])("fails the build if something stays exposed to %s", (match) => {
    expect(() => minimizeWebAccessibleResources({ web_accessible_resources: [{ matches: [match], resources: ["src/detail/index.html"] }] })).toThrow(/every website/);
  });

  it("injects only the overlay entry by service worker", () => {
    expect(EXTENSION_INJECTED_FILES).toEqual(["src/overlay/entry.js"]);
  });
});
