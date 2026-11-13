// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps personal settings behind login and navigates back to meetings", async () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  });
  const fetchStub = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/auth/login")) return new Response(JSON.stringify({ access_token: "synthetic-token" }), { status: 200 });
    if (path.endsWith("/meetings") || path.endsWith("/templates") || path.endsWith("/templates/categories")) {
      return new Response(JSON.stringify([]), { status: 200 });
    }
    throw Error(`Unexpected route: ${path}`);
  });
  vi.stubGlobal("fetch", fetchStub);
  render(<App />);
  expect(screen.queryByRole("button", { name: "Summary template settings" })).toBeNull();
  expect(fetchStub).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox", { name: /email/i }), { target: { value: "user@example.test" } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "synthetic-password" } });
  fireEvent.click(screen.getByRole("button", { name: /log in/i }));
  fireEvent.click(await screen.findByRole("button", { name: "Summary template settings" }));
  expect(await screen.findByRole("heading", { name: "Personal summary templates" })).toBeDefined();
  await waitFor(() => expect(fetchStub.mock.calls.map(([input]) => String(input))).toEqual(expect.arrayContaining([
    expect.stringContaining("/templates"), expect.stringContaining("/templates/categories"),
  ])));
  fireEvent.click(screen.getByRole("button", { name: "Back to meetings" }));
  expect(await screen.findByRole("button", { name: "Summary template settings" })).toBeDefined();
});
