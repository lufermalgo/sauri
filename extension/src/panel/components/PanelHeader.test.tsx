import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PanelHeader } from "./PanelHeader";
import { panelCopy as copy } from "../copy";

describe("PanelHeader", () => {
  it("shows the official Sauri logo as the brand, with the name as its accessible name and no settings button", () => {
    const { container } = render(<PanelHeader />);
    const logo = screen.getByRole("img", { name: copy.brandName });
    expect(copy.brandName).toBe("Sauri");
    expect(logo.querySelector('polygon[fill="#4a7c59"]')).toBeTruthy();
    expect(logo.querySelector("path.ui-brand-word")).toBeTruthy();
    // The word is the outlined artwork, never live text in the interface font.
    expect(container.querySelector(".panel-brand")!.textContent).toBe("");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it.each([false, true])("shows the projected recording badge, paused=%s", paused => {
    render(<PanelHeader captureState="recording" paused={paused} />);
    expect(screen.getByText(paused ? copy.paused : copy.recording)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
