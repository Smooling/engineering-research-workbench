/* Android shell. Keep the existing data, editor guards and desktop host intact. */
(() => {
  'use strict';
  const root = document.documentElement;
  if (root.dataset.platform !== 'android') return;
  const $ = selector => document.querySelector(selector);
  const small = matchMedia('(max-width: 1024px)');
  const paths = {
    overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    todos:'M9 6h12 M9 12h12 M9 18h12 M3 6l1 1 2-2 M3 12l1 1 2-2 M3 18l1 1 2-2',
    notes:'M14 3H5v18h14V8 M14 3v5h5 M8 12h8 M8 16h6',
    more:'M4 6h16 M4 12h16 M4 18h16'
  };
  const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]}"/></svg>`;
  let installed = false, scheduled = false, lastRoute = '', returnFocus;
  let viewportHeight = innerHeight, viewportWidth = innerWidth, nativeKeyboard = null;
  function keyboard(visible) {
    root.dataset.androidKeyboard = String(!!visible);
  }
  function resize() {
    // Android 7–10 and browser previews use the resized visual viewport. API 30+
    // also reports actual IME visibility from MainActivity, including rotation.
    const height = window.visualViewport?.height || innerHeight;
    if (Math.abs(innerWidth - viewportWidth) > 80) {viewportHeight = height;viewportWidth = innerWidth;}
    viewportHeight = Math.max(viewportHeight, height);
    const editing = !!document.activeElement?.matches('input:not([type=checkbox]):not([type=radio]),textarea,[contenteditable=true]');
    if (nativeKeyboard === null) keyboard(small.matches && editing && viewportHeight - height > 140);
    root.style.setProperty('--android-height', `${Math.round(height)}px`);
  }
  function drawer(open) {
    open = small.matches && open;
    if (open && root.dataset.androidDrawer !== 'true') returnFocus = document.activeElement;
    root.dataset.androidDrawer = String(open);
    const sidebar = $('.sidebar');
    sidebar?.setAttribute('aria-hidden', String(small.matches && !open));
    if (sidebar) sidebar.inert = small.matches && !open;
    if ($('.main-shell')) $('.main-shell').inert = open;
    if ($('#android-nav')) $('#android-nav').inert = open;
    $('#sidebar-toggle')?.setAttribute('aria-expanded', String(open));
    if (open) $('#android-drawer-close')?.focus();
    else if (returnFocus?.isConnected) {returnFocus.focus({preventScroll:true});returnFocus = null;}
  }
  function button(id, text, action) {
    const el = document.createElement('button');el.type = 'button';el.id = id;
    el.className = 'ghost-btn';el.textContent = text;el.onclick = action;return el;
  }
  function editorStatus() {
    const status = $('#android-save-status');if (!status) return;
    const dirty = window.ERWDesktop?.hasUnsavedChanges();
    const text = dirty ? '未保存' : '已保存';
    if (status.textContent !== text) status.textContent = text;
    status.dataset.dirty = String(!!dirty);
  }
  function enhanceEditor(editor) {
    if (!$('#android-editor-head')) {
      const head = document.createElement('header');head.id = 'android-editor-head';
      head.append(button('android-doc-back','‹ 列表',()=>window.ERWNav.backToList()));
      const status = document.createElement('span');status.id = 'android-save-status';status.setAttribute('aria-live','polite');
      head.append(status);
      // Move the real buttons, preserving the existing save/delete handlers.
      for (const selector of ['#doc-delete','#doc-save']) {const el = $(selector);if(el)head.append(el);}
      editor.prepend(head);
      if (small.matches) editor.querySelector('[data-edit-mode="edit"]')?.click();
    }
    editorStatus();
  }
  function enhanceOverview() {
    const dashboard = $('.overview-dashboard'), top = dashboard?.querySelector(':scope > .overview-top-row');
    if (!top) return;
    const details = document.createElement('details');details.className = 'android-progress';
    const summary = document.createElement('summary');summary.textContent = '科研进展与目标';
    const hint = document.createElement('span');hint.textContent = '热力图 · 学业 · 科研节奏';summary.append(hint);
    details.append(summary,top);
    const rhythm = dashboard.querySelector('.rhythm-card');if (rhythm) top.append(rhythm);
    dashboard.querySelector('.overview-ops-grid')?.after(details);
    try {details.open = localStorage.getItem('androidProgressOpen') === 'true';}catch{}
    details.addEventListener('toggle',()=>{try{localStorage.setItem('androidProgressOpen',String(details.open));}catch{}window.dispatchEvent(new Event('resize'));});
  }
  function agentPane(pane) {
    const layout = $('.agent-layout');if(!layout)return;
    layout.dataset.androidAgentPane = pane;
    const b = $('#android-agent-sessions');if(b)b.textContent = pane === 'sessions' ? '返回对话' : '历史对话';
  }
  function enhanceAgent() {
    const layout = $('.agent-layout');if (!layout || $('#android-agent-bar')) return;
    const bar = document.createElement('div');bar.id = 'android-agent-bar';
    bar.append(button('android-agent-sessions','历史对话',()=>agentPane(layout.dataset.androidAgentPane==='sessions'?'chat':'sessions')),
      button('android-agent-new','＋ 新对话',()=>{$('#agent-new')?.click();agentPane('chat');}));
    layout.prepend(bar);agentPane('chat');
    $('#agent-input')?.setAttribute('placeholder','输入问题，点击发送；回车换行…');
  }
  function pdfPane(pane) {
    const shell = $('.lit-shell');if (!shell) return;
    if (pane !== 'library' && $('#lit-reader-live')?.hidden) return;
    shell.dataset.androidPdfPane = pane;
    shell.querySelectorAll('[data-android-pdf]').forEach(b=>{
      const selected = b.dataset.androidPdf === pane;b.classList.toggle('active', selected);
      b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;
    });
    // Rendering and fit calculations need the selected pane to have a width.
    window.dispatchEvent(new Event('resize'));
  }
  function enhancePdf() {
    const shell = $('.lit-shell');if (!shell) return;
    if (!$('#android-pdf-tabs')) {
      const tabs = document.createElement('div');tabs.id = 'android-pdf-tabs';tabs.setAttribute('role','tablist');tabs.ariaLabel='文献工作区';
      for (const [pane,text] of [['library','文献库'],['reader','阅读'],['side','信息与批注']]) {
        const b = button('',text,()=>pdfPane(pane));b.dataset.androidPdf=pane;b.setAttribute('role','tab');tabs.append(b);
      }
      tabs.addEventListener('keydown',e=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
        const buttons = [...tabs.querySelectorAll('button:not(:disabled)')], index=buttons.indexOf(document.activeElement);
        const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowLeft'?-1:1)+buttons.length)%buttons.length;
        e.preventDefault();buttons[next].click();buttons[next].focus();
      });
      shell.prepend(tabs);pdfPane('library');
    }
    const ready = !$('#lit-reader-live')?.hidden;
    shell.querySelectorAll('[data-android-pdf]:not([data-android-pdf=library])').forEach(b=>b.disabled=!ready);
    const selected = $('.lit-item.active')?.dataset.paper || '';
    if (ready && shell.dataset.androidPaper !== selected) {shell.dataset.androidPaper=selected;pdfPane('reader');}
  }
  function enhance() {
    scheduled = false;
    const editor = $('#doc-editor:not(.empty-editor)');
    root.dataset.androidEditor = String(!!editor);
    root.dataset.androidPage = editor ? 'editor' : $('.lit-shell') ? 'pdf' : $('.agent-layout') ? 'agent' : 'page';
    if(editor)enhanceEditor(editor);
    enhanceOverview();enhanceAgent();enhancePdf();
    const toggle=$('#sidebar-toggle');
    if(toggle&&!toggle.querySelector('svg')){toggle.innerHTML=icon('more');toggle.ariaLabel='打开导航菜单';toggle.title='导航菜单';}
    document.querySelectorAll('#android-nav [data-android-route]').forEach(b=>{
      const active=root.dataset.route===b.dataset.androidRoute || (b.dataset.androidRoute==='more'&&!['overview','todos','notes'].includes(root.dataset.route));
      b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');
    });
    if(lastRoute!==root.dataset.route){lastRoute=root.dataset.route;$('#main').scrollTop=0;}
  }
  function schedule() {if(!scheduled){scheduled=true;requestAnimationFrame(enhance);}}
  function install() {
    if(installed)return;installed=true;
    const scrim=button('android-drawer-scrim','',()=>drawer(false));scrim.ariaLabel='关闭导航菜单';scrim.tabIndex=-1;document.body.append(scrim);
    const close=button('android-drawer-close','×',()=>drawer(false));close.ariaLabel='关闭导航菜单';$('.sidebar .brand').append(close);
    const nav=document.createElement('nav');nav.id='android-nav';nav.ariaLabel='常用功能';
    for(const [route,label] of [['overview','概览'],['todos','待办'],['notes','笔记'],['more','更多']]){
      const b=button('',label,()=>route==='more'?drawer(true):window.ERWNav.navigate(route));b.dataset.androidRoute=route;
      b.innerHTML=`<span class="android-nav-icon">${icon(route)}</span><span>${label}</span>`;nav.append(b);
    }
    document.body.append(nav);
    document.addEventListener('click',e=>{
      if(small.matches&&e.target.closest('#sidebar-toggle')){e.preventDefault();e.stopImmediatePropagation();drawer(root.dataset.androidDrawer!=='true');}
      if(e.target.closest('.sidebar [data-route]'))drawer(false);
      if(e.target.closest('[data-agent-session]'))agentPane('chat');
    },true);
    document.addEventListener('keydown',e=>{
      if(root.dataset.androidDrawer!=='true')return;
      if(e.key==='Escape'){drawer(false);e.preventDefault();e.stopImmediatePropagation();}
      if(e.key==='Tab'){
        const focusable=[...$('.sidebar').querySelectorAll('button,a,input,select')].filter(x=>!x.disabled&&x.getClientRects().length);
        if(e.shiftKey&&document.activeElement===focusable[0]){focusable.at(-1)?.focus();e.preventDefault();}
        else if(!e.shiftKey&&document.activeElement===focusable.at(-1)){focusable[0]?.focus();e.preventDefault();}
      }
    },true);
    document.addEventListener('input',editorStatus);
    window.addEventListener('workbench:editor-state',schedule);
    new MutationObserver(schedule).observe($('#main'),{childList:true,subtree:true,attributes:true,attributeFilter:['hidden']});
    window.addEventListener('resize',resize);window.visualViewport?.addEventListener('resize',resize);
    document.addEventListener('focusin',resize);document.addEventListener('focusout',()=>requestAnimationFrame(resize));
    small.addEventListener('change',()=>{drawer(false);schedule();});
    drawer(false);resize();enhance();
  }
  window.ERWAndroid={
    setKeyboardVisible(visible){nativeKeyboard=!!visible;keyboard(visible);resize();},
    handleBack(){
      if(root.dataset.androidDrawer==='true'){drawer(false);return true;}
      if(window.ERWDialog?.isOpen()){document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;}
      if(!$('#modal-backdrop').classList.contains('hidden')){$('#modal-close').click();return true;}
      const fab=$('#erw-fab-panel');if(fab&&!fab.hidden){$('#fab-close')?.click();return true;}
      if(small.matches&&root.dataset.androidEditor==='true'){window.ERWNav.backToList();return true;}
      if(small.matches&&$('.lit-shell')?.dataset.androidPdfPane!=='library'&&$('.lit-shell')){pdfPane('library');return true;}
      if(small.matches&&$('.agent-layout')?.dataset.androidAgentPane==='sessions'){agentPane('chat');return true;}
      if((location.hash||'#overview')!=='#overview'){window.ERWNav.navigate('overview');return true;}
      return false;
    }
  };
  window.addEventListener('workbench:ready',install,{once:true});
})();
