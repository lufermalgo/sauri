import type { EngineProviderKind } from "@sauri/shared-types";
import { PROVIDER_LOGOS, UNKNOWN_PROVIDER_GLYPH } from "../../assets/providers/logos";
import { Icon } from "../ui";

interface ProviderLogoProps {
  kind: EngineProviderKind;
  /** The provider's name, always written next to the logo by the caller; the logo itself never spells it. */
  name?: string;
  /** `md` is the 36px mark of a card; `sm` is the 22px one of chips, pickers and catalog rows. */
  size?: "sm" | "md";
}

/** Small identifier of a provider: its single-color mark or, when no mark can be used, a neutral glyph.
 * Decorative: the provider's name is always written next to it. The marks only identify the provider (nominative use). */
export function ProviderLogo({ kind, size = "md" }: ProviderLogoProps) {
  const source = PROVIDER_LOGOS[kind] ?? { glyph: UNKNOWN_PROVIDER_GLYPH };
  return (
    <span className={`engines-logo engines-logo--${size}`} aria-hidden="true">
      {"mark" in source ? (
        <svg viewBox="0 0 24 24" focusable="false">
          <path d={source.mark} fill="currentColor" />
        </svg>
      ) : (
        <Icon icon={source.glyph} className="engines-logo-glyph" />
      )}
    </span>
  );
}
