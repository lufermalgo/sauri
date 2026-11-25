// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SIDE_COLUMN_MIN_PX,
  SIDE_COLUMN_STORAGE_KEY,
  SideColumnResizer,
  useSideColumnWidth,
} from "../SideColumnResizer";
import { t } from "../../i18n";

const BODY_WIDTH = 1200;
const DEFAULT_COLUMN_WIDTH = 400;

/** The meeting body as TranscriptView lays it out: the column's width follows --meeting-side-w. */
function Harness() {
  const { width, resize } = useSideColumnWidth();
  return <div data-testid="body">
    <aside data-testid="column" style={width === null ? undefined : { "--meeting-side-w": `${width}px` } as React.CSSProperties}>
      <SideColumnResizer width={width} onResize={resize} />
    </aside>
  </div>;
}

function rect(width: number): DOMRect {
  return { width, height: 600, top: 0, left: 0, right: width, bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
}

function columnWidth(): string {
  return screen.getByTestId("column").style.getPropertyValue("--meeting-side-w");
}

function createLocalStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

/** jsdom has no PointerEvent: a mouse event with a pointer id carries clientX and button like the real one. */
class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
  }
}

beforeEach(() => {
  vi.stubGlobal("localStorage", createLocalStorage());
  vi.stubGlobal("PointerEvent", TestPointerEvent);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.dataset.testid === "body") return rect(BODY_WIDTH);
    if (this.dataset.testid === "column") {
      const chosen = Number.parseFloat(this.style.getPropertyValue("--meeting-side-w"));
      return rect(Number.isFinite(chosen) ? chosen : DEFAULT_COLUMN_WIDTH);
    }
    return rect(0);
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SideColumnResizer", () => {
  it("widens the column when its edge is dragged left and remembers the width", () => {
    render(<Harness />);
    const handle = screen.getByRole("separator", { name: t("meeting:resizeSidePanel") });
    expect(handle).toHaveAttribute("aria-valuenow", String(DEFAULT_COLUMN_WIDTH));

    fireEvent.pointerDown(handle, { clientX: 800, button: 0, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 700, pointerId: 1 });
    expect(columnWidth()).toBe("500px");
    expect(localStorage.getItem(SIDE_COLUMN_STORAGE_KEY)).toBeNull();
    fireEvent.pointerUp(handle, { clientX: 700, pointerId: 1 });

    expect(localStorage.getItem(SIDE_COLUMN_STORAGE_KEY)).toBe("500");
    expect(handle).toHaveAttribute("aria-valuenow", "500");
  });

  it("keeps the width between the minimum and what leaves the player and transcript room", () => {
    render(<Harness />);
    const handle = screen.getByRole("separator");

    fireEvent.pointerDown(handle, { clientX: 800, button: 0, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 0, pointerId: 1 });
    // Capped at 720px (the 1200px body minus the 380px the main column keeps would allow 820px).
    expect(columnWidth()).toBe("720px");
    fireEvent.pointerMove(handle, { clientX: 1190, pointerId: 1 });
    expect(columnWidth()).toBe(`${SIDE_COLUMN_MIN_PX}px`);
    fireEvent.pointerUp(handle, { pointerId: 1 });
    expect(localStorage.getItem(SIDE_COLUMN_STORAGE_KEY)).toBe(String(SIDE_COLUMN_MIN_PX));
  });

  it("resizes with the arrow keys, Home and End", () => {
    render(<Harness />);
    const handle = screen.getByRole("separator");

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(columnWidth()).toBe("424px");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(columnWidth()).toBe("400px");
    fireEvent.keyDown(handle, { key: "Home" });
    expect(columnWidth()).toBe(`${SIDE_COLUMN_MIN_PX}px`);
    fireEvent.keyDown(handle, { key: "End" });
    expect(columnWidth()).toBe("720px");
    expect(localStorage.getItem(SIDE_COLUMN_STORAGE_KEY)).toBe("720");
  });

  it("opens with the remembered width and the default when nothing was chosen", () => {
    const first = render(<Harness />);
    expect(columnWidth()).toBe("");
    first.unmount();

    localStorage.setItem(SIDE_COLUMN_STORAGE_KEY, "520");
    render(<Harness />);
    expect(columnWidth()).toBe("520px");
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "520");
  });
});
