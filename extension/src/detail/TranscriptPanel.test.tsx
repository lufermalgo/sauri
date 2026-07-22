// Example-based test: Transcript_Panel (Req. 6.4, 6.6, 8.1-8.10, 14.3)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TranscriptPanel } from "./TranscriptPanel";
import type { InterventionDTO } from "../core/types";

const interventions: InterventionDTO[] = [
  {
    turnId: "t2",
    text: "Segunda intervención", // spanish-sample-data
    startMs: 5000,
    endMs: 8000,
    sequence: 0,
    speaker: { id: "h1", label: "Ana Pérez", sequence: 1 }, // spanish-sample-data
  },
  {
    turnId: "t1",
    text: "Primera intervención", // spanish-sample-data
    startMs: 0,
    endMs: 4000,
    sequence: 0,
    speaker: null,
  },
];

describe("TranscriptPanel", () => {
  it("presents one Intervention per Turn with label, avatar, timestamp and text (Req. 8.1, 8.3, 8.5)", () => {
    render(<TranscriptPanel state="withData" interventions={interventions} onRetry={vi.fn()} />);
    expect(screen.getByText("Segunda intervención")).toBeInTheDocument(); // spanish-sample-data
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument(); // spanish-sample-data
    expect(screen.getByText("00:05")).toBeInTheDocument();
  });

  it("shows the unidentified-speaker marker when there is no Speaker_Assignment (Req. 8.7)", () => {
    render(<TranscriptPanel state="withData" interventions={interventions} onRetry={vi.fn()} />);
    expect(screen.getByText("Unidentified speaker")).toBeInTheDocument();
  });

  it("View_State loading (Req. 8.9, 14.3)", () => {
    render(<TranscriptPanel state="loading" interventions={[]} onRetry={vi.fn()} />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("View_State empty when the Meeting has no Transcript (Req. 8.8)", () => {
    render(<TranscriptPanel state="empty" interventions={[]} onRetry={vi.fn()} />);
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
  });

  it("View_State error with a retry action (Req. 8.10)", () => {
    const onRetry = vi.fn();
    render(<TranscriptPanel state="error" interventions={[]} onRetry={onRetry} />);
    screen.getByRole("button", { name: /retry/i }).click();
    expect(onRetry).toHaveBeenCalled();
  });

  it("enables vertical scrolling over the sequence of Interventions (Req. 8.6)", () => {
    const { container } = render(
      <TranscriptPanel state="withData" interventions={interventions} onRetry={vi.fn()} />
    );
    const list = container.querySelector("ul");
    expect(list).toHaveStyle({ overflowY: "auto" });
  });
});
