import { describe, expect, it } from "vitest";

import { findPassageAt } from "./PlaybackController";
import type { TimedPassage } from "./PlaybackController";

function passage(
  id: string,
  startMs: number,
  endMs: number,
): TimedPassage {
  return { id, startMs, endMs, text: `Synthetic passage ${id}` };
}

describe("findPassageAt", () => {
  it("matches valid half-open intervals, including adjacent boundaries", () => {
    const passages = [passage("first", 0, 1000), passage("second", 1000, 2000)];

    expect(findPassageAt(passages, 0)?.id).toBe("first");
    expect(findPassageAt(passages, 999)?.id).toBe("first");
    expect(findPassageAt(passages, 1000)?.id).toBe("second");
    expect(findPassageAt(passages, 2000)).toBeNull();
  });

  it("returns the first matching passage in supplied order when intervals overlap", () => {
    const passages = [passage("later-start", 500, 1500), passage("earlier-start", 0, 1000)];

    expect(findPassageAt(passages, 750)?.id).toBe("later-start");
    expect(passages.map(({ id }) => id)).toEqual(["later-start", "earlier-start"]);
  });

  it("returns no passage for gaps, empty input, or invalid intervals", () => {
    expect(findPassageAt([passage("before", 0, 100), passage("after", 200, 300)], 150)).toBeNull();
    expect(findPassageAt([], 0)).toBeNull();
    expect(
      findPassageAt(
        [
          passage("zero-length", 100, 100),
          passage("reversed", 200, 100),
          passage("not-finite", Number.NaN, 300),
        ],
        150,
      ),
    ).toBeNull();
  });
});
