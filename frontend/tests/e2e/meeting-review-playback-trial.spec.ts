import { expect, test } from "@playwright/test";

const TRIAL_PATH = "/_trial/meeting-review-playback";
const FIXTURE_PATH = "/test-fixtures/meeting-review-playback.wav";

test("trial playback uses the real WAV and seeks to the second transcript passage", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "sauri" })).toBeVisible();
  const trialLink = page.locator(`a[href="${TRIAL_PATH}"]`);
  await expect(trialLink).toBeVisible();
  await trialLink.click();
  await expect(page).toHaveURL(new RegExp(`${TRIAL_PATH}$`));
  await expect(page.getByRole("heading", { name: "Meeting playback" })).toBeVisible();

  const media = page.getByTestId("playback-media");
  // Audio-only media has no native controls and need not occupy visible layout space.
  await expect(media).toBeAttached();
  await expect.poll(() => media.evaluate((element: HTMLMediaElement) => element.readyState)).toBeGreaterThanOrEqual(1);
  const { duration, sourcePath } = await media.evaluate((element: HTMLMediaElement) => ({
    duration: element.duration,
    sourcePath: new URL(element.currentSrc).pathname,
  }));
  expect(Number.isFinite(duration)).toBe(true);
  expect(duration).toBeGreaterThan(0);
  expect(sourcePath).toBe(FIXTURE_PATH);

  await page.getByText("Playback passages (3)").click();
  const rows = page.getByRole("list", { name: "Transcript passages" }).getByRole("listitem");
  await expect(rows).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) await expect(rows.nth(index)).toBeVisible();
  await expect(rows.nth(1)).toContainText("0:04");
  await expect(rows.nth(1).getByRole("button", { name: /^Play / })).toBeVisible();

  const startTime = await media.evaluate((element: HTMLMediaElement) => element.currentTime);
  await page.getByRole("button", { name: "Play or resume playback" }).click();
  await expect.poll(() => media.evaluate((element: HTMLMediaElement) => ({
    paused: element.paused,
    advanced: element.currentTime - startTime >= 0.5,
  })), { timeout: 5_000, message: "Play must unpause and advance at least 500 ms within five seconds" })
    .toEqual({ paused: false, advanced: true });

  // Pause with the visible control so the passage action must seek and start playback again.
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect.poll(() => media.evaluate((element: HTMLMediaElement) => element.paused)).toBe(true);

  type EventSample = { name: string; time: number; paused: boolean };
  // Register listeners synchronously before the click; never play or seek from the test.
  await media.evaluate((element: HTMLMediaElement & { trialEvents?: EventSample[] }) => {
    element.trialEvents = [];
    for (const name of ["seeked", "playing"]) {
      element.addEventListener(name, () => {
        element.trialEvents?.push({ name, time: element.currentTime, paused: element.paused });
      }, { once: true });
    }
  });
  await rows.nth(1).getByRole("button", { name: /^Play / }).click();
  await expect.poll(() => media.evaluate((element: HTMLMediaElement & { trialEvents?: EventSample[] }) =>
    element.trialEvents?.map((event) => event.name)), { timeout: 5_000 }).toEqual(["seeked", "playing"]);
  const events = await media.evaluate((element: HTMLMediaElement & { trialEvents?: EventSample[] }) => element.trialEvents!);
  expect(Math.abs(events[0].time - 4)).toBeLessThanOrEqual(0.25);
  expect(events[1].paused).toBe(false);
});
