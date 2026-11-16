import { DEFAULT_RESOLUTION, isRecordingResolution } from "../core/resolution";
import type { RecordingSettings } from "../core/types";

/** `chrome.storage.local` key of the single recording-settings record. */
export const RECORDING_SETTINGS_KEY = "recordingSettings";

export const DEFAULT_RECORDING_SETTINGS: RecordingSettings = {
  countdownSeconds: 3,
  resolution: DEFAULT_RESOLUTION,
  showControlBar: true,
  skipMicWarning: false,
};

/** Reads each field independently, so records saved by older versions (no `resolution`) stay valid. */
export function parseRecordingSettings(value: unknown): RecordingSettings {
  const raw = (value && typeof value === "object" ? value : {}) as Partial<Record<keyof RecordingSettings, unknown>>;
  return {
    countdownSeconds: [0, 3, 5, 10].includes(raw.countdownSeconds as number)
      ? raw.countdownSeconds as RecordingSettings["countdownSeconds"] : DEFAULT_RECORDING_SETTINGS.countdownSeconds,
    resolution: isRecordingResolution(raw.resolution) ? raw.resolution : DEFAULT_RECORDING_SETTINGS.resolution,
    showControlBar: typeof raw.showControlBar === "boolean" ? raw.showControlBar : DEFAULT_RECORDING_SETTINGS.showControlBar,
    skipMicWarning: typeof raw.skipMicWarning === "boolean" ? raw.skipMicWarning : DEFAULT_RECORDING_SETTINGS.skipMicWarning,
  };
}

export async function readRecordingSettings(): Promise<RecordingSettings> {
  const stored = await chrome.storage.local.get(RECORDING_SETTINGS_KEY);
  return parseRecordingSettings(stored[RECORDING_SETTINGS_KEY]);
}

/** Merges `change` into the stored record and returns what was saved. */
export async function writeRecordingSettings(change: Partial<RecordingSettings>): Promise<RecordingSettings> {
  const next = { ...await readRecordingSettings(), ...change };
  await chrome.storage.local.set({ [RECORDING_SETTINGS_KEY]: next });
  return next;
}
