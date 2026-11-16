import { useCallback, useSyncExternalStore } from "react";
import { createStoredFlag } from "../stored-flag";

export const SPEAKER_DOCK_STORAGE_KEY = "sauri_speaker_dock_open";

// One shared flag, so a change made in one meeting is the starting state of the next one.
const dockFlag = createStoredFlag(SPEAKER_DOCK_STORAGE_KEY);

/**
 * Whether the speakers panel beside the video is open. Closed until the user opens it; the choice is
 * remembered per browser, and blocked storage only keeps it for this visit.
 */
export function useSpeakerDock() {
  const open = useSyncExternalStore(dockFlag.subscribe, dockFlag.read) === true;
  const setOpen = useCallback((value: boolean) => dockFlag.write(value), []);
  return { open, setOpen };
}
