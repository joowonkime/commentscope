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
