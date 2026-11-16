import type { ReactNode } from "react";
import { Button } from "./ui";
import { useT } from "../i18n";

/**
 * One external sign-in option (e.g. "Continue with Google") shown below the password form.
 * `label` is user-facing text and must come from `frontend/src/locales/`.
 */
export interface LoginProvider {
  /** Stable key, e.g. "google". */
  id: string;
  /** Visible button text, e.g. t("login:continueWithGoogle"). */
  label: string;
  /** Decorative brand glyph shown before the label. */
  icon?: ReactNode;
  /** Starts the provider's sign-in flow. */
  onSelect: () => void;
}

/**
 * Providers enabled today. Empty on purpose: no external sign-in exists yet, so the area is not rendered.
 * To add Google: add its label to the login copy, append a `LoginProvider` here, and wire `onSelect`
 * to the backend flow. Nothing else in the login screen changes.
 */
export const ENABLED_LOGIN_PROVIDERS: readonly LoginProvider[] = [];

interface LoginProvidersProps {
  providers: readonly LoginProvider[];
  disabled?: boolean;
}

/** Separator plus one outlined button per provider; renders nothing when the list is empty. */
export function LoginProviders({ providers, disabled = false }: LoginProvidersProps) {
  const { t } = useT();
  if (providers.length === 0) return null;
  return (
    <div className="login-providers">
      <p className="login-separator">{t("login:providersSeparator")}</p>
      {providers.map((provider) => (
        <Button
          key={provider.id}
          variant="secondary"
          className="login-provider"
          disabled={disabled}
          onClick={provider.onSelect}
        >
          {provider.icon}
          {provider.label}
        </Button>
      ))}
    </div>
  );
}
