// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MeetingHeader } from "./MeetingHeader";
import { deleteMeeting, renameMeeting } from "../api";
import { navigate } from "../router";
import { meeting as text } from "../copy/meeting";
import { processing } from "../copy/processing";
import type { DetectedStage } from "../processing-estimate";

vi.mock("../api", () => ({ renameMeeting: vi.fn(), deleteMeeting: vi.fn() }));
vi.mock("../router", () => ({ navigate: vi.fn() }));

beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
afterEach(cleanup);

function open(title: string | null = "Synthetic meeting") {
  return render(<MeetingHeader title={title} createdAt="2026-11-14T12:00:00Z" meetingId="m1"
    onBack={vi.fn()} manifest={null} turns={[]} />);
}

function openDelete() {
  fireEvent.click(screen.getByRole("button", { name: text.moreActions }));
  fireEvent.click(screen.getByRole("menuitem", { name: text.deleteRecording }));
}

function edit(value: string) {
  fireEvent.click(screen.getByRole("button", { name: text.rename }));
  fireEvent.change(screen.getByRole("textbox", { name: text.titleLabel }), { target: { value } });
}

describe("MeetingHeader", () => {
  it("renders the fallback title and a localized real date", () => {
    open(null);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(text.untitled);
    expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-11-14T12:00:00Z");
    expect(document.querySelector("time")).toHaveTextContent("14");
  });

  it("renames with a trimmed title and displays the title returned by the API", async () => {
    vi.mocked(renameMeeting).mockResolvedValue({ meetingId: "m1", title: "Canonical title" });
    open(); edit(" New title ");
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    expect(await screen.findByRole("heading", { name: "Canonical title" })).toBeVisible();
    expect(renameMeeting).toHaveBeenCalledWith("m1", "New title");
  });

  it("names the transcript download after the renamed title", async () => {
    vi.mocked(renameMeeting).mockResolvedValue({ meetingId: "m1", title: "Canonical title" });
    const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: () => "blob:synthetic", revokeObjectURL: revoke });
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked = this; });
    const turns = [{ timestampMs: 1000, speakerLabel: "Synthetic speaker", text: "Synthetic text" }];
    render(<MeetingHeader title="Old title" createdAt="2026-11-14T12:00:00Z" meetingId="m1"
      onBack={vi.fn()} manifest={null} turns={turns} />);
    edit("New title");
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    await screen.findByRole("heading", { name: "Canonical title" });
    fireEvent.click(screen.getByRole("button", { name: text.download }));
    fireEvent.click(screen.getByRole("menuitem", { name: text.downloadTranscript }));
    expect(clicked).toHaveAttribute("download", "Canonical title.txt");
    await waitFor(() => expect(revoke).toHaveBeenCalled());
    vi.unstubAllGlobals();
  });

  it.each(["", "  ", "x".repeat(513)])("rejects invalid titles (%s)", value => {
    open(); edit(value);
    expect(screen.getByRole("button", { name: text.save })).toBeDisabled();
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    expect(renameMeeting).not.toHaveBeenCalled();
  });

  it("accepts exactly 512 characters", () => {
    open(); edit("x".repeat(512));
    expect(screen.getByRole("button", { name: text.save })).toBeEnabled();
  });

  it("cancels editing without calling the API", () => {
    open(); edit("Unused title");
    fireEvent.click(screen.getByRole("button", { name: text.cancel }));
    expect(renameMeeting).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Synthetic meeting");
  });

  it("keeps the draft and offers a retry after rename failure", async () => {
    vi.mocked(renameMeeting).mockRejectedValueOnce(new Error("Error 503"))
      .mockResolvedValueOnce({ meetingId: "m1", title: "Retried title" });
    open(); edit("Retried title");
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.renameFailed);
    expect(screen.getByRole("textbox")).toHaveValue("Retried title");
    fireEvent.click(screen.getByRole("button", { name: text.save }));
    expect(await screen.findByRole("heading", { name: "Retried title" })).toBeVisible();
  });

  it("requires confirmation, focuses cancel and never deletes on cancellation", () => {
    open(); openDelete();
    expect(deleteMeeting).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: text.deleteTitle });
    const cancel = within(dialog).getByRole("button", { name: text.cancel });
    expect(cancel).toHaveFocus();
    fireEvent.click(cancel);
    expect(deleteMeeting).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("deletes only after confirmation and navigates only after success", async () => {
    let finish!: () => void;
    vi.mocked(deleteMeeting).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    open(); openDelete();
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: text.delete });
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(deleteMeeting).toHaveBeenCalledTimes(1);
    expect(deleteMeeting).toHaveBeenCalledWith("m1");
    expect(navigate).not.toHaveBeenCalled();
    finish();
    await waitFor(() => expect(navigate).toHaveBeenCalledWith({ name: "library" }));
  });

  it("keeps the meeting open after deletion failure", async () => {
    vi.mocked(deleteMeeting).mockRejectedValue(new Error("Error 503"));
    open(); openDelete();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: text.delete }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.deleteFailed);
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Synthetic meeting");
  });
});


it("orders download, rename and more actions, keeping deletion inside the menu", () => {
  open();
  const actions = document.querySelector(".meeting-heading-row > .meeting-actions")!;
  const buttons = within(actions as HTMLElement).getAllByRole("button");
  expect(buttons).toHaveLength(3);
  expect(buttons[0]).toHaveAccessibleName(text.download);
  expect(buttons[0]).toHaveClass("ui-menu-trigger--primary");
  expect(buttons[1]).toHaveAccessibleName(text.rename);
  expect(buttons[2]).toHaveAccessibleName(text.moreActions);
  expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  fireEvent.click(buttons[2]);
  expect(screen.getByRole("menuitem", { name: text.deleteRecording })).toHaveClass("ui-menu-item--danger");
});

it.each([[65, "01:05"], [3605, "1:00:05"], [0, "00:00"]])("formats real duration %s and speaker count", (duration, label) => {
  render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1" onBack={vi.fn()}
    stage="done" speakerCount={2} turns={[]} manifest={{ meeting_id: "m1", duration_seconds: Number(duration),
      video_presence: "absent", audio_source: { source_id: "a", url: "/audio", mime_type: "audio/wav" },
      muxed_video_source: null, video_sources: [] }} />);
  expect(screen.getByText(label)).toHaveClass("meeting-duration");
  expect(screen.getByText(text.speakerCount(2))).toBeVisible();
  expect(screen.getByText(text.ready)).toHaveClass("ui-status-badge--success");
});

it("omits duration and speaker count without their source data", () => {
  open();
  expect(document.querySelector(".meeting-duration")).not.toBeInTheDocument();
  expect(screen.queryByText(text.speakerCount(0))).not.toBeInTheDocument();
});

it.each([['transcribing', 'transcription', 'progress'], ['failed', 'failed', 'error']])("shows the %s badge with its real tone", (processState, stage, tone) => {
  render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1" onBack={vi.fn()}
    stage={stage as DetectedStage} processState={processState} turns={[]} manifest={null} />);
  expect(document.querySelector(".ui-status-badge")).toHaveClass(`ui-status-badge--${tone}`);
});

it.each([
  ["transcription", "queued", "En cola", "progress"],
  ["speakers", "completed", processing.identifying, "progress"],
  ["summary", "completed", processing.summarizing, "progress"],
  ["done", "completed", text.ready, "success"],
] as const)("shows the %s stage as %s without calling it ready early", (stage, processState, label, tone) => {
  render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1" onBack={vi.fn()}
    stage={stage} processState={processState} turns={[]} manifest={null} />);
  const badge = document.querySelector(".ui-status-badge");
  expect(badge).toHaveTextContent(label);
  expect(badge).toHaveClass(`ui-status-badge--${tone}`);
  if (stage !== "done") expect(screen.queryByText(text.ready)).not.toBeInTheDocument();
});

it("shows no status badge while the stage is unknown to the page", () => {
  open();
  expect(document.querySelector(".ui-status-badge")).not.toBeInTheDocument();
});
