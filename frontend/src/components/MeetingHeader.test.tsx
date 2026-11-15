// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MeetingHeader } from "./MeetingHeader";
import { deleteMeeting, renameMeeting } from "../api";
import { navigate } from "../router";
import { meeting as text } from "../copy/meeting";

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
    open(); fireEvent.click(screen.getByRole("button", { name: text.delete }));
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
    open(); fireEvent.click(screen.getByRole("button", { name: text.delete }));
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
    open(); fireEvent.click(screen.getByRole("button", { name: text.delete }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: text.delete }));
    expect(await screen.findByRole("alert")).toHaveTextContent(text.deleteFailed);
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Synthetic meeting");
  });
});
