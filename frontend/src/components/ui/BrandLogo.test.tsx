// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BrandLogo, BrandWordmark, WORDMARK_PATH } from "./BrandLogo";

function brandFile(name: string) {
  return readFileSync(resolve(process.cwd(), "..", "brand", name), "utf8");
}

describe("brand artwork stays canonical", () => {
  it.each([
    ["sauri-logo.svg", "#2f5a3c"],
    ["sauri-logo-dark.svg", "#faf6f0"],
  ])("%s is outlined (no live text) and its word matches the component's path", (file, wordColor) => {
    const svg = brandFile(file);
    expect(svg).not.toMatch(/<text|font-family/);
    const path = svg.match(/<path fill="([^"]+)" d="([^"]+)"/)!;
    expect(path[1]).toBe(wordColor);
    expect(path[2]).toBe(WORDMARK_PATH);
  });
});

describe("BrandLogo and BrandWordmark", () => {
  it("expose the accessible name when given a title, and are decorative otherwise", () => {
    const named = render(<BrandLogo title="Sauri" />);
    expect(named.getByRole("img", { name: "Sauri" })).toBeTruthy();
    named.unmount();
    const decorative = render(<><BrandLogo /><BrandWordmark /></>);
    for (const svg of decorative.container.querySelectorAll("svg")) {
      expect(svg.getAttribute("aria-hidden")).toBe("true");
      expect(svg.getAttribute("role")).toBeNull();
    }
  });

  it("draw the isotype and the word of the official logo, with the word following the theme", () => {
    const { container } = render(<BrandLogo height={50} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 317.18 100");
    expect(svg.getAttribute("height")).toBe("50");
    expect(Number(svg.getAttribute("width"))).toBeCloseTo(158.59, 2);
    expect(svg.querySelector('polygon[fill="#4a7c59"]')).toBeTruthy();
    expect(svg.querySelector('polygon[fill="#78a886"]')).toBeTruthy();
    expect(svg.querySelector("path.ui-brand-word")!.getAttribute("d")).toBe(WORDMARK_PATH);
    expect(svg.querySelector("text")).toBeNull();
  });

  it("draws the word alone with a width that follows its proportions", () => {
    const { container } = render(<BrandWordmark height={20} />);
    const svg = container.querySelector("svg")!;
    expect(svg.querySelector("polygon")).toBeNull();
    expect(svg.querySelector("path.ui-brand-word")!.getAttribute("d")).toBe(WORDMARK_PATH);
    expect(Number(svg.getAttribute("width"))).toBeCloseTo(20 * (195.18 / 60.16), 2);
  });

  it("gives each logo its own clip path id", () => {
    const { container } = render(<><BrandLogo /><BrandLogo /></>);
    const ids = [...container.querySelectorAll("clipPath")].map((node) => node.id);
    expect(new Set(ids).size).toBe(2);
  });
});
