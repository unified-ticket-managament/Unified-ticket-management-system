const { chromium } = require("playwright-core");
const path = require("path");

const SCREEN_DIR = path.join(__dirname, "screenshots2");
require("fs").mkdirSync(SCREEN_DIR, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath:
      "C:\\Users\\vishnu\\AppData\\Local\\ms-playwright\\chromium-1228\\chrome-win64\\chrome.exe",
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push("PAGEERROR: " + err.message));

  async function shot(name) {
    await page.screenshot({ path: path.join(SCREEN_DIR, name), fullPage: true });
    console.log("screenshot:", name);
  }

  console.log("=== Login as Team Lead ===");
  await page.goto("http://localhost:3000/login", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#email", { timeout: 20000 });
  await page.waitForTimeout(1000);
  await page.fill("#email", "teamlead@probeps.com");
  await page.fill("#email", "teamlead@probeps.com");
  await page.fill("#password", "TeamLead@123");
  await page.fill("#password", "TeamLead@123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/dashboard/, { timeout: 40000 });

  console.log("=== 1) Dashboard: SLA Overview section ===");
  await page.waitForSelector("text=SLA Overview", { timeout: 30000 });
  // ~33 tickets x one real GET /tickets/{id}/sla call each, in
  // parallel, against a backend that hits a remote Neon DB even
  // locally — give it real time rather than guessing.
  await page.waitForFunction(
    () => !document.body.innerText.includes("…"),
    { timeout: 60000 }
  ).catch(() => console.log("(still showing loading placeholder after 60s)"));
  await page.waitForTimeout(500);
  await shot("01-dashboard-sla-overview.png");
  const dashText = await page.locator("body").innerText();
  console.log("Has 'Running':", dashText.includes("Running"));
  console.log("Has 'At Risk':", dashText.includes("At Risk"));
  console.log("Has 'Breached':", dashText.includes("Breached"));
  console.log("Has 'Escalated':", dashText.includes("Escalated"));
  console.log("Existing mock 'SLA Breaches' KPI still present:", dashText.includes("SLA Breaches"));

  console.log("=== Find a ticket via Tickets list ===");
  await page.goto("http://localhost:3000/dashboard/tickets", { waitUntil: "domcontentloaded" });
  await page.waitForSelector('a:has-text("View"), button:has-text("View")', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1000);
  const viewLinks = page.locator('a:has-text("View"), button:has-text("View")');
  const count = await viewLinks.count();
  console.log("ticket rows found:", count);

  // Try a few tickets looking for one that shows a non-healthy tier,
  // to actually see the badge color variety, not just "healthy".
  let checkedDetail = false;
  for (let i = 0; i < Math.min(count, 6); i++) {
    await page.goto("http://localhost:3000/dashboard/tickets", { waitUntil: "domcontentloaded" });
    await page.waitForSelector('a:has-text("View"), button:has-text("View")', { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(500);
    const link = page.locator('a:has-text("View"), button:has-text("View")').nth(i);
    await link.click();
    await page.waitForSelector("text=Resolution SLA", { timeout: 30000 }).catch(() => {});
    // Wait for the card to settle on a real status word (RUNNING's
    // tier badge, or PAUSED/COMPLETED's plain text) instead of a fixed
    // guess — same "this backend is genuinely slow" reasoning as
    // everywhere else in this script.
    await page
      .waitForFunction(
        () => {
          const t = document.body.innerText;
          return (
            t.includes("Healthy") ||
            t.includes("At Risk") ||
            t.includes("Breached") ||
            t.includes("Escalated") ||
            t.includes("PAUSED") ||
            t.includes("COMPLETED")
          );
        },
        { timeout: 20000 }
      )
      .catch(() => {});
    const detailText = await page.locator("body").innerText();
    const hasCard = detailText.includes("Resolution SLA");
    const hasTimeline = detailText.includes("SLA Timeline");
    const tierWords = ["At Risk", "Breached", "Escalated", "Healthy"].filter((w) =>
      detailText.includes(w)
    );
    console.log(`ticket #${i}: card=${hasCard} timeline=${hasTimeline} tiers=[${tierWords.join(",")}]`);

    if (hasCard && tierWords.length > 0) {
      await shot(`02-ticket-detail-${tierWords.join("-")}.png`);
      // Element-level crop of just the card, so the badge color is
      // actually visible without hunting through a full-page shot.
      const cardHeading = page.locator("text=Resolution SLA").first();
      const cardBox = cardHeading.locator("xpath=ancestor::div[contains(@class,'rounded-md2')][1]");
      await cardBox
        .screenshot({ path: path.join(SCREEN_DIR, `02b-sla-card-${i}-${tierWords.join("-")}.png`) })
        .catch((e) => console.log("card element screenshot failed:", e.message));
      checkedDetail = true;

      // 2) & 3): countdown ticking — sample the remaining-time text
      // twice, a few seconds apart, on the same page. Only meaningful
      // for a RUNNING ticket (has a tier word other than none) —
      // still useful to try on the first one we find either way.
      const remainingSelector = "text=/remaining|Overdue/";
      const first = await page.locator(remainingSelector).first().innerText().catch(() => null);
      await page.waitForTimeout(5000);
      const second = await page.locator(remainingSelector).first().innerText().catch(() => null);
      console.log(`  countdown sample 1: ${first}`);
      console.log(`  countdown sample 2: ${second}`);
      console.log(`  countdown text changed: ${first !== null && first !== second}`);
    }
  }
  if (!checkedDetail && count > 0) {
    console.log("No non-healthy ticket found in the first few rows — screenshotting whatever's current.");
    await shot("02-ticket-detail-fallback.png");
  }

  console.log("=== 5) Notification Center + toast ===");
  await page.goto("http://localhost:3000/dashboard", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  const bell = page.locator('button:has(svg.lucide-bell)').first();
  if ((await bell.count()) > 0) {
    await bell.click();
    await page.waitForTimeout(1000);
    await shot("03-notification-bell-open.png");
    const bellText = await page.locator("body").innerText();
    console.log("Bell dropdown mentions SLA:", /SLA/i.test(bellText));
  } else {
    console.log("Bell not found.");
  }

  console.log("=== CONSOLE ERRORS ===");
  console.log(consoleErrors.length === 0 ? "none" : consoleErrors.join("\n"));

  await browser.close();
})().catch((err) => {
  console.error("SCRIPT FAILURE:", err);
  process.exit(1);
});
