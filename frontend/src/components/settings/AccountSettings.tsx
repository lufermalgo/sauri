import { User } from "lucide-react";
import { userInitials, type SessionUser } from "../../session-user";
import { Avatar, Button, Card, Icon } from "../ui";
import { t, useT } from "../../i18n";

interface AccountSettingsProps {
  user: SessionUser | null;
  onLogout: () => void;
}

/** Same rule as the profile card: the name leads when known and the email is never renamed. */
function accountLines(user: SessionUser | null): { primary: string; secondary: string | null } {
  const primary = user?.name ?? user?.email ?? t("settings:account.fallbackName");
  const secondary = user?.name && user.email && user.email !== user.name ? user.email : null;
  return { primary, secondary };
}

/** Read-only account details; only password sessions can sign out. */
export function AccountSettings({ user, onLogout }: AccountSettingsProps) {
  const { t } = useT();
  const { primary, secondary } = accountLines(user);
  return (
    <div className="settings-stack">
      <Card className="settings-card" aria-label={t("settings:categories.account.label")}>
        <div className="settings-account">
          <Avatar initials={user ? userInitials(user) : <Icon icon={User} />} color="var(--ds-accent-line)" />
          <div className="settings-account-text">
            <span className="settings-account-name">{primary}</span>
            {secondary && <span className="settings-account-email">{secondary}</span>}
          </div>
        </div>
        <p className="settings-help">{t(user?.mode === "local" ? "settings:account.localNote" : "settings:account.note")}</p>
      </Card>
      {user?.mode !== "local" && <Card className="settings-card" aria-labelledby="settings-session-title">
        <h3 id="settings-session-title" className="settings-card-title">{t("settings:account.session")}</h3>
        <p className="settings-help">{t("settings:account.sessionHelp")}</p>
        <div>
          <Button variant="secondary" onClick={onLogout}>{t("shell:logout")}</Button>
        </div>
      </Card>}
    </div>
  );
}
