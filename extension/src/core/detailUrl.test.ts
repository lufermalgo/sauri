// Feature: chrome-side-panel, Property 19: meeting_id round-trip in the Detail View URL

import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { buildDetailUrl, readMeetingId } from "./detailUrl";

describe("buildDetailUrl / readMeetingId", () => {
  it("Property 19: round-trip preserves the exact meeting_id (Req. 6.2)", () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 40 }).filter((s) => s.trim().length > 0),
        (meetingId) => {
          const url = buildDetailUrl(meetingId);
          const read = readMeetingId(url);
          expect(read).toBe(meetingId);
        }
      ),
      { numRuns: 100 }
    );
  });

  it("readMeetingId returns null when there's no parameter", () => {
    expect(readMeetingId("detail.html")).toBeNull();
  });
});
