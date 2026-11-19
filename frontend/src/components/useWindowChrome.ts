import { useState, useSyncExternalStore } from "react";
import { desktopBridge, type WindowState } from "../desktop-bridge";
import { usePushed } from "./usePushed";

/**
 * The window around the portal. `inset`: the desktop app on a Mac draws no title bar, so the portal's top bar shares
 * its row with the traffic lights and moves the window; `fullScreen`: macOS hid them, their room is free again;
 * `zoom`: the page zoom (View > Zoom), because the traffic lights keep their size in screen points while the
 * portal's pixels grow or shrink with it. In a normal browser, or an app version with the system's title bar, `inset`
 * is false and nothing changes.
 */
export interface WindowChrome {
  inset: boolean;
  fullScreen: boolean;
  zoom: number;
}

/** The page zoom: the window's width in screen points over the page's width in CSS pixels (1 when unknown). */
function pageZoom(): number {
  const ratio = window.outerWidth / window.innerWidth;
  return Number.isFinite(ratio) && ratio >= 0.25 && ratio <= 5 ? Math.round(ratio * 100) / 100 : 1;
}

function onResize(listener: () => void): () => void {
  window.addEventListener("resize", listener);
  return () => window.removeEventListener("resize", listener);
}

const noResize = () => () => undefined;
const unzoomed = () => 1;

export function useWindowChrome(): WindowChrome {
  const [bridge] = useState(desktopBridge);
  const inset = bridge?.titleBar === "inset";
  const [state] = usePushed<WindowState>(inset ? bridge?.getWindowState : undefined, inset ? bridge?.onWindowState : undefined);
  const zoom = useSyncExternalStore(inset ? onResize : noResize, inset ? pageZoom : unzoomed, unzoomed);
  return { inset, fullScreen: inset && state?.fullScreen === true, zoom };
}
