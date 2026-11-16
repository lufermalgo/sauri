// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render } from "@testing-library/react";
import type { EngineProviderKind } from "@sauri/shared-types";
import { PROVIDER_LOGO_PATHS } from "../assets/providers/logos";
import { es } from "../locales/es";
import { ProviderLogo } from "./settings/ProviderLogo";
import { t } from "../i18n";

afterEach(cleanup);

describe("ProviderLogo", () => {
  it("draws the single-color mark with currentColor and hides it from assistive technology", () => {
    const { container } = render(<ProviderLogo kind="anthropic" name="Anthropic" />);
    const mark = container.firstElementChild!;
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark).toHaveClass("engines-logo--md");
    expect(container.querySelector("path")).toHaveAttribute("fill", "currentColor");
    expect(container.querySelector("path")).toHaveAttribute("d", PROVIDER_LOGO_PATHS.anthropic);
    expect(container).not.toHaveTextContent(/\S/);
  });

  it("falls back to a monogram when the provider has no mark", () => {
    const { container } = render(<ProviderLogo kind="openai" name="OpenAI" size="sm" />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.firstElementChild).toHaveClass("engines-logo--sm");
    expect(container).toHaveTextContent("O");
    const compatible = render(<ProviderLogo kind="openai_compatible" name={t("engines:kinds.openai_compatible.label")} />);
    expect(compatible.container).toHaveTextContent("SC");
  });

  it("only knows marks for kinds the API can link, and no mark carries a literal color", () => {
    const kinds = Object.keys(es.engines.kinds) as EngineProviderKind[];
    for (const key of Object.keys(PROVIDER_LOGO_PATHS)) expect(kinds).toContain(key);
    for (const path of Object.values(PROVIDER_LOGO_PATHS)) expect(path).toMatch(/^[MmLlHhVvCcSsQqTtAaZz0-9\s.,-]+$/);
  });
});
