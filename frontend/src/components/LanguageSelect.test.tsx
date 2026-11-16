// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryStorage } from "../test/storage";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LanguageSelect } from "./LanguageSelect";
import { LoginScreen } from "./LoginScreen";
import { LANGUAGE_NAMES, LANGUAGE_STORAGE_KEY, t } from "../i18n";

beforeEach(() => { vi.stubGlobal("localStorage", createMemoryStorage()); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("LanguageSelect", () => {
  it("is a labeled radio group with each language written in itself", () => {
    render(<LanguageSelect />);
    const group = screen.getByRole("group", { name: t("language:label") });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: LANGUAGE_NAMES.es })).toBeChecked();
    expect(screen.getByRole("radio", { name: LANGUAGE_NAMES.en })).not.toBeChecked();
    expect(screen.getByText(LANGUAGE_NAMES.en).closest("label")).toHaveAttribute("lang", "en");
  });

  it("switches the interface, announces it in the new language, sets the page language and remembers it", async () => {
    render(<LanguageSelect />);
    fireEvent.click(screen.getByRole("radio", { name: LANGUAGE_NAMES.en }));
    await waitFor(() => expect(screen.getByRole("group", { name: "Interface language" })).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent(`Language changed to ${LANGUAGE_NAMES.en}.`);
    expect(screen.getByRole("radio", { name: LANGUAGE_NAMES.en })).toBeChecked();
    expect(document.documentElement.lang).toBe("en");
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");

    fireEvent.click(screen.getByRole("radio", { name: LANGUAGE_NAMES.es }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(`Idioma cambiado a ${LANGUAGE_NAMES.es}.`));
    expect(document.documentElement.lang).toBe("es");
  });

  it("is made of native radios in one group, so the arrow keys move the choice", async () => {
    render(<LanguageSelect />);
    const spanish = screen.getByRole("radio", { name: LANGUAGE_NAMES.es });
    spanish.focus();
    expect(document.activeElement).toBe(spanish);
    expect(spanish).toHaveAttribute("type", "radio");
    expect(spanish).toHaveAttribute("name", screen.getByRole("radio", { name: LANGUAGE_NAMES.en }).getAttribute("name"));
  });
});

describe("login screen", () => {
  it("offers the language choice before signing in and retranslates the form", async () => {
    render(<LoginScreen onLogin={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Bienvenido a Sauri" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: LANGUAGE_NAMES.en }));
    expect(await screen.findByRole("heading", { name: "Welcome to Sauri" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});
