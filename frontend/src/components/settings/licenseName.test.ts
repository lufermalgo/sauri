import { describe, expect, it } from "vitest";
import { licenseName } from "./licenseName";

describe("licenseName", () => {
  it("writes the identifiers of the catalog and of Hugging Face as people write them", () => {
    expect(licenseName("mit")).toBe("MIT");
    expect(licenseName("MIT")).toBe("MIT");
    expect(licenseName("apache-2.0")).toBe("Apache 2.0");
    expect(licenseName("Apache-2.0")).toBe("Apache 2.0");
    expect(licenseName("CC-BY-4.0")).toBe("CC BY 4.0");
    expect(licenseName("cc-by-nc-sa-4.0")).toBe("CC BY-NC-SA 4.0");
    expect(licenseName("cc0-1.0")).toBe("CC0 1.0");
    expect(licenseName("bsd-3-clause")).toBe("BSD 3-Clause");
    expect(licenseName("gpl-3.0")).toBe("GPL 3.0");
    expect(licenseName("LGPL-2.1-or-later")).toBe("LGPL 2.1+");
    expect(licenseName("llama3.1")).toBe("Llama 3.1 Community License");
    expect(licenseName("gemma")).toBe("Gemma Terms of Use");
  });

  it("shows any other identifier as it came instead of guessing", () => {
    expect(licenseName("other")).toBe("other");
    expect(licenseName("qwen-research")).toBe("qwen-research");
    expect(licenseName("cc-by-4")).toBe("cc-by-4");
  });
});
