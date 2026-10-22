/* knowledge-graph · 图谱可视化（从内核补丁 web/v260922-research-pages.js 迁出）
 *
 * 两块能力，都通过内核的渲染接管接缝 `window.ERWGraphRenderers` 注册（§6.3，v261009.13）：
 *   ① graph     —— 图谱页（#graph）画布接管：大图力导向布局、Focus+Context、搜索定位、节点预览、导出
 *   ② overview  —— 研究总览页迷你知识关系图（#overview-graph）
 * 内核在渲染这两处时先问注册表：有接管者就不画自己的兜底图，把画布交给插件；
 * 插件抛错或未启用时内核自动回退 drawGraph 兜底（内核不依赖本插件）。
 *
 * 数据面走内核公开 API：GET /api/graph、GET /api/graph/overview、GET /api/docs/<id>、POST /api/graph/bundle。
 * 文案面走内核接缝：window.ERWContract（kind/关系标签）、window.ERWMarkdown（Markdown 渲染）。
 */

/* 接缝就位检查：v261009.13 之前的内核没有渲染接管接缝。此时插件静默不生效并留一条明确日志，
   免得手工装到旧内核上在加载期抛异常（core_min 已声明 v261009.13，正常安装不会遇到）。 */
if (!window.ERWGraphRenderers || typeof window.ERWGraphRenderers.register !== 'function') {
  console.error('[knowledge-graph] 内核缺少 window.ERWGraphRenderers 渲染接管接缝（需要 v261009.13+），本插件不生效');
}

(() => {
  'use strict';

  const MAX_FETCH_NODES = 500;
  const SEARCH_LIMIT = 10;
  const LAYOUT_CACHE_VERSION = 2;
  /* 标签与关系文案走内核契约接缝 window.ERWContract（§6.3，v261009.13）；兜底常量只给极老内核用。
     此前这里自带一份映射表且**缺 experiment** —— 导致「仅知识节点」把实验条目一起取消勾选、
     标签位回落成英文 experiment。改用契约后与内核「实验」口径一致。 */
  const CONTRACT = window.ERWContract || null;
  const DOC_KINDS = new Set(['idea','journal','note','experiment','milestone','summary','literature']);
  const KIND_LABEL = Object.assign({project:'项目', tag:'标签'}, CONTRACT ? CONTRACT.kindLabels() : {idea:'灵感',journal:'研究日志',note:'笔记',experiment:'实验',milestone:'里程碑',summary:'工作总结',literature:'文献'});
  const REL_LABEL = CONTRACT ? Object.fromEntries(CONTRACT.relations().map(r=>[r.id, r.label])) : {wikilink:'显式引用',tag:'标签关联',project:'项目归属'};
  const KIND_COLOR = {idea:'#2a9d8f',journal:'#5b8def',note:'#6f7a8a',experiment:'#d1569a',milestone:'#c6863b',summary:'#845ec2',literature:'#2673a7',tag:'#b56a9d',project:'#087f8c'};
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
    const res=await (window.erwFetch||fetch)(url,init); let data={}; try{data=await res.json()}catch{}
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
      this.focusDepth = 1;
      this.focusDistances = new Map();
      this.mode = '2d'; // A single, readable relationship view across all entry points.
      this.camera = {
        '2d': {panX:0,panY:0,zoom:1,rotX:0,rotY:0},
        '3d': {panX:0,panY:0,zoom:1,rotX:.25,rotY:0},
      };
      this.screen = new Map();
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
      this.bindCanvas();
    }

    async init(initialGraph) {
      this.installToolbar();
      this.bindExistingControls();
      this.setStatus('正在建立图结构索引…');
      const graph = initialGraph || await api(`/api/graph?limit=${MAX_FETCH_NODES}`);
      if (this.destroyed || route() !== 'graph' || !this.canvas.isConnected) return;
      this.raw = graph || {nodes:[],edges:[],meta:{}};
      this.refreshFilteredGraph(true);
      this.resizeObserver = new ResizeObserver(() => this.requestRender());
      this.resizeObserver.observe(this.canvas);
      this.requestRender();
      const meta=this.raw.meta||{};
      this.setStatus(`${this.graph.nodes.length} 节点 · ${this.graph.edges.length} 关系 · Force + LOD${meta.truncated?' · 当前服务端载入 '+meta.shown_documents+'/'+meta.total_documents:''}`);
    }

    destroy() {
      this.destroyed = true;
      try { this.resizeObserver?.disconnect(); } catch (_) {}
      if(this.outsidePointerHandler)document.removeEventListener('pointerdown',this.outsidePointerHandler,{capture:true});
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
          <div class="graph-focus-tools" aria-label="图谱聚焦">
            <button class="secondary-btn active" type="button" data-graph-focus="1">直接关系</button>
            <button class="secondary-btn" type="button" data-graph-focus="2">两级关系</button>
            <button class="secondary-btn" type="button" data-graph-focus="0">恢复全图</button>
            <span class="graph-tool-sep"></span>
            <button class="ghost-btn" type="button" data-graph-scope="docs">仅知识节点</button>
            <button class="ghost-btn" type="button" data-graph-scope="all">全部节点</button>
          </div>
          <div class="graph-engine-status" id="graph-engine-status"></div>`;
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
      const nodes=(this.raw.nodes||[]).filter(n=>kinds.has(n.kind)); const ids=new Set(nodes.map(n=>String(n.id)));
      const edges=(this.raw.edges||[]).filter(e=>relations.has(e.relation)&&ids.has(String(e.source))&&ids.has(String(e.target)));
      this.graph={nodes,edges}; this.nodeMap=new Map(nodes.map(n=>[String(n.id),n]));
      this.buildAdjacency(); this.buildSearchIndex();
      if(this.selectedId&&!this.nodeMap.has(this.selectedId)) this.clearFocus(false);
      if(rebuildLayout) this.ensureLayout(); else this.requestRender();
      this.updateFocus();
      this.setStatus(`${nodes.length} 节点 · ${edges.length} 关系 · Force + LOD`);
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
    syncFocusButtons(){document.querySelectorAll('[data-graph-focus]').forEach(b=>b.classList.toggle('active',Number(b.dataset.graphFocus||0)===this.focusDepth&&!!this.selectedId))}

    selectNode(id,animate=false){
      const node=this.nodeMap.get(String(id));if(!node)return;this.selectedId=String(id);this.focusDepth=this.focusDepth||1;this.updateFocus();this.syncFocusButtons();this.setSidePanel('detail');this.updateSidePanel(node);this.openPreview(node);const bundle=document.querySelector('#graph-bundle');if(bundle)bundle.disabled=false;if(animate)this.animateCameraTo(id);else this.requestRender();
    }
    clearFocus(resetCamera=false){
      this.setSidePanel('overview');this.selectedId=null;this.focusDistances.clear();this.searchHits.clear();this.syncFocusButtons();const title=document.querySelector('#graph-node-title'),info=document.querySelector('#graph-node-info'),bundle=document.querySelector('#graph-bundle');if(title)title.textContent='选择节点';if(info)info.textContent='搜索或点击节点后，将进入 Focus + Context；点击空白处可恢复全图。';if(bundle)bundle.disabled=true;this.hidePreview();if(resetCamera){const c=this.camera[this.mode];c.panX=0;c.panY=0;c.zoom=1;if(this.mode==='3d'){c.rotX=.25;c.rotY=0}}this.requestRender();
    }

    updateSidePanel(n){
      const title=document.querySelector('#graph-node-title'),info=document.querySelector('#graph-node-info');if(title)title.textContent=n.label||n.id;if(!info)return;const projects=(n.projects||[]).length?n.projects:(n.project?[n.project]:[]),tags=n.tags||[],degree=this.degree.get(String(n.id))||0;info.innerHTML=`<div><b>类型：</b>${esc(KIND_LABEL[n.kind]||n.kind)}</div><div><b>项目：</b>${esc(projects.join(', ')||'—')}</div><div><b>标签：</b>${esc(tags.join(', ')||'—')}</div><div><b>状态：</b>${esc(n.status||'—')}</div><div><b>直接关系：</b>${degree}</div><div class="row-meta graph-selection-hint">Focus + Context 已启用；可切换直接关系 / 两级关系。</div>`;
    }

    async openPreview(n){
      const wrap=document.querySelector('#graph-wrap'),panel=document.querySelector('#graph-preview'),body=document.querySelector('#graph-preview-body');if(!wrap||!panel||!body)return;const seq=`${this.pageToken}:${n.id}:${Date.now()}`;this.previewSeq=seq;wrap.classList.add('preview-open');panel.classList.remove('hidden');document.querySelector('#graph-preview-title').textContent=n.label||n.id;const projects=(n.projects||[]).length?n.projects:(n.project?[n.project]:[]);document.querySelector('#graph-preview-meta').textContent=`${KIND_LABEL[n.kind]||n.kind}${projects.length?' · '+projects.join(', '):''}`;body.innerHTML='<div class="empty" style="min-height:120px">正在加载 Markdown…</div>';
      try{let raw='';if(n.virtual){raw=this.virtualMarkdown(n)}else{const doc=await api('/api/docs/'+encodeURIComponent(n.id));raw=doc.body||''}if(this.previewSeq!==seq||this.selectedId!==String(n.id))return;await this.renderMarkdown(body,raw||'*暂无正文*')}catch(err){if(this.previewSeq===seq)body.innerHTML=`<div class="empty danger">预览失败：${esc(err.message)}</div>`}
    }
    hidePreview(){this.previewSeq='';const wrap=document.querySelector('#graph-wrap'),panel=document.querySelector('#graph-preview'),body=document.querySelector('#graph-preview-body');wrap?.classList.remove('preview-open');panel?.classList.add('hidden');if(body)body.innerHTML=''}
    virtualMarkdown(n){const rows=(this.adjacency.get(String(n.id))||[]).map(x=>{const other=this.nodeMap.get(x.id);return other?`- [[${other.label}]] · ${KIND_LABEL[other.kind]||other.kind} · ${REL_LABEL[x.edge.relation]||x.edge.relation}`:''}).filter(Boolean);return `# ${n.label}\n\n> 这是一个由知识图谱自动生成的${KIND_LABEL[n.kind]||n.kind}节点预览。\n\n## 当前可见关联\n\n${rows.join('\n')||'- 当前筛选条件下暂无可见关联。'}\n`}
    async renderMarkdown(out,raw){
      /* 走内核 Markdown 接缝（同一套 marked + DOMPurify + hljs + mermaid/mathjax），
         图片路径归一化用内核的 normalizePaths —— 不再照抄一份渲染与 /workspace-file/ 规则。 */
      if(!window.ERWMarkdown || typeof window.ERWMarkdown.renderInto!=='function')
        throw new Error('内核未提供 ERWMarkdown 渲染接缝（core_min 应 ≥ v261009.13）');
      await window.ERWMarkdown.renderInto(out, raw);
      if(typeof window.ERWMarkdown.normalizePaths==='function') out.innerHTML=window.ERWMarkdown.normalizePaths(out.innerHTML);
    }

    async openBundle(){
      if(!this.selectedId)return;const root=this.nodeMap.get(this.selectedId);if(!root)return;const dist=new Map([[this.selectedId,0]]),q=[this.selectedId];for(let i=0;i<q.length;i++){const cur=q[i],d=dist.get(cur);if(d>=2)continue;for(const nb of this.adjacency.get(cur)||[]){if(!dist.has(nb.id)){dist.set(nb.id,d+1);q.push(nb.id)}}}const rows=[...dist.entries()].filter(([id,d])=>id!==this.selectedId&&d<=2&&!this.nodeMap.get(id)?.virtual).map(([id,d])=>({...this.nodeMap.get(id),distance:d})).sort((a,b)=>a.distance-b.distance||String(a.label).localeCompare(String(b.label),'zh-CN'));
      const backdrop=document.querySelector('#modal-backdrop'),title=document.querySelector('#modal-title'),body=document.querySelector('#modal-body'),footer=document.querySelector('#modal-footer');if(!backdrop||!body||!footer)return;title.textContent='整理关联 Markdown';body.innerHTML=`<div class="bundle-root"><strong>${esc(root.label)}</strong><span class="badge accent">核心</span></div><div class="graph-bundle-depth"><label><input type="radio" name="opt-bundle-depth" value="1" checked> 一阶</label><label><input type="radio" name="opt-bundle-depth" value="2"> 二阶</label></div><div class="bundle-list" id="opt-bundle-list">${rows.map(x=>`<label class="bundle-item" data-distance="${x.distance}"><input type="checkbox" value="${esc(x.id)}" ${x.distance===1?'checked':''}><span class="badge">${x.distance} 阶</span><span><strong>${esc(x.label)}</strong><br><span class="row-meta">${esc(KIND_LABEL[x.kind]||x.kind)}</span></span></label>`).join('')||'<div class="empty">当前筛选条件下没有关联 Markdown</div>'}</div>`;footer.innerHTML='<button class="secondary-btn" id="opt-bundle-cancel">取消</button><button class="primary-btn" id="opt-bundle-generate">生成 Markdown</button>';backdrop.classList.remove('hidden');
      const apply=()=>{const depth=Number(document.querySelector('input[name="opt-bundle-depth"]:checked')?.value||1);body.querySelectorAll('.bundle-item').forEach(i=>{i.classList.toggle('hidden',Number(i.dataset.distance)>depth);if(Number(i.dataset.distance)>depth)i.querySelector('input').checked=false})};body.querySelectorAll('input[name="opt-bundle-depth"]').forEach(x=>x.onchange=apply);document.querySelector('#opt-bundle-cancel').onclick=()=>backdrop.classList.add('hidden');document.querySelector('#opt-bundle-generate').onclick=async()=>{const depth=Number(document.querySelector('input[name="opt-bundle-depth"]:checked')?.value||1),ids=[...body.querySelectorAll('.bundle-item:not(.hidden) input:checked')].map(x=>x.value),active=[this.selectedId,...ids,...[...dist.entries()].filter(([id,d])=>d<=depth&&this.nodeMap.get(id)?.virtual).map(([id])=>id)],set=new Set(active),relations=this.graph.edges.filter(e=>set.has(String(e.source))&&set.has(String(e.target)));const r=await api('/api/graph/bundle',{method:'POST',body:{root:this.selectedId,selected_ids:ids,active_node_ids:active,relations}});body.innerHTML=`<textarea class="search-input mono" id="opt-bundle-content" style="height:460px">${esc(r.content||'')}</textarea>`;footer.innerHTML='<button class="secondary-btn" id="opt-bundle-copy">复制</button><button class="primary-btn" id="opt-bundle-done">完成</button>';document.querySelector('#opt-bundle-copy').onclick=()=>navigator.clipboard?.writeText(r.content||'');document.querySelector('#opt-bundle-done').onclick=()=>backdrop.classList.add('hidden')};apply();
    }

    animateCameraTo(id){
      const p=this.layout.get(String(id));if(!p){this.requestRender();return}const c=this.camera[this.mode],start={...c},target={...c,zoom:Math.max(c.zoom,1.55)};const projected=this.projectBase(p,target);target.panX=-projected.x;target.panY=-projected.y;const t0=now(),dur=320;const tick=()=>{if(this.destroyed)return;const u=clamp((now()-t0)/dur,0,1),ease=1-Math.pow(1-u,3);c.panX=start.panX+(target.panX-start.panX)*ease;c.panY=start.panY+(target.panY-start.panY)*ease;c.zoom=start.zoom+(target.zoom-start.zoom)*ease;this.requestRender();if(u<1)requestAnimationFrame(tick)};requestAnimationFrame(tick)
    }

    projectBase(p,c){
      if(this.mode==='3d'){const cy=Math.cos(c.rotY),sy=Math.sin(c.rotY),cx=Math.cos(c.rotX),sx=Math.sin(c.rotX);let x=p.x*cy-p.z*sy,z=p.x*sy+p.z*cy,y=p.y*cx-z*sx;z=p.y*sx+z*cx;const ss=560/Math.max(160,560+z);return{x:x*ss*c.zoom,y:y*ss*c.zoom,z,s:ss*c.zoom}}
      return{x:p.x*c.zoom,y:p.y*c.zoom,z:0,s:c.zoom}
    }

    requestRender(){if(this.renderPending||this.destroyed)return;this.renderPending=true;requestAnimationFrame(()=>{this.renderPending=false;this.paint()})}
    paint(){
      if(this.destroyed||!this.canvas.isConnected)return;const rect=this.canvas.getBoundingClientRect();if(rect.width<2||rect.height<2)return;const dpr=Math.min(window.devicePixelRatio||1,2),W=Math.round(rect.width*dpr),H=Math.round(rect.height*dpr);if(this.canvas.width!==W||this.canvas.height!==H){this.canvas.width=W;this.canvas.height=H}const ctx=this.ctx;ctx.setTransform(dpr,0,0,dpr,0,0);const w=rect.width,h=rect.height;ctx.clearRect(0,0,w,h);const c=this.camera[this.mode],margin=52;this.screen=new Map();
      for(const n of this.graph.nodes){const base=this.layout.get(String(n.id));if(!base)continue;const p=this.projectBase(base,c);p.x+=w/2+c.panX;p.y+=h/2+c.panY;p.visible=p.x>=-margin&&p.x<=w+margin&&p.y>=-margin&&p.y<=h+margin;this.screen.set(String(n.id),p)}
      const visibleNodes=this.graph.nodes.filter(n=>this.screen.get(String(n.id))?.visible);const nodeCount=this.graph.nodes.length,zoom=c.zoom;this.paintEdges(ctx,w,h,zoom);const sorted=visibleNodes.map(n=>({n,p:this.screen.get(String(n.id))})).sort((a,b)=>a.p.z-b.p.z);const labelCandidates=[];
      for(const {n,p} of sorted){const id=String(n.id),dist=this.focusDistances.get(id),isSel=id===this.selectedId,isSearch=this.searchHits.has(id),alpha=this.nodeAlpha(dist,isSel);if(alpha<=.015)continue;const degree=this.degree.get(id)||0,base=n.virtual?7.5:5.5,rad=clamp((base+(isSel?4:dist===1?2:0))*clamp(p.s,.58,1.8),2.8,16);ctx.globalAlpha=alpha;ctx.beginPath();ctx.arc(p.x,p.y,rad,0,Math.PI*2);ctx.fillStyle=n.kind==='project'?css('--accent',KIND_COLOR.project):(KIND_COLOR[n.kind]||css('--accent','#087f8c'));ctx.fill();if(isSel||isSearch){ctx.globalAlpha=1;ctx.strokeStyle=isSel?css('--text','#222'):css('--accent','#087f8c');ctx.lineWidth=isSel?3:2;ctx.stroke()}else if(dist===1){ctx.globalAlpha=.95;ctx.strokeStyle=css('--accent','#087f8c');ctx.lineWidth=1.6;ctx.stroke()}const priority=this.labelPriority(n,id,degree,dist,isSel,isSearch,zoom,nodeCount);if(priority>0)labelCandidates.push({n,p,rad,priority,isSel,dist,isSearch})}
      ctx.globalAlpha=1;this.paintLabels(ctx,labelCandidates,zoom,nodeCount);ctx.globalAlpha=1;
    }

    nodeAlpha(dist,isSel){if(!this.selectedId)return 1;if(isSel)return 1;if(dist===1)return 1;if(dist===2)return this.focusDepth>=2?.55:.16;return .12}
    edgeAlpha(e,zoom){
      const a=String(e.source),b=String(e.target),da=this.focusDistances.get(a),db=this.focusDistances.get(b);if(this.selectedId){if(a===this.selectedId||b===this.selectedId)return 1;if(this.focusDepth>=2&&da!=null&&db!=null&&Math.max(da,db)<=2)return .32;return .025}
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
      candidates.sort((a,b)=>b.priority-a.priority);const placed=[],limit=nodeCount<100?180:nodeCount<500?(zoom>=1.5?140:70):(zoom>=1.5?110:45);let count=0;
      for(const x of candidates){if(count>=limit&&!x.isSel&&!x.isSearch)break;const text=String(x.n.label||'').slice(0,x.isSel?36:24),fontSize=clamp((x.isSel?12:x.dist===1?11:10)*clamp(zoom,.82,1.28),9,15),weight=(x.isSel||x.dist===1||x.isSearch)?700:500,font=`${weight} ${fontSize}px Microsoft YaHei, sans-serif`;ctx.font=font;const key=`${font}|${text}`;let tw=this.labelWidth.get(key);if(tw==null){tw=ctx.measureText(text).width;this.labelWidth.set(key,tw)}const left=x.p.x+x.rad+4,top=x.p.y-fontSize*.72,rect={l:left-2,t:top-2,r:left+tw+3,b:top+fontSize+4};const collide=!x.isSel&&!x.isSearch&&placed.some(r=>!(rect.r<r.l||rect.l>r.r||rect.b<r.t||rect.t>r.b));if(collide)continue;placed.push(rect);ctx.globalAlpha=x.isSel||x.isSearch?1:(this.selectedId?(x.dist===1?.95:x.dist===2?.62:.2):.78);ctx.fillStyle=x.isSel||x.isSearch?css('--text','#222'):css('--muted','#667');ctx.fillText(text,left,x.p.y+fontSize*.25);count++}ctx.globalAlpha=1;
    }

    hit(x,y){let best=null,bd=24;for(const n of this.graph.nodes){const p=this.screen.get(String(n.id));if(!p?.visible)continue;const d=Math.hypot(x-p.x,y-p.y);if(d<bd){bd=d;best=String(n.id)}}return best}
    bindCanvas(){
      const c=this.canvas;c.oncontextmenu=e=>{if(this.mode==='3d')e.preventDefault()};
      c.onpointerdown=e=>{this.pressNodeId=this.hit(e.offsetX,e.offsetY);this.dragMoved=false;this.drag={x:e.offsetX,y:e.offsetY,mode:(this.mode==='3d'&&(e.altKey||e.button===2))?'rotate':'pan'};c.setPointerCapture?.(e.pointerId)};
      c.onpointermove=e=>{if(!this.drag)return;const dx=e.offsetX-this.drag.x,dy=e.offsetY-this.drag.y;if(Math.hypot(dx,dy)>1)this.dragMoved=true;const cam=this.camera[this.mode];if(this.drag.mode==='rotate'){cam.rotY+=dx*.008;cam.rotX=clamp(cam.rotX+dy*.006,-1.2,1.2)}else{cam.panX+=dx;cam.panY+=dy}this.drag.x=e.offsetX;this.drag.y=e.offsetY;this.requestRender()};
      c.onpointerup=e=>{const id=this.hit(e.offsetX,e.offsetY),wasDrag=this.dragMoved;try{c.releasePointerCapture?.(e.pointerId)}catch{}this.drag=null;if(!wasDrag){if(this.pressNodeId&&id===this.pressNodeId)this.selectNode(id,false);else if(!this.pressNodeId)this.clearFocus(false)}this.pressNodeId=null};
      c.onpointercancel=e=>{this.drag=null;this.pressNodeId=null;try{c.releasePointerCapture?.(e.pointerId)}catch{}};
      c.onwheel=e=>{if(!(e.ctrlKey||e.metaKey))return;e.preventDefault();const cam=this.camera[this.mode],old=cam.zoom,next=clamp(old*Math.exp(-e.deltaY*.0015),.32,4.5);if(Math.abs(next-old)<1e-4)return;const rect=c.getBoundingClientRect(),cx=e.clientX-rect.left-rect.width/2,cy=e.clientY-rect.top-rect.height/2,localX=(cx-cam.panX)/old,localY=(cy-cam.panY)/old;cam.zoom=next;cam.panX=cx-localX*next;cam.panY=cy-localY*next;this.requestRender()};
    }

    setStatus(text){const el=document.querySelector('#graph-engine-status');if(el)el.textContent=text+(this.layoutStats?.ms?` · 布局 ${this.layoutStats.ms} ms`:'')}
  }
  OptimizedKnowledgeGraph.layoutCache = new Map();

  let instance=null;

  /* v261009.18 · 图谱**页面整体由本插件渲染**：内核 renderGraphPage 只问注册表，
     有本插件就把 #main 交给 `mount(host, ctx)`（内核已不再自带渲染器——那份简易图按用户要求删掉了）。
     markup 原先在内核 app.js 里，现随功能一起搬进插件。 */
  const GRAPH_KINDS=[['idea','灵感'],['journal','研究日志'],['note','笔记'],['experiment','实验'],['milestone','里程碑'],['summary','工作总结'],['literature','文献'],['tag','标签'],['project','项目']];
  const GRAPH_RELATION_FALLBACK=[['uses-knowledge','依据知识'],['uses-data','使用数据'],['cites','引用文献'],['series','同系列'],['chain-prev','上一环节'],['chain-next','下一环节'],['produces','产出汇总'],['wikilink','显式引用'],['tag','标签关联'],['project','项目归属']];
  function lsSet(key,fallback){try{const v=JSON.parse(localStorage.getItem(key)||'null');return new Set(Array.isArray(v)?v:fallback)}catch{return new Set(fallback)}}
  function graphMarkup(contract){
    const kindLabels=(contract&&contract.kindLabels)?contract.kindLabels():{};
    const rels=(contract&&contract.relations)?contract.relations():GRAPH_RELATION_FALLBACK.map(([id,label])=>({id,label}));
    const onKinds=lsSet('graphKinds',GRAPH_KINDS.map(x=>x[0]));
    const onRels=lsSet('graphRelations',rels.map(r=>r.id));
    if(localStorage.getItem('graphRelationsV2')!=='1'){ try{localStorage.setItem('graphRelations',JSON.stringify(rels.map(r=>r.id)));localStorage.setItem('graphRelationsV2','1')}catch{} }
    const view=(localStorage.getItem('graphView')||'2d');
    return '<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">RELATION MAP</div><h3>知识图谱</h3></div>'
      +'<div class="graph-view-tools"><div class="view-tabs"><button data-gview="2d" class="'+(view==='2d'?'active':'')+'">2D</button><button data-gview="3d" class="'+(view==='3d'?'active':'')+'">3D 星图</button></div><button class="secondary-btn" id="graph-fit" type="button">⤢ 全览</button></div></div>'
      +'<div class="graph-wrap" id="graph-wrap"><div class="graph-canvas-wrap"><canvas class="graph-canvas" id="graph-canvas"></canvas><div class="graph-canvas-help">空白处拖动平移 · 3D 下 Alt/右键拖动旋转 · Ctrl+滚轮缩放</div></div>'
      +'<section class="card graph-preview hidden" id="graph-preview"><div class="preview-pane-head"><div><div class="card-kicker">MARKDOWN PREVIEW</div><h3 id="graph-preview-title">节点预览</h3></div><button class="ghost-btn" id="graph-preview-close" type="button">关闭</button></div><div class="preview-pane-meta" id="graph-preview-meta"></div><div class="md-preview graph-preview-body" id="graph-preview-body"></div></section>'
      +'<aside class="card graph-side"><h3 id="graph-node-title">选择节点</h3><div class="graph-node-info" id="graph-node-info">点击任意节点后，将高亮相邻节点与关系边。点击画布空白处可取消高亮。</div><div style="margin-top:12px"><button class="primary-btn" id="graph-bundle" disabled>整理关联 Markdown</button></div>'
      +'<div class="graph-filter"><strong>显示节点类别</strong><div class="graph-filter-grid">'+GRAPH_KINDS.map(([k,label])=>'<label><input type="checkbox" data-graph-kind="'+k+'" '+(onKinds.has(k)?'checked':'')+'> '+(kindLabels[k]||label)+'</label>').join('')+'</div><div class="graph-filter-actions"><button class="ghost-btn" id="graph-filter-all">全选</button><button class="ghost-btn" id="graph-filter-docs">仅知识条目</button></div></div>'
      +'<div class="graph-filter"><strong>关系来源</strong><div class="graph-filter-grid">'+rels.map(r=>'<label><input type="checkbox" data-graph-relation="'+esc(r.id)+'" '+(onRels.has(r.id)?'checked':'')+'> '+esc(r.label)+'</label>').join('')+'</div><div class="row-meta">隐藏“标签”或“项目”节点时，对应关系边也会立即从图谱和导出结果中移除。</div></div></aside></div></div>';
  }
  function mountGraph(host, ctx){
    if(!host) throw new Error('内核没有给出挂载容器');
    host.innerHTML=graphMarkup((ctx&&ctx.contract)||window.ERWContract||null);
    const canvas=host.querySelector('#graph-canvas');
    if(!canvas) throw new Error('图谱页缺少 #graph-canvas');
    instance?.destroy(); instance=null;
    canvas.dataset.optimizedGraph='1';
    instance=new OptimizedKnowledgeGraph(canvas);
    window.__knowledgeGraphEngine=instance;   /* 调试/测试句柄 */
    return instance.init().catch(err=>{
      console.error('[knowledge-graph]',err);
      const st=host.querySelector('#graph-engine-status');
      if(st) st.replaceChildren(document.createTextNode('图谱引擎加载失败：'+err.message));
      throw err;
    });
  }
  window.ERWGraphRenderers?.register?.({ id:'knowledge-graph', graph:{ mount: mountGraph } });

  /* 实例生命周期归插件自己：内核只在进入图谱页时喊 enhance，离开页面由这里释放。 */
  window.addEventListener('hashchange',()=>{ if(route()!=='graph'){ instance?.destroy(); instance=null; } });
})();

(() => {
  'use strict';

  const ROUTE = 'research-overview';
  const MAX_NODES = 80;
  const KIND_COLOR = {idea:'#2a9d8f',journal:'#5b8def',note:'#6f7a8a',milestone:'#c6863b',summary:'#845ec2',literature:'#2673a7',tag:'#b56a9d',project:'#087f8c'};
  const route = () => (location.hash || '#overview').slice(1).split('?')[0];
  const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
  const css = (name,fallback='') => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

  function hashString(s) {
    let h=2166136261>>>0;
    for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}
    return h>>>0;
  }
  function seeded(seed){
    let x=(seed||1)>>>0;
    x^=x<<13;x^=x>>>17;x^=x<<5;
    return ((x>>>0)%1000000)/1000000;
  }

  class OverviewGraph {
    constructor(canvas, graph) {
      this.canvas=canvas;
      this.ctx=canvas.getContext('2d');
      this.graph=graph||{nodes:[],edges:[]};
      this.nodes=(this.graph.nodes||[]).slice(0,MAX_NODES);
      this.nodeMap=new Map(this.nodes.map(n=>[String(n.id),n]));
      this.edges=(this.graph.edges||[]).filter(e=>this.nodeMap.has(String(e.source))&&this.nodeMap.has(String(e.target)));
      this.adj=new Map(this.nodes.map(n=>[String(n.id),[]]));
      this.degree=new Map(this.nodes.map(n=>[String(n.id),0]));
      this.layout=new Map();
      this.screen=new Map();
      this.labelWidths=new Map();
      this.camera={panX:0,panY:0,zoom:1};
      this.drag=null;
      this.dragMoved=false;
      this.pressId=null;
      this.renderPending=false;
      this.destroyed=false;
      this.buildIndex();
      this.layoutGraph();
      this.fit();
      this.bind();
      this.resizeObserver=new ResizeObserver(()=>{this.fit(false);this.requestRender()});
      this.resizeObserver.observe(canvas);
      this.requestRender();
    }

    destroy(){this.destroyed=true;try{this.resizeObserver?.disconnect()}catch{}}

    buildIndex(){
      for(const e of this.edges){
        const a=String(e.source),b=String(e.target);
        this.adj.get(a)?.push(b);this.adj.get(b)?.push(a);
        this.degree.set(a,(this.degree.get(a)||0)+1);
        this.degree.set(b,(this.degree.get(b)||0)+1);
      }
      this.degreeSorted=[...this.degree.values()].sort((a,b)=>a-b);
    }

    communities(){
      const ids=this.nodes.map(n=>String(n.id));
      const c=new Map(ids.map((id,i)=>[id,i]));
      if(ids.length<18)return c;
      for(let it=0;it<5;it++){
        let changed=0;
        for(const id of ids){
          const scores=new Map();
          for(const nb of this.adj.get(id)||[]){const x=c.get(nb);scores.set(x,(scores.get(x)||0)+1)}
          if(!scores.size)continue;
          let best=c.get(id),score=-1;
          for(const [k,v] of scores){if(v>score||(v===score&&k<best)){best=k;score=v}}
          if(best!==c.get(id)){c.set(id,best);changed++}
        }
        if(!changed)break;
      }
      const remap=new Map();let next=0;
      for(const id of ids){const x=c.get(id);if(!remap.has(x))remap.set(x,next++);c.set(id,remap.get(x))}
      return c;
    }

    layoutGraph(){
      const n=this.nodes.length;if(!n)return;
      const community=this.communities();
      const count=Math.max(1,new Set(community.values()).size);
      const centers=new Map();
      for(let i=0;i<count;i++){const a=i/count*Math.PI*2;centers.set(i,{x:Math.cos(a)*230,y:Math.sin(a)*160})}
      for(const node of this.nodes){
        const id=String(node.id),seed=hashString(id),center=centers.get(community.get(id)||0)||{x:0,y:0},a=seeded(seed)*Math.PI*2,r=24+70*seeded(seed^0x9e3779b9);
        this.layout.set(id,{x:center.x+Math.cos(a)*r,y:center.y+Math.sin(a)*r});
      }
      const ids=this.nodes.map(n=>String(n.id));
      const iterations=n<40?110:80;
      for(let step=0;step<iterations;step++){
        const delta=new Map(ids.map(id=>[id,{x:0,y:0}]));
        const cool=.9*(1-step/iterations)+.1;
        for(const e of this.edges){
          const a=String(e.source),b=String(e.target),pa=this.layout.get(a),pb=this.layout.get(b);if(!pa||!pb)continue;
          let dx=pb.x-pa.x,dy=pb.y-pa.y,d=Math.hypot(dx,dy)||1;
          const target=e.relation==='tag'?75:e.relation==='project'?88:105,f=(d-target)*.014;
          dx/=d;dy/=d;delta.get(a).x+=dx*f;delta.get(a).y+=dy*f;delta.get(b).x-=dx*f;delta.get(b).y-=dy*f;
        }
        for(let i=0;i<ids.length;i++){
          const id=ids[i],p=this.layout.get(id),d=delta.get(id);
          for(let j=i+1;j<ids.length;j++){
            const qid=ids[j],q=this.layout.get(qid);let dx=p.x-q.x,dy=p.y-q.y,ds=dx*dx+dy*dy+64,dist=Math.sqrt(ds),f=Math.min(2.2,620/ds);dx/=dist;dy/=dist;
            d.x+=dx*f;d.y+=dy*f;delta.get(qid).x-=dx*f;delta.get(qid).y-=dy*f;
          }
          const center=centers.get(community.get(id)||0)||{x:0,y:0};
          d.x+=(center.x-p.x)*.0025-p.x*.0007;d.y+=(center.y-p.y)*.0025-p.y*.0007;
        }
        for(const id of ids){const p=this.layout.get(id),d=delta.get(id),mag=Math.hypot(d.x,d.y),cap=7*cool,s=mag>cap?cap/mag:1;p.x+=d.x*s;p.y+=d.y*s}
      }
    }

    fit(resetPan=true){
      const rect=this.canvas.getBoundingClientRect();if(rect.width<20||rect.height<20||!this.layout.size)return;
      let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
      for(const p of this.layout.values()){minX=Math.min(minX,p.x);maxX=Math.max(maxX,p.x);minY=Math.min(minY,p.y);maxY=Math.max(maxY,p.y)}
      const spanX=Math.max(1,maxX-minX),spanY=Math.max(1,maxY-minY);
      this.camera.zoom=clamp(Math.min((rect.width-70)/spanX,(rect.height-60)/spanY),.5,1.45);
      if(resetPan){this.camera.panX=-(minX+maxX)/2*this.camera.zoom;this.camera.panY=-(minY+maxY)/2*this.camera.zoom}
    }

    threshold(q){if(!this.degreeSorted.length)return 0;return this.degreeSorted[Math.floor((this.degreeSorted.length-1)*q)]||0}
    requestRender(){if(this.renderPending||this.destroyed)return;this.renderPending=true;requestAnimationFrame(()=>{this.renderPending=false;this.paint()})}

    paint(){
      if(this.destroyed||!this.canvas.isConnected)return;
      const rect=this.canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2),W=Math.round(rect.width*dpr),H=Math.round(rect.height*dpr);
      if(this.canvas.width!==W||this.canvas.height!==H){this.canvas.width=W;this.canvas.height=H}
      const ctx=this.ctx,w=rect.width,h=rect.height;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);this.screen.clear();
      for(const n of this.nodes){const p=this.layout.get(String(n.id));if(!p)continue;this.screen.set(String(n.id),{x:w/2+this.camera.panX+p.x*this.camera.zoom,y:h/2+this.camera.panY+p.y*this.camera.zoom})}
      const zoom=this.camera.zoom;
      let edges=this.edges;
      if(zoom<.75&&edges.length>120)edges=[...edges].sort((a,b)=>((this.degree.get(String(b.source))||0)+(this.degree.get(String(b.target))||0))-((this.degree.get(String(a.source))||0)+(this.degree.get(String(a.target))||0))).slice(0,Math.max(70,Math.round(edges.length*.35)));
      ctx.strokeStyle=css('--line-strong','#bcc8ca');ctx.lineWidth=1;
      for(const e of edges){const a=this.screen.get(String(e.source)),b=this.screen.get(String(e.target));if(!a||!b)continue;ctx.globalAlpha=zoom<.8?.09:.16;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}
      ctx.globalAlpha=1;
      const labels=[];
      for(const n of this.nodes){
        const id=String(n.id),p=this.screen.get(id);if(!p||p.x<-30||p.x>w+30||p.y<-30||p.y>h+30)continue;
        const deg=this.degree.get(id)||0,rad=n.virtual?5.5:4.5;
        ctx.beginPath();ctx.arc(p.x,p.y,rad,0,Math.PI*2);ctx.fillStyle=KIND_COLOR[n.kind]||css('--accent','#087f83');ctx.fill();
        const priority=n.kind==='project'?900+deg:n.kind==='tag'?500+deg:deg>=this.threshold(.78)?700+deg:zoom>=1.15?300+deg:0;
        if(priority>0)labels.push({n,p,rad,priority});
      }
      labels.sort((a,b)=>b.priority-a.priority);const placed=[];let shown=0,maxLabels=zoom<.75?12:zoom<1.15?22:36;
      for(const x of labels){if(shown>=maxLabels)break;const text=String(x.n.label||'').slice(0,18),font=`${x.n.kind==='project'?'700':'500'} 10px Microsoft YaHei, sans-serif`;ctx.font=font;const key=font+'|'+text;let width=this.labelWidths.get(key);if(width==null){width=ctx.measureText(text).width;this.labelWidths.set(key,width)}const left=x.p.x+x.rad+4,box={l:left-2,t:x.p.y-8,r:left+width+3,b:x.p.y+7};if(placed.some(r=>!(box.r<r.l||box.l>r.r||box.b<r.t||box.t>r.b)))continue;placed.push(box);ctx.globalAlpha=.78;ctx.fillStyle=css('--muted','#68777c');ctx.fillText(text,left,x.p.y+3);shown++}
      ctx.globalAlpha=1;
    }

    hit(x,y){let best=null,dist=18;for(const n of this.nodes){const p=this.screen.get(String(n.id));if(!p)continue;const d=Math.hypot(x-p.x,y-p.y);if(d<dist){dist=d;best=String(n.id)}}return best}
    bind(){
      const c=this.canvas;c.style.cursor='grab';
      c.onpointerdown=e=>{this.pressId=this.hit(e.offsetX,e.offsetY);this.dragMoved=false;this.drag={x:e.offsetX,y:e.offsetY};c.setPointerCapture?.(e.pointerId)};
      c.onpointermove=e=>{if(!this.drag)return;const dx=e.offsetX-this.drag.x,dy=e.offsetY-this.drag.y;if(Math.hypot(dx,dy)>1)this.dragMoved=true;this.camera.panX+=dx;this.camera.panY+=dy;this.drag.x=e.offsetX;this.drag.y=e.offsetY;c.style.cursor='grabbing';this.requestRender()};
      c.onpointerup=e=>{const id=this.hit(e.offsetX,e.offsetY),moved=this.dragMoved;try{c.releasePointerCapture?.(e.pointerId)}catch{}this.drag=null;c.style.cursor='grab';if(!moved&&id&&id===this.pressId)this.openFullGraph(id);this.pressId=null};
      c.onpointercancel=e=>{this.drag=null;this.pressId=null;c.style.cursor='grab';try{c.releasePointerCapture?.(e.pointerId)}catch{}};
      c.onwheel=e=>{if(!(e.ctrlKey||e.metaKey))return;e.preventDefault();const old=this.camera.zoom,next=clamp(old*Math.exp(-e.deltaY*.0015),.4,3);const r=c.getBoundingClientRect(),cx=e.clientX-r.left-r.width/2,cy=e.clientY-r.top-r.height/2,lx=(cx-this.camera.panX)/old,ly=(cy-this.camera.panY)/old;this.camera.zoom=next;this.camera.panX=cx-lx*next;this.camera.panY=cy-ly*next;this.requestRender()};
    }

    openFullGraph(id){
      sessionStorage.setItem('erw:pending-graph-focus',id);
      location.hash='graph';
      focusWhenReady();
    }
  }

  let instance=null, seq=0;

  /* 注册总览迷你图的接管（同一接缝的 overview 作用域）：内核在渲染研究总览页时调用。
     两条退出路径要分清（ui_smoke 抓过一次真 bug）：
       · 真失败（取数 HTTP 错）→ **throw**，让内核回退 drawGraph 兜底；
       · 被取消（页面已经切走 / 画布已被更新的一次渲染换掉）→ **静默返回 null**，
         那不是失败，不该往控制台丢 error，也不该去碰别人正在用的画布。 */
  window.ERWGraphRenderers?.register?.({
    id:'knowledge-graph-overview',
    overview:{
      async enhance(canvas){
        const old=canvas||document.querySelector('#overview-graph');
        if(!old) return null;
        const mine=++seq;
        const res=await (window.erwFetch||fetch)(`/api/graph/overview?limit=${MAX_NODES}`);
        if(!res.ok) throw new Error(`HTTP ${res.status}`);
        const graph=await res.json();
        const cur=document.querySelector('#overview-graph');
        if(!cur||mine!==seq||cur!==old) return null;   /* 已切走 / 已被更新的一次渲染接管 */
        instance?.destroy();
        const next=cur.cloneNode(false);next.dataset.modernOverviewGraph='1';next.setAttribute('aria-label','新版知识关系预览');cur.replaceWith(next);
        instance=new OverviewGraph(next,graph);
        window.__overviewKnowledgeGraph=instance;   /* 调试/测试句柄（内核不再读它） */
        return instance;
      },
    },
  });

  function focusWhenReady(){
    if(route()!=='graph')return;
    const id=sessionStorage.getItem('erw:pending-graph-focus');if(!id)return;
    let tries=0;const timer=setInterval(()=>{
      tries++;
      const engine=window.__knowledgeGraphEngine;
      if(engine?.nodeMap?.has?.(id)){clearInterval(timer);sessionStorage.removeItem('erw:pending-graph-focus');engine.selectNode(id,true)}
      else if(tries>50){clearInterval(timer)}
    },60);
  }

  /* 实例生命周期归插件自己：离开总览路由时释放迷你图；顺带处理「从迷你图跳到图谱页并定位节点」的待办。 */
  window.addEventListener('hashchange',()=>{
    if(route()!==ROUTE){ instance?.destroy(); instance=null; focusWhenReady(); }
  });
})();
