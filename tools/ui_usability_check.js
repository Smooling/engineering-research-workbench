/* Run against a local server with Playwright available in NODE_PATH.
 * All task/document writes are intercepted; the user's workspace is never edited.
 * node tools/ui_usability_check.js (starts its own static fixture server)
 * --pdf-quality-only tests chips/DPR/cache; add --pdf-fixture=path.pdf --pdf-page=7
 * for read-only verification with the same PDF.js version used by the app.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require('playwright');
const output = path.resolve('.scratch/verify/usability');
fs.mkdirSync(output, {recursive:true});

(async()=>{
  const webRoot=path.resolve('web');
  const server=http.createServer((req,res)=>{
    const pathname=new URL(req.url,'http://localhost').pathname;
    const file=path.resolve(webRoot,'.'+(pathname==='/'?'/index.html':pathname));
    if(!file.startsWith(webRoot+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end()}
    const mime={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'};
    res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=process.argv.slice(2).find(value=>/^https?:/.test(value))||`http://127.0.0.1:${server.address().port}`;
  const readingOnly=process.argv.includes('--reading-only');
  const overviewOnly=process.argv.includes('--overview-only');
  const pdfQualityOnly=process.argv.includes('--pdf-quality-only');
  const referencesOnly=process.argv.includes('--references-only');
  const planningOnly=process.argv.includes('--planning-only');
  const literatureOnly=process.argv.includes('--literature-only');
  let browser;
  try{
    browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
    const page=await browser.newPage({viewport:{width:1600,height:1000},reducedMotion:'reduce'});
    const errors=[];
    const libraryRequests=[],graphRequests=[];
    page.on('request',request=>{
      const url=new URL(request.url());
      if(/\/(mathjax-tex-svg|mermaid\.min)/.test(url.pathname))libraryRequests.push(url.pathname);
      if(url.pathname==='/api/graph')graphRequests.push(url.href);
    });
    page.on('pageerror',e=>errors.push(e.message));
    page.on('dialog',dialog=>{errors.push('Unexpected browser dialog: '+dialog.type());dialog.dismiss()});
    const date='2026-10-15';
    let todos=[{id:'ui-todo',title:'核对实验结果',project:'示例项目',due:date,priority:'普通',done:false},...['整理论文实验','复核对照结果'].map((title,i)=>({id:'ui-extra-'+i,title,project:'示例项目',due:date,priority:'普通',done:false}))];
    todos.push({id:'ui-urgent',title:'今天的紧急事项',due:date,priority:'紧急',done:false},
      {id:'ui-next',title:'明天的事项',due:'2026-10-16',priority:'普通',done:false},
      {id:'ui-yesterday',title:'昨天未完成的事项',due:'2026-10-14',priority:'低',done:false},
      {id:'ui-old',title:'较早的事项',due:'2026-08-04',priority:'高',done:false},
      {id:'ui-no-date',title:'未设置日期',due:'',priority:'紧急',done:false},
      {id:'ui-done',title:'保留的已完成事项',due:'2020-01-01',priority:'普通',done:true});
    let writes=0,docWrites=0,draftReads=0,failSave=false,failWrite=false,failDocId='',failTodoId='',cleanupCalls=0,failBootstrapOnce=false,bootstrapFailures=0,graphGate=null;
    const deletedDocs=new Set();
    const doc=(kind,id,title)=>({id,kind,title,status:kind==='milestone'?'进行中':'记录',due:date,record_date:date,created:date,updated:date,project:'示例项目',projects:['示例项目'],tags:[],kind_marks:['knowledge','method'],body:'# '+title+'\n\n用于验证文档直达。',path:'Knowledge/'+id+'.md'});
    const milestone=doc('milestone','ui-milestone','打开这一份里程碑文档');
    const journal=doc('journal','ui-journal','有两种分类的实验记录');
    const milestoneRows=Array.from({length:14},(_,i)=>{
      const day=String(i+8).padStart(2,'0');
      return day==='15'?milestone:{...doc('milestone','ui-ms-'+day,'研究节点 '+day),due:'2026-10-'+day,status:['完成','进行中','计划','受阻'][i%4]};
    });
    const longTitle='研究内容标题需要允许换行并且最多显示两行，在更长的情况下才显示省略号，避免标题在第一行就被截断';
    const otherJournals=[journal,doc('journal','ui-journal-2','另一份实验记录'),doc('journal','ui-journal-3','第三份实验记录')];
    const recentDocs=['idea','note','summary'].flatMap(kind=>Array.from({length:5},(_,i)=>({...doc(kind,'ui-recent-'+kind+i,({idea:'灵感',note:'笔记',summary:'工作总结'}[kind])+'·'+longTitle+' '+i),project:['模型推理优化','联邦学习系统','科研工作台性能测试'][i%3],status:({idea:['探索中','已采纳','已归档','待整理','探索中'],note:['稳定','整理中','草稿','已归档','稳定'],summary:['已定稿','草稿','已归档','已定稿','草稿']}[kind])[i]})));
    const literatureEditor={...doc('literature','ui-lit-editor','完整元数据的文献'),authors:'Research Team',year:'2026',venue:'Research Conference',doi:'10.0000/test',url:'https://example.invalid/paper',cite_key:'qa_paper',bibtex:'@article{qa_paper,\n'+Array.from({length:12},(_,i)=>`  field${i} = {value},`).join('\n')+'\n}'};
    const docRecords=[...milestoneRows,...otherJournals,...recentDocs,literatureEditor];
    const paper={...literatureEditor,doc_id:literatureEditor.id,pdf_available:true,id:'ui-paper',title:'Dark workspace readability',authors:'Research Team',year:2026,reading_status:'在读',kind_marks:['knowledge','method'],tags:[],stored_filename:'ui-paper.pdf',last_page:1};
    const agentSession={id:'ui-agent-session',title:'实验设计与结果分析',updated:date,message_count:2,messages:[
      {role:'user',content:'请分析这组实验结果，检查 **可复现性**。',created:date},
      {role:'assistant',content:'## 分析建议\n\n先对照基线，再检查实验参数。\n\n`seed = 42`\n\n| 指标 | 结果 |\n| --- | --- |\n| 准确率 | 93% |',reasoning:'核对数据和参数，再比较结果。',created:date},
    ]};
    const days=Array.from({length:14},(_,i)=>({date:`2026-10-${String(i+2).padStart(2,'0')}`,count:i%4,breakdown:{todo_done:i===13?2:0}}));
    const projectStats=Array.from({length:6},(_,i)=>({id:'proj_internal_'+i,name:'研究项目 '+(i+1),description:'验证模型质量、实验结果与研究进展。',status:'进行中',docs:19,open_todos:4,open_milestones:3,literature:5,last_updated:date,created:'2025-12-10'}));
    const projectCards=projectStats.map((p,i)=>({...p,name:i===1?'一个需要占据两行的较长研究项目名称以检验卡片对齐':p.name,description:['简短描述。','研究长文本建模、实验验证、数据对照与结果复核，覆盖更多内容以检验两行描述的高度及省略效果。',''][i%3]}));
    const fixtureDashboard={today:date,academic:{configured:true,percent:43.4,start_date:'2024-09-05',expected_end_date:'2029-07-15',elapsed_days:770,remaining_days:1004,weekly_goal_days:5,conditions_total:1,conditions_done:0,graduation_conditions:[{label:'期刊论文',current:1,target:3,percent:33}]},counts:{journal:1,note:1,literature:0,milestone:1},recent:{ideas:[],notes:[doc('note','ui-note','研究笔记')],summaries:[]},project_stats:projectStats,upcoming_milestones:[milestone,...Array.from({length:4},(_,i)=>doc('milestone','ui-extra-ms-'+i,'下一阶段研究节点 '+(i+1)))],activity:{days,start:'2026-10-02',end:date,events_month:20,active_days_month:8}};
    let syncRuns=0,syncChecks=0,syncResolves=0;
    const syncState={config:{mode:'off',url:'',interval:30,scopes:['documents','attachments','records','settings']},phase:'idle',upload:0,download:0,conflicts:0,changes:[],preferences:{},applied:0,remote_known:false};
    await page.addInitScript(()=>{
      localStorage.setItem('sidebarOpen',JSON.stringify(['core','research','resources','system']));
      localStorage.setItem('sidebarPinned',JSON.stringify(['core']));
      localStorage.setItem('uiScale','100');
      const page={getViewport:({scale})=>({width:600*scale,height:840*scale,scale,transform:[scale,0,0,-scale,0,840*scale]}),render:({canvasContext:ctx})=>{ctx.fillStyle='#fff';ctx.fillRect(0,0,ctx.canvas.width,ctx.canvas.height);return {promise:Promise.resolve()}},getTextContent:async()=>({items:[]}),cleanup(){}};
      window.pdfjsLib={getDocument:()=>({promise:Promise.resolve({numPages:3,getPage:async()=>page,destroy(){}})})};
      localStorage.setItem('fabBallPos',JSON.stringify({x:1548,y:300}));
      localStorage.setItem('erwRecent:doc',JSON.stringify({id:'ui-note',kind:'note',title:'知识-方法-物理状态计算与大模型决策的职责分离'}));
      localStorage.setItem('erwRecent:pdf',JSON.stringify({id:'ui-paper',title:'文献-物理信息引导思维树搜索的大模型负荷转供方法'}));
      localStorage.setItem('erwRecent:chat',JSON.stringify({id:'ui-agent-session',title:'LLM 的世界模型与确定性电气求解器如何分工？'}));
    });
    await page.route('**/api/**',async route=>{
      const request=route.request(),url=new URL(request.url()),method=request.method();
      const send=data=>route.fulfill({json:data});
      if(url.pathname.startsWith('/api/sync/')){
        const action=url.pathname.split('/').pop();
        if(action==='preferences'){Object.assign(syncState.preferences,request.postDataJSON());return send(syncState.preferences)}
        if(action==='guard')return send({ok:true});
        if(action==='config'){syncState.config=request.postDataJSON();return send(syncState)}
        if(action==='test')return send({ok:true,count:25});
        if(action==='run'){syncRuns++;syncState.phase='synced';syncState.last_success=Date.now()/1000;return send(syncState)}
        if(action==='check'){syncChecks++;return send(syncState)}
        if(action==='resolve'){syncResolves++;syncState.conflicts=0;syncState.changes=[];return send(syncState)}
        if(action==='conflict')return send({key:'doc:ui-journal',label:'实验记录',local_hash:'test-hash',remote_version:4,local:{text:'本地修改\n# 实验记录',editable:true},remote:{text:'服务器修改\n# 实验记录'},base:{text:'共同版本'},can_keep_both:true});
        return send(syncState);
      }
      if(url.pathname==='/api/dashboard')return send(fixtureDashboard);
      if(url.pathname==='/api/todos/batch-delete'){
        const body=request.postDataJSON();if(body.completed_only)cleanupCalls++;
        const removed=body.ids.filter(id=>id!==failTodoId&&todos.some(t=>t.id===id&&(!body.completed_only||t.done)));
        todos=todos.filter(t=>!removed.includes(t.id));
        return send({deleted:removed,failed:body.ids.filter(id=>!removed.includes(id)).map(id=>({id,message:'模拟删除失败'}))});
      }
      if(url.pathname==='/api/docs/batch-delete'){
        const ids=request.postDataJSON().ids,removed=ids.filter(id=>id!==failDocId);
        removed.forEach(id=>deletedDocs.add(id));
        return send({deleted:removed,failed:ids.filter(id=>!removed.includes(id)).map(id=>({id,message:'模拟删除失败'}))});
      }
      if(url.pathname==='/api/todos'&&method==='GET')return send(todos);
      if(url.pathname==='/api/todos'&&method==='POST'){
        writes++;const t={...request.postDataJSON(),id:'ui-new-todo',done:false};todos.push(t);return send(t);
      }
      if(url.pathname.startsWith('/api/todos/')&&method==='POST'){
        writes++;if(failWrite)return route.fulfill({status:500,json:{message:'模拟保存失败'}});
        const t=todos.find(t=>t.id===decodeURIComponent(url.pathname.split('/').pop()));Object.assign(t,request.postDataJSON());return send(t);
      }
      if(url.pathname==='/api/docs/draft'){
        draftReads++;const kind=url.searchParams.get('kind');
        return send({...doc(kind,'ui-draft-'+draftReads,'未命名文档'),path:'',draft:true,body:'# 未命名文档\n\n## 研究记录\n\n'});
      }
      if(url.pathname==='/api/docs'&&method==='POST'){
        if(failSave)return route.fulfill({status:500,json:{message:'模拟保存失败'}});
        docWrites++;const body=request.postDataJSON(),saved={...doc(body.kind,'ui-saved-'+docWrites,body.title),...body};docRecords.push(saved);return send(saved);
      }
      if(url.pathname.startsWith('/api/docs/')&&method==='POST'&&url.pathname!=='/api/docs/batch-delete'){
        if(failSave)return route.fulfill({status:500,json:{message:'模拟保存失败'}});
        docWrites++;const saved=docRecords.find(d=>d.id===decodeURIComponent(url.pathname.split('/').pop()));Object.assign(saved,request.postDataJSON());return send(saved);
      }
      if(url.pathname==='/api/docs'){
        const kind=url.searchParams.get('kind'),scope=url.searchParams.get('scope');
        const rows=docRecords.filter(d=>!deletedDocs.has(d.id)&&(!kind||d.kind===kind));
        const pageNum=Number(url.searchParams.get('page')||1),size=scope==='overview'?6:kind==='journal'?2:200;
        const pages=Math.max(1,Math.ceil(rows.length/size));
        return send({items:rows.slice((pageNum-1)*size,pageNum*size),total:rows.length,page:pageNum,pages,page_size:size,next_page:pageNum<pages?pageNum+1:null,prev_page:pageNum>1?pageNum-1:null});
      }
      if(url.pathname==='/api/milestones/plan')return send({items:docRecords.filter(d=>d.kind==='milestone'&&!deletedDocs.has(d.id)),unavailable:0});
      if(url.pathname.startsWith('/api/docs/'))return send(docRecords.find(d=>d.id===decodeURIComponent(url.pathname.split('/').pop()))||journal);
      if(url.pathname==='/api/graph'){if(graphGate)await graphGate;return send({nodes:[{...journal,label:journal.title},{...milestone,label:milestone.title}],edges:[{source:journal.id,target:milestone.id,kind:'wikilink'}],meta:{total_documents:2,shown_documents:2}})}
      if(url.pathname==='/api/graph/bundle')return send({content:'# 关联资料汇总\n\n'+Array.from({length:80},(_,i)=>`## 研究条目 ${i+1}\n\n包含完整的研究记录与关联 Markdown 内容。\n`).join('\n')});
      if(url.pathname==='/api/agent/sessions')return send([agentSession]);
      if(url.pathname==='/api/agent/sessions/'+agentSession.id)return send(agentSession);
      if(url.pathname.startsWith('/api/literature/document/'))return send({...paper,doc_id:decodeURIComponent(url.pathname.split('/').pop())});
      if(url.pathname==='/api/literature')return send({items:[paper],total:1});
      if(url.pathname==='/api/literature/'+paper.id){if(method==='POST')Object.assign(paper,request.postDataJSON());return send(paper)}
      if(url.pathname==='/api/literature/'+paper.id+'/annotations')return send([]);
      if(url.pathname==='/api/literature/'+paper.id+'/note')return send({content:'# 文献笔记\n\n核对实验设置。'});
      if(url.pathname==='/api/system/reload')return send({ok:true});
      if(url.pathname==='/api/config'){
        const cfg={app:{app_name:'科研工作台',subtitle:'Engineering Research Workspace',ui:{graph_default_view:'3d'},academic_profile:{graduation_conditions:[{label:'论文',current:1,target:3,unit:'篇'}]},llm:{enabled:false,active_profile_id:'qa',profiles:[{id:'qa',name:'测试配置',base_url:'https://example.invalid/v1',request_presets:[{id:'default',label:'默认',model:'qa'}]}]}},rss:{sources:[{name:'测试资讯',url:'https://example.invalid/rss',enabled:true}]},weather:{enabled:false}};
        cfg.app.classification_marks=[{id:'knowledge',label:'知识',icon:'◈',color:'#2a9d8f'},{id:'method',label:'方法',icon:'⚒',color:'#e76f51'}];
        return send(cfg);
      }
      if(url.pathname==='/api/knowledge-types'){
        if(failBootstrapOnce){failBootstrapOnce=false;bootstrapFailures++;return route.abort('failed')}
        return send(['idea','journal','note','milestone','summary','literature'].map((id,i)=>({id,label:['灵感','实验记录','笔记','里程碑','工作总结','文献'][i],builtin:true,statuses:['草稿','记录'],template:'# {{title}}\n\n## 要点\n',default_template:'# {{title}}\n'})));
      }
      if(url.pathname==='/api/statuses')return send({journal:['记录'],milestone:['进行中','完成','计划','受阻'],note:['记录']});
      if(url.pathname==='/api/projects')return send(['示例项目']);
      if(url.pathname==='/api/project-records')return send(projectCards);
      if(url.pathname==='/api/billing/summary')return send({total:{calls:3,total_tokens:9000,prompt_tokens:7000,completion_tokens:2000,cached_tokens:3500,cache_hit_rate:.5,unpriced_calls:3},by_session:[{title:'研究对话',calls:2,total_tokens:8000},{title:'阅读助手',calls:1,total_tokens:1000}],by_model:[{model:'qa-model',calls:3,total_tokens:9000,unpriced_calls:3}],by_date:[{date,calls:3,total_tokens:9000}],unpriced:[{profile_name:'测试配置',model:'qa-model',calls:3,total_tokens:9000,suggested_key:'qa/qa-model'}]});
      if(url.pathname==='/api/billing/prices')return send({currency:'USD',models:{},plans:{}});
      if(url.pathname==='/api/billing/records')return send({total:2,items:[{ts:date,session_title:'研究对话',model:'qa-model',prompt_tokens:4000,completion_tokens:1000},{ts:date,session_title:'阅读助手',model:'qa-model',prompt_tokens:3000,completion_tokens:1000}]});
      if(url.pathname==='/api/health')return send({version:'ui-test'});
      if(url.pathname==='/api/workspace/info')return send({relative:'Test Workspace'});
      if(url.pathname.startsWith('/api/weather'))return send({enabled:false});
      if(method!=='GET')throw new Error('Unexpected write: '+method+' '+url.pathname);
      return send([]);
    });
    const ready=()=>page.waitForSelector('.overview-todo-add');
    const go=async route=>{await page.locator(`#sidebar-nav [data-route="${route}"]`).click();await page.waitForFunction(r=>document.documentElement.dataset.route===r,route)};
    const respond=async(trigger,result='confirm')=>{const work=trigger();await page.waitForSelector('#workbench-dialog');await page.locator(`[data-dialog-result="${result}"]`).click();await page.waitForSelector('#workbench-dialog',{state:'detached'});await work};
    const shot=(name,options={})=>page.screenshot({path:path.join(output,name+'.png'),fullPage:true,...options});
    // Resize handlers and the heatmap observer may reflow cards after the viewport event.
    const settleOverview=()=>page.waitForFunction(()=>{const e=document.querySelector('.overview-dashboard'),r=e.getBoundingClientRect(),key=[r.width,r.height,document.querySelector('.heatmap-card')?.style.cssText].join('|');if(e._testLayoutKey!==key){e._testLayoutKey=key;e._testLayoutSince=performance.now()}return performance.now()-e._testLayoutSince>=160});
    const smallText=()=>page.evaluate(()=>Array.from(document.querySelectorAll('body *')).filter(e=>e.children.length===0&&e.textContent.trim()&&e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<11).map(e=>({class:e.className,size:getComputedStyle(e).fontSize,text:e.textContent.slice(0,30)})));
    await page.goto(base);await ready();
    if(literatureOnly){
      page.setDefaultTimeout(12000);await page.setViewportSize({width:2550,height:1369});
      const longProject='Two-stage fine-tuning of large language models for distribution network service restoration via CoT reasoning';
      const papers=[{...paper,doc_id:'unified-doc',title:'文献-物理信息引导思维树搜索的大模型负荷转供方法',pdf_available:true,projects:[longProject],tags:['研究方法'],bibtex:'@article{original}',url:'https://example.invalid/source',added_date:date},{...paper,id:'entry-unified-missing',doc_id:'unified-missing',title:'未附 PDF 的旧文献',pdf_available:false,projects:['示例项目']}];
      const notes=new Map(papers.map(p=>[p.id,{content:'# 历史阅读笔记\n\n保留已有 Markdown、引用与图片。',revision:'revision-1'}]));
      let failNote=false,failNoteLoad=false,assistCalls=[],noteWrites=0,paperWrites=0,importBinding='';
      await page.route('**/api/agent/assist',async route=>{assistCalls.push(route.request().postDataJSON());return route.fulfill({json:{content:'# AI 整理后的笔记\n\n仅使用当前笔记原文。'}})});
      await page.route('**/api/literature**',async route=>{
        const request=route.request(),url=new URL(request.url()),method=request.method(),send=json=>route.fulfill({json});
        if(url.pathname==='/api/literature'){const pdf=url.searchParams.get('pdf'),query=url.searchParams.get('q')||'',items=papers.filter(p=>(!pdf||p.pdf_available===(pdf==='available'))&&p.title.includes(query));return send({items,total:items.length,page:1,page_size:60})}
        if(url.pathname==='/api/literature/import'){importBinding=decodeURIComponent(request.headers()['x-bind-paper']||'');const p=papers.find(p=>p.id===importBinding);p.pdf_available=true;return send(p)}
        if(url.pathname.startsWith('/api/literature/document/'))return send(papers.find(p=>p.doc_id===decodeURIComponent(url.pathname.split('/').pop()))||papers[0]);
        const match=url.pathname.match(/^\/api\/literature\/([^/]+)(?:\/(note|annotations|pdf))?$/);if(!match)return route.fallback();const id=decodeURIComponent(match[1]),p=papers.find(p=>p.id===id);if(!p)return route.fallback();
        if(match[2]==='annotations')return send([]);
        if(match[2]==='note'){
          if(method==='POST'){if(failNote)return route.fulfill({status:500,json:{message:'模拟磁盘保存失败'}});noteWrites++;const data=request.postDataJSON();notes.set(id,{content:data.content,revision:'revision-'+(noteWrites+1)});return send({ok:true,revision:notes.get(id).revision})}
          if(failNoteLoad)return route.fulfill({status:500,json:{message:'模拟读取失败'}});return send(notes.get(id));
        }
        if(!match[2]){if(method==='POST'){Object.assign(p,request.postDataJSON());paperWrites++}return send(p)}return route.fallback();
      });
      await page.evaluate(()=>{
        window.__pdfDelay=170;window.__pdfRenders=0;window.__pdfCancels=0;window.__frontViolations=[];
        const sample=()=>{for(const cv of document.querySelectorAll('.lit-page canvas')){if(cv.dataset.ready!=='true'||cv.width<2||cv.height<2)window.__frontViolations.push('unfinished canvas');else{const pixel=cv.getContext('2d').getImageData(0,0,1,1).data;if(pixel[0]<240||pixel[1]<240||pixel[2]<240)window.__frontViolations.push('black front buffer')}}requestAnimationFrame(sample)};requestAnimationFrame(sample);
        const transform=(a,b)=>[a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]];
        const pdfPage={getViewport:({scale})=>({width:600*scale,height:800*scale,scale,transform:[scale,0,0,-scale,0,800*scale]}),render:({canvasContext:ctx,viewport:v})=>{window.__pdfRenders++;ctx.fillStyle='#000';ctx.fillRect(0,0,ctx.canvas.width,ctx.canvas.height);let reject,timer;const promise=new Promise((resolve,fail)=>{reject=fail;timer=setTimeout(()=>{ctx.fillStyle='#fff';ctx.fillRect(0,0,ctx.canvas.width,ctx.canvas.height);ctx.fillStyle='#151c2b';ctx.font='35px serif';ctx.fillText('PDF completed vector frame',50,100);resolve()},window.__pdfDelay)});return {promise,cancel(){clearTimeout(timer);window.__pdfCancels++;reject(Object.assign(Error('cancelled'),{name:'RenderingCancelledException'}))}}},getTextContent:async()=>({items:[{str:'PDF 选中的原文段落',width:350,transform:[20,0,0,20,30,480]}]}),cleanup(){}};
        window.pdfjsLib={Util:{transform},getDocument:()=>({promise:Promise.resolve({numPages:15,getPage:async()=>pdfPage,destroy(){}})})};
      });
      await go('literature');await page.waitForSelector('.lit-page canvas[data-ready=true]');
      assert.equal(await page.locator('#open-lit-workspace,#lit-back,#f-title').count(),0,'literature has a single workspace');
      assert.equal(await page.locator('.lit-item').count(),2);assert((await page.locator('.lit-item').first().boundingBox()).height<78,'PDF cards are compact');
      const left=page.locator('.lit-library'),oldWidth=(await left.boundingBox()).width,splitter=page.locator('.lit-splitter-library'),handle=await splitter.boundingBox();
      await page.mouse.move(handle.x+handle.width/2,handle.y+180);await page.mouse.down();await page.mouse.move(handle.x+100,handle.y+180,{steps:6});await page.mouse.up();assert((await left.boundingBox()).width>oldWidth+70,'left list width changes with drag');
      await page.locator('#lit-toggle-side').click();await page.locator('.lit-splitter-side').focus();const sideBefore=(await page.locator('.lit-side').boundingBox()).width;await page.keyboard.press('ArrowLeft');assert((await page.locator('.lit-side').boundingBox()).width>sideBefore,'right pane supports keyboard resizing');
      await page.locator('[data-tab=notes]').click();await page.waitForSelector('#lit-note');const draft='# 用户的未保存笔记\n\n包含新内容和 [[本地引用]]。';await page.locator('#lit-note').fill(draft);
      await page.locator('[data-tab=info]').click();await page.locator('[data-tab=notes]').click();await page.waitForSelector('#lit-note');assert.equal(await page.locator('#lit-note').inputValue(),draft,'tab switches retain note drafts');
      failNote=true;await page.locator('#lit-note-save').click();await page.waitForFunction(()=>document.querySelector('#lit-note-status').textContent.includes('保存失败'));assert.equal(await page.locator('#lit-note').inputValue(),draft);failNote=false;
      await page.locator('#lit-note-save').click();await page.waitForFunction(()=>document.querySelector('#lit-note-status').textContent.includes('笔记已保存'));assert.equal(notes.get(papers[0].id).content,draft);assert.equal(noteWrites,1);
      // The note source must win over any PDF selection left in the reader.
      const hit=page.locator('.lit-interaction-layer').first(),bounds=await hit.boundingBox();await page.mouse.move(bounds.x+bounds.width*.06,bounds.y+bounds.height*.3875);await page.mouse.down();await page.mouse.move(bounds.x+bounds.width*.61,bounds.y+bounds.height*.3875,{steps:6});await page.mouse.up();
      await page.locator('#lit-note').fill(draft+'\n\n正在整理的草稿');await page.locator('#lit-note-ai').click();await page.waitForSelector('#lit-ai-append');assert.equal(assistCalls.at(-1).text,draft+'\n\n正在整理的草稿','AI receives the latest note draft');assert.equal(noteWrites,1,'AI never writes a note without applying/saving');
      await page.locator('#lit-ai-append').click();await page.waitForSelector('#lit-note');assert((await page.locator('#lit-note').inputValue()).includes('\n\n# AI 整理后的笔记'),'AI appends real Markdown newlines');assert.equal(noteWrites,1);await page.locator('#lit-note-save').click();await page.waitForFunction(()=>document.querySelector('#lit-note-status').textContent.includes('笔记已保存'));
      await page.locator('#lit-note').fill('离开前的草稿');const leave=page.locator('#sidebar-nav [data-route=overview]').click();await page.waitForSelector('#workbench-dialog');await page.locator('[data-dialog-result=cancel]').click();await leave;assert.equal(await page.locator('#lit-note').inputValue(),'离开前的草稿');
      await respond(()=>page.locator('[data-paper="'+papers[1].id+'"]').click(),'discard');await page.waitForSelector('#lit-bind-pdf');await page.locator('[data-tab=notes]').click();await page.waitForSelector('#lit-note');assert((await page.locator('#lit-note').inputValue()).includes('历史阅读笔记'),'legacy metadata notes remain reachable without a PDF');
      await page.locator('#lit-bind-pdf').click();await page.locator('#lit-file').setInputFiles({name:'绑定文献.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4\nfixture')});await page.waitForSelector('.lit-page canvas[data-ready=true]');assert.equal(importBinding,papers[1].id,'binding uses the old record identity');
      await page.locator('[data-tab=info]').click();await page.locator('#li-title').fill('修改后的文献题名');await page.locator('#li-url').fill('https://example.invalid/updated');await page.locator('#li-save').click();await page.waitForFunction(()=>document.querySelector('#li-message').textContent==='信息已保存');assert.equal(papers[1].url,'https://example.invalid/updated');assert(await page.locator('#li-projects').count());
      await page.locator('#lit-toggle-side').click();await page.waitForTimeout(300);
      const before=await page.locator('.lit-page canvas').first().evaluate(e=>{e.dataset.frontIdentity='retained';return e.width});await page.locator('#lit-zoom-in').click();
      assert.equal(await page.locator('canvas[data-front-identity=retained]').count(),1,'zoom retains the completed old frame while rendering');
      await page.waitForFunction(()=>!document.querySelector('#lit-pages').style.zoom&&document.querySelector('.lit-page canvas')?.dataset.frontIdentity!=='retained');
      for(let i=0;i<3;i++){await page.locator('#lit-zoom-out').click();await page.waitForTimeout(30)}await page.waitForTimeout(500);assert.equal(await page.locator('.lit-page-error').count(),0);assert.deepEqual(await page.evaluate(()=>window.__frontViolations),[],'no black/unfinished canvas is ever displayed');
      await page.locator('#lit-toggle-side').click();await page.locator('[data-tab=notes]').click();await page.waitForSelector('#lit-note');
      for(const theme of ['light','dark']){await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);for(const width of [2550,1920,1280,760]){await page.setViewportSize({width,height:1100});await page.waitForTimeout(180);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'workspace stays in viewport '+width);const metrics=await page.locator('.lit-note-actions').evaluate(e=>{const r=e.getBoundingClientRect(),p=e.closest('.lit-side').getBoundingClientRect();return {inside:r.bottom<=p.bottom+1,buttons:[...e.querySelectorAll('button')].every(b=>getComputedStyle(b).whiteSpace==='nowrap')}});assert(metrics.inside&&metrics.buttons,'note actions remain readable and visible at '+width);assert((await page.locator('.lit-side').boundingBox()).width>=230,'overlay retains usable width at '+width);await shot('unified-literature-'+theme+'-'+width,{fullPage:false})}}
      await page.setViewportSize({width:1920,height:1080});await page.locator('[data-tab=info]').click();await page.locator('#zoom-btn').click();await page.locator('[data-zoom="125"]').click();await page.waitForTimeout(220);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'125% layout');await shot('unified-literature-info-125',{fullPage:false});
      assert.deepEqual(errors,[]);console.log('PASS: single PDF workspace, compact cards, pointer/keyboard pane resizing, retained white render frames, zoom cancellation, draft/save/failure guards, note AI source/approval, legacy PDF binding, complete metadata, 2550/1920/1280/760 light/dark and 125% UI scale; no real model calls');return;
    }
    if(planningOnly){
      page.setDefaultTimeout(10000);
      const projectA='物理信息引导思维树搜索的大模型负荷转供方法',projectB='Two-stage fine-tuning of large language models for distribution network service restoration via CoT reasoning';
      const plans=[
        ['phase-active','方法与基线复现','2026-10-05','2026-11-20','进行中',35],
        ['phase-done','文献梳理与问题定义','2026-09-15','2026-10-03','完成',100],
        ['phase-late','物理约束与潮流接口验收','2026-09-20','2026-10-01','进行中',75],
        ['phase-blocked','消融与鲁棒性实验','2026-10-18','2026-11-25','受阻',20],
        ['point-review','阶段组会评审',null,'2026-11-20','计划',null],
        ['point-same-day','同日模型验收',null,'2026-11-20','计划',null],
        ['phase-new-year','跨年论文整理','2026-12-10','2027-01-21','计划',null],
        ['phase-undated','尚未排期的研究想法',null,null,'计划',null],
        ['phase-invalid','外部日期错误的旧条目','2026-11-20','2026-10-01','计划',null],
        ...Array.from({length:18},(_,i)=>['phase-generated-'+i,'验证实验 '+(i+1),'2026-10-'+String(5+i).padStart(2,'0'),'2026-11-'+String(5+i).padStart(2,'0'),['计划','进行中','受阻','完成'][i%4],i%4===3?100:i*4]),
      ].map(([id,title,start_date,due,status,progress],i)=>({...doc('milestone',id,title),start_date:start_date||'',due:due||'',status,progress,project:i%2?projectB:projectA,projects:i===0?[projectA,projectB]:[i%2?projectB:projectA]}));
      docRecords.splice(0,docRecords.length,...plans,journal);
      fs.writeFileSync(path.join(output,'planning-fixture.json'),JSON.stringify(plans,null,2));
      const graphNodes=[...plans.slice(0,10).map((d,i)=>({...d,kind:'note',label:d.title,id:'g'+i})),{id:'project-a',kind:'project',label:projectA,virtual:true},{id:'project-b',kind:'project',label:projectB,virtual:true},{id:'tag-a',kind:'tag',label:'电网恢复',virtual:true}];
      const graphEdges=[...graphNodes.slice(0,10).map((n,i)=>({source:n.id,target:i%2?'project-b':'project-a',relation:'project'})),{source:'g0',target:'tag-a',relation:'tag'},{source:'g0',target:'g2',relation:'wikilink'}];
      await page.route('**/api/graph?*',route=>route.fulfill({json:{nodes:graphNodes,edges:graphEdges,meta:{total_documents:10,shown_documents:10}}}));
      await page.setViewportSize({width:2550,height:1233});await go('graph');await page.waitForFunction(()=>!!window.__knowledgeGraphEngine?.projectPicker);
      assert.equal(await page.evaluate(()=>window.__knowledgeGraphEngine.selectedId),null);
      const scope=page.locator('#graph-project-scope');await scope.locator('button.project-scope-trigger').click();
      await scope.locator('input').fill('Two-stage');await scope.locator('input').press('Enter');
      assert.equal(await page.evaluate(()=>window.__knowledgeGraphEngine.scopeProject),projectB);
      assert.equal(await page.evaluate(()=>window.__knowledgeGraphEngine.selectedId),null,'switching projects never implicitly selects a recent node');
      assert(await page.evaluate(()=>window.__knowledgeGraphEngine.graph.nodes.every(n=>window.__knowledgeGraphEngine.nodeAlpha(undefined,false)===1)),'scope overview shows all loaded project nodes');
      await page.evaluate(()=>window.__knowledgeGraphEngine.selectNode('g1',true));
      await scope.locator('button.project-scope-trigger').click();await scope.locator('input').fill('物理');await scope.locator('input').press('ArrowDown');await scope.locator('input').press('Enter');
      await page.waitForTimeout(350);
      const overview=await page.evaluate(()=>{const e=window.__knowledgeGraphEngine;return {selected:e.selectedId,scope:e.scopeProject,tags:e.graph.nodes.some(n=>n.id==='tag-a'),camera:e.camera['2d'],visible:e.graph.nodes.every(n=>e.screen.get(n.id)?.visible)}});
      assert.equal(overview.scope,projectA);assert.equal(overview.selected,null);assert(overview.tags,'related tag nodes survive project scoping');assert(overview.visible,'scoped overview fits every node');
      await page.locator('[data-graph-focus="0"]').click();assert.equal(await page.evaluate(()=>window.__knowledgeGraphEngine.scopeProject),projectA,'scope overview keeps chosen project');
      assert.equal(await page.locator('#graph-wrap.preview-open').count(),0);
      await shot('planning-graph-light');
      await scope.locator('button.project-scope-trigger').click();await scope.locator('input').press('Escape');assert.equal(await scope.locator('button.project-scope-trigger').getAttribute('aria-expanded'),'false');
      assert((await scope.boundingBox()).width<300,'long project names do not stretch the toolbar');
      await go('milestones');await page.locator('[data-ms-view="gantt"]').click();await page.waitForSelector('[data-plan-id="phase-active"]');
      assert.equal(await page.locator('.mg-row').count(),plans.length,'undated/invalid items remain visible');
      assert.equal(await page.locator('.mg-diamond[data-plan-id="point-review"]').count(),1);
      assert.equal(await page.locator('.mg-bar[data-plan-id="phase-active"]').count(),1);
      assert.equal(await page.locator('.mg-row.is-late[data-milestone-id="phase-late"]').count(),1);
      assert.equal(await page.locator('[data-milestone-id="phase-invalid"] .mg-pending').innerText(),'日期待修正');
      await page.locator('[data-plan-id="phase-active"]').click();await page.waitForSelector('.mg-detail-form');
      await page.locator('.mg-detail-form [name="progress"]').fill('62.5');await page.locator('.mg-detail-form [name="due"]').fill('2026-11-28');
      failSave=true;await page.locator('.mg-detail-form button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.mg-form-message').textContent.includes('保存失败'));
      assert.equal(await page.locator('.mg-detail-form [name="progress"]').inputValue(),'62.5');failSave=false;
      await page.locator('.mg-detail-form button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.mg-form-message').textContent==='计划已保存');
      assert.equal(docRecords.find(d=>d.id==='phase-active').progress,62.5);assert.equal(docRecords.find(d=>d.id==='phase-active').due,'2026-11-28');
      await page.locator('.mg-detail-form [name="progress"]').fill('70');
      const leaving=page.locator('[data-ms-view="timeline"]').click();await page.waitForSelector('#workbench-dialog');await page.locator('[data-dialog-result="cancel"]').click();await leaving;assert.equal(await page.locator('.milestone-gantt').count(),1,'cancel preserves unsaved plan');
      await respond(()=>page.locator('.mg-detail-head button').click(),'discard');
      await page.locator('.mg-search').fill('阶段组会');assert.equal(await page.locator('.mg-row').count(),1);await page.locator('.mg-search').fill('');
      await page.locator('.mg-filter').selectOption('undated');assert.equal(await page.locator('.mg-row').count(),2);await page.locator('.mg-filter').selectOption('');
      const picker=page.locator('.mg-controls .project-scope');await picker.locator('.project-scope-trigger').click();await picker.locator('input').fill('物理');await picker.locator('input').press('Enter');
      assert.equal(await page.locator('.mg-group').count(),1);await picker.locator('.project-scope-trigger').click();await picker.locator('input').fill('全部项目');await picker.locator('input').press('Enter');
      await page.locator('.mg-group-label').first().click();assert((await page.locator('.mg-row').count())<plans.length);await page.locator('.mg-group-label').first().click();
      await page.locator('[data-gantt-scale="day"]').click();await page.locator('.mg-scroll').evaluate(e=>e.scrollLeft=450);
      const pinned=await page.locator('.mg-scroll').evaluate(e=>{const l=e.querySelector('.mg-row-label'),s=e.getBoundingClientRect();return Math.abs(l.getBoundingClientRect().left-s.left)<2});assert(pinned,'row labels stay fixed during horizontal scroll');
      await page.locator('.mg-scroll').evaluate(e=>e.scrollTop=240);assert(await page.locator('.mg-axis').evaluate(e=>Math.abs(e.getBoundingClientRect().top-e.closest('.mg-scroll').getBoundingClientRect().top)<2),'date header stays fixed during vertical scroll');
      await page.locator('[data-gantt-scale="fit"]').click();
      for(const theme of ['light','dark']){
        await page.evaluate(t=>{localStorage.setItem('theme',t);document.documentElement.dataset.theme=t},theme);
        for(const width of [2550,1920,1280,760]){
          await page.setViewportSize({width,height:width>1900?1233:900});await page.waitForTimeout(200);
          assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'planning has no page-wide horizontal overflow at '+width);
          const b=await page.locator('.mg-chart').boundingBox();assert(b.width>260,'chart remains usable at '+width);
          if(width>=1280)assert(await page.locator('.mg-footer').evaluate(e=>e.getBoundingClientRect().bottom<=innerHeight-8),'chart and footer fit the viewport at '+width);
          await shot('planning-gantt-'+theme+'-'+width);
        }
      }
      await page.setViewportSize({width:1920,height:1080});await page.locator('#zoom-btn').click();await page.locator('[data-zoom="125"]').click();await page.waitForTimeout(200);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'planning fits 125% UI scale');await shot('planning-gantt-dark-125pct');
      await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
      await page.setViewportSize({width:1920,height:1080});await page.locator('[data-plan-id="phase-active"]').click();await shot('planning-gantt-detail-dark');
      await page.locator('.mg-detail-form [name="start_date"]').fill('');await page.locator('.mg-detail-form [name="progress"]').fill('');await page.locator('.mg-detail-form button[type=submit]').click();await page.waitForFunction(()=>document.querySelector('.mg-form-message').textContent==='计划已保存');
      assert.equal(await page.locator('.mg-diamond[data-plan-id="phase-active"]').count(),1,'clearing the start date turns a phase into a point');
      await page.locator('.mg-detail-form .secondary-btn').click();await page.waitForSelector('#f-title');assert.equal(await page.locator('#f-title').inputValue(),'方法与基线复现');
      await page.locator('#meta-toggle').click();await page.locator('#f-start-date').fill('2026-10-10');await page.locator('#f-progress').fill('40');await page.locator('#doc-save').click();await page.waitForFunction(()=>!window.ERWDesktop.hasUnsavedChanges());
      assert.equal(docRecords.find(d=>d.id==='phase-active').progress,40,'document editor shares schedule fields');
      await page.locator('[data-ms-view="gantt"]').click();await page.waitForSelector('.mg-bar[data-plan-id="phase-active"]');
      docRecords.splice(0,docRecords.length);await page.locator('[data-ms-view="list"]').click();await page.locator('[data-ms-view="gantt"]').click();await page.waitForSelector('.mg-empty .primary-btn');
      assert.equal(errors.length,0,errors.join('\n'));
      console.log('PASS: scoped graph overview, searchable keyboard picker, tag context, cancelled camera animation; generated milestone phases/points, save/failure/clear, dirty guards, filters, sticky axes, dark/light at 2550/1920/1280/760, document roundtrip and empty state');return;
    }
    if(referencesOnly){
      const source=doc('note','ref-source','知识-原理-GraphRAG 与电网物理图的区别');
      const referenced={...doc('literature','ref-paper','文献-物理信息引导思维树搜索的大模型负荷转供方法'),attachment:'Knowledge/Literature/PDF/ui-paper.pdf',body:'# 方法与原文\n\n这份文献提供真实的局部物理状态，先核对证据再选择动作。\n\n| 方法 | 依据 |\n| --- | --- |\n| 物理模型 | 状态计算 |\n\n参见 [[ref-child|结构化任务描述]] 或 [本地笔记文件](../Notes/ref-child.md)。\n\n`[[代码示例]]`'};
      const child={...doc('note','ref-child','知识-方法-物理信息与结构化任务描述'),body:'# 结构化任务描述\n\n这里是第二份引用文档。'};
      const slow={...doc('note','ref-slow','延迟返回的笔记'),body:'# 延迟结果\n\n旧响应不能覆盖新预览。'};
      source.body='# 本地文档引用\n\n请比较 [[ref-paper|物理信息引导思维树搜索]]，以及 [[ref-child|结构化任务描述]]。\n\n失效引用：[[已删除的资料]]；重名引用：[[同名条目]]；连接问题：[[连接异常]]。\n\n慢速引用：[[ref-slow|延迟笔记]]。再次引用 [[ref-paper|原文]]。\n\n`[[代码示例不应该高亮]]`\n\n[Markdown 文件](../Notes/ref-child.md) · [网络链接](https://example.invalid/paper.md)';
      docRecords.push(source,referenced,child,slow);
      const resolutions=new Map(),searches=[];let holdSlow=null,failConnection=true;
      await page.route('**/api/docs**',async route=>{
        const u=new URL(route.request().url());
        if(u.pathname==='/api/docs/resolve'){
          const target=(u.searchParams.get('target')||'').split('#')[0];resolutions.set(target,(resolutions.get(target)||0)+1);
          if(target===slow.id&&holdSlow)await holdSlow;
          if(target==='同名条目')return route.fulfill({status:400,json:{message:'存在同名条目，请使用条目 ID 引用'}});
          if(target==='连接异常'&&failConnection)return route.fulfill({status:503,json:{message:'服务暂时不可用'}});
          const found=docRecords.find(d=>d.id===target||d.title===target);
          return route.fulfill(found?{json:found}:{status:404,json:{message:'未找到对应条目：'+target}});
        }
        if(u.pathname==='/api/docs'&&u.searchParams.get('scope')==='reference'){
          const query=(u.searchParams.get('q')||'').toLowerCase();searches.push(query);
          if(query==='搜索失败')return route.fulfill({status:500,json:{message:'模拟搜索失败'}});
          if(query==='慢查询')await new Promise(resolve=>setTimeout(resolve,350));
          const items=docRecords.filter(d=>[d.title,d.body,...(d.tags||[])].join(' ').toLowerCase().includes(query));
          return route.fulfill({json:{items,total:items.length,page:1,pages:1,page_size:30}});
        }
        return route.fallback();
      });
      await page.setViewportSize({width:2550,height:1233});await page.evaluate(()=>window.ERWNav.open('note','ref-source'));await page.waitForSelector('#md-input',{state:'attached'});
      const sourceLink=target=>page.locator(`#md-preview a[data-agent-reference="${target}"]`).first();
      await page.waitForSelector('#md-preview [data-reference-state="valid"]');await page.waitForSelector('#md-preview [data-reference-state="missing"]');await page.waitForSelector('#md-preview [data-reference-state="unavailable"]');
      assert.equal(await page.locator('#md-preview code [data-agent-reference],#md-preview pre [data-agent-reference]').count(),0);
      assert.equal(await page.locator('#md-preview a[href="https://example.invalid/paper.md"]').getAttribute('data-reference-state'),null,'external links remain untouched');
      assert.equal(await page.locator('#md-preview a[href="../Notes/ref-child.md"]').getAttribute('data-agent-reference'),child.id,'local Markdown paths resolve by stable document identity');
      assert.equal(resolutions.get(referenced.id),1,'duplicate citations share one exact lookup');
      const editor=page.locator('#md-input');await page.locator('[data-edit-mode="split"]').click();
      const draft=source.body+'\n\n未保存的研究补充';await editor.fill(draft);await page.waitForSelector('#md-preview a[data-agent-reference="ref-paper"]');
      await editor.fill(draft+'\n\n<img src="reference-invalid.png" onerror="window.__unsafeReferenceHtml=true">');await page.waitForSelector('#md-preview img');await page.waitForTimeout(100);
      assert.equal(await page.evaluate(()=>window.__unsafeReferenceHtml),undefined,'reference conversion never executes raw document HTML');assert.equal(await page.locator('#md-preview img').getAttribute('onerror'),null);await editor.fill(draft);
      await sourceLink(referenced.id).click();await page.waitForFunction(()=>document.querySelector('#reference-preview-title')?.textContent.includes('物理信息引导'));
      assert.equal(await page.locator('.docs-layout').getAttribute('data-reference-docked'),'true');assert.equal(await editor.inputValue(),draft);assert.equal(await page.locator('#f-title').inputValue(),source.title);
      assert.equal(await page.locator('#workbench-dialog').count(),0,'preview never invokes the unsaved-document guard');
      assert.equal(await page.locator('[data-reference-pdf]').isVisible(),true);
      await page.locator('body').dispatchEvent('keydown',{key:'Escape',isComposing:true,keyCode:229});assert.equal(await page.locator('.document-reference-preview').count(),1,'IME cancellation does not close the reference pane');
      await page.waitForSelector('.reference-preview-body a[href="../Notes/ref-child.md"][data-agent-reference="ref-child"]');
      await page.locator('.reference-preview-body a[href="../Notes/ref-child.md"]').click();await page.waitForFunction(()=>document.querySelector('#reference-preview-title').textContent.includes('结构化任务描述'));
      await page.locator('[data-reference-back]').click();await page.waitForFunction(()=>document.querySelector('#reference-preview-title').textContent.includes('文献-'));
      await sourceLink('已删除的资料').click();await page.waitForSelector('.reference-preview-body [data-reference-retry]');assert((await page.locator('.reference-preview-body').innerText()).includes('未找到'));
      const restored=doc('note','ref-restored','已删除的资料');restored.body='# 恢复的资料\n\n原引用现在可以重新使用。';docRecords.push(restored);
      await page.locator('[data-reference-retry]').click();await page.waitForFunction(()=>document.querySelector('#reference-preview-title').textContent==='已删除的资料');await page.waitForSelector('#md-preview [data-agent-reference="已删除的资料"][data-reference-state="valid"]');
      let releaseSlow;holdSlow=new Promise(resolve=>releaseSlow=resolve);await page.evaluate(()=>window.ERWDocReferences.invalidate());
      await sourceLink(slow.id).click();await sourceLink(child.id).click();await page.waitForFunction(()=>document.querySelector('#reference-preview-title').textContent.includes('结构化任务描述'));releaseSlow();holdSlow=null;await page.waitForTimeout(100);
      assert((await page.locator('#reference-preview-title').innerText()).includes('结构化任务描述'),'late preview responses cannot replace the latest target');
      for(const theme of ['dark','light']){
        if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#theme-btn').click();
        await sourceLink(referenced.id).click();await page.waitForFunction(()=>document.querySelector('#reference-preview-title')?.textContent.includes('文献-'));
        await page.waitForSelector('#md-preview [data-agent-reference="同名条目"][data-reference-state="missing"]');
        const broken=await sourceLink('同名条目').evaluate(e=>({color:getComputedStyle(e).color,style:getComputedStyle(e).textDecorationStyle,title:e.title}));assert.equal(broken.style,'wavy');assert(broken.title.includes('同名'));
        await shot('document-reference-fullscreen-'+theme,{fullPage:false});
        for(const zoom of [100,125]){
          await page.setViewportSize({width:2550,height:1233});
          await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();
          for(const width of [2550,1920,1280,760]){
            await page.setViewportSize({width,height:1000});await page.waitForTimeout(50);const b=await page.locator('.document-reference-preview').boundingBox();assert(b.x>=0&&b.x+b.width<=width+1&&b.y>=0&&b.y+b.height<=1001,'reference pane stays inside the viewport at '+width+' '+zoom+'%');
            assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'reference pane does not widen the document');
          }
        }
        await page.setViewportSize({width:2550,height:1233});
        await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
      }
      await respond(()=>sourceLink(child.id).click({modifiers:['Control']}),'cancel');assert.equal(await page.locator('#f-title').inputValue(),source.title);assert.equal(await editor.inputValue(),draft);
      await page.locator('[data-reference-close]').click();assert.equal(await page.locator('.document-reference-preview').count(),0);
      const beforePerf=await page.evaluate(()=>JSON.stringify({docs:window.__workbenchPerf.docs,key:window.__workbenchPerf.docKey,page:window.__workbenchPerf.docPage}));
      await editor.fill('前文 [[物理');await page.waitForSelector('[data-reference-option]');
      await editor.press('ArrowDown');await editor.press('ArrowUp');await editor.press('Enter');
      const inserted=await editor.inputValue();assert.equal(inserted,'前文 [[ref-paper|'+referenced.title+']]');
      assert.equal(await page.evaluate(()=>JSON.stringify({docs:window.__workbenchPerf.docs,key:window.__workbenchPerf.docKey,page:window.__workbenchPerf.docPage})),beforePerf,'reference search never changes list pagination');
      await editor.press('Control+z');assert.equal(await editor.inputValue(),'前文 [[物理','inserting a reference has a native undo step');await editor.press('Escape');
      await editor.fill('保留前后文字');await editor.evaluate(e=>{e.setSelectionRange(2,2)});await page.locator('[data-md="wiki"]').click();await page.locator('#document-reference-search').fill('结构化');await page.waitForSelector('[data-reference-option]');await page.locator('#document-reference-search').press('Enter');
      assert.equal(await editor.inputValue(),'保留[[ref-child|'+child.title+']]前后文字');
      await editor.press('Control+Shift+k');await page.waitForSelector('#document-reference-search');assert.equal(await page.locator('#global-search-input').count(),0);await page.locator('#document-reference-search').press('Escape');
      await editor.fill('```text\n[[物理');await page.waitForTimeout(200);assert.equal(await page.locator('.document-reference-completion').count(),0,'code examples do not trigger completion');
      await editor.dispatchEvent('compositionstart');await editor.fill('[[物理');assert.equal(await page.locator('.document-reference-completion').count(),0);await editor.dispatchEvent('compositionend');await page.waitForSelector('[data-reference-option]');await editor.press('Escape');
      await editor.fill('[[不存在的候选项');await page.waitForSelector('.reference-completion-results .reference-status');await page.waitForFunction(()=>document.querySelector('.reference-completion-results')?.textContent.includes('没有找到'));await editor.press('Escape');
      await editor.fill('[[搜索失败');await page.waitForFunction(()=>document.querySelector('.reference-completion-results')?.textContent.includes('模拟搜索失败'));await editor.press('Escape');
      await editor.fill('[[慢查询');await page.waitForTimeout(180);await editor.fill('[[结构化');await page.waitForSelector('[data-reference-option]');await page.waitForTimeout(400);assert((await page.locator('.reference-completion-results').innerText()).includes(child.title));await editor.press('Escape');
      for(const zoom of [125,100]){
        await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();await editor.fill('[[物理');await page.waitForSelector('[data-reference-option]');
        const b=await page.locator('.document-reference-completion').boundingBox();assert(b.x>=0&&b.x+b.width<=2551&&b.y>=0&&b.y+b.height<=1234,'completion popup respects app zoom');await editor.press('Escape');
      }
      await editor.fill('[[物理');await page.waitForSelector('[data-reference-option]');await page.waitForFunction(()=>document.querySelector('#md-preview').textContent.includes('物理'));await shot('document-reference-completion',{fullPage:false});await editor.press('Enter');
      const finalBody=await editor.inputValue();await page.locator('#doc-save').click();await page.waitForFunction(()=>document.querySelector('#doc-save')?.disabled===false);assert.equal(source.body,finalBody);assert.equal(docWrites,1);
      await page.evaluate(()=>{const pdfPage={getViewport:({scale})=>({width:600*scale,height:840*scale,scale,transform:[scale,0,0,-scale,0,840*scale]}),render:()=>({promise:Promise.resolve()}),getTextContent:async()=>({items:[]}),cleanup:()=>{}};window.pdfjsLib={getDocument:()=>({promise:Promise.resolve({numPages:1,getPage:async()=>pdfPage})})}});
      await page.waitForSelector('#md-preview [data-agent-reference="ref-paper"]');await sourceLink(referenced.id).click({modifiers:['Control']});await page.waitForSelector('.lit-page canvas');
      assert.equal(await page.locator('.document-reference-preview').count(),0);assert.equal(await page.locator('#workbench-dialog').count(),0,'clean Ctrl-click opens the referenced PDF directly');
      assert.deepEqual(errors,[]);console.log('PASS: local reference previews/history, exact/broken/ambiguous/offline status, retry/late responses, unsaved draft protection; picker, [[ completion, keyboard/IME/undo, stable identities, independent paging, saved references and responsive themes. No model requests.');return;
    }
    if(pdfQualityOnly){
      const longProject='Two-stage fine-tuning of large language models for distribution network service restoration via CoT reasoning';
      const longTag='结构化输出与供电恢复的物理约束 <RAG> "测试"';
      const chipDoc=recentDocs.find(d=>d.kind==='note');chipDoc.projects=[longProject,'短项目'];chipDoc.tags=[longTag,'RAG'];paper.tags=[longTag,'RAG'];
      await page.setViewportSize({width:2550,height:1233});
      if(await page.locator('html').getAttribute('data-theme')!=='dark')await page.locator('#theme-btn').click();
      await page.evaluate(id=>window.ERWNav.open('note',id),chipDoc.id);await page.waitForSelector('#f-projects .project-chip-label');
      const chips=async(selector,width)=>{
        const values=await page.locator(selector+' .project-chip').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect(),label=e.querySelector('.project-chip-label'),b=e.querySelector('button').getBoundingClientRect();return {width:e.offsetWidth,height:e.offsetHeight,title:e.title,text:label.textContent,ellipsis:getComputedStyle(label).textOverflow,nowrap:getComputedStyle(label).whiteSpace,clipped:label.scrollWidth>label.clientWidth,buttonInside:b.left>=r.left&&b.right<=r.right+1&&b.top>=r.top&&b.bottom<=r.bottom+1}}));
        assert.equal(values.length,2);assert(values.every(v=>v.width===width&&v.height===22&&v.buttonInside&&v.ellipsis==='ellipsis'&&v.nowrap==='nowrap'),'equal-sized chips preserve accessible remove buttons: '+JSON.stringify(values));assert(values[0].clipped,'long labels are truncated instead of wrapping');return values;
      };
      for(const zoom of [100,125]){
        await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();
        for(const width of [2550,1280]){
          await page.setViewportSize({width,height:1233});await chips('#f-projects',160);
          assert.equal(await page.locator('#f-projects .project-chip').first().getAttribute('title'),longProject);
          assert((await page.locator('.meta-block').boundingBox()).height<=90*(zoom/100),'long projects keep compact metadata short');
        }
      }
      await page.setViewportSize({width:2550,height:1233});await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
      await shot('project-chips-editor-fullscreen',{fullPage:false});
      await page.locator('#meta-toggle').click();assert.equal((await chips('#f-tags',120))[0].title,longTag);
      await page.locator('[data-project-remove="1"]').click();assert.deepEqual(JSON.parse(await page.locator('#f-projects').getAttribute('data-projects')),[longProject]);
      await page.locator('#f-tags [data-tag-remove="1"]').click();assert.deepEqual(JSON.parse(await page.locator('#f-tags').getAttribute('data-tags')),[longTag]);
      await respond(()=>go('overview'),'discard');
      const installMock=()=>page.evaluate(()=>{
        window.__qualityRenders=0;window.__qualityCancels=0;
        const pdfPage={getViewport:({scale})=>({width:960*scale,height:540*scale,scale,transform:[scale,0,0,-scale,0,540*scale]}),render:({canvasContext:ctx,viewport:v,transform})=>{
          window.__qualityRenders++;ctx.setTransform(...transform);ctx.fillStyle='#fff';ctx.fillRect(0,0,v.width,v.height);ctx.fillStyle='#111';ctx.font=(14*v.scale)+'px sans-serif';ctx.fillText('Sharp vector text · PDF rendering quality',30*v.scale,50*v.scale);
          let reject,timer;const promise=new Promise((resolve,fail)=>{reject=fail;timer=setTimeout(resolve,window.__qualityDelay||40)});return {promise,cancel:()=>{window.__qualityCancels++;clearTimeout(timer);reject(Object.assign(new Error('cancelled'),{name:'RenderingCancelledException'}))}};
        },getTextContent:async()=>({items:[]}),cleanup:()=>{}};
        window.pdfjsLib={getDocument:()=>({promise:Promise.resolve({numPages:20,getPage:async()=>pdfPage})})};
      });
      await installMock();await go('literature');await page.locator('[data-paper="ui-paper"]').click();
      const rendered=()=>page.waitForFunction(()=>{const sc=document.querySelector('#lit-scroll'),v=sc.getBoundingClientRect(),visible=[...document.querySelectorAll('.lit-page-shell')].filter(e=>{const r=e.getBoundingClientRect();return r.bottom>v.top&&r.top<v.bottom});return !document.querySelector('#lit-pages').style.zoom&&visible.length&&visible.every(e=>e.querySelector('canvas')?.width>1&&e.querySelector('.lit-interaction-layer')?.onmousedown)&&!document.querySelector('.lit-page-error')});
      await rendered();await page.locator('#lit-toggle-side').click();await chips('#li-tags',120);
      await shot('project-chips-fullscreen',{fullPage:false});
      await page.locator('#lit-toggle-side').click();
      const wheelPdf=async(delta,count=1)=>{await page.locator('#lit-scroll').hover({position:{x:180,y:180}});await page.keyboard.down('Control');for(let i=0;i<count;i++)await page.mouse.wheel(0,delta);await page.keyboard.up('Control');await page.waitForTimeout(220);await rendered()};
      await wheelPdf(240,3); // Manual zoom small enough to test native DPR without hitting the pixel limit.
      const cdp=await page.context().newCDPSession(page);
      const resolution=()=>page.locator('.lit-page canvas').first().evaluate(e=>({width:e.width,height:e.height,cssWidth:parseFloat(e.style.width),screenWidth:e.getBoundingClientRect().width,screenHeight:e.getBoundingClientRect().height,dpr:devicePixelRatio}));
      for(const dpr of [1,2,3]){
        await cdp.send('Emulation.setDeviceMetricsOverride',{width:2550,height:1233,deviceScaleFactor:dpr,mobile:false});
        for(const zoom of [100,125]){
          await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();
          await page.waitForFunction(({density,zoom})=>{const e=document.querySelector('.lit-page canvas');return e&&Math.abs(e.width/parseFloat(e.style.width)-Math.max(2,density)*zoom/100)<.01},{density:dpr,zoom});
          const r=await resolution();assert(r.width/r.screenWidth>=Math.max(2,dpr)-.02,'canvas meets screen density at DPR '+dpr+' and '+zoom+'%');
        }
      }
      await cdp.send('Emulation.setDeviceMetricsOverride',{width:2550,height:1233,deviceScaleFactor:1,mobile:false});
      await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
      await wheelPdf(-240,8);assert(parseInt(await page.locator('#lit-zoom-label').innerText(),10)>=399);
      const large=await resolution();assert(large.width*large.height<=12*1024*1024&&large.width<=8192&&large.height<=8192,'large zoom obeys the per-page allocation limit');
      for(const target of [2,5,10,15,20,10,1]){
        await page.locator('#lit-scroll').evaluate((sc,n)=>{const el=document.querySelector(`.lit-page-shell[data-page="${n}"]`);sc.scrollTop=el.offsetTop-8},target);
        await page.waitForFunction(n=>document.querySelector(`.lit-page-shell[data-page="${n}"] canvas`)?.width>1,target);
        await page.waitForTimeout(180);
        const cache=await page.locator('.lit-page canvas').evaluateAll(es=>({pixels:es.reduce((sum,e)=>sum+e.width*e.height,0),count:es.length}));
        assert(cache.pixels<=40*1024*1024,'retained page pixels remain bounded after scrolling: '+JSON.stringify({target,cache}));
      }
      assert.equal(await page.locator('.lit-page-error').count(),0);
      const renders=await page.evaluate(()=>{window.__qualityDelay=400;return window.__qualityRenders}),cancels=await page.evaluate(()=>window.__qualityCancels);
      await page.locator('#lit-zoom-out').click();await page.waitForFunction(before=>window.__qualityRenders>before,renders);await page.locator('#lit-zoom-in').click();await rendered();
      assert(await page.evaluate(()=>window.__qualityCancels)>cancels,'superseded renders are actually cancelled');assert.equal(await page.locator('.lit-page-error').count(),0,'cancelled renders do not appear as page errors');
      const fixtureArg=process.argv.find(value=>value.startsWith('--pdf-fixture='));
      if(fixtureArg){
        const fixturePath=path.resolve(fixtureArg.slice('--pdf-fixture='.length)),pdfBytes=fs.readFileSync(fixturePath),cache=path.join(output,'pdfjs-3.11.174');fs.mkdirSync(cache,{recursive:true});
        for(const name of ['pdf.min.js','pdf.worker.min.js']){const file=path.join(cache,name);if(!fs.existsSync(file)){const response=await fetch('https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/'+name);assert(response.ok);fs.writeFileSync(file,Buffer.from(await response.arrayBuffer()))}}
        await page.context().route('**/qa-pdfjs/*',route=>route.fulfill({contentType:'application/javascript',path:path.join(cache,new URL(route.request().url()).pathname.split('/').pop())}));
        await page.route('**/api/literature/ui-paper/pdf',route=>route.fulfill({contentType:'application/pdf',body:pdfBytes}));
        await page.evaluate(()=>delete window.pdfjsLib);await page.addScriptTag({url:base+'/qa-pdfjs/pdf.min.js'});await page.evaluate(()=>window.pdfjsLib.GlobalWorkerOptions.workerSrc=location.origin+'/qa-pdfjs/pdf.worker.min.js');
        const pageArg=process.argv.find(value=>value.startsWith('--pdf-page=')),targetPage=Math.max(1,Math.trunc(Number(pageArg?.split('=')[1])||1));
        paper.last_page=targetPage;await page.locator('[data-paper="ui-paper"]').click();
        try{await page.waitForSelector(`.lit-page[data-page="${targetPage}"] canvas`)}catch(error){console.log('Real PDF diagnostics:',await page.evaluate(()=>({page:window.ERWLiterature.context().page,label:document.querySelector('#lit-page-label')?.textContent,text:document.querySelector('#lit-pages')?.textContent.slice(0,500),canvases:[...document.querySelectorAll('.lit-page')].map(e=>e.dataset.page)})),errors);await shot('pdf-real-failure',{fullPage:false});throw error}
        await page.waitForFunction(()=>window.ERWLiterature.context().page_text.length>100);await rendered();
        assert.equal(await page.locator('.lit-page-error').count(),0);assert((await page.locator(`.lit-page[data-page="${targetPage}"] canvas`).evaluate(e=>e.width/e.getBoundingClientRect().width))>1.9);
        await shot('pdf-sharp-real-fullscreen',{fullPage:false});
        await wheelPdf(-100);assert.equal(await page.locator('.lit-page-error').count(),0);await shot('pdf-sharp-real-zoom',{fullPage:false});
        await page.locator('#lit-toggle-side').click();await page.locator('[data-tab="info"]').click();await page.locator('#lit-fit').click();await page.waitForTimeout(180);await rendered();
        await shot('pdf-sharp-real-side-info',{fullPage:false});
      }
      assert.deepEqual(errors,[]);console.log('PASS: fixed single-line project/tag chips, full-name identity and remove controls; PDF supersampling, app zoom, DPR 1/2/3 transitions, large-page pixel/cache limits, scroll rehydration and render cancellation'+(fixtureArg?'; real PDF.js rendering verified':''));return;
    }
    if(overviewOnly){
      let scrollChecks=0,navChecks=0;
      const verify=async(label)=>{
        await page.waitForFunction(()=>document.querySelector('.overview-continue button'));
        await page.waitForFunction(()=>Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--vh-px'))*(parseFloat(document.documentElement.style.zoom)||1)-innerHeight)<1);
        await settleOverview();
        const frame=await page.evaluate(()=>{
          const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
          const root=document.querySelector('.overview-dashboard'),selectors=['.overview-preferences','.overview-continue','.overview-top-row','.overview-mid-row','.overview-ops-grid','.overview-lower-band'];
          return {root:rect(root),sections:selectors.map(selector=>({selector,...rect(root.querySelector(':scope > '+selector))})),scroll:document.documentElement.scrollWidth,width:innerWidth};
        });
        for(const section of frame.sections){assert(section.width>=frame.root.width-2,'overview sections use the full row: '+JSON.stringify({label,section,root:frame.root}));assert(section.left>=frame.root.left-1&&section.right<=frame.root.right+1,'section stays inside dashboard: '+label)}
        for(let i=1;i<frame.sections.length;i++)assert(frame.sections[i].top>=frame.sections[i-1].bottom-1,'sections retain their visible order without overlap: '+JSON.stringify({label,sections:frame.sections}));
        assert(frame.scroll<=frame.width+1,'no page horizontal overflow: '+label);
        assert.equal(await page.locator('#overview-continue button').count(),4,'all recent-work actions remain accessible');
        const sidebar=page.locator('#app>.sidebar'),before=await sidebar.boundingBox();
        assert(Math.abs(before.y)<1&&Math.abs(before.height-(await page.evaluate(()=>innerHeight)))<2,'browser navigation fills the viewport: '+JSON.stringify({label,before}));
        await page.evaluate(()=>window.scrollTo(0,Math.min(640,document.documentElement.scrollHeight-innerHeight)));
        const scrolled=await page.evaluate(()=>window.scrollY);
        if(scrolled>2){scrollChecks++;const after=await sidebar.boundingBox();assert(Math.abs(after.y-before.y)<1&&Math.abs(after.height-before.height)<1,'navigation stays fixed while the page scrolls: '+label)}
        const nav=page.locator('#sidebar-nav'),canScroll=await nav.evaluate(e=>e.scrollHeight>e.clientHeight+2);
        if(canScroll){navChecks++;const bounds=await nav.boundingBox();await page.mouse.move(bounds.x+bounds.width/2,bounds.y+bounds.height/2);const pageScroll=await page.evaluate(()=>window.scrollY);await page.mouse.wheel(0,440);await page.waitForFunction(()=>document.querySelector('#sidebar-nav').scrollTop>0);const after=await page.evaluate(()=>({page:window.scrollY,nav:document.querySelector('#sidebar-nav').scrollTop}));assert(Math.abs(after.page-pageScroll)<2,'scrolling navigation does not move the page: '+JSON.stringify({label,pageScroll,after}));await nav.evaluate(e=>e.scrollTop=0)}
        await page.evaluate(()=>window.scrollTo(0,0));
      };
      for(const density of ['cozy','compact']){
        if(await page.locator('html').getAttribute('data-density')!==density)await page.locator('#density-btn').click();
        for(const zoom of [100,125]){
          await page.setViewportSize({width:2550,height:1233});await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();
          for(const [width,height] of [[2550,1233],[2560,1440],[1920,1080],[1536,864],[1280,720],[1279,900],[1100,800]]){
            await page.setViewportSize({width,height});await verify(`${density} ${width}x${height} ${zoom}%`);
            if(width===2550&&zoom===100){await shot('overview-browser-fullscreen-'+density,{fullPage:false});await page.evaluate(()=>window.scrollTo(0,600));await shot('overview-browser-scrolled-'+density,{fullPage:false});await page.evaluate(()=>window.scrollTo(0,0))}
          }
        }
      }
      assert(scrollChecks>0&&navChecks>0,'the matrix includes real page and navigation scrolling');
      todos=[];for(const record of milestoneRows)deletedDocs.add(record.id);fixtureDashboard.upcoming_milestones=[];
      await page.setViewportSize({width:2550,height:1233});await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
      if(await page.locator('html').getAttribute('data-density')!=='cozy')await page.locator('#density-btn').click();
      if(await page.locator('html').getAttribute('data-theme')!=='dark')await page.locator('#theme-btn').click();
      await go('overview');await ready();await verify('full-screen empty tasks and milestones');
      assert.equal(await page.locator('[data-overview-check]').count(),0);
      await shot('overview-browser-fullscreen-empty-dark',{fullPage:false});
      await page.locator('#overview-stats-visible').uncheck();
      assert.equal(await page.locator('.heatmap-card').isVisible(),false);assert.equal(await page.locator('#overview-continue').isVisible(),true);assert.equal(await page.locator('.overview-task-card').isVisible(),true);
      const hidden=await page.locator('.overview-dashboard').evaluate(root=>{const rows=[...root.children].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.getBoundingClientRect());return rows.every((r,i)=>!i||r.top>=rows[i-1].bottom-1)});assert(hidden,'hiding statistics leaves no overlapping or misplaced rows');
      await page.locator('#overview-stats-visible').check();
      // The fixed-height shell must retain the resize handle and all three sidebar modes.
      const resizer=page.locator('.sidebar-resizer');
      for(const [key,mode] of [['Home','icon'],['End','full']]){
        await resizer.press(key);assert.equal(await page.locator('html').getAttribute('data-sidebar-mode'),mode);await verify('full-screen '+mode+' navigation');
      }
      for(let i=0;i<8;i++)await resizer.press('ArrowLeft');
      assert.equal(await page.locator('html').getAttribute('data-sidebar-mode'),'compact');await verify('full-screen compact navigation');
      await resizer.dblclick();assert.equal(await resizer.getAttribute('aria-valuenow'),'168');
      await page.setViewportSize({width:760,height:1000});
      assert(await page.locator('#app>.sidebar').evaluate(e=>e.getBoundingClientRect().height<160),'small-screen navigation remains compact');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.deepEqual(errors,[]);console.log('PASS: full-screen-first overview order and row widths, empty/populated states, fixed navigation with independent scrolling, both densities, 100/125% and responsive boundaries');return;
    }
    assert.equal(await page.locator('#overview-continue').isVisible(),true);
    await page.locator('#overview-stats-visible').uncheck();
    assert.equal(await page.locator('.heatmap-card').isVisible(),false);
    assert.equal(await page.locator('.rhythm-card').isVisible(),false);
    assert.equal(await page.locator('.overview-task-card').isVisible(),true,'hiding statistics preserves actionable tasks');
    await page.locator('#overview-stats-visible').check();
    await page.waitForFunction(()=>{const cards=[...document.querySelectorAll('.rhythm-card,.overview-task-card,.overview-milestone-card')].map(e=>e.getBoundingClientRect());return cards.every(b=>Math.abs(b.y-cards[0].y)<2)});
    assert.deepEqual(libraryRequests,[], 'Plain overview should not load math or diagram libraries');
    await page.waitForFunction(()=>document.querySelector('.overview-milestone-list')?.scrollTop>0);
    const aligned=async selectors=>{
      await page.mouse.move(5,5);
      const boxes=await Promise.all(selectors.map(s=>page.locator(s).boundingBox()));
      for(const b of boxes){assert(Math.abs(b.y-boxes[0].y)<2,'card tops align: '+selectors);assert(Math.abs(b.y+b.height-boxes[0].y-boxes[0].height)<2,'card bottoms align: '+selectors)}
    };
    const checkBands=async()=>{
      await aligned(['.heatmap-card','.overview-academic-grid']);
      await aligned(['.rhythm-card','.overview-task-card','.overview-milestone-card']);
      await aligned(['.overview-lower-left','.overview-recent-section']);
      await aligned(['.overview-today','.quick-capture-card']);
    };
    await checkBands();
    const taskIds=await page.locator('[data-overview-check]').evaluateAll(es=>es.map(e=>e.dataset.overviewCheck));
    assert.equal(taskIds.length,todos.filter(t=>!t.done).length);
    assert.equal(taskIds[0],'ui-urgent','same-date urgent tasks come first');
    assert(taskIds.indexOf('ui-next')<taskIds.indexOf('ui-old'),'near dates precede distant overdue dates');
    assert.equal(taskIds.at(-1),'ui-no-date','undated tasks come last');
    assert.equal(await page.locator('.overview-milestone-row').count(),milestoneRows.length,'all milestone pages are loaded');
    const windowMetrics=await page.evaluate(()=>['.overview-task-list','.overview-milestone-list'].map(s=>{const e=document.querySelector(s);return {height:e.clientHeight,scroll:e.scrollHeight,row:e.querySelector('.overview-task-row,.overview-milestone-row').offsetHeight}}));
    for(const m of windowMetrics){assert.equal(m.height,m.row*5);assert(m.scroll>m.height)}
    assert(await page.locator('.overview-milestone-list').evaluate(e=>{const r=e.querySelector('.is-nearest');return Math.abs(r.offsetTop-e.scrollTop+r.offsetHeight/2-e.clientHeight/2)<2}),'nearest milestone occupies the center row');
    const taskList=page.locator('.overview-task-list');
    await taskList.hover();await page.mouse.wheel(0,280);await page.waitForTimeout(100);assert(await taskList.evaluate(e=>e.scrollTop>0));
    await taskList.evaluate(e=>e.scrollTop=0);
    await page.waitForSelector('[data-recent-expanded="done"] .recent-activity-row');
    const titleStyle=await page.locator('.recent-card .row-title').first().evaluate(e=>({clamp:getComputedStyle(e).webkitLineClamp,white:getComputedStyle(e).whiteSpace,height:e.getBoundingClientRect().height,line:parseFloat(getComputedStyle(e).lineHeight)}));
    assert.equal(titleStyle.clamp,'2');assert.equal(titleStyle.white,'normal');assert(titleStyle.height<=titleStyle.line*2+1);
    assert((await page.locator('.recent-card-head').first().boundingBox()).height<=32);
    assert.equal(await page.locator('.overview-recent-group>.recent-card').count(),3,'activity cards retain the three-column layout');
    assert.equal(await page.locator('.recent-status').count(),15);
    assert(!(await page.locator('.recent-card-ideas .row-title').first().innerText()).startsWith('灵感·'));
    assert.equal(cleanupCalls,0,'completed tasks are retained until manual cleanup');
    console.log('PASS: aligned bands, five-row scrolling, task date/priority order, centered complete milestone history and two-line recent titles');
    assert.equal(await page.locator('[data-route="projects"]').count(),1);
    assert.equal(await page.locator('[data-route="research-overview"]').count(),0);
    const type=await page.evaluate(()=>({group:parseFloat(getComputedStyle(document.querySelector('.group-toggle')).fontSize),item:parseFloat(getComputedStyle(document.querySelector('.nav-item')).fontSize),weight:parseFloat(getComputedStyle(document.querySelector('.group-toggle')).fontWeight)}));
    assert(type.group<type.item&&type.weight>=600);
    assert.equal(await page.locator('.rhythm-day').count(),7);
    assert((await page.locator('.rhythm-goal').innerText()).includes('2'));
    await shot('overview');
    assert.equal(await page.locator('#page-eyebrow').count(),0);
    assert(!(await page.locator('#main').innerText()).includes('把学业周期'));
    const checkHeading=async()=>{
      const bar=await page.locator('.topbar').boundingBox();
      for(const selector of ['#page-title','#page-date']){const box=await page.locator(selector).boundingBox();assert(box.y>=bar.y&&box.y+box.height<=bar.y+bar.height+1,selector+' fits inside topbar')}
    };
    await checkHeading();
    assert((await page.locator('.overview-top-row').boundingBox()).height<260,'top cards have no forced empty height');
    assert((await page.locator('.overview-ops-grid').boundingBox()).height<360,'operations stay compact');
    await page.setViewportSize({width:2550,height:1233});await page.waitForTimeout(180);await checkHeading();await checkBands();await shot('overview-wide');
    await page.setViewportSize({width:1600,height:1000});await page.waitForTimeout(180);
    const small=await smallText();assert.deepEqual(small,[],'overview text is at least 11px');
    const recentNote=page.locator('.recent-card-notes .recent-activity-row').first(),recentId=await recentNote.getAttribute('data-open-doc');
    const readingDoc=docRecords.find(d=>d.id===recentId),originalReadingBody=readingDoc.body;
    readingDoc.body=Array.from({length:80},(_,i)=>`## 研究段落 ${i+1}\n\n${'这是一段用于验证阅读位置与分栏缩放的研究记录。'.repeat(5)}\n`).join('\n');
    await recentNote.click();await page.waitForFunction(id=>window.ERWCurrentDoc===id,recentId);
    assert.equal(await page.locator('[data-edit-mode=preview]').getAttribute('class'),'active','existing documents open in reading mode');
    assert.equal(await page.locator('#md-input').isVisible(),false);
    assert.equal(await page.locator('#f-title').isVisible(),true);
    assert.equal(await page.locator('#main .meta-block').getAttribute('class').then(x=>x.includes('compact')),true);
    await page.locator('#zoom-btn').click();await page.locator('#reading-font-size').selectOption('18');
    assert.equal(await page.locator('#md-preview').evaluate(e=>getComputedStyle(e).fontSize),'18px');
    await page.locator('#reading-font-size').selectOption('14');await page.keyboard.press('Escape');
    assert.equal(await page.locator('#f-title').inputValue(),docRecords.find(d=>d.id===recentId).title);
    await page.locator('[data-edit-mode=split]').click();
    assert.equal(await page.locator('#meta-toggle').getAttribute('aria-expanded'),'false');
    const layout=await page.evaluate(()=>({bottom:document.querySelector('.doc-editor').getBoundingClientRect().bottom,height:innerHeight,meta:document.querySelector('.meta-block').getBoundingClientRect().height}));
    assert(layout.height-layout.bottom>=5&&layout.height-layout.bottom<=12,'browser editor fills the bottom of the viewport: '+JSON.stringify(layout));
    assert(layout.meta<=40,'wide editor metadata fits on one compact line: '+JSON.stringify(layout));
    const wheel=async(selector,delta)=>{await page.locator(selector).hover();await page.keyboard.down('Control');await page.mouse.wheel(0,delta);await page.keyboard.up('Control')};
    const font=selector=>page.locator(selector).first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
    const editBefore=await font('#md-input'),previewBefore=await font('#md-preview'),rootZoom=await page.locator('html').evaluate(e=>e.style.zoom);
    await page.locator('#md-input').evaluate(e=>{e.selectionStart=e.selectionEnd=64;e.scrollTop=600});await page.waitForTimeout(180);
    const oppositeScroll=await page.locator('#md-preview').evaluate(e=>e.scrollTop);
    await wheel('#md-input',-75);await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('#md-input')).fontSize)>before,editBefore);
    assert.equal(await font('#md-preview'),previewBefore,'editor wheel zoom leaves preview scale untouched');
    assert.equal(await page.locator('#md-input').evaluate(e=>e.selectionStart),64,'font zoom preserves the editing cursor');
    assert(Math.abs(await page.locator('#md-preview').evaluate(e=>e.scrollTop)-oppositeScroll)<2,'zoom does not drive the other pane scroll sync');
    const enlargedEditor=await font('#md-input');await wheel('#md-input',45);
    await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('#md-input')).fontSize)<before,enlargedEditor);
    const editorScale=await font('#md-input');await page.waitForTimeout(180);
    await wheel('#md-preview',-95);await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('#md-preview')).fontSize)>before,previewBefore);
    assert.equal(await font('#md-input'),editorScale,'preview wheel zoom leaves editor scale untouched');
    assert.equal(await page.locator('html').evaluate(e=>e.style.zoom),rootZoom,'pane zoom does not zoom the application');
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),false,'zoom never edits document content');
    const listBefore=await font('#doc-list .title');await wheel('#doc-list',-65);await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('#doc-list .title')).fontSize)>before,listBefore);
    assert.equal(await font('#md-input'),editorScale,'list wheel zoom is also independent');
    const previewScale=await font('#md-preview');await page.locator('#md-preview').hover();await page.mouse.wheel(0,110);assert.equal(await font('#md-preview'),previewScale,'ordinary wheel scrolling does not change font size');
    await wheel('#md-preview',50);await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('#md-preview')).fontSize)<before,previewScale);
    assert.equal(await font('#md-input'),editorScale,'zooming the preview out remains independent');
    await shot('reading-wheel-browser');
    await page.setViewportSize({width:1100,height:720});
    await page.waitForFunction(()=>{const bottom=document.querySelector('.doc-editor').getBoundingClientRect().bottom;return innerHeight-bottom>=5&&innerHeight-bottom<=12});
    assert((await page.locator('.meta-block').boundingBox()).height<90,'medium-width metadata wraps into two compact lines');
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="125"]').click();
    await page.waitForFunction(()=>{const bottom=document.querySelector('.doc-editor').getBoundingClientRect().bottom;return innerHeight-bottom>=5&&innerHeight-bottom<=16});
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();await page.setViewportSize({width:1600,height:1000});
    await page.locator('[data-editor-zoom=edit]').selectOption('100');await page.locator('[data-editor-zoom=preview]').selectOption('100');
    await page.evaluate(()=>localStorage.setItem('erwDocumentListZoom','100'));
    await go('literature');await page.locator('.lit-shell').waitFor();
    await page.evaluate(()=>{
      window.__readingPdfRenders=0;
      const page={getViewport:({scale})=>({width:600*scale,height:840*scale,scale,transform:[scale,0,0,-scale,0,840*scale]}),render:({canvasContext:ctx,viewport:v})=>{window.__readingPdfRenders++;ctx.fillStyle='#fff';ctx.fillRect(0,0,v.width,v.height);return {promise:Promise.resolve()}},getTextContent:async()=>({items:[]}),cleanup:()=>{}};
      window.pdfjsLib={getDocument:()=>({promise:Promise.resolve({numPages:3,getPage:async()=>page})})};
    });
    await page.locator('[data-paper="ui-paper"]').click();await page.locator('.lit-page canvas').first().waitFor();
    const pdfLayout=await page.locator('.lit-shell').boundingBox();assert(1000-pdfLayout.y-pdfLayout.height<=12,'browser PDF also fills the bottom');
    await page.locator('#lit-scroll').hover({position:{x:240,y:180}});
    const pdfPoint=await page.locator('#lit-scroll').evaluate(e=>{const r=e.getBoundingClientRect();return {x:r.left+240,y:r.top+180}});
    const pdfAnchor=()=>page.evaluate(point=>{const shells=[...document.querySelectorAll('.lit-page-shell')],el=shells.find(e=>{const r=e.getBoundingClientRect();return point.y>=r.top&&point.y<=r.bottom}),r=el.getBoundingClientRect();return {page:el.dataset.page,u:(point.x-r.left)/r.width,v:(point.y-r.top)/r.height}},pdfPoint);
    const pdfBefore=await pdfAnchor(),renderBefore=await page.evaluate(()=>window.__readingPdfRenders),percentBefore=await page.locator('#lit-zoom-label').innerText();
    await page.keyboard.down('Control');for(let i=0;i<5;i++)await page.mouse.wheel(0,-24);await page.keyboard.up('Control');
    await page.waitForFunction(before=>document.querySelector('#lit-zoom-label').textContent!==before,percentBefore);
    await page.waitForFunction(()=>!document.querySelector('#lit-pages').style.zoom&&document.querySelector('.lit-page canvas'));
    const pdfAfter=await pdfAnchor();assert.equal(pdfAfter.page,pdfBefore.page);assert(Math.abs(pdfAfter.v-pdfBefore.v)<.015,'PDF wheel zoom holds the point under the mouse');
    assert(await page.evaluate(()=>window.__readingPdfRenders)<=renderBefore+4,'continuous wheel gesture batches expensive PDF renders');
    assert.equal(await page.locator('html').evaluate(e=>e.style.zoom),rootZoom);
    const enlargedPdf=parseInt(await page.locator('#lit-zoom-label').innerText(),10);await page.mouse.move(pdfPoint.x,pdfPoint.y);await page.keyboard.down('Control');await page.mouse.wheel(0,75);await page.keyboard.up('Control');
    await page.waitForFunction(before=>parseInt(document.querySelector('#lit-zoom-label').textContent,10)<before,enlargedPdf);
    await page.waitForFunction(()=>!document.querySelector('#lit-pages').style.zoom&&document.querySelector('.lit-page canvas'));
    const percentZoomed=await page.locator('#lit-zoom-label').innerText();await page.locator('#lit-toggle-side').click();await page.locator('[data-tab=notes]').click();await page.locator('#lit-note').waitFor();
    const noteBefore=await font('#lit-note');await wheel('#lit-note',-85);await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('#lit-note')).fontSize)>before,noteBefore);
    assert.equal(await page.locator('#lit-zoom-label').innerText(),percentZoomed,'side-note zoom never changes PDF scale');
    await page.locator('#lit-fit').click();await page.waitForFunction(()=>{const e=document.querySelector('#lit-scroll');return e.scrollWidth<=e.clientWidth+2});
    await shot('pdf-wheel-browser');
    assert.deepEqual(errors,[]);console.log('PASS: compact metadata and full-height browser workspaces; independent Ctrl+wheel for editor, preview, lists, PDF and side notes; PDF anchoring and batched redraw');
    readingDoc.body=originalReadingBody;
    if(readingOnly)return;
    await go('overview');await ready();
    for(let i=0;i<2;i++){
      await go('projects');await page.waitForSelector('.project-manager');
      assert.equal(await page.locator('.project-id,.project-id-note').count(),0);
      assert(!(await page.locator('#main').innerText()).includes('proj_internal_'));
      assert((await page.locator('.project-manager-head').boundingBox()).height<65);
      assert((await page.locator('.project-manager-card').first().boundingBox()).height<240);
      const heights=await page.locator('.project-manager-card').evaluateAll(es=>es.map(e=>e.getBoundingClientRect().height));
      assert(Math.max(...heights)-Math.min(...heights)<1,'short, long and empty descriptions use equal card heights');
      const rows=await page.locator('.project-manager-card').evaluateAll(es=>es.map(e=>({top:e.offsetTop,metrics:e.querySelector('.project-card-metrics').offsetTop,actions:e.querySelector('.project-card-actions').offsetTop})));
      for(const row of rows){const peers=rows.filter(x=>x.top===row.top);assert(Math.max(...peers.map(x=>x.metrics))-Math.min(...peers.map(x=>x.metrics))<1);assert(Math.max(...peers.map(x=>x.actions))-Math.min(...peers.map(x=>x.actions))<1)}
      if(i===0){await shot('projects');await page.locator('[data-project-edit]').first().click();assert(!(await page.locator('#modal-body').innerText()).includes('proj_internal_'));assert.equal(await page.locator('#pm-display-name').isVisible(),true);await page.locator('#pm-cancel').click()}
      await go('overview');await ready();assert.equal(await page.locator('[data-route="projects"]').count(),1);
    }
    console.log('PASS: stable project navigation and sidebar hierarchy');

    await page.locator('#overview-todo-title').fill('新增研究任务');await page.locator('#overview-todo-title').press('Enter');
    await page.waitForSelector('[data-overview-check="ui-new-todo"]');assert.equal(writes,1);
    await respond(()=>page.locator('[data-overview-check="ui-todo"]').click(),'cancel');
    assert.equal(await page.locator('[data-overview-check="ui-todo"]').isChecked(),false);assert.equal(writes,1);
    await respond(()=>page.locator('[data-overview-check="ui-todo"]').click(),'confirm');
    await page.waitForFunction(()=>!document.querySelector('[data-overview-check="ui-todo"]'));assert.equal(writes,2);
    failWrite=true;await respond(()=>page.locator('[data-overview-check="ui-new-todo"]').click(),'confirm');
    await page.waitForFunction(()=>document.querySelector('[data-overview-check="ui-new-todo"]')?.disabled===false);
    assert.equal(await page.locator('[data-overview-check="ui-new-todo"]').isChecked(),false);failWrite=false;
    console.log('PASS: inline Todo add, completion confirmation, cancellation and failed-save recovery');

    await page.locator('[data-open-doc="ui-milestone"]').click();await page.waitForSelector('#f-title');
    assert.equal(await page.locator('#f-title').inputValue(),milestone.title);assert.equal(await page.locator('#md-input').inputValue(),milestone.body);
    assert.equal(await page.locator('[data-ms-view="docs"].active').count(),1);
    await go('journals');await page.waitForSelector('[data-doc-kind="journal"] .doc-compact-meta .mark-badge');
    assert.equal(await page.locator('.doc-item').first().locator('.mark-badge').count(),2);
    const colors=await page.locator('.doc-compact-meta .mark-badge').evaluateAll(es=>es.map(e=>({color:getComputedStyle(e).color,border:getComputedStyle(e).borderTopColor,radius:getComputedStyle(e).borderRadius})));
    assert.notEqual(colors[0].color,colors[1].color);assert.notEqual(colors[0].border,colors[1].border);assert.equal(colors[0].radius,'5px');
    await shot('document');assert.deepEqual(await smallText(),[],'document controls are at least 11px');
    assert.equal(await page.locator('#doc-selection-toolbar').isVisible(),false);
    assert.equal(await page.locator('[data-doc-pick]').first().isVisible(),false);
    const plus=await page.locator('#new-doc').boundingBox(),trash=await page.locator('#doc-batch-toggle').boundingBox();
    assert(Math.abs(plus.y-trash.y)<2&&trash.x>=plus.x+plus.width&&trash.x-plus.x-plus.width<10,'batch entry sits next to the plus button');
    const savedBody=await page.locator('#md-input').inputValue();await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill(savedBody+'\n未保存的编辑');
    await page.locator('#doc-batch-toggle').click();
    assert.equal(await page.locator('#doc-selection-toolbar').isVisible(),true);
    assert.equal(await page.locator('[data-doc-pick]').first().isVisible(),true);
    assert((await page.locator('#md-input').inputValue()).includes('未保存的编辑'),'entering selection preserves unsaved edits');
    await page.locator('[data-doc-pick]').first().check();await page.locator('#doc-clear-selection').click();
    assert.equal(await page.locator('#doc-selection-toolbar').isVisible(),false);
    assert.equal(await page.locator('[data-doc-pick]:checked').count(),0);
    assert((await page.locator('#md-input').inputValue()).includes('未保存的编辑'),'exiting selection preserves unsaved edits');
    await page.locator('#doc-batch-toggle').click();
    await page.locator('#doc-select-all').check();
    assert.equal(await page.locator('[data-doc-pick]:checked').count(),2);
    await page.locator('[data-perf-page="next"]').click();await page.waitForSelector('[data-doc-pick="ui-journal-3"]');
    await page.locator('[data-doc-pick="ui-journal-3"]').check();
    assert.equal(await page.locator('#doc-selected-count').innerText(),'已选 3 条');
    await respond(()=>page.locator('#doc-delete-selected').click(),'cancel');assert.equal(deletedDocs.size,0);
    failDocId='ui-journal-2';await respond(()=>page.locator('#doc-delete-selected').click(),'confirm');
    await page.waitForFunction(()=>document.querySelector('#doc-selected-count')?.textContent==='已选 1 条');
    assert(deletedDocs.has('ui-journal')&&deletedDocs.has('ui-journal-3'));
    assert.equal(await page.locator('[data-doc-pick="ui-journal-2"]').isChecked(),true,'failed deletion stays selected after pagination clamps');
    assert.equal(await page.locator('#md-input').count(),0,'deleted active document is removed from the editor');
    failDocId='';await respond(()=>page.locator('#doc-delete-selected').click(),'confirm');
    await page.waitForFunction(()=>document.querySelector('#doc-selected-count')?.textContent==='已选 0 条');
    assert.equal(await page.locator('[data-doc-pick]').count(),0);
    assert.equal(await page.locator('#doc-selection-toolbar').isVisible(),false,'successful deletion returns to normal browsing');
    console.log('PASS: cross-page document selection, confirmation cancellation, partial failure retention and empty last-page recovery');

    await go('todos');await page.waitForSelector('#todo-clear-completed');
    assert.equal(await page.locator('#todo-selection-toolbar').isVisible(),false);
    assert.equal(await page.locator('[data-todo-pick]').first().isVisible(),false);
    const add=await page.locator('#todo-add').boundingBox(),todoTrash=await page.locator('#todo-batch-toggle').boundingBox();
    assert(Math.abs(add.y-todoTrash.y)<2&&todoTrash.x>=add.x+add.width,'Todo batch entry sits beside Add');
    await respond(()=>page.locator('[data-todo-check="ui-next"]').click(),'cancel');
    assert.equal(await page.locator('[data-todo-check="ui-next"]').getAttribute('aria-checked'),'false');
    await respond(()=>page.locator('[data-todo-check="ui-next"]').click(),'confirm');
    await page.waitForFunction(()=>document.querySelector('[data-todo-check="ui-next"]')?.getAttribute('aria-checked')==='true');
    const pendingBefore=todos.filter(t=>!t.done).map(t=>t.id);
    await respond(()=>page.locator('#todo-clear-completed').click(),'cancel');assert.equal(cleanupCalls,0);
    await respond(()=>page.locator('#todo-clear-completed').click(),'confirm');
    await page.waitForFunction(()=>document.querySelector('#todo-clear-completed')?.disabled===true);
    assert.equal(cleanupCalls,1);assert.deepEqual(todos.map(t=>t.id),pendingBefore,'manual cleanup preserves all pending tasks');
    await page.locator('#todo-batch-toggle').click();
    await page.locator('[data-todo-pick="ui-extra-0"]').check();await page.locator('[data-todo-pick="ui-extra-1"]').check();
    failTodoId='ui-extra-1';await respond(()=>page.locator('#todo-delete-selected').click(),'confirm');
    await page.waitForFunction(()=>document.querySelector('#todo-selected-count')?.textContent==='已选 1 条');
    assert(!todos.some(t=>t.id==='ui-extra-0'));assert(todos.some(t=>t.id===failTodoId));
    assert.equal(await page.locator('[data-todo-pick="ui-extra-1"]').isChecked(),true);
    await page.locator('#todo-clear-selection').click();failTodoId='';
    assert.equal(await page.locator('#todo-selection-toolbar').isVisible(),false);
    assert.equal(await page.locator('[data-todo-pick]').first().isVisible(),false);
    await shot('todo-batch');
    console.log('PASS: Todo multiselect deletion and explicit manual-only completed cleanup');
    const beforeGraph=graphRequests.length;
    await go('graph');await page.waitForSelector('#graph-smart-toolbar');
    assert.equal(graphRequests.length-beforeGraph,1,'Graph page should fetch data exactly once');
    assert.equal(await page.locator('#graph-smart-toolbar').count(),1);
    assert.equal(await page.evaluate(()=>window.__knowledgeGraphEngine.scopeProject),'示例项目');
    assert.equal(await page.evaluate(()=>window.__knowledgeGraphEngine.selectedId),null,'scope opens an overview without selecting a topic');
    assert.equal(await page.locator('.graph-diagnostics').getAttribute('open'),null,'graph diagnostics start collapsed');
    let releaseGraph;graphGate=new Promise(resolve=>releaseGraph=resolve);
    await go('todos');await page.waitForSelector('.todo-page');
    await go('graph');await page.locator('.page-loading').waitFor();
    assert.equal(await page.locator('.todo-page').count(),0,'new page loading never displays the old page');
    const graphResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/graph');
    await go('todos');await page.waitForSelector('.todo-page');releaseGraph();graphGate=null;await graphResponse;
    assert.equal(await page.locator('.todo-page').count(),1,'a late graph response cannot replace the current page');
    await go('graph');await page.waitForSelector('#graph-smart-toolbar');
    await page.evaluate(async()=>{
      const first=document.createElement('div'),second=document.createElement('div');
      first.id='qa-lazy-markdown';second.id='qa-lazy-math';
      first.className=second.className='md-preview';document.body.append(first,second);
      second.textContent='$$a^2+b^2=c^2$$';
      await Promise.all([
        window.ERWMarkdown.renderInto(first,'$$E=mc^2$$\n\n```mermaid\nflowchart LR\n A --> B\n```'),
        window.ERWRenderLibraries.renderMath([second]),
      ]);
    });
    assert.equal(await page.locator('#qa-lazy-markdown .mermaid svg').count(),1);
    assert.equal(await page.locator('#qa-lazy-markdown mjx-container svg').count(),1);
    assert.equal(await page.locator('#qa-lazy-math mjx-container svg').count(),1);
    assert.equal(libraryRequests.filter(url=>url.includes('mathjax')).length,1);
    assert.equal(libraryRequests.filter(url=>url.includes('mermaid')).length,1);
    await page.locator('#qa-lazy-markdown').evaluate(node=>node.remove());
    await page.locator('#qa-lazy-math').evaluate(node=>node.remove());
    console.log('PASS: graph fetches once; math and diagrams load once on demand');
    assert.equal(await page.locator('[data-gview]').count(),0);assert.equal(await page.locator('.graph-view-label').innerText(),'关系网络');
    console.log('PASS: milestone document opens directly, multicolor classification badges, single graph view');

    await go('overview');await ready();await page.mouse.move(500,200);
    await page.waitForTimeout(800);
    const ball=page.locator('#erw-fab-ball');
    const b=await ball.boundingBox();assert(Math.abs(b.x+b.width/2-1600)<3,'right dock exposes half the ball');
    await ball.hover();await page.waitForTimeout(250);const revealed=await ball.boundingBox();assert(revealed.x+revealed.width<=1601);
    await page.mouse.move(revealed.x+26,revealed.y+26);await page.mouse.down();await page.mouse.move(10,400,{steps:12});await page.mouse.up();await page.mouse.move(500,200);await page.waitForTimeout(800);
    const left=await ball.boundingBox();assert(Math.abs(left.x+left.width/2)<3,'left dock exposes half the ball');
    await ball.hover();await page.waitForTimeout(250);await ball.click();await page.waitForSelector('#erw-fab-panel:not([hidden])');
    assert.equal(await page.locator('[data-resize-edge]').count(),8);
    const panel=page.locator('#erw-fab-panel');
    const checkAssistantRow=async()=>{const boxes=await Promise.all(['#fab-persona','#fab-history','#fab-new','#fab-close'].map(s=>page.locator(s).boundingBox()));const panelBox=await panel.boundingBox();const mid=boxes[0].y+boxes[0].height/2;for(const b of boxes){assert(Math.abs(b.y+b.height/2-mid)<2,'assistant controls share one row');assert(b.x>=panelBox.x&&b.x+b.width<=panelBox.x+panelBox.width,'assistant controls fit inside panel')}};
    await checkAssistantRow();
    const resize=async(edge,dx,dy)=>{const h=await page.locator(`[data-resize-edge="${edge}"]`).boundingBox();await page.mouse.move(h.x+h.width/2,h.y+h.height/2);await page.mouse.down();await page.mouse.move(h.x+h.width/2+dx,h.y+h.height/2+dy,{steps:6});await page.mouse.up()};
    let before=await panel.boundingBox();await resize('nw',-100,-50);let after=await panel.boundingBox();assert(after.width>before.width+70&&after.height>before.height+30);
    await checkAssistantRow();
    before=after;await resize('w',-50,0);after=await panel.boundingBox();assert(after.width>before.width+30);
    for(const edge of ['n','e','s','w','ne','nw','se','sw']){
      before=await panel.boundingBox();
      await resize(edge,edge.includes('e')?-15:edge.includes('w')?15:0,edge.includes('s')?-15:edge.includes('n')?15:0);
      after=await panel.boundingBox();
      if(/[ew]/.test(edge))assert(after.width<before.width-10,edge+' changes width');
      if(/[ns]/.test(edge))assert(after.height<before.height-10,edge+' changes height');
    }
    await page.locator('#fab-close').click();await ball.hover();await ball.click();const restored=await panel.boundingBox();assert(Math.abs(restored.width-after.width)<3);
    await resize('w',-420,0);await checkAssistantRow();await shot('assistant-wide');
    await resize('w',700,0);await checkAssistantRow();
    assert((await panel.locator('.fab-head').boundingBox()).height<50,'assistant header stays compact at minimum width');
    await shot('assistant');await page.locator('#fab-close').click();
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="125"]').click();await ball.hover();await ball.click();
    await checkBands();
    console.log('Heatmap zoom:',await page.evaluate(()=>['.heatmap-card','.heatmap-scroll','.heatmap-plot','.heatmap-stage','.heatmap-cells','.heatmap-axis'].map(s=>{const e=document.querySelector(s),c=getComputedStyle(e);return [s,e.clientHeight,e.scrollHeight,c.height,c.maxHeight,c.minHeight,c.overflowY]})));
    await shot('overview-zoom125');
    assert(await page.locator('.heatmap-scroll').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'all seven heatmap rows fit after zoom');
    const z=await panel.boundingBox();assert(z.x>=0&&z.y>=0&&z.x+z.width<=1601&&z.y+z.height<=1001,'zoomed panel stays on screen');
    before=z;await resize('w',-50,0);after=await panel.boundingBox();assert(after.width>before.width+30);
    await checkAssistantRow();
    await page.locator('#fab-close').click();
    console.log('PASS: left/right half docking, hover reveal, all resize handles, persistence and 125% zoom');

    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
    await checkHeading();
    await page.setViewportSize({width:1100,height:900});await shot('overview-1100');
    await page.setViewportSize({width:760,height:1000});await shot('overview-760');
    console.log('Narrow layout:',await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,overflow:Array.from(document.querySelectorAll('#app *')).filter(e=>e.getBoundingClientRect().right>innerWidth+1&&getComputedStyle(e).position!=='fixed'&&!e.closest('#sidebar-nav')).slice(0,12).map(e=>[e.className,e.getBoundingClientRect().right])})));
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no horizontal overflow on narrow viewport');
    assert((await page.locator('.sidebar').boundingBox()).height<160,'narrow-screen navigation stays compact');
    await page.goto(base+'/#research-overview');await ready();assert.equal(new URL(page.url()).hash,'#overview');
    assert.equal(await page.locator('#desktop-titlebar').isVisible(),false,'browser mode has no desktop chrome');
    deletedDocs.clear();
    await page.addInitScript(()=>{
      const state={title:'科研工作台',tray_available:true,maximized:false,hidden:false,close_action:localStorage.getItem('qa-close-action')||'tray'};
      window.__desktopCommands=[];
      const invoke=(name,update={})=>{window.__desktopCommands.push(name);Object.assign(state,update);return Promise.resolve({...state})};
      window.pywebview={api:{
        desktop_get_state:()=>Promise.resolve({...state}),
        desktop_hide:()=>invoke('hide',{hidden:true}),
        desktop_minimize:()=>invoke('minimize',{hidden:true}),
        desktop_close:()=>invoke('close:'+state.close_action,{hidden:state.close_action==='tray'}),
        desktop_set_close_action:action=>{localStorage.setItem('qa-close-action',action);return invoke('preference:'+action,{close_action:action})},
        desktop_toggle_maximize:()=>invoke('maximize',{maximized:!state.maximized}),
        desktop_resize:edge=>invoke('resize:'+edge),
      }};
    });
    await page.setViewportSize({width:1600,height:1000});
    failBootstrapOnce=true;
    // Desktop dimensions below are measured at 100%, independently of the earlier zoom fixture.
    syncState.preferences.uiScale='100';
    await page.goto(base);await ready();
    assert.equal(bootstrapFailures,1,'a temporary bootstrap read failure recovers automatically');
    await page.waitForSelector('html[data-desktop="true"]');
    const chrome=page.locator('#desktop-titlebar');
    assert.equal(await chrome.isVisible(),true);
    assert.equal(Math.round((await chrome.boundingBox()).height),48);
    assert.equal(await page.locator('[data-desktop-resize]').count(),8);
    assert((await page.locator('#app').boundingBox()).y>=48,'content starts below native chrome');
    const controlBoxes=await Promise.all(['#desktop-minimize','#desktop-maximize','#desktop-close'].map(s=>page.locator(s).boundingBox()));
    assert(controlBoxes[0].x<controlBoxes[1].x&&controlBoxes[1].x<controlBoxes[2].x,'Windows controls use the right-side order');
    assert(controlBoxes[2].x+controlBoxes[2].width>=1599,'close control sits at the right edge');
    assert.equal(await page.locator('.desktop-traffic-lights').count(),0);
    await page.waitForFunction(()=>getComputedStyle(document.documentElement).zoom==='1');
    assert.equal(Math.round((await page.locator('[data-group="core"] .nav-group-head').boundingBox()).height),36);
    assert.equal(Math.round((await page.locator('.nav-item[data-route="overview"]').boundingBox()).height),30);
    const researchToggle=page.locator('[data-group-toggle="research"]');
    const icon=page.locator('[data-group="research"] .group-disclosure');
    assert.equal(await researchToggle.getAttribute('aria-expanded'),'true');
    const openTransform=await icon.evaluate(e=>getComputedStyle(e).transform);
    await researchToggle.click();
    assert.equal(await researchToggle.getAttribute('aria-expanded'),'false');
    assert.equal(await page.locator('[data-route="journals"]').isVisible(),false);
    const collapsedTransform=await icon.evaluate(e=>getComputedStyle(e).transform);
    assert.notEqual(collapsedTransform,openTransform,'diamond rotates with group state');
    await researchToggle.click();
    assert.equal(await researchToggle.getAttribute('aria-expanded'),'true');
    assert.equal(await icon.evaluate(e=>getComputedStyle(e).transform),openTransform);
    await page.locator('#desktop-maximize').click();
    await page.waitForSelector('html[data-window-maximized="true"]');
    assert.equal(await page.locator('[data-desktop-resize="e"]').isVisible(),false);
    await page.locator('.desktop-page-tools .page-heading').dblclick();
    await page.waitForSelector('html[data-window-maximized="false"]');
    assert.equal(await page.locator('[data-desktop-resize="e"]').isVisible(),true);
    for(const zoom of [100,125]){
      await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();
      for(const edge of ['n','e','s','w','ne','nw','se','sw']){
        const b=await page.locator(`[data-desktop-resize="${edge}"]`).boundingBox();
        assert(b.width>=6.9&&b.height>=6.9,'resize target has a stable physical size: '+edge+' '+zoom);
        const target=await page.evaluate(({x,y})=>document.elementFromPoint(x,y)?.dataset.desktopResize,{x:b.x+b.width/2,y:b.y+b.height/2});
        assert.equal(target,edge,'resize target stays above page overlays');
        await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.up();
        await page.waitForFunction(e=>window.__desktopCommands.includes('resize:'+e),edge);
      }
    }
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
    await page.locator('#desktop-minimize').click();
    await go('settings');await page.locator('[data-set-tab="desktop"]').click();await page.waitForSelector('#desktop-close-action');
    await page.locator('#desktop-close-action').selectOption('quit');await page.locator('#desktop-settings-save').click();
    await page.waitForFunction(()=>document.querySelector('#desktop-close').title==='退出应用');
    await page.locator('#desktop-close').click();
    await page.locator('#desktop-close-action').selectOption('tray');await page.locator('#desktop-settings-save').click();
    await page.waitForFunction(()=>document.querySelector('#desktop-close').title.includes('托盘'));
    await shot('desktop-settings');
    await page.evaluate(()=>window.ERWNav.open('journal','ui-journal'));
    await page.waitForSelector('#md-input');
    await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill('# 未保存的桌面内容');
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),true);
    await page.locator('#desktop-close').click();
    assert.equal(await page.locator('#md-input').inputValue(),'# 未保存的桌面内容');
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),true);
    await shot('desktop-editor');
    // Navigate with the existing unsaved-document guard, then check shell zoom.
    await respond(()=>go('overview'),'discard');await ready();
    await shot('desktop-overview');
    const previousDensity=await page.locator('html').getAttribute('data-density');
    if(previousDensity!=='cozy')await page.locator('#density-btn').click();
    await page.setViewportSize({width:2550,height:1233});
    for(const zoom of [100,125]){
      await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();await settleOverview();
      const sidebar=page.locator('#app>.sidebar'),before=await sidebar.boundingBox();
      assert(Math.abs(before.y-48)<1&&Math.abs(before.height-1185)<2,'desktop navigation fits below the titlebar at '+zoom+'%');
      await page.evaluate(()=>window.scrollTo(0,600));assert(await page.evaluate(()=>scrollY>2),'desktop overview exercises actual scrolling');
      const after=await sidebar.boundingBox();assert(Math.abs(after.y-48)<1&&Math.abs(after.height-before.height)<1,'desktop navigation remains fixed when full-screen content scrolls');
      await page.evaluate(()=>window.scrollTo(0,0));
    }
    if(previousDensity!=='cozy')await page.locator('#density-btn').click();
    await page.setViewportSize({width:1600,height:1000});
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="125"]').click();
    await page.waitForTimeout(150);
    assert.equal(Math.round((await chrome.boundingBox()).height),48,'titlebar height is stable under app zoom');
    assert((await page.locator('#app').boundingBox()).y>=47.9);
    assert(await page.evaluate(()=>Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--vh-px'))*1.25-(innerHeight-48))<1));
    await shot('desktop-zoom125');
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
    await page.evaluate(()=>window.dispatchEvent(new CustomEvent('workbench:window-state',{detail:{tray_available:false}})));
    assert((await page.locator('#desktop-close').getAttribute('title')).includes('任务栏'));
    await page.setViewportSize({width:1100,height:800});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    assert.deepEqual(await page.evaluate(()=>window.__desktopCommands.filter(c=>!c.startsWith('resize:'))),['maximize','maximize','minimize','preference:quit','close:quit','preference:tray','close:tray']);
    await page.reload();await ready();
    await go('settings');await page.locator('[data-set-tab="desktop"]').click();await page.waitForSelector('#desktop-close-action');
    assert.equal(await page.locator('#desktop-close-action').inputValue(),'tray');
    console.log('PASS: right-side chrome, close preferences, rotating disclosure, swapped row heights and desktop zoom');
    await page.setViewportSize({width:1600,height:1000});
    assert.equal(await page.locator('#app .topbar').isVisible(),false,'old toolbar is removed from the desktop layout');
    for(const id of ['page-title','page-date','sidebar-toggle','weather-pill','theme-btn','density-btn','zoom-btn','reload-btn']){
      assert.equal(await chrome.locator('#'+id).count(),1,id+' moved to native titlebar');
      const bounds=await page.locator('#'+id).boundingBox();
      assert(bounds.y>=0&&bounds.y+bounds.height<=49,id+' fits in the single titlebar');
    }
    const refreshBox=await page.locator('#reload-btn').boundingBox(),minimizeBox=await page.locator('#desktop-minimize').boundingBox();
    assert(refreshBox.x+refreshBox.width<=minimizeBox.x+1&&minimizeBox.x-refreshBox.x-refreshBox.width<10,'refresh is beside minimize');
    assert.equal((await page.locator('#reload-btn').innerText()).trim(),'','refresh button is icon-only');
    await page.locator('#reload-btn').click();
    assert.equal(await page.locator('#reload-menu').isVisible(),true);
    assert.equal(await page.locator('#reload-btn').getAttribute('aria-expanded'),'true');
    await respond(()=>page.locator('[data-system-action="restart"]').click(),'cancel');
    assert.equal(await page.locator('#reload-menu').isVisible(),false,'canceling restart leaves the app open');
    await go('overview');await ready();
    await shot('single-titlebar-light');
    await page.locator('#theme-btn').click();
    await page.waitForSelector('html[data-theme="dark"]');
    await shot('single-titlebar-dark');
    const contrast=async selectors=>page.evaluate(selectors=>{
      const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
      const ctx=canvas.getContext('2d',{willReadFrequently:true});
      const rgb=value=>{ctx.clearRect(0,0,1,1);ctx.fillStyle=value;ctx.fillRect(0,0,1,1);return [...ctx.getImageData(0,0,1,1).data]};
      const blend=(front,back)=>front.slice(0,3).map((c,i)=>c*front[3]/255+back[i]*(1-front[3]/255));
      const luminance=values=>values.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
      return selectors.flatMap(selector=>Array.from(document.querySelectorAll(selector)).filter(el=>el.getClientRects().length).map(el=>{
        const layers=[];let bg=[17,24,39],node=el;
        while(node){const c=rgb(getComputedStyle(node).backgroundColor);layers.push(c);if(c[3]===255)break;node=node.parentElement}
        for(const c of layers.reverse())bg=blend(c,bg);
        const fg=blend(rgb(getComputedStyle(el).color),bg);
        const a=luminance(fg),b=luminance(bg);return {selector,text:el.textContent.slice(0,30),ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
      }));
    },selectors);
    const overviewContrast=await contrast(['#page-title','#page-date','#weather-text','#density-btn','#zoom-btn','.nav-item','.card-head h3','.row-meta','.quick-action b','.recent-card .row-title']);
    assert.deepEqual(overviewContrast.filter(x=>x.ratio<4.5),[],'dark text has readable contrast');
    await page.locator('#reload-btn').click();await shot('refresh-menu-dark');
    assert.deepEqual((await contrast(['#reload-menu button'])).filter(x=>x.ratio<4.5),[]);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#reload-menu').isVisible(),false);
    await page.evaluate(()=>window.ERWNav.open('journal','ui-journal'));
    await page.waitForSelector('#md-input');
    await shot('editor-dark');
    assert.deepEqual((await contrast(['#f-title','#md-input','.md-preview h1','#doc-save','.toolbar button','.project-chip'])).filter(x=>x.ratio<4.5),[]);
    const readable=async selectors=>{
      for(const s of selectors)assert(await page.locator(s).count()>0,'contrast check has real content: '+s);
      assert.deepEqual((await contrast(selectors)).filter(x=>x.ratio<4.5),[],'dark page text contrast: '+selectors);
    };
    const darkSurfaces=async selectors=>{
      const light=await page.evaluate(selectors=>{
        const c=document.createElement('canvas');c.width=c.height=1;const ctx=c.getContext('2d',{willReadFrequently:true});
        return selectors.flatMap(s=>[...document.querySelectorAll(s)].filter(e=>{const r=e.getBoundingClientRect();return e.getClientRects().length&&r.width>=24&&r.height>=16}).map(e=>({selector:s,element:e.id||e.className||e.tagName,color:getComputedStyle(e).backgroundColor}))).filter(x=>{
          ctx.clearRect(0,0,1,1);ctx.fillStyle=x.color;ctx.fillRect(0,0,1,1);const rgba=[...ctx.getImageData(0,0,1,1).data];
          return rgba[3]>180&&Math.min(...rgba.slice(0,3))>140;
        });
      },selectors);
      assert.deepEqual(light,[],'module surfaces must not retain a light background');
    };
    await go('literature');await page.waitForSelector('.lit-page canvas');await page.locator('#lit-toggle-side').click();
    for(const density of ['compact','cozy']){
      if(await page.evaluate(d=>document.documentElement.dataset.density!==d,density))await page.locator('#density-btn').click();
      for(const [width,height,zoom] of [[1600,1000,100],[1100,720,100],[1600,1000,125],[1100,720,125]]){
        await page.setViewportSize({width,height});await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();await page.waitForTimeout(140);
        await page.locator('.lit-info-extra summary').click();await page.locator('#li-bibtex').scrollIntoViewIfNeeded();assert.equal(await page.locator('#li-bibtex').inputValue(),paper.bibtex);
        await page.locator('#li-save').scrollIntoViewIfNeeded();assert(await page.locator('#li-save').isVisible(),'all metadata can scroll to its save action');assert.equal(await page.locator('#li-title').inputValue(),paper.title);
        await page.locator('.lit-info-extra summary').click();
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'unified metadata retains a bounded workspace');
      }
    }
    await page.setViewportSize({width:1600,height:1000});await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
    if(await page.evaluate(()=>document.documentElement.dataset.density!=='compact'))await page.locator('#density-btn').click();
    await shot('literature-unified-metadata-dark');
    for(const density of ['compact','cozy']){
      if(await page.evaluate(d=>document.documentElement.dataset.density!==d,density))await page.locator('#density-btn').click();
      for(const zoom of [100,125]){
        await page.setViewportSize({width:2559,height:1527});await page.locator('#zoom-btn').click();await page.locator(`[data-zoom="${zoom}"]`).click();
        for(const route of ['overview','projects','todos','journals','notes','summaries','literature','agent','billing','settings']){
          await go(route);await page.waitForTimeout(80);
          const bounds=await page.evaluate(()=>{const box=e=>e.getBoundingClientRect().toJSON(),main=document.querySelector('#main');return {sidebar:box(document.querySelector('#app>.sidebar')),main:box(main),child:box(main.firstElementChild),width:innerWidth,scroll:document.documentElement.scrollWidth}});
          assert(Math.abs(bounds.main.left-bounds.sidebar.right)<1&&Math.abs(bounds.main.right-bounds.width)<2,'canvas fills available width: '+JSON.stringify({route,density,zoom,bounds}));
          assert(bounds.child.left-bounds.main.left<=17*zoom/100&&bounds.main.right-bounds.child.right<=17*zoom/100,'workspace retains only its normal edge padding: '+JSON.stringify({route,density,zoom,bounds}));
          assert(bounds.scroll<=bounds.width+1,'wide canvas has no horizontal page overflow');
          if(['journals','notes','summaries'].includes(route)){
            if((await page.locator('#meta-toggle').getAttribute('aria-expanded'))==='false')await page.locator('#meta-toggle').click();
            assert(await page.locator('.meta-block').evaluate(e=>e.scrollHeight<=e.clientHeight+1),'all document kinds expand metadata without internal scrolling');
            if(density==='compact'&&zoom===100){
              const fits=await page.evaluate(()=>document.querySelector('.meta-block').getBoundingClientRect().bottom<=document.querySelector('.doc-editor-content').getBoundingClientRect().bottom+1);
              assert(fits,'all expanded metadata is visible together at normal wide-screen size: '+route);
              if(route==='notes'){
                await shot('metadata-expanded-wide-dark');await page.locator('#meta-toggle').click();await shot('metadata-collapsed-wide-dark');
                await page.locator('#theme-btn').click();await shot('metadata-collapsed-wide-light');await page.locator('#meta-toggle').click();await shot('metadata-expanded-wide-light');await page.locator('#theme-btn').click();
              }
            }
          }
        }
      }
    }
    await page.setViewportSize({width:1600,height:1000});await page.locator('#zoom-btn').click();await page.locator('[data-zoom="100"]').click();
    if(await page.evaluate(()=>document.documentElement.dataset.density!=='compact'))await page.locator('#density-btn').click();
    await go('billing');await page.waitForSelector('.billing-card');
    await readable(['.billing-card .k','.billing-card .v','.billing-card .s','.billing-table td','.billing-table th','.billing-tabs button']);
    await darkSurfaces(['.billing-page *']);await shot('billing-dark');
    await page.locator('[data-btab="records"]').click();await page.waitForSelector('#billing-filter');
    await readable(['.billing-table td','.billing-table th','.billing-badge']);await darkSurfaces(['.billing-page *']);await shot('billing-records-dark');
    await page.locator('[data-btab="prices"]').click();await page.waitForSelector('#billing-prices-text');
    await readable(['#billing-prices-text','.billing-sub']);await darkSurfaces(['.billing-page *']);await shot('billing-prices-dark');
    console.log('PASS: complete expanded metadata, unclipped fold buttons, full-width canvases across 10 routes at both densities and 100/125% zoom; dark billing');
    await go('journals');await page.waitForSelector('#md-input');
    await readable(['.doc-list-panel .mark-badge','.mark-chip.on','.nav-ico']);
    assert.notEqual(await page.locator('.mark-badge').first().evaluate(e=>getComputedStyle(e).color),await page.locator('.row-meta').first().evaluate(e=>getComputedStyle(e).color),'classification labels retain their color');
    await go('summaries');await page.waitForSelector('.doc-item .mark-badge');
    await readable(['.doc-item .mark-badge','.nav-item']);await shot('summaries-dark');
    await go('todos');await page.waitForSelector('.todo-row');
    await darkSurfaces(['.todo-row']);
    await readable(['.todo-title','.todo-row .row-meta','.todo-row time','.todo-row .badge','.todo-row button']);
    await shot('todos-dark');
    await go('milestones');await page.locator('[data-ms-view="timeline"]').click();
    await page.waitForSelector('.mdt-card.month-cluster');
    await darkSurfaces(['.mdt-ruler','.mdt-stats','.mdt-scale','.mdt-card']);
    await readable(['.mdt-month-label','.mdt-date-label','.mdt-stat','.mdt-status-copy strong','.mdt-status-copy span','.mdt-month-cluster-title strong','.mdt-month-cluster-title span']);
    await shot('milestone-month-dark');
    await page.locator('.mdt-card.month-cluster').first().click();await page.waitForSelector('.mdt-drawer-item');
    await readable(['.mdt-drawer-copy strong','.mdt-drawer-copy span','.mdt-drawer-year','.mdt-drawer-monthday']);
    await shot('milestone-drawer-dark');await page.locator('.mdt-drawer-head>.ghost-btn').click();
    await page.locator('.mdt-scale button').filter({hasText:'周'}).click();await page.waitForSelector('.mdt-card-date');
    await readable(['.mdt-card-date','.mdt-card-title']);await shot('milestone-week-dark');
    await page.locator('[data-ms-view="list"]').click();await page.waitForSelector('.timeline-card');
    await darkSurfaces(['.timeline-card']);await readable(['.timeline-card strong','.timeline-card .row-meta','.timeline-date']);
    await shot('milestone-list-dark');
    await go('agent');await page.waitForSelector('.agent-message-body h2');
    await page.locator('.agent-reasoning summary').click();
    await darkSurfaces(['.agent-side-head','.agent-chat-head','.agent-messages','.agent-bubble','.agent-composer']);
    await readable(['.agent-side-head h3','#agent-chat-title','.agent-session strong','.agent-session small','.agent-message-body p','.agent-message-body h2','.agent-message-body code','.agent-msg-meta','.agent-reasoning summary','.agent-reasoning-body','#agent-input','.agent-preset-label','.agent-avatar']);
    await shot('agent-dark');
    await go('literature');await page.waitForSelector('.lit-shell');
    // The actual reader controller and UI run with a deterministic in-memory page renderer.
    // This avoids a CDN dependency and tests workspace colors without modifying real PDFs.
    await page.evaluate(()=>{
      const page={getViewport:({scale})=>({width:400*scale,height:560*scale,scale,transform:[scale,0,0,-scale,0,560*scale]}),
        render:({canvasContext:ctx,viewport:v})=>{ctx.fillStyle='#fff';ctx.fillRect(0,0,v.width,v.height);ctx.fillStyle='#111';ctx.font='18px serif';ctx.fillText('PDF document keeps its original colors',25,50);return {promise:Promise.resolve()}},
        getTextContent:async()=>({items:[]}),cleanup:()=>{}};
      window.pdfjsLib={getDocument:()=>({promise:Promise.resolve({numPages:1,getPage:async()=>page})})};
    });
    await page.waitForSelector('[data-paper="ui-paper"]');
    await page.locator('[data-paper="ui-paper"]').click();await page.waitForSelector('.lit-page canvas');
    assert.equal(await page.locator('.lit-side').isVisible(),false,'empty information sidebar stays closed by default');
    const fitted=()=>page.locator('#lit-scroll').evaluate(e=>e.scrollWidth<=e.clientWidth+2);
    await page.waitForFunction(()=>{const e=document.querySelector('#lit-scroll');return e.scrollWidth<=e.clientWidth+2});
    assert.equal(await fitted(),true,'PDF defaults to the available reader width');
    await page.locator('#lit-focus').click();
    assert.equal(await page.locator('.lit-library').isVisible(),false);assert.equal(await page.locator('.lit-side').isVisible(),false);
    await page.waitForFunction(()=>{const e=document.querySelector('#lit-scroll');return e.scrollWidth<=e.clientWidth+2});
    await shot('literature-focus-dark');
    await page.locator('#lit-focus').click();assert.equal(await page.locator('.lit-library').isVisible(),true);
    await page.locator('#lit-toggle-side').click();
    await darkSurfaces(['.lit-library-head','.lit-toolbar','.lit-canvas-scroll']);
    await readable(['.lit-library-head h3','.lit-side-tabs button','#li-title','#li-authors','#li-year','.lit-info label','#lit-area','#lit-page-label','#lit-zoom-label']);
    assert.equal(await page.locator('.lit-page').evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)','PDF paper remains white');
    await shot('literature-dark');
    await page.locator('.lit-side-tabs [data-tab="notes"]').click();await page.waitForSelector('#lit-note');
    await readable(['#lit-note']);await shot('literature-notes-dark');
    await go('overview');await ready();await page.waitForFunction(()=>document.querySelector('.overview-milestone-list').scrollTop>0);
    const rail=page.locator('.overview-milestone-rail'),ring=page.locator('.is-nearest .milestone-ring'),list=page.locator('.overview-milestone-list');
    assert.equal(await rail.count(),1,'all milestone rings share one continuous rail');
    assert.equal(await page.locator('.milestone-ring').count(),milestoneRows.length);
    const railBefore=await rail.boundingBox(),ringBefore=await ring.boundingBox();
    assert(Math.abs(railBefore.x+railBefore.width/2-ringBefore.x-ringBefore.width/2)<1,'rings align with the common rail');
    await list.evaluate(e=>e.scrollTop+=40);
    const railAfter=await rail.boundingBox(),ringAfter=await ring.boundingBox();
    assert(Math.abs(railBefore.y-railAfter.y)<1&&Math.abs(railBefore.height-railAfter.height)<1,'rail stays fixed while scrolling');
    assert(Math.abs(ringAfter.y-ringBefore.y+40)<1,'rings move with their milestones along the rail');
    await page.locator('#overview-ms-center').click();
    assert(await list.evaluate(e=>{const r=e.querySelector('.is-nearest');return Math.abs(r.offsetTop-e.scrollTop+r.offsetHeight/2-e.clientHeight/2)<2}));
    assert.equal(await ring.evaluate(e=>getComputedStyle(e,'::after').animationName),'none','reduced motion disables ring animation');
    await page.emulateMedia({reducedMotion:'no-preference'});
    assert.equal(await ring.evaluate(e=>getComputedStyle(e,'::after').animationName),'milestone-orbit');
    await page.evaluate(()=>document.documentElement.dataset.animations='off');
    assert.equal(await ring.evaluate(e=>getComputedStyle(e,'::after').animationName),'none','app animation preference is respected');
    await page.evaluate(()=>document.documentElement.dataset.animations='on');await page.emulateMedia({reducedMotion:'reduce'});
    await readable(['.mini-ms-date strong']);await shot('overview-timeline-dark');
    console.log('PASS: dark todo, milestone month/week/list/drawer, Agent, PDF workspace, colored classifications and moving milestone rings');
    await go('focus');await page.waitForSelector('#focus-apply');await page.locator('#focus-apply').click();
    await readable(['#toast-stack .toast']);await darkSurfaces(['#toast-stack .toast']);await shot('toast-dark');
    await go('settings');
    for(const tab of ['general','knowledge','service','literature','academic','weather','rss','llm','interface','sync','desktop']){
      await page.locator(`[data-set-tab="${tab}"]`).click();await page.waitForTimeout(160);
      await darkSurfaces(['#settings-panel *:not([type="color"])']);
      const bad=(await contrast(['#settings-panel h3','#settings-panel .row-title','#settings-panel .row-meta','#settings-panel .field-help','#settings-panel .field>label','#settings-panel input:not([type="color"]):not([type="checkbox"])','#settings-panel textarea','#settings-panel select','#settings-panel button:not(:disabled)'])).filter(x=>x.ratio<4.5);
      assert.deepEqual(bad,[],'all settings tabs remain readable: '+tab);
    }
    await page.locator('[data-set-tab="knowledge"]').click();await page.waitForSelector('[data-kt-template]');
    await shot('settings-knowledge-dark');
    await page.locator('[data-kt-template]').first().click();await page.waitForSelector('#kt-template-edit');
    await readable(['#modal-title','#kt-template-edit','#kt-template-cancel']);await darkSurfaces(['#modal','#kt-template-edit']);await shot('settings-template-dark');
    await page.locator('#kt-template-cancel').click();
    await page.locator('#kt-add').click();await page.waitForSelector('#kt-id');
    await readable(['#kt-id','#kt-label','#kt-template']);await darkSurfaces(['#modal','#kt-template']);await shot('settings-new-type-dark');
    await page.locator('#modal-close').click();
    await page.locator('#km-icon-trigger').click();await page.waitForSelector('.compact-icon-menu');
    await darkSurfaces(['.compact-icon-menu']);await shot('settings-icons-dark');await page.locator('[data-km-icon]').first().click();
    await page.locator('[data-km-delete]').first().click();await page.waitForSelector('#workbench-dialog');
    await readable(['#workbench-dialog-title','#workbench-dialog-message','#workbench-dialog button']);await darkSurfaces(['#workbench-dialog']);
    assert.equal(await page.locator('[data-dialog-result="cancel"]').evaluate(e=>e===document.activeElement),true,'destructive actions focus Cancel');
    await shot('confirmation-dark');await page.keyboard.press('Escape');await page.waitForSelector('#workbench-dialog',{state:'detached'});
    await page.locator('#theme-btn').click();await page.locator('[data-km-delete]').first().click();await page.waitForSelector('#workbench-dialog');
    await readable(['#workbench-dialog-title','#workbench-dialog-message','#workbench-dialog button']);await shot('confirmation-light');
    await page.locator('[data-dialog-result="cancel"]').click();await page.locator('#theme-btn').click();
    await page.locator('#erw-fab-ball').hover();await page.locator('#erw-fab-ball').click();await page.waitForSelector('#erw-fab-panel:not([hidden])');
    await darkSurfaces(['#erw-fab-panel','.fab-head','.fab-foot','.fab-compose']);
    await readable(['.fab-title strong','#fab-input','#fab-send']);await page.locator('#fab-shot-page').click();await page.waitForSelector('.fab-notice.error');
    await readable(['.fab-notice.error']);await shot('floating-assistant-dark');await page.locator('#fab-close').click();
    console.log('PASS: all 11 settings tabs, template/type/icon dialogs, shared notifications, floating assistant and themed confirmations');

    await go('notes');await page.waitForSelector('#new-doc');const writesBeforeDrafts=docWrites;
    await page.locator('#new-doc').click();await page.waitForSelector('[data-doc-draft]');
    assert.equal(await page.evaluate(()=>window.ERWDesktop.documentDraft()),true);
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),false);
    await page.locator('#doc-save').click();assert.equal(docWrites,writesBeforeDrafts,'an untouched template never persists');
    await go('overview');await ready();assert.equal(docWrites,writesBeforeDrafts);
    await go('notes');await page.waitForSelector('#new-doc');await page.locator('#new-doc').click();await page.waitForSelector('[data-doc-draft]');
    const template=await page.locator('#md-input').inputValue();
    await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill(template+'temporary');await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill(template);
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),false,'reverting to the template is not a change');
    await go('overview');await ready();assert.equal(docWrites,writesBeforeDrafts);
    await go('notes');await page.waitForSelector('#new-doc');await page.locator('#new-doc').click();await page.waitForSelector('[data-doc-draft]');
    await page.locator('#f-title').fill('保存这份新文档');
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),true,'metadata edits count as changes');
    await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill('# 实验结果\n\n这里是修改后的内容。');
    await respond(()=>page.locator('[data-route="overview"]').click(),'cancel');
    assert.equal(await page.locator('#f-title').inputValue(),'保存这份新文档');assert.equal(docWrites,writesBeforeDrafts);
    failSave=true;await respond(()=>page.locator('[data-route="overview"]').click(),'save');
    await page.waitForFunction(()=>document.querySelector('#doc-save')?.disabled===false);
    assert.equal(await page.evaluate(()=>document.documentElement.dataset.route),'notes');assert.equal(docWrites,writesBeforeDrafts);
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),true,'failed save retains the modified draft');
    failSave=false;await respond(()=>go('overview'),'save');await ready();
    assert.equal(docWrites,writesBeforeDrafts+1,'first save creates exactly one document');
    const newDoc=docRecords.find(d=>d.title==='保存这份新文档');assert(newDoc&&!newDoc.draft);
    await page.evaluate(id=>window.ERWNav.open('note',id),newDoc.id);await page.waitForSelector('#md-input');
    await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill('# 第二次修改');await page.locator('#doc-save').click();
    await page.waitForFunction(()=>!window.ERWDesktop.hasUnsavedChanges());
    assert.equal(docRecords.filter(d=>d.title==='保存这份新文档').length,1,'later saves update the same document');
    await page.locator('#new-doc').click();await page.waitForSelector('[data-doc-draft]');await page.locator('[data-edit-mode=edit]').click();await page.locator('#md-input').fill('# 放弃的草稿');
    const savedCount=docRecords.length;
    await respond(()=>go('overview'),'discard');await ready();assert.equal(docRecords.length,savedCount,'discard never writes or deletes persisted documents');
    await go('milestones');await page.waitForSelector('#new-ms');await page.locator('#new-ms').click();await page.waitForSelector('[data-doc-draft]');
    assert.equal(await page.evaluate(()=>window.ERWDesktop.hasUnsavedChanges()),false);
    await go('overview');await ready();assert.equal(docRecords.length,savedCount,'untouched milestone drafts also disappear');
    await page.emulateMedia({reducedMotion:'no-preference'});
    assert.equal(await page.locator('.degree-progress-track i').evaluate(e=>getComputedStyle(e,'::after').animationName),'overview-water-glint');
    await page.evaluate(()=>document.documentElement.dataset.animations='off');
    assert.equal(await page.locator('.degree-progress-track i').evaluate(e=>getComputedStyle(e,'::after').animationName),'none');
    await page.evaluate(()=>document.documentElement.dataset.animations='on');await page.emulateMedia({reducedMotion:'reduce'});
    assert.equal(await page.locator('.degree-progress-track i').evaluate(e=>getComputedStyle(e,'::after').animationName),'none');
    console.log('PASS: untouched/reverted drafts, metadata edits, cancel, save failure, first save, updates, discard, milestone drafts and optional overview motion');
    await go('graph');await page.waitForSelector('#graph-smart-toolbar');
    await page.evaluate(()=>window.__knowledgeGraphEngine.selectNode('ui-journal'));
    await page.locator('#graph-bundle').click();await page.waitForSelector('#opt-bundle-list');
    const selectionBounds=await page.locator('#modal').boundingBox();
    assert(selectionBounds.height>=600&&selectionBounds.width>=900);
    await page.locator('#opt-bundle-generate').click();await page.waitForSelector('#opt-bundle-content');
    const exportBounds=await page.locator('#modal').boundingBox(),textBounds=await page.locator('#opt-bundle-content').boundingBox();
    assert(Math.abs(selectionBounds.height-exportBounds.height)<2,'selection and export keep a fixed dialog size');
    assert(textBounds.height>=450&&textBounds.width>=850,'export textarea has room for many lines');
    assert.equal(await page.locator('#opt-bundle-content').evaluate(e=>getComputedStyle(e).resize),'none');
    assert(await page.locator('#opt-bundle-content').evaluate(e=>e.scrollHeight>e.clientHeight));
    assert.deepEqual((await contrast(['#modal-title','#opt-bundle-content','#opt-bundle-copy'])).filter(x=>x.ratio<4.5),[]);
    await shot('markdown-export-dark');
    await page.locator('#theme-btn').click();await page.waitForSelector('html[data-theme="light"]');
    await page.waitForTimeout(220);
    await shot('markdown-export-light');
    await page.setViewportSize({width:1000,height:700});
    await page.waitForFunction(()=>Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--vh-px'))-(innerHeight-48))<1);
    const smallModal=await page.locator('#modal').boundingBox();
    assert(smallModal.x>=0&&smallModal.y>=48&&smallModal.x+smallModal.width<=1001&&smallModal.y+smallModal.height<=701,'fixed export dialog adapts to smaller work areas: '+JSON.stringify(smallModal));
    await page.locator('#opt-bundle-done').click();
    await page.setViewportSize({width:1600,height:1000});
    await page.locator('#zoom-btn').click();await page.locator('[data-zoom="125"]').click();
    for(const id of ['page-title','page-date','weather-pill','theme-btn','density-btn','zoom-btn','reload-btn']){
      const b=await page.locator('#'+id).boundingBox();assert(b.y>=0&&b.y+b.height<=49,id+' remains inside the titlebar at 125%');
    }
    await shot('single-titlebar-zoom125');
    console.log('PASS: one titlebar, refresh dropdown, fixed Markdown export, dark contrast and 125% zoom');
    // This section verifies both themes independently of previous checks.
    if(await page.locator('html').getAttribute('data-theme')!=='light')await page.locator('#theme-btn').click();
    await go('settings');await page.locator('[data-set-tab="sync"]').click();await page.waitForSelector('#sync-url');
    assert.equal(await page.locator('.sync-wrap').isVisible(),false,'sync button hidden while disabled');
    await page.locator('#sync-url').fill('http://192.168.1.10:8765');await page.locator('#sync-test').click();await page.waitForFunction(()=>document.querySelector('#sync-test-result').textContent.includes('连接成功'));
    await page.locator('#sync-mode').selectOption('manual');await page.locator('#sync-save').click();await page.waitForFunction(()=>!document.querySelector('.sync-wrap').hidden);
    assert.equal(await page.locator('#desktop-sync-slot .sync-wrap').count(),1,'sync button in desktop titlebar');
    assert.equal(await page.locator('#sync-more svg.sync-chevron').count(),1,'sync dropdown uses a crisp vector chevron');
    assert.equal((await page.locator('#sync-more').textContent()).trim(),'','dropdown is not a text glyph');
    const syncBounds=await page.locator('.sync-wrap').boundingBox(),reloadBounds=await page.locator('#reload-btn').boundingBox();
    assert(syncBounds.x+syncBounds.width<=reloadBounds.x,'sync precedes refresh and minimize');
    await page.locator('#sync-now').click();await page.waitForFunction(()=>document.querySelector('.sync-wrap').dataset.phase==='synced');assert.equal(syncRuns,1);
    await page.locator('#sync-more').click();
    assert.equal(await page.locator('#sync-more').getAttribute('aria-expanded'),'true');
    assert.notEqual(await page.locator('#sync-more svg').evaluate(e=>getComputedStyle(e).transform),'none','expanded chevron rotates');
    await shot('sync-menu-light');
    await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/sync/check')),page.locator('#sync-menu [data-sync-check]').click()]);assert.equal(syncChecks,1);
    syncState.phase='conflict';syncState.conflicts=1;syncState.changes=[{key:'doc:ui-journal',code:'!',doc_id:'ui-journal',label:'实验记录',scope:'documents'}];await page.evaluate(()=>window.ERWSync.poll());
    await page.locator('#sync-more').click();await page.locator('#sync-menu [data-sync-conflict]').click();await page.waitForSelector('.sync-conflict-modal textarea');
    await shot('sync-conflict-light');
    await page.locator('#theme-btn').click();await page.waitForSelector('html[data-theme="dark"]');
    await readable(['.sync-conflict textarea','.sync-conflict .sync-caption','#modal-footer button']);await darkSurfaces(['.sync-conflict textarea','#modal']);await shot('sync-conflict-dark');
    await respond(()=>page.locator('[data-sync-choice="both"]').click());await page.waitForSelector('#modal-backdrop',{state:'hidden'});assert.equal(syncResolves,1);
    await page.locator('[data-set-tab="sync"]').click();await page.waitForSelector('#sync-mode');await shot('sync-settings-dark');
    await page.locator('#sync-mode').selectOption('auto');await page.locator('#sync-save').click();await page.waitForSelector('#sync-mode');assert.equal(syncState.config.mode,'auto');
    await page.locator('#sync-mode').selectOption('off');await page.locator('#sync-save').click();await page.waitForFunction(()=>document.querySelector('.sync-wrap').hidden);
    console.log('PASS: centralized sync settings, disabled/active/auto modes, desktop placement, Git status, conflict comparison and resolution in light/dark themes');
    assert.deepEqual(errors,[]);
    console.log('PASS: responsive layout, legacy overview redirect and no browser errors');
    console.log('Screenshots:',output);
  }finally{await browser?.close();await new Promise(resolve=>server.close(resolve))}
})().catch(e=>{console.error(e);process.exitCode=1});
