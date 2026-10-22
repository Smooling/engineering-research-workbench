/* plugin-manager.js · v261009.4 —— 设置 → 插件
 *
 * 一块**插件预览 + 设置**页（本文件是内核模块，但走 §6.3 的自登记扩展点，
 * 不在 app.js 里加分支）：
 *   · 预览：每个插件的状态、版本、来源、类型、权限（带中文说明）、路由、面板、工具、依赖、目录
 *   · 设置：读/写插件**自己的配置接口**（`/api/plugins/<id>/config`）——
 *     内核不解释插件配置的内容，只做转发与展示。插件没提供配置接口时如实说明。
 *   · 启停：写 `System/plugins.json`（**不删文件、不动数据**），后端热重载插件集合。
 *
 * 数据来自 `GET /api/plugins?detail=1`（内核的插件预览接口）。
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

  var PLUGINS = {};   /* id -> 预览信息（配置块据此判断该插件有没有配置接口） */
  var OPEN = {};      /* id -> 配置区是否展开（默认收成一行） */
  var DETAIL = {};    /* id -> 卡片详情（权限/路由/工具/依赖/面板/目录）是否展开 */
  var CFG = {};       /* id -> 已读取的配置（展开/收起之间复用，避免反复请求） */
  var STATE_LABEL = {
    available: ['可用', 'ok'], blocked: ['被阻塞', 'warn'],
    rejected: ['被拒绝', 'bad'], conflict: ['冲突', 'bad'],
  };

  function badge(state) {
    var pair = STATE_LABEL[state] || [state, ''];
    return '<span class="badge ' + pair[1] + '">' + esc(pair[0]) + '</span>';
  }

  function metaRow(label, value) {
    if (!value || (Array.isArray(value) && !value.length)) return '';
    return '<div class="pm-meta-row"><span class="pm-meta-label">' + esc(label) + '</span><span>' + value + '</span></div>';
  }

  function cardHtml(plugin) {
    var hasDetail = plugin.state !== undefined;   /* 旧后端只返回精简清单（无 state/enabled/…） */
    var perms = (plugin.permissions || []).map(function (p) {
      return '<span class="pm-perm" title="' + esc(p.label) + '">' + esc(p.id) + '</span>';
    }).join('');
    var panels = (plugin.nav || []).map(function (n) {
      var where = n.slot ? ('槽位 ' + esc(n.slot)) : '导航页';
      return '<span class="pm-panel">' + esc(n.label) + ' <small>' + where + '</small></span>';
    }).join('') || '<span class="muted">无前端面板</span>';
    /* v261009.7 · 卡片默认只留**一行**：版本号（+ 来源）；权限/路由/工具/依赖/目录/面板
       都收进「详情」，需要时再展开——与配置区的交互一致。 */
    var detailRows = hasDetail
      ? metaRow('权限', perms || '<span class="muted">未声明</span>')
        + metaRow('路由', (plugin.routes || []).map(function (r) { return '<code>' + esc(r) + '</code>'; }).join(' ') || '<span class="muted">无后端接口</span>')
        + metaRow('工具', (plugin.mcp_tools || []).map(function (t) { return '<code>p_' + esc(plugin.id) + '__' + esc(t) + '</code>'; }).join(' ') || '<span class="muted">未注册工具</span>')
        + metaRow('依赖', (plugin.dependencies || []).map(function (d) { return '<code>' + esc(d) + '</code>'; }).join(' ') || '<span class="muted">无</span>')
        + metaRow('面板', panels)
        + metaRow('目录', '<code class="pm-path">' + esc(plugin.dir || '') + '</code>')
      : '<div class="field-help">当前后端只下发了精简清单（' + esc(Object.keys(plugin).join(' / '))
        + '）——权限、路由、工具、目录与启用状态需要新版后端。</div>';
    var open = !!DETAIL[plugin.id];
    /* v261009.10 · 一行摘要里直接写明「**提供什么**」：面板 / 工具 / 路由。
       此前只有「版本 + 来源」，像 litnote 这种**只有工具、没有页面**的插件
       在列表里看不出用途（用户反馈「没看到文献工具插件」）。 */
    var provides = [];
    if (plugin.slot_only) provides.push('顶栏组件');
    else if ((plugin.nav_labels || []).length) provides.push('面板 ' + plugin.nav_labels.join('、'));
    if ((plugin.mcp_tools || []).length) provides.push(plugin.mcp_tools.length + ' 个 AI 工具');
    if ((plugin.routes || []).length) provides.push(plugin.routes.length + ' 条接口');
    if (plugin.has_config_route) provides.push('可配置');
    var providesText = provides.length ? provides.join(' · ') : '纯后端/无扩展点';
    return '<section class="card card-pad pm-card" data-plugin-card="' + esc(plugin.id) + '">'
      + '<div class="card-head"><div><div class="card-kicker">' + esc(plugin.kind || 'plugin') + '</div>'
      + '<h3>' + esc(plugin.name || plugin.id) + ' <small class="muted">' + esc(plugin.id) + '</small></h3>'
      + (plugin.description ? '<div class="row-meta" title="' + esc(plugin.description) + '">' + esc(plugin.description) + '</div>' : '') + '</div>'
      + '<div class="pm-actions">'
      + (hasDetail
          ? '<button type="button" class="badge pm-state-btn" data-plugin-state="' + esc(plugin.id) + '"'
            + ' title="点击' + (plugin.enabled ? '停用' : '启用') + '这个插件">'
            + esc((STATE_LABEL[plugin.state] || [plugin.state, ''])[0]) + '</button>'
          : '<span class="badge">未知</span>')
      + '<label class="pm-switch"' + (hasDetail ? '' : ' title="当前后端不支持启停接口：请重启工作台"') + '>'
      + '<input type="checkbox" data-plugin-toggle="' + esc(plugin.id) + '"'
      + (hasDetail ? (plugin.enabled ? ' checked' : '') : ' disabled') + '> 启用</label></div></div>'
      + (hasDetail && plugin.state !== 'available' && plugin.reason
          ? '<div class="pm-alert"><strong>不可用</strong><span>' + esc(plugin.reason) + (plugin.fix ? '　建议：' + esc(plugin.fix) : '') + '</span></div>' : '')
      + '<button class="pm-row pm-row-toggle" type="button" data-plugin-detail="' + esc(plugin.id) + '"'
      + ' title="展开查看权限 / 路由 / 工具 / 依赖 / 面板 / 目录">'
      + '<span class="pm-row-label">版本</span>'
      + '<code class="pm-row-main">' + esc(plugin.version || '-') + '</code>'
      + '<span class="pm-row-sub">' + esc(providesText) + '</span>'
      + '<span class="pm-row-action">' + (open ? '▾ 收起详情' : '▸ 详情') + '</span></button>'
      + '<div class="pm-detail"' + (open ? '' : ' hidden') + '>' + detailRows + '</div>'
      + '<div class="pm-config" data-plugin-config="' + esc(plugin.id) + '"></div>'
      + (hasDetail && hasPreview(plugin)
          ? '<button class="pm-row pm-row-preview" type="button" data-plugin-preview="' + esc(plugin.id) + '"'
            + ' title="悬停即看演示预览；点击可固定">'
            + '<span class="pm-row-label">预览</span>'
            + '<span class="pm-row-main">' + esc(plugin.preview.summary || '看它能做什么').slice(0, 46) + '</span>'
            + '<span class="pm-row-action">悬停 / 点击</span></button>'
          : '')
      + '</section>';
  }

  function render(root) {
    root.innerHTML = '<div class="card-head"><div><div class="card-kicker">PLUGINS</div><h3>插件</h3>'
      + '<div class="row-meta">插件放在 <code>plugins/</code> 或 <code>&lt;数据根&gt;/plugins/</code> 即被发现；'
      + '停用只改「开不开」，<strong>不删文件、不动数据</strong>。</div></div>'
      + '<div style="display:flex;gap:8px"><button class="secondary-btn" id="pm-reload">重新扫描</button>'
      + '<button class="secondary-btn" id="pm-reload-page">刷新页面</button></div></div>'
      + '<div id="pm-list"><div class="empty">正在读取插件…</div></div>';

    $('#pm-reload').onclick = function () { load(root); };
    $('#pm-reload-page').onclick = function () { location.reload(); };
    wire(root);
    load(root);
  }

  function wire(root) {
    var stale = Object.keys(PLUGINS).length > 0
      && Object.keys(PLUGINS).every(function (id) { return PLUGINS[id].state === undefined; });
    if (!stale) {
      $$('[data-plugin-toggle]', root).forEach(function (box) {
        box.onchange = async function () {
          var id = box.dataset.pluginToggle;
          /* 停用加一道确认：这个开关很小、又在卡片右上角，容易误点（实测发生过一次）。
             启用不需要确认（随时可再关，且不破坏数据）。 */
          if (!box.checked && !confirm('停用插件 ' + id + '？\n\n插件文件、配置与数据都会保留，'
            + '用同一个开关随时可以恢复；停用后它的面板与工具会从界面消失。')) {
            box.checked = true;
            return;
          }
          box.disabled = true;
          try {
            var res = await api('/api/plugin-manager/' + encodeURIComponent(id) + '/enabled',
              { method: 'POST', body: { enabled: box.checked } });
            toast((box.checked ? '已启用 ' : '已停用 ') + id + '（刷新页面后侧栏同步）');
            if (res && res.note) console.info('[plugins] ' + res.note);
          } catch (e) {
            box.checked = !box.checked;
            toast('切换失败：' + e.message, true);
          } finally {
            box.disabled = false;
          }
        };
      });
    }
    /* 状态徽章：点击即启停（此前它只是个徽章，看起来像按钮却点不动——用户反馈） */
    $$('[data-plugin-state]', root).forEach(function (btn) {
      btn.onclick = function (event) {
        event.stopPropagation();
        var box = root.querySelector('[data-plugin-toggle="' + btn.dataset.pluginState + '"]');
        if (!box || box.disabled) { toast('当前后端不支持启停', true); return; }
        box.checked = !box.checked;
        box.dispatchEvent(new Event('change', { bubbles: true }));
      };
    });

    /* 详情展开/收起：只切那一段，不重画整页 */
    $$('[data-plugin-detail]', root).forEach(function (btn) {
      btn.onclick = function () {
        var id = btn.dataset.pluginDetail;
        DETAIL[id] = !DETAIL[id];
        var box = btn.parentElement.querySelector('.pm-detail');
        if (box) box.hidden = !DETAIL[id];
        var act = btn.querySelector('.pm-row-action');
        if (act) act.textContent = DETAIL[id] ? '▾ 收起详情' : '▸ 详情';
      };
    });
    $$('[data-plugin-config]', root).forEach(function (host) {
      paintConfig(host);
    });
    wirePreview(root);
  }

  /* ---------- 演示预览浮层（v261009.27） ----------
     预览内容**由插件自己在 plugin.json 的 preview 里声明**（摘要 / 功能点 / 在哪里找到它 / 截图），
     内核只负责呈现——所以内核仍然不认识任何具体插件，没声明 preview 的插件这一行就不出现。

     交互：鼠标移到插件卡片或「预览」行上就浮出；点击「预览」行**固定**（再点或按 Esc / 点别处解除）；
     浮层贴卡片右侧（放不下就贴下方），滚动时收起，避免遮挡与错位。 */
  var PREVIEW = { id: '', pinned: false, el: null, anchor: null, hideTimer: 0 };

  /* 有内容才算「有预览」：后端可能下发空对象（`{}` 在 JS 里是真值），不能只看字段存在 */
  function hasPreview(plugin) {
    var pv = (plugin && plugin.preview) || null;
    if (!pv) return false;
    return !!(pv.summary || (pv.features || []).length || (pv.screens || []).length);
  }

  function previewHtml(plugin) {
    var pv = plugin.preview || {};
    var shots = (pv.screens || []).map(function (s) {
      return '<a class="pm-shot" href="' + esc(s.url) + '" target="_blank" rel="noopener"'
        + ' title="点击在新标签打开原图">'
        + '<img src="' + esc(s.url) + '" alt="' + esc(plugin.name || plugin.id) + ' 预览截图" loading="lazy">'
        + '</a>';
    }).join('');
    var features = (pv.features || []).length
      ? '<ul class="pm-pv-feats">' + pv.features.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul>'
      : '';
    return '<div class="pm-pv-head"><b>' + esc(plugin.name || plugin.id) + '</b>'
      + badge(plugin.state) + '<code>v' + esc(plugin.version || '-') + '</code>'
      + '<span class="pm-pv-close" data-pv-close="1" title="关闭（Esc）">×</span></div>'
      + (pv.summary ? '<div class="pm-pv-sum">' + esc(pv.summary) + '</div>' : '')
      + (pv.where ? '<div class="pm-pv-where">在哪找：' + esc(pv.where) + '</div>' : '')
      + features
      + (shots ? '<div class="pm-pv-shots">' + shots + '</div>'
              : '<div class="pm-pv-noshot">（插件没提供截图；下面就是它的能力清单）</div>')
      + '<div class="pm-pv-foot">'
      + (plugin.enabled ? '<span class="ok">已启用</span>' : '<span class="warn">未启用</span>——启用后才能看到它的页面/面板')
      + (plugin.mcp_tools && plugin.mcp_tools.length
          ? '　工具：' + plugin.mcp_tools.map(function (t) { return '<code>p_' + esc(plugin.id) + '__' + esc(t) + '</code>'; }).join(' ')
          : '')
      + '</div>';
  }

  function hidePreview() {
    PREVIEW.id = '';
    PREVIEW.pinned = false;
    PREVIEW.anchor = null;
    if (PREVIEW.el) { PREVIEW.el.remove(); PREVIEW.el = null; }
  }

  /** 把浮层贴到卡片右侧（放不下就贴左侧、再不行贴下方），并保证不越出视口。 */
  function positionPreview(box, anchor) {
    var rect = anchor.getBoundingClientRect();
    var w = box.offsetWidth || 380;
    var h = box.offsetHeight || 300;
    var left = rect.right + 12;
    if (left + w > window.innerWidth - 8) left = Math.max(8, rect.left - w - 12);
    if (left < 8) left = 8;
    var top = Math.min(Math.max(8, rect.top), Math.max(8, window.innerHeight - h - 8));
    box.style.left = left + 'px';
    box.style.top = top + 'px';
  }

  /* 滚动时**跟随卡片**而不是直接收起：page.hover()/scrollIntoView 这类程序化滚动
     会先滚动再触发 mouseenter——之前「一滚就收」会让浮层刚建出来就被自己收掉（实测踩到）。 */
  function onPreviewScroll() {
    if (!PREVIEW.el || !PREVIEW.anchor) return;
    var rect = PREVIEW.anchor.getBoundingClientRect();
    if (!PREVIEW.anchor.isConnected || rect.bottom < 0 || rect.top > window.innerHeight) {
      hidePreview();
      return;
    }
    positionPreview(PREVIEW.el, PREVIEW.anchor);
  }

  function showPreview(id, anchor, pinned) {
    var plugin = PLUGINS[id];
    if (!hasPreview(plugin)) return;
    if (PREVIEW.id === id && PREVIEW.pinned && !pinned) return;   // 已固定：悬停不要抢
    if (PREVIEW.el) PREVIEW.el.remove();
    var box = document.createElement('div');
    box.className = 'pm-preview';
    box.innerHTML = previewHtml(plugin);
    document.body.appendChild(box);
    PREVIEW.id = id;
    PREVIEW.pinned = !!pinned || PREVIEW.pinned;
    PREVIEW.el = box;
    PREVIEW.anchor = anchor;
    box.style.width = Math.min(430, Math.max(300, window.innerWidth - 40)) + 'px';
    positionPreview(box, anchor);
    positionPreview(box, anchor);        // 第二遍：拿到真实高度后再夹一次，避免越出视口底部
    box.onmouseenter = function () { clearTimeout(PREVIEW.hideTimer); };
    box.onmouseleave = function () { if (!PREVIEW.pinned) PREVIEW.hideTimer = setTimeout(hidePreview, 160); };
    box.querySelector('[data-pv-close]').onclick = hidePreview;
  }

  function wirePreview(root) {
    window.removeEventListener('scroll', onPreviewScroll, true);
    document.removeEventListener('keydown', onPreviewKey);
    document.removeEventListener('click', onPreviewOutside, true);
    $$('[data-plugin-preview]', root).forEach(function (btn) {
      var id = btn.dataset.pluginPreview;
      var card = btn.closest('.pm-card') || btn;
      var enter = function () { clearTimeout(PREVIEW.hideTimer); if (!PREVIEW.pinned) showPreview(id, card, false); };
      var leave = function () { if (!PREVIEW.pinned) PREVIEW.hideTimer = setTimeout(hidePreview, 220); };
      card.addEventListener('mouseenter', enter);
      card.addEventListener('mouseleave', leave);
      btn.addEventListener('focus', enter);
      btn.onclick = function (event) {
        event.stopPropagation();
        if (PREVIEW.pinned && PREVIEW.id === id) { hidePreview(); return; }
        showPreview(id, card, true);
      };
    });
    window.addEventListener('scroll', onPreviewScroll, true);
    document.addEventListener('keydown', onPreviewKey);
    document.addEventListener('click', onPreviewOutside, true);
  }

  function onPreviewKey(event) { if (event.key === 'Escape') hidePreview(); }

  function onPreviewOutside(event) {
    if (!PREVIEW.el) return;
    if (PREVIEW.el.contains(event.target) || (event.target.closest && event.target.closest('[data-plugin-preview]'))) return;
    hidePreview();
  }

  /* ---------- 配置区：默认**收成一行**，要改再展开（v261009.6） ----------
     一个插件一行摘要，页面不再被大段 JSON 撑长；展开后才拉取配置并显示编辑器。 */
  function configSummary(cfg) {
    var one = JSON.stringify(cfg);
    if (one === undefined) one = String(cfg);
    return one.length > 120 ? one.slice(0, 120) + '…' : one;
  }

  function paintConfig(host) {
    var id = host.dataset.pluginConfig;
    var plugin = PLUGINS[id] || {};
    /* 配置区统一**只有一行**（v261009.6）：标签 + 状态 + 摘要 + 动作都在同一行；
       「内核只做转发」这类说明放进悬停提示，不占版面。 */
    var note = plugin.config_url
      ? '内核只做转发，读写都由插件自己负责（' + plugin.config_url + '）'
      : '配置由插件自己负责';

    if (plugin.state === undefined) {
      /* 旧后端：连状态都没有，配置接口自然也谈不上——如实说明，别猜 */
      host.innerHTML = '<div class="pm-row" title="' + esc(note) + '">'
        + '<span class="pm-row-label">配置</span>'
        + '<span class="pm-row-note">当前后端没有提供插件预览字段，请<b>重启工作台</b>后再看这里。</span></div>';
      return;
    }
    if (!plugin.has_config_route) {
      /* 没有配置接口就直接说明（本来就是一行），不发无谓的请求 */
      var hint = (plugin.nav_labels || []).length
        ? '该插件没有提供配置接口——它的设置在自己的界面里：' + esc(plugin.nav_labels.join('、'))
        : '该插件没有提供配置接口，也不需要配置。';
      host.innerHTML = '<div class="pm-row" title="' + esc(note) + '">'
        + '<span class="pm-row-label">配置</span><span class="pm-row-note">' + hint + '</span></div>';
      return;
    }

    if (!OPEN[id]) {
      var cfg = CFG[id];
      host.innerHTML = '<button class="pm-row pm-row-toggle" type="button" data-config-toggle="' + esc(id) + '" title="' + esc(note) + '">'
        + '<span class="pm-row-label">配置</span>'
        + '<span class="pm-row-state">' + (cfg ? '已读取' : '未展开') + '</span>'
        + '<code class="pm-row-main pm-row-json">' + (cfg ? esc(configSummary(cfg)) : '点右侧展开后读取并编辑') + '</code>'
        + '<span class="pm-row-action">' + (cfg ? '▸ 展开编辑' : '▸ 读取并展开') + '</span></button>';
      $('[data-config-toggle]', host).onclick = function () {
        OPEN[id] = true;
        if (CFG[id]) { paintConfig(host); return; }
        $('.pm-row-state', host).textContent = '读取中…';
        loadCfg(id).then(function () { paintConfig(host); })
          .catch(function (e) {
            OPEN[id] = false;
            host.innerHTML = '<div class="pm-row" title="' + esc(note) + '">'
              + '<span class="pm-row-label">配置</span><span class="pm-row-note">读取配置失败：'
              + esc(e.message) + '（可在插件自己的界面里设置）</span></div>';
          });
      };
      return;
    }

    /* 展开态：**同一行**点一下就收起（不再放一个大「收起」按钮） */
    host.innerHTML = '<button class="pm-row pm-row-toggle pm-row-open" type="button" data-config-toggle="' + esc(id) + '" title="' + esc(note) + '">'
      + '<span class="pm-row-label">配置</span>'
      + '<span class="pm-row-state">已展开</span>'
      + '<span class="pm-row-note">JSON，可直接编辑后保存</span>'
      + '<span class="pm-row-action">▾ 收起</span></button>'
      + '<textarea class="pm-json" data-config-json rows="5" spellcheck="false"></textarea>'
      + '<div class="pm-config-actions">'
      + '<button class="secondary-btn" data-config-reload>重新读取</button>'
      + '<button class="primary-btn" data-config-save>保存配置</button></div>';
    var ta = $('[data-config-json]', host);
    ta.value = JSON.stringify(CFG[id] || {}, null, 2);
    $('[data-config-toggle]', host).onclick = function () {
      OPEN[id] = false;
      paintConfig(host);
    };
    $('[data-config-reload]', host).onclick = function () {
      loadCfg(id, true).then(function (c) {
        ta.value = JSON.stringify(c, null, 2);
        toast('已重新读取');
      }).catch(function (e) { toast(e.message, true); });
    };
    $('[data-config-save]', host).onclick = async function () {
      var parsed;
      try { parsed = JSON.parse(ta.value); }
      catch (e) { toast('JSON 解析失败：' + e.message, true); return; }
      try {
        var saved = await api('/api/plugins/' + encodeURIComponent(id) + '/config', { method: 'POST', body: parsed });
        CFG[id] = (saved && saved.config) ? saved.config : saved;
        OPEN[id] = false;             /* 存完收回一行，回到「默认一条目」 */
        paintConfig(host);
        toast(id + ' 配置已保存');
      } catch (e) { toast('保存失败：' + e.message, true); }
    };
  }

  function loadCfg(id, force) {
    if (CFG[id] && !force) return Promise.resolve(CFG[id]);
    return api('/api/plugins/' + encodeURIComponent(id) + '/config').then(function (cfg) {
      CFG[id] = cfg;
      return cfg;
    });
  }

  /* 单文件包安装结果（内核 §2 解包规则）：结构化下发，前端只负责呈现。
     拒收与冲突必须显示出来——「丢个 zip 进来毫无反应」比报错更难查。 */
  function installHtml(items) {    if (!items || !items.length) return '';
    var rows = items.map(function (it) {
      var bad = it.action === 'rejected' || it.action === 'conflict';
      var good = it.action === 'unpacked' || it.action === 'upgraded';
      var who = it.id ? (it.id + (it.version ? ' v' + it.version : '')) : '';
      return '<li class="' + (bad ? 'bad' : (good ? 'good' : 'flat')) + '">'
        + '<code>' + esc(it.file) + '</code> '
        + esc(it.action_label || it.action)
        + (who ? '：<b>' + esc(who) + '</b>' : '')
        + (it.reason ? '<span>' + esc(it.reason) + '</span>' : '')
        + '</li>';
    }).join('');
    return '<div class="pm-notes"><strong>单文件包（<code>plugins/*.zip</code>）安装结果</strong>'
      + '<ul>' + rows + '</ul></div>';
  }

  /* 其它发现期提示（同名遮蔽、依赖等） */
  function notesHtml(notes) {
    if (!notes || !notes.length) return '';
    return '<div class="pm-notes"><strong>提示</strong><ul>'
      + notes.map(function (n) { return '<li class="flat">' + esc(n) + '</li>'; }).join('')
      + '</ul></div>';
  }

  async function load(root) {
    var list = $('#pm-list', root);
    list.innerHTML = '<div class="empty">正在读取插件…</div>';
    try {
      var data = await api('/api/plugins?detail=1');
      var plugins = data.plugins || [];
      PLUGINS = {};
      plugins.forEach(function (p) { PLUGINS[p.id] = p; });
      var stale = plugins.length > 0 && plugins[0].state === undefined;
      var banner = stale
        ? '<div class="pm-alert"><strong>后端版本较旧，本页信息不完整</strong>'
          + '<span>当前后端只下发了 <code>' + esc(Object.keys(plugins[0]).join(' / ')) + '</code>，'
          + '所以权限、路由、工具、目录与「启用」状态都读不到（勾选框也因此不可用）。'
          + '<b>重启工作台</b>（<code>python server.py</code>）后再打开本页即可。</span></div>'
        : '';
      var blocks = installHtml(data.install) + notesHtml(data.notes);
      if (!plugins.length) {
        list.innerHTML = blocks
          + '<div class="empty">还没有发现任何插件。把插件目录（含 <code>plugin.json</code>）'
          + '或单文件包 <code>&lt;id&gt;-&lt;version&gt;.zip</code> 放进 <code>plugins/</code> 即可。</div>';
        return;
      }
      list.innerHTML = '<div class="row-meta" style="margin-bottom:10px">共 ' + plugins.length + ' 个 · 内核 '
        + esc(data.core_version || '-') + ' · 未启用则其工具与面板都不出现（I10）</div>'
        + banner
        + blocks
        + plugins.map(cardHtml).join('');
      wire(root);
    } catch (e) {
      list.innerHTML = '<div class="pm-alert"><strong>插件清单读取失败</strong><span>' + esc(e.message) + '</span></div>';
    }
  }

  if (window.ERWPanels) {
    window.ERWPanels.register({
      id: 'plugin-manager',
      label: '插件',
      settingsTab: {
        id: 'plugins',
        label: '插件',
        render: function (container) { render(container); },
      },
    });
  }
})();
