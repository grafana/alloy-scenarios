import { test, expect, devices } from "@playwright/test";
const base = process.env.GAME_URL || "http://localhost:8088";
const loki = process.env.LOKI_URL || "http://localhost:3100";

test("the director loops all four book-one highlights without viewer input", async ({
  page,
}) => {
  test.setTimeout(65000);
  await page.goto(base);
  await page.getByRole("button", { name: "Watch Carl", exact: true }).click();
  for (const title of [
    "Goblin motor pool",
    "Scatterer tunnels",
    "The Hoarder",
    "Tutorial Guild",
    "Goblin motor pool",
  ]) {
    await expect(page.locator("#scene-title")).toHaveText(title, {
      timeout: 15000,
    });
    await expect(page.locator("#who")).toHaveText("Carl");
  }
});

for (const touch of [false, true]) {
  test(`favourite journey and broadcast control · ${touch ? "touch" : "keyboard"}`, async ({
    browser,
    request,
  }, info) => {
    test.setTimeout(120000);
    const context = await browser.newContext(
      touch ? devices["Pixel 7"] : { viewport: { width: 1440, height: 980 } },
    );
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const button = (name) => page.getByRole("button", { name, exact: true });
    async function press(element) {
      await expect(element).toBeEnabled();
      if (touch) await element.tap();
      else {
        await element.focus();
        await element.press("Enter");
      }
    }
    const shot = (name) =>
      page.screenshot({ path: info.outputPath(name + ".png") });
    try {
      await page.goto(base);
      await expect(page.getByText("Tune in to a crawler")).toBeVisible();
      await press(button("Pause broadcast"));
      await press(button("Watch Carl"));
      await expect(page.locator("#commentary")).toContainText("engine");
      await shot("broadcast");
      await press(button("☆ Favourite Carl"));
      await expect(page.locator("#feedback")).toContainText("Carl added");
      const toggle = page.getByRole("switch", { name: "Website v2" });
      await press(toggle);
      await expect(toggle).toBeChecked();
      await press(button("Watch Princess Donut"));
      await press(button("Watch The Hoarder"));
      await expect(page.locator("#byline")).toContainText("LEVEL 7");
      await expect(page.locator("#commentary")).toContainText("Scatterers");
      await press(button("Enlarge camera still"));
      await expect(
        page.getByRole("dialog", { name: "The Hoarder" }),
      ).toBeVisible();
      await shot("boss");
      await press(button("Close dialog"));
      for (let i = 0; i < 2; i++) {
        const response = page.waitForResponse(
          (r) =>
            r.url().endsWith("/api/favourites/donut") &&
            r.request().method() === "PUT",
        );
        await press(button("☆ Favourite Princess Donut"));
        expect((await response).status()).toBe(422);
        await expect(page.locator("#feedback")).toContainText("Couldn’t save");
      }
      await expect(page.locator("#count")).toHaveText("1");
      await shot("failed-save");
      await press(button("Open full profile →"));
      await press(button("Save favourite"));
      await expect(page.locator("#count")).toHaveText("2");
      await page.reload();
      await expect(toggle).toBeChecked();
      await press(button("Favourites 2"));
      await press(button("★ Princess Donut →"));
      await expect(page.locator("#who")).toHaveText("Princess Donut");
      await press(button("★ Favourited"));
      await expect(page.locator("#count")).toHaveText("1");
      await press(button("☆ Favourite Princess Donut"));
      await expect(page.locator("#feedback")).toContainText("Couldn’t save");
      await press(toggle);
      await expect(toggle).not.toBeChecked();
      await press(button("☆ Favourite Princess Donut"));
      await expect(page.locator("#count")).toHaveText("2");
      await press(page.getByRole("link", { name: "Broadcast control ↗" }));
      await expect(page).toHaveURL(/\/d\/crawlcast-audience\/.*var-session=.+/);
      const session = new URL(page.url()).searchParams.get("var-session");
      expect(session).toBeTruthy();
      const panel = (name) => page.getByRole("region", { name, exact: true });
      await panel("Save completion").scrollIntoViewIfNeeded();
      await expect(panel("Save completion")).toContainText("Site v2", {
        timeout: 45000,
      });
      await panel("Affected journeys").scrollIntoViewIfNeeded();
      await expect(panel("Affected journeys")).toContainText("Site v1");
      await panel("Where viewers finish saving").scrollIntoViewIfNeeded();
      await expect(panel("Where viewers finish saving")).toContainText(
        "v2 / profile",
        { timeout: 30000 },
      );
      const timeline = panel("Viewer session · event timeline");
      await timeline.scrollIntoViewIfNeeded();
      await expect(
        timeline.getByText(/ERROR · v2 · Watchlist rejected donut/).first(),
      ).toBeVisible({ timeout: 45000 });
      await expect(
        timeline.getByText(/v1 · favourite_saved · donut quick/).first(),
      ).toBeVisible({ timeout: 30000 });
      await shot("control");
      const response = await request.get(loki + "/loki/api/v1/query_range", {
        params: {
          query:
            '{service_name="borant-broadcast"} | json | session_id=' +
            JSON.stringify(session),
          limit: 1000,
        },
      });
      expect(response.ok()).toBeTruthy();
      const rows = (await response.json()).data.result.flatMap((s) =>
        s.values.map(([, line]) => JSON.parse(line)),
      );
      const events = (name) => rows.filter((r) => r.event_name === name);
      expect(events("favourite_started")).toHaveLength(4);
      expect(events("favourite_saved")).toHaveLength(3);
      expect(events("favourite_failed")).toHaveLength(3);
      expect(events("favourite_abandoned")).toHaveLength(1);
      const fallback = events("favourite_saved").find(
        (r) => r.event_data_route === "profile",
      );
      expect(fallback.event_data_site_version).toBe("v2");
      expect(
        events("favourite_failed").filter(
          (r) => r.event_data_journey === fallback.event_data_journey,
        ),
      ).toHaveLength(2);
      expect(
        rows.some(
          (r) =>
            r.type === "FavouriteSaveError" &&
            r.stacktrace.includes("broadcast.js"),
        ),
      ).toBe(true);
      expect(errors).toEqual([]);
    } finally {
      await context.close();
    }
  });
}
