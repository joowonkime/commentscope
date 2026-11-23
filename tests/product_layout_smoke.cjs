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

test('Explore limits the comparison queue, publishes individual results, and resumes the current opinion', async () => {
  const browser=await chromium.launch({executablePath:process.env.CHROME_BIN});
  try{
    const page=await browser.newPage({viewport:{width:390,height:844}});
    const submitted=[], jobs=new Map(), held=new Set(), failures=new Set();
    const ids=Array.from({length:11},(_,i)=>'p'+(i+1));
    let peak=0;
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url()), pathname=url.pathname;
      if(url.origin!==origin)return route.abort();
      const file=files.get(pathname);
      if(file)return route.fulfill({path:path.join(product,file[0]),contentType:file[1]});
      if(pathname==='/api/v1/analyses')return route.fulfill({json:{analyses:[]}});
      if(pathname==='/api/v1/sessions/qa/comparisons'){
        const {perspective_id:id,initial_revision:revision}=route.request().postDataJSON();
        const key=revision+'-'+id, job='j'+submitted.length;
        submitted.push({key,job});jobs.set(job,key);held.add(job);peak=Math.max(peak,held.size);
        return route.fulfill({status:202,json:{job_id:job}});
      }
      if(pathname.startsWith('/api/v1/jobs/')){
        const job=pathname.split('/').pop(), key=jobs.get(job);
        if(held.has(job))return route.fulfill({json:{job_id:job,state:'running'}});
        if(failures.has(job))return route.fulfill({json:{job_id:job,state:'failed',error:{code:'test_failure'}}});
        return route.fulfill({json:{job_id:job,state:'succeeded',result:{available:true,items:[]},stale:false}});
      }
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    await page.evaluate(ids=>{
      state.analysis={perspectives:ids.map(id=>({id,display_name:id,text:'Test stance',source_count:1,grounds:[],source_ids:[]}))};
      state.session={session_id:'qa',rooms:[],comparisons:{},capabilities:{},initial_opinion:{text:'',revision:1}};
      $('before').hidden=true;$('workspace').hidden=false;renderPerspectives();showStep('explore');
    },ids);
    assert.equal(submitted.length,0);
    assert.equal(await page.getByText('Add your view to compare',{exact:true}).count(),11);
    await page.locator('.compare-button').first().click();
    await page.locator('#comparison[open]').waitFor();
    await page.locator('#close-comparison').click();
    assert.equal(submitted.length,0);
    const revision=(rev)=>page.evaluate(rev=>{
      state.session.initial_opinion={text:'My view '+rev,revision:rev};state.session.comparisons={};
      renderPerspectives();showStep('explore');
    },rev);
    const eventually=async condition=>{
      const deadline=Date.now()+10000;
      while(!condition()&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,25));
      assert.ok(condition(),'Expected queued comparisons to settle');
    };
    const release=(key,fail=false)=>{
      const item=submitted.find(x=>x.key===key && held.has(x.job));
      assert.ok(item,key);
      held.delete(item.job);if(fail)failures.add(item.job);
    };
    await revision(1);
    await eventually(()=>submitted.length===3);
    assert.deepEqual(submitted.map(x=>x.key).sort(),['1-p1','1-p2','1-p3']);
    await page.locator('[data-perspective=p11] .card-stance').click();
    release('1-p1');
    await eventually(()=>submitted.length===4);
    assert.equal(submitted[3].key,'1-p11');
    await page.waitForFunction(()=>$('compare-progress').textContent.startsWith('1 / 11'));
    assert.equal(await page.locator('[data-perspective=p1] .card-relations').getAttribute('data-state'),'done');
    await page.evaluate(()=>showStep('converse'));
    release('1-p2',true);release('1-p3');release('1-p11');
    await page.waitForFunction(()=>activeComparisons===0);
    assert.equal(submitted.length,4);
    assert.equal(await page.locator('#comparison').isVisible(),false);
    await page.evaluate(()=>showStep('explore'));
    await eventually(()=>submitted.length===7);
    while(submitted.length<11){
      held.clear();
      await eventually(()=>submitted.length===11||held.size>0);
    }
    held.clear();
    await page.waitForFunction(()=>$('compare-progress').textContent==='10 / 11 perspectives compared · 1 unavailable');
    assert.equal(new Set(submitted.map(x=>x.key)).size,11);
    await page.locator('#compare-all').click();
    await eventually(()=>submitted.length===12);
    assert.equal(submitted[11].key,'1-p2');
    held.clear();
    await page.waitForFunction(()=>$('compare-progress').textContent==='11 / 11 perspectives compared');
    await page.evaluate(()=>{showStep('converse');showStep('explore');});
    await page.locator('[data-perspective=p1] .compare-button').click();
    await page.locator('#comparison[open]').waitFor();
    await page.locator('#close-comparison').click();
    assert.equal(submitted.length,12);
    // Changing the opinion while three jobs are in flight must not start three additional paid jobs.
    await revision(2);
    await eventually(()=>held.size===3);
    await revision(3);
    assert.equal(submitted.length,15);
    held.clear();
    await eventually(()=>submitted.length===18);
    assert.equal(submitted.filter(x=>x.key.startsWith('2-')).length,3);
    assert.equal(await page.locator('#compare-progress').innerText(),'0 / 11 perspectives compared');
    assert.equal(peak,3);
  }finally{await browser.close();}
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
          ranked:{...report,multiple:1,supports:{a:2,b:1}},
          empty:{...report,positions:0,no_position:4,unmatched:0,multiple:0,supports:{a:0,b:0}}}});
      }
      if (url.pathname === '/api/v1/analyses') return route.fulfill({json:{analyses:[]}});
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    const selectAnalysis = analysis => page.evaluate(a => enter({
      session_id:'chart-session', analysis_id:a.analysis_id, analysis:a,
      initial_opinion:{text:''}, capabilities:{}, rooms:[], reflections:[],
    }), analysis);
    const stripWidths = figure => figure.locator('rect').evaluateAll(nodes => nodes.map(r => Number(r.getAttribute('width'))));
    const opinion = page.locator('#opinion-share'), likes = page.locator('#like-share');
    const view = page.getByLabel('Show coverage for');
    const table = page.locator('#share-table');

    await selectAnalysis(base);
    await selectAnalysis({...base,analysis_id:'unreviewed'});
    releaseCatalog();
    await page.evaluate(()=>opinionCatalog);
    assert.equal(await table.isVisible(),true);
    assert.equal(await view.isVisible(),false);
    assert.equal(await page.locator('#status').isVisible(),false);
    assert.equal(await page.locator('#opinion-base').innerText(),'No reviewed sample');
    await page.locator('#share-details summary').click();
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
    assert.equal(await table.isVisible(),true);
    assert.equal(await page.locator('#opinion-base').innerText(),'of 3 sampled positions');
    assert.equal(await page.locator('#like-base').innerText(),'of 2,000 recorded likes');
    assert.equal(await page.locator('#share-scale').innerText(),'Bar scale 0–75%');
    assert.match(await page.locator('#share-coverage').innerText(),/1 of 3 sampled positions.*1,997 of 2,000 likes/);
    assert.match(await page.locator('#share-method').innerText(),/AI review of 5 of the 100 processed comments/);
    assert.equal(await page.locator('#share-table tbody tr').count(),2);
    assert.deepEqual(await table.locator('tbody tr:first-child strong').allTextContents(),['66.7%','<0.1%']);
    assert.deepEqual(await table.locator('tbody tr:first-child small').allTextContents(),['2 comments','1 like']);
    assert.deepEqual(await table.locator('tbody tr:first-child progress').evaluateAll(bars=>bars.map(b=>[b.value,b.max])),[[200/3,75],[0.05,75]]);

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
        bars:[...panel.querySelectorAll('tbody progress')].map(el=>el.getBoundingClientRect().width),
        cellsFit:[...panel.querySelectorAll('tbody td')].every(el=>el.scrollWidth<=el.clientWidth+1),
      }));
      assert.ok(geometry.fits,width+'px');
      assert.equal(geometry.tracks.length,2);
      assert.equal(geometry.tracks[0],geometry.tracks[1]);
      assert.ok(geometry.bars[0]>15 && geometry.bars.every(w=>Math.abs(w-geometry.bars[0])<1));
      assert.ok(geometry.cellsFit,width+'px wide chart cells');
      if(width<=390)assert.ok(geometry.valuesFit,'Legend text at '+width+'px');
    }
    await selectAnalysis({...base,analysis_id:'ranked',composition:base.composition.map(e=>
      e.perspective_id ? {...e,likes:e.perspective_id==='b'?1:0} : e)});
    await page.locator('#opinion-column[aria-sort=descending]').waitFor();
    await page.getByRole('checkbox',{name:'Select Shorter days'}).check();
    await view.selectOption('a');
    assert.deepEqual(await table.locator('tbody th').allTextContents(),['Shorter days','Earlier finish']);
    await page.locator('#rank-likes').focus();
    await page.keyboard.press('Space');
    assert.deepEqual(await table.locator('tbody th').allTextContents(),['Earlier finish','Shorter days']);
    assert.equal(await page.locator('#like-column').getAttribute('aria-sort'),'descending');
    assert.equal(await page.locator('#share-scale').innerText(),'Bar scale 0–75%');
    assert.equal(await view.inputValue(),'a');
    assert.deepEqual(await page.evaluate(()=>[...state.selected]),['a']);
    await view.selectOption('a');
    await selectAnalysis({...base,analysis_id:'legacy'});
    assert.equal(await view.inputValue(),'');
    assert.deepEqual(await opinion.locator('.share-key').allTextContents(),['Any listed view','Outside these views']);
    assert.deepEqual(await stripWidths(opinion),[2,1]);
    await selectAnalysis({...base,analysis_id:'empty',engagement:{available:true,total_likes:0},
      composition:base.composition.map(e=>({...e,likes:0}))});
    assert.match(await opinion.innerText(),/0 of 5 sampled comments/);
    assert.match(await likes.innerText(),/No likes were recorded/);
    assert.equal(await page.locator('#rank-opinions').isDisabled(),true);
    assert.equal(await page.locator('#rank-likes').isDisabled(),true);
    assert.equal(await page.locator('#like-base').innerText(),'of 0 recorded likes');
    assert.deepEqual(await table.locator('tbody tr:first-child small').allTextContents(),['0 comments','0 likes']);
    assert.deepEqual(await table.locator('tbody tr:first-child strong').allTextContents(),['—','—']);
    assert.equal(await table.locator('progress').count(),0);
    assert.equal(await page.locator('.share-plot svg').count(),0);
    for (const change of [{analysis_id:'unknown'},{analysis_id:'bad'},{analyzed_comments:99},
      {status:'expired'},{count_scope:'registered_sources'}]) {
      await selectAnalysis({...base,...change,engagement:{available:false,total_likes:null}});
      assert.match(await opinion.innerText(),/No reviewed opinion sample/);
      assert.match(await likes.innerText(),/Like counts are unavailable/);
      assert.equal(await page.locator('#like-base').innerText(),'Counts unavailable');
      assert.equal(await table.locator('tbody small').count(),0);
      assert.equal(await page.locator('.share-plot svg').count(),0);
    }
    assert.deepEqual(reads,['/mvp/opinion-samples.json']);
  } finally {
    await browser.close();
  }
});
