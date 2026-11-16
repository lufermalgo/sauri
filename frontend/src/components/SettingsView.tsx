import { useEffect, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { ChevronLeft, ChevronRight, FileText, Mic, Palette, UserRound } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { copy } from "../copy/es";
import {
  DEFAULT_SETTINGS_CATEGORY,
  SETTINGS_CATEGORIES,
  navigate,
  routePath,
  type Route,
  type SettingsCategory,
} from "../router";
import type { SessionUser } from "../session-user";
import { AccountSettings } from "./settings/AccountSettings";
import { AppearanceSettings } from "./settings/AppearanceSettings";
import { RecordingSettings } from "./settings/RecordingSettings";
import { SummarySettings } from "./settings/SummarySettings";
import { Button, Icon } from "./ui";
import { useMediaQuery } from "./useMediaQuery";
import "../styles/settings.css";

type SettingsRoute = Extract<Route, { name: "settings" }>;

interface SettingsViewProps {
  route: SettingsRoute;
  user: SessionUser | null;
  onLogout: () => void;
}

const COMPACT_QUERY = "(max-width: 639px)";
const SETTINGS_ROOT: SettingsRoute = { name: "settings" };

const ICONS: Record<SettingsCategory, LucideIcon> = {
  account: UserRound,
  appearance: Palette,
  summaries: FileText,
  recording: Mic,
};

function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

/**
 * Settings console: a category list on the left and the chosen category on the right. Under 640px
 * the screen is two steps: the list, then one category with a back button.
 */
export function SettingsView({ route, user, onLogout }: SettingsViewProps) {
  const compact = useMediaQuery(COMPACT_QUERY);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const category = route.category ?? (compact ? null : DEFAULT_SETTINGS_CATEGORY);

  // On small screens the list is replaced by the category, so focus follows to its heading.
  useEffect(() => {
    if (compact && route.category) detailHeading.current?.focus();
  }, [compact, route.category]);

  function open(event: MouseEvent<HTMLAnchorElement>, target: SettingsRoute) {
    if (!isPlainLeftClick(event)) return;
    event.preventDefault();
    navigate(target);
  }

  const showList = !compact || category === null;
  const label = category ? copy.settings.categories[category].label : "";

  return (
    <section className="settings" aria-labelledby="settings-title">
      <h1 id="settings-title" className="shell-page-title">{copy.settings.title}</h1>
      <div className="settings-layout">
        {showList && (
          <nav className="settings-nav" aria-label={copy.settings.navLabel}>
            <ul className="settings-nav-list">
              {SETTINGS_CATEGORIES.map((name) => {
                const target: SettingsRoute = { name: "settings", category: name };
                const entry = copy.settings.categories[name];
                return (
                  <li key={name}>
                    <a
                      className="settings-nav-link"
                      href={routePath(target)}
                      aria-current={category === name ? "page" : undefined}
                      onClick={(event) => open(event, target)}
                    >
                      <Icon icon={ICONS[name]} />
                      <span className="settings-nav-text">
                        <span className="settings-nav-label">{entry.label}</span>
                        {compact && <span className="settings-nav-description">{entry.description}</span>}
                      </span>
                      {compact && <Icon icon={ChevronRight} />}
                    </a>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}
        {category && (
          <div className="settings-detail">
            {compact && (
              <Button
                variant="ghost"
                className="settings-back"
                aria-label={copy.settings.backLabel}
                onClick={() => navigate(SETTINGS_ROOT)}
              >
                <Icon icon={ChevronLeft} />
                {copy.settings.back}
              </Button>
            )}
            <h2 ref={detailHeading} tabIndex={-1} className="settings-detail-title">{label}</h2>
            {renderCategory(category, user, onLogout)}
          </div>
        )}
      </div>
    </section>
  );
}

function renderCategory(category: SettingsCategory, user: SessionUser | null, onLogout: () => void): ReactNode {
  switch (category) {
    case "account":
      return <AccountSettings user={user} onLogout={onLogout} />;
    case "appearance":
      return <AppearanceSettings />;
    case "summaries":
      return <SummarySettings />;
    case "recording":
      return <RecordingSettings />;
  }
}
