import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useT } from "../i18n";

/**
 * Width of the meeting's notes column (summary and chat), chosen by dragging its left edge and remembered
 * per device. The limits keep the notes readable and leave the player and transcript enough room.
 */
export const SIDE_COLUMN_STORAGE_KEY = "sauri_meeting_side_width";
export const SIDE_COLUMN_MIN_PX = 280;
export const SIDE_COLUMN_MAX_PX = 720;
/** Room the player and transcript keep beside the column. */
export const MAIN_COLUMN_MIN_PX = 380;
const KEYBOARD_STEP_PX = 24;

function readStoredWidth(): number | null {
  try {
    const stored = Number(localStorage.getItem(SIDE_COLUMN_STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0 ? stored : null;
  } catch {
    return null; // blocked storage: the column starts at its default width
  }
}

function storeWidth(width: number): void {
  try {
    localStorage.setItem(SIDE_COLUMN_STORAGE_KEY, String(width));
  } catch {
    // blocked storage: the width lasts for this visit only
  }
}

/** The widest the column may be when the meeting body is `bodyWidth` wide. */
export function maxSideColumnWidth(bodyWidth: number): number {
  return Math.max(SIDE_COLUMN_MIN_PX, Math.min(SIDE_COLUMN_MAX_PX, bodyWidth - MAIN_COLUMN_MIN_PX));
}

/** The chosen width (null until the user picks one) and a setter that keeps it within the limits. */
export function useSideColumnWidth() {
  const [width, setWidth] = useState<number | null>(readStoredWidth);
  const resize = useCallback((next: number, bodyWidth: number, persist: boolean) => {
    const clamped = Math.round(Math.min(maxSideColumnWidth(bodyWidth), Math.max(SIDE_COLUMN_MIN_PX, next)));
    setWidth(clamped);
    if (persist) storeWidth(clamped);
  }, []);
  return { width, resize };
}

interface SideColumnResizerProps {
  /** Called with the new width, the meeting body's width and whether the choice is final (to remember it). */
  onResize: (width: number, bodyWidth: number, persist: boolean) => void;
  width: number | null;
}

/** The drag handle on the column's left edge; a separator that also moves with the arrow keys. */
export function SideColumnResizer({ onResize, width }: SideColumnResizerProps) {
  const { t } = useT();
  const handleRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ startX: number; startWidth: number; bodyWidth: number; lastWidth: number } | null>(null);
  const [measured, setMeasured] = useState<{ width: number; max: number } | null>(null);

  function sizes() {
    const column = handleRef.current?.parentElement;
    const body = column?.parentElement;
    return { columnWidth: column?.getBoundingClientRect().width ?? 0, bodyWidth: body?.getBoundingClientRect().width ?? 0 };
  }

  // The separator announces the column's real width, also before the user has chosen one.
  useLayoutEffect(() => {
    const { columnWidth, bodyWidth } = sizes();
    setMeasured({ width: Math.round(columnWidth), max: maxSideColumnWidth(bodyWidth) });
  }, [width]);

  function onPointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault();
    const { columnWidth, bodyWidth } = sizes();
    drag.current = { startX: event.clientX, startWidth: columnWidth, bodyWidth, lastWidth: columnWidth };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    document.body.classList.add("meeting-resizing");
  }

  function onPointerMove(event: React.PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current) return;
    // The handle is on the left edge: moving left widens the column.
    current.lastWidth = current.startWidth + current.startX - event.clientX;
    onResize(current.lastWidth, current.bodyWidth, false);
  }

  function endDrag() {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    document.body.classList.remove("meeting-resizing");
    onResize(current.lastWidth, current.bodyWidth, true);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const { columnWidth, bodyWidth } = sizes();
    const steps: Record<string, number> = {
      ArrowLeft: columnWidth + KEYBOARD_STEP_PX,
      ArrowRight: columnWidth - KEYBOARD_STEP_PX,
      Home: SIDE_COLUMN_MIN_PX,
      End: SIDE_COLUMN_MAX_PX,
    };
    const next = steps[event.key];
    if (next === undefined) return;
    event.preventDefault();
    onResize(next, bodyWidth, true);
  }

  return <div ref={handleRef} className="meeting-side-resizer" role="separator" aria-orientation="vertical"
    aria-label={t("meeting:resizeSidePanel")} tabIndex={0}
    aria-valuemin={SIDE_COLUMN_MIN_PX} aria-valuemax={measured?.max ?? SIDE_COLUMN_MAX_PX}
    aria-valuenow={width ?? measured?.width ?? undefined}
    onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}
    onLostPointerCapture={endDrag} onKeyDown={onKeyDown} />;
}
