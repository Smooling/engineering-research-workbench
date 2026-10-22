(() => {
  'use strict';

  const STORAGE_KEY = 'sidebarWidth';
  const DEFAULT_WIDTH = 168;
  const MIN_WIDTH = 52;
  const MAX_WIDTH = 200;
  const MOBILE_QUERY = '(max-width: 820px)';

  const clamp = value => Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, Math.round(value)));

  function readStoredWidth() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if(stored===null)return DEFAULT_WIDTH;
    const value = Number(stored);
    return Number.isFinite(value) ? clamp(value) : DEFAULT_WIDTH;
  }

  function currentZoom() {
    const inline = Number.parseFloat(document.documentElement.style.zoom);
    if (Number.isFinite(inline) && inline > 0) return inline;
    const computed = Number.parseFloat(getComputedStyle(document.documentElement).zoom);
    return Number.isFinite(computed) && computed > 0 ? computed : 1;
  }

  function applyWidth(value, handle, persist = false) {
    const width = clamp(value);
    document.documentElement.style.setProperty('--sidebar', width + 'px', 'important');
    const mode = width < 90 ? 'icon' : width < 140 ? 'compact' : 'full';
    document.documentElement.dataset.sidebarMode = mode;
    if (handle) handle.setAttribute('aria-valuenow', String(width));
    if (persist) localStorage.setItem(STORAGE_KEY, String(width));
    return width;
  }

  function initSidebarResize() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar || sidebar.querySelector('.sidebar-resizer')) return;

    const handle = document.createElement('div');
    handle.className = 'sidebar-resizer';
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', 'vertical');
    handle.setAttribute('aria-label', '调整侧边栏宽度');
    handle.setAttribute('aria-valuemin', String(MIN_WIDTH));
    handle.setAttribute('aria-valuemax', String(MAX_WIDTH));
    handle.tabIndex = 0;
    sidebar.appendChild(handle);

    let width = applyWidth(readStoredWidth(), handle, false);
    let dragging = false;
    let pointerId = null;

    const measureFromPointer = event => {
      const zoom = currentZoom();
      const left = sidebar.getBoundingClientRect().left;
      return clamp((event.clientX - left) / zoom);
    };

    const finishDrag = () => {
      if (!dragging) return;
      dragging = false;
      pointerId = null;
      document.documentElement.classList.remove('sidebar-resizing');
      applyWidth(width, handle, true);
      requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    };

    handle.addEventListener('pointerdown', event => {
      if (window.matchMedia(MOBILE_QUERY).matches || event.button !== 0) return;
      dragging = true;
      pointerId = event.pointerId;
      document.documentElement.classList.add('sidebar-resizing');
      try { handle.setPointerCapture(pointerId); } catch {}
      event.preventDefault();
    });

    handle.addEventListener('pointermove', event => {
      if (!dragging || event.pointerId !== pointerId) return;
      width = applyWidth(measureFromPointer(event), handle, false);
    });

    handle.addEventListener('pointerup', finishDrag);
    handle.addEventListener('pointercancel', finishDrag);
    handle.addEventListener('lostpointercapture', finishDrag);

    handle.addEventListener('dblclick', event => {
      event.preventDefault();
      width = applyWidth(DEFAULT_WIDTH, handle, true);
      requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    });

    handle.addEventListener('keydown', event => {
      if (window.matchMedia(MOBILE_QUERY).matches) return;
      let next = width;
      const step = event.shiftKey ? 20 : 8;
      if (event.key === 'ArrowLeft') next -= step;
      else if (event.key === 'ArrowRight') next += step;
      else if (event.key === 'Home') next = MIN_WIDTH;
      else if (event.key === 'End') next = MAX_WIDTH;
      else return;
      event.preventDefault();
      width = applyWidth(next, handle, true);
      requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
    });

    window.addEventListener('storage', event => {
      if (event.key !== STORAGE_KEY) return;
      width = applyWidth(readStoredWidth(), handle, false);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebarResize, { once: true });
  } else {
    initSidebarResize();
  }
})();
