import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { createStoredFlag } from "../stored-flag";
import { useMediaQuery } from "./useMediaQuery";

export const SIDEBAR_STORAGE_KEY = "sauri_sidebar_collapsed";
const DRAWER_QUERY = "(max-width: 639px)";
const NARROW_QUERY = "(max-width: 1319px)";

export type SidebarMode = "full" | "rail" | "drawer";

// The collapsed/expanded choice is shared by every hook instance (the shell and the settings
// switch), so a change anywhere shows up everywhere.
const sidebarFlag = createStoredFlag(SIDEBAR_STORAGE_KEY);

/**
 * The remembered sidebar choice. Without a stored choice, narrow screens (under 1320px) start
 * collapsed. `setCollapsed` stores the choice per device.
 */
export function useSidebarCollapsed() {
  const narrowViewport = useMediaQuery(NARROW_QUERY);
  const choice = useSyncExternalStore(sidebarFlag.subscribe, sidebarFlag.read);
  const collapsed = choice ?? narrowViewport;
  return { collapsed, setCollapsed: sidebarFlag.write };
}

/**
 * Sidebar state. Wide screens show the full panel or a rail (the choice is remembered per device,
 * and below 1320px the rail is the default); under 640px the panel is an off-canvas drawer.
 */
export function useSidebar() {
  const drawerViewport = useMediaQuery(DRAWER_QUERY);
  const { collapsed, setCollapsed } = useSidebarCollapsed();
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
