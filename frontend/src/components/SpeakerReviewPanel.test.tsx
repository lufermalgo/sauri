// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { avatarText, firstGrapheme, SpeakerReviewPanel, type SpeakerRowModel } from "./SpeakerReviewPanel";
import { t } from "../i18n";

afterEach(cleanup);

const [G1, G3] = [t("transcript:numberedSpeaker", { number: "1" }), t("transcript:numberedSpeaker", { number: "3" })];
const interval = { startMs: 0, endMs: 9000, short: false };
const rows: SpeakerRowModel[] = [
  { speakerId: "a", label: G1, generic: true, color: "var(--ds-speaker-1)", disposition: null, interval },
  { speakerId: "b", label: "Ana", generic: false, color: "var(--ds-speaker-2)", disposition: "named", interval: null },
  { speakerId: "c", label: G3, generic: true, color: "var(--ds-speaker-3)", disposition: null, interval },
];

function panel(overrides: Partial<Parameters<typeof SpeakerReviewPanel>[0]> = {}) {
  const props = {
    rows, complete: false, busyIds: [] as string[], playingId: null, playbackReady: true,
    playbackLoading: false, error: null, onListen: vi.fn(),
    onRename: vi.fn(async () => null as string | null), onAcceptSuggestion: vi.fn(), onLeaveUnnamed: vi.fn(async () => {}),
    ...overrides,
  };
  render(<SpeakerReviewPanel {...props} />);
  return props;
}

const article = (index: number) => screen.getAllByRole("article")[index];
const pencil = (label: string) => screen.getByRole("button", { name: t("speakerReview:editName", { label }) });
const nameInput = (label: string) => screen.getByRole("textbox", { name: t("speakerReview:nameFor", { label }) });

describe("avatar text", () => {
  it("is H1 for a generic label and the first letter of a name", () => {
    expect(avatarText(G1, true)).toBe("H1");
    expect(avatarText(t("transcript:numberedSpeaker", { number: "12" }), true)).toBe("H12");
    expect(avatarText("ana", false)).toBe("A");
    expect(avatarText("  \u00e1lvaro", false)).toBe("\u00c1");
    expect(avatarText("\u00d1and\u00fa", false)).toBe("\u00d1");
  });

  it("keeps an emoji or a combined character whole", () => {
    expect(firstGrapheme("🎉 Fiesta")).toBe("🎉");
    expect(firstGrapheme("👩🏽‍💻 Dev")).toBe("👩🏽‍💻");
    expect(firstGrapheme("école")).toBe("É");
  });

  it("renders in each row's avatar", () => {
    panel();
    expect(within(article(0)).getByText("H1")).toBeInTheDocument();
    expect(within(article(1)).getByText("A")).toBeInTheDocument();
    expect(within(article(2)).getByText("H3")).toBeInTheDocument();
  });
});

describe("SpeakerReviewPanel", () => {
  it("marks only the speaker talking now as the current row", () => {
    panel({ speakingId: "c" });
    expect(article(2)).toHaveAttribute("aria-current", "true");
    expect(article(2)).toHaveClass("meeting-review-item--speaking");
    expect(article(0)).not.toHaveAttribute("aria-current");
  });

  it("announces the pending and the complete state", () => {
    panel();
    expect(screen.getByText(t("speakerReview:pending"))).toBeInTheDocument();
    cleanup();
    panel({ complete: true });
    expect(screen.getByText(t("speakerReview:complete"))).toBeInTheDocument();
  });

  it("lists one row per speaker with its status, a play icon first and a pencil last", () => {
    panel();
    expect(article(0)).toHaveTextContent(t("speakerReview:pendingState"));
    expect(article(1)).toHaveTextContent(t("speakerReview:namedState"));
    const buttons = within(article(0)).getAllByRole("button");
    expect(buttons.map(button => button.getAttribute("aria-label"))).toEqual([t("speakerReview:listenTo", { label: G1 }), t("speakerReview:editName", { label: G1 })]);
    for (const button of buttons) {
      expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
      expect(button).toHaveTextContent("");
    }
    expect(within(article(1)).getByRole("button", { name: t("speakerReview:listenTo", { label: "Ana" }) })).toBeDisabled();
    expect(screen.getByText(t("speakerReview:noInterval"))).toBeInTheDocument();
  });

  it("has no text buttons for saving, confirming, correcting or listening", () => {
    panel();
    for (const name of ["Guardar", "Confirmar", "Corregir", "Escuchar", "Detener"]) {
      expect(screen.queryByRole("button", { name: new RegExp(`^${name}$`) })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("toggles the play button to a pressed pause state while that speaker plays", () => {
    const props = panel({ playingId: "a" });
    const play = screen.getByRole("button", { name: t("speakerReview:listenTo", { label: G1 }) });
    expect(play).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: t("speakerReview:listenTo", { label: G3 }) })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(play);
    expect(props.onListen).toHaveBeenCalledWith(rows[0]);
  });

  it("shows the error inside the panel", () => {
    panel({ error: t("speakerReview:playbackFailed") });
    expect(screen.getByRole("alert")).toHaveTextContent(t("speakerReview:playbackFailed"));
  });

  describe("inline name editing", () => {
    it("opens an input on the pencil with the name selected and focused", () => {
      panel();
      fireEvent.click(pencil(G1));
      const input = nameInput(G1) as HTMLInputElement;
      expect(input).toHaveFocus();
      expect(input.value).toBe(G1);
      expect(input.selectionStart).toBe(0);
      expect(input.selectionEnd).toBe(G1.length);
      expect(screen.queryByRole("button", { name: t("speakerReview:editName", { label: G1 }) })).not.toBeInTheDocument();
    });

    it("saves the trimmed name once on Enter, announces it and returns focus to the pencil", async () => {
      const props = panel();
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "  Luisa  " } });
      fireEvent.keyDown(nameInput(G1), { key: "Enter" });
      await waitFor(() => expect(props.onRename).toHaveBeenCalledTimes(1));
      expect(props.onRename).toHaveBeenCalledWith("a", "Luisa");
      await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
      expect(pencil(G1)).toHaveFocus();
      expect(screen.getByText(t("speakerReview:saved", { name: "Luisa" }))).toBeInTheDocument();
      expect(props.onRename).toHaveBeenCalledTimes(1);
    });

    it("saves on blur without taking focus back", async () => {
      const props = panel();
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "Luisa" } });
      fireEvent.blur(nameInput(G1));
      await waitFor(() => expect(props.onRename).toHaveBeenCalledWith("a", "Luisa"));
      await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
      expect(pencil(G1)).not.toHaveFocus();
      expect(props.onRename).toHaveBeenCalledTimes(1);
    });

    it("cancels on Escape without saving, keeps the dialog's Escape out and returns focus to the pencil", () => {
      const props = panel();
      const outer = vi.fn();
      document.addEventListener("keydown", outer);
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "Luisa" } });
      fireEvent.keyDown(nameInput(G1), { key: "Escape" });
      expect(outer.mock.calls[0][0].defaultPrevented).toBe(true);
      document.removeEventListener("keydown", outer);
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(pencil(G1)).toHaveFocus();
      expect(props.onRename).not.toHaveBeenCalled();
      expect(article(0)).toHaveTextContent(G1);
    });

    it("does not call the API for an unchanged name", () => {
      const props = panel();
      fireEvent.click(pencil("Ana"));
      fireEvent.keyDown(nameInput("Ana"), { key: "Enter" });
      expect(props.onRename).not.toHaveBeenCalled();
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      fireEvent.click(pencil("Ana"));
      fireEvent.change(nameInput("Ana"), { target: { value: "  Ana " } });
      fireEvent.blur(nameInput("Ana"));
      expect(props.onRename).not.toHaveBeenCalled();
    });

    it("does not save an empty name: Enter explains it, blur cancels", () => {
      const props = panel();
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "   " } });
      fireEvent.keyDown(nameInput(G1), { key: "Enter" });
      expect(screen.getByText(t("speakerReview:nameRequired"), { selector: "p" })).toBeInTheDocument();
      expect(nameInput(G1)).toHaveAttribute("aria-invalid", "true");
      fireEvent.blur(nameInput(G1));
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
      expect(props.onRename).not.toHaveBeenCalled();
      expect(article(0)).toHaveTextContent(G1);
    });

    it("ignores Enter while an input method composition is open", () => {
      const props = panel();
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "Luisa" } });
      fireEvent.keyDown(nameInput(G1), { key: "Enter", isComposing: true });
      expect(props.onRename).not.toHaveBeenCalled();
    });

    it("shows a busy state while saving, keeps the input and focus, and ignores a second commit", async () => {
      let finish: (message: string | null) => void = () => {};
      const onRename = vi.fn(() => new Promise<string | null>(resolve => { finish = resolve; }));
      panel({ onRename });
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "Luisa" } });
      fireEvent.keyDown(nameInput(G1), { key: "Enter" });
      expect(article(0)).toHaveAttribute("aria-busy", "true");
      expect(nameInput(G1)).toHaveAttribute("readonly");
      expect(nameInput(G1)).toHaveFocus();
      fireEvent.keyDown(nameInput(G1), { key: "Enter" });
      fireEvent.blur(nameInput(G1));
      expect(onRename).toHaveBeenCalledTimes(1);
      await act(async () => finish(null));
      expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    });

    it("keeps the input open with the typed text, the error and the focus when the save fails", async () => {
      const onRename = vi.fn(async () => t("speakerReview:saveFailed") as string | null);
      panel({ onRename });
      fireEvent.click(pencil(G1));
      fireEvent.change(nameInput(G1), { target: { value: "Luisa" } });
      fireEvent.keyDown(nameInput(G1), { key: "Enter" });
      expect(await screen.findByText(t("speakerReview:saveFailed"), { selector: "p" })).toBeInTheDocument();
      const input = nameInput(G1) as HTMLInputElement;
      expect(input.value).toBe("Luisa");
      expect(input).toHaveFocus();
      expect(input).not.toHaveAttribute("readonly");
      expect(input).toHaveAttribute("aria-invalid", "true");
      expect(input).toHaveAccessibleDescription(t("speakerReview:saveFailed"));
      expect(screen.getAllByRole("status").some(region => region.textContent === t("speakerReview:saveFailed"))).toBe(true);
      // Retrying works.
      onRename.mockResolvedValueOnce(null);
      fireEvent.keyDown(input, { key: "Enter" });
      await waitFor(() => expect(onRename).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(screen.queryByRole("textbox")).not.toBeInTheDocument());
    });
  });

  describe("leaving speakers unnamed", () => {
    it("offers one text link while a speaker with the generic label is pending and runs it once", async () => {
      const props = panel();
      fireEvent.click(screen.getByRole("button", { name: t("speakerReview:leaveUnnamed") }));
      await waitFor(() => expect(props.onLeaveUnnamed).toHaveBeenCalledTimes(1));
      expect(await screen.findByText(t("speakerReview:leftUnnamed"))).toBeInTheDocument();
    });

    it("disappears when no generic speaker is pending", () => {
      panel({ rows: [rows[1], { ...rows[0], disposition: "confirmed" }] });
      expect(screen.queryByRole("button", { name: t("speakerReview:leaveUnnamed") })).not.toBeInTheDocument();
      expect(article(1)).toHaveTextContent(t("speakerReview:unnamedState"));
    });
  });

  describe("machine-suggested names", () => {
    const suggested: SpeakerRowModel = { speakerId: "s", label: "Known Speaker", generic: false, color: "var(--ds-speaker-4)", disposition: null, interval };

    it("shows a one-tap chip that keeps the suggestion, and the first letter in the avatar", () => {
      const props = panel({ rows: [suggested] });
      expect(article(0)).toHaveTextContent(t("speakerReview:suggestedState"));
      expect(within(article(0)).getByText("K")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: t("speakerReview:acceptSuggestion", { name: "Known Speaker" }) }));
      expect(props.onAcceptSuggestion).toHaveBeenCalledWith("s");
    });

    it("has no chip once the name is accepted", () => {
      panel({ rows: [{ ...suggested, disposition: "confirmed" }] });
      expect(screen.queryByRole("button", { name: t("speakerReview:acceptSuggestion", { name: "Known Speaker" }) })).not.toBeInTheDocument();
      expect(article(0)).toHaveTextContent(t("speakerReview:namedState"));
    });
  });
});
