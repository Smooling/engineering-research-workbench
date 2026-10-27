(() => {
  'use strict';

  const VERSION = '261027.1';
  const MAX_FETCH_NODES = 500;
  const SEARCH_LIMIT = 10;
  const LAYOUT_CACHE_VERSION = 2;
  const GRAPH_HEIGHT = {min:420,default:760,max:1600};
  const DOC_KINDS = new Set(['idea','journal','note','milestone','summary','literature']);
  const KIND_LABEL = {idea:'灵感',journal:'研究日志',note:'笔记',milestone:'里程碑',summary:'工作总结',literature:'文献',project:'项目',tag:'标签'};
  const KIND_COLOR = {idea:'#2a9d8f',journal:'#5b8def',note:'#6f7a8a',milestone:'#c6863b',summary:'#845ec2',literature:'#2673a7',tag:'#b56a9d',project:'#087f8c'};
  const STAR_COLOR = {idea:'#64ded3',journal:'#88b8ff',note:'#c9d9ed',milestone:'#f6c77c',summary:'#c6a4ef',literature:'#6bd7e7',tag:'#d7a1cb',project:'#f0b3a5'};
  const REL_LABEL = {wikilink:'显式引用',tag:'标签关联',project:'项目归属'};
  const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));
  const css = (name, fallback='') => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const route = () => (location.hash || '#overview').slice(1).split('?')[0];
  const now = () => performance.now();

  function hashString(s) {
    let h = 2166136261 >>> 0;
    for (let i=0;i<s.length;i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  function seededUnit(seed) {
    let x = (seed || 1) >>> 0;
    x ^= x << 13; x ^= x >>> 17; x ^= x << 5;
    return ((x >>> 0) % 1000000) / 1000000;
  }
  function safeDateValue(v) { const n = Date.parse(v || ''); return Number.isFinite(n) ? n : 0; }
  function relativeDate(v) {
    const t=safeDateValue(v); if(!t) return '';
    const d=Math.max(0,Date.now()-t), m=Math.floor(d/60000), h=Math.floor(d/3600000), day=Math.floor(d/86400000);
    if(m<1)return '刚刚'; if(m<60)return `${m} 分钟前`; if(h<24)return `${h} 小时前`; if(day<2)return '昨天'; if(day<7)return `${day} 天前`;
    return new Date(t).toLocaleDateString('zh-CN',{month:'numeric',day:'numeric'});
  }
  async function api(url, opts={}) {
    const init={...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}};
    if(init.body && typeof init.body!=='string') init.body=JSON.stringify(init.body);
    const res=await fetch(url,init); let data={}; try{data=await res.json()}catch{}
    if(!res.ok) throw new Error(data.message||data.error||`HTTP ${res.status}`); return data;
  }

  class OptimizedKnowledgeGraph {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.pageToken = `${Date.now()}-${Math.random()}`;
      this.raw = {nodes:[],edges:[],meta:{}};
      this.graph = {nodes:[],edges:[]};
      this.nodeMap = new Map();
      this.adjacency = new Map();
      this.degree = new Map();
      this.edgeImportance = new Map();
      this.communities = new Map();
      this.layout = new Map();
      this.searchIndex = [];
      this.searchHits = new Set();
      this.selectedId = null;
      this.focusDepth = 1;this.scopeProject='';
      this.focusDistances = new Map();
      this.mode = localStorage.getItem('erwGraphView') === '2d' ? '2d' : '3d';
      this.camera = {
        '2d': {panX:0,panY:0,zoom:1,rotX:0,rotY:0},
        '3d': {panX:0,panY:0,zoom:1,rotX:.25,rotY:0},
      };
      this.screen = new Map();
      this.labelBoxes = [];
      this.renderPending = false;
      this.drag = null;
      this.dragMoved = false;
      this.pressNodeId = null;
      this.labelWidth = new Map();
      this.layoutSignature = '';
      this.layoutStats = null;
      this.searchCursor = -1;
      this.destroyed = false;
      this.resizeObserver = null;
      this.starLayout = new Map();
      this.starSprites = new Map();
      this.backgroundStars = this.makeBackgroundStars();
      this.hoveredId = null;
      this.autoRotate = false;
      this.rotationFrame = null;
      this.renderFrame = null;
      this.bindCanvas();
    }

    async init(initialGraph) {
      this.installToolbar();
      this.bindExistingControls();
      this.installViewControls();
      this.installResizeControls();
      this.setStatus('正在建立图结构索引…');
      const graph = initialGraph || await api(`/api/graph?limit=${MAX_FETCH_NODES}`);
      if (this.destroyed || route() !== 'graph' || !this.canvas.isConnected) return;
      this.raw = graph || {nodes:[],edges:[],meta:{}};
      const projects=[...new Set(this.raw.nodes.flatMap(n=>n.kind==='project'?[n.label]:(n.projects?.length?n.projects:n.project?[n.project]:[])))].filter(Boolean);
      const saved=localStorage.getItem('erwGraphProjectScope'),preferred=window.ERWResearchUI?.recent('doc')?.projects?.[0];
      this.scopeProject=saved===null?(projects.includes(preferred)?preferred:projects[0]||''):(projects.includes(saved)?saved:'');

      this.projectPicker=window.ERWProjectScope.mount(document.querySelector('#graph-project-scope'),{names:projects,value:this.scopeProject,onChange:name=>this.setProjectScope(name)});
      this.refreshFilteredGraph(true);this.clearFocus(true);
      this.resizeObserver = new ResizeObserver(() => {if(!this.selectedId&&!this.cameraTouched)this.fitCamera();this.requestRender()});
      this.resizeObserver.observe(this.canvas);
      this.requestRender();
      const meta=this.raw.meta||{};
      this.setStatus(`${this.graph.nodes.length} 节点 · ${this.graph.edges.length} 关系 · Force + LOD${meta.truncated?' · 当前服务端载入 '+meta.shown_documents+'/'+meta.total_documents:''}`);
    }

    destroy() {
      this.destroyed = true;
      this.hideTooltip();
      this.stopRotation();
      cancelAnimationFrame(this.renderFrame);
      this.cameraAnimation=(this.cameraAnimation||0)+1;
      try { this.resizeObserver?.disconnect(); } catch (_) {}
      this.projectPicker?.destroy();
      document.removeEventListener('visibilitychange',this.visibilityHandler);
      this.canvas.onpointerdown=this.canvas.onpointermove=this.canvas.onpointerup=this.canvas.onpointercancel=this.canvas.onpointerleave=this.canvas.onwheel=this.canvas.onkeydown=this.canvas.oncontextmenu=null;
      this.starSprites.clear();
      this.viewControls?.remove();this.rotateButton?.remove();this.legend?.remove();this.tooltip?.remove();this.emptyMessage?.remove();
      this.heightDrag=null;this.canvas.parentElement?.classList.remove('resizing');this.resizeHandle?.remove();
      if(this.outsidePointerHandler)document.removeEventListener('pointerdown',this.outsidePointerHandler,{capture:true});
    }

    installResizeControls(){
      const stage=this.canvas.parentElement,handle=document.createElement('div');
      handle.className='graph-height-handle';handle.tabIndex=0;handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','horizontal');handle.setAttribute('aria-label','调整图谱高度');handle.setAttribute('aria-controls',this.canvas.id);handle.setAttribute('aria-valuemin',GRAPH_HEIGHT.min);handle.setAttribute('aria-valuemax',GRAPH_HEIGHT.max);handle.title='上下拖动调整高度 · 双击恢复默认 · 方向键微调';
      stage.append(handle);this.resizeHandle=handle;
      let saved=0;try{saved=Number(localStorage.getItem('erwGraphHeight'))}catch{}
      this.setGraphHeight(saved>0?saved:GRAPH_HEIGHT.default);
      handle.onpointerdown=e=>{
        if(e.button!==0||this.heightDrag)return;e.preventDefault();e.stopPropagation();handle.focus({preventScroll:true});
        this.heightDrag={pointerId:e.pointerId,startY:e.clientY,height:this.graphHeight,scale:stage.getBoundingClientRect().height/stage.offsetHeight||1};
        stage.classList.add('resizing');handle.setPointerCapture(e.pointerId);this.hideTooltip();
      };
      handle.onpointermove=e=>{const drag=this.heightDrag;if(!drag||e.pointerId!==drag.pointerId)return;e.preventDefault();this.setGraphHeight(drag.height+(e.clientY-drag.startY)/drag.scale)};
      const finish=e=>{if(!this.heightDrag||e.pointerId!==this.heightDrag.pointerId)return;this.heightDrag=null;stage.classList.remove('resizing');if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);this.setGraphHeight(this.graphHeight,true)};
      handle.onpointerup=finish;handle.onpointercancel=finish;handle.onlostpointercapture=finish;
      handle.ondblclick=()=>this.setGraphHeight(GRAPH_HEIGHT.default,true);
      handle.onkeydown=e=>{
        let height=this.graphHeight;const step=e.shiftKey?80:24;
        if(e.key==='ArrowDown')height+=step;else if(e.key==='ArrowUp')height-=step;else if(e.key==='Home')height=GRAPH_HEIGHT.min;else if(e.key==='End')height=GRAPH_HEIGHT.max;else if(e.key==='Enter')height=GRAPH_HEIGHT.default;else return;
        e.preventDefault();e.stopPropagation();this.setGraphHeight(height,true);
      };
    }

    setGraphHeight(value,persist=false){
      const height=Math.round(clamp(Number(value)||GRAPH_HEIGHT.default,GRAPH_HEIGHT.min,GRAPH_HEIGHT.max));this.graphHeight=height;
      document.querySelector('#graph-wrap')?.style.setProperty('--graph-height',height+'px');
      this.resizeHandle?.setAttribute('aria-valuenow',height);this.resizeHandle?.setAttribute('aria-valuetext',height+' 像素');
      if(persist){try{localStorage.setItem('erwGraphHeight',String(height))}catch{}}
    }

    installViewControls() {
      const tools=document.querySelector('.graph-view-tools'),stage=this.canvas.parentElement;
      if(tools){
        const controls=document.createElement('div');controls.className='graph-view-switch';controls.setAttribute('role','group');controls.setAttribute('aria-label','图谱视图');
        controls.innerHTML='<button type="button" data-graph-view="3d">✧ 星图</button><button type="button" data-graph-view="2d">平面</button>';
        tools.prepend(controls);this.viewControls=controls;
        controls.querySelectorAll('[data-graph-view]').forEach(button=>button.onclick=()=>this.setMode(button.dataset.graphView));
        const rotate=document.createElement('button');rotate.type='button';rotate.id='graph-rotate';rotate.className='secondary-btn';rotate.onclick=()=>{this.autoRotate=!this.autoRotate;this.syncViewControls();this.startRotation()};tools.append(rotate);this.rotateButton=rotate;
      }
      const legend=document.createElement('div');legend.className='graph-star-legend';
      legend.innerHTML='<span><i style="--star-color:#f0b3a5"></i>项目</span><span><i style="--star-color:#64ded3"></i>知识</span><span><i style="--star-color:#d7a1cb"></i>标签</span><small>亮度随关联数量变化 · 微光为背景</small>';stage.append(legend);this.legend=legend;
      this.tooltip=document.createElement('div');this.tooltip.className='graph-star-tooltip';this.tooltip.hidden=true;this.tooltip.setAttribute('role','status');stage.append(this.tooltip);
      this.emptyMessage=document.createElement('div');this.emptyMessage.className='graph-empty-message';this.emptyMessage.hidden=true;stage.append(this.emptyMessage);
      this.canvas.tabIndex=0;this.canvas.setAttribute('role','img');
      this.visibilityHandler=()=>{if(document.hidden)this.stopRotation();else this.startRotation()};document.addEventListener('visibilitychange',this.visibilityHandler);
      this.syncViewControls();
    }

    syncViewControls(){
      const star=this.mode==='3d';document.querySelector('#graph-wrap')?.setAttribute('data-graph-view',this.mode);
      document.querySelectorAll('[data-graph-view]').forEach(b=>{if(b.tagName!=='BUTTON')return;const active=b.dataset.graphView===this.mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
      const rotate=document.querySelector('#graph-rotate');if(rotate){rotate.hidden=!star;rotate.textContent=this.autoRotate?'暂停自转':'缓慢自转';rotate.setAttribute('aria-pressed',String(this.autoRotate))}
      const label=document.querySelector('.graph-view-label');if(label)label.textContent=star?'知识星图':'关系网络';
      const help=document.querySelector('.graph-canvas-help');if(help)help.textContent=star?'拖动旋转 · Shift + 拖动平移 · Ctrl + 滚轮缩放 · 点击查看':'拖动平移 · Ctrl + 滚轮缩放 · 点击节点查看文档与关联';
      const copy=document.querySelector('.graph-side-copy');if(copy)copy.textContent=star?'每颗彩色星点对应一条知识、一个项目或标签，弧线表示真实关联。拖动探索不同角度，悬停查看标题，点击查看文档与直接关系。':'拖动空白区域平移；Ctrl + 滚轮缩放。点击节点后会自动进入详情面板并突出直接关联。';
      this.canvas.setAttribute('aria-label',star?'三维知识星图。方向键旋转，Shift 加方向键平移，加减号缩放，Home 全览。也可通过上方搜索选择节点。':'平面知识图谱。方向键平移，加减号缩放，Home 全览。也可通过上方搜索选择节点。');
    }

    setMode(mode){
      if(!['2d','3d'].includes(mode)||mode===this.mode)return;
      this.cameraAnimation=(this.cameraAnimation||0)+1;this.stopRotation();this.mode=mode;this.hoveredId=null;this.hideTooltip();localStorage.setItem('erwGraphView',mode);this.syncViewControls();this.fitCamera();
      if(this.selectedId)this.animateCameraTo(this.selectedId);this.requestRender();this.startRotation();
    }

    activeLayout(){return this.mode==='3d'?this.starLayout:this.layout}

    fitCamera(){
      const c=this.camera[this.mode],rect=this.canvas.getBoundingClientRect();c.panX=c.panY=0;this.cameraTouched=false;
      if(this.mode==='3d'){c.zoom=clamp(Math.min((rect.width-48)/640,(rect.height-100)/640),.08,1.65);return}
      const points=[...this.layout.values()];c.zoom=1;if(!points.length)return;
      const xs=points.map(p=>p.x),ys=points.map(p=>p.y),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
      c.zoom=clamp(Math.min((rect.width-110)/Math.max(120,maxX-minX),(rect.height-100)/Math.max(120,maxY-minY)),.08,1.8);c.panX=-(minX+maxX)/2*c.zoom;c.panY=-(minY+maxY)/2*c.zoom;
    }

    startRotation(){
      this.stopRotation();if(!this.autoRotate||this.mode!=='3d'||this.destroyed||document.hidden||!this.graph.nodes.length)return;
      let last=now();const tick=t=>{this.rotationFrame=null;if(this.destroyed||!this.autoRotate||this.mode!=='3d'||document.hidden)return;
        const elapsed=Math.min(t-last,80);if(t-last>=32){last=t;if(!this.drag&&!this.selectedId&&!this.hoveredId){this.camera['3d'].rotY+=elapsed*.000055;this.requestRender()}}
        this.rotationFrame=requestAnimationFrame(tick)};this.rotationFrame=requestAnimationFrame(tick);
    }
    stopRotation(){cancelAnimationFrame(this.rotationFrame);this.rotationFrame=null}

    makeBackgroundStars(){
      // Decorative dust has no node IDs and is never included in hits or metrics.
      const count=1650;
      return Array.from({length:count},(_,i)=>{const seed=hashString('knowledge-dust-'+i),y=1-2*(i+.5)/count,angle=i*2.399963229728653,r=270*Math.cbrt(.58+.42*seededUnit(seed)),ring=Math.sqrt(1-y*y);return{x:Math.cos(angle)*ring*r,y:y*r,z:Math.sin(angle)*ring*r,size:.36+seededUnit(seed^723)*.8,alpha:.28+seededUnit(seed^846)*.68}});
    }

    constellationLayout(){
      const positions=new Map(),nodes=[...this.graph.nodes].sort((a,b)=>(this.degree.get(String(b.id))||0)-(this.degree.get(String(a.id))||0)||String(a.id).localeCompare(String(b.id)));
      if(nodes.length===1){positions.set(String(nodes[0].id),{x:0,y:0,z:0});return positions}
      const hubs=nodes.filter(n=>n.kind==='project'||(this.degree.get(String(n.id))||0)>=Math.max(3,this.degreeThreshold(.9))).slice(0,12),hubIds=new Set(hubs.map(n=>String(n.id)));
      const place=(i,count,r)=>{const y=1-2*(i+.5)/count,angle=i*2.399963229728653;return{x:Math.cos(angle)*Math.sqrt(1-y*y)*r,y:y*r,z:Math.sin(angle)*Math.sqrt(1-y*y)*r}};
      hubs.forEach((n,i)=>positions.set(String(n.id),place(i,hubs.length,100+seededUnit(hashString(String(n.id)))*65)));
      nodes.forEach((n,i)=>{const id=String(n.id);if(positions.has(id))return;const seed=hashString(id),p=place(i,nodes.length,185+65*seededUnit(seed));
        const anchor=(this.adjacency.get(id)||[]).filter(x=>hubIds.has(x.id)).sort((a,b)=>(this.degree.get(b.id)||0)-(this.degree.get(a.id)||0))[0],center=anchor&&positions.get(anchor.id);
        if(center){const mix=.32;p.x=p.x*(1-mix)+center.x*mix;p.y=p.y*(1-mix)+center.y*mix;p.z=p.z*(1-mix)+center.z*mix}positions.set(id,p)});
      return positions;
    }

    installToolbar() {
      const wrap=document.querySelector('#graph-wrap'); if(!wrap) return;
      let toolbar=document.querySelector('#graph-smart-toolbar');
      if(!toolbar){
        toolbar=document.createElement('section'); toolbar.id='graph-smart-toolbar'; toolbar.className='graph-smart-toolbar';
        toolbar.innerHTML=`
          <div class="graph-smart-search-wrap">
            <div class="graph-smart-search"><span>⌕</span><input id="graph-smart-search" autocomplete="off" placeholder="搜索知识、标签或项目……"><kbd>↑↓ Enter</kbd></div>
            <div class="graph-smart-results hidden" id="graph-smart-results"></div>
          </div>
          <div class="graph-focus-tools" aria-label="图谱聚焦"><div id="graph-project-scope"></div>
            <button class="secondary-btn active" type="button" data-graph-focus="1">直接关系</button>
            <button class="secondary-btn" type="button" data-graph-focus="2">两级关系</button>
            <button class="secondary-btn" type="button" data-graph-focus="0">范围全览</button>
            <span class="graph-tool-sep"></span>
            <button class="ghost-btn" type="button" data-graph-scope="docs">仅知识节点</button>
            <button class="ghost-btn" type="button" data-graph-scope="all">全部节点</button>
          </div>
          <div class="graph-engine-status" id="graph-engine-status"></div><details class="graph-diagnostics"><summary>诊断信息</summary><pre id="graph-diagnostics-text"></pre></details>`;
        wrap.parentElement.insertBefore(toolbar,wrap);
      }
      const input=toolbar.querySelector('#graph-smart-search'); const results=toolbar.querySelector('#graph-smart-results');
      input.onfocus=()=>this.showSuggestions(input.value);
      input.oninput=()=>this.showSuggestions(input.value);
      input.onkeydown=e=>this.onSearchKey(e);
      this.outsidePointerHandler=e=>{if(this.destroyed)return;if(!toolbar.contains(e.target))results.classList.add('hidden')};
      document.addEventListener('pointerdown',this.outsidePointerHandler,{capture:true});
      toolbar.querySelectorAll('[data-graph-focus]').forEach(b=>b.onclick=()=>{
        const d=Number(b.dataset.graphFocus||0); if(!d){this.clearFocus(true);return} this.focusDepth=d; this.updateFocus(); this.syncFocusButtons(); this.requestRender();
      });
      toolbar.querySelector('[data-graph-scope="docs"]').onclick=()=>this.setScope(true);
      toolbar.querySelector('[data-graph-scope="all"]').onclick=()=>this.setScope(false);
    }

    bindExistingControls() {
      document.querySelectorAll('[data-graph-panel]').forEach(button => {
        button.onclick = () => this.setSidePanel(button.dataset.graphPanel);
      });
      const fit=document.querySelector('#graph-fit'); if(fit)fit.onclick=(e)=>{e.preventDefault();this.clearFocus(true)};
      const close=document.querySelector('#graph-preview-close'); if(close)close.onclick=()=>this.clearFocus(false);
      const bundle=document.querySelector('#graph-bundle'); if(bundle)bundle.onclick=()=>this.openBundle();

      document.querySelectorAll('[data-graph-kind],[data-graph-relation]').forEach(input=>{input.onchange=(e)=>{e.stopPropagation();this.persistFilters();this.refreshFilteredGraph(true)}});
      const all=document.querySelector('#graph-filter-all'); if(all)all.onclick=(e)=>{e.preventDefault();e.stopPropagation();document.querySelectorAll('[data-graph-kind]').forEach(x=>x.checked=true);this.persistFilters();this.refreshFilteredGraph(true)};
      const docs=document.querySelector('#graph-filter-docs'); if(docs)docs.onclick=(e)=>{e.preventDefault();e.stopPropagation();this.setScope(true)};
    }

    setSidePanel(name) {
      document.querySelectorAll('[data-graph-panel]').forEach(button => button.classList.toggle('active', button.dataset.graphPanel === name));
      document.querySelectorAll('[data-graph-panel-view]').forEach(panel => panel.classList.toggle('active', panel.dataset.graphPanelView === name));
    }

    persistFilters(){
      localStorage.setItem('graphKinds',JSON.stringify([...document.querySelectorAll('[data-graph-kind]:checked')].map(x=>x.dataset.graphKind)));
      localStorage.setItem('graphRelations',JSON.stringify([...document.querySelectorAll('[data-graph-relation]:checked')].map(x=>x.dataset.graphRelation)));
    }
    setScope(docsOnly){
      document.querySelectorAll('[data-graph-kind]').forEach(x=>x.checked=docsOnly?DOC_KINDS.has(x.dataset.graphKind):true);
      this.persistFilters(); this.refreshFilteredGraph(true);
    }

    refreshFilteredGraph(rebuildLayout=false) {
      const kinds=new Set([...document.querySelectorAll('[data-graph-kind]:checked')].map(x=>x.dataset.graphKind));
      const relations=new Set([...document.querySelectorAll('[data-graph-relation]:checked')].map(x=>x.dataset.graphRelation));
      const scoped=new Set((this.raw.nodes||[]).filter(n=>(n.projects||[]).includes(this.scopeProject)||n.project===this.scopeProject).map(n=>String(n.id)));
      const tags=new Set((this.raw.edges||[]).filter(e=>scoped.has(String(e.source))&&e.relation==='tag').map(e=>String(e.target)));
      const nodes=(this.raw.nodes||[]).filter(n=>kinds.has(n.kind)&&(!this.scopeProject||scoped.has(String(n.id))||(n.kind==='project'&&n.label===this.scopeProject)||(n.kind==='tag'&&tags.has(String(n.id))))); const ids=new Set(nodes.map(n=>String(n.id)));
      const edges=(this.raw.edges||[]).filter(e=>relations.has(e.relation)&&ids.has(String(e.source))&&ids.has(String(e.target)));
      this.graph={nodes,edges}; this.nodeMap=new Map(nodes.map(n=>[String(n.id),n]));
      this.buildAdjacency(); this.buildSearchIndex();
      this.starLayout=this.constellationLayout();this.hoveredId=null;this.hideTooltip();
      if(this.selectedId&&!this.nodeMap.has(this.selectedId)) this.clearFocus(false);
      if(rebuildLayout) this.ensureLayout(); else this.requestRender();
      this.updateFocus();
      this.setStatus(`${nodes.length} 节点 · ${edges.length} 关系 · Force + LOD`);
      this.startRotation();
    }

    setProjectScope(name){
      this.scopeProject=name;localStorage.setItem('erwGraphProjectScope',name);this.projectPicker?.setValue(name);
      const input=document.querySelector('#graph-smart-search');if(input)input.value='';document.querySelector('#graph-smart-results')?.classList.add('hidden');
      this.selectedId=null;this.refreshFilteredGraph(true);this.clearFocus(true);
    }
    buildAdjacency() {
      this.adjacency=new Map(); this.degree=new Map(); this.edgeImportance=new Map(); this._degreeSorted=null;
      for(const n of this.graph.nodes){const id=String(n.id);this.adjacency.set(id,[]);this.degree.set(id,0)}
      for(const e of this.graph.edges){const a=String(e.source),b=String(e.target);if(!this.adjacency.has(a)||!this.adjacency.has(b))continue;this.adjacency.get(a).push({id:b,edge:e});this.adjacency.get(b).push({id:a,edge:e});this.degree.set(a,(this.degree.get(a)||0)+1);this.degree.set(b,(this.degree.get(b)||0)+1)}
      for(const e of this.graph.edges){const a=String(e.source),b=String(e.target);const rel=e.relation==='wikilink'?4:e.relation==='project'?2:1;this.edgeImportance.set(e,rel+(this.degree.get(a)||0)+(this.degree.get(b)||0))}
    }

    buildSearchIndex() {
      this.searchIndex=this.graph.nodes.map(n=>{
        const projects=(n.projects||[]).length?n.projects:(n.project?[n.project]:[]); const tags=n.tags||[];
        const label=String(n.label||n.id||''); return {id:String(n.id),label,kind:n.kind||'',projects,tags,updated:n.updated||'',searchText:[label,...projects,...tags,KIND_LABEL[n.kind]||n.kind||''].join(' ').toLocaleLowerCase()};
      });
    }

    layoutKey(){
      let s=`${LAYOUT_CACHE_VERSION}|${this.graph.nodes.length}|${this.graph.edges.length}|`;
      for(const n of this.graph.nodes)s+=`${n.id};`; for(const e of this.graph.edges)s+=`${e.source}>${e.target}:${e.relation};`;
      return hashString(s).toString(36);
    }

    ensureLayout(){
      const sig=this.layoutKey(); this.layoutSignature=sig;
      const memory=OptimizedKnowledgeGraph.layoutCache.get(sig); if(memory){this.layout=new Map(memory.map(x=>[x[0],{...x[1]}]));this.communities=this.detectCommunities();this.layoutStats={cached:true};this.requestRender();return}
      try{
        const raw=sessionStorage.getItem(`erw:graph-layout:${sig}`); if(raw){const arr=JSON.parse(raw);if(Array.isArray(arr)&&arr.length===this.graph.nodes.length){this.layout=new Map(arr);OptimizedKnowledgeGraph.layoutCache.set(sig,arr);this.communities=this.detectCommunities();this.layoutStats={cached:true};this.requestRender();return}}
      }catch(_){ }
      const t=now(); this.communities=this.detectCommunities(); this.layout=this.forceLayout(); this.layoutStats={cached:false,ms:Math.round((now()-t)*10)/10};
      const arr=[...this.layout.entries()]; OptimizedKnowledgeGraph.layoutCache.set(sig,arr);
      try{if(arr.length<=1200)sessionStorage.setItem(`erw:graph-layout:${sig}`,JSON.stringify(arr))}catch(_){ }
      this.requestRender();
    }

    detectCommunities(){
      const ids=this.graph.nodes.map(n=>String(n.id)); const community=new Map(ids.map((id,i)=>[id,i])); if(ids.length<25)return community;
      const iterations=ids.length>800?3:5;
      for(let it=0;it<iterations;it++){
        let changed=0;
        for(const id of ids){const score=new Map();for(const nb of this.adjacency.get(id)||[]){const c=community.get(nb.id);score.set(c,(score.get(c)||0)+1)}if(!score.size)continue;let best=community.get(id),bestScore=-1;for(const [c,v] of score){if(v>bestScore||(v===bestScore&&c<best)){best=c;bestScore=v}}if(best!==community.get(id)){community.set(id,best);changed++}}
        if(!changed)break;
      }
      const remap=new Map();let k=0;for(const id of ids){const c=community.get(id);if(!remap.has(c))remap.set(c,k++);community.set(id,remap.get(c))}return community;
    }

    forceLayout(){
      const nodes=this.graph.nodes, n=nodes.length; const pos=new Map(); if(!n)return pos;
      const commCount=Math.max(1,new Set(this.communities.values()).size); const communityCenter=new Map();
      for(let c=0;c<commCount;c++){const a=2*Math.PI*c/commCount;communityCenter.set(c,{x:Math.cos(a)*260,y:Math.sin(a)*190})}
      for(let i=0;i<n;i++){const node=nodes[i],id=String(node.id),seed=hashString(id),c=this.communities.get(id)||0,center=communityCenter.get(c)||{x:0,y:0};const a=seededUnit(seed)*Math.PI*2,r=25+80*seededUnit(seed^0x9e3779b9);pos.set(id,{x:center.x+Math.cos(a)*r,y:center.y+Math.sin(a)*r,z:(seededUnit(seed^0x85ebca6b)-.5)*180})}
      if(n===1){const only=pos.values().next().value;only.x=only.y=0;return pos}
      const iter=n<100?140:n<500?90:n<1200?55:36; const sample=n<200?Math.min(32,n-1):n<800?20:12; const ids=nodes.map(x=>String(x.id));
      for(let step=0;step<iter;step++){
        const cool=.9*(1-step/iter)+.08; const delta=new Map(ids.map(id=>[id,{x:0,y:0}]));
        for(const e of this.graph.edges){const a=String(e.source),b=String(e.target),pa=pos.get(a),pb=pos.get(b);if(!pa||!pb)continue;let dx=pb.x-pa.x,dy=pb.y-pa.y,dist=Math.hypot(dx,dy)||1;const desired=e.relation==='project'?95:e.relation==='tag'?82:115;const f=(dist-desired)*.012;dx/=dist;dy/=dist;delta.get(a).x+=dx*f;delta.get(a).y+=dy*f;delta.get(b).x-=dx*f;delta.get(b).y-=dy*f}
        for(let i=0;i<n;i++){const id=ids[i],p=pos.get(id),d=delta.get(id);const stride=1+(hashString(id)%Math.max(1,n-1));for(let s=1;s<=sample;s++){const j=(i+s*stride)%n;if(j===i)continue;const q=pos.get(ids[j]);let dx=p.x-q.x,dy=p.y-q.y,dist2=dx*dx+dy*dy+36,dist=Math.sqrt(dist2);const f=Math.min(2.6,780/dist2);d.x+=dx/dist*f;d.y+=dy/dist*f}const center=communityCenter.get(this.communities.get(id)||0)||{x:0,y:0};d.x+=(center.x-p.x)*.0028;d.y+=(center.y-p.y)*.0028;d.x+=-p.x*.0008;d.y+=-p.y*.0008}
        for(const id of ids){const p=pos.get(id),d=delta.get(id);const mag=Math.hypot(d.x,d.y),cap=8*cool,scale=mag>cap?cap/mag:1;p.x+=d.x*scale;p.y+=d.y*scale}
      }
      let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;for(const p of pos.values()){minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);minY=Math.min(minY,p.y);maxY=Math.max(maxY,p.y)}const cx=(minX+maxX)/2,cy=(minY+maxY)/2,span=Math.max(1,maxX-minX,maxY-minY),scale=650/span;for(const p of pos.values()){p.x=(p.x-cx)*scale;p.y=(p.y-cy)*scale}
      return pos;
    }

    showSuggestions(query=''){
      const box=document.querySelector('#graph-smart-results');if(!box)return;const q=String(query||'').trim().toLocaleLowerCase();let rows=[];
      if(!q){rows=[...this.searchIndex].filter(x=>DOC_KINDS.has(x.kind)).sort((a,b)=>safeDateValue(b.updated)-safeDateValue(a.updated)).slice(0,8).map(x=>({...x,score:0,recent:true}))}
      else{rows=this.searchIndex.map(x=>{const label=x.label.toLocaleLowerCase();let score=0;if(label===q)score=1000;else if(label.startsWith(q))score=700;else if(label.includes(q))score=500;else if(x.tags.some(t=>String(t).toLocaleLowerCase().includes(q)))score=350;else if(x.projects.some(p=>String(p).toLocaleLowerCase().includes(q)))score=300;else if(x.searchText.includes(q))score=150;score+=(this.degree.get(x.id)||0)*.2;return {...x,score}}).filter(x=>x.score>0).sort((a,b)=>b.score-a.score||a.label.localeCompare(b.label,'zh-CN')).slice(0,SEARCH_LIMIT)}
      this.searchHits=new Set(q?rows.map(x=>x.id):[]);this.searchCursor=rows.length?0:-1;box.dataset.ids=JSON.stringify(rows.map(x=>x.id));
      box.innerHTML=`<div class="graph-result-heading">${q?'匹配节点':'最近编辑'}</div>${rows.map((x,i)=>`<button type="button" class="graph-result-row ${i===this.searchCursor?'active':''}" data-graph-result="${esc(x.id)}"><span class="graph-result-kind">${esc(KIND_LABEL[x.kind]||x.kind)}</span><span><strong>${esc(x.label)}</strong><small>${esc((x.projects||[]).join(', ')||(x.tags||[]).slice(0,3).join(', ')||'')}</small></span><time>${esc(x.recent?relativeDate(x.updated):'')}</time></button>`).join('')||'<div class="graph-result-empty">没有找到匹配节点</div>'}`;
      box.classList.remove('hidden');box.querySelectorAll('[data-graph-result]').forEach(btn=>btn.onclick=()=>{this.selectSearchResult(btn.dataset.graphResult);box.classList.add('hidden')});this.requestRender();
    }

    onSearchKey(e){
      const box=document.querySelector('#graph-smart-results');let ids=[];try{ids=JSON.parse(box?.dataset.ids||'[]')}catch{}
      if(e.key==='Escape'){box?.classList.add('hidden');return}
      if((e.key==='ArrowDown'||e.key==='ArrowUp')&&ids.length){e.preventDefault();this.searchCursor=(this.searchCursor+(e.key==='ArrowDown'?1:-1)+ids.length)%ids.length;box.querySelectorAll('.graph-result-row').forEach((x,i)=>x.classList.toggle('active',i===this.searchCursor));box.querySelector('.graph-result-row.active')?.scrollIntoView({block:'nearest'});return}
      if(e.key==='Enter'&&ids.length){e.preventDefault();const id=ids[Math.max(0,this.searchCursor)];this.selectSearchResult(id);box?.classList.add('hidden')}
    }
    selectSearchResult(id){const input=document.querySelector('#graph-smart-search');const node=this.nodeMap.get(id);if(input&&node)input.value=node.label;this.selectNode(id,true)}

    updateFocus(){
      this.focusDistances=new Map();if(!this.selectedId||!this.nodeMap.has(this.selectedId))return;this.focusDistances.set(this.selectedId,0);const q=[this.selectedId];for(let i=0;i<q.length;i++){const id=q[i],d=this.focusDistances.get(id);if(d>=2)continue;for(const nb of this.adjacency.get(id)||[]){if(!this.focusDistances.has(nb.id)){this.focusDistances.set(nb.id,d+1);q.push(nb.id)}}}
    }
    syncFocusButtons(){document.querySelectorAll('[data-graph-focus]').forEach(b=>{const depth=Number(b.dataset.graphFocus||0);b.classList.toggle('active',depth?depth===this.focusDepth&&!!this.selectedId:!this.selectedId);b.disabled=!!depth&&!this.selectedId})}

    selectNode(id,animate=false){
      const node=this.nodeMap.get(String(id));if(!node)return;this.hideTooltip();this.selectedId=String(id);this.focusDepth=this.focusDepth||1;this.updateFocus();this.syncFocusButtons();this.setSidePanel('detail');this.updateSidePanel(node);this.openPreview(node);this.setStatus('主题已聚焦');const bundle=document.querySelector('#graph-bundle');if(bundle)bundle.disabled=false;if(animate)this.animateCameraTo(id);else this.requestRender();
    }
    clearFocus(resetCamera=false){
      this.setSidePanel('overview');this.selectedId=null;this.focusDistances.clear();this.searchHits.clear();this.syncFocusButtons();const title=document.querySelector('#graph-node-title'),info=document.querySelector('#graph-node-info'),bundle=document.querySelector('#graph-bundle');if(title)title.textContent='选择节点';if(info)info.textContent='搜索或点击节点，查看相关主题；需要浏览全部资料时点击“范围全览”。';if(bundle)bundle.disabled=true;this.hidePreview();this.setStatus('项目概览');this.cameraAnimation=(this.cameraAnimation||0)+1;if(resetCamera){this.camera['3d'].rotX=.25;this.camera['3d'].rotY=0;this.fitCamera()}this.hoveredId=null;this.hideTooltip();this.requestRender();
    }

    updateSidePanel(n){
      const title=document.querySelector('#graph-node-title'),info=document.querySelector('#graph-node-info');if(title)title.textContent=n.label||n.id;if(!info)return;const projects=(n.projects||[]).length?n.projects:(n.project?[n.project]:[]),tags=n.tags||[],degree=this.degree.get(String(n.id))||0;info.innerHTML=`<div><b>类型：</b>${esc(KIND_LABEL[n.kind]||n.kind)}</div><div><b>项目：</b>${esc(projects.join(', ')||'—')}</div><div><b>标签：</b>${esc(tags.join(', ')||'—')}</div><div><b>状态：</b>${esc(n.status||'—')}</div><div><b>直接关系：</b>${degree}</div><div class="row-meta graph-selection-hint">已聚焦此主题；可切换直接关系或两级关系。</div>`;
    }

    async openPreview(n){
      const wrap=document.querySelector('#graph-wrap'),panel=document.querySelector('#graph-preview'),body=document.querySelector('#graph-preview-body');if(!wrap||!panel||!body)return;const seq=`${this.pageToken}:${n.id}:${Date.now()}`;this.previewSeq=seq;wrap.classList.add('preview-open');panel.classList.remove('hidden');document.querySelector('#graph-preview-title').textContent=n.label||n.id;const projects=(n.projects||[]).length?n.projects:(n.project?[n.project]:[]);document.querySelector('#graph-preview-meta').textContent=`${KIND_LABEL[n.kind]||n.kind}${projects.length?' · '+projects.join(', '):''}`;body.innerHTML='<div class="empty" style="min-height:120px">正在加载 Markdown…</div>';
      try{let raw='';if(n.virtual){raw=this.virtualMarkdown(n)}else{const doc=await api('/api/docs/'+encodeURIComponent(n.id));raw=doc.body||''}if(this.previewSeq!==seq||this.selectedId!==String(n.id))return;await this.renderMarkdown(body,raw||'*暂无正文*')}catch(err){if(this.previewSeq===seq)body.innerHTML=`<div class="empty danger">预览失败：${esc(err.message)}</div>`}
    }
    hidePreview(){this.previewSeq='';const wrap=document.querySelector('#graph-wrap'),panel=document.querySelector('#graph-preview'),body=document.querySelector('#graph-preview-body');wrap?.classList.remove('preview-open');panel?.classList.add('hidden');if(body)body.innerHTML=''}
    virtualMarkdown(n){const rows=(this.adjacency.get(String(n.id))||[]).map(x=>{const other=this.nodeMap.get(x.id);return other?`- [[${other.label}]] · ${KIND_LABEL[other.kind]||other.kind} · ${REL_LABEL[x.edge.relation]||x.edge.relation}`:''}).filter(Boolean);return `# ${n.label}\n\n> 这是一个由知识图谱自动生成的${KIND_LABEL[n.kind]||n.kind}节点预览。\n\n## 当前可见关联\n\n${rows.join('\n')||'- 当前筛选条件下暂无可见关联。'}\n`}
    async renderMarkdown(out,raw){return window.ERWMarkdown.renderInto(out,raw)}

    async openBundle(){
      if(!this.selectedId)return;const root=this.nodeMap.get(this.selectedId);if(!root)return;const dist=new Map([[this.selectedId,0]]),q=[this.selectedId];for(let i=0;i<q.length;i++){const cur=q[i],d=dist.get(cur);if(d>=2)continue;for(const nb of this.adjacency.get(cur)||[]){if(!dist.has(nb.id)){dist.set(nb.id,d+1);q.push(nb.id)}}}const rows=[...dist.entries()].filter(([id,d])=>id!==this.selectedId&&d<=2&&!this.nodeMap.get(id)?.virtual).map(([id,d])=>({...this.nodeMap.get(id),distance:d})).sort((a,b)=>a.distance-b.distance||String(a.label).localeCompare(String(b.label),'zh-CN'));
      const backdrop=document.querySelector('#modal-backdrop'),title=document.querySelector('#modal-title'),body=document.querySelector('#modal-body'),footer=document.querySelector('#modal-footer');if(!backdrop||!body||!footer)return;title.textContent='整理关联 Markdown';body.innerHTML=`<div class="bundle-root"><strong>${esc(root.label)}</strong><span class="badge accent">核心</span></div><div class="graph-bundle-depth"><label><input type="radio" name="opt-bundle-depth" value="1" checked> 一阶</label><label><input type="radio" name="opt-bundle-depth" value="2"> 二阶</label></div><div class="bundle-list" id="opt-bundle-list">${rows.map(x=>`<label class="bundle-item" data-distance="${x.distance}"><input type="checkbox" value="${esc(x.id)}" ${x.distance===1?'checked':''}><span class="badge">${x.distance} 阶</span><span><strong>${esc(x.label)}</strong><br><span class="row-meta">${esc(KIND_LABEL[x.kind]||x.kind)}</span></span></label>`).join('')||'<div class="empty">当前筛选条件下没有关联 Markdown</div>'}</div>`;footer.innerHTML='<button class="secondary-btn" id="opt-bundle-cancel">取消</button><button class="primary-btn" id="opt-bundle-generate">生成 Markdown</button>';backdrop.classList.remove('hidden');
      const apply=()=>{const depth=Number(document.querySelector('input[name="opt-bundle-depth"]:checked')?.value||1);body.querySelectorAll('.bundle-item').forEach(i=>{i.classList.toggle('hidden',Number(i.dataset.distance)>depth);if(Number(i.dataset.distance)>depth)i.querySelector('input').checked=false})};body.querySelectorAll('input[name="opt-bundle-depth"]').forEach(x=>x.onchange=apply);document.querySelector('#opt-bundle-cancel').onclick=()=>backdrop.classList.add('hidden');document.querySelector('#opt-bundle-generate').onclick=async()=>{const depth=Number(document.querySelector('input[name="opt-bundle-depth"]:checked')?.value||1),ids=[...body.querySelectorAll('.bundle-item:not(.hidden) input:checked')].map(x=>x.value),active=[this.selectedId,...ids,...[...dist.entries()].filter(([id,d])=>d<=depth&&this.nodeMap.get(id)?.virtual).map(([id])=>id)],set=new Set(active),relations=this.graph.edges.filter(e=>set.has(String(e.source))&&set.has(String(e.target)));const r=await api('/api/graph/bundle',{method:'POST',body:{root:this.selectedId,selected_ids:ids,active_node_ids:active,relations}});body.innerHTML=`<textarea class="search-input mono" id="opt-bundle-content" style="height:460px">${esc(r.content||'')}</textarea>`;footer.innerHTML='<button class="secondary-btn" id="opt-bundle-copy">复制</button><button class="primary-btn" id="opt-bundle-done">完成</button>';document.querySelector('#opt-bundle-copy').onclick=()=>navigator.clipboard?.writeText(r.content||'');document.querySelector('#opt-bundle-done').onclick=()=>backdrop.classList.add('hidden')};apply();
    }

    animateCameraTo(id){
      const animation=this.cameraAnimation=(this.cameraAnimation||0)+1,p=this.activeLayout().get(String(id));if(!p){this.requestRender();return}this.cameraTouched=true;const c=this.camera[this.mode],start={...c},target={...c,zoom:Math.max(c.zoom,this.mode==='3d'?1:1.55)};const projected=this.projectBase(p,target);target.panX=-projected.x;target.panY=-projected.y;const t0=now(),dur=window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:320;const tick=()=>{if(this.destroyed||this.cameraAnimation!==animation)return;const u=dur?clamp((now()-t0)/dur,0,1):1,ease=1-Math.pow(1-u,3);c.panX=start.panX+(target.panX-start.panX)*ease;c.panY=start.panY+(target.panY-start.panY)*ease;c.zoom=start.zoom+(target.zoom-start.zoom)*ease;this.requestRender();if(u<1)requestAnimationFrame(tick)};requestAnimationFrame(tick)
    }

    projectBase(p,c){
      if(this.mode==='3d'){const cy=Math.cos(c.rotY),sy=Math.sin(c.rotY),cx=Math.cos(c.rotX),sx=Math.sin(c.rotX);let x=p.x*cy-p.z*sy,z=p.x*sy+p.z*cy,y=p.y*cx-z*sx;z=p.y*sx+z*cx;const ss=850/Math.max(320,850+z);return{x:x*ss*c.zoom,y:y*ss*c.zoom,z,s:ss*c.zoom}}
      return{x:p.x*c.zoom,y:p.y*c.zoom,z:0,s:c.zoom}
    }

    requestRender(){if(this.renderPending||this.destroyed)return;this.renderPending=true;this.renderFrame=requestAnimationFrame(()=>{this.renderPending=false;this.paint()})}
    paint(){
      this.labelBoxes=[];
      if(this.destroyed||!this.canvas.isConnected)return;const rect=this.canvas.getBoundingClientRect();if(rect.width<2||rect.height<2)return;const dpr=Math.min(window.devicePixelRatio||1,2),W=Math.round(rect.width*dpr),H=Math.round(rect.height*dpr);if(this.canvas.width!==W||this.canvas.height!==H){this.canvas.width=W;this.canvas.height=H}const ctx=this.ctx;ctx.setTransform(dpr,0,0,dpr,0,0);const w=rect.width,h=rect.height;ctx.clearRect(0,0,w,h);const c=this.camera[this.mode],margin=52;this.screen=new Map();
      if(this.emptyMessage){this.emptyMessage.hidden=!!this.graph.nodes.length;this.emptyMessage.textContent=this.raw.nodes.length?'当前范围没有节点，试试切换项目或调整筛选。':'还没有知识节点，添加笔记并建立关联后，星图会在这里展开。'}
      if(this.mode==='3d'){this.paintConstellation(ctx,w,h,c);return}
      for(const n of this.graph.nodes){const base=this.layout.get(String(n.id));if(!base)continue;const p=this.projectBase(base,c);p.x+=w/2+c.panX;p.y+=h/2+c.panY;p.visible=p.x>=-margin&&p.x<=w+margin&&p.y>=-margin&&p.y<=h+margin;this.screen.set(String(n.id),p)}
      const visibleNodes=this.graph.nodes.filter(n=>this.screen.get(String(n.id))?.visible);const nodeCount=this.graph.nodes.length,zoom=c.zoom;this.paintEdges(ctx,w,h,zoom);const sorted=visibleNodes.map(n=>({n,p:this.screen.get(String(n.id))})).sort((a,b)=>a.p.z-b.p.z);const labelCandidates=[];
      for(const {n,p} of sorted){const id=String(n.id),dist=this.focusDistances.get(id),isSel=id===this.selectedId,isSearch=this.searchHits.has(id),alpha=this.nodeAlpha(dist,isSel);if(alpha<=.015)continue;const degree=this.degree.get(id)||0,base=n.virtual?7.5:5.5,rad=clamp((base+(isSel?4:dist===1?2:0))*clamp(p.s,.58,1.8),2.8,16);ctx.globalAlpha=alpha;ctx.beginPath();ctx.arc(p.x,p.y,rad,0,Math.PI*2);ctx.fillStyle=n.kind==='project'?css('--accent',KIND_COLOR.project):(KIND_COLOR[n.kind]||css('--accent','#087f8c'));ctx.fill();if(isSel||isSearch){ctx.globalAlpha=1;ctx.strokeStyle=isSel?css('--text','#222'):css('--accent','#087f8c');ctx.lineWidth=isSel?3:2;ctx.stroke()}else if(dist===1){ctx.globalAlpha=.95;ctx.strokeStyle=css('--accent','#087f8c');ctx.lineWidth=1.6;ctx.stroke()}const priority=this.labelPriority(n,id,degree,dist,isSel,isSearch,zoom,nodeCount);if(priority>0)labelCandidates.push({n,p,rad,priority,isSel,dist,isSearch})}
      ctx.globalAlpha=1;this.paintLabels(ctx,labelCandidates,zoom,nodeCount);ctx.globalAlpha=1;
    }

    starSprite(color){
      if(this.starSprites.has(color))return this.starSprites.get(color);
      const sprite=document.createElement('canvas');sprite.width=sprite.height=96;const ctx=sprite.getContext('2d'),rgb=[1,3,5].map(i=>parseInt(color.slice(i,i+2),16)).join(','),glow=ctx.createRadialGradient(48,48,0,48,48,48);
      glow.addColorStop(0,'rgba(255,255,255,1)');glow.addColorStop(.045,'rgba(255,255,255,.98)');glow.addColorStop(.11,`rgba(${rgb},.88)`);glow.addColorStop(.24,`rgba(${rgb},.25)`);glow.addColorStop(.5,`rgba(${rgb},.055)`);glow.addColorStop(1,`rgba(${rgb},0)`);ctx.fillStyle=glow;ctx.fillRect(0,0,96,96);this.starSprites.set(color,sprite);return sprite;
    }

    nebulaSprite(){
      if(this.starSprites.has('nebula'))return this.starSprites.get('nebula');
      const sprite=document.createElement('canvas');sprite.width=sprite.height=192;const ctx=sprite.getContext('2d'),fog=ctx.createRadialGradient(96,96,0,96,96,96);
      fog.addColorStop(0,'rgba(96,179,160,.25)');fog.addColorStop(.3,'rgba(72,145,138,.17)');fog.addColorStop(.65,'rgba(49,106,111,.06)');fog.addColorStop(1,'rgba(49,106,111,0)');ctx.fillStyle=fog;ctx.fillRect(0,0,192,192);this.starSprites.set('nebula',sprite);return sprite;
    }

    paintConstellation(ctx,w,h,c){
      ctx.fillStyle='#030609';ctx.fillRect(0,0,w,h);if(!this.graph.nodes.length)return;
      const center={x:w/2+c.panX,y:h/2+c.panY},radius=290*c.zoom;
      const haze=ctx.createRadialGradient(center.x,center.y,0,center.x,center.y,radius*1.25);haze.addColorStop(0,'rgba(33,67,76,.13)');haze.addColorStop(.72,'rgba(15,30,39,.06)');haze.addColorStop(1,'rgba(3,6,9,0)');ctx.fillStyle=haze;ctx.fillRect(0,0,w,h);
      ctx.save();ctx.globalCompositeOperation='lighter';
      for(const cloud of [{x:100,y:-45,z:40},{x:-70,y:110,z:20}]){const p=this.projectBase(cloud,c),size=300*p.s;ctx.globalAlpha=this.selectedId ? .13 : .48;ctx.drawImage(this.nebulaSprite(),center.x+p.x-size/2,center.y+p.y-size/2,size,size)}
      const dust=this.starSprite('#b6ccde');
      for(const star of this.backgroundStars){const p=this.projectBase(star,c),x=center.x+p.x,y=center.y+p.y;if(x<0||x>w||y<0||y>h)continue;const size=star.size*9*clamp(p.s,.3,2);ctx.globalAlpha=star.alpha*clamp((500-p.z)/650,.3,1)*(this.selectedId ? .28 : 1);ctx.drawImage(dust,x-size/2,y-size/2,size,size)}
      ctx.restore();
      const ordered=[];
      for(const n of this.graph.nodes){const id=String(n.id),base=this.starLayout.get(id);if(!base)continue;const p=this.projectBase(base,c);p.x+=center.x;p.y+=center.y;p.visible=p.x>=-32&&p.x<=w+32&&p.y>=-32&&p.y<=h+32;this.screen.set(id,p);if(p.visible)ordered.push({n,p})}
      this.paintConstellationEdges(ctx,c,center);
      ordered.sort((a,b)=>b.p.z-a.p.z);const labels=[];
      ctx.save();ctx.globalCompositeOperation='lighter';
      for(const {n,p} of ordered){const id=String(n.id),dist=this.focusDistances.get(id),isSel=id===this.selectedId,isSearch=this.searchHits.has(id),hover=id===this.hoveredId,alpha=this.nodeAlpha(dist,isSel);if(alpha<.01)continue;
        const degree=this.degree.get(id)||0,hub=n.kind==='project'||degree>=Math.max(3,this.degreeThreshold(.9)),rad=clamp((1.65+Math.log2(degree+1)*.5+(hub?.55:0))*clamp(p.s,.55,2),1.2,7),size=rad*(isSel||hover||isSearch?15:11);
        ctx.globalAlpha=alpha*clamp((550-p.z)/680,.38,1);ctx.drawImage(this.starSprite(STAR_COLOR[n.kind]||'#b6ccde'),p.x-size/2,p.y-size/2,size,size);
        if(hub||isSel){ctx.strokeStyle=STAR_COLOR[n.kind]||'#c9d9ed';ctx.globalAlpha=alpha*(isSel?.75:.35);ctx.lineWidth=.65;ctx.beginPath();ctx.moveTo(p.x-rad*3,p.y);ctx.lineTo(p.x+rad*3,p.y);ctx.moveTo(p.x,p.y-rad*3);ctx.lineTo(p.x,p.y+rad*3);ctx.stroke()}
        if(isSel||hover||isSearch){ctx.globalAlpha=.85;ctx.strokeStyle='#c2eee9';ctx.lineWidth=1;ctx.beginPath();ctx.arc(p.x,p.y,rad+6,0,Math.PI*2);ctx.stroke()}
        const priority=hover?9500:isSel?9000:isSearch?10000:dist===1?8000:dist===2&&this.focusDepth>=2?7000:hub?4000+degree:0;if(priority)labels.push({n,p,rad,priority,isSel:isSel||hover,dist,isSearch});
      }
      ctx.restore();this.paintLabels(ctx,labels,c.zoom,this.graph.nodes.length);ctx.globalAlpha=1;
    }

    paintConstellationEdges(ctx,c,center){
      let edges=this.graph.edges;if(!this.selectedId&&edges.length>700)edges=[...edges].sort((a,b)=>(this.edgeImportance.get(b)||0)-(this.edgeImportance.get(a)||0)).slice(0,700);
      ctx.save();
      for(const e of edges){const source=String(e.source),target=String(e.target),a=this.screen.get(source),b=this.screen.get(target);if(!a||!b||(!a.visible&&!b.visible))continue;
        const alpha=this.selectedId?this.edgeAlpha(e,c.zoom):.15;if(alpha<.01)continue;
        const direct=this.selectedId&&(source===this.selectedId||target===this.selectedId),hover=source===this.hoveredId||target===this.hoveredId,pa=this.starLayout.get(source),pb=this.starLayout.get(target),seed=hashString(source+'>'+target),bend=1.2+(seed%12)/100,arc=seed%2 ? .16 : -.16;
        const control=this.projectBase({x:(pa.x+pb.x)*.5*bend+(pb.y-pa.y)*arc,y:(pa.y+pb.y)*.5*bend-(pb.x-pa.x)*arc,z:(pa.z+pb.z)*.5*bend+32},c);
        ctx.globalAlpha=(hover?.78:direct?.8:alpha)*clamp((700-(a.z+b.z)*.5)/950,.35,1);ctx.strokeStyle=direct||hover?'#9bebe0':e.relation==='project'?'#cbafb0':'#83a4b4';ctx.lineWidth=direct||hover?1.25:.65;
        ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.quadraticCurveTo(center.x+control.x,center.y+control.y,b.x,b.y);ctx.stroke();
      }
      ctx.restore();
    }

    hideTooltip(){if(this.tooltip)this.tooltip.hidden=true;window.ERWDocReferences?.hover?.close(this.canvas)}
    leaveTooltip(){
      if(window.ERWDocReferences?.hover){window.ERWDocReferences.hover.leave(this.canvas);return}
      this.hoveredId=null;this.hideTooltip();this.requestRender();
    }
    showTooltip(id,x,y){
      const node=this.nodeMap.get(id);if(!node||!this.tooltip){this.hideTooltip();return}
      const preview=window.ERWDocReferences?.hover;
      if(preview){
        this.tooltip.hidden=true;
        const label=this.labelBoxes.find(box=>box.id===id&&x>=box.l&&x<=box.r&&y>=box.t&&y<=box.b);
        const getRect=()=>{const rect=this.canvas.getBoundingClientRect(),p=this.screen.get(id)||{x,y},bounds=label&&this.labelBoxes.find(box=>box.id===id);return bounds?{left:rect.left+bounds.l,right:rect.left+bounds.r,top:rect.top+bounds.t,bottom:rect.top+bounds.b}:{left:rect.left+p.x-6,right:rect.left+p.x+6,top:rect.top+p.y-8,bottom:rect.top+p.y+8}};
        const doc=node.virtual?{...node,title:node.label,projects:node.kind==='project'?[node.label]:[],tags:node.kind==='tag'?[node.label]:[],body:`当前范围内有 ${this.degree.get(id)||0} 条直接关联。\n\n`+(this.adjacency.get(id)||[]).slice(0,8).map(nb=>this.nodeMap.get(nb.id)?.label||'').filter(Boolean).join('、')}:undefined;
        preview.show(this.canvas,{target:id,getRect,doc,onClose:()=>{if(this.hoveredId===id){this.hoveredId=null;this.requestRender()}}});return;
      }
      this.tooltip.textContent=`${node.label||node.id} · ${KIND_LABEL[node.kind]||node.kind} · ${this.degree.get(id)||0} 条关联`;this.tooltip.hidden=false;
      const rect=this.canvas.getBoundingClientRect();this.tooltip.style.left=clamp(x+16,8,Math.max(8,rect.width-this.tooltip.offsetWidth-8))+'px';this.tooltip.style.top=clamp(y-42,8,Math.max(8,rect.height-this.tooltip.offsetHeight-8))+'px';
    }

    nodeAlpha(dist,isSel){if(!this.selectedId)return 1;if(isSel)return 1;if(dist===1)return 1;if(dist===2)return this.focusDepth>=2?.7:0;return 0}
    edgeAlpha(e,zoom){
      const a=String(e.source),b=String(e.target),da=this.focusDistances.get(a),db=this.focusDistances.get(b);if(this.selectedId){if(a===this.selectedId||b===this.selectedId)return 1;if(this.focusDepth>=2&&da!=null&&db!=null&&Math.max(da,db)<=2)return .32;return 0}
      if(zoom<.6)return .06;if(zoom<.9)return .10;if(zoom<1.35)return .16;return .28;
    }
    paintEdges(ctx,w,h,zoom){
      let edges=this.graph.edges;if(!this.selectedId&&zoom<.7&&edges.length>180){const sorted=[...edges].sort((a,b)=>(this.edgeImportance.get(b)||0)-(this.edgeImportance.get(a)||0));edges=sorted.slice(0,Math.max(90,Math.round(edges.length*.24)))}else if(!this.selectedId&&zoom<1&&edges.length>800){edges=[...edges].sort((a,b)=>(this.edgeImportance.get(b)||0)-(this.edgeImportance.get(a)||0)).slice(0,500)}
      for(const e of edges){const a=this.screen.get(String(e.source)),b=this.screen.get(String(e.target));if(!a||!b||(!a.visible&&!b.visible))continue;const alpha=this.edgeAlpha(e,zoom);if(alpha<.01)continue;const direct=this.selectedId&&(String(e.source)===this.selectedId||String(e.target)===this.selectedId);ctx.globalAlpha=alpha;ctx.lineWidth=direct?2.4:1;ctx.strokeStyle=direct?css('--accent','#087f8c'):css('--line-strong','#b7c0c8');ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}ctx.globalAlpha=1;
    }

    labelPriority(n,id,degree,dist,isSel,isSearch,zoom,nodeCount){
      if(isSearch)return 10000;if(isSel)return 9000;if(dist===1)return 8000;if(this.focusDepth>=2&&dist===2&&zoom>=.9)return 7000;if(n.kind==='project')return 5500+degree;if(nodeCount<100&&zoom>=.65)return 4000+degree;if(zoom<.7)return degree>=this.degreeThreshold(.94)?3000+degree:0;if(zoom<1.5){if(degree>=this.degreeThreshold(.82))return 3000+degree;if(n.kind==='tag'&&degree>=3)return 2200+degree;return 0}if(degree>=this.degreeThreshold(.5))return 1800+degree;return n.kind==='tag'?900:1100}
    degreeThreshold(q){if(!this._degreeSorted||this._degreeSorted.length!==this.degree.size)this._degreeSorted=[...this.degree.values()].sort((a,b)=>a-b);if(!this._degreeSorted.length)return 0;return this._degreeSorted[Math.floor((this._degreeSorted.length-1)*q)]||0}
    paintLabels(ctx,candidates,zoom,nodeCount){
      const star=this.mode==='3d',width=this.canvas.getBoundingClientRect().width;
      candidates.sort((a,b)=>b.priority-a.priority);
      const placed=[],limit=star?(this.selectedId?26:7):nodeCount<100?180:nodeCount<500?(zoom>=1.5?140:70):(zoom>=1.5?110:45);let count=0;
      for(const x of candidates){
        if(count>=limit&&!x.isSel&&!x.isSearch)break;
        const text=String(x.n.label||'').slice(0,x.isSel?36:24),fontSize=clamp((x.isSel?12:x.dist===1?11:10)*clamp(zoom,.82,1.28),9,15),weight=(x.isSel||x.dist===1||x.isSearch)?700:500,font=`${weight} ${fontSize}px Microsoft YaHei, sans-serif`;
        ctx.font=font;const key=`${font}|${text}`;let tw=this.labelWidth.get(key);
        if(tw==null){tw=ctx.measureText(text).width;this.labelWidth.set(key,tw)}
        const left=star?Math.max(8,Math.min(x.p.x+x.rad+7,width-tw-8)):x.p.x+x.rad+4,top=x.p.y-fontSize*.72,rect={l:left-2,t:top-2,r:left+tw+3,b:top+fontSize+4};
        const collide=!x.isSel&&!x.isSearch&&placed.some(r=>!(rect.r<r.l||rect.l>r.r||rect.b<r.t||rect.t>r.b));if(collide)continue;
        placed.push(rect);this.labelBoxes.push({...rect,id:String(x.n.id)});
        ctx.globalAlpha=x.isSel||x.isSearch?1:(this.selectedId?(x.dist===1?.95:x.dist===2?.62:.2):.78);
        if(star){ctx.fillStyle='rgba(3,6,9,.78)';ctx.fillRect(rect.l-3,rect.t-1,rect.r-rect.l+6,rect.b-rect.t+2)}
        ctx.fillStyle=star?(x.isSel||x.isSearch?'#e2f7f3':'#a1b8c8'):x.isSel||x.isSearch?css('--text','#222'):css('--muted','#667');ctx.fillText(text,left,x.p.y+fontSize*.25);count++;
      }
      ctx.globalAlpha=1;
    }

    hit(x,y){let best=null,bd=this.mode==='3d'?14:24;for(const n of this.graph.nodes){const p=this.screen.get(String(n.id));if(!p?.visible||this.nodeAlpha(this.focusDistances.get(String(n.id)),String(n.id)===this.selectedId)<.05)continue;const d=Math.hypot(x-p.x,y-p.y);if(d<bd){bd=d;best=String(n.id)}}if(best)return best;for(let i=this.labelBoxes.length-1;i>=0;i--){const b=this.labelBoxes[i];if(this.nodeMap.has(b.id)&&x>=b.l&&x<=b.r&&y>=b.t&&y<=b.b)return b.id}return null}
    bindCanvas(){
      const c=this.canvas;c.oncontextmenu=e=>{if(this.mode==='3d')e.preventDefault()};
      const point=e=>{const rect=c.getBoundingClientRect();return{x:e.clientX-rect.left,y:e.clientY-rect.top}};
      c.onpointerdown=e=>{if(e.button!==0&&e.button!==2)return;this.cameraAnimation=(this.cameraAnimation||0)+1;this.hideTooltip();c.focus({preventScroll:true});const p=point(e);this.pressNodeId=this.hit(p.x,p.y);this.dragMoved=false;this.drag={startX:p.x,startY:p.y,x:p.x,y:p.y,mode:this.mode==='3d'&&!e.shiftKey&&e.button===0?'rotate':'pan'};c.setPointerCapture?.(e.pointerId);c.classList.add('dragging')};
      c.onpointermove=e=>{const p=point(e);if(!this.drag){if(e.pointerType==='touch')return;const id=this.hit(p.x,p.y);if(id!==this.hoveredId){this.hoveredId=id;this.requestRender()}c.style.cursor=id?'pointer':this.mode==='3d'?'grab':'move';if(id)this.showTooltip(id,p.x,p.y);else this.hideTooltip();return}const dx=p.x-this.drag.x,dy=p.y-this.drag.y;if(Math.hypot(p.x-this.drag.startX,p.y-this.drag.startY)>4)this.dragMoved=true;if(!this.dragMoved)return;this.cameraTouched=true;const cam=this.camera[this.mode];if(this.drag.mode==='rotate'){cam.rotY+=dx*.008;cam.rotX=clamp(cam.rotX+dy*.006,-Math.PI/2,Math.PI/2)}else{cam.panX+=dx;cam.panY+=dy}this.drag.x=p.x;this.drag.y=p.y;this.requestRender()};
      c.onpointerup=e=>{if(!this.drag)return;const p=point(e),id=this.hit(p.x,p.y),wasDrag=this.dragMoved;try{c.releasePointerCapture?.(e.pointerId)}catch{}this.drag=null;c.classList.remove('dragging');if(!wasDrag&&e.button===0){if(this.pressNodeId&&id===this.pressNodeId)this.selectNode(id,false);else if(!this.pressNodeId)this.clearFocus(false)}this.pressNodeId=null};
      c.onpointercancel=e=>{this.drag=null;this.pressNodeId=null;c.classList.remove('dragging');try{c.releasePointerCapture?.(e.pointerId)}catch{}};
      c.onpointerleave=()=>this.leaveTooltip();
      c.onwheel=e=>{if(!(e.ctrlKey||e.metaKey))return;e.preventDefault();this.cameraAnimation=(this.cameraAnimation||0)+1;this.cameraTouched=true;this.hideTooltip();const cam=this.camera[this.mode],old=cam.zoom,next=clamp(old*Math.exp(-e.deltaY*.0015),.08,4.5);if(Math.abs(next-old)<1e-4)return;const rect=c.getBoundingClientRect(),cx=e.clientX-rect.left-rect.width/2,cy=e.clientY-rect.top-rect.height/2,localX=(cx-cam.panX)/old,localY=(cy-cam.panY)/old;cam.zoom=next;cam.panX=cx-localX*next;cam.panY=cy-localY*next;this.requestRender()};
      c.onkeydown=e=>{if(e.defaultPrevented)return;const cam=this.camera[this.mode],x=e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:0,y=e.key==='ArrowUp'?-1:e.key==='ArrowDown'?1:0;if(x||y){e.preventDefault();this.hideTooltip();this.cameraAnimation=(this.cameraAnimation||0)+1;this.cameraTouched=true;if(this.mode==='3d'&&!e.shiftKey){cam.rotY+=x*.12;cam.rotX=clamp(cam.rotX+y*.12,-Math.PI/2,Math.PI/2)}else{cam.panX+=x*24;cam.panY+=y*24}this.requestRender()}else if(['+','=','-','_'].includes(e.key)){e.preventDefault();this.hideTooltip();cam.zoom=clamp(cam.zoom*(e.key==='-'||e.key==='_'?.88:1.12),.08,4.5);this.cameraAnimation=(this.cameraAnimation||0)+1;this.cameraTouched=true;this.requestRender()}else if(e.key==='Home'){e.preventDefault();this.clearFocus(true)}else if(e.key==='Escape'){this.clearFocus(false)}};
    }

    setStatus(text){
      const el=document.querySelector('#graph-engine-status'),diagnostics=document.querySelector('#graph-diagnostics-text');
      if(diagnostics)diagnostics.textContent=text+(this.layoutStats?.ms?` · 布局 ${this.layoutStats.ms} ms`:'');
      if(el){const selected=this.nodeMap.get(this.selectedId);el.textContent=`${this.scopeProject?window.ERWResearchUI?.projectLabel(this.scopeProject)||this.scopeProject:'全部项目'} · ${this.graph.nodes.length} 个节点 · ${this.graph.edges.length} 条关系${selected?' · 当前主题：'+(selected.label||'已选主题'):''}`}
      const metrics=document.querySelectorAll('.graph-overview-metrics strong');if(metrics.length){metrics[0].textContent=this.graph.nodes.length;metrics[1].textContent=this.graph.edges.length;metrics[2].textContent=new Set(this.graph.nodes.map(n=>n.kind)).size}
    }
  }
  OptimizedKnowledgeGraph.layoutCache = new Map();

  let instance = null;
  function destroy() {
    instance?.destroy();
    instance = null;
    window.__knowledgeGraphEngine = null;
  }
  async function mount(canvas, graph) {
    destroy();
    const engine = new OptimizedKnowledgeGraph(canvas);
    instance = engine;
    window.__knowledgeGraphEngine = engine;
    await engine.init(graph);
    return engine;
  }
  window.ERWKnowledgeGraph = {mount, destroy};
  window.__knowledgeGraphEngineVersion = VERSION;
})();
