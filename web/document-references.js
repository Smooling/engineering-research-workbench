/* Read-only reference previews and editor completion. Searches never use a model. */
(()=>{
  'use strict';
  const q=(s,r=document)=>r.querySelector(s),all=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=value=>window.ERWResearchUI.esc(value);
  const kinds={note:'笔记',literature:'文献',idea:'灵感',journal:'实验记录',summary:'工作总结',milestone:'里程碑'};
  const cache=new Map();
  let peek=null,completion=null,completionSeq=0;
  async function json(url,signal){
    const response=await (window.erwFetch||fetch)(url,{signal});let data={};try{data=await response.json()}catch{}
    if(!response.ok)throw Object.assign(new Error(data.message||data.error||'请求失败'),{status:response.status});
    return data;
  }
  function resolve(target,force=false){
    const key=String(target||'').trim(),existing=cache.get(key);
    if(existing&&(!force&&existing.expires>Date.now()||!existing.expires))return existing.promise;
    const entry={expires:0};
    entry.promise=json('/api/docs/resolve?target='+encodeURIComponent(key)).then(doc=>{entry.expires=Date.now()+30000;return doc},error=>{entry.expires=Date.now()+5000;throw error});
    cache.set(key,entry);if(cache.size>100)cache.delete(cache.keys().next().value);
    return entry.promise;
  }
  function targetOf(anchor){return anchor.dataset.wiki||anchor.dataset.agentReference||''}
  function annotate(anchor,state,message){
    anchor.dataset.referenceState=state;
    anchor.title=message;
    anchor.setAttribute('aria-label',(anchor.textContent||'引用')+'；'+message);
  }
  async function validate(root,force=false){
    const version=(root._referenceValidation||0)+1;root._referenceValidation=version;
    const links=all('a[data-wiki],a[data-agent-reference]',root),groups=[...new Set(links.map(targetOf))];
    links.forEach(anchor=>annotate(anchor,'checking','正在检查引用…'));
    let next=0;
    await Promise.all(Array.from({length:Math.min(3,groups.length)},async()=>{
      for(;;){
        if(!root.isConnected||root._referenceValidation!==version)return;
        const target=groups[next++];if(target===undefined)return;const anchors=links.filter(anchor=>targetOf(anchor)===target);
        try{await resolve(target,force);if(root._referenceValidation===version)anchors.filter(anchor=>anchor.isConnected).forEach(anchor=>annotate(anchor,'valid','点击预览 · Ctrl/⌘ + 点击打开文档'))}
        catch(error){
          if(root._referenceValidation!==version)continue;
          const broken=[400,404].includes(error.status);
          anchors.filter(anchor=>anchor.isConnected).forEach(anchor=>annotate(anchor,broken?'missing':'unavailable',broken?'引用不可用：'+error.message:'暂时无法检查引用，请检查连接后重试'));
        }
      }
    }));
  }
  function bindPreview(root){
    if(!root)return;
    // Only local document files/endpoints participate; external URLs keep browser behavior.
    all('a[href]:not([data-wiki]):not([data-agent-reference])',root).forEach(anchor=>{
      try{
        const url=new URL(anchor.getAttribute('href'),location.href);if(url.origin!==location.origin)return;
        const endpoint=url.pathname.match(/^\/api\/docs\/([^/]+)(?:\/attachment)?$/),file=url.pathname.match(/\/([^/]+)\.md$/i);
        if(endpoint||file)anchor.dataset.agentReference=decodeURIComponent((endpoint||file)[1]);
      }catch{}
    });
    if(!root.dataset.referencePreviewBound){
      root.dataset.referencePreviewBound='true';
      root.addEventListener('click',event=>{
        const anchor=event.target.closest('a[data-wiki],a[data-agent-reference]');if(!anchor||!root.contains(anchor))return;
        event.preventDefault();event.stopPropagation();
        if(event.ctrlKey||event.metaKey)openTarget(targetOf(anchor));else openPreview(targetOf(anchor),anchor);
      });
    }
    validate(root);
  }
  async function openTarget(target,options={}){
    try{const doc=await resolve(target,true);await window.ERWNav.open(doc.kind,doc.id,options)}catch(error){window.ERWToast?.('引用无法打开：'+error.message,true)}
  }
  function closePreview(restoreFocus=true){
    if(!peek)return;
    const previous=peek;peek=null;previous.seq++;previous.observer.disconnect();previous.panel.remove();delete previous.layout.dataset.referenceDocked;
    if(restoreFocus&&previous.trigger?.isConnected)previous.trigger.focus({preventScroll:true});
  }
  function positionPreview(){
    if(!peek)return;if(!peek.layout.isConnected){closePreview(false);return}
    const {layout,panel}=peek,docked=layout.classList.contains('docs-layout')&&layout.clientWidth>=1250;
    layout.dataset.referenceDocked=String(docked);
    const zoom=parseFloat(document.documentElement.style.zoom)||1,chrome=document.documentElement.dataset.desktop==='true'?48:0;
    panel.style.setProperty('--reference-top',Math.max(chrome+8,Math.min(layout.getBoundingClientRect().top,innerHeight-240))/zoom+'px');
  }
  function createPreview(trigger){
    const layout=trigger?.closest('.lit-shell')||q('#doc-editor')?.closest('.docs-layout');if(!layout)return null;
    const panel=document.createElement('aside');panel.className='document-reference-preview';panel.setAttribute('aria-label','引用文档预览');
    panel.innerHTML='<header><div><span>引用预览</span><h3 id="reference-preview-title"></h3></div><button type="button" data-reference-back disabled title="返回上一个引用" aria-label="返回上一个引用">←</button><button type="button" data-reference-close title="关闭引用预览 · Esc" aria-label="关闭引用预览">×</button></header><div class="reference-preview-meta"></div><div class="md-preview reference-preview-body" tabindex="0" aria-label="引用正文"></div><footer><span>Ctrl/⌘ + 点击引用可直接打开</span><div><button type="button" data-reference-pdf hidden>阅读 PDF</button><button type="button" data-reference-open disabled>打开文档 ↗</button></div></footer>';
    layout.append(panel);
    const current={layout,panel,trigger,history:[],seq:0,doc:null,sourceId:window.ERWCurrentDoc,observer:new ResizeObserver(positionPreview)};peek=current;current.observer.observe(layout);positionPreview();
    q('[data-reference-close]',panel).onclick=()=>closePreview();
    q('[data-reference-back]',panel).onclick=()=>{if(current.history.length>1){current.history.pop();showPreview(current.history.at(-1),false)}};
    q('[data-reference-open]',panel).onclick=()=>{if(current.doc)openTarget(current.doc.id,{note:true})};
    q('[data-reference-pdf]',panel).onclick=()=>{if(current.doc)openTarget(current.doc.id)};
    const body=q('.reference-preview-body',panel);bindPreview(body);window.ERWPaneZoom?.bindText(body,'erwReferencePreviewZoom',14);
    return current;
  }
  function openPreview(target,trigger){
    closeCompletion(false);
    if(peek&&!peek.layout.isConnected)closePreview(false);
    if(!peek&&!createPreview(trigger))return;
    peek.trigger=trigger;showPreview(target);
  }
  async function showPreview(target,remember=true){
    const current=peek;if(!current)return;const seq=++current.seq,{panel}=current;current.doc=null;
    if(remember&&current.history.at(-1)!==target){current.history.push(target);if(current.history.length>20)current.history.shift()}
    q('[data-reference-back]',panel).disabled=current.history.length<2;
    q('#reference-preview-title',panel).textContent='正在打开引用…';
    q('.reference-preview-meta',panel).textContent='';q('[data-reference-open]',panel).disabled=true;q('[data-reference-pdf]',panel).hidden=true;
    const body=q('.reference-preview-body',panel);body.innerHTML='<div class="reference-status" role="status">正在读取文档…</div>';
    try{
      const doc=await resolve(target);if(peek!==current||seq!==current.seq||!panel.isConnected)return;
      current.doc=doc;q('#reference-preview-title',panel).textContent=doc.title||'未命名文档';
      q('.reference-preview-meta',panel).textContent=[kinds[doc.kind]||doc.kind,...(doc.projects?.length?doc.projects:doc.project?[doc.project]:[]),doc.status].filter(Boolean).join(' · ');
      q('[data-reference-open]',panel).disabled=false;q('[data-reference-pdf]',panel).hidden=!(doc.attachment||doc.has_pdf);
      await window.ERWMarkdown.renderInto(body,doc.body||'*暂无正文*');
      if(peek!==current||seq!==current.seq)return;body.scrollTop=0;bindPreview(body);all('[data-reference-preview-bound]').filter(root=>root!==body).forEach(root=>validate(root));
    }catch(error){
      if(peek!==current||seq!==current.seq)return;
      q('#reference-preview-title',panel).textContent=[400,404].includes(error.status)?'引用不可用':'暂时无法读取';
      body.innerHTML='<div class="reference-status reference-error"><p>'+esc(error.message)+'</p><button type="button" data-reference-retry>重新检查</button></div>';
      q('[data-reference-retry]',body).onclick=()=>{cache.delete(String(target).trim());showPreview(target,false)};
    }
  }
  function invalidate(){cache.clear();all('[data-reference-preview-bound]').forEach(root=>validate(root,true))}

  function closeCompletion(restoreFocus=false){
    completionSeq++;
    if(!completion)return;
    const current=completion;completion=null;clearTimeout(current.timer);current.controller?.abort();current.menu.remove();
    current.ta.setAttribute('aria-expanded','false');current.ta.removeAttribute('aria-activedescendant');current.ta.removeAttribute('aria-controls');
    if(restoreFocus&&current.ta.isConnected)current.ta.focus({preventScroll:true});
  }
  function wikiRange(ta){
    if(ta.selectionStart!==ta.selectionEnd)return null;
    const caret=ta.selectionStart,before=ta.value.slice(0,caret),start=before.lastIndexOf('[[');if(start<0)return null;
    const query=before.slice(start+2);if(query.length>120||/[\[\]\n|]/.test(query))return null;
    let fence='';for(const line of before.split('\n')){const match=line.match(/^\s*(`{3,}|~{3,})/);if(match){if(!fence)fence=match[1];else if(match[1][0]===fence[0]&&match[1].length>=fence.length)fence=''}}
    if(fence||(before.slice(before.lastIndexOf('\n')+1).match(/(?<!\\)`/g)||[]).length%2)return null;
    const rest=ta.value.slice(caret),closing=rest.indexOf(']]'),tail=closing>=0?rest.slice(0,closing):'';
    return {start,end:closing>=0&&!/[\[\]\n|]/.test(tail)?caret+closing+2:caret,query};
  }
  function caretPoint(ta){
    const rect=ta.getBoundingClientRect(),style=getComputedStyle(ta),mirror=document.createElement('div');
    for(const prop of ['fontFamily','fontSize','fontWeight','fontStyle','lineHeight','letterSpacing','padding','border','boxSizing','tabSize','direction'])mirror.style[prop]=style[prop];
    Object.assign(mirror.style,{position:'absolute',visibility:'hidden',whiteSpace:'pre-wrap',overflowWrap:'break-word',width:ta.offsetWidth+'px',left:'0',top:'0'});
    mirror.textContent=ta.value.slice(0,ta.selectionStart);const marker=document.createElement('span');marker.textContent='.';mirror.append(marker);document.body.append(mirror);
    const scale=rect.width/ta.offsetWidth||1,point={left:rect.left+(marker.offsetLeft-ta.scrollLeft)*scale,top:rect.top+(marker.offsetTop-ta.scrollTop)*scale,line:(parseFloat(style.lineHeight)||22)*scale};mirror.remove();return point;
  }
  function positionCompletion(){
    const current=completion;if(!current)return;if(!current.ta.isConnected){closeCompletion();return}
    const zoom=parseFloat(document.documentElement.style.zoom)||1,point=current.picker?(()=>{const r=current.button.getBoundingClientRect();return {left:r.left,top:r.bottom,line:0}})():caretPoint(current.ta);
    const width=Math.min(400,innerWidth/zoom-24),height=current.menu.offsetHeight||260,available=innerHeight/zoom;
    current.menu.style.width=width+'px';current.menu.style.left=Math.max(12,Math.min(point.left/zoom,innerWidth/zoom-width-12))+'px';
    const below=(point.top+point.line)/zoom+5;
    current.menu.style.top=Math.max(8,Math.min(below+height>available-12?point.top/zoom-height-5:below,available-height-12))+'px';
  }
  function chooseReference(index){
    const current=completion,doc=current?.rows[index];if(!doc)return;
    const {ta,range,snapshot}=current;if(!ta.isConnected||ta.value!==snapshot){closeCompletion(true);return}
    const title=String(doc.title||'未命名文档').replace(/[\r\n]/g,' ').replace(/\|/g,'｜').replace(/\]\]/g,'］］');
    const text='[['+doc.id+'|'+title+']]';closeCompletion();ta.focus({preventScroll:true});ta.setSelectionRange(range.start,range.end);
    // Chromium's native insertText preserves undo history; other engines retain a safe fallback.
    if(!document.execCommand('insertText',false,text))ta.setRangeText(text,range.start,range.end,'end');
    ta.dispatchEvent(new Event('input',{bubbles:true}));
  }
  function highlightCompletion(index){
    const current=completion;if(!current||!current.rows.length)return;current.index=(index+current.rows.length)%current.rows.length;
    all('[data-reference-option]',current.menu).forEach((button,i)=>{button.setAttribute('aria-selected',String(i===current.index));if(i===current.index){current.ta.setAttribute('aria-activedescendant',button.id);button.scrollIntoView({block:'nearest'})}});
  }
  function completionKey(event){
    if(!completion||event.isComposing||event.keyCode===229)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeCompletion(true);return}
    if(event.key==='ArrowDown'||event.key==='ArrowUp'){if(completion.rows.length){event.preventDefault();event.stopPropagation();highlightCompletion(completion.index+(event.key==='ArrowDown'?1:-1))}}
    if((event.key==='Enter'||event.key==='Tab')&&completion.rows.length){event.preventDefault();event.stopPropagation();chooseReference(completion.index)}
  }
  function createCompletion(ta,range,picker=false){
    closeCompletion();const menu=document.createElement('div');menu.className='document-reference-completion';menu.id='document-reference-completion';
    menu.innerHTML=(picker?'<label>插入引用<input id="document-reference-search" type="search" autocomplete="off" placeholder="搜索文献、笔记等资料的标题或关键词"></label>':'<div class="reference-completion-heading">选择引用</div>')+'<div class="reference-completion-results" role="listbox" aria-label="引用候选项"></div><div class="reference-completion-help">↑↓ 选择 · Enter 插入 · Esc 关闭</div>';
    document.body.append(menu);const current={ta,range,picker,menu,button:q('[data-md="wiki"]'),rows:[],index:0,snapshot:ta.value};completion=current;
    ta.setAttribute('aria-controls','document-reference-completion');ta.setAttribute('aria-expanded','true');
    menu.addEventListener('pointerdown',event=>{if(event.target.closest('[data-reference-option]'))event.preventDefault()});
    if(picker){const input=q('input',menu);input.value=range.query;input.addEventListener('input',()=>searchCompletion(input.value));input.addEventListener('keydown',completionKey);input.focus()}
    positionCompletion();return current;
  }
  function searchCompletion(query){
    const current=completion;if(!current)return;clearTimeout(current.timer);current.controller?.abort();const seq=++completionSeq;
    current.rows=[];current.ta.removeAttribute('aria-activedescendant');q('.reference-completion-results',current.menu).innerHTML='<div class="reference-status" role="status">正在查找资料…</div>';positionCompletion();
    current.timer=setTimeout(async()=>{
      current.controller=new AbortController();
      try{
        const params=new URLSearchParams({scope:'reference',q:query.trim(),page:'1',page_size:'30',paged:'1'}),data=await json('/api/docs?'+params,current.controller.signal);
        if(completion!==current||completionSeq!==seq||!current.ta.isConnected)return;
        const rows=Array.isArray(data)?data:data.items||[],needle=query.trim().toLocaleLowerCase();
        current.rows=rows.filter(doc=>doc.id!==window.ERWCurrentDoc).sort((a,b)=>Number(b.title.toLocaleLowerCase().includes(needle))-Number(a.title.toLocaleLowerCase().includes(needle))).slice(0,20);current.index=0;
        const results=q('.reference-completion-results',current.menu);
        results.innerHTML=current.rows.length?current.rows.map((doc,i)=>'<button type="button" role="option" tabindex="-1" id="reference-option-'+i+'" data-reference-option="'+i+'" aria-selected="'+(i===0)+'"><span class="reference-result-kind">'+esc(kinds[doc.kind]||doc.kind)+'</span><span><strong>'+esc(doc.title)+'</strong><small>'+esc([...(doc.projects?.length?doc.projects:doc.project?[doc.project]:[]),doc.status].filter(Boolean).join(' · ')||'未关联项目')+'</small></span></button>').join(''):'<div class="reference-status">没有找到资料，请换一个关键词</div>';
        all('[data-reference-option]',results).forEach(button=>button.onclick=()=>chooseReference(+button.dataset.referenceOption));
        if(current.rows.length)current.ta.setAttribute('aria-activedescendant','reference-option-0');positionCompletion();
      }catch(error){if(error.name!=='AbortError'&&completion===current&&completionSeq===seq){q('.reference-completion-results',current.menu).innerHTML='<div class="reference-status reference-error">搜索失败：'+esc(error.message)+'</div>';positionCompletion()}}
    },160);
  }
  function updateCompletion(ta){
    if(ta._referenceComposing)return;
    const range=wikiRange(ta);if(!range){if(completion?.ta===ta&&!completion.picker)closeCompletion();return}
    if(!completion||completion.ta!==ta||completion.picker)createCompletion(ta,range);
    completion.range=range;completion.snapshot=ta.value;searchCompletion(range.query);
  }
  function openPicker(ta){
    if(!ta)return;const range=wikiRange(ta)||{start:ta.selectionStart,end:ta.selectionEnd,query:ta.value.slice(ta.selectionStart,ta.selectionEnd).slice(0,120)};
    createCompletion(ta,range,true);searchCompletion(range.query);
  }
  function bindEditor(ta){
    if(!ta||ta.dataset.referenceCompletionBound)return;ta.dataset.referenceCompletionBound='true';
    ta.setAttribute('aria-autocomplete','list');ta.setAttribute('aria-haspopup','listbox');
    if(completion&&completion.ta!==ta)closeCompletion();if(peek&&peek.sourceId!==window.ERWCurrentDoc)closePreview(false);
    ta.addEventListener('input',()=>updateCompletion(ta));
    ta.addEventListener('compositionstart',()=>{ta._referenceComposing=true;closeCompletion()});ta.addEventListener('compositionend',()=>{ta._referenceComposing=false;updateCompletion(ta)});
    ta.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.shiftKey&&event.key.toLowerCase()==='k'){event.preventDefault();event.stopPropagation();openPicker(ta);return}completionKey(event)});
    ta.addEventListener('click',()=>updateCompletion(ta));ta.addEventListener('scroll',positionCompletion);
  }
  function close(){closeCompletion();closePreview(false)}
  document.addEventListener('pointerdown',event=>{if(completion&&!completion.menu.contains(event.target)&&event.target!==completion.ta&&!event.target.closest('[data-md="wiki"]'))closeCompletion()});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.defaultPrevented&&!event.isComposing&&event.keyCode!==229&&peek){event.preventDefault();closePreview()}});
  window.addEventListener('resize',()=>{positionCompletion();positionPreview()});window.addEventListener('scroll',positionPreview,{passive:true});
  window.addEventListener('focus',()=>all('[data-reference-preview-bound]').forEach(root=>validate(root,true)));
  window.ERWDocReferences={bindEditor,bindPreview,openPicker,close,invalidate};
})();
