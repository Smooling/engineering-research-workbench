(() => {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const CARD_SELECTOR = '.heatmap-card';
  const observed = new WeakMap();
  const settleState = new WeakMap();

  function parseIsoLocal(value) {
    const m = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    return {
      year: Number(m[1]),
      month: Number(m[2]),
      day: Number(m[3]),
    };
  }

  function ensureDividerLayer(stage) {
    let layer = stage.querySelector(':scope > .heatmap-month-divider-layer');
    if (layer) return layer;
    layer = document.createElementNS(SVG_NS, 'svg');
    layer.classList.add('heatmap-month-divider-layer');
    layer.setAttribute('aria-hidden', 'true');
    layer.setAttribute('focusable', 'false');
    layer.setAttribute('preserveAspectRatio', 'none');
    stage.appendChild(layer);
    return layer;
  }

  function visibleMonthStarts(cells) {
    const visible = cells
      .map((cell, index) => ({ cell, index, date: parseIsoLocal(cell.dataset.date) }))
      .filter(item => item.date && !item.cell.classList.contains('outside'));

    if (!visible.length) return [];

    const first = visible[0].date;
    const firstMonthKey = `${first.year}-${first.month}`;

    return visible.filter(item => {
      const d = item.date;
      if (d.day !== 1) return false;
      return `${d.year}-${d.month}` !== firstMonthKey;
    });
  }

  function geometrySignature(card) {
    const stage = card.querySelector('.heatmap-stage');
    const grid = card.querySelector('.heatmap-cells');
    const cells = grid ? [...grid.querySelectorAll('.heat-cell[data-date]')] : [];
    if (!stage || !grid || !cells.length) return '';

    const gridRect = grid.getBoundingClientRect();
    const firstRect = cells[0].getBoundingClientRect();
    const lastRect = cells[cells.length - 1].getBoundingClientRect();
    const computed = getComputedStyle(grid);

    const round = n => Math.round(Number(n || 0) * 100) / 100;
    return [
      round(gridRect.left), round(gridRect.top), round(gridRect.width), round(gridRect.height),
      round(firstRect.left), round(firstRect.top), round(firstRect.width), round(firstRect.height),
      round(lastRect.left), round(lastRect.top),
      computed.columnGap, computed.rowGap,
      getComputedStyle(card).getPropertyValue('--heat-cell-width').trim(),
      getComputedStyle(card).getPropertyValue('--heat-cell-height').trim(),
      getComputedStyle(card).getPropertyValue('--heat-gap-x').trim(),
      getComputedStyle(card).getPropertyValue('--heat-gap-y').trim(),
      cells.length,
    ].join('|');
  }

  function alignMonthDividers(card) {
    const stage = card.querySelector('.heatmap-stage');
    const grid = card.querySelector('.heatmap-cells');
    if (!stage || !grid) return;

    const cells = [...grid.querySelectorAll('.heat-cell[data-date]')];
    if (!cells.length) return;

    const monthStarts = visibleMonthStarts(cells);
    const layer = ensureDividerLayer(stage);

    const gridRect = grid.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const zoom = Number.parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
    const width = gridRect.width / zoom;
    const height = gridRect.height / zoom;
    if (!(width > 0 && height > 0)) {
      layer.replaceChildren();
      return;
    }

    /* Anchor the SVG to the final, actually rendered heat-cell grid. */
    const layerLeft = (gridRect.left - stageRect.left) / zoom;
    const layerTop = (gridRect.top - stageRect.top) / zoom;
    layer.style.left = `${layerLeft}px`;
    layer.style.top = `${layerTop}px`;
    layer.style.width = `${width}px`;
    layer.style.height = `${height}px`;
    layer.setAttribute('width', String(width));
    layer.setAttribute('height', String(height));
    layer.setAttribute('viewBox', `0 0 ${width} ${height}`);

    const computed = getComputedStyle(grid);
    const columnGap = Number.parseFloat(computed.columnGap) || 0;
    const rowGap = Number.parseFloat(computed.rowGap) || 0;
    const tolerance = 0.75;

    const paths = monthStarts.map(({ cell, date }) => {
      const rect = cell.getBoundingClientRect();
      const cellLeft = (rect.left - gridRect.left) / zoom;
      const cellTop = (rect.top - gridRect.top) / zoom;

      const xLeft = Math.max(0, cellLeft - columnGap / 2);
      const xRight = Math.min(width, cellLeft + rect.width / zoom + columnGap / 2);
      const y = Math.max(0, cellTop - rowGap / 2);

      const path = document.createElementNS(SVG_NS, 'path');
      path.classList.add('heatmap-month-divider-path');
      path.dataset.month = `${date.year}-${String(date.month).padStart(2, '0')}`;

      if (y <= tolerance) {
        path.setAttribute('d', `M ${xLeft} 0 V ${height}`);
      } else {
        path.setAttribute('d', `M ${xRight} 0 V ${y} H ${xLeft} V ${height}`);
      }
      return path;
    });

    layer.replaceChildren(...paths);
  }

  /*
   * fitResearchHeatmap() updates split heat-cell width/height and gap variables after the card is
   * inserted. Measuring immediately can therefore catch the previous geometry.
   * Wait until the real grid geometry is unchanged for three animation frames,
   * then draw. This reproduces the useful part of a browser zoom/resize without
   * requiring the user to trigger one manually.
   */
  function settleAndAlign(card) {
    if (!card || !card.isConnected) return;

    const previous = settleState.get(card) || { token: 0 };
    const token = previous.token + 1;
    settleState.set(card, { token });

    let lastSignature = '';
    let stableFrames = 0;
    let frameCount = 0;
    const maxFrames = 24;

    const tick = () => {
      requestAnimationFrame(() => {
        const current = settleState.get(card);
        if (!current || current.token !== token || !card.isConnected) return;

        const signature = geometrySignature(card);
        frameCount += 1;

        if (signature && signature === lastSignature) stableFrames += 1;
        else stableFrames = 0;
        lastSignature = signature;

        if ((signature && stableFrames >= 3) || frameCount >= maxFrames) {
          alignMonthDividers(card);
          return;
        }
        tick();
      });
    };

    tick();
  }

  function attach(card) {
    if (!card || observed.has(card)) return;
    card.classList.add('heatmap-divider-v2');

    const stage = card.querySelector('.heatmap-stage');
    const grid = card.querySelector('.heatmap-cells');
    if (!stage || !grid) return;

    let resizeObserver = null;
    if ('ResizeObserver' in window) {
      resizeObserver = new ResizeObserver(() => settleAndAlign(card));
      resizeObserver.observe(stage);
      resizeObserver.observe(grid);
    }

    /* fitResearchHeatmap writes the fitted width/height/gap variables inline on card. */
    const styleObserver = new MutationObserver(mutations => {
      if (mutations.some(m => m.type === 'attributes' && m.attributeName === 'style')) {
        settleAndAlign(card);
      }
    });
    styleObserver.observe(card, { attributes: true, attributeFilter: ['style'] });

    observed.set(card, { resizeObserver, styleObserver });
    settleAndAlign(card);

    /* Delayed safety passes cover debounced fitResearchHeatmap() updates. */
    setTimeout(() => settleAndAlign(card), 100);
    setTimeout(() => settleAndAlign(card), 220);
  }

  function scan() {
    document.querySelectorAll(CARD_SELECTOR).forEach(attach);
  }

  const root = document.getElementById('main') || document.body;
  /* v261009 · A9：文档级 childList 改用共享接缝；下方的属性观察（attributeFilter: style）
     语义不同（只看某张卡片的行内样式），继续自带一个 MutationObserver。 */
  window.ERWDom.onChildList(() => scan(), { root: root });

  window.addEventListener('resize', () => {
    document.querySelectorAll(CARD_SELECTOR).forEach(settleAndAlign);
  }, { passive: true });

  /* Run after the select's own handler has replaced/refitted the heatmap DOM. */
  document.addEventListener('change', event => {
    if (event.target?.id !== 'heatmap-month-select') return;
    setTimeout(() => {
      scan();
      document.querySelectorAll(CARD_SELECTOR).forEach(settleAndAlign);
    }, 0);
    setTimeout(() => document.querySelectorAll(CARD_SELECTOR).forEach(settleAndAlign), 120);
    setTimeout(() => document.querySelectorAll(CARD_SELECTOR).forEach(settleAndAlign), 260);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan, { once: true });
  } else {
    scan();
  }
})();
