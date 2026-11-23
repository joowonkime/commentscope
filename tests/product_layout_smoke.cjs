const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright-core');

const product = path.join(__dirname, '../src/commentscope/product');
const origin = 'https://commentscope.test';
const files = new Map([
  ['/mvp', ['mvp.html', 'text/html']],
  ['/mvp/app.css', ['mvp.css', 'text/css']],
  ['/mvp/app.js', ['mvp.js', 'text/javascript']],
]);

test('source notices remain readable and Reflect remains clickable at six viewport widths', async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      if (url.pathname === '/api/v1/analyses') return route.fulfill({json: {analyses: []}});
      const file = files.get(url.pathname);
      if (file) return route.fulfill({path: path.join(product, file[0]), contentType: file[1]});
      if (url.pathname.startsWith('/mvp/assets/')) {
        return route.fulfill({path: path.join(product, 'assets', path.basename(url.pathname)), contentType: 'image/svg+xml'});
      }
      return route.fulfill({status: 404, body: ''});
    });
    await page.goto(origin + '/mvp');
    await page.evaluate(() => {
      state.analysis = {perspectives: Array.from({length: 8}, (_, index) => ({
        id: 'view-' + index, display_name: '시간과 근무 조건에 대한 관점 ' + index,
        text: 'A synthetic viewpoint', admission_policy: 'seeded', source_count: 1,
        source_ids: [], grounds: [],
      }))};
      state.session = {initial_opinion: {text: ''}};
      document.body.dataset.step = 'explore';
      document.getElementById('before').hidden = true;
      document.getElementById('workspace').hidden = false;
      document.getElementById('explore').hidden = false;
      for (const button of document.querySelectorAll('.step-nav button')) button.disabled = false;
      renderPerspectives();
    });
    assert.equal(await page.locator('.card > small').count(), 8);
    assert.equal(await page.getByRole('img', {name: 'Your private session'}).count(), 1);
    for (const width of [320, 360, 375, 390, 768, 1440]) {
      await page.setViewportSize({width, height: 844});
      const errors = await page.evaluate(() => {
        const errors = [];
        const reflect = document.querySelector('.step-nav [data-step=reflect]');
        const rect = reflect.getBoundingClientRect();
        for (const position of [0.1, 0.5, 0.9]) {
          const hit = document.elementFromPoint(rect.left + position * rect.width, rect.top + rect.height / 2);
          if (!reflect.contains(hit)) errors.push('Reflect hit target ' + position);
        }
        for (const note of document.querySelectorAll('.card > small')) {
          const choice = note.parentElement.querySelector('.card-select').getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(note);
          if ([...range.getClientRects()].some(line => line.left < choice.right && choice.left < line.right &&
              line.top < choice.bottom && choice.top < line.bottom)) errors.push('Selector overlaps source notice');
        }
        return errors;
      });
      assert.deepEqual(errors, [], width + 'px');
    }
  } finally {
    await browser.close();
  }
});

test('Explore separates direct evidence from overlapping sampled opinions and clears stale samples', async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const base = {
      analysis_id:'reviewed', status:'experimental', count_scope:'processed_comments', analyzed_comments:100,
      perspectives:[{id:'a',text:'Shorter days',source_count:1},{id:'b',text:'Earlier finish',source_count:1}],
      composition:[{kind:'multiple',count:1},{kind:'other',count:99}],
    };
    const report = {reviewer:'ai',issue:'Which schedule?',population:100,sample_size:5,
      positions:3,no_position:1,unclear:1,unmatched:1,supports:{a:2,b:2}};
    let releaseCatalog;
    const gate = new Promise(resolve => {releaseCatalog=resolve;});
    const reads = [];
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      const file = files.get(url.pathname);
      if (file) return route.fulfill({path:path.join(product,file[0]),contentType:file[1]});
      if (url.pathname === '/mvp/opinion-samples.json') {
        reads.push(url.pathname);
        await gate;
        return route.fulfill({json:{reviewed:report, empty:{...report,positions:0,no_position:4,unmatched:0,supports:{a:0,b:0}}}});
      }
      if (url.pathname === '/api/v1/analyses') return route.fulfill({json:{analyses:[]}});
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    const select = analysis => page.evaluate(a => {
      state.analysis=a;
      state.session={initial_opinion:{text:''}};
      document.getElementById('workspace').hidden=false;
      renderAnalysis();
      renderPerspectives();
    }, analysis);
    await select(base);
    await select({...base,analysis_id:'unreviewed'});
    releaseCatalog();
    await page.evaluate(()=>opinionCatalog);
    const preview=page.locator('#sample-preview'), bars=page.locator('#sample-bars');
    assert.match(await preview.innerText(),/No reviewed sample/);
    assert.equal(await bars.locator('meter').count(),0);
    await select(base);
    await page.locator('#opinion-sample summary').click();
    assert.equal(await preview.innerText(), '3 of 5 sampled comments stated a position');
    assert.match(await page.locator('#analysis-summary').innerText(),/100 comments processed · 1 linked as direct evidence/);
    assert.equal(await page.locator('.source-badge').first().innerText(),'1 direct source comment');
    assert.equal(await page.locator('#sample-issue').innerText(),'Which schedule?');
    assert.match(await page.locator('#sample-method').innerText(), /AI review of 5 comments drawn from 100/);
    assert.deepEqual(await bars.locator('.sample-value').allTextContents(),['2 / 3 (67%)','2 / 3 (67%)','1 / 3 (33%)']);
    assert.match(await bars.innerText(),/Position outside these cards/);
    await select({...base,analysis_id:'empty'});
    assert.match(await preview.innerText(),/^0 of 5/);
    assert.equal(await bars.locator('meter').count(),0);
    for (const change of [{analysis_id:'unknown'},{analyzed_comments:99},{status:'expired'},{count_scope:'registered_sources'}]) {
      await select({...base,...change});
      assert.match(await preview.innerText(),/No reviewed sample/);
      assert.equal(await bars.locator('meter').count(),0);
    }
    assert.deepEqual(reads,['/mvp/opinion-samples.json']);
  } finally {
    await browser.close();
  }
});
