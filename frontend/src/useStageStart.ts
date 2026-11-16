import { useState } from "react";
import type { DetectedStage } from "./processing-estimate";

/**
 * When this page saw `stage` begin, or null when it was already running on open: leaving the loading
 * state (a null stage) is not a real stage start, the page simply learned the state.
 */
export function useStageStart(stage: DetectedStage | null): number | null {
  const [track, setTrack] = useState<{ stage: DetectedStage | null; since: number | null }>({ stage, since: null });
  if (track.stage !== stage) {
    // Render-time update (React's derived-state pattern).
    const since = track.stage === null ? null : Date.now();
    setTrack({ stage, since });
    return since;
  }
  return track.since;
}
