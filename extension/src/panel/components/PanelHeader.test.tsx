import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PanelHeader } from "./PanelHeader";
import { panelCopy as copy } from "../copy";

describe("PanelHeader", () => {
  it("shows the panel title and no brand name or settings button", () => {
    render(<PanelHeader />);
    expect(screen.getByText(copy.panelTitle)).toBeInTheDocument();
    expect(screen.queryByText("Sauri")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("draws the Sauri isotype next to the title, hidden from assistive tech", () => {
    const { container } = render(<PanelHeader />);
    const mark = container.querySelector(".panel-brand svg")!;
    expect(mark.querySelector('polygon[fill="#4a7c59"]')).toBeTruthy();
    expect(mark.getAttribute("aria-hidden")).toBe("true");
  });
  it.each([false, true])("shows the projected recording badge, paused=%s", paused => {
    render(<PanelHeader captureState="recording" paused={paused} />);
    expect(screen.getByText(paused ? copy.paused : copy.recording)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
