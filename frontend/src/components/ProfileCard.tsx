import type { MouseEvent } from "react";
import { Settings, User } from "lucide-react";
import { routePath, type Route } from "../router";
import { userInitials, type SessionUser } from "../session-user";
import { Avatar, Icon, Menu, MenuItem, useTooltip } from "./ui";
import type { SecondaryPaneControl } from "./useSecondaryPane";
import { t, useT } from "../i18n";

interface ProfileCardProps {
  user: SessionUser | null;
  route: Route;
  /** The settings categories pane when it can be hidden (on settings, two panes): the gear toggles it. */
  settingsPane?: SecondaryPaneControl | null;
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, target: Route) => void;
  onLogout: () => void;
}

const SETTINGS_ROUTE: Route = { name: "settings" };

/** Display lines: the name leads when known, the email never gets replaced by an invented name. */
function profileLines(user: SessionUser | null): { primary: string; secondary: string | null } {
  const primary = user?.name ?? user?.email ?? t("shell:profile.fallbackName");
  const secondary = user?.name && user.email && user.email !== user.name ? user.email : null;
  return { primary, secondary };
}

/** Account card at the bottom of the sidebar: a menu with sign-out plus the settings link. */
export function ProfileCard({ user, route, settingsPane = null, onNavigate, onLogout }: ProfileCardProps) {
  const { t } = useT();
  const { primary, secondary } = profileLines(user);
  const menuLabel = user ? t("shell:profile.menu", { account: secondary ? `${primary}, ${secondary}` : primary }) : primary;
  const settingsActive = route.name === "settings";
  const gearTip = useTooltip(settingsPane ? (settingsPane.hidden ? t("shell:settingsPane.show") : t("shell:settingsPane.hide")) : undefined);

  return (
    <div className="shell-profile">
      <Menu
        className="shell-profile-menu"
        triggerClassName="shell-profile-trigger"
        label={menuLabel}
        trigger={
          <>
            <Avatar initials={user ? userInitials(user) : <Icon icon={User} />} color="var(--ds-accent)" />
            <span className="shell-collapsible shell-profile-text">
              <span className="shell-profile-name">{primary}</span>
              {secondary && <span className="shell-profile-email">{secondary}</span>}
            </span>
          </>
        }
      >
        <MenuItem onSelect={onLogout}>{t("shell:logout")}</MenuItem>
      </Menu>
      {settingsPane ? (
        <span className="shell-gear-wrap">
          <button
            type="button"
            className="shell-gear"
            aria-label={t("shell:profile.settings")}
            aria-current="page"
            aria-expanded={!settingsPane.hidden}
            aria-controls={settingsPane.id}
            {...gearTip.triggerProps}
            onClick={() => { gearTip.hide(); settingsPane.toggle(); }}
          >
            <Icon icon={Settings} />
          </button>
          {gearTip.tooltip}
        </span>
      ) : (
        <a
          className="shell-gear"
          href={routePath(SETTINGS_ROUTE)}
          aria-label={t("shell:profile.settings")}
          aria-current={settingsActive ? "page" : undefined}
          onClick={(event) => onNavigate(event, SETTINGS_ROUTE)}
        >
          <Icon icon={Settings} />
          <span className="shell-tip-only" aria-hidden="true">{t("shell:profile.settings")}</span>
        </a>
      )}
    </div>
  );
}
