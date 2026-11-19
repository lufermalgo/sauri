// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { SauriDesktop, ServicesStatus, UpdateStatus } from "../desktop-bridge";
import { DesktopNotices } from "./DesktopNotices";
import { t } from "../i18n";

const BASE: UpdateStatus = { state: "idle", current: "0.1.3", autoCheck: true };
const READY: UpdateStatus = { ...BASE, state: "ready", version: "0.1.4" };
const CALM: ServicesStatus = { starting: false, problem: false };

function install(options: { update?: UpdateStatus; applied?: UpdateStatus; services?: ServicesStatus } = {}) {
  let pushUpdate: (status: UpdateStatus) => void = () => undefined;
  let pushServices: (status: ServicesStatus) => void = () => undefined;
  const bridge = {
    getPaths: vi.fn(),
    relocate: vi.fn(),
    markSetupDone: vi.fn(),
    updates: {
      status: vi.fn(async () => options.update ?? BASE),
      check: vi.fn(),
      apply: vi.fn(async () => options.applied ?? { ...READY, state: "applying" as const }),
      setAutoCheck: vi.fn(),
      onChange: (listener: (status: UpdateStatus) => void) => {
        pushUpdate = listener;
        return () => undefined;
      },
    },
    getServicesStatus: vi.fn(async () => options.services ?? CALM),
    onServicesStatus: (listener: (status: ServicesStatus) => void) => {
      pushServices = listener;
      return () => undefined;
    },
  };
  window.sauriDesktop = bridge as unknown as SauriDesktop;
  return {
    bridge,
    pushUpdate: (status: UpdateStatus) => act(() => pushUpdate(status)),
    pushServices: (status: ServicesStatus) => act(() => pushServices(status)),
  };
}

afterEach(() => {
  cleanup();
  delete window.sauriDesktop;
});

describe("DesktopNotices", () => {
  it("shows nothing in a normal browser", () => {
    const { container } = render(<DesktopNotices />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing while Sauri is up to date and every service is ready", async () => {
    const { bridge } = install({ update: { ...BASE, state: "up_to_date" } });
    const { container } = render(<DesktopNotices />);
    await act(async () => undefined);
    expect(bridge.updates.status).toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();
  });

  it("offers the verified update as one pill that installs and restarts on click", async () => {
    const { bridge } = install({ update: READY });
    render(<DesktopNotices />);
    const pill = await screen.findByRole("button", { name: t("shell:desktop.updateLabel", { version: "0.1.4" }) });
    expect(pill).toHaveTextContent(t("shell:desktop.update", { version: "0.1.4" }));
    fireEvent.click(pill);
    expect(bridge.updates.apply).toHaveBeenCalledOnce();
    expect(await screen.findByRole("button", { name: t("shell:desktop.updating", { version: "0.1.4" }) })).toBeDisabled();
  });

  it("appears when the app says an update became ready", async () => {
    const { pushUpdate } = install();
    render(<DesktopNotices />);
    await act(async () => undefined);
    expect(screen.queryByRole("button")).toBeNull();
    pushUpdate(READY);
    expect(screen.getByRole("button", { name: t("shell:desktop.updateLabel", { version: "0.1.4" }) })).toBeInTheDocument();
  });

  it("says why the update did not install while meetings are being processed", async () => {
    install({ update: READY, applied: { ...READY, error: "processing", count: 2 } });
    render(<DesktopNotices />);
    fireEvent.click(await screen.findByRole("button", { name: t("shell:desktop.updateLabel", { version: "0.1.4" }) }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("settings:updates.errors.processing", { count: 2 }));
    expect(screen.getByRole("button", { name: t("shell:desktop.updateLabel", { version: "0.1.4" }) })).toBeEnabled();
  });

  it("shows the engines starting and hides it once they are ready", async () => {
    const { pushServices } = install({ services: { starting: true, problem: false } });
    render(<DesktopNotices />);
    expect(await screen.findByRole("status")).toHaveTextContent(t("shell:desktop.starting"));
    pushServices(CALM);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("reports a service that did not start", async () => {
    const { pushServices } = install();
    render(<DesktopNotices />);
    await act(async () => undefined);
    pushServices({ starting: false, problem: true });
    expect(screen.getByRole("alert")).toHaveTextContent(t("shell:desktop.problem"));
  });
});
