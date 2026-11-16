import { afterEach, describe, expect, it } from "vitest";
import { showNotice } from "./recording";

describe("Meet overlay design tokens", () => {
  afterEach(() => {
    document.getElementById("sauri-consent-banner-host")?.remove();
  });

  it("resolves the shared tokens inside the shadow root and follows the system theme", () => {
    expect(showNotice()).toBe(true);
    const host = document.getElementById("sauri-consent-banner-host")!;
    const css = host.shadowRoot!.querySelector("style")!.textContent!;

    // Same token file as the extension pages, applied through :host.
    expect(css).toMatch(/:root,\s*:host\s*{/);
    expect(css).toContain("--ds-bg: light-dark(#faf6f0, #181b19)");
    expect(css).toMatch(/:host\s*{\s*all:\s*initial;\s*color-scheme:\s*light dark/);
    // Inline style on the host would otherwise reset color-scheme to normal and pin the light theme.
    expect(host.style.cssText).toMatch(/color-scheme:\s*light dark/);
    // No literal colors in the overlay rules.
    const rules = css.slice(css.indexOf(":host { all: initial"));
    expect(rules).not.toMatch(/#[0-9a-fA-F]{3,8}\b|\brgba?\(/);
  });
});
