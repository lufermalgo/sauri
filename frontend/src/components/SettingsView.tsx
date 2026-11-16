import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  Mic,
  Palette,
  Search,
  Sparkles,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
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
import { EnginesSettings } from "./settings/EnginesSettings";
import { ProcessSettings } from "./settings/ProcessSettings";
import { filterSettingsGroups } from "./settings/settingsSearch";
import { SummarySettings } from "./settings/SummarySettings";
import { Button, Icon } from "./ui";
import { useMediaQuery } from "./useMediaQuery";
import { SETTINGS_PANE_ID, SETTINGS_PANE_STORAGE_KEY, hiddenPaneAttributes, useSecondaryPane } from "./useSecondaryPane";
import "../styles/settings.css";
import { useT } from "../i18n";

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
  engines: Sparkles,
  transcription: Mic,
  speakers: UsersRound,
  summaries: FileText,
};

function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

/**
 * Settings console: grouped categories with a search field on the left and the chosen category on
 * the right. Under 640px the screen is two steps: the list, then one category with a back button.
 */
export function SettingsView({ route, user, onLogout }: SettingsViewProps) {
  const { t } = useT();
  const compact = useMediaQuery(COMPACT_QUERY);
  // The sidebar's gear hides the category pane to give the category the full width; it stays
  // mounted, so the search text is still there. Under 640px the list is a step of its own.
  const { hidden: paneHidden } = useSecondaryPane(SETTINGS_PANE_STORAGE_KEY);
  const hidden = !compact && paneHidden;
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const searchId = useId();
  const [query, setQuery] = useState("");
  const category = route.category ?? (compact ? null : DEFAULT_SETTINGS_CATEGORY);
  const groups = filterSettingsGroups(query);
  const resultCount = groups.reduce((total, group) => total + group.categories.length, 0);
  const searching = query.trim() !== "";

  // On small screens the list is replaced by the category, so focus follows to its heading.
  useEffect(() => {
    if (compact && route.category) detailHeading.current?.focus();
  }, [compact, route.category]);

  function open(event: MouseEvent<HTMLAnchorElement>, target: SettingsRoute) {
    if (!isPlainLeftClick(event)) return;
    event.preventDefault();
    navigate(target);
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape" && query !== "") {
      event.preventDefault();
      setQuery("");
    } else if (event.key === "Enter" && resultCount > 0) {
      event.preventDefault();
      navigate({ name: "settings", category: groups[0].categories[0] });
    }
  }

  // Up and Down walk the search field and the visible rows without leaving the nav.
  function onNavKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const stops = Array.from(navRef.current?.querySelectorAll<HTMLElement>("input, a[href]") ?? []);
    const index = stops.indexOf(document.activeElement as HTMLElement);
    if (index === -1) return;
    event.preventDefault();
    stops[Math.min(Math.max(index + (event.key === "ArrowDown" ? 1 : -1), 0), stops.length - 1)].focus();
  }

  const showList = !compact || category === null;
  const label = category ? t(`settings:categories.${category}.label`) : "";

  return (
    <section className="app-view settings" aria-labelledby="settings-title">
      <header className="ui-pane-header">
        <h1 id="settings-title" className="ui-pane-title">{t("settings:title")}</h1>
      </header>
      <div className="settings-layout">
        {showList && (
          <div id={SETTINGS_PANE_ID} className="settings-nav-slot" {...hiddenPaneAttributes(hidden)}>
          <nav ref={navRef} className="settings-nav" aria-label={t("settings:navLabel")} onKeyDown={onNavKeyDown}>
            <div className="settings-search">
              <Icon icon={Search} size={16} className="settings-search-icon" />
              <input
                ref={searchRef}
                id={searchId}
                type="search"
                className="settings-search-input"
                value={query}
                placeholder={t("settings:search.placeholder")}
                aria-label={t("settings:search.label")}
                autoComplete="off"
                spellCheck={false}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onSearchKeyDown}
              />
              {query !== "" && (
                <button
                  type="button"
                  className="settings-search-clear"
                  aria-label={t("settings:search.clear")}
                  onClick={() => {
                    setQuery("");
                    searchRef.current?.focus();
                  }}
                >
                  <Icon icon={X} size={14} />
                </button>
              )}
            </div>
            <p
              role="status"
              className={searching && resultCount === 0 ? "settings-nav-empty" : "settings-visually-hidden"}
            >
              {searching ? (resultCount === 0 ? t("settings:search.noResultsFor", { query: query.trim() }) : t("settings:search.resultCount", { count: resultCount })) : ""}
            </p>
            {groups.map((group) => {
              const titleId = `${searchId}-group-${group.id}`;
              return (
                <div key={group.id} className="settings-nav-group" role="group" aria-labelledby={titleId}>
                  <span id={titleId} className="settings-nav-group-title">{t(`settings:groups.${group.id}`)}</span>
                  <ul className="settings-nav-list">
                    {group.categories.map((name) => {
                      const target: SettingsRoute = { name: "settings", category: name };
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
                              <span className="settings-nav-label">{t(`settings:categories.${name}.label`)}</span>
                              {compact && <span className="settings-nav-description">{t(`settings:categories.${name}.description`)}</span>}
                            </span>
                            {compact && <Icon icon={ChevronRight} />}
                          </a>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </nav>
          </div>
        )}
        {category && (
          <div className="settings-content">
          <div className="settings-detail">
            {compact && (
              <Button
                variant="ghost"
                size="sm"
                className="settings-back"
                aria-label={t("settings:backLabel")}
                onClick={() => navigate(SETTINGS_ROOT)}
              >
                <Icon icon={ChevronLeft} />
                {t("settings:back")}
              </Button>
            )}
            <h2 ref={detailHeading} tabIndex={-1} className="settings-detail-title">{label}</h2>
            {renderCategory(category, user, onLogout)}
          </div>
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
    case "engines":
      return <EnginesSettings />;
    case "transcription":
      return <ProcessSettings process="transcription" />;
    case "speakers":
      return <ProcessSettings process="diarization" />;
    case "summaries":
      return <SummarySettings />;
  }
}
