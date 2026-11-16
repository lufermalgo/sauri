import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { FocusEvent, KeyboardEvent, ReactNode } from "react";

/** Delay before a tooltip appears (DESIGN.md section 7). */
export const TOOLTIP_DELAY_MS = 400;

function isKeyboardFocus(target: HTMLElement) {
  try {
    return target.matches(":focus-visible");
  } catch {
    // Engines without :focus-visible: treat every focus as keyboard focus.
    return true;
  }
}

type TooltipTriggerProps = {
  "aria-describedby"?: string;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  onFocus?: (event: FocusEvent<HTMLElement>) => void;
  onBlur?: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
};

/** Accessible tooltip for a control that already has its own name.
 * The tooltip complements the name: it is always in the DOM and linked with `aria-describedby`,
 * shown after a short delay on hover or keyboard focus, and dismissed with Escape. */
export function useTooltip(text: string | undefined) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const hide = useCallback(() => {
    clearTimeout(timer.current);
    setVisible(false);
  }, []);
  const showSoon = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setVisible(true), TOOLTIP_DELAY_MS);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  if (!text) return { triggerProps: {} as TooltipTriggerProps, hide, tooltip: null as ReactNode };
  return {
    hide,
    triggerProps: {
      "aria-describedby": id,
      onMouseEnter: showSoon,
      onMouseLeave: hide,
      onFocus: (event: FocusEvent<HTMLElement>) => { if (isKeyboardFocus(event.currentTarget)) showSoon(); },
      onBlur: hide,
      onKeyDown: (event: KeyboardEvent<HTMLElement>) => { if (event.key === "Escape") hide(); },
    } as TooltipTriggerProps,
    tooltip: <span id={id} role="tooltip" className="ui-tooltip" hidden={!visible}>{text}</span>,
  };
}
