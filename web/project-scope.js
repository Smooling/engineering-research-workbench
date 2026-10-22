/* Searchable, keyboard-accessible project scope picker shared by planning and graph. */
(() => {
  'use strict';
  let sequence = 0;
  const el = (tag, cls, text) => { const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n; };
  function mount(root, options={}) {
    root.replaceChildren();root.classList.add('project-scope');
    const id='project-scope-'+(++sequence), trigger=el('button','project-scope-trigger'), copy=el('span','project-scope-copy');
    trigger.type='button';trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',id);
    copy.append(el('small','',options.label||'项目范围'),el('strong','','全部项目'));
    trigger.append(el('span','project-scope-icon','▱'),copy,el('span','project-scope-chevron','⌄'));
    const popup=el('div','project-scope-popup'),search=el('input','project-scope-search'),list=el('div','project-scope-options');
    popup.hidden=true;search.type='search';search.placeholder='搜索项目名称…';search.setAttribute('aria-label','搜索项目');search.setAttribute('role','combobox');search.setAttribute('aria-autocomplete','list');search.setAttribute('aria-controls',id);
    list.id=id;list.setAttribute('role','listbox');list.setAttribute('aria-label',options.label||'项目范围');popup.append(search,list);root.append(trigger,popup);
    let names=[],value=options.value||'',cursor=0,rows=[],destroyed=false;
    function paint(){
      const q=search.value.trim().toLocaleLowerCase();rows=['',...names].filter(name=>(name||'全部项目').toLocaleLowerCase().includes(q));cursor=Math.max(0,Math.min(cursor,rows.length-1));list.replaceChildren();
      rows.forEach((name,index)=>{
        const b=el('button','project-scope-option'),title=el('span','',name||'全部项目');b.type='button';b.id=id+'-'+index;b.setAttribute('role','option');b.setAttribute('aria-selected',String(name===value));b.tabIndex=-1;b.title=name||'全部项目';b.classList.toggle('is-cursor',cursor===index);
        b.append(title,el('span','project-scope-check',name===value?'✓':''));b.onclick=()=>{setValue(name);close(true);options.onChange?.(name)};list.append(b);
      });
      if(!rows.length)list.append(el('div','project-scope-empty','没有匹配的项目'));
      if(rows.length){search.setAttribute('aria-activedescendant',id+'-'+cursor);list.children[cursor]?.scrollIntoView({block:'nearest'})}else search.removeAttribute('aria-activedescendant');
    }
    function setValue(name){value=names.includes(name)?name:'';const label=copy.querySelector('strong');label.textContent=value?(window.ERWResearchUI?.projectLabel(value)||value):'全部项目';trigger.title=value||'全部项目';trigger.setAttribute('aria-label',(options.label||'项目范围')+'：'+(value||'全部项目'));if(!popup.hidden)paint()}
    function setOptions(items){names=[...new Set((items||[]).map(String).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));setValue(value)}
    function close(focus=false){popup.hidden=true;trigger.setAttribute('aria-expanded','false');search.setAttribute('aria-expanded','false');if(focus&&!destroyed)trigger.focus()}
    function open(){search.value='';cursor=Math.max(0,['',...names].indexOf(value));popup.hidden=false;trigger.setAttribute('aria-expanded','true');search.setAttribute('aria-expanded','true');paint();search.focus()}
    trigger.onclick=()=>popup.hidden?open():close(true);
    trigger.onkeydown=e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();open()}};
    search.oninput=()=>{cursor=0;paint()};
    popup.onkeydown=e=>{
      if(e.isComposing)return;
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();cursor=e.key==='Home'?0:e.key==='End'?rows.length-1:Math.max(0,Math.min(rows.length-1,cursor+(e.key==='ArrowDown'?1:-1)));paint()}
      else if(e.key==='Enter'){e.preventDefault();list.children[cursor]?.click()}
      else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true)}
    };
    const outside=e=>{if(!root.contains(e.target))close()};
    const blur=()=>queueMicrotask(()=>{if(!destroyed&&!root.contains(document.activeElement))close()});
    document.addEventListener('pointerdown',outside);root.addEventListener('focusout',blur);
    setOptions(options.names||[]);
    return {setValue,setOptions,destroy(){destroyed=true;document.removeEventListener('pointerdown',outside);root.removeEventListener('focusout',blur);root.replaceChildren()}};
  }
  window.ERWProjectScope={mount};
})();
