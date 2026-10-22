/* 外部接入授权 · 内核模块（v261009.38）
 *
 * 往「设置」里加一个 tab：谁可以改知识库。
 * 内核自带的 Agent 写工具走草稿闸门；外部通道（MCP 客户端 / 插件）此前没有闸门，这里给它们
 * 一个**默认拒绝、显式授权**的开关。
 *
 * 与插件无关：本模块是内核自带设置项（和 plugin-manager.js 一样自登记 settingsTab，不动 app.js）。
 */
(function () {
  'use strict';

  var ID = 'external-access';

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function api(path, options) {
    return (window.erwFetch || window.fetch)('/api' + path, options).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }
  function toast(m, e) { if (typeof window.ERWToast === 'function') window.ERWToast(m, e); else console.log(m); }

  function itemHtml(item) {
    return '<label class="ea-row' + (item.value ? ' on' : '') + '" data-ea-row="' + esc(item.id) + '">'
      + '<span class="ea-switch"><input type="checkbox" data-ea-flag="' + esc(item.id) + '"'
      + (item.value ? ' checked' : '') + '></span>'
      + '<span class="ea-text"><b>' + esc(item.label) + '</b>'
      + '<span class="ea-detail">' + item.detail.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>') + '</span>'
      + '<span class="ea-risk">⚠ ' + esc(item.risk) + '</span></span></label>';
  }

  function render(root) {
    root.innerHTML = '<div class="card-head"><div><div class="card-kicker">EXTERNAL ACCESS</div>'
      + '<h3>外部接入</h3>'
      + '<div class="row-meta">管的是「谁可以改知识库」：内核自带 Agent 的写操作一律走草稿确认（不可关闭），'
      + '这里授权的是**外部通道**——MCP 客户端与插件。</div></div>'
      + '<button class="secondary-btn" id="ea-reload">重新读取</button></div>'
      + '<div id="ea-body"><div class="empty">正在读取授权状态…</div></div>';

    root.querySelector('#ea-reload').onclick = function () { load(root); };
    load(root);
  }

  function load(root) {
    var body = root.querySelector('#ea-body');
    api('/external-access').then(function (data) {
      var flags = data.flags || {};
      body.innerHTML = ''
        + '<div class="ea-status">'
        +   '<span class="ea-chip ' + (flags.mcp_write ? 'on' : 'off') + '">MCP 写入：'
        +     (flags.mcp_write ? '已授权' : '只读（默认）') + '</span>'
        +   '<span class="ea-chip ' + (flags.plugin_write ? 'on' : 'off') + '">插件写入：'
        +     (flags.plugin_write ? '已授权（默认）' : '只读') + '</span>'
        +   (data.note ? '<span class="ea-note">' + esc(data.note) + '</span>' : '')
        + '</div>'
        + (data.items || []).map(itemHtml).join('')
        + '<div class="ea-foot"><span class="row-meta">配置：<code>' + esc(data.path || '') + '</code></span>'
        +   '<span class="row-meta">只读操作（检索、读条目、看统计）永远允许；授权只影响写入。</span></div>';

      Array.prototype.forEach.call(body.querySelectorAll('[data-ea-flag]'), function (box) {
        box.onchange = function () {
          var payload = {};
          payload[box.dataset.eaFlag] = box.checked;
          api('/external-access', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }).then(function (out) {
            toast((out.changed || []).join('；') || '没有变化');
            load(root);
          }).catch(function (e) { toast('保存失败：' + e.message, true); box.checked = !box.checked; });
        };
      });
    }).catch(function (e) {
      body.innerHTML = '<div class="ea-error">读取失败：' + esc(e.message) + '</div>';
    });
  }

  if (!window.ERWPanels) return;
  window.ERWPanels.register({
    id: ID,
    label: '外部接入',
    settingsTab: {
      id: ID,
      label: '外部接入',
      render: function (container) { render(container); },
    },
  });
})();
