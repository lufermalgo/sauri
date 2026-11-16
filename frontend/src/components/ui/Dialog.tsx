import { useEffect, useId, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Icon } from "./Icon";
import { useTooltip } from "./Tooltip";

export type DialogProps = {
  title: string;
  /** Accessible name (and tooltip) of the close button. */
  closeLabel: string;
  onClose: () => void;
  size?: "sm" | "md";
  /** Element that takes focus on close. Defaults to the element focused when the dialog opened. */
  returnFocus?: () => HTMLElement | null;
  children: ReactNode;
};

const TABBABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

function tabbables(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(TABBABLE)).filter(element => !element.hidden);
}

/** Modal dialog rendered in a portal: centered panel with a fixed header and a scrolling body.
 * Mount it while open. Focus moves in on open, is trapped while open and returns on close;
 * Escape, the close button and a click on the backdrop call `onClose`. */
export function Dialog({ title, closeLabel, onClose, size = "md", returnFocus, children }: DialogProps) {
  const titleId = useId();
  const host = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const pressedBackdrop = useRef(false);
  const latest = useRef({ onClose, returnFocus });
  latest.current = { onClose, returnFocus };
  const closeTip = useTooltip(closeLabel);

  useEffect(() => {
    const panelElement = panel.current!;
    const hostElement = host.current!;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    tabbables(panelElement)[0]?.focus();

    // Everything else on the page becomes inert so no browser or assistive technology leaves the dialog.
    const inerted = Array.from(document.body.children).filter(element =>
      element !== hostElement && !element.hasAttribute("inert"));
    inerted.forEach(element => element.setAttribute("inert", ""));
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        latest.current.onClose();
      }
    };
    const onFocusIn = (event: FocusEvent) => {
      if (event.target instanceof Node && !panelElement.contains(event.target)) tabbables(panelElement)[0]?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("focusin", onFocusIn);
      document.body.style.overflow = previousOverflow;
      inerted.forEach(element => element.removeAttribute("inert"));
      const preferred = latest.current.returnFocus?.();
      (preferred?.isConnected ? preferred : opener?.isConnected ? opener : null)?.focus();
    };
  }, []);

  const wrapTab = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") return;
    const items = tabbables(panel.current!);
    if (items.length === 0) { event.preventDefault(); return; }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !panel.current!.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !panel.current!.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  };

  // A drag that starts in the panel and ends on the backdrop must not close the dialog.
  const onBackdropMouseDown = (event: MouseEvent<HTMLDivElement>) => { pressedBackdrop.current = event.target === event.currentTarget; };
  const onBackdropClick = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget && pressedBackdrop.current) onClose();
    pressedBackdrop.current = false;
  };

  return createPortal(
    <div ref={host} className="ui-modal-backdrop" onMouseDown={onBackdropMouseDown} onClick={onBackdropClick}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className={`ui-modal ui-modal--${size}`} onKeyDown={wrapTab}>
        <div className="ui-modal-header">
          <h2 id={titleId} className="ui-modal-title">{title}</h2>
          <span className="ui-modal-close">
            <button type="button" className="ui-icon-button ui-icon-button--quiet" aria-label={closeLabel}
              {...closeTip.triggerProps} onClick={onClose}>
              <Icon icon={X} />
            </button>
            {closeTip.tooltip}
          </span>
        </div>
        <div className="ui-modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
