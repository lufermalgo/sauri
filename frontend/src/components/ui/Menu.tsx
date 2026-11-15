import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

type MenuContextValue = { close: () => void };
const MenuContext = createContext<MenuContextValue | null>(null);

export type MenuProps = {
  label: string;
  children: ReactNode;
};

export function Menu({ label, children }: MenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef<"first" | "last" | null>(null);
  const panelId = useId();

  const items = () => Array.from(panelRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }, []);

  const openMenu = (focus: "first" | "last") => {
    pendingFocus.current = focus;
    setOpen(true);
  };

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
    <div className="ui-menu" ref={rootRef}>
      <button ref={triggerRef} type="button" className="ui-menu-trigger" aria-label={label}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? panelId : undefined}
        onClick={() => (open ? close(false) : openMenu("first"))} onKeyDown={onTriggerKeyDown}>
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" focusable="false">
          <circle cx="4" cy="9" r="1.6" fill="currentColor" />
          <circle cx="9" cy="9" r="1.6" fill="currentColor" />
          <circle cx="14" cy="9" r="1.6" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <MenuContext.Provider value={{ close: () => close(true) }}>
          <div ref={panelRef} id={panelId} role="menu" aria-label={label} className="ui-menu-panel"
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
  tone?: "default" | "danger";
  children: ReactNode;
};

export function MenuItem({ onSelect, tone = "default", children }: MenuItemProps) {
  const menu = useContext(MenuContext);
  return (
    <button type="button" role="menuitem" tabIndex={-1} className={`ui-menu-item ui-menu-item--${tone}`}
      onClick={() => {
        onSelect();
        menu?.close();
      }}>
      {children}
    </button>
  );
}
