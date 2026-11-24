import {test,expect,type Page} from '@playwright/test';

const source={comment_id:'source-g4',text:'Services need coverage even when staff have a day off.',original_text:'직원이 쉬어도 서비스 운영 대책이 필요합니다.',like_count:35,is_reply:false,url:'https://www.youtube.com/watch?v=BAHKmi4F1L8&lc=source-g4'};
const agents=['g1','g2','g3','g4','g5'].map((id,i)=>({agent_id:id,title:['A Full Day Off','Shorter Days Instead','Fix Overtime First','Keep Services Open','Test the Economics'][i],subtitle:'A distinct comment perspective',stance:'This group has a specific position on shorter working weeks.',reasoning:'Commenters describe different priorities and trade-offs.',full_stance:'The complete position is based on comments in this group.',statistics:{comment_count:[127,161,136,206,233][i],comment_share:[127,161,136,206,233][i]/1150,like_count:100,like_share:.1},arguments:[{text:'Coverage is a priority.',comment_ids:['source-g4']}],variations:[],limitations:['Comments do not establish policy outcomes.'],representative_comments:[source]}));
const catalog={fingerprint:'ui-fixture',video:{video_id:'BAHKmi4F1L8',title:'Could a shorter week work?',url:'https://www.youtube.com/watch?v=BAHKmi4F1L8'},agents,counts:{collected:1217,keep:1150,exclude:12,review:55,grouped:863,other:287,likes:1000},other_statistics:{comment_count:287,comment_share:287/1150,like_count:500,like_share:.5},rooms:[]};
const roomId='a'.repeat(32);
async function mockApi(page:Page,{existing=false,partial=false}={}){
  let state:any={room_id:roomId,participants:['g4'],initial_opinion:'I support shorter weeks and want to protect shift workers.',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),paused:true,active_job:null,message_count:0,preview:'Start with a question',auto_turns:0,auto_limit:6,messages:[],errors:[]};
  const requests:any[]=[];
  let hasRoom=existing;
  function reply(id:string,target:string){return {message_id:`m${state.messages.length+1}`,role:'agent',sender_id:id,reply_to:target,text:'My view is that service coverage needs a plan.',created_at:new Date().toISOString(),segments:[{text:'My view is that service coverage needs a plan.',basis:'comment',comment_ids:[source.comment_id]}],evidence:[source],follow_up_questions:['What coverage plan would you consider?']};}
  if(existing){state.messages=[{message_id:'m1',role:'user',sender_id:'user',reply_to:null,text:'What is your view?',created_at:new Date().toISOString(),segments:[],evidence:[],follow_up_questions:[]}];state.messages.push(reply('g4','m1'));state.message_count=2;}
  const jobs=new Map<string,any>();
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname,method=request.method(),body=method==='GET'?undefined:request.postDataJSON();
    requests.push({path,method,body,video:request.headers()['x-review-video']});
    const respond=(json:any,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(json)});
    if(path==='/api/videos' && method==='GET')return respond({demo:catalog.video,can_generate:true,comment_limit:100});
    if(path==='/api/bootstrap')return respond({...catalog,rooms:hasRoom?[state]:[]});
    if(path==='/api/rooms'&&method==='GET')return respond(hasRoom?[state]:[]);
    if(path==='/api/rooms'&&method==='POST'){state={...state,participants:body.participants,initial_opinion:body.initial_opinion,messages:[],errors:[],message_count:0};hasRoom=true;return respond(state,201);}
    if(path===`/api/rooms/${roomId}`){if(method==='PATCH')state.paused=body.paused;return respond(state);}
    if(path==='/api/compare')return respond({job_id:'compare',status:'completed',result:{similar:'You both value usable time outside work.',different:'You have not specified how services would stay open.',consideration:'Who would cover the remaining shifts?',similar_quotes:['shorter weeks'],different_quotes:[]}});
    if(path==='/api/comments')return respond({job_id:'comments',status:'completed',result:{comments:[source],total:287,page:body.page,page_size:12}});
    if(method==='POST'&&(path.endsWith('/ask')||path.endsWith('/retry'))){
      const jobId=path.endsWith('/retry')?'retry':'ask';
      const target=path.endsWith('/retry')?body.target_message_id:`m${state.messages.length+1}`;
      if(jobId==='ask')state.messages.push({message_id:target,role:'user',sender_id:'user',reply_to:null,text:body.text,created_at:new Date().toISOString(),segments:[],evidence:[],follow_up_questions:[]});
      state.active_job=jobId;
      jobs.set(jobId,{polls:0,finish:()=>{for(const aid of body.recipients){if(partial&&jobId==='ask'&&aid==='g3'){state.errors.push({agent_id:aid,target_message_id:target,error:'Provider unavailable'});continue;}state.messages.push(reply(aid,target));}if(jobId==='retry')state.errors=[];state.active_job=null;state.message_count=state.messages.length;}});
      return respond({job_id:jobId,status:'running',room_id:roomId},202);
    }
    if(path.startsWith('/api/jobs/')){const id=path.split('/').at(-1)!,job=jobs.get(id);job.polls++;if(job.polls===1)return respond({job_id:id,status:'running'});if(job.polls===2)job.finish();return respond({job_id:id,status:'completed',result:{}});}
    return respond({error:'Unmocked endpoint'},404);
  });
  return {requests};
}
async function initial(page:Page){await page.goto('/');await page.getByRole('link',{name:'Open prepared video'}).click();await page.getByRole('textbox',{name:'Your initial view',exact:true}).fill('I support shorter weeks and want to protect shift workers.');await page.getByRole('button',{name:'Save & explore perspectives'}).click();}

test('A submitted URL survives reload and opens a conversation in that video', async({page})=>{
  const api=await mockApi(page);
  const id='newvideo123', video={video_id:id,title:'A new discussion',url:'https://youtu.be/'+id};
  let ready=false, starts=0, reads=0, stage='grouping', elapsed=64;
  let accept!:()=>void;
  const submitted=new Promise<void>(resolve=>{accept=resolve;});
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(path==='/api/videos' && req.method()==='POST'){
      starts++;
      expect(req.postDataJSON()).toEqual({url:video.url});
      await submitted;
      return route.fulfill({status:202,json:{video_id:id,status:'running',stage:'collecting'}});
    }
    if(path==='/api/videos/'+id){
      reads++;
      return route.fulfill({json:{video_id:id,status:ready?'ready':'running',stage,elapsed_seconds:elapsed}});
    }
    if(path==='/api/bootstrap' && req.headers()['x-review-video']===id)
      return route.fulfill({json:{...catalog,video,fingerprint:id,agents:[agents[0]]}});
    return route.fallback();
  });
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  const start=page.getByRole('button',{name:'Generate agents'});
  await expect(start).toBeDisabled();
  await page.getByLabel('YouTube video URL').fill(video.url);
  await start.click();
  const progress=page.getByRole('progressbar',{name:'Agent generation progress'});
  try {
    await expect(progress).toBeVisible();
    await expect(progress).not.toHaveAttribute('aria-valuenow',/.+/);
  } finally {
    accept();
  }
  await expect(page).toHaveURL(/\?prepare=newvideo123$/);
  await expect(page.getByRole('status')).toContainText('Grouping related perspectives');
  await expect(progress).toHaveAttribute('aria-valuenow','2');
  await expect(page.getByRole('status')).toContainText('Step 3 of 5');
  await expect(page.getByRole('timer')).toHaveText('Elapsed 1:04');
  elapsed=67;
  await page.reload();
  await expect(progress).toHaveAttribute('aria-valuenow','2');
  await expect(page.getByRole('timer')).toHaveText('Elapsed 1:07');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
  stage='preparing_cards';elapsed=145;
  await expect(progress).toHaveAttribute('aria-valuenow','4');
  await expect(page.getByRole('status')).toContainText('Step 5 of 5');
  await expect(page.getByRole('timer')).toHaveText('Elapsed 2:25');
  ready=true;
  await expect(page).toHaveURL(/\?video=newvideo123$/);
  await expect(progress).toHaveCount(0);
  await page.getByLabel('Your initial view',{exact:true}).fill('I want to understand this video.');
  await page.getByRole('button',{name:'Save & explore perspectives'}).click();
  await expect(page.locator('.perspective-card')).toHaveCount(1);
  await page.getByRole('button',{name:'Converse with the perspectives'}).click();
  await expect(page.getByRole('button',{name:/Group chat \(1:N\)/})).toBeDisabled();
  await page.getByRole('button',{name:/1:1 chat/}).click();
  await page.getByRole('radio').first().click();
  await page.getByRole('button',{name:/Start 1:1 chat/}).click();
  await expect(page.getByRole('textbox',{name:'Message',exact:true})).toBeVisible();
  expect(api.requests.find(r=>r.path==='/api/rooms'&&r.method==='POST')?.video).toBe(id);
  expect(starts).toBe(1);
  expect(reads).toBeGreaterThan(1);
  await page.getByRole('link',{name:'Choose video',exact:true}).click();
  await expect(page.getByLabel('YouTube video URL')).toHaveValue('');
});

test('Invalid links and failed preparations leave the URL editable and the example usable', async({page})=>{
  await mockApi(page);
  const id='badvideo123';
  let starts=0;
  await page.route('**/api/videos',async route=>{
    if(route.request().method()==='GET')return route.fallback();
    starts++;
    if(starts===1)return route.fulfill({status:400,json:{error:'Enter a YouTube video link or its 11-character video ID.'}});
    return route.fulfill({status:202,json:{video_id:id,status:'running',stage:'collecting'}});
  });
  await page.route('**/api/videos/'+id,route=>route.fulfill({json:{video_id:id,status:'failed',error:'Comments are disabled for this video. Choose another video.'}}));
  await page.goto('/');
  const input=page.getByLabel('YouTube video URL');
  await input.fill('invalid');
  await page.getByRole('button',{name:'Generate agents'}).click();
  await expect(page.getByRole('alert')).toContainText('Enter a YouTube video');
  await input.fill('https://youtu.be/'+id);
  await page.getByRole('button',{name:'Generate agents'}).click();
  await expect(page.getByRole('alert')).toContainText('Comments are disabled');
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await expect(input).toBeEditable();
  await page.getByRole('link',{name:'Open prepared video'}).click();
  await expect(page.getByLabel('Your initial view',{exact:true})).toBeVisible();
  expect(starts).toBe(2);
});

test('The previous API still opens its SBS example during a staged deployment',async({page})=>{
  const api=await mockApi(page);
  await page.route('**/api/videos',route=>route.fulfill({status:404,json:{error:'API endpoint not found.'}}));
  await page.goto('/');
  await expect(page.getByText('New video generation is unavailable on this server.',{exact:false})).toBeVisible();
  await page.getByRole('link',{name:'Open prepared video'}).click();
  await expect(page.getByLabel('Your initial view',{exact:true})).toBeVisible();
  await page.goto('/?video=newvideo123');
  await expect(page.getByRole('alert')).toContainText('This analysis is unavailable');
  await page.getByRole('link',{name:'Choose video',exact:true}).click();
  await expect(page.getByLabel('YouTube video URL')).toBeVisible();
  expect(api.requests.filter(r=>r.method==='POST')).toHaveLength(0);
});

test('Explore uses five actual groups, preserves other opinions and compares the initial view',async({page})=>{
  await mockApi(page);await initial(page);
  await expect(page.locator('.perspective-card')).toHaveCount(5);
  await expect(page.locator('.other-opinions')).toContainText('287');
  await page.getByTestId('card-g4').click();
  await expect(page.locator('.comparison-section')).toHaveCount(3);
  await expect(page.locator('mark.similar')).toHaveText('shorter weeks');
  await page.getByRole('button',{name:'Source comments',exact:true}).click();
  await expect(page.locator('blockquote[lang="ko"]')).toHaveCount(0);
  await page.getByRole('button',{name:'Show Korean original'}).click();
  await expect(page.locator('blockquote[lang="ko"]')).toContainText('서비스');
  await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:/Browse other opinions/}).click();
  await expect(page.locator('.comments-modal .source-comment')).toHaveCount(1);
});

test('Group selection requires two agents and retry targets only the failed participant',async({page})=>{
  const api=await mockApi(page,{partial:true});await initial(page);
  await page.getByRole('button',{name:'Converse with the perspectives'}).click();
  await page.getByRole('button',{name:/Group chat \(1:N\)/}).click();
  const start=page.getByRole('button',{name:'Start group chat',exact:true});await expect(start).toBeDisabled();
  await page.getByRole('checkbox').nth(0).click();await expect(start).toBeDisabled();
  await page.getByRole('checkbox').nth(3).click();await expect(start).toBeEnabled();await start.click();
  await page.getByRole('textbox',{name:'Message',exact:true}).fill('What would have to change?');
  await page.getByRole('button',{name:'Send message',exact:true}).click();
  await expect(page.getByRole('button',{name:'Send message',exact:true})).toBeDisabled();
  await expect(page.locator('[data-testid="message-agent"]')).toHaveCount(1);
  await expect(page.locator('.reply-error')).toBeVisible();
  await page.getByRole('button',{name:'Retry this agent'}).click();
  await expect(page.locator('[data-testid="message-agent"]')).toHaveCount(2);
  await expect(page.locator('.reply-error')).toHaveCount(0);
  const retry=api.requests.find(r=>r.path.endsWith('/retry'));
  expect(retry.body.recipients).toEqual(['g3']);
  expect(api.requests.filter(r=>r.method==='POST'&&r.path.endsWith('/ask'))).toHaveLength(1);
});

test('Evidence survives reload and mobile layout stays within the viewport',async({page})=>{
  await mockApi(page,{existing:true});
  await page.addInitScript(({id})=>{localStorage.setItem('review:ui-fixture:initial','I support shorter weeks.');localStorage.setItem('review:ui-fixture:room',id);},{id:roomId});
  await page.goto('/#converse');
  await page.locator('.evidence-chip').click();await page.locator('.save-evidence').click();
  await page.reload();await page.getByRole('button',{name:'Open evidence panel',exact:true}).click();
  await expect(page.getByRole('button',{name:'Saved · 1',exact:true})).toBeVisible();
  await expect(page.locator('.saved-actions')).toHaveCount(1);
  await page.getByRole('button',{name:'Close evidence panel'}).click();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
  await page.getByRole('button',{name:'Explore',exact:true}).click();
  await expect(page.locator('.perspective-card')).toHaveCount(5);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
});
