import type { ReactNode } from "react";
import { GoogleGlyph } from "../assets/providers/GoogleGlyph";
import { Button, useTooltip } from "./ui";
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
  /**
   * Starts the provider's sign-in flow. Without it the option is "coming soon": it is shown in grey,
   * `aria-disabled`, focusable with a "Coming soon" tooltip, and does nothing.
   */
  onSelect?: () => void;
}

/**
 * Flag for Google sign-in. `undefined` keeps the button visible but inactive ("coming soon").
 * To turn it on, set this to the function that starts the backend flow; nothing else in the login screen changes.
 */
export const startGoogleSignIn: (() => void) | undefined = undefined;

/** Providers shown today, with their labels in the current language. */
export function useLoginProviders(): readonly LoginProvider[] {
  const { t } = useT();
  return [{ id: "google", label: t("login:continueWithGoogle"), icon: <GoogleGlyph />, onSelect: startGoogleSignIn }];
}

interface LoginProvidersProps {
  providers: readonly LoginProvider[];
  /** Disables the working options while a sign-in is in progress. */
  disabled?: boolean;
}

function ProviderButton({ provider, disabled }: { provider: LoginProvider; disabled: boolean }) {
  const { t } = useT();
  const soon = !provider.onSelect;
  const tip = useTooltip(soon ? t("login:soon") : undefined, { className: "login-soon-tip" });
  // A "coming soon" option keeps its tab stop and uses aria-disabled (not `disabled`) so its tooltip stays reachable.
  return (
    <span className="login-soon-wrap">
      <Button
        variant="secondary"
        className="login-provider"
        disabled={!soon && disabled}
        aria-disabled={soon ? "true" : undefined}
        onClick={soon ? undefined : provider.onSelect}
        {...tip.triggerProps}
      >
        {provider.icon}
        {provider.label}
      </Button>
      {tip.tooltip}
    </span>
  );
}

/** Separator plus one outlined button per provider; renders nothing when the list is empty. */
export function LoginProviders({ providers, disabled = false }: LoginProvidersProps) {
  const { t } = useT();
  if (providers.length === 0) return null;
  return (
    <div className="login-providers">
      <p className="login-separator">{t("login:providersSeparator")}</p>
      {providers.map((provider) => (
        <ProviderButton key={provider.id} provider={provider} disabled={disabled} />
      ))}
    </div>
  );
}
