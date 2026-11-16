import type { ReactNode } from "react";
import { useTooltip } from "./ui";
import { useT } from "../i18n";

/**
 * Text link for a login option that does not work yet. It stays visible in grey, as the reference shows it,
 * and does nothing: `aria-disabled="true"`, no `href`, no click action.
 *
 * Accessible pattern: it remains focusable (tabindex 0) and `aria-describedby` points to the tooltip text
 * "Coming soon". A native `disabled` or a removed tab stop would hide it from keyboard and screen-reader users,
 * who could not learn that the option exists or why it is unavailable. The tooltip is shown on hover and keyboard focus;
 * on touch screens the grey look is the cue.
 */
export function SoonLink({ children }: { children: ReactNode }) {
  const { t } = useT();
  const tip = useTooltip(t("login:soon"), { className: "login-soon-tip" });
  return (
    <span className="login-soon-wrap">
      <a role="link" tabIndex={0} aria-disabled="true" className="login-link" {...tip.triggerProps}>
        {children}
      </a>
      {tip.tooltip}
    </span>
  );
}
