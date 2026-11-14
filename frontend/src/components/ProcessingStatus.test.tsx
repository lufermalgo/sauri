// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ProcessingStatus } from "./ProcessingStatus";
import { copy } from "../copy/es";

afterEach(cleanup);

describe("ProcessingStatus", () => {
  it.each(["queued", "joining", "recording", "transcribing", "completed"] as const)(
    "shows the real %s state without a percentage", (processState) => {
      render(<ProcessingStatus meeting={{ meetingId: "m-1", processState }}
        hasTranscript={false} diarizationNotFound={false} error={false} />);
      expect(screen.getByRole("status")).toHaveTextContent(copy.processing[processState]);
      expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
      expect(screen.getByRole("status").textContent).not.toContain("%");
    },
  );

  it.each(["transcribing", "completed"])("shows identification after transcript availability in %s", (processState) => {
    render(<ProcessingStatus meeting={{ meetingId: "m-1", processState }}
      hasTranscript diarizationNotFound error={false} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.processing.identifying);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not claim identification before a transcript exists", () => {
    render(<ProcessingStatus meeting={{ meetingId: "m-1", processState: "transcribing" }}
      hasTranscript={false} diarizationNotFound error={false} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.processing.transcribing);
  });

  it.each(["could_not_join", "meeting_cancelled", "engine_failure", "engine_failed",
    "engine_contract_mismatch", "invalid_response", "unknown", null])(
    "explains failure %s without exposing raw diagnostics or inventing a retry", (failureCause) => {
      render(<ProcessingStatus meeting={{ meetingId: "m-1", processState: "failed", failureCause }}
        hasTranscript diarizationNotFound error={false} />);
      expect(screen.getByRole("status")).toHaveTextContent(copy.processing.failed);
      expect(screen.getByRole("status")).toHaveTextContent(copy.processing.failureCause(failureCause));
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    },
  );

  it("does not turn a state load failure into a processing state", () => {
    render(<ProcessingStatus meeting={null} hasTranscript={false} diarizationNotFound={false} error />);
    expect(screen.getByRole("alert")).toHaveTextContent(copy.processing.loadFailed);
  });
});
