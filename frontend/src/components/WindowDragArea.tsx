import { useWindowChrome } from "./useWindowChrome";

/**
 * The screens outside the portal's frame (opening, sign-in, first-run setup) have no top bar of their own: in the
 * desktop app on a Mac, whose window has no title bar, this invisible strip along the top edge moves the window.
 */
export function WindowDragArea() {
  const { inset, fullScreen } = useWindowChrome();
  return inset && !fullScreen ? <div className="window-drag-area" aria-hidden="true" /> : null;
}
