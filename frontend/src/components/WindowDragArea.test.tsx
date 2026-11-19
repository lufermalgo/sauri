// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render } from "@testing-library/react";
import type { SauriDesktop, WindowState } from "../desktop-bridge";
import { WindowDragArea } from "./WindowDragArea";

let push: (state: WindowState) => void = () => undefined;

function installBridge(titleBar: "inset" | "native") {
  window.sauriDesktop = {
    titleBar,
    getWindowState: vi.fn(async () => ({ fullScreen: false })),
    onWindowState: (listener: (state: WindowState) => void) => {
      push = listener;
      return () => undefined;
    },
  } as unknown as SauriDesktop;
}

afterEach(() => {
  cleanup();
  delete window.sauriDesktop;
});

describe("WindowDragArea", () => {
  it("is not there in a normal browser or with the system's title bar", () => {
    expect(render(<WindowDragArea />).container).toBeEmptyDOMElement();
    cleanup();
    installBridge("native");
    expect(render(<WindowDragArea />).container).toBeEmptyDOMElement();
  });

  it("moves the window from the top edge on a Mac, except in full screen", async () => {
    installBridge("inset");
    const { container } = render(<WindowDragArea />);
    await act(async () => undefined);
    expect(container.querySelector(".window-drag-area")).not.toBeNull();
    act(() => push({ fullScreen: true }));
    expect(container).toBeEmptyDOMElement();
  });
});
