// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { FolderUsage, RelocateResult, SauriDesktop } from "../../desktop-bridge";
import { formatBytes } from "./engineLabels";
import { relocateMessage, StorageSettings } from "./StorageSettings";
import { t } from "../../i18n";

const FOLDERS: FolderUsage[] = [
  { kind: "recordings", path: "/Users/test/Sauri/Recordings", usedBytes: 3_200_000_000, freeBytes: 120_000_000_000 },
  { kind: "database", path: "/Users/test/Sauri/Database", usedBytes: 80_000_000, freeBytes: 120_000_000_000 },
  { kind: "models", path: "/Volumes/External/Models", usedBytes: null, freeBytes: null },
];

function bridge(result: RelocateResult | Promise<RelocateResult>) {
  return {
    getPaths: vi.fn(async (): Promise<FolderUsage[]> => FOLDERS),
    relocate: vi.fn(async () => result),
    markSetupDone: vi.fn(async () => undefined),
  } satisfies SauriDesktop;
}

afterEach(() => {
  cleanup();
  delete window.sauriDesktop;
});

describe("StorageSettings", () => {
  it("in a normal browser tells the person to open the app", () => {
    render(<StorageSettings />);
    expect(screen.getByRole("heading", { name: t("settings:storage.browserOnly") })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cambiar|change/i })).toBeNull();
  });

  it("shows each folder with its size, the free space of its disk, and a missing folder plainly", async () => {
    window.sauriDesktop = bridge({ ok: false, reason: "cancelled" });
    render(<StorageSettings />);
    const recordings = await screen.findByRole("region", { name: t("settings:storage.kinds.recordings.label") });
    expect(within(recordings).getByText("/Users/test/Sauri/Recordings")).toBeInTheDocument();
    expect(recordings).toHaveTextContent(t("settings:storage.used", { size: formatBytes(3_200_000_000) }));
    expect(recordings).toHaveTextContent(t("settings:storage.free", { size: formatBytes(120_000_000_000) }));
    const models = screen.getByRole("region", { name: t("settings:storage.kinds.models.label") });
    expect(within(models).getByText(t("settings:storage.missing"))).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^.+$/ })).toHaveLength(3);
  });

  it("asks the app to move a folder, says it is working, reports the result and reads the folders again", async () => {
    let finish: (result: RelocateResult) => void = () => undefined;
    const pending = new Promise<RelocateResult>((resolve) => (finish = resolve));
    const api = bridge(pending);
    window.sauriDesktop = api;
    render(<StorageSettings />);
    const label = t("settings:storage.changeLabel", { kind: t("settings:storage.kinds.recordings.label").toLowerCase() });
    fireEvent.click(await screen.findByRole("button", { name: label }));
    expect(api.relocate).toHaveBeenCalledWith("recordings");
    expect(await screen.findByText(t("settings:storage.moving"))).toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
    finish({ ok: true, kind: "recordings", path: "/Volumes/External/Recordings", previous: FOLDERS[0].path, previousTrashed: false });
    expect(
      await screen.findByText(t("settings:storage.moved", { kind: t("settings:storage.kinds.recordings.label"), path: "/Volumes/External/Recordings" })),
    ).toBeInTheDocument();
    await waitFor(() => expect(api.getPaths).toHaveBeenCalledTimes(2));
  });

  it("explains a refusal while meetings are processed", async () => {
    window.sauriDesktop = bridge({ ok: false, reason: "processing", count: 2 });
    render(<StorageSettings />);
    const label = t("settings:storage.changeLabel", { kind: t("settings:storage.kinds.models.label").toLowerCase() });
    fireEvent.click(await screen.findByRole("button", { name: label }));
    expect(await screen.findByRole("alert")).toHaveTextContent(t("settings:storage.errors.processing", { count: 2 }));
  });
});

describe("relocateMessage", () => {
  it("has a sentence for every refusal and none for a closed dialog", () => {
    expect(relocateMessage({ ok: false, reason: "cancelled" })).toBeNull();
    expect(relocateMessage({ ok: false, reason: "no_space", neededBytes: 5e9, freeBytes: 1e9 })?.text).toBe(
      t("settings:storage.errors.no_space", { needed: formatBytes(5e9), free: formatBytes(1e9) }),
    );
    for (const reason of [
      "status_unavailable", "busy", "same", "nested", "not_empty", "not_writable", "not_a_directory", "foreign",
      "duplicate", "unavailable", "unsupported_file", "copy_failed", "verify_failed",
    ] as const) {
      const message = relocateMessage({ ok: false, reason, detail: "audio/a.webm" });
      expect(message?.kind).toBe("error");
      expect(message?.text).not.toContain("settings:");
      expect(message?.text).not.toContain("{{");
    }
    expect(relocateMessage({ ok: false, reason: "verify_failed", detail: "audio/a.webm" })?.text).toContain("audio/a.webm");
  });
});
