import type { RecordingSettings } from "../core/types";

export const DEFAULT_RECORDING_SETTINGS: RecordingSettings = {
  countdownSeconds: 3,
  showControlBar: true,
  skipMicWarning: false,
};

export function parseRecordingSettings(value: unknown): RecordingSettings {
  const raw = (value && typeof value === "object" ? value : {}) as Partial<RecordingSettings>;
  return {
    countdownSeconds: [0, 3, 5, 10].includes(raw.countdownSeconds as number)
      ? raw.countdownSeconds! : 3,
    showControlBar: typeof raw.showControlBar === "boolean" ? raw.showControlBar : true,
    skipMicWarning: typeof raw.skipMicWarning === "boolean" ? raw.skipMicWarning : false,
  };
}
