/* 日历 · 插件面板 v1.0.1
 *
 * 一个脚本登记两个自登记点（内核只加载一次 nav[0] 的 mount）：
 *   ① 侧栏导航页「日历」（核心工作组，待办之后）——月历 + 逾期/今日/近期清单；
 *   ② **顶栏槽位角标**（nav[].slot = "topbar"）——逾期/今日数量常驻可见。
 * 样式全部落在 [data-plugin="milestone-calendar"] 内。
 */
(function () {
  'use strict';

  var ID = 'milestone-calendar';
  if (window.__erwCalendarLoaded) return;      // 防御：脚本被重复注入时不要二次注册
  window.__erwCalendarLoaded = true;

  function el(sel, root) { return (root || document).querySelector(sel); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function toast(m, e) { if (typeof window.ERWToast === 'function') window.ERWToast(m, e); else console.log('[' + ID + '] ' + m); }
  function api(path, body) {
    var f = window.erwFetch || window.fetch;
    var init = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined;
    return f('/api/plugins/' + ID + '/' + path, init).then(function (r) { return r.json(); });
  }
  function ymd(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }

  var DATA = null;

  /* ---------------------------------------------------------------- 顶栏角标 */

  function paintBadge(box, data) {
    var c = (data && data.counts) || {};
    var overdue = c.overdue || 0, today = c.today || 0;
    if (!overdue && !today) {
      box.innerHTML = '<span class="mc-badge calm" title="没有逾期或今日到期的项">✓ 到期</span>';
      box.title = '没有逾期或今日到期的项（点开侧栏「日历」看明细）';
      return;
    }
    box.innerHTML = (overdue ? '<span class="mc-badge bad" title="逾期未完成">⚠ ' + overdue + '</span>' : '')
      + (today ? '<span class="mc-badge warn" title="今天到期">◔ ' + today + '</span>' : '');
    box.title = '逾期 ' + overdue + ' · 今日到期 ' + today + '（点开侧栏「日历」看明细）';
    box.onclick = function () { location.hash = '#' + ID; };
  }

  function refreshBadge(box) {
    api('agenda').then(function (data) { if (box.isConnected) paintBadge(box, data); })
      .catch(function () { /* 静默：角标失败不该影响页面 */ });
  }

  /* ---------------------------------------------------------------- 页面 */

  function taskRow(item) {
    var due = item.due || '（无日期）';
    var tail = item.overdue_days ? '<span class="mc-late">逾期 ' + item.overdue_days + ' 天</span>'
      : (item.days_left === 0 ? '<span class="mc-today">今天</span>'
        : (item.days_left > 0 ? '<span class="mc-muted">还有 ' + item.days_left + ' 天</span>' : ''));
    return '<li><span class="mc-kind">' + esc(item.kind_label) + '</span>'
      + '<span class="mc-title">' + esc(item.title) + '</span>'
      + (item.project ? '<span class="mc-muted">' + esc(item.project) + '</span>' : '')
      + '<span class="mc-due">' + esc(due) + '</span>' + tail + '</li>';
  }

  function bucketHtml(title, items, cls) {
    if (!items.length) return '';
    return '<div class="mc-block"><div class="mc-block-head ' + cls + '">' + title + ' · ' + items.length + '</div>'
      + '<ul class="mc-list">' + items.map(taskRow).join('') + '</ul></div>';
  }

  function monthGrid(data) {
    var today = new Date(data.today + 'T00:00:00');
    var first = new Date(today.getFullYear(), today.getMonth(), 1);
    var start = new Date(first);
    start.setDate(1 - ((first.getDay() + 6) % 7));       // 从周一开始
    var byDay = {};
    ['overdue', 'today', 'soon', 'later'].forEach(function (k) {
      (data.buckets[k] || []).forEach(function (it) {
        if (!it.due) return;
        (byDay[it.due] = byDay[it.due] || []).push(it);
      });
    });
    var cells = [];
    for (var i = 0; i < 42; i++) {
      var d = new Date(start); d.setDate(start.getDate() + i);
      var key = ymd(d);
      var items = byDay[key] || [];
      var cls = ['mc-cell'];
      if (d.getMonth() !== today.getMonth()) cls.push('out');
      if (key === data.today) cls.push('today');
      if (items.length) cls.push('has');
      cells.push('<div class="' + cls.join(' ') + '" data-mc-day="' + key + '">'
        + '<span class="mc-daynum">' + d.getDate() + '</span>'
        + (items.length ? '<span class="mc-dots">' + items.slice(0, 4).map(function (it) {
            return '<i class="' + (it.kind === 'todo' ? 'dot-todo' : 'dot-ms') + '" title="' + esc(it.title) + '"></i>';
          }).join('') + (items.length > 4 ? '<em>+' + (items.length - 4) + '</em>' : '') + '</span>' : '')
        + '</div>');
    }
    return '<div class="mc-cal"><div class="mc-week">' + ['一', '二', '三', '四', '五', '六', '日']
      .map(function (w) { return '<span>' + w + '</span>'; }).join('')
      + '</div><div class="mc-grid">' + cells.join('') + '</div>'
      + '<div class="mc-legend"><i class="dot-ms"></i>里程碑<i class="dot-todo"></i>待办'
      + '<span class="mc-muted">点某天看当天明细</span></div></div>';
  }

  function renderDay(key) {
    if (!DATA) return;
    var all = [];
    ['overdue', 'today', 'soon', 'later'].forEach(function (k) { all = all.concat(DATA.buckets[k] || []); });
    var items = all.filter(function (it) { return it.due === key; });
    el('#mc-day').innerHTML = '<div class="mc-block-head">' + esc(key) + ' · ' + items.length + ' 项</div>'
      + (items.length ? '<ul class="mc-list">' + items.map(taskRow).join('') + '</ul>'
                      : '<div class="mc-muted">这天没有到期项。</div>');
  }

  function renderPage(data) {
    DATA = data;
    var c = data.counts || {};
    el('#mc-summary').innerHTML = '<span class="mc-chip bad">逾期 ' + (c.overdue || 0) + '</span>'
      + '<span class="mc-chip warn">今日 ' + (c.today || 0) + '</span>'
      + '<span class="mc-chip">' + data.lookahead_days + ' 天内 ' + (c.soon || 0) + '</span>'
      + '<span class="mc-chip calm">无日期 ' + (c.undated || 0) + '</span>'
      + '<span class="mc-muted">今天 ' + esc(data.today) + '</span>';
    el('#mc-body').innerHTML = monthGrid(data)
      + bucketHtml('逾期未完成', data.buckets.overdue || [], 'bad')
      + bucketHtml('今天到期', data.buckets.today || [], 'warn')
      + bucketHtml(data.lookahead_days + ' 天内', data.buckets.soon || [], '')
      + bucketHtml('无日期（待安排）', (data.buckets.undated || []).slice(0, 20), '');
    Array.prototype.slice.call(el('#mc-body').querySelectorAll('[data-mc-day]')).forEach(function (cell) {
      cell.onclick = function () { renderDay(cell.dataset.mcDay); };
    });
  }

  function render(main) {
    main.innerHTML = ''
      + '<section class="card card-pad mc-card">'
      +   '<div class="card-kicker">CALENDAR</div>'
      +   '<h3>日历</h3>'
      +   '<p class="row-meta">里程碑与待办的到期情况：逾期 / 今天 / 近期一目了然，顶栏还有常驻角标。'
      +     '（不做系统通知——内核没有通知通道；常驻角标比会漏的弹窗可靠。）</p>'
      +   '<div class="mc-summary" id="mc-summary"></div>'
      +   '<div class="mc-actions"><button class="secondary-btn" id="mc-refresh" type="button">刷新</button>'
      +     '<label class="mc-muted">近期窗口 <input id="mc-days" type="number" min="1" max="90" value="7"> 天'
      +     '<button class="secondary-btn" id="mc-save" type="button">保存</button></label></div>'
      +   '<div id="mc-day"></div>'
      +   '<div id="mc-body"></div>'
      + '</section>';

    function load() {
      api('agenda').then(function (data) {
        renderPage(data);
        if (el('#mc-days')) el('#mc-days').value = data.lookahead_days;
      }).catch(function (e) { toast('读取失败：' + e.message, true); });
    }
    el('#mc-refresh').onclick = load;
    el('#mc-save').onclick = function () {
      api('config', { lookahead_days: Number(el('#mc-days').value) || 7 })
        .then(function () { toast('已保存'); load(); })
        .catch(function (e) { toast('保存失败：' + e.message, true); });
    };
    load();
  }

  if (!window.ERWPanels) return;

  window.ERWPanels.register({
    id: ID,
    group: 'core',
    before: 'agent',
    label: '日历',
    icon: '▦',
    eyebrow: 'PLAN',
    title: '日历',
    render: function (main) { render(main); },
  });

  window.ERWPanels.register({
    id: ID + '-badge',
    slot: 'topbar',
    label: '到期',
    renderSlot: function (box) {
      box.classList.add('mc-badge-box');
      paintBadge(box, null);
      refreshBadge(box);
      /* 每 5 分钟自刷一次；切回标签页也刷（完成待办后回来即更新） */
      setInterval(function () { if (box.isConnected) refreshBadge(box); }, 5 * 60 * 1000);
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden && box.isConnected) refreshBadge(box);
      });
    },
  });
})();
