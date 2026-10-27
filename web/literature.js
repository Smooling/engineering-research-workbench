(()=>{
"use strict";
const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>Array.from(r.querySelectorAll(s));
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clamp=v=>Math.max(0,Math.min(1,v));
const PDF_RENDER_RADIUS=4; /* v261009p · 仅保留当前页前后少量已渲染 canvas，防长 PDF 内存随滚动线性增长 */
const PDF_PAGE_PIXEL_LIMIT=12*1024*1024, PDF_CACHE_PIXEL_LIMIT=40*1024*1024, PDF_CANVAS_SIDE_LIMIT=8192;
const S={items:[],paper:null,pdf:null,scale:1.15,zoomMode:"fit",focus:false,libraryHidden:false,sideHidden:true,layoutObserver:null,layoutTimer:null,openSeq:0,current:1,pages:new Map(),observer:null,pending:null,undo:[],area:false,generation:0,selectedAnn:null,selectionOrigin:null,dragSel:null,annotations:[],annByPage:new Map(),trimTimer:null,ai:{text:"",image:"",result:"",error:"",busy:false,instruction:""}};
let wheelFrame=0,wheelTimer=null,wheelTarget=null,wheelBase=1,wheelAnchor=null,zoomSerial=0;
Object.assign(S,{listPage:1,listSeq:0,noteState:null,infoDraft:null,infoBase:null,sideTab:"info",noteMode:"edit",bindPaper:null});
const annotationDrafts=new Map();
function captureAnnotation(){
 const ta=q('#ann-comment');if(!ta)return;
 const key=ta.dataset.paperId+'/'+ta.dataset.annId;
 let draft=annotationDrafts.get(key);
 if(!draft){const a=annotationById(ta.dataset.annId);if(!a)return;draft={paperId:ta.dataset.paperId,id:a.id,page:a.page,base:String(a.comment||''),text:String(a.comment||'')};annotationDrafts.set(key,draft)}
 draft.text=ta.value;
}
function dirtyAnnotations(){return [...annotationDrafts.values()].filter(d=>d.text!==d.base)}
function toast(message,error=false){if(window.ERWToast)return window.ERWToast(message,error);const stack=q("#toast-stack");if(!stack)return;const item=document.createElement("div");item.className="toast"+(error?" error":"");item.textContent=message;stack.append(item);setTimeout(()=>item.remove(),3500)}
function captureNote(){const ta=q("#lit-note");if(ta&&S.noteState?.id===S.paper?.id)S.noteState.text=ta.value}
function infoPayload(){
 if(!q("#li-title"))return S.infoDraft;
 const value=id=>q("#"+id)?.value||"";
 return {title:value("li-title"),authors:value("li-authors"),year:value("li-year"),reading_status:value("li-status"),tags:liTags(),projects:liProjects(),venue:value("li-venue"),doi:value("li-doi"),url:value("li-url"),cite_key:value("li-cite"),added_date:value("li-added"),bibtex:value("li-bibtex"),favorite:!!q("#li-favorite")?.checked,kind_marks:qa("#li-marks .mark-chip.on").map(b=>b.dataset.mark)};
}
function captureInfo(){if(q("#li-title"))S.infoDraft=infoPayload()}
function dirty(){if(!q(".lit-shell"))return false;captureNote();captureInfo();captureAnnotation();return !!(S.noteState&&S.noteState.text!==S.noteState.base||S.infoBase&&JSON.stringify(S.infoDraft)!==S.infoBase||dirtyAnnotations().length)}
async function guard(){
 if(S.noteState?.saving&&!await S.noteState.saving)return false;if(S.infoSaving&&!await S.infoSaving)return false;
 for(const draft of annotationDrafts.values())if(draft.saving&&!await draft.saving)return false;
 if(!dirty())return true;if(S.guardPending)return S.guardPending;
 S.guardPending=(async()=>{const answer=await window.ERWDialog.choose("文献信息、阅读笔记或批注有未保存的修改，是否保存后继续？",{title:"保存文献修改？",buttons:[{value:"cancel",label:"继续编辑"},{value:"discard",label:"不保存"},{value:"save",label:"保存并继续",primary:true}]});if(answer==="cancel")return false;if(answer==="save"){if(S.infoBase&&JSON.stringify(S.infoDraft)!==S.infoBase&&!await saveInfo())return false;if(S.noteState&&S.noteState.text!==S.noteState.base&&!await saveNote())return false;for(const draft of dirtyAnnotations())if(!await saveAnnotationDraft(draft))return false;return !dirty()}if(S.noteState){S.noteState.text=S.noteState.base;const ta=q("#lit-note");if(ta)ta.value=S.noteState.base}if(S.infoBase){S.infoDraft=JSON.parse(S.infoBase);if(q("#li-title"))sideTab("info")}for(const draft of annotationDrafts.values())draft.text=draft.base;const ta=q('#ann-comment');if(ta)ta.value=annotationDrafts.get(ta.dataset.paperId+'/'+ta.dataset.annId)?.base||'';return true})();
 try{return await S.guardPending}finally{S.guardPending=null}
}
async function loadNote(){
 const id=S.paper?.id;if(!id)throw Error("请先选择文献");if(S.noteState?.id===id&&S.noteState.loaded)return S.noteState;
 const state=S.noteState?.id===id?S.noteState:{id,text:"",base:"",loaded:false,revision:null};S.noteState=state;
 if(!state.loading)state.loading=api("/api/literature/"+encodeURIComponent(id)+"/note").then(data=>{state.text=state.base=String(data.content||"");state.revision=data.revision??null;state.loaded=true;return state}).finally(()=>state.loading=null);
 return state.loading;
}
function noteStatus(message){const status=q("#lit-note-status");if(status)status.textContent=message;window.dispatchEvent(new Event("workbench:editor-state"))}

async function api(url,opts={}){
 const r=await fetch(url,opts);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.message||d.error||("HTTP "+r.status));
 if(opts.method&&opts.method!=='GET'&&/^\/api\/literature\/[^/]+(?:\/note)?$/.test(url)&&!['/api/literature/lookup','/api/literature/export-bibtex'].includes(url))window.ERWDocReferences?.invalidate();
 return d;
}
let pdfJsLoading=null;
async function ensurePdfJs(){
 if(window.pdfjsLib)return;
 if(!pdfJsLoading)pdfJsLoading=new Promise((ok,bad)=>{const s=document.createElement("script");s.src="/vendor/pdf.min.js?v=3.11.174";s.onload=ok;s.onerror=()=>{pdfJsLoading=null;bad(Error("PDF 渲染组件加载失败，请更新客户端后重试"))};document.head.appendChild(s)});
 await pdfJsLoading;
 if(!window.pdfjsLib)throw new Error("PDF.js 加载失败");
 window.pdfjsLib.GlobalWorkerOptions.workerSrc="/vendor/pdf.worker.min.js?v=3.11.174";
}
/* v260929 · 阅读区列表条目统一为文献列表页风格（.doc-item 同构）：标题→摘要→徽章行→项目+日期
   徽章行 = 阅读状态 + 收藏 + 分类标记；附件徽章去掉（点击条目本身即打开 PDF，徽章冗余）
   分类统一走「分类标记」（kind_marks），原 categories 徽章已移除（与标记重复） */
function item(x){
 const meta=[x.year,(x.authors||"").split(/[;；]/)[0],x.pdf_available===false?"待补充 PDF":x.reading_status||"未读"].filter(Boolean).join(" · ");
 return '<article class="doc-item lit-item'+(S.paper?.id===x.id?' active':'')+'" data-paper="'+esc(x.id)+'" '+(x.doc_id?'data-hover-doc-id="'+esc(x.doc_id)+'" ':'')+'tabindex="0" role="button" aria-label="打开 '+esc(x.title)+'"><div class="lit-item-heading"><span class="lit-pdf-icon '+(x.pdf_available===false?'missing':'')+'">'+(x.pdf_available===false?'＋':'PDF')+'</span><div class="title" title="'+esc(x.title)+'">'+esc(x.title)+'</div>'+(x.favorite?'<span class="lit-item-star">★</span>':'')+'</div><div class="lit-item-meta" title="'+esc(meta)+'">'+esc(meta)+'</div></article>';
}
async function loadList(){
 const list=q("#lit-list");if(!list)return;const seq=++S.listSeq;
 const url='/api/literature?q='+encodeURIComponent(q('#lit-search')?.value||'')+'&status='+encodeURIComponent(q('#lit-status')?.value||'')+'&mark='+encodeURIComponent(q('#lit-mark')?.value||'')+'&pdf='+encodeURIComponent(q('#lit-pdf-filter')?.value||'')+'&page_size=60&page='+S.listPage;
 try{const d=await api(url);if(seq!==S.listSeq||!list.isConnected)return;S.items=d.items||[];S.listTotal=+d.total||0;S.listPage=+d.page||1;
 list.innerHTML=S.items.length?S.items.map(item).join(''):'<div class="lit-empty">没有匹配的文献<br>上传 PDF 或调整筛选条件</div>';
 const c=q('#lit-mark'),old=c.value;c.innerHTML='<option value="">全部分类</option>'+(window.ERWMarkList?window.ERWMarkList():[]).map(k=>'<option value="'+esc(k.id)+'"'+(k.id===old?' selected':'')+'>'+esc(k.icon)+' '+esc(k.label)+'</option>').join('');
 qa('[data-paper]',list).forEach(e=>{e.onclick=()=>openPaper(e.dataset.paper).catch(error=>toast(error.message,true));e.onkeydown=event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();e.click()}}});
 const pager=q('#lit-pager');if(pager){const pages=Math.max(1,Math.ceil(S.listTotal/(+d.page_size||60)));pager.innerHTML='<button type="button" '+(S.listPage<=1?'disabled':'')+' data-lit-page="-1" aria-label="上一页">‹</button><span>'+S.listPage+' / '+pages+' · '+S.listTotal+' 篇</span><button type="button" '+(S.listPage>=pages?'disabled':'')+' data-lit-page="1" aria-label="下一页">›</button>';qa('[data-lit-page]',pager).forEach(b=>b.onclick=()=>{S.listPage+=+b.dataset.litPage;loadList()})}
 }catch(error){if(seq===S.listSeq&&list.isConnected){list.innerHTML='<div class="lit-empty">文献加载失败：'+esc(error.message)+'<br><button id="lit-list-retry" type="button">重试</button></div>';q('#lit-list-retry').onclick=loadList}}
}

function shell(){
 S.openSeq++;reset();S.paper=null;clearTimeout(S.layoutTimer);
 q("#main").innerHTML='<div class="lit-shell side-hidden"><div class="lit-layout-toolbar"><button type="button" id="lit-toggle-library" aria-expanded="true">文献列表</button><button type="button" id="lit-focus" aria-pressed="false" disabled>专注阅读</button><button type="button" id="lit-fit" disabled>适应宽度</button><button type="button" id="lit-toggle-side" aria-expanded="false" disabled>资料与笔记</button></div><aside class="card doc-list-panel lit-library"><div class="lit-library-head"><div><div class="card-kicker">LITERATURE LIBRARY</div><h3>文献库</h3></div><div class="lit-head-actions"><button class="ghost-btn" id="lit-export">导出引用</button><button class="primary-btn" id="lit-upload">＋ 上传 PDF</button></div></div><input id="lit-file" type="file" accept="application/pdf,.pdf" hidden><div id="lit-export-status" class="row-meta" role="status" hidden></div><div class="doc-filter"><input class="search-input" id="lit-search" placeholder="搜索题名、作者、标签、分类…"><div class="lit-filters"><select class="search-input" id="lit-status"><option value="">全部进度</option><option>未读</option><option>在读</option><option>已读</option></select><select class="search-input" id="lit-mark"><option value="">全部分类</option></select></div></div><select class="search-input" id="lit-pdf-filter" aria-label="PDF 状态筛选"><option value="">全部文献</option><option value="available">已有 PDF</option><option value="missing">待补充 PDF</option></select><div class="doc-list lit-list" id="lit-list"></div><div id="lit-pager" class="lit-pager"></div></aside><section class="card lit-reader"><div id="lit-reader-empty" class="lit-empty lit-reader-empty">选择一篇文献开始阅读</div><div id="lit-reader-live" hidden><div class="lit-toolbar"><button data-ann="highlight" disabled>高亮</button><button data-ann="underline" disabled>下划线</button><button data-ann="strikeout" disabled>删除线</button><button id="lit-copy" disabled title="Ctrl+C">复制</button><span class="lit-sep"></span><button data-ai="translate" disabled title="将选中文本交给 AI 翻译为中文">AI 翻译</button><button data-ai="summarize" disabled title="将选中文本交给 AI 总结要点">AI 总结</button><button data-ai="organize" disabled title="将选中文本交给 AI 整理为知识笔记">AI 整理</button><span class="lit-sep"></span><button id="lit-area">框选区域</button><span class="lit-sep"></span><button id="lit-undo" disabled title="Ctrl+Z">↶ 撤销</button><span class="lit-sep"></span><span id="lit-page-label">1 / 1</span><button id="lit-zoom-out">−</button><span id="lit-zoom-label">115%</span><button id="lit-zoom-in">＋</button></div><div class="lit-canvas-scroll" id="lit-scroll"><div id="lit-pages" class="lit-pages"></div></div></div></section><aside class="card lit-side" id="lit-side"><div class="lit-empty">文献信息、批注和笔记将在这里显示</div></aside></div>';
 S.layoutObserver?.disconnect();S.libraryHidden=false;S.sideHidden=true;S.focus=false;installSplitters();
 q("#lit-toggle-library").onclick=()=>{S.libraryHidden=!S.libraryHidden;S.focus=false;layout()};
 q("#lit-toggle-side").onclick=()=>{S.sideHidden=!S.sideHidden;S.focus=false;layout()};
 q("#lit-focus").onclick=()=>{S.focus=!S.focus;S.libraryHidden=S.focus;S.sideHidden=true;layout()};
 q("#lit-fit").onclick=()=>{stopWheelZoom();S.zoomMode="fit";refit()};
 q("#lit-scroll").addEventListener("wheel",pdfWheelZoom,{passive:false});
 S.layoutObserver=new ResizeObserver(schedulePdfLayout);S.layoutObserver.observe(q(".lit-reader"));
 q("#lit-upload").onclick=()=>{S.bindPaper=null;q("#lit-file").click()};q("#lit-file").onchange=e=>upload(e.target.files?.[0]);
 q("#lit-export").onclick=exportReferences; /* v260929 · 返回文献列表：经事件通知 app.js 重新渲染列表页（hash 未变不触发路由） */
 let t;const filter=()=>{S.listPage=1;loadList()};q("#lit-search").oninput=()=>{clearTimeout(t);t=setTimeout(filter,160)};q("#lit-status").onchange=filter;q("#lit-mark").onchange=filter;q("#lit-pdf-filter").onchange=filter;
 qa("[data-ann]").forEach(b=>b.onclick=()=>commit(b.dataset.ann));qa("[data-ai]").forEach(b=>b.onclick=()=>aiFromSelection(b.dataset.ai));q("#lit-copy").onclick=copyPendingText;q("#lit-area").onclick=toggleArea;q("#lit-undo").onclick=undo;q("#lit-zoom-in").onclick=()=>zoom(.15);q("#lit-zoom-out").onclick=()=>zoom(-.15);
}
async function upload(file){if(!file)return;if(!await guard())return;const binding=S.bindPaper;S.bindPaper=null;try{const r=await fetch("/api/literature/import",{method:"POST",headers:{"Content-Type":"application/pdf","X-Filename":encodeURIComponent(file.name),...(binding?{"X-Bind-Paper":encodeURIComponent(binding)}:{})},body:file});const d=await r.json();if(!r.ok)throw new Error(d.message||"上传失败");await loadList();await openPaper(d.id)}catch(e){window.ERWDialog.alert(e.message)}finally{q("#lit-file").value=""}}

async function openPaper(id){
 if(!await guard())return false;
 annotationDrafts.clear();
 const origin=window.ERWNavigation?.capture();
 const openSeq=++S.openSeq;reset();S.noteState=null;S.infoDraft=null;S.infoBase=null;
 const enc=encodeURIComponent(id);
 const [paper,annotations]=await Promise.all([
  api("/api/literature/"+enc),
  api("/api/literature/"+enc+"/annotations")
 ]);
 if(openSeq!==S.openSeq||!q(".lit-shell"))return;
 S.paper=paper;window.ERWCurrentDoc=paper.doc_id||paper.id;localStorage.setItem("erwLitRecentPaper",paper.id);window.ERWResearchUI?.remember("pdf",{id:paper.id,title:paper.title});S.annotations=Array.isArray(annotations)?annotations:[];rebuildAnnotationIndex();
 q("#lit-toggle-side").disabled=false;
 if(paper.pdf_available===false){q("#lit-reader-empty").hidden=false;q("#lit-reader-live").hidden=true;q("#lit-reader-empty").innerHTML='<div><strong>这篇文献尚未附上 PDF</strong><p>信息与历史笔记已保留，上传 PDF 后即可在这里阅读。</p><button type="button" class="primary-btn" id="lit-bind-pdf">＋ 为此文献添加 PDF</button></div>';q("#lit-bind-pdf").onclick=()=>{S.bindPaper=paper.id;q("#lit-file").click()};side();showSide();await loadList();if(origin)window.ERWNavigation?.commit(origin);return true}
 q("#lit-reader-empty").hidden=true;q("#lit-reader-live").hidden=false;side();loadList().catch(()=>{}) /* v260929 · 列表刷新仅更新徽章，不阻塞 PDF 加载 */;
 try{
  await ensurePdfJs();const pdf=await window.pdfjsLib.getDocument({url:"/api/literature/"+enc+"/pdf",rangeChunkSize:4*1024*1024,isEvalSupported:false,enableXfa:false}).promise;
  if(openSeq!==S.openSeq||!q(".lit-shell")){pdf.destroy?.();return}
  S.pdf=pdf;S.zoomMode="fit";layout();
  const target=Math.max(1,Math.min(pdf.numPages,+S.paper.last_page||1));S.current=target;
  await build();requestAnimationFrame(()=>{if(openSeq===S.openSeq&&q(".lit-shell"))go(target,false)});
 }
 catch(e){const host=q("#lit-pages");if(host&&openSeq===S.openSeq)host.innerHTML='<div class="lit-empty">PDF 渲染失败：'+esc(e.message)+"</div>"}
 if(openSeq===S.openSeq&&origin)window.ERWNavigation?.commit(origin);
}
function releasePageCanvas(r){
 if(!r?.el)return;
 r.renderTask?.cancel?.();
 const cv=q("canvas",r.el);
 if(cv){cv.width=1;cv.height=1} /* 先主动释放 backing store，再移除 DOM，避免 GC 延迟占住几十 MB */
}
function reset(){
 stopWheelZoom();
 S.generation++;S.aiRequest=(S.aiRequest||0)+1;S.buildKey=(S.buildKey||0)+1;S.observer?.disconnect();clearTimeout(S.trimTimer);clearTimeout(track.t);q("#lit-pages")?.replaceChildren();
 const scroll=q("#lit-scroll");if(scroll)scroll.onscroll=null;
 S.pages.forEach(r=>releasePageCanvas(r));S.pages.clear();S.pdf?.destroy?.();
 S.pending=null;S.undo=[];S.area=false;S.pdf=null;S.selectedAnn=null;S.selectionOrigin=null;S.dragSel=null;S.areaResolver=null;
 S.annotations=[];S.annByPage.clear();S.ai={text:"",image:"",result:"",error:"",busy:false,instruction:""}
} /* v261009p · 切文献时主动释放 PDF canvas / 文本几何 */
function rebuildAnnotationIndex(){
 S.annByPage.clear();
 for(const a of S.annotations||[]){const p=+a.page||1;if(!S.annByPage.has(p))S.annByPage.set(p,[]);S.annByPage.get(p).push(a)}
}
function annotationsForPage(page){return S.annByPage.get(+page)||[]}
function annotationById(id){return (S.annotations||[]).find(a=>a.id===id)||null}
function upsertAnnotation(a){
 const i=S.annotations.findIndex(x=>x.id===a.id);
 if(i>=0)S.annotations[i]=a;else S.annotations.push(a);
 rebuildAnnotationIndex(); /* 批注通常很少；写入时一次重建，换取渲染页 O(1) 读取 */
 const r=S.pages.get(+a.page);if(r)r.annotations=annotationsForPage(a.page);
}
function removeAnnotationLocal(id,page){
 annotationDrafts.delete(S.paper?.id+'/'+id);
 S.annotations=S.annotations.filter(a=>a.id!==id);rebuildAnnotationIndex();
 const r=S.pages.get(+page);if(r)r.annotations=annotationsForPage(page);
}
function unloadPage(n){
 const r=S.pages.get(+n);if(!r||r.rendering||!q("canvas",r.el))return false;
 if(S.pending?.page===+n||S.selectedAnn?.page===+n)return; /* 正在编辑/选择的页不回收 */
 if(pageIsVisible(r))return;
 const old=q("canvas",r.el);r.renderTask?.cancel?.();
 r.el.innerHTML='<div class="lit-page-placeholder">第 '+n+" 页</div>";
 if(old){old.width=1;old.height=1}
 r.rendered=false;r.textItems=null;r.annotations=annotationsForPage(n);
 return true;
}
function trimRenderedPages(center=S.current){
 if(!S.pdf)return;
 const lo=Math.max(1,+center-PDF_RENDER_RADIUS),hi=Math.min(S.pdf.numPages,+center+PDF_RENDER_RADIUS);
 S.pages.forEach((r,n)=>{if(n<lo||n>hi)unloadPage(n)});
 const cached=[...S.pages.entries()].map(([n,r])=>{const cv=q("canvas",r.el);return {n,r,pixels:cv?cv.width*cv.height:0}}).filter(item=>item.pixels>1);
 let pixels=cached.reduce((total,item)=>total+item.pixels,0);
 for(const item of cached.sort((a,b)=>Math.abs(b.n-center)-Math.abs(a.n-center))){
  if(pixels<=PDF_CACHE_PIXEL_LIMIT)break;
  if(item.n===+center)continue;
  if(unloadPage(item.n))pixels-=item.pixels;
 }
}
function pageIsVisible(r){const sc=q("#lit-scroll");if(!sc||!r.el.isConnected)return false;const view=sc.getBoundingClientRect(),page=r.el.getBoundingClientRect();return page.bottom>view.top&&page.top<view.bottom}
/* Render vector text above screen resolution, including CSS/app zoom. Bound each
   backing store instead of capping native DPR, so high-DPI screens stay sharp. */
function pdfPixelSize(width,height,element){
 const cssZoom=element.getBoundingClientRect().width/(parseFloat(element.style.width)||width)||1;
 const density=Math.max(2,window.devicePixelRatio||1)*cssZoom;
 const scale=Math.min(density,Math.sqrt(PDF_PAGE_PIXEL_LIMIT/(width*height)),PDF_CANVAS_SIDE_LIMIT/width,PDF_CANVAS_SIDE_LIMIT/height);
 return {width:Math.max(1,Math.floor(width*scale)),height:Math.max(1,Math.floor(height*scale))};
}
function refreshPdfResolution(){
 if(!S.pdf||S.zooming)return;
 S.pages.forEach((r,n)=>{
  if(!r.rendered||r.rendering)return;
  const cv=q("canvas",r.el);if(!cv)return;
  const size=pdfPixelSize(parseFloat(cv.style.width),parseFloat(cv.style.height),r.el);
  if(size.width===cv.width&&size.height===cv.height)return;
  r.rendered=false;renderPage(n);
 });
}
function schedulePdfLayout(){
 clearTimeout(S.layoutTimer);
 if(!S.pdf||!q(".lit-shell"))return;
 S.layoutTimer=setTimeout(()=>{
  if(!S.pdf||!q(".lit-shell")||S.zooming)return;
  if(S.zoomMode==="fit")refit().catch(error=>toast("PDF 显示更新失败："+error.message,true));else refreshPdfResolution();
 },120);
}
function scheduleTrim(center=S.current){
 clearTimeout(S.trimTimer);
 S.trimTimer=setTimeout(()=>trimRenderedPages(center),120);
}
function availablePdfWidth(){const scroll=q("#lit-scroll");if(!scroll)return 320;const style=getComputedStyle(scroll);return Math.max(1,scroll.clientWidth-parseFloat(style.paddingLeft||0)-parseFloat(style.paddingRight||0))}
async function build(){
 const host=q("#lit-pages"),pdf=S.pdf;if(!host||!pdf)return;
 const gen=S.generation,buildKey=S.buildKey=(S.buildKey||0)+1;
 S.observer?.disconnect();
 const first=await pdf.getPage(1);if(gen!==S.generation||pdf!==S.pdf||buildKey!==S.buildKey||!host.isConnected)return;
 if(S.zoomMode==="fit")S.scale=Math.max(.2,Math.min(2.4,availablePdfWidth()/first.getViewport({scale:1}).width));
 const baseVp=first.getViewport({scale:S.scale});host.style.minWidth=baseVp.width+"px";
 const previous=S.pages,next=new Map(),frag=document.createDocumentFragment();
 for(let n=1;n<=pdf.numPages;n++){
  let r=previous.get(n);
  if(!r){const el=document.createElement("div");el.className="lit-page-shell";el.dataset.page=n;el.innerHTML='<div class="lit-page-placeholder">第 '+n+' 页</div>';r={el,annotations:annotationsForPage(n)}}
  r.renderKey=(r.renderKey||0)+1;r.renderTask?.cancel?.();r.renderTask=null;r.rendered=false;r.rendering=false;r.renderPromise=null;
  r.el.style.width=baseVp.width+"px";r.el.style.height=baseVp.height+"px";
  const old=q(".lit-page",r.el);if(old){old.style.width=baseVp.width+"px";old.style.height=baseVp.height+"px";const canvas=q("canvas",old);if(canvas){canvas.style.width=baseVp.width+"px";canvas.style.height=baseVp.height+"px"}}
  next.set(n,r);frag.append(r.el);
 }
 S.pages=next;host.replaceChildren(frag);
 S.observer=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)renderPage(+e.target.dataset.page)}),{root:q("#lit-scroll"),rootMargin:"700px 0px",threshold:.01});
 S.pages.forEach(r=>S.observer.observe(r.el));q("#lit-scroll").onscroll=throttle(track,80);toolbar();renderPage(S.current);
}
function renderPage(n){
 const r=S.pages.get(n);if(!r||r.rendered||!S.pdf||wheelTarget!=null)return Promise.resolve();if(r.rendering)return r.renderPromise;
 const gen=S.generation,pdf=S.pdf,scale=S.scale,renderKey=r.renderKey=(r.renderKey||0)+1;r.rendering=true;
 const valid=()=>gen===S.generation&&pdf===S.pdf&&r===S.pages.get(n)&&r.renderKey===renderKey&&r.el.isConnected;
 r.renderPromise=(async()=>{
  let cv=null;
  try{
   const p=await pdf.getPage(n),vp=p.getViewport({scale});if(!valid())return;
   /* Paint off-screen. An opaque canvas starts black in WebView2; never expose
      it until PDF.js has finished, and retain the previous frame during zoom. */
   cv=document.createElement("canvas");const size=pdfPixelSize(vp.width,vp.height,r.el);cv.width=size.width;cv.height=size.height;cv.style.width=vp.width+"px";cv.style.height=vp.height+"px";cv.style.background="#fff";
   const ctx=cv.getContext("2d",{alpha:false});ctx.fillStyle="#fff";ctx.fillRect(0,0,cv.width,cv.height);ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality="high";
   r.renderTask=p.render({canvasContext:ctx,viewport:vp,background:"#ffffff",transform:[cv.width/vp.width,0,0,cv.height/vp.height,0,0]});
   await r.renderTask.promise;if(!valid())return;
   const text=await p.getTextContent();if(!valid())return;
   const old=q("canvas",r.el),pageEl=document.createElement("div");pageEl.className="lit-page";pageEl.dataset.page=n;pageEl.style.width=vp.width+"px";pageEl.style.height=vp.height+"px";
   pageEl.innerHTML='<svg class="lit-annotation-layer" viewBox="0 0 1 1" preserveAspectRatio="none"></svg><div class="lit-selection-layer"></div><div class="lit-interaction-layer" title="拖动选择文字"></div>';
   cv.dataset.ready="true";pageEl.prepend(cv);r.el.style.width=vp.width+"px";r.el.style.height=vp.height+"px";r.el.replaceChildren(pageEl);cv=null;
   if(old){old.width=1;old.height=1}
   r.textItems=buildPdfTextGeometry(text,vp);r.annotations=annotationsForPage(n);r.rendered=true;
   const hit=q(".lit-interaction-layer",pageEl);hit.onmousedown=e=>beginPdfGeometrySelection(n,e);hit.onclick=e=>handlePageAnnotationClick(n,e);
   paint(n);paintPending();scheduleTrim(S.current);try{p.cleanup()}catch{}
  }catch(e){if(valid()&&e.name!=="RenderingCancelledException"){if(!q("canvas",r.el))r.el.innerHTML='<div class="lit-page-error">第 '+n+' 页渲染失败：'+esc(e.message)+'</div>';toast("PDF 第 "+n+" 页绘制失败："+e.message,true)}}
  finally{if(cv){cv.width=1;cv.height=1}if(r.renderKey===renderKey){r.rendering=false;r.renderTask=null;if(valid()){trimRenderedPages();const front=q("canvas",r.el);if(r.rendered&&front){const size=pdfPixelSize(parseFloat(front.style.width),parseFloat(front.style.height),r.el);if(size.width!==front.width||size.height!==front.height)schedulePdfLayout()}}}}
 })();return r.renderPromise;
}

function buildPdfTextGeometry(text,viewport){
 const out=[];
 for(const it of text.items||[]){
  const str=String(it.str||"");if(!str.trim())continue;
  const tx=window.pdfjsLib.Util.transform(viewport.transform,it.transform);
  const h=Math.max(1,Math.hypot(tx[2],tx[3]));
  const w=Math.max(1,Math.abs((it.width||0)*viewport.scale));
  const x=tx[4],y=tx[5]-h;
  out.push({
   text:str,
   x1:clamp(x/viewport.width), y1:clamp(y/viewport.height),
   x2:clamp((x+w)/viewport.width), y2:clamp((y+h)/viewport.height),
   cx:clamp((x+w*.5)/viewport.width), cy:clamp((y+h*.5)/viewport.height),
   h:h/viewport.height
  });
 }
 return out;
}
function geometryHasTwoColumns(items){
 if(!items?.length)return false;
 let left=0,right=0,center=0;
 for(const it of items){
  if(it.x2-it.x1>.55){center++;continue}
  if(it.cx<.46)left++;else if(it.cx>.54)right++;else center++;
 }
 return left>10&&right>10&&center<Math.max(12,(left+right)*.22);
}
function geometryRows(items,side){
 let list=(items||[]).filter(it=>side==="left"?it.cx<.5:side==="right"?it.cx>.5:true)
   .slice().sort((a,b)=>a.cy-b.cy||a.x1-b.x1);
 const rows=[];
 for(const it of list){
  let row=rows[rows.length-1];
  if(!row||Math.abs(it.cy-row.cy)>Math.max(it.h,row.h)*.58){
   row={items:[],cy:it.cy,h:it.h};rows.push(row);
  }
  row.items.push(it);
  row.cy=row.items.reduce((s,v)=>s+v.cy,0)/row.items.length;
  row.h=Math.max(...row.items.map(v=>v.h));
 }
 rows.forEach(row=>row.items.sort((a,b)=>a.x1-b.x1));
 return rows;
}
function nearestGeometryRow(rows,y){
 let best=-1,d=Infinity;
 rows.forEach((r,i)=>{const z=Math.abs(r.cy-y);if(z<d){d=z;best=i}});
 return best;
}
function charOffsetForX(it,x){
 const len=Math.max(1,it.text.length);
 const t=clamp((x-it.x1)/Math.max(.00001,it.x2-it.x1));
 return Math.max(0,Math.min(len,Math.round(t*len)));
}
function buildSelectionFromPdfGeometry(n,start,end){
 const rec=S.pages.get(n);if(!rec?.textItems?.length)return null;
 const two=geometryHasTwoColumns(rec.textItems);
 const side=two?(start.x<.5?"left":"right"):null;
 const rows=geometryRows(rec.textItems,side);if(!rows.length)return null;
 let sr=nearestGeometryRow(rows,start.y),er=nearestGeometryRow(rows,end.y);
 if(sr<0||er<0)return null;
 const forward=sr<er||(sr===er&&end.x>=start.x);
 const first=forward?sr:er,last=forward?er:sr;
 const firstX=forward?start.x:end.x,lastX=forward?end.x:start.x;
 const rects=[],lines=[];
 for(let ri=first;ri<=last;ri++){
  const row=rows[ri],rowLeft=Math.min(...row.items.map(it=>it.x1)),rowRight=Math.max(...row.items.map(it=>it.x2));
  let minX=rowLeft,maxX=rowRight;
  if(first===last){minX=Math.min(start.x,end.x);maxX=Math.max(start.x,end.x);}
  else{if(ri===first)minX=firstX;if(ri===last)maxX=lastX;}
  if(maxX<minX){const t=minX;minX=maxX;maxX=t}
  const parts=[];
  for(const it of row.items){
   if(it.x2<=minX||it.x1>=maxX)continue;
   let from=0,to=it.text.length;
   if(minX>it.x1&&minX<it.x2)from=charOffsetForX(it,minX);
   if(maxX>it.x1&&maxX<it.x2)to=charOffsetForX(it,maxX);
   if(to<from){const t=from;from=to;to=t}
   if(to<=from)continue;
   const len=Math.max(1,it.text.length),w=it.x2-it.x1;
   const x1=it.x1+w*(from/len),x2=it.x1+w*(to/len);
   const hh=it.y2-it.y1;
   rects.push([x1,it.y1+hh*.10,x2,it.y2-hh*.08]);
   parts.push(it.text.slice(from,to));
  }
  if(parts.length)lines.push(parts.join("").trimEnd());
 }
 const merged=mergeGeometryRects(rects);
 if(!merged.length)return null;
 return {page:n,rects:merged,text:lines.join("\n").trim(),kind:"text"};
}
function mergeGeometryRects(rects){
 const list=rects.filter(r=>r[2]-r[0]>.0003&&r[3]-r[1]>.0003)
  .sort((a,b)=>(((a[1]+a[3])/2)-((b[1]+b[3])/2))||a[0]-b[0]);
 const out=[];
 for(const r of list){
  const last=out[out.length-1];
  if(last){
   const h=Math.max(r[3]-r[1],last[3]-last[1]);
   const same=Math.abs((r[1]+r[3]-last[1]-last[3])/2)<=h*.5;
   const gap=r[0]-last[2];
   if(same&&gap>=-.003&&gap<=.012){
    last[0]=Math.min(last[0],r[0]);last[1]=Math.min(last[1],r[1]);
    last[2]=Math.max(last[2],r[2]);last[3]=Math.max(last[3],r[3]);continue;
   }
  }
  out.push([...r]);
 }
 return out;
}
function eventPointInPage(page,e){
 const pr=page.getBoundingClientRect();
 return {x:clamp((e.clientX-pr.left)/pr.width),y:clamp((e.clientY-pr.top)/pr.height)};
}
function beginPdfGeometrySelection(n,e){
 if(S.area||e.button!==0)return;
 const rec=S.pages.get(n),page=q(".lit-page",rec.el);if(!page||!rec.textItems?.length)return;
 e.preventDefault();e.stopPropagation();
 if(S.pending){S.pending=null;paintPending();toolbar()}
 const start=eventPointInPage(page,e);
 S.dragSel={page:n,start,last:start,moved:false};
 const move=ev=>{
  if(!S.dragSel||S.dragSel.page!==n)return;
  const last=eventPointInPage(page,ev);S.dragSel.last=last;
  if(!S.dragSel.moved&&Math.hypot((last.x-start.x)*page.clientWidth,(last.y-start.y)*page.clientHeight)>3)S.dragSel.moved=true;
  if(!S.dragSel.moved)return;
  const next=buildSelectionFromPdfGeometry(n,start,last);
  if(next){S.pending=next;paintPending();toolbar();document.dispatchEvent(new CustomEvent("erw-lit-selection",{detail:{kind:"text",page:n,length:String(next.text||"").length}}))}
 };
 const up=ev=>{
  document.removeEventListener("mousemove",move,true);document.removeEventListener("mouseup",up,true);
  const drag=S.dragSel;S.dragSel=null;if(!drag?.moved)return;
  const last=eventPointInPage(page,ev),next=buildSelectionFromPdfGeometry(n,start,last);
  if(next)S.pending=next;paintPending();toolbar();
  document.dispatchEvent(new CustomEvent("erw-lit-selection",{detail:{kind:S.pending?.kind||"",page:n,length:String(S.pending?.text||"").length}}));
 };
 document.addEventListener("mousemove",move,true);
 document.addEventListener("mouseup",up,true);
}
function paintPending(){qa(".lit-selection-layer").forEach(x=>x.innerHTML="");if(!S.pending)return;const r=S.pages.get(S.pending.page);if(!r?.rendered)return;const l=q(".lit-selection-layer",r.el);S.pending.rects.forEach(a=>{const d=document.createElement("div");d.className="lit-pending-selection";d.style.left=a[0]*100+"%";d.style.top=a[1]*100+"%";d.style.width=(a[2]-a[0])*100+"%";d.style.height=(a[3]-a[1])*100+"%";l.appendChild(d)})}

function areaPreviewDataUrl(pending,maxW=640,maxH=420,quality=.82){ /* v260929c · 加参数：批注预览用默认档，AI 截图用高清档（1400/1200/.86） */
 if(!pending||pending.kind!=="area"||!pending.rects?.[0])return "";
 const rec=S.pages.get(pending.page),canvas=q("canvas",rec?.el);
 if(!canvas)return "";
 const [x1,y1,x2,y2]=pending.rects[0];
 const sx=Math.max(0,Math.floor(x1*canvas.width)),sy=Math.max(0,Math.floor(y1*canvas.height));
 const sw=Math.max(1,Math.floor((x2-x1)*canvas.width)),sh=Math.max(1,Math.floor((y2-y1)*canvas.height));
 const scale=Math.min(1,maxW/sw,maxH/sh);
 const out=document.createElement("canvas");
 out.width=Math.max(1,Math.round(sw*scale));out.height=Math.max(1,Math.round(sh*scale));
 const ctx=out.getContext("2d");
 ctx.drawImage(canvas,sx,sy,sw,sh,0,0,out.width,out.height);
 return out.toDataURL("image/webp",quality);
}
/* v260929c · 截取当前整页给 AI（多模态）：降采样到 ≤1400px 宽的 WebP，代替选中文本提高公式/表格提取正确率 */
function pageDataUrl(maxW=1400,quality=.86){
 const rec=S.pages.get(S.current),canvas=q("canvas",rec?.el);
 if(!canvas)return "";
 const sc=Math.min(1,maxW/canvas.width);
 const out=document.createElement("canvas");
 out.width=Math.max(1,Math.round(canvas.width*sc));out.height=Math.max(1,Math.round(canvas.height*sc));
 out.getContext("2d").drawImage(canvas,0,0,out.width,out.height);
 return out.toDataURL("image/webp",quality);
}
async function copyPendingText(){
 const text=String(S.pending?.text||"");
 if(!text||S.pending?.kind==="area")return;
 try{
  await navigator.clipboard.writeText(text);
 }catch{
  const ta=document.createElement("textarea");ta.value=text;ta.style.position="fixed";ta.style.opacity="0";
  document.body.appendChild(ta);ta.select();document.execCommand("copy");ta.remove();
 }
 const b=q("#lit-copy");if(b){const old=b.textContent;b.textContent="已复制";b.classList.add("copied");setTimeout(()=>{if(b){b.textContent=old;b.classList.remove("copied")}},900)}
}
function previewUrl(a){
 return a?.preview_path?"/workspace-file/"+String(a.preview_path).split("/").map(encodeURIComponent).join("/"):"";
}
function annotationExcerpt(a,small=false){
 if(a?.selection_kind==="area"&&a?.preview_path){
  return '<div class="lit-ann-preview-wrap"><img class="lit-ann-preview'+(small?' small':'')+'" src="'+previewUrl(a)+'" alt="框选区域截图"></div>';
 }
 return '<blockquote>'+esc(a?.text||"区域标记")+'</blockquote>';
}
async function commit(action){
 if(!S.pending)return;
 const payload={
  page:S.pending.page,type:action,rects:S.pending.rects,text:S.pending.text||"",comment:"",
  selection_kind:S.pending.kind||"text"
 };
 if(S.pending.kind==="area")payload.preview_data_url=areaPreviewDataUrl(S.pending);
 const row=await api("/api/literature/"+S.paper.id+"/annotations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
 S.undo.push({id:row.id,page:S.pending.page});
 upsertAnnotation(row);
 S.pending=null;paintPending();paint(row.page);toolbar();annList();
 document.dispatchEvent(new CustomEvent("erw-lit-selection",{detail:{kind:"",page:row.page,length:0}}));
}
function toggleArea(){
 S.area=!S.area;S.pending=null;paintPending();toolbar();
 document.dispatchEvent(new CustomEvent("erw-lit-selection",{detail:{kind:"",page:S.current||1,length:0}}));
 qa(".lit-interaction-layer").forEach(el=>{el.onmousedown=S.area?areaStart:null});
 if(!S.area&&S.areaResolver){const rs=S.areaResolver;S.areaResolver=null;rs("")} /* v260930n · 取消框选时释放悬浮球等待中的截图 promise，避免永久悬挂 */
}
function areaStart(e){
 const page=e.target.closest(".lit-page");if(!page||!S.area)return;e.preventDefault();const n=+page.dataset.page,pr=page.getBoundingClientRect(),a=[clamp((e.clientX-pr.left)/pr.width),clamp((e.clientY-pr.top)/pr.height)];
 const move=ev=>{const b=[clamp((ev.clientX-pr.left)/pr.width),clamp((ev.clientY-pr.top)/pr.height)];S.pending={page:n,text:"区域选块",kind:"area",rects:[[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])]]};paintPending();document.dispatchEvent(new CustomEvent("erw-lit-selection",{detail:{kind:"area",page:n,length:0}}))};
 const up=()=>{document.removeEventListener("mousemove",move,true);document.removeEventListener("mouseup",up,true);S.area=false;qa(".lit-interaction-layer").forEach(el=>el.onmousedown=null);toolbar();const rs=S.areaResolver;S.areaResolver=null;if(rs){rs(areaPreviewDataUrl(S.pending))}else{openAiTabForArea()}}; /* v260930e · 框选完成：外部接管（悬浮球截图）优先于阅读区 AI 面板联动 */
 document.addEventListener("mousemove",move,true);document.addEventListener("mouseup",up,true); /* v260930n · 修复框选失效：move/up 此前定义后未挂载，拖动与松开无人监听，选区不出现 */
}
function openAiTabForArea(){ /* v260929d · 框选完成后联动：多模态开启时自动切到 AI 面板，「用框选区域」截图按钮立即出现 */
  const vis=window.ERWVisionEnabled?window.ERWVisionEnabled():false;if(!vis)return;
  const aiBtn=qa('[data-tab]').find(b=>b.dataset.tab==="ai");if(!aiBtn)return;
  switchTab("ai");
}
async function undo(){const op=S.undo.pop();if(!op)return;await api("/api/literature/"+S.paper.id+"/annotations/"+op.id,{method:"DELETE"});removeAnnotationLocal(op.id,op.page);paint(op.page);toolbar();annList()}
function paint(n){
 const r=S.pages.get(n);if(!r?.rendered)return;
 const svg=q(".lit-annotation-layer",r.el);svg.innerHTML="";
 (r.annotations||[]).forEach(a=>(a.rects||[]).forEach(x=>{
  if(a.type==="underline"||a.type==="strikeout"){
   const line=document.createElementNS("http://www.w3.org/2000/svg","line");
   const y=a.type==="underline"?x[3]:(x[1]+x[3])/2;
   line.setAttribute("x1",x[0]);line.setAttribute("x2",x[2]);line.setAttribute("y1",y);line.setAttribute("y2",y);
   line.setAttribute("class","ann-line "+(a.type==="underline"?"ann-underline-line":"ann-strike-line"));
   svg.appendChild(line);
  }else{
   const e=document.createElementNS("http://www.w3.org/2000/svg","rect");
   e.setAttribute("x",x[0]);e.setAttribute("y",x[1]);e.setAttribute("width",x[2]-x[0]);e.setAttribute("height",x[3]-x[1]);
   e.setAttribute("class","ann-highlight");svg.appendChild(e);
  }
 }));
}
function handlePageAnnotationClick(n,e){
 if(S.pending||S.area)return;
 const r=S.pages.get(n),page=q(".lit-page",r.el),pr=page.getBoundingClientRect();
 const x=clamp((e.clientX-pr.left)/pr.width),y=clamp((e.clientY-pr.top)/pr.height);
 const anns=[...(r.annotations||[])].reverse();
 for(const a of anns){
  for(const rect of a.rects||[]){
   const padY=Math.max(.003,(rect[3]-rect[1])*.28),padX=.003;
   if(x>=rect[0]-padX&&x<=rect[2]+padX&&y>=rect[1]-padY&&y<=rect[3]+padY){
    openAnnotation(n,a.id);return;
   }
  }
 }
}
function pageAtScroll(){
 const sc=q("#lit-scroll");if(!sc||!S.pdf)return 1;
 const y=sc.scrollTop+70;let lo=1,hi=S.pdf.numPages,best=1;
 /* v261009p · 二分定位当前页：旧实现每次滚动对所有页 getBoundingClientRect()，长文档会频繁强制布局 O(N)。 */
 while(lo<=hi){const mid=(lo+hi)>>1,r=S.pages.get(mid);if(!r){break}if(r.el.offsetTop<=y){best=mid;lo=mid+1}else hi=mid-1}
 const a=S.pages.get(best),b=S.pages.get(Math.min(S.pdf.numPages,best+1));
 if(a&&b){const da=Math.abs((a.el.offsetTop+a.el.offsetHeight/2)-y),db=Math.abs((b.el.offsetTop+b.el.offsetHeight/2)-y);if(db<da)best=best+1}
 return best;
}
function track(){if(S.zooming)return;const best=pageAtScroll();/* 回收的预读页可能仍在 observer 边界内，滚动时重新预热当前页和相邻页。 */for(let n=Math.max(1,best-1);n<=Math.min(S.pdf?.numPages||0,best+1);n++)renderPage(n);scheduleTrim(best);if(best===S.current)return;S.current=best;toolbar();dispatchPage();clearTimeout(track.t);track.t=setTimeout(()=>savePos(best),400)} /* v261009p · O(logN) 页定位 + 有界渲染缓存 */
async function savePos(page){if(!S.paper||!S.pdf)return;const st=S.paper.reading_status==="未读"?"在读":S.paper.reading_status;S.paper.last_page=page;S.paper.reading_status=st;if(S.infoBase&&JSON.stringify(S.infoDraft)===S.infoBase){S.infoDraft.reading_status=st;const select=q("#li-status");if(select)select.value=st;S.infoBase=JSON.stringify(S.infoDraft)}try{await api("/api/literature/"+S.paper.id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({last_page:page,page_count:S.pdf.numPages,reading_status:st})})}catch{}}
function dispatchPage(){document.dispatchEvent(new CustomEvent("erw-lit-page",{detail:{page:S.current}}))} /* v260930d · M5 翻页事件 */
function go(n,smooth=true){
 const rec=S.pages.get(n),sc=q("#lit-scroll");if(!rec||!sc)return;
 renderPage(+n); /* 跳页时主动预热目标页，不等 IntersectionObserver 下一拍 */
 const top=Math.max(0,rec.el.offsetTop-8);
 sc.scrollTo({top,behavior:smooth?"smooth":"auto"});S.current=+n;toolbar();dispatchPage();scheduleTrim(+n);
}
function layout(){
 const shell=q(".lit-shell");if(!shell)return;
 shell.classList.toggle("library-hidden",S.libraryHidden);shell.classList.toggle("side-hidden",S.sideHidden);
 q("#lit-toggle-library").setAttribute("aria-expanded",String(!S.libraryHidden));q("#lit-toggle-side").setAttribute("aria-expanded",String(!S.sideHidden));
 q("#lit-focus").setAttribute("aria-pressed",String(S.focus));q("#lit-focus").textContent=S.focus?"退出专注":"专注阅读";
}
function showSide(){S.sideHidden=false;S.focus=false;layout()}
async function refit(){
 const pdf=S.pdf;if(!pdf||!q(".lit-shell"))return;const first=await pdf.getPage(1);if(pdf!==S.pdf||!q("#lit-scroll"))return;
 const target=Math.max(.2,Math.min(2.4,availablePdfWidth()/first.getViewport({scale:1}).width));
 if(S.pages.size&&Math.abs(target-S.scale)<.002){refreshPdfResolution();return}
 const keep=S.current,gen=++S.generation;S.observer?.disconnect();await build();if(gen===S.generation&&q(".lit-shell"))go(keep,false);
}
function pdfAnchor(clientX,clientY){
 const sc=q("#lit-scroll");if(!sc)return null;const view=sc.getBoundingClientRect(),scale=view.width/sc.clientWidth||1;
 const x=clientX??(view.left+view.width/2),y=clientY??(view.top+view.height/2);
 const rec=[...S.pages.entries()].find(([,r])=>{const b=r.el.getBoundingClientRect();return y>=b.top&&y<=b.bottom})||[S.current,S.pages.get(S.current)];
 if(!rec[1])return null;const b=rec[1].el.getBoundingClientRect();
 return {page:rec[0],x:(x-view.left)/scale,y:(y-view.top)/scale,u:Math.max(0,Math.min(1,(x-b.left)/(b.width||1))),v:Math.max(0,Math.min(1,(y-b.top)/(b.height||1)))};
}
function restorePdfAnchor(anchor){
 const sc=q("#lit-scroll"),rec=anchor&&S.pages.get(anchor.page);if(!sc||!rec)return;
 const view=sc.getBoundingClientRect(),page=rec.el.getBoundingClientRect(),scale=view.width/sc.clientWidth||1;
 sc.scrollLeft+=(page.left+page.width*anchor.u-view.left)/scale-anchor.x;
 sc.scrollTop+=(page.top+page.height*anchor.v-view.top)/scale-anchor.y;
 S.current=anchor.page;
}
function stopWheelZoom(){
 clearTimeout(wheelTimer);cancelAnimationFrame(wheelFrame);wheelFrame=0;wheelTarget=null;wheelAnchor=null;zoomSerial++;S.zooming=false;
 const host=q("#lit-pages");if(host)host.style.zoom="";
}
function paintWheelZoom(){
 wheelFrame=0;const host=q("#lit-pages");if(!host||wheelTarget==null)return;
 host.style.zoom=String(wheelTarget/wheelBase);restorePdfAnchor(wheelAnchor);toolbar();
}
async function commitPdfZoom(target,anchor){
 if(!S.pdf||!q("#lit-pages"))return;const serial=++zoomSerial,gen=++S.generation;
 S.zooming=true;S.zoomMode="manual";S.scale=target;wheelTarget=null;q("#lit-pages").style.zoom="";S.observer?.disconnect();clearTimeout(track.t);
 try{await build();if(gen!==S.generation||serial!==zoomSerial||!q("#lit-pages"))return;restorePdfAnchor(anchor);renderPage(S.current);toolbar();dispatchPage();scheduleTrim();
  requestAnimationFrame(()=>{if(serial===zoomSerial)S.zooming=false});
 }catch(error){if(serial===zoomSerial){S.zooming=false;toast("PDF 缩放失败："+error.message,true)}}
}
function pdfWheelZoom(event){
 if(!(event.ctrlKey||event.metaKey)||!event.deltaY||!S.pdf)return;
 event.preventDefault();event.stopPropagation();
 const current=wheelTarget??S.scale,next=window.ERWResearchUI.wheelScale(current,event,.2,4);if(Math.abs(next-current)<.00001)return;
 if(wheelTarget==null)wheelBase=S.scale;
 wheelAnchor=pdfAnchor(event.clientX,event.clientY);wheelTarget=next;S.zoomMode="manual";S.zooming=true;zoomSerial++;clearTimeout(track.t);
 if(!wheelFrame)wheelFrame=requestAnimationFrame(paintWheelZoom);
 clearTimeout(wheelTimer);wheelTimer=setTimeout(()=>{if(wheelFrame){cancelAnimationFrame(wheelFrame);paintWheelZoom()}commitPdfZoom(wheelTarget,wheelAnchor)},160);
}
async function zoom(delta){
 if(!S.pdf)return;const target=Math.max(.2,Math.min(4,(wheelTarget??S.scale)+delta)),anchor=pdfAnchor();stopWheelZoom();await commitPdfZoom(target,anchor);
}
function toolbar(){if(!S.pdf)return;q(".lit-toolbar").dataset.selection=String(!!S.pending);q("#lit-focus").disabled=false;q("#lit-fit").disabled=false;q("#lit-toggle-side").disabled=false;q("#lit-page-label").textContent=S.current+" / "+S.pdf.numPages;q("#lit-zoom-label").textContent=Math.round((wheelTarget??S.scale)*100)+"%";qa("[data-ann]").forEach(b=>{b.disabled=!S.pending;b.classList.toggle("ready",!!S.pending)});qa("[data-ai]").forEach(b=>{b.disabled=!(S.pending?.kind==="text"&&S.pending?.text);b.classList.toggle("ready",!!(S.pending?.kind==="text"&&S.pending?.text))});q("#lit-area").classList.toggle("active",S.area);q("#lit-area").textContent=S.area?"拖动选择区域…":"框选区域";q("#lit-undo").disabled=!S.undo.length;const cp=q("#lit-copy");if(cp)cp.disabled=!(S.pending?.kind==="text"&&S.pending?.text)}


async function openAnnotation(page,id){
 showSide();
 const a=annotationById(id);if(!a)return;
 captureAnnotation();
 S.selectedAnn={page:+page,id};
 switchTab('annotations');
}
async function jumpToAnnotation(page,id){
 const r=S.pages.get(+page);if(!r)return;
 if(!r.rendered)await renderPage(+page);
 go(+page,true);
 const a=annotationById(id);
 if(a)await openAnnotation(page,id);
}
async function saveAnnotationComment(){
 captureAnnotation();const draft=annotationDrafts.get(S.paper?.id+'/'+S.selectedAnn?.id);if(!draft)return false;
 if(!await saveAnnotationDraft(draft))return false;
 if(draft.text===draft.base&&S.selectedAnn?.id===draft.id){S.selectedAnn=null;annList();go(draft.page,true)}
 return true;
}
async function saveAnnotationDraft(draft){
 if(draft.saving)return draft.saving;
 const a=annotationById(draft.id);if(!a||S.paper?.id!==draft.paperId)return false;
 const comment=draft.text;
 draft.saving=(async()=>{try{
  const saved=await api('/api/literature/'+encodeURIComponent(draft.paperId)+'/annotations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...a,comment})});
  captureAnnotation();draft.base=String(saved.comment||'');upsertAnnotation(saved);paint(draft.page);return true;
 }catch(e){toast('批注保存失败：'+e.message,true);return false}
 finally{draft.saving=null;window.dispatchEvent(new Event('workbench:editor-state'))}})();
 return draft.saving;
}
/* v260929f · 批注加入笔记：摘录（blockquote）+ 意见，可勾选附带已落盘截图（Markdown 图片引用，Workspace 相对路径） */
async function annToNote(){
 const a=annotationById(S.selectedAnn?.id);if(!a)return;
 const withShot=!!(q("#ann-with-shot")?.checked&&a.preview_path);
 const comment=(q("#ann-comment")?.value||"").trim();
 const text=String(a.text||"").trim();
 if(!text&&!comment&&!withShot){toast("批注还没有内容：先填写批注意见或勾选截图",true);return}
 const btn=q("#ann-to-note");if(btn){btn.disabled=true;btn.textContent="写入中…"}
 try{
  /* v260929w · 截图复制到笔记图片目录（设置指定的位置）：Previews 缩略图会随批注删除被清理，笔记引用须独立文件 */
  let shotPath=String(a.preview_path||"");
  if(withShot){try{const cp=await api("/api/literature/note-image-copy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({paper_id:S.paper.id,preview_path:a.preview_path})});if(cp?.path)shotPath=cp.path}catch{}}
  const state=await loadNote();
  const cur=state.text;
  const tag="P."+a.page+(a.no?" · #"+a.no:"");
  let block="**批注 "+tag+"**\n";
  if(text)block+="> "+text.replace(/\r?\n/g,"\n> ")+"\n";
  if(withShot)block+="![批注 "+tag+" 截图]("+shotPath+")\n";
  if(comment)block+=comment+"\n";
  const next=cur.replace(/\s+$/,"")+(cur.trim()?"\n\n":"")+block;
  state.text=next;switchTab("notes");noteStatus("批注已加入草稿，请保存笔记");
  if(btn){btn.textContent="已写入 ✓";setTimeout(()=>btn&&(btn.textContent="加入笔记"),1200)}
  loadList().catch(()=>{});
 }catch(e){if(btn){btn.textContent="失败";setTimeout(()=>btn&&(btn.textContent="加入笔记"),1500)}toast(e?.message||String(e),true)}
}
function side(){
 q('#lit-side').innerHTML='<div class="lit-side-tabs"><button class="active" data-tab="info">信息</button><button data-tab="annotations">批注</button><button data-tab="notes">笔记</button><button data-tab="ai">AI</button></div><div id="lit-side-body"></div>';
 qa('#lit-side [data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));S.sideTab='info';sideTab('info');
}
function sideTab(tab){
 captureAnnotation();
 const root=q('#lit-side-body');if(!root||!S.paper)return;root.dataset.litTab=tab;
 if(tab==='info'){
  const p=S.infoDraft||S.paper;
  const field=(label,id,value,type='text')=>'<label>'+label+'<input id="'+id+'" type="'+type+'" value="'+esc(value||'')+'"></label>';
  root.innerHTML='<div class="lit-info">'+field('题名','li-title',p.title)+field('作者','li-authors',p.authors)+'<div class="lit-two">'+field('年份','li-year',p.year)+'<label>阅读状态<select id="li-status">'+['未读','在读','已读'].map(x=>'<option '+(x===(p.reading_status||'未读')?'selected':'')+'>'+x+'</option>').join('')+'</select></label></div><label>关联项目</label><div class="project-picker-row"><div class="project-chip-box" id="li-projects"></div><button type="button" class="secondary-btn project-add-btn" id="li-project-add" aria-label="选择关联项目">＋</button></div><label>分类标记</label><div class="mark-chip-box" id="li-marks"></div><label>标签</label><div class="project-picker-row"><div class="project-chip-box" id="li-tags"></div><button type="button" class="secondary-btn project-add-btn" id="li-tag-add" aria-label="添加标签">＋</button></div>'+field('期刊 / 会议','li-venue',p.venue)+field('DOI','li-doi',p.doi)+field('来源 URL','li-url',p.url)+'<div class="lit-two">'+field('引用键','li-cite',p.cite_key)+field('加入日期','li-added',p.added_date,'date')+'</div><details class="lit-info-extra"><summary>BibTeX 与自动填写</summary><div class="lit-lookup"><input id="li-lookup" placeholder="DOI、arXiv 或 BibTeX"><button type="button" id="li-lookup-run">填写</button></div><label>BibTeX<textarea id="li-bibtex" rows="6">'+esc(p.bibtex||'')+'</textarea></label></details><label class="lit-favorite"><input type="checkbox" id="li-favorite" '+(p.favorite?'checked':'')+'> 收藏 / 置顶</label><div class="lit-info-message" id="li-message" role="status"></div><div class="lit-info-actions"><button type="button" class="primary-btn" id="li-save">保存信息</button><button type="button" class="ghost-btn danger" id="li-delete">删除文献</button></div></div>';
  renderLiMarks();paintLiTags(p.tags||[]);paintLiProjects(p.projects||[]);q('#li-save').onclick=saveInfo;q('#li-delete').onclick=deletePaper;
  q('#li-lookup-run').onclick=async()=>{const value=q('#li-lookup').value.trim(),button=q('#li-lookup-run');if(!value)return;button.disabled=true;try{const data=value.startsWith('@')?window.ERWBibtexFields(value):await api('/api/literature/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:value})});for(const [key,id] of Object.entries({title:'li-title',authors:'li-authors',year:'li-year',venue:'li-venue',doi:'li-doi',url:'li-url',cite_key:'li-cite',bibtex:'li-bibtex'}))if(data[key])q('#'+id).value=data[key];captureInfo();q('#li-message').textContent='已填写，请核对后保存'}catch(e){q('#li-message').textContent=e.message}finally{button.disabled=false}};
  S.infoDraft=infoPayload();if(!S.infoBase)S.infoBase=JSON.stringify(S.infoDraft);
  root.oninput=()=>{captureInfo();window.dispatchEvent(new Event('workbench:editor-state'))};
 }else{root.oninput=null;if(tab==='annotations')annList();else if(tab==='ai')aiPanel();else return note()}
}
function switchTab(tab){captureNote();captureInfo();captureAnnotation();if(tab!=='annotations')S.selectedAnn=null;S.sideTab=tab;qa('#lit-side [data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));return sideTab(tab)}
function liProjects(){const box=q('#li-projects');try{return JSON.parse(box?.dataset.projects||'[]')}catch{return []}}
function paintLiProjects(names){const box=q('#li-projects');if(!box)return;box.dataset.projects=JSON.stringify(names);box.innerHTML=names.length?names.map((name,index)=>'<span class="project-chip" title="'+esc(name)+'"><span class="project-chip-label">'+esc(window.ERWResearchUI?.projectLabel(name)||name)+'</span><button type="button" data-li-project-remove="'+index+'" aria-label="移除项目">×</button></span>').join(''):'<span class="row-meta">未关联项目</span>';qa('[data-li-project-remove]',box).forEach(b=>b.onclick=()=>{const values=liProjects();values.splice(+b.dataset.liProjectRemove,1);paintLiProjects(values);captureInfo()});q('#li-project-add').onclick=()=>window.ERWProjectPicker?.(liProjects(),values=>{paintLiProjects(values);captureInfo()})}
/* v260929 · PDF 阅读区 AI 助手：选中文本 → 翻译/总结/整理/自定义指令，结果可追加/替换到文献笔记（条目正文同源） */

function aiFromSelection(action){if(!(S.pending?.kind==="text"&&S.pending?.text))return;switchTab("ai");runAssist(action,"")}
const AI_LABELS={translate:"AI 翻译中…",summarize:"AI 总结中…",organize:"AI 整理中…",polish:"AI 润色笔记中…",custom:"AI 处理中…"};
async function runAssist(action,instruction,label,explicitSource){ /* v260929b · label：按钮文字，自定义动作据此显示「AI xxx中…」；v260929c · image：截图代替/伴随文本 */
 if(S.ai.busy)return;
 const fresh=S.pending?.kind==="text"?String(S.pending.text||""):"";
 const src=explicitSource!==undefined?explicitSource:fresh||S.ai.text||"";
 const img=explicitSource!==undefined?"":S.ai.image||"";
 if(!src&&!img){S.ai={...S.ai,text:"",result:"",busy:false,error:"没有可处理的内容：请先在 PDF 中选中文字、截取页面/框选区域，或在「笔记」页用 AI 整理已有笔记。"};aiPanel();return}
 const paperId=S.paper?.id,requestKey=S.aiRequest=(S.aiRequest||0)+1;
 S.ai={...S.ai,text:src,instruction:action==="custom"?(instruction||S.ai.instruction):"",result:"",error:"",busy:true,busyLabel:AI_LABELS[action]||(label?"AI "+label+"中…":"AI 处理中…")};aiPanel();
 try{const d=await api("/api/agent/assist",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,text:src,instruction:action==="custom"?(instruction||S.ai.instruction):"",...(img?{image:img}:{})})});if(paperId!==S.paper?.id||requestKey!==S.aiRequest)return;S.ai={...S.ai,result:String(d.content||""),error:"",busy:false}}
 catch(e){if(paperId!==S.paper?.id||requestKey!==S.aiRequest)return;S.ai={...S.ai,error:String(e?.message||e),result:"",busy:false}}
 aiPanel();
}
function mdLite(s){ /* 结果区轻量 Markdown 渲染：所有模型输出先转义，再拼受控标签，避免同源 XSS */
 const lines=String(s||"").split(/\r?\n/);let out="",inList=false,inCode=false;
 const inline=t=>esc(t).replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`]+)`/g,"<code>$1</code>");
 for(const raw of lines){
  const t=raw.trimEnd();
  if(t.trim().startsWith("```")){if(inList){out+="</ul>";inList=false}out+=inCode?"</code></pre>":"<pre><code>";inCode=!inCode;continue}
  if(inCode){out+=esc(raw)+"\n";continue}
  const h=t.match(/^(#{1,6})\s+(.*)$/);
  if(h){if(inList){out+="</ul>";inList=false}out+="<h4>"+inline(h[2])+"</h4>";continue}
  const li=t.match(/^\s*[-*·]\s+(.*)$/);
  if(li){if(!inList){out+="<ul>";inList=true}out+="<li>"+inline(li[1])+"</li>";continue}
  if(!t.trim()){if(inList){out+="</ul>";inList=false}continue}
  if(inList){out+="</ul>";inList=false}
  out+="<p>"+inline(t)+"</p>";
 }
 if(inList)out+="</ul>";if(inCode)out+="</code></pre>";
 return out;
}
function aiPanel(){
 const root=q("#lit-side-body");if(!root||S.sideTab!=="ai")return;const a=S.ai;
 const cas=window.ERWAssistCustomActions?window.ERWAssistCustomActions():[]; /* v260929b · 设置中维护的自定义阅读动作，与固定四动作并列 */
 const vis=window.ERWVisionEnabled?window.ERWVisionEnabled():false; /* v260929c · 多模态开关：开启才显示截图入口 */
 const srcHtml=a.image?'<img class="lit-ai-img" src="'+esc(a.image)+'" alt="待处理截图">'+(a.text?'<div class="lit-ai-src-text">'+esc(a.text.slice(0,600))+(a.text.length>600?"…":"")+'</div>':"")
  :'<div class="lit-ai-src-text">'+(a.text?esc(a.text.slice(0,600))+(a.text.length>600?"…":""):'<i>暂无。选中文字后点工具栏「AI 翻译 / 总结 / 整理」'+(vis?'，或点下方「📷 截取当前页」用截图代替选中文本':'')+'；也可在「笔记」页点「AI 整理」。</i>')+'</div>';
 root.innerHTML='<div class="lit-ai">'
 +'<div class="lit-ai-src"><span class="lit-ai-src-head">待处理内容</span>'+srcHtml+'</div>'
 +(vis?'<div class="lit-ai-capture"><button type="button" class="secondary-btn" id="lit-ai-cap-page" title="把当前整页截图交给 AI（多模态），代替选中文本，公式/表格提取更准">📷 截取当前页</button>'+(S.pending?.kind==="area"?'<button type="button" class="secondary-btn" id="lit-ai-cap-area" title="把当前框选区域截图交给 AI">用框选区域</button>':"")+(a.image?'<button type="button" class="ghost-btn danger" id="lit-ai-cap-clear" title="移除截图，回到纯文本模式">移除截图</button>':"")+'</div>':"")
 +'<div class="lit-ai-actions"><button type="button" class="secondary-btn" data-aia="translate">翻译</button><button type="button" class="secondary-btn" data-aia="summarize">总结</button><button type="button" class="secondary-btn" data-aia="organize">整理</button><button type="button" class="secondary-btn" data-aia="polish" title="处理当前待处理内容为润色后的笔记">润色</button>'+cas.map(x=>'<button type="button" class="secondary-btn" data-aia="'+esc(x.id)+'" title="'+esc(String(x.prompt||"").slice(0,100))+'">'+esc(x.name)+'</button>').join('')+'</div>'
 +'<div class="lit-ai-custom"><input id="lit-ai-instr" placeholder="自定义指令，如：解释这段公式推导…" value="'+esc(a.instruction||"")+'"><button type="button" class="primary-btn" id="lit-ai-run">运行</button></div>'
 +(a.busy?'<div class="lit-ai-result busy">'+esc(a.busyLabel||"AI 处理中…")+'</div>'
  :(a.result?'<div class="lit-ai-result">'+mdLite(a.result)+'</div><div class="lit-ai-foot"><button type="button" class="primary-btn" id="lit-ai-append" title="把 AI 结果追加到该文献笔记（条目正文）末尾">追加到笔记</button><button type="button" class="secondary-btn" id="lit-ai-replace" title="用 AI 结果整体替换该文献笔记（条目正文）">替换笔记</button><button type="button" class="secondary-btn" id="lit-ai-copy">复制</button></div>'
  :(a.error?'<div class="lit-ai-result err">'+esc(a.error)+'</div>':'')))
 +'</div>';
 qa("[data-aia]").forEach(b=>b.onclick=()=>runAssist(b.dataset.aia,"",b.textContent)); /* v260929b · 传按钮文字作 label，固定四动作仍由 AI_LABELS 优先 */
 const capP=q("#lit-ai-cap-page");if(capP)capP.onclick=()=>{const d=pageDataUrl();if(!d){S.ai={...S.ai,error:"当前页尚未渲染完成，请稍候再试"};aiPanel();return}S.ai={...S.ai,image:d,result:"",error:""};aiPanel()}; /* v260929c · 整页截图 */
 const capA=q("#lit-ai-cap-area");if(capA)capA.onclick=()=>{const d=areaPreviewDataUrl(S.pending,1400,1200,.86);if(d){S.ai={...S.ai,image:d,result:"",error:""};aiPanel()}}; /* v260929c · 框选区域截图（高清档） */
 const capX=q("#lit-ai-cap-clear");if(capX)capX.onclick=()=>{S.ai={...S.ai,image:""};aiPanel()}; /* v260929c · 移除截图 */
 const run=q("#lit-ai-run");if(run)run.onclick=()=>{const v=q("#lit-ai-instr")?.value||"";S.ai.instruction=v;if(!v.trim()){S.ai={...S.ai,error:"请先输入自定义指令（如：解释这段公式推导）"};aiPanel();return}runAssist("custom",v)};
 const ap=q("#lit-ai-append");if(ap)ap.onclick=()=>noteApply("append");
 const rp=q("#lit-ai-replace");if(rp)rp.onclick=()=>noteApply("replace");
 const cp=q("#lit-ai-copy");if(cp)cp.onclick=async()=>{try{await navigator.clipboard.writeText(S.ai.result||"");cp.textContent="已复制";setTimeout(()=>cp&&(cp.textContent="复制"),900)}catch{}};
}
async function noteApply(mode){
 if(!S.paper||!S.ai.result)return;
 try{const state=await loadNote();if(state.id!==S.paper?.id)return;captureNote();if(mode==='replace'&&state.text.trim()&&!await window.ERWDialog.confirm('用 AI 结果替换当前笔记草稿？保存前仍可继续编辑。',{title:'替换笔记草稿'}))return;
 if(state.id!==S.paper?.id)return;state.text=mode==='replace'?S.ai.result:state.text.replace(/\s+$/,'')+(state.text.trim()?'\n\n':'')+S.ai.result+'\n';switchTab('notes');noteStatus('AI 结果已放入草稿，请核对并保存')
 }catch(e){toast(e.message,true)}
}
async function saveInfo(){
 captureInfo();if(S.infoSaving)return S.infoSaving;const payload=S.infoDraft,id=S.paper?.id;if(!payload||!id)return false;const requestBody={...payload};if(payload.bibtex===JSON.parse(S.infoBase||"{}").bibtex)delete requestBody.bibtex;
 if(S.noteState&&S.noteState.text!==S.noteState.base&&!await saveNote())return false;
 const button=q('#li-save'),message=q('#li-message');if(button)button.disabled=true;if(message)message.textContent='正在保存…';
 S.infoSaving=(async()=>{try{const paper=await api('/api/literature/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(requestBody)});if(S.paper?.id===id){S.paper=paper;S.infoBase=JSON.stringify(payload);if("bibtex" in requestBody&&S.noteState?.text===S.noteState?.base)S.noteState=null;if(message)message.textContent='信息已保存';await loadList();window.dispatchEvent(new Event('workbench:editor-state'))}return true}catch(e){if(message)message.textContent='保存失败：'+e.message;toast('文献信息保存失败：'+e.message,true);return false}finally{if(button)button.disabled=false;S.infoSaving=null}})();return S.infoSaving;
}
async function deletePaper(){if(!S.paper||!await guard())return;if(!await window.ERWDialog.confirm('删除这篇文献、PDF 与笔记？本地文件将移入回收区。'))return;const id=S.paper.id;try{await api('/api/literature/'+encodeURIComponent(id),{method:'DELETE'});S.noteState=null;S.infoBase=null;S.infoDraft=null;reset();S.paper=null;shell();await loadList()}catch(e){toast(e.message,true)}}
/* v260929 · 阅读区信息栏「分类标记」chips：与编辑区同款渲染（复用 app.js 的 ERWMarkChips），保存时随 saveInfo 写回条目 md */
function renderLiMarks(){
 const box=q("#li-marks"); if(!box||!window.ERWMarkChips)return;
 const on=qa("#li-marks .mark-chip.on").map(b=>b.dataset.mark);
 const saved=(S.infoDraft||S.paper)?.kind_marks||[];
 box.innerHTML=window.ERWMarkChips.html([...new Set([...on,...saved])]);
 qa("#li-marks .mark-chip:not(.add-mark)").forEach(b=>b.onclick=()=>b.classList.toggle("on"));
 const add=q("#li-marks .mark-chip.add-mark");
  if(add)add.onclick=()=>window.ERWMarkChips.openManager(renderLiMarks);
}
/* v260929 · 阅读区标签 chip 化：与文献编辑区同款（× 移除 + ＋ 弹窗勾选已有或新建），替换原逗号输入框 */
function liTags(){const box=q("#li-tags");if(!box)return [];try{const v=JSON.parse(box.dataset.tags||"[]");return Array.isArray(v)?v:[]}catch{return []}}
function paintLiTags(tags){
 const box=q("#li-tags");if(!box)return;
 const list=[...new Set((tags||[]).map(x=>String(x).trim()).filter(Boolean))];
 box.dataset.tags=JSON.stringify(list);
 box.innerHTML=list.length?list.map((t,i)=>'<span class="project-chip tag-chip" title="'+esc(t)+'"><span class="project-chip-label">'+esc(t)+'</span><button type="button" data-tag-remove="'+i+'" title="移除标签">×</button></span>').join(""):'<span class="row-meta">暂无标签</span>';
 qa("[data-tag-remove]",box).forEach(b=>b.onclick=()=>{const now=liTags();now.splice(+b.dataset.tagRemove,1);paintLiTags(now)});
 const add=q("#li-tag-add");
 if(add)add.onclick=()=>{if(window.ERWTagPicker)window.ERWTagPicker(liTags(),()=>[...new Set(S.items.flatMap(x=>x.tags||[]))],paintLiTags)};
}
/* v260929g · 列表按编号排序：编号即创建（截图）顺序，跨页也按全局编号排列；缺号旧数据排末尾 */
function loadedAnns(){return [...(S.annotations||[])].sort((a,b)=>((a.no||Number.MAX_SAFE_INTEGER)-(b.no||Number.MAX_SAFE_INTEGER))||String(a.created_at||"").localeCompare(String(b.created_at||"")))}
function annList(){
 const root=q("#lit-side-body");if(!root||!q('[data-tab="annotations"]')?.classList.contains("active"))return;
 captureAnnotation();
 if(S.selectedAnn&&!annotationById(S.selectedAnn.id))S.selectedAnn=null;
 const editId=S.selectedAnn?.id;
 const rows=loadedAnns();
 /* v260929g · 选中批注原地展开为编辑卡片（不抽到顶部，位置不随选中改变） */
 const card=a=>{
  if(a.id!==editId)return '<article class="lit-ann" data-open-ann="'+a.id+'" data-page="'+a.page+'"><div><strong>P.'+a.page+(a.no?" · #"+a.no:"")+" · "+esc(a.type)+'</strong><button data-del="'+a.id+'" data-page="'+a.page+'">×</button></div>'+annotationExcerpt(a,true)+(a.comment?"<p>"+esc(a.comment)+"</p>":"")+"</article>";
  return '<section class="lit-ann lit-ann-editor"><div class="lit-ann-editor-head"><strong>P.'+a.page+(a.no?' · #'+a.no:'')+' · '+esc(a.type)+'</strong><button id="ann-editor-close" title="收起">×</button></div>'+annotationExcerpt(a,false)+'<label>批注<textarea id="ann-comment" data-paper-id="'+esc(S.paper.id)+'" data-ann-id="'+esc(a.id)+'" placeholder="为这个标记添加批注…">'+esc(annotationDrafts.get(S.paper.id+'/'+a.id)?.text??a.comment??'')+'</textarea></label><div class="lit-ann-editor-actions"><button class="primary-btn" id="ann-comment-save">保存批注</button><button class="secondary-btn" id="ann-to-note" title="把批注摘录与意见写入笔记（条目正文）末尾'+(a.preview_path?'，可附带截图':'')+'">加入笔记</button>'+(a.preview_path?'<label class="lit-ann-shot-check" title="勾选后随批注内容一并写入笔记的 Markdown 图片引用"><input type="checkbox" id="ann-with-shot" checked> 附带截图</label>':'')+'</div></section>';
 };
 root.innerHTML='<div class="lit-ann-list">'+(rows.length?rows.map(card).join(""):'<div class="lit-empty">当前已加载页面暂无批注</div>')+"</div>";
 if(q("#ann-comment-save"))q("#ann-comment-save").onclick=saveAnnotationComment;
 if(q('#ann-comment'))q('#ann-comment').oninput=()=>{captureAnnotation();window.dispatchEvent(new Event('workbench:editor-state'))};
 if(q("#ann-to-note"))q("#ann-to-note").onclick=annToNote; /* v260929f · 批注内容（可含截图）写入笔记 */
 if(q("#ann-editor-close"))q("#ann-editor-close").onclick=()=>{S.selectedAnn=null;annList()};
 qa("[data-open-ann]").forEach(x=>x.onclick=e=>{if(e.target.closest("[data-del]"))return;jumpToAnnotation(+x.dataset.page,x.dataset.openAnn)});
 qa("[data-del]").forEach(b=>b.onclick=async()=>{const page=+b.dataset.page;await api("/api/literature/"+S.paper.id+"/annotations/"+b.dataset.del,{method:"DELETE"});removeAnnotationLocal(b.dataset.del,page);paint(page);if(S.selectedAnn?.id===b.dataset.del)S.selectedAnn=null;annList()});
}
/* v260929f · 笔记插图：选本地图片 → 落盘笔记图片目录 → 光标处插入 Markdown 图片引用（路径口径与附件一致） */
function insertAtCursor(ta,text){if(!ta)return;const s=ta.selectionStart??ta.value.length,e=ta.selectionEnd??s;ta.value=ta.value.slice(0,s)+text+ta.value.slice(e);const p=s+text.length;ta.focus();ta.setSelectionRange(p,p);ta.dispatchEvent(new Event("input",{bubbles:true}))}
async function uploadNoteImage(file){
 const dataUrl=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result));r.onerror=()=>rej(new Error("读取图片失败"));r.readAsDataURL(file)});
 return api("/api/literature/note-image",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({paper_id:S.paper.id,data_url:dataUrl})});
}
async function note(){
 const root=q('#lit-side-body'),id=S.paper?.id;if(!root||!id)return;root.innerHTML='<div class="lit-empty">正在载入笔记…</div>';
 try{const state=await loadNote();if(S.paper?.id!==id||S.sideTab!=='notes'||!root.isConnected)return;
 root.innerHTML='<div class="lit-note-tools"><strong>阅读笔记</strong><button type="button" id="lit-note-mode">'+(S.noteMode==='preview'?'编辑':'预览')+'</button><button type="button" id="lit-note-reference">引用</button></div><div class="lit-note-editor"><textarea class="lit-note" id="lit-note" placeholder="写下阅读笔记，支持 Markdown 和 [[引用]]…">'+esc(state.text)+'</textarea><div class="md-preview lit-note-preview" id="lit-note-preview" hidden></div></div><div class="lit-note-actions"><span id="lit-note-status" role="status">'+(state.text===state.base?'已保存 · Ctrl+S':'有未保存的修改')+'</span><div class="lit-note-buttons"><button type="button" class="secondary-btn" id="lit-note-img">插入图片</button><input type="file" id="lit-note-img-file" accept="image/png,image/jpeg,image/webp" hidden><button type="button" class="secondary-btn" id="lit-note-ai">AI 整理</button><button type="button" class="primary-btn" id="lit-note-save">保存笔记</button></div></div>';
 const ta=q('#lit-note');ta.oninput=()=>{state.text=ta.value;noteStatus(state.text===state.base?'已保存 · Ctrl+S':'有未保存的修改')};
 const mode=()=>{captureNote();const preview=q('#lit-note-preview');ta.hidden=S.noteMode==='preview';preview.hidden=S.noteMode!=='preview';q('#lit-note-mode').textContent=S.noteMode==='preview'?'编辑':'预览';if(S.noteMode==='preview'){const raw=state.text.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,(_,target,label)=>'<a data-agent-reference="'+esc(target)+'" href="#">'+esc(label||target)+'</a>');preview.innerHTML=window.DOMPurify?.sanitize(window.marked?.parse(raw)||mdLite(raw))||esc(raw);window.ERWDocReferences?.bindPreview(preview)}};
 q('#lit-note-mode').onclick=()=>{S.noteMode=S.noteMode==='edit'?'preview':'edit';mode()};q('#lit-note-reference').onclick=()=>{if(S.noteMode!=='edit'){S.noteMode='edit';mode()}window.ERWDocReferences?.openPicker(ta)};mode();window.ERWDocReferences?.bindEditor(ta);window.ERWPaneZoom?.bindText(ta,'erwPdfNoteZoom');
 q('#lit-note-save').onclick=saveNote;q('#lit-note-ai').onclick=()=>{captureNote();const text=state.text.trim();if(!text){noteStatus('笔记为空，请先输入内容');return}S.ai={...S.ai,text,image:'',result:'',error:'',busy:false};switchTab('ai');runAssist('polish','',undefined,text)};
 q('#lit-note-img').onclick=()=>q('#lit-note-img-file').click();q('#lit-note-img-file').onchange=async e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;try{const data=await uploadNoteImage(file);if(S.paper?.id!==id)return;const ta=q('#lit-note');const markdown='!['+(data.filename||'图片')+']('+(data.path||'')+')';if(ta)insertAtCursor(ta,markdown);else state.text+='\n'+markdown;captureNote();noteStatus('图片已插入，请保存笔记')}catch(error){toast(error.message,true)}};
 }catch(e){if(S.paper?.id===id&&S.sideTab==='notes'&&root.isConnected){root.innerHTML='<div class="lit-empty">笔记加载失败：'+esc(e.message)+'<br><button type="button" id="lit-note-retry">重试</button></div>';q('#lit-note-retry').onclick=note}}
}
async function saveNote(){
 captureNote();let state;try{state=await loadNote()}catch(e){toast('笔记加载失败：'+e.message,true);return false}if(state.saving)return state.saving;
 const text=state.text,button=q('#lit-note-save');if(button)button.disabled=true;noteStatus('正在保存…');
 state.saving=(async()=>{try{const saved=await api('/api/literature/'+encodeURIComponent(state.id)+'/note',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:text,...(state.revision!==null?{expected_revision:state.revision}:{})})});state.base=text;state.revision=saved.revision??null;if(S.paper?.id===state.id){noteStatus(state.text===text?'笔记已保存 · Ctrl+S':'已保存，仍有新的修改');loadList()}return true}catch(e){if(S.paper?.id===state.id)noteStatus('保存失败：'+e.message);toast('笔记保存失败：'+e.message,true);return false}finally{if(button)button.disabled=false;state.saving=null}})();return state.saving;
}
function throttle(fn,ms){let wait=false;return(...a)=>{if(wait)return;wait=true;fn(...a);setTimeout(()=>wait=false,ms)}}

function installSplitters(){
 const shell=q('.lit-shell');
 for(const [name,selector,fallback,min,max] of [['library','.lit-library',244,160,440],['side','.lit-reader',340,270,620]]){
  const key='erwLitWidth:'+name,stored=Number(localStorage.getItem(key)),width=Number.isFinite(stored)&&stored>=min?stored:fallback;
  shell.style.setProperty('--lit-'+name+'-width',Math.max(min,Math.min(max,width))+'px');
  const bar=document.createElement('div');bar.className='lit-splitter lit-splitter-'+name;bar.tabIndex=0;bar.setAttribute('role','separator');bar.setAttribute('aria-orientation','vertical');bar.setAttribute('aria-label',name==='library'?'调整文献列表宽度':'调整资料与笔记宽度');bar.setAttribute('aria-valuemin',min);bar.setAttribute('aria-valuemax',max);bar.setAttribute('aria-valuenow',width);q(selector,shell).after(bar);
  const apply=(value,persist=false)=>{const available=shell.clientWidth-(name==='library'&&!S.sideHidden?parseFloat(shell.style.getPropertyValue('--lit-side-width'))||340:name==='side'&&!S.libraryHidden?parseFloat(shell.style.getPropertyValue('--lit-library-width'))||244:0)-290;const next=Math.max(min,Math.min(max,available,value));shell.style.setProperty('--lit-'+name+'-width',next+'px');bar.setAttribute('aria-valuenow',Math.round(next));if(persist)localStorage.setItem(key,String(next));};
  let drag=null;bar.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();drag={x:e.clientX,width:parseFloat(shell.style.getPropertyValue('--lit-'+name+'-width')),zoom:shell.getBoundingClientRect().width/shell.clientWidth};bar.setPointerCapture(e.pointerId);shell.classList.add('is-resizing')};bar.onpointermove=e=>{if(drag)apply(drag.width+(e.clientX-drag.x)/(drag.zoom||1)*(name==='library'?1:-1))};
  const finish=()=>{if(!drag)return;drag=null;shell.classList.remove('is-resizing');apply(parseFloat(shell.style.getPropertyValue('--lit-'+name+'-width')),true);schedulePdfLayout()};bar.onpointerup=finish;bar.onpointercancel=finish;bar.onlostpointercapture=finish;
  bar.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();apply(e.key==='Home'?min:e.key==='End'?max:parseFloat(shell.style.getPropertyValue('--lit-'+name+'-width'))+(e.key==='ArrowRight'?16:-16)*(name==='library'?1:-1),true)}};
  bar.ondblclick=()=>apply(fallback,true);
 }
}
async function exportReferences(){
 const button=q('#lit-export'),status=q('#lit-export-status');
 try{
  const ids=S.items.map(item=>item.doc_id).filter(Boolean);
  if(!ids.length){toast('当前页没有可导出的引用');return}
  button.disabled=true;
  const result=await api('/api/literature/export-bibtex',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
  const missing=result.missing||[],reasons={missing_bibtex:'未填写 BibTeX',not_found:'文献不存在',not_literature:'不是文献条目',read_failed:'文献读取失败'};
  status.hidden=false;
  status.innerHTML='已选 '+(result.selected_count??ids.length)+' 篇 · 已导出 '+result.count+' 条 · 缺失 '+missing.length+' 篇'+(missing.length?'<details><summary>查看缺失引用</summary><ul>'+missing.map(x=>'<li>'+esc(x.title||x.id)+'：'+esc(reasons[x.reason]||x.reason)+'</li>').join('')+'</ul></details>':'');
  if(!result.count){toast('没有可导出的 BibTeX，请补充引用信息',true);return}
  const url=URL.createObjectURL(new Blob([result.content||''],{type:'application/x-bibtex;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='literature.bib';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(e){toast(e.message,true)}finally{if(button)button.disabled=false}
}
async function start(options={}){if(!await guard())return false;shell();S.listPage=1;await loadList();if(options.autoOpen!==false&&q('.lit-shell')){const saved=localStorage.getItem('erwLitRecentPaper'),hit=S.items.find(item=>item.id===saved)||S.items.find(item=>item.pdf_available!==false);if(hit)await openPaper(hit.id)}return true}
/* v260929 · 由文献条目附件徽章进入：按 attachment 路径尾段匹配库内 PDF 文件名（stored_filename 唯一），
   命中则进工作区并直接打开该论文；未登记（如手动填写附件路径的旧条目）抛错，由调用方退回新窗口直开 */
async function openByAttachment(att){
 const name=String(att||"").split(/[\\/]/).pop().trim();
 if(!name)throw new Error("无附件路径");
 /* v261009 · 分页查找，避免文献超过 200 篇时只扫第一页导致已登记附件被误判为“未登记”。 */
 let page=1,hit=null,total=0;
 do{
  const d=await api("/api/literature?page_size=200&page="+page);
  total=Number(d.total||0);
  hit=(d.items||[]).find(x=>String(x.stored_filename||"")===name)||null;
  if(hit)break;
  page++;
 }while((page-1)*200<total);
 if(!hit)throw new Error("该附件未登记到 PDF 工作区");
 if(await start({autoOpen:false})!==false)await openPaper(hit.id);
}
function destroy(){S.openSeq++;S.listSeq++;S.layoutObserver?.disconnect();clearTimeout(S.layoutTimer);reset();S.paper=null;S.noteState=null;S.infoDraft=null;S.infoBase=null;annotationDrafts.clear();window.ERWDocReferences?.close()}
function navigationState(){
 if(!q('.lit-shell')||!S.paper)return null;
 const scrolls={};for(const selector of ['#lit-scroll','#lit-list','#lit-side-body','#lit-note','#lit-note-preview']){const el=q(selector);if(el)scrolls[selector]={top:el.scrollTop,left:el.scrollLeft}}
 return {docId:S.paper.doc_id,title:S.paper.title,page:S.current,scale:S.scale,zoomMode:S.zoomMode,tab:S.sideTab,noteMode:S.noteMode,libraryHidden:S.libraryHidden,sideHidden:S.sideHidden,focus:S.focus,scrolls};
}
async function restoreNavigation(entry){
 if(!S.paper||S.paper.doc_id!==entry.docId)return;
 S.libraryHidden=entry.libraryHidden;S.sideHidden=entry.sideHidden;S.focus=entry.focus;S.noteMode=entry.noteMode;layout();
 await switchTab(entry.tab);
 if(S.pdf){S.scale=entry.scale;S.zoomMode=entry.zoomMode;await build();go(entry.page,false)}
 await new Promise(resolve=>requestAnimationFrame(resolve));
 for(const [selector,point] of Object.entries(entry.scrolls||{})){const el=q(selector);if(el){el.scrollTop=point.top;el.scrollLeft=point.left}}
}
window.ERWLiterature={start,guard,dirty,destroy,navigationState,restoreNavigation,refresh:loadList,openByAttachment,openById:async id=>{if(await start({autoOpen:false})!==false)return openPaper(id)},openByDocument:async(id,options={})=>{const paper=await api('/api/literature/document/'+encodeURIComponent(id));if(!q('.lit-shell')&&await start({autoOpen:false})===false)return false;const result=await openPaper(paper.id);if(options.note&&result!==false){showSide();await switchTab('notes')}return result},context:()=>({paper_id:S.paper?.id||"",title:S.paper?.title||"",page:S.current||1,selection:S.pending?.kind==="text"?String(S.pending.text||""):"",page_text:pageText(S.current||1)})};
/* v260930e · 悬浮球截图桥：page()=截当前整页；area()=进入框选模式，resolve 框选区域截图（外部接管联动） */
window.ERWCapture={
 page:()=>S.pdf?pageDataUrl():"",
 area:()=>new Promise(res=>{
   if(!S.pdf||!q(".lit-shell")){res("");return}
   S.areaResolver=res;
   if(!S.area)toggleArea();
 }),
};
// App zoom does not reliably trigger ResizeObserver. DPR can change on monitor moves.
new MutationObserver(schedulePdfLayout).observe(document.documentElement,{attributes:true,attributeFilter:["style"]});
window.addEventListener("resize",schedulePdfLayout);
function watchPdfDpi(){window.matchMedia("(resolution: "+(window.devicePixelRatio||1)+"dppx)").addEventListener("change",()=>{schedulePdfLayout();watchPdfDpi()},{once:true})}
watchPdfDpi();

function pageText(n){ /* v260930c · M4 · 取渲染页缓存的文本几何拼正文：textItems 为内容流顺序，术语提取够用；未渲染页返回空 */
 const r=S.pages.get(+n);if(!r||!Array.isArray(r.textItems))return "";
 return r.textItems.map(i=>i.text).join(" ").replace(/\s+/g," ").trim().slice(0,6000);
}
document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"&&q(".lit-shell")&&S.paper){e.preventDefault();if(S.sideTab==="info")saveInfo();else if(S.sideTab==="annotations")saveAnnotationComment();else saveNote()}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="c"&&S.pending?.kind==="text"&&!/input|textarea/i.test(document.activeElement?.tagName||"")){e.preventDefault();copyPendingText()}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="z"&&S.paper&&!/input|textarea/i.test(document.activeElement?.tagName||"")){e.preventDefault();undo()}else if(e.key==="Escape"&&(S.pending||S.area)){S.pending=null;paintPending();if(S.area)toggleArea();else toolbar();document.dispatchEvent(new CustomEvent("erw-lit-selection",{detail:{kind:"",page:S.current||1,length:0}}))} /* v261009 · Esc 同步清空悬浮 Agent 选区 chip */});
})();
