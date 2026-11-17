// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BrandMark } from "./BrandMark";

const MASTER_DARK = "-10,-10 108.3,-10 54.4,43.9 50,39.5 39.5,50 43.9,54.4 -10,108.3";
const SMALL_DARK = "-10,-10 105.76,-10 54.88,40.88 50,36 36,50 40.88,54.88 -10,105.76";

function darkPoints(container: HTMLElement) {
  return container.querySelector('polygon[fill="#A59837"]')?.getAttribute("points");
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

  it("keeps the two brand greens and gives every instance its own clip path id", () => {
    const { container } = render(<><BrandMark /><BrandMark /></>);
    expect(container.querySelectorAll('polygon[fill="#CFBB23"]')).toHaveLength(2);
    const ids = [...container.querySelectorAll("clipPath")].map((node) => node.id);
    expect(new Set(ids).size).toBe(2);
    for (const svg of container.querySelectorAll("svg")) {
      const clip = svg.querySelector("g")!.getAttribute("clip-path");
      expect(ids).toContain(clip!.slice(5, -1));
    }
  });
});
