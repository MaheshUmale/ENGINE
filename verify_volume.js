const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('http://localhost:3000');
  await page.waitForTimeout(5000); // Wait for data to load
  await page.screenshot({ path: '/home/jules/verification/main_dashboard_volume.png' });
  await browser.close();
})();
