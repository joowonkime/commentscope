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

test('Explore topics disclose individual evidence and preserve cross-topic debate choices and shares', async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROME_BIN});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844},locale:'en-US'});
    const topics = [
      {en:'School schedules',ko:'수업 시간',members:['a','b']},
      {en:'Transport',ko:'통학 수단',members:['c']},
    ];
    const all = ['a','b','c','d'].map(id=>({id,display_name:'View '+id,text:'Claim '+id,
      source_count:1,source_ids:['s'+id],core_claim_id:'C'+id,grounds:[]}));
    const writes = [];
    await page.route('**/*', route => {
      const req=route.request(), url=new URL(req.url());
      if (url.origin!==origin) return route.abort();
      if (req.method()!=='GET') writes.push(url.pathname);
      const file=files.get(url.pathname);
      if (file) return route.fulfill({path:path.join(product,file[0]),contentType:file[1]});
      if (url.pathname.startsWith('/mvp/assets/')) return route.fulfill({path:path.join(product,'assets',path.basename(url.pathname))});
      if (url.pathname==='/api/v1/analyses') return route.fulfill({json:{analyses:[]}});
      if (url.pathname==='/mvp/perspective-translations.json') return route.fulfill({json:{reviewed:{topics}}});
      if (url.pathname==='/mvp/opinion-samples.json') return route.fulfill({json:{}});
      if (url.pathname.endsWith('/sources/sa')) return route.fulfill({json:{id:'sa',text:'Original evidence for a.'}});
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    await page.getByText('No analyses are available yet.',{exact:true}).waitFor();
    const load = id => page.evaluate(({id,all}) => {
      state.analysis={analysis_id:id,perspectives:all,status:'available',count_scope:'processed_comments',
        analyzed_comments:4,composition:all.map(p=>({perspective_id:p.id,count:1,likes:2})),
        engagement:{available:true,total_likes:8}};
      state.session={session_id:'S',initial_opinion:{text:'',revision:1},rooms:[],comparisons:{},capabilities:{structured_debate:true}};
      $('before').hidden=true;$('workspace').hidden=false;showStep('explore');renderAnalysis();renderPerspectives();
    },{id,all});
    await load('reviewed');
    const groups=page.locator('#perspectives > .perspective-topic');
    await groups.first().locator(':scope > summary').waitFor({timeout:3000});
    assert.equal(await groups.count(),2);
    const first=groups.nth(0),second=groups.nth(1), a=page.locator('[data-perspective="a"]');
    assert.equal(await a.isVisible(),false);
    assert.equal(await page.locator('[data-perspective="d"]').isVisible(),true);
    assert.equal(await page.locator('#perspectives .card').count(),4);
    const metricRows = await page.locator('#share-table tbody tr').allTextContents();
    assert.equal(metricRows.length,4);
    await first.locator(':scope > summary').press('Enter');
    await a.locator('.source-disclosure summary').click();
    await a.locator('.source-button').click();
    assert.match(await page.locator('#source-dialog[open]').innerText(),/Original evidence for a/);
    await page.locator('#close-source').click();
    await a.getByRole('checkbox').check();
    await first.locator(':scope > summary').click();
    await page.locator('#interface-language').selectOption('ko');
    assert.match(await first.locator(':scope > summary').innerText(),/수업 시간/);
    assert.match(await first.locator(':scope > summary').innerText(),/1개 선택/);
    await second.locator(':scope > summary').click();
    await second.getByRole('checkbox').check();
    await page.locator('#interface-language').selectOption('en');
    assert.deepEqual(await page.locator('#share-table tbody tr').allTextContents(),metricRows);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.locator('#open-room').click();
    await page.waitForFunction(()=>state.room?.kind==='debate_draft');
    assert.deepEqual(await page.evaluate(()=>state.room.participant_ids),['a','c']);
    await load('unregistered');
    await page.locator('[data-perspective="a"]').waitFor();
    assert.equal(await groups.count(),0);
    assert.equal(await page.locator('#perspectives > .card').count(),4);
    assert.deepEqual(writes,[]);
  } finally { await browser.close(); }
});

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
    await page.getByText('No analyses are available yet.', {exact:true}).waitFor();
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
    await page.getByText('No analyses are available yet.', {exact:true}).waitFor();
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
    await page.getByText('No analyses are available yet.', {exact:true}).waitFor();
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
    assert.equal(await page.locator('#like-base').innerText(),'of 3 linked likes');
    assert.equal(await page.locator('#share-scale').innerText(),'Bar scale 0–75%');
    assert.match(await page.locator('#share-coverage').innerText(),/1 of 3 sampled positions.*3 of 2,000 recorded likes \(0.2%\).*1,997 are on unlinked comments/);
    assert.match(await page.locator('#share-method').innerText(),/AI review of 5 of the 100 processed comments/);
    assert.equal(await page.locator('#share-table tbody tr').count(),2);
    assert.deepEqual(await table.locator('tbody tr:first-child strong').allTextContents(),['66.7%','33.3%']);
    assert.equal(await table.locator('tfoot strong').innerText(),'66.7%');
    assert.equal(await table.locator('tfoot small').innerText(),'2 likes');
    assert.deepEqual(await table.locator('tbody tr:first-child small').allTextContents(),['2 comments','1 like']);
    assert.deepEqual(await table.locator('tbody tr:first-child progress').evaluateAll(bars=>bars.map(b=>[b.value,b.max])),[[200/3,75],[100/3,75]]);

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
    assert.equal(await page.locator('#like-base').innerText(),'No recorded likes');
    assert.deepEqual(await table.locator('tbody tr:first-child small').allTextContents(),['0 comments','0 likes']);
    assert.deepEqual(await table.locator('tbody tr:first-child strong').allTextContents(),['—','—']);
    assert.equal(await table.locator('progress').count(),0);
    assert.equal(await page.locator('.share-plot svg').count(),0);
    await selectAnalysis({...base,composition:base.composition.map(e=>({...e,likes:e.kind==='other'?2000:0}))});
    assert.equal(await page.locator('#like-base').innerText(),'No linked likes');
    assert.equal(await page.locator('#rank-likes').isDisabled(),true);
    assert.equal(await table.locator('tfoot').isVisible(),false);
    assert.equal(await table.locator('tbody tr:first-child td:last-child strong').innerText(),'—');
    assert.match(await page.locator('#share-coverage').innerText(),/0 of 2,000 recorded likes \(0%\)/);
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

test('the interface language survives reloads and switches in place without translating evidence or drafts', async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROME_BIN});
  try {
    const context = await browser.newContext({locale:'ko-KR',viewport:{width:390,height:844}});
    const page = await context.newPage();
    const writes = [], errors = [];
    page.on('pageerror',e=>errors.push(e.message));
    const example = {analysis_id:'languages',status:'available',count_scope:'processed_comments',analyzed_comments:2,
      video:{video_id:'BAHKmi4F1L8',title:'Library',description:'Perspective breakdown'},perspectives:[
        {id:'raw',text:'Explore',display_name:'Library',source_count:1,source_ids:['source'],grounds:[]},
      ],composition:[{perspective_id:'raw',count:1,likes:3},{kind:'multiple',count:0,likes:0},{kind:'other',count:1,likes:97}],
      engagement:{available:true,total_likes:100}};
    await page.route('**/*',route=>{
      const req=route.request(),u=new URL(req.url());
      if(u.origin!==origin)return route.abort();
      if(req.method()!=='GET'){writes.push(u.pathname);return route.abort();}
      const asset=files.get(u.pathname);
      if(asset)return route.fulfill({path:path.join(product,asset[0]),contentType:asset[1]});
      if(u.pathname==='/api/v1/analyses')return route.fulfill({json:{analyses:[example]}});
      if(u.pathname==='/mvp/opinion-samples.json')return route.fulfill({json:{languages:{issue:'Explore',reviewer:'ai',population:2,sample_size:2,
        positions:2,no_position:0,unclear:0,unmatched:1,multiple:0,supports:{raw:1}}}});
      if(u.pathname.endsWith('/sources/source'))return route.fulfill({json:{text:'Library',PARENT_CONTEXT_ONLY:{text:'Explore'}}});
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    const selector=page.locator('#interface-language');
    assert.equal(await selector.inputValue(),'ko');
    await page.locator('#initial').fill('What changed');
    await selector.selectOption('en');
    assert.equal(await page.locator('#initial').inputValue(),'What changed');
    assert.equal(await page.locator('html').getAttribute('lang'),'en');
    await page.reload();
    assert.equal(await selector.inputValue(),'en');
    await page.locator('#open-library').click();
    await page.locator('#library-dialog .interface-language').selectOption('ko');
    assert.equal(await page.locator('#library-title').innerText(),'보관함');
    assert.equal(await page.locator('#library-videos .library-item strong').innerText(),'Library');
    await page.locator('#close-library').click();
    await page.evaluate(a=>enter({analysis:a,analysis_id:a.analysis_id,session_id:'languages',initial_opinion:{text:'',revision:1},
      capabilities:{},rooms:[],reflections:[]}),example);
    await page.waitForFunction(()=>$('opinion-base').textContent.includes('2개'));
    await page.getByRole('checkbox',{name:'Library 선택'}).check();
    await page.locator('#share-details summary').click();
    await page.locator('#share-view').selectOption('raw');
    await page.locator('.initial-summary summary').click();
    await page.locator('#initial-edit').fill('Explore');
    const card=page.locator('[data-perspective=raw]');
    await card.locator('.source-disclosure summary').click();
    await card.locator('.card-sources button').click();
    await page.locator('#source-dialog[open]').waitFor();
    assert.equal(await page.locator('#source').innerText(),'Library\n\n부모 댓글 · 문맥 참고\nExplore');
    await page.locator('#source-dialog .interface-language').selectOption('en');
    assert.equal(await page.locator('#source').innerText(),'Library\n\nParent comment for context\nExplore');
    await page.locator('#close-source').click();
    assert.equal(await page.locator('#share-view').inputValue(),'raw');
    assert.equal(await page.getByRole('checkbox',{name:'Select Library'}).isChecked(),true);
    assert.equal(await page.locator('#initial-edit').inputValue(),'Explore');
    assert.equal(await page.locator('#like-base').innerText(),'of 3 linked likes');
    assert.deepEqual(await page.locator('#share-table tbody strong').allTextContents(),['50%','100%']);
    for(const language of ['ko','en']){
      await selector.selectOption(language);
      for(const width of [320,390,768,901,1024,1280]){
        await page.setViewportSize({width,height:844});
        const layout=await page.locator('.app-header').evaluate(header=>{
          const rect=el=>el.getBoundingClientRect();
          const lang=rect(header.querySelector('select')),lib=rect(header.querySelector('#open-library')),nav=rect(header.querySelector('.step-nav'));
          return {fits:header.scrollWidth<=innerWidth && lang.right<=innerWidth && lang.left>=lib.right-1,
            clear:nav.bottom<=lang.top+1 || nav.top>=lang.bottom-1 || nav.right<=lib.left+1};
        });
        assert.ok(layout.fits&&layout.clear,language+' '+width+'px header');
      }
    }
    await page.evaluate(()=>{showStep('converse');$('opening-question').value='Library';$('opening-question').dispatchEvent(new Event('input'));});
    await selector.selectOption('ko');
    assert.equal(await page.locator('#opening-question').inputValue(),'Library');
    assert.equal(await page.locator('#empty-conversation h1').innerText(),'대화 시작');
    await page.evaluate(()=>{document.body.dataset.step='reflect';$('reflect').hidden=false;$('converse').hidden=true;});
    await page.locator('#current').fill('What stayed the same');
    await selector.selectOption('en');
    assert.equal(await page.locator('#current').inputValue(),'What stayed the same');
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  } finally { await browser.close(); }
});

test('registered perspective translations follow the language without moving source highlights or borrowing other analyses', async () => {
  const {createHash} = require('node:crypto');
  const field = (source, ko) => ({sha256:createHash('sha256').update(source).digest('hex'), ko});
  const p = {id:'P1', display_name:'Library', core_claim_id:'C1', text:'Start later.', grounds:[
    {claim_id:'G1', text:'School starts then.', role:'reason', kind:'value', source_count:1, source_ids:['S']}],
    source_count:1, source_ids:['S']};
  const first = {analysis_id:'A1', video:{title:'Library'}, status:'available', count_scope:'processed_comments', analyzed_comments:1, perspectives:[p]};
  const second = {...first, analysis_id:'A2'};
  const catalog = {A1:{source_language:'en',fields:{
    'name:P1':field('Library','시작 시간 제안'), 'claim:C1':field(p.text,'더 늦게 시작하자.'),
    'claim:G1':field(p.grounds[0].text,'그때 학교 수업이 시작된다.'), issue:field('What time?','몇 시에 시작할까?')}},
    A2:{source_language:'en',fields:{'name:P1':field('Previous name','이전 이름')}}};
  const report = {issue:'What time?',reviewer:'ai',sample_size:1,population:1,positions:1,no_position:0,unclear:0,unmatched:0,supports:{P1:1}};
  const item = {relation:'agreement',explanation:'A comparison result',user_spans:[{start:0,end:7,text:'Library'}],
    perspective_claims:[{claim_id:'C1',text:p.text},{claim_id:'G1',text:'School'}],required_premises:[]};
  let release, catalogReads=0;
  const pending = new Promise(resolve=>{release=resolve;});
  const writes=[], errors=[];
  const browser=await chromium.launch({executablePath:process.env.CHROME_BIN});
  try {
    const page=await browser.newPage({locale:'en-US',viewport:{width:390,height:844}});
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*', async route=>{
      const req=route.request(), u=new URL(req.url());
      if(u.origin!==origin)return route.abort();
      if(req.method()!=='GET'){writes.push(u.pathname);return route.abort();}
      const staticFile=files.get(u.pathname);
      if(staticFile)return route.fulfill({path:path.join(product,staticFile[0]),contentType:staticFile[1]});
      if(u.pathname==='/api/v1/analyses')return route.fulfill({json:{analyses:[first,second]}});
      if(u.pathname==='/mvp/opinion-samples.json')return route.fulfill({json:{A1:report,A2:report}});
      if(u.pathname==='/mvp/perspective-translations.json'){catalogReads++;await pending;return route.fulfill({json:catalog});}
      if(u.pathname==='/api/v1/jobs/j')return route.fulfill({json:{job_id:'j',state:'succeeded',result:{available:true,items:[item]}}});
      if(u.pathname.endsWith('/sources/S'))return route.fulfill({json:{text:'Library',PARENT_CONTEXT_ONLY:{text:p.text}}});
      return route.fulfill({status:404,body:''});
    });
    await page.goto(origin+'/mvp');
    await page.waitForFunction(()=>$('begin').querySelector('button[type=submit]').disabled===false);
    const enterSession=a=>page.evaluate(analysis=>enter({session_id:'qa',analysis_id:analysis.analysis_id,analysis,
      initial_opinion:{text:'Library',revision:1},capabilities:{},rooms:[],reflections:[],
      comparisons:{P1:{job_id:'j',available:true,relations:['agreement']}}}),a);
    await enterSession(first);
    await page.locator('#perspectives input').check();
    await page.locator('.compare-button').first().click();
    const modal=page.locator('#comparison[open]');
    await modal.waitFor();
    await modal.locator('.interface-language').selectOption('ko');
    release();
    await page.waitForFunction(()=>$('comparison-title').textContent==='시작 시간 제안');
    assert.equal(await page.locator('#comparison-stance mark.mark-agreement').innerText(),'더 늦게 시작하자.');
    assert.equal(await page.locator('#comparison-initial mark').innerText(),'Library');
    assert.deepEqual(await modal.locator('.comparison-item blockquote mark').allTextContents(),['더 늦게 시작하자.','School']);
    assert.equal(await page.locator('#share-issue').textContent(),'몇 시에 시작할까?');
    assert.equal(await page.locator('#share-table tbody th').textContent(),'시작 시간 제안');
    assert.equal(await page.locator('#share-view option[value=P1]').textContent(),'시작 시간 제안');
    assert.equal(await page.locator('#perspectives .card-ground span').nth(1).textContent(),'그때 학교 수업이 시작된다.');
    await modal.locator('.source-disclosure summary').click();
    await modal.locator('.card-sources button').click();
    const sources=page.locator('#source-dialog[open]');
    assert.ok((await sources.innerText()).includes('Library'));
    await sources.locator('.interface-language').selectOption('en');
    assert.equal(await page.locator('#source').innerText(),'Library\n\nParent comment for context\nStart later.');
    await page.locator('#close-source').click();
    assert.equal(await page.locator('#comparison-stance mark').innerText(),p.text);
    await page.locator('#close-comparison').click();
    assert.equal(await page.locator('#perspectives input').isChecked(),true);
    await enterSession(second);
    await page.locator('#interface-language').selectOption('ko');
    await page.waitForFunction(()=>!$('perspective-language-note').hidden && $('perspective-language-note').textContent.includes('일부'));
    assert.equal(await page.locator('#perspectives .card-title strong').innerText(),'Library');
    assert.equal(await page.locator('#perspectives .card-stance').innerText(),p.text);
    assert.equal(catalogReads,1);
    assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  } finally { release(); await browser.close(); }
});
