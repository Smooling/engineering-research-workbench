(() => {
  'use strict';

  const VERSION = '260922.1';
  const MAX_FETCH_NODES = 500;
  const SEARCH_LIMIT = 10;
  const LAYOUT_CACHE_VERSION = 2;
  const DOC_KINDS = new Set(['idea','journal','note','milestone','summary','literature']);
  const KIND_LABEL = {idea:'灵感',journal:'研究日志',note:'笔记',milestone:'里程碑',summary:'工作总结',literature:'文献',project:'项目',tag:'标签'};
  const KIND_COLOR = {idea:'#2a9d8f',journal:'#5b8def',note:'#6f7a8a',milestone:'#c6863b',summary:'#845ec2',literature:'#2673a7',tag:'#b56a9d',project:'#087f8c'};
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
      this.focusDepth = 1;
      this.focusDistances = new Map();
      this.mode = document.querySelector('[data-gview].active')?.dataset.gview || '2d';
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

    async init() {
      window.__workbenchPerf && (window.__workbenchPerf.graphLimit = Math.max(window.__workbenchPerf.graphLimit || 0, MAX_FETCH_NODES));
      this.installToolbar();
      this.bindExistingControls();
      this.setStatus('正在建立图结构索引…');
      const graph = await api(`/api/graph?limit=${MAX_FETCH_NODES}`);
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
      document.querySelectorAll('[data-gview]').forEach(btn=>{btn.onclick=(e)=>{e.preventDefault();e.stopPropagation();this.mode=btn.dataset.gview||'2d';document.querySelectorAll('[data-gview]').forEach(x=>x.classList.toggle('active',x===btn));this.requestRender()}});
      const fit=document.querySelector('#graph-fit'); if(fit)fit.onclick=(e)=>{e.preventDefault();this.clearFocus(true)};
      const close=document.querySelector('#graph-preview-close'); if(close)close.onclick=()=>this.clearFocus(false);
      const bundle=document.querySelector('#graph-bundle'); if(bundle)bundle.onclick=()=>this.openBundle();

      document.querySelectorAll('[data-graph-kind],[data-graph-relation]').forEach(input=>{input.onchange=(e)=>{e.stopPropagation();this.persistFilters();this.refreshFilteredGraph(true)}});
      const all=document.querySelector('#graph-filter-all'); if(all)all.onclick=(e)=>{e.preventDefault();e.stopPropagation();document.querySelectorAll('[data-graph-kind]').forEach(x=>x.checked=true);this.persistFilters();this.refreshFilteredGraph(true)};
      const docs=document.querySelector('#graph-filter-docs'); if(docs)docs.onclick=(e)=>{e.preventDefault();e.stopPropagation();this.setScope(true)};
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
      const node=this.nodeMap.get(String(id));if(!node)return;this.selectedId=String(id);this.focusDepth=this.focusDepth||1;this.updateFocus();this.syncFocusButtons();this.updateSidePanel(node);this.openPreview(node);const bundle=document.querySelector('#graph-bundle');if(bundle)bundle.disabled=false;if(animate)this.animateCameraTo(id);else this.requestRender();
    }
    clearFocus(resetCamera=false){
      this.selectedId=null;this.focusDistances.clear();this.searchHits.clear();this.syncFocusButtons();const title=document.querySelector('#graph-node-title'),info=document.querySelector('#graph-node-info'),bundle=document.querySelector('#graph-bundle');if(title)title.textContent='选择节点';if(info)info.textContent='搜索或点击节点后，将进入 Focus + Context；点击空白处可恢复全图。';if(bundle)bundle.disabled=true;this.hidePreview();if(resetCamera){const c=this.camera[this.mode];c.panX=0;c.panY=0;c.zoom=1;if(this.mode==='3d'){c.rotX=.25;c.rotY=0}}this.requestRender();
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
      let html='';if(window.marked){const renderer=new marked.Renderer();renderer.code=(tokenOrCode,info)=>{let code='',lang='';if(tokenOrCode&&typeof tokenOrCode==='object'){code=tokenOrCode.text||'';lang=tokenOrCode.lang||''}else{code=String(tokenOrCode||'');lang=String(info||'')}if(String(lang).trim()==='mermaid')return `<div class="mermaid">${esc(code)}</div>`;return `<pre><code class="language-${esc(String(lang).trim())}">${esc(code)}</code></pre>`};try{html=marked.parse(raw||'',{gfm:true,renderer})}catch{html=`<pre>${esc(raw)}</pre>`}}else html=`<pre>${esc(raw)}</pre>`;
      html=html.replace(/(src|href)="(?:\.\.\/)+(?:Knowledge\/)?Attachments\//g,'$1="/workspace-file/Knowledge/Attachments/').replace(/(src|href)="Attachments\//g,'$1="/workspace-file/Knowledge/Attachments/').replace(/src="(?!https?:|data:|\/|#)([^"]+)"/g,(m,p)=>'src="/workspace-file/'+p.replace(/^\.?\//,"")+'"'); /* v260929w · Workspace 相对路径图片（批注截图 / 笔记插图）：img src 经 /workspace-file/ 服务 */
      out.innerHTML=window.DOMPurify?DOMPurify.sanitize(html,{ADD_TAGS:['mjx-container']}):html;out.querySelectorAll('pre code').forEach(el=>{try{window.hljs?.highlightElement(el)}catch{}});try{if(window.mermaid){mermaid.initialize({startOnLoad:false,securityLevel:'strict'});await mermaid.run({nodes:[...out.querySelectorAll('.mermaid')]})}}catch{};try{await window.MathJax?.typesetPromise?.([out])}catch{}
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

  let instance=null, enhancing=false;
  function replaceCanvas(oldCanvas){const clone=oldCanvas.cloneNode(false);clone.width=oldCanvas.width;clone.height=oldCanvas.height;oldCanvas.replaceWith(clone);return clone}
  async function enhance(){
    if(enhancing||route()!=='graph')return;const old=document.querySelector('#graph-canvas');if(!old||old.dataset.optimizedGraph==='1')return;enhancing=true;try{instance?.destroy();const canvas=replaceCanvas(old);canvas.dataset.optimizedGraph='1';instance=new OptimizedKnowledgeGraph(canvas);window.__knowledgeGraphEngine=instance;await instance.init()}catch(err){console.error('[graph-engine]',err);document.querySelector('#graph-engine-status')?.replaceChildren(document.createTextNode('图谱优化引擎加载失败：'+err.message))}finally{enhancing=false}}
  function maybeEnhance(){if(route()!=='graph'){instance?.destroy();instance=null;return}requestAnimationFrame(enhance)}

  const observer=new MutationObserver(()=>maybeEnhance());
  window.addEventListener('DOMContentLoaded',()=>{observer.observe(document.querySelector('#main')||document.body,{childList:true,subtree:true});maybeEnhance()});
  window.addEventListener('hashchange',()=>setTimeout(maybeEnhance,0));
  window.__knowledgeGraphEngineVersion=VERSION;
})();
