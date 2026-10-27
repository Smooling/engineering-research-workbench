/* Embedded Agent workspace: one conversation, with tasks, memory and skills. */
(()=>{
  'use strict';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const $=(s,r=document)=>r.querySelector(s);
  const labels={queued:'排队中',running:'执行中',pausing:'正在停止',paused:'已暂停',interrupted:'执行中断',waiting_approval:'等待你确认',completed:'已完成',failed:'失败',cancelled:'已停止'};
  let panelHost=null,tab='chat',timer=null,selected='',cursor=0,log=[],generation=0;
  async function api(path,body){const r=await fetch('/api/agent/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.message||d.error||r.status);return d}
  const toast=(s,bad=false)=>window.ERWToast?.(s,bad);
  const tabs=[['chat','对话'],['runs','任务'],['memory','记忆'],['skills','技能'],['rag','RAG'],['settings','设置']];
  function close(){open('chat')}
  function open(initial='chat'){
    tab=tabs.some(([id])=>id===initial)?initial:'chat';
    if(!$('#agent-workspace')){location.hash='agent';return}
    mount();
  }
  function mount(){
    const panel=$('#agent-system-panel'),nav=$('#agent-workspace-tabs');
    if(!panel||!nav)return;
    const changed=panelHost!==panel;panelHost=panel;
    if(!nav.children.length){
      nav.innerHTML=tabs.filter(([id])=>id!=='chat').map(([id,label])=>`<button type="button" role="tab" id="agent-tab-${id}" data-as-tab="${id}" aria-controls="agent-system-content">${label}</button>`).join('');
      nav.querySelectorAll('[data-as-tab]').forEach((button,index)=>{
        button.onclick=()=>{tab=button.dataset.asTab;load()};
        button.onkeydown=event=>{const key=event.key;if(!['ArrowLeft','ArrowRight','Home','End'].includes(key))return;event.preventDefault();const buttons=nav.querySelectorAll('button'),next=key==='Home'?0:key==='End'?buttons.length-1:(index+(key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();buttons[next].click()};
      });
    }
    $('#as-back-chat',panel).onclick=()=>{close();$('#agent-input')?.focus()};
    if(changed){clearInterval(timer);timer=setInterval(()=>{if(!panelHost?.isConnected){clearInterval(timer);timer=null;return}if(tab==='runs')refreshRuns().catch(()=>{})},2500)}
    load();
  }
  async function load(){
    if(!panelHost)return;
    const sequence=++generation;
    $('#agent-workspace-tabs')?.querySelectorAll('[data-as-tab]').forEach(b=>{const active=b.dataset.asTab===tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1});
    const chat=$('#agent-chat-panel');if(chat)chat.hidden=tab!=='chat';
    panelHost.hidden=tab==='chat';
    if(tab==='chat'){window.ERWAgentPage?.refresh?.().catch(error=>toast(error.message,true));return}
    $('.as-content',panelHost).setAttribute('aria-labelledby','agent-tab-'+tab);
    const root=document.createElement('div');root.innerHTML='<p>正在载入…</p>';
    $('.as-content',panelHost).replaceChildren(root);
    try{if(tab==='runs')await runs(root);else if(tab==='memory')await memory(root);else if(tab==='skills')await skills(root);else if(tab==='rag')await rag(root);else await settings(root)}catch(e){if(sequence===generation&&root.isConnected)root.innerHTML=`<p class="as-error">${esc(e.message)}</p>`}
  }
  async function runs(root){
    root.innerHTML='<div class="as-section-head"><div><h3>当前会话任务</h3><p class="as-hint">对话中发送的消息会自动在这里记录进度。确认草稿后，可继续同一个任务。</p></div><button type="button" class="primary-btn" id="as-go-chat">返回对话</button></div><div id="as-runs-list"></div><section id="as-run-detail"></section>';
    $('#as-go-chat',root).onclick=()=>{open('chat');$('#agent-input')?.focus()};
    await refreshRuns();
  }
  function runSummary(run){
    if(run.summary&&run.summary!=='科研任务')return run.summary;
    const id=window.ERWAgentPage?.sessionId?.(),messages=id?window.ERWAgentClient?.snapshot(id)?.session.messages||[]:[];
    const index=messages.findIndex(m=>m.run_id===run.id);return (index>0?[...messages.slice(0,index)].reverse().find(m=>m.role==='user')?.content:'')?.slice(0,180)||'科研任务';
  }
  async function refreshRuns(){
    if(!panelHost||tab!=='runs')return;
    const root=$('#as-runs-list',panelHost);if(!root)return;
    const session=window.ERWAgentPage?.sessionId?.()||'';
    const rows=await api('runs?session_id='+encodeURIComponent(session));
    if(!panelHost||tab!=='runs'||!root.isConnected)return;
    if(!rows.some(run=>run.id===selected)){selected=rows[0]?.id||'';cursor=0;log=[]}
    root.innerHTML=rows.length?rows.map(r=>`<article class="as-run"><button type="button" class="as-run-title as-run-summary" data-as-run="${esc(r.id)}"><strong>${esc(runSummary(r))}</strong><small>${esc(new Date(r.updated).toLocaleString('zh-CN',{hour12:false}))}</small></button><span class="as-status" data-state="${esc(r.status)}">${labels[r.status]||esc(r.status)}</span><div class="as-actions">${['running','queued'].includes(r.status)?`<button type="button" data-as-control="pause" data-id="${r.id}">暂停</button><button type="button" data-as-control="cancel" data-id="${r.id}">停止</button>`:''}${['paused','interrupted','waiting_approval','failed'].includes(r.status)?`<button type="button" data-as-control="resume" data-id="${r.id}">继续</button>`:''}</div>${r.error?`<p class="as-error">${esc(r.error)}</p>`:''}</article>`).join(''):'<p class="as-hint">暂无任务，普通对话也会自动出现在这里。</p>';
    root.querySelectorAll('[data-as-run]').forEach(b=>b.onclick=()=>{selected=b.dataset.asRun;cursor=0;log=[];detail().catch(e=>toast(e.message,true))});
    root.querySelectorAll('[data-as-control]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{if(b.dataset.asControl==='resume')await window.ERWAgentClient.resume(b.dataset.id);else await api('runs/'+b.dataset.id+'/'+b.dataset.asControl,{});await refreshRuns();await window.ERWAgentPage?.refresh?.()}catch(e){toast(e.message,true)}finally{b.disabled=false}});
    if(selected)await detail();
  }
  async function detail(){
    const root=panelHost&&$('#as-run-detail',panelHost);if(!root||!selected)return;
    const id=selected,sequence=root._detailSequence=(root._detailSequence||0)+1;
    const [run,events,drafts]=await Promise.all([api('runs/'+id),api('runs/'+id+'/events?after='+cursor),api('drafts?status=')]);
    if(!root.isConnected||!panelHost||selected!==id||tab!=='runs'||sequence!==root._detailSequence)return;
    log.push(...events.filter(event=>event.seq>cursor));if(events.length)cursor=Math.max(cursor,events.at(-1).seq);
    const pending=(Array.isArray(drafts)?drafts:[]).filter(d=>d.context?.run_id===id&&d.status==='pending');
    const plan=log.filter(e=>e.event==='plan').at(-1)?.data.steps||[];
    const key=JSON.stringify([run,pending,log]);if(root._detailKey===key)return;root._detailKey=key;
    const opened=root.dataset.runId===id?new Set([...root.querySelectorAll('details[open]')].map(element=>element.classList.contains('as-run-result')?'result':element.classList.contains('as-draft')?element.querySelector('[data-as-draft]')?.dataset.asDraft:'diagnostics')):new Set();root.dataset.runId=id;
    root.innerHTML=`<h3>执行记录</h3>${plan.length?`<ol class="as-plan">${plan.map(p=>`<li>${p.status==='completed'?'✓':p.status==='in_progress'?'◉':'○'} ${esc(p.step)}</li>`).join('')}</ol>`:''}${pending.map(d=>`<details class="as-draft"><summary>待确认：${esc(d.tool)}</summary><pre>${esc(window.ERWAgentClient.draftPreview(d))}</pre><button type="button" data-as-draft="${d.id}" data-action="confirm">确认执行</button><button type="button" data-as-draft="${d.id}" data-action="reject">拒绝</button></details>`).join('')}${run.result?.assistant?`<button type="button" id="as-view-answer">查看对话中的回复</button><details class="as-run-result"><summary>展开任务结果</summary><div class="as-answer">${window.ERWFabTimeline?.responses?.(run.result.assistant)||''}${window.ERWFabTimeline?.render?.(run.result.assistant.content)||esc(run.result.assistant.content)}${window.ERWAgentSources?.entry(run.result.assistant,run.session_id)||''}</div></details>`:''}<details><summary>诊断信息 · 事件与工具证据 · ${log.length} 项</summary><pre>${esc(JSON.stringify({task_id:run.id,events:log.filter(e=>e.event!=='delta')},null,2))}</pre></details>`;
    root.querySelectorAll(':scope > details').forEach(element=>{const key=element.classList.contains('as-run-result')?'result':element.classList.contains('as-draft')?element.querySelector('[data-as-draft]')?.dataset.asDraft:'diagnostics';element.open=opened.has(key)});
    const answerButton=$('#as-view-answer',root);if(answerButton)answerButton.onclick=async()=>{open('chat');await window.ERWAgentPage?.refresh?.();const id=run.result.assistant.id;[...document.querySelectorAll('[data-message-id]')].find(e=>e.dataset.messageId===id)?.scrollIntoView({block:'center'})};
    root.querySelectorAll('[data-as-draft]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await window.ERWAgentClient.resolveDraft(b.dataset.asDraft,b.dataset.action==='confirm');await detail();toast('草稿已处理，全部处理后点击继续')}catch(e){toast(e.message,true)}});
  }
  async function memory(root){
    const [sessions,projects]=await Promise.all([api('sessions'),window.ERWResearchUI?.loadProjects()||Promise.resolve([])]);
    root.innerHTML=`<div class="as-form"><div class="as-row"><label>会话范围<select id="as-memory-session"><option value="">用户与全局记忆</option>${sessions.map(s=>`<option value="${esc(s.id)}">${esc(s.title)}</option>`).join('')}</select></label><label>项目<select id="as-memory-project"><option value="">全部项目</option>${projects.map(p=>`<option value="${esc(p.id)}" title="${esc(p.name)}">${esc(p.display_name||p.name)}</option>`).join('')}</select></label></div><div class="as-row"><input id="as-memory-query" placeholder="检索记忆，例如：实验口径、研究偏好"><button type="button" id="as-recall">检索</button></div><div id="as-memory-results"></div></div><details><summary>添加长期记忆</summary><form class="as-form" id="as-memory-form"><label>记忆内容<textarea name="content" rows="3" required></textarea></label><div class="as-row"><label>作用域<select name="scope"><option value="user">用户</option><option value="global">全局</option><option value="project">项目</option><option value="session">会话</option></select></label><label class="as-scope-id" hidden>适用范围<select name="scope_id"><option value="">请先选择作用域</option></select></label><label>类型<select name="kind">${['fact','preference','procedure','decision','episode'].map(k=>`<option>${k}</option>`).join('')}</select></label></div><label>稳定标识（同作用域相同标识将替代旧内容）<input name="memory_key" placeholder="例如：research-metric-policy"></label><button type="submit">保存记忆</button></form></details>`;
    const show=async(query='')=>{const sid=$('#as-memory-session',root).value,pid=$('#as-memory-project',root).value;const rows=query?(await api('memory/recall',{query,session_id:sid,project_id:pid})).results:await api('memories?session_id='+encodeURIComponent(sid)+'&project_id='+encodeURIComponent(pid));$('#as-memory-results',root).innerHTML=rows.map(m=>`<article class="as-memory"><p>${esc(m.content)}</p><small>${esc(m.scope)} · ${esc(m.kind)} · 来源 ${esc(JSON.stringify(m.source))}</small><button type="button" data-forget="${esc(m.id)}">忘记</button></article>`).join('')||'<div class="as-empty">没有匹配的记忆。可以记录研究偏好、实验口径或长期约定。<br>例如：比较实验时同时报告延迟、精度和计算预算。</div>';root.querySelectorAll('[data-forget]').forEach(b=>b.onclick=async()=>{try{await api('memory/forget',{id:b.dataset.forget});await show()}catch(e){toast(e.message,true)}})};
    $('#as-recall',root).onclick=()=>show($('#as-memory-query',root).value).catch(e=>toast(e.message,true));
    $('#as-memory-project',root).onchange=()=>show().catch(e=>toast(e.message,true));
    const memoryForm=$('#as-memory-form',root);memoryForm.elements.scope.onchange=()=>{const scope=memoryForm.elements.scope.value,select=memoryForm.elements.scope_id,needed=['project','session'].includes(scope);select.closest('label').hidden=!needed;select.required=needed;select.innerHTML=scope==='project'?'<option value="">请选择项目</option>'+projects.map(p=>`<option value="${esc(p.id)}">${esc(p.display_name||p.name)}</option>`).join(''):scope==='session'?'<option value="">请选择会话</option>'+sessions.map(p=>`<option value="${esc(p.id)}">${esc(p.title)}</option>`).join(''):'<option value=""></option>'};
    $('#as-memory-session',root).onchange=()=>show().catch(e=>toast(e.message,true));
    const current=window.ERWAgentPage?.sessionId?.();if(current&&sessions.some(session=>session.id===current))$('#as-memory-session',root).value=current;
    $('#as-memory-form',root).onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;try{await api('memory/remember',Object.fromEntries(new FormData(form)));form.reset();form.elements.scope.onchange();await show();toast('记忆已保存')}catch(err){toast(err.message,true)}};
    await show();
  }
  function lastSkillUse(name){
    const id=window.ERWAgentPage?.sessionId?.(),messages=id?window.ERWAgentClient?.snapshot(id)?.session.messages||[]:[];
    const message=[...messages].reverse().find(m=>(m.skills_used||[]).some(skill=>skill.name===name));
    return message?'当前会话最近使用：'+esc(new Date(message.created).toLocaleString('zh-CN',{hour12:false})):'当前会话尚未使用';
  }
  async function skills(root){
    const [data,system]=await Promise.all([api('skills'),api('system')]);const options=system.settings||{};window.ERWAgentClient.adoptCapabilities(options);
    const enabled=options.skills_enabled!==false,disabled=new Set(options.disabled_skills||[]);
    root.innerHTML=`<div class="as-section-head"><div><h3>技能</h3><p class="as-hint">助手按任务需要加载技能，再读取参考资料、模板或运行脚本。技能使用记录随回复保存。</p></div><label class="as-check"><input type="checkbox" id="as-skills-enabled" ${enabled?'checked':''}>启用 Skill</label></div><div class="as-row"><input id="as-skill-search" aria-label="搜索技能" placeholder="搜索名称或用途"></div><details class="as-skill-import"><summary>安装与导入技能</summary><div class="as-row"><label class="as-check">导入 ZIP<input type="file" id="as-skill-zip" accept=".zip" aria-label="导入技能 ZIP"></label><label class="as-check">导入文件夹<input type="file" id="as-skill-folder" webkitdirectory multiple aria-label="导入技能文件夹"></label></div><p class="as-hint" id="as-skill-status" role="status">支持 SKILL.md、references/、scripts/、assets/ 和 agents/openai.yaml；脚本使用隔离执行环境。</p></details><div>${data.skills.map(skill=>`<article class="as-skill ${disabled.has(skill.name)?'as-skill-off':''}" data-skill-card="${esc(skill.name)}"><strong>${esc(skill.display_name||skill.name)} <small>${skill.builtin?'内置':'用户'}${skill.version?' · '+esc(skill.version):''}</small></strong><label class="as-check"><input type="checkbox" data-enable-skill="${esc(skill.name)}" aria-label="启用 ${esc(skill.name)}" ${!disabled.has(skill.name)?'checked':''} ${enabled?'':'disabled'}>启用</label><p>${esc(skill.description)}</p><p class="as-hint">${lastSkillUse(skill.name)}</p><details class="as-skill-tech"><summary>指令、资源与环境</summary><p class="as-hint">${esc(skill.name)} · ${skill.allow_implicit_invocation===false?'仅明确调用':'按需自动选用'}${skill.shadows?' · 覆盖同名内置或工作区技能':''}</p><div class="as-actions"><button type="button" data-read-skill="${esc(skill.name)}">查看指令</button><button type="button" data-skill-resources="${esc(skill.name)}">资源与环境</button></div><div class="as-skill-resources" hidden></div><pre hidden></pre><button type="button" data-skill-more hidden>继续读取</button></details></article>`).join('')}</div>${data.errors.map(error=>`<p class="as-error">${esc(error.name)}：${esc(error.error)}</p>`).join('')}<details><summary>安装文本技能</summary><form class="as-form" id="as-skill-install"><label>目录名称<input name="name" required pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="my-research-skill"></label><label>SKILL.md<textarea name="content" rows="9" required placeholder="---&#10;name: my-research-skill&#10;description: 说明用途和触发条件&#10;---&#10;具体工作流程"></textarea></label><button type="submit">安装技能</button></form></details>`;
    $('#as-skills-enabled',root).onchange=async event=>{const checkbox=event.target;checkbox.disabled=true;try{await window.ERWAgentClient.saveSettings({skills_enabled:checkbox.checked});await skills(root)}catch(error){checkbox.checked=!checkbox.checked;toast(error.message,true)}finally{if(checkbox.isConnected)checkbox.disabled=false}};
    root.querySelectorAll('[data-enable-skill]').forEach(checkbox=>checkbox.onchange=async()=>{checkbox.disabled=true;try{const fresh=(await api('system')).settings||{};const names=new Set(fresh.disabled_skills||[]);checkbox.checked?names.delete(checkbox.dataset.enableSkill):names.add(checkbox.dataset.enableSkill);await window.ERWAgentClient.saveSettings({disabled_skills:[...names]});await skills(root)}catch(error){checkbox.checked=!checkbox.checked;toast(error.message,true)}finally{if(checkbox.isConnected)checkbox.disabled=false}});
    async function readResource(card,name,path='SKILL.md',offset=0){const data=await api('skills/read',{name,path,offset});if(!card.isConnected)return;const preview=$('pre',card),more=$('[data-skill-more]',card);preview.hidden=false;preview.textContent=(offset?preview.textContent:'')+data.content;more.hidden=data.next_offset==null;more.onclick=()=>readResource(card,name,path,data.next_offset).catch(error=>toast(error.message,true))}
    root.querySelectorAll('[data-read-skill]').forEach(button=>button.onclick=()=>readResource(button.closest('.as-skill'),button.dataset.readSkill).catch(error=>toast(error.message,true)));
    root.querySelectorAll('[data-skill-resources]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const data=await api('skills/resources',{name:button.dataset.skillResources});const card=button.closest('.as-skill'),area=$('.as-skill-resources',card);area.hidden=false;area.innerHTML=(data.warnings||[]).map(w=>`<p class="as-hint">${esc(w)}</p>`).join('')+`<p class="as-hint">${data.files.length} 个文件 · ${Math.ceil(data.bytes/1024)} KB</p>`+data.files.map(f=>`<button type="button" data-skill-file="${esc(f.path)}">${esc(f.path)}</button>`).join('');area.querySelectorAll('[data-skill-file]').forEach(file=>file.onclick=()=>readResource(card,button.dataset.skillResources,file.dataset.skillFile).catch(error=>toast(error.message,true)))}catch(error){toast(error.message,true)}finally{button.disabled=false}});
    $('#as-skill-search',root).oninput=event=>{const query=event.target.value.toLocaleLowerCase();root.querySelectorAll('[data-skill-card]').forEach(card=>card.hidden=!card.textContent.toLocaleLowerCase().includes(query))};
    const base64=file=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('文件读取失败'));reader.readAsDataURL(file)});
    $('#as-skill-zip',root).onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>12*1024*1024)throw Error('ZIP 最大 12 MB');$('#as-skill-status',root).textContent='正在导入技能包…';await api('skills/import',{base64:await base64(file)});await skills(root);toast('技能包已导入')}catch(error){toast(error.message,true);$('#as-skill-status',root).textContent=error.message}};
    $('#as-skill-folder',root).onchange=async event=>{try{const files=[...event.target.files];if(!files.length)return;if(files.length>128||files.reduce((sum,f)=>sum+f.size,0)>20*1024*1024)throw Error('技能包最多 128 个文件，合计 20 MB');const manifest=files.find(f=>f.webkitRelativePath.split('/').length===2&&f.name==='SKILL.md');if(!manifest)throw Error('请选择直接包含 SKILL.md 的技能文件夹');$('#as-skill-status',root).textContent='正在导入技能包…';const content=await manifest.text();const resources=await Promise.all(files.filter(f=>f!==manifest).map(async f=>({path:f.webkitRelativePath.split('/').slice(1).join('/'),base64:await base64(f)})));await api('skills/install',{content,files:resources});await skills(root);toast('技能包已导入')}catch(error){toast(error.message,true);$('#as-skill-status',root).textContent=error.message}};
    $('#as-skill-install',root).onsubmit=async event=>{event.preventDefault();try{await api('skills/install',Object.fromEntries(new FormData(event.currentTarget)));await skills(root);toast('技能已安装')}catch(error){toast(error.message,true)}};
  }
  async function capabilities(root,data){
    data=data||await api('system');const options=data.settings||{};window.ERWAgentClient.adoptCapabilities(options);
    root.innerHTML=`<h3>AI 能力</h3><div class="as-switches">${[['rag_enabled','RAG 知识检索'],['memory_enabled','记忆'],['skills_enabled','Skill']].map(([key,label])=>`<label class="as-check"><input type="checkbox" data-capability="${key}" ${options[key]!==false?'checked':''}>启用 ${label}</label>`).join('')}</div><p class="as-hint">三个总开关也位于主对话和悬浮助手的输入框下方，并实时同步。RAG 检索资料；记忆控制自动召回及助手读写长期记忆；Skill 控制技能选用。主动引用的资料和已有数据会保留。</p><div class="as-actions"><button type="button" data-capability-tab="skills">管理技能</button><button type="button" data-capability-tab="rag">配置 RAG</button></div><p class="as-hint" role="status" id="as-capability-status"></p>`;
    root.querySelectorAll('[data-capability]').forEach(checkbox=>checkbox.onchange=async()=>{checkbox.disabled=true;try{await window.ERWAgentClient.saveSettings({[checkbox.dataset.capability]:checkbox.checked});$('#as-capability-status',root).textContent='已保存，后续工具调用立即生效'}catch(error){checkbox.checked=!checkbox.checked;toast(error.message,true)}finally{checkbox.disabled=false}});
    root.querySelectorAll('[data-capability-tab]').forEach(button=>button.onclick=()=>open(button.dataset.capabilityTab));
  }
  async function rag(root){
    const [data,initial]=await Promise.all([api('system'),api('rag')]),options=data.settings||{},r=initial.settings||{};
    root.innerHTML=`<h3>RAG / 嵌入模型</h3><p class="as-hint">语义检索需要专用 Embedding 模型。填写兼容 /embeddings 的接口，保存后建立资料向量索引。聊天模型配置与此处独立。</p>
      <form class="as-form" id="as-rag-settings">
        <label class="as-check"><input name="rag_enabled" data-capability="rag_enabled" type="checkbox" ${options.rag_enabled!==false?'checked':''}>启用 RAG 知识检索</label>
        <div class="as-row"><label>检索方式<select name="mode">${[['keyword','关键词（无需嵌入调用）'],['hybrid','混合（关键词 + 语义）'],['semantic','语义向量']].map(([id,label])=>`<option value="${id}" ${r.mode===id?'selected':''}>${label}</option>`).join('')}</select></label><label>最多召回条数<input name="rag_top_k" type="number" min="1" max="20" value="${options.rag_top_k||8}"></label></div>
        <label>Embedding Base URL<input name="base_url" type="url" placeholder="https://你的服务地址/v1" value="${esc(r.base_url||'')}"></label>
        <div class="as-row"><label>Embedding 模型名称<input name="model" placeholder="填写服务商提供的嵌入模型 ID" value="${esc(r.model||'')}"></label><label>API Key<input name="api_key" type="password" autocomplete="new-password" placeholder="${r.has_api_key?'已保存；留空保留原密钥':'本地无鉴权服务可留空'}"></label></div>
        <label class="as-check"><input name="clear_api_key" type="checkbox">清除已保存的 Embedding 密钥</label>
        <details><summary>分块与索引选项</summary><div class="as-row">${[['dimensions','向量维数（0 = 模型默认）',0,8192,0],['chunk_chars','分块长度（字符）',256,8000,1600],['overlap_chars','重叠长度（字符）',0,2000,200],['batch_size','每次请求分块数',1,64,16]].map(([key,label,min,max,fallback])=>`<label>${label}<input name="${key}" type="number" min="${min}" max="${max}" value="${r[key]??fallback}"></label>`).join('')}</div><label class="as-check"><input name="include_pdf" type="checkbox" ${r.include_pdf?'checked':''}>同时索引文献 PDF 正文（按页提取；扫描件需先做 OCR）</label></details>
        <details><summary>自动更新</summary><label class="as-check"><input name="realtime_updates" type="checkbox" ${r.realtime_updates?'checked':''}>资料变化后自动更新</label><label>合并连续修改的等待时间（秒）<input name="update_debounce_seconds" type="number" min="5" max="300" value="${r.update_debounce_seconds??15}"></label><label class="as-check"><input name="scheduled_updates" type="checkbox" ${r.scheduled_updates?'checked':''}>定期更新</label><label>更新间隔（分钟）<input name="update_interval_minutes" type="number" min="5" max="10080" value="${r.update_interval_minutes??60}"></label><p class="as-hint">工作台服务运行期间生效，每 5 秒检查变化；未修改的分块复用向量。RAG 关闭或使用关键词模式时暂停自动更新。自动更新会向已配置的 Embedding 接口发送变化的资料分块。</p></details>
        <p class="as-hint">索引包含知识库 Markdown 全文。构建时向该接口发送资料分块；检索时发送问题。连接测试仅发送一段短文本。密钥仅保存在本机配置中，不写入对话或工作区备份。</p>
        <div class="as-actions"><button type="submit" class="primary-btn">保存 RAG 设置</button><button type="button" id="as-rag-test" class="secondary-btn">保存并测试连接</button><button type="button" id="as-rag-build" class="secondary-btn">保存并更新索引</button><button type="button" id="as-rag-cancel" class="secondary-btn" hidden>取消构建</button></div><p role="status" id="as-rag-status"></p>
      </form><div class="as-rag-index" id="as-rag-index" aria-live="polite"></div><details id="as-rag-clear-panel"><summary>清除向量数据库</summary><p class="as-hint">删除所有资料分块向量并释放索引空间，保留文献、笔记、灵感和长期记忆。自动更新会关闭，后续可手动重建。正在构建时需先取消并等待结束。</p><button type="button" id="as-rag-clear">清除向量索引…</button></details>
      <form class="as-form" id="as-rag-search"><label>检索试用<input name="query" required maxlength="8000" placeholder="例如：有哪些减少微调参数的方法？"></label><button type="submit" class="secondary-btn">检索资料</button><div id="as-rag-results"></div></form>`;
    const form=$('#as-rag-settings',root),message=$('#as-rag-status',root);
    const top=document.createElement('section');top.className='as-rag-status-card';top.setAttribute('aria-label','RAG 可用状态');
    top.append($('#as-rag-index',root));const common=document.createElement('div');common.className='as-actions';
    for(const id of ['as-rag-test','as-rag-build','as-rag-cancel']){const button=$('#'+id,root);button.dataset.ragOperation='true';common.append(button)}top.append(common);root.prepend(top);
    $('#as-rag-test',root).textContent='连接检查';$('#as-rag-build',root).textContent='更新资料索引';
    const connection=document.createElement('details');connection.className='as-rag-connection';connection.id='as-rag-connection';connection.innerHTML='<summary>接口与检索设置</summary>';
    connection.open=!r.model&&r.mode!=='keyword';const controls=[...form.children].filter(e=>e.id!=='as-rag-status');for(const control of controls)connection.append(control);form.prepend(connection);

    let busy=false,polling=false,currentStatus=initial;
    function draw(status){
      currentStatus=status;
      const index=status.index||{},job=status.job||{},running=['running','cancelling'].includes(job.state);
      const mode=status.settings?.mode||'keyword';const title=!form.elements.rag_enabled.checked?'RAG 已关闭':running?'语义索引构建中':index.stale?'配置已变化，请更新索引':mode==='keyword'?'关键词检索可用':index.ready?'语义索引可用':'语义索引尚未建立';

      $('#as-rag-index',root).innerHTML=`<strong class="as-rag-availability">${esc(title)}</strong><p><strong>资料向量索引：</strong>${index.generation?`${index.chunks} 个分块 · ${index.sources} 份来源 · ${esc(index.model)} · ${index.dimensions} 维`:'尚未建立'}</p>${index.stale?'<p class="as-error">接口、模型或分块配置已改变，请更新索引后使用语义检索。</p>':''}${job.state?`<p>${({running:'构建中',cancelling:'正在取消',completed:'构建完成',failed:'构建失败',cancelled:'已取消',cleared:'已清除'})[job.state]||esc(job.state)} · 已处理 ${job.sources||0} 份来源 / ${job.chunks||0} 个分块 · 新嵌入 ${job.embedded||0} · 复用 ${job.reused||0}${job.empty_sources?` · 空正文 ${job.empty_sources}`:''}</p>${job.error?`<p class="as-error">${esc(job.error)}</p>`:''}`:''}<p class="as-hint">资料修改后点击更新；未改变的分块复用已有向量。失败或取消会保留上次完整索引。关键词模式不调用嵌入接口；混合模式不可用时明确提示并退回关键词。</p>`;
      const updates=status.updates||{};if(status.settings?.scheduled_updates&&updates.next_scheduled_at)$('#as-rag-index',root).insertAdjacentHTML('beforeend',`<p class="as-hint">下次定期更新：${esc(new Date(updates.next_scheduled_at*1000).toLocaleString())}</p>`);
      $('#as-rag-build',root).disabled=busy||running;$('#as-rag-clear',root).disabled=busy||running;$('#as-rag-cancel',root).hidden=!running;return running;
    }
    async function poll(){if(polling)return;polling=true;try{while(root.isConnected){const status=await api('rag');if(!root.isConnected)return;const running=draw(status),automatic=status.settings?.realtime_updates||status.settings?.scheduled_updates;if(!running&&!automatic)break;await new Promise(resolve=>setTimeout(resolve,running?1000:5000))}}catch(error){if(root.isConnected)message.textContent='索引状态读取失败：'+error.message}finally{polling=false}}
    async function save(){
      const fields=Object.fromEntries(new FormData(form));
      for(const key of ['dimensions','chunk_chars','overlap_chars','batch_size','update_interval_minutes','update_debounce_seconds'])fields[key]=Number(fields[key]);
      for(const key of ['include_pdf','realtime_updates','scheduled_updates','clear_api_key'])fields[key]=form.elements[key].checked;
      const saved=await api('rag/settings',fields);
      await window.ERWAgentClient.saveSettings({rag_enabled:form.elements.rag_enabled.checked,rag_top_k:Number(fields.rag_top_k)});
      form.elements.api_key.value='';form.elements.api_key.placeholder=saved.has_api_key?'已保存；留空保留原密钥':'本地无鉴权服务可留空';form.elements.clear_api_key.checked=false;
    }
    async function perform(action){
      if(busy)return;if(!form.checkValidity()){form.querySelectorAll('details').forEach(d=>d.open=true);form.reportValidity();return}busy=true;root.querySelectorAll('#as-rag-settings button,[data-rag-operation]:not(#as-rag-cancel)').forEach(button=>button.disabled=true);message.textContent='正在保存…';
      try{await save();if(action==='test'){message.textContent='正在测试连接…';const result=await api('rag/test',{});message.textContent=`连接成功 · ${result.model} · ${result.dimensions} 维`}else if(action==='index'){draw(await api('rag/index',{}));message.textContent='已开始构建索引';poll()}else{message.textContent='RAG 设置已保存';draw(await api('rag'))}}catch(error){message.textContent=error.message;toast(error.message,true)}finally{busy=false;root.querySelectorAll('#as-rag-settings button,[data-rag-operation]:not(#as-rag-cancel)').forEach(button=>button.disabled=false);api('rag').then(status=>{if(!root.isConnected)return;const running=draw(status);if(running||status.settings?.realtime_updates||status.settings?.scheduled_updates)poll()}).catch(()=>{})}
    }
    form.onsubmit=event=>{event.preventDefault();perform('save')};$('#as-rag-test',root).onclick=()=>perform('test');$('#as-rag-build',root).onclick=()=>perform('index');$('#as-rag-cancel',root).onclick=async()=>{try{draw(await api('rag/cancel',{}))}catch(error){toast(error.message,true)}};
    $('#as-rag-clear',root).onclick=async event=>{
      if(busy)return;busy=true;const button=event.currentTarget;button.disabled=true;let cancelled=false;
      try{
        if(!window.ERWDialog?.confirm)throw Error('确认窗口未能加载，请刷新后重试');
        const index=currentStatus.index||{},scope=index.generation?`当前索引包含 ${Number(index.sources)||0} 份来源、${Number(index.chunks)||0} 个分块。\n\n`:'';
        const confirmed=await window.ERWDialog.confirm(scope+'将删除全部资料向量并关闭实时和定期更新。文献、笔记、灵感、长期记忆及 Embedding 配置会保留。\n\n恢复语义检索需要重新构建索引，可能产生嵌入调用费用。是否继续？',{
          title:'清除向量数据库？',danger:true,buttons:[{value:'cancel',label:'取消'},{value:'confirm',label:'确认清除',primary:true,danger:true}]
        });
        if(!confirmed){cancelled=true;return}if(!root.isConnected)return;
        const status=await api('rag/clear',{});form.elements.realtime_updates.checked=false;form.elements.scheduled_updates.checked=false;draw(status);message.textContent='向量数据库已清除，原始资料和长期记忆已保留，自动更新已关闭';
      }catch(error){message.textContent=error.message;toast(error.message,true)}finally{busy=false;button.disabled=false;if(cancelled&&button.isConnected)button.focus({preventScroll:true});if(root.isConnected)try{draw(await api('rag'))}catch(error){message.textContent+='；状态读取失败：'+error.message}}
    };
    $('#as-rag-search',root).onsubmit=async event=>{event.preventDefault();const f=event.currentTarget,b=$('button',f);b.disabled=true;try{const result=await api('rag/search',{query:f.elements.query.value});$('#as-rag-results',root).innerHTML=`<p class="as-hint">检索方式：${esc(result.mode)}${result.warning?' · '+esc(result.warning):''} · 实际 ${result.count} 条 / 最多 ${result.limit??form.elements.rag_top_k.value} 条</p>${result.items.map(item=>`<article class="as-memory"><a href="#" data-agent-reference="${esc(item.id||item.title)}">${esc(item.title)}</a> ${window.ERWResearchUI?.evidenceBadge(item)||''}<p>${esc(item.excerpt)}</p><small>${esc(item.source?.path||item.id)}${item.source?.page?' · 第 '+item.source.page+' 页':''}</small></article>`).join('')}`}catch(error){$('#as-rag-results',root).textContent=error.message}finally{b.disabled=false}};
    if(draw(initial)||r.realtime_updates||r.scheduled_updates)poll();
  }
  async function settings(root){
    const data=await api('system'),s={max_steps:48,time_budget_seconds:900,context_tokens:24000,mcp_servers:[],...data.settings};
    root.innerHTML=`<div id="as-capabilities"></div><details class="as-advanced"><summary>高级运行设置</summary><p class="as-hint">本地记忆 · ${data.brain?.counts?.memories||0} 条 · ${data.brain?.counts?.runs||0} 个任务</p><form class="as-form" id="as-settings"><div class="as-row">${[['max_steps','每次执行最多轮数',1,256],['time_budget_seconds','每次执行时间预算（秒）',10,7200],['context_tokens','上下文估算 Token 预算',2048,200000]].map(([key,label,min,max])=>`<label>${label}<input type="number" name="${key}" value="${s[key]}" min="${min}" max="${max}"></label>`).join('')}</div><label class="as-check"><input name="auto_recall" type="checkbox" ${s.auto_recall?'checked':''}>自动召回相关长期记忆</label><label class="as-check"><input name="web_enabled" type="checkbox" ${s.web_enabled?'checked':''}>允许公开网页与文献检索</label><label class="as-check"><input name="code_enabled" type="checkbox" ${s.code_enabled?'checked':''}>允许 Docker 隔离代码执行（需已安装并启动 Docker）</label><label>本地 Python 镜像<input name="docker_image" value="${esc(s.docker_image)}"></label><p class="as-hint">代码容器无网络，仅能读取明确选择的输入；输出保存在 Workspace/System/Agent/Artifacts。镜像须事先拉取。</p><label>MCP HTTP 服务配置（JSON）<textarea name="mcp_servers" rows="8">${esc(JSON.stringify(s.mcp_servers,null,2))}</textarea></label><p class="as-hint">每项包含 name、url、enabled、tools（明确允许的远端工具）、read_only_tools、headers_env（请求头到环境变量名称）。保存后刷新连接，并在人设编辑器中勾选工具权限。</p><div class="as-actions"><button type="submit" class="primary-btn">保存设置</button><button type="button" id="as-mcp-refresh">刷新 MCP 连接</button><button type="button" id="as-backup">备份记忆库</button></div><pre id="as-settings-result"></pre></form></details>`;
    await capabilities($('#as-capabilities',root),data);
    $('#as-settings',root).onsubmit=async e=>{e.preventDefault();try{const f=e.currentTarget;const d=Object.fromEntries(new FormData(f));for(const key of ['auto_recall','code_enabled','web_enabled'])d[key]=f.elements[key].checked;for(const key of ['max_steps','time_budget_seconds','context_tokens'])d[key]=Number(d[key]);d.mcp_servers=JSON.parse(d.mcp_servers);await window.ERWAgentClient.saveSettings(d);toast('设置已保存')}catch(err){toast(err.message,true)}};
    $('#as-mcp-refresh',root).onclick=async e=>{e.target.disabled=true;try{const d=await api('mcp/refresh',{});$('#as-settings-result',root).textContent=JSON.stringify(d,null,2)}catch(err){toast(err.message,true)}finally{e.target.disabled=false}};
    $('#as-backup',root).onclick=async()=>{try{const d=await api('backup',{});const a=document.createElement('a');a.href=d.url;a.textContent='下载一致性备份';a.download=d.path.split('/').at(-1);$('#as-settings-result',root).replaceChildren(a)}catch(e){toast(e.message,true)}};
  }
  function attach(){
    const panel=$('#agent-system-panel');
    if(panel&&panel!==panelHost)mount();
    if(!panel&&panelHost&&!panelHost.isConnected){clearInterval(timer);timer=null;panelHost=null;generation++}
  }
  let queued=false;
  new MutationObserver(()=>{if(!queued){queued=true;requestAnimationFrame(()=>{queued=false;attach()})}}).observe(document.body,{childList:true,subtree:true});
  document.addEventListener('erw-agent-run-updated',()=>{if(tab==='runs')refreshRuns().catch(error=>toast(error.message,true))});
  window.ERWAgentSystem={open,close,mount,renderCapabilities:root=>capabilities(root).catch(error=>{root.textContent='AI 能力设置加载失败：'+error.message}),renderRag:root=>rag(root).catch(error=>{root.textContent='RAG 设置加载失败：'+error.message}),showRun:id=>{if(selected!==id){selected=id;cursor=0;log=[]}open('runs')}};attach();
})();
