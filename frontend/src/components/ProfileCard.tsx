import type { MouseEvent } from "react";
import { Settings, User } from "lucide-react";
import { copy } from "../copy/es";
import { routePath, type Route } from "../router";
import { userInitials, type SessionUser } from "../session-user";
import { Avatar, Icon, Menu, MenuItem } from "./ui";

interface ProfileCardProps {
  user: SessionUser | null;
  route: Route;
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, target: Route) => void;
  onLogout: () => void;
}

const SETTINGS_ROUTE: Route = { name: "settings" };

/** Display lines: the name leads when known, the email never gets replaced by an invented name. */
function profileLines(user: SessionUser | null): { primary: string; secondary: string | null } {
  const primary = user?.name ?? user?.email ?? copy.shell.profile.fallbackName;
  const secondary = user?.name && user.email && user.email !== user.name ? user.email : null;
  return { primary, secondary };
}

/** Account card at the bottom of the sidebar: a menu with sign-out plus the settings link. */
export function ProfileCard({ user, route, onNavigate, onLogout }: ProfileCardProps) {
  const { primary, secondary } = profileLines(user);
  const menuLabel = user ? copy.shell.profile.menu(secondary ? `${primary}, ${secondary}` : primary) : primary;
  const settingsActive = route.name === "settings";

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
        <MenuItem onSelect={onLogout}>{copy.shell.logout}</MenuItem>
      </Menu>
      <a
        className="shell-gear"
        href={routePath(SETTINGS_ROUTE)}
        aria-label={copy.shell.profile.settings}
        aria-current={settingsActive ? "page" : undefined}
        onClick={(event) => onNavigate(event, SETTINGS_ROUTE)}
      >
        <Icon icon={Settings} />
        <span className="shell-tip-only" aria-hidden="true">{copy.shell.profile.settings}</span>
      </a>
    </div>
  );
}
