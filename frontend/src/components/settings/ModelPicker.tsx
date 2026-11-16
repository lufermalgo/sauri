import { forwardRef, useEffect, useId, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { FocusEvent, KeyboardEvent, ReactNode } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import type { EngineProviderKind } from "@sauri/shared-types";
import { Button, Icon } from "../ui";
import { ProviderLogo } from "./ProviderLogo";
import { useT } from "../../i18n";

const VIEWPORT_MARGIN_PX = 12;
const OPTION = '[role="option"]';

export interface PickerOption {
  /** Value handed back to `onSelect`. */
  key: string;
  label: string;
  /** Technical identifier or size, in monospace after the label. */
  detail?: string;
  inUse?: boolean;
  suggested?: boolean;
  /** Short word shown in the option, for example «Activo». */
  tag?: string;
}

export interface PickerGroup {
  id: string;
  label: string;
  /** Provider mark shown beside the group name. */
  logo?: { kind: EngineProviderKind; name: string };
  options: PickerOption[];
  /** `loading` while the provider's list is being asked for; `failed` leaves manual entry as the way in. */
  state?: "loading" | "ready" | "failed";
  /** A sentence under the group name: why the list is missing, or that it came from the cache. */
  note?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  refreshLabel?: string;
  /** Lets the person type a model name the provider did not list. */
  manual?: { onSubmit: (model: string) => void };
}

interface ModelPickerProps {
  /** Visible label of the field. */
  label: string;
  /** Id of the element that describes the field (the help line under it). */
  describedBy?: string;
  /** What the trigger shows today. */
  current: { title: string; detail?: string; logo?: { kind: EngineProviderKind; name: string } };
  groups: PickerGroup[];
  disabled?: boolean;
  onSelect: (groupId: string, optionKey: string) => void;
  /** Called when the panel opens or closes; the screen asks the providers for their lists on open. */
  onOpenChange?: (open: boolean) => void;
  /** Footer action, for example "Volver al local". */
  footer?: ReactNode | ((close: () => void) => ReactNode);
}

/** Lets the screen open the panel from elsewhere (the «Servicios externos» row of the local card). */
export interface ModelPickerHandle {
  open: () => void;
}

function matches(option: PickerOption, group: PickerGroup, needle: string): boolean {
  return `${option.label} ${option.detail ?? ""} ${group.label}`.toLowerCase().includes(needle);
}

/** One popover to choose an engine and its model: a search box, a group "En este equipo" and one group per
 * provider, with the one in use marked in words. It never saves: it reports the choice and the screen decides
 * (an external provider asks for the privacy notice first). Escape closes the popover and returns focus to
 * the trigger; arrow keys move through the options. */
export const ModelPicker = forwardRef<ModelPickerHandle, ModelPickerProps>(function ModelPicker(
  { label, describedBy, current, groups, disabled, onSelect, onOpenChange, footer },
  handle,
) {
  const { t } = useT();
  const ids = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const openChange = useRef(onOpenChange);
  openChange.current = onOpenChange;

  function show(next: boolean, restoreFocus = false) {
    setOpen(next);
    if (!next) {
      setQuery("");
      if (restoreFocus) triggerRef.current?.focus();
    }
  }

  useImperativeHandle(handle, () => ({
    open: () => {
      triggerRef.current?.scrollIntoView?.({ block: "nearest" });
      setOpen(true);
    },
  }));

  useEffect(() => {
    openChange.current?.(open);
  }, [open]);

  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  // The panel is as wide as the trigger; keep it inside the window on narrow screens.
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
      if (!rootRef.current?.contains(event.target as Node)) show(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
    };
  }, [open]);

  const needle = query.trim().toLowerCase();
  const shown = useMemo(
    () =>
      groups
        .map((group) => ({ group, options: needle ? group.options.filter((option) => matches(option, group, needle)) : group.options }))
        .filter(({ group, options }) => options.length > 0 || (!needle && (group.state !== undefined || group.manual !== undefined))),
    [groups, needle],
  );
  const optionCount = shown.reduce((total, entry) => total + entry.options.length, 0);

  function options(): HTMLElement[] {
    return Array.from(panelRef.current?.querySelectorAll<HTMLElement>(OPTION) ?? []);
  }

  function onPanelKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      show(false, true);
      return;
    }
    const active = document.activeElement as HTMLElement | null;
    const list = options();
    const index = active ? list.indexOf(active) : -1;
    const inSearch = active === searchRef.current;
    if (!inSearch && index < 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      (inSearch ? list[0] : list[Math.min(index + 1, list.length - 1)])?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (inSearch) return;
      (index === 0 ? searchRef.current : list[index - 1])?.focus();
    } else if (event.key === "Home" && !inSearch) {
      event.preventDefault();
      list[0]?.focus();
    } else if (event.key === "End" && !inSearch) {
      event.preventDefault();
      list[list.length - 1]?.focus();
    }
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget as Node | null;
    if (open && next && !rootRef.current?.contains(next)) show(false);
  }

  const labelId = `${ids}-label`;
  const valueId = `${ids}-value`;
  const panelId = `${ids}-panel`;

  return (
    <div className="engines-picker" ref={rootRef} onBlur={onBlur}>
      <span id={labelId} className="engines-picker-label">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        className="engines-picker-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-labelledby={`${labelId} ${valueId}`}
        aria-describedby={describedBy}
        disabled={disabled}
        onClick={() => show(!open)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            show(true);
          }
        }}
      >
        {current.logo && <ProviderLogo kind={current.logo.kind} name={current.logo.name} size="sm" />}
        <span id={valueId} className="engines-picker-value">
          <span className="engines-picker-title">{current.title}</span>
          {current.detail && <span className="engines-picker-detail">{current.detail}</span>}
        </span>
        <Icon icon={ChevronDown} className="engines-picker-chevron" />
      </button>

      {open && (
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-label={t("engines:process.pickerPanel")}
          className="engines-picker-panel"
          onKeyDown={onPanelKeyDown}
        >
          <label className="engines-picker-search">
            <Icon icon={Search} />
            <input
              ref={searchRef}
              type="search"
              aria-label={t("engines:process.pickerSearch")}
              placeholder={t("engines:process.pickerSearch")}
              value={query}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="engines-picker-list" role="listbox" aria-label={t("engines:process.pickerList")}>
            {shown.map(({ group, options: groupOptions }) => (
              <div key={group.id} role="group" aria-labelledby={`${ids}-${group.id}`} className="engines-picker-group">
                <div className="engines-picker-group-head">
                  {group.logo && <ProviderLogo kind={group.logo.kind} name={group.logo.name} size="sm" />}
                  <span id={`${ids}-${group.id}`} className="engines-picker-group-name">{group.label}</span>
                  {group.onRefresh && (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={group.refreshLabel}
                      disabled={group.refreshing}
                      onClick={group.onRefresh}
                    >
                      {group.refreshing ? t("engines:process.modelsRefreshing") : t("engines:process.modelsRefresh")}
                    </Button>
                  )}
                </div>
                {group.state === "loading" && groupOptions.length === 0 && (
                  <p role="status" className="engines-picker-note">{t("engines:process.modelsLoading")}</p>
                )}
                {group.note && <p className="engines-picker-note">{group.note}</p>}
                {groupOptions.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    role="option"
                    aria-selected={option.inUse === true}
                    tabIndex={-1}
                    className="engines-picker-option"
                    onClick={() => {
                      show(false, true);
                      onSelect(group.id, option.key);
                    }}
                  >
                    <span className="engines-picker-option-name">{option.label}</span>
                    {option.detail && <span className="engines-picker-option-detail">{option.detail}</span>}
                    {option.suggested && <span className="engines-picker-mark">{t("engines:process.suggested")}</span>}
                    {option.tag && <span className="engines-picker-mark">{option.tag}</span>}
                    {option.inUse && (
                      <span className="engines-picker-mark engines-picker-mark--use">
                        <Icon icon={Check} size={12} />
                        {t("engines:process.inUse")}
                      </span>
                    )}
                  </button>
                ))}
                {group.manual && !needle && <ManualModel onSubmit={(model) => { show(false, true); group.manual!.onSubmit(model); }} />}
              </div>
            ))}
            {optionCount === 0 && needle && <p role="status" className="engines-picker-note">{t("engines:process.noMatches")}</p>}
          </div>
          {footer && <div className="engines-picker-footer">{typeof footer === "function" ? footer(() => show(false, true)) : footer}</div>}
        </div>
      )}
    </div>
  );
});

/** Text field for a provider that gave no list: the person types the model name exactly as the provider shows it. */
function ManualModel({ onSubmit }: { onSubmit: (model: string) => void }) {
  const { t } = useT();
  const id = useId();
  const [value, setValue] = useState("");
  const submit = () => value.trim() && onSubmit(value.trim());
  return (
    <div className="engines-picker-manual">
      <label htmlFor={id}>{t("engines:process.manualModel")}</label>
      <div className="engines-picker-manual-row">
        <input
          id={id}
          className="ui-input"
          value={value}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={`${id}-help`}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              submit();
            }
          }}
        />
        <Button variant="secondary" size="sm" disabled={!value.trim()} onClick={submit}>{t("engines:process.manualModelUse")}</Button>
      </div>
      <span id={`${id}-help`} className="settings-help">{t("engines:process.manualModelHelp")}</span>
    </div>
  );
}
