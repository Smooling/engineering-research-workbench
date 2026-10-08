/* v260930 · M2 悬浮球全局助手：全局常驻对话面板 + 页面上下文自动注入 + 划词气泡 + 工具草稿确认。
   依赖 M1 后端：/api/agent/send 的 context 参数、/api/agent/drafts/<id>/confirm|reject、assistant 消息的 tool_trace/drafts 字段。
   独立 IIFE，不侵入 app.js / literature.js；文献上下文经 window.ERWLiterature.context() 桥获取。 */
(()=>{
"use strict";
const q=(s,r=document)=>r.querySelector(s), qa=(s,r=document)=>Array.from(r.querySelectorAll(s));
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const S={
  open:false, session:null, messages:[], sending:false,
  bubbleSel:"",      /* 划词气泡捕获的选中内容（优先于发送时的实时 DOM 选中） */
  writeDirect:false, /* true=写工具直接落盘；false=出草稿待确认（默认） */
  draftState:{},     /* draft_id -> {status, result} 本地面板内状态 */
  personaId:localStorage.getItem("fabPersona")||(window.__FAB_DEFAULT_PERSONA__||"executor"), /* v260930g · 默认执行助手（含知识库写工具）；老用户尊重已存选择 */
  personas:null,     /* v260930 · M3 人设缓存（首次打开面板时拉取） */
  relatedCache:{},   /* v260930g9 · M5 关联匹配结果按文献缓存（paper_id → {page,items}）：每文献只匹配一次，切换/切回即时恢复 */
  relatedItems:[],   /* v260930d · M5 当前关联/检索条目缓存 */
  relatedOpen:null,  /* v260930d · M5 展开的卡片下标 */
  images:[],         /* v260930e · 待发送截图（dataURL，发送时才上传落盘） */
  view:"chat",       /* v260930e · 面板视图：chat 对话 / history 历史回看 */
  quote:null,        /* v260930j · 引用的历史对话 {id,title,text,count}，发送时随 context 注入，手动×移除 */
  relatedCollapsed:localStorage.getItem("fabRelatedCollapsed")==="1", /* v260930g8 · 关联知识区折叠态（持久化） */
};

async function api(url,opts={}){
  const init={...opts,headers:{"Content-Type":"application/json",...(opts.headers||{})}};
  if(init.body&&typeof init.body!=="string")init.body=JSON.stringify(init.body);
  const r=await fetch(url,init);let d={};try{d=await r.json()}catch{}
  if(!r.ok)throw new Error(d.message||d.error||("HTTP "+r.status));
  return d;
}

/* ---------- 上下文采集 ---------- */
const ROUTE_LABELS={overview:"概览",todos:"待办",focus:"专注",agent:"Agent 对话",news:"资讯","research-overview":"研究 · 知识总览",ideas:"灵感",journals:"研究日志",notes:"笔记",milestones:"里程碑",summaries:"工作总结",literature:"文献",graph:"知识图谱",folders:"文件夹",settings:"设置"};

function litContext(){
  /* PDF 阅读工作区激活时（.lit-shell 存在）取当前文献/页码/选中 */
  if(!q(".lit-shell")||!window.ERWLiterature?.context)return null;
  try{const c=window.ERWLiterature.context();return c&&c.paper_id?c:null}catch{return null}
}
function routeName(){return (location.hash||"").replace(/^#/,"")||"overview"}
function domSelection(){
  const sel=window.getSelection?.();
  if(!sel||sel.isCollapsed)return "";
  const txt=String(sel.toString()||"").trim();
  if(!txt||txt.length<2||txt.length>6000)return "";
  /* 排除面板自身与输入控件内的选中 */
  const node=sel.anchorNode;
  const el=node&&(node.nodeType===3?node.parentElement:node);
  if(!el)return "";
  if(el.closest("#erw-fab-panel,#erw-sel-bubble,input,textarea"))return "";
  return txt;
}
function docIdContext(){
  const el=q("#main .doc-item.active,[data-doc-id].active");
  return el?.dataset?.docId||window.ERWCurrentDoc||"";
}
function buildContext(){
  const ctx={view:ROUTE_LABELS[routeName()]||routeName(),write_mode:S.writeDirect?"direct":"confirm"};
  const lit=litContext();
  if(lit){ctx.paper_id=lit.paper_id;if(lit.page)ctx.page=lit.page;if(lit.page_text)ctx.page_text=lit.page_text} /* v260930c · M4 · 附带当前页文本层正文（术语提取输入） */
  const docId=docIdContext();
  if(docId)ctx.doc_id=docId;
  const sel=S.bubbleSel||domSelection()||(lit?.selection||"");
  if(sel)ctx.selection=sel;
  if(S.quote)ctx.quote_text=S.quote.text; /* v260930j · 引用的历史对话随消息注入 */
  return ctx;
}

/* ---------- 骨架 DOM ---------- */
function mount(){
  if(q("#erw-fab-ball"))return;
  const ball=document.createElement("button");
  ball.id="erw-fab-ball";ball.type="button";ball.title="AI 助手";
  ball.innerHTML='<span class="fab-pulse"></span>◉';
  ball.onclick=openPanel;
  restoreBallPos(ball); /* v260930f · 恢复上次拖拽位置 */
  initBallDrag(ball);   /* v260930f · 拖拽移动（阈值内视为点击） */
  document.body.appendChild(ball);

  const panel=document.createElement("section");
  panel.id="erw-fab-panel";panel.hidden=true;
  panel.innerHTML=`
    <div class="fab-resize" id="fab-resize" title="拖拽调整面板大小"></div><!-- v260930g7 · 左上角拖拽手柄（面板锚定右下） -->
    <div class="fab-head">
      <div class="fab-logo">◉</div>
      <div><strong>AI 助手</strong><div class="fab-sub">可检索知识库 · 建档 · 写文献笔记</div></div>
      <div class="fab-head-actions">
        <select id="fab-persona" class="search-input" title="切换 AI 人设（角色 × 工具权限 × 写入模式）" style="font-size:11px;padding:3px 6px;max-width:120px"></select>
        <button type="button" id="fab-history" title="历史对话回看">🕘</button><!-- v260930e -->
        <button type="button" id="fab-new" title="新建对话">＋</button>
        <button type="button" id="fab-close" title="收起">×</button>
      </div>
    </div>
    <div class="fab-context" id="fab-context"></div>
    <div id="fab-related"></div><!-- v260930d · M5 本页关联知识 / 检索结果宿主 -->
    <div class="fab-messages" id="fab-messages"></div>
    <div class="fab-foot">
      <div id="fab-quote"></div><!-- v260930j · 引用历史对话条 -->
      <div class="fab-attach" id="fab-attach"></div><!-- v260930e · 待发送截图预览 -->
      <div class="fab-foot-top">
        <div class="fab-shot-btns">
          <button type="button" id="fab-shot-page" title="截取当前 PDF 整页发给 AI（多模态）">📷 截当前页</button>
          <button type="button" id="fab-shot-area" title="框选 PDF 区域截图发给 AI：点击后收起面板，在页面上拖拽框选">⬚ 框选截图</button>
        </div><!-- v260930e · 截图入口（文献页可用） -->
        <label class="fab-write-toggle" title="关闭后，Agent 写知识库/笔记只生成草稿，由你确认后落盘">
          <input type="checkbox" id="fab-write-direct"> 写工具直接落盘
        </label>
        <span id="fab-mode-hint">默认：写入需确认</span>
      </div>
      <div class="fab-compose">
        <textarea id="fab-input" rows="1" placeholder="提问，或让 AI 检索知识库 / 建档 / 写文献笔记…"></textarea>
        <button type="button" id="fab-send">发送</button>
      </div>
    </div>`;
  document.body.appendChild(panel);

  const bubble=document.createElement("div");
  bubble.id="erw-sel-bubble";
  bubble.innerHTML=`
    <button type="button" data-fab-act="explain"><b>解释</b></button>
    <button type="button" data-fab-act="summarize"><b>总结</b></button>
    <button type="button" data-fab-act="save"><b>存知识库</b></button>
    <button type="button" data-fab-act="kb" title="即时检索知识库中与选中内容相关的条目（不经 AI）"><b>查知识库</b></button>
    <button type="button" data-fab-act="ask">问 AI…</button>`;
  document.body.appendChild(bubble);

  initPanelResize(); /* v260930g7 · 左上角手柄拖拽调尺寸 */
  initPanelDrag(); /* v260930j3 · 头部拖动移动面板（展开后不再固定右下角） */
  q("#fab-close").onclick=closePanel;
  q("#fab-persona").onchange=e=>switchPersona(e.target.value);
  /* v260930e · 历史回看：切换面板视图（对话 ⇄ 历史列表） */
  q("#fab-history").onclick=()=>{S.view=S.view==="chat"?"history":"chat";paintView()};
  /* v260930e · 截图：当前整页立即截；框选则收起面板等用户框完再回 */
  q("#fab-shot-page").onclick=()=>{const d=window.ERWCapture?.page();if(!d){toastInPanel("仅文献阅读页可截当前页",true);return}attachImage(d)};
  q("#fab-shot-area").onclick=async()=>{
    if(!q(".lit-shell")){toastInPanel("仅文献阅读页可框选截图",true);return}
    closePanel();
    const d=await window.ERWCapture.area();
    if(d){attachImage(d);openPanel();toastInPanel("已附加框选截图")}
    else{openPanel();toastInPanel("框选已取消或未截到区域",true)}
  };
  q("#fab-new").onclick=async()=>{try{const s=await api("/api/agent/sessions",{method:"POST",body:{}});S.session=s.id;S.messages=[];S.draftState={};S.view="chat";paintView();paintContext();toastInPanel("已新建对话")}catch(e){toastInPanel(e.message,true)}};
  q("#fab-send").onclick=()=>{ /* v260930l · 发送中再点=停止生成（abort 流式请求，后端随之中止） */
    if(S.sending){S.abortCtl?.abort();return}
    send();
  };
  const input=q("#fab-input");
  input.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();send()}});
  input.addEventListener("input",()=>{input.style.height="auto";input.style.height=Math.min(120,input.scrollHeight)+"px"});
  const wd=q("#fab-write-direct");
  wd.onchange=()=>{S.writeDirect=wd.checked;q("#fab-mode-hint").textContent=wd.checked?"直接落盘已开启（谨慎）":"默认：写入需确认"};
  qa("[data-fab-act]",bubble).forEach(b=>b.onclick=()=>bubbleAct(b.dataset.fabAct));
  document.addEventListener("mousedown",onDocMouseDown,false);
  document.addEventListener("mouseup",onDocMouseUp,false);
  window.addEventListener("hashchange",()=>{if(S.open){paintContext();ensureRelated()}}); /* v260930g9b · 切页同步刷新关联区：离开阅读工作区即清空，防止残留「没在阅读的文献」的关联 */
  window.addEventListener("erw-lit-back",()=>{if(S.open)ensureRelated()}); /* v260930g9b · 返回文献列表同样清空（事件派发在 window；同 hash 不触发 hashchange） */
  document.addEventListener("erw-lit-page",()=>{ /* v260930d · M5 翻页刷新关联知识（literature.js track/go 派发） */
    paintContext();
    if(S.open)ensureRelated(true);
  });
  window.addEventListener("scroll",hideBubble,{passive:true,capture:true});
}

/* ---------- 悬浮球拖拽移动（v260930f）：Pointer Events 拖拽，位移 <5px 视为点击；位置持久化 localStorage ---------- */
function clampBallPos(x,y){
  const w=52,h=52; /* 球固定尺寸，与 CSS 一致 */
  return [Math.max(6,Math.min(x,window.innerWidth-w-6)),Math.max(6,Math.min(y,window.innerHeight-h-6))];
}
function restoreBallPos(ball){
  try{
    const p=JSON.parse(localStorage.getItem("fabBallPos")||"null");
    if(!p||!isFinite(p.x)||!isFinite(p.y))return;
    const [x,y]=clampBallPos(p.x,p.y);
    ball.style.left=x+"px";ball.style.top=y+"px";
    ball.style.right="auto";ball.style.bottom="auto";
  }catch{}
}
function initBallDrag(ball){
  let drag=false,moved=false,sx=0,sy=0,ox=0,oy=0;
  ball.addEventListener("pointerdown",e=>{
    if(e.button!==0)return;
    const r=ball.getBoundingClientRect();
    drag=true;moved=false;sx=e.clientX;sy=e.clientY;ox=r.left;oy=r.top;
    try{ball.setPointerCapture(e.pointerId)}catch{}
  });
  ball.addEventListener("pointermove",e=>{
    if(!drag)return;
    const dx=e.clientX-sx,dy=e.clientY-sy;
    if(!moved&&Math.hypot(dx,dy)<5)return; /* 小于阈值不动，保证正常点击 */
    moved=true;ball.classList.add("dragging");
    const [x,y]=clampBallPos(e.clientX-sx+ox,e.clientY-sy+oy);
    ball.style.left=x+"px";ball.style.top=y+"px";
    ball.style.right="auto";ball.style.bottom="auto";
  });
  const finish=()=>{
    if(!drag)return;drag=false;ball.classList.remove("dragging");
    if(!moved)return;
    localStorage.setItem("fabBallPos",JSON.stringify({x:parseFloat(ball.style.left),y:parseFloat(ball.style.top)}));
    /* 拖拽后吞掉紧随的 click，避免误开面板 */
    ball.addEventListener("click",ev=>{ev.stopPropagation();ev.preventDefault()},{capture:true,once:true});
  };
  ball.addEventListener("pointerup",finish);
  ball.addEventListener("pointercancel",()=>{drag=false;moved=false;ball.classList.remove("dragging")});
}

function toastInPanel(msg,isErr){
  const el=document.createElement("div");
  el.style.cssText="font-size:11px;padding:4px 8px;border-radius:7px;"+(isErr?"color:#b3392f;background:#fdecea;":"color:var(--accent-ink);background:var(--accent-soft);");
  el.textContent=msg;
  const box=q("#fab-messages");if(box){box.appendChild(el);box.scrollTop=box.scrollHeight;setTimeout(()=>el.remove(),2600)}
}

/* ---------- 面板开关与上下文条 ---------- */
/* ---------- 本页关联知识（M5）：页面正文 × 知识库条目纯文本匹配，翻页自动刷新 ---------- */
const MARK_GLYPHS={architecture:"▤",method:"⚒",model:"⬡",principle:"∑",experiment:"⚗",data:"⊞",knowledge:"◈",synthesis:"◎"}; /* v260930d · 类别标记符号（对齐命名规范 kind_marks） */
async function ensureRelated(force){
  const lit=litContext();
  const root=q("#fab-related");if(!root)return;
  if(!lit||!lit.paper_id){root.innerHTML="";return} /* 非阅读页：清空 */
  const page=lit.page||0,key=String(lit.paper_id),text=lit.page_text||"";
  const cached=S.relatedCache[key];
  if(!force&&cached&&cached.page===page){paintRelated(cached.items,{mode:"related"});return} /* v260930g9 · 同文献同页：缓存直显，切回文献即恢复 */
  if(!text)return; /* v260930g9 · 正文未就绪：保留现有显示，等 erw-lit-page 事件再刷（修复切换文献时闪没） */
  try{
    const r=await api("/api/kb/related",{method:"POST",body:{page_text:text}});
    const now=litContext();
    if(!now||String(now.paper_id)!==key||(now.page||0)!==page)return; /* 竞态防护：已切走则丢弃过期结果 */
    S.relatedCache[key]={page,items:r.items||[]}; /* 会话内每文献只匹配一次 */
    paintRelated(r.items||[],{mode:"related"});
  }catch{/* 匹配失败静默：不影响对话主功能 */}
}
function relatedCardHtml(d){
  const marks=(d.kind_marks||[]).map(m=>MARK_GLYPHS[m]||"◈").join("");
  const hits=(d.hits||[]).map(h=>`<mark>${esc(h)}</mark>`).join("、");
  return `<div class="fab-rel-card" data-rel-card="${esc(d.id)}">
    <div class="fab-rel-head"><span class="fab-rel-title" title="${esc(d.title)}">${esc(d.title||d.id)}</span><span class="fab-rel-marks">${marks}</span></div>
    ${hits?`<div class="fab-rel-hits">命中：${hits}</div>`:""}
    <div class="fab-rel-excerpt">${esc(d.excerpt||"（无摘要）")}</div>
    <div class="fab-rel-actions">
      <button type="button" class="go" data-rel-open="${esc(d.id)}" data-rel-kind="${esc(d.kind||"note")}">打开条目</button>
      <button type="button" data-rel-ask="${esc(d.title||d.id)}">问 AI 关联</button>
    </div>
  </div>`;
}
function paintRelated(items,{mode}={}){
  const root=q("#fab-related");if(!root)return;
  S.relatedItems=items||[];S.relatedMode=mode||"related";S.relatedOpen=null;
  if(!S.relatedItems.length){root.innerHTML="";return}
  const label=mode==="search"?"知识库检索结果":"本页关联知识";
  /* v260930g9d · 按条目类型分区：知识点（note）/ 来源文献（literature）常显，其余默认折叠——梳理知识不被日志杂音干扰 */
  /* v260930g9e · 类型配色：知识点蓝 / 来源文献紫 / 其他灰——颜色即类型，扫一眼可分 */
  const KIND_TONE={note:"note",literature:"lit"};
  const chipHtml=(d,i)=>`<button type="button" class="fab-rel-chip${KIND_TONE[d.kind]?" fab-rel-chip-"+KIND_TONE[d.kind]:""}" data-rel-idx="${i}" title="${esc(d.title)}">${esc((d.title||d.id).slice(0,14))}${(d.title||"").length>14?"…":""}</button>`;
  const groups=[["知识点","note",["note"]],["来源文献","lit",["literature"]],["其他","",["journal","idea","milestone","summary"]]];
  const bodyHtml=groups.map(([label,tone,kinds],gi)=>{
    const items=S.relatedItems.map((d,i)=>({d,i})).filter(x=>kinds.includes(x.d.kind||"note"));
    if(!items.length)return "";
    const fold=gi===2; /* 其他组默认折叠 */
    return `<div class="fab-rel-group"><button type="button" class="fab-rel-gcap${tone?" fab-rel-gcap-"+tone:""}"${fold?' data-gtoggle="1"':""}>${tone?`<span class="fab-rel-dot"></span>`:""}${label} · ${items.length}${fold?'<span class="fab-rel-gchev">▸</span>':""}</button><div class="fab-rel-chips"${fold?" hidden":""}>${items.map(x=>chipHtml(x.d,x.i)).join("")}</div></div>`;
  }).join("")||'<div class="fab-rel-empty">本页暂无关联条目</div>';
  root.innerHTML=`<div class="fab-related"><button type="button" class="fab-rel-cap" id="fab-rel-toggle" title="${S.relatedCollapsed?"展开":"收起"}">${label} <span class="fab-rel-count">${S.relatedItems.length}</span><span class="fab-rel-chev">${S.relatedCollapsed?"▸":"▾"}</span></button>
    <div id="fab-rel-body"${S.relatedCollapsed?" hidden":""}>
    ${bodyHtml}
    <div id="fab-rel-card-host"></div></div></div>`;
  /* v260930g8 · 标题行点击折叠/展开，状态持久化 */
  q("#fab-rel-toggle").onclick=()=>{
    S.relatedCollapsed=!S.relatedCollapsed;
    try{localStorage.setItem("fabRelatedCollapsed",S.relatedCollapsed?"1":"0")}catch{}
    const b=q("#fab-rel-body");if(b)b.hidden=S.relatedCollapsed;
    const c=q(".fab-rel-chev",root);if(c)c.textContent=S.relatedCollapsed?"▸":"▾";
  };
  const host=q("#fab-rel-card-host");
  const show=i=>{
    S.relatedOpen=i;
    host.innerHTML=relatedCardHtml(S.relatedItems[i]);
    q("[data-rel-open]",host).onclick=e=>window.ERWNav?.open(e.target.dataset.relKind,e.target.dataset.relOpen);
    q("[data-rel-ask]",host).onclick=e=>{
      const input=q("#fab-input");if(!input)return;
      input.value=`请结合知识条目《${e.target.dataset.relAsk}》解释它与当前页面内容的关联与应用。`;
      input.focus();input.dispatchEvent(new Event("input"));
    };
  };
  qa("[data-rel-idx]",root).forEach(b=>b.onclick=()=>{const i=+b.dataset.relIdx;host.innerHTML=S.relatedOpen===i?"":(show(i),"")});
  qa("[data-gtoggle]",root).forEach(b=>b.onclick=()=>{ /* v260930g9d · 「其他」组展开/收起 */
    const chips=b.nextElementSibling;if(!chips)return;
    chips.hidden=!chips.hidden;const ev=q(".fab-rel-gchev",b);if(ev)ev.textContent=chips.hidden?"▸":"▾";
  });
  if(S.relatedItems.length===1)show(0); /* 单条命中直接展开 */
}
/* ---------- 人设（M3） ---------- */
const TOOL_LABELS={kb_search:"检索知识库",kb_read:"读条目",kb_create_entry:"建档",kb_update_entry:"改条目",lit_context:"文献上下文",lit_note_write:"写文献笔记"};
async function ensurePersonas(force){
  if(S.personas&&!force)return S.personas;
  try{
    const cfg=await api("/api/config");
    const list=Array.isArray(cfg?.app?.llm?.personas)?cfg.app.llm.personas:[];
    S.personas=list.length?list:[{id:"reader",name:"阅读助手",write_mode:"confirm",tools:[]}];
  }catch{S.personas=S.personas||[{id:"reader",name:"阅读助手",write_mode:"confirm",tools:[]}]}
  return S.personas;
}
function currentPersona(){return (S.personas||[]).find(p=>p.id===S.personaId)||S.personas?.[0]||null}
/* v260930g · 写入能力保障：当前人设无写工具时，写类动作自动切到有写工具的人设（默认执行助手） */
const WRITE_TOOLS=["kb_create_entry","kb_update_entry","lit_note_write"];
function personaHasWrite(){
  const p=(S.personas||[]).find(x=>x.id===S.personaId);
  return !!p&&(p.tools||[]).some(t=>WRITE_TOOLS.includes(t));
}
async function ensureWritePersona(){
  await ensurePersonas();
  if(personaHasWrite()||!S.personas?.length)return;
  const target=S.personas.find(p=>p.id==="executor"&&(p.tools||[]).some(t=>WRITE_TOOLS.includes(t)))
    ||S.personas.find(p=>(p.tools||[]).some(t=>WRITE_TOOLS.includes(t)));
  if(!target)return;
  S.personaId=target.id;localStorage.setItem("fabPersona",S.personaId);
  paintPersonaSelect();
  toastInPanel(`当前人设无知识库写入工具，已切换到「${target.name}」`);
}
function paintPersonaSelect(){
  const sel=q("#fab-persona");if(!sel||!S.personas)return;
  sel.innerHTML=S.personas.map(p=>`<option value="${esc(p.id)}" ${p.id===S.personaId?"selected":""}>${esc(p.name)}</option>`).join("");
  syncWriteToggle();
  if(S.open)paintContext(); /* v260930g · 人设就绪/切换后刷新写入能力徽章 */
}
function switchPersona(id){
  S.personaId=id;localStorage.setItem("fabPersona",id);
  paintPersonaSelect(); /* v260930g · 同步写入开关与能力徽章 */
  const p=currentPersona();
  toastInPanel(p?`已切换人设：${p.name}（${p.write_mode==="direct"?"可直接写入":"写入需确认"}）`:"已切换人设");
}
function syncWriteToggle(){
  const wd=q("#fab-write-direct"),hint=q("#fab-mode-hint"),p=currentPersona();
  if(!wd||!hint)return;
  const locked=p&&p.write_mode!=="direct"; /* 人设为 confirm 时锁定开关：写入永远走草稿确认 */
  wd.disabled=locked;
  if(locked){wd.checked=false;S.writeDirect=false}
  else if(wd.checked!==S.writeDirect)wd.checked=S.writeDirect;
  hint.textContent=locked?"人设要求：写入需确认":(wd.checked?"直接落盘已开启（谨慎）":"默认：写入需确认");
}
async function openPanel(){
  S.open=true;const p=q("#erw-fab-panel");if(!p)return;
  p.hidden=false;q("#erw-fab-ball").style.display="none";
  applyPanelSize(); /* v260930g7 · 恢复上次手动调整的面板尺寸 */
  applyPanelPos(); /* v260930j3 · 恢复上次拖动的面板位置 */
  paintContext();
  ensureRelated(); /* v260930d · M5 打开面板即匹配本页关联知识（异步，不阻塞对话） */
  syncDraftStatuses(); /* v260930g9f · 打开面板即校准草稿真实状态（面板外确认的草稿不再误显待确认） */
  await ensurePersonas();
  paintPersonaSelect();
  if(!S.session){restoreSession().then(()=>{if(!S.messages.length)renderEmpty()})}
  else if(!S.messages.length)loadSession();
  setTimeout(()=>q("#fab-input")?.focus(),30);
}
function closePanel(){
  S.open=false;const p=q("#erw-fab-panel");if(p)p.hidden=true;
  const b=q("#erw-fab-ball");if(b)b.style.display="";
  hideBubble();
}
/* ---------- v260930g7 · 面板手动调尺寸：左上角手柄拖拽，宽高持久化 ---------- */
const FAB_SIZE_KEY="fabPanelSize";
const fabClamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
/* v261008b · 尺寸上下限随视口走：窗口很窄时上限会低于原下限，必须先夹住上限再夹值，否则面板顶出视口 */
const fabMaxW=()=>Math.max(280,Math.min(760,innerWidth-40));
const fabMaxH=()=>Math.max(260,Math.min(900,innerHeight-110));
const fabMinW=()=>Math.min(300,fabMaxW());
const fabMinH=()=>Math.min(280,fabMaxH());
function applyPanelSize(){
  const p=q("#erw-fab-panel");if(!p)return;
  try{
    const s=JSON.parse(localStorage.getItem(FAB_SIZE_KEY)||"");
    if(!s||!s.w||!s.h)return;
    p.style.width=fabClamp(s.w,fabMinW(),fabMaxW())+"px";
    p.style.height=fabClamp(s.h,fabMinH(),fabMaxH())+"px";
  }catch{}
}
/* ---------- v260930j3 · 面板移动：按住头部拖动（控件区除外），位置持久化 ---------- */
const FAB_POS_KEY="fabPanelPos";
function applyPanelPos(){
  const p=q("#erw-fab-panel");if(!p)return;
  try{
    const s=JSON.parse(localStorage.getItem(FAB_POS_KEY)||"");
    if(!s||!Number.isFinite(s.x)||!Number.isFinite(s.y))return;
    p.style.left=fabClamp(s.x,8,Math.max(8,innerWidth-p.offsetWidth-8))+"px";
    p.style.top=fabClamp(s.y,8,Math.max(8,innerHeight-p.offsetHeight-8))+"px";
    p.style.right="auto";p.style.bottom="auto";
  }catch{}
}
/* v261008b · 窗口缩放自适应：尺寸/位置只在「恢复」和「拖拽」时钳制过，窗口变小后不会重算，
   于是面板会顶出视口、内容被裁。这里在 resize 时按当前视口重新钳制面板与悬浮球。 */
let fabReflowTimer=null;
function reflowPanel(){
  const p=q("#erw-fab-panel");
  if(p&&!p.hidden){
    applyPanelSize();
    if(p.style.left!==""){ /* 只有被移动过的面板才需要重算位置（默认锚定右下，CSS 自己管） */
      const w=p.offsetWidth||0,h=p.offsetHeight||0;
      p.style.left=fabClamp(parseFloat(p.style.left)||0,8,Math.max(8,innerWidth-w-8))+"px";
      p.style.top=fabClamp(parseFloat(p.style.top)||0,8,Math.max(8,innerHeight-h-8))+"px";
      try{localStorage.setItem(FAB_POS_KEY,JSON.stringify({x:parseFloat(p.style.left),y:parseFloat(p.style.top)}))}catch{}
    }
  }
  const ball=q("#erw-fab-ball");
  if(ball&&ball.style.left){
    const [x,y]=clampBallPos(parseFloat(ball.style.left)||0,parseFloat(ball.style.top)||0);
    ball.style.left=x+"px";ball.style.top=y+"px";
  }
}
window.addEventListener("resize",()=>{clearTimeout(fabReflowTimer);fabReflowTimer=setTimeout(reflowPanel,120)});

function initPanelDrag(){  const head=q("#erw-fab-panel .fab-head"),p=q("#erw-fab-panel");if(!head||!p)return;
  head.addEventListener("pointerdown",e=>{
    if(e.button!==0)return;
    if(e.target.closest("button,select,input,label"))return; /* 人设/历史/新建/关闭等控件不触发拖动 */
    e.preventDefault();
    const r=p.getBoundingClientRect(),sx=e.clientX,sy=e.clientY,ox=r.left,oy=r.top;
    p.style.left=r.left+"px";p.style.top=r.top+"px";p.style.right="auto";p.style.bottom="auto";
    head.setPointerCapture(e.pointerId);head.classList.add("dragging");
    const mv=ev=>{
      p.style.left=fabClamp(ox+(ev.clientX-sx),8,Math.max(8,innerWidth-r.width-8))+"px";
      p.style.top=fabClamp(oy+(ev.clientY-sy),8,Math.max(8,innerHeight-r.height-8))+"px";
    };
    const up=()=>{
      head.removeEventListener("pointermove",mv);head.removeEventListener("pointerup",up);
      head.classList.remove("dragging");
      try{localStorage.setItem(FAB_POS_KEY,JSON.stringify({x:parseFloat(p.style.left),y:parseFloat(p.style.top)}))}catch{}
    };
    head.addEventListener("pointermove",mv);head.addEventListener("pointerup",up);
  });
}
function initPanelResize(){
  const h=q("#fab-resize"),p=q("#erw-fab-panel");if(!h||!p)return;
  h.addEventListener("pointerdown",e=>{
    e.preventDefault();
    const sw=p.offsetWidth,sh=p.offsetHeight,sx=e.clientX,sy=e.clientY;
    const hadLeft=p.style.left!=="",oleft=parseFloat(p.style.left)||0,otop=parseFloat(p.style.top)||0; /* v260930j3 · 移动过的面板 resize 时保持右下角不动 */
    h.setPointerCapture(e.pointerId);
    const mv=ev=>{
      const nw=fabClamp(sw+(sx-ev.clientX),fabMinW(),fabMaxW());
      const nh=fabClamp(sh+(sy-ev.clientY),fabMinH(),fabMaxH());
      p.style.width=nw+"px";p.style.height=nh+"px";
      if(hadLeft){p.style.left=oleft-(nw-sw)+"px";p.style.top=otop-(nh-sh)+"px"}
    };
    const up=()=>{
      h.removeEventListener("pointermove",mv);h.removeEventListener("pointerup",up);
      try{localStorage.setItem(FAB_SIZE_KEY,JSON.stringify({w:p.offsetWidth,h:p.offsetHeight}))}catch{}
    };
    h.addEventListener("pointermove",mv);h.addEventListener("pointerup",up);
  });
}
function contextChips(){
  const ctx=buildContext();
  const chips=[];
  chips.push(`<span class="ctx-chip">▦ ${esc(ctx.view)}</span>`);
  const lit=litContext();
  if(lit){chips.push(`<span class="ctx-chip">◫ <b title="${esc(lit.title)}">${esc(lit.title||lit.paper_id)}</b> · P.${esc(lit.page||1)}</span>`);
    if(lit.page_text)chips.push(`<span class="ctx-chip" title="当前页正文已随消息附带，供术语提取与问答">▤ 本页正文 ${lit.page_text.length} 字</span>`);} /* v260930c · M4 */
  if(ctx.doc_id)chips.push(`<span class="ctx-chip" title="已自动附带该条目标题与正文节选，AI 可直接引用">▧ ${esc(ctx.doc_id)} · 正文已附</span>`); /* v260930i · 直接引用当前条目 */
  if(ctx.selection)chips.push(`<span class="ctx-chip">❝ <b title="${esc(ctx.selection.slice(0,300))}">选中 ${ctx.selection.length} 字</b> <span class="ctx-x" id="fab-sel-clear" title="清除选中">×</span></span>`);
  return {ctx,chips};
}
function paintContext(){
  const root=q("#fab-context");if(!root)return;
  const {chips}=contextChips();
  /* v260930g · 当前人设写入能力徽章：只读人设提醒用户写动作会自动切换 */
  const p=currentPersona();
  const badge=p?`<span class="ctx-chip fab-rw${personaHasWrite()?" on":""}" title="${personaHasWrite()?`当前人设「${p.name}」可写知识库（${p.write_mode==="direct"?"直接落盘":"写入需确认"}）`:`当前人设「${p.name}」只读：点「存知识库/建档」等写动作会自动切换人设`}">${personaHasWrite()?"✎ 可写":"◔ 只读"}</span>`:"";
  root.innerHTML=chips.join("")+'<span style="flex:1"></span>'+badge+'<span class="ctx-empty">随消息自动附带</span>';
  const x=q("#fab-sel-clear");
  if(x)x.onclick=()=>{S.bubbleSel="";hideBubble();paintContext()};
}

/* ---------- 会话 ---------- */
async function restoreSession(){
  try{
    const saved=localStorage.getItem("fabAgentSession");
    if(saved){S.session=saved;await loadSession();return}
    const sessions=await api("/api/agent/sessions");
    if(sessions.length){S.session=sessions[0].id;await loadSession()}
  }catch(e){/* 网络失败静默：面板仍可提问，发送时会自动建会话 */}
}
async function loadSession(){
  if(!S.session)return;
  try{
    const s=await api("/api/agent/sessions/"+encodeURIComponent(S.session));
    S.messages=Array.isArray(s.messages)?s.messages:[];
    localStorage.setItem("fabAgentSession",S.session);
    renderMessages();
    syncDraftStatuses(); /* v260930g9f · 异步校准草稿真实状态（消息快照可能过期） */
  }catch(e){S.session=null;S.messages=[];renderEmpty()}
}
/* v260930g9f · 草稿状态校准：拉全量草稿（含已处理），用磁盘真实状态覆盖消息里的 pending 快照——
   草稿在别处（知识库页批量确认/另一会话）被处理后，面板不再误显「待确认」 */
async function syncDraftStatuses(){
  try{
    const list=await api("/api/agent/drafts?status=");
    if(!Array.isArray(list))return;
    const ids=new Set(S.messages.flatMap(m=>Array.isArray(m.drafts)?m.drafts.map(d=>d.draft_id):[]));
    let changed=false;
    for(const d of list){
      if(!ids.has(d.id)||d.status==="pending")continue;
      const cur=S.draftState[d.id];
      if(!cur||cur.status!==d.status){S.draftState[d.id]={status:d.status,result:d.result||cur?.result};changed=true}
    }
    if(changed)renderMessages();
  }catch{/* 校准失败静默：快照状态兜底 */}
}

/* ---------- 消息渲染 ---------- */
/* v261008b · 把过宽块级元素（表格）包进滚动容器：表格保持自身布局（不逐字换行），
   超宽时在气泡内横向滚动，而不是把面板撑破（.fab-messages 已 overflow-x:hidden）。 */
function wrapWideBlocks(html){
  return String(html||"").replace(/<table[\s\S]*?<\/table>/gi,(m)=>`<div class="fab-tbl">${m}</div>`);
}
function mdRender(raw){
  /* 轻量 Markdown → 安全 HTML（先转义再拼标签；marked/DOMPurify 可用时走完整渲染） */
  if(window.marked&&window.DOMPurify){
    try{
      const html=window.marked.parse(String(raw||""),{gfm:true});
      return wrapWideBlocks(window.DOMPurify.sanitize(html,{ADD_TAGS:["mjx-container"]})); /* v261008b · 表格套气泡内滚动容器 */
    }catch{/* 落回轻量渲染 */}
  }
  const lines=String(raw||"").split(/\r?\n/);let out="",inList=false,inCode=false;
  const inline=t=>t.replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`]+)`/g,"<code>$1</code>");
  for(const r of lines){
    const t=r.trimEnd();
    if(t.trim().startsWith("```")){if(inList){out+="</ul>";inList=false}out+=inCode?"</code></pre>":"<pre><code>";inCode=!inCode;continue}
    if(inCode){out+=esc(r)+"\n";continue}
    const h=t.match(/^(#{1,6})\s+(.*)$/);
    if(h){if(inList){out+="</ul>";inList=false}out+="<h4>"+inline(esc(h[2]))+"</h4>";continue}
    const li=t.match(/^\s*[-*·]\s+(.*)$/);
    if(li){if(!inList){out+="<ul>";inList=true}out+="<li>"+inline(esc(li[1]))+"</li>";continue}
    if(!t.trim()){if(inList){out+="</ul>";inList=false}continue}
    if(inList){out+="</ul>";inList=false}
    out+="<p>"+inline(esc(t))+"</p>";
  }
  if(inList)out+="</ul>";if(inCode)out+="</code></pre>";
  return out;
}
/* ---------- v261008b · 工具时间条：把「逐条 chip 流水账」换成与真实耗时成比例的堆叠条 ---------- */
function fmtDur(ms){
  ms=Math.max(0,Math.round(Number(ms)||0));
  if(ms<1000)return ms+"ms";
  if(ms<60000)return (ms/1000).toFixed(ms<10000?1:0)+"s";
  const m=Math.floor(ms/60000),s=Math.round(ms%60000/1000);
  return m+"m"+String(s).padStart(2,"0")+"s";
}
function timelineOf(m){
  const tl=m&&m.timing&&m.timing.timeline;
  if(Array.isArray(tl)&&tl.length)return tl.filter(s=>s&&(s.kind==="llm"||s.kind==="tool"));
  /* 兜底：没有服务端时间轴（老会话）时，按 tool_trace 的 ms 顺序拼一条，只是没有思考段 */
  const trace=Array.isArray(m&&m.tool_trace)?m.tool_trace:[];
  let t=0;
  return trace.map(x=>{const ms=Math.max(0,x.ms|0);const seg={kind:"tool",name:x.tool,ok:!!x.ok,t0:t,t1:t+ms,ms};t=seg.t1;return seg});
}
/* v261008b · 每个工具一种颜色：按本消息内「首次出现顺序」取色，保证同一条时间条里各工具颜色互不相同 */
const TL_PALETTE=["#3b82f6","#10b981","#f59e0b","#8b5cf6","#06b6d4","#ec4899","#84cc16","#f97316"];
const TL_LLM_COLOR="color-mix(in srgb,var(--muted) 45%,transparent)";
const TL_FAIL_COLOR="var(--danger,#b3392f)";
function tlColorMap(segs){
  const map=new Map();let i=0;
  for(const s of (segs||[])){
    if(!s||s.kind!=="tool")continue;
    const name=s.name||"工具";
    if(!map.has(name))map.set(name,TL_PALETTE[i++%TL_PALETTE.length]);
  }
  return map;
}
function tlSegColor(s,colors){
  if(s.kind==="llm")return TL_LLM_COLOR;
  if(s.ok===false)return TL_FAIL_COLOR; /* 失败仍用红色，语义优先于配色区分 */
  return (colors&&colors.get(s.name||"工具"))||"var(--accent)";
}
function tlBarHtml(segs,total,extra,colors){
  const list=(Array.isArray(segs)?segs:[]).filter(s=>s&&(s.kind==="llm"||s.kind==="tool"));
  if(!list.length)return "";
  const cmap=colors||tlColorMap(list);
  const end=Math.max(Number(total)||0,...list.map(s=>Number(s.t1)||0),1);
  const minW=end*0.004; /* 极短片段也留 0.4% 宽度，避免视觉上消失 */
  return `<div class="fab-tl-bar${extra?" "+extra:""}">`+list.map(s=>{
    const ms=Math.max(0,(Number(s.t1)||0)-(Number(s.t0)||0));
    const isLlm=s.kind==="llm";
    const cls=isLlm?"llm":"tool";
    const tip=isLlm?`思考 · 第 ${s.round||1} 轮 · ${fmtDur(ms)}`:`${s.name||"工具"} · ${fmtDur(ms)}${s.ok===false?" · 失败":""}`;
    return `<i class="fab-tl-seg ${cls}" style="flex:${Math.max(minW,ms).toFixed(1)} 1 0;background:${tlSegColor(s,cmap)}" title="${esc(tip)}"></i>`;
  }).join("")+`</div>`;
}
/* 图例：思考（灰）+ 每个工具（同色）+ 失败（红），各带次数与累计耗时 */
function tlLegendHtml(segs,colors){
  const list=(Array.isArray(segs)?segs:[]).filter(s=>s&&(s.kind==="llm"||s.kind==="tool"));
  if(!list.length)return "";
  const cmap=colors||tlColorMap(list);
  const llm=list.filter(s=>s.kind==="llm");
  const items=[];
  if(llm.length){
    const ms=llm.reduce((a,s)=>a+Math.max(0,(Number(s.t1)||0)-(Number(s.t0)||0)),0);
    items.push(`<span class="lg" title="模型思考累计 ${fmtDur(ms)}"><i style="background:${TL_LLM_COLOR}"></i>思考<span class="c">${llm.length} 轮</span><span class="t">${fmtDur(ms)}</span></span>`);
  }
  const order=[],agg=new Map();
  for(const s of list){
    if(s.kind!=="tool")continue;
    const name=s.name||"工具";
    if(!agg.has(name)){agg.set(name,{n:0,ms:0,bad:0});order.push(name)}
    const a=agg.get(name);a.n++;a.ms+=Math.max(0,(Number(s.t1)||0)-(Number(s.t0)||0));if(s.ok===false)a.bad++;
  }
  for(const name of order){
    const a=agg.get(name);
    items.push(`<span class="lg${a.bad?" bad":""}" title="${esc(name)}：${a.n} 次，累计 ${fmtDur(a.ms)}${a.bad?`，失败 ${a.bad} 次`:""}"><i style="background:${cmap.get(name)||"var(--accent)"}"></i><span class="nm">${esc(name)}</span><span class="c">×${a.n}</span><span class="t">${fmtDur(a.ms)}</span>${a.bad?`<span class="c bad">✗${a.bad}</span>`:""}</span>`);
  }
  return `<div class="fab-tl-legend">${items.join("")}</div>`;
}
function liveSegs(m){ /* 流式中的时间轴：未闭合段以当前时刻收尾，画成动态增长的条 */
  const now=Date.now()-(m.__t0||Date.now());
  return (m.__tl||[]).map(s=>({kind:s.kind,name:s.name,ok:s.ok,round:s.round,t0:s.t0,t1:s.t1==null?now:s.t1}));
}
function liveStatusHtml(m){
  if(!(m.__tl&&m.__tl.length&&(m.__thinking||m.__streaming)))return "";
  return `<div class="fab-tl-live"><div class="fab-thinking"><span class="dots"><i></i><i></i><i></i></span>${esc(m.__note||"正在思考 / 调用工具…")}</div>${tlBarHtml(liveSegs(m),Date.now()-(m.__t0||Date.now()),"live")}</div>`;
}
function toolTraceHtml(m){
  const trace=Array.isArray(m.tool_trace)?m.tool_trace:[];
  const segs=timelineOf(m);
  if(!trace.length&&!segs.length)return "";
  const timing=m.timing||{};
  const end=Number(timing.total_ms)||(segs.length?Number(segs[segs.length-1].t1)||0:0);
  const toolMs=timing.tool_ms!=null?Number(timing.tool_ms):segs.filter(s=>s.kind==="tool").reduce((a,s)=>a+Math.max(0,(Number(s.t1)||0)-(Number(s.t0)||0)),0);
  const rounds=Number(timing.rounds)||segs.filter(s=>s.kind==="llm").length;
  const calls=Number(timing.tool_calls)||trace.length||segs.filter(s=>s.kind==="tool").length;
  const llmMs=timing.llm_ms!=null?Number(timing.llm_ms):segs.filter(s=>s.kind==="llm").reduce((a,s)=>a+Math.max(0,(Number(s.t1)||0)-(Number(s.t0)||0)),0);
  const pct=end?Math.round(toolMs/end*100):0;
  const hasTiming=!!(m.timing&&Array.isArray(m.timing.timeline)&&m.timing.timeline.length); /* v261008b · 老会话只有 tool_trace：不谎报 0 轮 / 0ms 思考 */
  const sum=hasTiming
    ?`<span class="fab-tl-total">⏱ ${fmtDur(end)}</span><span>总耗时</span><span class="sep">·</span><span>${rounds} 轮</span><span class="sep">·</span><span title="模型思考累计耗时">思考 ${fmtDur(llmMs)}</span><span class="sep">·</span><span title="工具累计 ${fmtDur(toolMs)}，占总耗时 ${pct}%">工具 ${fmtDur(toolMs)} · ${calls} 次</span>`
    :`<span class="fab-tl-total">⏱ ${fmtDur(end)}</span><span>工具耗时合计</span><span class="sep">·</span><span>${calls} 次调用</span><span class="sep">·</span><span title="该消息产生于计时功能上线前，服务端未记录思考段与轮次">旧记录</span>`;
  const colors=tlColorMap(segs);
  let ti=0;
  const rows=segs.map(s=>{
    const ms=Math.max(0,(Number(s.t1)||0)-(Number(s.t0)||0));
    if(s.kind==="llm")return `<div class="fab-tl-row"><span class="k llm">思考</span><span class="n">第 ${s.round||1} 轮</span><span class="d">${fmtDur(ms)}</span></div>`;
    const t=trace[ti++]||{};
    const st=S.draftState[t.draft_id]?.status;
    const mark=st==="confirmed"?"✓ 已确认":st==="rejected"?"✗ 已拒绝":(s.ok===false?"✗ 失败":"");
    return `<div class="fab-tl-row"><span class="k tool${s.ok===false?" bad":""}"><i class="dot" style="background:${tlSegColor(s,colors)}"></i>${esc(s.name||t.tool||"工具")}</span><span class="n">${mark}</span><span class="d">${fmtDur(ms)}</span></div>`;
  }).join("");
  return `<div class="fab-tl">
    <div class="fab-tl-sum">${sum}</div>
    ${tlBarHtml(segs,end,"",colors)}
    ${tlLegendHtml(segs,colors)}
    <details class="fab-tl-detail"><summary>过程明细（${segs.length} 段）</summary>
      <div class="fab-tl-list">${rows}</div>
    </details>
  </div>`;
}
/* v261008b · 草稿输出紧凑化：待确认＝紧凑行（标题 + 行内确认/拒绝，≥2 篇给整批操作条）；
   已处理＝折成一行汇总（✓ 已确认 N / ✗ 已拒绝 M），明细收进 <details> 默认收起。
   注意：data-draft-confirm / -reject / -confirm-all / -reject-all 四个钩子必须保留——批量确认靠
   msgEl.querySelectorAll("[data-draft-confirm]") 收集 id（见 wireDrafts）。 */
function draftHtml(m,stateMap){
  const drafts=Array.isArray(m.drafts)?m.drafts:[];
  if(!drafts.length)return "";
  const stOf=(d)=>(stateMap||S.draftState)[d.draft_id]||{status:"pending"};
  const pend=drafts.filter(d=>stOf(d).status==="pending");
  const done=drafts.filter(d=>stOf(d).status!=="pending");
  const okN=done.filter(d=>stOf(d).status==="confirmed").length,noN=done.length-okN;
  const parts=[];
  if(pend.length){
    parts.push(`<div class="fab-drafts">
      <div class="fab-drafts-head"><span class="hd">◔ ${pend.length} 篇待确认</span>${pend.length>=2?`
        <button type="button" class="go" data-draft-confirm-all="1">✓ 全部确认</button>
        <button type="button" data-draft-reject-all="1">✗ 全部拒绝</button>`:""}</div>
      ${pend.map(d=>`<div class="fab-drow" data-draft="${esc(d.draft_id)}">
        <span class="dt-badge tool">${esc(d.tool)}</span>
        <span class="fab-drow-title" title="${esc(d.summary||d.draft_id)}">${esc(d.summary||d.draft_id)}</span>
        <span class="fab-drow-acts">
          <button type="button" class="go" data-draft-confirm="${esc(d.draft_id)}" title="确认并落盘">✓ 确认</button>
          <button type="button" data-draft-reject="${esc(d.draft_id)}" title="拒绝，不写入">✗ 拒绝</button>
        </span>
      </div>`).join("")}
      <div class="fab-drafts-note">草稿尚未落盘，确认后才写入知识库</div>
    </div>`);
  }
  if(done.length){
    parts.push(`<div class="fab-drafts done"><details>
      <summary><span class="hd ok">✓ 已确认 ${okN}</span>${noN?`<span class="hd no">✗ 已拒绝 ${noN}</span>`:""}<span class="fab-drafts-note">共 ${done.length} 篇 · 点击展开明细</span></summary>
      <div class="fab-dlist">${done.map(d=>{
        const st=stOf(d),r=st.result||{},ok=st.status==="confirmed";
        const dest=ok?(r.doc_id||r.title||"已完成"):"—";
        return `<div class="fab-drow done ${ok?"ok":"no"}" data-draft="${esc(d.draft_id)}">
          <span class="dt-badge st ${ok?"ok":"no"}">${ok?"已确认":"已拒绝"}</span>
          <span class="dt-badge tool">${esc(d.tool)}</span>
          <span class="fab-drow-title" title="${esc(d.summary||d.draft_id)}">${esc(d.summary||d.draft_id)}</span>
          <span class="fab-drow-id" title="${esc(dest)}">${esc(dest)}</span>
        </div>`}).join("")}</div>
    </details></div>`);
  }
  return parts.join("");
}
function quickActionsHtml(m){
  if(m.role!=="assistant")return "";
  const lit=litContext();
  return `<div class="fab-quick">
    <button type="button" data-fab-quick="note" title="把这条回复整理为知识库笔记草稿">存为笔记</button>
    ${lit?`<button type="button" data-fab-quick="lit" title="把这条回复追加到当前文献笔记">写入文献笔记</button>`:""}
    ${lit?`<button type="button" data-fab-quick="terms" title="从当前页提取专业名词，按 SOP 分族后逐条生成建档草稿（自动切换到术语建档员）">提取本页术语</button>`:""}
  </div>`;
}
function msgImagesHtml(m){ /* v260930e · 消息附图：user 消息 images 为落盘相对路径；待发消息为本地面板临时 dataURL */
  const imgs=Array.isArray(m.images)?m.images:[];
  if(!imgs.length)return "";
  return `<div class="fab-msg-imgs">${imgs.map(p=>`<img class="fab-msg-img" loading="lazy" alt="截图" src="${String(p).startsWith("data:")?esc(p):"/workspace-file/"+esc(p)}">`).join("")}</div>`;
}
function msgQuoteHtml(m){ /* v260930j · 消息内引用标记（本地发送时带 quoteTitle，会话重载后消失） */
  return m.quoteTitle?`<div class="fab-msg-quote">❝ 引用历史对话「${esc(m.quoteTitle)}」</div>`:"";
}
/* v261008b · 元信息去重：请求模式标签通常自带模型名（如「DeepSeek V4.1 Flash（默认）」、
   「DeepSeek V4.1 Flash · 无思考」），再并排显示 model 字段就成了同一件事报两遍。
   归一化后标签已含模型名 → 只留标签；标签与模型确实不同（如自定义标签）→ 两者都留。 */
function metaParts(m){
  const persona=String(m.persona_name||"").trim();
  const model=String(m.model||"").trim();
  const mode=String(m.request_preset_label||"").trim();
  const norm=(s)=>s.toLowerCase().replace(/[\s._\-（）()·/、]/g,"");
  const modelShown=!!model&&!(mode&&norm(mode).includes(norm(model)));
  return [persona,modelShown?model:"",mode].filter(Boolean);
}
function msgHtml(m,idx){
  const who=m.role==="assistant"?"AI":"YOU";
  const meta=[...metaParts(m).map(esc),esc(fmtTime(m.created))].filter(Boolean).join(" · ");
  const live=liveStatusHtml(m);
  const body=m.__thinking
    ?(live?"":'<div class="fab-thinking"><span class="dots"><i></i><i></i><i></i></span>正在思考 / 调用工具…</div>')
    :`<div class="fab-body">${mdRender(m.content||"")}</div>`;
  const cite=(m.__thinking||m.__streaming)?"":`<button type="button" class="fab-msg-cite" data-cite="${idx}" title="引用此条消息：发送时把该条内容带给 AI">❝</button>`; /* v260930j · 消息级引用；v260930k 生成中不显示 */
  return `<article class="fab-msg ${m.role==="assistant"?"assistant":"user"}">
    <div class="fab-avatar">${who}</div>
    <div class="fab-bubble">
      ${cite}
      ${msgQuoteHtml(m)}
      ${msgImagesHtml(m)}
      ${live}
      ${body}
      ${m.__thinking?"":toolTraceHtml(m)+draftHtml(m)+quickActionsHtml(m)}
      <div class="fab-msg-meta">${meta}</div>
    </div>
  </article>`;
}
function fmtTime(v){if(!v)return "";try{const d=new Date(v);return isNaN(d)?"":d.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit"})}catch{return ""}}
function renderEmpty(){
  const root=q("#fab-messages");if(!root)return;
  root.innerHTML=`<div class="fab-empty">我是全局 AI 助手：<br>· 问答时自动带上当前页面 / 文献 / 选中内容<br>· 可让我检索知识库、把术语建档（草稿需确认）<br>· 阅读文献时让我总结页面、写文献笔记</div>`;
}

/* ---------- 视图切换 / 附加截图 / 历史回看（v260930e） ---------- */
function paintView(){
  const root=q("#fab-messages");
  if(S.view==="history"){paintHistory();return}
  q("#fab-history")?.classList.remove("active");
  if(S.messages.length)renderMessages();else renderEmpty();
}
async function paintHistory(){
  q("#fab-history")?.classList.add("active");
  const root=q("#fab-messages");if(!root)return;
  root.innerHTML='<div class="fab-empty">加载历史对话…</div>';
  try{
    const rows=await api("/api/agent/sessions");
    if(!rows.length){root.innerHTML='<div class="fab-empty">暂无历史对话</div>';return}
    const active=rows.filter(s=>!s.archived),archived=rows.filter(s=>s.archived); /* v260930n · 活跃/已归档分组 */
    const row=(s)=>`
      <div class="fab-hist-row">
        <button type="button" class="fab-hist-item${s.id===S.session?" current":""}" data-hist="${esc(s.id)}">
          <span class="fab-hist-title">${esc(s.title||"新对话")}${s.id===S.session?' <i class="fab-hist-cur">当前</i>':""}</span>
          <span class="fab-hist-meta">${esc((s.updated||s.created||"").replace("T"," ").slice(0,16))} · ${s.message_count||0} 条</span>
          <span class="fab-hist-preview">${esc(s.preview||"")}</span>
        </button>
        <button type="button" class="fab-quote-btn" data-quote="${esc(s.id)}" data-quote-title="${esc(s.title||"历史对话")}" title="引用此对话：发送消息时把该对话内容作为参考带给 AI">❝</button>
        <button type="button" class="fab-hist-act" data-arch="${esc(s.id)}" data-flag="${s.archived?"0":"1"}" title="${s.archived?"取消归档，恢复到对话列表":"归档：从对话列表隐藏，可随时恢复"}">${s.archived?"📤":"📥"}</button><!-- v260930n -->
        <button type="button" class="fab-hist-act danger" data-del="${esc(s.id)}" data-title="${esc(s.title||"新对话")}" title="删除此对话（移入 AgentChats/Trash/，可从文件系统找回）">🗑</button><!-- v260930n -->
      </div>`;
    const sec=(label,list)=>list.length?`<div class="fab-hist-sec">${label}</div>${list.map(row).join("")}`:""; /* v260930n · 分组标题 */
    root.innerHTML=`<div class="fab-history-list">${sec("对话",active)}${sec("已归档",archived)}</div>`;
    qa("[data-hist]",root).forEach(b=>b.onclick=()=>{
      S.session=b.dataset.hist;S.messages=[];S.draftState={};S.relatedItems=[];S.view="chat";paintView();
      loadSession();paintContext();
      localStorage.setItem("fabAgentSession",S.session);
    });
    qa("[data-quote]",root).forEach(b=>b.onclick=()=>quoteSession(b.dataset.quote,b.dataset.quoteTitle));
    qa("[data-arch]",root).forEach(b=>b.onclick=async()=>{ /* v260930n · 归档/取消归档 */
      try{
        await api("/api/agent/session/archive",{method:"POST",body:{id:b.dataset.arch,archived:b.dataset.flag==="1"}});
        if(b.dataset.flag==="1")toastInPanel("已归档，可从「已归档」分组找回");
        paintHistory();
      }catch(e){toastInPanel(e.message,true)}
    });
    qa("[data-del]",root).forEach(b=>b.onclick=async()=>{ /* v260930n · 删除对话（后端移入 Trash，可从文件系统找回） */
      if(!confirm(`删除对话「${b.dataset.title}」？\n会话文件将移入 AgentChats/Trash/，可从文件系统找回。`))return;
      try{
        await api("/api/agent/sessions/"+encodeURIComponent(b.dataset.del),{method:"DELETE"});
        toastInPanel("已删除");
        if(b.dataset.del===S.session){ /* 删除的是当前会话：切到最近活跃会话或空态 */
          const rest=await api("/api/agent/sessions");
          const next=rest.find(s=>!s.archived);
          S.session=next?next.id:"";S.messages=[];S.draftState={};S.relatedItems=[];
          if(S.session){await loadSession();localStorage.setItem("fabAgentSession",S.session)}
          else{localStorage.removeItem("fabAgentSession")}
          paintContext();
        }
        paintHistory();
      }catch(e){toastInPanel(e.message,true)}
    });
  }catch(e){root.innerHTML=`<div class="fab-empty">加载失败：${esc(e.message)}</div>`}
}
/* v260930j · 引用历史对话：取该会话最近 12 条消息拼为参考文本（≤3800 字），发送时随 context 注入 AI */
async function quoteSession(id,title){
  try{
    const s=await api("/api/agent/sessions/"+encodeURIComponent(id));
    const msgs=(Array.isArray(s.messages)?s.messages:[]).slice(-12);
    let text="",count=0;
    for(const m of msgs){
      const body=String(m.content||"").trim();
      if(!body||m.role==="system")continue;
      text+=(m.role==="user"?"用户":"AI")+"："+body.slice(0,600)+"\n\n";count++;
      if(text.length>3800){text=text.slice(0,3800);break}
    }
    if(!count){toastInPanel("该会话没有可引用的内容",true);return}
    S.quote={id,title:title||"历史对话",text,count};
    paintQuoteBar();
    toastInPanel(`已引用「${S.quote.title}」的 ${count} 条消息，下次发送时生效`);
  }catch(e){toastInPanel(e.message,true)}
}
function paintQuoteBar(){
  const root=q("#fab-quote");if(!root)return;
  root.innerHTML=S.quote?`<div class="fab-quote-bar">❝ 引用「${esc(S.quote.title)}」· ${S.quote.count} 条 <button type="button" id="fab-quote-x" title="移除引用">×</button></div>`:"";
  const x=q("#fab-quote-x");if(x)x.onclick=()=>{S.quote=null;paintQuoteBar()};
}
/* v260930j · 消息级引用：对话流里点气泡 ❝ 直接引用该条（跨会话有效，替代翻历史列表） */
function quoteMessage(idx){
  const m=S.messages[idx];
  if(!m||!String(m.content||"").trim()){toastInPanel("该消息没有可引用的内容",true);return}
  const who=m.role==="assistant"?"AI":"用户";
  const brief=String(m.content||"").replace(/\s+/g," ").slice(0,16);
  S.quote={id:"msg-"+idx,title:`${who}：${brief}…`,text:`${who}：${String(m.content).slice(0,900)}`,count:1};
  paintQuoteBar();
  toastInPanel("已引用该条消息，下次发送时生效");
}
function attachImage(dataUrl){ /* v260930e · 附加截图（≤4 张，dataURL 暂存，发送时才上传落盘） */
  if(!dataUrl)return;
  if(S.images.length>=4){toastInPanel("一次最多附加 4 张截图",true);return}
  S.images.push(dataUrl);paintAttach();
}
function paintAttach(){
  const root=q("#fab-attach");if(!root)return;
  if(!S.images.length){root.innerHTML="";return}
  root.innerHTML=S.images.map((d,i)=>`<span class="fab-attach-item"><img src="${d}" alt="附图${i+1}"><span class="fab-attach-x" data-attach-x="${i}" title="移除">×</span></span>`).join("");
  qa("[data-attach-x]",root).forEach(b=>b.onclick=()=>{S.images.splice(+b.dataset.attachX,1);paintAttach()});
}
function renderMessages(){
  const root=q("#fab-messages");if(!root)return;
  if(!S.messages.length)return renderEmpty();
  root.innerHTML=S.messages.map((m,i)=>msgHtml(m,i)).join("");
  root.scrollTop=root.scrollHeight;
  if(window.MathJax?.typesetPromise){try{MathJax.typesetPromise([root])}catch{}}
  wireMessageActions(root);
}
function wireMessageActions(root){
  qa("[data-draft-confirm]",root).forEach(b=>b.onclick=()=>resolveDraft(b.dataset.draftConfirm,true));
  qa("[data-draft-reject]",root).forEach(b=>b.onclick=()=>resolveDraft(b.dataset.draftReject,false));
  qa("[data-fab-quick]",root).forEach(b=>b.onclick=()=>quickAction(b.dataset.fabQuick));
  qa("[data-cite]",root).forEach(b=>b.onclick=()=>quoteMessage(+b.dataset.cite)); /* v260930j · 消息级引用 */
  /* v260930c · M4 批量确认/拒绝：批量条在 draftHtml 内，取同一条消息下所有待确认草稿 id */
  qa("[data-draft-confirm-all],[data-draft-reject-all]",root).forEach(b=>b.onclick=()=>{
    const go=b.hasAttribute("data-draft-confirm-all");
    const msgEl=b.closest(".fab-msg");if(!msgEl)return;
    const ids=[...msgEl.querySelectorAll("[data-draft-confirm]")].map(x=>x.dataset.draftConfirm).filter(Boolean);
    if(ids.length)resolveDrafts(ids,go);
  });
}
async function resolveDrafts(ids,go){ /* v260930c · M4 · 批量逐个执行（草稿间无事务，单个失败不影响其余），完成后统一汇报 */
  if(!ids.length)return;
  let done=0,failed=0;
  for(const id of ids){
    try{
      const r=await api("/api/agent/drafts/"+encodeURIComponent(id)+(go?"/confirm":"/reject"),{method:"POST",body:{}});
      S.draftState[id]=go?{status:r.status==="confirmed"?"confirmed":"rejected",result:r.result}:{status:"rejected"};
      if(go&&r.status!=="confirmed")failed++;else done++;
    }catch(e){
      failed++; /* v260930g9g · 「已处理（xxx）」视为已同步状态而非失败 */
      const m=String(e.message||"").match(/已处理（([a-z]+)）/);
      S.draftState[id]=m?{status:m[1]}:{status:"rejected"};
    }
  }
  toastInPanel(go?(failed?`批量确认完成：${done} 成功 / ${failed} 失败`:`已确认 ${done} 篇草稿`):`已拒绝 ${ids.length} 篇草稿`);
  updateBallBadge();
  renderMessages();
}

/* ---------- 草稿确认 / 快捷动作 ---------- */
async function resolveDraft(id,go){
  if(!id)return;
  try{
    const r=await api("/api/agent/drafts/"+encodeURIComponent(id)+(go?"/confirm":"/reject"),{method:"POST",body:{}});
    S.draftState[id]=go?{status:r.status==="confirmed"?"confirmed":"rejected",result:r.result}:{status:"rejected"};
    if(go&&r.status!=="confirmed")toastInPanel(r.result?.error||"草稿执行失败",true);
    else toastInPanel(go?"已确认写入":"已拒绝草稿");
    updateBallBadge();
    renderMessages();
  }catch(e){
    /* v260930g9g · 草稿已被别处处理（知识库页确认/另一面板）：从报错解析真实状态并同步，不再误报错误 */
    const m=String(e.message||"").match(/已处理（([a-z]+)）/);
    if(m){S.draftState[id]={status:m[1]};updateBallBadge();renderMessages();toastInPanel("该草稿已处理过，状态已同步");return}
    toastInPanel(e.message,true);
  }
}
function quickAction(kind){
  const input=q("#fab-input");if(!input)return;
  if(kind==="terms"){ /* v260930c · M4 提取术语：切到术语建档员并预填 SOP 指令，上下文已自动附带当前页正文 */
    if(S.personas?.some(p=>p.id==="archivist")&&S.personaId!=="archivist"){S.personaId="archivist";localStorage.setItem("fabPersona","archivist");paintPersonaSelect()}
    input.value="请提取当前页正文中的专业名词：先分族与判定类别词，逐篇按五要素骨架生成建档草稿（每篇建档前先 kb_search 查重），最后输出术语清单表（术语/类别/条目标题/去向）。";
    input.focus();input.dispatchEvent(new Event("input"));
    return;
  }
  if(kind==="note")ensureWritePersona(); /* v260930g · 建档/写笔记需写工具，人设只读时自动切换 */
  input.value=kind==="note"
    ?"请把上一条回复整理为一条知识库笔记（先 kb_search 查重；标题按命名规范：知识-<类别>-<名称>；正文含摘要/要点/关联）"
    :"请把上一条回复追加到当前文献笔记末尾（lit_note_write，mode=append）";
  input.focus();
  input.dispatchEvent(new Event("input"));
}

/* ---------- 发送 ---------- */
async function send(){
  const input=q("#fab-input");if(!input||S.sending)return;
  const text=input.value.trim();
  if(!text&&!S.images.length)return;
  if(!window.ERWLLMReady?.()){toastInPanel("模型接口未启用：请先在 设置 → Agent / LLM 配置",true);return}
  S.sending=true;const btn=q("#fab-send");btn.textContent="停止";btn.title="停止生成";btn.classList.add("stop"); /* v260930l · 发送中按钮变停止键 */
  S.abortCtl=new AbortController(); /* v260930l */
  const {ctx}=contextChips();
  try{
    if(!S.session){const s=await api("/api/agent/sessions",{method:"POST",body:{}});S.session=s.id;localStorage.setItem("fabAgentSession",S.session)}
    /* v260930e · 附图上传落盘（dataURL → /api/agent/assets → 相对路径），单张失败不阻塞其余 */
    const imgPaths=[];
    for(const d of S.images){
      try{const r=await api("/api/agent/assets",{method:"POST",body:{data_url:d,name:"fab-shot.png"}});if(r.path)imgPaths.push(r.path)}
      catch(e){toastInPanel("截图上传失败："+e.message,true)}
    }
    S.messages.push({role:"user",content:text,images:imgPaths,quoteTitle:S.quote?.title||"",created:new Date().toISOString()}); /* v260930j · 本地气泡带引用标记 */
    S.images=[];paintAttach();
    input.value="";input.style.height="auto";
    /* v260930k · 方案 A 流式：SSE 逐字渲染。round=新一轮 LLM 请求（清缓冲），delta=文本片段，done=完整响应（与旧 JSON 同构），error=失败 */
    const streamMsg={role:"assistant",content:"",__thinking:true,__t0:Date.now(),__tl:[]}; /* v261008b · 实时时间条状态 */
    S.messages.push(streamMsg);
    renderMessages();
    const res=await fetch("/api/agent/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:S.session,message:text,refs:[],images:imgPaths,request_preset:"",context:ctx,persona_id:S.personaId}),signal:S.abortCtl.signal}); /* v260930l · 带 abort 信号 */
    if(!res.ok||!res.body){let d={};try{d=await res.json()}catch{};throw new Error(d.message||d.error||("HTTP "+res.status))}
    const reader=res.body.getReader(),dec=new TextDecoder("utf-8");
    let buf="",doneData=null;
    let rafPending=false;
    const paintStream=()=>{ /* 轻量增量渲染：只重绘最后气泡正文，不做全量重渲染/MathJax */
      if(rafPending)return;rafPending=true;
      requestAnimationFrame(()=>{rafPending=false;const root=q("#fab-messages");const body=root?.querySelector(".fab-msg:last-child .fab-body");if(body&&root){body.innerHTML=mdRender(streamMsg.content);root.scrollTop=root.scrollHeight}});
    };
    const nowMs=()=>Date.now()-streamMsg.__t0;
    const closeSeg=(seg)=>{if(seg&&seg.t1==null)seg.t1=nowMs()};
    const openLlm=()=>{const tl=streamMsg.__tl=streamMsg.__tl||[];const last=tl[tl.length-1];if(!last||last.kind!=="llm"||last.t1!=null)tl.push({kind:"llm",t0:nowMs(),t1:null,round:streamMsg.__round||1})};
    const paintStatus=(note)=>{ /* v261008b · 状态行 + 实时时间条：状态驱动渲染，重绘不丢进度（原实现改 DOM，首帧 delta 重绘即丢） */
      streamMsg.__note=note;renderMessages();
    };
    const handle=(ev,dataStr)=>{
      let data={};try{data=JSON.parse(dataStr)}catch{}
      if(ev==="delta"){
        if(streamMsg.__thinking){streamMsg.__thinking=false;streamMsg.__streaming=true;renderMessages()}
        openLlm(); /* v261008b · 首个 delta 前若还没开思考段（极少数时序）也补上 */
        streamMsg.content+=data.text||"";
        paintStream();
      }else if(ev==="round"){ /* v260930k · 工具循环新一轮：中途文本废弃，缓冲清零 */
        streamMsg.content="";streamMsg.__streaming=true;streamMsg.__round=(data.i|0)+1;
        closeSeg((streamMsg.__tl||[])[(streamMsg.__tl||[]).length-1]); /* v261008b · 收上一段 */
        openLlm();
        paintStatus(`第 ${streamMsg.__round} 轮 · 模型思考中…`);
      }else if(ev==="tool"){ /* v260930l · 工具执行完成实时上报 */
        streamMsg.__tools=streamMsg.__tools||[];
        streamMsg.__tools.push({n:String(data.name||""),ok:!!data.ok,ms:data.ms|0});
        const ms=Math.max(0,data.ms|0),t1=nowMs();const tl=streamMsg.__tl=streamMsg.__tl||[]; /* v261008b · 工具段：按上报耗时回推起点 */
        closeSeg(tl[tl.length-1]);
        tl.push({kind:"tool",name:String(data.name||""),ok:!!data.ok,ms,t0:Math.max(0,t1-ms),t1});
        paintStatus(`第 ${streamMsg.__round||1} 轮 · ${String(data.name||"工具")} ${data.ok?"✓":"✗"}（${ms}ms）· 累计 ${streamMsg.__tools.length} 次`);
      }else if(ev==="error"){throw new Error(data.message||"生成失败")}
      else if(ev==="done"){doneData=data}
    };
    let chunk;
    while(true){
      if(doneData)break; /* v260930m · done 已到立即收尾：不等 EOF（keep-alive 下 EOF 可能永不到达，曾致按钮卡「停止」、草稿卡片不渲染） */
      const rd=await reader.read();if(rd.done)break;chunk=rd.value;
      buf+=dec.decode(chunk,{stream:true});
      let idx;
      while((idx=buf.indexOf("\n\n"))>=0){
        const block=buf.slice(0,idx);buf=buf.slice(idx+2);
        let ev="",dline="";
        for(const line of block.split("\n")){if(line.startsWith("event:"))ev=line.slice(6).trim();else if(line.startsWith("data:"))dline+=line.slice(5).trim()}
        if(ev)handle(ev,dline);
      }
    }
    if(!doneData)throw new Error("连接中断，未收到完整响应");
    S.messages=S.messages.slice(0,-1);
    S.messages.push(doneData.assistant);
    S.bubbleSel="";paintContext();updateBallBadge();
    renderMessages();
    reader.cancel().catch(()=>{}); /* v260930m · 主动释放连接：done 后不再依赖服务器关闭 */
  }catch(e){
    const aborted=e&&e.name==="AbortError"; /* v260930l · 用户主动停止 */
    S.messages=S.messages.filter(m=>!m.__thinking&&!m.__streaming); /* v260930k · 同时清理思考中/流式未定稿消息 */
    S.messages.push({role:"assistant",content:aborted?"已停止生成。本轮任务可能已部分执行（以知识库草稿与会话记录为准），可继续追问或换个小任务分步做。":"请求失败："+e.message,created:new Date().toISOString()});
    renderMessages();
  }finally{
    S.sending=false;btn.textContent="发送";btn.title="";btn.classList.remove("stop");S.abortCtl=null; /* v260930l · 按钮恢复 */
    if(S.messages.at(-1)?.__thinking||S.messages.at(-1)?.__streaming){S.messages=S.messages.filter(m=>!m.__thinking&&!m.__streaming);renderMessages()}
  }
}

window.ERWFabTimeline={html:toolTraceHtml,bar:tlBarHtml,fmtDur,live:liveStatusHtml,drafts:draftHtml,metaParts:metaParts,render:mdRender}; /* v261008b · 供 Agent 页（app.js）复用同一套渲染，避免两处实现漂移 */

/* ---------- 划词气泡 ---------- */
function onDocMouseDown(e){
  if(!e.target.closest("#erw-sel-bubble"))hideBubble();
}
function onDocMouseUp(){
  setTimeout(()=>{
    /* v260930e · PDF 阅读区也弹气泡（用户要求内容选中功能）；截图上传后复制文本交给 AI 同样适用 */
    const txt=domSelection();
    if(!txt){hideBubble();return}
    S.bubbleSel=txt;
    const sel=window.getSelection();const range=sel?.getRangeAt(0);
    if(!range)return;
    const rect=range.getBoundingClientRect();
    const bubble=q("#erw-sel-bubble");if(!bubble)return;
    bubble.classList.add("show");
    const bw=bubble.offsetWidth||300;
    let left=rect.left+rect.width/2-bw/2;
    left=Math.max(10,Math.min(left,window.innerWidth-bw-10));
    let top=rect.top-44;if(top<70)top=rect.bottom+8;
    bubble.style.left=left+"px";bubble.style.top=top+"px";
  },10);
}
function hideBubble(){q("#erw-sel-bubble")?.classList.remove("show")}
const QUICK_PROMPTS={
  explain:"请解释我选中的内容：先讲清楚概念本身，再说明它在当前页面/文献语境中的作用。",
  summarize:"请总结我选中的内容要点，用 Markdown 列表输出，保留关键数字与公式。",
  save:"请把选中的内容整理为知识库条目：先 kb_search 查重（命中则改用增补），再按命名规范「知识-<类别>-<名称>」生成建档草稿，正文含摘要/原理或要点/关联。",
  ask:"",
};
function bubbleAct(act){
  const sel=S.bubbleSel||domSelection();
  hideBubble();
  if(!sel)return;
  openPanel();
  S.bubbleSel=sel;
  paintContext();
  if(act==="kb"){ /* v260930d · M5 查知识库：选中文本即时检索（/api/docs 复用知识库搜索），不经 AI */
    api("/api/docs?q="+encodeURIComponent(sel.slice(0,60))).then(rows=>{
      paintRelated(Array.isArray(rows)?rows.slice(0,8):[],{mode:"search"});
      if(!Array.isArray(rows)||!rows.length)toastInPanel("知识库中未找到相关条目");
    }).catch(e=>toastInPanel(e.message||"检索失败",true));
    return;
  }
  if(act==="save")ensureWritePersona(); /* v260930g · 存知识库需写工具，人设只读时自动切换 */
  const input=q("#fab-input");
  if(input&&QUICK_PROMPTS[act]!==undefined){input.value=QUICK_PROMPTS[act]||"请结合我选中的内容回答：";input.focus();input.dispatchEvent(new Event("input"))}
}

/* ---------- 草稿角标 & 启动 ---------- */
function updateBallBadge(){
  const pending=S.messages.some(m=>Array.isArray(m.drafts)&&m.drafts.some(d=>(S.draftState[d.draft_id]||{status:"pending"}).status==="pending"));
  q("#erw-fab-ball")?.classList.toggle("has-draft",pending);
}

/* ---------- 设置页人设编辑器（M3）：挂在 Agent/LLM 设置面板底部 ---------- */
let PE=null; /* 编辑器状态 */
document.addEventListener("erw-llm-settings-rendered",()=>renderPersonaEditor().catch(()=>{}));

async function renderPersonaEditor(){
  const host=q("#erw-persona-host");if(!host)return;
  const [cfg,tools]=await Promise.all([api("/api/config"),api("/api/agent/tools")]);
  const personas=JSON.parse(JSON.stringify(cfg?.app?.llm?.personas||[]));
  const presets=Array.isArray(cfg?.app?.llm?.request_presets)?cfg.app.llm.request_presets:[];
  PE={personas,tools,presets,open:PE?.open||null};
  paintPersonaEditor(host);
}
function personaRow(p,i){
  const t=PE.tools.map(tool=>`<label class="mark-chip" style="--mark-color:var(--accent)" title="${esc(tool.description||"")}"><input type="checkbox" data-pe-tool="${i}" value="${esc(tool.name)}" ${(p.tools||[]).includes(tool.name)?"checked":""}> ${esc(TOOL_LABELS[tool.name]||tool.name)}</label>`).join("");
  const presetOpts=PE.presets.map(m=>`<option value="${esc(m.id)}" ${p.request_preset===m.id?"selected":""}>${esc(m.label||m.id)}</option>`).join("");
  return `<div class="pe-row" data-pe-row="${i}" style="border:1px solid var(--line);border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:8px">
    <div style="display:flex;align-items:center;gap:8px">
      <input class="search-input" data-pe-name value="${esc(p.name)}" style="max-width:180px" ${p.builtin?"disabled title='内置人设不可改名'":""}>
      ${p.builtin?'<span class="badge">内置</span>':""}
      <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px">写入模式
        <select class="search-input" data-pe-write style="font-size:11px;padding:2px 6px">
          <option value="confirm" ${p.write_mode!=="direct"?"selected":""}>需确认（草稿）</option>
          <option value="direct" ${p.write_mode==="direct"?"selected":""}>直接写入</option>
        </select>
      </label>
      <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px">请求模式
        <select class="search-input" data-pe-preset style="font-size:11px;padding:2px 6px"><option value="">跟随对话</option>${presetOpts}</select>
      </label>
      <label style="font-size:11px;color:var(--muted);display:flex;align-items:center;gap:4px">温度
        <input class="search-input" data-pe-temp type="number" min="0" max="2" step="0.1" style="width:64px" value="${p.temperature==null?"":p.temperature}" placeholder="默认">
      </label>
      ${p.builtin?"":`<button type="button" class="ghost-btn danger" data-pe-del="${i}" style="margin-left:auto;font-size:11px">删除</button>`}
    </div>
    <textarea class="search-input" data-pe-prompt placeholder="系统提示词：定义这个角色的职责与风格" style="min-height:64px;font-size:12px">${esc(p.system_prompt||"")}</textarea>
    <div style="display:flex;flex-wrap:wrap;gap:5px;align-items:center"><span style="font-size:11px;color:var(--muted)">工具白名单</span>${t}</div>
  </div>`;
}
function paintPersonaEditor(host){
  host.innerHTML=`<div class="card-head" style="margin-top:18px;flex-wrap:wrap;row-gap:6px"><div style="min-width:0"><div class="card-kicker">AI ASSISTANT PERSONAS</div><h3>AI 助手人设</h3><p class="row-meta">自定义悬浮球 AI 助手的角色：修改系统提示词、新增/删除人设、勾选工具白名单（检索/建档/写笔记）、设定写入模式与温度。悬浮球头部下拉即可切换，保存后立即生效。撰写笔记/日志等的统一约束见写作规范文档（Workspace/System/AI助手写作与建档规范.md，个人数据不入 git）。</p></div><div style="display:flex;gap:8px;flex-shrink:0"><button type="button" class="secondary-btn" id="pe-open-rules" title="在资源管理器中打开写作规范文档所在目录，编辑后重启工作台生效">打开写作规范</button><button type="button" class="secondary-btn" id="pe-add">＋ 新增人设</button></div></div>
  <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px">${PE.personas.map(personaRow).join("")}</div>
  <div style="margin-top:12px"><button type="button" class="primary-btn" id="pe-save">保存人设</button></div>`;
  q("#pe-open-rules").onclick=()=>{ /* v260930g5 · 跳转写作规范（个人工作区数据，经 /api/workspace/open 打开所在目录） */
    fetch("/api/workspace/open",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({path:"System/AI助手写作与建档规范.md"})}).then(r=>r.json()).then(d=>{if(!d.ok)throw new Error(d.message||"打开失败")}).catch(e=>alert("打开写作规范失败："+e.message));
  };
  q("#pe-add").onclick=()=>{
    collectPersonaEditor();
    PE.personas.push({id:"persona-"+Date.now(),name:"新人设",builtin:false,system_prompt:"",tools:["kb_search","kb_read","lit_context"],write_mode:"confirm",request_preset:"",temperature:null});
    paintPersonaEditor(host);
  };
  qa("[data-pe-del]",host).forEach(b=>b.onclick=()=>{collectPersonaEditor();PE.personas.splice(+b.dataset.peDel,1);paintPersonaEditor(host)});
  q("#pe-save").onclick=savePersonaEditor;
}
function collectPersonaEditor(){
  qa("[data-pe-row]").forEach(row=>{
    const i=+row.dataset.peRow,p=PE.personas[i];if(!p)return;
    if(!p.builtin)p.name=row.querySelector("[data-pe-name]").value.trim()||p.name;
    p.system_prompt=row.querySelector("[data-pe-prompt]").value;
    p.write_mode=row.querySelector("[data-pe-write]").value;
    p.request_preset=row.querySelector("[data-pe-preset]").value;
    const temp=row.querySelector("[data-pe-temp]").value.trim();
    p.temperature=temp===""?null:Number(temp);
    p.tools=qa("[data-pe-tool]:checked",row).map(x=>x.value);
  });
}
async function savePersonaEditor(){
  try{
    collectPersonaEditor();
    const cfg=await api("/api/config");
    cfg.app.llm={...cfg.app.llm,personas:PE.personas};
    const saved=await api("/api/config/app",{method:"POST",body:cfg.app});
    window.ERWConfigSync?.(saved);
    S.personas=JSON.parse(JSON.stringify(saved.llm?.personas||[]));
    if(!S.personas.some(p=>p.id===S.personaId))S.personaId=S.personas[0]?.id||"reader";
    paintPersonaSelect();
    const host=q("#erw-persona-host");
    if(host){PE.personas=JSON.parse(JSON.stringify(saved.llm?.personas||[]));paintPersonaEditor(host)}
    window.ERWToast?.("人设已保存");
  }catch(e){window.ERWToast?.(e.message,true)}
}

function boot(){
  mount();
  updateBallBadge();
}
/* v260930 · M3：toast 桥（设置页人设编辑器用），复用主应用 toast-stack 容器 */
window.ERWToast=(msg,bad)=>{
  const root=q("#toast-stack");if(!root)return;
  const el=document.createElement("div");
  el.className="toast"+(bad?" error":"");el.textContent=msg;
  root.appendChild(el);setTimeout(()=>el.remove(),3200);
};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);
else boot();
})();
