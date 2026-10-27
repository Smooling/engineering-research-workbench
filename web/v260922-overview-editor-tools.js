(() => {
  'use strict';

  const qs = (s, root=document) => root.querySelector(s);
  const qsa = (s, root=document) => [...root.querySelectorAll(s)];

  const clampZoom = (value) => {
    const n = Number(value);
    if (!Number.isFinite(n)) return 100;
    return Math.max(10, Math.min(300, Math.round(n * 10) / 10));
  };
  const readZoom = key => clampZoom(localStorage.getItem(key) || 100);
  const writeZoom = (key, value) => {
    const z = clampZoom(value);
    localStorage.setItem(key, String(z));
    return z;
  };
  const zoomOptions = current => [...new Set([...Array.from({length:30}, (_,i)=>(i+1)*10),current])].sort((a,b)=>a-b)
    .map(n=>`<option value="${n}" ${n===current?'selected':''}>${n}%</option>`).join('');

  function applyEditorZoom(){
    const pane=qs('#editor-pane'); if(!pane)return;
    const edit=readZoom('erwEditorZoom'), preview=readZoom('erwPreviewZoom');
    pane.style.setProperty('--md-edit-scale', String(edit/100));
    pane.style.setProperty('--md-preview-scale', String(preview/100));
    const a=qs('[data-editor-zoom="edit"]'), b=qs('[data-editor-zoom="preview"]');
    for(const [select,value] of [[a,edit],[b,preview]])if(select){if(![...select.options].some(option=>+option.value===value)){select.querySelector('[data-wheel-value]')?.remove();const option=new Option(value+'%',String(value));option.dataset.wheelValue='true';select.add(option)}select.value=String(value)}
  }

  function bindWheelZoom(element,key,apply){
    if(!element||element.dataset.wheelZoomReady)return;element.dataset.wheelZoomReady='true';
    // Keep native tooltips off reading surfaces; zoom help stays on toolbar controls.
    let frame=0,next=0,point=0,anchor=null,release=0;
    element.addEventListener('wheel',event=>{
      if(!(event.ctrlKey||event.metaKey)||!event.deltaY)return;
      event.preventDefault();event.stopPropagation();
      const rect=element.getBoundingClientRect(),scale=rect.height/element.clientHeight||1;
      point=Math.max(0,Math.min(element.clientHeight,(event.clientY-rect.top)/scale));
      if(!frame)anchor=window.ERWEditorViewport?.capture(element,point)||{fraction:(element.scrollTop+point)/Math.max(1,element.scrollHeight)};
      next=window.ERWResearchUI.wheelScale(next||readZoom(key),event,10,300);
      clearTimeout(release);element.dataset.zooming='true';
      if(!frame)frame=requestAnimationFrame(()=>{
        frame=0;if(!element.isConnected)return;
        writeZoom(key,next);apply();
        if(window.ERWEditorViewport)window.ERWEditorViewport.restore(element,anchor,point);else element.scrollTop=anchor.fraction*element.scrollHeight-point;
        next=0;release=setTimeout(()=>delete element.dataset.zooming,120);
      });
    },{passive:false});
  }
  window.ERWPaneZoom={bindText(element,key,base=13){
    if(!element)return;const apply=()=>element.style.setProperty('font-size',base*readZoom(key)/100+'px','important');
    apply();bindWheelZoom(element,key,apply);
  }};

  function injectEditorZoomControls(){
    for(const [selector,key] of [['.docs-layout .doc-list','erwDocumentListZoom'],['#lit-list','erwPdfListZoom']]){
      const list=qs(selector);if(list){const apply=()=>list.style.setProperty('--document-list-zoom',readZoom(key)/100);apply();bindWheelZoom(list,key,apply)}
    }
    const toolbar=qs('#doc-editor .toolbar');
    if(!toolbar){return;}
    bindWheelZoom(qs('#md-input'),'erwEditorZoom',applyEditorZoom);
    bindWheelZoom(qs('#md-preview'),'erwPreviewZoom',applyEditorZoom);
    if(toolbar.querySelector('.editor-zoom-controls')){applyEditorZoom();return;}
    const edit=readZoom('erwEditorZoom'), preview=readZoom('erwPreviewZoom');
    const box=document.createElement('div');
    box.className='editor-zoom-controls';
    box.innerHTML=`<label class="editor-zoom-field" title="鼠标放在编辑栏，Ctrl + 滚轮缩放"><span>编辑</span><select data-editor-zoom="edit" aria-label="编辑区缩放">${zoomOptions(edit)}</select></label><label class="editor-zoom-field" title="鼠标放在预览栏，Ctrl + 滚轮缩放"><span>预览</span><select data-editor-zoom="preview" aria-label="预览区缩放">${zoomOptions(preview)}</select></label>`;
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
    const head=qs('.card-head',card);if(!head)return;
    [...card.children].forEach(child=>{if(child!==head)child.remove()});
    const list=document.createElement('div');list.className='recent-card-list';
    const rows=(docs||[]).slice(0,5);
    if(!rows.length){const empty=document.createElement('div');empty.className='empty recent-empty';empty.textContent='暂无内容';list.appendChild(empty)}
    else if(window.ERWRecentActivity){
      list.innerHTML=rows.map(doc=>window.ERWRecentActivity.row(doc)).join('');
      qsa('.recent-activity-row',list).forEach((row,i)=>row.onclick=()=>window.ERWRecentActivity.open(rows[i]));
    }
    card.appendChild(list);
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
