// @vitest-environment jsdom
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Avatar, Button, Card, ConfirmDialog, Dialog, Menu, MenuItem, Popover, ProgressBar, Skeleton, SkeletonLines, StatusBadge, Tabs,
  TextField, TimeChip } from "./index";

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
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  });

  it("speaks a value text only when determinate", () => {
    const { rerender } = render(<ProgressBar label="Estimate" value={42} valueText="≈ 42 %" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "≈ 42 %");
    rerender(<ProgressBar label="Estimate" valueText="≈ 42 %" />);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuetext");
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
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

describe("Skeleton", () => {
  it("is aria-hidden, textless and applies size and radius", () => {
    const { container } = render(<Skeleton width={120} height="2rem" radius="full" className="custom" />);
    const node = container.firstElementChild as HTMLElement;
    expect(node).toHaveAttribute("aria-hidden", "true");
    expect(node).toHaveTextContent("");
    expect(node).toHaveClass("ui-skeleton", "ui-skeleton--full", "custom");
    expect(node).toHaveStyle({ width: "120px", height: "2rem" });
  });

  it("renders the requested number of lines with a shorter last line", () => {
    const { container } = render(<SkeletonLines lines={3} lastWidth="40%" />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
    const lines = container.querySelectorAll<HTMLElement>(".ui-skeleton");
    expect(lines).toHaveLength(3);
    expect(lines[2]).toHaveStyle({ width: "40%" });
    expect(container).toHaveTextContent("");
  });
});

describe("Menu", () => {
  function setup() {
    const onRename = vi.fn();
    const onDelete = vi.fn();
    render(<div>
      <button>Outside</button>
      <Menu label="More actions">
        <MenuItem onSelect={onRename}>Rename</MenuItem>
        <MenuItem onSelect={() => undefined}>Share</MenuItem>
        <MenuItem tone="danger" onSelect={onDelete}>Delete</MenuItem>
      </Menu>
    </div>);
    return { onRename, onDelete, trigger: screen.getByRole("button", { name: "More actions" }) };
  }

  it("exposes menu semantics and toggles on click", () => {
    const { trigger } = setup();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getAllByRole("menuitem")).toHaveLength(3);
    expect(screen.getAllByRole("menuitem")[0]).toHaveFocus();
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveClass("ui-menu-item--danger");
    fireEvent.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens with ArrowDown from the trigger and navigates with arrows, Home and End", () => {
    const { trigger } = setup();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const items = screen.getAllByRole("menuitem");
    expect(items[0]).toHaveFocus();
    for (const [key, index] of [["ArrowDown", 1], ["ArrowDown", 2], ["ArrowDown", 0],
      ["ArrowUp", 2], ["Home", 0], ["End", 2]] as const) {
      fireEvent.keyDown(document.activeElement!, { key });
      expect(items[index]).toHaveFocus();
    }
  });

  it("closes on Escape and returns focus to the trigger", () => {
    const { trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on outside click", () => {
    const { trigger } = setup();
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("fires onSelect and closes after selecting", () => {
    const { trigger, onRename, onDelete } = setup();
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    expect(onRename).toHaveBeenCalledOnce();
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});

describe("Menu text trigger and disabled items", () => {
  it("shows visible text with a chevron while keeping label as aria-label", () => {
    render(<Menu label="Download options" triggerLabel="Download" triggerVariant="primary">
      <MenuItem onSelect={() => undefined}>One</MenuItem>
    </Menu>);
    const trigger = screen.getByRole("button", { name: "Download options" });
    expect(trigger).toHaveTextContent("Download");
    expect(trigger).toHaveClass("ui-menu-trigger--primary");
    expect(trigger.querySelector("svg")).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("supports the secondary variant and defaults to the icon trigger", () => {
    const { rerender } = render(<Menu label="Options" triggerLabel="Options" triggerVariant="secondary">
      <MenuItem onSelect={() => undefined}>One</MenuItem></Menu>);
    expect(screen.getByRole("button", { name: "Options" })).toHaveClass("ui-menu-trigger--secondary");
    expect(screen.getByRole("button", { name: "Options" })).toHaveTextContent("Options");
    rerender(<Menu label="Options"><MenuItem onSelect={() => undefined}>One</MenuItem></Menu>);
    expect(screen.getByRole("button", { name: "Options" })).toHaveClass("ui-menu-trigger--icon");
    expect(screen.getByRole("button", { name: "Options" })).toHaveTextContent("");
  });

  it("skips disabled items in navigation and never selects them", () => {
    const onDisabled = vi.fn();
    render(<Menu label="Actions">
      <MenuItem onSelect={() => undefined}>First</MenuItem>
      <MenuItem disabled onSelect={onDisabled}>Unavailable</MenuItem>
      <MenuItem onSelect={() => undefined}>Last</MenuItem>
    </Menu>);
    fireEvent.click(screen.getByRole("button", { name: "Actions" }));
    const disabled = screen.getByRole("menuitem", { name: "Unavailable" });
    expect(disabled).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getByRole("menuitem", { name: "Last" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(screen.getByRole("menuitem", { name: "First" })).toHaveFocus();
    fireEvent.click(disabled);
    expect(onDisabled).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});

describe("Avatar", () => {
  it("shows initials, is aria-hidden and sets the color variable", () => {
    const { container } = render(<Avatar initials="LF" color="var(--ds-speaker-2)" size="sm" />);
    const node = container.firstElementChild as HTMLElement;
    expect(node).toHaveTextContent("LF");
    expect(node).toHaveAttribute("aria-hidden", "true");
    expect(node).toHaveClass("ui-avatar--sm");
    expect(node.style.getPropertyValue("--avatar-color")).toBe("var(--ds-speaker-2)");
  });
});

describe("TimeChip", () => {
  it("shows the timestamp and calls onClick", () => {
    const onClick = vi.fn();
    render(<TimeChip label="02:10" ariaLabel="Jump to 02:10" onClick={onClick} />);
    const chip = screen.getByRole("button", { name: "Jump to 02:10" });
    expect(chip).toHaveTextContent("02:10");
    fireEvent.click(chip);
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("Menu custom trigger", () => {
  it("renders the given content inside a button that keeps the menu semantics and the label", () => {
    render(<Menu label="Account" trigger={<span>Ana</span>} triggerClassName="custom-trigger" className="custom-root">
      <MenuItem onSelect={() => undefined}>Sign out</MenuItem>
    </Menu>);
    const trigger = screen.getByRole("button", { name: "Account" });
    expect(trigger).toHaveClass("custom-trigger");
    expect(trigger).not.toHaveClass("ui-menu-trigger");
    expect(trigger).toHaveTextContent("Ana");
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger.parentElement).toHaveClass("ui-menu", "custom-root");
    fireEvent.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Sign out" })).toHaveFocus();
  });
});

describe("Dialog", () => {
  function Harness({ onClose = () => {} }: { onClose?: () => void }) {
    const [open, setOpen] = useState(false);
    return <div>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      <input aria-label="Behind" />
      {open && <Dialog title="Speakers" closeLabel="Close" onClose={() => { onClose(); setOpen(false); }}>
        <button type="button">First</button>
        <button type="button">Last</button>
      </Dialog>}
    </div>;
  }

  function open() {
    const result = render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    opener.focus();
    fireEvent.click(opener);
    return { ...result, opener };
  }

  it("is a labelled modal dialog rendered in a portal on the body", () => {
    const { container } = open();
    const dialog = screen.getByRole("dialog", { name: "Speakers" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(container.contains(dialog)).toBe(false);
    expect(document.body.contains(dialog)).toBe(true);
    expect(dialog).toHaveClass("ui-modal--md");
    expect(screen.getByRole("heading", { name: "Speakers" })).toBeInTheDocument();
  });

  it("moves focus inside on open, makes the page inert and locks body scroll until it closes", () => {
    const { container, opener } = open();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    expect(container).toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(container).not.toHaveAttribute("inert");
    expect(document.body.style.overflow).toBe("");
    expect(opener).toHaveFocus();
  });

  it("traps Tab and Shift+Tab inside the dialog", () => {
    open();
    const close = screen.getByRole("button", { name: "Close" });
    const last = screen.getByRole("button", { name: "Last" });
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("pulls focus back when it escapes the dialog", () => {
    open();
    screen.getByLabelText("Behind").focus();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("closes with Escape, the close button and a click on the backdrop, but not on a drag that ends there", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const reopen = () => fireEvent.click(screen.getByRole("button", { name: "Open" }));
    reopen();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    reopen();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    reopen();
    const backdrop = document.querySelector(".ui-modal-backdrop")!;
    fireEvent.mouseDown(screen.getByRole("dialog"));
    fireEvent.click(backdrop);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("dialog"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(3);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("returns focus to the requested element, then to the opener, when that is gone", () => {
    const target = document.createElement("button");
    document.body.append(target);
    const { rerender, unmount } = render(<Dialog title="T" closeLabel="Close" onClose={() => {}} returnFocus={() => target}>x</Dialog>);
    rerender(<div />);
    expect(target).toHaveFocus();
    unmount();
    target.remove();
  });
});

describe("Menu radio items", () => {
  it("exposes menuitemradio with aria-checked and keeps arrow navigation", () => {
    render(<Menu label="Sort">
      <MenuItem checked onSelect={() => undefined}>Newest</MenuItem>
      <MenuItem checked={false} onSelect={() => undefined}>Oldest</MenuItem>
    </Menu>);
    fireEvent.click(screen.getByRole("button", { name: "Sort" }));
    const radios = screen.getAllByRole("menuitemradio");
    expect(radios.map(radio => radio.getAttribute("aria-checked"))).toEqual(["true", "false"]);
    expect(radios[0]).toHaveFocus();
    fireEvent.keyDown(radios[0], { key: "ArrowDown" });
    expect(radios[1]).toHaveFocus();
  });
});

describe("Popover", () => {
  function setup() {
    render(<div>
      <button>Outside</button>
      <Popover label="Dates: none" panelLabel="Dates" trigger={<span>icon</span>}>
        {close => <>
          <input aria-label="Since" />
          <button onClick={close}>Done</button>
        </>}
      </Popover>
    </div>);
    return screen.getByRole("button", { name: "Dates: none" });
  }

  it("is a non-modal dialog opened by the trigger, with focus moved to its first control", () => {
    const trigger = setup();
    expect(trigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Dates" });
    expect(dialog).not.toHaveAttribute("aria-modal");
    expect(trigger).toHaveAttribute("aria-controls", dialog.id);
    expect(screen.getByLabelText("Since")).toHaveFocus();
    fireEvent.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens with ArrowDown, closes with Escape and returns focus to the trigger", () => {
    const trigger = setup();
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("Since"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes on a click outside and when focus moves outside, and `close` returns focus", () => {
    const trigger = setup();
    fireEvent.click(trigger);
    fireEvent.mouseDown(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    fireEvent.blur(screen.getByLabelText("Since"), { relatedTarget: screen.getByRole("button", { name: "Outside" }) });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("describes the trigger with a tooltip that repeats its name", () => {
    const trigger = setup();
    const tooltip = document.getElementById(trigger.getAttribute("aria-describedby")!);
    expect(tooltip).toHaveAttribute("role", "tooltip");
    expect(tooltip).toHaveTextContent("Dates: none");
  });
});
