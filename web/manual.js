/* 使用手册 · 内核模块（v261009.30）
 *
 * 自登记侧栏「系统 → 使用手册」页：左侧章节目录 + 右侧正文。
 * 与插件不同，它是**内核自带文档的阅读器**——零插件时也能读（章节来自 /api/manual）。
 *
 * 约定：
 *   · 正文一律走内核接缝 `window.ERWMarkdown.renderInto`（与条目编辑器同一套 marked + DOMPurify + hljs + mermaid）；
 *   · 图片走内核路由 `/manual-file/...`（只读 `docs/manual/**`，路径安全在服务端收口）；
 *   · 站内章节链接（`02-xxx.md`）在本页直接切换，不整页跳转；
 *   · 指向仓库其它文件的链接（如 `../../mcp/README.md`）在应用内打不开，明确提示而不是静默 404。
 */
(function () {
  'use strict';

  var ID = 'manual';

  function el(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function toast(m, e) { if (typeof window.ERWToast === 'function') window.ERWToast(m, e); else console.log('[' + ID + '] ' + m); }
  function api(path) {
    return (window.erwFetch || window.fetch)('/api' + path).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function normalize(md) {
    /* 手册里的图片是相对路径 `img/x.png`，改成内核路由；绝对路径不会被内核的 normalizePaths 改写 */
    return String(md || '').replace(/\]\(img\//g, '](/manual-file/img/');
  }

  var STATE = { chapters: [], current: '' };

  function tocHtml() {
    return STATE.chapters.map(function (c) {
      var kb = Math.max(1, Math.round(c.bytes / 1024));
      /* 前置 `·` 与内核「文件夹」页树里的文件行同一符号（目录用 ▱、文件用 ·）；
         体积只留在 title 提示里，不在行内堆信息（照 .settings-nav / 树行的干净口径） */
      return '<button type="button" class="manual-toc-item' + (c.id === STATE.current ? ' active' : '')
        + '" data-manual-chapter="' + esc(c.id) + '" title="' + esc(c.title) + '（' + kb + ' KB）">'
        + '<span class="manual-toc-icon">·</span>'
        + '<span class="manual-toc-title">' + esc(c.title) + '</span></button>';
    }).join('');
  }

  function paintToc(root) {
    var box = el('#manual-toc', root);
    if (!box) return;
    box.innerHTML = tocHtml();
    $$('[data-manual-chapter]', box).forEach(function (btn) {
      btn.onclick = function () { loadChapter(btn.dataset.manualChapter, root); };
    });
    var active = el('.manual-toc-item.active', box);
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
  }

  function neighbors() {
    var index = STATE.chapters.findIndex(function (c) { return c.id === STATE.current; });
    return {
      prev: index > 0 ? STATE.chapters[index - 1] : null,
      next: index >= 0 && index < STATE.chapters.length - 1 ? STATE.chapters[index + 1] : null,
    };
  }

  function paintFooter(root) {
    var nav = neighbors();
    var box = el('#manual-foot', root);
    if (!box) return;
    box.innerHTML = '<button type="button" class="secondary-btn" id="manual-prev"' + (nav.prev ? '' : ' disabled')
      + '>‹ ' + esc(nav.prev ? nav.prev.title : '上一章') + '</button>'
      + '<span class="row-meta">' + esc(STATE.current) + '</span>'
      + '<button type="button" class="secondary-btn" id="manual-next"' + (nav.next ? '' : ' disabled')
      + '>' + esc(nav.next ? nav.next.title : '下一章') + ' ›</button>';
    if (nav.prev) el('#manual-prev', box).onclick = function () { loadChapter(nav.prev.id, root); };
    if (nav.next) el('#manual-next', box).onclick = function () { loadChapter(nav.next.id, root); };
  }

  function wireLinks(root) {
    $$('#manual-body a', root).forEach(function (a) {
      var href = a.getAttribute('href') || '';
      if (/^https?:/i.test(href)) { a.target = '_blank'; a.rel = 'noopener'; return; }
      if (href.startsWith('#') || href.startsWith('/')) return;
      /* 渲染管线会把中文文件名百分号编码（`01-快速开始.md` → `01-%E5%BF%AB….md`），
         比较前必须解码，否则站内章节链接会被误判成"仓库文件"（实测踩到） */
      var decoded = href;
      try { decoded = decodeURIComponent(href); } catch (e) { /* 保留原样 */ }
      var base = decoded.replace(/^\.\//, '').replace(/\.md(#.*)?$/, '');
      var hit = STATE.chapters.find(function (c) { return c.id === base; });
      if (hit) { a.onclick = function (e) { e.preventDefault(); loadChapter(hit.id, root); }; return; }
      a.onclick = function (e) {
        e.preventDefault();
        toast('这条链接指向仓库里的文件（' + decoded + '），在编辑器/仓库里查看', true);
      };
    });
  }

  function loadChapter(id, root) {
    STATE.current = id;
    paintToc(root);
    var body = el('#manual-doc', root) || el('#manual-body', root);
    body.innerHTML = '<div class="empty">正在加载…</div>';
    api('/manual/' + encodeURIComponent(id)).then(function (data) {
      if (!window.ERWMarkdown) { body.innerHTML = '<pre class="manual-raw">' + esc(data.markdown) + '</pre>'; return; }
      return window.ERWMarkdown.renderInto(body, normalize(data.markdown)).then(function () {
        wireLinks(root);
      });
    }).then(function () {
      paintFooter(root);
      var pane = el('#manual-pane', root);
      if (pane) pane.scrollTop = 0;
      try { history.replaceState(null, '', '#' + ID + '/' + id); } catch (e) { /* 忽略 */ }
    }).catch(function (e) {
      body.innerHTML = '<div class="manual-error">这一章读不出来：' + esc(e.message) + '</div>';
    });
  }

  function render(main) {
    main.innerHTML = ''
      + '<section class="manual-layout" data-plugin="' + ID + '">'
      +   '<aside class="card manual-side">'
      +     '<div class="card-kicker">MANUAL</div>'
      +     '<h3>使用手册</h3>'
      +     '<p class="row-meta">内核自带功能的教程。插件功能见各自 README。</p>'
      +     '<div class="manual-toc" id="manual-toc"><div class="empty compact">正在读目录…</div></div>'
      +   '</aside>'
      +   '<section class="card manual-pane" id="manual-pane">'
      +     '<div class="manual-body" id="manual-body"><div class="manual-doc" id="manual-doc">'
      +       '<div class="empty">正在加载…</div></div></div>'
      +     '<div class="manual-foot" id="manual-foot"></div>'
      +   '</section>'
      + '</section>';

    api('/manual').then(function (data) {
      STATE.chapters = data.chapters || [];
      if (!STATE.chapters.length) {
        el('#manual-toc', main).innerHTML = '<div class="empty compact">没找到手册（docs/manual/）</div>';
        el('#manual-body', main).innerHTML = '<div class="manual-error">docs/manual/ 里没有章节文件</div>';
        return;
      }
      var hash = (location.hash || '').split('/');
      var want = hash[0] === '#' + ID && hash[1] ? hash[1] : '';
      var first = STATE.chapters.find(function (c) { return c.id === want; }) || STATE.chapters[0];
      loadChapter(first.id, main);
    }).catch(function (e) {
      el('#manual-toc', main).innerHTML = '<div class="empty compact">目录读取失败</div>';
      el('#manual-body', main).innerHTML = '<div class="manual-error">' + esc(e.message) + '</div>';
    });
  }

  if (!window.ERWPanels) return;
  window.ERWPanels.register({
    id: ID,
    group: 'system',
    before: 'settings',
    label: '使用手册',
    icon: '☰',
    eyebrow: 'MANUAL',
    title: '使用手册',
    render: function (main) { render(main); },
  });
})();
