/* Full original Agent page, fixture HTTP APIs, no personal data or model calls. */
const assert=require('node:assert/strict');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const output=path.join(root,'.scratch','verify','agent-system');fs.mkdirSync(output,{recursive:true});
const longTitle='配电网供电恢复文献检索与多种方法的证据对比，保留完整来源并核验物理约束。'.repeat(5);
const sessions=[{id:'chat-fixture123',title:longTitle,updated:'2026-10-19',messages:[]},{id:'chat-other123',title:'另一会话',updated:'2026-10-18',messages:[]}];
const runs=[{id:'run-other',session_id:sessions[1].id,status:'completed',updated:'2026-10-18'}],memories=[],installed=[],requests=[];
let opts={max_steps:48,time_budget_seconds:900,context_tokens:24000,auto_recall:true,web_enabled:true,code_enabled:false,docker_image:'python:3.12-slim',mcp_servers:[],skills_enabled:true,disabled_skills:[],rag_enabled:true,memory_enabled:true,rag_top_k:8,rag_context_chars:8000};
let mode='normal',failSessionOnce=false,approved=false,sequence=0,delayMemory=false,failListReads=1,failedListReads=0,releaseStream=null,draftId='draft-fixture',confirmFailure=false,draftWrites=0,draftStatus='confirmed',resumeDelayed=false;
let ragOptions={mode:'keyword',base_url:'',model:'',dimensions:0,chunk_chars:1600,overlap_chars:200,batch_size:16,include_pdf:false,has_api_key:false},ragIndex={},ragJob={},settingsFailure=false,clearFailure=false;
const skill={name:'literature-review',description:'比较文献并保留证据',builtin:true};
const citationNote={id:'note-citation',kind:'note',title:'知识-原理-辐射状约束与供电连通性',body:'## 原理\n无环还需要结合连通性。\n\n| 术语 | 说明 |\n| --- | --- |\n| **合法动作** | `D1` 需要校核 |',projects:[],tags:[],kind_marks:[],status:'记录'};
const citationPaper={...citationNote,id:'literature-citation',kind:'literature',title:'文献-组会原文',attachment:'Knowledge/Literature/PDF/fixture.pdf',body:'## 原始文献\n程序组织物理依据，模型选择动作。'};
const cfg={app:{app_name:'科研工作台',subtitle:'Engineering Research Workspace',ui:{},academic_profile:{graduation_conditions:[]},llm:{enabled:true,active_profile_id:'fixture',request_presets:[{id:'default',label:'默认',model:'fixture'}],profiles:[{id:'fixture',name:'测试配置',base_url:'https://example.invalid/v1',request_presets:[{id:'default',label:'默认',model:'fixture'}]}],personas:[{id:'executor',name:'执行助手',tools:['kb_read'],write_mode:'confirm'},{id:'reader',name:'阅读助手',tools:['kb_read'],write_mode:'confirm'}]}},rss:{sources:[]},weather:{enabled:false}};
function answer(content,extra={}){return {id:'msg-'+(++sequence),role:'assistant',content,created:'2026-10-19',model:'fixture',...extra}}
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost'),p=url.pathname;
  if(p.startsWith('/api/')){
    let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):{};
    requests.push({path:p,query:url.searchParams,body});let data=[];
    if(p==='/api/config')data=cfg;
    else if(p==='/api/knowledge-types')data=['idea','journal','note','milestone','summary','literature'].map(id=>({id,label:id,statuses:['记录']}));
    else if(p==='/api/statuses')data={note:['记录']};
    else if(p==='/api/projects')data=[];
    else if(p==='/api/health')data={version:'agent-test'};
    else if(p==='/api/workspace/info')data={relative:'Fixture'};
    else if(p.startsWith('/api/weather'))data={enabled:false};
    else if(p==='/api/agent/send'){
      const session=sessions.find(s=>s.id===body.session_id);assert(session);
      session.messages.push({id:'msg-'+(++sequence),role:'user',content:body.message,quote_text:body.context?.quote_text||'',edited_from:body.context?.edited_from||'',created:'2026-10-19'});
      const run={id:'run-'+sequence,session_id:session.id,status:mode==='draft'?'waiting_approval':'completed',updated:'2026-10-19'};
      const parts=[{round:1,content:'## 核心方法\n第一轮分析：低秩适配。'},{round:2,content:'第二轮比较：\n\n| 方法 | 特点 |\n| --- | --- |\n| LoRA | 参数少 |'}];
      const multi=['multi','partial'].includes(mode);
      const message=answer(mode==='draft'?'请确认草稿后继续。':multi?'任务已完成。':'已完成带来源的研究总结 '+sequence,{run_id:run.id,...(multi?{response_parts:parts}:{}),...(mode==='draft'?{drafts:[{draft_id:draftId,tool:'kb_create_entry',summary:'知识-方法-测试'}]}:{})});
      if(mode==='error'){res.writeHead(200,{'Content-Type':'text/event-stream'});res.end('event: error\ndata: '+JSON.stringify({message:'模拟模型接口失败'})+'\n\n');return}
      session.messages.push(message);session.title='已更新的研究会话';session.updated='2026-10-19T12:00:00';run.result={assistant:message};runs.unshift(run);
      if(mode==='metadata')failSessionOnce=true;
      const encode=events=>events.map(([event,data])=>'event: '+event+'\ndata: '+JSON.stringify(data)+'\n\n').join('');
      if(mode==='rag-evidence'){
        message.content='## 检索结果\n\n'+Array.from({length:60},(_,i)=>`${i+1}. 这是用于验证长回复底部入口的检索结果，来自实际返回的来源片段。`).join('\n\n');
        const retrieval={call_id:'rag-fixture',query:'供电恢复',mode:'keyword',requested_mode:'hybrid',warning:'模拟 Embedding 超时',count:1,limit:12,items:[{id:citationNote.id,title:citationNote.title,kind:'note',retrieval:'keyword',excerpt:'实际传给模型的来源片段 <script>不执行</script>',source:{type:'markdown',offset:0,end_offset:30}}]};
        message.retrievals=[retrieval];message.capabilities={rag_enabled:true,memory_enabled:false,skills_enabled:false};message.source_policy='rag_only';
        res.writeHead(200,{'Content-Type':'text/event-stream','X-Agent-Run-ID':run.id});res.write(encode([['run',{run_id:run.id}],['capabilities',{capabilities:message.capabilities,source_policy:'rag_only'}],['round',{i:0}],['retrieval',retrieval]]));
        await new Promise(resolve=>{releaseStream=resolve});releaseStream=null;
        res.write(encode([['delta',{text:'正在按来源整理'}]]));
        await new Promise(resolve=>{releaseStream=resolve});releaseStream=null;
        res.end(encode([['done',{ok:true,assistant:message}]]));return;
      }
      if(mode==='citation'){message.content='参见 [[知识-原理-辐射状约束与供电连通性]] 和 [[literature-citation|组会原文]]。\n\n`[[代码中的引用不应变成链接]]`\n\n| 术语 | 校验 |\n| --- | --- |\n| **合法动作** | `D1` 需要核对 |';message.skills_used=[{name:'evidence-audit',display_name:'证据核查',reason:'implicit',resources:['SKILL.md','references/checklist.md'],script_runs:0}]}
      if(['hold','delayed-hold'].includes(mode)){
        session.messages.pop();run.status='running';run.result=null;
        run.stop=()=>{const partial=answer('已生成的部分回答',{run_id:run.id,run_status:'cancelled',interruption:'已停止生成，已生成内容和原有提问已保留。'});session.messages.push(partial);run.status='cancelled';run.result={assistant:partial};delete run.stop;res.end(encode([['done',run.result]]))};
        const begin=()=>{res.writeHead(200,{'Content-Type':'text/event-stream','X-Agent-Run-ID':run.id});res.write(encode([['run',{run_id:run.id,session_id:session.id}],['round',{i:0}],['delta',{text:'已生成的部分回答'}]]))};
        if(mode==='delayed-hold'){await new Promise(resolve=>{releaseStream=resolve});releaseStream=null}begin();return;
      }
      if(mode==='eof'){
        res.writeHead(200,{'Content-Type':'text/event-stream','X-Agent-Run-ID':run.id});res.end(encode([['delta',{text:'流已结束，后台结果已保存'}]]));return;
      }
      if(mode==='replay'){
        run.status='running';run.pending=message;run.result=null;run.polls=0;session.messages.pop();
        res.writeHead(200,{'Content-Type':'text/event-stream','X-Agent-Run-ID':run.id});
        res.end('event: run\nid: 1\ndata: '+JSON.stringify({run_id:run.id,session_id:session.id})+'\n\nevent: delta\nid: 2\ndata: '+JSON.stringify({text:'恢复前正文。'})+'\n\n');return;
      }
      if(mode==='crlf'){
        const frames=[['run',{run_id:run.id,session_id:session.id}],['delta',{text:message.content}],['done',{ok:true,assistant:message}]];
        const bytes=Buffer.from(frames.map(([event,data])=>'event: '+event+'\r\n'+JSON.stringify(data,null,2).split('\n').map(line=>'data: '+line).join('\r\n')+'\r\n\r\n').join('').trimEnd());
        res.writeHead(200,{'Content-Type':'text/event-stream'});const cuts=[7,38,bytes.length-4,bytes.length];let offset=0;for(const cut of cuts){res.write(bytes.subarray(offset,cut));offset=cut;await new Promise(resolve=>setTimeout(resolve,4))}res.end();return;
      }
      if(multi){
        res.writeHead(200,{'Content-Type':'text/event-stream; charset=utf-8'});
        res.write(encode([['run',{run_id:run.id,session_id:session.id}],['round',{i:0}],['delta',{text:parts[0].content}],['response',{...parts[0],intermediate:true}],['tool',{name:'kb_search',ok:true,ms:5}],['round',{i:1}],['delta',{text:parts[1].content}],['response',{...parts[1],intermediate:true}],['round',{i:2}]]));
        if(mode==='partial'){res.end(encode([['error',{message:'模拟中途连接失败'}]]));return}
        await new Promise(resolve=>{releaseStream=resolve});releaseStream=null;
        res.end(encode([['delta',{text:message.content}],['response',{round:3,content:message.content,intermediate:false}],['done',{ok:true,assistant:message}]]));return;
      }
      const events=[['run',{run_id:run.id,session_id:session.id}],['round',{i:0}],['delta',{text:message.content}],['done',{ok:true,assistant:message}]];
      res.writeHead(200,{'Content-Type':'text/event-stream; charset=utf-8'});res.end(events.map(([event,data])=>'event: '+event+'\ndata: '+JSON.stringify(data)+'\n\n').join(''));return;
    }
    else if(p==='/api/agent/sessions'&&req.method==='POST'){data={id:'chat-new123',title:'新对话',messages:[]};sessions.unshift(data)}
    else if(p==='/api/agent/sessions'){if(failListReads>0){failListReads--;failedListReads++;res.destroy();return}data=sessions.map(s=>({...s,message_count:s.messages.length}))}
    else if(p.startsWith('/api/agent/sessions/')){if(failSessionOnce){failSessionOnce=false;res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({message:'模拟会话列表刷新失败'}));return}data=sessions.find(s=>s.id===p.split('/').at(-1))}
    else if(p==='/api/agent/runs')data=runs.filter(r=>!url.searchParams.get('session_id')||r.session_id===url.searchParams.get('session_id'));
    else if(p.endsWith('/cancel')){const run=runs.find(r=>r.id===p.split('/').at(-2));run.stop?.();data=run}
    else if(p.endsWith('/events')){
      const run=runs.find(r=>r.id===p.split('/').at(-2));
      if(run?.pending){run.polls++;if(run.polls===1)data=[{seq:3,event:'delta',data:{text:'恢复后续正文。'}}];else{run.status='completed';run.result={assistant:run.pending};sessions.find(s=>s.id===run.session_id).messages.push(run.pending);delete run.pending;data=[{seq:4,event:'done',data:run.result}]}}
      else data=[{seq:1,event:'plan',data:{steps:[{step:'核对来源',status:'completed'}]}},{seq:2,event:'tool_result',data:{tool:'kb_read',result:{body:'可核对的证据'}}}].filter(e=>e.seq>Number(url.searchParams.get('after')||0));
    }
    else if(p.endsWith('/resume')){const run=runs.find(r=>r.id===p.split('/').at(-2));const message=answer('确认后已在同一会话完成',{run_id:run.id});if(resumeDelayed){run.status='running';run.result=null;run.pending=message;run.polls=0}else{run.status='completed';sessions.find(s=>s.id===run.session_id).messages.push(message);run.result={assistant:message}}data=run}
    else if(p.includes('/agent/runs/'))data=runs.find(r=>r.id===p.split('/').at(-1));
    else if(p.endsWith('/drafts'))data=[{id:draftId,tool:'kb_create_entry',status:approved?draftStatus:'pending',context:{run_id:runs.find(r=>r.status==='waiting_approval')?.id},args:{title:'知识-方法-测试',body:'先检查草稿正文'}}];
    else if(p.includes('/drafts/')){if(confirmFailure){confirmFailure=false;res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({message:'模拟确认失败，草稿仍待处理'}));return}approved=true;draftStatus=p.endsWith('/confirm')?'confirmed':'rejected';if(draftStatus==='confirmed')draftWrites++;data={status:draftStatus}}
    else if(p.endsWith('/skills/install')){installed.push({name:body.name,description:'用户技能',builtin:false});data={ok:true}}
    else if(p.endsWith('/skills/read'))data={content:'---\nname: literature-review\n---\n核对来源与页码'};
    else if(p.endsWith('/skills/resources'))data={files:[{path:'SKILL.md',bytes:80},{path:'references/check.md',bytes:40}],bytes:120,warnings:['脚本执行未开启']};
    else if(p.endsWith('/skills/import')){installed.push({name:'zip-flow',display_name:'导入的技能',description:'来自 ZIP 的工作流程',builtin:false});data={ok:true,name:'zip-flow'}}
    else if(p.endsWith('/skills'))data={skills:[skill,...installed],errors:[]};
    else if(p==='/api/agent/rag')data={settings:ragOptions,index:ragIndex,job:ragJob};
    else if(p==='/api/agent/rag/settings'){const {api_key,clear_api_key,...safe}=body;ragOptions={...ragOptions,...safe,has_api_key:clear_api_key?false:!!api_key||ragOptions.has_api_key};data=ragOptions}
    else if(p==='/api/agent/rag/test')data={ok:true,dimensions:3,model:ragOptions.model};
    else if(p==='/api/agent/rag/index'){ragIndex={generation:'fake-index',chunks:6,sources:2,dimensions:3,model:ragOptions.model,ready:true};ragJob={state:'completed',sources:2,chunks:6,embedded:6,reused:0};data={settings:ragOptions,index:ragIndex,job:ragJob}}
    else if(p==='/api/agent/rag/clear'){if(clearFailure){clearFailure=false;res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({message:'模拟清除失败，原索引保留'}));return}ragIndex={ready:false};ragJob={state:'cleared'};ragOptions={...ragOptions,realtime_updates:false,scheduled_updates:false};data={settings:ragOptions,index:ragIndex,job:ragJob}}
    else if(p==='/api/agent/rag/search')data={mode:ragOptions.mode,count:1,limit:opts.rag_top_k,items:[{id:'adapter',title:'Low rank adaptation',excerpt:'Tune an adapter instead of all parameters.',source:{path:'Knowledge/Notes/adapter.md'}}]};
    else if(p.endsWith('/system'))data={settings:opts,brain:{counts:{memories:memories.length,runs:runs.length,events:2}}};
    else if(p.endsWith('/settings')){if(settingsFailure){settingsFailure=false;res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({message:'模拟设置保存失败'}));return}opts={...opts,...body};data=opts}
    else if(p.endsWith('/mcp/refresh'))data={tools:[],errors:[]};
    else if(p.endsWith('/memory/remember')){data={...body,id:'mem-fixture',source:{type:'user'}};memories.push(data)}
    else if(p.endsWith('/memory/recall'))data={results:memories};
    else if(p.endsWith('/memories')){if(delayMemory)await new Promise(resolve=>setTimeout(resolve,200));data=memories}
    else if(p.endsWith('/memory/forget')){memories.length=0;data={ok:true}}
    else if(p.endsWith('/backup'))data={url:'/backup.sqlite',path:'System/Agent/Backups/brain.sqlite'};
    else if(p==='/api/docs/resolve')data=[citationNote,citationPaper].find(d=>[d.id,d.title].includes(url.searchParams.get('target')));
    else if(p.startsWith('/api/docs/'))data=[citationNote,citationPaper].find(d=>d.id===p.split('/').at(-1));
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
  }
  const file=path.resolve(root,'web','.'+(p==='/'?'/index.html':p));
  if(file.startsWith(path.join(root,'web')+path.sep)&&fs.existsSync(file)){
    const mime={'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.png':'image/png'};
    res.writeHead(200,{'Content-Type':(mime[path.extname(file)]||'application/octet-stream')+'; charset=utf-8'});res.end(fs.readFileSync(file));
  }else{res.writeHead(404);res.end()}
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
  let lastPage;
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),errors=[];page.on('pageerror',e=>errors.push(String(e)));
    lastPage=page;page.setDefaultTimeout(10000);
    await page.goto('http://127.0.0.1:'+server.address().port+'/#agent');
    await page.locator('#agent-chat-panel [data-agent-settings]').waitFor();
    async function agentTab(name){
      await page.locator('#agent-workspace-tabs [data-as-tab]').first().waitFor({state:'attached'});
      if(name==='对话'){if(await page.locator('#agent-system-panel').isVisible())await page.locator('#as-back-chat').click();return}
      if(await page.locator('#agent-chat-panel').isVisible())await page.locator('#agent-chat-panel [data-agent-settings]').click();
      await page.getByRole('tab',{name,exact:true}).click();
    }
    assert.equal(await page.locator('#agent-workspace-tabs').isVisible(),false,'settings navigation is collapsed during chat');
    const chatTop=await page.locator('#agent-chat-panel').boundingBox(),workspaceTop=await page.locator('#agent-workspace').boundingBox();
    assert.ok(Math.abs(chatTop.y-workspaceTop.y)<1,'chat uses the space previously occupied by the tabs');
    await page.locator('#agent-profile-select').waitFor({state:'attached'});
    const headerLayout=async()=>{
      const layout=await page.locator('.agent-chat-head').evaluate(header=>{
        const title=header.querySelector('h3'),actions=header.querySelector('.agent-head-actions'),head=header.getBoundingClientRect(),text=title.getBoundingClientRect(),buttons=actions.getBoundingClientRect();
        return {noOverflow:header.scrollWidth<=header.clientWidth+1,hasRoom:text.width>24&&text.right<=buttons.left,actionsFit:buttons.right<=head.right+1,tooltip:title.title,background:getComputedStyle(header).backgroundColor};
      });
      assert.equal(layout.noOverflow,true);assert.equal(layout.hasRoom,true);assert.equal(layout.actionsFit,true);assert.equal(layout.tooltip,longTitle);assert.equal(layout.background,'rgba(0, 0, 0, 0)');
    };
    await headerLayout();await page.screenshot({path:path.join(output,'chat-header-light.png')});
    await page.setViewportSize({width:390,height:844});await headerLayout();await page.screenshot({path:path.join(output,'chat-header-mobile.png')});
    await page.setViewportSize({width:1440,height:1000});
    await page.getByText('模型选项',{exact:true}).click();await page.locator('#agent-profile-select').waitFor();await page.getByText('模型选项',{exact:true}).click();
    assert.equal(failedListReads,1,'transient connection failure retries safely without a model call');
    await page.locator('#agent-chat-panel [data-agent-capability="rag_enabled"]:enabled').waitFor();
    const mainCaps=page.locator('#agent-chat-panel .agent-capability-controls');assert.equal(await mainCaps.locator('[data-agent-capability]').count(),3);
    const sendBox=await page.locator('#agent-send').boundingBox(),capsBox=await mainCaps.boundingBox();assert.ok(Math.abs((sendBox.y+sendBox.height/2)-(capsBox.y+capsBox.height/2))<4,'capability switches share the send row');
    await mainCaps.locator('[data-agent-capability="memory_enabled"]').click();await page.waitForFunction(()=>document.querySelector('#agent-chat-panel [data-agent-capability="memory_enabled"]').getAttribute('aria-pressed')==='false');assert.equal(opts.memory_enabled,false);assert.equal(opts.rag_enabled,true);
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-input').waitFor();
    assert.equal(await page.locator('#erw-fab-panel [data-agent-capability="memory_enabled"]').getAttribute('aria-pressed'),'false');
    const fabSend=await page.locator('#fab-send').boundingBox(),fabCaps=await page.locator('#erw-fab-panel .agent-capability-controls').boundingBox();assert.ok(Math.abs((fabSend.y+fabSend.height/2)-(fabCaps.y+fabCaps.height/2))<4);
    await page.locator('#erw-fab-panel [data-agent-capability="memory_enabled"]').click();await page.waitForFunction(()=>document.querySelector('#agent-chat-panel [data-agent-capability="memory_enabled"]').getAttribute('aria-pressed')==='true');
    settingsFailure=true;await mainCaps.locator('[data-agent-capability="rag_enabled"]').click();await page.getByText('能力设置未保存：模拟设置保存失败',{exact:true}).waitFor();assert.equal(opts.rag_enabled,true);assert.equal(await mainCaps.locator('[data-agent-capability="rag_enabled"]').getAttribute('aria-pressed'),'true');
    await page.locator('#fab-close').click();
    assert.equal(await page.getByRole('button',{name:'Agent 系统',exact:true}).count(),0);
    assert.equal(await page.locator('.agent-system-overlay').count(),0);
    await page.locator('#agent-input').fill('保留这段输入');
    await agentTab('技能');
    await page.getByRole('checkbox',{name:'启用 literature-review',exact:true}).uncheck();
    await page.getByRole('checkbox',{name:'启用 literature-review',exact:true}).check();
    await agentTab('对话');
    await page.locator('#agent-input').waitFor({state:'visible'});
    assert.equal(await page.locator('#agent-input').inputValue(),'保留这段输入');
    assert.equal(await page.locator('#agent-skill').count(),0,'skills are managed outside the composer');
    await page.locator('#agent-input').fill('核对论文');await page.locator('#agent-send').click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    assert.equal(await page.locator('#agent-messages .agent-error').count(),0);
    assert.match(await page.locator('#agent-messages').innerText(),/已完成带来源的研究总结/);
    assert.equal(await page.locator('[data-agent-session="chat-fixture123"] strong').textContent(),'已更新的研究会话');
    assert.equal(requests.filter(r=>r.path==='/api/agent/send').length,1);
    assert.equal(await page.locator('#agent-profile-select').count(),1,'concurrent enhancement must not duplicate API selectors');
    const sent=requests.find(r=>r.path==='/api/agent/send').body;assert.equal(sent.persona_id,'executor');assert.equal(sent.message,'核对论文');
    await page.screenshot({path:path.join(output,'integrated-chat.png')});
    mode='metadata';await page.locator('#agent-input').fill('测试回复后的列表刷新失败');await page.locator('#agent-send').click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    assert.equal(await page.locator('#agent-messages .agent-error').count(),0);
    assert.equal(await page.locator('#agent-messages .assistant').count(),2);
    await page.getByText('回复已保存，界面刷新失败：模拟会话列表刷新失败',{exact:true}).waitFor();
    mode='draft';await page.locator('#agent-input').fill('生成知识草稿');await page.locator('#agent-send').click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    await agentTab('任务');
    assert.equal(await page.locator('#as-run-form').count(),0,'tasks use the existing chat composer');
    assert.equal(await page.locator('#agent-input').count(),1,'one Agent input across all panels');
    await page.getByText('待确认：kb_create_entry').click();
    assert.equal(await page.getByText('run-other',{exact:true}).count(),0);
    await page.getByRole('button',{name:'确认执行',exact:true}).click();
    await page.getByRole('button',{name:'继续',exact:true}).click();
    await page.locator('.as-run-result>summary').click();await page.locator('.as-answer').getByText('确认后已在同一会话完成',{exact:true}).waitFor();
    await page.screenshot({path:path.join(output,'integrated-tasks.png')});
    await agentTab('对话');
    await page.locator('#agent-messages').getByText('确认后已在同一会话完成',{exact:true}).waitFor();
    await agentTab('记忆');
    await page.locator('#as-memory-session').waitFor();assert.equal(await page.locator('#as-memory-session').inputValue(),'chat-fixture123');
    await page.getByText('添加长期记忆',{exact:true}).click();await page.locator('#as-memory-form textarea').fill('实验统一使用 SCR 指标');
    await page.getByRole('button',{name:'保存记忆',exact:true}).click();await page.getByText('实验统一使用 SCR 指标',{exact:true}).waitFor();
    await page.getByRole('button',{name:'忘记',exact:true}).click();await page.getByText(/没有匹配的记忆/).waitFor();
    await agentTab('技能');await page.locator('.as-skill-tech>summary').click();await page.getByRole('button',{name:'查看指令',exact:true}).click();
    await page.getByText('核对来源与页码',{exact:false}).waitFor();await page.getByText('安装文本技能',{exact:true}).click();
    await page.locator('#as-skill-install input').fill('custom-flow');await page.locator('#as-skill-install textarea').fill('---\nname: custom-flow\ndescription: test\n---\n检查输入');
    await page.getByRole('button',{name:'安装技能',exact:true}).click();await page.locator('[data-enable-skill="custom-flow"]').waitFor();
    await page.locator('[data-skill-card="literature-review"] .as-skill-tech>summary').click();await page.locator('[data-skill-resources="literature-review"]').click();await page.getByRole('button',{name:'references/check.md',exact:true}).click();await page.getByText('脚本执行未开启',{exact:true}).waitFor();
    await page.locator('#as-skill-search').fill('custom-flow');assert.equal(await page.locator('[data-skill-card="literature-review"]').isVisible(),false);await page.locator('#as-skill-search').fill('');
    await page.locator('.as-skill-import>summary').click();await page.locator('#as-skill-zip').setInputFiles({name:'skill.zip',mimeType:'application/zip',buffer:Buffer.from('fake fixture ZIP')});await page.locator('[data-enable-skill="zip-flow"]').waitFor();
    assert.equal(await page.locator('#agent-skill').count(),0);
    delayMemory=true;await agentTab('记忆');await page.locator('#as-memory-session').waitFor();
    const lateMemory=page.waitForResponse(r=>r.url().includes('/api/agent/memories'));await agentTab('技能');await lateMemory;
    await page.locator('.as-skill').filter({hasText:'custom-flow'}).waitFor();assert.equal(await page.locator('#as-memory-results').count(),0);delayMemory=false;
    await agentTab('设置');await page.getByText('高级运行设置',{exact:true}).click();await page.locator('input[name=max_steps]').fill('64');
    await page.getByRole('button',{name:'保存设置',exact:true}).click();await page.getByText('设置已保存',{exact:true}).waitFor();assert.equal(opts.max_steps,64);
    await page.getByRole('button',{name:'刷新 MCP 连接',exact:true}).click();await page.getByRole('button',{name:'备份记忆库',exact:true}).click();await page.getByRole('link',{name:'下载一致性备份'}).waitFor();
    assert.equal(await page.locator('#agent-system-panel').evaluate(panel=>{const bounds=panel.getBoundingClientRect(),back=panel.querySelector('#as-back-chat').getBoundingClientRect(),nav=panel.querySelector('#agent-workspace-tabs').getBoundingClientRect();return back.top>=bounds.top&&nav.bottom<bounds.bottom&&panel.querySelector('.as-content').scrollTop>0}),true,'settings navigation and return button remain reachable while the form scrolls');
    await page.screenshot({path:path.join(output,'integrated-settings.png')});
    await page.locator('#theme-btn').click();await page.screenshot({path:path.join(output,'integrated-dark.png')});
    await agentTab('技能');await page.locator('.as-skill').filter({hasText:'custom-flow'}).waitFor();
    await page.getByRole('tab',{name:'技能',exact:true}).press('Home');assert.equal(await page.getByRole('tab',{name:'任务',exact:true}).getAttribute('aria-selected'),'true');
    await page.getByRole('tab',{name:'任务',exact:true}).press('End');assert.equal(await page.getByRole('tab',{name:'设置',exact:true}).getAttribute('aria-selected'),'true');
    await agentTab('对话');assert.equal(await page.locator('#agent-input').evaluate(el=>document.activeElement===el),true);
    await page.locator('#agent-input').fill('切换会话前保留的草稿');await agentTab('任务');await agentTab('对话');assert.equal(await page.locator('#agent-input').inputValue(),'切换会话前保留的草稿');
    mode='error';await page.locator('#agent-input').fill('验证真实模型失败');await page.locator('#agent-send').click();await page.locator('.agent-error').getByText('请求失败：模拟模型接口失败',{exact:true}).waitFor();
    await page.locator('[data-agent-session="chat-other123"]').click();await agentTab('任务');await page.locator('[data-as-run="run-other"]').waitFor();
    assert.equal(await page.locator('.as-run').count(),1);
    await agentTab('对话');mode='multi';
    await page.locator('#agent-input').fill('展示全部分析过程');await page.locator('#agent-send').click();
    await page.locator('#agent-thinking .agent-response-part').filter({hasText:'第二轮比较'}).waitFor();
    assert.equal(await page.locator('#agent-thinking .agent-response-part').count(),2);
    assert.match(await page.locator('#agent-thinking').innerText(),/第一轮分析/);
    assert.equal(await page.locator('#agent-thinking table').count(),1);
    const beforeOpenReads=requests.filter(r=>r.path==='/api/agent/sessions/chat-other123').length;
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-messages .fab-msg:last-child .agent-response-part').nth(1).waitFor();
    assert.match(await page.locator('#fab-messages .fab-msg:last-child').innerText(),/第一轮分析/);
    assert.equal(requests.filter(r=>r.path==='/api/agent/sessions/chat-other123').length,beforeOpenReads,'opening the second view while streaming uses live shared state');
    await page.locator('#fab-close').click();
    releaseStream();await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    assert.equal(await page.locator('#agent-messages .agent-response-part').count(),2);
    assert.match(await page.locator('#agent-messages').innerText(),/任务已完成/);
    await agentTab('任务');await page.locator('[data-as-run="'+runs[0].id+'"]').click();
    await page.locator('.as-run-result>summary').click();await page.locator('.as-answer .agent-response-part').nth(1).waitFor();assert.match(await page.locator('.as-answer').innerText(),/第一轮分析/);
    await agentTab('对话');
    await page.reload();await page.locator('#agent-input').waitFor();
    await page.locator('[data-agent-session="chat-other123"]').click();
    await page.locator('#agent-messages .agent-response-part').nth(1).waitFor();
    assert.match(await page.locator('#agent-messages').innerText(),/第一轮分析/);
    await page.screenshot({path:path.join(output,'intermediate-main.png')});
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-input').waitFor();
    await page.locator('#fab-input').fill('悬浮助手保留过程');await page.locator('#fab-send').click();
    await page.locator('#fab-messages .fab-msg:last-child .agent-response-part').nth(1).waitFor();
    assert.match(await page.locator('#fab-messages .fab-msg:last-child').innerText(),/第一轮分析/);
    await page.locator('#agent-thinking .agent-response-part').nth(1).waitFor();assert.match(await page.locator('#agent-thinking').innerText(),/第二轮比较/);
    releaseStream();await page.waitForFunction(()=>document.querySelector('#fab-send').textContent==='发送');
    assert.equal(await page.locator('#fab-messages .fab-msg:last-child .agent-response-part').count(),2);
    await page.screenshot({path:path.join(output,'intermediate-floating.png')});
    mode='partial';await page.locator('#fab-input').fill('中途失败保留结果');await page.locator('#fab-send').click();
    await page.locator('#fab-messages').getByText('请求失败：模拟中途连接失败',{exact:true}).waitFor();
    assert.equal(await page.locator('#fab-messages .agent-response-part').count(),6,'shared history and partial answers are retained');
    await page.locator('#fab-close').click();
    const partialErrorCount=await page.locator('#agent-messages .agent-error').count();
    const partialSendCount=requests.filter(r=>r.path==='/api/agent/send').length;
    await page.locator('#agent-input').fill('主页面中断保留结果');await page.locator('#agent-send').click();
    await page.waitForFunction(before=>{
      const client=window.ERWAgentClient,id=client.sessionId(),messages=client.snapshot(id).session.messages;
      const sent=messages.findLastIndex(m=>m.role==='user'&&m.content==='主页面中断保留结果');
      return sent>=0&&!client.busy(id)&&messages.slice(sent+1).some(m=>m.error)&&document.querySelectorAll('#agent-messages .agent-error').length===before+1;
    },partialErrorCount);
    assert.equal(requests.filter(r=>r.path==='/api/agent/send').length,partialSendCount+1);
    assert.equal(requests.filter(r=>r.path==='/api/agent/send').at(-1).body.message,'主页面中断保留结果');
    await page.locator('#agent-messages .agent-message:last-child .agent-error').getByText('请求失败：模拟中途连接失败',{exact:true}).waitFor();
    assert.equal(await page.locator('#agent-messages .agent-response-part').count(),8);
    const offline=await browser.newPage({viewport:{width:1440,height:1000}});offline.setDefaultTimeout(10000);let offlineReads=3;
    await offline.route('**/api/agent/sessions',route=>offlineReads-->0?route.abort('failed'):route.continue());
    await offline.goto('http://127.0.0.1:'+server.address().port+'/#agent');
    await offline.locator('#agent-sessions-retry').waitFor();await offline.locator('#agent-input').fill('连接恢复时保留草稿');
    assert.match(await offline.locator('#agent-sessions-status').innerText(),/无法连接本地 Agent 服务/);
    await offline.locator('#agent-sessions-retry').click();await offline.locator('[data-agent-session="chat-fixture123"]').waitFor();
    assert.equal(await offline.locator('#agent-input').inputValue(),'连接恢复时保留草稿');assert.equal(await offline.locator('#agent-sessions-retry').count(),0);await offline.close();
    for(const recoveryMode of ['eof','replay','crlf']){
      mode=recoveryMode;const before=requests.filter(r=>r.path==='/api/agent/send').length;
      await page.locator('#agent-input').fill('传输恢复 '+recoveryMode);await page.locator('#agent-send').click();
      await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
      assert.match(await page.locator('#agent-messages .agent-message:last-child').innerText(),/已完成带来源的研究总结/);
      assert.equal(requests.filter(r=>r.path==='/api/agent/send').length,before+1,'transport recovery must not resubmit the task');
      assert.equal(await page.locator('#agent-messages .agent-message:last-child .agent-error').count(),0);
    }
    mode='draft';approved=false;draftId='draft-main-inline';confirmFailure=true;
    await page.locator('#agent-input').fill('主聊天直接确认草稿');await page.locator('#agent-send').click();await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    await page.locator('#agent-messages [data-draft-preview="'+draftId+'"]').click();await page.locator('#agent-messages .agent-draft-preview').getByText(/先检查草稿正文/).waitFor();
    const writesBefore=draftWrites;await page.locator('#agent-messages [data-draft-confirm="'+draftId+'"]').click();
    await page.getByText('模拟确认失败，草稿仍待处理',{exact:true}).waitFor();assert.equal(draftWrites,writesBefore);
    await page.locator('#agent-messages [data-draft-confirm="'+draftId+'"]').click();
    assert.equal(draftWrites,writesBefore+1);await page.locator('#erw-fab-ball').click();
    assert.equal(await page.locator('#fab-messages [data-draft-confirm="'+draftId+'"]').count(),0,'approval is shared with the floating view');await page.locator('#fab-close').click();
    resumeDelayed=true;await page.locator('#agent-messages [data-agent-resume]').last().click();
    await page.locator('#agent-messages .agent-message:last-child').getByText('确认后已在同一会话完成',{exact:true}).waitFor();
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-messages').getByText('确认后已在同一会话完成',{exact:true}).waitFor();
    mode='eof';await page.locator('#fab-input').fill('悬浮助手断线恢复');await page.locator('#fab-send').click();await page.waitForFunction(()=>document.querySelector('#fab-send').textContent==='发送');
    assert.match(await page.locator('#fab-messages .fab-msg:last-child').innerText(),/已完成带来源的研究总结/);
    assert.match(await page.locator('#agent-messages .agent-message:last-child').innerText(),/已完成带来源的研究总结/);
    await page.locator('#agent-input').fill('切换会话仍保留输入');await page.locator('#fab-history').click();await page.locator('[data-hist="chat-fixture123"]').click();
    await page.locator('[data-agent-session="chat-fixture123"].active').waitFor();assert.equal(await page.locator('#agent-input').inputValue(),'切换会话仍保留输入');
    await page.locator('#fab-close').click();
    mode='multi';await page.locator('#erw-fab-ball').click();await page.locator('#fab-input').fill('后台原会话的任务');await page.locator('#fab-send').click();
    await page.locator('#fab-messages .fab-msg:last-child .agent-response-part').nth(1).waitFor();await page.locator('#fab-close').click();
    await page.locator('[data-agent-session="chat-other123"]').click();await page.locator('[data-agent-session="chat-other123"].active').waitFor();
    releaseStream();await page.waitForFunction(()=>!window.ERWAgentClient.busy('chat-fixture123'));
    assert.equal(await page.locator('#agent-messages').getByText('后台原会话的任务',{exact:true}).count(),0,'late completion cannot move an answer to a different session');
    await page.locator('#erw-fab-ball').click();assert.equal(await page.locator('#fab-messages').getByText('后台原会话的任务',{exact:true}).count(),0);await page.locator('#fab-close').click();
    // Dragging across reply paragraphs offers quote and stays in the main conversation.
    async function selectReply(view){
      if(view==='#fab-messages')await page.waitForFunction(()=>document.activeElement===document.querySelector('#fab-input'));
      const reply=page.locator(view+' .agent-response-body').first();await reply.scrollIntoViewIfNeeded();
      await reply.evaluate(el=>{const article=el.closest('article'),parts=article.querySelectorAll('.agent-response-body'),range=document.createRange();range.setStart(parts[0],0);range.setEnd(parts[parts.length-1],parts[parts.length-1].childNodes.length);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);el.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))});
      await page.locator('#erw-sel-bubble.show').waitFor();
    }
    await page.locator('#agent-input').fill('针对引用继续追问');await selectReply('#agent-messages');
    await page.locator('[data-fab-act="quote"]').click();assert.equal(await page.locator('#agent-context-strip .agent-quote-chip').count(),1);assert.equal(await page.locator('#agent-input').inputValue(),'针对引用继续追问');assert.equal(await page.locator('#erw-fab-panel').isVisible(),false);
    await selectReply('#agent-messages');await page.locator('[data-fab-act="ask"]').click();assert.equal(await page.locator('#agent-context-strip .agent-quote-chip').count(),2);assert.equal(await page.locator('#erw-fab-panel').isVisible(),false);
    mode='normal';await page.locator('#agent-send').click();await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    assert.match(requests.filter(r=>r.path==='/api/agent/send').at(-1).body.context.quote_text,/第一轮分析/);assert.match(requests.filter(r=>r.path==='/api/agent/send').at(-1).body.context.quote_text,/第二轮比较/);assert.equal(await page.locator('#agent-context-strip .agent-quote-chip').count(),0);assert.ok(await page.locator('#agent-messages .agent-sent-quote').count()>0);
    await page.locator('#erw-fab-ball').click();await selectReply('#fab-messages');await page.locator('[data-fab-act="quote"]').click();assert.match(await page.locator('#fab-quote').innerText(),/回复选段/);await page.locator('#fab-quote-x').click();await page.locator('#fab-close').click();
    await agentTab('RAG');await page.locator('#as-rag-settings').waitFor();if(await page.locator('#as-rag-connection').getAttribute('open')===null)await page.locator('#as-rag-connection>summary').click();
    await page.locator('#as-rag-settings input[name=rag_enabled]').uncheck();await page.locator('#as-rag-settings input[name=rag_top_k]').fill('4');
    await page.getByRole('button',{name:'保存 RAG 设置',exact:true}).click();await page.getByText('RAG 设置已保存',{exact:true}).waitFor();assert.equal(opts.rag_enabled,false);assert.equal(opts.rag_top_k,4);
    await agentTab('技能');await page.locator('#as-skills-enabled').uncheck();await page.locator('[data-enable-skill="literature-review"]').waitFor();
    await page.waitForFunction(()=>document.querySelector('[data-enable-skill="literature-review"]')?.disabled===true);
    assert.equal(await page.locator('[data-enable-skill="literature-review"]').isDisabled(),true);assert.equal(opts.skills_enabled,false);
    await page.screenshot({path:path.join(output,'skills-managed.png')});
    await page.locator('[data-route="settings"]').click();await page.locator('[data-set-tab="ai"]').click();await page.locator('[data-capability="skills_enabled"]').waitFor();
    assert.equal(await page.locator('[data-capability="skills_enabled"]').isChecked(),false);assert.equal(await page.locator('[data-capability="rag_enabled"]').isChecked(),false);
    await page.locator('[data-capability="skills_enabled"]').check();await page.locator('[data-capability="rag_enabled"]').check();
    await page.getByText('已保存，后续工具调用立即生效',{exact:true}).waitFor();assert.equal(opts.skills_enabled,true);assert.equal(opts.rag_enabled,true);
    await page.getByRole('button',{name:'配置 RAG',exact:true}).click();await page.locator('#as-rag-settings').waitFor();if(await page.locator('#as-rag-connection').getAttribute('open')===null)await page.locator('#as-rag-connection>summary').click();assert.equal(await page.locator('#as-rag-settings input[name=rag_top_k]').inputValue(),'4');
    await page.locator('#as-rag-settings [name=rag_top_k]').fill('12');await page.locator('#as-rag-settings [name=mode]').selectOption('hybrid');await page.locator('#as-rag-settings [name=base_url]').fill('http://127.0.0.1:12345/v1');await page.locator('#as-rag-settings [name=model]').fill('fake-embedding');await page.locator('#as-rag-settings [name=api_key]').fill('fake-private-key');
    await page.locator('#as-rag-test').click();await page.getByText('连接成功 · fake-embedding · 3 维',{exact:true}).waitFor();assert.equal(await page.locator('#as-rag-settings [name=api_key]').inputValue(),'');assert.equal(ragOptions.has_api_key,true);
    await page.locator('#as-rag-build').click();await page.locator('#as-rag-index').getByText(/资料向量索引：6 个分块/).waitFor();assert.equal(await page.locator('#as-rag-cancel').isVisible(),false);await page.locator('#as-rag-search [name=query]').fill('省参数的方法');await page.getByRole('button',{name:'检索资料',exact:true}).click();await page.locator('#as-rag-results').getByText('Low rank adaptation',{exact:true}).waitFor();
    assert.equal(opts.rag_top_k,12);await page.locator('#as-rag-results').getByText(/实际 1 条 \/ 最多 12 条/).waitFor();
    await page.locator('[data-route="settings"]').click();await page.locator('[data-set-tab="rag"]').click();await page.locator('#as-rag-connection>summary').click();await page.locator('#as-rag-settings [name=model]').waitFor();assert.equal(await page.locator('#as-rag-settings [name=model]').inputValue(),'fake-embedding');await page.getByRole('button',{name:'保存 RAG 设置',exact:true}).click();await page.getByText('RAG 设置已保存',{exact:true}).waitFor();assert.equal(ragOptions.has_api_key,true,'blank password preserves the saved key');
    await page.getByText('自动更新',{exact:true}).click();await page.locator('[name=realtime_updates]').check();await page.locator('[name=scheduled_updates]').check();await page.locator('[name=update_interval_minutes]').fill('30');await page.getByRole('button',{name:'保存 RAG 设置',exact:true}).click();await page.getByText('RAG 设置已保存',{exact:true}).waitFor();assert.equal(ragOptions.realtime_updates,true);assert.equal(ragOptions.scheduled_updates,true);assert.equal(ragOptions.update_interval_minutes,30);
    const clearRequests=()=>requests.filter(r=>r.path==='/api/agent/rag/clear').length,clearBefore=clearRequests();
    await page.getByText('清除向量数据库',{exact:true}).click();await page.locator('#as-rag-clear').click();
    await page.getByRole('alertdialog',{name:'清除向量数据库？'}).waitFor();
    await page.locator('#workbench-dialog-message').getByText(/2 份来源、6 个分块/).waitFor();
    assert.equal(await page.locator('#workbench-dialog [data-dialog-result=cancel]').evaluate(e=>e===document.activeElement),true,'cancellation is the default focused action');
    assert.equal(clearRequests(),clearBefore,'opening confirmation must not clear data');
    await page.locator('#workbench-dialog [data-dialog-result=cancel]').click();assert.equal(ragIndex.ready,true);assert.equal(ragOptions.realtime_updates,true);
    assert.equal(await page.locator('#as-rag-clear').evaluate(e=>e===document.activeElement),true,'cancel restores focus to the trigger');
    await page.locator('#as-rag-clear:enabled').click();await page.getByRole('alertdialog').waitFor();await page.keyboard.press('Escape');
    await page.locator('#as-rag-clear:enabled').click();await page.getByRole('alertdialog').waitFor();await page.locator('#workbench-dialog-backdrop').click({position:{x:2,y:2}});assert.equal(clearRequests(),clearBefore,'Escape and backdrop also cancel without writes');
    clearFailure=true;await page.locator('#as-rag-clear:enabled').click();await page.locator('#workbench-dialog [data-dialog-result=confirm]').click();
    await page.locator('#as-rag-status').getByText('模拟清除失败，原索引保留',{exact:true}).waitFor();assert.equal(ragIndex.ready,true);assert.equal(ragOptions.scheduled_updates,true);
    await page.locator('#as-rag-clear:enabled').click();await page.screenshot({path:path.join(output,'rag-clear-confirm-dark.png')});await page.locator('#workbench-dialog [data-dialog-result=confirm]').click();
    await page.getByText('向量数据库已清除，原始资料和长期记忆已保留，自动更新已关闭',{exact:true}).waitFor();assert.equal(clearRequests(),clearBefore+2);assert.equal(ragIndex.ready,false);assert.equal(ragOptions.realtime_updates,false);assert.equal(ragOptions.scheduled_updates,false);assert.equal(await page.locator('[name=realtime_updates]').isChecked(),false);
    await page.locator('[data-route="agent"]').click();await agentTab('对话');await page.locator('#agent-chat-panel [data-agent-settings]').click();await page.locator('#as-capabilities [data-capability]').first().waitFor();assert.equal(await page.getByRole('tab',{name:'设置',exact:true}).getAttribute('aria-selected'),'true');await agentTab('RAG');await page.locator('#as-rag-settings').waitFor();if(await page.locator('#as-rag-connection').getAttribute('open')===null)await page.locator('#as-rag-connection>summary').click();
    await page.screenshot({path:path.join(output,'rag-settings.png')});
    await page.setViewportSize({width:390,height:844});await agentTab('技能');await page.locator('.as-skill').filter({hasText:'custom-flow'}).waitFor();
    assert.ok(await page.locator('#agent-system-panel').evaluate(e=>e.scrollWidth<=e.clientWidth+1));await page.screenshot({path:path.join(output,'integrated-mobile.png'),fullPage:true});
    await agentTab('对话');await page.locator('#agent-input').waitFor();
    assert.equal(await page.locator('.agent-sessions').isVisible(),false);
    await page.locator('#agent-input').fill('窄屏抽屉操作保留草稿');
    await page.locator('#agent-session-drawer').click();assert.equal(await page.locator('.agent-sessions').isVisible(),true);
    await page.locator('#agent-session-drawer').click();assert.equal(await page.locator('.agent-sessions').isVisible(),false);
    assert.equal(await page.locator('#agent-input').inputValue(),'窄屏抽屉操作保留草稿');
    const mobileSend=await page.locator('#agent-send').boundingBox(),mobileCaps=await page.locator('#agent-chat-panel .agent-capability-controls').boundingBox();assert.ok(Math.abs((mobileSend.y+mobileSend.height/2)-(mobileCaps.y+mobileCaps.height/2))<4);assert.ok(await page.locator('#agent-chat-panel').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    assert.ok(mobileSend.y+mobileSend.height<=844,'sending stays within the mobile viewport');
    await page.screenshot({path:path.join(output,'mobile-composer.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    if(await page.locator('#fab-close').isVisible())await page.locator('#fab-close').click();
    mode='rag-evidence';await page.locator('#agent-input').fill('检索供电恢复，只参考RAG');await page.locator('#agent-send').click();
    await page.locator('#agent-thinking .agent-retrieval-warning').getByText(/模拟 Embedding 超时/).waitFor();
    await page.locator('#agent-thinking .agent-capability-stamp').getByText(/Skill 关闭/).waitFor();
    await page.locator('#agent-thinking .agent-retrievals>summary').click();await page.locator('#agent-thinking .agent-retrieval-query>summary').click();
    await page.locator('#agent-thinking .agent-retrieval-source blockquote').getByText('实际传给模型的来源片段 <script>不执行</script>',{exact:true}).waitFor();
    releaseStream();await page.locator('#agent-thinking .agent-message-body').getByText('正在按来源整理',{exact:true}).waitFor();assert.equal(await page.locator('#agent-thinking .agent-retrievals').getAttribute('open'),'');
    releaseStream();await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-messages .assistant').last().locator('.agent-retrieval-source').getByText(citationNote.title,{exact:true}).waitFor();await page.locator('#fab-close').click();
    await page.reload();await page.locator('#agent-messages .assistant').last().locator('.agent-retrievals>summary').getByText(/RAG 检索依据/).waitFor();
    const assertRetrievalFooter=async selector=>{
      const result=await page.locator(selector).evaluate(root=>{
        const message=[...root.querySelectorAll('.assistant')].at(-1),body=message.querySelector('.agent-message-body,.fab-body'),cards=message.querySelectorAll('.agent-retrievals');
        const card=cards[0],summary=card.querySelector(':scope > summary'),viewport=root.getBoundingClientRect(),bounds=summary.getBoundingClientRect();
        return {count:cards.length,afterAnswer:!!(body.compareDocumentPosition(card)&Node.DOCUMENT_POSITION_FOLLOWING),visible:bounds.top>=viewport.top&&bounds.bottom<=viewport.bottom};
      });
      assert.deepEqual(result,{count:1,afterAnswer:true,visible:true},'retrieval evidence is visible below a long answer without scrolling back to its beginning');
    };
    await assertRetrievalFooter('#agent-messages');
    await page.screenshot({path:path.join(output,'rag-evidence.png')});
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-messages .assistant').last().locator('.agent-retrievals>summary').waitFor();
    await assertRetrievalFooter('#fab-messages');await page.locator('#fab-close').click();
    mode='citation';await page.locator('#agent-input').fill('验证引用跳转');await page.locator('#agent-send').click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    let reply=page.locator('#agent-messages .assistant').last();
    assert.equal(await reply.locator('[data-agent-reference]').count(),2,'wiki links become clickable, inline code stays literal');
    await hoverContrast('#agent-messages .assistant:last-child tbody td');await reply.locator('.agent-skills-used summary').click();await reply.getByText('证据核查 · 任务匹配',{exact:true}).waitFor();
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-messages .assistant').last().locator('tbody td').last().waitFor();await hoverContrast('#fab-messages .assistant:last-child tbody td');await page.locator('#fab-close').click();
    await reply.getByRole('link',{name:citationNote.title,exact:true}).click({modifiers:['Control']});
    await page.waitForFunction(()=>window.ERWCurrentDoc==='note-citation');
    await page.locator('#md-input').waitFor({state:'attached'});assert.match(await page.locator('#md-input').inputValue(),/无环还需要结合连通性/);
    async function hoverContrast(selector){
      const cell=page.locator(selector).last();await cell.waitFor();await cell.hover();
      const colors=await cell.evaluate(el=>{const style=getComputedStyle(el);return {fg:style.color,bg:style.backgroundColor}});
      const luminance=color=>{const rgb=color.match(/[\d.]+/g).slice(0,3).map(v=>Number(v)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return .2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2]};
      const a=luminance(colors.fg),b=luminance(colors.bg);assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,'hover text contrast '+JSON.stringify(colors));
    }
    await hoverContrast('.md-preview tbody td');await page.screenshot({path:path.join(output,'dark-table-hover.png')});
    await page.locator('#theme-btn').click();await page.locator('#theme-btn').click();await hoverContrast('.md-preview tbody td');
    await page.locator('[data-route="agent"]').click();await page.locator('#agent-input').waitFor();
    await page.evaluate(()=>{window.__openedCitationPdf='';window.ERWLiterature.openByDocument=async id=>{window.__openedCitationPdf=id}});
    await page.locator('#agent-messages .assistant').last().getByRole('link',{name:'组会原文',exact:true}).click({modifiers:['Control']});
    await page.waitForFunction(()=>window.__openedCitationPdf==='literature-citation');
    assert.equal(await page.locator('#doc-list [data-doc-id="literature-citation"]').count(),0,'citation opens a PDF even when absent from the filtered list page');
    await page.locator('[data-route="agent"]').click();await page.locator('#agent-input').waitFor();
    const originalId=await page.locator('#agent-messages .user').last().getAttribute('data-message-id');
    const originalQuestion=await page.locator('#agent-messages .user').last().locator('.agent-message-body').innerText();
    const userBox=await page.locator('#agent-messages .user').last().locator('.agent-bubble').boundingBox(),aiBox=await page.locator('#agent-messages .assistant').last().locator('.agent-bubble').boundingBox();
    assert.ok(userBox.x>aiBox.x+100,'user question on right, assistant answer on left');
    await page.locator('#agent-input').fill('尚未发送的草稿');await page.locator('#agent-messages .user').last().getByRole('button',{name:'编辑重发',exact:true}).click();
    assert.equal(await page.locator('#agent-input').inputValue(),originalQuestion);
    await page.getByRole('button',{name:'取消编辑',exact:true}).click();assert.equal(await page.locator('#agent-input').inputValue(),'尚未发送的草稿');
    await page.locator('#agent-messages .user').last().getByRole('button',{name:'编辑重发',exact:true}).click();
    await page.locator('#agent-input').fill('修订后的检索问题');mode='normal';await page.getByRole('button',{name:'重新发送',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    const resent=requests.filter(r=>r.path==='/api/agent/send').at(-1).body;
    assert.equal(resent.context.edited_from,originalId);
    assert.equal(await page.locator(`[data-message-id="${originalId}"] .agent-message-body`).innerText(),originalQuestion);
    assert.equal(await page.locator('#agent-messages .user').last().locator('.agent-message-body').innerText(),'修订后的检索问题');
    await page.locator('#agent-messages .user').last().getByRole('button',{name:'由历史提问编辑重发 · 查看原提问',exact:true}).click();
    assert.equal(await page.evaluate(()=>document.activeElement.dataset.messageId),originalId);
    const beforeStops=requests.filter(r=>r.path.endsWith('/cancel')).length;
    mode='hold';await page.locator('#agent-input').fill('生成中从另一界面停止');await page.locator('#agent-send').click();
    await page.locator('#agent-thinking').getByText('已生成的部分回答',{exact:true}).waitFor();
    await page.locator('#erw-fab-ball').click();await page.locator('#fab-send').getByText('停止',{exact:true}).waitFor();await page.locator('#fab-send').click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    await page.locator('#agent-messages .assistant').last().getByText('已停止生成，已生成内容和原有提问已保留。',{exact:true}).waitFor();
    await page.locator('#fab-messages').getByText('已停止生成，已生成内容和原有提问已保留。',{exact:true}).waitFor();
    assert.equal(requests.filter(r=>r.path.endsWith('/cancel')).length,beforeStops+1);
    await page.locator('#fab-close').click();
    mode='delayed-hold';await page.locator('#agent-input').fill('收到任务编号前也可以停止');await page.locator('#agent-send').click();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='停止');await page.locator('#agent-send').click();
    while(!releaseStream)await new Promise(resolve=>setTimeout(resolve,10));releaseStream();
    await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');
    assert.equal(requests.filter(r=>r.path.endsWith('/cancel')).length,beforeStops+2,'early stop waits for run ID then cancels exactly once');
    await page.reload();await page.locator('#agent-messages .user').filter({hasText:'修订后的检索问题'}).waitFor();
    assert.equal(await page.locator(`[data-message-id="${originalId}"] .agent-message-body`).innerText(),originalQuestion);
    await page.locator('#agent-messages .assistant').last().getByText('已停止生成，已生成内容和原有提问已保留。',{exact:true}).waitFor();
    const originalSession=await page.evaluate(()=>window.ERWAgentClient.sessionId());
    const otherSession=sessions.find(session=>session.id!==originalSession).id;
    mode='hold';await page.locator('#erw-fab-ball').click();await page.locator('#fab-input').fill('旧会话的并行任务');await page.locator('#fab-send').click();
    await page.locator('#fab-messages .fab-msg').last().getByText('已生成的部分回答',{exact:true}).waitFor();await page.locator('#fab-close').click();
    await page.locator(`[data-agent-session="${otherSession}"]`).click();await page.locator('#agent-input').fill('当前会话的并行任务');await page.locator('#agent-send').click();
    await page.locator('#agent-thinking').getByText('已生成的部分回答',{exact:true}).waitFor();
    await page.evaluate(id=>window.ERWAgentClient.stop(id),originalSession);
    await page.waitForFunction(id=>!window.ERWAgentClient.busy(id),originalSession);
    await page.locator('#erw-fab-ball').click();assert.equal(await page.locator('#fab-send').textContent(),'停止');assert.equal(await page.locator('#fab-send').isEnabled(),true,'finishing another session must not disable cancellation of the current run');
    await page.locator('#fab-send').click();await page.waitForFunction(()=>document.querySelector('#agent-send').textContent==='发送');await page.locator('#fab-close').click();
    await page.locator(`[data-agent-session="${originalSession}"]`).click();
    await page.screenshot({path:path.join(output,'citations-edit-stop-desktop.png')});
    await page.setViewportSize({width:390,height:844});assert.ok(await page.locator('#agent-chat-panel').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    await page.screenshot({path:path.join(output,'citations-edit-stop-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);console.log('Integrated Agent UI passed: citation links/PDF outside list page, left/right messages, edit resend preserving originals, cancel from either view/before run ID, partial output after reload; EOF recovery, drafts, sync, capabilities, Embedding settings, selection quotes, themes/mobile. No model API calls.');
  }catch(error){if(lastPage){console.error('Selection state:',await lastPage.evaluate(()=>({selection:getSelection()?.toString(),anchor:getSelection()?.anchorNode?.parentElement?.outerHTML?.slice(0,300),bubble:document.querySelector('#erw-sel-bubble')?.outerHTML?.slice(0,300)})));console.error('UI failure state:',(await lastPage.locator('#fab-messages').innerText()).slice(-1500));await lastPage.screenshot({path:path.join(output,'failure.png')})}throw error}
  finally{releaseStream?.();await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve))}
})().catch(e=>{console.error(e);process.exitCode=1;server.close()});
