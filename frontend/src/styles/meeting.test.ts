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

describe("speaker dock row density", () => {
  it("lays each row out on a three-column grid with the avatar at the DS 28px size", () => {
    expect(rule(".meeting-review-item")).toMatch(/grid-template-columns:\s*28px minmax\(0, 1fr\) auto/);
  });

  it("keeps the row compact and leaves the 44px target to coarse pointers (the control tokens grow there)", () => {
    expect(rule(".meeting-review-item")).toMatch(/padding:\s*var\(--ds-space-1\) var\(--ds-space-3\)/);
    expect(rule(".meeting-review-item")).not.toMatch(/min-height/);
    expect(rule(".meeting-review-name")).toMatch(/font-size:\s*var\(--ds-text-md\)/);
    expect(rule(".meeting-review-chip")).toMatch(/min-height:\s*24px/);
  });

  it("truncates a long name on one line", () => {
    const name = rule(".meeting-review-name");
    expect(name).toMatch(/text-overflow:\s*ellipsis/);
    expect(name).toMatch(/white-space:\s*nowrap/);
  });
});
