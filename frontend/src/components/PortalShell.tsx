import { useEffect, useId, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { Library, PanelLeft } from "lucide-react";
import { navigate, routePath, type Route } from "../router";
import type { SessionUser } from "../session-user";
import { readLastMeetingId } from "../last-meeting";
import { ProfileCard } from "./ProfileCard";
import { useSidebar } from "./useSidebar";
import { useMediaQuery } from "./useMediaQuery";
import { WORKSPACE_WIDE_QUERY } from "./useLibraryPane";
import {
  LIBRARY_PANE_ID,
  LIBRARY_PANE_STORAGE_KEY,
  SETTINGS_PANE_ID,
  SETTINGS_PANE_STORAGE_KEY,
  useSecondaryPane,
  type SecondaryPaneControl,
} from "./useSecondaryPane";
import { BrandMark, Icon, useTooltip } from "./ui";
import "../styles/shell.css";
import { useT } from "../i18n";

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

const BRAND_MARK_SIZE = 24;

export function PortalShell({ route, user = null, onLogout, children }: PortalShellProps) {
  const { t } = useT();
  const { mode, drawerOpen, toggleCollapsed, openDrawer, closeDrawer } = useSidebar();
  const sidebarId = useId();
  const sidebarRef = useRef<HTMLElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const closerRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const drawer = mode === "drawer";
  // A sidebar item whose section has a secondary pane shows or hides it, but only while that pane
  // exists beside the content: the library list on the library routes of a wide screen, the settings
  // categories on any screen wide enough for two panes. Everywhere else the item is a plain link.
  const wide = useMediaQuery(WORKSPACE_WIDE_QUERY);
  const library = useSecondaryPane(LIBRARY_PANE_STORAGE_KEY);
  const settings = useSecondaryPane(SETTINGS_PANE_STORAGE_KEY);
  const libraryPane: SecondaryPaneControl | null =
    (route.name === "library" || route.name === "meeting") && wide ? { id: LIBRARY_PANE_ID, hidden: library.hidden, toggle: library.toggle } : null;
  const settingsPane: SecondaryPaneControl | null =
    route.name === "settings" && !drawer ? { id: SETTINGS_PANE_ID, hidden: settings.hidden, toggle: settings.toggle } : null;
  // A plain link says its name (the rail already pops its label out beside the icon).
  const libraryTip = useTooltip(
    libraryPane
      ? (libraryPane.hidden ? t("shell:libraryPane.show") : t("shell:libraryPane.hide"))
      : mode === "rail" ? undefined : t("shell:library"),
  );

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
  const onLibraryRoute = route.name === "library" || route.name === "meeting";
  // From another section the item returns to the recording the user was exploring, if there is one.
  const lastMeetingId = onLibraryRoute ? null : readLastMeetingId();
  const libraryTarget: Route = lastMeetingId ? { name: "meeting", meetingId: lastMeetingId } : LIBRARY_ROUTE;

  return (
    <div className="shell-root" data-mode={mode}>
      {drawer && (
        <header className="shell-topbar">
          <button
            ref={openerRef}
            type="button"
            className="shell-icon-button"
            aria-label={t("shell:sidebar.open")}
            aria-expanded={drawerOpen}
            aria-controls={sidebarId}
            onClick={openDrawer}
          >
            <Icon icon={PanelLeft} />
          </button>
          <span className="shell-brand">
            <BrandMark className="shell-brand-mark" size={BRAND_MARK_SIZE} />
            <span className="shell-brand-name">{t("shell:brand")}</span>
          </span>
        </header>
      )}
      {drawer && drawerOpen && <div className="shell-backdrop" aria-hidden="true" onClick={closeDrawer} />}
      <aside
        ref={sidebarRef}
        id={sidebarId}
        className="shell-sidebar"
        aria-label={t("shell:sidebar.region")}
        data-open={drawer ? drawerOpen : undefined}
      >
        <div className="shell-sidebar-head">
          <a className="shell-brand" href={routePath(LIBRARY_ROUTE)} aria-label={t("shell:brand")} onClick={(event) => go(event, LIBRARY_ROUTE)}>
            <BrandMark className="shell-brand-mark" size={BRAND_MARK_SIZE} />
            <span className="shell-brand-name shell-collapsible">{t("shell:brand")}</span>
          </a>
          {drawer ? (
            <button
              ref={closerRef}
              type="button"
              className="shell-icon-button"
              aria-label={t("shell:sidebar.close")}
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
              aria-label={t("shell:sidebar.toggle")}
              aria-expanded={mode === "full"}
              aria-controls={sidebarId}
              onClick={toggleCollapsed}
            >
              <Icon icon={PanelLeft} />
              <span className="shell-tip-only" aria-hidden="true">{t("shell:sidebar.toggle")}</span>
            </button>
          )}
        </div>
        <nav className="shell-nav" aria-label={t("shell:navLabel")}>
          {libraryPane ? (
            <span className="shell-link-wrap">
              <button
                type="button"
                className="shell-link shell-link--pane"
                aria-label={t("shell:library")}
                aria-current={onLibraryRoute ? "page" : undefined}
                aria-expanded={!libraryPane.hidden}
                aria-controls={libraryPane.id}
                {...libraryTip.triggerProps}
                onClick={() => { libraryTip.hide(); libraryPane.toggle(); }}
              >
                <Icon icon={Library} />
                <span className="shell-link-label" aria-hidden="true">{t("shell:library")}</span>
              </button>
              {libraryTip.tooltip}
            </span>
          ) : (
            <span className="shell-link-wrap">
              <a
                className="shell-link"
                href={routePath(libraryTarget)}
                aria-current={libraryActive ? "page" : undefined}
                {...libraryTip.triggerProps}
                onClick={(event) => { libraryTip.hide(); go(event, libraryTarget); }}
              >
                <Icon icon={Library} />
                <span className="shell-collapsible">{t("shell:library")}</span>
              </a>
              {libraryTip.tooltip}
            </span>
          )}
        </nav>
        <ProfileCard user={user} route={route} settingsPane={settingsPane} onNavigate={go} onLogout={onLogout} />
      </aside>
      <div className="shell-content">
        <main className="shell-main">{children}</main>
      </div>
    </div>
  );
}
