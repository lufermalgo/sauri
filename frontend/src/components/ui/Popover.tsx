import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { FocusEvent, KeyboardEvent, ReactNode } from "react";
import { useTooltip } from "./Tooltip";

/** Minimum distance kept between an open panel and the viewport edges. */
const VIEWPORT_MARGIN_PX = 12;
const FOCUSABLE = 'input:not(:disabled), button:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])';

export type PopoverProps = {
  /** Accessible name and tooltip of the trigger; include the current state (e.g. the active range). */
  label: string;
  /** Accessible name of the panel; defaults to `label`. */
  panelLabel?: string;
  /** Content of the trigger button, usually an icon. */
  trigger: ReactNode;
  triggerClassName?: string;
  className?: string;
  /** The panel content; a function receives `close`, which returns focus to the trigger. */
  children: ReactNode | ((close: () => void) => ReactNode);
};

/** Non-modal popover for small forms (e.g. a date range). Enter, Space or ArrowDown on the trigger
 * opens it and moves focus to its first control; Escape closes it and returns focus to the trigger;
 * a click outside, or Tab leaving the panel, closes it without stealing focus. The panel is shifted
 * to stay inside the viewport. */
export function Popover({ label, panelLabel, trigger, triggerClassName, className, children }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const tip = useTooltip(label);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (open) panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  }, [open]);

  // Keeps the panel inside the viewport: it is anchored to the trigger, which can sit anywhere in the row.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !panel) return;
    panel.style.transform = "";
    const { left, right } = panel.getBoundingClientRect();
    const viewport = document.documentElement.clientWidth;
    let shift = 0;
    if (right > viewport - VIEWPORT_MARGIN_PX) shift = viewport - VIEWPORT_MARGIN_PX - right;
    if (left + shift < VIEWPORT_MARGIN_PX) shift = VIEWPORT_MARGIN_PX - left;
    if (shift !== 0) panel.style.transform = `translateX(${shift}px)`;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent | TouchEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    }
  };

  const onBlur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as Node | null;
    if (next && !rootRef.current?.contains(next)) setOpen(false);
  };

  return (
    <div className={className ? `ui-popover ${className}` : "ui-popover"} ref={rootRef}
      onKeyDown={onKeyDown} onBlur={onBlur}>
      <button ref={triggerRef} type="button" className={triggerClassName} aria-label={label}
        aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? panelId : undefined}
        {...tip.triggerProps}
        onClick={() => { tip.hide(); setOpen(value => !value); }}
        onKeyDown={event => {
          tip.triggerProps.onKeyDown?.(event);
          if (event.key === "ArrowDown" && !open) { event.preventDefault(); setOpen(true); }
        }}>
        {trigger}
      </button>
      {tip.tooltip}
      {open && (
        <div ref={panelRef} id={panelId} role="dialog" aria-label={panelLabel ?? label} className="ui-popover-panel">
          {typeof children === "function" ? children(() => close(true)) : children}
        </div>
      )}
    </div>
  );
}
