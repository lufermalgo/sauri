import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "sauri_sidebar_collapsed";
const DRAWER_QUERY = "(max-width: 639px)";
const NARROW_QUERY = "(max-width: 1319px)";

export type SidebarMode = "full" | "rail" | "drawer";

function matches(query: string): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(query).matches;
}

function useMediaQuery(query: string): boolean {
  const [value, setValue] = useState(() => matches(query));
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const onChange = () => setValue(list.matches);
    onChange();
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);
  return value;
}

function readStoredChoice(): boolean | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "1" ? true : stored === "0" ? false : null;
  } catch {
    return null; // blocked storage: fall back to the viewport default
  }
}

function storeChoice(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
  } catch {
    // blocked storage: the choice only lasts for this visit
  }
}

/**
 * Sidebar state. Wide screens show the full panel or a rail (the choice is remembered per device,
 * and below 1320px the rail is the default); under 640px the panel is an off-canvas drawer.
 */
export function useSidebar() {
  const drawerViewport = useMediaQuery(DRAWER_QUERY);
  const narrowViewport = useMediaQuery(NARROW_QUERY);
  const [choice, setChoice] = useState<boolean | null>(readStoredChoice);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const collapsed = choice ?? narrowViewport;
  const mode: SidebarMode = drawerViewport ? "drawer" : collapsed ? "rail" : "full";

  useEffect(() => {
    if (!drawerViewport) setDrawerOpen(false);
  }, [drawerViewport]);

  const toggleCollapsed = useCallback(() => {
    setChoice(!collapsed);
    storeChoice(!collapsed);
  }, [collapsed]);
  const openDrawer = useCallback(() => setDrawerOpen(true), []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  return { mode, drawerOpen, toggleCollapsed, openDrawer, closeDrawer };
}
