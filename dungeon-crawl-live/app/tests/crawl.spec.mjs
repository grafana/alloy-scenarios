import { test, expect, devices } from "@playwright/test";

const gameURL = process.env.GAME_URL || "http://localhost:8088";
const lokiURL = process.env.LOKI_URL || "http://localhost:3100";
const frontend = '{service_name="crawler-hud"}';
const receipts = '{service_name="reward-service"}';

for (const touch of [false, true]) {
  test(`goblin encounter, missing key, investigation and rollback · ${touch ? "touch" : "keyboard"}`, async ({
    browser,
    request,
  }, testInfo) => {
    test.setTimeout(150_000);
    const context = await browser.newContext(
      touch
        ? { ...devices["Pixel 7"], defaultBrowserType: undefined }
        : { viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" },
    );
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const button = (name) => page.getByRole("button", { name, exact: true });
    async function press(name) {
      await expect(button(name)).toBeEnabled();
      if (touch) await button(name).tap();
      else {
        await button(name).focus();
        await page.keyboard.press("Enter");
      }
    }
    const runId = () => new URL(page.url()).searchParams.get("run");
    async function shot(name) {
      await page.screenshot({
        path: testInfo.outputPath(name + ".png"),
        animations: "disabled",
      });
    }
    async function records(selector, id) {
      const query = selector + " |= " + JSON.stringify(id);
      const response = await request.get(lokiURL + "/loki/api/v1/query_range", {
        params: { query, limit: 500 },
      });
      expect(response.ok()).toBeTruthy();
      return (await response.json()).data.result.flatMap((stream) =>
        stream.values.map(([, line]) => JSON.parse(line)),
      );
    }
    try {
      await page.goto(gameURL);
      await expect(button("Enter the floor")).toBeEnabled();
      await press("Enter the floor");
      await expect(page).toHaveURL(/run=/);
      const healthy = runId();
      if (touch) await press("Toll booth");
      else for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
      await press("Challenge the clerk");
      await shot("encounter");
      await press("Cast Magic Missile");
      await expect(page.locator("#health")).toContainText("2/3");
      await press("Distract with Carl");
      await press("Cast Magic Missile");
      await expect(
        page.getByRole("heading", { name: "Toll evasion rewarded" }),
      ).toBeVisible();
      await press("Inspect crawler box");
      await expect(page.locator("#message")).toContainText("stays sealed");
      await press("Enter the guildhall");
      await press("Open crawler box");
      await press("Equip brass key");
      await press("Approach the grille");
      await press("Unlock the grille");
      await press("Descend together");
      await press("Replay with HUD 1.1");
      await expect(button("Open crawler box")).toBeEnabled();
      const failed = runId();
      await press("Open crawler box");
      await expect(page.locator("#item")).toHaveText("Empty slot");
      await press("Reopen crawler box");
      await press("Approach the grille");
      await press("Unlock the grille");
      await press("Try the grille again");
      await shot("missing-key");
      await press("Investigate this run");
      await expect(page).toHaveURL(new RegExp("var-run=" + failed));
      await expect(
        page.getByText("Selected attempt · duty log", { exact: true }).first(),
      ).toBeVisible();
      await page.reload();
      await expect(
        page.getByText(/REWARD SERVICE  ·  Brass key issued/).first(),
      ).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText(/HUD ERROR  ·/).first()).toBeVisible({
        timeout: 30_000,
      });
      await shot("duty-desk");
      await page
        .getByText("Return to operator checkpoint", { exact: true })
        .first()
        .click();
      await expect(page).toHaveURL(new RegExp("operator=" + failed));
      await press("Roll back inventory display");
      await expect(button("Open crawler box")).toBeEnabled();
      const recovered = runId();
      expect(new Set([healthy, failed, recovered]).size).toEqual(3);
      await press("Open crawler box");
      await press("Equip brass key");
      await press("Approach the grille");
      await press("Unlock the grille");
      await shot("unlocked");
      await press("Descend together");
      await shot("descended");
      await press("Verify recovery in Grafana");
      await expect(
        page.getByText(/CRAWLER HUD  ·  floor_descended/).first(),
      ).toBeVisible({ timeout: 45_000 });
      // Each deep link opens at the start of this complete shift.
      for (const [panel, stable, faulty] of [
        ["Keys issued", 2, 1],
        ["Usable inventory slots", 2, 0],
        ["Successful descents", 2, 0],
      ]) {
        const region = page.getByRole("region", { name: panel, exact: true });
        await expect(region).toContainText(
          new RegExp("HUD 1\\.0\\s*" + stable + "\\s*HUD 1\\.1\\s*" + faulty),
          { timeout: 30_000 },
        );
      }
      const sessions = new Set();
      for (const [id, release] of [
        [healthy, "1.0"],
        [failed, "1.1"],
        [recovered, "1.0"],
      ]) {
        const grants = await records(receipts, id);
        expect(grants).toHaveLength(1);
        expect(grants[0]).toMatchObject({
          event_name: "key_granted",
          release,
          run_id: id,
        });
        const logs = (await records(frontend, id)).filter(
          (row) => row.page_attr_run_id === id,
        );
        for (const row of logs) {
          expect(row.page_attr_release).toBe(release);
          expect(row.session_id).toBeTruthy();
          sessions.add(row.session_id);
        }
        const count = (name) =>
          logs.filter((row) => row.event_name === name).length;
        expect(count("key_usable")).toBe(id === failed ? 0 : 1);
        expect(count("floor_descended")).toBe(id === failed ? 0 : 1);
        expect(count("unlock_blocked")).toBe(id === failed ? 2 : 0);
        expect(
          logs.some((row) => row.stacktrace?.includes("renderInventoryItem")),
        ).toBe(id === failed);
        expect(
          logs.some(
            (row) =>
              row.type === "inventory_render" &&
              Number(row.value_duration_ms) >= 0,
          ),
        ).toBe(id !== failed);
        if (id === healthy) expect(count("mob_defeated")).toBe(1);
      }
      expect(sessions.size).toBe(1);
      expect(errors).toEqual([]);
    } finally {
      await context.close();
    }
  });
}
