import { describe, expect, it } from "vitest";
import type { EngineProcessState, LocalModel } from "@sauri/shared-types";
import { engineFor } from "./useTranscriptionEngine";

function model(overrides: Partial<LocalModel> & Pick<LocalModel, "id" | "engine">): LocalModel {
  return {
    process: "transcription", kind: "model", size: 1, min_ram_gib: 8, requires: [], status: "measured", default: false,
    managed_by: null, recommended: false, in_use_by: [], state: "installed", installed_size: 1, installed_at: null,
    availability: "installed", ...overrides,
  };
}
const setting = (overrides: Partial<EngineProcessState> = {}): EngineProcessState => ({
  capability: "transcription", provider_id: null, provider_kind: null, provider_label: null, model: "local:default",
  local_fallback: false, configured: true, version: 1, updated_at: null, notice_version: null, ...overrides,
});
const PARAKEET = model({ id: "parakeet", engine: "fluidaudio", preferred: true, needs: "cli", needs_ready: true });
const WHISPER = model({ id: "whisper", engine: "whisper.cpp", default: true });

describe("engineFor", () => {
  it("is Parakeet when local:default resolves to it", () => {
    expect(engineFor(setting(), [PARAKEET, WHISPER])).toBe("parakeet");
    expect(engineFor(undefined, [PARAKEET, WHISPER])).toBe("parakeet");
  });

  it("is Whisper when Parakeet is missing or its engine is not installed", () => {
    expect(engineFor(setting(), [WHISPER])).toBe("whisper");
    expect(engineFor(setting(), [{ ...PARAKEET, needs_ready: false }, WHISPER])).toBe("whisper");
    expect(engineFor(setting(), [{ ...PARAKEET, availability: "available" }, WHISPER])).toBe("whisper");
  });

  it("follows a model the person pinned", () => {
    expect(engineFor(setting({ model: "local:whisper" }), [PARAKEET, WHISPER])).toBe("whisper");
    expect(engineFor(setting({ model: "local:parakeet" }), [PARAKEET, WHISPER])).toBe("parakeet");
  });

  it("stays cautious for an external provider", () => {
    expect(engineFor(setting({ provider_id: "p1", model: "nova-3" }), [PARAKEET, WHISPER])).toBe("whisper");
  });
});
