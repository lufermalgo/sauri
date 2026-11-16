// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ENABLED_LOGIN_PROVIDERS, LoginProviders } from "./LoginProviders";
import { copy } from "../copy/es";

afterEach(cleanup);

describe("login providers area", () => {
  it("is empty today: no external sign-in is enabled", () => {
    expect(ENABLED_LOGIN_PROVIDERS).toHaveLength(0);
  });

  it("renders nothing when the provider list is empty", () => {
    const { container } = render(<LoginProviders providers={[]} />);

    expect(container.innerHTML).toBe("");
    expect(screen.queryByText(copy.login.providersSeparator)).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders the separator and one button per provider, and starts the chosen flow", () => {
    const onSelectFirst = vi.fn();
    const onSelectSecond = vi.fn();
    render(
      <LoginProviders
        providers={[
          { id: "first", label: "Continuar con uno", icon: <svg data-testid="glyph" />, onSelect: onSelectFirst },
          { id: "second", label: "Continuar con dos", onSelect: onSelectSecond },
        ]}
      />,
    );

    expect(screen.getByText(copy.login.providersSeparator)).toBeTruthy();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByTestId("glyph")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continuar con dos" }));
    expect(onSelectSecond).toHaveBeenCalledTimes(1);
    expect(onSelectFirst).not.toHaveBeenCalled();
  });

  it("disables the buttons while a sign-in is in progress", () => {
    render(<LoginProviders disabled providers={[{ id: "first", label: "Continuar con uno", onSelect: vi.fn() }]} />);

    expect((screen.getByRole("button", { name: "Continuar con uno" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
