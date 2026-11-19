// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { FolderUsage, RelocateProgress, RelocateResult, SauriDesktop } from "../../desktop-bridge";
import { formatBytes } from "./engineLabels";
import { ESTIMATE_AFTER_MS, progressText, relocateMessage, remainingText, StorageSettings } from "./StorageSettings";
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

/** A bridge of an app that reports each step of the move, with a hand to send them and to finish the move. */
function reportingBridge() {
  let finish: (result: RelocateResult) => void = () => undefined;
  const listeners = new Set<(progress: RelocateProgress) => void>();
  const api = {
    ...bridge(new Promise<RelocateResult>((resolve) => (finish = resolve))),
    onRelocateProgress: vi.fn((listener: (progress: RelocateProgress) => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }),
  } satisfies SauriDesktop;
  const send = (progress: RelocateProgress) => act(() => listeners.forEach((listener) => listener(progress)));
  return { api, send, finish: (result: RelocateResult) => act(async () => finish(result)), listeners };
}

const label = (kind: FolderUsage["kind"]) =>
  t("settings:storage.changeLabel", { kind: t(`settings:storage.kinds.${kind}.label`).toLowerCase() });

afterEach(() => {
  vi.restoreAllMocks();
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

describe("StorageSettings while a folder moves", () => {
  it("shows each step on the moving folder's card and keeps every «Cambiar» disabled until the end", async () => {
    const { api, send, finish } = reportingBridge();
    window.sauriDesktop = api;
    render(<StorageSettings />);
    fireEvent.click(await screen.findByRole("button", { name: label("models") }));
    const card = screen.getByRole("region", { name: t("settings:storage.kinds.models.label") });
    // Before the app's first answer.
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.preparing"));
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();

    send({ kind: "models", phase: "choosing" });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.choosing"));
    expect(within(card).queryByRole("progressbar")).toBeNull();
    expect(within(card).queryByText(t("settings:storage.progress.keepOpen"))).toBeNull();

    send({ kind: "models", phase: "preparing" });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.preparing"));
    expect(within(card).getByText(t("settings:storage.progress.keepOpen"))).toBeInTheDocument();

    send({ kind: "models", phase: "copying", bytesDone: 2_100_000_000, bytesTotal: 6_400_000_000 });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.copying"));
    const bytes = t("settings:storage.progress.bytes", { done: formatBytes(2_100_000_000), total: formatBytes(6_400_000_000) });
    expect(card).toHaveTextContent(bytes);
    const bar = within(card).getByRole("progressbar", { name: t("settings:storage.progress.label", { kind: t("settings:storage.kinds.models.label").toLowerCase() }) });
    expect(bar).toHaveAttribute("aria-valuenow", "33");
    expect(bar).toHaveAttribute("aria-valuetext", bytes);
    // The live region holds the step only, so a screen reader is not read every byte count.
    expect(within(card).getByRole("status")).not.toHaveTextContent(bytes);
    expect(within(card).getByRole("status")).toHaveAttribute("aria-live", "polite");

    send({ kind: "models", phase: "verifying", bytesDone: 6_400_000_000, bytesTotal: 6_400_000_000 });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.verifying"));
    expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");

    send({ kind: "models", phase: "switching" });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.switching"));
    expect(within(card).queryByRole("progressbar")).toBeNull();
    expect(within(card).queryByText(t("settings:storage.progress.keepOpen"))).toBeNull();

    send({ kind: "models", phase: "restarting" });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.restarting"));
    send({ kind: "models", phase: "confirm_trash" });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.confirm_trash"));
    send({ kind: "models", phase: "trashing" });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.trashing"));
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();

    // Another folder's events never reach this card.
    send({ kind: "recordings", phase: "copying", bytesDone: 1, bytesTotal: 2 });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.trashing"));

    await finish({ ok: true, kind: "models", path: "/Volumes/External/Models", previous: FOLDERS[2].path, previousTrashed: true });
    const done = t("settings:storage.movedTrashed", { kind: t("settings:storage.kinds.models.label"), path: "/Volumes/External/Models" });
    const after = await screen.findByRole("region", { name: t("settings:storage.kinds.models.label") });
    expect(await within(after).findByText(done)).toBeInTheDocument();
    expect(within(after).queryByRole("progressbar")).toBeNull();
    for (const button of screen.getAllByRole("button")) expect(button).toBeEnabled();
  });

  it("says the database is restarted when the database moves", async () => {
    const { api, send } = reportingBridge();
    window.sauriDesktop = api;
    render(<StorageSettings />);
    fireEvent.click(await screen.findByRole("button", { name: label("database") }));
    send({ kind: "database", phase: "restarting" });
    const card = screen.getByRole("region", { name: t("settings:storage.kinds.database.label") });
    expect(within(card).getByRole("status")).toHaveTextContent(t("settings:storage.progress.restartingDatabase"));
  });

  it("shows a failed move on its card with the existing wording and lets the person try again", async () => {
    const { api, send, finish } = reportingBridge();
    window.sauriDesktop = api;
    render(<StorageSettings />);
    fireEvent.click(await screen.findByRole("button", { name: label("recordings") }));
    send({ kind: "recordings", phase: "copying", bytesDone: 10, bytesTotal: 100 });
    send({ kind: "recordings", phase: "restarting" });
    await finish({ ok: false, reason: "copy_failed", detail: "audio/a.webm" });
    const card = await screen.findByRole("region", { name: t("settings:storage.kinds.recordings.label") });
    expect(await within(card).findByRole("alert")).toHaveTextContent(t("settings:storage.errors.copy_failed"));
    expect(within(card).queryByRole("progressbar")).toBeNull();
    for (const button of screen.getAllByRole("button")) expect(button).toBeEnabled();
  });

  it("stops listening when the page closes", async () => {
    const { api, listeners } = reportingBridge();
    window.sauriDesktop = api;
    const view = render(<StorageSettings />);
    await screen.findByRole("button", { name: label("recordings") });
    expect(listeners.size).toBe(1);
    view.unmount();
    expect(listeners.size).toBe(0);
  });

  it("estimates the time left from the pace of the copy, only after a few seconds", async () => {
    const { api, send } = reportingBridge();
    window.sauriDesktop = api;
    let clock = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => clock);
    render(<StorageSettings />);
    fireEvent.click(await screen.findByRole("button", { name: label("models") }));
    const card = screen.getByRole("region", { name: t("settings:storage.kinds.models.label") });
    send({ kind: "models", phase: "copying", bytesDone: 0, bytesTotal: 6_000_000_000 });
    clock += 2000;
    send({ kind: "models", phase: "copying", bytesDone: 100_000_000, bytesTotal: 6_000_000_000 });
    expect(card).not.toHaveTextContent(t("settings:storage.progress.minutesLeft", { count: 2 }));
    // 1 GB in 60 s: 5 GB left is about 5 minutes.
    clock += 58_000;
    send({ kind: "models", phase: "copying", bytesDone: 1_000_000_000, bytesTotal: 6_000_000_000 });
    expect(card).toHaveTextContent(t("settings:storage.progress.minutesLeft", { count: 5 }));
  });
});

describe("move step texts", () => {
  it("has a sentence for every step, in both languages' keys, and a time estimate only with enough data", () => {
    for (const phase of ["choosing", "preparing", "copying", "verifying", "switching", "restarting", "confirm_trash", "trashing"] as const) {
      for (const kind of ["recordings", "database", "models"] as const) {
        const text = progressText({ kind, phase });
        expect(text).not.toContain("settings:");
        expect(text.length).toBeGreaterThan(3);
      }
    }
    const progress: RelocateProgress = { kind: "models", phase: "copying", bytesDone: 50, bytesTotal: 100 };
    expect(remainingText(progress, null, 0)).toBeNull();
    expect(remainingText(progress, { at: 0, bytes: 0 }, ESTIMATE_AFTER_MS - 1)).toBeNull();
    expect(remainingText(progress, { at: 0, bytes: 50 }, ESTIMATE_AFTER_MS)).toBeNull();
    expect(remainingText(progress, { at: 0, bytes: 0 }, 10_000)).toBe(t("settings:storage.progress.lessThanMinute"));
    expect(remainingText({ ...progress, phase: "verifying" }, { at: 0, bytes: 0 }, 10_000)).toBeNull();
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
