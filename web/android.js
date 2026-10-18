/* Android-only navigation and file affordances; desktop UI retains its own host. */
(() => {
  'use strict';
  const root = document.documentElement;
  if (root.dataset.platform !== 'android') return;
  const $ = selector => document.querySelector(selector);
  const small = matchMedia('(max-width: 820px)');
  let installed = false;
  function drawer(open) {
    root.dataset.androidDrawer = String(open);
    const sidebar = $('.sidebar');
    sidebar?.setAttribute('aria-hidden', String(small.matches && !open));
    if (sidebar) sidebar.inert = small.matches && !open;
    $('.main-shell').inert = small.matches && open;
    $('#android-nav').inert = small.matches && open;
    $('#sidebar-toggle')?.setAttribute('aria-expanded', String(open));
    if (open) $('#android-drawer-close')?.focus();
  }
  function enhance() {
    const editor = $('#doc-editor:not(.empty-editor)');
    root.dataset.androidEditor = String(!!editor);
    if (editor && !$('#android-doc-back')) {
      const back = document.createElement('button');
      back.id = 'android-doc-back';back.className = 'ghost-btn';back.textContent = '‹ 返回条目列表';
      back.onclick = () => window.ERWNav.backToList();
      editor.prepend(back);
      // Keep edit/preview tabs available while avoiding two full editors on a phone.
      if (small.matches) editor.querySelector('[data-edit-mode="edit"]')?.click();
    }
    document.querySelectorAll('#android-nav [data-android-route]').forEach(button => {
      const active = root.dataset.route === button.dataset.androidRoute;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');else button.removeAttribute('aria-current');
    });
  }
  function install() {
    if (installed) return;
    installed = true;
    const scrim = document.createElement('button');
    scrim.id = 'android-drawer-scrim';scrim.ariaLabel = '关闭导航菜单';scrim.onclick = () => drawer(false);
    document.body.append(scrim);
    const close = document.createElement('button');
    close.id = 'android-drawer-close';close.className = 'icon-btn';close.textContent = '×';close.ariaLabel = '关闭导航菜单';
    close.onclick = () => drawer(false);$('.sidebar .brand').append(close);
    const nav = document.createElement('nav');nav.id = 'android-nav';nav.ariaLabel = '常用功能';
    for (const [route, icon, label] of [['overview','▦','概览'],['todos','✓','待办'],['notes','✎','笔记'],['more','☰','更多']]) {
      const button = document.createElement('button');button.type = 'button';button.dataset.androidRoute = route;
      const glyph = document.createElement('span');glyph.textContent = icon;glyph.setAttribute('aria-hidden','true');
      const text = document.createElement('span');text.textContent = label;button.append(glyph,text);
      button.onclick = () => route === 'more' ? drawer(true) : window.ERWNav.navigate(route);
      nav.append(button);
    }
    document.body.append(nav);
    document.addEventListener('click', event => {
      if (small.matches && event.target.closest('#sidebar-toggle')) {
        event.preventDefault();event.stopImmediatePropagation();drawer(root.dataset.androidDrawer !== 'true');
      }
      if (event.target.closest('.sidebar [data-route]')) drawer(false);
    }, true);
    window.addEventListener('hashchange', enhance);
    new MutationObserver(enhance).observe($('#main'), {childList:true, subtree:true});
    small.addEventListener('change', () => drawer(false));
    drawer(false);enhance();
  }
  window.ERWAndroid = {
    handleBack() {
      if (root.dataset.androidDrawer === 'true') {drawer(false);return true;}
      if (window.ERWDialog?.isOpen()) {document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;}
      if (!$('#modal-backdrop').classList.contains('hidden')) {$('#modal-close').click();return true;}
      const fab = $('#erw-fab-panel');
      if (fab && !fab.hidden) {$('#fab-close')?.click();return true;}
      if (small.matches && root.dataset.androidEditor === 'true') {window.ERWNav.backToList();return true;}
      if ((location.hash || '#overview') !== '#overview') {window.ERWNav.navigate('overview');return true;}
      return false;
    }
  };
  window.addEventListener('workbench:ready', install, {once:true});
})();
