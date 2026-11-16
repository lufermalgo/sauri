import { useCallback, useSyncExternalStore } from "react";
import { createStoredFlag, type StoredFlag } from "../stored-flag";

/**
 * Secondary panes: the navigation or list region that sits beside a section's content (the library
 * list, the settings categories). The sidebar item of that section shows or hides it. Each pane has
 * its own storage key, so hiding one never affects another.
 */
export interface SecondaryPaneControl {
  /** `id` of the pane region, the target of the sidebar item's `aria-controls`. */
  id: string;
  hidden: boolean;
  toggle: () => void;
}

export const LIBRARY_PANE_ID = "library-pane";
export const LIBRARY_PANE_STORAGE_KEY = "sauri_library_pane_hidden";
export const SETTINGS_PANE_ID = "settings-pane";
export const SETTINGS_PANE_STORAGE_KEY = "sauri_settings_pane_hidden";

// One shared flag per key, so every hook instance of a pane (the sidebar item and the pane's own
// view) sees a change made anywhere.
const flags = new Map<string, StoredFlag>();

function flagFor(key: string): StoredFlag {
  let flag = flags.get(key);
  if (!flag) {
    flag = createStoredFlag(key);
    flags.set(key, flag);
  }
  return flag;
}

/**
 * Whether the user hid the pane stored under `key`. The choice is remembered per device; blocked
 * storage only keeps it for this visit. Whether it applies (a screen wide enough, the right route)
 * is up to the caller.
 */
export function useSecondaryPane(key: string) {
  const flag = flagFor(key);
  const hidden = useSyncExternalStore(flag.subscribe, flag.read) === true;
  const toggle = useCallback(() => flag.write(flag.read() !== true), [flag]);
  return { hidden, setHidden: flag.write, toggle };
}

/** Attributes of a hidden pane's slot: collapsed by CSS, out of the tab order and the accessibility tree. */
export function hiddenPaneAttributes(hidden: boolean) {
  return {
    "data-hidden": hidden || undefined,
    "aria-hidden": hidden || undefined,
    ...(hidden ? { inert: "" } : {}),
  };
}
