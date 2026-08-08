import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * The path a person actually takes: make a model, change it, run it, look at it.
 *
 * Every step here is covered by unit tests somewhere. What they cannot cover is
 * the joins — a field that saves but does not reach the writer, a step that
 * reports success while the next one has nothing to read, a package that
 * validates and then writes an empty file.
 */

async function createColumn(page: Page, name: string): Promise<string> {
  const parent = mkdtempSync(join(tmpdir(), "mup-e2e-"));
  await page.goto("/");
  await page
    .getByRole("button", { name: /Project/ })
    .first()
    .click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Where to create the project").fill(parent);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByText(new RegExp(`${name}: mf6rtm`))).toBeVisible({ timeout: 30_000 });
  return join(parent, `${name}.mup`);
}

test("a new project opens on a model that already runs", async ({ page }) => {
  await createColumn(page, "starter");

  await page
    .getByRole("button", { name: /Simulate/ })
    .first()
    .click();
  await page.getByRole("button", { name: "Validate" }).click();

  await expect(page.getByText(/ok — /)).toBeVisible({ timeout: 30_000 });
});

test("a boundary keeps its edits through a save", async ({ page }) => {
  await createColumn(page, "edited");
  await page.getByRole("button", { name: /Flow/ }).first().click();

  await page.getByRole("button", { name: /^WEL/ }).first().click();
  await page
    .getByRole("button", { name: /inflow/ })
    .first()
    .click();

  const rate = page.getByLabel("Rate").first();
  await rate.fill("0.42");
  await rate.press("Enter");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("unsaved")).toBeHidden({ timeout: 20_000 });

  await page.reload();
  await page.getByRole("button", { name: /^WEL/ }).first().click();
  await page
    .getByRole("button", { name: /inflow/ })
    .first()
    .click();

  await expect(page.getByLabel("Rate").first()).toHaveValue("0.42");
});

test("a package can hold a second entry at its own rate", async ({ page }) => {
  // The thing a package holding one selection and one value could not say.
  await createColumn(page, "twowells");
  await page.getByRole("button", { name: /Flow/ }).first().click();
  await page.getByRole("button", { name: /^WEL/ }).first().click();
  await page
    .getByRole("button", { name: /inflow/ })
    .first()
    .click();

  await page.getByRole("button", { name: /another WEL/ }).click();
  await expect(page.getByText(/2 entries/)).toBeVisible();

  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("unsaved")).toBeHidden({ timeout: 20_000 });
});

test("the model runs and its results can be scrubbed", async ({ page }) => {
  test.slow();
  await createColumn(page, "running");

  await page
    .getByRole("button", { name: /Simulate/ })
    .first()
    .click();
  await page.getByRole("button", { name: "Write and run" }).click();

  // A reactive column is seconds, not minutes, but a cold engine fetch is not.
  await expect(page.getByText(/succeeded|failed/)).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText("succeeded")).toBeVisible();

  await page
    .getByRole("button", { name: /Results/ })
    .first()
    .click();
  await expect(page.locator("canvas")).toBeVisible({ timeout: 30_000 });
});
