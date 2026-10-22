/* research-pages.js · v261009.13 —— 研究知识页补丁合并模块（A2）
 *
 * 本文件由以下原补丁按序拼接而成，内容未做任何改写（逐字保留），加载位置即原来第一个补丁的位置：
 *   1. v260922-projects.js
 *   2. v260922-overview-editor-tools.js
 *   3. v260922-agent-profiles.js
 *
 * v261009.13 · 图谱可视化的两个补丁（v260922-graph-performance.js / v260922-overview-graph.js）
 * 已迁成插件 plugins/knowledge-graph/（走内核 window.ERWGraphRenderers 渲染接管接缝），
 * 不在本文件内。
 * 合并前提（改这里之前请先复核）：每个原文件都是 IIFE 且无顶层声明，
 * 彼此只经 window / 自定义事件 / DOM 通信。装配顺序见 web/manifest.json，
 * 提交前跑 python tools/web_check.py。
 */

(() => {
  'use strict';

  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => [...r.querySelectorAll(s)];
  const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const STATUS = ['进行中','暂停','完成','归档'];
  let milestoneStatus = localStorage.getItem('milestoneStatusFilter') || '';
  let projectsLoading = false;

  async function api(url, opts={}) {
    const init={...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}};
    if(init.body && typeof init.body!=='string') init.body=JSON.stringify(init.body);
    const res=await (window.erwFetch||fetch)(url,init); let data={}; try{data=await res.json()}catch{}
    if(!res.ok) throw new Error(data.message||data.error||`HTTP ${res.status}`); return data;
  }
  function toast(msg,error=false){
    const stack=$('#toast-stack'); if(!stack)return;
    const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=msg;stack.appendChild(el);setTimeout(()=>el.remove(),3200);
  }
  function modal(title, body, footer=''){
    $('#modal-title').textContent=title;$('#modal-body').innerHTML=body;$('#modal-footer').innerHTML=footer;$('#modal-backdrop').classList.remove('hidden');
  }
  function closeModal(){ $('#modal-backdrop')?.classList.add('hidden'); }
  function fmtDate(s){return s?String(s).slice(0,10):'—'}
  function fmtTime(s){try{return s?new Date(s).toLocaleString('zh-CN',{hour12:false}):'—'}catch{return s||'—'}}

  async function showProjects(){
    if(projectsLoading)return;
    projectsLoading=true;
    const main=$('#main');
    main.innerHTML='<div class="empty"><div><div class="empty-symbol">PROJECTS</div>正在加载项目…</div></div>';
    try{
      const rows=await api('/api/project-records');
      if(location.hash!=='#projects')return;
      main.innerHTML=`<div class="project-manager">
        <section class="card card-pad project-manager-head"><div><div class="card-kicker">PROJECT MANAGEMENT</div><h3>项目管理</h3><p>项目以稳定 ID 作为唯一索引。修改名称不会改变关联关系；删除项目时工程目录会移入 Workspace 回收目录。</p></div><button class="primary-btn" id="project-new">＋ 新建项目</button></section>
        <div class="project-manager-grid">${rows.length?rows.map(projectCard).join(''):'<section class="card card-pad"><div class="empty">暂无项目，点击“新建项目”开始。</div></section>'}</div>
      </div>`;
      $('#project-new').onclick=()=>openProjectEditor();
      $$('[data-project-edit]').forEach(b=>b.onclick=()=>openProjectEditor(rows.find(x=>x.id===b.dataset.projectEdit)));
      $$('[data-project-delete]').forEach(b=>b.onclick=()=>deleteProject(rows.find(x=>x.id===b.dataset.projectDelete)));
    }catch(e){main.innerHTML=`<div class="card card-pad danger">项目加载失败：${esc(e.message)}</div>`}
    finally{projectsLoading=false;}
  }

  function projectCard(p){
    return `<section class="card project-manager-card">
      <div class="project-card-top"><div><div class="project-id mono">${esc(p.id)}</div><h3>${esc(p.name)}</h3></div><span class="badge ${p.status==='进行中'?'accent':''}">${esc(p.status||'进行中')}</span></div>
      <p class="project-desc">${esc(p.description||'暂无项目描述')}</p>
      <div class="project-card-metrics"><span><b>${p.docs||0}</b> 知识条目</span><span><b>${p.open_todos||0}</b> 待办</span><span><b>${p.milestones||0}</b> 里程碑</span></div>
      <div class="project-card-meta"><span>最近编辑 ${esc(fmtTime(p.last_updated))}</span><span>创建 ${esc(fmtDate(p.created))}</span></div>
      <div class="project-card-actions"><button class="secondary-btn" data-project-edit="${esc(p.id)}">编辑</button><button class="ghost-btn danger-text" data-project-delete="${esc(p.id)}">删除</button></div>
    </section>`;
  }

  function openProjectEditor(p=null){
    const editing=!!p;
    modal(editing?'编辑项目':'新建项目',`<div class="project-form">
      <label><span>项目名称</span><input class="search-input" id="pm-name" value="${esc(p?.name||'')}" maxlength="100" placeholder="请输入项目名称"></label>
      <label><span>项目状态</span><select class="search-input" id="pm-status">${STATUS.map(s=>`<option ${p?.status===s?'selected':''}>${s}</option>`).join('')}</select></label>
      <label class="wide"><span>项目描述</span><textarea class="search-input" id="pm-desc" rows="5" placeholder="简要说明项目目标、阶段或范围">${esc(p?.description||'')}</textarea></label>
      ${editing?`<div class="wide project-id-note">唯一 ID：<code>${esc(p.id)}</code>。重命名项目不会改变此 ID。</div>`:''}
    </div>`,`<button class="secondary-btn" id="pm-cancel">取消</button><button class="primary-btn" id="pm-save">保存</button>`);
    $('#pm-cancel').onclick=closeModal;
    $('#pm-save').onclick=async()=>{
      const body={name:$('#pm-name').value.trim(),status:$('#pm-status').value,description:$('#pm-desc').value.trim()};
      if(!body.name)return toast('项目名称不能为空',true);
      try{
        if(editing) await api('/api/projects/'+encodeURIComponent(p.id),{method:'POST',body});
        else await api('/api/project-records',{method:'POST',body});
        closeModal();toast(editing?'项目已更新':'项目已创建');await showProjects();
      }catch(e){toast(e.message,true)}
    };
  }

  async function deleteProject(p){
    if(!p)return;
    if(!await window.ERWDialog.confirm(`删除项目“${p.name}”？\n\n知识条目不会被删除，只会解除该项目关联；项目工程目录会移入 Workspace/System/Trash/Projects。`))return;
    try{await api('/api/projects/'+encodeURIComponent(p.id),{method:'DELETE'});toast('项目已删除，工程目录已移入回收目录');await showProjects()}catch(e){toast(e.message,true)}
  }

  function enhanceMilestones(){
    const root=$('#ms-view'); if(!root)return;
    const timeline=$('.timeline',root), three=$('.milestone-3d-layout',root); if(!timeline&&!three)return;
    if(!$('.milestone-status-filter',root)){
      const bar=document.createElement('div');bar.className='milestone-status-filter';
      bar.innerHTML=`<span>状态筛选</span><select class="mini-select" id="milestone-status-filter"><option value="">全部状态</option>${['计划','进行中','受阻','完成'].map(s=>`<option value="${s}" ${milestoneStatus===s?'selected':''}>${s}</option>`).join('')}</select>`;
      root.insertAdjacentElement('afterbegin',bar);
      $('#milestone-status-filter',root).onchange=e=>{milestoneStatus=e.target.value;localStorage.setItem('milestoneStatusFilter',milestoneStatus);applyMilestoneFilter(root)};
    }
    applyMilestoneFilter(root);
  }

  function applyMilestoneFilter(root){
    $$('.timeline-item',root).forEach(x=>{const s=$('.badge',x)?.textContent.trim()||'';x.hidden=!!milestoneStatus&&s!==milestoneStatus});
    $$('.timeline-3d-card',root).forEach(x=>{const txt=$('.row-meta',x)?.textContent||'';const status=txt.split('·').pop().trim();x.hidden=!!milestoneStatus&&status!==milestoneStatus});
  }

  function fixPreviewImages(root=document){
    $$('img',root).forEach(img=>{
      const raw=img.getAttribute('src')||'';
      if(/^\.\.\/(?:\.\.\/)?Attachments\//.test(raw)){
        const rest=raw.replace(/^\.\.\/(?:\.\.\/)?Attachments\//,'');
        img.setAttribute('src','/workspace-file/Knowledge/Attachments/'+rest);
      }
    });
  }

  window.ERWDom.onChildList(()=>{   /* v261009 · A9：共享 DOM 变更接缝 */
    enhanceMilestones();
    fixPreviewImages(document);
  }, {root:'html'});

  window.ERWPanels.register({id:'projects',group:'core',before:'todos',label:'项目',icon:'▥',
    eyebrow:'CORE WORK',title:'项目',render:showProjects});
  setTimeout(()=>{enhanceMilestones();fixPreviewImages()},100);
})();

(() => {
  'use strict';

  const qs = (s, root=document) => root.querySelector(s);
  const qsa = (s, root=document) => [...root.querySelectorAll(s)];

  const clampZoom = (value) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return 100;
    return Math.max(10, Math.min(200, Math.round(n / 10) * 10));
  };
  const readZoom = key => clampZoom(localStorage.getItem(key) || 100);
  const writeZoom = (key, value) => {
    const z = clampZoom(value);
    localStorage.setItem(key, String(z));
    return z;
  };
  const zoomOptions = current => Array.from({length:20}, (_,i)=>(i+1)*10)
    .map(n=>`<option value="${n}" ${n===current?'selected':''}>${n}%</option>`).join('');

  function applyEditorZoom(){
    const pane=qs('#editor-pane'); if(!pane)return;
    const edit=readZoom('erwEditorZoom'), preview=readZoom('erwPreviewZoom');
    pane.style.setProperty('--md-edit-scale', String(edit/100));
    pane.style.setProperty('--md-preview-scale', String(preview/100));
    const a=qs('[data-editor-zoom="edit"]'), b=qs('[data-editor-zoom="preview"]');
    if(a)a.value=String(edit); if(b)b.value=String(preview);
  }

  function injectEditorZoomControls(){
    const toolbar=qs('#doc-editor .toolbar');
    if(!toolbar){return;}
    if(toolbar.querySelector('.editor-zoom-controls')){applyEditorZoom();return;}
    const edit=readZoom('erwEditorZoom'), preview=readZoom('erwPreviewZoom');
    const box=document.createElement('div');
    box.className='editor-zoom-controls';
    box.innerHTML=`<label class="editor-zoom-field" title="Markdown 编辑区缩放"><span>编辑</span><select data-editor-zoom="edit" aria-label="编辑区缩放">${zoomOptions(edit)}</select></label><label class="editor-zoom-field" title="Markdown 预览区缩放"><span>预览</span><select data-editor-zoom="preview" aria-label="预览区缩放">${zoomOptions(preview)}</select></label>`;
    const tabs=toolbar.querySelector('.editor-tabs');
    if(tabs)toolbar.insertBefore(box,tabs);else toolbar.appendChild(box);
    qsa('[data-editor-zoom]',box).forEach(sel=>sel.addEventListener('change',()=>{
      writeZoom(sel.dataset.editorZoom==='edit'?'erwEditorZoom':'erwPreviewZoom',sel.value);
      applyEditorZoom();
    }));
    applyEditorZoom();
  }

  /* Only CURRENT TASKS and NEXT MILESTONE are capped here. Research Rhythm is untouched. */
  function limitOverviewRows(ops){
    if(!ops)return;
    const cards=[...ops.children];
    [1,2].forEach(i=>{
      const card=cards[i]; if(!card)return;
      qsa('.list-row',card).forEach((row,index)=>{
        row.style.display=index>=3?'none':'';
      });
    });
  }

  function openRecentDoc(card, docId){
    const allButton=qs('[data-go]',card);
    if(!allButton)return;
    allButton.click();
    let tries=0;
    const timer=setInterval(()=>{
      const target=qsa('[data-doc-id]').find(el=>el.dataset.docId===String(docId));
      if(target){clearInterval(timer);target.click();return;}
      if(++tries>=30)clearInterval(timer);
    },80);
  }

  function paintRecentCard(card, docs){
    const head=qs('.card-head',card); if(!head)return;
    [...card.children].forEach(child=>{if(child!==head)child.remove();});
    const rows=(docs||[]).slice(0,10);
    if(!rows.length){
      const empty=document.createElement('div');
      empty.className='empty';
      empty.style.minHeight='120px';
      empty.textContent='暂无内容';
      card.appendChild(empty);
      return;
    }
    rows.forEach(doc=>{
      const row=document.createElement('div');
      row.className='list-row clickable';
      const main=document.createElement('div'); main.className='row-main';
      const title=document.createElement('div'); title.className='row-title'; title.textContent=doc.title||'未命名';
      const meta=document.createElement('div'); meta.className='row-meta'; meta.textContent=`${doc.project||'未归属项目'} · ${doc.status||''}`;
      main.append(title,meta); row.appendChild(main);
      row.addEventListener('click',()=>openRecentDoc(card,doc.id));
      card.appendChild(row);
    });
  }

  async function expandRecentResearch(dashboard){
    const group=qs('.overview-recent-group',dashboard); if(!group||group.dataset.recentExpanded==='loading'||group.dataset.recentExpanded==='done')return;
    const cards=qsa('.recent-card',group); if(cards.length<3)return;
    group.dataset.recentExpanded='loading';
    const specs=[['idea',cards[0]],['note',cards[1]],['summary',cards[2]]];
    try{
      const results=await Promise.all(specs.map(async([kind])=>{
        const res=await (window.erwFetch||fetch)('/api/docs?kind='+encodeURIComponent(kind));
        if(!res.ok)throw new Error(`HTTP ${res.status}`);
        const data=await res.json();
        return Array.isArray(data)?data.slice(0,5):[]; /* v260922i2 · 笔记行数 6→5，压缩最近卡高度 */
      }));
      specs.forEach(([,card],i)=>paintRecentCard(card,results[i]));
      group.dataset.recentExpanded='done';
    }catch(err){
      console.warn('recent research expansion failed',err);
      group.dataset.recentExpanded='error';
    }
  }

  function enhanceOverviewLayout(){
    const dashboard=qs('#main .overview-dashboard'); if(!dashboard)return;
    if(!qs(':scope > .overview-mid-band',dashboard)){
      const today=qs(':scope > .overview-today',dashboard), quick=qs(':scope > .quick-capture-card',dashboard), ops=qs(':scope > .overview-ops-grid',dashboard);
      if(today&&quick&&ops){
        const band=document.createElement('div');band.className='overview-mid-band';
        const left=document.createElement('div');left.className='overview-mid-left';
        dashboard.insertBefore(band,today);left.append(today,quick);band.append(left,ops);
      }
    }
    if(!qs(':scope > .overview-lower-band',dashboard)){
      const project=qs(':scope > .project-pulse-card',dashboard), stats=qs(':scope > .overview-stats',dashboard), heading=qs(':scope > .section-title',dashboard), recent=heading?.nextElementSibling;
      if(project&&stats&&heading&&recent?.classList.contains('grid-3')){
        const band=document.createElement('div');band.className='overview-lower-band';
        const left=document.createElement('div');left.className='overview-lower-left';
        const right=document.createElement('div');right.className='overview-recent-group';
        dashboard.insertBefore(band,project);left.append(project,stats);right.append(heading,recent);band.append(left,right);
      }
    }
    limitOverviewRows(qs('.overview-mid-band .overview-ops-grid',dashboard)||qs('.overview-ops-grid',dashboard));
    expandRecentResearch(dashboard);
    dashboard.dataset.layoutEnhanced='1';
  }

  let scheduled=false;
  function enhance(){scheduled=false;enhanceOverviewLayout();injectEditorZoomControls();}
  function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(enhance);}
  function start(){window.ERWDom.onChildList(schedule,{root:'#main'});schedule();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();



(() => {
  'use strict';
  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=(v='')=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const route=()=> (location.hash||'#overview').slice(1).split('?')[0];
  async function api(url,opts={}){const init={...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}};if(init.body&&typeof init.body!=='string')init.body=JSON.stringify(init.body);const r=await (window.erwFetch||fetch)(url,init);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.message||d.error||`HTTP ${r.status}`);return d}
  function toast(msg,bad=false){const root=$('#toast-stack');if(!root)return;const el=document.createElement('div');el.className='toast'+(bad?' error':'');el.textContent=msg;root.appendChild(el);setTimeout(()=>el.remove(),3200)}

  function installSidebarToggle(){
    const top=$('.topbar');if(!top||$('#sidebar-toggle'))return;
    const btn=document.createElement('button');btn.id='sidebar-toggle';btn.className='sidebar-toggle-btn';btn.type='button';btn.title='收起 / 展开侧边栏';btn.setAttribute('aria-label','收起 / 展开侧边栏');btn.textContent='☰';
    top.insertBefore(btn,top.firstChild);
    const saved=localStorage.getItem('sidebarCollapsed')==='1';document.body.classList.toggle('sidebar-collapsed',saved);
    const sync=()=>{const c=document.body.classList.contains('sidebar-collapsed');btn.textContent=c?'☰':'⇤';btn.title=c?'展开侧边栏':'收起侧边栏';btn.setAttribute('aria-expanded',String(!c))};
    btn.onclick=()=>{document.body.classList.toggle('sidebar-collapsed');localStorage.setItem('sidebarCollapsed',document.body.classList.contains('sidebar-collapsed')?'1':'0');sync()};sync();
  }

  let managerState=null;
  async function renderProfileManager(){
    const panel=$('#settings-panel');if(!panel||route()!=='settings')return;
    const cfg=await api('/api/config');const app=cfg.app||{},llm=app.llm||{};const profiles=JSON.parse(JSON.stringify(llm.profiles||[]));
    if(!profiles.length)return;
    managerState={cfg,app,llm,profiles,activeId:llm.active_profile_id||profiles[0].id,selectedId:llm.active_profile_id||profiles[0].id,openModes:{}}; /* v260929d · openModes：每个配置下展开编辑的请求模式 id 集合（默认全部收起省空间） */
    paintManagerShell(panel);paintProfileEditor();
  }
  function paintManagerShell(panel){
    const s=managerState;
    panel.innerHTML=`<div class="card-head"><div><div class="card-kicker">OPENAI COMPATIBLE PROFILES</div><h3>Agent API 配置</h3><p class="row-meta">多套配置保存在本地 config/secret.json；系统提示词统一保存在 app.json。只使用 OpenAI-compatible Chat Completions。</p></div></div>
    <div class="agent-profile-settings"><aside class="agent-profile-list"><div class="agent-profile-list-head"><h4>配置列表</h4><button class="primary-btn" id="profile-add">＋</button></div><div class="agent-profile-items" id="profile-items"></div></aside><section class="agent-profile-editor" id="profile-editor"></section></div>
    <div class="field" style="margin-top:14px"><label>统一系统提示词</label><textarea id="global-system-prompt" style="min-height:120px">${esc(s.llm.system_prompt||'')}</textarea><p class="row-meta">对所有模型请求生效的全局提示词；悬浮球 AI 助手的角色化提示词（阅读助手 / 执行助手 / 术语建档员等）在设置页「AI 助手人设」tab 中单独配置（由插件 floating-assist 提供）。</p></div>
    <div class="agent-settings-footer"><div class="left"><label class="badge"><input type="checkbox" id="agent-enabled" ${s.llm.enabled?'checked':''}> 启用 Agent</label><label class="badge"><input type="checkbox" id="llm-vision-global" ${s.llm.vision_enabled?'checked':''}> 多模态 / 截图识别</label><span class="row-meta">开启后阅读区 AI 面板可用「截取当前页 / 框选区域」代替选中文本；需模型支持图片输入（如 qwen-vl / gpt-4o 系列）。</span></div><button class="primary-btn" id="profile-save-all">保存全部配置</button></div>`;
    $('#profile-add').onclick=()=>{const id='profile-'+Date.now();s.profiles.push({id,name:'未命名配置',base_url:'https://api.openai.com/v1',has_api_key:false,headers:{},timeout:120,max_output_tokens:0,temperature:null,show_reasoning:true,default_request_preset:'default',request_presets:[{id:'default',label:'默认',model:'',temperature:null,params:{}}]});s.selectedId=id;paintProfileList();paintProfileEditor()};
    $('#profile-save-all').onclick=saveAllProfiles;paintProfileList();
    /* v261009.16 · 人设编辑器已随悬浮球模块搬成插件 plugins/floating-assist（作为它的设置页 tab）：
       内核不再插 #erw-persona-host、也不再广播 erw-llm-settings-rendered。 */
  }
  function paintProfileList(){
    const s=managerState,root=$('#profile-items');if(!root)return;root.innerHTML=s.profiles.map(p=>`<button class="agent-profile-item ${p.id===s.selectedId?'active':''}" data-profile-id="${esc(p.id)}"><span class="profile-state"><span class="profile-dot ${p.id===s.activeId?'on':''}"></span><strong>${esc(p.name||'未命名配置')}</strong></span><small>${esc(p.base_url||'')} · ${(p.request_presets||[]).length} 模式</small></button>`).join('');$$('[data-profile-id]',root).forEach(b=>b.onclick=()=>{captureEditor();s.selectedId=b.dataset.profileId;paintProfileList();paintProfileEditor()})
  }
  function selectedProfile(){return managerState?.profiles.find(p=>p.id===managerState.selectedId)}
  function paintProfileEditor(){
    const p=selectedProfile(),root=$('#profile-editor');if(!p||!root)return;const modes=p.request_presets||[];
    root.innerHTML=`<div class="agent-profile-editor-head"><div><div class="card-kicker">PROFILE</div><h3>${esc(p.name||'未命名配置')}</h3></div><div class="agent-profile-editor-actions"><button class="secondary-btn" id="profile-activate">${p.id===managerState.activeId?'当前已激活':'设为当前配置'}</button><button class="secondary-btn" id="profile-test">测试连接</button><button class="ghost-btn danger" id="profile-delete" ${managerState.profiles.length<=1?'disabled':''}>删除</button></div></div>
    <div class="agent-profile-grid">
      <div class="field span-2"><label>配置名称</label><input id="pf-name" value="${esc(p.name||'')}"></div>
      <div class="field span-2"><label>Base URL</label><input id="pf-base" value="${esc(p.base_url||'')}"></div>
      <div class="field span-2"><label>API Key</label><input id="pf-key" type="password" placeholder="${p.has_api_key?'已保存；留空则保持原 Key':'输入 API Key'}"></div>
      <div class="field"><label>超时 / 秒</label><input id="pf-timeout" type="number" min="5" max="600" value="${Number(p.timeout||120)}"></div>
      <div class="field"><label>最大输出 tokens</label><input id="pf-max" type="number" min="0" value="${Number(p.max_output_tokens||0)}"></div>
      <div class="field"><label>默认 Temperature</label><input id="pf-temp" type="number" min="0" max="2" step="0.1" value="${p.temperature==null?'':p.temperature}" placeholder="留空 = 不发送"></div>
      <div class="field"><label>思考过程</label><select id="pf-reason"><option value="1" ${p.show_reasoning!==false?'selected':''}>显示</option><option value="0" ${p.show_reasoning===false?'selected':''}>隐藏</option></select></div>
      <div class="field span-2"><label>自定义请求头（JSON，留空即不加）</label><textarea class="search-input" id="pf-headers" style="min-height:72px" placeholder='{"x-opencode-session":"ses_xxx"}'>${esc(JSON.stringify(p.headers&&Object.keys(p.headers).length?p.headers:{},null,2))}</textarea><p class="row-meta">按配置附加的 HTTP 请求头。例：直连 opencode.ai Zen Go 必须带 <code>x-opencode-session</code>（缺它上游返回 400）；<code>Authorization</code> 与 <code>Content-Type</code> 由工作台接管，写在这里也不生效。</p></div>
    </div><div class="agent-secret-note">Key 仅保存在本机 config/secret.json。仓库 .gitignore 已忽略整个 config/ 目录。</div>
    <div class="agent-mode-section"><div class="agent-mode-head"><div><h4>请求模式</h4><span class="row-meta">每个模式保存 id、label、模型名、可选 temperature 和 params。</span></div><button class="secondary-btn" id="mode-add">＋ 新增模式</button></div><div class="agent-mode-list" id="mode-list">${modes.map(modeRow).join('')}</div></div>`;
    $('#profile-activate').onclick=()=>{captureEditor();managerState.activeId=p.id;paintProfileList();paintProfileEditor()};
    $('#profile-delete').onclick=()=>{if(managerState.profiles.length<=1)return;managerState.profiles=managerState.profiles.filter(x=>x.id!==p.id);if(managerState.activeId===p.id)managerState.activeId=managerState.profiles[0].id;managerState.selectedId=managerState.profiles[0].id;paintProfileList();paintProfileEditor()};
    $('#mode-add').onclick=()=>{captureEditor();p.request_presets.push({id:'mode-'+(p.request_presets.length+1),label:'新模式',model:'',temperature:null,params:{}});const nm=p.request_presets[p.request_presets.length-1];(managerState.openModes[p.id]||(managerState.openModes[p.id]=new Set())).add(nm.id);paintProfileEditor()}; /* v260929d · 新增模式自动展开 */
    $('#profile-test').onclick=async()=>{try{captureEditor();managerState.activeId=p.id;await saveAllProfiles(false);const r=await api('/api/agent/test',{method:'POST',body:{}});toast(r.models?.length?`连接成功：${r.models.slice(0,3).join(' / ')}`:'连接成功')}catch(e){toast(e.message,true)}};
    wireModeDeletes();
  }
  function modeRow(m,i){const pid=selectedProfile()?.id,open=!!managerState.openModes?.[pid]?.has(m.id);return `<div class="agent-mode-row${open?' open':''}" data-mode-row="${i}"><input class="search-input" data-mode-id value="${esc(m.id||'')}" placeholder="id"><input class="search-input" data-mode-label value="${esc(m.label||'')}" placeholder="label"><input class="search-input" data-mode-model value="${esc(m.model||'')}" placeholder="模型名"><label class="mode-default"><input type="radio" name="mode-default" value="${esc(m.id||'')}" ${m.id===selectedProfile()?.default_request_preset?'checked':''}> 默认</label><button class="ghost-btn mode-toggle" type="button" data-mode-toggle="${i}" title="${open?'收起':'展开'}">${open?'▾':'▸'}</button><div class="agent-mode-body"><input class="search-input" data-mode-temp type="number" min="0" max="2" step="0.1" value="${m.temperature==null?'':m.temperature}" placeholder="温度"><button class="ghost-btn danger mode-delete" type="button" data-mode-delete="${i}">删除</button><textarea class="search-input mode-params" data-mode-params placeholder='{"reasoning_effort":"low"}'>${esc(JSON.stringify(m.params||{},null,2))}</textarea></div></div>`} /* v260929d · 模式行折叠：头部只留 id/label/模型/默认/▸，温度与 params 藏进 body（DOM 常驻，captureEditor 仍可读到） */
  function wireModeDeletes(){$$('[data-mode-toggle]').forEach(b=>b.onclick=()=>{const p=selectedProfile();const set=managerState.openModes[p.id]||(managerState.openModes[p.id]=new Set());const id=$(`[data-mode-row="${b.dataset.modeToggle}"] [data-mode-id]`)?.value.trim()||p.request_presets[Number(b.dataset.modeToggle)]?.id;if(id)set.has(id)?set.delete(id):set.add(id);paintProfileEditor()});$$('[data-mode-delete]').forEach(b=>b.onclick=()=>{captureEditor();const p=selectedProfile();p.request_presets.splice(Number(b.dataset.modeDelete),1);if(!p.request_presets.length)p.request_presets=[{id:'default',label:'默认',model:'',temperature:null,params:{}}];if(!p.request_presets.some(x=>x.id===p.default_request_preset))p.default_request_preset=p.request_presets[0].id;paintProfileEditor()})}
  function captureEditor(){
    const p=selectedProfile();if(!p||!$('#pf-name'))return;
    p.name=$('#pf-name').value.trim()||'未命名配置';p.base_url=$('#pf-base').value.trim();const key=$('#pf-key').value.trim();if(key)p.api_key=key;p.timeout=Math.max(5,Math.min(600,Number($('#pf-timeout').value)||120));p.max_output_tokens=Math.max(0,Number($('#pf-max').value)||0);p.temperature=$('#pf-temp').value.trim()===''?null:Number($('#pf-temp').value);p.show_reasoning=$('#pf-reason').value==='1';let hdr={};try{hdr=JSON.parse($('#pf-headers')?.value||'{}')}catch{throw new Error('自定义请求头必须是合法 JSON 对象')}if(!hdr||Array.isArray(hdr)||typeof hdr!=='object')throw new Error('自定义请求头必须是 JSON 对象');p.headers=hdr; /* v261008 · 档案级自定义请求头（直连 Zen Go 等网关用） */
    const modes=[];$$('[data-mode-row]').forEach(r=>{let params={};try{params=JSON.parse($('[data-mode-params]',r).value||'{}')}catch{throw new Error('请求模式 params 必须是合法 JSON 对象')}if(!params||Array.isArray(params)||typeof params!=='object')throw new Error('请求模式 params 必须是 JSON 对象');const id=$('[data-mode-id]',r).value.trim();if(!id)throw new Error('请求模式 id 不能为空');modes.push({id,label:$('[data-mode-label]',r).value.trim()||id,model:$('[data-mode-model]',r).value.trim(),temperature:$('[data-mode-temp]',r).value.trim()===''?null:Number($('[data-mode-temp]',r).value),params})});
    const ids=new Set();for(const m of modes){if(ids.has(m.id))throw new Error('请求模式 id 不能重复：'+m.id);ids.add(m.id)}p.request_presets=modes;const checked=$('input[name="mode-default"]:checked');p.default_request_preset=checked?.value||modes[0]?.id||'default';
  }
  async function saveAllProfiles(notify=true){
    try{captureEditor();const s=managerState;s.app.llm={...s.app.llm,enabled:$('#agent-enabled')?.checked===true,vision_enabled:$('#llm-vision-global')?.checked===true,system_prompt:$('#global-system-prompt')?.value||'',active_profile_id:s.activeId,profiles:s.profiles};const saved=await api('/api/config/app',{method:'POST',body:s.app});window.ERWConfigSync?.(saved); /* v260929d · 回写主应用 state.config，多模态开关等免刷新生效 */s.cfg.app=saved;s.app=saved;s.llm=saved.llm||{};s.profiles=JSON.parse(JSON.stringify(s.llm.profiles||[]));s.activeId=s.llm.active_profile_id||s.profiles[0]?.id;s.selectedId=s.activeId;paintManagerShell($('#settings-panel'));paintProfileEditor();if(notify)toast('Agent 配置已保存')}catch(e){toast(e.message,true);throw e}
  }

  async function enhanceAgentPage(){
    if(route()!=='agent')return;const preset=$('#agent-preset');if(!preset||$('#agent-profile-select'))return;const cfg=await api('/api/config');const llm=cfg.app?.llm||{},profiles=llm.profiles||[];if(!profiles.length)return;
    /* v261008c · 徽标改为显示「接口地址主机」而不是把选中项名字重复一遍：
       select 里已经有配置名，这里给的是 直连(域名) / 本地反代理(127.0.0.1:9355) / 方舟 这类一眼可辨的信息 */
    const hostOf=p=>{try{return new URL(p?.base_url||'').host||'—'}catch{return String(p?.base_url||'').replace(/^https?:\/\//,'').split('/')[0]||'—'}};
    const active0=profiles.find(p=>p.id===llm.active_profile_id)||profiles[0];
    const wrap=document.createElement('div');wrap.className='agent-runtime-selects';wrap.innerHTML=`<label>API 配置 <select class="search-input" id="agent-profile-select">${profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===llm.active_profile_id?'selected':''}>${esc(p.name||'未命名配置')}</option>`).join('')}</select></label><span class="agent-profile-badge" id="agent-profile-badge" title="接口地址：${esc(active0?.base_url||'')}">${esc(hostOf(active0))}</span>`;
    preset.closest('.agent-preset-label')?.parentElement?.insertBefore(wrap,preset.closest('.agent-preset-label'));
    $('#agent-profile-select').onchange=async()=>{const fresh=await api('/api/config');fresh.app.llm.active_profile_id=$('#agent-profile-select').value;const saved=await api('/api/config/app',{method:'POST',body:fresh.app});const active=saved.llm?.profiles?.find(p=>p.id===saved.llm.active_profile_id);const badge=$('#agent-profile-badge');if(badge){badge.textContent=hostOf(active);badge.title='接口地址：'+(active?.base_url||'')}const modes=active?.request_presets||[];preset.innerHTML=modes.map((m,i)=>`<option value="${esc(m.id)}" ${m.id===active?.default_request_preset||(!active?.default_request_preset&&i===0)?'selected':''}>${esc(m.label||m.id)}</option>`).join('');preset.dispatchEvent(new Event('change',{bubbles:true}));toast('已切换 Agent API 配置')};
  }

  function onSettingsClick(e){const btn=e.target.closest('[data-set-tab="llm"]');if(!btn)return;setTimeout(()=>renderProfileManager().catch(err=>toast(err.message,true)),0)}
  window.addEventListener('DOMContentLoaded',()=>{installSidebarToggle();document.addEventListener('click',onSettingsClick);window.ERWDom.onChildList(()=>{installSidebarToggle();if(route()==='agent')enhanceAgentPage().catch(()=>{})});if(route()==='agent')enhanceAgentPage().catch(()=>{})});
  window.addEventListener('hashchange',()=>setTimeout(()=>{installSidebarToggle();if(route()==='agent')enhanceAgentPage().catch(()=>{})},0));
})();
