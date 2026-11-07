import { describe, expect, it } from "vitest";
import viteConfig from "../vite.config";

describe("Vitest file discovery", () => {
  it("excludes Playwright E2E specs", () => {
    expect(viteConfig.test?.exclude).toContain("tests/e2e/**");
  });
});
