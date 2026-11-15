import type { MouseEvent, ReactNode } from "react";
import { navigate, routePath, type Route } from "../router";
import { copy } from "../copy/es";
import "../styles/shell.css";

interface PortalShellProps {
  route: Route;
  onLogout: () => void;
  children: ReactNode;
}

interface NavItem {
  label: string;
  target: Route;
}

const NAV_ITEMS: NavItem[] = [
  { label: copy.shell.library, target: { name: "library" } },
  { label: copy.shell.upload, target: { name: "upload" } },
];

function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export function PortalShell({ route, onLogout, children }: PortalShellProps) {
  return (
    <div className="shell-root">
      <header className="shell-bar">
        <div className="shell-bar-inner">
          <a
            className="shell-brand"
            href={routePath({ name: "library" })}
            onClick={(event) => {
              if (!isPlainLeftClick(event)) return;
              event.preventDefault();
              navigate({ name: "library" });
            }}
          >
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
            <span className="shell-brand-name">{copy.shell.brand}</span>
          </a>
          <nav className="shell-nav" aria-label={copy.shell.navLabel}>
            {NAV_ITEMS.map((item) => {
              const active = route.name === item.target.name;
              return (
                <a
                  key={item.target.name}
                  className="shell-link"
                  href={routePath(item.target)}
                  aria-current={active ? "page" : undefined}
                  onClick={(event) => {
                    if (!isPlainLeftClick(event)) return;
                    event.preventDefault();
                    navigate(item.target);
                  }}
                >
                  {item.label}
                </a>
              );
            })}
          </nav>
          <button type="button" className="shell-logout" onClick={onLogout}>
            {copy.shell.logout}
          </button>
        </div>
      </header>
      <main className="shell-main">{children}</main>
    </div>
  );
}
