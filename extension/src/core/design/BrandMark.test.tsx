import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BrandMark, BRAND_SHAPES } from "./BrandMark";

const MASTER_DARK = "-10,-10 108.3,-10 54.4,43.9 50,39.5 39.5,50 43.9,54.4 -10,108.3";
const SMALL_DARK = "-10,-10 105.76,-10 54.88,40.88 50,36 36,50 40.88,54.88 -10,105.76";

function darkPoints(container: HTMLElement) {
  return container.querySelector('polygon[fill="#9A8CE0"]')?.getAttribute("points");
}

describe("BrandMark", () => {
  it("is decorative (hidden from assistive tech) when no title is given", () => {
    const { container } = render(<BrandMark />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.getAttribute("role")).toBeNull();
  });

  it("exposes its accessible name when a title is given", () => {
    const { getByRole } = render(<BrandMark title="Sauri" />);
    expect(getByRole("img", { name: "Sauri" })).toBeTruthy();
  });

  it("uses the master drawing above 32 px and the small variant at 32 px or less", () => {
    expect(darkPoints(render(<BrandMark size={33} />).container)).toBe(MASTER_DARK);
    expect(darkPoints(render(<BrandMark size={32} />).container)).toBe(SMALL_DARK);
    expect(darkPoints(render(<BrandMark size={16} />).container)).toBe(SMALL_DARK);
  });

  it("keeps the two lavender halves and the volt diamond, and gives every instance its own clip path id", () => {
    const { container } = render(<><BrandMark /><BrandMark /></>);
    expect(container.querySelectorAll('polygon[fill="#6A5ACD"]')).toHaveLength(2);
    expect(container.querySelectorAll('polygon[fill="#C6FF24"]')).toHaveLength(2);
    const ids = [...container.querySelectorAll("clipPath")].map((node) => node.id);
    expect(new Set(ids).size).toBe(2);
    for (const svg of container.querySelectorAll("svg")) {
      const clip = svg.querySelector("g")!.getAttribute("clip-path");
      expect(ids).toContain(clip!.slice(5, -1));
    }
  });
});

describe("BrandMark geometry stays canonical", () => {
  it.each([
    ["sauri-isotype.svg", "master"],
    ["sauri-isotype-small.svg", "small"],
  ] as const)("%s draws the same colors and polygons as the %s shapes", (file, key) => {
    const svg = readFileSync(resolve(process.cwd(), "..", "brand", file), "utf8");
    const polygons = [...svg.matchAll(/<polygon fill="([^"]+)" points="([^"]+)"/g)].map((m) => [m[1], m[2]]);
    const shape = BRAND_SHAPES[key];
    expect(polygons).toEqual([
      ["#9A8CE0", shape.second],
      ["#6A5ACD", shape.main],
      ["#C6FF24", shape.spark],
    ]);
  });
});
