/** Dispatched on `window` when a recording is renamed or deleted, so the list pane refreshes quietly. */
export const LIBRARY_CHANGED_EVENT = "sauri:library-changed";

export function notifyLibraryChanged(): void {
  window.dispatchEvent(new Event(LIBRARY_CHANGED_EVENT));
}
