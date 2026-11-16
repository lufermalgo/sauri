import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PanelHeader } from "./PanelHeader";
import { panelCopy as copy } from "../copy";

describe("PanelHeader", () => {
  it("shows the brand and opens recording settings", () => {
    const onOpenSettings = vi.fn();
    render(<PanelHeader onOpenSettings={onOpenSettings} />);
    expect(screen.getByText(copy.brand)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
  });
  it.each([false, true])("shows the projected recording badge, paused=%s", paused => {
    render(<PanelHeader captureState="recording" paused={paused} />);
    expect(screen.getByText(paused ? copy.paused : copy.recording)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
