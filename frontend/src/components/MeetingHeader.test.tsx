// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MeetingHeader } from "./MeetingHeader";
import { TOOLTIP_DELAY_MS } from "./ui";
import { deleteMeeting, renameMeeting } from "../api";
import { navigate } from "../router";

const speakersName = new RegExp(`^${t("speakerReview:heading")}`);
import type { DetectedStage } from "../processing-estimate";
import { t } from "../i18n";

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
    manifest={null} turns={[]} />);
}

function openDelete() {
  fireEvent.click(screen.getByRole("button", { name: t("meeting:moreActions") }));
  fireEvent.click(screen.getByRole("menuitem", { name: t("meeting:deleteRecording") }));
}

function startRename() {
  fireEvent.click(screen.getByRole("button", { name: t("meeting:moreActions") }));
  fireEvent.click(screen.getByRole("menuitem", { name: t("meeting:rename") }));
}

function edit(value: string) {
  startRename();
  fireEvent.change(screen.getByRole("textbox", { name: t("meeting:titleLabel") }), { target: { value } });
}

describe("MeetingHeader", () => {
  it("shows the recording date, with both dates in the tooltip when they differ", () => {
    render(<MeetingHeader title="Old video" createdAt="2026-11-14T12:00:00Z" recordedAt="2026-06-02T09:30:00Z"
      meetingId="m1" manifest={null} turns={[]} />);
    const time = document.querySelector("time");
    expect(time).toHaveAttribute("datetime", "2026-06-02T09:30:00Z");
    expect(time).toHaveTextContent("2026");
    expect(time).toHaveTextContent("junio");
    expect(time?.getAttribute("title")).toMatch(/^Grabada el .+ · Procesada el .+/);
  });

  it("has no dates tooltip when the recording is processed as it is recorded or the date is unknown", () => {
    const { unmount } = render(<MeetingHeader title="Live" createdAt="2026-11-14T12:00:20Z"
      recordedAt="2026-11-14T12:00:00Z" meetingId="m1" manifest={null} turns={[]} />);
    expect(document.querySelector("time")).not.toHaveAttribute("title");
    unmount();
    render(<MeetingHeader title="Legacy" createdAt="2026-11-14T12:00:00Z" meetingId="m1" manifest={null} turns={[]} />);
    expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-11-14T12:00:00Z");
    expect(document.querySelector("time")).not.toHaveAttribute("title");
  });

  it("renders the fallback title and a localized real date", () => {
    open(null);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(t("meeting:untitled"));
    expect(document.querySelector("time")).toHaveAttribute("datetime", "2026-11-14T12:00:00Z");
    expect(document.querySelector("time")).toHaveTextContent("14");
  });

  it("has no back link and exactly one h1", () => {
    open();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("renames with a trimmed title and displays the title returned by the API", async () => {
    vi.mocked(renameMeeting).mockResolvedValue({ meetingId: "m1", title: "Canonical title" });
    open(); edit(" New title ");
    fireEvent.click(screen.getByRole("button", { name: t("meeting:save") }));
    expect(await screen.findByRole("heading", { name: "Canonical title" })).toBeVisible();
    expect(renameMeeting).toHaveBeenCalledWith("m1", "New title");
  });

  it("shows a newer title that arrives from outside (renamed in the library list) over the one saved here", async () => {
    vi.mocked(renameMeeting).mockResolvedValue({ meetingId: "m1", title: "Saved here" });
    const view = open();
    edit("Saved here");
    fireEvent.click(screen.getByRole("button", { name: t("meeting:save") }));
    expect(await screen.findByRole("heading", { level: 1, name: "Saved here" })).toBeInTheDocument();

    view.rerender(<MeetingHeader title="Renamed in the list" createdAt="2026-11-14T12:00:00Z" meetingId="m1"
      manifest={null} turns={[]} />);
    expect(screen.getByRole("heading", { level: 1, name: "Renamed in the list" })).toBeInTheDocument();
  });

  it("names the transcript download after the renamed title", async () => {
    vi.mocked(renameMeeting).mockResolvedValue({ meetingId: "m1", title: "Canonical title" });
    const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: () => "blob:synthetic", revokeObjectURL: revoke });
    let clicked: HTMLAnchorElement | undefined;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked = this; });
    const turns = [{ timestampMs: 1000, speakerLabel: "Synthetic speaker", text: "Synthetic text" }];
    render(<MeetingHeader title="Old title" createdAt="2026-11-14T12:00:00Z" meetingId="m1"
      manifest={null} turns={turns} />);
    edit("New title");
    fireEvent.click(screen.getByRole("button", { name: t("meeting:save") }));
    await screen.findByRole("heading", { name: "Canonical title" });
    fireEvent.click(screen.getByRole("button", { name: t("meeting:download") }));
    fireEvent.click(screen.getByRole("menuitem", { name: t("meeting:downloadTranscript") }));
    expect(clicked).toHaveAttribute("download", "Canonical title.txt");
    await waitFor(() => expect(revoke).toHaveBeenCalled());
    vi.unstubAllGlobals();
  });

  it.each(["", "  ", "x".repeat(513)])("rejects invalid titles (%s)", value => {
    open(); edit(value);
    expect(screen.getByRole("button", { name: t("meeting:save") })).toBeDisabled();
    fireEvent.submit(screen.getByRole("textbox").closest("form")!);
    expect(renameMeeting).not.toHaveBeenCalled();
  });

  it("accepts exactly 512 characters", () => {
    open(); edit("x".repeat(512));
    expect(screen.getByRole("button", { name: t("meeting:save") })).toBeEnabled();
  });

  it("cancels editing without calling the API", () => {
    open(); edit("Unused title");
    fireEvent.click(screen.getByRole("button", { name: t("meeting:cancel") }));
    expect(renameMeeting).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Synthetic meeting");
  });

  it("keeps the draft and offers a retry after rename failure", async () => {
    vi.mocked(renameMeeting).mockRejectedValueOnce(new Error("Error 503"))
      .mockResolvedValueOnce({ meetingId: "m1", title: "Retried title" });
    open(); edit("Retried title");
    fireEvent.click(screen.getByRole("button", { name: t("meeting:save") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("meeting:renameFailed"));
    expect(screen.getByRole("textbox")).toHaveValue("Retried title");
    fireEvent.click(screen.getByRole("button", { name: t("meeting:save") }));
    expect(await screen.findByRole("heading", { name: "Retried title" })).toBeVisible();
  });

  it("requires confirmation, focuses cancel and never deletes on cancellation", () => {
    open(); openDelete();
    expect(deleteMeeting).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: t("meeting:deleteTitle") });
    const cancel = within(dialog).getByRole("button", { name: t("meeting:cancel") });
    expect(cancel).toHaveFocus();
    fireEvent.click(cancel);
    expect(deleteMeeting).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("deletes only after confirmation and navigates only after success", async () => {
    let finish!: () => void;
    vi.mocked(deleteMeeting).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    open(); openDelete();
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: t("meeting:delete") });
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
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: t("meeting:delete") }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("meeting:deleteFailed"));
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Synthetic meeting");
  });
});

it("shows two icon-only actions with names, keeping rename and deletion inside the more menu", () => {
  open();
  const actions = document.querySelector(".meeting-heading-row > .meeting-actions")!;
  const buttons = within(actions as HTMLElement).getAllByRole("button");
  expect(buttons).toHaveLength(2);
  expect(buttons[0]).toHaveAccessibleName(t("meeting:download"));
  expect(buttons[0]).toHaveClass("ui-icon-button--primary");
  expect(buttons[1]).toHaveAccessibleName(t("meeting:moreActions"));
  for (const button of buttons) {
    expect(button).toHaveTextContent("");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  }
  expect(screen.queryByRole("button", { name: t("meeting:rename") })).not.toBeInTheDocument();
  expect(screen.queryByRole("menuitem")).not.toBeInTheDocument();
  fireEvent.click(buttons[1]);
  const items = screen.getAllByRole("menuitem");
  expect(items.map(item => item.textContent)).toEqual([t("meeting:rename"), t("meeting:deleteRecording")]);
  expect(items[1]).toHaveClass("ui-menu-item--danger");
});

it("opens the more menu with the keyboard, focuses Rename, closes with Escape and returns focus", () => {
  open();
  const trigger = screen.getByRole("button", { name: t("meeting:moreActions") });
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  expect(screen.getByRole("menuitem", { name: t("meeting:rename") })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "ArrowDown" });
  expect(screen.getByRole("menuitem", { name: t("meeting:deleteRecording") })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("focuses the title field after choosing Rename and offers no second Rename while editing", () => {
  open(); startRename();
  expect(screen.getByRole("textbox", { name: t("meeting:titleLabel") })).toHaveFocus();
  expect(screen.getByRole("textbox", { name: t("meeting:titleLabel") })).toHaveValue("Synthetic meeting");
  fireEvent.click(screen.getByRole("button", { name: t("meeting:moreActions") }));
  expect(screen.queryByRole("menuitem", { name: t("meeting:rename") })).not.toBeInTheDocument();
  expect(screen.getByRole("menuitem", { name: t("meeting:deleteRecording") })).toHaveAttribute("aria-disabled", "true");
});

describe("header tooltips", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it.each([t("meeting:download"), t("meeting:moreActions")])("describes the %s button with a delayed tooltip on hover and focus", name => {
    open();
    const button = screen.getByRole("button", { name });
    const tooltip = document.getElementById(button.getAttribute("aria-describedby")!)!;
    expect(tooltip).toHaveAttribute("role", "tooltip");
    expect(tooltip).toHaveTextContent(name);
    expect(button).toHaveAccessibleDescription(name);
    expect(tooltip).not.toBeVisible();
    fireEvent.mouseEnter(button);
    act(() => { vi.advanceTimersByTime(TOOLTIP_DELAY_MS - 1); });
    expect(tooltip).not.toBeVisible();
    act(() => { vi.advanceTimersByTime(1); });
    expect(tooltip).toBeVisible();
    fireEvent.mouseLeave(button);
    expect(tooltip).not.toBeVisible();
    act(() => button.focus());
    act(() => { vi.advanceTimersByTime(TOOLTIP_DELAY_MS); });
    expect(tooltip).toBeVisible();
    fireEvent.keyDown(button, { key: "Escape" });
    expect(tooltip).not.toBeVisible();
  });

  it("hides the tooltip when the menu opens", () => {
    open();
    const button = screen.getByRole("button", { name: t("meeting:moreActions") });
    fireEvent.mouseEnter(button);
    act(() => { vi.advanceTimersByTime(TOOLTIP_DELAY_MS); });
    fireEvent.click(button);
    expect(document.getElementById(button.getAttribute("aria-describedby")!)).not.toBeVisible();
    expect(screen.getByRole("menu")).toBeVisible();
  });
});

it.each([[65, "01:05"], [3605, "1:00:05"], [0, "00:00"]])("formats real duration %s and speaker count", (duration, label) => {
  render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1"
    stage="done" speakerCount={2} turns={[]} manifest={{ meeting_id: "m1", duration_seconds: Number(duration),
      video_presence: "absent", audio_source: { source_id: "a", url: "/audio", mime_type: "audio/wav" },
      muxed_video_source: null, video_sources: [] }} />);
  expect(screen.getByText(label)).toHaveClass("meeting-duration");
  expect(screen.getByText(t("meeting:speakerCount", { count: 2 }))).toBeVisible();
  expect(screen.getByText(t("meeting:ready"))).toHaveClass("ui-status-badge--success");
});

it("omits duration and speaker count without their source data", () => {
  open();
  expect(document.querySelector(".meeting-duration")).not.toBeInTheDocument();
  expect(screen.queryByText(t("meeting:speakerCount", { count: 0 }))).not.toBeInTheDocument();
});

it.each([['transcribing', 'transcription', 'progress'], ['failed', 'failed', 'error']])("shows the %s badge with its real tone", (processState, stage, tone) => {
  render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1"
    stage={stage as DetectedStage} processState={processState} turns={[]} manifest={null} />);
  expect(document.querySelector(".ui-status-badge")).toHaveClass(`ui-status-badge--${tone}`);
});

it.each([
  ["transcription", "queued", "En cola", "progress"],
  ["speakers", "completed", t("processing:identifying"), "progress"],
  ["summary", "completed", t("processing:summarizing"), "progress"],
  ["done", "completed", t("meeting:ready"), "success"],
] as const)("shows the %s stage as %s without calling it ready early", (stage, processState, label, tone) => {
  render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1"
    stage={stage} processState={processState} turns={[]} manifest={null} />);
  const badge = document.querySelector(".ui-status-badge");
  expect(badge).toHaveTextContent(label);
  expect(badge).toHaveClass(`ui-status-badge--${tone}`);
  if (stage !== "done") expect(screen.queryByText(t("meeting:ready"))).not.toBeInTheDocument();
});

it("shows no status badge while the stage is unknown to the page", () => {
  open();
  expect(document.querySelector(".ui-status-badge")).not.toBeInTheDocument();
});

describe("MeetingHeader speakers entry", () => {
  function withSpeakers(speakerReview?: { pendingCount: number; hasUnnamed: boolean; onReview: () => void }) {
    return render(<MeetingHeader title="Synthetic meeting" createdAt={null} meetingId="m1"
      manifest={null} turns={[]} speakerReview={speakerReview} />);
  }

  it("renders no speakers icon without review data", () => {
    withSpeakers();
    expect(screen.queryByRole("button", { name: speakersName })).not.toBeInTheDocument();
  });

  it("puts the icon right before the download button and names the pending count; the dot is decorative", () => {
    withSpeakers({ pendingCount: 3, hasUnnamed: false, onReview: vi.fn() });
    const icon = screen.getByRole("button", { name: t("meeting:speakersButtonPending", { count: 3 }) });
    expect(icon).toHaveAccessibleName(t("meeting:speakersButtonPending", { count: 3 }));
    expect(icon).toHaveClass("ui-icon-button", "ui-icon-button--ghost", "ui-icon-button--alert");
    expect(icon).toHaveAttribute("aria-haspopup", "dialog");
    expect(icon).toHaveAttribute("aria-expanded", "false");
    expect(icon.textContent).toBe("");
    const order = screen.getAllByRole("button").map(button => button.getAttribute("aria-label"));
    expect(order).toEqual([t("meeting:speakersButtonPending", { count: 3 }), t("meeting:download"), t("meeting:moreActions")]);
  });

  it("shows the message and the link in a popover; the link closes it and calls onReview", () => {
    const onReview = vi.fn();
    withSpeakers({ pendingCount: 1, hasUnnamed: false, onReview });
    fireEvent.click(screen.getByRole("button", { name: t("meeting:speakersButtonPending", { count: 1 }) }));
    const popover = screen.getByRole("dialog", { name: t("meeting:speakersPanel") });
    expect(popover).toHaveTextContent(t("meeting:pendingSpeakers", { count: 1 }));
    fireEvent.click(within(popover).getByRole("button", { name: t("meeting:reviewSpeakers") }));
    expect(onReview).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("has no dot and offers editing when nothing is pending", () => {
    withSpeakers({ pendingCount: 0, hasUnnamed: true, onReview: vi.fn() });
    const icon = screen.getByRole("button", { name: t("meeting:speakersButton") });
    expect(icon).not.toHaveClass("ui-icon-button--alert");
    fireEvent.click(icon);
    expect(screen.getByText(t("meeting:speakersSomeUnnamed"))).toBeVisible();
    expect(screen.getByRole("button", { name: t("meeting:editSpeakers") })).toBeVisible();
  });
});
