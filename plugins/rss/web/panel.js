/* RSS 科研资讯面板 · 插件 rss v1.0.0
 *
 * 从 web/app.js 搬出：`renderNews`（资讯列表 + 源筛选 + 刷新 + 诊断）与设置页的
 * `sourceRow` / `wireSourceRows` / 「资讯源」编辑区（第 1237 行的那个 tab）。
 *
 * 两处有意的变化（PLUGIN_SPEC §11.2「差异必须显式声明」）：
 * 1. 资讯源设置从「设置页的一个 tab」改为**本页内联**（点「资讯源设置」展开）——
 *    插件自己拥有 UI，内核不再知道「资讯源」这个概念；
 * 2. 接口从 `/api/rss`、`/api/config/rss` 改为 `/api/plugins/rss/feed`、`/api/plugins/rss/config`。
 *
 * 自登记（§6.3）：导航项、页头、渲染函数都由本文件声明；容器带 `data-plugin="rss"`，
 * 与插件自带样式的作用域（PLUGIN_SPEC §2）一致。
 */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var esc = function (v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  function api(url, opts) {
    var init = Object.assign({}, opts || {}, { headers: { 'Content-Type': 'application/json' } });
    if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
    return (window.erwFetch || fetch)(url, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error((d && (d.message || d.error)) || ('HTTP ' + r.status));
        return d;
      });
    });
  }
  function toast(message, error) {
    if (typeof window.ERWToast === 'function') { window.ERWToast(message, error); return; }
    var stack = $('#toast-stack');
    if (!stack) return;
    var el = document.createElement('div');
    el.className = 'toast' + (error ? ' error' : '');
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }
  function fmtTime(s) {
    if (!s) return '—';
    try { return new Date(s).toLocaleString('zh-CN', { hour12: false }); } catch (e) { return s; }
  }

  function sourceRow(s, i) {
    return `<div class="source-row"><input class="search-input" data-rss-name value="${esc(s.name || '')}" placeholder="名称">`
      + `<input class="search-input" data-rss-url value="${esc(s.url || '')}" placeholder="https://example.com/feed.xml">`
      + `<label class="source-enable"><input type="checkbox" data-rss-enable ${s.enabled !== false ? 'checked' : ''}> 启用</label>`
      + `<button class="ghost-btn danger" data-rss-del="${i}">删除</button></div>`;
  }
  function wireSourceRows() {
    $$('[data-rss-del]').forEach(function (b) {
      b.onclick = function () { b.closest('.source-row').remove(); };
    });
  }

  function settingsHtml(cfg) {
    var sources = (cfg && cfg.sources) || [];
    return `<section class="rss-settings card card-pad" id="rss-settings-panel">
      <div class="card-head"><div><div class="card-kicker">RSS SOURCES</div><h3>资讯源</h3></div>
      <button class="secondary-btn" id="rss-add">＋ 添加</button></div>
      <div id="rss-list">${sources.map(function (s, i) { return sourceRow(s, i); }).join('')}</div>
      <div class="field" style="max-width:260px;margin-top:10px"><label>每源最大条数</label>
      <input id="rss-limit" type="number" value="${(cfg && cfg.max_items_per_source) || 12}"></div>
      <div style="margin-top:14px"><button class="primary-btn" id="rss-save">保存资讯配置</button></div></section>`;
  }

  function wireSettings() {
    wireSourceRows();
    var add = $('#rss-add');
    if (add) {
      add.onclick = function () {
        $('#rss-list').insertAdjacentHTML('beforeend', sourceRow({ name: '新资讯源', url: '', enabled: true }, $$('.source-row').length));
        wireSourceRows();
      };
    }
    var save = $('#rss-save');
    if (save) {
      save.onclick = async function () {
        var sources = $$('.source-row').map(function (r) {
          return { name: $('[data-rss-name]', r).value, url: $('[data-rss-url]', r).value, enabled: $('[data-rss-enable]', r).checked };
        });
        try {
          await api('/api/plugins/rss/config', {
            method: 'POST',
            body: { sources: sources, max_items_per_source: +$('#rss-limit').value || 12 },
          });
          toast('资讯配置已保存');
          load(true);
        } catch (e) { toast(e.message, true); }
      };
    }
  }

  var state = { route: 'news', showSettings: false, loading: false };
  /* v261009.1 · 上次抓取结果与配置：切「资讯源设置」、点源筛选、切页面都**只重绘、不重新抓取**。
     此前这三个动作都会 await 一整轮抓取（离线时 6 个源逐个超时），点了像没反应。 */
  var lastData = null;
  var lastCfg = null;

  function statusHtml() {
    var data = lastData;
    if (!data) return '';
    var filter = localStorage.getItem('newsFilter') || '';
    var sources = data.sources || [];
    if (!sources.length) return '';
    return '<div class="rss-status-grid"><div class="rss-status ' + (!filter ? 'ok active' : 'ok pickable') + '" data-news-src="" title="显示全部资讯源"><strong>≡ 全部</strong><span>' + (data.items || []).length + ' 条</span></div>'
      + sources.map(function (x) {
          var pickable = x.ok && (x.count || 0) > 0;
          var sel = filter && filter === x.source ? ' active' : '';
          return '<div class="rss-status ' + (pickable ? 'ok pickable' : (x.ok ? 'ok' : 'bad')) + sel + '"'
            + (pickable ? ' data-news-src="' + esc(x.source) + '" title="点击只看该资讯源的文章"' : '')
            + '><strong>' + (x.ok ? '✓' : '!') + ' ' + esc(x.source || 'RSS') + '</strong><span>'
            + (x.ok ? ((x.count || 0) + ' 条' + (x.fallback ? ' · 已启用备用接口' : '')) : esc(x.error || '获取失败'))
            + '</span></div>';
        }).join('') + '</div>';
  }

  function bodyHtml() {
    var data = lastData || {};
    var filter = localStorage.getItem('newsFilter') || '';
    var stale = data.stale ? '<div class="rss-alert warn"><strong>当前显示缓存内容</strong><span>本次刷新未能访问任何资讯源；旧内容没有被空结果覆盖。</span></div>' : '';
    var failure = !(data.items || []).length && (data.errors || []).length
      ? '<div class="rss-alert danger"><strong>资讯源全部获取失败</strong><span>这通常是网络 / DNS / 代理或源站连接问题。空失败结果不会再缓存，下一次强制刷新会立即重试。</span><details><summary>查看诊断</summary>'
        + data.errors.map(function (e) {
            return '<div class="rss-error"><b>' + esc(e.source || '') + '</b><code>' + esc(e.error || '') + '</code>'
              + (e.attempts || []).map(function (a) { return '<small>' + esc(a) + '</small>'; }).join('') + '</div>';
          }).join('') + '</details></div>' : '';
    var items = (data.items || []).filter(function (n) { return !filter || n.source === filter; });
    return '<div class="card card-pad" data-plugin="rss"><div class="card-head"><div><div class="card-kicker">RSS / INFORMATION</div><h3>资讯</h3>'
      + '<div class="row-meta">' + (!data.updated && !data.refresh_failed_at ? '尚无内容' : (data.stale ? '缓存更新' : '最近抓取') + ' ' + fmtTime(data.updated || data.refresh_failed_at))
      + (state.loading ? ' · 正在抓取…' : '')
      + (filter ? ' · 只看「' + esc(filter) + '」' : '') + '</div></div>'
      + '<div style="display:flex;gap:8px"><button class="secondary-btn" id="news-settings">资讯源设置</button>'
      + '<button class="primary-btn" id="news-refresh"' + (state.loading ? ' disabled' : '') + '>' + (state.loading ? '抓取中…' : '强制刷新') + '</button></div></div>'
      + stale + failure + statusHtml()
      + (state.showSettings ? settingsHtml(lastCfg) : '')   /* v261009.2 · 设置放在列表**上方**：
          放在 72 张卡片下面时，点按钮后设置出现在屏幕外，看起来像「点了没反应」 */
      + '<div class="news-grid">' + (state.loading && !items.length ? '<div class="empty">正在抓取资讯源…</div>' : (items.length
          ? items.map(function (n) {
              return '<article class="card news-card"><div class="news-meta">' + esc(n.source) + ' · ' + esc(n.published || '') + '</div>'
                + '<h3><a href="' + esc(n.url) + '" target="_blank" rel="noopener">' + esc(n.title) + '</a></h3>'
                + '<p>' + esc(n.summary || '') + '</p></article>';
            }).join('')
          : '<div class="empty">' + (filter ? '该资讯源暂无条目，点击上方「≡ 全部」查看其他内容。' : '当前没有可显示的资讯。请查看上方源状态与诊断信息。') + '</div>'))
      + '</div></div>';
  }

  function paint() {
    if (state.route !== 'news') return;
    var main = $('#main');
    if (!main) return;
    main.innerHTML = bodyHtml();
    $$('#main .rss-status[data-news-src]').forEach(function (el) {
      el.onclick = function () {
        var cur = localStorage.getItem('newsFilter') || '';
        localStorage.setItem('newsFilter', cur === el.dataset.newsSrc ? '' : el.dataset.newsSrc);
        paint();   /* 只重绘，不再跑一遍抓取 */
      };
    });
    var refresh = $('#news-refresh');
    if (refresh) refresh.onclick = function () { load(true); };
    var settings = $('#news-settings');
    if (settings) settings.onclick = function () {
      state.showSettings = !state.showSettings;
      if (state.showSettings && !lastCfg) loadCfg().then(function () { paint(); reveal(); });
      else { paint(); if (state.showSettings) reveal(); }
    };
    if (state.showSettings) wireSettings();
  }

  /* 展开设置后把它滚到可见处：列表很长时设置在上方也可能在视野外 */
  function reveal() {
    var panel = $('#rss-settings-panel');
    if (panel && panel.scrollIntoView) {
      try { panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e) { panel.scrollIntoView(); }
    }
  }

  async function loadCfg() {
    try { lastCfg = await api('/api/plugins/rss/config'); } catch (e) { lastCfg = lastCfg || { sources: [] }; }
    return lastCfg;
  }

  async function load(force) {
    if (state.route !== 'news') return;
    if (lastData) paint();             /* 有旧内容就先画出来（含设置面板），不吃网络延迟 */
    else { state.loading = true; paint(); }
    if (!lastCfg) await loadCfg();
    state.loading = true;
    paint();
    try {
      lastData = await api('/api/plugins/rss/feed' + (force ? '?force=1' : ''));
      state.loading = false;
      if (state.route !== 'news') return;
      paint();
    } catch (e) {
      state.loading = false;
      if (state.route !== 'news') return;
      $('#main').innerHTML = '<div class="card card-pad" data-plugin="rss"><div class="card-head"><div><div class="card-kicker">RSS / INFORMATION</div><h3>资讯</h3></div>'
        + '<div style="display:flex;gap:8px"><button class="secondary-btn" id="news-settings">资讯源设置</button>'
        + '<button class="secondary-btn" id="news-refresh">重试</button></div></div>'
        + '<div class="rss-alert danger"><strong>资讯接口调用失败</strong><span>' + esc(e.message) + '</span></div>'
        + (state.showSettings ? settingsHtml(lastCfg) : '') + '</div>';
      $('#news-refresh').onclick = function () { load(true); };
      $('#news-settings').onclick = function () {
        state.showSettings = !state.showSettings;
        if (state.showSettings && !lastCfg) loadCfg().then(function () { load(false); });
        else load(false);
      };
      if (state.showSettings) { wireSettings(); reveal(); }
    }
  }

  function render(main) {
    state.route = 'news';
    state.showSettings = false;
    /* 内存里留着的上次结果先画（切回资讯页立刻有内容），随后再刷新一次 */
    if (lastData) paint();
    load(false);
  }

  if (window.ERWPanels) {
    window.ERWPanels.register({
      id: 'news', group: 'core',
      label: '资讯', icon: '◎', eyebrow: 'CORE WORK', title: '资讯',
      render: function (main) { render(main); },
    });
  }
})();
