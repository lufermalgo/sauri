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
  it.each([false, true])("shows the projected recording badge, paused=%s", paused => {
    render(<PanelHeader captureState="recording" paused={paused} />);
    expect(screen.getByText(paused ? copy.paused : copy.recording)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
