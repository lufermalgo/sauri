// Example-based test: Transcript_Search (Req. 9.1-9.5)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TranscriptSearch } from "./TranscriptSearch";
import type { InterventionDTO } from "../core/types";

const interventions: InterventionDTO[] = [
  { turnId: "t1", text: "Hablemos del presupuesto", startMs: 0, endMs: 1000, sequence: 0, speaker: null }, // spanish-sample-data
  { turnId: "t2", text: "El PRESUPUESTO ya se aprobó", startMs: 2000, endMs: 3000, sequence: 0, speaker: null }, // spanish-sample-data
];

describe("TranscriptSearch", () => {
  it("reports case-insensitive matches, first by start_ms (Req. 9.1, 9.2)", async () => {
    const onResult = vi.fn();
    render(<TranscriptSearch interventions={interventions} onResult={onResult} />);
    fireEvent.change(screen.getByLabelText(/search the transcript/i), { target: { value: "presupuesto" } }); // spanish-sample-data

    await waitFor(() => {
      const lastCall = onResult.mock.calls.at(-1)?.[0];
      expect(lastCall.matchingTurnIds).toEqual(["t1", "t2"]);
      expect(lastCall.firstMatchId).toBe("t1");
    });
  });

  it("clears highlights and keeps original order with blank text (Req. 9.3)", async () => {
    const onResult = vi.fn();
    render(<TranscriptSearch interventions={interventions} onResult={onResult} />);
    fireEvent.change(screen.getByLabelText(/search the transcript/i), { target: { value: "   " } });

    await waitFor(() => {
      const lastCall = onResult.mock.calls.at(-1)?.[0];
      expect(lastCall.matchingTurnIds).toEqual([]);
      expect(lastCall.interventions).toEqual(interventions);
    });
  });

  it("indicates no matches without altering the Interventions (Req. 9.4)", async () => {
    render(<TranscriptSearch interventions={interventions} onResult={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/search the transcript/i), { target: { value: "nonexistent" } });
    await waitFor(() => expect(screen.getByText(/no matches/i)).toBeInTheDocument());
  });

  it("limits the search text to 200 characters (Req. 9.5)", () => {
    render(<TranscriptSearch interventions={interventions} onResult={vi.fn()} />);
    expect(screen.getByLabelText(/search the transcript/i)).toHaveAttribute("maxLength", "200");
  });
});
