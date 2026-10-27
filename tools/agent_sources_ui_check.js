/* Original application + isolated fixture APIs; no user Workspace/model calls. */
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..'),output=path.join(root,'.scratch/verify/agent-sources');fs.mkdirSync(output,{recursive:true});
const sid='chat-sources123',other='chat-sources456',requests=[];
const summary={schema_version:1,revision:4,recording_status:'complete',provided_source_count:3,cited_source_count:2,counts_by_kind:{note:2,idea:1}};
const docs=[{id:'note-cache',title:'反馈共享必须绑定状态与候选域',kind:'note',body:'原条目的最新内容。',tags:['方法'],projects:['缓存研究'],status:'记录'},{id:'note-check',title:'同一父状态下的候选独立校验',kind:'note',body:'独立校验。',tags:[],projects:[],status:'记录'}];
const excerpt='缓存键至少含状态哈希、负荷、电源、故障隔离和动作；\n状态变化后重算合法候选，必要时废弃旧反馈。\n<script>window.__sourcesInjected=true</script>\n'+('需要独立校核状态和动作条件。\n'.repeat(24));
function source(id,title,kind,number,text,channel='rag'){
  return {source_id:'source-'+id,entity_id:id,entity_key:'doc:'+id,entity_type:'doc',title,kind,number,tags:kind==='idea'?['待验证']:['方法'],projects:['缓存研究'],provided:true,cited:number<3,channels:[channel],snapshots:[{snapshot_id:'src-'+id,entity_id:id,text,wire_text:text,version:'version-old-12345678',provided:true,channel,request_ids:['req-1'],location:{offset:12},partial:false}]};
}
const sources=[source('note-cache',docs[0].title,'note',1,excerpt),source('note-check',docs[1].title,'note',2,'每个候选从相同父状态独立施加动作。','manual'),source('idea-share','同父状态物理反馈的跨分支共享','idea',3,'研究设想：共享反馈是否能减少重复试错，需要实验验证。')];
sources[0].snapshots.push({...sources[0].snapshots[0],snapshot_id:'src-cache-new',version:'version-new',text:'第二次读取的实际片段。',channel:'read'});
const messages=[{id:'msg-question',role:'user',content:'思维树的不同分支可以共享潮流校验反馈吗？',created:'2026-10-22'},{id:'msg-a',role:'assistant',content:`可以共享，但必须绑定父状态和动作条件。\n\n参见 [[${docs[0].title}]] 和 [[note-check|独立校验]]。\n\n\`[[代码中的引用不应计入]]\``,source_summary:summary,run_id:'run-a',created:'2026-10-22'},{id:'msg-b',role:'assistant',content:'另一条回答。',source_summary:{...summary,provided_source_count:1,cited_source_count:0,counts_by_kind:{idea:1}},run_id:'run-b',created:'2026-10-22'}];
const sessions=[{id:sid,title:'跨分支反馈共享的边界',updated:'2026-10-22',messages},{id:other,title:'另一个会话',updated:'2026-10-21',messages:[]}];
function view(mid,live=false){const rows=mid==='msg-b'?[sources[2]]:sources;return {schema_version:1,session_id:sid,message_id:mid,run_id:mid==='msg-b'?'run-b':'run-a',source_summary:{...(mid==='msg-b'?messages[2].source_summary:summary),revision:live?liveRevision:4},sources:rows.map(s=>live?structuredClone(s):({...s,snapshot_count:s.snapshots.length,snapshots:undefined})),requests:[{id:'req-1',created:'2026-10-22T13:40:00',status:'responded',protocol:'tools',stream:true}],warnings:[],unresolved_citations:[]}}
let slow=false,failOnce=false,liveRevision=4,deleted=false;
const cfg={app:{app_name:'科研工作台',subtitle:'Engineering Research Workspace',ui:{},academic_profile:{graduation_conditions:[]},llm:{enabled:true,active_profile_id:'fixture',request_presets:[{id:'default',label:'默认',model:'fixture'}],profiles:[{id:'fixture',name:'测试配置',base_url:'https://example.invalid/v1',request_presets:[{id:'default',label:'默认',model:'fixture'}]}],personas:[{id:'executor',name:'阅读助手',tools:['kb_read'],write_mode:'confirm'}]}},rss:{sources:[]},weather:{enabled:false}};
const opts={max_steps:48,time_budget_seconds:900,context_tokens:24000,rag_enabled:true,memory_enabled:true,skills_enabled:true,rag_top_k:8,rag_context_chars:8000};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost'),p=url.pathname;
  const send=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data))};
  if(p.startsWith('/api/')){
    requests.push(p+url.search);let data=[];
    if(p==='/api/config')data=cfg;
    else if(p==='/api/knowledge-types')data=['idea','journal','note','milestone','summary','literature'].map(id=>({id,label:id,statuses:['记录']}));
    else if(p==='/api/statuses')data={note:['记录']};
    else if(p==='/api/health')data={version:'sources-test'};
    else if(p==='/api/workspace/info')data={relative:'Fixture'};
    else if(p.startsWith('/api/weather'))data={enabled:false};
    else if(p==='/api/agent/system')data={settings:opts,brain:{counts:{}}};
    else if(p==='/api/agent/skills')data={skills:[],errors:[]};
    else if(p==='/api/agent/sessions')data=sessions.map(s=>({...s,message_count:s.messages.length,messages:undefined}));
    else if(p.includes('/messages/')&&p.includes('/sources')){
      const parts=p.split('/'),mid=parts[6],id=parts[8];
      if(parts[4]!==sid||!['msg-a','msg-b'].includes(mid))return send({message:'回答不存在'},404);
      if(slow&&mid==='msg-a'&&!id)await new Promise(resolve=>setTimeout(resolve,400));
      if(failOnce){failOnce=false;return send({message:'模拟暂时无法读取来源'},503)}
      data=id?sources.find(s=>s.source_id===id):view(mid);
    }
    else if(p.startsWith('/api/agent/sessions/'))data=sessions.find(s=>s.id===p.split('/').at(-1));
    else if(p==='/api/agent/runs')data=[{id:'run-a',session_id:sid,summary:'核对跨分支反馈',status:'completed',updated:'2026-10-22',result:{assistant:messages[1]}}];
    else if(p.endsWith('/events'))data=[];
    else if(p.endsWith('/sources')&&p.includes('/runs/'))data=view('',true);
    else if(p==='/api/agent/runs/run-a')data={id:'run-a',session_id:sid,status:'completed',state:{plan:[]},result:{assistant:messages[1]}};
    else if(p.startsWith('/api/docs/')){if(deleted)return send({message:'原条目已删除，历史片段仍保留'},404);data=docs.find(d=>d.id===p.split('/').at(-1))}
    return send(data??{});
  }
  const file=path.resolve(root,'web','.'+(p==='/'?'/index.html':p));
  if(!file.startsWith(path.join(root,'web')+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return}
  const mime={'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.woff2':'font/woff2'};
  res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
  const context=await browser.newContext({viewport:{width:1804,height:1000},reducedMotion:'reduce',permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));page.setDefaultTimeout(10000);
  try{
    await page.addInitScript(sid=>localStorage.setItem('agentActiveSession',sid),sid);
    await page.goto(`http://127.0.0.1:${server.address().port}/#agent`);
    const entries=page.locator('#agent-messages .agent-sources-entry'),panel=page.locator('#agent-sources-panel');
    async function assertBallAccessible(){
      await page.waitForFunction(()=>{const ball=document.querySelector('#erw-fab-ball'),r=ball.getBoundingClientRect();return Math.min(r.right,innerWidth)-Math.max(r.left,0)>10&&r.top>=0&&r.bottom<=innerHeight+.5});
      const hit=await page.locator('#erw-fab-ball').evaluate(ball=>{const r=ball.getBoundingClientRect(),left=Math.max(r.left,0),right=Math.min(r.right,innerWidth);return [.25,.5,.75].every(x=>ball.contains(document.elementFromPoint(left+(right-left)*x,r.top+r.height/2)))});
      assert.equal(hit,true,'the visible part of the AI ball stays above the sources panel and receives clicks');
    }
    async function revealBall(){
      await assertBallAccessible();
      const point=await page.locator('#erw-fab-ball').evaluate(ball=>{const r=ball.getBoundingClientRect();return {x:(Math.max(r.left,0)+Math.min(r.right,innerWidth))/2,y:r.top+r.height/2}});
      await page.mouse.move(point.x,point.y);
      await page.waitForFunction(()=>{const r=document.querySelector('#erw-fab-ball').getBoundingClientRect();return r.left>=-.5&&r.right<=innerWidth+.5});
    }
    async function assertBallDocking(){
      for(const side of ['right','left']){
        await revealBall();
        const ball=page.locator('#erw-fab-ball'),r=await ball.boundingBox(),viewport=page.viewportSize();
        await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();
        await page.mouse.move(side==='left'?10:viewport.width-10,300,{steps:12});await page.mouse.up();
        await page.mouse.move(viewport.width/2,200);
        assert.equal(await page.locator('#erw-fab-panel').isVisible(),false,'dragging does not open the assistant');
        await page.waitForFunction(side=>{const ball=document.querySelector('#erw-fab-ball'),r=ball.getBoundingClientRect();return ball.dataset.dock===side&&Math.abs(r.left+r.width/2-(side==='left'?0:innerWidth))<1},side);
        await assertBallAccessible();await revealBall();await page.mouse.move(viewport.width/2,200);
        await page.waitForFunction(side=>{const r=document.querySelector('#erw-fab-ball').getBoundingClientRect();return Math.abs(r.left+r.width/2-(side==='left'?0:innerWidth))<1},side);
      }
      await page.keyboard.press('Tab');await page.locator('#erw-fab-ball').focus();
      await page.waitForFunction(()=>{const ball=document.querySelector('#erw-fab-ball'),r=ball.getBoundingClientRect();return ball.matches(':focus-visible')&&r.left>=-.5&&r.right<=innerWidth+.5});
      await page.waitForTimeout(800);
      assert.ok((await page.locator('#erw-fab-ball').boundingBox()).x>=-.5,'keyboard focus keeps the ball expanded');
      await page.locator('#erw-fab-ball').evaluate(ball=>ball.blur());
      await page.waitForFunction(()=>{const r=document.querySelector('#erw-fab-ball').getBoundingClientRect();return Math.abs(r.left+r.width/2)<1});
    }
    async function openAssistantFromSources(){
      await revealBall();await page.locator('#erw-fab-ball').click();await page.locator('#fab-input').waitFor();
      assert.equal(await panel.isVisible(),false,'opening the assistant closes the sources panel so the chat is not covered');
      assert.equal(await page.locator('#fab-input').evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))}),true,'assistant input is clickable');
      await page.locator('#fab-close').click();
    }
    await entries.first().waitFor();assert.equal(requests.filter(p=>p.includes('/sources')).length,0,'closed panel never fetches snapshots');
    await assertBallDocking();
    await page.locator('#agent-messages .assistant').first().getByRole('link',{name:docs[0].title,exact:true}).click();
    await panel.locator('.agent-source-excerpt').getByText(/缓存键至少含状态哈希/).waitFor();
    assert.equal(await panel.locator('.agent-source-card.selected strong').textContent(),docs[0].title);
    assert.equal(await panel.locator('.agent-source-card').count(),3);
    assert.match(await panel.locator('.agent-sources-stats').textContent(),/3 条资料已提供 · 2 条在回答中引用/);
    assert.equal(await page.evaluate(()=>window.__sourcesInjected),undefined,'source text is escaped');
    assert.equal(await panel.locator('script').count(),0);
    assert.equal(await page.locator('body').getAttribute('data-agent-sources-mode'),'dock');
    await assertBallDocking();
    const chat=await page.locator('#agent-chat-panel').boundingBox(),box=await panel.boundingBox();assert.ok(chat.x+chat.width<=box.x,'docked pane does not cover the conversation');
    const density=await panel.evaluate(el=>{
      const size=selector=>parseFloat(getComputedStyle(el.querySelector(selector)).fontSize);
      return {title:size('h3'),source:size('.agent-source-card strong'),excerpt:size('.agent-source-excerpt'),metadata:size('.agent-source-card small'),lineHeight:parseFloat(getComputedStyle(el.querySelector('.agent-source-excerpt')).lineHeight)};
    });
    assert.deepEqual(density,{title:15,source:12,excerpt:12,metadata:11,lineHeight:18.6},'source panel uses compact secondary typography');
    await page.evaluate(()=>document.documentElement.style.setProperty('--reading-font-size','20px'));
    assert.equal(await panel.locator('.agent-source-excerpt').evaluate(el=>getComputedStyle(el).fontSize),'12px','reading size does not enlarge source snippets');
    await page.evaluate(()=>document.documentElement.style.removeProperty('--reading-font-size'));
    await assertBallAccessible();
    await page.screenshot({path:path.join(output,'desktop-sources.png')});
    await page.locator('#theme-btn').click();await page.screenshot({path:path.join(output,'desktop-sources-dark.png')});await page.locator('#theme-btn').click();
    await openAssistantFromSources();await page.locator('#agent-messages .assistant').first().getByRole('link',{name:docs[0].title,exact:true}).click();await panel.locator('.agent-source-excerpt').waitFor();
    await panel.locator('[data-source-snapshot]').selectOption('src-cache-new');await panel.getByText('第二次读取的实际片段。',{exact:true}).waitFor();
    await panel.getByRole('button',{name:'复制片段',exact:true}).click();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'第二次读取的实际片段。');
    await panel.locator('[data-sources-filter=idea]').click();assert.equal(await panel.locator('.agent-source-card').count(),1);await panel.locator('.agent-source-card').click();await panel.getByText(/研究设想：共享反馈/).waitFor();
    await panel.locator('[data-sources-filter=all]').click();await panel.locator('[data-source-select=source-note-cache]').click();
    deleted=true;await panel.getByRole('button',{name:'打开原条目 ↗'}).click();await panel.locator('[role=status]').getByText(/原条目已删除/).waitFor();assert.match(await panel.locator('.agent-source-excerpt').textContent(),/缓存键/);deleted=false;
    await page.keyboard.press('Escape');assert.equal(await panel.isVisible(),false);
    // Closing via Esc restores focus to the link that opened it.
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.agentReference),docs[0].title);
    slow=true;await entries.first().click();await entries.last().click();await panel.getByText(/研究设想：共享反馈/).waitFor();await page.waitForTimeout(550);assert.equal(await panel.locator('.agent-source-card').count(),1,'slow old reply cannot replace another reply');slow=false;
    await page.keyboard.press('Escape');failOnce=true;await entries.first().click();await panel.getByText('模拟暂时无法读取来源',{exact:false}).waitFor();await panel.getByRole('button',{name:'重试',exact:true}).click();await panel.locator('.agent-source-excerpt').waitFor();
    await page.keyboard.press('Escape');await page.reload();await page.locator('#agent-messages .agent-sources-entry').first().click();await panel.locator('.agent-source-excerpt').waitFor();assert.equal(await panel.locator('.agent-source-card').count(),3,'refresh keeps answer binding');
    await page.keyboard.press('Escape');
    // A live panel preserves the selected DOM/text across source revisions and
    // ignores duplicate events; token deltas do not fetch source records.
    await page.evaluate(sid=>window.ERWAgentSources.open({sid,rid:'run-live'}),sid);await panel.locator('.agent-source-excerpt').waitFor();
    await panel.locator('.agent-source-excerpt').evaluate(el=>{window.__excerptNode=el;el.scrollTop=55;const range=document.createRange();range.selectNodeContents(el);window.getSelection().removeAllRanges();window.getSelection().addRange(range)});
    const before=requests.filter(p=>p.includes('/sources')).length;
    await page.evaluate(()=>{for(let i=0;i<20;i++)document.dispatchEvent(new CustomEvent('erw-agent-sources-updated',{detail:{run_id:'other-run',revision:i}}))});await page.waitForTimeout(220);assert.equal(requests.filter(p=>p.includes('/sources')).length,before);
    liveRevision=5;sources[0].snapshots.push({...sources[0].snapshots[0],snapshot_id:'src-live-more',text:'新增片段'});
    await page.evaluate(()=>document.dispatchEvent(new CustomEvent('erw-agent-sources-updated',{detail:{run_id:'run-live',revision:5}})));await page.waitForTimeout(400);
    assert.equal(await page.evaluate(()=>window.__excerptNode===document.querySelector('.agent-source-excerpt')),true);
    assert.match(await page.evaluate(()=>window.getSelection().toString()),/缓存键/);assert.equal(await panel.locator('[data-source-snapshot] option').count(),3);
    const updated=requests.filter(p=>p.includes('/sources')).length;await page.evaluate(()=>{for(const revision of [5,4,5])document.dispatchEvent(new CustomEvent('erw-agent-sources-updated',{detail:{run_id:'run-live',revision}}))});await page.waitForTimeout(250);assert.equal(requests.filter(p=>p.includes('/sources')).length,updated);
    await page.keyboard.press('Escape');
    await revealBall();await page.locator('#erw-fab-ball').click();await page.locator('#fab-messages .agent-sources-entry').first().click();await panel.locator('.agent-source-excerpt').waitFor();assert.equal(await page.locator('body').getAttribute('data-agent-sources-mode'),'drawer');await page.keyboard.press('Escape');await page.locator('#fab-close').click();
    await page.locator('#agent-chat-panel [data-agent-settings]').click();await page.getByRole('tab',{name:'任务',exact:true}).click();await page.locator('.as-run-result>summary').click();await page.locator('.as-answer .agent-sources-entry').click();await panel.locator('.agent-source-excerpt').waitFor();await page.keyboard.press('Escape');await page.locator('#as-back-chat').click();
    await page.setViewportSize({width:390,height:844});await page.locator('#agent-messages .agent-sources-entry').first().click();await panel.locator('.agent-source-excerpt').waitFor();
    const mobile=await panel.boundingBox();assert.ok(mobile.x>=0&&mobile.x+mobile.width<=390);assert.equal(await page.locator('body').getAttribute('data-agent-sources-mode'),'drawer');assert.ok(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    await assertBallDocking();
    await assertBallAccessible();await page.screenshot({path:path.join(output,'mobile-sources.png')});await openAssistantFromSources();
    await page.setViewportSize({width:1804,height:1000});await page.locator('#agent-messages .agent-sources-entry').first().click();await panel.locator('.agent-source-excerpt').waitFor();await page.evaluate(other=>window.ERWAgentClient.select(other),other);assert.equal(await panel.isVisible(),false,'switching sessions closes the old answer panel');
    // File/PDF snapshots use the same panel, with a file label and PDF page.
    const file=source('file','Resources/qa-source.txt','file',1,'QA-FILE-SOURCE-73','read');
    Object.assign(file,{entity_type:'file',entity_id:'Resources/qa-source.txt',entity_key:'file:Resources/qa-source.txt'});
    file.snapshots[0].location={path:'Resources/qa-source.txt',offset:5,end_offset:22};
    const pdf=source('pdf','PDF 来源验证','literature',2,'QA-PDF-SOURCE-73','read');
    Object.assign(pdf,{entity_type:'paper',entity_id:'paper-qa',paper_id:'paper-qa',entity_key:'paper:paper-qa'});
    pdf.snapshots[0].location={page:2,offset:0,end_offset:16};
    sources.splice(0,sources.length,file,pdf);
    Object.assign(summary,{provided_source_count:2,cited_source_count:2,counts_by_kind:{file:1,literature:1}});
    await page.evaluate(sid=>window.ERWAgentClient.select(sid),sid);
    await page.locator('#agent-messages .agent-sources-entry').first().click();
    await panel.locator('[data-sources-filter=file]').click();await panel.locator('[data-source-select=source-file]').click();
    await panel.getByText('QA-FILE-SOURCE-73',{exact:true}).waitFor();
    assert.match(await panel.locator('.agent-source-card small').first().textContent(),/文件/);
    assert.match(await panel.locator('.agent-sources-detail').textContent(),/字符起点 5/);
    await panel.getByRole('button',{name:'复制片段',exact:true}).click();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'QA-FILE-SOURCE-73');
    await panel.locator('[data-sources-filter=literature]').click();await panel.locator('[data-source-select=source-pdf]').click();
    await panel.getByText('QA-PDF-SOURCE-73',{exact:true}).waitFor();
    assert.match(await panel.locator('.agent-sources-detail').textContent(),/第 2 页/);
    await page.screenshot({path:path.join(output,'file-pdf-sources.png')});await page.keyboard.press('Escape');
    sources.splice(0);Object.assign(summary,{recording_status:'incomplete',provided_source_count:0,cited_source_count:0,counts_by_kind:{}});
    await page.reload();await page.locator('#agent-messages .agent-sources-entry').first().click();
    await panel.getByText('没有可还原的来源片段。',{exact:true}).waitFor();
    assert.match(await page.locator('#agent-messages .agent-sources-entry').first().textContent(),/来源记录不完整/);
    assert.equal(await panel.getByText('本轮未提供知识资料。',{exact:true}).count(),0);
    assert.deepEqual(errors,[]);console.log('Sources UI passed: left/right ball docking with sources closed/docked/drawer, hover/keyboard reveal, visible ball hit area, main/floating/task views, citation selection, version/filter/copy, deleted source, refresh, errors, async isolation, live DOM/selection, idempotent events, mobile, file/PDF snapshots and incomplete fallback.');
  }catch(error){await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error}
  finally{await browser.close();server.close()}
})().catch(error=>{console.error(error);process.exitCode=1;server.close()});
