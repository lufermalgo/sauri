// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { DesktopUpdates, UpdateStatus } from "../../desktop-bridge";
import { UpdateSettings } from "./UpdateSettings";
import { t } from "../../i18n";

function updates(first: UpdateStatus, after: Partial<UpdateStatus> = {}) {
  const next: UpdateStatus = { ...first, ...after };
  return {
    status: vi.fn(async (): Promise<UpdateStatus> => first),
    check: vi.fn(async (): Promise<UpdateStatus> => next),
    apply: vi.fn(async (): Promise<UpdateStatus> => next),
    setAutoCheck: vi.fn(async (on: boolean): Promise<UpdateStatus> => ({ ...first, autoCheck: on })),
  } satisfies DesktopUpdates;
}

const BASE: UpdateStatus = { state: "idle", current: "0.1.0", autoCheck: true };

afterEach(cleanup);

describe("UpdateSettings", () => {
  it("says updates are not available yet when there is no download place, with no buttons", async () => {
    render(<UpdateSettings updates={updates({ ...BASE, state: "disabled" })} />);
    expect(await screen.findByText(t("settings:updates.disabled"))).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("checks on demand and says when this is the latest version", async () => {
    const api = updates(BASE, { state: "up_to_date" });
    render(<UpdateSettings updates={api} pollIntervalMs={5} />);
    fireEvent.click(await screen.findByRole("button", { name: t("settings:updates.check") }));
    expect(await screen.findByText(t("settings:updates.upToDate"))).toBeInTheDocument();
    expect(api.check).toHaveBeenCalledOnce();
  });

  it("turns the automatic checks off with the switch", async () => {
    const api = updates(BASE);
    render(<UpdateSettings updates={api} />);
    const box = await screen.findByRole("checkbox", { name: t("settings:updates.auto") });
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(api.setAutoCheck).toHaveBeenCalledWith(false);
    expect(await screen.findByRole("checkbox", { name: t("settings:updates.auto") })).not.toBeChecked();
  });

  it("offers «Reiniciar y actualizar» for a verified version and explains a refusal while meetings are processed", async () => {
    const api = updates({ ...BASE, state: "ready", version: "0.1.1" }, { error: "processing", count: 2 });
    render(<UpdateSettings updates={api} />);
    fireEvent.click(await screen.findByRole("button", { name: t("settings:updates.apply", { version: "0.1.1" }) }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("settings:updates.errors.processing", { count: 2 }));
    expect(api.apply).toHaveBeenCalledOnce();
  });

  it("follows a download with its progress", async () => {
    render(<UpdateSettings updates={updates({ ...BASE, state: "downloading", version: "0.1.1", percent: 40 })} />);
    expect(await screen.findByRole("progressbar", { name: t("settings:updates.progressLabel") })).toBeInTheDocument();
    expect(screen.getByText(t("settings:updates.downloading", { version: "0.1.1", percent: 40 }))).toBeInTheDocument();
  });
});
