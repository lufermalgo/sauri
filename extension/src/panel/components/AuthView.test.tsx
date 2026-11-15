// Example-based test: Auth_View (Req. 13.2, 13.6, 13.7)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { panelCopy as copy } from "../copy";
import { AuthView } from "./AuthView";

describe("AuthView", () => {
  it("presents the login flow (Req. 13.2)", () => {
    render(<AuthView onLogin={vi.fn()} />);
    expect(screen.getByLabelText(copy.email)).toBeInTheDocument();
    expect(screen.getByLabelText(copy.password)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.login })).toBeInTheDocument();
  });

  it("a valid login invokes onLogin with the credentials", async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    render(<AuthView onLogin={onLogin} />);
    fireEvent.change(screen.getByLabelText(copy.email), { target: { value: "a@summan.com" } });
    fireEvent.change(screen.getByLabelText(copy.password), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: copy.login }));

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith("a@summan.com", "secret"));
  });

  it("locks new attempts after 5 consecutive failures (Req. 13.6)", async () => {
    const onLogin = vi.fn().mockRejectedValue(new Error("Invalid credentials"));
    render(<AuthView onLogin={onLogin} />);

    for (let i = 0; i < 5; i++) {
      fireEvent.change(screen.getByLabelText(copy.email), { target: { value: "a@summan.com" } });
      fireEvent.change(screen.getByLabelText(copy.password), { target: { value: "wrong" } });
      fireEvent.click(screen.getByRole("button", { name: copy.login }));
      await waitFor(() => expect(onLogin).toHaveBeenCalledTimes(i + 1));
    }

    expect(screen.getByText(copy.locked)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.login })).toBeDisabled();
  });

  it("indicates service unavailability (Req. 13.7)", () => {
    render(<AuthView onLogin={vi.fn()} unavailable />);
    expect(screen.getByText(copy.unavailable)).toBeInTheDocument();
  });
});
