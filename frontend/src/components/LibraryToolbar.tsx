import { useEffect, useRef, useState } from "react";
import type { FocusEvent, KeyboardEvent, Ref } from "react";
import { ArrowUpDown, CalendarRange, Check, FilterX, Search, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { copy } from "../copy/es";
import type { LibraryQuery, LibrarySort } from "../library-query";
import { Button, Icon, Menu, MenuItem, Popover, TextField, useTooltip } from "./ui";
import { SelectAllCheckbox } from "./LibraryBulkBar";
import type { SelectAllState } from "./useLibrarySelection";

const text = copy.library.search;

const SORT_OPTIONS: Array<{ value: LibrarySort; label: string }> = [
  { value: "newest", label: text.sortNewest },
  { value: "oldest", label: text.sortOldest },
  { value: "title", label: text.sortTitle },
];

const TOOL_CLASS = "ui-icon-button ui-icon-button--ghost";

/** "YYYY-MM-DD" (the value of a date input) as "DD/MM/YYYY". */
function displayDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function toolClass(active: boolean): string {
  return active ? `${TOOL_CLASS} ui-icon-button--active` : TOOL_CLASS;
}

/** Icon-only button with an accessible name and a tooltip. */
function ToolButton({ label, icon, onClick, buttonRef }: {
  label: string;
  icon: LucideIcon;
  onClick: () => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  const tip = useTooltip(label);
  return (
    <span className="library-tool">
      <button ref={buttonRef} type="button" className={TOOL_CLASS} aria-label={label} {...tip.triggerProps}
        onClick={() => { tip.hide(); onClick(); }}>
        <Icon icon={icon} />
      </button>
      {tip.tooltip}
    </span>
  );
}

interface LibraryToolbarProps {
  query: LibraryQuery;
  onChange: (query: LibraryQuery) => void;
  /** The header checkbox: selects or deselects every row that is shown. */
  selectAll: { state: SelectAllState; disabled: boolean; onChange: () => void };
}

/**
 * Search, date range and sort as icon controls. Every control applies its value immediately,
 * as the labeled fields did; the search field stays open while it holds text.
 */
export function LibraryToolbar({ query, onChange, selectAll }: LibraryToolbarProps) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [focusTick, setFocusTick] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const searchButtonRef = useRef<HTMLButtonElement>(null);
  const expanded = searchOpen || query.text !== "";
  const dateRange = query.from !== null || query.to !== null;
  const filtersActive = query.text.trim() !== "" || dateRange;

  useEffect(() => {
    if (searchOpen) inputRef.current?.focus();
  }, [searchOpen]);

  // After the field collapses or the filters reset, the trigger takes the focus back.
  useEffect(() => {
    if (focusTick > 0) searchButtonRef.current?.focus();
  }, [focusTick]);

  const collapseSearch = () => {
    onChange({ ...query, text: "" });
    setSearchOpen(false);
    setFocusTick((tick) => tick + 1);
  };

  const clearFilters = () => {
    onChange({ ...query, text: "", from: null, to: null });
    setSearchOpen(false);
    setFocusTick((tick) => tick + 1);
  };

  const onSearchKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    collapseSearch();
  };

  // An empty field folds back into its icon once focus leaves it; one with text stays open.
  const onSearchBlur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget as Node | null;
    if (query.text === "" && !(next && event.currentTarget.contains(next))) setSearchOpen(false);
  };

  const sortLabel = SORT_OPTIONS.find((option) => option.value === query.sort)?.label ?? text.sortNewest;

  return (
    <div className="library-toolbar" role="search" aria-label={text.regionLabel} data-searching={expanded || undefined}>
      <SelectAllCheckbox className="library-selectall library-selectall--toolbar" state={selectAll.state}
        disabled={selectAll.disabled} onChange={selectAll.onChange} />
      {/* First, so the other icons keep their place when it appears. */}
      {filtersActive && <ToolButton label={text.clearFilters} icon={FilterX} onClick={clearFilters} />}
      {expanded ? (
        <div className="library-searchbox" onBlur={onSearchBlur}>
          <Icon icon={Search} className="library-searchbox-icon" />
          <input ref={inputRef} type="search" className="library-searchbox-input" aria-label={text.text}
            value={query.text} onKeyDown={onSearchKeyDown}
            onChange={(event) => onChange({ ...query, text: event.target.value })} />
          <button type="button" className={TOOL_CLASS} aria-label={text.closeSearch} onClick={collapseSearch}>
            <Icon icon={X} />
          </button>
        </div>
      ) : (
        <ToolButton label={text.text} icon={Search} buttonRef={searchButtonRef} onClick={() => setSearchOpen(true)} />
      )}
      <Popover className="library-tool" label={dateRange ? text.datesActive(
          query.from && displayDate(query.from), query.to && displayDate(query.to)) : text.dates}
        panelLabel={text.dates} trigger={<Icon icon={CalendarRange} />} triggerClassName={toolClass(dateRange)}>
        {(close) => (
          <>
            <TextField type="date" label={text.from} value={query.from ?? ""} max={query.to ?? undefined}
              onChange={(event) => onChange({ ...query, from: event.target.value || null })} />
            <TextField type="date" label={text.to} value={query.to ?? ""} min={query.from ?? undefined}
              onChange={(event) => onChange({ ...query, to: event.target.value || null })} />
            <Button variant="ghost" disabled={!dateRange}
              onClick={() => { onChange({ ...query, from: null, to: null }); close(); }}>
              {text.clear}
            </Button>
          </>
        )}
      </Popover>
      <Menu className="library-tool" label={text.sortCurrent(sortLabel)} tooltip trigger={<Icon icon={ArrowUpDown} />}
        triggerClassName={toolClass(query.sort !== "newest")}>
        {SORT_OPTIONS.map((option) => (
          <MenuItem key={option.value} checked={option.value === query.sort}
            onSelect={() => onChange({ ...query, sort: option.value })}>
            <span className="library-check">{option.value === query.sort && <Icon icon={Check} />}</span>
            {option.label}
          </MenuItem>
        ))}
      </Menu>
    </div>
  );
}
