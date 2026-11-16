import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { useTooltip } from "./Tooltip";

type MenuContextValue = { close: () => void };
const MenuContext = createContext<MenuContextValue | null>(null);

export type MenuProps = {
  label: string;
  triggerLabel?: string;
  triggerVariant?: "icon" | "primary" | "secondary";
  /** Custom trigger content (e.g. a profile card). The caller styles it through `triggerClassName`. */
  trigger?: ReactNode;
  triggerClassName?: string;
  className?: string;
  /** Shows `label` as a tooltip on the trigger (hover and keyboard focus). */
  tooltip?: boolean;
  /** Tab order of the trigger; -1 for a control reached with the arrow keys of a roving list. */
  triggerTabIndex?: number;
  children: ReactNode;
};

/** Visible vertical range of the trigger's nearest scroll or clipping ancestor, within the window. */
function visibleRange(element: HTMLElement): { top: number; bottom: number } {
  let top = 0;
  let bottom = window.innerHeight;
  for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
    const overflow = window.getComputedStyle(parent).overflowY;
    if (overflow === "auto" || overflow === "scroll" || overflow === "hidden") {
      const rect = parent.getBoundingClientRect();
      top = Math.max(top, rect.top);
      bottom = Math.min(bottom, rect.bottom);
    }
  }
  return { top, bottom };
}

export function Menu({ label, triggerLabel, triggerVariant = "icon", trigger, triggerClassName, className, tooltip, triggerTabIndex, children }: MenuProps) {
  const [open, setOpen] = useState(false);
  const [opensUp, setOpensUp] = useState(false);
  const tip = useTooltip(tooltip ? label : undefined);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<"first" | "last" | null>(null);
  const panelId = useId();

  const items = () => Array.from(panelRef.current?.querySelectorAll<HTMLElement>(
    '[role="menuitem"]:not([aria-disabled="true"]), [role="menuitemradio"]:not([aria-disabled="true"])') ?? []);

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  const openMenu = (focus: "first" | "last") => {
    pendingFocus.current = focus;
    setOpen(true);
  };

  // A menu opened near the bottom of a scrolling pane opens upward instead of being clipped.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    const trigger = triggerRef.current;
    if (!open || !panel || !trigger) { setOpensUp(false); return; }
    const range = visibleRange(trigger);
    const rect = trigger.getBoundingClientRect();
    const below = range.bottom - rect.bottom;
    const above = rect.top - range.top;
    setOpensUp(below < panel.offsetHeight && above > below);
  }, [open]);

  useEffect(() => {
    if (!open || !pendingFocus.current) return;
    const list = items();
    (pendingFocus.current === "last" ? list[list.length - 1] : list[0])?.focus();
    pendingFocus.current = null;
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

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openMenu("first");
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openMenu("last");
    }
  };

  const onPanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const list = items();
    const index = list.indexOf(document.activeElement as HTMLElement);
    let next: number | null = null;
    switch (event.key) {
      case "ArrowDown": next = (index + 1) % list.length; break;
      case "ArrowUp": next = (index <= 0 ? list.length : index) - 1; break;
      case "Home": next = 0; break;
      case "End": next = list.length - 1; break;
      case "Escape":
        event.preventDefault();
        close(true);
        return;
      case "Tab":
        close(false);
        return;
      default:
        return;
    }
    event.preventDefault();
    list[next]?.focus();
  };

  return (
    <div className={className ? `ui-menu ${className}` : "ui-menu"} ref={rootRef}>
      <button ref={triggerRef} type="button"
        className={trigger ? triggerClassName : `ui-menu-trigger ui-menu-trigger--${triggerLabel ? triggerVariant : "icon"}`} aria-label={label} tabIndex={triggerTabIndex}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? panelId : undefined}
        {...tip.triggerProps}
        onClick={() => { tip.hide(); if (open) close(false); else openMenu("first"); }}
        onKeyDown={event => { tip.triggerProps.onKeyDown?.(event); onTriggerKeyDown(event); }}>
        {trigger ? trigger : triggerLabel ? (
          <>
            <span>{triggerLabel}</span>
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true" focusable="false">
              <path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"
                strokeLinejoin="round" />
            </svg>
          </>
        ) : (
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
            <circle cx="4" cy="9" r="1.6" fill="currentColor" />
            <circle cx="9" cy="9" r="1.6" fill="currentColor" />
            <circle cx="14" cy="9" r="1.6" fill="currentColor" />
          </svg>
        )}
      </button>
      {tip.tooltip}
      {open && (
        <MenuContext.Provider value={{ close: () => close(true) }}>
          <div ref={panelRef} id={panelId} role="menu" aria-label={label} className={opensUp ? "ui-menu-panel ui-menu-panel--up" : "ui-menu-panel"}
            onKeyDown={onPanelKeyDown}>
            {children}
          </div>
        </MenuContext.Provider>
      )}
    </div>
  );
}

export type MenuItemProps = {
  onSelect: () => void;
  /** Native tooltip and description, e.g. why a disabled item is unavailable. */
  hint?: string;
  tone?: "default" | "danger";
  disabled?: boolean;
  /** Makes the item a radio-like choice (`menuitemradio`) that reports whether it is the selected one. */
  checked?: boolean;
  children: ReactNode;
};

export function MenuItem({ onSelect, hint, tone = "default", disabled = false, checked, children }: MenuItemProps) {
  const menu = useContext(MenuContext);
  return (
    <button type="button" role={checked === undefined ? "menuitem" : "menuitemradio"} tabIndex={-1}
      className={`ui-menu-item ui-menu-item--${tone}`}
      title={hint} aria-checked={checked} aria-disabled={disabled || undefined}
      onClick={() => {
        if (disabled) return;
        onSelect();
        menu?.close();
      }}>
      {children}
    </button>
  );
}

/** Thin rule between groups of items; not focusable, so arrow keys skip it. */
export function MenuSeparator() {
  return <div role="separator" className="ui-menu-separator" />;
}
