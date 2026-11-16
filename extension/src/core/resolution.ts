import type { RecordingResolution } from "./types";

export interface CaptureDimensions {
  width: number;
  height: number;
}

export const DEFAULT_RESOLUTION: RecordingResolution = "720p";

/** The only capture sizes the recorder accepts. */
export const RESOLUTION_DIMENSIONS: Record<RecordingResolution, CaptureDimensions> = {
  "480p": { width: 854, height: 480 },
  "720p": { width: 1280, height: 720 },
  "1080p": { width: 1920, height: 1080 },
};

export const RESOLUTIONS = Object.keys(RESOLUTION_DIMENSIONS) as RecordingResolution[];

export function isRecordingResolution(value: unknown): value is RecordingResolution {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(RESOLUTION_DIMENSIONS, value);
}

/** Returns the allowed dimensions equal to `value`; anything else falls back to the default. */
export function validCaptureDimensions(value: unknown): CaptureDimensions {
  const candidate = value as Partial<CaptureDimensions> | null | undefined;
  const match = RESOLUTIONS.map(name => RESOLUTION_DIMENSIONS[name])
    .find(size => size.width === candidate?.width && size.height === candidate?.height);
  return { ...(match ?? RESOLUTION_DIMENSIONS[DEFAULT_RESOLUTION]) };
}
