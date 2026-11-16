// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { LoginProviders, startGoogleSignIn, useLoginProviders } from "./LoginProviders";
import { t } from "../i18n";

afterEach(cleanup);

describe("login providers area", () => {
  it("has Google as the only default option, still inactive: its flag is unset", () => {
    expect(startGoogleSignIn).toBeUndefined();
    const { result } = renderHook(() => useLoginProviders());
    expect(result.current.map((provider) => provider.id)).toEqual(["google"]);
    expect(result.current[0].label).toBe(t("login:continueWithGoogle"));
    expect(result.current[0].onSelect).toBeUndefined();
  });

  it("renders nothing when the provider list is empty", () => {
    const { container } = render(<LoginProviders providers={[]} />);

    expect(container.innerHTML).toBe("");
    expect(screen.queryByText(t("login:providersSeparator"))).toBeNull();
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

    expect(screen.getByText(t("login:providersSeparator"))).toBeTruthy();
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

  it("shows an option without a handler as coming soon: focusable, aria-disabled, no action", () => {
    render(<LoginProviders providers={[{ id: "soon", label: "Continuar con pronto", icon: <svg data-testid="glyph" /> }]} />);

    const button = screen.getByRole("button", { name: "Continuar con pronto" }) as HTMLButtonElement;
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.disabled).toBe(false);
    expect(document.getElementById(button.getAttribute("aria-describedby")!)!.textContent).toBe(t("login:soon"));
    fireEvent.click(button);
    expect(screen.getByTestId("glyph")).toBeTruthy();
  });
});
