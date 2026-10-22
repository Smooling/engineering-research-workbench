/* Shared presentation preferences. These never change research source text. */
(()=>{
  'use strict';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let projects=[];
  const read=(key,fallback)=>{try{return localStorage.getItem(key)??fallback}catch{return fallback}};
  function projectLabel(name){return projects.find(p=>p.name===name||p.id===name)?.display_name||name||''}
  function setProjects(rows){projects=Array.isArray(rows)?rows.filter(p=>p&&p.name):[]}
  async function loadProjects(){try{const response=await (window.erwFetch||fetch)('/api/project-records');if(response.ok)setProjects(await response.json())}catch{}return projects}
  function evidence(doc){
    if(doc.evidence?.label&&doc.evidence?.level)return doc.evidence;
    const text=String(doc.body||doc.excerpt||'').slice(0,2400),declared=(text.match(/(?:证据级别|证据范围)\s*[:：]\s*([^\n]+)/)||[])[1]||'';
    const pdf=!!(doc.attachment_exists||doc.has_pdf||doc.source?.type==='pdf');
    let level=doc.kind==='literature'?'catalog':'note',label=level==='note'?'知识笔记':'题录';
    if((/摘要/.test(declared)&&!/(?:未|无|没有|不含|尚未|尚无).{0,5}摘要|摘要(?:尚未|未|不可|缺失)/.test(declared))||(doc.tags||[]).includes('摘要可检索')){level='abstract';label='公开摘要'}
    if(pdf||/PDF\s*全文已提取/.test(declared)){level='pdf';label='有 PDF 全文'}
    if(/^(?:已核对原文|已逐条核对原文|已精读原文)/.test(declared.trim())){level='verified';label='已核对原文'}
    return {level,label,has_pdf:pdf,declared:!!declared};
  }
  function evidenceBadge(doc){const e=evidence(doc);return `<span class="evidence-badge" data-evidence-level="${esc(e.level)}" title="${esc(e.declared?'资料记录的证据范围；不等同于本次模型已阅读全部内容':'资料可用范围；不等同于已精读')}" >${esc(e.label)}</span>`}
  function remember(kind,value){try{localStorage.setItem('erwRecent:'+kind,JSON.stringify(value))}catch{}}
  function recent(kind){try{return JSON.parse(read('erwRecent:'+kind,'null'))}catch{return null}}
  function readingSize(size){const n=Math.max(12,Math.min(20,Number(size)||14));document.documentElement.style.setProperty('--reading-font-size',n+'px');try{localStorage.setItem('readingFontSize',String(n))}catch{}return n}
  function wheelScale(current,event,min,max){const pixels=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?400:1);return Math.max(min,Math.min(max,current*Math.exp(-Math.max(-240,Math.min(240,pixels))*.0015)))}
  function init(){
    readingSize(read('readingFontSize','14'));
    const menu=document.querySelector('#zoom-menu');
    if(menu&&!menu.querySelector('#reading-font-size')){
      menu.insertAdjacentHTML('beforeend',`<label class="reading-size-control">阅读字号<select id="reading-font-size" aria-label="阅读字号">${[12,14,16,18,20].map(n=>`<option value="${n}">${n}px</option>`).join('')}</select></label><small class="reading-size-help">阅读字号影响笔记与 AI 回复；上方缩放调整整个界面。</small>`);
      const select=menu.querySelector('select');select.value=String(readingSize(read('readingFontSize','14')));select.onchange=()=>readingSize(select.value);
    }
  }
  window.ERWResearchUI={esc,projectLabel,setProjects,loadProjects,projectRecords:()=>projects,evidence,evidenceBadge,remember,recent,readingSize,wheelScale};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
