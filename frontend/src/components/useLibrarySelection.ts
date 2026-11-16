import { useCallback, useEffect, useRef, useState } from "react";

export type SelectAllState = "none" | "some" | "all";

/** Ids between `from` and `to` (inclusive, either direction) in `order`; just `to` if `from` is not in it. */
export function rangeBetween(order: readonly string[], from: string, to: string): string[] {
  const start = order.indexOf(from);
  const end = order.indexOf(to);
  if (end < 0) return [];
  if (start < 0) return [to];
  return order.slice(Math.min(start, end), Math.max(start, end) + 1);
}

/**
 * Multi-selection of library rows, by id. `order` is the row order as rendered (what a shift range
 * follows); `knownIds` is every recording in the list, so ids that disappear (deleted elsewhere,
 * removed by a refresh) leave the selection.
 */
export function useLibrarySelection(order: readonly string[], knownIds: readonly string[]) {
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const anchor = useRef<string | null>(null);

  // Pruning keeps the same Set when nothing changed, so a quiet refresh does not re-render.
  useEffect(() => {
    const known = new Set(knownIds);
    setSelected((current) => {
      const kept = [...current].filter((id) => known.has(id));
      return kept.length === current.size ? current : new Set(kept);
    });
    if (anchor.current !== null && !known.has(anchor.current)) anchor.current = null;
  }, [knownIds]);

  const toggle = useCallback((id: string) => {
    anchor.current = id;
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }, []);

  /** Adds the rows from the last toggled one to `id`; without an anchor it just selects `id`. */
  const selectRange = useCallback((id: string) => {
    const from = anchor.current;
    setSelected((current) => new Set([...current, ...(from === null ? [id] : rangeBetween(order, from, id))]));
    if (from === null) anchor.current = id;
  }, [order]);

  const visibleSelected = order.filter((id) => selected.has(id)).length;
  const allState: SelectAllState = visibleSelected === 0 ? "none"
    : visibleSelected === order.length ? "all" : "some";

  /** Everything shown becomes selected; when it all is already, the shown rows are deselected. */
  const toggleAllVisible = useCallback(() => {
    anchor.current = null;
    setSelected((current) => {
      const everyShown = order.length > 0 && order.every((id) => current.has(id));
      const next = new Set(current);
      for (const id of order) {
        if (everyShown) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }, [order]);

  const clear = useCallback(() => {
    anchor.current = null;
    setSelected((current) => (current.size === 0 ? current : new Set()));
  }, []);

  const remove = useCallback((ids: readonly string[]) => {
    setSelected((current) => {
      if (!ids.some((id) => current.has(id))) return current;
      const next = new Set(current);
      for (const id of ids) next.delete(id);
      return next;
    });
  }, []);

  return { selected, allState, toggle, selectRange, toggleAllVisible, clear, remove };
}
