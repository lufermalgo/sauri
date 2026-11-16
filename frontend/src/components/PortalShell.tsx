import { useEffect, useId, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { Library, PanelLeft } from "lucide-react";
import { navigate, routePath, type Route } from "../router";
import type { SessionUser } from "../session-user";
import { copy } from "../copy/es";
import { ProfileCard } from "./ProfileCard";
import { useSidebar } from "./useSidebar";
import { Icon } from "./ui";
import "../styles/shell.css";

interface PortalShellProps {
  route: Route;
  user?: SessionUser | null;
  onLogout: () => void;
  children: ReactNode;
}

const LIBRARY_ROUTE: Route = { name: "library" };
const FOCUSABLE = "a[href], button:not([disabled])";

function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function BrandMark() {
  return (
    <svg className="shell-brand-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="10" fill="currentColor" opacity="0.18" />
      <path
        d="M7 14c1.6-4.6 5-6.4 10-6-.4 5-3.4 8.4-8 8.4-.8 0-1.5-.1-2-.4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function PortalShell({ route, user = null, onLogout, children }: PortalShellProps) {
  const { mode, drawerOpen, toggleCollapsed, openDrawer, closeDrawer } = useSidebar();
  const sidebarId = useId();
  const sidebarRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const closerRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const drawer = mode === "drawer";

  // Focus moves into the drawer when it opens and back to its opener when it closes.
  useEffect(() => {
    if (drawerOpen) closerRef.current?.focus();
    else if (wasOpen.current) openerRef.current?.focus();
    wasOpen.current = drawerOpen;
  }, [drawerOpen]);

  // A route change always dismisses the drawer, however it was triggered.
  useEffect(closeDrawer, [route, closeDrawer]);

  // Escape closes the drawer; Tab stays inside it while it is open.
  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !event.defaultPrevented) {
        closeDrawer();
      } else if (event.key === "Tab") {
        const items = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        if (!first || !last) return;
        if (!sidebarRef.current?.contains(active)) {
          event.preventDefault();
          first.focus();
        } else if (event.shiftKey && active === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && active === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen, closeDrawer]);

  function go(event: MouseEvent<HTMLAnchorElement>, target: Route) {
    if (!isPlainLeftClick(event)) return;
    event.preventDefault();
    navigate(target);
    closeDrawer();
  }

  const libraryActive = route.name === LIBRARY_ROUTE.name;

  return (
    <div className="shell-root" data-mode={mode}>
      {drawer && (
        <header className="shell-topbar">
          <button
            ref={openerRef}
            type="button"
            className="shell-icon-button"
            aria-label={copy.shell.sidebar.open}
            aria-expanded={drawerOpen}
            aria-controls={sidebarId}
            onClick={openDrawer}
          >
            <Icon icon={PanelLeft} />
          </button>
          <span className="shell-brand">
            <BrandMark />
            <span className="shell-brand-name">{copy.shell.brand}</span>
          </span>
        </header>
      )}
      {drawer && drawerOpen && <div className="shell-backdrop" aria-hidden="true" onClick={closeDrawer} />}
      <aside
        ref={sidebarRef}
        id={sidebarId}
        className="shell-sidebar"
        aria-label={copy.shell.sidebar.region}
        data-open={drawer ? drawerOpen : undefined}
      >
        <div className="shell-sidebar-head">
          <a className="shell-brand shell-collapsible" href={routePath(LIBRARY_ROUTE)} onClick={(event) => go(event, LIBRARY_ROUTE)}>
            <BrandMark />
            <span className="shell-brand-name">{copy.shell.brand}</span>
          </a>
          {drawer ? (
            <button
              ref={closerRef}
              type="button"
              className="shell-icon-button"
              aria-label={copy.shell.sidebar.close}
              aria-expanded={drawerOpen}
              aria-controls={sidebarId}
              onClick={closeDrawer}
            >
              <Icon icon={PanelLeft} />
            </button>
          ) : (
            <button
              type="button"
              className="shell-icon-button"
              aria-label={copy.shell.sidebar.toggle}
              aria-expanded={mode === "full"}
              aria-controls={sidebarId}
              onClick={toggleCollapsed}
            >
              <Icon icon={PanelLeft} />
              <span className="shell-tip-only" aria-hidden="true">{copy.shell.sidebar.toggle}</span>
            </button>
          )}
        </div>
        <nav className="shell-nav" aria-label={copy.shell.navLabel}>
          <a
            className="shell-link"
            href={routePath(LIBRARY_ROUTE)}
            aria-current={libraryActive ? "page" : undefined}
            onClick={(event) => go(event, LIBRARY_ROUTE)}
          >
            <Icon icon={Library} />
            <span className="shell-collapsible">{copy.shell.library}</span>
          </a>
        </nav>
        <ProfileCard user={user} route={route} onNavigate={go} onLogout={onLogout} />
      </aside>
      <div className="shell-content">
        <main className="shell-main">{children}</main>
      </div>
    </div>
  );
}
