// @vitest-environment jsdom
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Button, Card, ConfirmDialog, ProgressBar, StatusBadge, Tabs, TextField } from "./index";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).showModal;
  delete (HTMLDialogElement.prototype as Partial<HTMLDialogElement>).close;
});

function TabExample() {
  const [activeId, setActiveId] = useState("first");
  return <Tabs aria-label="Content" activeId={activeId} onChange={setActiveId} tabs={[
    { id: "first", label: "First", panel: "First content" },
    { id: "second", label: "Second", panel: "Second content" },
    { id: "third", label: "Third", panel: "Third content" },
  ]} />;
}

describe("Tabs", () => {
  it("selects and focuses tabs with arrows, Home and End, including wrapping", () => {
    render(<TabExample />);
    const tabs = screen.getAllByRole("tab");
    tabs[0].focus();
    for (const [key, index] of [["ArrowRight", 1], ["ArrowRight", 2], ["ArrowRight", 0],
      ["ArrowLeft", 2], ["Home", 0], ["End", 2]] as const) {
      fireEvent.keyDown(document.activeElement!, { key });
      tabs.forEach((tab, position) => {
        expect(tab).toHaveAttribute("aria-selected", String(position === index));
        expect(tab).toHaveAttribute("tabindex", position === index ? "0" : "-1");
      });
      expect(tabs[index]).toHaveFocus();
      const panel = screen.getByRole("tabpanel");
      expect(panel).toHaveAttribute("aria-labelledby", tabs[index].id);
      expect(tabs[index]).toHaveAttribute("aria-controls", panel.id);
    }
  });

  it("selects by click and does not intercept unrelated keys", () => {
    render(<TabExample />);
    fireEvent.click(screen.getByRole("tab", { name: "Second" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Second content");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Second" }), { key: "Tab" });
    expect(screen.getByRole("tab", { name: "Second" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps ARIA ids unique across instances", () => {
    render(<><TabExample /><TabExample /></>);
    const ids = Array.from(document.querySelectorAll("[id]"), element => element.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("ConfirmDialog", () => {
  function setup() {
    // jsdom has no modal implementation; browser behavior is provided by native dialog.
    const showModal = vi.fn(function (this: HTMLDialogElement) { this.open = true; });
    const close = vi.fn(function (this: HTMLDialogElement) { this.open = false; });
    HTMLDialogElement.prototype.showModal = showModal;
    HTMLDialogElement.prototype.close = close;
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    const result = render(<ConfirmDialog title="Confirm action" body="Action details"
      confirmLabel="Confirm" cancelLabel="Cancel" onConfirm={onConfirm} onCancel={onCancel} />);
    return { ...result, showModal, close, onConfirm, onCancel };
  }

  it("opens modally, focuses cancel and confirms only on the confirm button", () => {
    const { showModal, onConfirm, onCancel } = setup();
    expect(showModal).toHaveBeenCalledOnce();
    expect(screen.getByRole("dialog", { name: "Confirm action" })).toHaveAccessibleDescription("Action details");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("cancels on native Escape cancel events and the cancel button, never confirming", () => {
    const { onConfirm, onCancel } = setup();
    const event = new Event("cancel", { cancelable: true });
    fireEvent(screen.getByRole("dialog"), event);
    expect(event.defaultPrevented).toBe(true);
    expect(onCancel).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("closes the native modal on unmount", () => {
    const { unmount, close } = setup();
    unmount();
    expect(close).toHaveBeenCalledOnce();
  });
});

describe("TextField", () => {
  it("associates its label, error and caller description with the input", () => {
    render(<><span id="hint">Help</span><TextField id="field" label="Name" error="Required"
      aria-describedby="hint" required /></>);
    const input = screen.getByRole("textbox", { name: "Name" });
    expect(input).toBeRequired();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Help Required");
    expect(screen.getByRole("alert")).toHaveTextContent("Required");
  });

  it("generates unique ids and clears the error state", () => {
    const { rerender } = render(<TextField label="Name" error="Required" />);
    rerender(<><TextField label="Name" /><TextField label="Other" /></>);
    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-invalid", "true");
    expect(input.id).not.toBe(screen.getByLabelText("Other").id);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("ProgressBar", () => {
  it("is indeterminate when no value is provided", () => {
    render(<ProgressBar label="Upload progress" />);
    expect(screen.getByRole("progressbar", { name: "Upload progress" })).not.toHaveAttribute("value");
  });

  it("exposes determinate progress including zero", () => {
    const { rerender } = render(<ProgressBar label="Upload progress" value={0} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0");
    rerender(<ProgressBar label="Upload progress" value={42} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "42");
    expect(screen.getByRole("progressbar")).toHaveAttribute("max", "100");
  });
});

describe("presentation primitives", () => {
  it("forwards button props without submitting by default and respects disabled", () => {
    const onClick = vi.fn();
    const { rerender } = render(<Button variant="primary" onClick={onClick}>Action</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
    rerender(<Button variant="danger" type="submit" disabled onClick={onClick}>Action</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
    expect(screen.getByRole("button")).toBeDisabled();
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders a section card and caller-supplied badge content", () => {
    render(<Card aria-label="Recording" className="custom"><StatusBadge tone="success">Ready</StatusBadge></Card>);
    expect(screen.getByRole("region", { name: "Recording" }).tagName).toBe("SECTION");
    expect(screen.getByRole("region")).toHaveClass("ui-card", "custom");
    expect(screen.getByText("Ready")).toHaveClass("ui-status-badge--success");
  });
});
