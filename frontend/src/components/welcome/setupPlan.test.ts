import { describe, expect, it } from "vitest";
import { actionFor, pendingItems, recommendedChoices } from "./setupPlan";
import { DIAR, LARGE_LLM, PARAKEET, SMALL_LLM, VAD, WHISPER, desktopListing, localProcess, withInstalled } from "./welcomeFixtures";

const ALL = [PARAKEET, WHISPER, VAD, SMALL_LLM, LARGE_LLM, DIAR];
const processes = () => [localProcess("transcription"), localProcess("diarization"), localProcess("summary")];

describe("setup plan", () => {
  it.each([
    [8, [PARAKEET, SMALL_LLM, DIAR], 632_314_500 + 2_740_937_888 + 251_532_143],
    [16, [PARAKEET, LARGE_LLM, DIAR], 632_314_500 + 5_680_522_464 + 251_532_143],
    [24, [PARAKEET, LARGE_LLM, DIAR], 632_314_500 + 5_680_522_464 + 251_532_143],
  ] as const)("installs the host's plan for a %i GB Mac, in order, without Whisper", (memory, ids, bytes) => {
    const items = pendingItems(desktopListing(memory));
    expect(items.map((item) => item.id)).toEqual(ids);
    expect(items.map((item) => item.id)).not.toContain(WHISPER);
    expect(items.map((item) => item.id)).not.toContain(VAD);
    expect(items.reduce((sum, item) => sum + item.bytes, 0)).toBe(bytes);
    // Same listing, same plan.
    expect(pendingItems(desktopListing(memory))).toEqual(pendingItems(desktopListing(memory)));
  });

  it("skips what is already installed and adds up only what is left to download", () => {
    const items = pendingItems(withInstalled(desktopListing(16), [PARAKEET]));
    expect(items.map((item) => item.id)).toEqual([LARGE_LLM, DIAR]);
    expect(items.reduce((sum, item) => sum + item.bytes, 0)).toBe(5_680_522_464 + 251_532_143);
    expect(pendingItems(withInstalled(desktopListing(16), ALL))).toEqual([]);
  });

  it("checks a file that is present but not checked yet, and never downloads a managed engine", () => {
    const list = desktopListing(16);
    const whisper = list.models.find((model) => model.id === WHISPER)!;
    expect(actionFor({ ...whisper, state: "unverified", availability: "present_unverified" })).toBe("verify");
    expect(actionFor({ ...whisper, state: "corrupt", availability: "present_unverified" })).toBe("install");
    expect(actionFor({ ...whisper, state: "unverified", availability: "present_unverified", reason: "hash_mismatch" })).toBe("install");
    expect(actionFor(list.models.find((model) => model.id === "fluidaudio-cli")!)).toBe("done");
  });

  it("falls back to the recommended models when the host sends no plan", () => {
    const { setup_plan: _plan, ...older } = desktopListing(8);
    expect(pendingItems(older).map((item) => item.id)).toEqual([PARAKEET, SMALL_LLM, DIAR]);
  });

  it("pins the 4B on an 8 GB Mac and leaves the defaults alone on 16 and 24 GB", () => {
    const small = withInstalled(desktopListing(8), ALL.filter((id) => id !== LARGE_LLM));
    expect(recommendedChoices(small, processes())).toEqual([{ ...localProcess("summary"), model: `local:${SMALL_LLM}` }]);
    for (const memory of [16, 24] as const) {
      expect(recommendedChoices(withInstalled(desktopListing(memory), ALL), processes())).toEqual([]);
    }
  });

  it("never touches a process served by an external provider or already on the right choice", () => {
    const small = withInstalled(desktopListing(8), ALL.filter((id) => id !== LARGE_LLM));
    const external = { ...localProcess("summary"), provider_id: "p-1", model: "gpt" };
    expect(recommendedChoices(small, [external])).toEqual([]);
    expect(recommendedChoices(small, [localProcess("summary", `local:${SMALL_LLM}`)])).toEqual([]);
  });
});
