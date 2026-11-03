import { describe, expect, it } from "vitest";
import { MeetingOrigin, ProcessState } from "./index";

describe("shared meeting types", () => {
  it("exposes synthetic contract enum values to package tests", () => {
    expect(ProcessState.Queued).toBe("queued");
    expect(MeetingOrigin.Manual).toBe("manual");
  });
});
