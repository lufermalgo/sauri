import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "meeting.css"), "utf8");

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? "";
}

describe("meeting transcript layout contract", () => {
  const widthCaps = /(?:^|[\s;])(?:max-width|max-inline-size)\s*:/;

  it.each([
    ".meeting-turns",
    ".meeting-turn",
    ".meeting-turn-action",
    ".meeting-turn-meta",
    ".meeting-turn-text",
    ".meeting-transcript",
    ".meeting-transcript-body",
  ])("does not cap the width of %s", (selector) => {
    expect(rule(selector)).not.toBe("");
    expect(rule(selector)).not.toMatch(widthCaps);
  });

  it("lets the turn text fill its column and wrap long strings", () => {
    const text = rule(".meeting-turn-text");
    expect(text).toMatch(/width:\s*100%/);
    expect(text).toMatch(/overflow-wrap:\s*anywhere/);
    expect(css).not.toMatch(/\d+ch\b/);
  });
});
