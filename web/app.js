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
  const fmtTime = (s) => {
    if (!s) return '—';
    try { return new Date(s).toLocaleString('zh-CN', {hour12:false}); } catch { return s; }
  };
  const debounce = (fn, ms=250) => { let t; return (...args) => { clearTimeout(t); t=setTimeout(()=>fn(...args),ms); }; };
  const readAsDataUrl = (file) => new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file)});
  const storedArray = (key, fallback) => { try { const x=JSON.parse(localStorage.getItem(key)||'null'); return Array.isArray(x)?x:fallback; } catch { return fallback; } };
  const storedInt = (key, fallback, min, max) => { const raw=localStorage.getItem(key); const n=Number(raw); return raw!=null&&Number.isFinite(n)?Math.max(min,Math.min(max,Math.round(n))):fallback; };

  const savedFocusMinutes = storedInt('focusMinutes', 25, 1, 240);
  const savedBreakMinutes = storedInt('breakMinutes', 5, 1, 120);

  const state = {
    config: null, statuses: {}, projects: [], route: 'overview', docs: [], selectedDoc: null,
    editorMode: 'split', milestoneView: 'timeline', graphView: '2d', graph: null, graphSelected: null, graphPreviewSeq: 0, previewSeq: 0,
    graphKinds: new Set(storedArray('graphKinds', ['idea','journal','note','milestone','summary','literature','project','tag'])),
    graphRelations: new Set(storedArray('graphRelations', ['wikilink','tag','project'])),
    agentSession: null, agentRefs: [], agentImages: [], agentPreset: localStorage.getItem('agentRequestPreset') || '', agentSending:false,
    heatmapMonths: storedInt('heatmapMonths', 12, 1, 12), heatmapObserver: null, uiScale: storedInt('uiScale', 100, 80, 125), density: localStorage.getItem('pageDensity')==='cozy'?'cozy':'compact', /* v260922h · 默认紧凑型（并排一屏收纳） */
    focus: {mode:'专注', focusMinutes:savedFocusMinutes, breakMinutes:savedBreakMinutes, seconds:savedFocusMinutes*60, total:savedFocusMinutes*60, timer:null, running:false},
    sidebarPinned: new Set(storedArray('sidebarPinned', ['core'])),
    sidebarOpen: new Set(storedArray('sidebarOpen', ['core','resources','system'])),
    dirty: false,
  };

  const NAV_GROUPS = [
    {id:'core', label:'核心工作', items:[
      ['overview','概览','▦'], ['todos','待办','✓'], ['focus','专注','◷'], ['agent','Agent','◉'], ['news','资讯','◎']
    ]},
    {id:'research', label:'研究 · 知识', defaultCollapsed:true, items:[
      ['research-overview','总览','◇'], ['ideas','灵感','✦'], ['journals','研究日志','▤'], ['notes','笔记','▧'],
      ['milestones','里程碑','⚑'], ['summaries','工作总结','▣'], ['literature','文献','◫'], ['graph','知识图谱','⌬']
    ]},
    {id:'resources', label:'资源', items:[['folders','文件夹','▱']]},
    {id:'system', label:'系统', items:[['settings','设置','⚙']]}
  ];

  const PAGE_META = {
    overview:['CORE WORK','概览'], todos:['CORE WORK','待办'], focus:['CORE WORK','专注'], agent:['CORE WORK','科研 Agent'], news:['CORE WORK','资讯'],
    'research-overview':['RESEARCH KNOWLEDGE','研究 · 知识总览'], ideas:['RESEARCH KNOWLEDGE','灵感'], journals:['RESEARCH KNOWLEDGE','研究日志'],
    notes:['RESEARCH KNOWLEDGE','笔记'], milestones:['RESEARCH KNOWLEDGE','里程碑'], summaries:['RESEARCH KNOWLEDGE','工作总结'],
    literature:['RESEARCH KNOWLEDGE','文献'], graph:['RESEARCH KNOWLEDGE','知识图谱'], folders:['RESOURCES','文件夹'], settings:['SYSTEM','设置']
  };

  const KIND_ROUTE = {ideas:'idea', journals:'journal', notes:'note', milestones:'milestone', summaries:'summary', literature:'literature'};
  const KIND_LABEL = {idea:'灵感', journal:'研究日志', note:'笔记', milestone:'里程碑', summary:'工作总结', literature:'文献'};

  /* v260923 · 内置分类标记 + 自定义标记（localStorage 持久化） */
  const KIND_MARKS=[
    {id:'knowledge',icon:'◈',label:'知识',color:'#2a9d8f'},
    {id:'synthesis',icon:'◎',label:'归类',color:'#845ec2'},
    {id:'method',icon:'⚒',label:'方法',color:'#e76f51'},
    {id:'question',icon:'？',label:'问题',color:'#bc4749'},
    {id:'thinking',icon:'✦',label:'思路',color:'#e9b44c'},
    {id:'architecture',icon:'▤',label:'架构',color:'#4a6fa5'},
    {id:'experiment',icon:'⚗',label:'实验',color:'#d1569a'},
    {id:'data',icon:'⊞',label:'数据',color:'#2f7d6d'}
  ];
  function customMarks(){ try{ const v=JSON.parse(localStorage.getItem('customMarks')||'[]'); return Array.isArray(v)?v:[]; }catch{ return []; } }
  function saveCustomMarks(v){ localStorage.setItem('customMarks', JSON.stringify(v)); }
  function allMarks(){ return KIND_MARKS.concat(customMarks()); }
  function kindLabel(kind){ return KIND_LABEL[kind] || kind; }

  async function api(url, opts={}) {
    const init = {...opts, headers:{'Content-Type':'application/json', ...(opts.headers||{})}};
    if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
    const res = await fetch(url, init);
    let data = null; try { data = await res.json(); } catch { data = {}; }
    if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
    return data;
  }

  function toast(message, error=false) {
    const el = document.createElement('div'); el.className = 'toast' + (error?' error':''); el.textContent = message;
    $('#toast-stack').appendChild(el); setTimeout(()=>el.remove(), 3200);
  }

  function modal(title, bodyHtml, footerHtml='') {
    $('#modal-title').textContent = title; $('#modal-body').innerHTML = bodyHtml; $('#modal-footer').innerHTML = footerHtml;
    $('#modal-backdrop').classList.remove('hidden');
  }
  function closeModal(){ $('#modal-backdrop').classList.add('hidden'); }

  function saveSidebarState(){
    localStorage.setItem('sidebarPinned', JSON.stringify([...state.sidebarPinned]));
    localStorage.setItem('sidebarOpen', JSON.stringify([...state.sidebarOpen]));
  }

  function navGroups(){
    return NAV_GROUPS.map(g=>({...g, items:[...g.items]}));
  }

  function renderSidebar(){
    const nav = $('#sidebar-nav');
    nav.innerHTML = navGroups().map(g => {
      const pinned = state.sidebarPinned.has(g.id);
      const open = pinned || state.sidebarOpen.has(g.id);
      return `<section class="nav-group ${open?'':'collapsed'} ${pinned?'pinned':''}" data-group="${g.id}">
        <div class="nav-group-head"><button class="group-toggle" type="button" data-group-toggle="${g.id}"><span class="chev">⌄</span><span>${g.label}</span></button><button class="pin" type="button" data-pin-group="${g.id}" title="常驻展开">◆</button></div>
        <div class="nav-items">${g.items.map(([id,label,ico])=>`<a class="nav-item ${state.route===id?'active':''}" href="#${id}" data-route="${id}"><span class="nav-ico">${ico}</span><span>${label}</span></a>`).join('')}</div>
      </section>`;
    }).join('');
    $$('[data-group-toggle]', nav).forEach(btn => btn.addEventListener('click', e => {
      if (e.target.closest('[data-pin-group]')) return;
      const id=btn.dataset.groupToggle; if(state.sidebarPinned.has(id)) return;
      if(state.sidebarOpen.has(id)) state.sidebarOpen.delete(id); else state.sidebarOpen.add(id); saveSidebarState(); renderSidebar();
    }));
    $$('[data-pin-group]', nav).forEach(btn => btn.addEventListener('click', e => {
      e.stopPropagation(); const id=btn.dataset.pinGroup;
      if(state.sidebarPinned.has(id)) state.sidebarPinned.delete(id); else {state.sidebarPinned.add(id); state.sidebarOpen.add(id);} saveSidebarState(); renderSidebar();
    }));
    $$('[data-route]', nav).forEach(a => a.addEventListener('click', e=>{ e.preventDefault(); navigate(a.dataset.route); }));
  }

  function setHeader(route){
    let eyebrow,pageTitle;
    const meta = PAGE_META[route];
    if(meta){ [eyebrow,pageTitle]=meta; }
    else { eyebrow='WORKBENCH'; pageTitle=route; }
    $('#page-eyebrow').textContent=eyebrow; $('#page-title').textContent=pageTitle;
    const d=new Date(); $('#page-date').textContent = d.toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short'});
    document.title = `${pageTitle} · ${state.config?.app?.app_name || '科研工作台'}`;
  }

  async function navigate(route){
    if (state.dirty && !confirm('当前 Markdown 有未保存修改，确定离开吗？')) return;
    state.dirty=false; state.route=route; location.hash=route; renderSidebar(); setHeader(route);
    if(state.heatmapObserver){try{state.heatmapObserver.disconnect();}catch{} state.heatmapObserver=null;}
    $('#main').innerHTML='<div class="empty"><div><div class="empty-symbol">LOADING</div>正在加载…</div></div>';
    try {
      if(route==='overview') await renderOverview();
      else if(route==='todos') await renderTodos();
      else if(route==='focus') await renderFocus();
      else if(route==='agent') await renderAgent();
      else if(route==='news') await renderNews();
      else if(route==='research-overview') await renderResearchOverview();
      else if(route==='graph') await renderGraphPage();
      else if(route==='folders') await renderFolders();
      else if(route==='settings') await renderSettings();
      else if(KIND_ROUTE[route]) await renderDocsPage(KIND_ROUTE[route]);
      else await renderOverview();
      animateMain();
    } catch(err){ console.error(err); $('#main').innerHTML=`<div class="card card-pad danger">加载失败：${esc(err.message)}</div>`; animateMain(); }
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

  async function renderOverview(){
    const [dash,todosList] = await Promise.all([api('/api/dashboard'), api('/api/todos')]);
    const openTodos=todosList.filter(x=>!x.done).slice(0,5);
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
            <div class="card-kicker">TODAY / RESEARCH DESK</div>
            <h3>今天 · ${esc(dateTitle)}</h3>
            <p>把学业周期、科研资产、任务与研究节奏放在同一张仪表盘里。</p>
          </div>
          <div class="today-metrics">
            <div><strong>${todosList.filter(x=>!x.done).length}</strong><span>未完成待办</span></div>
            <div><strong>${activity.active_days_month||0}</strong><span>本月活跃日</span></div>
            <div><strong>${activity.events_month||0}</strong><span>本月科研记录</span></div>
            <div><strong>${recentToday}</strong><span>今日科研记录</span></div>
          </div>
        </section>

        <section class="card quick-capture-card">
          <div class="quick-capture-copy"><div class="card-kicker">QUICK CAPTURE</div><h3>快速记录</h3><p>把临时想法及时沉淀到 Workspace，减少页面跳转。</p></div>
          <div class="quick-capture-actions">
            <button class="quick-action" data-quick-doc="ideas"><span>✦</span><b>灵感</b><small>Idea</small></button>
            <button class="quick-action" data-quick-doc="journals"><span>▤</span><b>研究日志</b><small>Journal</small></button>
            <button class="quick-action" data-quick-doc="notes"><span>▧</span><b>笔记</b><small>Note</small></button>
            <button class="quick-action" data-quick-doc="literature"><span>◫</span><b>文献</b><small>Paper</small></button>
            <button class="quick-action" data-quick-doc="milestones"><span>⚑</span><b>里程碑</b><small>Milestone</small></button>
          </div>
        </section>
      </div>

      <div class="grid grid-3 overview-ops-grid">
        ${researchRhythmCard(activity,academic)}
        <section class="card card-pad"><div class="card-head"><div><div class="card-kicker">TODAY TASKS</div><h3>当前任务</h3></div><button class="secondary-btn" data-go="todos">全部待办</button></div>${listRows(openTodos.map(t=>({title:t.title,meta:`${t.project||'未归属项目'} · 截止 ${fmtDate(t.due)}`})), '暂无待办')}</section>
        <section class="card card-pad"><div class="card-head"><div><div class="card-kicker">NEXT MILESTONE</div><h3>近期节点</h3></div><button class="secondary-btn" data-go="milestones">时间轴</button></div>${listRows((dash.upcoming_milestones||[]).slice(0,5).map(d=>({title:d.title,meta:`${d.project||'未归属项目'} · ${fmtDate(d.due)} · ${d.status}`})), '暂无近期里程碑')}</section>
      </div>

      ${projectPulseCard(dash.project_stats||[])}

      <div class="section-title"><div><h3>最近研究活动</h3><p>快速回到最近产生的科研内容</p></div><button class="secondary-btn" data-go="research-overview">研究总览</button></div>
      <div class="grid grid-3">${recentCard('最近灵感',dash.recent.ideas,'ideas')}${recentCard('最近笔记',dash.recent.notes,'notes')}${recentCard('最近工作总结',dash.recent.summaries,'summaries')}</div>

      <div class="grid grid-4 overview-stats">
        ${stat('笔记',dash.counts.note||0,'NOTES')}
        ${stat('文献',dash.counts.literature||0,'LITERATURE')}
        ${stat('里程碑',dash.counts.milestone||0,'MILESTONES')}
        ${stat('研究日志',dash.counts.journal||0,'JOURNALS')}
      </div>
    </div>`;
    wireGo();
    fitResearchHeatmap();
  }

  function academicProgressCard(a){
    const configured=!!a.configured;
    const pct=Number(a.percent||0);
    return `<section class="card academic-progress-card">
      <div class="card-head"><div><div class="card-kicker">ACADEMIC TIMELINE</div><h3>${esc(a.degree_name||'学业进度')}</h3></div><button class="ghost-btn" data-go="settings">设置</button></div>
      ${configured?`<div class="degree-progress-value">${pct.toFixed(1)}<span>%</span></div>
      <div class="degree-progress-track"><i style="width:${Math.max(0,Math.min(100,pct))}%"></i></div>
      <div class="degree-progress-dates"><span>开始 ${esc(a.start_date)}</span><span>预计完成 ${esc(a.expected_end_date)}</span></div>
      <div class="degree-progress-foot"><span>已进行 <strong>${a.elapsed_days||0}</strong> 天</span><span>剩余 <strong>${a.remaining_days||0}</strong> 天</span></div>`:
      `<div class="academic-empty"><strong>尚未配置学业周期</strong><span>在「设置 → 学业与目标」中填写开始日期与预计完成日期后，这里会自动计算进度。</span></div>`}
    </section>`;
  }

  function graduationConditionsCard(a){
    const items=a.graduation_conditions||[];
    return `<section class="card graduation-card"><div class="card-head"><div><div class="card-kicker">GRADUATION TARGETS</div><h3>毕业条件</h3></div><div class="condition-score">${a.conditions_done||0}<span>/ ${a.conditions_total||0}</span></div></div>
      ${items.length?`<div class="condition-list">${items.map(x=>`<div class="condition-item"><div class="condition-line"><strong>${esc(x.label)}</strong><span>${formatMetric(x.current)} / ${formatMetric(x.target)}${esc(x.unit||'')}</span></div><div class="condition-track"><i style="width:${x.percent||0}%"></i></div></div>`).join('')}</div>`:
      `<div class="academic-empty compact"><strong>尚未配置毕业条件</strong><span>可以添加论文、会议、专利、学位论文阶段等自定义目标；数据由你自己掌控。</span><button class="secondary-btn" data-go="settings">配置目标</button></div>`}
    </section>`;
  }

  function formatMetric(v){ const n=Number(v); return Number.isFinite(n)&&Math.abs(n%1)>1e-9?n.toFixed(1):String(Number.isFinite(n)?n:(v||0)); }

  const HEATMAP_MONTH_OPTIONS=[2,4,6,12];
  const ACTIVITY_LABELS={doc_create:'新建文档',doc_update:'更新文档',doc_delete:'归档文档',todo_create:'新增任务',todo_update:'更新任务',todo_done:'完成任务',project_create:'新建项目',knowledge_export:'知识汇总',bibtex_export:'BibTeX导出',agent_chat:'Agent对话'};
  function researchHeatmapCard(activity){
    const rows=activity.days||[];
    if(!rows.length) return `<section class="card heatmap-card"><div class="card-head"><div><div class="card-kicker">RESEARCH HEATMAP</div><h3>科研热力图</h3></div></div><div class="empty">暂无活动数据</div></section>`;
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
      const level=count===0?0:count===1?1:count<=3?2:count<=6?3:4;
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
    return `<section class="card heatmap-card" data-heatmap-weeks="${weeks}"><div class="card-head"><div><div class="card-kicker">RESEARCH HEATMAP / ${months} MONTHS</div><h3>科研热力图</h3><p>根据 Markdown 创建/更新、任务完成与知识整理等本地活动自动累计。</p></div><div class="heatmap-head-tools"><div class="heatmap-summary"><strong>${activity.events_month||0}</strong><span>本月记录</span><strong>${activity.active_days_month||0}</strong><span>活跃日</span></div><select class="mini-select" id="heatmap-month-select" aria-label="科研热力图显示月份">${options}</select></div></div>
      <div class="heatmap-scroll"><div class="heatmap-plot"><div class="heatmap-axis"><div class="heatmap-axis-cap">星期</div><div class="heatmap-weekdays"><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span><span>日</span></div></div><div class="heatmap-stage"><div class="heatmap-months" style="--heat-weeks:${weeks}">${monthLabels.join('')}</div><div class="heatmap-month-boundaries">${monthBoundaries.join('')}</div><div class="heatmap-cells" style="--heat-weeks:${weeks}">${cells.join('')}</div></div></div></div>
      <div class="heatmap-footer"><span>少</span><i class="heat-cell level-0"></i><i class="heat-cell level-1"></i><i class="heat-cell level-2"></i><i class="heat-cell level-3"></i><i class="heat-cell level-4"></i><span>多</span><span class="heatmap-hint">鼠标悬停查看当天活动</span></div>
    </section>`;
  }

  function fitResearchHeatmap(){
    const card=$('.heatmap-card'); const scroll=$('.heatmap-scroll'); if(!card||!scroll) return;
    const topRow=card.closest('.overview-top-row');
    const academicGrid=$('.overview-academic-grid');
    const apply=()=>{
      const weeks=Math.max(1,Number(card.dataset.heatmapWeeks)||1), gap=2, axis=54;
      const csp=getComputedStyle(card), ssp=getComputedStyle(scroll);
      const chrome=axis+parseFloat(csp.paddingLeft)+parseFloat(csp.paddingRight)+parseFloat(ssp.paddingLeft)+parseFloat(ssp.paddingRight);
      const compact=document.documentElement.dataset.density==='compact';
      const wide=!!topRow&&window.matchMedia('(min-width:1080px)').matches; /* v260922h3 · 宽屏两种密度都并排：宽松=原样式，紧凑=并排+学业两卡再并排保一屏 */
      const totalW=topRow?topRow.clientWidth:scroll.clientWidth+chrome; /* v260922f · 用轨道宽度做基准，缩卡后无循环依赖 */
      /* v260922h6 · 防护：测量未就绪或异常窄时清空内联样式回退 CSS 默认，等下一轮 rAF/RO 重测，防坏值写死布局 */
      if(topRow&&(!Number.isFinite(totalW)||totalW<600)){
        topRow.style.gridTemplateColumns=''; card.style.maxWidth='';
        if(academicGrid) academicGrid.classList.remove('is-row');
        return;
      }
      const widthSize=Math.floor((totalW-chrome-gap*(weeks-1))/weeks);
      /* v260922k3 · 宽松型格子不设固定上限：按可用宽度自动放大铺满，
       * 仅保留学业区 330px 保底以维持并排；紧凑型仍用 21px 上限。 */
      const cozyMax=Math.floor((totalW-10-330-chrome-gap*(weeks-1))/weeks);
      const maxSize=compact?21:Math.max(6,cozyMax);
      const size=Math.max(6,Math.min(maxSize,widthSize));
      const needW=Math.round(chrome+weeks*size+gap*(weeks-1));
      const canDual=wide&&size<widthSize&&totalW-needW-10>=330; /* v260922k · 学业区最小宽度 420→330，让热力图多占横向空间；学业区变窄时进度/毕业条件自动改纵向堆叠 */
      let dualAcademic=wide&&!canDual; /* 宽松型维持原行为：仅热力图全宽时进度/毕业条件两卡并排 */
      if(compact) dualAcademic=wide&&canDual&&(totalW-needW-16>=640); /* v260922k · 双列门槛 680→640，配合热力图加宽后学业区仍可保持两卡并排 */
      if(topRow){
        if(wide){topRow.style.gridTemplateColumns=canDual?`${needW}px minmax(0,1fr)`:'minmax(0,1fr)';}
        else{topRow.style.gridTemplateColumns='';}
      }
      if(academicGrid) academicGrid.classList.toggle('is-row',dualAcademic);
      card.style.maxWidth=wide&&size<widthSize?`${needW}px`:''; /* v260922h6 · maxWidth 仅在宽屏并排管线收紧；窄屏一律放开，防热力图卡被压成窄条 */
      const cardW=wide&&canDual?needW:scroll.clientWidth+chrome;
      card.classList.toggle('is-narrow',cardW<700);
      card.style.setProperty('--heat-cell-size',`${size}px`); card.style.setProperty('--heat-gap',`${gap}px`);
      const step=size+gap;
      $$('.heatmap-month-boundary',card).forEach(line=>{
        const col0=Math.max(0,Number(line.dataset.col0)||0), row=Math.max(0,Math.min(6,Number(line.dataset.row)||0));
        const xLeft=col0*step-Math.ceil(gap/2), y=Math.max(0,row*step-Math.ceil(gap/2));
        line.style.left=`${xLeft}px`; line.style.top=`${y}px`;
        line.style.setProperty('--boundary-step',`${step}px`); line.style.setProperty('--boundary-y',`${y}px`);
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

  function applyUiScale(pct){
    const v=Math.max(80,Math.min(125,Math.round(Number(pct)||100)));
    state.uiScale=v; localStorage.setItem('uiScale',String(v));
    document.documentElement.style.zoom=v===100?'':String(v/100);
    const btn=$('#zoom-btn'); if(btn) btn.textContent=v+'%';
    $$('#zoom-menu button').forEach(b=>b.classList.toggle('active',Number(b.dataset.zoom)===v));
  }

  function applyDensity(mode){
    const v=mode==='cozy'?'cozy':'compact';
    state.density=v;
    document.documentElement.dataset.density=v;
    const btn=$('#density-btn'); if(btn){btn.textContent=v==='cozy'?'宽松型':'紧凑型';btn.title=v==='cozy'?'当前：宽松型（各卡片纵向排布、页面可下拉滚动）。点击切换为紧凑型':'当前：紧凑型（热力图与学业卡并排、一屏收纳免滚动）。点击切换为宽松型';}
  }

  function projectPulseCard(items){
    const rows=(items||[]).slice(0,6);
    return `<section class="card card-pad project-pulse-card"><div class="card-head"><div><div class="card-kicker">PROJECT PULSE</div><h3>项目推进</h3><p>把项目中的知识资产、待办和近期里程碑汇总到同一处。</p></div><div class="card-head-actions"><button class="primary-btn" id="overview-new-project">＋ 新建项目</button><button class="secondary-btn" data-go="folders">项目目录</button></div></div>${rows.length?`<div class="project-pulse-grid">${rows.map(x=>`<div class="project-pulse-item"><div class="project-pulse-name"><strong>${esc(x.name)}</strong><span>${x.last_updated?`更新 ${esc(fmtDate(x.last_updated))}`:'暂无更新记录'}</span></div><div class="project-pulse-metrics"><span><b>${x.docs||0}</b> 文档</span><span><b>${x.open_todos||0}</b> 待办</span><span><b>${x.milestones||0}</b> 里程碑</span><span><b>${x.literature||0}</b> 文献</span></div></div>`).join('')}</div>`:`<div class="academic-empty compact"><strong>还没有科研项目</strong><span>点击“新建项目”后会自动创建标准工程目录，并可用于灵感、笔记、文献等条目的项目关联。</span></div>`}</section>`;
  }

  function researchRhythmCard(activity,academic){
    const goal=Number(academic.weekly_goal_days||5);
    const recent=(activity.days||[]).slice(-7);
    const weekActive=recent.filter(x=>x.count>0).length;
    const weekEvents=recent.reduce((a,x)=>a+(x.count||0),0);
    const pct=Math.min(100,goal?weekActive/goal*100:0);
    return `<section class="card card-pad rhythm-card"><div class="card-head"><div><div class="card-kicker">RESEARCH RHYTHM</div><h3>科研节奏</h3></div><span class="badge accent">近 7 天</span></div><div class="rhythm-main"><div><strong>${weekActive}</strong><span>/ ${goal} 天目标</span></div><div class="condition-track"><i style="width:${pct}%"></i></div></div><div class="rhythm-grid"><div><strong>${weekEvents}</strong><span>科研记录</span></div><div><strong>${activity.current_streak||0}</strong><span>连续活跃天</span></div><div><strong>${activity.longest_streak||0}</strong><span>最长连续</span></div></div></section>`;
  }

  function stat(label,value,kicker){return `<div class="card stat-card"><div class="card-kicker">${kicker}</div><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>`}
  function listRows(items, empty='暂无内容'){
    if(!items.length) return `<div class="empty" style="min-height:110px">${empty}</div>`;
    return `<div class="list-stack">${items.map(x=>`<div class="list-row"><div class="row-main"><div class="row-title">${esc(x.title)}</div><div class="row-meta">${esc(x.meta||'')}</div></div></div>`).join('')}</div>`;
  }
  function recentCard(title,docs,route){return `<section class="card recent-card"><div class="card-head"><h3>${title}</h3><button class="ghost-btn" data-go="${route}">全部</button></div>${docs.length?docs.map(d=>`<div class="list-row clickable" data-open-doc="${d.id}" data-doc-route="${route}"><div class="row-main"><div class="row-title">${esc(d.title)}</div><div class="row-meta">${esc(d.project||'未归属项目')} · ${esc(d.status||'')}</div></div></div>`).join(''):`<div class="empty" style="min-height:120px">暂无内容</div>`}</section>`}
  function wireGo(){
    $$('[data-go]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.go)));
    $$('[data-open-doc]').forEach(b=>b.addEventListener('click',async()=>{ const r=b.dataset.docRoute; await navigate(r); setTimeout(()=>selectDoc(b.dataset.openDoc),10); }));
    $$('[data-quick-doc]').forEach(b=>b.addEventListener('click',async()=>{await navigate(b.dataset.quickDoc);setTimeout(()=>$('#new-doc')?.click(),30);}));
    const hm=$('#heatmap-month-select'); if(hm)hm.addEventListener('change',async()=>{await setHeatmapMonths(hm.value);await renderOverview();animateMain();});
    const np=$('#overview-new-project'); if(np)np.addEventListener('click',()=>openCreateProjectModal(async()=>{await loadBootstrap();await renderOverview();animateMain();}));
  }

  function openCreateProjectModal(afterCreate){
    modal('新建科研项目',`<div class="field"><label>项目名称</label><input id="new-project-name-global" placeholder="请输入你的项目名称"></div><div class="row-meta" style="margin-top:8px">将自动创建 Notes / Experiments / Data / Results / Figures / Manuscript / References，并进入全局项目列表。</div>`,`<button class="secondary-btn" id="new-project-cancel-global">取消</button><button class="primary-btn" id="new-project-create-global">创建项目</button>`);
    $('#new-project-cancel-global').onclick=closeModal;
    const input=$('#new-project-name-global');setTimeout(()=>input?.focus(),30);
    $('#new-project-create-global').onclick=async()=>{const name=input.value.trim();if(!name)return toast('请输入项目名称',true);try{const r=await api('/api/workspace/project',{method:'POST',body:{name}});toast('项目已创建：'+(r.path||name));closeModal();state.projects=await api('/api/projects');if(afterCreate)await afterCreate(r);}catch(e){toast(e.message,true)}};
  }

  async function renderTodos(){
    const [items,projects]=await Promise.all([api('/api/todos'),api('/api/projects')]);
    $('#main').innerHTML=`<section class="card card-pad"><div class="card-head"><div><div class="card-kicker">TASK SYSTEM</div><h3>待办</h3></div><span class="badge accent">默认日期：今天</span></div>
      <div class="todo-add"><input class="search-input" id="todo-title" placeholder="新增任务…"><select class="search-input" id="todo-project"><option value="">不关联项目</option>${projects.map(p=>`<option value="${esc(p)}">${esc(p)}</option>`).join('')}</select><input class="search-input" id="todo-due" type="date" value="${today()}"><select class="search-input" id="todo-priority"><option>普通</option><option>高</option><option>低</option></select><button class="primary-btn" id="todo-add">添加</button></div>
      <div style="margin-top:14px;border:1px solid var(--line);border-radius:9px;overflow:hidden">${items.length?items.map(todoRow).join(''):'<div class="empty">暂无任务</div>'}</div>
    </section>`;
    $('#todo-add').onclick=async()=>{ const title=$('#todo-title').value.trim(); if(!title)return; await api('/api/todos',{method:'POST',body:{title,project:$('#todo-project').value,due:$('#todo-due').value,priority:$('#todo-priority').value}}); toast('任务已添加'); renderTodos(); };
    $$('[data-todo-check]').forEach(x=>x.onchange=async()=>{await api('/api/todos/'+x.dataset.todoCheck,{method:'POST',body:{done:x.checked}});renderTodos();});
    $$('[data-todo-del]').forEach(x=>x.onclick=async()=>{if(confirm('删除该任务？')){await api('/api/todos/'+x.dataset.todoDel,{method:'DELETE'});renderTodos();}});
  }
  function todoRow(t){return `<div class="todo-row ${t.done?'done':''}"><input class="todo-check" type="checkbox" ${t.done?'checked':''} data-todo-check="${t.id}"><div><div class="todo-title">${esc(t.title)}</div><div class="row-meta">${esc(t.project||'未归属项目')}</div></div><div class="mono">${fmtDate(t.due)}</div><span class="badge ${t.priority==='高'?'warn':''}">${esc(t.priority)}</span><button class="ghost-btn danger" data-todo-del="${t.id}">删除</button></div>`}

  function renderFocus(){
    $('#main').innerHTML=`<section class="card focus-panel"><div class="card-kicker">FOCUS TIMER</div><h3>专注计时</h3><p class="focus-caption">专注与休息时长均可自定义，设置保存在当前浏览器。</p><div class="progress-ring" id="focus-ring"></div><div class="focus-time" id="focus-time">25:00</div><div class="focus-mode" id="focus-mode">专注 · 25 分钟</div>
      <div class="focus-duration-panel"><div class="focus-duration-grid"><label><span>专注时长</span><div><input id="focus-minutes" type="number" min="1" max="240" step="1" value="${state.focus.focusMinutes}"><em>分钟</em></div></label><label><span>休息时长</span><div><input id="break-minutes" type="number" min="1" max="120" step="1" value="${state.focus.breakMinutes}"><em>分钟</em></div></label><button class="secondary-btn" id="focus-apply">应用时长</button></div><div class="focus-presets"><span>快速预设</span>${[25,45,60,90].map(n=>`<button type="button" data-focus-preset="${n}">${n} min</button>`).join('')}</div></div>
      <div class="focus-actions"><button class="primary-btn" id="focus-start">开始</button><button class="secondary-btn" id="focus-reset">重置</button><button class="secondary-btn" id="focus-mode-btn">切换休息</button></div></section>`;
    paintFocus();
    $('#focus-start').onclick=()=>{ state.focus.running?pauseFocus():startFocus(); };
    $('#focus-reset').onclick=()=>resetFocus();
    $('#focus-mode-btn').onclick=()=>{ pauseFocus(); state.focus.mode=state.focus.mode==='专注'?'休息':'专注'; syncFocusModeDuration(); paintFocus(); };
    $('#focus-apply').onclick=()=>applyFocusDurations();
    $$('[data-focus-preset]').forEach(btn=>btn.onclick=()=>{ $('#focus-minutes').value=btn.dataset.focusPreset; applyFocusDurations(); });
  }
  function clampFocusMinutes(value,min,max,fallback){ const n=Math.round(Number(value)); return Number.isFinite(n)?Math.max(min,Math.min(max,n)):fallback; }
  function syncFocusModeDuration(){ state.focus.total=(state.focus.mode==='专注'?state.focus.focusMinutes:state.focus.breakMinutes)*60; state.focus.seconds=state.focus.total; }
  function applyFocusDurations(){
    const focus=clampFocusMinutes($('#focus-minutes')?.value,1,240,state.focus.focusMinutes);
    const rest=clampFocusMinutes($('#break-minutes')?.value,1,120,state.focus.breakMinutes);
    pauseFocus(); state.focus.focusMinutes=focus; state.focus.breakMinutes=rest;
    localStorage.setItem('focusMinutes',String(focus)); localStorage.setItem('breakMinutes',String(rest));
    if($('#focus-minutes')) $('#focus-minutes').value=focus; if($('#break-minutes')) $('#break-minutes').value=rest;
    syncFocusModeDuration(); paintFocus(); toast(`已设置：专注 ${focus} 分钟 · 休息 ${rest} 分钟`);
  }
  function paintFocus(){ const el=$('#focus-time'); if(!el)return; const s=state.focus.seconds; el.textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`; $('#focus-mode').textContent=`${state.focus.mode} · ${Math.round(state.focus.total/60)} 分钟`; $('#focus-start').textContent=state.focus.running?'暂停':'开始'; const deg=state.focus.total?Math.max(0,Math.min(360,(1-s/state.focus.total)*360)):0; $('#focus-ring').style.background=`conic-gradient(var(--accent) ${deg}deg,var(--surface-3) ${deg}deg)`; }
  function startFocus(){ if(state.focus.timer)return; state.focus.running=true; state.focus.timer=setInterval(()=>{state.focus.seconds=Math.max(0,state.focus.seconds-1);paintFocus();if(state.focus.seconds===0){pauseFocus();toast(`${state.focus.mode}计时完成`)}},1000);paintFocus(); }
  function pauseFocus(){clearInterval(state.focus.timer);state.focus.timer=null;state.focus.running=false;paintFocus();}
  function resetFocus(){pauseFocus();state.focus.seconds=state.focus.total;paintFocus();}


  async function openGlobalSearch(initial=''){
    modal('全局搜索',`<div class="global-search"><div class="global-search-box"><span>⌕</span><input id="global-search-input" autocomplete="off" placeholder="搜索灵感、日志、笔记、里程碑、总结、文献、待办与 Agent 对话…" value="${esc(initial)}"></div><div class="global-search-hint">支持标题、正文、标签、项目等全文匹配 · Ctrl/⌘ + K</div><div class="global-search-results" id="global-search-results"><div class="empty">输入关键词开始检索</div></div></div>`,'');
    const input=$('#global-search-input'); const run=debounce(async()=>{const q=input.value.trim();if(!q){$('#global-search-results').innerHTML='<div class="empty">输入关键词开始检索</div>';return}try{const rows=await api('/api/search?q='+encodeURIComponent(q));$('#global-search-results').innerHTML=rows.length?rows.map(searchResultRow).join(''):'<div class="empty">没有找到相关条目</div>';$$('[data-search-result]').forEach(b=>b.onclick=()=>openSearchResult(rows[+b.dataset.searchResult]));}catch(e){$('#global-search-results').innerHTML=`<div class="empty danger">${esc(e.message)}</div>`}},180);input.oninput=run;setTimeout(()=>input.focus(),20);if(initial)run();
  }
  function searchResultRow(r,i){const label=r.source==='chat'?'Agent 对话':r.source==='todo'?'待办':kindLabel(r.kind);return `<button class="global-search-row" type="button" data-search-result="${i}"><span class="global-search-kind">${esc(label)}</span><span class="global-search-copy"><strong>${esc(r.title||'未命名')}</strong><small>${esc(r.project||'')}${r.project?' · ':''}${esc(r.excerpt||'')}</small></span><span>↗</span></button>`}
  async function openSearchResult(r){closeModal();if(!r)return;if(r.source==='chat'){state.agentSession=r.id;await navigate('agent');return}if(r.source==='todo'){await navigate('todos');return}const route=routeForKind(r.kind);await navigate(route);setTimeout(()=>selectDoc(r.id),30)}

  async function renderAgent(){
    const sessions=await api('/api/agent/sessions');
    const llmCfg=state.config?.app?.llm||{};
    const requestPresets=Array.isArray(llmCfg.request_presets)&&llmCfg.request_presets.length?llmCfg.request_presets:[{id:'default',label:'默认（不附加参数）',params:{}},{id:'qwen-low',label:'Qwen · 低思考',params:{enable_thinking:true,thinking_budget:1024}},{id:'qwen-off',label:'Qwen · 无思考',params:{enable_thinking:false}}];
    if(!requestPresets.some(x=>String(x.id||'')===state.agentPreset)) state.agentPreset=String(llmCfg.default_request_preset||requestPresets[0].id||'default');
    const requestPresetHtml=requestPresets.map(x=>`<option value="${esc(x.id||'default')}" ${String(x.id||'')===state.agentPreset?'selected':''}>${esc(x.label||x.id||'默认')}</option>`).join('');
    if(state.agentSession&&!sessions.some(x=>x.id===state.agentSession))state.agentSession=null;
    if(!state.agentSession&&sessions.length)state.agentSession=sessions[0].id;
    $('#main').innerHTML=`<div class="agent-layout"><aside class="card agent-sessions"><div class="agent-side-head"><div><div class="card-kicker">LOCAL CHAT HISTORY</div><h3>Agent 对话</h3></div><button class="primary-btn" id="agent-new">＋</button></div><div class="agent-session-list">${sessions.length?sessions.map(x=>`<button type="button" class="agent-session ${x.id===state.agentSession?'active':''}" data-agent-session="${x.id}"><strong>${esc(x.title)}</strong><small>${esc(fmtTime(x.updated))} · ${x.message_count||0} 条</small></button>`).join(''):'<div class="empty compact">暂无对话</div>'}</div></aside><section class="card agent-chat"><div class="agent-chat-head"><div><div class="card-kicker">RESEARCH AGENT</div><h3 id="agent-chat-title">科研 Agent</h3></div><div class="agent-head-actions"><button class="secondary-btn" id="agent-ref">＋ 引用研究 · 知识</button><button class="ghost-btn danger" id="agent-delete" ${state.agentSession?'':'disabled'}>删除对话</button></div></div><div class="agent-messages" id="agent-messages"><div class="empty">${state.agentSession?'正在载入对话…':'新建一个对话开始'}</div></div><div class="agent-context-strip" id="agent-context-strip"></div><div class="agent-composer"><div class="agent-image-strip" id="agent-image-strip"></div><textarea id="agent-input" placeholder="向科研 Agent 提问。可粘贴/拖入图片，或手动引用研究 · 知识中的 Markdown…"></textarea><div class="agent-compose-actions"><div class="agent-compose-left"><button class="ghost-btn" id="agent-image">▧ 图片</button><label class="agent-preset-label">请求模式 <select class="search-input agent-preset-select" id="agent-preset">${requestPresetHtml}</select></label><span class="row-meta">Enter 发送 · Shift+Enter 换行</span></div><button class="primary-btn" id="agent-send">发送</button></div></div></section></div>`;
    $('#agent-new').onclick=async()=>{const s=await api('/api/agent/sessions',{method:'POST',body:{}});state.agentSession=s.id;state.agentRefs=[];state.agentImages=[];renderAgent()};
    $$('[data-agent-session]').forEach(b=>b.onclick=()=>{state.agentSession=b.dataset.agentSession;state.agentRefs=[];state.agentImages=[];renderAgent()});
    $('#agent-ref').onclick=openAgentReferencePicker;$('#agent-image').onclick=pickAgentImage;$('#agent-delete').onclick=async()=>{if(state.agentSession&&confirm('将该对话移入 Trash？')){await api('/api/agent/sessions/'+encodeURIComponent(state.agentSession),{method:'DELETE'});state.agentSession=null;renderAgent()}};
    const input=$('#agent-input');input.addEventListener('paste',onAgentPasteImage);input.addEventListener('dragover',e=>e.preventDefault());input.addEventListener('drop',onAgentDropImage);input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();sendAgentMessage()}});$('#agent-send').onclick=sendAgentMessage;const presetSelect=$('#agent-preset');if(presetSelect)presetSelect.onchange=()=>{state.agentPreset=presetSelect.value;localStorage.setItem('agentRequestPreset',state.agentPreset)};
    paintAgentContext(); paintAgentImages(); if(state.agentSession)await loadAgentSession(state.agentSession);
  }
  async function loadAgentSession(id){try{const s=await api('/api/agent/sessions/'+encodeURIComponent(id));if(state.route!=='agent'||state.agentSession!==id)return;$('#agent-chat-title').textContent=s.title||'科研 Agent';const root=$('#agent-messages');root.innerHTML=(s.messages||[]).length?(s.messages||[]).map(agentMessageHtml).join(''):'<div class="empty">暂无消息。你可以直接提问，或先引用研究资料。</div>';for(const el of $$('.agent-message-body',root))await renderMarkdownInto(el,el.dataset.raw||'');for(const el of $$('.agent-reasoning-body',root))await renderMarkdownInto(el,el.dataset.raw||'');root.scrollTop=root.scrollHeight}catch(e){toast(e.message,true)}}
  function agentMessageHtml(m){const refs=(m.refs||[]).map(r=>`<span class="badge">${esc(r.title)}</span>`).join('');const imgs=(m.images||[]).map(p=>`<img src="/workspace-file/${esc(typeof p==='string'?p:(p.path||''))}" alt="对话图片">`).join('');const showReasoning=state.config?.app?.llm?.show_reasoning!==false;const reasoning=showReasoning&&String(m.reasoning||'').trim()?`<details class="agent-reasoning"><summary>模型思考过程</summary><div class="agent-reasoning-body" data-raw="${esc(m.reasoning||'')}"></div></details>`:'';return `<article class="agent-message ${m.role==='assistant'?'assistant':'user'}"><div class="agent-avatar">${m.role==='assistant'?'AI':'YOU'}</div><div class="agent-bubble">${refs?`<div class="agent-msg-refs">${refs}</div>`:''}${imgs?`<div class="agent-msg-images">${imgs}</div>`:''}${reasoning}<div class="agent-message-body" data-raw="${esc(m.content||'')}"></div><div class="agent-msg-meta">${esc(m.model||'')}${m.request_preset_label?` · ${esc(m.request_preset_label)}`:''} · ${esc(fmtTime(m.created))}</div></div></article>`}
  async function renderMarkdownInto(out,raw){const seq=++state.previewSeq;let html='';if(window.marked&&window.DOMPurify){const renderer=new marked.Renderer();renderer.code=(tokenOrCode,info)=>{let code='',lang='';if(tokenOrCode&&typeof tokenOrCode==='object'){code=tokenOrCode.text||'';lang=tokenOrCode.lang||''}else{code=String(tokenOrCode||'');lang=String(info||'')}lang=lang.trim();if(lang==='mermaid')return `<div class="mermaid">${esc(code)}</div>`;return `<pre><code class="language-${esc(lang)}">${esc(code)}</code></pre>`};try{html=marked.parse(raw||'',{gfm:true,renderer})}catch{html=basicMarkdown(raw)}}else html=basicMarkdown(raw);out.innerHTML=window.DOMPurify?DOMPurify.sanitize(html,{ADD_TAGS:['mjx-container']}):html;$$('pre code',out).forEach(el=>{try{window.hljs?.highlightElement(el)}catch{}});await renderMermaidBlocks(out,seq);if(window.MathJax?.typesetPromise){try{await MathJax.typesetPromise([out])}catch{}}}
  function paintAgentContext(){const root=$('#agent-context-strip');if(!root)return;root.innerHTML=state.agentRefs.length?`<span class="row-meta">已引用</span>${state.agentRefs.map((r,i)=>`<button type="button" class="context-chip" data-ref-remove="${i}">${esc(r.title)}</button>`).join('')}`:'<span class="row-meta">未引用本地知识；点击“引用研究 · 知识”可手动选择上下文。</span>';$$('[data-ref-remove]',root).forEach(b=>b.onclick=()=>{state.agentRefs.splice(+b.dataset.refRemove,1);paintAgentContext()})}
  function paintAgentImages(){const root=$('#agent-image-strip');if(!root)return;root.innerHTML=state.agentImages.map((x,i)=>`<div class="agent-image-thumb"><img src="${esc(x.url)}"><button type="button" data-agent-image-remove="${i}">×</button></div>`).join('');$$('[data-agent-image-remove]',root).forEach(b=>b.onclick=()=>{state.agentImages.splice(+b.dataset.agentImageRemove,1);paintAgentImages()})}
  async function openAgentReferencePicker(){modal('引用研究 · 知识',`<div class="global-search"><div class="global-search-box"><span>⌕</span><input id="agent-ref-search" placeholder="搜索要引用的 Markdown 条目…"></div><div class="row-meta" style="margin:8px 0">只会把你最终勾选的条目发送给模型。</div><div class="agent-ref-results" id="agent-ref-results"><div class="empty">输入关键词检索研究资料</div></div></div>`,`<button class="secondary-btn" id="agent-ref-cancel">取消</button><button class="primary-btn" id="agent-ref-done">引用所选</button>`);let rows=[];const selected=new Map(state.agentRefs.map(x=>[x.id,x]));const run=debounce(async()=>{const q=$('#agent-ref-search').value.trim();if(!q){$('#agent-ref-results').innerHTML='<div class="empty">输入关键词检索研究资料</div>';return}rows=(await api('/api/docs?q='+encodeURIComponent(q))).slice(0,50);$('#agent-ref-results').innerHTML=rows.length?rows.map(x=>`<label class="bundle-item"><input type="checkbox" data-ref-id="${x.id}" ${selected.has(x.id)?'checked':''}><span class="badge">${esc(KIND_LABEL[x.kind]||x.kind)}</span><span><strong>${esc(x.title)}</strong><br><span class="row-meta">${esc(x.project||'未归属项目')} · ${esc(x.excerpt||'')}</span></span></label>`).join(''):'<div class="empty">未找到条目</div>';$$('[data-ref-id]').forEach(c=>c.onchange=()=>{const d=rows.find(x=>x.id===c.dataset.refId);if(c.checked&&d)selected.set(d.id,{id:d.id,title:d.title,kind:d.kind,project:d.project||''});else selected.delete(c.dataset.refId)})},180);$('#agent-ref-search').oninput=run;$('#agent-ref-cancel').onclick=closeModal;$('#agent-ref-done').onclick=()=>{state.agentRefs=[...selected.values()];closeModal();paintAgentContext()};setTimeout(()=>$('#agent-ref-search').focus(),20)}
  function pickAgentImage(){const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif';input.multiple=true;input.onchange=()=>[...input.files].slice(0,6).forEach(uploadAgentFile);input.click()}
  async function uploadAgentFile(file){if(!file?.type?.startsWith('image/'))return;const data=await readAsDataUrl(file);try{const r=await api('/api/agent/assets',{method:'POST',body:{data_url:data,name:file.name}});state.agentImages.push(r);paintAgentImages()}catch(e){toast(e.message,true)}}
  function onAgentPasteImage(e){const files=[...e.clipboardData.items].filter(i=>i.kind==='file').map(i=>i.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();files.slice(0,6).forEach(uploadAgentFile)}}
  function onAgentDropImage(e){e.preventDefault();[...e.dataTransfer.files].filter(f=>f.type.startsWith('image/')).slice(0,6).forEach(uploadAgentFile)}
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
      try{const r=await api('/api/agent/send',{method:'POST',body:{session_id:state.agentSession,message:text,refs:refs.map(x=>x.id),images:images.map(x=>x.path),request_preset:preset}});state.agentSession=r.session.id;clearInterval(timer);await renderAgent()}catch(e){clearInterval(timer);$('#agent-thinking')?.remove();if(root){root.insertAdjacentHTML('beforeend',`<article class="agent-message assistant"><div class="agent-avatar">AI</div><div class="agent-bubble"><div class="agent-error">请求失败：${esc(e.message)}</div></div></article>`);root.scrollTop=root.scrollHeight}toast(e.message,true)}
    }finally{state.agentSending=false;const b=$('#agent-send');if(b){b.disabled=false;b.textContent='发送'}}
  }

  async function renderNews(){
    $('#main').innerHTML=`<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">RSS / INFORMATION</div><h3>资讯</h3></div><button class="secondary-btn" id="news-refresh">强制刷新</button></div><div class="empty">正在抓取资讯源…</div></div>`;
    async function load(force=false){
      try { const data=await api('/api/rss'+(force?'?force=1':''));
        if(state.route!=='news')return;
        const render=()=>{ /* v260923 · 资讯源卡片即筛选标签：点击只看该源文章，再点或点「全部」恢复 */
          const filter=localStorage.getItem('newsFilter')||'';
          const sources=data.sources||[];
          const total=data.items?.length||0;
          const statusHtml=sources.length?`<div class="rss-status-grid"><div class="rss-status ${!filter?'ok active':'ok pickable'}" data-news-src="" title="显示全部资讯源"><strong>≡ 全部</strong><span>${total} 条</span></div>${sources.map(x=>{
            const pickable=x.ok&&(x.count||0)>0;
            const sel=filter&&filter===x.source?' active':'';
            return `<div class="rss-status ${pickable?'ok pickable':(x.ok?'ok':'bad')}${sel}"${pickable?` data-news-src="${esc(x.source)}" title="点击只看该资讯源的文章"`:''}><strong>${x.ok?'✓':'!'} ${esc(x.source||'RSS')}</strong><span>${x.ok?`${x.count||0} 条${x.fallback?' · 已启用备用接口':''}`:esc(x.error||'获取失败')}</span></div>`;
          }).join('')}</div>`:'';
          const stale=data.stale?`<div class="rss-alert warn"><strong>当前显示缓存内容</strong><span>本次强制刷新未能访问任何资讯源；旧内容没有被空结果覆盖。</span></div>`:'';
          const failure=!data.items?.length&&data.errors?.length?`<div class="rss-alert danger"><strong>资讯源全部获取失败</strong><span>这通常是网络 / DNS / 代理或源站连接问题。空失败结果不会再缓存，下一次强制刷新会立即重试。</span><details><summary>查看诊断</summary>${data.errors.map(e=>`<div class="rss-error"><b>${esc(e.source||'')}</b><code>${esc(e.error||'')}</code>${(e.attempts||[]).map(a=>`<small>${esc(a)}</small>`).join('')}</div>`).join('')}</details></div>`:'';
          const items=(data.items||[]).filter(n=>!filter||n.source===filter);
          $('#main').innerHTML=`<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">RSS / INFORMATION</div><h3>资讯</h3><div class="row-meta">${data.stale?'缓存更新':'最近抓取'} ${fmtTime(data.updated||data.refresh_failed_at)}${filter?` · 只看「${esc(filter)}」`:''}</div></div><div style="display:flex;gap:8px"><button class="secondary-btn" id="news-settings">资讯源设置</button><button class="primary-btn" id="news-refresh">强制刷新</button></div></div>${stale}${failure}${statusHtml}<div class="news-grid">${items.length?items.map(n=>`<article class="card news-card"><div class="news-meta">${esc(n.source)} · ${esc(n.published||'')}</div><h3><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></h3><p>${esc(n.summary||'')}</p></article>`).join(''):`<div class="empty">${filter?'该资讯源暂无条目，点击上方「≡ 全部」查看其他内容。':'当前没有可显示的资讯。请查看上方源状态与诊断信息。'}</div>`}</div></div>`;
          $$('#main .rss-status[data-news-src]').forEach(el=>el.onclick=()=>{const cur=localStorage.getItem('newsFilter')||'';localStorage.setItem('newsFilter',cur===el.dataset.newsSrc?'':el.dataset.newsSrc);render();});
          $('#news-refresh').onclick=()=>load(true);$('#news-settings').onclick=async()=>{await navigate('settings');setTimeout(()=>document.querySelector('[data-set-tab="rss"]')?.click(),40)};
        };
        render();
      } catch(e){ if(state.route!=='news')return; $('#main').innerHTML=`<div class="card card-pad"><div class="card-head"><h3>资讯</h3><button class="secondary-btn" id="news-refresh">重试</button></div><div class="rss-alert danger"><strong>资讯接口调用失败</strong><span>${esc(e.message)}</span></div></div>`; $('#news-refresh').onclick=()=>load(true); }
    }
    load(false);
  }

  async function renderResearchOverview(){
    const [dash,g]=await Promise.all([api('/api/dashboard'),api('/api/graph')]); state.graph=g;
    $('#main').innerHTML=`<div class="research-overview">
      <div class="recent-cards">${recentCard('最近灵感',dash.recent.ideas,'ideas')}${recentCard('最近笔记',dash.recent.notes,'notes')}${recentCard('最近工作总结',dash.recent.summaries,'summaries')}</div>
      <div class="overview-split">
        <section class="card card-pad"><div class="card-head"><div><div class="card-kicker">TIMELINE</div><h3>近期里程碑</h3></div><button class="ghost-btn" data-go="milestones">全部</button></div>${milestoneTimelineHtml(dash.upcoming_milestones,true)}</section>
        <section class="card card-pad"><div class="card-head"><div><div class="card-kicker">KNOWLEDGE GRAPH</div><h3>知识关系预览</h3></div><button class="ghost-btn" data-go="graph">完整图谱</button></div><div class="graph-canvas-wrap mini-graph"><canvas class="graph-canvas" id="overview-graph"></canvas></div></section>
      </div>
    </div>`;
    wireGo(); requestAnimationFrame(()=>drawGraph($('#overview-graph'),g,{interactive:true,mini:true,onSelect:(n)=>openGraphBundleFromNode(n)}));
  }

  async function renderDocsPage(kind){
    const [docs,projects] = await Promise.all([api('/api/docs?kind='+encodeURIComponent(kind)), api('/api/projects')]); state.docs=docs; state.projects=projects; state.selectedDoc=null;
    if(kind==='milestone') return renderMilestoneShell(docs,projects);
    $('#main').innerHTML=docsShell(kind,docs,projects);
    wireDocList(kind); wireDocFilters(kind); $('#new-doc').onclick=()=>createAndSelect(kind);
    if(kind==='literature') $('#export-bib').onclick=exportBibtex;
    if(docs.length) selectDoc(docs[0].id); else showEmptyEditor(kind);
  }
  function docsShell(kind,docs,projects){return `<div class="docs-layout"><aside class="card doc-list-panel"><div class="doc-filter"><div style="display:flex;gap:6px"><input class="search-input" id="doc-search" placeholder="搜索标题、正文、标签、项目、分类…"><button class="secondary-btn" id="new-doc">＋</button></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:6px"><select class="search-input" id="doc-status"><option value="">全部状态</option>${(state.statuses[kind]||[]).map(s=>`<option>${esc(s)}</option>`).join('')}</select><select class="search-input" id="doc-project"><option value="">全部项目</option>${projects.map(p=>`<option>${esc(p)}</option>`).join('')}</select><select class="search-input" id="doc-mark" style="grid-column:span 2"><option value="">全部分类</option>${allMarks().map(k=>`<option value="${esc(k.id)}">${esc(k.icon)} ${esc(k.label)}</option>`).join('')}</select></div>${kind==='literature'?'<button class="secondary-btn" id="export-bib">批量导出 BibTeX</button>':''}</div><div class="doc-list" id="doc-list">${docItems(docs)}</div></aside><section class="card doc-editor empty-editor" id="doc-editor"></section></div>`}
  function markBadges(d){return (d.kind_marks||[]).slice(0,4).map(id=>{const c=allMarks().find(k=>k.id===id);if(!c)return '';const col=esc(c.color);return `<span class="badge mark-badge" style="color:${col};border-color:${col};background:${col}1a">${esc(c.icon)} ${esc(c.label)}</span>`}).join('')}
  /* v260923 · 分类标记 chips 渲染 / 事件 / 重渲染（含「＋ 自定义」入口） */
  function markChipsHtml(selected){return allMarks().map(k=>`<button type="button" class="mark-chip${(selected||[]).includes(k.id)?' on':''}" data-mark="${esc(k.id)}" style="--mark-color:${esc(k.color)}" title="点击标记为${esc(k.label)}，可多选">${esc(k.icon)} ${esc(k.label)}</button>`).join('')+'<button type="button" class="mark-chip add-mark" id="f-mark-add" title="添加自定义标记">＋ 自定义</button>'}
  function wireMarkChips(){
    $$('#f-marks .mark-chip:not(.add-mark)').forEach(b=>b.onclick=()=>{b.classList.toggle('on');state.dirty=true});
    const add=$('#f-mark-add'); if(add)add.onclick=openMarkManager;
  }
  function refreshMarkChips(){
    const box=$('#f-marks'); if(!box)return;
    const on=$$('#f-marks .mark-chip.on').map(b=>b.dataset.mark);
    const saved=(state.selectedDoc&&state.selectedDoc.kind_marks)||[];
    box.innerHTML=markChipsHtml([...new Set([...on,...saved])]);
    wireMarkChips();
  }
  function openMarkManager(){
    const ICON_CHOICES=['★','✦','◆','●','■','▲','◈','◎','⚑','✿','☾','⚗']; /* v260923 · 预设标记形状 */
    const renderList=()=>{
      const list=customMarks();
      $('#f-mark-manage-list').innerHTML=list.length?list.map(m=>`<span class="mark-chip" style="--mark-color:${esc(m.color)}">${esc(m.icon)} ${esc(m.label)}<button type="button" class="mark-del" data-del="${esc(m.id)}" title="删除该标记">×</button></span>`).join(''):'<span class="row-meta">暂无自定义标记</span>';
      $$('#f-mark-manage-list .mark-del').forEach(b=>b.onclick=()=>{
        const m=customMarks().find(x=>x.id===b.dataset.del);
        if(m&&!confirm(`删除自定义标记「${m.label}」？已打标的内容将不再显示该标记。`))return;
        saveCustomMarks(customMarks().filter(x=>x.id!==b.dataset.del)); toast('已删除'); refreshMarkChips(); renderList();
      });
    };
    modal('自定义分类标记',`<div class="row-meta" style="margin-bottom:12px">选择形状、填写名称并挑一个颜色；标记保存在本浏览器，可在所有文档类型中使用与筛选。</div><div class="mark-icon-pick" id="f-mark-icon-pick" style="margin-bottom:12px">${ICON_CHOICES.map((ic,i)=>`<button type="button"${i===0?' class="on"':''} data-icon="${ic}">${ic}</button>`).join('')}</div><div class="mark-mgr-row" style="margin-bottom:12px"><input id="f-mark-label" class="mark-name" maxlength="8" placeholder="名称，如：思路"><label class="color-swatch" title="颜色"><input id="f-mark-color" type="color" value="#4a6fa5"><span id="f-mark-color-dot" style="background:#4a6fa5"></span></label><button class="primary-btn" id="f-mark-save">添加</button></div><div class="mark-chip-box" id="f-mark-manage-list"></div>`,`<button class="secondary-btn" id="mark-mgr-close">关闭</button>`);
    $('#mark-mgr-close').onclick=closeModal;
    $$('#f-mark-icon-pick button').forEach(b=>b.onclick=()=>$$('#f-mark-icon-pick button').forEach(x=>x.classList.toggle('on',x===b)));
    $('#f-mark-color').oninput=e=>{$('#f-mark-color-dot').style.background=e.target.value};
    $('#f-mark-save').onclick=()=>{
      const label=$('#f-mark-label').value.trim();
      if(!label){toast('请填写标记名称',true);return;}
      const marks=customMarks();
      if(marks.some(m=>m.label===label)||KIND_MARKS.some(m=>m.label===label)){toast('该名称已存在',true);return;}
      if(marks.length>=8){toast('自定义标记最多 8 个',true);return;}
      const picked=$('#f-mark-icon-pick button.on');
      marks.push({id:'c_'+Date.now().toString(36),icon:(picked&&picked.dataset.icon)||'★',label,color:$('#f-mark-color').value});
      saveCustomMarks(marks); toast(`已添加「${label}」`); refreshMarkChips(); renderList();
    };
    renderList();
  }
  /* v260923 · 笔记卡片格式统一：状态/分类一行；时间与项目名同排，项目名过长固定宽度省略 */
  function docItems(docs){return docs.length?docs.map(d=>{const projBadges=(d.projects||[]).map(p=>`<span class="badge accent proj-badge"><span class="proj-text">${esc(p)}</span></span>`).join('')||(d.project?`<span class="badge accent proj-badge"><span class="proj-text">${esc(d.project)}</span></span>`:'');const dateB=dateBadge(d);const projRow=(projBadges||dateB)?`<div class="doc-projects">${projBadges}${dateB}</div>`:'';return `<article class="doc-item" data-doc-id="${d.id}"><div class="title">${esc(d.title)}</div><div class="excerpt">${esc(d.excerpt||'')}</div><div class="tags"><span class="badge">${esc(d.status||'')}</span>${markBadges(d)}</div>${projRow}</article>`}).join(''):'<div class="empty" style="min-height:140px">暂无内容</div>'}
  function dateBadge(d){ const val=d.due||d.record_date||d.added_date; if(val)return `<span class="badge mono">${fmtDate(val)}</span>`; return d.updated?`<span class="badge mono" title="更新时间">更新 ${fmtDate(d.updated)}</span>`:''; }
  function wireDocList(kind){ $$('[data-doc-id]').forEach(x=>x.onclick=()=>selectDoc(x.dataset.docId)); }
  function wireDocFilters(kind){ const run=debounce(async()=>{const q=$('#doc-search').value,status=$('#doc-status').value,project=$('#doc-project').value,mark=$('#doc-mark')?.value||'';const url=`/api/docs?kind=${kind}&q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}&project=${encodeURIComponent(project)}&mark=${encodeURIComponent(mark)}`;state.docs=await api(url);$('#doc-list').innerHTML=docItems(state.docs);wireDocList(kind);},180); $('#doc-search').oninput=run;$('#doc-status').onchange=run;$('#doc-project').onchange=run;if($('#doc-mark'))$('#doc-mark').onchange=run; }
  async function createAndSelect(kind){ const doc=await api('/api/docs',{method:'POST',body:{kind,title:`未命名${kindLabel(kind)}`}}); await renderDocsPage(kind); setTimeout(()=>selectDoc(doc.id),10); }
  function showEmptyEditor(kind){ $('#doc-editor').className='card doc-editor empty-editor'; $('#doc-editor').innerHTML=`<div class="empty"><div><div class="empty-symbol">${esc(kindLabel(kind).toUpperCase())}</div>选择一条${kindLabel(kind)}，或点击左侧 ＋ 新建</div></div>`; }
  async function selectDoc(id){
    if(state.dirty && !confirm('当前 Markdown 有未保存修改，确定切换吗？'))return;
    state.dirty=false; const doc=await api('/api/docs/'+encodeURIComponent(id)); state.selectedDoc=doc;
    $$('[data-doc-id]').forEach(x=>x.classList.toggle('active',x.dataset.docId===id));
    renderDocEditor(doc);
  }
  function renderDocEditor(doc){
    const kind=doc.kind, special=kind==='literature';
    const dateField=kind==='milestone'?'due':(kind==='summary'||kind==='journal'?'record_date':kind==='literature'?'added_date':'');
    $('#doc-editor').className='card doc-editor';
    const tagsSpan=special||kind==='summary'?'span-4':(dateField?'span-2':'span-3');
    $('#doc-editor').innerHTML=`<div class="form-grid">
      <div class="field span-2"><label>标题</label><input id="f-title" value="${esc(doc.title)}"></div>
      <div class="field span-2"><div class="field-label-row"><label>项目</label><span class="field-help">默认为空；点击 ＋ 从已有项目中勾选，可同时关联多个项目。</span></div><div class="project-picker-row"><div class="project-chip-box" id="f-projects" data-projects="${esc(JSON.stringify(doc.projects||[]))}"></div><button type="button" class="secondary-btn project-add-btn" id="f-project-add" title="从已有项目中添加">＋</button></div></div>
      <div class="field"><label>状态</label><select id="f-status">${(state.statuses[kind]||[]).map(s=>`<option ${s===doc.status?'selected':''}>${esc(s)}</option>`).join('')}</select></div>
      ${dateField?`<div class="field"><label>${dateField==='due'?'截止日期':'日期'}</label><input id="f-date" type="date" value="${esc(doc[dateField]||today())}"></div>`:''}
      ${kind==='summary'?`<div class="field"><label>总结类型</label><select id="f-summary-type">${['日总结','周总结','月总结','阶段总结'].map(s=>`<option ${s===doc.summary_type?'selected':''}>${s}</option>`).join('')}</select></div>`:''}
      ${special?literatureFields(doc):''}
      <div class="field ${tagsSpan}"><div class="field-label-row"><label>标签</label><span class="field-help">点击 ＋ 添加：可勾选已有标签或输入新标签。</span></div><div class="project-picker-row"><div class="project-chip-box" id="f-tags" data-tags="${esc(JSON.stringify(doc.tags||[]))}"></div><button type="button" class="secondary-btn project-add-btn" id="f-tag-add" title="添加标签">＋</button></div></div>
      <div class="field span-4"><label>分类标记</label><div class="mark-chip-box" id="f-marks">${markChipsHtml(doc.kind_marks||[])}</div></div>
    </div>
    <div class="editor-wrap">${editorHtml(doc.body||'')}</div>
    <div class="editor-actions"><span class="row-meta">${esc(doc.path)} · 更新 ${fmtTime(doc.updated)}</span><div class="right"><button class="secondary-btn" id="doc-delete">删除</button><button class="primary-btn" id="doc-save">保存</button></div></div>`;
    wireEditor();
    ['f-title','f-status','f-date','f-summary-type','f-authors','f-year','f-venue','f-doi','f-url','f-cite-key','f-bibtex'].forEach(id=>{const el=$('#'+id);if(el)el.addEventListener('input',()=>state.dirty=true)});
    paintEditorProjects(doc.projects||[]); $('#f-project-add').onclick=openEditorProjectPicker;
    paintEditorTags(doc.tags||[]); $('#f-tag-add').onclick=openEditorTagPicker;
    wireMarkChips();
    $('#doc-save').onclick=()=>saveCurrentDoc(doc,dateField); $('#doc-delete').onclick=()=>deleteCurrentDoc(doc);
    renderMarkdownPreview();
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
  function openEditorTagPicker(){
    const selected=new Set(editorTags());
    let query=''; /* v260923 · 搜索与新建合并：输入即过滤，回车选中已有或创建新标签 */
    const allKnown=()=>[...new Set(state.docs.flatMap(d=>d.tags||[]))];
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
    $('#tag-pick-done').onclick=()=>{const list=$$('[data-tag-pick]:checked').map(x=>x.dataset.tagPick);paintEditorTags(list);state.dirty=true;closeModal()};
    renderList();
  }
  function openEditorProjectPicker(){
    const selected=new Set(editorProjects());
    modal('添加已有项目',`<div class="row-meta" style="margin-bottom:10px">勾选要关联到当前条目的已有项目。项目本身请在概览“项目推进”或资源页创建。</div><div class="project-pick-list">${state.projects.length?state.projects.map(p=>`<label class="bundle-item"><input type="checkbox" data-project-pick="${esc(p)}" ${selected.has(p)?'checked':''}><span><strong>${esc(p)}</strong></span></label>`).join(''):'<div class="empty">暂无已有项目，请先新建项目。</div>'}</div>`,`<button class="secondary-btn" id="project-pick-new">＋ 新建项目</button><button class="secondary-btn" id="project-pick-cancel">取消</button><button class="primary-btn" id="project-pick-done">应用</button>`);
    $('#project-pick-cancel').onclick=closeModal;
    $('#project-pick-new').onclick=()=>openCreateProjectModal(async()=>{state.projects=await api('/api/projects');openEditorProjectPicker()});
    $('#project-pick-done').onclick=()=>{const list=$$('[data-project-pick]:checked').map(x=>x.dataset.projectPick);paintEditorProjects(list);state.dirty=true;closeModal()};
  }

  function literatureFields(d){return `<div class="field span-2"><label>作者</label><input id="f-authors" value="${esc(d.authors||'')}"></div><div class="field"><label>年份</label><input id="f-year" value="${esc(d.year||'')}"></div><div class="field"><label>引用键 Cite Key</label><input id="f-cite-key" value="${esc(d.cite_key||'')}"></div><div class="field span-2"><label>期刊 / 会议</label><input id="f-venue" value="${esc(d.venue||'')}"></div><div class="field"><label>DOI</label><input id="f-doi" value="${esc(d.doi||'')}"></div><div class="field"><label>URL</label><input id="f-url" value="${esc(d.url||'')}"></div><div class="field span-4"><label>BibTeX（会与正文中的 bibtex 代码块同步）</label><textarea id="f-bibtex" class="mono bibtex-input" placeholder="@article{...}">${esc(d.bibtex||'')}</textarea></div>`}
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
    const bib=$('#f-bibtex'); let syncingBib=false;
    ta.addEventListener('input',()=>{state.dirty=true;if(bib&&!syncingBib){const m=ta.value.match(/```bibtex\s*\n([\s\S]*?)```/i);if(m&&bib.value.trim()!==m[1].trim()){syncingBib=true;bib.value=m[1].trim();syncingBib=false;}}debouncedPreview();});
    if(bib)bib.addEventListener('input',()=>{if(syncingBib)return;syncingBib=true;const block='```bibtex\n'+bib.value.trim()+'\n```';if(/```bibtex\s*\n[\s\S]*?```/i.test(ta.value))ta.value=ta.value.replace(/```bibtex\s*\n[\s\S]*?```/i,block);else ta.value='## BibTeX\n\n'+block+'\n\n'+ta.value;syncingBib=false;state.dirty=true;debouncedPreview();});
    ta.addEventListener('paste',onPasteImage); ta.addEventListener('dragover',e=>e.preventDefault()); ta.addEventListener('drop',onDropImage);
    $$('[data-edit-mode]').forEach(b=>b.onclick=()=>{state.editorMode=b.dataset.editMode; const p=$('#editor-pane');p.className='editor-pane '+(state.editorMode==='edit'?'edit-only':state.editorMode==='preview'?'preview-only':'');$$('[data-edit-mode]').forEach(x=>x.classList.toggle('active',x.dataset.editMode===state.editorMode)); if(state.editorMode!=='edit')renderMarkdownPreview();});
    $$('[data-md]').forEach(b=>b.onclick=()=>applyMdCommand(b.dataset.md));
  }
  const debouncedPreview=debounce(renderMarkdownPreview,250);
  function normalizePreviewPaths(html){
    return html
      .replace(/(src|href)="\.\.\/Attachments\//g, '$1="/workspace-file/Knowledge/Attachments/')
      .replace(/(src|href)="\.\.\/\.\.\/Attachments\//g, '$1="/workspace-file/Knowledge/Attachments/');
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
    if(!window.mermaid){nodes.forEach(n=>{n.className='mermaid-error';n.textContent='Mermaid 渲染库暂未加载。联网后 Reload 页面即可恢复图形渲染；Markdown 源码不会丢失。\n\n'+n.textContent;});return;}
    try{mermaid.initialize({startOnLoad:false,theme:document.documentElement.dataset.theme==='dark'?'dark':'default',securityLevel:'strict',fontFamily:'Microsoft YaHei, 微软雅黑, sans-serif'});}catch(e){console.warn(e)}
    for(let i=0;i<nodes.length;i++){
      const node=nodes[i],code=node.textContent.trim(); if(!code)continue;
      try{const id=`erw-mermaid-${seq}-${i}-${Date.now()}`;const result=await mermaid.render(id,code);if(seq!==state.previewSeq||!document.body.contains(out))return;node.innerHTML=result.svg;result.bindFunctions?.(node);}
      catch(e){console.warn('Mermaid render failed',e);node.className='mermaid-error';node.textContent=`Mermaid 渲染失败：${e?.message||e}\n\n${code}`;}
    }
  }

  async function renderMarkdownPreview(){
    const ta=$('#md-input'), out=$('#md-preview'); if(!ta||!out)return; const seq=++state.previewSeq; const raw=ta.value;
    let html='';
    if(window.marked && window.DOMPurify){
      const renderer=new marked.Renderer();
      renderer.code=(tokenOrCode,info)=>{let code='',lang='';if(tokenOrCode&&typeof tokenOrCode==='object'){code=tokenOrCode.text||'';lang=tokenOrCode.lang||'';}else{code=String(tokenOrCode||'');lang=String(info||'');}lang=lang.trim();if(lang==='mermaid')return `<div class="mermaid">${esc(code)}</div>`;return `<pre><code class="language-${esc(lang)}">${esc(code)}</code></pre>`;};
      try{html=marked.parse(raw,{gfm:true,breaks:false,renderer});}catch(e){console.warn('marked failed, fallback',e);html=basicMarkdown(raw);}
    } else html=basicMarkdown(raw);
    html=html.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(_,target,label)=>`<a href="#" class="wiki-link" data-wiki="${esc(target)}">${esc(label||target)}</a>`);
    html=normalizePreviewPaths(html);
    if(seq!==state.previewSeq||!document.body.contains(out))return;
    out.innerHTML=window.DOMPurify?DOMPurify.sanitize(html,{ADD_ATTR:['target','rel','data-wiki','checked','disabled'],ADD_TAGS:['mjx-container']}):html;
    $$('pre code',out).forEach(el=>{try{window.hljs?.highlightElement(el)}catch{}});
    await renderMermaidBlocks(out,seq);
    if(seq!==state.previewSeq||!document.body.contains(out))return;
    if(window.MathJax?.typesetPromise){try{MathJax.typesetClear?.([out]);await MathJax.typesetPromise([out])}catch(e){console.warn(e)}}
    if(seq!==state.previewSeq||!document.body.contains(out))return;
    $$('.wiki-link',out).forEach(a=>a.onclick=async e=>{e.preventDefault();const q=a.dataset.wiki;const results=await api('/api/docs?q='+encodeURIComponent(q));const exact=results.find(x=>x.id===q||x.title===q)||results[0];if(exact){const r=routeForKind(exact.kind);await navigate(r);setTimeout(()=>selectDoc(exact.id),10)}else toast(`未找到双链：${q}`,true)});
  }
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
  async function saveCurrentDoc(doc,dateField){ const projects=editorProjects(); const body={title:$('#f-title').value.trim(),project:projects[0]||'',projects,status:$('#f-status').value,tags:editorTags(),kind_marks:$$('#f-marks .mark-chip.on').map(b=>b.dataset.mark),body:$('#md-input').value}; if(dateField)body[dateField]=$('#f-date').value||today(); if(doc.kind==='summary')body.summary_type=$('#f-summary-type').value; if(doc.kind==='literature'){Object.assign(body,{authors:$('#f-authors').value,year:$('#f-year').value,venue:$('#f-venue').value,doi:$('#f-doi').value,url:$('#f-url').value,cite_key:$('#f-cite-key').value,bibtex:$('#f-bibtex').value,added_date:$('#f-date').value||today()});} const saved=await api('/api/docs/'+doc.id,{method:'POST',body});state.dirty=false;toast('已保存 Markdown');state.selectedDoc=saved; await refreshListAfterSave(doc.kind,saved.id); }
  async function refreshListAfterSave(kind,id){ state.docs=await api('/api/docs?kind='+kind);const list=$('#doc-list');if(list){list.innerHTML=docItems(state.docs);wireDocList(kind);$$('[data-doc-id]').forEach(x=>x.classList.toggle('active',x.dataset.docId===id));} }
  async function deleteCurrentDoc(doc){ if(!confirm(`删除“${doc.title}”？文件会移入 Workspace/System/Trash。`))return;await api('/api/docs/'+doc.id,{method:'DELETE'});toast('已移入回收目录');state.dirty=false;renderDocsPage(doc.kind); }
  function routeForKind(k){ return {idea:'ideas',journal:'journals',note:'notes',milestone:'milestones',summary:'summaries',literature:'literature'}[k]||'notes'}
  async function exportBibtex(){
    const docs=await api('/api/docs?kind=literature');
    modal('批量导出 BibTeX',`<div class="row-meta" style="margin-bottom:10px">默认全选；可取消不需要导出的文献。</div><div class="bundle-list">${docs.map(d=>`<label class="bundle-item"><input type="checkbox" class="bib-select" value="${d.id}" checked><span class="badge">文献</span><span><strong>${esc(d.title)}</strong><br><span class="row-meta">${esc(d.authors||'')} · ${esc(d.year||'')} · ${esc(d.venue||'')}</span></span></label>`).join('')||'<div class="empty">暂无文献</div>'}</div>`,`<button class="secondary-btn" id="bib-cancel">取消</button><button class="primary-btn" id="bib-export-run">导出所选</button>`);
    $('#bib-cancel').onclick=closeModal;$('#bib-export-run').onclick=async()=>{const ids=$$('.bib-select:checked').map(x=>x.value);const res=await api('/api/literature/export-bibtex',{method:'POST',body:{ids}});modal('BibTeX 已导出',`<div class="row-meta">${res.count} 条 · ${esc(res.path)}</div><textarea class="search-input mono" style="height:360px;margin-top:10px">${esc(res.content)}</textarea>`,`<button class="secondary-btn" id="bib-copy">复制</button><button class="primary-btn" id="bib-close">完成</button>`);$('#bib-copy').onclick=()=>copyText(res.content);$('#bib-close').onclick=closeModal;};
  }


  async function renderMilestoneShell(docs,projects){
    state.docs=docs; state.projects=projects;
    $('#main').innerHTML=`<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">MILESTONE SYSTEM</div><h3>里程碑</h3></div><div style="display:flex;gap:7px"><div class="view-tabs"><button data-ms-view="timeline" class="${state.milestoneView==='timeline'?'active':''}">时间轴</button><button data-ms-view="3d" class="${state.milestoneView==='3d'?'active':''}">3D 时间线</button><button data-ms-view="docs" class="${state.milestoneView==='docs'?'active':''}">文档</button></div><button class="primary-btn" id="new-ms">＋ 新建</button></div></div><div id="ms-view"></div></div>`;
    $('#new-ms').onclick=async()=>{const d=await api('/api/docs',{method:'POST',body:{kind:'milestone',title:'未命名里程碑',due:today()}});state.milestoneView='docs';await renderDocsPage('milestone');setTimeout(()=>selectDoc(d.id),10)};
    $$('[data-ms-view]').forEach(b=>b.onclick=()=>{state.milestoneView=b.dataset.msView;renderMilestoneView()}); renderMilestoneView();
  }
  function renderMilestoneView(){ $$('[data-ms-view]').forEach(b=>b.classList.toggle('active',b.dataset.msView===state.milestoneView)); const root=$('#ms-view'); if(!root)return;
    if(state.milestoneView==='timeline'){ root.innerHTML=milestoneTimelineHtml([...state.docs].sort((a,b)=>(a.due||'').localeCompare(b.due||''))); wireMilestoneCards(); }
    else if(state.milestoneView==='3d'){ root.innerHTML=milestone3dHtml(state.docs); animateMilestones3D(); }
    else { root.innerHTML=`<div class="docs-layout"><aside class="card doc-list-panel" style="position:relative;top:auto"><div class="doc-list">${docItems(state.docs)}</div></aside><section class="card doc-editor empty-editor" id="doc-editor"><div class="empty">选择里程碑文档进行编辑</div></section></div>`; wireDocList('milestone'); if(state.docs[0])selectDoc(state.docs[0].id); }
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

  async function renderGraphPage(){ const g=await api('/api/graph');state.graph=g;
    const filterKinds=[['idea','灵感'],['journal','研究日志'],['note','笔记'],['milestone','里程碑'],['summary','工作总结'],['literature','文献'],['tag','标签'],['project','项目']];
    const relationKinds=[['wikilink','显式引用'],['tag','标签关联'],['project','项目归属']];
    $('#main').innerHTML=`<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">RELATION MAP</div><h3>知识图谱</h3></div><div class="graph-view-tools"><div class="view-tabs"><button data-gview="2d" class="${state.graphView==='2d'?'active':''}">2D</button><button data-gview="3d" class="${state.graphView==='3d'?'active':''}">3D 星图</button></div><button class="secondary-btn" id="graph-fit" type="button">⤢ 全览</button></div></div>
      <div class="graph-wrap" id="graph-wrap"><div class="graph-canvas-wrap"><canvas class="graph-canvas" id="graph-canvas"></canvas><div class="graph-canvas-help">空白处拖动平移 · 3D 下 Alt/右键拖动旋转 · Ctrl+滚轮缩放</div></div><section class="card graph-preview hidden" id="graph-preview"><div class="preview-pane-head"><div><div class="card-kicker">MARKDOWN PREVIEW</div><h3 id="graph-preview-title">节点预览</h3></div><button class="ghost-btn" id="graph-preview-close" type="button">关闭</button></div><div class="preview-pane-meta" id="graph-preview-meta"></div><div class="md-preview graph-preview-body" id="graph-preview-body"></div></section><aside class="card graph-side"><h3 id="graph-node-title">选择节点</h3><div class="graph-node-info" id="graph-node-info">点击任意节点后，将高亮相邻节点与关系边。点击画布空白处可取消高亮。</div><div style="margin-top:12px"><button class="primary-btn" id="graph-bundle" disabled>整理关联 Markdown</button></div><div class="graph-filter"><strong>显示节点类别</strong><div class="graph-filter-grid">${filterKinds.map(([k,label])=>`<label><input type="checkbox" data-graph-kind="${k}" ${state.graphKinds.has(k)?'checked':''}> ${label}</label>`).join('')}</div><div class="graph-filter-actions"><button class="ghost-btn" id="graph-filter-all">全选</button><button class="ghost-btn" id="graph-filter-docs">仅知识条目</button></div></div><div class="graph-filter"><strong>关系来源</strong><div class="graph-filter-grid">${relationKinds.map(([k,label])=>`<label><input type="checkbox" data-graph-relation="${k}" ${state.graphRelations.has(k)?'checked':''}> ${label}</label>`).join('')}</div><div class="row-meta">隐藏“标签”或“项目”节点时，对应关系边也会立即从图谱和导出结果中移除。</div></div></aside></div>
    </div>`;
    $$('[data-gview]').forEach(b=>b.onclick=()=>{state.graphView=b.dataset.gview;renderGraphCanvas();animateSubView($('.graph-canvas-wrap'))});
    $$('[data-graph-kind]').forEach(c=>c.onchange=()=>{if(c.checked)state.graphKinds.add(c.dataset.graphKind);else state.graphKinds.delete(c.dataset.graphKind);localStorage.setItem('graphKinds',JSON.stringify([...state.graphKinds]));renderGraphCanvas()});
    $$('[data-graph-relation]').forEach(c=>c.onchange=()=>{if(c.checked)state.graphRelations.add(c.dataset.graphRelation);else state.graphRelations.delete(c.dataset.graphRelation);localStorage.setItem('graphRelations',JSON.stringify([...state.graphRelations]));renderGraphCanvas()});
    $('#graph-filter-all').onclick=()=>{$$('[data-graph-kind]').forEach(c=>c.checked=true);state.graphKinds=new Set(filterKinds.map(x=>x[0]));localStorage.setItem('graphKinds',JSON.stringify([...state.graphKinds]));renderGraphCanvas()};
    $('#graph-filter-docs').onclick=()=>{$$('[data-graph-kind]').forEach(c=>c.checked=!['project','tag'].includes(c.dataset.graphKind));state.graphKinds=new Set(filterKinds.map(x=>x[0]).filter(x=>!['project','tag'].includes(x)));localStorage.setItem('graphKinds',JSON.stringify([...state.graphKinds]));renderGraphCanvas()};
    $('#graph-bundle').onclick=()=>state.graphSelected&&openGraphBundleFromNode(state.graphSelected);
    $('#graph-preview-close').onclick=()=>onGraphSelect(null);
    $('#graph-fit').onclick=()=>{if(state.graphSelected)onGraphSelect(null);requestAnimationFrame(()=>$('#graph-canvas')?._graphResetView?.())};
    renderGraphCanvas();
  }
  function filteredGraph(){const allowed=state.graphKinds,relations=state.graphRelations;const nodes=(state.graph?.nodes||[]).filter(n=>allowed.has(n.kind));const ids=new Set(nodes.map(n=>n.id));return {nodes,edges:(state.graph?.edges||[]).filter(e=>relations.has(e.relation)&&ids.has(e.source)&&ids.has(e.target))}}
  function hideGraphPreview(){state.graphPreviewSeq++;$('#graph-wrap')?.classList.remove('preview-open');$('#graph-preview')?.classList.add('hidden');const body=$('#graph-preview-body');if(body)body.innerHTML='';}
  function graphVirtualMarkdown(n){const g=filteredGraph(),map=new Map(g.nodes.map(x=>[x.id,x])),rels=g.edges.filter(e=>e.source===n.id||e.target===n.id);const relLabel={wikilink:'显式引用',tag:'标签关联',project:'项目归属'};const kind={...KIND_LABEL,project:'项目',tag:'标签'};const rows=rels.map(e=>{const other=map.get(e.source===n.id?e.target:e.source);return other?`- [[${other.label}]] · ${kind[other.kind]||other.kind} · ${relLabel[e.relation]||e.relation}`:''}).filter(Boolean);return `# ${n.label}\n\n> 这是一个由知识图谱自动生成的${kind[n.kind]||n.kind}节点预览。\n\n## 当前可见关联\n\n${rows.join('\n')||'- 当前筛选条件下暂无可见关联。'}\n`;}
  async function showGraphPreview(n){const wrap=$('#graph-wrap'),panel=$('#graph-preview'),body=$('#graph-preview-body');if(!wrap||!panel||!body||!n)return;const seq=++state.graphPreviewSeq;wrap.classList.add('preview-open');panel.classList.remove('hidden');$('#graph-preview-title').textContent=n.label;const kind={...KIND_LABEL,project:'项目',tag:'标签'};$('#graph-preview-meta').textContent=`${kind[n.kind]||n.kind}${nodeProjects(n).length?' · '+nodeProjects(n).join(', '):''}`;body.innerHTML='<div class="empty" style="min-height:120px">正在加载 Markdown…</div>';try{const raw=n.virtual?graphVirtualMarkdown(n):(await api('/api/docs/'+encodeURIComponent(n.id))).body||'';if(seq!==state.graphPreviewSeq||state.graphSelected?.id!==n.id)return;await renderMarkdownInto(body,raw||'*暂无正文*');requestAnimationFrame(()=>renderGraphCanvas())}catch(e){if(seq===state.graphPreviewSeq)body.innerHTML=`<div class="empty danger">预览失败：${esc(e.message)}</div>`}}
  function renderGraphCanvas(){ $$('[data-gview]').forEach(b=>b.classList.toggle('active',b.dataset.gview===state.graphView)); const c=$('#graph-canvas');if(!c)return;const g=filteredGraph();if(state.graphSelected&&!g.nodes.some(n=>n.id===state.graphSelected.id)){state.graphSelected=null;$('#graph-node-title').textContent='选择节点';$('#graph-node-info').textContent='当前筛选已隐藏原选中节点。';$('#graph-bundle').disabled=true;hideGraphPreview()} drawGraph(c,g,{mode:state.graphView,interactive:true,selectedId:state.graphSelected?.id,onSelect:onGraphSelect}); }
  function nodeProjects(n){return (n.projects||[]).length?n.projects:(n.project?[n.project]:[])}
  function onGraphSelect(n){state.graphSelected=n||null;if(!n){$('#graph-node-title').textContent='选择节点';$('#graph-node-info').textContent='点击任意节点后，将高亮相邻节点与关系边；点击画布空白处可取消高亮。导出严格使用当前可见节点和关系。';$('#graph-bundle').disabled=true;hideGraphPreview();renderGraphCanvas();return}$('#graph-node-title').textContent=n.label;const projects=nodeProjects(n);const tags=n.tags||[];$('#graph-node-info').innerHTML=`<div><b>类型：</b>${esc(kindLabel(n.kind)||({project:'项目',tag:'标签'}[n.kind])||n.kind)}</div><div><b>项目：</b>${esc(projects.join(', ')||'—')}</div><div><b>标签：</b>${esc(tags.join(', ')||'—')}</div><div><b>状态：</b>${esc(n.status||'—')}</div><div class="row-meta graph-selection-hint">相邻节点和边已高亮；点击空白处恢复全图。导出会继承当前图谱筛选。</div>`;$('#graph-bundle').disabled=false;showGraphPreview(n);renderGraphCanvas();}
  function drawGraph(canvas,g,opts={}){
    const token=(canvas._graphRenderToken||0)+1;canvas._graphRenderToken=token;
    const mode=opts.mode||'2d';canvas._graphCameras=canvas._graphCameras||{};const camera=canvas._graphCameras[mode]||(canvas._graphCameras[mode]={panX:0,panY:0,zoom:1,rotX:.25,rotY:0});
    const resetCamera=()=>{camera.panX=0;camera.panY=0;camera.zoom=1;camera.rotX=.25;camera.rotY=0};canvas._graphResetView=()=>{resetCamera();paint()};
    const dpr=Math.min(devicePixelRatio||1,2),rect=canvas.getBoundingClientRect();canvas.width=Math.max(1,rect.width*dpr);canvas.height=Math.max(1,rect.height*dpr);const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);const w=rect.width,h=rect.height,nodes=g.nodes.map((n,i)=>({...n,_i:i})),edges=g.edges;const byId=new Map(nodes.map(n=>[n.id,n]));
    let drag=null,dragMoved=false,pressNode=null,selected=byId.get(opts.selectedId)||null; const R=Math.min(w,h)*(opts.mini?.28:.34);
    nodes.forEach((n,i)=>{const a=(i/Math.max(1,nodes.length))*Math.PI*2*2.39996;const r=R*(.25+.75*Math.sqrt((i+1)/Math.max(1,nodes.length)));n.bx=Math.cos(a)*r;n.by=Math.sin(a)*r*.72;n.bz=Math.sin(a*1.7)*R*.45;});
    function project(n){ if(mode==='3d'){const cy=Math.cos(camera.rotY),sy=Math.sin(camera.rotY),cx=Math.cos(camera.rotX),sx=Math.sin(camera.rotX);let x=n.bx*cy-n.bz*sy,z=n.bx*sy+n.bz*cy,y=n.by*cx-z*sx;z=n.by*sx+z*cx;const ss=560/(560+z);return{x:w/2+camera.panX+x*ss*camera.zoom,y:h/2+camera.panY+y*ss*camera.zoom,z,s:ss*camera.zoom}} return{x:w/2+camera.panX+n.bx*camera.zoom,y:h/2+camera.panY+n.by*camera.zoom,z:0,s:camera.zoom}; }
    function paint(){if(canvas._graphRenderToken!==token)return;ctx.clearRect(0,0,w,h);const pos=new Map(nodes.map(n=>[n.id,project(n)]));const neighborIds=new Set();if(selected){for(const e of edges){if(e.source===selected.id)neighborIds.add(e.target);else if(e.target===selected.id)neighborIds.add(e.source)}}
      edges.forEach(e=>{const a=pos.get(e.source),b=pos.get(e.target);if(!a||!b)return;const hi=!!selected&&(e.source===selected.id||e.target===selected.id);ctx.globalAlpha=selected?(hi?1:.12):.5;ctx.lineWidth=hi?3:1;ctx.strokeStyle=hi?getCss('--accent'):getCss('--line-strong');ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()});ctx.globalAlpha=1;
      const sorted=[...nodes].sort((a,b)=>project(a).z-project(b).z);for(const n of sorted){const p=pos.get(n.id),isSel=selected?.id===n.id,isNei=neighborIds.has(n.id),base=n.virtual?8:6,rad=Math.max(3,(base+(isSel?4:isNei?2:0))*Math.max(.55,Math.min(1.8,p.s)));ctx.globalAlpha=selected?(isSel||isNei?1:.32):1;ctx.beginPath();ctx.arc(p.x,p.y,rad,0,Math.PI*2);ctx.fillStyle=n.kind==='project'?getCss('--accent'):kindColor(n.kind);ctx.fill();if(isSel){ctx.strokeStyle=getCss('--text');ctx.lineWidth=3;ctx.stroke()}else if(isNei){ctx.strokeStyle=getCss('--accent');ctx.lineWidth=1.8;ctx.stroke()}if(!opts.mini||nodes.length<18||isSel||isNei){ctx.font=`${isSel||isNei?'700':'400'} ${Math.max(9,(isSel?12:isNei?11:10)*Math.max(.75,Math.min(1.4,camera.zoom)))}px Microsoft YaHei`;ctx.fillStyle=isSel||isNei?getCss('--text'):getCss('--muted');ctx.fillText(truncate(n.label,isSel?22:14),p.x+rad+4,p.y+3)}}ctx.globalAlpha=1;canvas._positions=pos; }
    function hit(x,y){let best=null,bd=22;for(const n of nodes){const p=canvas._positions?.get(n.id);if(!p)continue;const d=Math.hypot(x-p.x,y-p.y);if(d<bd){bd=d;best=n}}return best}
    canvas.oncontextmenu=e=>{if(mode==='3d')e.preventDefault()};
    canvas.onpointerdown=e=>{pressNode=hit(e.offsetX,e.offsetY);dragMoved=false;if(!pressNode&&!selected){drag={x:e.offsetX,y:e.offsetY,mode:(mode==='3d'&&(e.altKey||e.button===2))?'rotate':'pan'};canvas.setPointerCapture?.(e.pointerId)}else drag=null};
    canvas.onpointermove=e=>{if(!drag)return;const dx=e.offsetX-drag.x,dy=e.offsetY-drag.y;if(Math.hypot(dx,dy)>1)dragMoved=true;if(drag.mode==='rotate'){camera.rotY+=dx*.008;camera.rotX=Math.max(-1.2,Math.min(1.2,camera.rotX+dy*.006))}else{camera.panX+=dx;camera.panY+=dy}drag.x=e.offsetX;drag.y=e.offsetY;paint()};
    canvas.onpointerup=e=>{const n=hit(e.offsetX,e.offsetY);try{canvas.releasePointerCapture?.(e.pointerId)}catch{};const wasDrag=dragMoved;drag=null;if(!wasDrag){if(pressNode&&n?.id===pressNode.id){selected=n;paint();opts.onSelect?.(n)}else if(!pressNode){selected=null;paint();opts.onSelect?.(null)}}pressNode=null};
    canvas.onpointercancel=e=>{drag=null;pressNode=null;try{canvas.releasePointerCapture?.(e.pointerId)}catch{}};
    canvas.onwheel=e=>{if(!(e.ctrlKey||e.metaKey))return;e.preventDefault();const old=camera.zoom,next=Math.max(.35,Math.min(4,old*Math.exp(-e.deltaY*.0015)));if(Math.abs(next-old)<1e-4)return;const cx=e.offsetX-w/2,cy=e.offsetY-h/2,localX=(cx-camera.panX)/old,localY=(cy-camera.panY)/old;camera.zoom=next;camera.panX=cx-localX*next;camera.panY=cy-localY*next;paint()};
    paint();
    if(mode==='3d'&&state.config?.app?.ui?.animations&&!matchMedia('(prefers-reduced-motion: reduce)').matches){const loop=()=>{if(canvas._graphRenderToken!==token||!document.body.contains(canvas))return;if(!drag&&!selected){camera.rotY+=.0015;paint()}requestAnimationFrame(loop)};requestAnimationFrame(loop)}
  }

  function kindColor(kind){const c={idea:'#2a9d8f',journal:'#5b8def',note:'#6f7a8a',milestone:'#c6863b',summary:'#845ec2',literature:'#2673a7',tag:'#b56a9d',project:'#087f8c'};return c[kind]||getCss('--accent')}
  function getCss(name){return getComputedStyle(document.documentElement).getPropertyValue(name).trim()}
  function truncate(s,n){s=String(s||'');return s.length>n?s.slice(0,n)+'…':s}
  function visibleGraphNeighborhood(rootId,depth=2){const g=filteredGraph(),nodeMap=new Map(g.nodes.map(n=>[n.id,n])),adj=new Map();for(const e of g.edges){if(!adj.has(e.source))adj.set(e.source,[]);if(!adj.has(e.target))adj.set(e.target,[]);adj.get(e.source).push([e.target,e]);adj.get(e.target).push([e.source,e])}const dist=new Map([[rootId,0]]),q=[rootId];for(let qi=0;qi<q.length;qi++){const cur=q[qi],d=dist.get(cur);if(d>=depth)continue;for(const [nxt] of adj.get(cur)||[]){if(!dist.has(nxt)){dist.set(nxt,d+1);q.push(nxt)}}}return {graph:g,nodeMap,dist};}
  async function openGraphBundleFromNode(node){ if(!node)return; const neighborhood=visibleGraphNeighborhood(node.id,2); const selectable=[...neighborhood.dist.entries()].filter(([id,d])=>id!==node.id&&d<=2&&!neighborhood.nodeMap.get(id)?.virtual).map(([id,d])=>({...neighborhood.nodeMap.get(id),distance:d})).sort((a,b)=>a.distance-b.distance||String(a.label).localeCompare(String(b.label),'zh-CN')); const rootKindLabel={project:'项目',tag:'标签'}[node.kind]||kindLabel(node.kind); modal('整理关联 Markdown',`<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px"><strong>${esc(node.label)}</strong><span class="badge accent">${esc(rootKindLabel)}核心</span><label class="badge"><input type="radio" name="bundle-depth" value="1" checked> 一阶</label><label class="badge"><input type="radio" name="bundle-depth" value="2"> 二阶</label></div><div class="row-meta" style="margin-bottom:10px">候选关系只来自当前图谱中可见的节点类别与关系来源；隐藏项目/标签后，其边不会进入本次导出。</div><div style="display:flex;gap:7px;margin-bottom:10px"><button class="secondary-btn" id="bundle-all">全选</button><button class="secondary-btn" id="bundle-none">清空</button></div><div class="bundle-list" id="bundle-list">${selectable.map(x=>`<label class="bundle-item" data-distance="${x.distance}"><input type="checkbox" value="${x.id}" ${x.distance===1?'checked':''}><span class="badge">${x.distance} 阶</span><span><strong>${esc(x.label)}</strong><br><span class="row-meta">${esc(kindLabel(x.kind))} · ${esc(nodeProjects(x).join(', ')||'未归属项目')}</span></span></label>`).join('')||'<div class="empty">当前筛选条件下没有关联 Markdown</div>'}</div>`,`<button class="secondary-btn" id="bundle-cancel">取消</button><button class="primary-btn" id="bundle-generate">生成 Markdown</button>`);
    function applyDepth(){const depth=+$('input[name="bundle-depth"]:checked').value;$$('.bundle-item').forEach(i=>{i.classList.toggle('hidden',+i.dataset.distance>depth);const cb=$('input',i);if(+i.dataset.distance>depth)cb.checked=false;});}$$('input[name="bundle-depth"]').forEach(r=>r.onchange=applyDepth);$('#bundle-all').onclick=()=>{$$('.bundle-item:not(.hidden) input').forEach(x=>x.checked=true)};$('#bundle-none').onclick=()=>{$$('.bundle-item input').forEach(x=>x.checked=false)};$('#bundle-cancel').onclick=closeModal;applyDepth();$('#bundle-generate').onclick=async()=>{const depth=+$('input[name="bundle-depth"]:checked').value,ids=$$('.bundle-item:not(.hidden) input:checked').map(x=>x.value);const activeVirtual=[...neighborhood.dist.entries()].filter(([id,d])=>d<=depth&&neighborhood.nodeMap.get(id)?.virtual).map(([id])=>id);const activeNodeIds=[node.id,...ids,...activeVirtual];const activeSet=new Set(activeNodeIds);const relations=neighborhood.graph.edges.filter(e=>activeSet.has(e.source)&&activeSet.has(e.target));const r=await api('/api/graph/bundle',{method:'POST',body:{root:node.id,selected_ids:ids,active_node_ids:activeNodeIds,relations}});showBundleResult(node,r.content)};
  }
  function showBundleResult(node,content){modal('关联 Markdown 已生成',`<textarea id="bundle-content" class="search-input mono" style="height:460px">${esc(content)}</textarea>`,`<button class="secondary-btn" id="bundle-copy">复制到剪贴板</button><button class="primary-btn" id="bundle-save">保存到本地</button>`);$('#bundle-copy').onclick=()=>copyText(content);$('#bundle-save').onclick=async()=>{const name=`${node.label}-关联汇总.md`;const r=await api('/api/graph/bundle/save',{method:'POST',body:{filename:name,content}});toast('已保存：'+r.path);closeModal()};}
  async function copyText(text){try{await navigator.clipboard.writeText(text);toast('已复制到剪贴板')}catch{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();toast('已复制到剪贴板')}}


  async function renderFolders(){const [tree,info]=await Promise.all([api('/api/workspace/tree'),api('/api/workspace/info')]);
    $('#main').innerHTML=`<div class="workspace-layout"><section class="card tree-panel"><div class="card-head"><div><div class="card-kicker">WORKSPACE</div><h3>文件夹</h3></div><button class="secondary-btn" id="tree-refresh">刷新</button></div>${treeHtml(tree)}</section><section class="card card-pad"><div class="card-head"><div><div class="card-kicker">AUTO WORKSPACE</div><h3>工作目录</h3></div></div><div class="field"><label>当前根目录</label><input readonly value="${esc(info.root)}"></div><div style="margin-top:12px"><button class="primary-btn" id="open-workspace">在系统文件管理器中打开</button> <button class="secondary-btn" id="new-project">新建项目</button> <button class="secondary-btn" id="new-folder">新建文件夹</button></div><div class="section-title"><div><h3>自动结构</h3><p>启动时自动识别、创建必要目录；兼容旧版 data/research_os 等常见目录并进行非破坏式复制迁移。</p></div></div><div class="mono" style="font-size:12px;line-height:1.8">Workspace/<br>├─ Knowledge/{Ideas, Journals, Notes, Milestones, Summaries, Literature, Attachments, Exports}<br>├─ Projects/<br>├─ Resources/<br>└─ System/</div><div class="section-title"><div><h3>迁移状态</h3></div></div><div class="row-meta">${info.migration?.performed_at?`已检查 · ${esc(info.migration.performed_at)} · 发现 ${info.migration.sources_found||0} 个旧数据源 · 本次复制 ${info.migration.copied_count||0} 个文件`:'尚未执行迁移检查'}</div><div style="margin-top:10px"><button class="secondary-btn" id="migration-rescan">重新扫描并迁移</button></div></section></div>`;
    $('#tree-refresh').onclick=renderFolders;$('#open-workspace').onclick=()=>api('/api/workspace/open',{method:'POST',body:{path:''}}).then(()=>toast('已打开 Workspace')).catch(e=>toast(e.message,true));$('#migration-rescan').onclick=async()=>{const r=await api('/api/workspace/migrate',{method:'POST',body:{}});toast(`迁移扫描完成：复制 ${r.copied_count||0} 个文件`);renderFolders()};$('#new-project').onclick=()=>{modal('新建项目工程目录',`<div class="field"><label>项目名称</label><input id="new-project-name" placeholder="请输入你的项目名称"></div><div class="row-meta" style="margin-top:8px">将自动创建 Notes / Experiments / Data / Results / Figures / Manuscript / References。</div>`,`<button class="secondary-btn" id="project-cancel">取消</button><button class="primary-btn" id="project-create">创建</button>`);$('#project-cancel').onclick=closeModal;$('#project-create').onclick=async()=>{const r=await api('/api/workspace/project',{method:'POST',body:{name:$('#new-project-name').value}});toast('项目目录已创建：'+r.path);closeModal();renderFolders()}};$('#new-folder').onclick=()=>{modal('新建 Workspace 文件夹',`<div class="field"><label>相对路径</label><input id="new-folder-path" value="Projects/NewProject" placeholder="Projects/项目名"></div>`,`<button class="secondary-btn" id="folder-cancel">取消</button><button class="primary-btn" id="folder-create">创建</button>`);$('#folder-cancel').onclick=closeModal;$('#folder-create').onclick=async()=>{await api('/api/workspace/folder',{method:'POST',body:{path:$('#new-folder-path').value}});toast('文件夹已创建');closeModal();renderFolders()}};wireTreeOpen();
  }
  function treeHtml(node){const ico=node.type==='dir'?'▱':'·';return `<div class="tree-node"><div class="tree-line"><span>${ico}</span><span class="folder-name" title="${esc(node.path)}">${esc(node.name)}</span>${node.type==='dir'?`<span class="folder-actions"><button data-open-path="${esc(node.path)}">↗</button></span>`:''}</div>${node.children?.length?`<div class="tree-children">${node.children.map(treeHtml).join('')}</div>`:''}</div>`}
  function wireTreeOpen(){$$('[data-open-path]').forEach(b=>b.onclick=e=>{e.stopPropagation();api('/api/workspace/open',{method:'POST',body:{path:b.dataset.openPath}}).catch(x=>toast(x.message,true))})}

  async function renderSettings(){const cfg=await api('/api/config');state.config=cfg;
    $('#main').innerHTML=`<div class="settings-layout"><aside class="card settings-nav"><button class="active" data-set-tab="general">基础</button><button data-set-tab="service">服务与存储</button><button data-set-tab="academic">学业与目标</button><button data-set-tab="weather">天气</button><button data-set-tab="rss">资讯源</button><button data-set-tab="llm">Agent / LLM</button><button data-set-tab="interface">界面</button></aside><section class="card settings-panel" id="settings-panel"></section></div>`;
    $$('[data-set-tab]').forEach(b=>b.onclick=()=>{$$('[data-set-tab]').forEach(x=>x.classList.toggle('active',x===b));renderSettingsTab(b.dataset.setTab,cfg)});renderSettingsTab('general',cfg);
  }
  function renderSettingsTab(tab,cfg){const p=$('#settings-panel'),app=cfg.app,rss=cfg.rss;if(tab==='general'){
      p.innerHTML=`<div class="card-head"><div><div class="card-kicker">GENERAL</div><h3>基础设置</h3></div></div><div class="form-grid"><div class="field span-2"><label>工作台名称</label><input id="set-app-name" value="${esc(app.app_name)}"></div><div class="field span-2"><label>副标题</label><input id="set-subtitle" value="${esc(app.subtitle)}"></div></div><div class="field-help" style="margin-top:10px">运行端口、监听地址、Workspace 路径和启动行为已移动到“服务与存储”，均可在页面中配置。</div><div style="margin-top:14px"><button class="primary-btn" id="save-settings">保存</button></div>`;$('#save-settings').onclick=async()=>{app.app_name=$('#set-app-name').value.trim()||'科研工作台';app.subtitle=$('#set-subtitle').value.trim();const saved=await api('/api/config/app',{method:'POST',body:app});state.config.app=saved;cfg.app=saved;toast('基础设置已保存');await loadBootstrap();};
    }
    else if(tab==='service'){
      const mig=app.workspace_migration||{};
      p.innerHTML=`<div class="card-head"><div><div class="card-kicker">SERVICE / STORAGE</div><h3>服务与存储</h3><p class="row-meta">这些参数直接对应 config/app.json 中的运行与 Workspace 配置。</p></div><span class="badge warn">Host / Port 修改后需快速重启</span></div><div class="form-grid"><div class="field span-2"><label>监听地址 Host</label><input id="svc-host" value="${esc(app.host||'127.0.0.1')}" placeholder="127.0.0.1"><span class="field-help">仅本机使用建议 127.0.0.1；局域网访问可配置 0.0.0.0，并自行确认防火墙安全。</span></div><div class="field"><label>端口 Port</label><input id="svc-port" type="number" min="1" max="65535" value="${Number(app.port||8765)}"></div><div class="field"><label>启动时打开浏览器</label><select id="svc-browser"><option value="1" ${app.auto_open_browser!==false?'selected':''}>是</option><option value="0" ${app.auto_open_browser===false?'selected':''}>否 / 静默启动</option></select></div><div class="field span-4"><label>Workspace 路径</label><input id="svc-workspace" value="${esc(app.workspace||'Workspace')}" placeholder="Workspace"><span class="field-help">支持项目相对路径或绝对路径。修改后后续数据读写会使用新目录；建议修改前先备份 Workspace。</span></div><div class="field"><label>旧数据自动识别</label><select id="svc-migrate"><option value="1" ${mig.enabled!==false?'selected':''}>启用</option><option value="0" ${mig.enabled===false?'selected':''}>关闭</option></select></div><div class="field"><label>迁移时复制旧数据</label><select id="svc-copy"><option value="1" ${mig.copy_legacy_data!==false?'selected':''}>复制（非破坏）</option><option value="0" ${mig.copy_legacy_data===false?'selected':''}>仅识别</option></select></div></div><div style="margin-top:14px;display:flex;gap:8px"><button class="primary-btn" id="svc-save">保存服务与存储设置</button><button class="secondary-btn" id="svc-restart">保存后快速重启</button></div>`;
      const collect=()=>{const newWs=$('#svc-workspace').value.trim()||'Workspace';if(newWs!==String(app.workspace||'Workspace')&&!confirm(`Workspace 将从“${app.workspace||'Workspace'}”切换到“${newWs}”。确定保存吗？`))return null;app.host=$('#svc-host').value.trim()||'127.0.0.1';app.port=Math.max(1,Math.min(65535,+$('#svc-port').value||8765));app.auto_open_browser=$('#svc-browser').value==='1';app.workspace=newWs;app.workspace_migration={...mig,enabled:$('#svc-migrate').value==='1',copy_legacy_data:$('#svc-copy').value==='1'};return app};
      $('#svc-save').onclick=async()=>{const data=collect();if(!data)return;const saved=await api('/api/config/app',{method:'POST',body:data});state.config.app=saved;cfg.app=saved;toast('服务与存储设置已保存；Host / Port 修改需重启生效')};
      $('#svc-restart').onclick=async()=>{const data=collect();if(!data)return;await api('/api/config/app',{method:'POST',body:data});systemAction('restart')};
    }
    else if(tab==='academic'){
      const ac=app.academic_profile||{}; const conditions=Array.isArray(ac.graduation_conditions)?ac.graduation_conditions:[];
      p.innerHTML=`<div class="card-head"><div><div class="card-kicker">ACADEMIC PROFILE</div><h3>学业周期与毕业目标</h3></div><span class="badge accent">用于概览仪表盘</span></div>
      <div class="form-grid"><div class="field span-2"><label>进度卡片名称</label><input id="ac-degree" value="${esc(ac.degree_name||'博士进度')}" placeholder="例如：博士进度"></div><div class="field"><label>开始日期</label><input id="ac-start" type="date" value="${esc(ac.start_date||'')}"></div><div class="field"><label>预计完成日期</label><input id="ac-end" type="date" value="${esc(ac.expected_end_date||'')}"></div><div class="field"><label>每周活跃目标</label><input id="ac-weekly" type="number" min="1" max="7" value="${Number(ac.weekly_goal_days||5)}"><span class="field-help">用于概览中的科研节奏卡片。</span></div></div>
      <div class="section-title"><div><h3>毕业条件</h3><p>完全自定义，不预设学校要求。可用于论文、会议、专利、资格考试、学位论文阶段等。</p></div><button class="secondary-btn" id="condition-add">＋ 添加条件</button></div>
      <div class="condition-editor-head"><span>条件名称</span><span>当前</span><span>目标</span><span>单位</span><span></span></div><div id="condition-editor">${conditions.map(conditionEditRow).join('')}</div>
      <div style="margin-top:16px"><button class="primary-btn" id="academic-save">保存学业与目标</button></div>`;
      const wire=()=>$$('[data-cond-del]').forEach(b=>b.onclick=()=>b.closest('.condition-edit-row').remove()); wire();
      $('#condition-add').onclick=()=>{$('#condition-editor').insertAdjacentHTML('beforeend',conditionEditRow({label:'',current:0,target:1,unit:''}));wire();};
      $('#academic-save').onclick=async()=>{const graduation_conditions=$$('.condition-edit-row').map(r=>({label:$('[data-cond-label]',r).value.trim(),current:+$('[data-cond-current]',r).value||0,target:+$('[data-cond-target]',r).value||0,unit:$('[data-cond-unit]',r).value.trim()})).filter(x=>x.label);app.academic_profile={...ac,degree_name:$('#ac-degree').value.trim()||'学业进度',start_date:$('#ac-start').value,expected_end_date:$('#ac-end').value,weekly_goal_days:Math.max(1,Math.min(7,+$('#ac-weekly').value||5)),graduation_conditions};await api('/api/config/app',{method:'POST',body:app});state.config.app=app;toast('学业与毕业目标已保存');};
    }
    else if(tab==='weather'){const w=app.weather||{};p.innerHTML=`<div class="card-head"><div><div class="card-kicker">OPEN-METEO</div><h3>天气设置</h3></div><span class="badge accent">无需 API Key</span></div><div class="form-grid"><div class="field"><label>启用天气</label><select id="w-enabled"><option value="1" ${w.enabled!==false?'selected':''}>启用</option><option value="0" ${w.enabled===false?'selected':''}>关闭</option></select></div><div class="field span-2"><label>地点名称</label><input id="w-location" value="${esc(w.location||'')}"></div><div class="field"><label>纬度</label><input id="w-lat" type="number" step="0.0001" value="${w.latitude??''}"></div><div class="field"><label>经度</label><input id="w-lon" type="number" step="0.0001" value="${w.longitude??''}"></div><div class="field span-2"><label>时区</label><input id="w-tz" value="${esc(w.timezone||'Asia/Shanghai')}"></div></div><div style="margin-top:14px;display:flex;gap:7px"><button class="secondary-btn" id="weather-geocode">根据地点搜索坐标</button><button class="primary-btn" id="weather-save">保存并刷新天气</button></div>`;$('#weather-geocode').onclick=async()=>{const r=await api('/api/weather/geocode?name='+encodeURIComponent($('#w-location').value));if(!r.results?.length)return toast('没有找到地点',true);const x=r.results[0];$('#w-lat').value=x.latitude;$('#w-lon').value=x.longitude;$('#w-tz').value=x.timezone||'auto';toast(`已匹配：${x.name} ${x.admin1||''}`)};$('#weather-save').onclick=async()=>{app.weather={...w,enabled:$('#w-enabled').value==='1',location:$('#w-location').value,latitude:+$('#w-lat').value,longitude:+$('#w-lon').value,timezone:$('#w-tz').value};await api('/api/config/app',{method:'POST',body:app});state.config.app=app;toast('天气设置已保存');loadWeather(true);};}
    else if(tab==='rss'){p.innerHTML=`<div class="card-head"><div><div class="card-kicker">RSS SOURCES</div><h3>资讯源</h3></div><button class="secondary-btn" id="rss-add">＋ 添加</button></div><div id="rss-list">${rss.sources.map((s,i)=>sourceRow(s,i)).join('')}</div><div class="field" style="max-width:260px;margin-top:10px"><label>每源最大条数</label><input id="rss-limit" type="number" value="${rss.max_items_per_source||12}"></div><div style="margin-top:14px"><button class="primary-btn" id="rss-save">保存资讯配置</button></div>`;wireSourceRows();$('#rss-add').onclick=()=>{$('#rss-list').insertAdjacentHTML('beforeend',sourceRow({name:'新资讯源',url:'',enabled:true},$$('.source-row').length));wireSourceRows()};$('#rss-save').onclick=async()=>{const sources=$$('.source-row').map(r=>({name:$('[data-rss-name]',r).value,url:$('[data-rss-url]',r).value,enabled:$('[data-rss-enable]',r).checked}));await api('/api/config/rss',{method:'POST',body:{sources,max_items_per_source:+$('#rss-limit').value||12}});toast('资讯配置已保存')};}
    else if(tab==='llm'){const llm=app.llm||{};const fallbackPresets=[{id:'default',label:'默认（不附加参数）',params:{}},{id:'qwen-low',label:'Qwen · 低思考',params:{enable_thinking:true,thinking_budget:1024}},{id:'qwen-off',label:'Qwen · 无思考',params:{enable_thinking:false}}];const presets=Array.isArray(llm.request_presets)&&llm.request_presets.length?llm.request_presets:fallbackPresets;const presetText=JSON.stringify(presets,null,2);p.innerHTML=`<div class="card-head"><div><div class="card-kicker">RESEARCH AGENT / OPENAI COMPATIBLE</div><h3>Agent 与模型接口</h3><p class="row-meta">API Key 不写入工作台配置、不会上传 git。推荐填入本地私密文件 config/secrets.json（自动注入环境变量，保存后自动生效），或直接设置系统环境变量。</p></div><span class="badge ${llm.has_api_key?'accent':'warn'}">${llm.has_api_key?'环境变量已读取':'环境变量未设置'}</span></div><div class="form-grid"><div class="field"><label>接口名称</label><input id="llm-provider" value="${esc(llm.provider_label||'OpenAI-compatible')}" placeholder="OpenAI-compatible"></div><div class="field"><label>启用 Agent</label><select id="llm-enabled"><option value="1" ${llm.enabled?'selected':''}>启用</option><option value="0" ${!llm.enabled?'selected':''}>关闭</option></select></div><div class="field"><label>协议</label><select id="llm-protocol"><option value="chat_completions" ${llm.protocol!=='responses'?'selected':''}>OpenAI-compatible Chat Completions</option><option value="responses" ${llm.protocol==='responses'?'selected':''}>OpenAI Responses API</option></select></div><div class="field span-2"><label>Base URL</label><input id="llm-base" value="${esc(llm.base_url||'https://api.openai.com/v1')}" placeholder="https://api.openai.com/v1"></div><div class="field span-2"><label>API Key 环境变量名称</label><input id="llm-key-env" value="${esc(llm.api_key_env||'OPENAI_API_KEY')}" placeholder="OPENAI_API_KEY"><span class="field-help">推荐把密钥填入项目 config/secrets.json 的 env 对象（本地私密、不上传 git，保存后自动生效）；也可以在启动工作台前设置系统环境变量。工作台不会读取后写回 Key。</span></div><div class="field span-2"><label>模型</label><input id="llm-model" value="${esc(llm.model||'')}" placeholder="模型 ID"></div><div class="field"><label>显示模型思考过程</label><select id="llm-show-reasoning"><option value="1" ${llm.show_reasoning!==false?'selected':''}>显示（接口返回时）</option><option value="0" ${llm.show_reasoning===false?'selected':''}>隐藏</option></select></div><div class="field"><label>超时 / 秒</label><input id="llm-timeout" type="number" min="5" max="600" value="${Number(llm.timeout||120)}"></div><div class="field"><label>最大输出 tokens（可选）</label><input id="llm-max" type="number" min="0" value="${Number(llm.max_output_tokens||0)}" placeholder="0 = 使用模型默认"></div><div class="field"><label>Temperature（可选）</label><input id="llm-temp" type="number" min="0" max="2" step="0.1" value="${llm.temperature==null?'':Number(llm.temperature)}" placeholder="留空 = 不发送"></div><div class="field"><label>默认请求模式 ID</label><input id="llm-default-preset" value="${esc(llm.default_request_preset||presets[0].id||'default')}" placeholder="default"></div><div class="field span-4"><label>动态请求模式（JSON）</label><textarea id="llm-presets" class="mono" style="min-height:280px">${esc(presetText)}</textarea><span class="field-help">默认提供“默认 / Qwen 低思考 / Qwen 无思考”三套。params 会合并到请求 JSON；可按实际接口修改 enable_thinking、thinking_budget、reasoning_effort 等字段。</span></div><div class="field span-4"><label>系统提示词</label><textarea id="llm-system" style="min-height:130px">${esc(llm.system_prompt||'')}</textarea></div></div><div style="margin-top:14px;display:flex;gap:8px"><button class="primary-btn" id="llm-save">保存模型设置</button><button class="secondary-btn" id="llm-test">测试连接</button></div>`;$('#llm-save').onclick=async()=>{let requestPresets;try{requestPresets=JSON.parse($('#llm-presets').value);if(!Array.isArray(requestPresets)||!requestPresets.length)throw new Error('必须是非空 JSON 数组');const ids=new Set();for(const item of requestPresets){if(!item||typeof item!=='object'||!String(item.id||'').trim()||typeof item.params!=='object'||Array.isArray(item.params))throw new Error('每项必须包含 id、label 和 params 对象');if(ids.has(item.id))throw new Error('预设 id 不能重复：'+item.id);ids.add(item.id)}}catch(e){toast('请求模式 JSON 无效：'+e.message,true);return}app.llm={...llm,provider_label:$('#llm-provider').value.trim()||'OpenAI-compatible',enabled:$('#llm-enabled').value==='1',protocol:$('#llm-protocol').value,base_url:$('#llm-base').value.trim(),api_key_env:$('#llm-key-env').value.trim()||'OPENAI_API_KEY',show_reasoning:$('#llm-show-reasoning').value==='1',model:$('#llm-model').value.trim(),timeout:Math.max(5,Math.min(600,+$('#llm-timeout').value||120)),max_output_tokens:Math.max(0,+$('#llm-max').value||0),temperature:$('#llm-temp').value.trim()===''?null:Math.max(0,Math.min(2,+$('#llm-temp').value||0)),default_request_preset:$('#llm-default-preset').value.trim()||requestPresets[0].id,request_presets:requestPresets,system_prompt:$('#llm-system').value};delete app.llm.api_key;delete app.llm.has_api_key;const saved=await api('/api/config/app',{method:'POST',body:app});state.config.app=saved;cfg.app=saved;state.agentPreset=saved.llm?.default_request_preset||requestPresets[0].id;localStorage.setItem('agentRequestPreset',state.agentPreset);toast('Agent / LLM 设置已保存；API Key 将从环境变量读取')};$('#llm-test').onclick=async()=>{try{$('#llm-test').disabled=true;const r=await api('/api/agent/test',{method:'POST',body:{}});toast(r.models?.length?`连接成功 · ${r.models.slice(0,3).join(' / ')}`:'连接成功')}catch(e){toast(e.message,true)}finally{$('#llm-test').disabled=false}};}
    else {const ui=app.ui||{};const pins=new Set(ui.sidebar_pinned_groups||[]);p.innerHTML=`<div class="card-head"><div><div class="card-kicker">INTERFACE</div><h3>界面设置</h3></div></div><div class="form-grid"><div class="field"><label>默认主题</label><select id="ui-theme"><option value="light" ${ui.theme==='light'?'selected':''}>明亮</option><option value="dark" ${ui.theme==='dark'?'selected':''}>深色</option></select></div><div class="field"><label>里程碑默认视图</label><select id="ui-ms"><option value="timeline">时间轴</option><option value="3d" ${ui.milestone_default_view==='3d'?'selected':''}>3D 时间线</option><option value="docs" ${ui.milestone_default_view==='docs'?'selected':''}>文档</option></select></div><div class="field"><label>图谱默认视图</label><select id="ui-graph"><option value="2d">2D</option><option value="3d" ${ui.graph_default_view==='3d'?'selected':''}>3D 星图</option></select></div><div class="field"><label>动画</label><select id="ui-anim"><option value="1" ${ui.animations!==false?'selected':''}>启用</option><option value="0" ${ui.animations===false?'selected':''}>关闭</option></select></div><div class="field"><label>科研热力图月份</label><select id="ui-heatmap">${(()=>{const hm=Number(ui.heatmap_months||12);const cs=HEATMAP_MONTH_OPTIONS.includes(hm)?HEATMAP_MONTH_OPTIONS:[...HEATMAP_MONTH_OPTIONS,hm].sort((a,b)=>a-b);return cs.map(n=>`<option value="${n}" ${hm===n?'selected':''}>近 ${n} 个月</option>`).join('')})()}</select></div><div class="field span-4"><label>侧栏默认常驻展开</label><div class="check-grid">${NAV_GROUPS.map(g=>`<label><input type="checkbox" data-pin-default value="${g.id}" ${pins.has(g.id)?'checked':''}> ${g.label}</label>`).join('')}</div><span class="field-help">侧栏中仍可随时用菱形按钮单独固定；这里决定首次使用或重置后的默认状态。</span></div></div><div style="margin-top:14px"><button class="primary-btn" id="ui-save">保存界面设置</button> <button class="secondary-btn" id="ui-reset-sidebar">应用默认侧栏状态</button></div>`;$('#ui-save').onclick=async()=>{app.ui={...ui,theme:$('#ui-theme').value,milestone_default_view:$('#ui-ms').value,graph_default_view:$('#ui-graph').value,animations:$('#ui-anim').value==='1',heatmap_months:Math.max(1,Math.min(12,+$('#ui-heatmap').value||12)),sidebar_pinned_groups:$$('[data-pin-default]:checked').map(x=>x.value)};state.heatmapMonths=app.ui.heatmap_months;localStorage.setItem('heatmapMonths',String(state.heatmapMonths));await api('/api/config/app',{method:'POST',body:app});state.config.app=app;applyTheme(app.ui.theme);toast('界面设置已保存')};$('#ui-reset-sidebar').onclick=()=>{state.sidebarPinned=new Set($$('[data-pin-default]:checked').map(x=>x.value));state.sidebarOpen=new Set([...state.sidebarPinned,'core']);saveSidebarState();renderSidebar();toast('已应用默认侧栏状态')};}
  }
  function conditionEditRow(x={}){return `<div class="condition-edit-row"><input class="search-input" data-cond-label value="${esc(x.label||'')}" placeholder="例如：期刊论文"><input class="search-input" data-cond-current type="number" min="0" step="0.1" value="${Number(x.current||0)}"><input class="search-input" data-cond-target type="number" min="0" step="0.1" value="${Number(x.target||0)}"><input class="search-input" data-cond-unit value="${esc(x.unit||'')}" placeholder="篇 / 项"><button class="ghost-btn danger" type="button" data-cond-del>删除</button></div>`}
  function sourceRow(s,i){return `<div class="source-row"><input class="search-input" data-rss-name value="${esc(s.name)}"><input class="search-input" data-rss-url value="${esc(s.url)}"><label class="badge"><input type="checkbox" data-rss-enable ${s.enabled!==false?'checked':''}> 启用</label><button class="ghost-btn danger" data-rss-del>删除</button></div>`}
  function wireSourceRows(){$$('[data-rss-del]').forEach(b=>b.onclick=()=>b.closest('.source-row').remove())}

  function applyTheme(theme){document.documentElement.dataset.theme=theme||'light';localStorage.setItem('theme',theme||'light');if($('#md-preview')&&state.editorMode!=='edit')setTimeout(()=>renderMarkdownPreview(),20)}
  async function loadWeather(force=false){try{const w=await api('/api/weather'+(force?'?force=1':''));if(!w.enabled){$('#weather-text').textContent='天气关闭';return}const d=w.daily?.[0];$('#weather-text').textContent=`${w.location} · ${w.current.condition} ${w.current.temperature}° · ${d?.low ?? '—'}~${d?.high ?? '—'}°`;$('#weather-pill').title=`Open-Meteo · 体感 ${w.current.apparent}° · 降水 ${w.current.precipitation} mm`; }catch(e){$('#weather-text').textContent='天气不可用';$('#weather-pill').title=e.message;}}
  async function systemAction(action){ if(action==='reload'){try{await api('/api/system/reload',{method:'POST',body:{}});await loadBootstrap();toast('所有配置文件已 Reload');navigate(state.route)}catch(e){toast(e.message,true)}} else if(action==='restart'){if(!confirm('快速重启本地服务？浏览器将在约 1 秒后自动重连。'))return;try{await api('/api/system/restart',{method:'POST',body:{}})}catch{}toast('服务正在重启');setTimeout(waitForRestart,700)} }

  async function waitForRestart(attempt=0){
    if(attempt>18){toast('服务重启等待超时，请手动刷新页面',true);return;}
    try{await api('/api/health');location.reload();}catch{setTimeout(()=>waitForRestart(attempt+1),450);}
  }

  async function loadBootstrap(){ const [cfg,statuses,projects,health,ws]=await Promise.all([api('/api/config'),api('/api/statuses'),api('/api/projects'),api('/api/health'),api('/api/workspace/info')]); state.config=cfg;state.statuses=statuses;state.projects=projects;if(localStorage.getItem('sidebarPinned')===null){state.sidebarPinned=new Set(cfg.app.ui?.sidebar_pinned_groups||['core']);saveSidebarState();}$('#brand-title').textContent=cfg.app.app_name;$('#brand-subtitle').textContent=cfg.app.subtitle;$('#version-label').textContent=health.version;$('#workspace-mini').textContent='Workspace · '+ws.relative;state.milestoneView=cfg.app.ui?.milestone_default_view||state.milestoneView;state.graphView=cfg.app.ui?.graph_default_view||state.graphView;state.heatmapMonths=Math.max(1,Math.min(12,Number(cfg.app.ui?.heatmap_months)||state.heatmapMonths||12));localStorage.setItem('heatmapMonths',String(state.heatmapMonths));const theme=localStorage.getItem('theme')||cfg.app.ui?.theme||'light';applyTheme(theme); }

  function bindGlobal(){
    $('#modal-close').onclick=closeModal;$('#modal-backdrop').addEventListener('click',e=>{if(e.target===$('#modal-backdrop'))closeModal()});
    $('#theme-btn').onclick=()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
    $('#zoom-btn').onclick=()=>$('#zoom-menu').classList.toggle('hidden');
    $$('[data-zoom]').forEach(b=>b.onclick=()=>{applyUiScale(b.dataset.zoom);$('#zoom-menu').classList.add('hidden')});
    applyUiScale(state.uiScale);
    /* v260922h · 密度默认紧凑型（并排一屏收纳）；手动切换后记忆用户选择 */
    $('#density-btn').onclick=()=>{const v=state.density==='cozy'?'compact':'cozy';localStorage.setItem('pageDensityManual','1');localStorage.setItem('pageDensity',v);applyDensity(v);fitResearchHeatmap();};
    const savedDensity=localStorage.getItem('pageDensity'), manualDensity=localStorage.getItem('pageDensityManual')==='1';
    applyDensity(manualDensity&&savedDensity?savedDensity:'compact'); /* v260922h · 默认紧凑型：并排一屏、免滚动 */
    $('#global-search-btn').onclick=()=>openGlobalSearch();
    document.addEventListener('keydown',e=>{const mod=e.ctrlKey||e.metaKey,key=e.key.toLowerCase();if(mod&&key==='s'&&$('#md-input')&&state.selectedDoc){e.preventDefault();$('#doc-save')?.click();return}if(mod&&key==='k'){e.preventDefault();openGlobalSearch();}});
    $('#reload-btn').onclick=()=>systemAction('reload');$('#reload-menu-btn').onclick=()=>$('#reload-menu').classList.toggle('hidden');$$('[data-system-action]').forEach(b=>b.onclick=()=>{ $('#reload-menu').classList.add('hidden');systemAction(b.dataset.systemAction)});
    document.addEventListener('click',e=>{if(!e.target.closest('.reload-wrap'))$('#reload-menu').classList.add('hidden');if(!e.target.closest('.zoom-wrap'))$('#zoom-menu').classList.add('hidden')});
    window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue=''}});
    window.addEventListener('hashchange',()=>{const r=location.hash.slice(1)||'overview';if(r!==state.route)navigate(r)});
  }

  async function init(){ try{bindGlobal();await loadBootstrap();renderSidebar();loadWeather();const route=location.hash.slice(1)||'overview';await navigate(route);}catch(e){console.error(e);$('#main').innerHTML=`<div class="card card-pad danger">初始化失败：${esc(e.message)}<br><span class="muted">确认已使用 <span class="mono">python server.py</span> 启动工程。</span></div>`;} }
  window.addEventListener('load',init);
})();
