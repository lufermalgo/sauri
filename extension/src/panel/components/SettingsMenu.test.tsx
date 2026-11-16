import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SettingsMenu } from "./SettingsMenu";
import { DEFAULT_RECORDING_SETTINGS } from "../recordingSettings";
import { panelCopy as copy } from "../../i18n/spanish";

const trigger = () => screen.getByRole("button", { name: copy.settings });

describe("SettingsMenu", () => {
  it("opens from the button, focuses the first control and exposes the four rows", () => {
    render(<SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={vi.fn()} />);
    expect(trigger()).toHaveAttribute("aria-haspopup", "dialog");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(trigger()).toHaveAttribute("title", copy.settings);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("dialog", { name: copy.settings })).toBeInTheDocument();
    expect(screen.getByLabelText(copy.countdown)).toHaveFocus();
    expect(Array.from((screen.getByLabelText(copy.countdown) as HTMLSelectElement).options).map(option => option.text)).toEqual([copy.countdownOff, "3 s", "5 s", "10 s"]);
    expect(Array.from((screen.getByLabelText(copy.resolution) as HTMLSelectElement).options).map(option => option.text)).toEqual(["480p", "720p", "1080p"]);
    expect(screen.getByLabelText(copy.countdown)).toHaveValue("3");
    expect(screen.getByLabelText(copy.resolution)).toHaveValue("720p");
    expect(screen.getByRole("switch", { name: copy.controlBar })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("switch", { name: copy.micWarning })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(copy.resolutionHint)).toBeInTheDocument();
  });
  it("opens with the arrow key and closes with Escape returning focus to the button", () => {
    render(<SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={vi.fn()} />);
    trigger().focus();
    fireEvent.keyDown(trigger(), { key: "ArrowDown" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText(copy.countdown), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });
  it("toggles from the button and closes on an outside press or when focus leaves", () => {
    render(<div><SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={vi.fn()} /><button>Elsewhere</button></div>);
    fireEvent.click(trigger());
    fireEvent.click(trigger());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(trigger());
    fireEvent.pointerDown(screen.getByLabelText(copy.countdown));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Elsewhere" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(trigger());
    fireEvent.blur(screen.getByRole("switch", { name: copy.micWarning }), { relatedTarget: screen.getByRole("button", { name: "Elsewhere" }) });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("saves each change immediately through onChange", () => {
    const onChange = vi.fn();
    render(<SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={onChange} />);
    fireEvent.click(trigger());
    fireEvent.change(screen.getByLabelText(copy.countdown), { target: { value: "0" } });
    expect(onChange).toHaveBeenLastCalledWith({ countdownSeconds: 0 });
    fireEvent.change(screen.getByLabelText(copy.resolution), { target: { value: "480p" } });
    expect(onChange).toHaveBeenLastCalledWith({ resolution: "480p" });
    fireEvent.click(screen.getByRole("switch", { name: copy.controlBar }));
    expect(onChange).toHaveBeenLastCalledWith({ showControlBar: false });
    fireEvent.click(screen.getByRole("switch", { name: copy.micWarning }));
    expect(onChange).toHaveBeenLastCalledWith({ skipMicWarning: true });
  });
  it("locks the next-recording settings while recording but keeps the switches usable", () => {
    render(<SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={vi.fn()} recording />);
    fireEvent.click(trigger());
    expect(screen.getByLabelText(copy.countdown)).toBeDisabled();
    expect(screen.getByLabelText(copy.resolution)).toBeDisabled();
    expect(screen.getByLabelText(copy.resolution)).toHaveAttribute("title", copy.settingsLocked);
    expect(screen.getByRole("switch", { name: copy.controlBar })).toBeEnabled();
    expect(screen.getByRole("switch", { name: copy.controlBar })).toHaveFocus();
  });
  it("closes when it becomes disabled and shows a save error inside the popover", () => {
    const view = render(<SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={vi.fn()} error={copy.settingsError} />);
    fireEvent.click(trigger());
    expect(screen.getByRole("alert")).toHaveTextContent(copy.settingsError);
    view.rerender(<SettingsMenu settings={DEFAULT_RECORDING_SETTINGS} onChange={vi.fn()} disabled />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger()).toBeDisabled();
  });
});
