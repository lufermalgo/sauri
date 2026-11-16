import React, { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, type LucideIcon } from "lucide-react";
import { Icon } from "../../core/design/Icon";

export interface MenuOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
  disabled?: boolean;
  title?: string;
}

export interface MenuButtonProps<T extends string> {
  options: MenuOption<T>[];
  value: T | undefined;
  onSelect: (value: T) => void;
  /** Accessible name of the menu itself. */
  menuLabel: string;
  /** Accessible name of the trigger; omit to name it from its visible content. */
  triggerLabel?: string;
  title?: string;
  disabled?: boolean;
  className?: string;
  children: React.ReactNode;
}

/** Single-choice menu button: Enter, Space and the arrows open it, Escape closes it and returns focus. */
export function MenuButton<T extends string>({ options, value, onSelect, menuLabel, triggerLabel, title, disabled, className, children }: MenuButtonProps<T>) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const items = () => Array.from(rootRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not(:disabled)') ?? []);

  useEffect(() => {
    if (!open) return;
    const selected = rootRef.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"]:not(:disabled)');
    (selected ?? items()[0])?.focus();
    const close = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);

  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  const closeAndReturn = () => { setOpen(false); triggerRef.current?.focus(); };
  const move = (event: React.KeyboardEvent, target: (list: HTMLButtonElement[], index: number) => number) => {
    const list = items();
    if (list.length === 0) return;
    event.preventDefault();
    list[target(list, list.indexOf(document.activeElement as HTMLButtonElement))]?.focus();
  };
  const onMenuKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") move(event, (list, index) => (index + 1) % list.length);
    else if (event.key === "ArrowUp") move(event, (list, index) => (index <= 0 ? list.length - 1 : index - 1));
    else if (event.key === "Home") move(event, () => 0);
    else if (event.key === "End") move(event, list => list.length - 1);
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeAndReturn(); }
    else if (event.key === "Tab") setOpen(false);
  };

  return <span className="panel-menu-root" ref={rootRef}>
    <button ref={triggerRef} type="button" className={className} disabled={disabled} title={title} aria-label={triggerLabel}
      aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined}
      onClick={() => setOpen(current => !current)}
      onKeyDown={event => { if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); } }}>
      {children}
      <Icon icon={ChevronDown} size={14} className="panel-chevron" />
    </button>
    {open && <ul id={menuId} className="panel-menu" role="menu" aria-label={menuLabel} onKeyDown={onMenuKeyDown}>
      {options.map(option => <li key={option.value} role="none">
        <button type="button" role="menuitemradio" aria-checked={option.value === value} tabIndex={-1} disabled={option.disabled} title={option.title}
          onClick={() => { onSelect(option.value); closeAndReturn(); }}>
          {option.icon && <Icon icon={option.icon} size={16} />}
          <span className="panel-ellipsis">{option.label}</span>
          {option.value === value && <Icon icon={Check} size={16} className="panel-menu-check" />}
        </button>
      </li>)}
    </ul>}
  </span>;
}
