(() => {
  'use strict';

  const KEY = 'erwEditorSplitPercent';
  const MIN = 28;
  const MAX = 72;

  const clamp = (v,min,max) => Math.max(min,Math.min(max,v));

  function readPercent(){
    const n = Number(localStorage.getItem(KEY));
    return Number.isFinite(n) ? clamp(n,MIN,MAX) : 50;
  }

  function applyPercent(pane,percent,persist=false){
    const p=clamp(percent,MIN,MAX);
    pane.style.setProperty('--editor-split', p + '%');
    if(persist) localStorage.setItem(KEY,String(Math.round(p*10)/10));
    const splitter=pane.querySelector('.editor-splitter');
    if(splitter) splitter.setAttribute('aria-valuenow',String(Math.round(p)));
    return p;
  }

  function installPane(pane){
    if(!pane || pane.dataset.softSplitReady==='1') return;
    const input=pane.querySelector('.md-input');
    const preview=pane.querySelector('.md-preview');
    if(!input || !preview) return;
    pane.dataset.softSplitReady='1';

    const splitter=document.createElement('div');
    splitter.className='editor-splitter';
    splitter.setAttribute('role','separator');
    splitter.setAttribute('aria-orientation','vertical');
    splitter.setAttribute('aria-label','调整 Markdown 编辑与预览宽度');
    splitter.setAttribute('aria-valuemin',String(MIN));
    splitter.setAttribute('aria-valuemax',String(MAX));
    splitter.tabIndex=0;
    pane.insertBefore(splitter,preview);

    let percent=applyPercent(pane,readPercent(),false);
    let dragging=false;
    let pointerId=null;

    const fromPointer=e=>{
      const r=pane.getBoundingClientRect();
      if(!r.width) return percent;
      return clamp((e.clientX-r.left)/r.width*100,MIN,MAX);
    };

    const end=()=>{
      if(!dragging)return;
      dragging=false;
      pointerId=null;
      document.documentElement.classList.remove('editor-resizing');
      applyPercent(pane,percent,true);
    };

    splitter.addEventListener('pointerdown',e=>{
      if(e.button!==0 || pane.classList.contains('edit-only') || pane.classList.contains('preview-only'))return;
      dragging=true;pointerId=e.pointerId;
      document.documentElement.classList.add('editor-resizing');
      try{splitter.setPointerCapture(pointerId)}catch{}
      e.preventDefault();
    });
    splitter.addEventListener('pointermove',e=>{
      if(!dragging || e.pointerId!==pointerId)return;
      percent=applyPercent(pane,fromPointer(e),false);
    });
    splitter.addEventListener('pointerup',end);
    splitter.addEventListener('pointercancel',end);
    splitter.addEventListener('lostpointercapture',end);
    splitter.addEventListener('dblclick',()=>{
      percent=applyPercent(pane,50,true);
    });
    splitter.addEventListener('keydown',e=>{
      let next=percent;
      const step=e.shiftKey?8:3;
      if(e.key==='ArrowLeft')next-=step;
      else if(e.key==='ArrowRight')next+=step;
      else if(e.key==='Home')next=MIN;
      else if(e.key==='End')next=MAX;
      else return;
      e.preventDefault();
      percent=applyPercent(pane,next,true);
    });
  }

  function scan(root=document){
    root.querySelectorAll?.('.editor-pane').forEach(installPane);
    if(root.matches?.('.editor-pane'))installPane(root);
  }

  function init(){
    scan();
    /* v261015 · 文档级 DOM 变更统一走 ERWDom 单例（installPane 幂等，重扫即安全） */
    window.ERWDom?.onChildList(()=>scan());
    window.addEventListener('storage',e=>{
      if(e.key!==KEY)return;
      document.querySelectorAll('.editor-pane').forEach(p=>applyPercent(p,readPercent(),false));
    });
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();