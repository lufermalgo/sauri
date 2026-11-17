import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PanelHeader } from "./PanelHeader";
import { panelCopy as copy } from "../../i18n/spanish";

describe("PanelHeader", () => {
  it("shows the official Sauri logo and the panel title, with no settings button", () => {
    const { container } = render(<PanelHeader />);
    const logo = screen.getByRole("img", { name: copy.brandName });
    expect(copy.brandName).toBe("Sauri");
    expect(logo.querySelector('polygon[fill="#9A8CE0"]')).toBeTruthy();
    expect(logo.querySelector("path.ui-brand-word")).toBeTruthy();
    expect(screen.getByText("Grabar reunión")).toBeInTheDocument(); // spanish-sample-data
    expect(copy.panelTitle).toBe("Grabar reunión"); // spanish-sample-data
    // The word "Sauri" is the outlined artwork, never live text in the interface font.
    expect(screen.queryByText("Sauri")).not.toBeInTheDocument();
    expect(container.querySelector(".panel-brand svg")).toBe(logo);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it.each([false, true])("shows the projected recording badge, paused=%s", paused => {
    render(<PanelHeader captureState="recording" paused={paused} />);
    expect(screen.getByText(paused ? copy.paused : copy.recording)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
