import { useEffect, useRef } from "react";
import type { Ref } from "react";
import { FileText, ScrollText, Trash2 } from "lucide-react";
import { copy } from "../copy/es";
import type { SelectAllState } from "./useLibrarySelection";
import { Button, Icon, useTooltip } from "./ui";

const text = copy.library.selection;

/** Checkbox that shows "some" as the indeterminate state. */
export function SelectAllCheckbox({ state, disabled, onChange, className }: {
  state: SelectAllState;
  disabled?: boolean;
  onChange: () => void;
  className?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (input.current) input.current.indeterminate = state === "some";
  }, [state]);
  return (
    <input ref={input} type="checkbox" className={className} aria-label={text.selectAll} disabled={disabled}
      checked={state === "all"} onChange={onChange} />
  );
}

/** Icon-only button with an accessible name and a tooltip. */
function BarIconButton({ label, icon, onClick }: { label: string; icon: typeof FileText; onClick: () => void }) {
  const tip = useTooltip(label);
  return (
    <span className="library-tool">
      <button type="button" aria-label={label} {...tip.triggerProps} className="ui-icon-button ui-icon-button--ghost"
        onClick={() => { tip.hide(); onClick(); }}>
        <Icon icon={icon} />
      </button>
      {tip.tooltip}
    </span>
  );
}

interface LibraryBulkBarProps {
  count: number;
  allState: SelectAllState;
  onToggleAll: () => void;
  onClear: () => void;
  onDownload: () => void;
  onDownloadSummaries: () => void;
  onDelete: () => void;
  headerRef: Ref<HTMLDivElement>;
}

/**
 * Replaces the list header and toolbar while recordings are selected: the count and a way out on
 * the header line, then select-all and the bulk actions on the toolbar line.
 */
export function LibraryBulkBar({ count, allState, onToggleAll, onClear, onDownload, onDownloadSummaries, onDelete, headerRef }: LibraryBulkBarProps) {
  return (
    <>
      <div ref={headerRef} tabIndex={-1} className="ui-pane-header library-bulk-header">
        <p role="status" className="ui-pane-title library-bulk-count">{text.count(count)}</p>
        <Button variant="ghost" size="sm" onClick={onClear}>{text.clear}</Button>
      </div>
      <div className="library-toolbar library-bulk-toolbar" role="toolbar" aria-label={text.toolbar}>
        <label className="library-selectall">
          <SelectAllCheckbox state={allState} onChange={onToggleAll} />
          <span>{text.selectAll}</span>
        </label>
        <BarIconButton label={text.downloadAll} icon={FileText} onClick={onDownload} />
        <BarIconButton label={text.downloadSummaries} icon={ScrollText} onClick={onDownloadSummaries} />
        <Button variant="ghost" size="sm" className="library-danger" onClick={onDelete}>
          <Icon icon={Trash2} size={16} />
          {text.deleteAll}
        </Button>
      </div>
    </>
  );
}
