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

test('Explore compares both shares without double counting, changing chat selection or borrowing another sample', async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROME_BIN});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const base = {
      analysis_id:'reviewed', status:'experimental', count_scope:'processed_comments', analyzed_comments:100,
      perspectives:[{id:'a',text:'Shorter days',source_count:1},{id:'b',text:'Earlier finish',source_count:1}],
      composition:[{perspective_id:'a',count:1,likes:1},{perspective_id:'b',count:1,likes:0},
        {kind:'multiple',count:1,likes:2},{kind:'other',count:97,likes:1997}],
      engagement:{available:true,total_likes:2000},
    };
    const report = {reviewer:'ai',issue:'Which schedule?',population:100,sample_size:5,
      positions:3,no_position:1,unclear:1,unmatched:1,multiple:2,supports:{a:2,b:2}};
    const {multiple, ...legacy} = report;
    let releaseCatalog;
    const waitForCatalog = new Promise(resolve => {releaseCatalog=resolve;});
    const reads = [];
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) return route.abort();
      const file = files.get(url.pathname);
      if (file) return route.fulfill({path:path.join(product,file[0]),contentType:file[1]});
      if (url.pathname === '/mvp/opinion-samples.json') {
        reads.push(url.pathname);
        await waitForCatalog;
        return route.fulfill({json:{reviewed:report, legacy, bad:{...report,multiple:0},
          empty:{...report,positions:0,no_position:4,unmatched:0,multiple:0,supports:{a:0,b:0}}}});
      }
      if (url.pathname === '/api/v1/analyses') return route.fulfill({json:{analyses:[]}});
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    const selectAnalysis = analysis => page.evaluate(a => {
      state.analysis=a;
      state.session={initial_opinion:{text:''},capabilities:{}};
      document.getElementById('before').hidden=true;
      document.getElementById('workspace').hidden=false;
      document.body.dataset.step='explore';
      renderAnalysis();
      renderPerspectives();
    }, analysis);
    const stripWidths = figure => figure.locator('rect').evaluateAll(nodes => nodes.map(r => Number(r.getAttribute('width'))));
    const opinion = page.locator('#opinion-share'), likes = page.locator('#like-share');
    const view = page.getByRole('combobox',{name:'Perspective shown in both charts'});

    await selectAnalysis(base);
    await selectAnalysis({...base,analysis_id:'unreviewed'});
    releaseCatalog();
    await page.evaluate(()=>opinionCatalog);
    assert.match(await opinion.innerText(),/No reviewed opinion sample/);
    assert.deepEqual(await stripWidths(opinion),[]);
    assert.deepEqual(await stripWidths(likes),[1,2,1997]);

    await selectAnalysis(base);
    assert.equal(await page.locator('#share-issue').innerText(),'Which schedule?');
    assert.match(await page.locator('#analysis-summary').innerText(),/100 comments processed · 3 linked as direct evidence/);
    assert.equal(await page.locator('.source-badge').first().innerText(),'1 direct source comment');
    assert.match(await opinion.innerText(),/3 of 5 sampled comments stated a position/);
    assert.deepEqual(await stripWidths(opinion),[2,1]);
    assert.deepEqual(await opinion.locator('.share-value').allTextContents(),['0 · 0%','2 · 66.7%','1 · 33.3%']);
    assert.deepEqual(await likes.locator('.share-value').allTextContents(),['1 · <0.1%','2 · 0.1%','1,997 · 99.9%']);
    assert.equal(await page.locator('#share-table').isVisible(),false);
    await page.locator('#share-details summary').click();
    assert.match(await page.locator('#share-method').innerText(),/AI review of 5 of the 100 processed comments/);
    assert.equal(await page.locator('#share-table tbody tr').count(),2);
    assert.deepEqual(await page.locator('#share-table tbody tr:first-child small').allTextContents(),['66.7%','<0.1%']);

    await page.getByRole('checkbox',{name:'Select Shorter days'}).check();
    await view.selectOption('b');
    assert.match(await opinion.innerText(),/2 \/ 3 comments support this view/);
    assert.match(await likes.innerText(),/0 \/ 2,000 likes linked only to this view/);
    assert.deepEqual(await stripWidths(opinion),[2,1]);
    assert.deepEqual(await stripWidths(likes),[2000]);
    assert.deepEqual(await page.evaluate(()=>[...state.selected]),['a']);
    await view.focus();
    await page.keyboard.press('Home');
    assert.equal(await view.inputValue(),'');
    for (const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:844});
      const geometry=await page.locator('.breakdown').evaluate(panel => ({
        fits:panel.scrollWidth<=panel.clientWidth && panel.getBoundingClientRect().right<=innerWidth,
        tracks:[...panel.querySelectorAll('svg')].map(el=>el.getBoundingClientRect().width),
        valuesFit:[...panel.querySelectorAll('.share-legend li')].every(item=>{
          const edge=(item.nextElementSibling || item.parentElement).getBoundingClientRect();
          const bound=item.nextElementSibling ? edge.left : edge.right;
          return item.querySelector('.share-value').getBoundingClientRect().right<=bound+1;
        }),
      }));
      assert.ok(geometry.fits,width+'px');
      assert.equal(geometry.tracks.length,2);
      assert.equal(geometry.tracks[0],geometry.tracks[1]);
      if(width<=390)assert.ok(geometry.valuesFit,'Legend text at '+width+'px');
    }
    await view.selectOption('a');
    await selectAnalysis({...base,analysis_id:'legacy'});
    assert.equal(await view.inputValue(),'');
    assert.deepEqual(await opinion.locator('.share-key').allTextContents(),['Any listed view','Outside these views']);
    assert.deepEqual(await stripWidths(opinion),[2,1]);
    await selectAnalysis({...base,analysis_id:'empty',engagement:{available:true,total_likes:0},
      composition:base.composition.map(e=>({...e,likes:0}))});
    assert.match(await opinion.innerText(),/0 of 5 sampled comments/);
    assert.match(await likes.innerText(),/No likes were recorded/);
    assert.equal(await page.locator('.share-plot svg').count(),0);
    for (const change of [{analysis_id:'unknown'},{analysis_id:'bad'},{analyzed_comments:99},
      {status:'expired'},{count_scope:'registered_sources'}]) {
      await selectAnalysis({...base,...change,engagement:{available:false,total_likes:null}});
      assert.match(await opinion.innerText(),/No reviewed opinion sample/);
      assert.match(await likes.innerText(),/Like counts are unavailable/);
      assert.equal(await page.locator('.share-plot svg').count(),0);
    }
    assert.deepEqual(reads,['/mvp/opinion-samples.json']);
  } finally {
    await browser.close();
  }
});
