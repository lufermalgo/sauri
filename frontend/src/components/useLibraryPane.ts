import { LIBRARY_PANE_STORAGE_KEY, useSecondaryPane } from "./useSecondaryPane";

export { LIBRARY_PANE_STORAGE_KEY };

/** From this width the list and the open recording sit side by side; below it they are two steps. */
export const WORKSPACE_WIDE_QUERY = "(min-width: 1100px)";

/**
 * Whether the user hid the library list pane to give the open recording the full width. It applies
 * only while a recording is open on a wide screen.
 */
export function useLibraryPaneHidden() {
  return useSecondaryPane(LIBRARY_PANE_STORAGE_KEY);
}
