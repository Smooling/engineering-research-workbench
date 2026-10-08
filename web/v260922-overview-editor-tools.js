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
        const res=await fetch('/api/docs?kind='+encodeURIComponent(kind));
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
  function start(){const main=qs('#main');if(!main)return;new MutationObserver(schedule).observe(main,{childList:true,subtree:true});schedule();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
