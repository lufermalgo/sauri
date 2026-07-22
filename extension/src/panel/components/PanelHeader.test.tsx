// Example-based test: Panel_Header and New_Note_Button (Req. 2.1, 2.2, 2.3, 2.5, 2.6)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PanelHeader } from "./PanelHeader";

describe("PanelHeader", () => {
  it("shows the 'REC Notes' title (Req. 2.1)", () => {
    render(<PanelHeader captureState="idle" onNewNote={() => {}} />);
    expect(screen.getByText("REC Notes")).toBeInTheDocument();
  });

  it("shows the New_Note_Button with the '+ New Note REC' label (Req. 2.2)", () => {
    render(<PanelHeader captureState="idle" onNewNote={() => {}} />);
    expect(screen.getByRole("button", { name: "+ New Note REC" })).toBeInTheDocument();
  });

  it("fires onNewNote when activated in the idle state (Req. 2.4)", () => {
    const onNewNote = vi.fn();
    render(<PanelHeader captureState="idle" onNewNote={onNewNote} />);
    fireEvent.click(screen.getByRole("button", { name: "+ New Note REC" }));
    expect(onNewNote).toHaveBeenCalledTimes(1);
  });

  it("disables the New_Note_Button while recording or stopping (Req. 2.5)", () => {
    render(<PanelHeader captureState="recording" onNewNote={() => {}} />);
    expect(screen.getByRole("button", { name: "+ New Note REC" })).toBeDisabled();
  });

  it("shows an error message if starting the recording fails (Req. 2.6)", () => {
    render(
      <PanelHeader
        captureState="idle"
        onNewNote={() => {}}
        startError="The recording could not be started"
      />
    );
    expect(screen.getByText("The recording could not be started")).toBeInTheDocument();
  });
});
