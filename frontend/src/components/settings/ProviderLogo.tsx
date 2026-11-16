import type { EngineProviderKind } from "@sauri/shared-types";
import { PROVIDER_LOGO_PATHS } from "../../assets/providers/logos";

interface ProviderLogoProps {
  kind: EngineProviderKind;
  /** Name the monogram is taken from when the provider has no mark of its own. */
  name: string;
  /** `md` is the 36px mark of a card; `sm` is the 20px one of chips, pickers and catalog rows. */
  size?: "sm" | "md";
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const letters = words.length > 1 ? `${words[0][0]}${words[1][0]}` : (words[0] ?? "?").slice(0, 1);
  return letters.toUpperCase();
}

/** Small identifier of a provider: its single-color mark, or a monogram when it has none. Decorative:
 * the provider's name is always written next to it. The marks only identify the provider (nominative use). */
export function ProviderLogo({ kind, name, size = "md" }: ProviderLogoProps) {
  const path = PROVIDER_LOGO_PATHS[kind];
  return (
    <span className={`engines-logo engines-logo--${size}`} aria-hidden="true">
      {path ? (
        <svg viewBox="0 0 24 24" focusable="false">
          <path d={path} fill="currentColor" />
        </svg>
      ) : (
        <span className="engines-logo-monogram">{initials(name)}</span>
      )}
    </span>
  );
}
