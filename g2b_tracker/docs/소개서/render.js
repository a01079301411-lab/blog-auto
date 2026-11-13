const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({viewport:{width:794,height:1123}});
  await p.goto('file://' + process.cwd() + '/brochure.html'); await p.waitForTimeout(500);
  await p.pdf({ path: '관공서_회사소개서_로젠이사.pdf', format: 'A4', printBackground: true });
  await p.screenshot({ path: 'brochure.png', fullPage: true }); await b.close();
})();
