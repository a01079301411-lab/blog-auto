const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 794, height: 1123 } });
  await p.goto('file://' + __dirname + '/brochure2.html');
  await p.waitForTimeout(700);
  await p.pdf({ path: __dirname + '/로젠이사_기관이전_제안서.pdf', format: 'A4', printBackground: true });
  const pages = await p.$$('section.page');
  for (let i = 0; i < pages.length; i++) await pages[i].screenshot({ path: __dirname + `/pg${i + 1}.png` });
  console.log('pages', pages.length);
  await b.close();
})();
