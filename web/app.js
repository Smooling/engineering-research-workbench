(() => {
  'use strict';

  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];
  const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const today = () => { const d=new Date(); const z=n=>String(n).padStart(2,'0'); return `${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}`; };
  const fmtDate = (s) => {
    if (!s) return '—';
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : String(s);
  };
  /* v261019 · 待办截止时间精确到分：`YYYY-MM-DD HH:MM`；只有日期时按当天 23:59 口径显示。 */
  const dueParts = (s) => {
    const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
    return m ? { ymd: `${m[1]}-${m[2]}-${m[3]}`, hm: m[4] ? `${m[4]}:${m[5]}` : '' } : null;
  };
  const fmtDue = (s) => {
    const p = dueParts(s);
    if (!p) return s ? String(s) : '—';
    return p.hm ? `${p.ymd.slice(5)} ${p.hm}` : p.ymd.slice(5);
  };
  const dueFromInputs = (date, time) => (!date ? '' : (time ? `${date} ${time}` : date));
  const dueTimeOf = (s) => dueParts(s)?.hm || '';
  const fmtTime = (s) => {
    if (!s) return '—';
    try { return new Date(s).toLocaleString('zh-CN', {hour12:false}); } catch { return s; }
  };
  const debounce = (fn, ms=250) => { let t; return (...args) => { clearTimeout(t); t=setTimeout(()=>fn(...args),ms); }; };
  const readAsDataUrl = (file) => new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file)});
  const storedArray = (key, fallback) => { try { const x=JSON.parse(localStorage.getItem(key)||'null'); return Array.isArray(x)?x:fallback; } catch { return fallback; } };
  const storedInt = (key, fallback, min, max) => { const raw=localStorage.getItem(key); const n=Number(raw); return raw!=null&&Number.isFinite(n)?Math.max(min,Math.min(max,Math.round(n))):fallback; };

  /* v261008.2 · 关系层：类型化关系（由「关联」段小标题推导）+ 标签/项目两种结构关系 */
  const GRAPH_RELATION_LABELS = [
    ['uses-knowledge','依据知识'], ['uses-data','使用数据'], ['cites','引用文献'], ['series','同系列'],
    ['chain-prev','上一环节'], ['chain-next','下一环节'], ['produces','产出汇总'],
    ['wikilink','显式引用'], ['tag','标签关联'], ['project','项目归属']
  ];
  const GRAPH_RELATION_IDS = GRAPH_RELATION_LABELS.map(x=>x[0]);
  const savedHeatmapThresholds = (()=>{try{const v=JSON.parse(localStorage.getItem('heatmapThresholds')||'null');if(Array.isArray(v)&&v.length===2){const a=Math.max(1,Math.round(+v[0]||1)),b=Math.max(a+1,Math.round(+v[1]||3));return [a,b]}}catch{}return [1,3]})();
  const savedHeatmapColors = (()=>{try{const v=JSON.parse(localStorage.getItem('heatmapColors')||'null');if(Array.isArray(v)&&v.length===3&&v.every(x=>/^#[0-9a-f]{6}$/i.test(String(x))))return v}catch{}return ['#C9D4F7','#8297E5','#4059B8']})();

  const state = {
    config: null, statuses: {}, projects: [], route: 'overview', docs: [], selectedDoc: null,
    editorMode: 'split', milestoneView: 'timeline', graphView: '2d', graph: null, graphSelected: null, graphPreviewSeq: 0, previewSeq: 0,
    graphKinds: new Set(storedArray('graphKinds', ['idea','journal','note','experiment','milestone','summary','literature','project','tag'])),
    graphRelations: new Set(storedArray('graphRelations', GRAPH_RELATION_IDS)),
    tagOptions: [],
    agentSession: null, agentRefs: [], agentImages: [], agentPreset: localStorage.getItem('agentRequestPreset') || '', agentSending:false,
    heatmapMonths: storedInt('heatmapMonths', 12, 1, 12), heatmapThresholds: savedHeatmapThresholds, heatmapColors: savedHeatmapColors, heatmapObserver: null, uiScale: storedInt('uiScale', 100, 80, 125), density: localStorage.getItem('pageDensity')==='cozy'?'cozy':'compact', /* v260922h · 默认紧凑型（并排一屏收纳） */
    sidebarPinned: new Set(storedArray('sidebarPinned', ['core'])),
    sidebarOpen: new Set(storedArray('sidebarOpen', ['core','resources','system'])),
    knowledgeTypes: [],
    dirty: false, editorBaseline:null, draft:null, saving:null, leaving:null, docSelectSeq: 0, docSelection: new Set(), todoSelection: new Set(), todoEditing:null, docSelectionMode:false, todoSelectionMode:false, bulkBusy:false,
  };
  window.ERWDesktop = {...window.ERWDesktop, hasUnsavedChanges: () => editorDirty()||!!state.saving,
    documentOpen: () => !!state.selectedDoc, documentDraft: () => !!state.selectedDoc?.draft,
    prepareToLeave: () => guardEditor('退出工作台'),
    requestExit: async token => {let approved=false;try{approved=await guardEditor('退出工作台');if(approved){state.dirty=false;state.editorBaseline=null}}catch(error){toast(error.message,true)}await window.pywebview.api.desktop_resolve_exit(token,approved)}};

  const BUILTIN_KIND_ROUTE = {ideas:'idea', journals:'journal', notes:'note', experiments:'experiment', milestones:'milestone', summaries:'summary', literature:'literature'};
  const BUILTIN_ROUTE_KIND = {idea:'ideas', journal:'journals', note:'notes', experiment:'experiments', milestone:'milestones', summary:'summaries', literature:'literature'};
  function configuredKnowledgeTypes(){
    const rows=state.knowledgeTypes?.length?state.knowledgeTypes:(state.config?.app?.knowledge_types?.registry||[]);
    return Array.isArray(rows)?rows:[];
  }
  function knowledgeType(kind){return configuredKnowledgeTypes().find(x=>x.id===kind)||null}
  function kindFromRoute(route){
    if(BUILTIN_KIND_ROUTE[route])return BUILTIN_KIND_ROUTE[route];
    if(route.startsWith('kind-'))return decodeURIComponent(route.slice(5));
    return '';
  }

  const NAV_GROUPS = [
    {id:'core', label:'核心工作', items:[
      ['overview','概览','▦'], ['todos','待办','✓'], ['agent','Agent','◉']
    ]},
    {id:'research', label:'研究 · 知识', defaultCollapsed:true, items:[
      ['ideas','灵感','✦'], ['journals','研究日志','▤'], ['notes','笔记','▧'],
      ['experiments','实验','⚗'],
      ['milestones','里程碑','⚑'], ['summaries','工作总结','▣'], ['literature','文献','◫'], ['graph','知识图谱','⌬']
    ]},
    {id:'resources', label:'资源', items:[['folders','文件夹','▱']]},
    {id:'system', label:'系统', items:[['settings','设置','⚙']]}
  ];

  /* v261009 · §6.3 前端面板注册表。
     目标：**内核不认识具体功能**——功能自己登记导航项、标题与渲染函数，内核只负责挂载。
     这解掉的是 P14/§6.7 红线 5「内核功能依赖某个补丁才能工作」：此前 app.js 里硬编码了
     用量计费（导航项 + PAGE_META + 路由分支 + 页面壳），删掉计费模块就会白屏。
     面板形如：{ id, group, label, icon, eyebrow, title, before?, render(mainEl) }
     槽位面板形如：{ id, slot: 'topbar', label, renderSlot(containerEl) } —— 画进内核给的槽位
     设置页贡献形如：{ id, settingsTab: { label, render(containerEl) } } —— 往「设置」里加一个 tab */
  const PANELS = [];
  const SLOTS = { topbar: true, overlay: true };
  window.ERWPanels = {
    register(panel){
      if(!panel || !panel.id) throw new Error('ERWPanels.register 需要 {id, ...}');
      if(PANELS.some(p => p.id === panel.id)) throw new Error('面板 id 重复：' + panel.id);
      if(panel.slot && !SLOTS[panel.slot]) throw new Error('未知槽位：' + panel.slot);
      /* 三项能力各自独立声明，按声明的能力挂载（不禁「面板 + 设置页」这种组合）：
         render → 侧栏导航页；slot + renderSlot → 画进内核槽位；settingsTab → 「设置」里加一个 tab；
         readerTab → 文献阅读区右侧加一个 tab */
      if(panel.render !== undefined && typeof panel.render !== 'function') throw new Error('render 必须是函数');
      if(panel.slot && typeof panel.renderSlot !== 'function') throw new Error('槽位面板需要 renderSlot(container)');
      if(panel.settingsTab && typeof panel.settingsTab.render !== 'function') throw new Error('settingsTab 需要 render(container)');
      if(panel.readerTab && typeof panel.readerTab.render !== 'function') throw new Error('readerTab 需要 render(container, context)');
      if(!panel.render && !panel.slot && !panel.settingsTab && !panel.readerTab)
        throw new Error('面板至少要声明 render(main) / slot+renderSlot(container) / settingsTab.render(container) / readerTab.render(container, context) 之一');
      PANELS.push(panel);
      return panel.id;
    },
    list(){ return PANELS.slice(); },
    get(id){ return PANELS.find(p => p.id === id) || null; },
    /* 设置页 tab：面板可通过 settingsTab 贡献（内核「设置」页只负责把它们排进去） */
    settingsTabs(){
      return PANELS.filter(p => p.settingsTab).map(p => ({
        id: p.settingsTab.id || p.id,
        label: p.settingsTab.label || p.label || p.id,
        render: p.settingsTab.render,
      }));
    },
    /* 文献阅读区 tab：面板可通过 readerTab 贡献（阅读器只负责把它们排进右侧 tab 行）。
       阅读器会传入上下文 {paper, refreshList, aiPolish}，见 literature.js。 */
    readerTabs(){
      return PANELS.filter(p => p.readerTab).map(p => ({
        id: p.readerTab.id || p.id,
        label: p.readerTab.label || p.label || p.id,
        title: p.readerTab.title || '',
        render: p.readerTab.render,
      }));
    },
  };

  /* v261009.13 · §6.3 渲染接管接缝；v261009.18 · 图谱可视化**整体由插件提供**（连页面 markup 也在插件里）。
     内核不再自带渲染器：`graph.mount(host, ctx)` 由插件画整页、`overview.enhance(canvas, ctx)` 画总览迷你图；
     接管者缺席时内核只给一条「请启用插件」的提示（用户明确要求去掉旧的那份难看兜底图）。
     注册形如 { id, graph?: {mount(host, ctx)}, overview?: {enhance(canvas, ctx)} }；
     两者都可返回 Promise：内核 await 它，抛错则打日志并显示提示。 */
  const GRAPH_RENDERERS = [];
  window.ERWGraphRenderers = {
    register(r){
      if(!r || !r.id) throw new Error('ERWGraphRenderers.register 需要 {id, ...}');
      if(!r.graph && !r.overview) throw new Error('图谱接管至少要声明 graph 或 overview 之一');
      if(r.graph && typeof r.graph.enhance !== 'function' && typeof r.graph.mount !== 'function')
        throw new Error('graph 需要 enhance(canvas) 或 mount(host, ctx)');
      if(r.overview && typeof r.overview.enhance !== 'function') throw new Error('overview.enhance 必须是函数');
      if(GRAPH_RENDERERS.some(x => x.id === r.id)) throw new Error('图谱接管 id 重复：' + r.id);
      GRAPH_RENDERERS.push(r);
      return r.id;
    },
    list(){ return GRAPH_RENDERERS.slice(); },
    get(scope){ return GRAPH_RENDERERS.find(r => r[scope]) || null; },   /* scope: 'graph' | 'overview' */
  };

  /* v261009.14 · §6.3 阅读区接管接缝：PDF 阅读工作区（打开/翻页/缩放/批注/AI tab/插件 tab）可由附属模块提供。
     内核只保留文献**数据与文件服务**（`/api/literature/*`、PDF 与 `Annotations/`）与**文献列表条目页**
     （与笔记/灵感共用的 `renderDocsPage`）；没有接管者时列表页照常可用，只是「PDF 阅读工作区」入口
     不出现、点附件徽章给一条明确提示（SCOPE §2.1 C6：2026-10-10 起阅读区改为附属插件）。
     注册形如 `{id, open(paperId?), openByAttachment(attachment), context?()}`。 */
  const READER_MISSING = '阅读区不可用：请在「设置 → 插件」里启用「文献阅读工作区」';
  const READERS = [];
  window.ERWReader = {
    register(r){
      if(!r || !r.id) throw new Error('ERWReader.register 需要 {id, ...}');
      if(typeof r.open !== 'function') throw new Error('阅读区接管需要 open(paperId)');
      if(typeof r.openByAttachment !== 'function') throw new Error('阅读区接管需要 openByAttachment(attachment)');
      if(READERS.some(x => x.id === r.id)) throw new Error('阅读区接管 id 重复：' + r.id);
      READERS.push(r);
      return r.id;
    },
    list(){ return READERS.slice(); },
    get(){ return READERS[0] || null; },
    available(){ return READERS.length > 0; },
    context(){ try{ return this.get()?.context?.() || null; }catch{ return null; } },
    async open(paperId){ const r=this.get(); if(!r) throw new Error(READER_MISSING); return r.open(paperId); },
    async openByAttachment(att){ const r=this.get(); if(!r) throw new Error(READER_MISSING); return r.openByAttachment(att); },
  };

  /* 槽位挂载：内核把槽位容器交给槽位面板，容器上带 data-plugin=<id> 以便插件样式作用域（§2）。
     插件只在这个容器里画东西，不去改内核 DOM。 */
  function mountSlots(){
    $$('[data-erw-slot]').forEach(host=>{
      host.querySelectorAll('[data-plugin]').forEach(el=>el.remove());   /* 重挂时先清掉自己上一轮画的 */
      PANELS.filter(p=>p.slot === host.dataset.erwSlot).forEach(p=>{
        const box = document.createElement('span');
        box.className = 'plugin-slot-item';
        box.dataset.plugin = p.id;
        host.appendChild(box);
        try{ p.renderSlot(box); }
        catch(err){ console.error('[panel] 槽位渲染失败 ' + p.id + '：' + (err && err.message ? err.message : err)); }
      });
    });
  }

  const PAGE_META = {
    overview:['CORE WORK','概览'], todos:['CORE WORK','待办'], agent:['CORE WORK','科研 Agent'],
    'research-overview':['RESEARCH KNOWLEDGE','研究 · 知识总览'], ideas:['RESEARCH KNOWLEDGE','灵感'], journals:['RESEARCH KNOWLEDGE','研究日志'],
    notes:['RESEARCH KNOWLEDGE','笔记'], experiments:['RESEARCH KNOWLEDGE','实验'], milestones:['RESEARCH KNOWLEDGE','里程碑'], summaries:['RESEARCH KNOWLEDGE','工作总结'],
    literature:['RESEARCH KNOWLEDGE','文献'], graph:['RESEARCH KNOWLEDGE','知识图谱'], folders:['RESOURCES','文件夹'], settings:['SYSTEM','设置']
  };

  const KIND_ROUTE = {ideas:'idea', journals:'journal', notes:'note', experiments:'experiment', milestones:'milestone', summaries:'summary', literature:'literature'};
  const KIND_LABEL = {idea:'灵感', journal:'研究日志', note:'笔记', experiment:'实验', milestone:'里程碑', summary:'工作总结', literature:'文献'};

  /* v261009 · 分类标记统一由 app.json 管理；默认仅保留知识 / 方法 / 实验，增减在设置页完成。 */
  const DEFAULT_KIND_MARKS=[
    {id:'knowledge',icon:'◈',label:'知识',color:'#2a9d8f'},
    {id:'method',icon:'⚒',label:'方法',color:'#e76f51'},
    {id:'experiment',icon:'⚗',label:'实验',color:'#d1569a'}
  ];
  /* v261020 · 分类标记内置模板（与 core/contracts/kinds.py 的 MARK_IDS 对齐）。
     正常走 /api/knowledge-marks 取服务端数据；这里只作接口不可用时的兜底展示。 */
  const MARK_TEMPLATE_FALLBACK=[
    {id:'knowledge',icon:'◈',label:'知识',color:'#2a9d8f',hint:'术语、概念与机制'},
    {id:'synthesis',icon:'◎',label:'归类',color:'#6b7fd7',hint:'跨族归并与索引'},
    {id:'method',icon:'⚒',label:'方法',color:'#e76f51',hint:'算法、流程与操作口径'},
    {id:'question',icon:'？',label:'问题',color:'#d1495b',hint:'待解疑问与风险'},
    {id:'thinking',icon:'✦',label:'思路',color:'#f4a261',hint:'猜想、方案与思路'},
    {id:'architecture',icon:'▤',label:'架构',color:'#4a6fa5',hint:'结构设计与模块边界'},
    {id:'experiment',icon:'⚗',label:'实验',color:'#d1569a',hint:'实验记录与结论'},
    {id:'data',icon:'⊞',label:'数据',color:'#2d7dd2',hint:'数据集与选型'},
    {id:'model',icon:'⬡',label:'模型',color:'#8e6fbf',hint:'模型、训练与推理设置'},
    {id:'principle',icon:'∑',label:'原理',color:'#7a8b3a',hint:'原理、度量与数学基础'}
  ];
  /* v261020 · 标记图案面板：分组陈列，兼顾符号/emoji 与科研场景。 */
  const MARK_ICON_GROUPS=[
    {name:'几何',icons:['◆','◇','●','○','■','□','▲','△','▶','▷','◈','◉','⬡','⬢','▣','▤']},
    {name:'科研',icons:['⚗','⚛','∑','∫','∞','≡','⊞','⊟','⌬','☰','⚙','⚑','✎','✍','☀','☾']},
    {name:'符号',icons:['✦','✧','★','☆','✱','✳','❖','⚡','☁','❄','☯','⚖','⌁','⟡','⌘','⌥']},
    {name:'标记',icons:['✓','✔','✗','✘','❗','❓','➜','⇢','↗','↘','⟳','⌛','⏱','⇧','◎','？']}
  ];
  function allMarks(){
    const rows=state.config?.app?.classification_marks;
    return Array.isArray(rows)?rows:DEFAULT_KIND_MARKS;
  }
  function kindLabel(kind){ return knowledgeType(kind)?.label || KIND_LABEL[kind] || kind; }

  /* v261009.13 · §6.3 契约接缝：把内核的「七类 kind / 类别词 / 标记 / 关系」视图**只读**暴露给附属模块，
     免得插件各抄一份中文标签（此前图谱补丁与内核就各有一份）。权威声明仍在 core/contracts/。 */
  window.ERWContract = {
    kinds(){ return Object.keys(KIND_LABEL); },
    kindLabels(){ return {...KIND_LABEL}; },
    kindLabel(kind){ return kindLabel(kind); },
    /* 图谱里的节点类型比七类多两种虚拟实体：标签节点与项目节点 */
    entityLabel(kind){ return KIND_LABEL[kind] || ({project:'项目', tag:'标签'}[kind]) || kind; },
    marks(){ return allMarks().map(m=>({id:m.id, icon:m.icon, label:m.label, color:m.color})); },
    relations(){ return GRAPH_RELATION_LABELS.map(([id,label])=>({id, label})); },
    relationLabel(id){ const hit=GRAPH_RELATION_LABELS.find(x=>x[0]===id); return hit ? hit[1] : id; },
  };

  /* v261009.13 · §6.3 Markdown 接缝：附属模块渲染笔记正文时走内核同一套
     （marked + DOMPurify + hljs + mermaid/mathjax 按需），观感一致，且以后加渲染钩子只改一处。 */
  window.ERWMarkdown = {
    renderInto(el, raw){ return renderMarkdownInto(el, raw); },
    /* v261009.13 · Workspace 相对路径图片（批注截图 / 笔记插图）归一化为 /workspace-file/：
       renderMarkdownInto 本身不做这步（内核在笔记预览处另调），图谱节点预览需要它，
       故把内核已有的 normalizePreviewPaths 一并暴露，免得上层再抄一份规则。 */
    normalizePaths(html){ return normalizePreviewPaths(html); },
  };

  async function api(url, opts={}) {
    const init = {...opts, headers:{'Content-Type':'application/json', ...(opts.headers||{})}};
    if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
    const res = await (window.erwFetch || fetch)(url, init);
    let data = null; try { data = await res.json(); } catch { data = {}; }
    if (!res.ok) {const error=new Error(data.message || data.error || `HTTP ${res.status}`);error.status=res.status;throw error;}
    return data;
  }

  async function bootstrapRead(url){
    for(let attempt=0;attempt<3;attempt++){
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
      try{return await api(url,{signal:controller.signal})}
      catch(error){if(attempt===2||(error.status&&error.status<500))throw error}
      finally{clearTimeout(timeout)}
      await new Promise(resolve=>setTimeout(resolve,150*(attempt+1)));
    }
  }

  function toast(message, error=false) {
    const el = document.createElement('div'); el.className = 'toast' + (error?' error':''); el.textContent = message;
    $('#toast-stack').appendChild(el); setTimeout(()=>el.remove(), 3200);
  }
  /* v261009.16 · 通用 UI 接缝：提示条。此前 5 个模块各写一份 toast（app.js / research-pages /
     plugin-manager / floating-agent / literature），插件也没有稳定入口；内核这份从此对外可用，
     插件优先用它、缺失时自行兜底（ERWToast 缺席不该报错）。 */
  window.ERWToast = toast;
  /* v261022.3 · 上游 Agent 系统模块（agent-system.js / agent-client.js）依赖的宿主接口：
     本地 Agent 页用自己的实现、也没有悬浮助手时间线，这里给最小适配——
     缺失的能力按空值降级（页面照常打开，只是少跳转/少渲染一段回复）。 */
  window.ERWAgentPage = window.ERWAgentPage || {
    sessionId:()=>state.agentSession||null,
    refresh:async()=>{ if(state.route==='agent'&&state.agentSession) await loadAgentSession(state.agentSession); },
    quote:()=>{}, searchSelection:()=>{}
  };
  window.ERWResearchUI = window.ERWResearchUI || {
    esc,
    projectLabel:n=>n,
    loadProjects:async()=>{ const rows=await api('/api/projects')||[]; return rows.map(p=>p.name||p); },
    evidenceBadge:()=>''
  };
  window.ERWFabTimeline = window.ERWFabTimeline || { responses:()=>'', render:()=>'', retrievals:()=>'' };
  /* v261022.4 · 本地没有面板级文本缩放模块：给空实现，引用预览照常渲染、只是不能单独缩放正文 */
  window.ERWPaneZoom = window.ERWPaneZoom || { bindText:()=>{} };

  function modal(title, bodyHtml, footerHtml='') {
    $('#modal-title').textContent = title; $('#modal-body').innerHTML = bodyHtml; $('#modal-footer').innerHTML = footerHtml;
    $('#modal-backdrop').classList.remove('hidden');
  }
  function closeModal(){ $('#modal-backdrop').classList.add('hidden'); }

  function editorPayload(doc){
    const value=id=>$('#'+id)?.value||'',projects=editorProjects();
    const body={title:value('f-title').trim(),project:projects[0]||'',projects,status:value('f-status'),tags:editorTags(),kind_marks:$$('#f-marks .mark-chip.on').map(b=>b.dataset.mark),body:value('md-input'),pinned:!!$('#f-pinned')?.checked};
    const dateField=({journal:'record_date',milestone:'due',summary:'record_date',literature:'added_date'})[doc.kind];
    if(dateField)body[dateField]=value('f-date')||today();
    if(doc.kind==='summary')body.summary_type=value('f-summary-type');
    if(doc.kind==='literature')Object.assign(body,{authors:value('f-authors'),year:value('f-year'),venue:value('f-venue'),doi:value('f-doi'),url:value('f-url'),cite_key:value('f-cite-key'),attachment:value('f-attachment').trim(),bibtex:value('f-bibtex')});
    return body;
  }
  function editorDirty(){
    if(state.editorBaseline!==null&&state.selectedDoc&&$('#md-input'))state.dirty=JSON.stringify(editorPayload(state.selectedDoc))!==state.editorBaseline;
    return state.dirty;
  }
  async function guardEditor(action='离开当前文档'){
    if(state.saving){try{await state.saving}catch{return false}}
    if(!editorDirty())return true;
    if(state.leaving)return state.leaving;
    state.leaving=(async()=>{
      const answer=await window.ERWDialog.choose(`“${$('#f-title')?.value||state.selectedDoc?.title||'当前文档'}”有未保存的修改。${action}前是否保存？`,{title:'保存文档修改？',buttons:[{value:'cancel',label:'继续编辑'},{value:'discard',label:'不保存'},{value:'save',label:'保存并继续',primary:true}]});
      if(answer==='cancel')return false;
      if(answer==='save'){try{await saveCurrentDoc(state.selectedDoc);if(editorDirty()){toast('当次内容已保存，但还有新的修改，请确认后再离开');return false}}catch{return false}}
      return true;
    })();
    try{return await state.leaving}finally{state.leaving=null}
  }

  function saveSidebarState(){
    localStorage.setItem('sidebarPinned', JSON.stringify([...state.sidebarPinned]));
    localStorage.setItem('sidebarOpen', JSON.stringify([...state.sidebarOpen]));
  }

  function navGroups(){
    const groups = NAV_GROUPS.map(g=>({...g, items:[...g.items]}));
    /* 面板登记项并入导航：默认追加到声明分组末尾；给 before 则插到该路由之前。
       进导航的**只有**声明了 render 的面板——槽位面板画进内核槽位，只贡献设置页 tab 的
       面板（如「插件」页）也不该在侧栏里多出一项。 */
    for(const panel of PANELS){
      if(panel.slot || typeof panel.render !== 'function') continue;
      const groupId = panel.group || 'system';
      let group = groups.find(g=>g.id===groupId);
      if(!group){ group = {id:groupId, label:panel.group_label||'扩展', items:[]}; groups.push(group); }
      const item = [panel.id, panel.label||panel.id, panel.icon||'▪'];
      const at = panel.before ? group.items.findIndex(it=>it[0]===panel.before) : -1;
      if(at>=0) group.items.splice(at, 0, item); else group.items.push(item);
    }
    /* v261015 · 自定义知识类型：app.json 里新增的类型也进侧栏（内置七类已在 NAV_GROUPS 声明，
       故只补未出现的）；插到 research 组的「知识图谱」之前，与静态顺序一致。 */
    const research = groups.find(g=>g.id==='research');
    if(research){
      const known = new Set(research.items.map(it=>it[0]));
      const extra = configuredKnowledgeTypes()
        .filter(x=>!x.hidden)
        .map(x=>[routeForKind(x.id), x.label, x.icon||'◆'])
        .filter(it=>!known.has(it[0]));
      const at = research.items.findIndex(it=>it[0]==='graph');
      if(at>=0) research.items.splice(at, 0, ...extra); else research.items.push(...extra);
    }
    return groups;
  }

  function renderSidebar(){
    const nav = $('#sidebar-nav');
    nav.innerHTML = navGroups().map(g => {
      const pinned = state.sidebarPinned.has(g.id);
      const open = pinned || state.sidebarOpen.has(g.id);
      return `<section class="nav-group ${open?'':'collapsed'} ${pinned?'pinned':''}" data-group="${g.id}">
        <div class="nav-group-head"><button class="group-toggle" type="button" data-group-toggle="${g.id}" aria-expanded="${open}"><span class="group-disclosure" aria-hidden="true"></span><span>${g.label}</span></button><button class="pin" type="button" data-pin-group="${g.id}" title="常驻展开" aria-label="${pinned?'取消常驻展开':'常驻展开'}：${g.label}" aria-pressed="${pinned}">◆</button></div>
        <div class="nav-items">${g.items.map(([id,label,ico])=>`<a class="nav-item ${state.route===id?'active':''}" href="#${id}" data-route="${id}" aria-label="${esc(label)}" title="${esc(label)}"><span class="nav-ico">${ico}</span><span>${label}</span></a>`).join('')}</div>
      </section>`;
    }).join('');
    $$('[data-group-toggle]', nav).forEach(btn => btn.addEventListener('click', e => {
      if (e.target.closest('[data-pin-group]')) return;
      const id=btn.dataset.groupToggle; if(state.sidebarPinned.has(id)) return;
      if(state.sidebarOpen.has(id)) state.sidebarOpen.delete(id); else state.sidebarOpen.add(id);
      const open=state.sidebarOpen.has(id);btn.setAttribute('aria-expanded',String(open));btn.closest('.nav-group').classList.toggle('collapsed',!open);saveSidebarState();
    }));
    $$('[data-pin-group]', nav).forEach(btn => btn.addEventListener('click', e => {
      e.stopPropagation(); const id=btn.dataset.pinGroup;
      if(state.sidebarPinned.has(id)) state.sidebarPinned.delete(id); else {state.sidebarPinned.add(id); state.sidebarOpen.add(id);} saveSidebarState(); renderSidebar();
    }));
    $$('[data-route]', nav).forEach(a => a.addEventListener('click', e=>{ e.preventDefault(); navigate(a.dataset.route); }));
  }

  function setHeader(route){
    let eyebrow,pageTitle;
    const panel = window.ERWPanels.get(route);
    const meta = PAGE_META[route] || (panel ? [panel.eyebrow || 'EXTENSION', panel.title || panel.label || route] : null);
    const dynamicKind = kindFromRoute(route);
    if(meta){ [eyebrow,pageTitle]=meta; }
    else if(dynamicKind){eyebrow='RESEARCH KNOWLEDGE';pageTitle=kindLabel(dynamicKind)}
    else { eyebrow='WORKBENCH'; pageTitle=route; }
    $('#page-title').textContent=pageTitle;
    const d=new Date(); $('#page-date').textContent = d.toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short'});
    document.title = `${pageTitle} · ${state.config?.app?.app_name || '科研工作台'}`;
  }

  async function navigate(route){
    if(state.bulkBusy){toast('正在删除所选条目，请稍候');return false}
    if(route==='research-overview')route='overview'; // Keep old bookmarks working after removing the duplicate page.
    if (!await guardEditor('离开当前页面')){if(location.hash.slice(1)!==state.route)location.replace('#'+state.route);return false}
    if(route!=='milestones')window.ERWMilestoneTimeline?.destroy?.(); /* v260930g9c · 返回 false 供 ERWNav 等调用方感知取消 */
    state.dirty=false;state.editorBaseline=null;state.draft=null;state.selectedDoc=null;window.ERWCurrentDoc='';++state.docSelectSeq;
    state.docSelection.clear();state.todoSelection.clear();
    state.docSelectionMode=false;state.todoSelectionMode=false;state.todoEditing=null;
    state.route=route; location.hash=route; document.documentElement.dataset.route=route; document.documentElement.dataset.knowledgeKind=kindFromRoute(route)||''; renderSidebar(); setHeader(route);
    if(state.heatmapObserver){try{state.heatmapObserver.disconnect();}catch{} state.heatmapObserver=null;}
    /* v260923u · 切页不再先清空主区为 LOADING：保留旧页面内容直到新页数据就绪后一次性替换，
     * 消除「白一下→加载→跳变」的重新加载感。navSeq 序号守卫：快速连点时丢弃过期渲染的收尾动画/错误覆盖。 */
    const seq=state.navSeq=(state.navSeq||0)+1;
    const mainEl=$('#main');
    /* v261009.22 · 挂载点标记：内核在插件自登记的容器上写 data-plugin=<id>，插件样式才能按
       §2 作用域（此前只有槽位容器带这个属性，导航页/设置 tab 拿不到，§2 的规则对它们落不了地）。
       每次导航先清掉上一轮的值，避免插件 CSS 泄漏到内核页面。 */
    if(mainEl) delete mainEl.dataset.plugin;
    try {
      if(route==='overview') await renderOverview();
      else if(route==='todos') await renderTodos();
      else if(route==='agent') await renderAgent();
      else if(route==='graph') await renderGraphPage();
      else if(route==='folders') await renderFolders();
      else if(route==='settings') await renderSettings();
      else if(window.ERWPanels.get(route)?.render){
        const panel=window.ERWPanels.get(route);
        if(mainEl) mainEl.dataset.plugin=panel.id;
        await panel.render(mainEl); /* 面板登记项（槽位面板没有 render，不进这里） */
      }
      else if(KIND_ROUTE[route]) await renderDocsPage(KIND_ROUTE[route]);
      else if(kindFromRoute(route)) await renderDocsPage(kindFromRoute(route));
      else await renderOverview();
      if(seq!==state.navSeq) return false; /* v260930g9c · 已被更新导航取代：视为未完成 */
      animateMain();
    } catch(err){
      if(seq!==state.navSeq) return false;
      console.error(err); $('#main').innerHTML=`<div class="card card-pad danger">加载失败：${esc(err.message)}</div>`; animateMain();
    }
    return true; /* v260930g9c · 导航成功完成 */
  }

  function animateMain(){
    const main=$('#main');
    if(!main || state.config?.app?.ui?.animations===false || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const heading=$('.page-heading');
    main.classList.remove('route-enter');
    heading?.classList.remove('heading-enter');
    void main.offsetWidth;
    main.classList.add('route-enter');
    heading?.classList.add('heading-enter');
    setTimeout(()=>main.classList.remove('route-enter'),760);
    setTimeout(()=>heading?.classList.remove('heading-enter'),620);
  }

  function animateSubView(el){
    if(!el || state.config?.app?.ui?.animations===false || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    el.classList.remove('subview-enter'); void el.offsetWidth; el.classList.add('subview-enter'); setTimeout(()=>el.classList.remove('subview-enter'),360);
  }

  function sortTodos(items,now=today()){
    /* v261019 · 截止时间可精确到分：比较用完整时刻，只有日期时按当天 23:59。 */
    const stamp=s=>{const p=dueParts(s);if(!p)return NaN;return Date.parse(`${p.ymd}T${p.hm||'23:59'}:00`)};
    const day=s=>/^\d{4}-\d{2}-\d{2}/.test(s||'')?Date.parse(String(s).slice(0,10)+'T12:00:00'):NaN;
    const reference=day(now),priority={紧急:0,高:1,普通:2,低:3};
    const distance=s=>Number.isFinite(stamp(s))?Math.abs(stamp(s)-reference):Infinity;
    return [...items].sort((a,b)=>Number(!!a.done)-Number(!!b.done)||distance(a.due)-distance(b.due)||(priority[a.priority]??2)-(priority[b.priority]??2)||String(a.due||'9999').localeCompare(String(b.due||'9999'))||String(a.id).localeCompare(String(b.id)));
  }

  async function loadOverviewMilestones(){
    const rows=[];
    for(let page=1;;page++){
      const result=await api(`/api/docs?kind=milestone&scope=overview&paged=1&page_size=200&page=${page}`);
      rows.push(...(Array.isArray(result)?result:result.items||[]));
      if(Array.isArray(result)||!result.next_page)break;
    }
    return rows;
  }

  async function renderOverview(){
    const taskScroll=$('.overview-task-list')?.scrollTop||0;
    const [dash,todosList,milestones] = await Promise.all([api('/api/dashboard'), api('/api/todos'),loadOverviewMilestones()]);
    if(state.route!=='overview')return;
    const openTodos=sortTodos(todosList.filter(x=>!x.done),dash.today||today());
    const academic=dash.academic||{};
    const activity=dash.activity||{days:[],active_days_month:0,events_month:0,current_streak:0,longest_streak:0};
    const d=new Date((dash.today||today())+'T00:00:00');
    const dateTitle=d.toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});
    const recentToday=(activity.days||[]).find(x=>x.date===dash.today)?.count||0;
    $('#main').innerHTML = `<div class="overview-dashboard">
      <div class="overview-top-row">
        ${researchHeatmapCard(activity)}
        <div class="overview-academic-grid">
          ${academicProgressCard(academic)}
          ${graduationConditionsCard(academic)}
        </div>
      </div>

      <div class="overview-mid-row">
        <section class="card overview-today">
          <div>

            <h3>今天 · ${esc(dateTitle)}</h3>

          </div>
          <div class="today-metrics">
            <div><strong>${todosList.filter(x=>!x.done).length}</strong><span>未完成待办</span></div>
            <div><strong>${activity.active_days_month||0}</strong><span>本月活跃日</span></div>
            <div><strong>${activity.events_month||0}</strong><span>本月科研记录</span></div>
            <div><strong>${recentToday}</strong><span>今日科研记录</span></div>
          </div>
        </section>

        <section class="card quick-capture-card">
          <div class="quick-capture-copy"><h3>快速记录</h3></div>
          <div class="quick-capture-actions">
            <button class="quick-action" data-quick-doc="ideas"><span>✦</span><b>灵感</b></button>
            <button class="quick-action" data-quick-doc="journals"><span>▤</span><b>实验记录</b></button>
            <button class="quick-action" data-quick-doc="notes"><span>▧</span><b>笔记</b></button>
            <button class="quick-action" data-quick-doc="literature"><span>◫</span><b>文献</b></button>
            <button class="quick-action" data-quick-doc="milestones"><span>⚑</span><b>里程碑</b></button>
          </div>
        </section>
      </div>

      <div class="grid grid-3 overview-ops-grid">
        ${researchRhythmCard(activity,academic,todosList,dash.today||today())}
        ${overviewTaskCard(openTodos)}
        ${overviewMilestoneCard(milestones,dash.today||today())}
      </div>

      <div class="overview-lower-band">
        <div class="overview-lower-left">
          ${projectPulseCard(dash.project_stats||[])}
          <div class="grid grid-4 overview-stats">
            ${stat('笔记',dash.counts.note||0,'NOTES')}
            ${stat('文献',dash.counts.literature||0,'LITERATURE')}
            ${stat('里程碑',dash.counts.milestone||0,'MILESTONES')}
            ${stat('实验记录',dash.counts.journal||0,'JOURNALS')}
          </div>
        </div>
        <section class="overview-recent-section">
          <div class="section-title overview-recent-head"><div><h3>最近研究活动</h3></div><button class="secondary-btn" data-go="graph">探索关联</button></div>
          <div class="grid grid-3 overview-recent-group">${recentCard('最近灵感',dash.recent.ideas,'ideas')}${recentCard('最近笔记',dash.recent.notes,'notes')}${recentCard('最近工作总结',dash.recent.summaries,'summaries')}</div>
        </section>
      </div>
    </div>`;
    wireGo();
    fitResearchHeatmap();
    requestAnimationFrame(()=>{
      const tasks=$('.overview-task-list');if(tasks)tasks.scrollTop=taskScroll;
      centerOverviewMilestone();
    });
  }

  function academicProgressCard(a){
    const configured=!!a.configured;
    const pct=Number(a.percent||0);
    return `<section class="card academic-progress-card">
      <div class="card-head"><div><h3>${esc(a.degree_name||'学业进度')}</h3></div><button class="ghost-btn" data-go="settings">设置</button></div>
      ${configured?`<div class="degree-progress-value">${pct.toFixed(1)}<span>%</span></div>
      <div class="degree-progress-track"><i style="width:${Math.max(0,Math.min(100,pct))}%"></i></div>
      <div class="degree-progress-dates"><span>开始 ${esc(a.start_date)}</span><span>预计完成 ${esc(a.expected_end_date)}</span></div>
      <div class="degree-progress-foot"><span>已进行 <strong>${a.elapsed_days||0}</strong> 天</span><span>剩余 <strong>${a.remaining_days||0}</strong> 天</span></div>`:
      `<div class="academic-empty"><strong>尚未配置学业周期</strong><span>在「设置 → 学业与目标」中填写开始日期与预计完成日期后，这里会自动计算进度。</span></div>`}
    </section>`;
  }

  function graduationConditionsCard(a){
    const items=a.graduation_conditions||[];
    return `<section class="card graduation-card"><div class="card-head"><div><h3>毕业条件</h3></div><div class="condition-score">${a.conditions_done||0}<span>/ ${a.conditions_total||0}</span></div></div>
      ${items.length?`<div class="condition-list">${items.map(x=>`<div class="condition-item"><div class="condition-line"><strong>${esc(x.label)}</strong><span>${formatMetric(x.current)} / ${formatMetric(x.target)}${esc(x.unit||'')}</span></div><div class="condition-track"><i style="width:${x.percent||0}%"></i></div></div>`).join('')}</div>`:
      `<div class="academic-empty compact"><strong>尚未配置毕业条件</strong><span>可以添加论文、会议、专利、学位论文阶段等自定义目标；数据由你自己掌控。</span><button class="secondary-btn" data-go="settings">配置目标</button></div>`}
    </section>`;
  }

  function formatMetric(v){ const n=Number(v); return Number.isFinite(n)&&Math.abs(n%1)>1e-9?n.toFixed(1):String(Number.isFinite(n)?n:(v||0)); }

  const HEATMAP_MONTH_OPTIONS=[2,4,6,12];
  const ACTIVITY_LABELS={doc_create:'新建文档',doc_update:'更新文档',doc_delete:'归档文档',todo_create:'新增任务',todo_update:'更新任务',todo_done:'完成任务',project_create:'新建项目',knowledge_export:'知识汇总',bibtex_export:'BibTeX导出',agent_chat:'Agent对话'};
  function researchHeatmapCard(activity){
    const rows=activity.days||[];
    if(!rows.length) return `<section class="card heatmap-card"><div class="card-head"><div><h3>科研热力图</h3></div></div><div class="empty">暂无活动数据</div></section>`;
    const months=Math.max(1,Math.min(12,Number(state.heatmapMonths)||12));
    const map=new Map(rows.map(x=>[x.date,x]));
    const rawEnd=new Date(activity.end+'T00:00:00');
    const rawStart=new Date(rawEnd.getFullYear(),rawEnd.getMonth()-(months-1),1);
    const start=new Date(rawStart); start.setDate(start.getDate()-((start.getDay()+6)%7));
    const end=new Date(rawEnd); end.setDate(end.getDate()+(6-((end.getDay()+6)%7)));
    const cells=[]; const z=n=>String(n).padStart(2,'0'); const iso=d=>`${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}`;
    const rangeStart=iso(rawStart), rangeEnd=iso(rawEnd);
    const cursor=new Date(start);
    while(cursor<=end){
      const key=iso(cursor), r=map.get(key), count=r?.count||0, inRange=key>=rangeStart&&key<=rangeEnd;
      const [thresholdLow,thresholdMid]=state.heatmapThresholds||[1,3];
      const level=count===0?0:count<=thresholdLow?1:count<=thresholdMid?2:3;
      const detail=r?Object.entries(r.breakdown||{}).map(([k,v])=>`${ACTIVITY_LABELS[k]||k} ${v}`).join(' · '):'';
      cells.push(`<span class="heat-cell level-${level} ${inRange?'':'outside'}" title="${esc(key)} · ${count} 次${detail?' · '+esc(detail):''}" data-date="${key}"></span>`);
      cursor.setDate(cursor.getDate()+1);
    }
    const weeks=Math.ceil(cells.length/7);
    const monthLabels=[]; const monthBoundaries=[];
    let monthCursor=new Date(rawStart.getFullYear(),rawStart.getMonth(),1);
    let monthIndex=0;
    while(monthCursor<=rawEnd){
      const diffDays=Math.round((monthCursor-start)/86400000); const col0=Math.floor(diffDays/7); const row=(monthCursor.getDay()+6)%7;
      const safeCol=Math.max(1,Math.min(weeks,col0+1));
      const next=new Date(monthCursor.getFullYear(),monthCursor.getMonth()+1,1);
      const nextDiff=Math.round((next-start)/86400000); const nextCol=Math.floor(nextDiff/7)+1;
      const span=Math.max(1,Math.min(weeks-safeCol+1,nextCol-safeCol+1));
      monthLabels.push(`<span style="grid-column:${safeCol} / span ${span}">${monthCursor.getMonth()+1}月</span>`);
      if(monthIndex>0) monthBoundaries.push(`<i class="heatmap-month-boundary" data-col0="${Math.max(0,col0)}" data-row="${row}" aria-hidden="true"></i>`);
      monthCursor=next; monthIndex++;
    }
    const monthChoices=HEATMAP_MONTH_OPTIONS.includes(months)?HEATMAP_MONTH_OPTIONS:[...HEATMAP_MONTH_OPTIONS,months].sort((a,b)=>a-b);
    const options=monthChoices.map(n=>`<option value="${n}" ${n===months?'selected':''}>近 ${n} 个月</option>`).join('');
    const [lowColor,midColor,highColor]=state.heatmapColors||['#C9D4F7','#8297E5','#4059B8'];
    const [thresholdLow,thresholdMid]=state.heatmapThresholds||[1,3];
    return `<section class="card heatmap-card" data-heatmap-weeks="${weeks}" style="--heat-low:${esc(lowColor)};--heat-mid:${esc(midColor)};--heat-high:${esc(highColor)}"><div class="card-head"><div><h3>科研热力图</h3></div><div class="heatmap-head-tools"><div class="heatmap-summary"><strong>${activity.events_month||0}</strong><span>本月记录</span><strong>${activity.active_days_month||0}</strong><span>活跃日</span></div><button class="secondary-btn heatmap-scale-btn" id="heatmap-scale-settings" type="button" title="设置活动量分界与三档颜色">色阶设置</button><select class="mini-select" id="heatmap-month-select" aria-label="科研热力图显示月份">${options}</select></div></div>
      <div class="heatmap-scroll"><div class="heatmap-plot"><div class="heatmap-axis"><div class="heatmap-axis-cap">星期</div><div class="heatmap-weekdays"><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span><span>日</span></div></div><div class="heatmap-stage"><div class="heatmap-months" style="--heat-weeks:${weeks}">${monthLabels.join('')}</div><div class="heatmap-month-boundaries">${monthBoundaries.join('')}</div><div class="heatmap-cells" style="--heat-weeks:${weeks}">${cells.join('')}</div></div></div></div>
      <div class="heatmap-footer"><span>少</span><i class="heat-cell level-0" title="0 次"></i><i class="heat-cell level-1" title="1–${thresholdLow} 次"></i><i class="heat-cell level-2" title="${thresholdLow+1}–${thresholdMid} 次"></i><i class="heat-cell level-3" title=">${thresholdMid} 次"></i><span>多</span><span class="heatmap-threshold-summary">≤${thresholdLow} / ≤${thresholdMid}</span><span class="heatmap-hint">鼠标悬停查看当天活动</span></div>
    </section>`;
  }

  function fitResearchHeatmap(){
    const card=$('.heatmap-card'); const scroll=$('.heatmap-scroll'); if(!card||!scroll) return;
    /* Soft Chromatic: the dashboard column ratio is CSS-owned and therefore no longer
     * changes when the user switches 2/4/6/12 months. Only cells adapt inside the card.
     * This keeps the academic-goal column stable and guarantees all seven weekdays fit. */
    if(!state.heatmapResizeHooked){
      state.heatmapResizeHooked=true;
      const reapply=debounce(()=>{ if(state.route==='overview') fitResearchHeatmap(); },80);
      window.addEventListener('resize',reapply);
      window.matchMedia('(min-width:1100px)').addEventListener?.('change',reapply);
    }
    const apply=()=>{
      const weeks=Math.max(1,Number(card.dataset.heatmapWeeks)||1);
      const compact=document.documentElement.dataset.density==='compact';
      const csp=getComputedStyle(card), ssp=getComputedStyle(scroll);
      const axisEl=$('.heatmap-axis',card);
      const axis=Math.max(34,axisEl?.offsetWidth||40);
      const plotGap=9, gapX=3, gapY=3;
      const chrome=axis+plotGap+
        parseFloat(csp.paddingLeft||0)+parseFloat(csp.paddingRight||0)+
        parseFloat(ssp.paddingLeft||0)+parseFloat(ssp.paddingRight||0);
      const viewport=Math.max(320,scroll.clientWidth||card.clientWidth||320);
      const usable=Math.max(1,viewport-chrome-gapX*(weeks-1));
      const longRange=weeks>=42;
      const minCellW=longRange?10:(compact?12:13);
      const maxCellW=compact?27:30;
      const cellW=Math.max(minCellW,Math.min(maxCellW,Math.floor(usable/weeks)));
      const cellH=compact?14:15;

      card.classList.toggle('is-narrow',viewport<650);
      card.style.maxWidth='';
      card.style.setProperty('--heat-cell-width',cellW+'px');
      card.style.setProperty('--heat-cell-height',cellH+'px');
      card.style.setProperty('--heat-gap-x',gapX+'px');
      card.style.setProperty('--heat-gap-y',gapY+'px');
      card.style.setProperty('--heat-cell-size',cellH+'px');
      card.style.setProperty('--heat-gap',gapY+'px');

      const stepX=cellW+gapX, stepY=cellH+gapY;
      $$('.heatmap-month-boundary',card).forEach(line=>{
        const col0=Math.max(0,Number(line.dataset.col0)||0);
        const row=Math.max(0,Math.min(6,Number(line.dataset.row)||0));
        const xLeft=col0*stepX-Math.ceil(gapX/2);
        const y=Math.max(0,row*stepY-Math.ceil(gapY/2));
        line.style.left=xLeft+'px'; line.style.top=y+'px';
        line.style.setProperty('--boundary-step-x',stepX+'px');
        line.style.setProperty('--boundary-step-y',stepY+'px');
        line.style.setProperty('--boundary-y',y+'px');
      });
    };
    apply();
    requestAnimationFrame(apply);
    if(window.ResizeObserver){
      state.heatmapObserver?.disconnect();
      state.heatmapObserver=new ResizeObserver(debounce(apply,80));
      state.heatmapObserver.observe(scroll);
    }
  }

  async function setHeatmapMonths(value){
    const months=Math.max(1,Math.min(12,Number(value)||12)); state.heatmapMonths=months; localStorage.setItem('heatmapMonths',String(months));
    if(state.config?.app){state.config.app.ui={...(state.config.app.ui||{}),heatmap_months:months}; try{await api('/api/config/app',{method:'POST',body:state.config.app});}catch(e){console.warn('heatmap preference save failed',e);}}
  }

  async function saveHeatmapScaleSettings(thresholds,colors){
    const a=Math.max(1,Math.round(Number(thresholds?.[0])||1));
    const b=Math.max(a+1,Math.round(Number(thresholds?.[1])||3));
    const defaults=['#C9D4F7','#8297E5','#4059B8'];
    const nextColors=(Array.isArray(colors)?colors:defaults).map((x,i)=>/^#[0-9a-f]{6}$/i.test(String(x||''))?String(x):defaults[i]);
    state.heatmapThresholds=[a,b]; state.heatmapColors=nextColors;
    localStorage.setItem('heatmapThresholds',JSON.stringify(state.heatmapThresholds));
    localStorage.setItem('heatmapColors',JSON.stringify(state.heatmapColors));
    if(state.config?.app){
      state.config.app.ui={...(state.config.app.ui||{}),heatmap_thresholds:[a,b],heatmap_colors:nextColors};
      try{await api('/api/config/app',{method:'POST',body:state.config.app});}
      catch(e){console.warn('heatmap scale settings save failed',e);}
    }
  }
  function openHeatmapScaleSettings(){
    const [a,b]=state.heatmapThresholds||[1,3];
    const [c1,c2,c3]=state.heatmapColors||['#C9D4F7','#8297E5','#4059B8'];
    modal('科研热力图色阶设置',`<div class="heatmap-scale-editor"><div class="heatmap-scale-copy">按“每天活动次数”划分三个非零等级。0 次始终使用中性灰，不参与阈值。</div><div class="heatmap-threshold-grid"><div class="field"><label>低 → 中分界</label><input id="hm-threshold-low" type="number" min="1" step="1" value="${a}"><span class="field-help">低活动：1 ～ 此值</span></div><div class="field"><label>中 → 高分界</label><input id="hm-threshold-mid" type="number" min="2" step="1" value="${b}"><span class="field-help">中活动：上一档 + 1 ～ 此值；高活动：超过此值</span></div></div><div class="heatmap-color-editor"><label><span>低活动</span><input id="hm-color-low" type="color" value="${esc(c1)}"><code>${esc(c1)}</code></label><label><span>中活动</span><input id="hm-color-mid" type="color" value="${esc(c2)}"><code>${esc(c2)}</code></label><label><span>高活动</span><input id="hm-color-high" type="color" value="${esc(c3)}"><code>${esc(c3)}</code></label></div><div class="heatmap-scale-preview"><i style="background:#E9EDF4"></i><i style="background:${esc(c1)}"></i><i style="background:${esc(c2)}"></i><i style="background:${esc(c3)}"></i></div></div>`,`<button class="secondary-btn" id="hm-scale-default">恢复默认</button><button class="secondary-btn" id="hm-scale-cancel">取消</button><button class="primary-btn" id="hm-scale-save">保存</button>`);
    const syncCodes=()=>[['hm-color-low',0],['hm-color-mid',1],['hm-color-high',2]].forEach(([id,i])=>{const input=$('#'+id);input.oninput=()=>{input.nextElementSibling.textContent=input.value.toUpperCase();const dots=$$('.heatmap-scale-preview i');if(dots[i+1])dots[i+1].style.background=input.value}});
    syncCodes();
    $('#hm-scale-cancel').onclick=closeModal;
    $('#hm-scale-default').onclick=()=>{ $('#hm-threshold-low').value=1;$('#hm-threshold-mid').value=3;const ds=['#C9D4F7','#8297E5','#4059B8'];['low','mid','high'].forEach((k,i)=>{const el=$('#hm-color-'+k);el.value=ds[i];el.dispatchEvent(new Event('input'))}); };
    $('#hm-scale-save').onclick=async()=>{const low=Math.max(1,Math.round(+$('#hm-threshold-low').value||1));const mid=Math.max(low+1,Math.round(+$('#hm-threshold-mid').value||3));await saveHeatmapScaleSettings([low,mid],[$('#hm-color-low').value,$('#hm-color-mid').value,$('#hm-color-high').value]);closeModal();await renderOverview();animateMain();};
  }

  function syncViewportVars(){
    /* v260929g · Chrome 的 100vh/100vw 不随根元素 zoom 折算（恒等于设备像素视口尺寸），
     * 应用内非 100% 缩放时依赖 100vh 的 sticky 全高布局会失配（设置页栏目条滚动时被推走）。
     * 这里把按 zoom 折算后的 CSS 像素视口尺寸写入变量，styles.css 的 settings-nav 高度改用该变量。 */
    const z=parseFloat(document.documentElement.style.zoom)||1;
    const s=document.documentElement.style;
    s.setProperty('--vw-px',(window.innerWidth/z)+'px');
    const chrome=document.documentElement.dataset.desktop==='true'?(window.ERWDesktop?.chromeHeight||48):0;
    s.setProperty('--vh-px',((window.innerHeight-chrome)/z)+'px');
  }

  function applyUiScale(pct){
    const v=Math.max(80,Math.min(125,Math.round(Number(pct)||100)));
    state.uiScale=v; localStorage.setItem('uiScale',String(v));
    document.documentElement.style.zoom=v===100?'':String(v/100);
    syncViewportVars(); /* v260929g · zoom 变化后重算折算视口变量 */
    /* v260923s · 根元素 zoom 变化时 ResizeObserver 不触发（局部坐标系尺寸不变），
     * 必须手动重跑热力图适配，否则 one-screen 类与内联样式残留导致小屏卡片重叠。 */
    requestAnimationFrame(()=>requestAnimationFrame(()=>{ if(state.route==='overview') fitResearchHeatmap(); }));
    const btn=$('#zoom-btn'); if(btn) btn.textContent=v+'%';
    $$('#zoom-menu button').forEach(b=>b.classList.toggle('active',Number(b.dataset.zoom)===v));
  }

  function applyDensity(mode){
    const v=mode==='cozy'?'cozy':'compact';
    state.density=v;
    document.documentElement.dataset.density=v;
    const btn=$('#density-btn'); if(btn){btn.textContent=v==='cozy'?'宽松型':'紧凑型';btn.title=v==='cozy'?'当前：宽松型（各卡片纵向排布、页面可下拉滚动）。点击切换为紧凑型':'当前：紧凑型（热力图与学业卡并排、一屏收纳免滚动）。点击切换为宽松型';}
  }

  function stableProjectAccent(name){
    const palette=['#5069DE','#168C78','#8462CB','#3488BE','#C58A31','#6979A8'];
    let h=0;for(const ch of String(name||''))h=(h*31+ch.codePointAt(0))>>>0;
    return palette[h%palette.length];
  }
  function overviewCardHeading(title,kicker,icon){
    const paths={
      rhythm:'<path d="M3 12h4l3-7 4 14 3-7h4"/>',
      tasks:'<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="m8 12 1 1 2-2m2 1h3m-8 5h8"/>',
      milestone:'<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4m8-4v4M4 10h16m-11 3v5m0-5h6l-1.5 2L15 17H9"/>',
      project:'<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Zm0 9 8-4.5M12 12 4 7.5M12 12v9M8 5.25l8 4.5"/>'
    };
    return `<div class="overview-module-heading"><span class="overview-module-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" focusable="false">${paths[icon]||''}</svg></span><h3>${esc(title)}</h3></div>`;
  }
  function projectPulseCard(items){
    const rows=(items||[]).slice(0,6);
    return `<section class="card card-pad project-pulse-card theme-card theme-project"><div class="card-head"><div>${overviewCardHeading('项目推进','PROJECT PULSE','project')}</div><div class="card-head-actions"><button class="primary-btn" id="overview-new-project">＋ 新建项目</button><button class="secondary-btn" data-go="folders">项目目录</button></div></div>${rows.length?`<div class="project-pulse-grid">${rows.map(x=>`<div class="project-pulse-item" style="--project-accent:${stableProjectAccent(x.name)}"><div class="project-pulse-name"><strong title="${esc(x.name)}">${esc(window.ERWResearchUI?.projectLabel(x.name)||x.name)}</strong><span>${x.last_updated?`更新 ${esc(fmtDate(x.last_updated))}`:'暂无更新记录'}</span></div><div class="project-pulse-metrics"><span><b>${x.docs||0}</b> 文档</span><span><b>${x.open_todos||0}</b> 待办</span><span><b>${x.open_milestones||0}</b> 待完成节点</span><span><b>${x.literature||0}</b> 文献</span></div></div>`).join('')}</div>`:`<div class="academic-empty compact"><strong>还没有科研项目</strong></div>`}</section>`;
  }

  function overviewTaskCard(items){
    return `<section class="card card-pad overview-task-card theme-card theme-task"><div class="card-head">${overviewCardHeading('当前任务','TODAY TASKS','tasks')}<button class="secondary-btn" data-go="todos">全部待办 · ${items.length}</button></div>
      <form class="overview-todo-add" id="overview-todo-form"><label class="sr-only" for="overview-todo-title">新增待办</label><input class="search-input" id="overview-todo-title" placeholder="添加一个待办，Enter 保存" required maxlength="300"><button class="primary-btn" type="submit" aria-label="添加待办">＋ 添加</button></form>
      <div class="overview-task-list" tabindex="0" aria-label="待办列表，滚动浏览全部任务">${items.length?items.map(t=>`<div class="overview-task-row ${t.overdue?'is-overdue':''}"><input type="checkbox" class="todo-check" data-overview-check="${esc(t.id)}" data-todo-overdue="${t.overdue?1:''}" data-todo-due="${esc(t.due)}" aria-label="完成任务：${esc(t.title)}"><div class="row-main"><div class="row-title" title="${esc(t.title)}">${esc(t.title)}</div><div class="row-meta">${esc(t.project||'未关联项目')}${t.done&&t.completed_at?` · 完成于 ${esc(fmtDue(t.completed_at))}`:''}</div></div><time class="overview-task-due ${t.overdue?'is-overdue':''}" title="${esc(fmtDue(t.due))}${t.overdue?'（已逾期）':''}">${esc(fmtDue(t.due))}</time>${t.priority?`<span class="badge" data-priority="${esc(t.priority)}">${esc(t.priority)}</span>`:''}</div>`).join(''):'<div class="empty compact-empty">暂无待办，添加下一步研究计划吧</div>'}</div></section>`;
  }

  function overviewMilestoneCard(items,now=today()){
    const rows=[...items].sort((a,b)=>(a.due||'9999').localeCompare(b.due||'9999')||String(a.id).localeCompare(String(b.id)));
    const reference=Date.parse(now+'T12:00:00');
    let nearest=-1,best=Infinity;
    rows.forEach((d,i)=>{const value=Date.parse((d.due||'')+'T12:00:00'),distance=Math.abs(value-reference);if(distance<best){best=distance;nearest=i}});
    return `<section class="card card-pad overview-milestone-card theme-card theme-milestone"><div class="card-head">${overviewCardHeading('近期节点','NEXT MILESTONE','milestone')}<button class="secondary-btn" data-go="milestones">时间轴</button></div>
      <div class="overview-ms-toolbar"><span>${rows.length} 个节点</span><button class="ghost-btn" id="overview-ms-center" ${nearest<0?'disabled':''}>回到临近节点</button></div>
      <div class="overview-milestone-track">${rows.length?'<span class="overview-milestone-rail" aria-hidden="true"></span>':''}<div class="overview-milestone-list" tabindex="0" aria-label="里程碑列表，滚动浏览过去与未来节点" data-nearest-index="${nearest}">${rows.length?`<div class="overview-list-spacer" aria-hidden="true"></div>${rows.map((d,i)=>`<div class="overview-milestone-row clickable ${i===nearest?'is-nearest':''}" data-open-doc="${esc(d.id)}" data-doc-route="milestones" ${i===nearest?'aria-current="date"':''}><div class="mini-ms-date"><i class="milestone-ring" aria-hidden="true"></i><strong>${esc(fmtDate(d.due))}</strong></div><div class="row-main"><div class="row-title" title="${esc(d.title)}">${esc(d.title)}</div><div class="row-meta">${esc(d.project||'未关联项目')}</div></div><span class="badge" data-status="${esc(d.status||'计划')}">${esc(d.status||'计划')}</span></div>`).join('')}<div class="overview-list-spacer" aria-hidden="true"></div>`:'<div class="empty compact-empty">暂无里程碑</div>'}</div></div></section>`;
  }

  function centerOverviewMilestone(){
    const list=$('.overview-milestone-list'),row=$('.overview-milestone-row.is-nearest',list||document);
    if(list&&row)list.scrollTop=row.offsetTop-(list.clientHeight-row.offsetHeight)/2;
  }

  function researchRhythmCard(activity,academic,todosList=[],endDate=today()){
    const goal=Math.max(1,Math.min(7,Number(academic.weekly_goal_days)||5));
    const buckets=new Map((activity.days||[]).map(x=>[x.date,x]));
    const recent=Array.from({length:14},(_,i)=>{const d=new Date(endDate+'T12:00:00');d.setDate(d.getDate()-13+i);const key=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;return buckets.get(key)||{date:key,count:0,breakdown:{}};});
    const previous=recent.splice(0,7);
    const weekActive=recent.filter(x=>x.count>0).length;
    const weekEvents=recent.reduce((a,x)=>a+(x.count||0),0);
    const previousEvents=previous.reduce((a,x)=>a+(x.count||0),0);
    const delta=weekEvents-previousEvents;
    const completed=recent.reduce((a,x)=>a+(x.breakdown?.todo_done||0),0);
    const overdue=todosList.filter(x=>!x.done&&x.overdue).length;
    const max=Math.max(1,...recent.map(x=>x.count||0));
    const pct=Math.min(100,goal?weekActive/goal*100:0);
    return `<section class="card card-pad rhythm-card"><div class="card-head">${overviewCardHeading('科研节奏','WEEKLY MOMENTUM','rhythm')}<span class="badge accent">近 7 天</span></div>
      <div class="rhythm-summary"><div><strong>${weekEvents}</strong><span>次研究活动</span></div><span class="rhythm-trend">${delta===0?'与前 7 天持平':`较前 7 天 ${delta>0?'+':''}${delta} 次`}</span></div>
      <div class="rhythm-week" role="img" aria-label="近七天研究活动：${recent.map(x=>`${x.date} ${x.count}次`).join('，')}">${recent.map(x=>`<div class="rhythm-day" title="${x.date} · ${x.count} 次活动"><span class="rhythm-day-count">${x.count}</span><div class="rhythm-bar-track"><i style="height:${Math.max(5,(x.count||0)/max*100)}%" class="${x.count?'':'is-empty'}"></i></div><time>${Number(x.date.slice(5,7))}/${Number(x.date.slice(8))}</time></div>`).join('')}</div>
      <div class="rhythm-goal"><span>活跃目标 <b>${weekActive} / ${goal} 天</b></span><span>完成待办 <b>${completed}</b></span></div><div class="condition-track"><i style="width:${pct}%"></i></div>
      <button class="rhythm-next" data-go="${overdue?'todos':'journals'}">${overdue?`有 ${overdue} 项待办已逾期，查看并安排 →`:weekActive>=goal?'近 7 天活跃目标已达成，记录最新进展 →':`还差 ${goal-weekActive} 个活跃日，记录一次实验进展 →`}</button></section>`;
  }

  function stat(label,value,kicker){return `<div class="card stat-card"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`}
  function listRows(items, empty='暂无内容'){
    if(!items.length) return `<div class="empty" style="min-height:110px">${empty}</div>`;
    return `<div class="list-stack">${items.map(x=>`<div class="list-row"><div class="row-main"><div class="row-title">${esc(x.title)}</div><div class="row-meta">${esc(x.meta||'')}</div></div></div>`).join('')}</div>`;
  }
  function recentActivityRow(doc,route=routeForKind(doc.kind)){
    const fullTitle=String(doc.title||'未命名'),label=kindLabel(doc.kind||kindFromRoute(route));
    let title=fullTitle;
    for(const separator of ['·','・',':','：']){if(title.startsWith(label+separator)){title=title.slice(label.length+1).trim();break}}
    const project=doc.project||doc.projects?.[0]||'未关联项目',status=String(doc.status||'');
    const tone=['稳定','已采纳','已定稿','完成'].includes(status)?'success':['探索中','整理中','进行中','持续维护'].includes(status)?'active':['草稿','待整理'].includes(status)?'draft':'neutral';
    return `<button type="button" class="recent-activity-row clickable" data-open-doc="${esc(doc.id)}" data-doc-route="${esc(route)}" title="${esc(fullTitle)}"><span class="row-title">${esc(title)}</span><span class="row-meta recent-activity-meta"><span class="recent-project" title="${esc(project)}">${esc(project)}</span>${status?`<span class="recent-status" data-tone="${tone}">${esc(status)}</span>`:''}</span></button>`;
  }
  window.ERWRecentActivity={row:recentActivityRow,open:async doc=>{try{await openDocRoute(routeForKind(doc.kind),doc.id)}catch(e){toast(e.message,true)}}};

  function recentCard(title,docs,route){
    const icon=route==='ideas'?'✦':route==='notes'?'▧':'◈';
    return `<section class="card recent-card recent-card-${route}"><div class="card-head recent-card-head"><div class="recent-card-title"><span class="recent-card-icon" aria-hidden="true">${icon}</span><h3>${title}</h3></div><button class="ghost-btn" data-go="${route}" aria-label="查看全部${esc(kindLabel(kindFromRoute(route)))}">全部</button></div><div class="recent-card-list">${docs.length?docs.map(d=>recentActivityRow(d,route)).join(''):`<div class="empty recent-empty">暂无内容</div>`}</div></section>`;
  }
  function wireGo(){
    $$('[data-go]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.go)));
    $$('[data-open-doc]').forEach(b=>{
      b.tabIndex=0;b.setAttribute('role','button');
      const open=async()=>{try{await openDocRoute(b.dataset.docRoute,b.dataset.openDoc)}catch(e){toast(e.message,true)}};
      b.addEventListener('click',open);
      b.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open()}});
    });
    $$('[data-quick-doc]').forEach(b=>b.addEventListener('click',async()=>{if(await navigate(b.dataset.quickDoc))setTimeout(()=>($('#new-doc')||$('#new-ms'))?.click(),30);}));
    const hm=$('#heatmap-month-select'); if(hm)hm.addEventListener('change',async()=>{await setHeatmapMonths(hm.value);await renderOverview();animateMain();});
    const center=$('#overview-ms-center');if(center)center.onclick=centerOverviewMilestone;
    const hs=$('#heatmap-scale-settings'); if(hs)hs.addEventListener('click',openHeatmapScaleSettings);
    const np=$('#overview-new-project'); if(np)np.addEventListener('click',()=>openCreateProjectModal(async()=>{await loadBootstrap();await renderOverview();animateMain();}));
    const form=$('#overview-todo-form');
    if(form)form.onsubmit=async e=>{e.preventDefault();const input=$('#overview-todo-title'),title=input.value.trim();if(!title)return;const submit=$('button',form);submit.disabled=true;try{await api('/api/todos',{method:'POST',body:{title,due:today(),priority:'普通'}});toast('待办已添加');await renderOverview()}catch(err){toast(err.message,true)}finally{submit.disabled=false}};
    $$('[data-overview-check]').forEach(x=>x.onchange=()=>confirmTodoCompletion(x,x.dataset.overviewCheck,renderOverview));
  }

  async function openDocRoute(route,id){
    const oldView=state.milestoneView;
    if(route==='milestones')state.milestoneView='docs';
    const ok=await navigate(route);
    if(ok===false){state.milestoneView=oldView;return false}
    await selectDoc(id);
    return true;
  }

  async function confirmTodoCompletion(input,id,refresh){
    const done=input.checked;
    const title=input.closest('.overview-task-row,.todo-row')?.querySelector('.row-title,.todo-title')?.textContent||'这项待办';
    const due=input.dataset.todoDue||'';
    if(done){
      /* v261019 · 完成时间限制：逾期待办需要二次确认，确认后带 force=true 提交；
         服务端同样会拦（409），这里先按界面已知的逾期状态把话说清楚。 */
      const overdue=input.dataset.todoOverdue==='1';
      const message=overdue
        ? `确认完成已逾期的“${title}”（截止 ${fmtDue(due)}）？完成时间会记为现在。`
        : `确认完成“${title}”？`;
      if(!await window.ERWDialog.confirm(message)){input.checked=false;return}
    }
    input.disabled=true;
    try{
      const body={done};
      if(done&&input.dataset.todoOverdue==='1')body.force=true;
      try{await api('/api/todos/'+encodeURIComponent(id),{method:'POST',body})}
      catch(err){
        /* 页面数据可能比服务端旧：409 + requires_confirm 时再问一次，确认后重试 force。 */
        if(done&&err.status===409&&await window.ERWDialog.confirm(err.message)){await api('/api/todos/'+encodeURIComponent(id),{method:'POST',body:{done:true,force:true}})}
        else throw err;
      }
      toast(done?'待办已完成':'待办已恢复');await refresh()
    }
    catch(e){input.checked=!done;toast(e.message,true)}
    finally{input.disabled=false}
  }

  function openCreateProjectModal(afterCreate){
    modal('新建科研项目',`<div class="field"><label>项目名称</label><input id="new-project-name-global" placeholder="请输入你的项目名称"></div><div class="row-meta" style="margin-top:8px">将自动创建 Notes / Experiments / Data / Results / Figures / Manuscript / References，并进入全局项目列表。</div>`,`<button class="secondary-btn" id="new-project-cancel-global">取消</button><button class="primary-btn" id="new-project-create-global">创建项目</button>`);
    $('#new-project-cancel-global').onclick=closeModal;
    const input=$('#new-project-name-global');setTimeout(()=>input?.focus(),30);
    $('#new-project-create-global').onclick=async()=>{const name=input.value.trim();if(!name)return toast('请输入项目名称',true);try{const r=await api('/api/workspace/project',{method:'POST',body:{name}});toast('项目已创建：'+(r.path||name));closeModal();state.projects=await api('/api/projects');if(afterCreate)await afterCreate(r);}catch(e){toast(e.message,true)}};
  }

  async function deleteSelection(collection,ids,completedOnly=false){
    if(state.bulkBusy)return null;
    state.bulkBusy=true;
    const controls=$$('[data-bulk-control]');controls.forEach(b=>b.disabled=true);
    const result={deleted:[],failed:[]};
    try{
      for(let offset=0;offset<ids.length;offset+=200){
        const chunk=ids.slice(offset,offset+200);
        try{const r=await api(`/api/${collection}/batch-delete`,{method:'POST',body:{ids:chunk,completed_only:completedOnly}});result.deleted.push(...r.deleted);result.failed.push(...r.failed)}
        catch(e){result.failed.push(...chunk.map(id=>({id,message:e.message})))}
      }
      toast(`已${collection==='docs'?'移入回收目录':'删除'} ${result.deleted.length} 条${result.failed.length?`，${result.failed.length} 条失败，已保留选择`:''}`,result.failed.length>0);
      return result;
    }finally{state.bulkBusy=false;controls.forEach(b=>b.disabled=false)}
  }

  function selectionToolbar(type){
    const docs=type==='doc';
    return `<div class="selection-toolbar" id="${type}-selection-toolbar" data-selection-toolbar="${type}" ${state[type+'SelectionMode']?'':'hidden'}><label><input type="checkbox" id="${type}-select-all" data-bulk-control> ${docs?'全选本页':'全选'}</label><span id="${type}-selected-count">已选 0 条</span><button class="ghost-btn" id="${type}-clear-selection" data-bulk-control>退出选择</button><button class="ghost-btn danger" id="${type}-delete-selected" data-bulk-control disabled>删除所选</button></div>`;
  }

  function batchModeButton(type){
    return `<button type="button" class="secondary-btn batch-mode-toggle" id="${type}-batch-toggle" data-bulk-control aria-label="批量删除" title="批量删除" aria-pressed="${!!state[type+'SelectionMode']}" aria-controls="${type}-selection-toolbar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7"/></svg></button>`;
  }

  function bindBatchModeButton(type,items){
    const toggle=$(`#${type}-batch-toggle`);if(!toggle)return;
    toggle.onclick=()=>{
      if(state.bulkBusy)return;
      if(type==='doc'&&state.route==='milestones'&&state.milestoneView!=='docs'){
        state.docSelectionMode=true;state.milestoneView='docs';renderMilestoneView();return;
      }
      state[type+'SelectionMode']=!state[type+'SelectionMode'];
      if(!state[type+'SelectionMode'])(type==='doc'?state.docSelection:state.todoSelection).clear();
      updateSelection(type,items);
    };
  }

  function updateSelection(type,items){
    const selected=type==='doc'?state.docSelection:state.todoSelection;
    const mode=state[type+'SelectionMode'];
    const toolbar=$(`#${type}-selection-toolbar`);if(toolbar)toolbar.hidden=!mode;
    const panel=type==='doc'?$('.doc-list-panel'):$('.todo-page');panel?.classList.toggle('is-selecting',mode);
    const toggle=$(`#${type}-batch-toggle`);if(toggle){toggle.setAttribute('aria-pressed',String(mode));toggle.title=mode?'退出批量删除':'批量删除';toggle.disabled=!items.length||state.bulkBusy}
    $$(`[data-${type}-pick]`).forEach(c=>{c.hidden=!mode||c.disabled;c.checked=!c.disabled&&selected.has(c.dataset[type+'Pick']);c.closest('.doc-item,.todo-row')?.classList.toggle('is-selected',mode&&c.checked)});
    const all=$(`#${type}-select-all`),count=items.filter(x=>selected.has(x.id)).length;
    if(all){all.checked=items.length>0&&count===items.length;all.indeterminate=count>0&&count<items.length;all.disabled=!items.length||state.bulkBusy}
    const counter=$(`#${type}-selected-count`);if(counter)counter.textContent=`已选 ${selected.size} 条`;
    const remove=$(`#${type}-delete-selected`);if(remove)remove.disabled=!selected.size||state.bulkBusy;
    const exit=$(`#${type}-clear-selection`);if(exit)exit.disabled=state.bulkBusy;
  }

  function wireSelection(type,items,onDelete){
    const selected=type==='doc'?state.docSelection:state.todoSelection;
    $$(`[data-${type}-pick]`).forEach(c=>c.onchange=()=>{if(c.checked)selected.add(c.dataset[type+'Pick']);else selected.delete(c.dataset[type+'Pick']);updateSelection(type,items)});
    const all=$(`#${type}-select-all`);if(all)all.onchange=()=>{items.forEach(x=>all.checked?selected.add(x.id):selected.delete(x.id));updateSelection(type,items)};
    const clear=$(`#${type}-clear-selection`);if(clear)clear.onclick=()=>{selected.clear();state[type+'SelectionMode']=false;updateSelection(type,items)};
    const remove=$(`#${type}-delete-selected`);if(remove)remove.onclick=onDelete;
    bindBatchModeButton(type,items);
    updateSelection(type,items);
  }

  async function renderTodos(){
    const [records,projects]=await Promise.all([api('/api/todos'),api('/api/projects')]);
    if(state.route!=='todos')return;
    const items=sortTodos(records),completed=items.filter(x=>x.done);
    state.todoSelection=new Set([...state.todoSelection].filter(id=>items.some(x=>x.id===id)));
    if(state.todoEditing&&!items.some(x=>x.id===state.todoEditing))state.todoEditing=null;
    $('#main').innerHTML=`<section class="card card-pad todo-page"><div class="card-head"><h3>待办</h3><button class="secondary-btn" id="todo-clear-completed" data-bulk-control ${completed.length?'':'disabled'}>清理已完成 · ${completed.length}</button></div>
      <div class="todo-add"><input class="search-input" id="todo-title" placeholder="新增任务…"><select class="search-input" id="todo-project"><option value="">不关联项目</option>${projects.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('')}</select><input class="search-input" id="todo-due" type="date" value="${today()}" aria-label="截止日期"><input class="search-input" id="todo-time" type="time" aria-label="截止时间（可选）"><select class="search-input" id="todo-priority"><option>普通</option><option>紧急</option><option>高</option><option>低</option></select><div class="todo-add-actions"><button class="primary-btn" id="todo-add">＋ 添加</button>${batchModeButton('todo')}</div></div>
      ${selectionToolbar('todo')}<div class="todo-list">${items.length?items.map(t=>todoRow(t,projects)).join(''):'<div class="empty">暂无任务</div>'}</div>
    </section>`;
    $('#todo-add').onclick=async()=>{const title=$('#todo-title').value.trim();if(!title)return;try{await api('/api/todos',{method:'POST',body:{title,project:$('#todo-project').value,due:dueFromInputs($('#todo-due').value,$('#todo-time').value),priority:$('#todo-priority').value}});toast('任务已添加');await renderTodos()}catch(e){toast(e.message,true)}};
    $$('[data-todo-check]').forEach(x=>x.onclick=()=>{x.checked=x.getAttribute('aria-checked')!=='true';confirmTodoCompletion(x,x.dataset.todoCheck,renderTodos)});
    $$('[data-todo-del]').forEach(x=>x.onclick=async()=>{if(await window.ERWDialog.confirm('删除该任务？')){try{await api('/api/todos/'+encodeURIComponent(x.dataset.todoDel),{method:'DELETE'});state.todoSelection.delete(x.dataset.todoDel);await renderTodos()}catch(e){toast(e.message,true)}}});
    $$('[data-todo-edit]').forEach(b=>b.onclick=()=>{state.todoEditing=b.dataset.todoEdit;renderTodos()});
    const editForm=$('#todo-edit-form');
    if(editForm){
      const titleInput=$('#todo-edit-title');
      setTimeout(()=>{titleInput?.focus();titleInput?.select()},20);
      $$('[data-todo-edit-cancel]').forEach(b=>b.onclick=()=>{state.todoEditing=null;renderTodos()});
      editForm.onsubmit=async e=>{
        e.preventDefault();
        const title=titleInput.value.trim();
        if(!title){toast('待办标题不能为空',true);titleInput.focus();return}
        const body={title,project:$('#todo-edit-project').value,due:dueFromInputs($('#todo-edit-date').value,$('#todo-edit-time').value),priority:$('#todo-edit-priority').value};
        try{await api('/api/todos/'+encodeURIComponent(editForm.dataset.todoEditId),{method:'POST',body});state.todoEditing=null;toast('待办已更新');await renderTodos()}
        catch(err){toast(err.message,true)}
      };
      $$('input,select',editForm).forEach(el=>el.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();state.todoEditing=null;renderTodos()}}));
    }
    const remove=async(ids,onlyDone=false)=>{
      if(!ids.length||!await window.ERWDialog.confirm(onlyDone?`确认清理 ${ids.length} 条已完成待办？未完成待办会保留。`:`确认删除所选 ${ids.length} 条待办？`))return;
      const result=await deleteSelection('todos',ids,onlyDone);if(!result)return;
      state.todoSelection=new Set(result.failed.map(x=>x.id));state.todoSelectionMode=state.todoSelection.size>0;await renderTodos();
    };
    wireSelection('todo',items,()=>remove([...state.todoSelection]));
    $('#todo-clear-completed').onclick=()=>remove(completed.map(x=>x.id),true);
  }
  function todoEditRow(t,projects){
    const date=dueParts(t.due)?.ymd||today();
    return `<div class="todo-row todo-row-editing is-editing" data-todo-row="${esc(t.id)}">
      <form class="todo-edit-form" id="todo-edit-form" data-todo-edit-id="${esc(t.id)}">
        <label class="todo-edit-title-field"><span>标题</span><input class="search-input" id="todo-edit-title" maxlength="300" value="${esc(t.title)}"></label>
        <label><span>截止日期</span><input class="search-input" id="todo-edit-date" type="date" value="${esc(date)}"></label>
        <label><span>时间</span><input class="search-input" id="todo-edit-time" type="time" value="${esc(dueTimeOf(t.due))}"></label>
        <label><span>项目</span><select class="search-input" id="todo-edit-project"><option value="">不关联项目</option>${projects.map(p=>`<option value="${esc(p)}" ${p===t.project?'selected':''}>${esc(p)}</option>`).join('')}</select></label>
        <label><span>优先级</span><select class="search-input" id="todo-edit-priority">${['普通','紧急','高','低'].map(p=>`<option ${p===(t.priority||'普通')?'selected':''}>${p}</option>`).join('')}</select></label>
        <div class="todo-edit-actions"><button class="primary-btn" type="submit">保存</button><button class="secondary-btn" type="button" data-todo-edit-cancel>取消</button></div>
      </form></div>`;
  }
  function todoRow(t,projects){
    if(state.todoEditing===t.id) return todoEditRow(t,projects||[]);
    const overdue=!!t.overdue;
    const doneMeta=t.done&&t.completed_at?`完成于 ${fmtDue(t.completed_at)}`:'';
    return `<div class="todo-row ${t.done?'done':''} ${overdue?'is-overdue':''}" data-todo-row="${esc(t.id)}"><input class="row-select" type="checkbox" ${state.todoSelectionMode?'':'hidden'} data-todo-pick="${esc(t.id)}" data-bulk-control aria-label="选择待办：${esc(t.title)}"><button type="button" class="todo-complete" role="checkbox" aria-checked="${!!t.done}" data-todo-check="${esc(t.id)}" data-todo-overdue="${overdue?1:''}" data-todo-due="${esc(t.due)}" aria-label="${t.done?'恢复待办':'完成任务'}：${esc(t.title)}" title="${t.done?'恢复待办':'标记完成'}">${t.done?'✓':''}</button><div class="todo-copy"><div class="todo-title">${esc(t.title)}</div><div class="row-meta">${esc(t.project||'未关联项目')}${doneMeta?` · ${esc(doneMeta)}`:''}</div></div><time class="${overdue?'is-overdue':''}" title="${esc(fmtDue(t.due))}${overdue?'（已逾期）':''}">${esc(fmtDue(t.due))}</time><span class="badge" data-priority="${esc(t.priority||'普通')}">${esc(t.priority||'普通')}</span><button class="ghost-btn" data-todo-edit="${esc(t.id)}" aria-label="编辑待办：${esc(t.title)}">编辑</button><button class="ghost-btn danger" data-todo-del="${esc(t.id)}">删除</button></div>`}

  /* v261009 · 专注计时已搬出内核，成为插件 plugins/focus（自登记 ERWPanels 面板）。
     内核不再认识「专注」：删掉该插件只是少一个导航项。 */

  async function openGlobalSearch(initial=''){
    modal('全局搜索',`<div class="global-search"><div class="global-search-box"><span>⌕</span><input id="global-search-input" autocomplete="off" placeholder="搜索灵感、日志、笔记、里程碑、总结、文献、待办与 Agent 对话…" value="${esc(initial)}"></div><div class="global-search-hint">支持标题、正文、标签、项目等全文匹配 · Ctrl/⌘ + K</div><div class="global-search-results" id="global-search-results"><div class="empty">输入关键词开始检索</div></div></div>`,'');
    const input=$('#global-search-input'); const run=debounce(async()=>{const q=input.value.trim();if(!q){$('#global-search-results').innerHTML='<div class="empty">输入关键词开始检索</div>';return}try{const rows=await api('/api/search?q='+encodeURIComponent(q));$('#global-search-results').innerHTML=rows.length?rows.map(searchResultRow).join(''):'<div class="empty">没有找到相关条目</div>';$$('[data-search-result]').forEach(b=>b.onclick=()=>openSearchResult(rows[+b.dataset.searchResult]));}catch(e){$('#global-search-results').innerHTML=`<div class="empty danger">${esc(e.message)}</div>`}},180);input.oninput=run;setTimeout(()=>input.focus(),20);if(initial)run();
  }
  function searchResultRow(r,i){const label=r.source==='chat'?'Agent 对话':r.source==='todo'?'待办':kindLabel(r.kind);return `<button class="global-search-row" type="button" data-search-result="${i}"><span class="global-search-kind">${esc(label)}</span><span class="global-search-copy"><strong>${esc(r.title||'未命名')}</strong><small>${esc(r.project||'')}${r.project?' · ':''}${esc(r.excerpt||'')}</small></span><span>↗</span></button>`}
  async function openSearchResult(r){closeModal();if(!r)return;if(r.source==='chat'){state.agentSession=r.id;await navigate('agent');return}if(r.source==='todo'){await navigate('todos');return}await openDocRoute(routeForKind(r.kind),r.id)}

  async function renderAgent(){
    const sessions=await api('/api/agent/sessions');
    const llmCfg=state.config?.app?.llm||{};
    const requestPresets=Array.isArray(llmCfg.request_presets)&&llmCfg.request_presets.length?llmCfg.request_presets:[{id:'default',label:'默认（不附加参数）',params:{}},{id:'qwen-low',label:'Qwen · 低思考',params:{enable_thinking:true,thinking_budget:1024}},{id:'qwen-off',label:'Qwen · 无思考',params:{enable_thinking:false}}];
    if(!requestPresets.some(x=>String(x.id||'')===state.agentPreset)) state.agentPreset=String(llmCfg.default_request_preset||requestPresets[0].id||'default');
    const requestPresetHtml=requestPresets.map(x=>`<option value="${esc(x.id||'default')}" ${String(x.id||'')===state.agentPreset?'selected':''}>${esc(x.label||x.id||'默认')}</option>`).join('');
    if(state.agentSession&&!sessions.some(x=>x.id===state.agentSession))state.agentSession=null;
    if(!state.agentSession&&sessions.length)state.agentSession=sessions[0].id;
    $('#main').innerHTML=`<div class="agent-layout"><aside class="card agent-sessions"><div class="agent-side-head"><div><h3>Agent 对话</h3></div><button class="primary-btn" id="agent-new">＋</button></div><div class="agent-session-list">${sessions.length?sessions.map(x=>`<button type="button" class="agent-session ${x.id===state.agentSession?'active':''}" data-agent-session="${x.id}"><strong>${esc(x.title)}</strong><small>${esc(fmtTime(x.updated))} · ${x.message_count||0} 条</small></button>`).join(''):'<div class="empty compact">暂无对话</div>'}</div></aside><section class="card agent-chat" id="agent-workspace"><div class="agent-workspace-tabs" id="agent-workspace-tabs"></div><div id="agent-chat-panel"><div class="agent-chat-head"><div><h3 id="agent-chat-title">科研 Agent</h3></div><div class="agent-head-actions"><button class="secondary-btn" id="agent-ref">＋ 引用研究 · 知识</button><button class="ghost-btn danger" id="agent-delete" ${state.agentSession?'':'disabled'}>删除对话</button></div></div><div class="agent-messages" id="agent-messages"><div class="empty">${state.agentSession?'正在载入对话…':'新建一个对话开始'}</div></div><div class="agent-context-strip" id="agent-context-strip"></div><div class="agent-composer"><div class="agent-image-strip" id="agent-image-strip"></div><textarea id="agent-input" placeholder="向科研 Agent 提问。可粘贴/拖入图片，或手动引用研究 · 知识中的 Markdown…"></textarea><div class="agent-compose-actions"><div class="agent-compose-left"><button class="ghost-btn" id="agent-image">▧ 图片</button><label class="agent-preset-label">请求模式 <select class="search-input agent-preset-select" id="agent-preset">${requestPresetHtml}</select></label><span class="row-meta">Enter 发送 · Shift+Enter 换行</span></div><button class="primary-btn" id="agent-send">发送</button></div></div></div><div id="agent-system-panel" hidden><div class="as-content"></div></div></section></div>`;
    $('#agent-new').onclick=async()=>{const s=await api('/api/agent/sessions',{method:'POST',body:{}});state.agentSession=s.id;state.agentRefs=[];state.agentImages=[];renderAgent()};
    $$('[data-agent-session]').forEach(b=>b.onclick=()=>{state.agentSession=b.dataset.agentSession;state.agentRefs=[];state.agentImages=[];renderAgent()});
    $('#agent-ref').onclick=openAgentReferencePicker;$('#agent-image').onclick=pickAgentImage;$('#agent-delete').onclick=async()=>{if(state.agentSession&&await window.ERWDialog.confirm('将该对话移入 Trash？')){await api('/api/agent/sessions/'+encodeURIComponent(state.agentSession),{method:'DELETE'});state.agentSession=null;renderAgent()}};
    const input=$('#agent-input');input.addEventListener('paste',onAgentPasteImage);input.addEventListener('dragover',e=>e.preventDefault());input.addEventListener('drop',onAgentDropImage);input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendAgentMessage()}});$('#agent-send').onclick=sendAgentMessage;const presetSelect=$('#agent-preset');if(presetSelect)presetSelect.onchange=()=>{state.agentPreset=presetSelect.value;localStorage.setItem('agentRequestPreset',state.agentPreset)};
    paintAgentContext(); paintAgentImages(); if(state.agentSession)await loadAgentSession(state.agentSession);
    /* v261022.6 · 任务/记忆/技能/RAG/设置面板：由 agent-system.js 渲染进 #agent-system-panel */
    window.ERWAgentSystem?.mount?.();
  }
  async function loadAgentSession(id){try{const s=await api('/api/agent/sessions/'+encodeURIComponent(id));if(state.route!=='agent'||state.agentSession!==id)return;$('#agent-chat-title').textContent=s.title||'科研 Agent';const root=$('#agent-messages');root.innerHTML=(s.messages||[]).length?(s.messages||[]).map(agentMessageHtml).join(''):'<div class="empty">暂无消息。你可以直接提问，或先引用研究资料。</div>';for(const el of $$('.agent-message-body',root))await renderMarkdownInto(el,el.dataset.raw||'');for(const el of $$('.agent-reasoning-body',root))await renderMarkdownInto(el,el.dataset.raw||'');root.scrollTop=root.scrollHeight}catch(e){toast(e.message,true)}}
  function agentMessageHtml(m){const refs=(m.refs||[]).map(r=>`<span class="badge">${esc(r.title)}</span>`).join('');const imgs=(m.images||[]).map(p=>`<img src="/workspace-file/${esc(typeof p==='string'?p:(p.path||''))}" alt="对话图片">`).join('');const showReasoning=state.config?.app?.llm?.show_reasoning!==false;const reasoning=showReasoning&&String(m.reasoning||'').trim()?`<details class="agent-reasoning"><summary>模型思考过程</summary><div class="agent-reasoning-body" data-raw="${esc(m.reasoning||'')}"></div></details>`:'';const tlHtml=(m.role==='assistant'&&window.ERWFabTimeline?.html)?window.ERWFabTimeline.html(m):''; /* v261008b · 复用悬浮球的时间条（工具耗时 + 总耗时 + 过程明细） */const metaParts=(window.ERWFabTimeline?.metaParts?window.ERWFabTimeline.metaParts(m):[String(m.model||'').trim(),String(m.request_preset_label||'').trim()].filter(Boolean)); /* v261008b · 元信息去重：标签已含模型名时不再重复显示 model */return `<article class="agent-message ${m.role==='assistant'?'assistant':'user'}"><div class="agent-avatar">${m.role==='assistant'?'AI':'YOU'}</div><div class="agent-bubble">${refs?`<div class="agent-msg-refs">${refs}</div>`:''}${imgs?`<div class="agent-msg-images">${imgs}</div>`:''}${reasoning}<div class="agent-message-body" data-raw="${esc(m.content||'')}"></div>${tlHtml}<div class="agent-msg-meta">${[...metaParts.map(esc),esc(fmtTime(m.created))].join(' · ')}</div></div></article>`}
  async function renderMarkdownInto(out,raw){const seq=++state.previewSeq;out._markdownSeq=seq;let html='';if(window.marked&&window.DOMPurify){const renderer=new marked.Renderer();renderer.code=(tokenOrCode,info)=>{let code='',lang='';if(tokenOrCode&&typeof tokenOrCode==='object'){code=tokenOrCode.text||'';lang=tokenOrCode.lang||''}else{code=String(tokenOrCode||'');lang=String(info||'')}lang=lang.trim();if(lang==='mermaid')return `<div class="mermaid">${esc(code)}</div>`;return `<pre><code class="language-${esc(lang)}">${esc(code)}</code></pre>`};try{html=marked.parse(raw||'',{gfm:true,renderer})}catch{html=basicMarkdown(raw)}}else html=basicMarkdown(raw);html=normalizePreviewPaths(html);out.innerHTML=window.DOMPurify?DOMPurify.sanitize(html,{ADD_TAGS:['mjx-container']}):html;out.innerHTML=out.innerHTML.replace(/<table[\s\S]*?<\/table>/gi,m=>`<div class="fab-tbl">${m}</div>`); /* v261008b · 宽表格套气泡内滚动层，避免撑破容器 */$$('pre code',out).forEach(el=>{try{window.hljs?.highlightElement(el)}catch{}});await renderMermaidBlocks(out,seq);if(window.ERWRenderLibraries?.renderMath){try{await window.ERWRenderLibraries.renderMath([out])}catch(e){console.warn(e)}}else{if(window.erwVendor?.hasMath(raw)&&!window.MathJax){try{await window.erwVendor.load('mathjax')}catch{}}if(window.MathJax?.typesetPromise){try{await MathJax.typesetPromise([out])}catch{}}}}
  function paintAgentContext(){const root=$('#agent-context-strip');if(!root)return;root.innerHTML=state.agentRefs.length?`<span class="row-meta">已引用</span>${state.agentRefs.map((r,i)=>`<button type="button" class="context-chip" data-ref-remove="${i}">${esc(r.title)}</button>`).join('')}`:'<span class="row-meta">未引用本地知识；点击“引用研究 · 知识”可手动选择上下文。</span>';$$('[data-ref-remove]',root).forEach(b=>b.onclick=()=>{state.agentRefs.splice(+b.dataset.refRemove,1);paintAgentContext()})}
  function paintAgentImages(){const root=$('#agent-image-strip');if(!root)return;root.innerHTML=state.agentImages.map((x,i)=>`<div class="agent-image-thumb"><img src="${esc(x.url)}"><button type="button" data-agent-image-remove="${i}">×</button></div>`).join('');$$('[data-agent-image-remove]',root).forEach(b=>b.onclick=()=>{state.agentImages.splice(+b.dataset.agentImageRemove,1);paintAgentImages()})}
  async function openAgentReferencePicker(){modal('引用研究 · 知识',`<div class="global-search"><div class="global-search-box"><span>⌕</span><input id="agent-ref-search" placeholder="搜索要引用的 Markdown 条目…"></div><div class="row-meta" style="margin:8px 0">只会把你最终勾选的条目发送给模型。</div><div class="agent-ref-results" id="agent-ref-results"><div class="empty">输入关键词检索研究资料</div></div></div>`,`<button class="secondary-btn" id="agent-ref-cancel">取消</button><button class="primary-btn" id="agent-ref-done">引用所选</button>`);let rows=[];const selected=new Map(state.agentRefs.map(x=>[x.id,x]));const run=debounce(async()=>{const q=$('#agent-ref-search').value.trim();if(!q){$('#agent-ref-results').innerHTML='<div class="empty">输入关键词检索研究资料</div>';return}rows=(await api('/api/docs?q='+encodeURIComponent(q))).slice(0,50);$('#agent-ref-results').innerHTML=rows.length?rows.map(x=>`<label class="bundle-item"><input type="checkbox" data-ref-id="${x.id}" ${selected.has(x.id)?'checked':''}><span class="badge">${esc(KIND_LABEL[x.kind]||x.kind)}</span><span><strong>${esc(x.title)}</strong><br><span class="row-meta">${esc(x.project||'未归属项目')} · ${esc(x.excerpt||'')}</span></span></label>`).join(''):'<div class="empty">未找到条目</div>';$$('[data-ref-id]').forEach(c=>c.onchange=()=>{const d=rows.find(x=>x.id===c.dataset.refId);if(c.checked&&d)selected.set(d.id,{id:d.id,title:d.title,kind:d.kind,project:d.project||''});else selected.delete(c.dataset.refId)})},180);$('#agent-ref-search').oninput=run;$('#agent-ref-cancel').onclick=closeModal;$('#agent-ref-done').onclick=()=>{state.agentRefs=[...selected.values()];closeModal();paintAgentContext()};setTimeout(()=>$('#agent-ref-search').focus(),20)}
  function pickAgentImage(){const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif';input.multiple=true;input.onchange=()=>[...input.files].slice(0,6).forEach(uploadAgentFile);input.click()}
  async function uploadAgentFile(file){if(!file?.type?.startsWith('image/'))return;const data=await readAsDataUrl(file);try{const r=await api('/api/agent/assets',{method:'POST',body:{data_url:data,name:file.name}});state.agentImages.push(r);paintAgentImages()}catch(e){toast(e.message,true)}}
  function onAgentPasteImage(e){const files=[...e.clipboardData.items].filter(i=>i.kind==='file').map(i=>i.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();files.slice(0,6).forEach(uploadAgentFile)}}
  function onAgentDropImage(e){e.preventDefault();[...e.dataTransfer.files].filter(f=>f.type.startsWith('image/')).slice(0,6).forEach(uploadAgentFile)}
  /* v261008 · /api/agent/send 自 v260930k 起是 SSE（event: round|delta|tool|done|error），
     而 app.js 的 Agent 页仍是旧 JSON 契约（`r.session.id`），对着流式响应必然抛
     「Cannot read properties of undefined (reading 'id')」——这里补上流式消费。
     done 负载自 v260930m 起只回 assistant，会话对象由调用方回读补齐。 */
  async function streamAgentSend(payload, onDelta, onStatus){
    const res=await fetch('/api/agent/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!res.ok||!res.body){let d={};try{d=await res.json()}catch{};throw new Error(d.message||d.error||`HTTP ${res.status}`)}
    const reader=res.body.getReader(),dec=new TextDecoder('utf-8');
    let buf='',ev='',doneData=null,text='';
    for(;;){
      const {value,done}=await reader.read();
      if(done)break;
      buf+=dec.decode(value,{stream:true});
      let i;
      while((i=buf.indexOf('\n\n'))>=0){
        const frame=buf.slice(0,i);buf=buf.slice(i+2);
        let dataStr='';
        for(const line of frame.split('\n')){
          if(line.startsWith('event:'))ev=line.slice(6).trim();
          else if(line.startsWith('data:'))dataStr+=line.slice(5).trim();
        }
        let data={};try{data=JSON.parse(dataStr||'{}')}catch{data={}}
        if(ev==='delta'){text+=data.text||'';if(onDelta)onDelta(text)}
        else if(ev==='round'){text='';if(onStatus)onStatus(`第 ${(data.i|0)+1} 轮 · 模型思考中…`)}
        else if(ev==='tool'){if(onStatus)onStatus(`工具 ${data.name||''} ${data.ok?'已完成':'失败'}`)}
        else if(ev==='done'){doneData=data}
        else if(ev==='error'){throw new Error(data.message||'请求失败')}
      }
    }
    if(!doneData)throw new Error('流式响应中断（未收到 done 事件）');
    return doneData.assistant;
  }

  async function sendAgentMessage(){
    const input=$('#agent-input'),text=input.value.trim();if(state.agentSending||(!text&&!state.agentImages.length))return;
    const btn=$('#agent-send');state.agentSending=true;btn.disabled=true;btn.textContent='思考中…';
    const refs=state.agentRefs.map(x=>({...x})),images=state.agentImages.map(x=>({...x})),preset=state.agentPreset||'';
    try{
      if(!state.agentSession){const s=await api('/api/agent/sessions',{method:'POST',body:{}});state.agentSession=s.id}
      input.value='';state.agentRefs=[];state.agentImages=[];paintAgentContext();paintAgentImages();
      const root=$('#agent-messages');
      if(root){$('.empty',root)?.remove();root.insertAdjacentHTML('beforeend',agentMessageHtml({role:'user',content:text,created:new Date().toISOString(),refs,images:images.map(x=>x.path),request_preset_label:($('#agent-preset')?.selectedOptions?.[0]?.textContent||'')}));for(const el of $$('.agent-message-body',root).slice(-1))await renderMarkdownInto(el,el.dataset.raw||'');const showReasoning=state.config?.app?.llm?.show_reasoning!==false;root.insertAdjacentHTML('beforeend',`<article class="agent-message assistant agent-thinking" id="agent-thinking"><div class="agent-avatar">AI</div><div class="agent-bubble"><div class="agent-thinking-line"><span class="thinking-dots"><i></i><i></i><i></i></span><strong>${showReasoning?'模型正在思考':'模型正在生成回复'}</strong><span class="row-meta" id="agent-thinking-time">0.0 s</span></div>${showReasoning?'<div class="agent-thinking-hint">若接口返回 reasoning / reasoning_content，将在最终回复中以可折叠区域显示。</div>':''}</div></article>`);root.scrollTop=root.scrollHeight}
      const started=performance.now();const timer=setInterval(()=>{const el=$('#agent-thinking-time');if(el)el.textContent=((performance.now()-started)/1000).toFixed(1)+' s'},100);
      try{ /* v261008 · 走 SSE 流式（原 `api(...)` 读 JSON 的写法对流式响应会返回 {}，随后 r.session.id 抛错） */
        const r0=await streamAgentSend({session_id:state.agentSession,message:text,refs:refs.map(x=>x.id),images:images.map(x=>x.path),request_preset:preset},
          (streamText)=>{const el=$('#agent-thinking');if(el){const b=el.querySelector('.agent-bubble');if(b)b.innerHTML=`<div class="agent-bubble-body" style="white-space:pre-wrap">${esc(streamText)}</div>`}},
          (note)=>{const el=$('#agent-thinking');if(el){const b=el.querySelector('.agent-bubble');if(b)b.innerHTML=`<div class="agent-thinking-line"><span class="thinking-dots"><i></i><i></i><i></i></span><strong>${esc(note)}</strong></div>`}});
        clearInterval(timer);
        const r={assistant:r0,session:await api('/api/agent/sessions/'+encodeURIComponent(state.agentSession))};
        /* v260929c · 提速：就地替换思考气泡为新回复并轻量更新侧栏条目，不再整页重渲染（省去重拉全部会话与全部消息重排版） */
        const think=$('#agent-thinking'),mroot=$('#agent-messages');
        if(think)think.outerHTML=agentMessageHtml(r.assistant);else if(mroot)mroot.insertAdjacentHTML('beforeend',agentMessageHtml(r.assistant));
        if(mroot&&state.route==='agent'){
          const bs=$$('.agent-message-body',mroot),lb=bs[bs.length-1];if(lb)await renderMarkdownInto(lb,lb.dataset.raw||'');
          const rbs=$$('.agent-reasoning-body',mroot),lrb=rbs[rbs.length-1];if(lrb)await renderMarkdownInto(lrb,lrb.dataset.raw||'');
          mroot.scrollTop=mroot.scrollHeight;
          const sb=qa('[data-agent-session]').find(b=>b.dataset.agentSession===r.session.id);
          if(sb){const st=sb.querySelector('strong'),sm=sb.querySelector('small');if(st)st.textContent=r.session.title||'Agent 对话';if(sm)sm.textContent=fmtTime(r.session.updated)+' · '+(r.session.messages?.length||0)+' 条'}
        }
      }catch(e){clearInterval(timer);$('#agent-thinking')?.remove();if(root){root.insertAdjacentHTML('beforeend',`<article class="agent-message assistant"><div class="agent-avatar">AI</div><div class="agent-bubble"><div class="agent-error">请求失败：${esc(e.message)}</div></div></article>`);root.scrollTop=root.scrollHeight}toast(e.message,true)}
    }finally{state.agentSending=false;const b=$('#agent-send');if(b){b.disabled=false;b.textContent='发送'}}
  }

  /* v261009 · 资讯（RSS）已搬出内核，成为插件 plugins/rss（自登记 ERWPanels 面板，
     后端走 /api/plugins/rss/*，配置落在 config/plugins/rss.json）。内核不再认识「资讯」。 */

  async function renderDocsPage(kind){
    if(!await guardEditor('重新载入文档列表'))return;
    /* v260929 · 文献页保留原有列表/编辑器（BibTeX 同步、自动 cite_key、元数据表单均在此），
       PDF 阅读工作区不整体接管，改由列表页头部按钮进入（openLiteratureWorkspace），两套 UI 共存 */
    const [docs,projects] = await Promise.all([api('/api/docs?kind='+encodeURIComponent(kind)), api('/api/projects')]); state.docs=docs; state.projects=projects; state.selectedDoc=null;state.draft=null;state.editorBaseline=null;state.dirty=false;
    /* v261008.2 · 标签筛选下拉的候选项：累积本会话已见到的全部标签 */
    state.tagOptions=[...new Set([...(state.tagOptions||[]), ...docs.flatMap(d=>d.tags||[])])].sort((a,b)=>a.localeCompare(b,'zh'));
    if(kind==='milestone') return renderMilestoneShell(docs,projects);
    $('#main').innerHTML=docsShell(kind,docs,projects);
    wireDocList(kind); wireDocFilters(kind); $('#new-doc').onclick=()=>createAndSelect(kind);
    if(kind==='literature'){$('#export-bib').onclick=exportBibtex;const ws=$('#open-lit-workspace');if(ws)ws.onclick=openLiteratureWorkspace;}
    if(docs.length) selectDoc(docs[0].id); else showEmptyEditor(kind);
  }
  /* v260929 · 文献列表页 → PDF 阅读工作区入口：编辑中先提示保存；进入后清选中态，
     工作区头部自带返回按钮（literature.js shell），返回时重新渲染文献列表。
     v261009.13 · 改走 ERWReader 接缝：没有阅读区接管者时给明确提示（而不是静默无反应）。 */
  async function openLiteratureWorkspace(){
    if(!await guardEditor('打开 PDF 工作区'))return;
    state.selectedDoc=null;state.draft=null;state.editorBaseline=null;state.dirty=false;
    try{ await window.ERWReader.open(); }
    catch(err){ toast(err&&err.message?err.message:String(err), true); }
  }
  /* v260929 · 附件入口统一：徽章点击一律跳 PDF 阅读区（原新窗口直开功能并入工作区）；
     未登记的附件先自动单条登记（迁移入 Knowledge/Literature/PDF/）再重试，仍失败才提示 */
  async function openAttachmentInWorkspace(d){
    if(!window.ERWReader.available())throw new Error(READER_MISSING);
    if(!await guardEditor('打开文献附件'))return;
    state.selectedDoc=null;state.draft=null;state.editorBaseline=null;state.dirty=false;
    if(!d||!d.attachment)throw new Error('该条目未配置 PDF 附件');
    try{await window.ERWReader.openByAttachment(d.attachment);return}
    catch(e){
      const r=await api('/api/literature/rebuild',{method:'POST',body:{doc_id:d.id}});
      const att=r.attachment||d.attachment;
      if(!att)throw new Error('附件文件不存在或无法登记到 PDF 工作区');
      try{await window.ERWReader.openByAttachment(att);return}
      catch(e2){throw new Error('附件文件不存在或无法登记到 PDF 工作区')}
    }
  }
  /* v260929 · 重建关联（真值归一）：以文献 md 条目为准补齐 PDF 工作区登记——
     未登记的附件 PDF 迁入 PDF 存放目录（设置 · 文献 / PDF 可配置）统一存放并建立双向关联；幂等可重复执行 */
  async function rebuildLiteratureLinks(){
    if(!await window.ERWDialog.confirm('将以文献条目为准重建 PDF 工作区关联：未登记的附件 PDF 会迁入 PDF 存放目录（默认 Workspace/Knowledge/Literature/PDF，可在设置 · 文献 / PDF 中修改）统一存放（Workspace 内为移动，外部路径保留原件复制）并建立关联。继续？'))return;
    const r=await api('/api/literature/rebuild',{method:'POST',body:{}});
    toast(`重建完成：补关联 ${r.linked||0} 篇，新登记 ${r.registered||0} 篇，补建条目 ${r.ensured||0} 篇`);
    if(state.route==='settings')renderSettings();else renderDocsPage('literature');
  }
  function docsShell(kind,docs,projects){return `<div class="docs-layout"><aside class="card doc-list-panel"><div class="doc-filter"><div style="display:flex;gap:6px"><input class="search-input" id="doc-search" placeholder="搜索标题、正文、标签、项目、分类…"><button class="secondary-btn" id="new-doc" title="新建条目" aria-label="新建条目">＋</button>${batchModeButton('doc')}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><select class="search-input" id="doc-status"><option value="">全部状态</option>${(state.statuses[kind]||[]).map(s=>`<option>${esc(s)}</option>`).join('')}</select><select class="search-input" id="doc-project"><option value="">全部项目</option><option value="__unowned__">未归属项目（通用基础）</option>${projects.map(p=>`<option>${esc(p)}</option>`).join('')}</select><select class="search-input" id="doc-mark" style="grid-column:span 2"><option value="">全部分类</option>${allMarks().map(k=>`<option value="${esc(k.id)}">${esc(k.icon)} ${esc(k.label)}</option>`).join('')}</select><div style="grid-column:span 2;display:flex;gap:6px;align-items:center"><input class="search-input" id="doc-tag" list="doc-tag-list" placeholder="按标签精确筛选（可输入）"><label class="row-meta" style="display:flex;gap:4px;align-items:center;white-space:nowrap"><input type="checkbox" id="doc-unowned">仅未归属</label></div><datalist id="doc-tag-list">${(state.tagOptions||[]).map(t=>`<option value="${esc(t)}"></option>`).join('')}</datalist></div>${kind==='literature'?`<div style="display:flex;gap:6px;flex-wrap:wrap"><button class="secondary-btn" id="export-bib">批量导出 BibTeX</button>${window.ERWReader.available()?'<button class="secondary-btn" id="open-lit-workspace">PDF 阅读工作区</button>':''}</div>`:''}</div>${selectionToolbar('doc')}<div class="doc-list" id="doc-list">${docItems(docs)}</div></aside><section class="card doc-editor empty-editor" id="doc-editor"></section></div>`}
  function markBadges(d){return (d.kind_marks||[]).slice(0,4).map(id=>{const c=allMarks().find(k=>k.id===id);if(!c)return '';const col=esc(c.color);return `<span class="badge mark-badge" style="--mark-color:${col};color:${col};border-color:${col};background:${col}1a">${esc(c.icon)} ${esc(c.label)}</span>`}).join('')}
  /* v260929 · 暴露给 PDF 阅读工作区复用同一套标记徽章渲染，避免标记目录二次维护 */
  window.ERWMarkBadges = markBadges;
  /* v260929 · 分类标记 chips 暴露给 PDF 阅读工作区复用（html 渲染 + 自定义标记管理）；onChanged 供调用方重渲染自己的 chips 盒 */
  window.ERWMarkChips = {html:markChipsHtml, openManager:openMarkManager, create:after=>openMarkCreator(after)};
  window.ERWMarkList = allMarks; /* v260929 · 标记目录（含自定义）供阅读区筛选项等复用 */
  /* v260929b · 阅读区 AI 助手自定义动作目录（设置 → 文献/PDF 维护），供 AI 面板渲染个性化按钮 */
  window.ERWAssistCustomActions = () => { const a = state.config?.app?.llm?.assist; return Array.isArray(a?.custom_actions) ? a.custom_actions : []; };
  /* v260929c · 多模态开关（设置 → Agent/LLM 维护），阅读区 AI 面板据此显示截图入口 */
  window.ERWVisionEnabled = () => state.config?.app?.llm?.vision_enabled === true;
  /* v260929d · 配置热同步：Agent API 配置页（独立脚本）保存后回写 state.config.app，免刷新生效 */
  window.ERWConfigSync = app => { if (state.config && app) state.config.app = app; };
  /* v260930 · M2 悬浮球助手：LLM 是否已启用（未启用时悬浮球发送前给出设置指引） */
  window.ERWLLMReady = () => state.config?.app?.llm?.enabled === true;
  /* v260930d · M5 阅读中知识关联：悬浮球/气泡跳转到指定知识条目（导航+选中跨脚本桥） */
  /* v260930g9c · 关联知识「打开条目」跳转：六类→对应路由并选中；literature 额外自动进 PDF 阅读工作区（引用跳文献即看原文） */
  window.ERWNav = { open: async (kind, id) => {
    const ok=await openDocRoute(routeForKind(kind),id);
    if(ok===false)return; /* 用户在未保存确认框点了取消：中止，不在旧页面执行 selectDoc */
    if(kind==='literature'){ setTimeout(async()=>{
      const doc=(state.docs||[]).find(x=>x.id===id);
      if(!doc)return; /* 列表未含该条目（分页/过滤）则停在选中态 */
      try{state.selectedDoc=doc;await openAttachmentInWorkspace(doc)}catch(e){toast(e.message,true)}
    },80); }
  } };
  /* v260923 · 分类标记 chips 渲染 / 事件 / 重渲染（含「＋ 自定义」入口） */
  function markChipsHtml(selected){return allMarks().map(k=>`<button type="button" class="mark-chip${(selected||[]).includes(k.id)?' on':''}" data-mark="${esc(k.id)}" style="--mark-color:${esc(k.color)}" title="点击标记为${esc(k.label)}，可多选">${esc(k.icon)} ${esc(k.label)}</button>`).join('')+`<button type="button" class="mark-chip add-mark" data-mark-add title="新建自定义分类标记（图标与名称可在设置里继续修改）">＋ 自定义</button>`}
  function wireMarkChips(){
    $$('#f-marks .mark-chip:not(.add-mark)').forEach(b=>b.onclick=()=>{b.classList.toggle('on');state.dirty=true});
    const add=$('#f-marks .mark-chip.add-mark');
    if(add)add.onclick=()=>openMarkCreator(mark=>{
      /* v261020 · 从条目编辑器直接建分类：建完立刻选中，并保留其它已选中的标记 */
      refreshMarkChips();
      const chip=$(`#f-marks .mark-chip[data-mark="${mark.id}"]`);
      if(chip){chip.classList.add('on');state.dirty=true}
    });
  }
  function refreshMarkChips(){
    const box=$('#f-marks'); if(!box)return;
    const on=$$('#f-marks .mark-chip.on').map(b=>b.dataset.mark);
    const saved=(state.selectedDoc&&state.selectedDoc.kind_marks)||[];
    box.innerHTML=markChipsHtml([...new Set([...on,...saved])]);
    wireMarkChips();
  }
  function openMarkManager(){
    navigate('settings').then(ok=>{
      if(ok===false)return;
      const tab=$('[data-set-tab="knowledge"]');
      if(tab){$$('[data-set-tab]').forEach(x=>x.classList.toggle('active',x===tab));renderSettingsTab('knowledge',state.config)}
    });
  }
  /* v260923 · 笔记卡片格式统一：状态/分类一行；时间与项目名同排，项目名过长固定宽度省略 */
  /* v260924i · 置顶条目卡片显示置顶徽章并加 pinned 类 */
  /* v261014 · 紧凑卡片（v3 视觉）：类型色条 + 单行元信息 + 右上角标；标题走 title 悬停提示，附件角标 data-att 供点击进 PDF 阅读区 */
  function docItems(docs){return docs.length?docs.map(d=>{
    const projects=(d.projects||[]).length?(d.projects||[]):(d.project?[d.project]:[]);
    const project=projects[0]||'未关联项目';
    const val=d.due||d.record_date||d.added_date||d.updated;
    const meta=`<span class="doc-project" title="${esc(project)}">${esc(project)}</span>${markBadges(d)}${d.status?`<span class="doc-status">${esc(d.status)}</span>`:''}${val?`<time>${esc(fmtDate(val))}</time>`:''}`;
    const attB=d.attachment_exists?'<span class="doc-mini-flag" data-att="1" title="在 PDF 阅读区打开附件">⧉</span>':'';
    const pinB=d.pinned?'<span class="doc-mini-flag" title="已置顶">📌</span>':'';
    return `<article class="doc-item${d.pinned?' pinned':''}" data-doc-id="${d.id}" data-doc-kind="${esc(d.kind||'')}" ${d.draft?'data-doc-draft="true"':''}><input type="checkbox" class="row-select doc-select" ${state.docSelectionMode&&!d.draft?'':'hidden'} ${d.draft?'disabled':''} data-doc-pick="${esc(d.id)}" data-bulk-control aria-label="选择文档：${esc(d.title)}"><div class="doc-type-rail" aria-hidden="true"></div><div class="doc-compact-main"><div class="title" title="${esc(d.title)}">${esc(d.title)}</div><div class="doc-compact-meta">${meta}</div><div class="excerpt" title="${esc(d.excerpt||'')}">${esc(d.draft?'新建草稿 · 尚未保存':d.excerpt||'')}</div></div><div class="doc-mini-flags">${attB}${pinB}</div></article>`
  }).join(''):'<div class="empty" style="min-height:140px">暂无内容</div>'}
  function dateBadge(d){ const val=d.due||d.record_date||d.added_date; if(val)return `<span class="badge mono">${fmtDate(val)}</span>`; return d.updated?`<span class="badge mono" title="更新时间">更新 ${fmtDate(d.updated)}</span>`:''; }
  function wireDocList(kind){
    $$('[data-doc-id]').forEach(x=>x.onclick=e=>{
      if(e.target.closest('[data-doc-pick]')||state.bulkBusy)return;
      /* v260929 · 附件入口统一：角标点击一律跳 PDF 阅读区（自动登记未入库附件），不再新窗口直开；v261014 角标改由 data-att 标记 */
      const att=e.target.closest('[data-att]');
      if(att){const d=state.docs.find(v=>v.id===x.dataset.docId);openAttachmentInWorkspace(d).catch(err=>toast(err.message||'附件打开失败',true));return}
      selectDoc(x.dataset.docId);
    });
    wireSelection('doc',state.docs,()=>deleteSelectedDocs(kind));
  }

  async function deleteSelectedDocs(kind){
    const ids=[...state.docSelection];if(!ids.length)return;
    const current=state.selectedDoc?.id;
    if(!await window.ERWDialog.confirm(`确认删除所选 ${ids.length} 条文档？文件会移入回收目录。${state.dirty?'当前文档有未保存修改，继续将丢弃这些修改。':''}`))return;
    const result=await deleteSelection('docs',ids);if(!result)return;
    state.docSelection=new Set(result.failed.map(x=>x.id));state.docSelectionMode=state.docSelection.size>0;state.dirty=false;state.editorBaseline=null;state.selectedDoc=null;state.draft=null;
    const projectRaw=$('#doc-project')?.value||'';
    const params=new URLSearchParams({kind,q:$('#doc-search')?.value||'',status:$('#doc-status')?.value||'',project:projectRaw==='__unowned__'?'':projectRaw,mark:$('#doc-mark')?.value||'',tag:$('#doc-tag')?.value.trim()||'',unowned:(projectRaw==='__unowned__'||$('#doc-unowned')?.checked)?'1':'0'});
    try{
      state.docs=await api('/api/docs?'+params);
      const perf=window.__workbenchPerf;
      if(perf?.docs?.page>perf.docs.pages){perf.docPage=perf.docs.pages;state.docs=await api('/api/docs?'+params)}
      $('#doc-list').innerHTML=docItems(state.docs);wireDocList(kind);
      if(current&&!result.deleted.includes(current))await selectDoc(current);
      else{++state.docSelectSeq;state.selectedDoc=null;window.ERWCurrentDoc='';showEmptyEditor(kind)}
    }catch(e){toast(e.message,true)}
  }

  function wireDocFilters(kind){ const run=debounce(async()=>{const q=$('#doc-search').value,status=$('#doc-status').value;const projectRaw=$('#doc-project').value;const project=projectRaw==='__unowned__'?'':projectRaw;const unowned=projectRaw==='__unowned__'||($('#doc-unowned')?.checked||false);const mark=$('#doc-mark')?.value||'';const tag=$('#doc-tag')?.value.trim()||'';const url=`/api/docs?kind=${kind}&q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}&project=${encodeURIComponent(project)}&mark=${encodeURIComponent(mark)}&tag=${encodeURIComponent(tag)}&unowned=${unowned?'1':'0'}`;state.docs=await api(url);$('#doc-list').innerHTML=docItems(state.docs);wireDocList(kind);},180); $('#doc-search').oninput=run;$('#doc-status').onchange=run;$('#doc-project').onchange=run;if($('#doc-mark'))$('#doc-mark').onchange=run;if($('#doc-tag'))$('#doc-tag').oninput=run;if($('#doc-unowned'))$('#doc-unowned').onchange=run; }
  async function createAndSelect(kind){
    if(!await guardEditor('新建另一篇文档'))return;
    const seq=++state.docSelectSeq;
    try{
      const doc=await api('/api/docs/draft?kind='+encodeURIComponent(kind));
      if(seq!==state.docSelectSeq)return;
      if(kind==='milestone'){state.milestoneView='docs';renderMilestoneView()}
      state.draft=doc;state.selectedDoc=doc;window.ERWCurrentDoc='';
      const list=$('#doc-list');if(list){list.innerHTML=docItems([doc,...state.docs]);wireDocList(kind);$('[data-doc-id="'+doc.id+'"]',list)?.classList.add('active')}
      renderDocEditor(doc);
    }catch(error){toast('新建文档失败：'+error.message,true)}
  }
  function showEmptyEditor(kind){ $('#doc-editor').className='card doc-editor empty-editor'; $('#doc-editor').innerHTML=`<div class="empty"><div><div class="empty-symbol">${esc(kindLabel(kind).toUpperCase())}</div>选择一条${kindLabel(kind)}，或点击左侧 ＋ 新建</div></div>`; }
  async function selectDoc(id){
    if(state.selectedDoc?.id===id)return true;
    if(!await guardEditor('切换文档'))return false;
    const seq=++state.docSelectSeq;
    const doc=await api('/api/docs/'+encodeURIComponent(id));
    if(seq!==state.docSelectSeq)return; /* later selection wins; prevents milestone jump race */
    state.draft=null;state.selectedDoc=doc;state.dirty=false;
    $$('#doc-list [data-doc-draft]').forEach(x=>x.remove());
    window.ERWCurrentDoc=doc.id;
    const list=$('#doc-list');
    const rows=$$('[data-doc-id]',list||document);
    rows.forEach(x=>x.classList.toggle('active',String(x.dataset.docId)===String(id)));
    const active=rows.find(x=>String(x.dataset.docId)===String(id));
    if(active){
      requestAnimationFrame(()=>active.scrollIntoView({block:'nearest',inline:'nearest',behavior:'smooth'}));
    }
    renderDocEditor(doc);
  }
  /* v260929 · 条目信息（填写一次即固定）可收起：收起后只留一行摘要，腾出正文撰写/阅读空间；收起状态按条目类型分别记忆 */
  function metaCollapsed(kind){try{return localStorage.getItem('erwMetaCollapsed:'+kind)==='1'}catch{return false}}
  function metaSummary(doc){
    const parts=String(doc.authors||'').split(/[;,，；]/).map(x=>x.trim()).filter(Boolean);
    const authors=parts.length?parts.length>1?parts[0]+' 等':parts[0]:'';
    return [doc.title,authors,doc.year?String(doc.year):'',doc.venue||''].filter(Boolean).join(' · ');
  }
  function renderDocEditor(doc){
    const kind=doc.kind, special=kind==='literature';
    const dateField=kind==='milestone'?'due':(kind==='summary'||kind==='journal'?'record_date':kind==='literature'?'added_date':'');
    $('#doc-editor').className='card doc-editor';
    const tagsSpan=special||kind==='summary'?'span-4':(dateField?'span-2':'span-3');
    const metaFold=metaCollapsed(kind);
    $('#doc-editor').innerHTML=`<div class="doc-editor-content"><div class="meta-block${metaFold?' collapsed':''}" id="meta-block">
      <div class="meta-head"><span class="meta-head-title">条目信息</span><span class="meta-summary">${esc(metaSummary(doc))}</span><button type="button" class="ghost-btn meta-toggle" id="meta-toggle" aria-expanded="${!metaFold}" aria-controls="meta-fields">${metaFold?'展开':'收起'}</button></div>
      <div class="form-grid" id="meta-fields">
      <div class="field span-2"><label>标题</label><input id="f-title" value="${esc(doc.title)}"></div>
      <div class="field span-2"><div class="field-label-row"><label>项目</label><span class="field-help">默认为空；点击 ＋ 从已有项目中勾选，可同时关联多个项目。</span></div><div class="project-picker-row"><div class="project-chip-box" id="f-projects" data-projects="${esc(JSON.stringify(doc.projects||[]))}"></div><button type="button" class="secondary-btn project-add-btn" id="f-project-add" title="从已有项目中添加">＋</button></div></div>
      <div class="field"><label>状态</label><select id="f-status">${(state.statuses[kind]||[]).map(s=>`<option ${s===doc.status?'selected':''}>${esc(s)}</option>`).join('')}</select></div>
      ${dateField?`<div class="field"><label>${dateField==='due'?'截止日期':'日期'}</label><input id="f-date" type="date" value="${esc(doc[dateField]||today())}"></div>`:''}
      ${kind==='summary'?`<div class="field"><label>总结类型</label><select id="f-summary-type">${['日总结','周总结','月总结','阶段总结'].map(s=>`<option ${s===doc.summary_type?'selected':''}>${s}</option>`).join('')}</select></div>`:''}
      ${special?literatureFields(doc):''}
      <div class="field ${tagsSpan}"><div class="field-label-row"><label>标签</label><span class="field-help">点击 ＋ 添加：可勾选已有标签或输入新标签。</span></div><div class="project-picker-row"><div class="project-chip-box" id="f-tags" data-tags="${esc(JSON.stringify(doc.tags||[]))}"></div><button type="button" class="secondary-btn project-add-btn" id="f-tag-add" title="添加标签">＋</button></div></div>
      <!-- v260924k · 置顶开关与分类标记同行：标签行右侧，不另占一行 -->
      <div class="field span-4"><div class="field-label-row"><label>分类标记</label><label class="pin-toggle" title="勾选后该条目固定显示在列表最前"><input id="f-pinned" type="checkbox" ${doc.pinned?'checked':''}>📌 置顶显示</label></div><div class="mark-chip-box" id="f-marks">${markChipsHtml(doc.kind_marks||[])}</div></div>
      </div>
    </div>
    <div class="editor-wrap">${editorHtml(doc.body||'')}</div></div>
    <div class="editor-actions"><span class="row-meta">${doc.draft?'新建草稿 · 首次保存后生成 Markdown 文件':`${esc(doc.path)} · 更新 ${fmtTime(doc.updated)}`}</span><div class="right"><button class="secondary-btn" id="doc-open-file" ${doc.draft?'disabled':''} title="在外部编辑器中打开该 Markdown 原文件">↗ 打开原文件</button><button class="secondary-btn" id="doc-delete">${doc.draft?'丢弃草稿':'删除'}</button><button class="primary-btn" id="doc-save">保存</button></div></div>`;
    wireEditor();
    const metaBtn=$('#meta-toggle'); /* v260929 · 条目信息收起/展开：只切类名不动输入值，保存仍带全部字段 */
    if(metaBtn)metaBtn.onclick=()=>{
      const folded=$('#meta-block').classList.toggle('collapsed');
      metaBtn.textContent=folded?'展开':'收起';
      metaBtn.setAttribute('aria-expanded',String(!folded));
      $('#meta-block').scrollTop=0;
      $('.doc-editor-content').scrollTop=0;
      try{localStorage.setItem('erwMetaCollapsed:'+kind,folded?'1':'0')}catch{}
    };
    ['f-title','f-status','f-date','f-summary-type','f-pinned','f-authors','f-year','f-venue','f-doi','f-url','f-cite-key','f-bibtex'].forEach(id=>{const el=$('#'+id);if(el)el.addEventListener('input',()=>state.dirty=true)}); /* v260924i · 含置顶开关脏标记 */
    const lookupBtn=$('#f-lookup-btn'); if(lookupBtn)lookupBtn.onclick=autoFillLiterature; /* v260929 · 自动填写按钮（文献编辑器） */
    paintEditorProjects(doc.projects||[]); $('#f-project-add').onclick=openEditorProjectPicker;
    paintEditorTags(doc.tags||[]); $('#f-tag-add').onclick=openEditorTagPicker;
    wireMarkChips();
    $('#doc-save').onclick=()=>saveCurrentDoc(state.selectedDoc).catch(()=>{}); $('#doc-delete').onclick=()=>deleteCurrentDoc(state.selectedDoc);
    $('#doc-open-file').onclick=()=>openSourceFile(doc);
    renderMarkdownPreview();
    state.editorBaseline=JSON.stringify(editorPayload(doc));state.dirty=false;
    window.dispatchEvent(new Event('workbench:editor-state'));
  }
  /* v261008 · 打开原文件：选择外部编辑器（VS Code / Typora）打开该条目的 Markdown 原文件（服务端按编辑器解析可执行文件） */
  function openSourceFile(doc){
    const editors=[{id:'vscode',label:'VS Code'},{id:'typora',label:'Typora'}];
    modal('打开原文件',`<div class="row-meta" style="margin-bottom:10px">选择编辑器打开该条目的 Markdown 原文件：<br><code>${esc(doc.path)}</code></div><div style="display:flex;gap:8px;flex-wrap:wrap">${editors.map(e=>`<button type="button" class="secondary-btn" data-editor="${e.id}">${e.label}</button>`).join('')}</div>`);
    $$('#modal-body [data-editor]').forEach(b=>b.onclick=async()=>{
      closeModal();
      try{ await api('/api/workspace/open-with',{method:'POST',body:{path:doc.path,editor:b.dataset.editor}}); toast('已用 '+b.textContent+' 打开原文件'); }
      catch(err){ toast(err.message||'打开失败',true); }
    });
  }
  function editorProjects(){
    const box=$('#f-projects');if(!box)return [];try{const v=JSON.parse(box.dataset.projects||'[]');return Array.isArray(v)?v:[]}catch{return []}
  }
  function paintEditorProjects(projects){
    const box=$('#f-projects');if(!box)return;const list=[...new Set((projects||[]).map(x=>String(x).trim()).filter(Boolean))];box.dataset.projects=JSON.stringify(list);box.innerHTML=list.length?list.map((p,i)=>`<span class="project-chip">${esc(p)}<button type="button" data-project-remove="${i}" title="移除项目">×</button></span>`).join(''):'<span class="row-meta">未关联项目</span>';$$('[data-project-remove]',box).forEach(b=>b.onclick=()=>{const now=editorProjects();now.splice(+b.dataset.projectRemove,1);paintEditorProjects(now);state.dirty=true});
  }
  /* v260923 · 标签 chip 化：与项目一致的交互（× 移除 + ＋ 弹窗添加） */
  function editorTags(){
    const box=$('#f-tags');if(!box)return [];try{const v=JSON.parse(box.dataset.tags||'[]');return Array.isArray(v)?v:[]}catch{return []}
  }
  function paintEditorTags(tags){
    const box=$('#f-tags');if(!box)return;const list=[...new Set((tags||[]).map(x=>String(x).trim()).filter(Boolean))];box.dataset.tags=JSON.stringify(list);box.innerHTML=list.length?list.map((t,i)=>`<span class="project-chip tag-chip">${esc(t)}<button type="button" data-tag-remove="${i}" title="移除标签">×</button></span>`).join(''):'<span class="row-meta">暂无标签</span>';$$('[data-tag-remove]',box).forEach(b=>b.onclick=()=>{const now=editorTags();now.splice(+b.dataset.tagRemove,1);paintEditorTags(now);state.dirty=true});
  }
  /* v260929 · 标签选择器通用化（入参：当前标签 / 已有标签来源 / 应用回调），文献编辑区与 PDF 阅读区共用 */
  function openTagPicker(current, known, onApply){
    const selected=new Set(current||[]);
    let query=''; /* v260923 · 搜索与新建合并：输入即过滤，回车选中已有或创建新标签 */
    const allKnown=()=>[...new Set(typeof known==='function'?known():(known||[]))];
    const renderList=()=>{
      const q=query.trim().toLowerCase();
      const known=allKnown().filter(t=>!selected.has(t)).filter(t=>!q||t.toLowerCase().includes(q)).sort((a,b)=>a.localeCompare(b,'zh'));
      const picked=[...selected];
      $('#f-tag-pick-list').innerHTML=(picked.map(t=>`<label class="bundle-item"><input type="checkbox" data-tag-pick="${esc(t)}" checked><span><strong>${esc(t)}</strong><span class="row-meta">新选择</span></span></label>`).join('')+(known.length?known.map(t=>`<label class="bundle-item"><input type="checkbox" data-tag-pick="${esc(t)}"><span><strong>${esc(t)}</strong></span></label>`).join(''):(q?`<div class="empty">没有匹配的标签，回车将创建「${esc(query.trim())}」</div>`:(picked.length?'':'<div class="empty">暂无已有标签，直接输入即可创建。</div>'))));
    };
    const commitQuery=()=>{
      const v=$('#f-tag-query').value.trim();if(!v)return;
      const hit=allKnown().find(t=>t.toLowerCase()===v.toLowerCase());
      const val=hit||v;
      if(selected.has(val)){toast('该标签已在列表中',true);return;}
      selected.add(val);$('#f-tag-query').value='';query='';renderList();
    };
    modal('添加标签',`<div class="row-meta" style="margin-bottom:10px">输入即实时搜索已有标签；没有匹配时回车或点「添加」将创建为新标签。</div><div class="mark-mgr-row" style="margin-bottom:10px"><input id="f-tag-query" class="mark-name" maxlength="24" placeholder="搜索已有标签，或输入新标签"><button class="primary-btn" id="f-tag-query-add">添加</button></div><div class="project-pick-list" id="f-tag-pick-list"></div>`,`<button class="secondary-btn" id="tag-pick-cancel">取消</button><button class="primary-btn" id="tag-pick-done">应用</button>`);
    $('#tag-pick-cancel').onclick=closeModal;
    $('#f-tag-query-add').onclick=commitQuery;
    $('#f-tag-query').oninput=e=>{query=e.target.value;renderList();};
    $('#f-tag-query').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();commitQuery();}};
    $('#tag-pick-done').onclick=()=>{const list=$$('[data-tag-pick]:checked').map(x=>x.dataset.tagPick);onApply(list);closeModal()};
    renderList();
  }
  function openEditorTagPicker(){ openTagPicker(editorTags(), ()=>[...new Set(state.docs.flatMap(d=>d.tags||[]))], list=>{paintEditorTags(list);state.dirty=true}) }
  window.ERWTagPicker = openTagPicker;
  function openEditorProjectPicker(){
    const selected=new Set(editorProjects());
    modal('添加已有项目',`<div class="row-meta" style="margin-bottom:10px">勾选要关联到当前条目的已有项目。项目本身请在概览“项目推进”或资源页创建。</div><div class="project-pick-list">${state.projects.length?state.projects.map(p=>`<label class="bundle-item"><input type="checkbox" data-project-pick="${esc(p)}" ${selected.has(p)?'checked':''}><span><strong>${esc(p)}</strong></span></label>`).join(''):'<div class="empty">暂无已有项目，请先新建项目。</div>'}</div>`,`<button class="secondary-btn" id="project-pick-new">＋ 新建项目</button><button class="secondary-btn" id="project-pick-cancel">取消</button><button class="primary-btn" id="project-pick-done">应用</button>`);
    $('#project-pick-cancel').onclick=closeModal;
    $('#project-pick-new').onclick=()=>openCreateProjectModal(async()=>{state.projects=await api('/api/projects');openEditorProjectPicker()});
    $('#project-pick-done').onclick=()=>{const list=$$('[data-project-pick]:checked').map(x=>x.dataset.projectPick);paintEditorProjects(list);state.dirty=true;closeModal()};
  }

  function literatureFields(d){return `<div class="field span-4"><div class="field-label-row"><label>自动填写</label><span class="field-help">粘贴 DOI 或 arXiv 编号联网抓取；直接粘贴一段 BibTeX 则本地解析回填。抓取/解析后请核对再保存。</span></div><div class="field-input-row"><input id="f-lookup" placeholder="如 10.1109/TGRS.2023.1234567、2401.02345 或 @article{…}"><button type="button" class="secondary-btn" id="f-lookup-btn">填写</button></div></div><div class="field span-2"><label>作者</label><input id="f-authors" value="${esc(d.authors||'')}"></div><div class="field"><label>年份</label><input id="f-year" value="${esc(d.year||'')}"></div><div class="field"><label>引用键 Cite Key</label><input id="f-cite-key" value="${esc(d.cite_key||'')}"></div><div class="field span-2"><label>期刊 / 会议</label><input id="f-venue" value="${esc(d.venue||'')}"></div><div class="field"><label>DOI</label><input id="f-doi" value="${esc(d.doi||'')}"></div><div class="field"><label>URL</label><input id="f-url" value="${esc(d.url||'')}"></div><div class="field span-2"><div class="field-label-row"><label>PDF 附件路径</label><span class="field-help">绝对路径或相对 Workspace 的路径，仅 .pdf；文件存在时列表会显示附件图标。</span></div><input id="f-attachment" value="${esc(d.attachment||'')}" placeholder="如 Knowledge/Attachments/xxx.pdf"></div><div class="field span-4"><label>BibTeX（会与正文中的 bibtex 代码块同步）</label><textarea id="f-bibtex" class="mono bibtex-input" placeholder="@article{...}">${esc(d.bibtex||'')}</textarea></div>`}
  /* v260929 · 自动填写（阶段 4）：DOI/arXiv 走后端 lookup（CrossRef/arXiv API），
     BibTeX 文本则前端本地解析；回填仅覆盖非空字段，不动用户已填内容 */
  function parseBibtexFields(bib){
    const out={bibtex:bib.trim()};
    const km=bib.match(/@\w+\s*\{\s*([^,\s]+)\s*,/); if(km)out.cite_key=km[1];
    const grab=f=>{const m=bib.match(new RegExp(f+'\\s*=\\s*\\{((?:[^{}]|\\{[^{}]*\\})*)\\}','i'));return m?m[1].replace(/\s+/g,' ').trim():''};
    out.title=grab('title'); out.authors=grab('author'); out.year=grab('year');
    out.venue=grab('journal')||grab('booktitle')||grab('publisher'); out.doi=grab('doi'); out.url=grab('url');
    return out;
  }
  async function autoFillLiterature(){
    const raw=($('#f-lookup')?.value||'').trim();
    if(!raw)return toast('请输入 DOI、arXiv 编号或一段 BibTeX',true);
    let m=null;
    if(raw.startsWith('@'))m=parseBibtexFields(raw);
    if(!m){try{m=await api('/api/literature/lookup',{method:'POST',body:{identifier:raw}})}catch(e){return toast(e.message||e.error||'抓取失败',true)}}
    const map={'f-title':m.title,'f-authors':m.authors,'f-year':m.year,'f-venue':m.venue,'f-doi':m.doi,'f-url':m.url,'f-cite-key':m.cite_key,'f-bibtex':m.bibtex};
    let n=0; for(const [id,val] of Object.entries(map)){const el=$('#'+id);if(el&&val){el.value=val;n++}}
    if(m.bibtex){const ta=$('#md-input');if(ta){const block='```bibtex\n'+m.bibtex+'\n```';ta.value=/```bibtex\s*\n[\s\S]*?```/i.test(ta.value)?ta.value.replace(/```bibtex\s*\n[\s\S]*?```/i,block):ta.value;debouncedPreview()}}
    state.dirty=true; toast(n?('已回填 '+n+' 项，请核对后保存'):'未解析到可回填字段',!n);
  }
  function editorHtml(body){return `<div class="toolbar">
    <button type="button" data-md="h1" title="一级标题">H1</button><button type="button" data-md="h2" title="二级标题">H2</button><button type="button" data-md="h3" title="三级标题">H3</button><span class="sep"></span>
    <button type="button" data-md="bold"><b>B</b></button><button type="button" data-md="italic"><i>I</i></button><button type="button" data-md="strike"><s>S</s></button><button type="button" data-md="inlinecode">&#96;</button><span class="sep"></span>
    <button type="button" data-md="ul" title="无序列表">•</button><button type="button" data-md="ol" title="有序列表">1.</button><button type="button" data-md="task">☑</button><button type="button" data-md="quote">❯</button><button type="button" data-md="hr">—</button><span class="sep"></span>
    <button type="button" data-md="link">↗</button><button type="button" data-md="image">▧</button><button type="button" data-md="wiki">[[ ]]</button><span class="sep"></span>
    <button type="button" data-md="math" title="行内公式">∑</button><button type="button" data-md="mathblock" title="块公式">∑□</button><button type="button" data-md="code">&lt;/&gt;</button><button type="button" data-md="table">▦</button><button type="button" data-md="mermaid" title="Mermaid 绘图（flowchart / sequence / class / state / gantt 等）">◇</button>
    <div class="editor-tabs"><button class="${state.editorMode==='split'?'active':''}" data-edit-mode="split">分屏</button><button class="${state.editorMode==='edit'?'active':''}" data-edit-mode="edit">编辑</button><button class="${state.editorMode==='preview'?'active':''}" data-edit-mode="preview">预览</button></div>
    </div><div class="editor-pane ${state.editorMode==='edit'?'edit-only':state.editorMode==='preview'?'preview-only':''}" id="editor-pane"><textarea class="md-input" id="md-input" spellcheck="false" placeholder="Markdown · GFM 表格/任务列表 · LaTeX · Mermaid · 代码高亮 · [[双链]] · 截图粘贴…">${esc(body)}</textarea><div class="md-preview" id="md-preview"></div></div>`}

  function wireEditor(){
    const ta=$('#md-input'); if(!ta)return;
    /* v261022.4 · 引用补全/预览（[[ 补全、Ctrl+Shift+K 引用选择器、悬停预览、断链状态） */
    window.ERWDocReferences?.bindEditor(ta);
    const bib=$('#f-bibtex'); let syncingBib=false;
    /* v260924b · 分屏滚动同步（精确版）：预览按 top-level 块渲染并记录源行号锚点（见 renderMarkdownPreview），
       编辑侧用 canvas 量宽估算软换行的物理行→逻辑行映射；两侧任一滚动，另一侧先落到所在块、再按块内比例对齐。 */
    const pv=$('#md-preview'); let syncLock=false, syncLockTimer=0;
    window.ERWDocReferences?.bindPreview?.(pv);
    /* v260924g · 锁改由「被写侧的 scroll 事件」释放：旧实现用 rAF 解锁，但渲染帧内 rAF 回调先于 scroll 事件派发，
     * 锁在回声事件到来前已失效 → 编辑器↔预览互相写入形成无限互滚（滚动条自动滑动）。
     * 事件驱动释放 + 150ms 兜底定时器（写入未引起滚动时防锁死）。 */
    const bindScrollSync=(src,dst,fn)=>src.addEventListener('scroll',()=>{
      if(syncLock){syncLock=false;clearTimeout(syncLockTimer);return;}
      if(state.editorMode!=='split')return;
      if(src.scrollHeight-src.clientHeight<=1||dst.scrollHeight-dst.clientHeight<=1)return;
      syncLock=true; fn();
      clearTimeout(syncLockTimer); syncLockTimer=setTimeout(()=>{syncLock=false},150);
    });
    if(pv){bindScrollSync(ta,pv,syncEdToPv);bindScrollSync(pv,ta,syncPvToEd);}
    ta.addEventListener('input',()=>{state.dirty=true;state._mdSyncVer=(state._mdSyncVer||0)+1;if(bib&&!syncingBib){const m=ta.value.match(/```bibtex\s*\n([\s\S]*?)```/i);if(m&&bib.value.trim()!==m[1].trim()){syncingBib=true;bib.value=m[1].trim();syncingBib=false;}}debouncedPreview();});
    if(bib)bib.addEventListener('input',()=>{if(syncingBib)return;syncingBib=true;const block='```bibtex\n'+bib.value.trim()+'\n```';if(/```bibtex\s*\n[\s\S]*?```/i.test(ta.value))ta.value=ta.value.replace(/```bibtex\s*\n[\s\S]*?```/i,block);else ta.value='## BibTeX\n\n'+block+'\n\n'+ta.value;syncingBib=false;state.dirty=true;debouncedPreview();});
    ta.addEventListener('paste',onPasteImage); ta.addEventListener('dragover',e=>e.preventDefault()); ta.addEventListener('drop',onDropImage);
    $$('[data-edit-mode]').forEach(b=>b.onclick=()=>{state.editorMode=b.dataset.editMode; const p=$('#editor-pane');p.className='editor-pane '+(state.editorMode==='edit'?'edit-only':state.editorMode==='preview'?'preview-only':'');$$('[data-edit-mode]').forEach(x=>x.classList.toggle('active',x.dataset.editMode===state.editorMode)); if(state.editorMode!=='edit')renderMarkdownPreview();});
    $$('[data-md]').forEach(b=>b.onclick=()=>applyMdCommand(b.dataset.md));
  }
  const debouncedPreview=debounce(renderMarkdownPreview,250);
  /* ---------- v260924b · 分屏滚动同步核心 ---------- */
  let _mdMeasureCtx=null;
  /* 用 canvas 逐行量宽，估算 textarea 软换行后的物理行累计表 cum[k] = 前 k 个逻辑行占用的物理行数 */
  function ensureMdSyncMap(ta){
    const ver=state._mdSyncVer||0,c=state._mdSyncCache;
    /* v260924b · 缓存键含文本长度：setRangeText/直接赋值不触发 input 事件，长度变化时强制重建 */
    if(c&&c.ver===ver&&c.w===ta.clientWidth&&c.len===ta.value.length)return c;
    const cs=getComputedStyle(ta);
    const lineH=parseFloat(cs.lineHeight)||parseFloat(cs.fontSize)*1.65||21;
    const wrapW=Math.max(40,ta.clientWidth-parseFloat(cs.paddingLeft||0)-parseFloat(cs.paddingRight||0));
    if(!_mdMeasureCtx)_mdMeasureCtx=document.createElement('canvas').getContext('2d');
    try{_mdMeasureCtx.font=`${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize}/${cs.lineHeight==='normal'?'normal':cs.lineHeight} ${cs.fontFamily}`;}catch(e){_mdMeasureCtx.font=`${cs.fontSize} ${cs.fontFamily}`;}
    const lines=ta.value.split('\n'),cum=[0];
    for(const ln of lines){const w=ln?_mdMeasureCtx.measureText(ln).width:0;cum.push(cum[cum.length-1]+(w<=0?1:Math.max(1,Math.ceil(w/wrapW))));}
    state._mdSyncCache={ver,w:ta.clientWidth,len:ta.value.length,cum,lineH};
    return state._mdSyncCache;
  }
  /* 物理行位置 → 逻辑行号（浮点） */
  function mdPhysToLogical(m,p){
    const cum=m.cum; p=Math.max(0,Math.min(p,cum[cum.length-1]));
    let lo=0,hi=cum.length-1;
    while(lo<hi-1){const mid=(lo+hi)>>1;if(p<cum[mid])hi=mid;else lo=mid;}
    const span=Math.max(1,cum[lo+1]-cum[lo]);
    return Math.min(lo+(p-cum[lo])/span,cum.length-2);
  }
  /* 逻辑行号（浮点） → 物理行位置 */
  function mdLogicalToPhys(m,L){
    const cum=m.cum,n=cum.length-1;
    let k=Math.max(0,Math.min(Math.floor(L),n-1));
    const frac=Math.max(0,Math.min(L-k,1));
    return cum[k]+frac*Math.max(1,cum[k+1]-cum[k]);
  }
  /* 取当前滚动位置所在的锚点块：返回像素区间（pStart/pEnd）与逻辑行区间（lStart/lEnd），blocks 与 anchors 一一对应 */
  function mdAnchorAt(pv,anchors,blocks,pos,isPixel){
    if(!anchors||!blocks.length||anchors.length!==blocks.length)return null;
    const pvTop=pv.getBoundingClientRect().top;
    const tops=blocks.map(el=>el.getBoundingClientRect().top-pvTop+pv.scrollTop);
    let i=0;
    if(isPixel){for(let k=0;k<blocks.length;k++){if(tops[k]<=pos)i=k;else break;}}
    else{for(let k=0;k<anchors.length;k++){if(anchors[k].line<=pos)i=k;else break;}}
    const pStart=tops[i],pEnd=(i+1<blocks.length?tops[i+1]:tops[i]+blocks[i].offsetHeight);
    const lStart=anchors[i].line,lEnd=(i+1<anchors.length?anchors[i+1].line:anchors[i].end);
    return {i,pStart,pEnd,lStart,lEnd,el:blocks[i]};
  }
  function syncEdToPv(){
    const ta=$('#md-input'),pv=$('#md-preview'); if(!ta||!pv)return;
    const sh=ta.scrollHeight-ta.clientHeight,dh=pv.scrollHeight-pv.clientHeight; if(sh<=1||dh<=1)return;
    const anchors=state._mdAnchors,blocks=$$('.md-block',pv);
    let target;
    if(anchors&&blocks.length===anchors.length){
      const m=ensureMdSyncMap(ta);
      const L=mdPhysToLogical(m,ta.scrollTop/m.lineH);
      const iv=mdAnchorAt(pv,anchors,blocks,L,false); if(!iv)return;
      const frac=iv.lEnd>iv.lStart?(L-iv.lStart)/(iv.lEnd-iv.lStart):0;
      target=iv.pStart+frac*(iv.pEnd-iv.pStart)-2;
    }else target=ta.scrollTop/sh*dh;
    pv.scrollTop=Math.max(0,Math.min(dh,target));
  }
  function syncPvToEd(){
    const ta=$('#md-input'),pv=$('#md-preview'); if(!ta||!pv)return;
    const sh=ta.scrollHeight-ta.clientHeight,dh=pv.scrollHeight-pv.clientHeight; if(sh<=1||dh<=1)return;
    const anchors=state._mdAnchors,blocks=$$('.md-block',pv);
    let target;
    if(anchors&&blocks.length===anchors.length){
      const m=ensureMdSyncMap(ta);
      const iv=mdAnchorAt(pv,anchors,blocks,pv.scrollTop+2,true); if(!iv)return;
      const frac=iv.pEnd>iv.pStart?(pv.scrollTop+2-iv.pStart)/(iv.pEnd-iv.pStart):0;
      const L=iv.lStart+frac*(iv.lEnd-iv.lStart);
      target=mdLogicalToPhys(m,L)*m.lineH-2;
    }else target=pv.scrollTop/dh*sh;
    ta.scrollTop=Math.max(0,Math.min(sh,target));
  }
  function normalizePreviewPaths(html){
    return html
      .replace(/(src|href)="\.\.\/Attachments\//g, '$1="/workspace-file/Knowledge/Attachments/')
      .replace(/(src|href)="\.\.\/\.\.\/Attachments\//g, '$1="/workspace-file/Knowledge/Attachments/')
      /* v260929w · Workspace 相对路径图片（批注截图 / 笔记插图 Knowledge/... 等）：img src 统一经 /workspace-file/ 服务；href 不动，避免干扰 wiki 内部相对链接 */
      .replace(/src="(?!https?:|data:|\/|#)([^"]+)"/g,(m,p)=>'src="/workspace-file/'+p.replace(/^\.?\//,"")+'"');
  }
  function basicMarkdown(raw){
    // Offline-safe fallback. Full Marked is preferred when available.
    const blocks=[];
    let src=String(raw||'').replace(/```([^\n]*)\n([\s\S]*?)```/g,(_,lang,code)=>{const i=blocks.length;blocks.push({lang:lang.trim(),code});return `\n@@CODE${i}@@\n`;});
    src=esc(src);
    src=src.replace(/^######\s+(.+)$/gm,'<h6>$1</h6>').replace(/^#####\s+(.+)$/gm,'<h5>$1</h5>').replace(/^####\s+(.+)$/gm,'<h4>$1</h4>').replace(/^###\s+(.+)$/gm,'<h3>$1</h3>').replace(/^##\s+(.+)$/gm,'<h2>$1</h2>').replace(/^#\s+(.+)$/gm,'<h1>$1</h1>');
    src=src.replace(/^&gt;\s?(.+)$/gm,'<blockquote>$1</blockquote>').replace(/^---+$/gm,'<hr>');
    src=src.replace(/^\s*- \[([ xX])\]\s+(.+)$/gm,(_,c,t)=>`<div class="task-fallback"><input type="checkbox" disabled ${c.trim()?'checked':''}> ${t}</div>`);
    src=src.replace(/^\s*[-*+]\s+(.+)$/gm,'<li>$1</li>');
    src=src.replace(/^\s*\d+\.\s+(.+)$/gm,'<li>$1</li>');
    src=src.replace(/(?:<li>.*<\/li>\n?)+/g,m=>`<ul>${m}</ul>`);
    src=src.replace(/!\[([^\]]*)\]\(([^\)]+)\)/g,'<img alt="$1" src="$2">').replace(/\[([^\]]+)\]\(([^\)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    src=src.replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/~~([^~]+)~~/g,'<del>$1</del>').replace(/\*([^*]+)\*/g,'<em>$1</em>');
    src=src.split(/\n{2,}/).map(x=>/^\s*<(h\d|ul|ol|blockquote|hr|div)/.test(x)||/^@@CODE/.test(x.trim())?x:`<p>${x.replace(/\n/g,'<br>')}</p>`).join('\n');
    src=src.replace(/@@CODE(\d+)@@/g,(_,n)=>{const b=blocks[+n];if(b.lang==='mermaid')return `<div class="mermaid">${esc(b.code)}</div>`;return `<pre><code class="language-${esc(b.lang)}">${esc(b.code)}</code></pre>`;});
    return src;
  }
  async function renderMermaidBlocks(out,seq){
    const nodes=$$('.mermaid',out); if(!nodes.length)return;
    try{await window.ERWRenderLibraries.ensureMermaid()}catch(error){
      nodes.forEach(node=>{node.className='mermaid-error';node.textContent=`Mermaid 加载失败：${error.message}\n\n${node.textContent}`});
      return;
    }
    if(seq!==out._markdownSeq||!out.isConnected)return;
    if(!window.mermaid){nodes.forEach(n=>{n.className='mermaid-error';n.textContent='Mermaid 渲染库暂未加载。联网后 Reload 页面即可恢复图形渲染；Markdown 源码不会丢失。\n\n'+n.textContent;});return;}
    try{mermaid.initialize({startOnLoad:false,theme:document.documentElement.dataset.theme==='dark'?'dark':'default',securityLevel:'strict',fontFamily:'Microsoft YaHei, 微软雅黑, sans-serif'});}catch(e){console.warn(e)}
    for(let i=0;i<nodes.length;i++){
      const node=nodes[i],code=node.textContent.trim(); if(!code)continue;
      try{const id=`erw-mermaid-${seq}-${i}-${Date.now()}`;const result=await mermaid.render(id,code);if(seq!==out._markdownSeq||!document.body.contains(out))return;node.innerHTML=result.svg;result.bindFunctions?.(node);}
      catch(e){console.warn('Mermaid render failed',e);node.className='mermaid-error';node.textContent=`Mermaid 渲染失败：${e?.message||e}\n\n${code}`;}
    }
  }

  async function renderMarkdownPreview(){
    const ta=$('#md-input'), out=$('#md-preview'); if(!ta||!out)return; const seq=++state.previewSeq;out._markdownSeq=seq; const raw=ta.value;
    let html='';
    if(window.marked && window.DOMPurify){
      const renderer=new marked.Renderer();
      renderer.code=(tokenOrCode,info)=>{let code='',lang='';if(tokenOrCode&&typeof tokenOrCode==='object'){code=tokenOrCode.text||'';lang=tokenOrCode.lang||'';}else{code=String(tokenOrCode||'');lang=String(info||'');}lang=lang.trim();if(lang==='mermaid')return `<div class="mermaid">${esc(code)}</div>`;return `<pre><code class="language-${esc(lang)}">${esc(code)}</code></pre>`;};
      const opts={gfm:true,breaks:false,renderer};
      /* v260924b · 按 top-level token 分块渲染并记录源行号锚点（供分屏滚动同步）；
         链接引用定义（[x]: url）注入每个分块，避免跨块引用失效 */
      try{
        const tokens=marked.lexer(raw);
        const parts=[],anchors=[];let lineNo=0,defsRaw='';
        for(const tk of tokens){
          const startLine=lineNo;lineNo+=tk.raw.split('\n').length-1;
          if(tk.type==='def'){defsRaw+=tk.raw;continue;}
          if(tk.type==='space'||!tk.raw.trim())continue;
          anchors.push({line:startLine,end:0});
          parts.push(marked.parse((defsRaw?defsRaw+'\n':'')+tk.raw,opts));
        }
        const totalLines=Math.max(lineNo,raw.split('\n').length);
        for(let i=0;i<anchors.length;i++)anchors[i].end=(i+1<anchors.length?anchors[i+1].line:totalLines);
        state._mdAnchors=anchors.length?anchors:null;
        html=parts.map((h,i)=>`<div class="md-block" data-line="${anchors[i].line}">${h}</div>`).join('');
      }catch(e){console.warn('marked chunked parse failed, fallback whole',e);state._mdAnchors=null;html=marked.parse(raw,opts);}
    } else {html=basicMarkdown(raw);state._mdAnchors=null;}
    html=html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(_,target,label)=>`<a href="#" class="wiki-link" data-wiki="${esc(target)}">${esc(label||target)}</a>`);
    /* v260924 · 关联条目跳转：符合知识库命名前缀的反引号标题（如 `知识-方法-…`、`文献-…`）自动转为
       可点击链接（点击复用双链逻辑，按目标 kind 路由到笔记/文献/总结等管理页并选中），
       仅包裹已有文本、不新增界面元素，避免加剧界面拥挤 */
    html=html.replace(/<code>([^<]{1,160})<\/code>/g,(m,inner)=>{
      const text=inner.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&amp;/g,'&');
      if(!/^(知识|总结|灵感|日志|里程碑|文献)-/.test(text))return m;
      return `<a href="#" class="wiki-link kb-ref" data-wiki="${esc(text)}"><code>${inner}</code></a>`;
    });
    html=normalizePreviewPaths(html);
    if(seq!==out._markdownSeq||!document.body.contains(out))return;
    out.innerHTML=window.DOMPurify?DOMPurify.sanitize(html,{ADD_ATTR:['target','rel','data-wiki','checked','disabled'],ADD_TAGS:['mjx-container']}):html;
    $$('pre code',out).forEach(el=>{try{window.hljs?.highlightElement(el)}catch{}});
    await renderMermaidBlocks(out,seq);
    if(seq!==out._markdownSeq||!document.body.contains(out))return;
    try{await window.ERWRenderLibraries.renderMath([out])}catch(e){console.warn(e)}
    if(seq!==out._markdownSeq||!document.body.contains(out))return;
    $$('.wiki-link',out).forEach(a=>a.onclick=async e=>{e.preventDefault();const q=a.dataset.wiki;const results=await api('/api/docs?q='+encodeURIComponent(q));const self=state.selectedDoc&&state.selectedDoc.id;const exact=results.find(x=>x.id===q||x.title===q)||results.find(x=>x.id!==self)||null;if(exact){await openDocRoute(routeForKind(exact.kind),exact.id)}else toast(`未找到关联条目：${q}`,true)});
  }
  window.ERWMarkdown = {renderInto: renderMarkdownInto};

  function applyMdCommand(cmd){
    const ta=$('#md-input'); const a=ta.selectionStart,b=ta.selectionEnd,sel=ta.value.slice(a,b);
    const map={h1:`# ${sel||'标题'}`,h2:`## ${sel||'标题'}`,h3:`### ${sel||'标题'}`,bold:`**${sel||'粗体'}**`,italic:`*${sel||'斜体'}*`,strike:`~~${sel||'删除线'}~~`,inlinecode:'`'+(sel||'code')+'`',ul:`- ${sel||'列表项'}`,ol:`1. ${sel||'列表项'}`,task:`- [ ] ${sel||'待办'}`,quote:`> ${sel||'引用'}`,hr:'\n---\n',link:`[${sel||'链接文字'}](https://)`,math:`$${sel||'E=mc^2'}$`,mathblock:'$$\n'+(sel||'\\int_0^1 x^2 \\, dx')+'\n$$',code:'```python\n'+(sel||'# code')+'\n```',table:'| 列1 | 列2 |\n| --- | --- |\n| 内容 | 内容 |',mermaid:'```mermaid\nflowchart LR\n  A[开始] --> B[结果]\n```',wiki:`[[${sel||'关联笔记标题'}]]`};
    if(cmd==='image'){pickImage();return;} insertAtSelection(ta,map[cmd]||'');
  }

  function insertAtSelection(ta,text){ const a=ta.selectionStart,b=ta.selectionEnd;ta.setRangeText(text,a,b,'end');ta.focus();state.dirty=true;debouncedPreview(); }
  function pickImage(){ const input=document.createElement('input');input.type='file';input.accept='image/*';input.onchange=()=>{if(input.files[0])uploadImage(input.files[0])};input.click(); }
  async function onPasteImage(e){ const files=[...e.clipboardData.items].filter(x=>x.type.startsWith('image/')).map(x=>x.getAsFile()).filter(Boolean); if(!files.length)return;e.preventDefault();for(const f of files)await uploadImage(f); }
  async function onDropImage(e){e.preventDefault();const files=[...e.dataTransfer.files].filter(f=>f.type.startsWith('image/'));for(const f of files)await uploadImage(f);}
  async function uploadImage(file){ if(file.size>15*1024*1024)return toast('图片不能超过 15 MB',true); const dataUrl=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file)}); const res=await api('/api/assets',{method:'POST',body:{data_url:dataUrl,name:file.name}});insertAtSelection($('#md-input'),'\n'+res.markdown+'\n');toast('图片已保存到 Workspace/Knowledge/Attachments'); }
  async function saveCurrentDoc(doc){
    if(state.saving)return state.saving;
    if(!doc)return;
    if(doc.draft&&!editorDirty()){toast('草稿尚未修改，无需保存');return}
    const body=editorPayload(doc),snapshot=JSON.stringify(body);
    state.saving=(async()=>{
      const button=$('#doc-save');if(button)button.disabled=true;
      try{
        const saved=await api(doc.draft?'/api/docs':'/api/docs/'+encodeURIComponent(doc.id),{method:'POST',body:doc.draft?{...body,kind:doc.kind}:{...body,...(doc.kind==='milestone'&&doc.revision?{expected_revision:state.selectedDoc?.id===doc.id?state.selectedDoc.revision:doc.revision}:{})}});
        window.ERWDocReferences?.invalidate();
        state.draft=null;state.selectedDoc=saved;window.ERWCurrentDoc=saved.id;
        // Do not drop edits typed while the request was in flight.
        if(JSON.stringify(editorPayload(doc))===snapshot){renderDocEditor(saved)}
        else{state.editorBaseline=snapshot;state.dirty=true;$('#doc-open-file').disabled=false;$('#doc-delete').textContent='删除'}
        toast('已保存 Markdown');window.dispatchEvent(new Event('workbench:editor-state'));
        await refreshListAfterSave(doc.kind,saved.id);return saved;
      }catch(error){toast('保存失败：'+error.message,true);throw error}
      finally{const b=$('#doc-save');if(b)b.disabled=false}
    })();
    try{return await state.saving}finally{state.saving=null}
  }
  async function refreshListAfterSave(kind,id){ state.docs=await api('/api/docs?kind='+kind);const list=$('#doc-list');if(list){list.innerHTML=docItems(state.docs);wireDocList(kind);$$('[data-doc-id]').forEach(x=>x.classList.toggle('active',x.dataset.docId===id));} }
  async function deleteCurrentDoc(doc){
    if(doc.draft){if(editorDirty()&&!await window.ERWDialog.confirm('丢弃这篇草稿及其修改？',{title:'丢弃草稿'}))return;state.draft=null;state.selectedDoc=null;state.editorBaseline=null;state.dirty=false;await renderDocsPage(doc.kind);return}
    if(!await window.ERWDialog.confirm(`删除“${doc.title}”？文件会移入 Workspace/System/Trash。`))return;
    await api('/api/docs/'+doc.id,{method:'DELETE'});toast('已移入回收目录');state.docSelection.delete(doc.id);state.selectedDoc=null;state.editorBaseline=null;state.dirty=false;await renderDocsPage(doc.kind);
  }
  function routeForKind(k){ return BUILTIN_ROUTE_KIND[k] || ('kind-'+encodeURIComponent(k))}
  async function exportBibtex(){
    const docs=await api('/api/docs?kind=literature');
    modal('批量导出 BibTeX',`<div class="row-meta" style="margin-bottom:10px">默认全选；可取消不需要导出的文献。</div><div class="bundle-list">${docs.map(d=>`<label class="bundle-item"><input type="checkbox" class="bib-select" value="${d.id}" checked><span class="badge">文献</span><span><strong>${esc(d.title)}</strong><br><span class="row-meta">${esc(d.authors||'')} · ${esc(d.year||'')} · ${esc(d.venue||'')}</span></span></label>`).join('')||'<div class="empty">暂无文献</div>'}</div>`,`<button class="secondary-btn" id="bib-cancel">取消</button><button class="primary-btn" id="bib-export-run">导出所选</button>`);
    $('#bib-cancel').onclick=closeModal;$('#bib-export-run').onclick=async()=>{const ids=$$('.bib-select:checked').map(x=>x.value);const res=await api('/api/literature/export-bibtex',{method:'POST',body:{ids}});modal('BibTeX 已导出',`<div class="row-meta">${res.count} 条 · ${esc(res.path)}</div><textarea class="search-input mono" style="height:360px;margin-top:10px">${esc(res.content)}</textarea>`,`<button class="secondary-btn" id="bib-copy">复制</button><button class="primary-btn" id="bib-close">完成</button>`);$('#bib-copy').onclick=()=>copyText(res.content);$('#bib-close').onclick=closeModal;};
  }


  async function renderMilestoneShell(docs,projects){
    state.docs=docs; state.projects=projects;
    if(state.milestoneView==='3d'||state.milestoneView==='fishbone')state.milestoneView='timeline';
    $('#main').innerHTML=`<div class="card card-pad milestone-page-card"><div class="card-head milestone-page-head"><div><h3>里程碑</h3></div><div style="display:flex;gap:7px"><div class="view-tabs"><button data-ms-view="timeline" class="${state.milestoneView==='timeline'?'active':''}">时间轴</button><button data-ms-view="gantt" class="${state.milestoneView==='gantt'?'active':''}">甘特</button><button data-ms-view="list" class="${state.milestoneView==='list'?'active':''}">列表</button><button data-ms-view="docs" class="${state.milestoneView==='docs'?'active':''}">文档</button></div><button class="primary-btn" id="new-ms">＋ 新建</button>${batchModeButton('doc')}</div></div><div id="ms-view"></div></div>`;
    $('#new-ms').onclick=()=>createAndSelect('milestone');
    $$('[data-ms-view]').forEach(b=>b.onclick=async()=>{
      /* v261022.1 · 甘特有未保存的计划修改：切走前先问（与文档编辑同一 guard 习惯） */
      if(state.milestoneView==='gantt'&&window.ERWMilestoneGantt?.guard&&!(await window.ERWMilestoneGantt.guard()))return;
      if(!await guardEditor('切换里程碑视图'))return;state.dirty=false;state.editorBaseline=null;state.draft=null;state.selectedDoc=null;state.milestoneView=b.dataset.msView;renderMilestoneView()}); renderMilestoneView();
  }
  function renderMilestoneView(){
    $$('[data-ms-view]').forEach(b=>b.classList.toggle('active',b.dataset.msView===state.milestoneView));
    const root=$('#ms-view'); if(!root)return;
    window.ERWMilestoneTimeline?.destroy?.();
    window.ERWMilestoneGantt?.destroy?.();
    if(state.milestoneView==='timeline'){
      if(!window.ERWMilestoneTimeline){root.innerHTML='<div class="empty">里程碑时间轴模块未加载</div>';}
      else window.ERWMilestoneTimeline.mount(root,{
        docs:[...state.docs],
        onOpen:(id)=>{state.milestoneView='docs';renderMilestoneView();setTimeout(()=>selectDoc(id),10)},
        onNew:()=>$('#new-ms')?.click()
      });
    }
    else if(state.milestoneView==='gantt'){
      /* v261022.1 · 上游甘特图：按项目分组、阶段条 + 截止节点，数据来自 /api/milestones/plan */
      if(!window.ERWMilestoneGantt){root.innerHTML='<div class="empty">里程碑甘特模块未加载</div>';}
      else window.ERWMilestoneGantt.mount(root,{});
    }
    else if(state.milestoneView==='list'){ root.innerHTML=milestoneTimelineHtml([...state.docs].sort((a,b)=>(a.due||'').localeCompare(b.due||''))); wireMilestoneCards(); }
    else { root.innerHTML=`<div class="docs-layout milestone-docs-layout"><aside class="card doc-list-panel" style="position:relative;top:auto">${selectionToolbar('doc')}<div class="doc-list" id="doc-list">${docItems(state.docs)}</div></aside><section class="card doc-editor empty-editor" id="doc-editor"><div class="empty">选择里程碑文档进行编辑</div></section></div>`; wireDocList('milestone'); }
    if(state.milestoneView!=='docs'){state.docSelectionMode=false;state.docSelection.clear()}
    bindBatchModeButton('doc',state.docs);updateSelection('doc',state.docs);
    animateSubView(root);
  }
  function milestoneTimelineHtml(docs,compact=false){ if(!docs.length)return '<div class="empty">暂无里程碑</div>'; return `<div class="timeline ${compact?'compact':''}">${docs.map(d=>`<div class="timeline-item" data-ms-id="${d.id}"><div class="timeline-date">${fmtDate(d.due)}</div><span class="timeline-dot"></span><div class="timeline-card"><div style="display:flex;justify-content:space-between;gap:10px"><strong>${esc(d.title)}</strong><span class="badge">${esc(d.status||'')}</span></div><div class="row-meta">${esc((d.projects||[]).join(', ')||d.project||'未归属项目')} · ${esc(d.excerpt||'')}</div></div></div>`).join('')}</div>`}
  function wireMilestoneCards(){ $$('[data-ms-id]').forEach(x=>x.onclick=async()=>{state.milestoneView='docs';renderMilestoneView();setTimeout(()=>selectDoc(x.dataset.msId),10)}); }
  function milestone3dHtml(docs){return `<div class="milestone-3d-layout" id="milestone-3d-layout"><div class="timeline-3d" id="timeline-3d"><div class="timeline-3d-controls"><span>拖动空白处平移 · Alt/右键拖动旋转 · 滚轮缩放</span><button class="ghost-btn" type="button" id="timeline-3d-auto">暂停旋转</button><button class="ghost-btn" type="button" id="timeline-3d-reset">复位</button></div><div class="timeline-3d-viewport" id="timeline-3d-viewport"><div class="timeline-3d-axis"></div><div class="timeline-3d-stage" id="timeline-3d-stage">${docs.map((d,i)=>{const angle=i*0.72,x=50+Math.sin(angle)*30,y=10+i*68,z=Math.cos(angle)*160;return `<article class="timeline-3d-card" data-ms-id="${d.id}" style="left:calc(${x}% - 115px);top:${y}px;transform:translateZ(${z}px) rotateY(${-angle*18}deg)"><div class="mono" style="font-size:11px;color:var(--accent)">${fmtDate(d.due)}</div><strong>${esc(d.title)}</strong><div class="row-meta">${esc((d.projects||[]).join(', ')||d.project||'未归属项目')} · ${esc(d.status||'')}</div></article>`}).join('')}</div></div></div><aside class="card milestone-preview hidden" id="milestone-preview"><div class="preview-pane-head"><div><div class="card-kicker">MARKDOWN PREVIEW</div><h3 id="milestone-preview-title">里程碑预览</h3></div><button class="ghost-btn" id="milestone-preview-close" type="button">关闭</button></div><div class="preview-pane-meta" id="milestone-preview-meta"></div><div class="md-preview milestone-preview-body" id="milestone-preview-body"></div><div class="preview-pane-actions"><button class="primary-btn" id="milestone-preview-edit" type="button">打开编辑</button></div></aside></div>`}
  async function showMilestonePreview(id){
    const layout=$('#milestone-3d-layout'),panel=$('#milestone-preview');if(!layout||!panel)return;
    try{
      const doc=await api('/api/docs/'+encodeURIComponent(id));
      layout.classList.add('preview-open');panel.classList.remove('hidden');
      $('#milestone-preview-title').textContent=doc.title||'里程碑';
      $('#milestone-preview-meta').textContent=`${fmtDate(doc.due)} · ${((doc.projects||[]).join(', ')||doc.project||'未归属项目')} · ${doc.status||'—'}`;
      $$('.timeline-3d-card').forEach(x=>x.classList.toggle('selected',x.dataset.msId===id));
      await renderMarkdownInto($('#milestone-preview-body'),doc.body||'');
      $('#milestone-preview-edit').onclick=()=>{state.milestoneView='docs';renderMilestoneView();setTimeout(()=>selectDoc(id),10)};
      $('#milestone-preview-close').onclick=hideMilestonePreview;
    }catch(e){toast('无法读取里程碑：'+e.message,true)}
  }
  function hideMilestonePreview(){const layout=$('#milestone-3d-layout'),panel=$('#milestone-preview');layout?.classList.remove('preview-open');panel?.classList.add('hidden');$$('.timeline-3d-card').forEach(x=>x.classList.remove('selected'))}
  function animateMilestones3D(){
    const stage=$('#timeline-3d-stage'),viewport=$('#timeline-3d-viewport');if(!stage||!viewport)return;
    let rotX=-5,rotY=0,panX=0,panY=0,zoom=-40,raf,drag=null,moved=false,auto=true;
    const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
    const apply=()=>{stage.style.transform=`translate3d(${panX}px,${panY}px,${zoom}px) rotateX(${rotX}deg) rotateY(${rotY}deg)`}; apply();
    const tick=()=>{if(!document.body.contains(stage)){if(raf)cancelAnimationFrame(raf);return}if(auto&&!drag&&!reduce){rotY=(rotY+.035)%360;apply()}raf=requestAnimationFrame(tick)};raf=requestAnimationFrame(tick);
    viewport.oncontextmenu=e=>e.preventDefault();
    viewport.onpointerdown=e=>{if(e.target.closest('.timeline-3d-controls')||e.target.closest('.milestone-preview'))return;drag={x:e.clientX,y:e.clientY,mode:(e.altKey||e.button===2)?'rotate':'pan'};moved=false;viewport.setPointerCapture?.(e.pointerId);viewport.classList.add('dragging')};
    viewport.onpointermove=e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>2)moved=true;if(drag.mode==='rotate'){rotY+=dx*.22;rotX=Math.max(-70,Math.min(70,rotX-dy*.16))}else{panX+=dx;panY+=dy}drag.x=e.clientX;drag.y=e.clientY;apply()};
    viewport.onpointerup=e=>{drag=null;viewport.classList.remove('dragging');try{viewport.releasePointerCapture?.(e.pointerId)}catch{};if(!moved&&!e.target.closest('[data-ms-id]'))hideMilestonePreview()};
    viewport.onwheel=e=>{e.preventDefault();zoom=Math.max(-520,Math.min(240,zoom-e.deltaY*.35));apply()};
    $('#timeline-3d-reset').onclick=()=>{rotX=-5;rotY=0;panX=0;panY=0;zoom=-40;apply()};
    $('#timeline-3d-auto').onclick=e=>{auto=!auto;e.currentTarget.textContent=auto?'暂停旋转':'自动旋转'};
    $$('[data-ms-id]',stage).forEach(x=>x.onclick=async e=>{e.stopPropagation();if(moved){moved=false;return}await showMilestonePreview(x.dataset.msId)});
  }

  /* v261009.18 · 知识图谱**整体由插件提供**（`plugins/knowledge-graph` 经 window.ERWGraphRenderers 注册）。
     内核此前自带一份简易渲染（drawGraph 的螺旋图）＋筛选/选中/预览/导出，用户明确要求去掉那份难看的效果：
     现在内核只问注册表——有接管者就把 #main 交给它的 `mount(host, ctx)`；没有就给一条启用提示。
     相关数据面（`/api/graph`、`/api/graph/bundle` 等）仍在内核，供插件消费。 */
  async function renderGraphPage(){
    const takeover=(()=>{ try{ return window.ERWGraphRenderers.get('graph'); }catch{ return null } })();
    if(takeover && typeof takeover.graph.mount === 'function'){
      try{ await takeover.graph.mount($('#main'), {route:'graph', contract:window.ERWContract}); return }
      catch(err){ console.error('[graph] 插件渲染失败：'+(err&&err.message?err.message:err)); }
    }
    $('#main').innerHTML='<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">RELATION MAP</div><h3>知识图谱</h3></div></div>'
      + '<div class="empty" style="min-height:220px"><div>知识图谱不可用<br><span class="row-meta">请在「设置 → 插件」里启用「知识图谱可视化」插件</span></div></div></div>';
  }

  async function copyText(text){try{await navigator.clipboard.writeText(text);toast('已复制到剪贴板')}catch{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('已复制到剪贴板')}}


  async function renderFolders(){const [tree,info]=await Promise.all([api('/api/workspace/tree'),api('/api/workspace/info')]);
    $('#main').innerHTML=`<div class="workspace-layout"><section class="card tree-panel"><div class="card-head"><div><h3>文件夹</h3></div><button class="secondary-btn" id="tree-refresh">刷新</button></div>${treeHtml(tree)}</section><section class="card card-pad"><div class="card-head"><div><h3>工作目录</h3></div></div><div class="field"><label>当前根目录</label><input readonly value="${esc(info.root)}"></div><div style="margin-top:12px"><button class="primary-btn" id="open-workspace">在系统文件管理器中打开</button> <button class="secondary-btn" id="new-project">新建项目</button> <button class="secondary-btn" id="new-folder">新建文件夹</button></div><div class="section-title"><div><h3>自动结构</h3><p>启动时自动识别、创建必要目录；兼容旧版 data/research_os 等常见目录并进行非破坏式复制迁移。</p></div></div><div class="mono" style="font-size:12px;line-height:1.8">Workspace/<br>├─ Knowledge/{Ideas, Journals, Notes, Milestones, Summaries, Literature, Attachments, Exports}<br>├─ Projects/<br>├─ Resources/<br>└─ System/</div><div class="section-title"><div><h3>迁移状态</h3></div></div><div class="row-meta">${info.migration?.performed_at?`已检查 · ${esc(info.migration.performed_at)} · 发现 ${info.migration.sources_found||0} 个旧数据源 · 本次复制 ${info.migration.copied_count||0} 个文件`:'尚未执行迁移检查'}</div><div style="margin-top:10px"><button class="secondary-btn" id="migration-rescan">重新扫描并迁移</button></div></section></div>`;
    $('#tree-refresh').onclick=renderFolders;$('#open-workspace').onclick=()=>api('/api/workspace/open',{method:'POST',body:{path:''}}).then(()=>toast('已打开 Workspace')).catch(e=>toast(e.message,true));$('#migration-rescan').onclick=async()=>{const r=await api('/api/workspace/migrate',{method:'POST',body:{}});toast(`迁移扫描完成：复制 ${r.copied_count||0} 个文件`);renderFolders()};$('#new-project').onclick=()=>{modal('新建项目工程目录',`<div class="field"><label>项目名称</label><input id="new-project-name" placeholder="请输入你的项目名称"></div><div class="row-meta" style="margin-top:8px">将自动创建 Notes / Experiments / Data / Results / Figures / Manuscript / References。</div>`,`<button class="secondary-btn" id="project-cancel">取消</button><button class="primary-btn" id="project-create">创建</button>`);$('#project-cancel').onclick=closeModal;$('#project-create').onclick=async()=>{const r=await api('/api/workspace/project',{method:'POST',body:{name:$('#new-project-name').value}});toast('项目目录已创建：'+r.path);closeModal();renderFolders()}};$('#new-folder').onclick=()=>{modal('新建 Workspace 文件夹',`<div class="field"><label>相对路径</label><input id="new-folder-path" value="Projects/NewProject" placeholder="Projects/项目名"></div>`,`<button class="secondary-btn" id="folder-cancel">取消</button><button class="primary-btn" id="folder-create">创建</button>`);$('#folder-cancel').onclick=closeModal;$('#folder-create').onclick=async()=>{await api('/api/workspace/folder',{method:'POST',body:{path:$('#new-folder-path').value}});toast('文件夹已创建');closeModal();renderFolders()}};wireTreeOpen();
  }
  function treeHtml(node){const ico=node.type==='dir'?'▱':'·';return `<div class="tree-node"><div class="tree-line"><span>${ico}</span><span class="folder-name" title="${esc(node.path)}">${esc(node.name)}</span>${node.type==='dir'?`<span class="folder-actions"><button data-open-path="${esc(node.path)}">↗</button></span>`:''}</div>${node.children?.length?`<div class="tree-children">${node.children.map(treeHtml).join('')}</div>`:''}</div>`}
  function wireTreeOpen(){$$('[data-open-path]').forEach(b=>b.onclick=e=>{e.stopPropagation();api('/api/workspace/open',{method:'POST',body:{path:b.dataset.openPath}}).catch(x=>toast(x.message,true))})}

  /* v261009.8 · 用量计费已整体搬成插件 plugins/billing（自己 register 面板：导航项 + 标题 + 渲染）；
     内核不再认识它——`web_check` 断言 app.js 里没有计费实现。 */

  async function saveKnowledgeTypes(app,cfg,message='知识条目设置已保存'){
    const saved=await api('/api/config/app',{method:'POST',body:app});
    state.config.app=saved;cfg.app=saved;
    const [types,statuses]=await Promise.all([api('/api/knowledge-types'),api('/api/statuses')]);
    state.knowledgeTypes=Array.isArray(types)?types:[];state.statuses=statuses||{};
    renderSidebar();toast(message);
    return saved;
  }
  /* 内置七类的默认顺序，与侧栏及 core/contracts 的 KIND 顺序一致（实验在里程碑之前）。 */
  const BUILTIN_KIND_ORDER=['idea','journal','note','experiment','milestone','summary','literature'];
  function knowledgeConfig(app){
    const raw=app.knowledge_types&&typeof app.knowledge_types==='object'?app.knowledge_types:{};
    if(!Array.isArray(raw.order))raw.order=[...BUILTIN_KIND_ORDER];
    else{
      /* 旧配置的 order 可能缺后来新增的内置类型（如 experiment）。按默认顺序的相对位置补齐，
         而不是让它在设置页里被当成「额外类型」排到最后。 */
      for(let i=0;i<BUILTIN_KIND_ORDER.length;i++){
        const kind=BUILTIN_KIND_ORDER[i];
        if(raw.order.includes(kind))continue;
        let prev=null;
        for(let j=i-1;j>=0;j--){if(raw.order.includes(BUILTIN_KIND_ORDER[j])){prev=BUILTIN_KIND_ORDER[j];break}}
        raw.order.splice(prev?raw.order.indexOf(prev)+1:0,0,kind);
      }
    }
    if(!Array.isArray(raw.hidden))raw.hidden=[];
    if(!Array.isArray(raw.custom))raw.custom=[];
    if(!raw.templates||typeof raw.templates!=='object'||Array.isArray(raw.templates))raw.templates={};
    app.knowledge_types=raw;return raw;
  }
  function classificationMarksConfig(app){
    if(!Array.isArray(app.classification_marks))app.classification_marks=DEFAULT_KIND_MARKS.map(x=>({...x}));
    return app.classification_marks;
  }
  function openKnowledgeTemplateEditor(app,cfg,row){
    const reg=knowledgeConfig(app);
    const current=String(row.template||'');
    const preset=String(row.default_template||'');
    modal('Markdown 模板 · '+row.label,`
      <div class="row-meta" style="margin-bottom:10px">该模板仅影响以后新建的“${esc(row.label)}”；已有文档正文不会被改写。支持 <code>{{title}}</code>、<code>{{date}}</code>；文献额外支持 <code>{{bibtex}}</code>。</div>
      <textarea id="kt-template-edit" style="width:100%;min-height:360px;font-family:Consolas,monospace">${esc(current)}</textarea>`,
      '<button class="secondary-btn" id="kt-template-reset">还原为预设</button><button class="secondary-btn" id="kt-template-cancel">取消</button><button class="primary-btn" id="kt-template-save">保存模板</button>');
    $('#kt-template-cancel').onclick=closeModal;
    $('#kt-template-reset').onclick=async()=>{
      delete reg.templates[row.id];
      await saveKnowledgeTypes(app,cfg,'已一键还原为预设模板');
      closeModal();renderSettingsTab('knowledge',cfg);
    };
    $('#kt-template-save').onclick=async()=>{
      const value=$('#kt-template-edit').value;
      if(value===preset)delete reg.templates[row.id];
      else reg.templates[row.id]=value;
      await saveKnowledgeTypes(app,cfg,value===preset?'已还原为预设模板':'Markdown 模板已保存');
      closeModal();renderSettingsTab('knowledge',cfg);
    };
  }
  /* v261020 · 分类标记：图标可自由输入（候选一键填入），既能在设置里新建/编辑，也能从条目编辑器“＋ 自定义”直接建。 */
  function markFormHtml(prefix,mark){
    const m=mark||{icon:'◆',label:'',color:'#4a6fa5'};
    const icon=m.icon||'◆';
    const color=m.color||'#4a6fa5';
    return `<div class="form-grid mark-form">
      <div class="field span-2"><label>分类名称</label><input id="${prefix}-label" maxlength="16" value="${esc(m.label||'')}" placeholder="例如：问题"></div>
      <div class="field"><label>颜色</label>
        <label class="mark-color-pick" title="选择颜色">
          <input id="${prefix}-color" type="color" value="${esc(color)}">
          <span class="mcp-dot" id="${prefix}-dot" style="background:${esc(color)}"></span>
          <span class="mcp-hex" id="${prefix}-hex">${esc(color)}</span>
        </label>
      </div>
      <div class="field"><label>预览</label>
        <div class="mark-preview-box"><span class="mark-chip on" id="${prefix}-preview" style="--mark-color:${esc(color)}">${esc(icon)} ${esc(m.label||'预览')}</span></div>
      </div>
      <div class="field span-4"><label>标记图案</label>
        <div class="mark-icon-groups" id="${prefix}-icon-groups">
          ${MARK_ICON_GROUPS.map(g=>`<div class="mig"><span class="mig-name">${esc(g.name)}</span><div class="mig-grid">${g.icons.map(ic=>`<button type="button" data-${prefix}-icon="${esc(ic)}" class="${icon===ic?'on':''}" title="选择 ${esc(ic)}">${esc(ic)}</button>`).join('')}</div></div>`).join('')}
        </div>
        <div class="mark-icon-custom"><input id="${prefix}-icon" maxlength="4" value="${esc(icon)}" placeholder="也可输入其它符号"><span class="field-help">点选上面的图案，或直接输入任意符号 / emoji（最多 4 个字符）。预览随名称、颜色与图案实时变化。</span></div>
      </div>
    </div>`;
  }
  function wireMarkForm(prefix){
    const iconInput=$(`#${prefix}-icon`),labelInput=$(`#${prefix}-label`),colorInput=$(`#${prefix}-color`),preview=$(`#${prefix}-preview`);
    const dot=$(`#${prefix}-dot`),hex=$(`#${prefix}-hex`);
    const syncPreview=()=>{
      const color=colorInput.value||'#4a6fa5';
      if(preview){
        preview.textContent=`${iconInput.value.trim()||'◆'} ${labelInput.value.trim()||'预览'}`;
        preview.style.setProperty('--mark-color',color);
      }
      if(dot)dot.style.background=color;
      if(hex)hex.textContent=color;
    };
    $$(`#${prefix}-icon-groups [data-${prefix}-icon]`).forEach(btn=>btn.onclick=()=>{
      const icon=btn.dataset[prefix+'Icon']||'◆';
      iconInput.value=icon;
      $$(`#${prefix}-icon-groups [data-${prefix}-icon]`).forEach(x=>x.classList.toggle('on',x===btn));
      syncPreview();
    });
    iconInput.addEventListener('input',()=>{
      const icon=iconInput.value.trim();
      $$(`#${prefix}-icon-groups [data-${prefix}-icon]`).forEach(x=>x.classList.toggle('on',x.dataset[prefix+'Icon']===icon));
      syncPreview();
    });
    labelInput.addEventListener('input',syncPreview);
    colorInput.addEventListener('input',syncPreview);
  }
  async function createClassificationMark(fields){
    const app=state.config?.app;
    if(!app)return null;
    const label=String(fields.label||'').trim();
    if(!label){toast('请填写分类名称',true);return null}
    const marks=classificationMarksConfig(app);
    if(marks.some(x=>x.label===label)){toast('该分类名称已存在',true);return null}
    const mark={id:'mark_'+Date.now().toString(36),icon:String(fields.icon||'◆').trim().slice(0,4)||'◆',label,color:fields.color||'#4a6fa5'};
    marks.push(mark);
    await saveKnowledgeTypes(app,state.config,'分类标记已添加');
    return mark;
  }
  async function saveClassificationMark(id,fields,cfg){
    const app=state.config?.app;
    if(!app)return null;
    const marks=classificationMarksConfig(app),idx=marks.findIndex(x=>x.id===id);
    if(idx<0)return null;
    const label=String(fields.label||'').trim();
    if(!label){toast('请填写分类名称',true);return null}
    if(marks.some((x,i)=>i!==idx&&x.label===label)){toast('该分类名称已存在',true);return null}
    marks[idx]={...marks[idx],label,icon:String(fields.icon||'◆').trim().slice(0,4)||'◆',color:fields.color||marks[idx].color};
    await saveKnowledgeTypes(app,cfg||state.config,'分类标记已更新');
    if(state.selectedDoc)refreshMarkChips();
    return marks[idx];
  }
  function openMarkCreator(after){
    modal('新建分类标记',markFormHtml('mk'),
      '<button class="secondary-btn" id="mk-cancel">取消</button><button class="primary-btn" id="mk-save">创建</button>');
    $('#mk-cancel').onclick=closeModal;
    wireMarkForm('mk');
    setTimeout(()=>$('#mk-label')?.focus(),30);
    $('#mk-save').onclick=async()=>{
      const mark=await createClassificationMark({label:$('#mk-label').value,icon:$('#mk-icon').value,color:$('#mk-color').value});
      if(!mark)return;
      closeModal();
      if(typeof after==='function')after(mark);
      toast(`已创建分类“${mark.label}”`);
    };
  }
  function openMarkEditor(mark,cfg,after){
    modal('编辑分类标记',markFormHtml('mk',mark),
      '<button class="secondary-btn" id="mk-cancel">取消</button><button class="primary-btn" id="mk-save">保存</button>');
    $('#mk-cancel').onclick=closeModal;
    wireMarkForm('mk');
    setTimeout(()=>$('#mk-label')?.focus(),30);
    $('#mk-save').onclick=async()=>{
      const saved=await saveClassificationMark(mark.id,{label:$('#mk-label').value,icon:$('#mk-icon').value,color:$('#mk-color').value},cfg);
      if(!saved)return;
      closeModal();
      if(typeof after==='function')after(saved);
      toast('分类标记已更新');
    };
  }
  function markTemplateById(id){
    const catalog=state.markCatalog||{};
    const rows=Array.isArray(catalog.templates)&&catalog.templates.length?catalog.templates:MARK_TEMPLATE_FALLBACK;
    return rows.find(t=>t.id===id)||null;
  }
  function markLimit(){
    return Number((state.markCatalog||{}).limit)||24;
  }
  async function addTemplateMark(app,cfg,id){
    const tpl=markTemplateById(id);
    if(!tpl)return;
    const marks=classificationMarksConfig(app);
    if(marks.length>=markLimit()){toast(`分类标记最多 ${markLimit()} 个，请先删除不用的`,true);return}
    if(marks.some(m=>m.id===tpl.id))return;
    marks.push({id:tpl.id,icon:tpl.icon,label:tpl.label,color:tpl.color});
    await saveKnowledgeTypes(app,cfg,`已添加分类“${tpl.label}”`);
    renderSettingsTab('knowledge',cfg);
  }
  async function addAllTemplateMarks(app,cfg){
    const marks=classificationMarksConfig(app),limit=markLimit();
    const rows=((state.markCatalog||{}).templates)||MARK_TEMPLATE_FALLBACK;
    const remaining=rows.filter(t=>!marks.some(m=>m.id===t.id));
    const room=Math.max(0,limit-marks.length);
    if(!remaining.length){toast('内置模板都已添加');return}
    if(!room){toast(`分类标记最多 ${limit} 个，请先删除不用的`,true);return}
    remaining.slice(0,room).forEach(t=>marks.push({id:t.id,icon:t.icon,label:t.label,color:t.color}));
    await saveKnowledgeTypes(app,cfg,`已添加 ${Math.min(remaining.length,room)} 个内置模板`);
    renderSettingsTab('knowledge',cfg);
  }
  async function deleteClassificationMark(app,cfg,id){
    const marks=classificationMarksConfig(app),mark=marks.find(x=>x.id===id);
    if(!mark)return;
    if(!await window.ERWDialog.confirm(`删除分类“${mark.label}”？所有使用该分类的笔记、灵感、文献等条目将自动清空分类标记。`))return;
    app.classification_marks=marks.filter(x=>x.id!==id);
    await saveKnowledgeTypes(app,cfg,'分类标记已删除');
    const result=await api('/api/knowledge-marks/cleanup',{method:'POST',body:{mark_id:id}});
    toast(`已清空 ${result.updated||0} 个条目的分类标记`);
    renderSettingsTab('knowledge',cfg);
  }

  const KNOWLEDGE_ICON_CHOICES=['✦','◆','◇','●','○','■','□','▲','△','▶','▣','◈','◎','✎','✍','⚑','⚗','☀','☾','★'];

  function openKnowledgeTypeEditor(app,cfg,existing=null){
    const custom=knowledgeConfig(app).custom;
    const item=existing||{id:'',label:'',icon:'◆',statuses:['草稿','进行中','完成','已归档'],template:'# {{title}}\n\n## 要点\n\n\n## 正文\n\n\n## 关联\n'};
    const editing=!!existing;
    modal(editing?'编辑自定义条目类型':'添加自定义条目类型',`
      <div class="form-grid">
        <div class="field"><label>标识 ID</label><input id="kt-id" ${editing?'disabled':''} value="${esc(item.id||'')}" placeholder="experiment"><span class="field-help">仅小写字母、数字、-、_；创建后不可修改。</span></div>
        <div class="field span-2"><label>显示名称</label><input id="kt-label" value="${esc(item.label||'')}" placeholder="实验记录"></div>
        <div class="field span-4"><label>图标</label>
          <div class="mark-icon-pick kt-icon-pick" id="kt-icon-pick">${KNOWLEDGE_ICON_CHOICES.map(ic=>`<button type="button" class="${(item.icon||'◆')===ic?'on':''}" data-kt-icon="${esc(ic)}" title="选择 ${esc(ic)}">${esc(ic)}</button>`).join('')}</div>
          <div class="field-help" style="margin:8px 0 5px">点击候选图标即可选择；也可以在下方输入其它符号。</div>
          <input id="kt-icon" maxlength="4" value="${esc(item.icon||'◆')}" placeholder="可手动输入其它图标">
        </div>
        <div class="field span-4"><label>状态（每行一个，或用逗号分隔）</label><textarea id="kt-statuses" style="min-height:84px">${esc((item.statuses||[]).join('\n'))}</textarea></div>
        <div class="field span-4"><label>该类型预设 Markdown 模板</label><textarea id="kt-template" style="min-height:260px;font-family:Consolas,monospace">${esc(item.template||'')}</textarea><span class="field-help">这是自定义类型的“预设”；实际使用模板仍可在知识条目列表点击“模板”单独覆盖并一键还原。支持 {{title}} 与 {{date}} 占位符。</span></div>
      </div>`,
      '<button class="secondary-btn" id="kt-cancel">取消</button><button class="primary-btn" id="kt-save">保存</button>');
    $('#kt-cancel').onclick=closeModal;
    $$('#kt-icon-pick [data-kt-icon]').forEach(btn=>btn.onclick=()=>{
      const icon=btn.dataset.ktIcon||'◆';
      $('#kt-icon').value=icon;
      $$('#kt-icon-pick [data-kt-icon]').forEach(x=>x.classList.toggle('on',x===btn));
    });
    $('#kt-icon').addEventListener('input',()=>{
      const icon=$('#kt-icon').value.trim();
      $$('#kt-icon-pick [data-kt-icon]').forEach(x=>x.classList.toggle('on',x.dataset.ktIcon===icon));
    });
    $('#kt-save').onclick=async()=>{
      const id=(editing?item.id:$('#kt-id').value.trim().toLowerCase());
      const label=$('#kt-label').value.trim();
      if(!/^[a-z][a-z0-9_-]{0,47}$/.test(id)){toast('ID 需以小写字母开头，只能包含小写字母、数字、-、_',true);return}
      if(['idea','journal','note','experiment','milestone','summary','literature'].includes(id)){toast('该 ID 为内置类型，请换一个',true);return}
      if(!label){toast('请填写显示名称',true);return}
      if(!editing&&custom.some(x=>x.id===id)){toast('该 ID 已存在',true);return}
      const statuses=$('#kt-statuses').value.split(/[\n,，]+/).map(x=>x.trim()).filter(Boolean);
      const next={id,label,icon:$('#kt-icon').value.trim()||'◆',statuses:[...new Set(statuses)].slice(0,12),template:$('#kt-template').value};
      if(editing){const idx=custom.findIndex(x=>x.id===id);if(idx>=0)custom[idx]=next}else{custom.push(next);if(!app.knowledge_types.order.includes(id))app.knowledge_types.order.push(id)}
      await saveKnowledgeTypes(app,cfg,editing?'自定义条目类型已更新':'自定义条目类型已添加');
      closeModal();renderSettingsTab('knowledge',cfg);
    };
  }
  function renderKnowledgeTypesSettings(p,app,cfg){
    const reg=knowledgeConfig(app),rows=state.knowledgeTypes?.length?state.knowledgeTypes:[];
    const ordered=reg.order.map(id=>rows.find(x=>x.id===id)).filter(Boolean);
    const extras=rows.filter(x=>!reg.order.includes(x.id));
    const all=[...ordered,...extras],marks=classificationMarksConfig(app);
    const limit=markLimit();
    const catalog=state.markCatalog||{};
    const templates=Array.isArray(catalog.templates)&&catalog.templates.length?catalog.templates:MARK_TEMPLATE_FALLBACK;
    const remaining=templates.filter(t=>!marks.some(m=>m.id===t.id));
    const atLimit=marks.length>=limit;
    p.innerHTML=`<div class="card-head"><div><h3>研究 · 知识条目</h3><p class="row-meta">这里统一管理条目类型、顺序、显示状态和新建 Markdown 模板。自定义类型共用通用 Markdown 编辑器。</p></div><button class="primary-btn" id="kt-add">＋ 添加自定义条目</button></div>
      <div class="list-stack" id="kt-list">${all.map((x,i)=>`<div class="list-row" data-kt="${esc(x.id)}">
        <div style="font-size:18px;width:24px;text-align:center">${esc(x.icon||'◆')}</div>
        <div class="row-main"><div class="row-title">${esc(x.label)} <span class="badge">${x.builtin?'内置':'自定义'}</span></div><div class="row-meta"><code>${esc(x.id)}</code> · 状态：${esc((x.statuses||[]).join(' / ')||'无')}</div></div>
        <label class="badge" style="gap:5px"><input type="checkbox" data-kt-visible="${esc(x.id)}" ${x.hidden?'':'checked'}>显示</label>
        <button class="secondary-btn" data-kt-template="${esc(x.id)}">模板</button>
        <button class="secondary-btn" data-kt-up="${esc(x.id)}" ${i===0?'disabled':''}>↑</button>
        <button class="secondary-btn" data-kt-down="${esc(x.id)}" ${i===all.length-1?'disabled':''}>↓</button>
        ${x.builtin?'':`<button class="secondary-btn" data-kt-edit="${esc(x.id)}">编辑</button><button class="secondary-btn" data-kt-delete="${esc(x.id)}">删除定义</button>`}
      </div>`).join('')||'<div class="empty">暂无知识条目类型</div>'}</div>
      <div class="field-help" style="margin-top:10px">隐藏不会删除 Markdown 数据；“模板”只影响以后新建的条目，并可一键还原为预设。</div>

      <div class="card-head" style="margin-top:26px"><div><h3>分类标记 <span class="badge">${marks.length}/${limit}</span></h3><p class="row-meta">默认 3 个（知识 / 方法 / 实验）。从下面的<b>内置模板</b>按需添加，或自定义名称、颜色与图标图案；条目编辑器里的「＋ 自定义」也能直接新建。删除分类后，使用该分类的条目会自动清空。</p></div></div>
      <div class="list-stack" id="km-list">${marks.map(m=>`<div class="list-row">
        <div style="font-size:18px;width:28px;text-align:center;color:${esc(m.color)}">${esc(m.icon)}</div>
        <div class="row-main"><div class="row-title">${esc(m.label)}</div><div class="row-meta"><code>${esc(m.id)}</code></div></div>
        <span class="mark-chip" style="--mark-color:${esc(m.color)}">${esc(m.icon)} ${esc(m.label)}</span>
        <button class="secondary-btn" data-km-edit="${esc(m.id)}">编辑</button>
        <button class="secondary-btn" data-km-delete="${esc(m.id)}">删除</button>
      </div>`).join('')||'<div class="empty">暂无分类标记；可从下面的模板添加，或自定义一个。</div>'}</div>

      <div class="section-title" style="margin-top:18px"><div><h3>内置模板</h3><p class="row-meta">点卡片即可添加；添加后仍可在这里编辑图案与颜色。</p></div>${remaining.length?`<button class="secondary-btn" id="km-add-all" ${atLimit?'disabled':''}>全部添加</button>`:''}</div>
      <div class="mark-template-grid" id="km-templates">${remaining.length?remaining.map(t=>`<button type="button" class="mark-template" data-km-tpl="${esc(t.id)}" style="--mark-color:${esc(t.color)}" ${atLimit?'disabled':''} title="${esc(t.hint||t.id)}">
          <span class="mt-icon">${esc(t.icon)}</span>
          <span class="mt-text"><b>${esc(t.label)}</b><small>${esc(t.hint||t.id)}</small></span>
          <span class="mt-add">＋</span>
        </button>`).join(''):'<div class="empty">内置模板都已添加；可在下面自定义新分类。</div>'}</div>
      <div class="mark-custom-row"><button class="primary-btn" id="km-custom" ${atLimit?'disabled':''}>＋ 自定义标记</button><span class="field-help">名称最多 16 字；图标支持任意符号 / emoji；上限 ${limit} 个${atLimit?'（已达上限，请先删除不用的）':''}。</span></div>`;
    $('#kt-add').onclick=()=>openKnowledgeTypeEditor(app,cfg);
    $$('[data-kt-visible]',p).forEach(el=>el.onchange=async()=>{
      const id=el.dataset.ktVisible;const set=new Set(reg.hidden||[]);if(el.checked)set.delete(id);else set.add(id);reg.hidden=[...set];
      await saveKnowledgeTypes(app,cfg,el.checked?'已显示该条目':'已隐藏该条目');renderSettingsTab('knowledge',cfg);
    });
    const move=async(id,delta)=>{
      const order=[...reg.order],i=order.indexOf(id),j=i+delta;if(i<0||j<0||j>=order.length)return;
      [order[i],order[j]]=[order[j],order[i]];reg.order=order;await saveKnowledgeTypes(app,cfg,'排序已保存');renderSettingsTab('knowledge',cfg);
    };
    $$('[data-kt-template]',p).forEach(b=>b.onclick=()=>{const row=all.find(x=>x.id===b.dataset.ktTemplate);if(row)openKnowledgeTemplateEditor(app,cfg,row)});
    $$('[data-kt-up]',p).forEach(b=>b.onclick=()=>move(b.dataset.ktUp,-1));
    $$('[data-kt-down]',p).forEach(b=>b.onclick=()=>move(b.dataset.ktDown,1));
    $$('[data-kt-edit]',p).forEach(b=>b.onclick=()=>openKnowledgeTypeEditor(app,cfg,reg.custom.find(x=>x.id===b.dataset.ktEdit)));
    $$('[data-kt-delete]',p).forEach(b=>b.onclick=async()=>{
      const id=b.dataset.ktDelete,label=knowledgeType(id)?.label||id,docs=await api('/api/docs?kind='+encodeURIComponent(id));
      if(docs.length){toast(`“${label}”已有 ${docs.length} 条或更多文档，不能删除定义；请改为隐藏。`,true);return}
      if(!await window.ERWDialog.confirm(`删除自定义条目类型“${label}”的定义？空目录会保留，现有其它数据不受影响。`))return;
      reg.custom=reg.custom.filter(x=>x.id!==id);reg.order=reg.order.filter(x=>x!==id);reg.hidden=reg.hidden.filter(x=>x!==id);delete reg.templates[id];
      await saveKnowledgeTypes(app,cfg,'自定义条目类型定义已删除');renderSettingsTab('knowledge',cfg);
    });
    $$('[data-km-tpl]',p).forEach(b=>b.onclick=()=>addTemplateMark(app,cfg,b.dataset.kmTpl));
    const kmAddAll=$('#km-add-all');if(kmAddAll)kmAddAll.onclick=()=>addAllTemplateMarks(app,cfg);
    const kmCustom=$('#km-custom');if(kmCustom)kmCustom.onclick=()=>openMarkCreator(()=>renderSettingsTab('knowledge',cfg));
    $$('[data-km-edit]',p).forEach(b=>b.onclick=()=>{
      const mark=marks.find(x=>x.id===b.dataset.kmEdit);
      if(mark)openMarkEditor(mark,cfg,()=>renderSettingsTab('knowledge',cfg));
    });
    $$('[data-km-delete]',p).forEach(b=>b.onclick=()=>deleteClassificationMark(app,cfg,b.dataset.kmDelete));
  }
  async function renderDesktopSettings(panel){
    panel.innerHTML='<div class="empty">读取窗口设置…</div>';
    try{
      const preferences=await window.pywebview.api.desktop_get_state();
      if(!panel.isConnected||!$('[data-set-tab="desktop"].active'))return;
      panel.innerHTML=`<div class="card-head"><div><h3>窗口与后台运行</h3><p class="row-meta">选择点击标题栏“关闭”按钮时的行为。</p></div></div><div class="form-grid"><div class="field span-2"><label for="desktop-close-action">点击关闭按钮时</label><select id="desktop-close-action"><option value="tray" ${preferences.close_action!=='quit'?'selected':''}>最小化到系统托盘，继续后台运行</option><option value="quit" ${preferences.close_action==='quit'?'selected':''}>退出应用</option></select><span class="field-help">同样适用于 Alt+F4。选择退出时，有未保存的 Markdown 会先询问确认。</span></div><div class="field span-4"><span class="field-help">标题栏的最小化按钮会缩到 Windows 任务栏。托盘右键菜单始终提供“打开科研工作台”和“退出”；最大化保留 Windows 任务栏。</span></div></div><div style="margin-top:14px"><button class="primary-btn" id="desktop-settings-save">保存窗口设置</button><span class="field-help" id="desktop-settings-feedback" role="status"></span></div>`;
      $('#desktop-settings-save').onclick=async()=>{
        const button=$('#desktop-settings-save');button.disabled=true;
        try{const saved=await window.pywebview.api.desktop_set_close_action($('#desktop-close-action').value);window.dispatchEvent(new CustomEvent('workbench:window-state',{detail:saved}));$('#desktop-settings-feedback').textContent='已保存，立即生效';toast('窗口设置已保存')}
        catch(error){toast('保存窗口设置失败：'+error.message,true)}
        finally{if(button.isConnected)button.disabled=false}
      };
    }catch(error){if(panel.isConnected)panel.textContent='读取窗口设置失败：'+error.message}
  }
  async function renderSettings(){
    const [cfg,markCatalog]=await Promise.all([api('/api/config'),api('/api/knowledge-marks').catch(()=>null)]);
    state.config=cfg;if(markCatalog)state.markCatalog=markCatalog;
    /* v261009.4 · 设置页 tab 由两部分组成：内核自带 + **模块自登记**（ERWPanels.settingsTab）。
       这样「插件管理」这类页面不必在 app.js 里加分支——内核不认识具体功能（§6.3）。 */
    const extra=window.ERWPanels.settingsTabs();
    $('#main').innerHTML=`<div class="settings-layout"><aside class="card settings-nav"><button class="active" data-set-tab="general">基础</button><button data-set-tab="knowledge">知识条目</button><button data-set-tab="service">服务与存储</button><button data-set-tab="sync">同步</button><button data-set-tab="literature">文献 / PDF</button><button data-set-tab="academic">学业与目标</button><button data-set-tab="llm">Agent / LLM</button><button data-set-tab="ai">AI 能力</button><button data-set-tab="rag">RAG</button><button data-set-tab="interface">界面</button>`
      +extra.map(t=>`<button data-set-tab="${esc(t.id)}">${esc(t.label)}</button>`).join('')
      +`</aside><section class="card settings-panel" id="settings-panel"></section></div>`;
    if(window.pywebview?.api?.desktop_set_close_action){const button=document.createElement('button');button.dataset.setTab='desktop';button.textContent='窗口';$('.settings-nav').append(button)}
    $$('[data-set-tab]').forEach(b=>b.onclick=()=>{
      $$('[data-set-tab]').forEach(x=>x.classList.toggle('active',x===b));
      const tab=window.ERWPanels.settingsTabs().find(t=>t.id===b.dataset.setTab);
      const p=$('#settings-panel');
      /* v261021.2 · 设置内容改为面板内部滚动：切 tab 时回到顶部，避免停在上一页的滚动位置 */
      p.scrollTop=0;
      /* v261009.22 · 插件自登记的设置 tab 也带 data-plugin=<id>（与导航页、槽位一致）；内核 tab 清掉 */
      if(tab){p.innerHTML='';p.dataset.plugin=tab.id;try{tab.render(p)}catch(e){p.innerHTML=`<div class="rss-alert danger"><strong>该设置页渲染失败</strong><span>${esc(e.message)}</span></div>`}}
      else {delete p.dataset.plugin; renderSettingsTab(b.dataset.setTab,cfg);}
    });renderSettingsTab('general',cfg);
  }
  function renderSettingsTab(tab,cfg){const p=$('#settings-panel'),app=cfg.app;if(tab==='ai'){
      /* v261022.3 · AI 能力（RAG / 记忆 / Skill 总开关）由 agent-system.js 自渲染 */
      if(window.ERWAgentSystem?.renderCapabilities)window.ERWAgentSystem.renderCapabilities(p);
      else p.innerHTML='<div class="empty">Agent 系统模块未加载</div>';
      return;
    }
    if(tab==='rag'){
      if(window.ERWAgentSystem?.renderRag)window.ERWAgentSystem.renderRag(p);
      else p.innerHTML='<div class="empty">Agent 系统模块未加载</div>';
      return;
    }
    if(tab==='sync'){
      /* v261022.2 · 同步页由 sync.js 自渲染（它只依赖 window.ERWSyncUI 适配层） */
      if(window.ERWSync?.renderSettings)window.ERWSync.renderSettings(p);
      else p.innerHTML='<div class="empty">同步模块未加载</div>';
      return;
    }
    if(tab==='general'){
      p.innerHTML=`<div class="card-head"><div><h3>基础设置</h3></div></div><div class="form-grid"><div class="field span-2"><label>工作台名称</label><input id="set-app-name" value="${esc(app.app_name)}"></div><div class="field span-2"><label>副标题</label><input id="set-subtitle" value="${esc(app.subtitle)}"></div></div><div class="field-help" style="margin-top:10px">运行端口、监听地址、Workspace 路径和启动行为已移动到“服务与存储”，均可在页面中配置。</div><div style="margin-top:14px"><button class="primary-btn" id="save-settings">保存</button></div>`;$('#save-settings').onclick=async()=>{app.app_name=$('#set-app-name').value.trim()||'科研工作台';app.subtitle=$('#set-subtitle').value.trim();const saved=await api('/api/config/app',{method:'POST',body:app});state.config.app=saved;cfg.app=saved;toast('基础设置已保存');await loadBootstrap();};
    }
    else if(tab==='knowledge'){renderKnowledgeTypesSettings(p,app,cfg);}
    else if(tab==='desktop'){renderDesktopSettings(p);}
    else if(tab==='service'){
      const mig=app.workspace_migration||{};
      p.innerHTML=`<div class="card-head"><div><h3>服务与存储</h3><p class="row-meta">这些参数直接对应 config/app.json 中的运行与 Workspace 配置。</p></div><span class="badge warn">Host / Port 修改后需快速重启</span></div><div class="form-grid"><div class="field span-2"><label>监听地址 Host</label><input id="svc-host" value="${esc(app.host||'127.0.0.1')}" placeholder="127.0.0.1"><span class="field-help">仅本机使用建议 127.0.0.1；局域网访问可配置 0.0.0.0，并自行确认防火墙安全。</span></div><div class="field"><label>端口 Port</label><input id="svc-port" type="number" min="1" max="65535" value="${Number(app.port||8765)}"></div><div class="field"><label>启动时打开浏览器</label><select id="svc-browser"><option value="1" ${app.auto_open_browser!==false?'selected':''}>是</option><option value="0" ${app.auto_open_browser===false?'selected':''}>否 / 静默启动</option></select></div><div class="field span-4"><label>Workspace 路径</label><input id="svc-workspace" value="${esc(app.workspace||'Workspace')}" placeholder="Workspace"><span class="field-help">支持项目相对路径或绝对路径。修改后后续数据读写会使用新目录；建议修改前先备份 Workspace。</span></div><div class="field"><label>旧数据自动识别</label><select id="svc-migrate"><option value="1" ${mig.enabled!==false?'selected':''}>启用</option><option value="0" ${mig.enabled===false?'selected':''}>关闭</option></select></div><div class="field"><label>迁移时复制旧数据</label><select id="svc-copy"><option value="1" ${mig.copy_legacy_data!==false?'selected':''}>复制（非破坏）</option><option value="0" ${mig.copy_legacy_data===false?'selected':''}>仅识别</option></select></div></div><div style="margin-top:14px;display:flex;gap:8px"><button class="primary-btn" id="svc-save">保存服务与存储设置</button><button class="secondary-btn" id="svc-restart">保存后快速重启</button></div>`;
      const collect=async()=>{const newWs=$('#svc-workspace').value.trim()||'Workspace';if(newWs!==String(app.workspace||'Workspace')&&!await window.ERWDialog.confirm(`Workspace 将从“${app.workspace||'Workspace'}”切换到“${newWs}”。确定保存吗？`))return null;app.host=$('#svc-host').value.trim()||'127.0.0.1';app.port=Math.max(1,Math.min(65535,+$('#svc-port').value||8765));app.auto_open_browser=$('#svc-browser').value==='1';app.workspace=newWs;app.workspace_migration={...mig,enabled:$('#svc-migrate').value==='1',copy_legacy_data:$('#svc-copy').value==='1'};return app};
      $('#svc-save').onclick=async()=>{const data=await collect();if(!data)return;const saved=await api('/api/config/app',{method:'POST',body:data});state.config.app=saved;cfg.app=saved;toast('服务与存储设置已保存；Host / Port 修改需重启生效')};
      $('#svc-restart').onclick=async()=>{const data=await collect();if(!data)return;await api('/api/config/app',{method:'POST',body:data});systemAction('restart')};
    }
    else if(tab==='academic'){
      const ac=app.academic_profile||{}; const conditions=Array.isArray(ac.graduation_conditions)?ac.graduation_conditions:[];
      p.innerHTML=`<div class="card-head"><div><h3>学业周期与毕业目标</h3></div><span class="badge accent">用于概览仪表盘</span></div>
      <div class="form-grid"><div class="field span-2"><label>进度卡片名称</label><input id="ac-degree" value="${esc(ac.degree_name||'博士进度')}" placeholder="例如：博士进度"></div><div class="field"><label>开始日期</label><input id="ac-start" type="date" value="${esc(ac.start_date||'')}"></div><div class="field"><label>预计完成日期</label><input id="ac-end" type="date" value="${esc(ac.expected_end_date||'')}"></div><div class="field"><label>每周活跃目标</label><input id="ac-weekly" type="number" min="1" max="7" value="${Number(ac.weekly_goal_days||5)}"><span class="field-help">用于概览中的科研节奏卡片。</span></div></div>
      <div class="section-title"><div><h3>毕业条件</h3><p>完全自定义，不预设学校要求。可用于论文、会议、专利、资格考试、学位论文阶段等。</p></div><button class="secondary-btn" id="condition-add">＋ 添加条件</button></div>
      <div class="condition-editor-head"><span>条件名称</span><span>当前</span><span>目标</span><span>单位</span><span></span></div><div id="condition-editor">${conditions.map(conditionEditRow).join('')}</div>
      <div style="margin-top:16px"><button class="primary-btn" id="academic-save">保存学业与目标</button></div>`;
      const wire=()=>$$('[data-cond-del]').forEach(b=>b.onclick=()=>b.closest('.condition-edit-row').remove()); wire();
      $('#condition-add').onclick=()=>{$('#condition-editor').insertAdjacentHTML('beforeend',conditionEditRow({label:'',current:0,target:1,unit:''}));wire();};
      $('#academic-save').onclick=async()=>{const graduation_conditions=$$('.condition-edit-row').map(r=>({label:$('[data-cond-label]',r).value.trim(),current:+$('[data-cond-current]',r).value||0,target:+$('[data-cond-target]',r).value||0,unit:$('[data-cond-unit]',r).value.trim()})).filter(x=>x.label);app.academic_profile={...ac,degree_name:$('#ac-degree').value.trim()||'学业进度',start_date:$('#ac-start').value,expected_end_date:$('#ac-end').value,weekly_goal_days:Math.max(1,Math.min(7,+$('#ac-weekly').value||5)),graduation_conditions};await api('/api/config/app',{method:'POST',body:app});state.config.app=app;toast('学业与毕业目标已保存');};
    }
    else if(tab==='llm'){const llm=app.llm||{};const fallbackPresets=[{id:'default',label:'默认（不附加参数）',params:{}},{id:'qwen-low',label:'Qwen · 低思考',params:{enable_thinking:true,thinking_budget:1024}},{id:'qwen-off',label:'Qwen · 无思考',params:{enable_thinking:false}}];const presets=Array.isArray(llm.request_presets)&&llm.request_presets.length?llm.request_presets:fallbackPresets;const presetText=JSON.stringify(presets,null,2);p.innerHTML=`<div class="card-head"><div><h3>Agent 与模型接口</h3><p class="row-meta">API Key 不写入工作台配置、不会上传 git。推荐填入本地私密文件 config/secrets.json（自动注入环境变量，保存后自动生效），或直接设置系统环境变量。</p></div><span class="badge ${llm.has_api_key?'accent':'warn'}">${llm.has_api_key?'环境变量已读取':'环境变量未设置'}</span></div><div class="form-grid"><div class="field"><label>接口名称</label><input id="llm-provider" value="${esc(llm.provider_label||'OpenAI-compatible')}" placeholder="OpenAI-compatible"></div><div class="field"><label>启用 Agent</label><select id="llm-enabled"><option value="1" ${llm.enabled?'selected':''}>启用</option><option value="0" ${!llm.enabled?'selected':''}>关闭</option></select></div><div class="field"><label>协议</label><select id="llm-protocol"><option value="chat_completions" ${llm.protocol!=='responses'?'selected':''}>OpenAI-compatible Chat Completions</option><option value="responses" ${llm.protocol==='responses'?'selected':''}>OpenAI Responses API</option></select></div><div class="field span-2"><label>Base URL</label><input id="llm-base" value="${esc(llm.base_url||'https://api.openai.com/v1')}" placeholder="https://api.openai.com/v1"></div><div class="field span-2"><label>API Key 环境变量名称</label><input id="llm-key-env" value="${esc(llm.api_key_env||'OPENAI_API_KEY')}" placeholder="OPENAI_API_KEY"><span class="field-help">推荐把密钥填入项目 config/secrets.json 的 env 对象（本地私密、不上传 git，保存后自动生效）；也可以在启动工作台前设置系统环境变量。工作台不会读取后写回 Key。</span></div><div class="field span-2"><label>模型</label><input id="llm-model" value="${esc(llm.model||'')}" placeholder="模型 ID"></div><div class="field"><label>显示模型思考过程</label><select id="llm-show-reasoning"><option value="1" ${llm.show_reasoning!==false?'selected':''}>显示（接口返回时）</option><option value="0" ${llm.show_reasoning===false?'selected':''}>隐藏</option></select></div><div class="field"><label>多模态 / 截图识别</label><select id="llm-vision"><option value="1" ${llm.vision_enabled?'selected':''}>开启</option><option value="0" ${!llm.vision_enabled?'selected':''}>关闭</option></select><span class="field-help">需模型支持图片输入（如 qwen-vl / gpt-4o 系列）。开启后 PDF 阅读区 AI 面板可用「截取当前页 / 框选区域」代替选中文本，公式与表格提取更准。</span></div><div class="field"><label>超时 / 秒</label><input id="llm-timeout" type="number" min="5" max="600" value="${Number(llm.timeout||120)}"></div><div class="field"><label>最大输出 tokens（可选）</label><input id="llm-max" type="number" min="0" value="${Number(llm.max_output_tokens||0)}" placeholder="0 = 使用模型默认"></div><div class="field"><label>Temperature（可选）</label><input id="llm-temp" type="number" min="0" max="2" step="0.1" value="${llm.temperature==null?'':Number(llm.temperature)}" placeholder="留空 = 不发送"></div><div class="field"><label>默认请求模式 ID</label><input id="llm-default-preset" value="${esc(llm.default_request_preset||presets[0].id||'default')}" placeholder="default"></div><div class="field span-4"><label>动态请求模式（JSON）</label><textarea id="llm-presets" class="mono" style="min-height:280px">${esc(presetText)}</textarea><span class="field-help">默认提供“默认 / Qwen 低思考 / Qwen 无思考”三套。params 会合并到请求 JSON；可按实际接口修改 enable_thinking、thinking_budget、reasoning_effort 等字段。</span></div><div class="field span-4"><label>系统提示词</label><textarea id="llm-system" style="min-height:130px">${esc(llm.system_prompt||'')}</textarea></div></div><div style="margin-top:14px;display:flex;gap:8px"><button class="primary-btn" id="llm-save">保存模型设置</button><button class="secondary-btn" id="llm-test">测试连接</button></div>`;$('#llm-save').onclick=async()=>{let requestPresets;try{requestPresets=JSON.parse($('#llm-presets').value);if(!Array.isArray(requestPresets)||!requestPresets.length)throw new Error('必须是非空 JSON 数组');const ids=new Set();for(const item of requestPresets){if(!item||typeof item!=='object'||!String(item.id||'').trim()||typeof item.params!=='object'||Array.isArray(item.params))throw new Error('每项必须包含 id、label 和 params 对象');if(ids.has(item.id))throw new Error('预设 id 不能重复：'+item.id);ids.add(item.id)}}catch(e){toast('请求模式 JSON 无效：'+e.message,true);return}app.llm={...llm,provider_label:$('#llm-provider').value.trim()||'OpenAI-compatible',enabled:$('#llm-enabled').value==='1',protocol:$('#llm-protocol').value,base_url:$('#llm-base').value.trim(),api_key_env:$('#llm-key-env').value.trim()||'OPENAI_API_KEY',show_reasoning:$('#llm-show-reasoning').value==='1',vision_enabled:$('#llm-vision').value==='1',model:$('#llm-model').value.trim(),timeout:Math.max(5,Math.min(600,+$('#llm-timeout').value||120)),max_output_tokens:Math.max(0,+$('#llm-max').value||0),temperature:$('#llm-temp').value.trim()===''?null:Math.max(0,Math.min(2,+$('#llm-temp').value||0)),default_request_preset:$('#llm-default-preset').value.trim()||requestPresets[0].id,request_presets:requestPresets,system_prompt:$('#llm-system').value};delete app.llm.api_key;delete app.llm.has_api_key;const saved=await api('/api/config/app',{method:'POST',body:app});state.config.app=saved;cfg.app=saved;state.agentPreset=saved.llm?.default_request_preset||requestPresets[0].id;localStorage.setItem('agentRequestPreset',state.agentPreset);toast('Agent / LLM 设置已保存；API Key 将从环境变量读取')};$('#llm-test').onclick=async()=>{try{$('#llm-test').disabled=true;const r=await api('/api/agent/test',{method:'POST',body:{}});toast(r.models?.length?`连接成功 · ${r.models.slice(0,3).join(' / ')}`:'连接成功')}catch(e){toast(e.message,true)}finally{$('#llm-test').disabled=false}};}
    else if(tab==='literature'){renderLiteratureSettings(p);return}
    else {const ui=app.ui||{};const pins=new Set(ui.sidebar_pinned_groups||[]);p.innerHTML=`<div class="card-head"><div><h3>界面设置</h3></div></div><div class="form-grid cols-5"><div class="field"><label>默认主题</label><select id="ui-theme"><option value="light" ${ui.theme==='light'?'selected':''}>明亮</option><option value="dark" ${ui.theme==='dark'?'selected':''}>深色</option></select></div><div class="field"><label>里程碑默认视图</label><select id="ui-ms"><option value="timeline">时间轴</option><option value="gantt" ${ui.milestone_default_view==='gantt'?'selected':''}>甘特图</option><option value="list" ${ui.milestone_default_view==='list'?'selected':''}>列表</option><option value="docs" ${ui.milestone_default_view==='docs'?'selected':''}>文档</option></select></div><div class="field"><label>动画</label><select id="ui-anim"><option value="1" ${ui.animations!==false?'selected':''}>启用</option><option value="0" ${ui.animations===false?'selected':''}>关闭</option></select></div><div class="field"><label>科研热力图月份</label><select id="ui-heatmap">${(()=>{const hm=Number(ui.heatmap_months||12);const cs=HEATMAP_MONTH_OPTIONS.includes(hm)?HEATMAP_MONTH_OPTIONS:[...HEATMAP_MONTH_OPTIONS,hm].sort((a,b)=>a-b);return cs.map(n=>`<option value="${n}" ${hm===n?'selected':''}>近 ${n} 个月</option>`).join('')})()}</select></div><div class="field span-2"><label>热力图活动量分界</label><div class="heatmap-settings-thresholds"><input id="ui-heatmap-threshold-low" type="number" min="1" value="${Number((ui.heatmap_thresholds||state.heatmapThresholds||[1,3])[0]||1)}"><span>低 / 中</span><input id="ui-heatmap-threshold-mid" type="number" min="2" value="${Number((ui.heatmap_thresholds||state.heatmapThresholds||[1,3])[1]||3)}"><span>中 / 高</span></div><span class="field-help">低：1～第一阈值；中：第一阈值+1～第二阈值；高：超过第二阈值。</span></div><div class="field span-2"><label>热力图三档颜色</label><div class="heatmap-settings-colors">${(ui.heatmap_colors||state.heatmapColors||['#C9D4F7','#8297E5','#4059B8']).map((x,i)=>`<label><span>${['低','中','高'][i]}</span><input id="ui-heatmap-color-${i}" type="color" value="${esc(x)}"></label>`).join('')}</div></div><div class="field span-4"><label>侧栏默认常驻展开</label><div class="check-grid">${NAV_GROUPS.map(g=>`<label><input type="checkbox" data-pin-default value="${g.id}" ${pins.has(g.id)?'checked':''}> ${g.label}</label>`).join('')}</div><span class="field-help">侧栏中仍可随时用菱形按钮单独固定；这里决定首次使用或重置后的默认状态。</span></div></div><div style="margin-top:14px"><button class="primary-btn" id="ui-save">保存界面设置</button> <button class="secondary-btn" id="ui-reset-sidebar">应用默认侧栏状态</button></div>`;$('#ui-save').onclick=async()=>{app.ui={...ui,theme:$('#ui-theme').value,milestone_default_view:$('#ui-ms').value,graph_default_view:'2d',animations:$('#ui-anim').value==='1',heatmap_months:Math.max(1,Math.min(12,+$('#ui-heatmap').value||12)),heatmap_thresholds:[Math.max(1,Math.round(+$('#ui-heatmap-threshold-low').value||1)),Math.max(Math.max(1,Math.round(+$('#ui-heatmap-threshold-low').value||1))+1,Math.round(+$('#ui-heatmap-threshold-mid').value||3))],heatmap_colors:[0,1,2].map(i=>$('#ui-heatmap-color-'+i).value),sidebar_pinned_groups:$$('[data-pin-default]:checked').map(x=>x.value)};state.heatmapMonths=app.ui.heatmap_months;state.heatmapThresholds=app.ui.heatmap_thresholds||[1,3];state.heatmapColors=app.ui.heatmap_colors||['#C9D4F7','#8297E5','#4059B8'];localStorage.setItem('heatmapMonths',String(state.heatmapMonths));localStorage.setItem('heatmapThresholds',JSON.stringify(state.heatmapThresholds));localStorage.setItem('heatmapColors',JSON.stringify(state.heatmapColors));await api('/api/config/app',{method:'POST',body:app});state.config.app=app;applyTheme(app.ui.theme);toast('界面设置已保存')};$('#ui-reset-sidebar').onclick=()=>{state.sidebarPinned=new Set($$('[data-pin-default]:checked').map(x=>x.value));state.sidebarOpen=new Set([...state.sidebarPinned,'core']);saveSidebarState();renderSidebar();toast('已应用默认侧栏状态')};}
  }
  /* v260929 · 设置 · 文献 / PDF：PDF 存放路径查看/修改/迁移、打开文件夹、重建关联入口 + AI 阅读助手（启用/请求模式/目标语言/风格指令/输入上限） */
  /* v260929x · 预设动作内置提示词（与 agent.py _ASSIST_PROMPTS 同源，仅作占位提示与「恢复默认」参照；实际默认以后端为准） */
  const LIT_PROMPT_DEFAULTS={
    translate:'你是科研文献翻译助手。将用户提供的学术内容准确翻译为目标语言：专业术语首次出现时在括号内保留原文；公式、变量、单位、人名保持原样。只输出译文本身，不要任何解释或原文重复。',
    summarize:'你是科研文献阅读助手。用中文对用户提供的内容做要点总结：提炼核心观点、方法与结论，输出为简洁的 Markdown 列表；只依据给定内容，不得编造其中不存在的信息。',
    organize:'你是科研知识整理助手。把用户提供的内容整理为结构化中文知识笔记（Markdown 分节）：核心要点、关键术语、方法/数据、可引用结论；条目化并保留关键数字与公式；只依据给定内容，不得编造。',
    polish:'你是科研笔记编辑助手。整理润色用户提供的文献笔记（Markdown）：统一为清晰的结构（如 摘要/要点/方法/结论/摘录），修正错别字与冗余表达；必须保留用户笔记中的全部原有信息，不得删改实质内容，不得添加虚构内容。'
  };
  /* v260929b · 自定义 AI 动作编辑行：名称 + 提示词 + 删除；id 藏在隐藏域，保存时保持稳定 */
  function litCaRow(x={}){return `<div class="lit-ca-row" data-ca-row><input type="hidden" data-ca-id value="${esc(x.id||'')}"><input class="search-input" data-ca-name value="${esc(x.name||'')}" placeholder="动作名称（如：提取公式）" style="max-width:200px"><textarea class="search-input" data-ca-prompt rows="2" style="min-height:52px" placeholder="提示词：写明任务要求与输出格式，如「提取选文中的全部公式，逐条给出 LaTeX 与一句说明」">${esc(x.prompt||'')}</textarea><button class="ghost-btn danger" type="button" data-ca-del>删除</button></div>`}
  async function renderLiteratureSettings(p){
    let st={pdf_dir:'',is_default:true,file_count:0,total_bytes:0,note_images_dir:'',note_images_is_default:true,note_images_count:0};
    try{st=await api('/api/literature/storage')}catch(e){}
    const mb=((st.total_bytes||0)/1048576).toFixed(1);
    const llm=state.config?.app?.llm||{},as=llm.assist||{};
    const presets=Array.isArray(llm.request_presets)&&llm.request_presets.length?llm.request_presets:[{id:'',label:'默认（不附加参数）'}];
    const selPreset=as.request_preset&&presets.some(x=>x.id===as.request_preset)?as.request_preset:(presets[0]?.id||'');
    const tempOv=as.temperature_override==null?'':Number(as.temperature_override);
    p.innerHTML=`<div class="card-head"><div><h3>文献 PDF 附件</h3><p class="row-meta">PDF 附件统一存放在下方目录；阅读工作区、附件登记与重建关联都以此为基准。批注、笔记与索引仍保存在 Workspace 的 Knowledge/Literature 下，不受此路径影响。</p></div><span class="badge ${st.is_default?'':'accent'}">${st.is_default?'默认路径':'自定义路径'}</span></div>
    <div class="form-grid"><div class="field span-4"><label>当前 PDF 存放路径</label><input value="${esc(st.pdf_dir||'')}" readonly><span class="field-help">现有 PDF：${st.file_count||0} 个 · 共 ${mb} MB${st.is_default?' · 默认目录 Workspace/Knowledge/Literature/PDF':''}</span></div>
    <div class="field span-4"><label>新的存放路径</label><input id="lit-pdf-dir" placeholder="例如 D:\\Papers\\PDF（绝对路径）或 Knowledge/Literature/PDF（相对 Workspace）"><span class="field-help">支持 Workspace 内相对路径或任意绝对路径；目录不存在会自动创建。留空保存 = 恢复默认目录。</span></div>
    <div class="field span-4"><label class="field-check-label"><input type="checkbox" id="lit-pdf-move" checked> 保存时迁移现有 PDF 到新目录，并回写文献条目的附件指向</label><span class="field-help">按上方「新的存放路径」执行迁移；Workspace 内为移动，外部路径保留原件复制。</span></div>
    <div class="field span-4"><label>笔记图片存放目录（批注截图入笔记 / 笔记插图）</label><input id="lit-noteimg-dir" value="${esc(st.note_images_dir||'')}" placeholder="例如 Knowledge/Literature/Images（相对 Workspace）或 D:\\Notes\\Images"><span class="field-help">阅读区「批注加入笔记」与笔记「插入图片」上传的图片统一存到这里；支持 Workspace 相对路径或任意绝对路径，仅影响之后上传的图片（现有 ${st.note_images_count||0} 张不迁移）。留空 = 默认 Workspace/Knowledge/Literature/Images。</span></div></div>
    <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap"><button class="primary-btn" id="lit-pdf-save">保存并应用</button><button class="secondary-btn" id="lit-noteimg-save">保存图片目录</button><button class="secondary-btn" id="lit-pdf-open">打开 PDF 文件夹</button><button class="secondary-btn" id="lit-pdf-rebuild" title="以文献条目为准，补齐 PDF 工作区关联与登记">重建关联</button></div>
    <p class="field-help" style="margin-top:8px">重建关联：以文献条目的附件记录为准，把未登记的 PDF 迁入上方存放目录统一保管（Workspace 内为移动，外部路径保留原件复制），并补齐「条目 ↔ PDF」双向关联；幂等可重复执行，批注与笔记不受影响。</p>
    <div class="section-title" style="margin-top:22px"><div><h3>AI 阅读助手</h3><p>控制 PDF 阅读区的选中文本 AI 处理（翻译 / 总结 / 整理 / 笔记润色 / 自定义指令）。模型接口沿用「Agent / LLM」中启用的配置，此处仅调整阅读场景的行为参数。</p></div><span class="badge ${as.enabled===false?'warn':'accent'}">${as.enabled===false?'已关闭':'已启用'}</span></div>
    <div class="form-grid">
    <div class="field"><label>启用 AI 阅读助手</label><select id="lit-ai-enabled"><option value="1" ${as.enabled!==false?'selected':''}>启用</option><option value="0" ${as.enabled===false?'selected':''}>关闭</option></select></div>
    <div class="field span-2"><label>请求模式</label><select id="lit-ai-preset">${presets.map(x=>`<option value="${esc(x.id)}" ${selPreset===x.id?'selected':''}>${esc(x.label||x.id)}${x.model?' · '+esc(x.model):''}</option>`).join('')}</select><span class="field-help">请求模式 = 一套模型 + 参数组合，在「Agent / LLM」中维护；未另行选择时默认使用列表第一个请求模式。</span></div>
    <div class="field"><label>翻译目标语言</label><input id="lit-ai-lang" value="${esc(as.target_language||'中文')}" placeholder="中文"><span class="field-help">作用于工具栏「AI 翻译」。</span></div>
    <div class="field span-2"><label>模型覆盖（可选）</label><input id="lit-ai-model" value="${esc(as.model_override||'')}" placeholder="留空 = 使用所选请求模式的模型"><span class="field-help">填写模型 ID 后无视所选请求模式的模型，直接使用它（例如换用更快的模型做翻译）。</span></div>
    <div class="field"><label>Temperature 覆盖（可选）</label><input id="lit-ai-temp" type="number" min="0" max="2" step="0.1" value="${tempOv}" placeholder="留空 = 沿用请求模式"><span class="field-help">0–2；留空沿用所选请求模式的温度。</span></div>
    <div class="field"><label>最大输入字符</label><input id="lit-ai-max" type="number" min="1000" max="60000" value="${Number(as.max_chars||24000)}"><span class="field-help">选中内容超出该长度会被截断（1000–60000）。</span></div>
    <div class="field span-4"><label>附加请求参数 JSON（可选）</label><textarea id="lit-ai-extra" class="mono" style="min-height:70px">${esc(JSON.stringify(as.extra_params||{},null,0)==='{}'?'':JSON.stringify(as.extra_params,null,2))}</textarea><span class="field-help">合并进请求体的额外参数（JSON 对象），如 {"enable_thinking": false} 或 {"thinking_budget": 1024}；model / messages / stream 不可在此覆盖。</span></div>
    <div class="field span-4"><label>附加风格指令（可选）</label><textarea id="lit-ai-style" style="min-height:90px">${esc(as.style_instruction||'')}</textarea><span class="field-help">追加到所有 AI 动作的系统提示词末尾。如：输出保持简洁；翻译保留术语对照表；总结按「结论 / 依据 / 局限」分节。</span></div>
    <div class="field span-4"><label>预设动作提示词覆盖（可选，留空用内置默认）</label><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:6px">${[['translate','AI 翻译'],['summarize','AI 总结'],['organize','AI 整理'],['polish','AI 笔记润色']].map(([k,label])=>`<label style="display:block;font-size:12px;opacity:.85">${label}<textarea id="lit-ai-prompt-${k}" rows="4" style="min-height:84px;margin-top:4px" placeholder="${esc(LIT_PROMPT_DEFAULTS[k])}">${esc((as.prompts||{})[k]||'')}</textarea></label>`).join('')}</div><span class="field-help">整段替换对应动作的内置系统提示词（占位灰字即默认内容）；「AI 翻译」的目标语言仍按上方「翻译目标语言」追加。约束示例（翻译）：完全翻译为中文，以下专业名词保留英文原文不翻译：U-Net、SNR、RoI；公式、变量与单位一律原样保留。</span></div>
    </div>
    <div class="section-title" style="margin-top:18px"><div><h3>自定义 AI 动作</h3><p>添加个性化阅读动作（最多 12 个）：填动作名称与提示词，保存后出现在 PDF 阅读区 AI 面板，选中文本一键执行。提示词写明任务要求与输出格式；模型 / 温度 / 附加参数沿用上方请求模式与覆盖设置。</p></div><button class="secondary-btn" id="lit-ca-add">＋ 添加动作</button></div>
    <div id="lit-ca-list">${(Array.isArray(as.custom_actions)?as.custom_actions:[]).map(litCaRow).join('')}</div>
    <div style="margin-top:12px"><button class="primary-btn" id="lit-ai-save">保存 AI 助手设置</button></div>`;
    $('#lit-pdf-save').onclick=async()=>{
      const dir=$('#lit-pdf-dir').value.trim(),move=$('#lit-pdf-move').checked;
      if(move&&!await window.ERWDialog.confirm(`将把现有 PDF 迁移到「${dir||'默认目录 Knowledge/Literature/PDF'}」并回写文献条目的附件指向。继续？`))return;
      try{
        const r=await api('/api/literature/storage',{method:'POST',body:{pdf_dir:dir,move_existing:move}});
        toast(`已保存：迁移 ${r.moved||0} 个 PDF（跳过 ${r.skipped||0}），更新 ${r.updated||0} 条附件指向`);
        renderLiteratureSettings(p);
      }catch(e){toast(e.message||'保存失败',true)}
    };
    $('#lit-noteimg-save').onclick=async()=>{ /* v260929f · 笔记图片目录单独保存，不动 PDF 目录 */
      try{
        const r=await api('/api/literature/storage',{method:'POST',body:{note_images_dir:$('#lit-noteimg-dir').value.trim()}});
        toast(`笔记图片目录已保存：${r.note_images_dir||'默认目录'}`);
        renderLiteratureSettings(p);
      }catch(e){toast(e.message||'保存失败',true)}
    };
    $('#lit-ai-save').onclick=async()=>{ /* v260929 · AI 阅读助手设置写入 app.llm.assist，随 /api/config/app 持久化 */
      let extra={};
      const rawExtra=$('#lit-ai-extra').value.trim();
      if(rawExtra){try{extra=JSON.parse(rawExtra);if(!extra||typeof extra!=='object'||Array.isArray(extra))throw new Error('必须是 JSON 对象')}catch(e){toast('附加请求参数 JSON 无效：'+e.message,true);return}}
      const rawTemp=$('#lit-ai-temp').value.trim();
      const app=state.config.app,cur=app.llm||{};
      const cas=$$('#lit-ca-list [data-ca-row]').map(r=>({id:$('[data-ca-id]',r).value||('ca-'+Math.random().toString(36).slice(2,10)),name:$('[data-ca-name]',r).value.trim(),prompt:$('[data-ca-prompt]',r).value.trim()})).filter(x=>x.name&&x.prompt); /* v260929b · 自定义动作随保存写入 */
      cur.assist={enabled:$('#lit-ai-enabled').value==='1',request_preset:$('#lit-ai-preset').value,model_override:$('#lit-ai-model').value.trim(),temperature_override:rawTemp===''?null:Math.max(0,Math.min(2,+rawTemp||0)),extra_params:extra,target_language:$('#lit-ai-lang').value.trim()||'中文',style_instruction:$('#lit-ai-style').value.trim(),max_chars:Math.max(1000,Math.min(60000,+$('#lit-ai-max').value||24000)),custom_actions:cas,prompts:Object.fromEntries(['translate','summarize','organize','polish'].map(k=>[k,$('#lit-ai-prompt-'+k).value.trim()]).filter(([,v])=>v))}; /* v260929x · 预设动作提示词覆盖随保存写入（空值不存 = 用内置默认） */
      app.llm=cur;
      const saved=await api('/api/config/app',{method:'POST',body:app});
      state.config.app=saved;toast('AI 阅读助手设置已保存');
      renderLiteratureSettings(p);
    };
    const wireCa=()=>{$$('#lit-ca-list [data-ca-del]').forEach(b=>b.onclick=()=>b.closest('[data-ca-row]').remove())};wireCa(); /* v260929b · 自定义动作行增删 */
    $('#lit-ca-add').onclick=()=>{const list=$('#lit-ca-list');if($$('#lit-ca-list [data-ca-row]').length>=12)return toast('自定义动作最多 12 个',true);list.insertAdjacentHTML('beforeend',litCaRow({id:'ca-'+Math.random().toString(36).slice(2,10)}));wireCa()};
    $('#lit-pdf-open').onclick=async()=>{try{await api('/api/literature/open-folder',{method:'POST',body:{}})}catch(e){toast(e.message||'打开失败',true)}};
    $('#lit-pdf-rebuild').onclick=rebuildLiteratureLinks;
  }
  function conditionEditRow(x={}){return `<div class="condition-edit-row"><input class="search-input" data-cond-label value="${esc(x.label||'')}" placeholder="例如：期刊论文"><input class="search-input" data-cond-current type="number" min="0" step="0.1" value="${Number(x.current||0)}"><input class="search-input" data-cond-target type="number" min="0" step="0.1" value="${Number(x.target||0)}"><input class="search-input" data-cond-unit value="${esc(x.unit||'')}" placeholder="篇 / 项"><button class="ghost-btn danger" type="button" data-cond-del>删除</button></div>`}



  function applyTheme(theme){ document.documentElement.dataset.animations=state.config?.app?.ui?.animations===false?"off":"on";document.documentElement.dataset.theme=theme||'light';localStorage.setItem('theme',theme||'light');if($('#md-preview')&&state.editorMode!=='edit')setTimeout(()=>renderMarkdownPreview(),20)}
  async function systemAction(action){
    const desktop=document.documentElement.dataset.desktop==='true';
    if(action==='restart'&&!editorDirty()&&!await window.ERWDialog.confirm(desktop?'快速重启工作台？桌面窗口将自动重新打开。':'快速重启本地服务？浏览器将在约 1 秒后自动重连。'))return;
    if(!await guardEditor(action==='restart'?'重启工作台':'重新加载工作台'))return;
    try{
      await api('/api/system/'+action,{method:'POST',body:{}});
      state.dirty=false;state.editorBaseline=null;
      if(action==='reload'){await loadBootstrap();toast('配置与索引已重新加载');await navigate(state.route)}
      else{toast('服务正在重启');if(!desktop)setTimeout(waitForRestart,700)}
    }catch(e){toast('操作失败：'+e.message,true)}
  }

  async function waitForRestart(attempt=0){
    if(attempt>18){toast('服务重启等待超时，请手动刷新页面',true);return;}
    try{await api('/api/health');location.reload();}catch{setTimeout(()=>waitForRestart(attempt+1),450);}
  }

  async function loadBootstrap(){ const [cfg,statuses,projects,health,ws,knowledgeTypes]=await Promise.all(['/api/config','/api/statuses','/api/projects','/api/health','/api/workspace/info','/api/knowledge-types'].map(bootstrapRead)); state.config=cfg;state.statuses=statuses;state.projects=projects;state.knowledgeTypes=Array.isArray(knowledgeTypes)?knowledgeTypes:[];if(localStorage.getItem('sidebarPinned')===null){state.sidebarPinned=new Set(cfg.app.ui?.sidebar_pinned_groups||['core']);saveSidebarState();}$('#brand-title').textContent=cfg.app.app_name;$('#brand-subtitle').textContent=cfg.app.subtitle;$('#version-label').textContent=health.version;$('#workspace-mini').textContent='Workspace · '+ws.relative;state.milestoneView=(['3d','fishbone'].includes(cfg.app.ui?.milestone_default_view)?'timeline':cfg.app.ui?.milestone_default_view)||state.milestoneView;state.graphView='2d';state.heatmapMonths=Math.max(1,Math.min(12,Number(cfg.app.ui?.heatmap_months)||state.heatmapMonths||12));if(Array.isArray(cfg.app.ui?.heatmap_thresholds)&&cfg.app.ui.heatmap_thresholds.length===2)state.heatmapThresholds=[Math.max(1,Math.round(+cfg.app.ui.heatmap_thresholds[0]||1)),Math.max(Math.max(1,Math.round(+cfg.app.ui.heatmap_thresholds[0]||1))+1,Math.round(+cfg.app.ui.heatmap_thresholds[1]||3))];if(Array.isArray(cfg.app.ui?.heatmap_colors)&&cfg.app.ui.heatmap_colors.length===3)state.heatmapColors=cfg.app.ui.heatmap_colors;localStorage.setItem('heatmapMonths',String(state.heatmapMonths));localStorage.setItem('heatmapThresholds',JSON.stringify(state.heatmapThresholds));localStorage.setItem('heatmapColors',JSON.stringify(state.heatmapColors));const theme=localStorage.getItem('theme')||cfg.app.ui?.theme||'light';applyTheme(theme); }

  function bindGlobal(){
    document.addEventListener('keydown',async e=>{if(document.documentElement.dataset.desktop==='true'&&(e.key==='F5'||((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='r'))){e.preventDefault();if(await guardEditor('刷新页面')){state.dirty=false;state.editorBaseline=null;location.reload()}}});
    $('#modal-close').onclick=closeModal;$('#modal-backdrop').addEventListener('click',e=>{if(e.target===$('#modal-backdrop'))closeModal()});
    $('#theme-btn').onclick=()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
    $('#zoom-btn').onclick=()=>$('#zoom-menu').classList.toggle('hidden');
    $$('[data-zoom]').forEach(b=>b.onclick=()=>{applyUiScale(b.dataset.zoom);$('#zoom-menu').classList.add('hidden')});
    applyUiScale(state.uiScale);
    window.addEventListener('resize',syncViewportVars); /* v260929g · 窗口尺寸变化时同步折算视口变量 */
    /* v260922h · 密度默认紧凑型（并排一屏收纳）；手动切换后记忆用户选择 */
    $('#density-btn').onclick=()=>{const v=state.density==='cozy'?'compact':'cozy';localStorage.setItem('pageDensityManual','1');localStorage.setItem('pageDensity',v);applyDensity(v);fitResearchHeatmap();};
    const savedDensity=localStorage.getItem('pageDensity'), manualDensity=localStorage.getItem('pageDensityManual')==='1';
    applyDensity(manualDensity&&savedDensity?savedDensity:'compact'); /* v260922h · 默认紧凑型：并排一屏、免滚动 */
    $('#global-search-btn').onclick=()=>openGlobalSearch();
    document.addEventListener('keydown',e=>{const mod=e.ctrlKey||e.metaKey,key=e.key.toLowerCase();if(mod&&key==='s'&&$('#md-input')&&state.selectedDoc){e.preventDefault();$('#doc-save')?.click();return}if(mod&&key==='k'){e.preventDefault();openGlobalSearch();}});
    const toggleReloadMenu=show=>{$('#reload-menu').classList.toggle('hidden',!show);$('#reload-btn').setAttribute('aria-expanded',String(show))};
    $('#reload-btn').onclick=()=>toggleReloadMenu($('#reload-menu').classList.contains('hidden'));
    $$('[data-system-action]').forEach(b=>b.onclick=()=>{toggleReloadMenu(false);systemAction(b.dataset.systemAction)});
    $('#reload-btn').onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();toggleReloadMenu(true);$('#reload-menu button')?.focus()}};
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#reload-menu').classList.contains('hidden')){toggleReloadMenu(false);$('#reload-btn').focus()}});
    document.addEventListener('click',e=>{if(!e.target.closest('.reload-wrap'))toggleReloadMenu(false);if(!e.target.closest('.zoom-wrap'))$('#zoom-menu').classList.add('hidden')});
    window.addEventListener('beforeunload',e=>{if(editorDirty()||state.saving){e.preventDefault();e.returnValue=''}});
    window.addEventListener('hashchange',()=>{const r=location.hash.slice(1)||'overview';if(r!==state.route)navigate(r)});
    /* v260929 · PDF 工作区「返回文献列表」事件：启动即注册（此前挂在 openLiteratureWorkspace 内，
       从附件徽章进入时无人监听，点击返回无反应）；hash 未变不触发路由，须显式重渲染列表页 */
    window.addEventListener('erw-lit-back',()=>renderDocsPage('literature'));
  }

  /* v261022.2 · 同步页宿主适配层：上游 sync.js 只认 window.ERWSyncUI，
     这里用本地 #modal / toast / 导航 / 设置页能力实现，不引入上游 app.js 的大改。 */
  function syncCloseModal(){
    $('#modal-backdrop').classList.add('hidden');
    $('#modal-body').innerHTML='';$('#modal-footer').innerHTML='';
    $('#modal').classList.remove('sync-conflict-modal');
  }
  function syncModal(title,html,footer){
    $('#modal-title').textContent=title||'同步';
    $('#modal-body').innerHTML=html||'';
    $('#modal-footer').innerHTML=footer||'';
    $('#modal-close').onclick=()=>syncCloseModal();
    $('#modal-backdrop').classList.remove('hidden');
    $('#modal-backdrop').onclick=e=>{if(e.target===$('#modal-backdrop'))syncCloseModal()};
  }
  window.ERWSyncUI={
    modal:syncModal, closeModal:syncCloseModal, toast,
    openSettings:async()=>{if(await navigate('settings'))setTimeout(()=>$('[data-set-tab="sync"]')?.click(),40)},
    applyPreferences(values){
      for(const [k,v] of Object.entries(values||{}))localStorage.setItem(k,String(v));
      if(values?.theme)applyTheme(values.theme);
      if(values?.uiScale)applyUiScale(values.uiScale);
      if(values?.pageDensity){localStorage.setItem('pageDensityManual','1');applyDensity(values.pageDensity)}
      for(const k of ['sidebarPinned','sidebarOpen'])if(values?.[k]){try{state[k]=new Set(JSON.parse(values[k]));renderSidebar()}catch{}}
    },
    refresh:async()=>{
      if(editorDirty()||state.saving||state.draft)return false;
      await loadBootstrap();renderSidebar();
      return await navigate(state.route);
    }
  };

  async function init(){ try{bindGlobal();
    /* v261009 · 先等插件宿主把面板挂进来（面板在 eval 期自登记 ERWPanels），
       再构建侧栏——否则插件的导航项要等下一次渲染才出现。 */
    try{ await window.ERWPluginHost?.ready; }catch(e){ console.warn('plugin host failed', e); }
    mountSlots();   /* v261009 · 插件槽位（顶栏等）在导航构建前挂好 */
    await loadBootstrap();renderSidebar();const route=location.hash.slice(1)||'overview';await navigate(route);
    /* v261022.5 · 项目名显示名/证据徽章需要项目记录：一次预取，失败不阻塞首屏 */
    window.ERWResearchUI?.loadProjects?.().catch(()=>{});
    /* v261022.2 · 通知外部模块（同步页等）可以开始贴附/轮询；只派发一次 */
    try{ window.dispatchEvent(new Event('workbench:ready')); }catch(e){ console.warn('workbench:ready', e); }
    }catch(e){console.error(e);$('#main').innerHTML=`<div class="card card-pad danger">初始化失败：${esc(e.message)}<br><span class="muted">确认已使用 <span class="mono">python server.py</span> 启动工程。</span></div>`;} }
  window.addEventListener('load',init);
})();
