(()=>{
"use strict";
const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>Array.from(r.querySelectorAll(s));
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clamp=v=>Math.max(0,Math.min(1,v));
const S={items:[],paper:null,pdf:null,scale:1.15,current:1,pages:new Map(),observer:null,pending:null,undo:[],area:false,generation:0,selectedAnn:null,selectionOrigin:null,dragSel:null,annotations:[],ai:{text:"",image:"",result:"",error:"",busy:false,instruction:""}};

async function api(url,opts={}){const r=await fetch(url,opts);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.message||d.error||("HTTP "+r.status));return d}
async function ensurePdfJs(){
 if(window.pdfjsLib)return;
 await new Promise((ok,bad)=>{const s=document.createElement("script");s.src="https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.min.js";s.onload=ok;s.onerror=bad;document.head.appendChild(s)});
 if(!window.pdfjsLib)throw new Error("PDF.js 加载失败");
 window.pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js";
}
/* v260929 · 阅读区列表条目统一为文献列表页风格（.doc-item 同构）：标题→摘要→徽章行→项目+日期
   徽章行 = 阅读状态 + 收藏 + 分类标记；附件徽章去掉（点击条目本身即打开 PDF，徽章冗余）
   分类统一走「分类标记」（kind_marks），原 categories 徽章已移除（与标记重复） */
function item(x){
 const act=S.paper?.id===x.id?" active":"";
 const favB=x.favorite?'<span class="badge" title="已收藏">★</span>':"";
 const summ=x.excerpt?esc(x.excerpt):((x.authors||"")+(x.year?(" · "+x.year):""));
 const markB=window.ERWMarkBadges?window.ERWMarkBadges(x):"";
 const projBadges=(x.projects||[]).slice(0,1).map(p=>'<span class="badge accent proj-badge"><span class="proj-text">'+esc(p)+"</span></span>").join("");
 const dateB=x.updated_at?'<span class="badge mono">'+esc(String(x.updated_at).slice(0,10))+"</span>":"";
 const projRow=(projBadges||dateB)?'<div class="doc-projects">'+projBadges+dateB+"</div>":"";
 return '<article class="doc-item lit-item'+act+'" data-paper="'+esc(x.id)+'"><div class="title">'+esc(x.title)+'</div><div class="excerpt">'+summ+'</div><div class="tags"><span class="badge lit-status '+(x.reading_status==="已读"?"done":x.reading_status==="在读"?"reading":"")+'">'+esc(x.reading_status||"未读")+"</span>"+favB+markB+"</div>"+projRow+"</article>";
}

async function loadList(){
 const d=await api("/api/literature?q="+encodeURIComponent(q("#lit-search")?.value||"")+"&status="+encodeURIComponent(q("#lit-status")?.value||"")+"&mark="+encodeURIComponent(q("#lit-mark")?.value||"")+"&page_size=100");
 S.items=d.items||[];
 q("#lit-list").innerHTML=S.items.length?S.items.map(item).join(""):'<div class="lit-empty">暂无文献<br>点击“上传 PDF”开始</div>';
 const c=q("#lit-mark"),old=c.value;c.innerHTML='<option value="">全部分类</option>'+(window.ERWMarkList?window.ERWMarkList():[]).map(k=>'<option value="'+esc(k.id)+'"'+(k.id===old?" selected":"")+">"+esc(k.icon)+" "+esc(k.label)+"</option>").join("");
 qa("[data-paper]").forEach(e=>e.onclick=()=>openPaper(e.dataset.paper));
}
function shell(){
 q("#main").innerHTML='<div class="lit-shell"><aside class="card doc-list-panel lit-library"><div class="lit-library-head"><div><div class="card-kicker">LITERATURE LIBRARY</div><h3>文献库</h3></div><div class="lit-head-actions"><button class="ghost-btn" id="lit-back">← 返回文献列表</button><button class="primary-btn" id="lit-upload">＋ 上传 PDF</button></div></div><input id="lit-file" type="file" accept="application/pdf,.pdf" hidden><div class="doc-filter"><input class="search-input" id="lit-search" placeholder="搜索题名、作者、标签、分类…"><div class="lit-filters"><select class="search-input" id="lit-status"><option value="">全部进度</option><option>未读</option><option>在读</option><option>已读</option></select><select class="search-input" id="lit-mark"><option value="">全部分类</option></select></div></div><div class="doc-list lit-list" id="lit-list"></div></aside><section class="card lit-reader"><div id="lit-reader-empty" class="lit-empty lit-reader-empty">选择一篇文献开始阅读</div><div id="lit-reader-live" hidden><div class="lit-toolbar"><button data-ann="highlight" disabled>高亮</button><button data-ann="underline" disabled>下划线</button><button data-ann="strikeout" disabled>删除线</button><button id="lit-copy" disabled title="Ctrl+C">复制</button><span class="lit-sep"></span><button data-ai="translate" disabled title="将选中文本交给 AI 翻译为中文">AI 翻译</button><button data-ai="summarize" disabled title="将选中文本交给 AI 总结要点">AI 总结</button><button data-ai="organize" disabled title="将选中文本交给 AI 整理为知识笔记">AI 整理</button><span class="lit-sep"></span><button id="lit-area">框选区域</button><span class="lit-sep"></span><button id="lit-undo" disabled title="Ctrl+Z">↶ 撤销</button><span class="lit-sep"></span><span id="lit-page-label">1 / 1</span><button id="lit-zoom-out">−</button><span id="lit-zoom-label">115%</span><button id="lit-zoom-in">＋</button></div><div class="lit-canvas-scroll" id="lit-scroll"><div id="lit-pages" class="lit-pages"></div></div></div></section><aside class="card lit-side" id="lit-side"><div class="lit-empty">文献信息、批注和笔记将在这里显示</div></aside></div>';
 q("#lit-upload").onclick=()=>q("#lit-file").click();q("#lit-file").onchange=e=>upload(e.target.files?.[0]);
 q("#lit-back").onclick=()=>window.dispatchEvent(new Event("erw-lit-back")); /* v260929 · 返回文献列表：经事件通知 app.js 重新渲染列表页（hash 未变不触发路由） */
 let t;q("#lit-search").oninput=()=>{clearTimeout(t);t=setTimeout(loadList,160)};q("#lit-status").onchange=loadList;q("#lit-mark").onchange=loadList;
 qa("[data-ann]").forEach(b=>b.onclick=()=>commit(b.dataset.ann));qa("[data-ai]").forEach(b=>b.onclick=()=>aiFromSelection(b.dataset.ai));q("#lit-copy").onclick=copyPendingText;q("#lit-area").onclick=toggleArea;q("#lit-undo").onclick=undo;q("#lit-zoom-in").onclick=()=>zoom(.15);q("#lit-zoom-out").onclick=()=>zoom(-.15);
}
async function upload(file){if(!file)return;try{const r=await fetch("/api/literature/import",{method:"POST",headers:{"Content-Type":"application/pdf","X-Filename":encodeURIComponent(file.name)},body:file});const d=await r.json();if(!r.ok)throw new Error(d.message||"上传失败");await loadList();await openPaper(d.id)}catch(e){alert(e.message)}finally{q("#lit-file").value=""}}

async function openPaper(id){
 reset();
 const enc=encodeURIComponent(id);
 const [paper,annotations]=await Promise.all([
  api("/api/literature/"+enc),
  api("/api/literature/"+enc+"/annotations")
 ]);
 S.paper=paper;S.annotations=Array.isArray(annotations)?annotations:[];
 q("#lit-reader-empty").hidden=true;q("#lit-reader-live").hidden=false;side();loadList().catch(()=>{}) /* v260929 · 列表刷新仅更新徽章，不阻塞 PDF 加载 */;
 try{await ensurePdfJs();S.pdf=await window.pdfjsLib.getDocument({url:"/api/literature/"+enc+"/pdf",rangeChunkSize:4*1024*1024}).promise;S.current=Math.max(1,Math.min(S.pdf.numPages,+S.paper.last_page||1));await build();requestAnimationFrame(()=>go(S.current,false))}
 catch(e){q("#lit-pages").innerHTML='<div class="lit-empty">PDF 渲染失败：'+esc(e.message)+"</div>"}
}
function reset(){S.generation++;S.observer?.disconnect();S.pages.clear();S.pending=null;S.undo=[];S.area=false;S.pdf=null;S.selectedAnn=null;S.selectionOrigin=null;S.dragSel=null;S.areaResolver=null;S.annotations=[];S.ai={text:"",image:"",result:"",error:"",busy:false,instruction:""}} /* v260930e · areaResolver 一并复位 */
function annotationsForPage(page){return (S.annotations||[]).filter(a=>+a.page===+page)}
function annotationById(id){return (S.annotations||[]).find(a=>a.id===id)||null}
function upsertAnnotation(a){
 const i=S.annotations.findIndex(x=>x.id===a.id);
 if(i>=0)S.annotations[i]=a;else S.annotations.push(a);
 const r=S.pages.get(+a.page);
 if(r){
  const j=(r.annotations||[]).findIndex(x=>x.id===a.id);
  if(j>=0)r.annotations[j]=a;else r.annotations.push(a);
 }
}
function removeAnnotationLocal(id,page){
 S.annotations=S.annotations.filter(a=>a.id!==id);
 const r=S.pages.get(+page);
 if(r)r.annotations=(r.annotations||[]).filter(a=>a.id!==id);
}
async function build(){
 const host=q("#lit-pages");host.innerHTML="";S.pages.clear();const gen=S.generation;
 for(let n=1;n<=S.pdf.numPages;n++){
  const p=await S.pdf.getPage(n);if(gen!==S.generation)return;const vp=p.getViewport({scale:S.scale});
  const el=document.createElement("div");el.className="lit-page-shell";el.dataset.page=n;el.style.width=vp.width+"px";el.style.height=vp.height+"px";el.innerHTML='<div class="lit-page-placeholder">第 '+n+" 页</div>";host.appendChild(el);S.pages.set(n,{el,rendered:false,rendering:false,annotations:annotationsForPage(n)});
 }
 S.observer=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)renderPage(+e.target.dataset.page)}),{root:q("#lit-scroll"),rootMargin:"1000px 0px",threshold:.01});
 S.pages.forEach(r=>S.observer.observe(r.el));q("#lit-scroll").onscroll=throttle(track,100);toolbar();
}
async function renderPage(n){
 const r=S.pages.get(n);if(!r||r.rendered||r.rendering||!S.pdf)return;r.rendering=true;const gen=S.generation;
 try{
  const p=await S.pdf.getPage(n),vp=p.getViewport({scale:S.scale}),dpr=window.devicePixelRatio||1;if(gen!==S.generation)return;
  r.el.style.width=vp.width+"px";r.el.style.height=vp.height+"px";r.el.innerHTML='<div class="lit-page" data-page="'+n+'" style="width:'+vp.width+'px;height:'+vp.height+'px"><canvas></canvas><svg class="lit-annotation-layer" viewBox="0 0 1 1" preserveAspectRatio="none"></svg><div class="lit-selection-layer"></div><div class="lit-interaction-layer" title="拖动选择文字"></div></div>';
  const cv=q("canvas",r.el),ctx=cv.getContext("2d");cv.width=Math.floor(vp.width*dpr);cv.height=Math.floor(vp.height*dpr);cv.style.width=vp.width+"px";cv.style.height=vp.height+"px";
  await p.render({canvasContext:ctx,viewport:vp,transform:dpr===1?null:[dpr,0,0,dpr,0,0]}).promise;if(gen!==S.generation)return;
  const text=await p.getTextContent();
  r.textItems=buildPdfTextGeometry(text,vp);
  r.annotations=annotationsForPage(n);r.rendered=true;
  const pageEl=q(".lit-page",r.el),hit=q(".lit-interaction-layer",r.el);
  hit.onmousedown=e=>beginPdfGeometrySelection(n,e);
  hit.onclick=e=>handlePageAnnotationClick(n,e);
  paint(n);
 }catch(e){r.el.innerHTML='<div class="lit-page-error">第 '+n+" 页渲染失败："+esc(e.message)+"</div>"}finally{r.rendering=false}
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
  if(next){S.pending=next;paintPending();toolbar()}
 };
 const up=ev=>{
  document.removeEventListener("mousemove",move,true);document.removeEventListener("mouseup",up,true);
  const drag=S.dragSel;S.dragSel=null;if(!drag?.moved)return;
  const last=eventPointInPage(page,ev),next=buildSelectionFromPdfGeometry(n,start,last);
  if(next)S.pending=next;paintPending();toolbar();
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
}
function toggleArea(){
 S.area=!S.area;S.pending=null;paintPending();toolbar();
 qa(".lit-interaction-layer").forEach(el=>{el.onmousedown=S.area?areaStart:null});
 if(!S.area&&S.areaResolver){const rs=S.areaResolver;S.areaResolver=null;rs("")} /* v260930n · 取消框选时释放悬浮球等待中的截图 promise，避免永久悬挂 */
}
function areaStart(e){
 const page=e.target.closest(".lit-page");if(!page||!S.area)return;e.preventDefault();const n=+page.dataset.page,pr=page.getBoundingClientRect(),a=[clamp((e.clientX-pr.left)/pr.width),clamp((e.clientY-pr.top)/pr.height)];
 const move=ev=>{const b=[clamp((ev.clientX-pr.left)/pr.width),clamp((ev.clientY-pr.top)/pr.height)];S.pending={page:n,text:"区域选块",kind:"area",rects:[[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])]]};paintPending()};
 const up=()=>{document.removeEventListener("mousemove",move,true);document.removeEventListener("mouseup",up,true);S.area=false;qa(".lit-interaction-layer").forEach(el=>el.onmousedown=null);toolbar();const rs=S.areaResolver;S.areaResolver=null;if(rs){rs(areaPreviewDataUrl(S.pending))}else{openAiTabForArea()}}; /* v260930e · 框选完成：外部接管（悬浮球截图）优先于阅读区 AI 面板联动 */
 document.addEventListener("mousemove",move,true);document.addEventListener("mouseup",up,true); /* v260930n · 修复框选失效：move/up 此前定义后未挂载，拖动与松开无人监听，选区不出现 */
}
function openAiTabForArea(){ /* v260929d · 框选完成后联动：多模态开启时自动切到 AI 面板，「用框选区域」截图按钮立即出现 */
  const vis=window.ERWVisionEnabled?window.ERWVisionEnabled():false;if(!vis)return;
  const aiBtn=qa('[data-tab]').find(b=>b.dataset.tab==="ai");if(!aiBtn)return;
  S.selectedAnn=null;qa('[data-tab]').forEach(x=>x.classList.toggle("active",x===aiBtn));sideTab("ai");
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
function track(){const sc=q("#lit-scroll"),y=sc.getBoundingClientRect().top+70;let best=1,d=Infinity;S.pages.forEach((r,n)=>{const z=Math.abs(r.el.getBoundingClientRect().top-y);if(z<d){d=z;best=n}});if(best===S.current)return;S.current=best;toolbar();dispatchPage();clearTimeout(track.t);track.t=setTimeout(()=>savePos(best),400)} /* v260930d · M5 翻页派发事件供悬浮球刷新关联知识 */
async function savePos(page){if(!S.paper||!S.pdf)return;const st=S.paper.reading_status==="未读"?"在读":S.paper.reading_status;S.paper.last_page=page;S.paper.reading_status=st;try{await api("/api/literature/"+S.paper.id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({last_page:page,page_count:S.pdf.numPages,reading_status:st})})}catch{}}
function dispatchPage(){document.dispatchEvent(new CustomEvent("erw-lit-page",{detail:{page:S.current}}))} /* v260930d · M5 翻页事件 */
function go(n,smooth=true){
 const rec=S.pages.get(n),sc=q("#lit-scroll");if(!rec||!sc)return;
 const top=Math.max(0,rec.el.offsetTop-8);
 sc.scrollTo({top,behavior:smooth?"smooth":"auto"});S.current=n;toolbar();dispatchPage();
}
async function zoom(delta){if(!S.pdf)return;const keep=S.current;S.scale=Math.max(.65,Math.min(2.4,S.scale+delta));S.generation++;S.observer?.disconnect();await build();requestAnimationFrame(()=>go(keep,false))}
function toolbar(){if(!S.pdf)return;q("#lit-page-label").textContent=S.current+" / "+S.pdf.numPages;q("#lit-zoom-label").textContent=Math.round(S.scale*100)+"%";qa("[data-ann]").forEach(b=>{b.disabled=!S.pending;b.classList.toggle("ready",!!S.pending)});qa("[data-ai]").forEach(b=>{b.disabled=!(S.pending?.kind==="text"&&S.pending?.text);b.classList.toggle("ready",!!(S.pending?.kind==="text"&&S.pending?.text))});q("#lit-area").classList.toggle("active",S.area);q("#lit-area").textContent=S.area?"拖动选择区域…":"框选区域";q("#lit-undo").disabled=!S.undo.length;const cp=q("#lit-copy");if(cp)cp.disabled=!(S.pending?.kind==="text"&&S.pending?.text)}


async function openAnnotation(page,id){
 const a=annotationById(id);if(!a)return;
 S.selectedAnn={page:+page,id};
 qa("[data-tab]").forEach(x=>x.classList.toggle("active",x.dataset.tab==="annotations"));
 annList();
}
async function jumpToAnnotation(page,id){
 const r=S.pages.get(+page);if(!r)return;
 if(!r.rendered)await renderPage(+page);
 go(+page,true);
 const a=annotationById(id);
 if(a){S.selectedAnn={page:+page,id};qa("[data-tab]").forEach(x=>x.classList.toggle("active",x.dataset.tab==="annotations"));annList();}
}
async function saveAnnotationComment(){
 if(!S.selectedAnn)return;
 const page=+S.selectedAnn.page,id=S.selectedAnn.id;
 const a=annotationById(id);if(!a)return;
 const comment=q("#ann-comment")?.value||"";
 const saved=await api("/api/literature/"+S.paper.id+"/annotations",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...a,comment})});
 upsertAnnotation(saved);
 S.selectedAnn=null;
 paint(page);annList();go(page,true);
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
  const d=await api("/api/literature/"+S.paper.id+"/note");
  const cur=String(d.content||"");
  const tag="P."+a.page+(a.no?" · #"+a.no:"");
  let block="**批注 "+tag+"**\n";
  if(text)block+="> "+text.replace(/\r?\n/g,"\n> ")+"\n";
  if(withShot)block+="![批注 "+tag+" 截图]("+shotPath+")\n";
  if(comment)block+=comment+"\n";
  const next=cur.replace(/\s+$/,"")+(cur.trim()?"\n\n":"")+block;
  await api("/api/literature/"+S.paper.id+"/note",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:next})});
  if(btn){btn.textContent="已写入 ✓";setTimeout(()=>btn&&(btn.textContent="加入笔记"),1200)}
  loadList().catch(()=>{});
 }catch(e){if(btn){btn.textContent="失败";setTimeout(()=>btn&&(btn.textContent="加入笔记"),1500)}toast(e?.message||String(e),true)}
}
function side(){const p=S.paper;q("#lit-side").innerHTML='<div class="lit-side-tabs"><button class="active" data-tab="info">信息</button><button data-tab="annotations">批注</button><button data-tab="notes">笔记</button><button data-tab="ai" title="AI 翻译 / 总结 / 整理 / 笔记润色">AI</button></div><div id="lit-side-body"></div>';qa("[data-tab]").forEach(b=>b.onclick=()=>{if(b.dataset.tab!=="annotations")S.selectedAnn=null;qa("[data-tab]").forEach(x=>x.classList.toggle("active",x===b));sideTab(b.dataset.tab)});sideTab("info")}
function sideTab(tab){
 const root=q("#lit-side-body"),p=S.paper;
 if(tab==="info"){root.innerHTML='<div class="lit-info"><label>题名<input id="li-title" value="'+esc(p.title)+'"></label><label>作者<input id="li-authors" value="'+esc(p.authors||"")+'"></label><div class="lit-two"><label>年份<input id="li-year" value="'+esc(p.year||"")+'"></label><label>阅读状态<select id="li-status"><option '+(p.reading_status==="未读"?"selected":"")+'>未读</option><option '+(p.reading_status==="在读"?"selected":"")+'>在读</option><option '+(p.reading_status==="已读"?"selected":"")+'>已读</option></select></label></div><label class="lit-marks-label">分类标记</label><div class="mark-chip-box" id="li-marks"></div><label class="lit-marks-label">标签</label><div class="project-picker-row"><div class="project-chip-box" id="li-tags"></div><button type="button" class="secondary-btn project-add-btn" id="li-tag-add" title="添加标签：可勾选已有或输入新标签">＋</button></div><label>期刊 / 会议<input id="li-venue" value="'+esc(p.venue||"")+'"></label><div class="lit-two"><label>DOI<input id="li-doi" value="'+esc(p.doi||"")+'"></label><label>Cite Key<input id="li-cite" value="'+esc(p.cite_key||"")+'"></label></div><label class="lit-favorite"><input type="checkbox" id="li-favorite" '+(p.favorite?"checked":"")+'> 收藏此文献</label><button class="primary-btn" id="li-save">保存信息</button></div>';q("#li-save").onclick=saveInfo;renderLiMarks();paintLiTags(p.tags||[])}
 else if(tab==="annotations")annList();else if(tab==="ai")aiPanel();else note();
}
/* v260929 · PDF 阅读区 AI 助手：选中文本 → 翻译/总结/整理/自定义指令，结果可追加/替换到文献笔记（条目正文同源） */
function switchTab(tab){qa("[data-tab]").forEach(x=>x.classList.toggle("active",x.dataset.tab===tab))}
function aiFromSelection(action){if(!(S.pending?.kind==="text"&&S.pending?.text))return;switchTab("ai");runAssist(action,"")}
const AI_LABELS={translate:"AI 翻译中…",summarize:"AI 总结中…",organize:"AI 整理中…",polish:"AI 润色笔记中…",custom:"AI 处理中…"};
async function runAssist(action,instruction,label){ /* v260929b · label：按钮文字，自定义动作据此显示「AI xxx中…」；v260929c · image：截图代替/伴随文本 */
 if(S.ai.busy)return;
 const fresh=S.pending?.kind==="text"?String(S.pending.text||""):"";
 const src=fresh||S.ai.text||"";
 const img=S.ai.image||"";
 if(!src&&!img){S.ai={...S.ai,text:"",result:"",busy:false,error:"没有可处理的内容：请先在 PDF 中选中文字、截取页面/框选区域，或在「笔记」页用 AI 整理已有笔记。"};aiPanel();return}
 S.ai={...S.ai,text:src,instruction:action==="custom"?(instruction||S.ai.instruction):"",result:"",error:"",busy:true,busyLabel:AI_LABELS[action]||(label?"AI "+label+"中…":"AI 处理中…")};aiPanel();
 try{const d=await api("/api/agent/assist",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,text:src,instruction:action==="custom"?(instruction||S.ai.instruction):"",...(img?{image:img}:{})})});S.ai={...S.ai,result:String(d.content||""),error:"",busy:false}}
 catch(e){S.ai={...S.ai,error:String(e?.message||e),result:"",busy:false}}
 aiPanel();
}
function mdLite(s){ /* 结果区轻量 Markdown 渲染：标题/列表/粗体/行内代码/代码块（已先转义，安全） */
 const lines=String(s||"").split(/\r?\n/);let out="",inList=false,inCode=false;
 const inline=t=>t.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`]+)`/g,"<code>$1</code>");
 for(const raw of lines){
  const t=raw.trimEnd();
  if(t.trim().startsWith("```")){if(inList){out+="</ul>";inList=false}out+=inCode?"</code></pre>":"<pre><code>";inCode=!inCode;continue}
  if(inCode){out+=raw+"\n";continue}
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
 const root=q("#lit-side-body");if(!root)return;const a=S.ai;
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
async function noteApply(mode){ /* AI 结果写入文献笔记（= 条目 md 正文）：append 追加 / replace 整体替换 */
 if(!S.paper||!S.ai.result)return;
 const btn=q(mode==="replace"?"#lit-ai-replace":"#lit-ai-append");if(btn){btn.disabled=true;btn.textContent="写入中…"}
 try{
  const d=await api("/api/literature/"+S.paper.id+"/note");
  const cur=String(d.content||"");
  const next=mode==="replace"?S.ai.result:cur.replace(/\s+$/,"")+(cur.trim()?"\n\n":"")+S.ai.result+"\n";
  await api("/api/literature/"+S.paper.id+"/note",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:next})});
  if(btn){btn.textContent="已写入 ✓";setTimeout(()=>btn&&(btn.textContent=mode==="replace"?"替换笔记":"追加到笔记"),1200)}
  loadList().catch(()=>{});
 }catch(e){if(btn){btn.textContent="失败";setTimeout(()=>btn&&(btn.textContent=mode==="replace"?"替换笔记":"追加到笔记"),1500)}alert(e?.message||e)}
}
async function saveInfo(){const p={title:q("#li-title").value,authors:q("#li-authors").value,year:q("#li-year").value,reading_status:q("#li-status").value,tags:liTags(),venue:q("#li-venue").value,doi:q("#li-doi").value,cite_key:q("#li-cite").value,favorite:q("#li-favorite").checked,kind_marks:qa("#li-marks .mark-chip.on").map(b=>b.dataset.mark)};S.paper=await api("/api/literature/"+S.paper.id,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)});await loadList()}
/* v260929 · 阅读区信息栏「分类标记」chips：与编辑区同款渲染（复用 app.js 的 ERWMarkChips），保存时随 saveInfo 写回条目 md */
function renderLiMarks(){
 const box=q("#li-marks"); if(!box||!window.ERWMarkChips)return;
 const on=qa("#li-marks .mark-chip.on").map(b=>b.dataset.mark);
 const saved=(S.paper&&S.paper.kind_marks)||[];
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
 box.innerHTML=list.length?list.map((t,i)=>'<span class="project-chip tag-chip">'+esc(t)+'<button type="button" data-tag-remove="'+i+'" title="移除标签">×</button></span>').join(""):'<span class="row-meta">暂无标签</span>';
 qa("[data-tag-remove]",box).forEach(b=>b.onclick=()=>{const now=liTags();now.splice(+b.dataset.tagRemove,1);paintLiTags(now)});
 const add=q("#li-tag-add");
 if(add)add.onclick=()=>{if(window.ERWTagPicker)window.ERWTagPicker(liTags(),()=>[...new Set(S.items.flatMap(x=>x.tags||[]))],paintLiTags)};
}
/* v260929g · 列表按编号排序：编号即创建（截图）顺序，跨页也按全局编号排列；缺号旧数据排末尾 */
function loadedAnns(){return [...(S.annotations||[])].sort((a,b)=>((a.no||Number.MAX_SAFE_INTEGER)-(b.no||Number.MAX_SAFE_INTEGER))||String(a.created_at||"").localeCompare(String(b.created_at||"")))}
function annList(){
 const root=q("#lit-side-body");if(!root||!q('[data-tab="annotations"]')?.classList.contains("active"))return;
 if(S.selectedAnn&&!annotationById(S.selectedAnn.id))S.selectedAnn=null;
 const editId=S.selectedAnn?.id;
 const rows=loadedAnns();
 /* v260929g · 选中批注原地展开为编辑卡片（不抽到顶部，位置不随选中改变） */
 const card=a=>{
  if(a.id!==editId)return '<article class="lit-ann" data-open-ann="'+a.id+'" data-page="'+a.page+'"><div><strong>P.'+a.page+(a.no?" · #"+a.no:"")+" · "+esc(a.type)+'</strong><button data-del="'+a.id+'" data-page="'+a.page+'">×</button></div>'+annotationExcerpt(a,true)+(a.comment?"<p>"+esc(a.comment)+"</p>":"")+"</article>";
  return '<section class="lit-ann lit-ann-editor"><div class="lit-ann-editor-head"><strong>P.'+a.page+(a.no?' · #'+a.no:'')+' · '+esc(a.type)+'</strong><button id="ann-editor-close" title="收起">×</button></div>'+annotationExcerpt(a,false)+'<label>批注<textarea id="ann-comment" placeholder="为这个标记添加批注…">'+esc(a.comment||"")+'</textarea></label><div class="lit-ann-editor-actions"><button class="primary-btn" id="ann-comment-save">保存批注</button><button class="secondary-btn" id="ann-to-note" title="把批注摘录与意见写入笔记（条目正文）末尾'+(a.preview_path?'，可附带截图':'')+'">加入笔记</button>'+(a.preview_path?'<label class="lit-ann-shot-check" title="勾选后随批注内容一并写入笔记的 Markdown 图片引用"><input type="checkbox" id="ann-with-shot" checked> 附带截图</label>':'')+'</div></section>';
 };
 root.innerHTML='<div class="lit-ann-list">'+(rows.length?rows.map(card).join(""):'<div class="lit-empty">当前已加载页面暂无批注</div>')+"</div>";
 if(q("#ann-comment-save"))q("#ann-comment-save").onclick=saveAnnotationComment;
 if(q("#ann-to-note"))q("#ann-to-note").onclick=annToNote; /* v260929f · 批注内容（可含截图）写入笔记 */
 if(q("#ann-editor-close"))q("#ann-editor-close").onclick=()=>{S.selectedAnn=null;annList()};
 qa("[data-open-ann]").forEach(x=>x.onclick=e=>{if(e.target.closest("[data-del]"))return;jumpToAnnotation(+x.dataset.page,x.dataset.openAnn)});
 qa("[data-del]").forEach(b=>b.onclick=async()=>{const page=+b.dataset.page;await api("/api/literature/"+S.paper.id+"/annotations/"+b.dataset.del,{method:"DELETE"});removeAnnotationLocal(b.dataset.del,page);paint(page);if(S.selectedAnn?.id===b.dataset.del)S.selectedAnn=null;annList()});
}
/* v260929f · 笔记插图：选本地图片 → 落盘笔记图片目录 → 光标处插入 Markdown 图片引用（路径口径与附件一致） */
function insertAtCursor(ta,text){if(!ta)return;const s=ta.selectionStart??ta.value.length,e=ta.selectionEnd??s;ta.value=ta.value.slice(0,s)+text+ta.value.slice(e);const p=s+text.length;ta.focus();ta.setSelectionRange(p,p)}
async function uploadNoteImage(file){
 const dataUrl=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result));r.onerror=()=>rej(new Error("读取图片失败"));r.readAsDataURL(file)});
 return api("/api/literature/note-image",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({paper_id:S.paper.id,data_url:dataUrl})});
}
async function note(){const root=q("#lit-side-body"),d=await api("/api/literature/"+S.paper.id+"/note");root.innerHTML='<textarea class="lit-note" id="lit-note" placeholder="Markdown 文献笔记…（与知识库条目正文同源，文献编辑器里看到的是同一份）">'+esc(d.content||"")+'</textarea><div class="lit-note-actions"><span>与知识库条目正文同源 · Ctrl+S 保存</span><span style="display:flex;gap:6px"><button type="button" class="secondary-btn" id="lit-note-img" title="上传图片到笔记图片目录，并在光标处插入 Markdown 图片引用">插入图片</button><input type="file" id="lit-note-img-file" accept="image/png,image/jpeg,image/webp" hidden><button type="button" class="secondary-btn" id="lit-note-ai" title="把当前笔记交给 AI 整理润色，结果在 AI 面板确认后写入">AI 整理</button><button class="primary-btn" id="lit-note-save">保存笔记</button></span></div>';q("#lit-note-save").onclick=saveNote;
 const imgBtn=q("#lit-note-img"),imgFile=q("#lit-note-img-file");
 if(imgBtn&&imgFile){imgBtn.onclick=()=>imgFile.click();imgFile.onchange=async()=>{const f=imgFile.files&&imgFile.files[0];imgFile.value="";if(!f)return;imgBtn.disabled=true;const old=imgBtn.textContent;imgBtn.textContent="上传中…";try{const r=await uploadNoteImage(f);insertAtCursor(q("#lit-note"),"!["+(r.filename||"图片")+"]("+(r.path||"")+")")}catch(e){toast(e?.message||String(e),true)}finally{imgBtn.disabled=false;imgBtn.textContent=old}}}
 q("#lit-note-ai").onclick=()=>{const t=q("#lit-note").value.trim();if(!t){S.ai={...S.ai,text:"",result:"",error:"笔记为空：先写点内容，或回到 PDF 选中段落用「AI 整理」生成。",busy:false};switchTab("ai");aiPanel();return}S.ai={...S.ai,text:t,instruction:"",result:"",error:"",busy:false};switchTab("ai");runAssist("polish","")}}
async function saveNote(){await api("/api/literature/"+S.paper.id+"/note",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content:q("#lit-note").value})});loadList().catch(()=>{}) /* v260929 · 保存后刷新左栏（摘要取自同一份正文） */}
function throttle(fn,ms){let wait=false;return(...a)=>{if(wait)return;wait=true;fn(...a);setTimeout(()=>wait=false,ms)}}

async function start(){shell();await loadList()}
/* v260929 · 由文献条目附件徽章进入：按 attachment 路径尾段匹配库内 PDF 文件名（stored_filename 唯一），
   命中则进工作区并直接打开该论文；未登记（如手动填写附件路径的旧条目）抛错，由调用方退回新窗口直开 */
async function openByAttachment(att){
 const name=String(att||"").split(/[\\/]/).pop().trim();
 if(!name)throw new Error("无附件路径");
 const d=await api("/api/literature?page_size=200");
 const hit=(d.items||[]).find(x=>String(x.stored_filename||"")===name);
 if(!hit)throw new Error("该附件未登记到 PDF 工作区");
 await start();await openPaper(hit.id);
}
window.ERWLiterature={start,openByAttachment,context:()=>({paper_id:S.paper?.id||"",title:S.paper?.title||"",page:S.current||1,selection:S.pending?.kind==="text"?String(S.pending.text||""):"",page_text:pageText(S.current||1)})}; /* v260930 · M2 悬浮球上下文桥：当前文献/页码/PDF 选中文本；v260930c · M4 增加当前页文本层正文（术语提取输入） */
/* v260930e · 悬浮球截图桥：page()=截当前整页；area()=进入框选模式，resolve 框选区域截图（外部接管联动） */
window.ERWCapture={
 page:()=>S.pdf?pageDataUrl():"",
 area:()=>new Promise(res=>{
   if(!S.pdf||!q(".lit-shell")){res("");return}
   S.areaResolver=res;
   if(!S.area)toggleArea();
 }),
};

function pageText(n){ /* v260930c · M4 · 取渲染页缓存的文本几何拼正文：textItems 为内容流顺序，术语提取够用；未渲染页返回空 */
 const r=S.pages.get(+n);if(!r||!Array.isArray(r.textItems))return "";
 return r.textItems.map(i=>i.text).join(" ").replace(/\s+/g," ").trim().slice(0,6000);
}
document.addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"&&q("#lit-note")){e.preventDefault();saveNote()}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="c"&&S.pending?.kind==="text"&&!/input|textarea/i.test(document.activeElement?.tagName||"")){e.preventDefault();copyPendingText()}else if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="z"&&S.paper&&!/input|textarea/i.test(document.activeElement?.tagName||"")){e.preventDefault();undo()}else if(e.key==="Escape"&&(S.pending||S.area)){S.pending=null;paintPending();if(S.area)toggleArea();else toolbar()} /* v260930n · Esc 退出框选态并释放悬挂 promise */});
})();