import { describe, expect, it } from "vitest";
import {
  MAX_LISTEN_MS,
  MAX_PAUSE_MS,
  SHORT_INTERVAL_MS,
  selectListeningInterval,
} from "./speaker-review-interval";
import type { IntervalTurn } from "./speaker-review-interval";

const turn = (speakerId: string | null, startMs: number, endMs: number, hasAmbiguous = false): IntervalTurn =>
  ({ speakerId, startMs, endMs, hasAmbiguous });

describe("selectListeningInterval — examples", () => {
  it.each<[string, IntervalTurn[], ReturnType<typeof selectListeningInterval>]>([
    ["returns null when the speaker has no turns", [turn("B", 0, 4000)], null],
    ["returns null when every turn of the speaker is ambiguous", [turn("A", 0, 9000, true)], null],
    ["returns null for zero-length or invalid timings", [turn("A", 10, 10), turn("A", -5, 100), turn("A", 300, 200)], null],
    ["prefers the longest stretch and caps it at 20 s",
      [turn("A", 0, 1000), turn("B", 1000, 2000), turn("A", 2000, 32000)],
      { startMs: 2000, endMs: 22000, short: false }],
    ["joins pauses up to 250 ms", [turn("A", 0, 3000), turn("A", 3250, 6000)], { startMs: 0, endMs: 6000, short: false }],
    ["does not join pauses over 250 ms", [turn("A", 0, 3000), turn("A", 3251, 4000)], { startMs: 0, endMs: 3000, short: true }],
    ["cuts at another speaker inside a short pause",
      [turn("A", 0, 3000), turn("B", 3000, 3100), turn("A", 3100, 6000)],
      { startMs: 0, endMs: 3000, short: true }],
    ["skips ambiguous turns and cuts the stretch there",
      [turn("A", 0, 3000), turn("A", 3000, 3200, true), turn("A", 3200, 9000)],
      { startMs: 3200, endMs: 9000, short: false }],
    ["cuts at turns without a speaker",
      [turn("A", 0, 2000), turn(null, 2000, 2100), turn("A", 2100, 4000)],
      { startMs: 0, endMs: 2000, short: true }],
    ["removes the part that overlaps another speaker",
      [turn("A", 0, 3000), turn("B", 2500, 4000), turn("A", 3900, 5700)],
      { startMs: 0, endMs: 2500, short: true }],
    ["does not cross a long foreign turn spanning several of the speaker's turns",
      [turn("B", 0, 4500), turn("A", 1000, 2000), turn("A", 2200, 5200)],
      { startMs: 4500, endMs: 5200, short: true }],
    ["chooses the earliest stretch on ties",
      [turn("A", 0, 6000), turn("B", 6000, 7000), turn("A", 7000, 13000)],
      { startMs: 0, endMs: 6000, short: false }],
    ["marks exactly 5 s as not short", [turn("A", 1000, 6000)], { startMs: 1000, endMs: 6000, short: false }],
    ["marks under 5 s as short", [turn("A", 1000, 5999)], { startMs: 1000, endMs: 5999, short: true }],
    ["is independent of input order",
      [turn("A", 3100, 6000), turn("B", 6000, 7000), turn("A", 0, 3000)],
      { startMs: 0, endMs: 6000, short: false }],
  ])("%s", (_name, turns, expected) => {
    expect(selectListeningInterval(turns, "A")).toEqual(expected);
  });
});

// Seeded generator: fast-check is not a frontend devDependency, so Property 13 is checked
// over a reproducible stream of random turn lists instead.
function generator(seed: number) {
  let state = seed >>> 0;
  return (max: number) => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state % max;
  };
}

function randomTurns(next: (max: number) => number): IntervalTurn[] {
  const speakers = ["A", "B", "C", null];
  const turns: IntervalTurn[] = [];
  let cursor = next(1000);
  for (let index = next(14); index > 0; index -= 1) {
    // Mostly sequential turns with small pauses, some overlaps and some long turns.
    const startMs = Math.max(0, cursor + next(700) - 200);
    const endMs = startMs + (next(5) === 0 ? next(30000) : next(4000));
    turns.push(turn(speakers[next(speakers.length)], startMs, endMs, next(6) === 0));
    cursor = endMs;
  }
  return turns;
}

const overlaps = (a: { startMs: number; endMs: number }, b: { startMs: number; endMs: number }) =>
  a.startMs < b.endMs && b.startMs < a.endMs;

describe("selectListeningInterval — Property 13", () => {
  it("stays inside the speaker's turns, never crosses another speaker and honours the limits", () => {
    for (let seed = 1; seed <= 2000; seed += 1) {
      const turns = randomTurns(generator(seed));
      const result = selectListeningInterval(turns, "A");
      const own = turns.filter((item) => item.speakerId === "A" && !item.hasAmbiguous && item.endMs > item.startMs);
      const others = turns.filter((item) => !own.includes(item) && item.endMs > item.startMs);
      const context = `seed ${seed}: ${JSON.stringify(turns)} -> ${JSON.stringify(result)}`;

      if (!result) {
        // Null only when every moment of the speaker's turns is covered by someone else.
        for (const item of own) {
          for (let ms = item.startMs; ms < item.endMs; ms += 50) {
            expect(others.some((other) => other.startMs <= ms && ms + 1 <= other.endMs), context).toBe(true);
          }
        }
        continue;
      }
      const duration = result.endMs - result.startMs;
      expect(duration, context).toBeGreaterThan(0);
      expect(duration, context).toBeLessThanOrEqual(MAX_LISTEN_MS);
      expect(result.short, context).toBe(duration < SHORT_INTERVAL_MS);
      expect(others.some((other) => overlaps(other, result)), context).toBe(false);

      // Every uncovered stretch inside the interval is a pause of at most 250 ms.
      const covering = own
        .map((item) => ({ startMs: Math.max(item.startMs, result.startMs), endMs: Math.min(item.endMs, result.endMs) }))
        .filter((item) => item.endMs > item.startMs)
        .sort((a, b) => a.startMs - b.startMs);
      expect(covering[0]?.startMs, context).toBe(result.startMs);
      let reached = result.startMs;
      for (const item of covering) {
        expect(item.startMs - reached, context).toBeLessThanOrEqual(MAX_PAUSE_MS);
        reached = Math.max(reached, item.endMs);
      }
      expect(reached, context).toBe(result.endMs);
    }
  });

  it("ignores other speakers' identities: relabelling them does not change the result", () => {
    for (let seed = 1; seed <= 500; seed += 1) {
      const turns = randomTurns(generator(seed));
      const relabelled = turns.map((item) => (item.speakerId === "A" ? item : { ...item, speakerId: "Z" }));
      expect(selectListeningInterval(relabelled, "A")).toEqual(selectListeningInterval(turns, "A"));
    }
  });
});
