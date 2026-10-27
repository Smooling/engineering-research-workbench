/* Native controls are enabled only by pywebview's local bridge. */
(() => {
  'use strict';
  let initialized = false;
  let nativeState = {};
  const CHROME_HEIGHT = 48;
  window.ERWDesktop = {...window.ERWDesktop, chromeHeight:CHROME_HEIGHT};
  const root = document.documentElement;
  const call = async (name, ...args) => {
    try {
      const result = await window.pywebview.api[name](...args);
      if (result && typeof result === 'object') applyState(result);
      return result;
    } catch (error) {
      console.error('Desktop window control failed:', error);
    }
  };
  function applyState(value) {
    nativeState = {...nativeState, ...value};
    root.dataset.windowMaximized = String(!!nativeState.maximized);
    root.dataset.windowHidden = String(!!nativeState.hidden);
    document.querySelector('#desktop-caption').textContent = nativeState.title || '科研工作台';
    const max = document.querySelector('#desktop-maximize');
    max.title = max.ariaLabel = nativeState.maximized ? '还原窗口' : '最大化窗口';
    const close = document.getElementById('desktop-close');
    close.title = close.ariaLabel = nativeState.close_action === 'quit' ? '退出应用' :
      nativeState.tray_available ? '关闭窗口并隐藏到托盘' : '关闭窗口并最小化到任务栏';
    document.querySelector('#desktop-minimize').title = '最小化到任务栏';
  }
  function syncChrome() {
    const zoom = parseFloat(root.style.zoom) || 1;
    const height = `${CHROME_HEIGHT / zoom}px`;
    if (root.style.getPropertyValue('--desktop-titlebar-height') !== height) {
      root.style.setProperty('--desktop-titlebar-height', height);
    }
    const scale = String(1 / zoom);
    if(root.style.getPropertyValue('--desktop-chrome-scale')!==scale)root.style.setProperty('--desktop-chrome-scale',scale);
  }
  async function initialize() {
    if (initialized || !window.pywebview?.api?.desktop_get_state) return;
    initialized = true;
    root.dataset.desktop = 'true';
    document.getElementById('desktop-titlebar').hidden = false;
    syncChrome();
    new MutationObserver(syncChrome).observe(root, {attributes:true, attributeFilter:['style']});
    const syncTheme = () => {
      if (window.pywebview.api.desktop_set_theme) call('desktop_set_theme', root.dataset.theme || 'light');
    };
    new MutationObserver(syncTheme).observe(root, {attributes:true, attributeFilter:['data-theme']});
    syncTheme();
    window.addEventListener('resize', syncChrome);
    window.addEventListener('workbench:window-state', event => applyState(event.detail));
    document.getElementById('desktop-close').onclick = () => call('desktop_close');
    document.getElementById('desktop-minimize').onclick = () => call('desktop_minimize');
    document.getElementById('desktop-maximize').onclick = () => call('desktop_toggle_maximize');
    document.getElementById('desktop-search').onclick = () => document.getElementById('global-search-btn')?.click();
    document.getElementById('desktop-titlebar').ondblclick = event => {
      if (!event.target.closest('button,input,select,.dropdown')) call('desktop_toggle_maximize');
    };
    // Move live controls to preserve handlers, IDs and preference state.
    const topbar=document.querySelector('#app .topbar');
    const tools=document.getElementById('desktop-page-tools');
    const mountTools=()=>{
      const history=topbar.querySelector('#navigation-history');if(history)tools.append(history);
      const heading=topbar.querySelector('.page-heading');
      if(heading){heading.classList.add('desktop-drag-region');tools.append(heading)}
      const toggle=topbar.querySelector('#sidebar-toggle');
      if(toggle)tools.prepend(toggle);
      const actions=topbar.querySelector('.top-actions');
      if(actions)document.getElementById('desktop-titlebar').insertBefore(actions,document.getElementById('desktop-save-status'));
      const reload=document.querySelector('.reload-wrap');
      const slot=document.getElementById('desktop-reload-slot');
      if(reload&&reload.parentElement!==slot)slot.append(reload);
      const sync=document.querySelector('.sync-wrap'),syncSlot=document.getElementById('desktop-sync-slot');
      if(sync&&syncSlot&&sync.parentElement!==syncSlot)syncSlot.append(sync);
    };
    mountTools();
    new MutationObserver(mountTools).observe(topbar,{childList:true});
    const borders = document.createElement('div');
    borders.id = 'desktop-resize-borders';
    for (const edge of ['n','e','s','w','ne','nw','se','sw']) {
      const handle = document.createElement('div');
      handle.dataset.desktopResize = edge;
      handle.setAttribute('aria-hidden', 'true');
      handle.onpointerdown = event => {
        if (event.button !== 0 || nativeState.maximized) return;
        event.preventDefault();
        event.stopPropagation();
        call('desktop_resize', edge);
      };
      borders.append(handle);
    }
    document.body.append(borders);
    let lastDirty, lastOpen, lastDraft;
    const heading=document.getElementById('page-title');
    const syncHeading=()=>{syncEditorStatus()};
    if(heading)new MutationObserver(syncHeading).observe(heading,{subtree:true,childList:true,characterData:true});
    syncHeading();
    function syncEditorStatus(){
      const dirty=!!window.ERWDesktop?.hasUnsavedChanges?.(), open=!!window.ERWDesktop?.documentOpen?.(),draft=!!window.ERWDesktop?.documentDraft?.();
      if(dirty===lastDirty&&open===lastOpen&&draft===lastDraft)return;
      lastDirty=dirty;lastOpen=open;lastDraft=draft;
      const status=document.getElementById('desktop-save-status');status.hidden=!open;status.dataset.dirty=String(dirty);
      status.querySelector('span').textContent=dirty?'未保存':draft?'新建草稿':'已保存';
    }
    document.addEventListener('input',syncEditorStatus);
    document.addEventListener('click',()=>queueMicrotask(syncEditorStatus));
    window.addEventListener('workbench:editor-state',syncEditorStatus);
    syncEditorStatus();
    await call('desktop_get_state');
    window.dispatchEvent(new Event('resize'));
  }
  const ready = () => document.readyState === 'loading'
    ? document.addEventListener('DOMContentLoaded', initialize, {once:true}) : initialize();
  window.addEventListener('pywebviewready', ready);
  ready();
})();
