import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_RECORDING_SETTINGS, parseRecordingSettings, readRecordingSettings, writeRecordingSettings } from "./recordingSettings";
import { RESOLUTION_DIMENSIONS, validCaptureDimensions } from "../core/resolution";

let stored: Record<string, unknown>;
beforeEach(() => {
  stored = {};
  vi.stubGlobal("chrome", { storage: { local: {
    get: vi.fn(async (key: string) => ({ [key]: stored[key] })),
    set: vi.fn(async (values: Record<string, unknown>) => { Object.assign(stored, values); }),
  } } });
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("recording settings store", () => {
  it("defaults to a 3 s countdown, 720p, control bar on and the microphone warning on", () => {
    expect(DEFAULT_RECORDING_SETTINGS).toEqual({ countdownSeconds: 3, resolution: "720p", showControlBar: true, skipMicWarning: false });
    expect(parseRecordingSettings(undefined)).toEqual(DEFAULT_RECORDING_SETTINGS);
  });
  it("reads a legacy record without resolution as 720p and keeps its other values", () => {
    expect(parseRecordingSettings({ countdownSeconds: 10, showControlBar: false, skipMicWarning: true }))
      .toEqual({ countdownSeconds: 10, resolution: "720p", showControlBar: false, skipMicWarning: true });
  });
  it.each(["480p", "720p", "1080p"])("accepts %s and rejects unknown resolutions", resolution => {
    expect(parseRecordingSettings({ resolution }).resolution).toBe(resolution);
    expect(parseRecordingSettings({ resolution: "4k" }).resolution).toBe("720p");
    expect(parseRecordingSettings({ resolution: 720 }).resolution).toBe("720p");
    expect(parseRecordingSettings({ resolution: "toString" }).resolution).toBe("720p");
  });
  it("reads and merges writes into the stored record", async () => {
    stored.recordingSettings = { countdownSeconds: 5, showControlBar: false };
    expect(await readRecordingSettings()).toEqual({ countdownSeconds: 5, resolution: "720p", showControlBar: false, skipMicWarning: false });
    expect(await writeRecordingSettings({ resolution: "1080p" })).toEqual({ countdownSeconds: 5, resolution: "1080p", showControlBar: false, skipMicWarning: false });
    expect(stored.recordingSettings).toEqual({ countdownSeconds: 5, resolution: "1080p", showControlBar: false, skipMicWarning: false });
  });
});

describe("capture dimensions", () => {
  it("maps each resolution to its size", () => {
    expect(RESOLUTION_DIMENSIONS).toEqual({ "480p": { width: 854, height: 480 }, "720p": { width: 1280, height: 720 }, "1080p": { width: 1920, height: 1080 } });
  });
  it("accepts only the allowed sizes and falls back to 720p", () => {
    expect(validCaptureDimensions({ width: 1920, height: 1080 })).toEqual({ width: 1920, height: 1080 });
    for (const bad of [undefined, null, {}, { width: 3840, height: 2160 }, { width: 1280, height: 1080 }, { width: "1280", height: "720" }, "720p"]) {
      expect(validCaptureDimensions(bad)).toEqual({ width: 1280, height: 720 });
    }
  });
});
