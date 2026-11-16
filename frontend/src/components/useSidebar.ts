import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { useMediaQuery } from "./useMediaQuery";

export const SIDEBAR_STORAGE_KEY = "sauri_sidebar_collapsed";
const DRAWER_QUERY = "(max-width: 639px)";
const NARROW_QUERY = "(max-width: 1319px)";

export type SidebarMode = "full" | "rail" | "drawer";

// The collapsed/expanded choice is shared by every hook instance (the shell and the settings
// switch), so a change anywhere shows up everywhere. localStorage is the source of truth;
// `unsaved` only holds a choice the browser refused to store (blocked storage), so it lasts for
// this visit. It is tied to the storage object it failed on, so a different storage starts clean.
const subscribers = new Set<() => void>();
let unsaved: { storage: Storage | null; collapsed: boolean } | null = null;

function currentStorage(): Storage | null {
  try {
    return localStorage;
  } catch {
    return null; // some browsers throw on access when site data is blocked
  }
}

function readStoredChoice(): boolean | null {
  const storage = currentStorage();
  try {
    const stored = storage?.getItem(SIDEBAR_STORAGE_KEY);
    if (stored === "1") return true;
    if (stored === "0") return false;
  } catch {
    // blocked storage: fall through to the unsaved choice
  }
  return unsaved && unsaved.storage === storage ? unsaved.collapsed : null;
}

function storeChoice(collapsed: boolean): void {
  const storage = currentStorage();
  try {
    if (!storage) throw new Error("storage unavailable");
    storage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? "1" : "0");
    unsaved = null;
  } catch {
    unsaved = { storage, collapsed };
  }
  subscribers.forEach((notify) => notify());
}

function subscribe(notify: () => void): () => void {
  subscribers.add(notify);
  return () => subscribers.delete(notify);
}

/**
 * The remembered sidebar choice. Without a stored choice, narrow screens (under 1320px) start
 * collapsed. `setCollapsed` stores the choice per device.
 */
export function useSidebarCollapsed() {
  const narrowViewport = useMediaQuery(NARROW_QUERY);
  const choice = useSyncExternalStore(subscribe, readStoredChoice);
  const collapsed = choice ?? narrowViewport;
  return { collapsed, setCollapsed: storeChoice };
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
