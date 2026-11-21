// Render the SVG masters to PNG with Playwright's Chromium.
// Usage: node script/render_icons.js
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const jobs = [
  ["assets/icon.svg", "custom_components/kroger_restock/brand"],
  ["assets/icon.svg", "brands/custom_integrations/kroger_restock"],
  ["assets/icon-transparent.svg", "brands/transparent"],
];

(async () => {
  const browser = await chromium.launch();
  for (const [src, outDir] of jobs) {
    const svg = fs.readFileSync(path.join(root, src), "utf8");
    for (const [name, size] of [["icon.png", 256], ["icon@2x.png", 512]]) {
      const page = await browser.newPage({ viewport: { width: size, height: size } });
      await page.setContent(
        `<html><body style="margin:0;background:transparent">` +
          svg.replace("<svg ", `<svg width="${size}" height="${size}" `) +
          `</body></html>`
      );
      fs.mkdirSync(path.join(root, outDir), { recursive: true });
      await page.screenshot({ path: path.join(root, outDir, name), omitBackground: true });
      await page.close();
    }
  }
  await browser.close();
})();
