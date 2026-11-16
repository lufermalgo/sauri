// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PortalShell } from "./PortalShell";
import { copy } from "../copy/es";

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

describe("PortalShell", () => {
  it("returns to the library from the upload route without reloading", () => {
    const listener = vi.fn();
    window.addEventListener("sauri:navigate", listener);
    render(<PortalShell route={{ name: "upload" }} onLogout={vi.fn()}>content</PortalShell>);

    fireEvent.click(screen.getByRole("link", { name: copy.shell.library }));
    expect(window.location.pathname).toBe("/");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("sauri:navigate", listener);
  });

  it("leaves modified clicks to the browser", () => {
    render(<PortalShell route={{ name: "library" }} onLogout={vi.fn()}>content</PortalShell>);
    const link = screen.getByRole("link", { name: copy.shell.library });
    // jsdom cannot navigate: record whether the component cancelled the browser default.
    let componentPrevented: boolean | null = null;
    const onWindowClick = (event: Event) => {
      componentPrevented = event.defaultPrevented;
      event.preventDefault();
    };
    window.addEventListener("click", onWindowClick);
    fireEvent.click(link, { ctrlKey: true });
    window.removeEventListener("click", onWindowClick);
    expect(componentPrevented).toBe(false);
    expect(window.location.pathname).toBe("/");
  });

  it("marks the active link and renders children inside main", () => {
    render(<PortalShell route={{ name: "upload" }} onLogout={vi.fn()}>hello body</PortalShell>);
    expect(screen.queryByRole("link", { name: copy.shell.upload })).toBeNull();
    expect(screen.getByRole("link", { name: copy.shell.library }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("main").textContent).toBe("hello body");
  });

  it("calls onLogout and has no other controls in the bar", () => {
    const onLogout = vi.fn();
    render(<PortalShell route={{ name: "library" }} onLogout={onLogout}>x</PortalShell>);
    fireEvent.click(screen.getByRole("button", { name: copy.shell.logout }));
    expect(onLogout).toHaveBeenCalledTimes(1);

    const bar = screen.getByRole("banner");
    expect(bar.querySelectorAll("button")).toHaveLength(1);
    const links = [...bar.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links).toEqual(["/", "/"]);
  });
});
