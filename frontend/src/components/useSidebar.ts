import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { createStoredFlag } from "../stored-flag";
import { useMediaQuery } from "./useMediaQuery";

export const SIDEBAR_STORAGE_KEY = "sauri_sidebar_collapsed";
const DRAWER_QUERY = "(max-width: 639px)";
const NARROW_QUERY = "(max-width: 1319px)";

export type SidebarMode = "full" | "rail" | "drawer";

// The collapsed/expanded choice is whatever the user last left with the panel toggle, remembered
// per device. Without one, narrow screens (under 1320px) start collapsed.
const sidebarFlag = createStoredFlag(SIDEBAR_STORAGE_KEY);

/**
 * Sidebar state. Wide screens show the full panel or a rail (the choice is remembered per device,
 * and below 1320px the rail is the default); under 640px the panel is an off-canvas drawer.
 */
export function useSidebar() {
  const drawerViewport = useMediaQuery(DRAWER_QUERY);
  const narrowViewport = useMediaQuery(NARROW_QUERY);
  const choice = useSyncExternalStore(sidebarFlag.subscribe, sidebarFlag.read);
  const collapsed = choice ?? narrowViewport;
  const setCollapsed = sidebarFlag.write;
  const [drawerOpen, setDrawerOpen] = useState(false);

  const mode: SidebarMode = drawerViewport ? "drawer" : collapsed ? "rail" : "full";

  useEffect(() => {
    if (!drawerViewport) setDrawerOpen(false);
  }, [drawerViewport]);

  const toggleCollapsed = useCallback(() => setCollapsed(!collapsed), [collapsed, setCollapsed]);
  const openDrawer = useCallback(() => setDrawerOpen(true), []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  return { mode, drawerOpen, toggleCollapsed, openDrawer, closeDrawer };
}
