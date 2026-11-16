import { expect, test } from "@playwright/test";

test("frontend E2E runner serves the root page", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sauri" })).toBeVisible();
});
