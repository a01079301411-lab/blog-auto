// 우편 DM 편지 3종 → PDF (node render_dm.js)
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  for (const n of ['편지', '편지_기관', '편지_병원']) {
    await p.goto('file://' + path.join(__dirname, n + '.html'));
    await p.waitForTimeout(800);
    await p.pdf({ path: path.join(__dirname, n + '.pdf'), format: 'A4', printBackground: true });
    await p.screenshot({ path: path.join(__dirname, n + '.png'), fullPage: true });
  }
  await b.close();
})();
