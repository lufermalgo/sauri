import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent } from "react";
import { X } from "lucide-react";
import { Icon, useTooltip } from "./ui";
import { SpeakerReviewPanel, type SpeakerReviewPanelProps } from "./SpeakerReviewPanel";
import { useT } from "../i18n";

const TABBABLE = 'button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])';

/** Moves focus to the first control of a mounted dock (the entry point uses it when the panel is already open). */
export function focusSpeakerDock(dock: HTMLElement | null) {
  dock?.querySelector<HTMLElement>(TABBABLE)?.focus();
}

interface SpeakerDockProps extends SpeakerReviewPanelProps {
  onClose: () => void;
  /** Takes focus on mount: set when the user just opened the panel, not when it was restored. */
  focusOnMount: boolean;
}

/**
 * The speaker naming panel, docked beside the video (or under it on narrow screens). It is not a
 * dialog: no backdrop, no focus trap, and the page and the player keep working while it is open.
 */
export function SpeakerDock({ onClose, focusOnMount, ...panel }: SpeakerDockProps) {
  const { t } = useT();
  const headingId = useId();
  const dockRef = useRef<HTMLElement>(null);
  const closeTip = useTooltip(t("speakerReview:close"));

  useEffect(() => {
    if (focusOnMount) focusSpeakerDock(dockRef.current);
    // Only the first render decides: a later prop change must not pull focus back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    // An edit that handled Escape (cancelling itself) has already prevented the default.
    if (event.key === "Escape" && !event.defaultPrevented) {
      event.preventDefault();
      onClose();
    }
  }

  return <aside ref={dockRef} className="meeting-dock" aria-labelledby={headingId} onKeyDown={onKeyDown}>
    <div className="meeting-dock-inner">
      <div className="meeting-dock-header">
        <h2 id={headingId} className="meeting-dock-title">{t("speakerReview:heading")}</h2>
        <span className="meeting-dock-close">
          <button type="button" className="ui-icon-button ui-icon-button--ghost" aria-label={t("speakerReview:close")}
            {...closeTip.triggerProps} onClick={() => { closeTip.hide(); onClose(); }}>
            <Icon icon={X} size={16} />
          </button>
          {closeTip.tooltip}
        </span>
      </div>
      <div className="meeting-dock-body"><SpeakerReviewPanel {...panel} /></div>
    </div>
  </aside>;
}
