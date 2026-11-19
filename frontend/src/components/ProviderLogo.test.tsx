// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render } from "@testing-library/react";
import type { EngineProviderKind } from "@sauri/shared-types";
import { PROVIDER_LOGOS } from "../assets/providers/logos";
import { es } from "../locales/es";
import { ProviderLogo } from "./settings/ProviderLogo";

afterEach(cleanup);

const KINDS = Object.keys(es.engines.kinds) as EngineProviderKind[];
const mark = (kind: EngineProviderKind) => {
  const source = PROVIDER_LOGOS[kind];
  return "mark" in source ? source.mark : null;
};

describe("ProviderLogo", () => {
  it("draws the single-color mark with currentColor and hides it from assistive technology", () => {
    const { container } = render(<ProviderLogo kind="anthropic" name="Anthropic" />);
    const logo = container.firstElementChild!;
    expect(logo).toHaveAttribute("aria-hidden", "true");
    expect(logo).toHaveClass("engines-logo--md");
    expect(container.querySelector("path")).toHaveAttribute("fill", "currentColor");
    expect(container.querySelector("path")).toHaveAttribute("d", mark("anthropic"));
    expect(container).not.toHaveTextContent(/\S/);
  });

  it("draws a neutral glyph in currentColor where no mark can be used", () => {
    const { container } = render(<ProviderLogo kind="openai_compatible" name="Server" size="sm" />);
    const logo = container.firstElementChild!;
    expect(logo).toHaveClass("engines-logo--sm");
    expect(logo).toHaveAttribute("aria-hidden", "true");
    const glyph = container.querySelector("svg.engines-logo-glyph")!;
    expect(glyph).toHaveAttribute("stroke", "currentColor");
    expect(container).not.toHaveTextContent(/\S/);
  });

  it.each(KINDS)("gives %s a mark or a glyph, never letters", (kind) => {
    const { container } = render(<ProviderLogo kind={kind} name={es.engines.kinds[kind].label} />);
    expect(container.querySelector(".engines-logo svg")).not.toBeNull();
    expect(container).not.toHaveTextContent(/\S/);
  });

  it("knows a logo for exactly the kinds the portal can name, and no mark carries a literal color", () => {
    expect(Object.keys(PROVIDER_LOGOS).sort()).toEqual([...KINDS].sort());
    for (const kind of KINDS) {
      const path = mark(kind);
      if (path !== null) expect(path).toMatch(/^[MmLlHhVvCcSsQqTtAaZz0-9\s.,-]+$/);
    }
  });

  it("uses the real marks only where simple-icons has them, and glyphs for the rest", () => {
    const glyphs = KINDS.filter((kind) => mark(kind) === null).sort();
    expect(glyphs).toEqual(["assemblyai", "chatgpt_plan", "groq", "openai", "openai_compatible"]);
  });
});
