// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { copy } from "../copy/es";
import { SpeakerReviewPanel, type SpeakerRowModel } from "./SpeakerReviewPanel";

afterEach(cleanup);

const sr = copy.speakerReview;
const rows: SpeakerRowModel[] = [
  { speakerId: "a", label: "Speaker 1", initials: "H1", color: "var(--ds-speaker-1)", disposition: null, interval: { startMs: 0, endMs: 9000, short: false } },
  { speakerId: "b", label: "Ana", initials: "A", color: "var(--ds-speaker-2)", disposition: "named", interval: null },
];

function panel(overrides: Partial<Parameters<typeof SpeakerReviewPanel>[0]> = {}) {
  const props = {
    rows, complete: false, selectedId: "a", names: {}, busyId: null, playingId: null, playbackReady: true,
    playbackLoading: false, error: null, onSelect: vi.fn(), onNameChange: vi.fn(), onListen: vi.fn(), onSubmit: vi.fn(),
    ...overrides,
  };
  render(<SpeakerReviewPanel {...props} />);
  return props;
}

describe("SpeakerReviewPanel", () => {
  it("announces the pending and the complete state", () => {
    panel();
    expect(screen.getByText(sr.pending)).toBeInTheDocument();
    cleanup();
    panel({ complete: true });
    expect(screen.getByText(sr.complete)).toBeInTheDocument();
  });

  it("lists one row per speaker with its status and a 44px-class Play button with icon and label", () => {
    panel();
    const articles = screen.getAllByRole("article");
    expect(articles).toHaveLength(2);
    expect(within(articles[0]).getByText(sr.pendingState)).toBeInTheDocument();
    expect(within(articles[1]).getByText(sr.confirmedState)).toBeInTheDocument();
    const listen = within(articles[0]).getByRole("button", { name: sr.listenTo("Speaker 1") });
    expect(listen).toHaveTextContent(sr.listen);
    expect(listen.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(within(articles[1]).getByRole("button", { name: sr.listenTo("Ana") })).toBeDisabled();
    expect(screen.getByText(sr.noInterval)).toBeInTheDocument();
  });

  it("toggles the listen button to a stop button while that speaker plays", () => {
    const props = panel({ playingId: "a" });
    const stop = screen.getByRole("button", { name: sr.stopFor("Speaker 1") });
    expect(stop).toHaveTextContent(sr.stop);
    fireEvent.click(stop);
    expect(props.onListen).toHaveBeenCalledWith(rows[0]);
  });

  it("saves and corrects with the trimmed name and confirms without one", () => {
    const props = panel({ names: { a: "  Luisa " } });
    fireEvent.click(screen.getByRole("button", { name: sr.saveNameFor("Speaker 1") }));
    expect(props.onSubmit).toHaveBeenLastCalledWith("a", "named", "Luisa");
    fireEvent.click(screen.getByRole("button", { name: sr.correctFor("Speaker 1") }));
    expect(props.onSubmit).toHaveBeenLastCalledWith("a", "corrected", "Luisa");
    fireEvent.click(screen.getByRole("button", { name: sr.confirmFor("Speaker 1") }));
    expect(props.onSubmit).toHaveBeenLastCalledWith("a", "confirmed");
  });

  it("disables saving while busy and shows the error inside the panel", () => {
    panel({ names: { a: "Luisa" }, busyId: "a", error: sr.saveFailed });
    expect(screen.getByRole("alert")).toHaveTextContent(sr.saveFailed);
    expect(screen.getByRole("button", { name: sr.saveNameFor("Speaker 1") })).toBeDisabled();
    expect(screen.getByText(sr.saving)).toBeInTheDocument();
  });
});
