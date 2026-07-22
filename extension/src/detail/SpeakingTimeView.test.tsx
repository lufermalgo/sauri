// Example-based test: Speaking_Time_View (Req. 10.1, 10.3, 10.4, 10.5, 10.6, 10.7)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SpeakingTimeView } from "./SpeakingTimeView";
import type { SpeakingTimeEntry } from "../core/types";

const entries: SpeakingTimeEntry[] = [
  { speaker: { id: "h1", label: "Ana Pérez", sequence: 1 }, timeMs: 5000 }, // spanish-sample-data
  { speaker: { id: "h2", label: "Beto Ruiz", sequence: 2 }, timeMs: 0 }, // spanish-sample-data
];

describe("SpeakingTimeView", () => {
  it("presents one entry per Speaker, including those with time 0 (Req. 10.1)", () => {
    render(<SpeakingTimeView state="withData" entries={entries} onRetry={vi.fn()} />);
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument(); // spanish-sample-data
    expect(screen.getByText("Beto Ruiz")).toBeInTheDocument(); // spanish-sample-data
    expect(screen.getByText("00:05")).toBeInTheDocument();
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });

  it("orders from highest to lowest Speaking_Time (Req. 10.4)", () => {
    render(<SpeakingTimeView state="withData" entries={entries} onRetry={vi.fn()} />);
    const names = screen.getAllByText(/Ana Pérez|Beto Ruiz/).map((el) => el.textContent); // spanish-sample-data
    expect(names).toEqual(["Ana Pérez", "Beto Ruiz"]); // spanish-sample-data
  });

  it("View_State empty when the Meeting has no Diarization (Req. 10.5)", () => {
    render(<SpeakingTimeView state="empty" entries={[]} onRetry={vi.fn()} />);
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
  });

  it("View_State loading (Req. 10.6)", () => {
    render(<SpeakingTimeView state="loading" entries={[]} onRetry={vi.fn()} />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("View_State error with a retry action (Req. 10.7)", () => {
    const onRetry = vi.fn();
    render(<SpeakingTimeView state="error" entries={[]} onRetry={onRetry} />);
    screen.getByRole("button", { name: /retry/i }).click();
    expect(onRetry).toHaveBeenCalled();
  });
});
