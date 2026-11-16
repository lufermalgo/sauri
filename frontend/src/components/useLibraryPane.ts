import { useCallback, useSyncExternalStore } from "react";
import { createStoredFlag } from "../stored-flag";

export const LIBRARY_PANE_STORAGE_KEY = "sauri_library_pane_hidden";

/** From this width the list and the open recording sit side by side; below it they are two steps. */
export const WORKSPACE_WIDE_QUERY = "(min-width: 1100px)";

const paneFlag = createStoredFlag(LIBRARY_PANE_STORAGE_KEY);

/**
 * Whether the user hid the library list pane to give the open recording the full width. The choice
 * is remembered per device and shared by the side panel toggle and the workspace; blocked storage
 * only keeps it for this visit. It applies only while a recording is open on a wide screen.
 */
export function useLibraryPaneHidden() {
  const hidden = useSyncExternalStore(paneFlag.subscribe, paneFlag.read) === true;
  const setHidden = paneFlag.write;
  const toggle = useCallback(() => paneFlag.write(paneFlag.read() !== true), []);
  return { hidden, setHidden, toggle };
}
