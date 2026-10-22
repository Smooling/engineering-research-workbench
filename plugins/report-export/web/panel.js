/* 报告导出 · 插件面板 v1.0.0
 *
 * 自登记一个侧栏导航页（内核不认识本插件，加它不需要改内核一行）。
 * 只通过 window.ERW* 接缝接触内核：erwFetch 走网络、ERWToast 提示条、ERWContract 只读契约；
 * 样式全部落在 [data-plugin="report-export"] 里（内核给挂载容器打这个属性）。
 */
(function () {
  'use strict';

  var ID = 'report-export';

  function el(sel, root) { return (root || document).querySelector(sel); }

  function esc(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function toast(message, error) {
    if (typeof window.ERWToast === 'function') { window.ERWToast(message, error); return; }
    console.log('[' + ID + '] ' + message);
  }

  function api(path, body) {
    var f = window.erwFetch || window.fetch;
    var init = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body) } : undefined;
    return f('/api/plugins/' + ID + '/' + path, init).then(function (r) { return r.json(); });
  }

  var STATE = { scopes: null, entries: [], last: null };

  function scopePayload() {
    var type = el('#re-scope-type').value;
    var value = '';
    if (type === 'project') value = el('#re-scope-project').value;
    if (type === 'kind') value = el('#re-scope-kind').value;
    return { type: type, value: value };
  }

  function optionsPayload() {
    return {
      include_body: el('#re-body').checked,
      include_meta: el('#re-meta').checked,
      split_by_kind: el('#re-split').checked,
      max_entries: Math.max(1, Math.min(500, Number(el('#re-max').value) || 200)),
    };
  }

  function syncScopeInputs() {
    var type = el('#re-scope-type').value;
    el('#re-scope-project').hidden = type !== 'project';
    el('#re-scope-kind').hidden = type !== 'kind';
  }

  function renderScopeOptions() {
    var s = STATE.scopes || { projects: [], kinds: [], total: 0 };
    el('#re-scope-project').innerHTML = (s.projects || []).map(function (p) {
      return '<option value="' + esc(p.value) + '">' + esc(p.value) + '（' + p.docs + ' 条）</option>';
    }).join('') || '<option value="">（当前没有项目）</option>';
    el('#re-scope-kind').innerHTML = (s.kinds || []).map(function (k) {
      return '<option value="' + esc(k.value) + '">' + esc(k.label) + '（' + k.count + ' 条）</option>';
    }).join('');
    var labels = s.kinds || [];
    el('#re-total').textContent = '当前知识库共 ' + (s.total || 0) + ' 条条目 · 可导出类别：'
      + labels.map(function (k) { return k.label; }).join(' / ');
    syncScopeInputs();
  }

  function renderPreview(data) {
    var items = data.items || [];
    STATE.entries = items;
    if (!items.length) {
      el('#re-preview').innerHTML = '<div class="re-empty">该范围没有条目。</div>';
      return;
    }
    el('#re-preview').innerHTML = ''
      + '<div class="re-pv-head">预览 · <b>' + esc(data.title) + '</b> · 共 ' + data.count + ' 条'
      + (data.options && data.options.include_body ? ' · 含正文' : ' · 仅元信息') + '</div>'
      + '<ol class="re-pv-list">'
      + items.slice(0, 300).map(function (it) {
          return '<li><span class="re-kind">' + esc(it.kind_label) + '</span>'
            + '<span class="re-title">' + esc(it.title) + '</span>'
            + (it.status ? '<span class="re-status">' + esc(it.status) + '</span>' : '')
            + '<span class="re-chars">' + (it.chars ? it.chars + ' 字' : '') + '</span></li>';
        }).join('')
      + '</ol>'
      + (items.length > 300 ? '<div class="re-empty">（预览只列前 300 条，导出仍按设置收录全部）</div>' : '');
  }

  function renderResult(data) {
    STATE.last = data;
    if (!data || !data.ok) {
      el('#re-result').innerHTML = '<div class="re-alert">导出失败：' + esc((data && data.error) || '未知错误') + '</div>';
      return;
    }
    var rows = '<div class="re-ok"><b>已生成</b> ' + esc(data.file) + ' · ' + data.entries + ' 条 · '
      + (data.bytes / 1024).toFixed(1) + ' KB</div>'
      + '<div class="re-actions">'
      + '<a class="primary-btn" href="' + esc(data.url) + '" download>下载 ' + esc(data.format.toUpperCase()) + '</a>';
    if (data.print_url) {
      rows += '<a class="secondary-btn" href="' + esc(data.print_url) + '" target="_blank" rel="noopener">打印 / 另存为 PDF</a>';
    }
    rows += '</div>';
    if (data.format === 'docx') {
      rows += '<div class="re-hint">Word 打开后可直接「另存为 PDF」；也可以先导 HTML 再打印（中文字体由系统处理，效果最好）。</div>';
    }
    el('#re-result').innerHTML = rows;
  }

  function render(main) {
    main.innerHTML = ''
      + '<section class="card card-pad re-card">'
      +   '<div class="card-kicker">REPORT EXPORT</div>'
      +   '<h3>报告导出</h3>'
      +   '<p class="row-meta">把项目或某一类条目整理成交付文档。<b>DOCX</b> 由本机标准库直接写出（不需要安装任何东西）；'
      +     '<b>HTML</b> 可用浏览器「打印 → 另存为 PDF」得到 PDF；<b>Markdown</b> 便于再加工。</p>'
      +   '<div class="re-grid">'
      +     '<label class="re-field"><span>范围</span>'
      +       '<select id="re-scope-type"><option value="project">某个项目</option>'
      +       '<option value="kind">某一类条目</option><option value="all">全部条目</option></select></label>'
      +     '<label class="re-field" id="re-project-wrap"><span>项目</span><select id="re-scope-project"></select></label>'
      +     '<label class="re-field"><span>类别</span><select id="re-scope-kind"></select></label>'
      +     '<label class="re-field"><span>最多收录</span><input id="re-max" type="number" min="1" max="500" value="200"></label>'
      +   '</div>'
      +   '<div class="re-opts">'
      +     '<label><input type="checkbox" id="re-body" checked> 收录正文</label>'
      +     '<label><input type="checkbox" id="re-meta" checked> 收录状态/项目/标签/日期</label>'
      +     '<label><input type="checkbox" id="re-split" checked> 按类别分章</label>'
      +   '</div>'
      +   '<div class="re-actions">'
      +     '<button class="secondary-btn" id="re-preview-btn" type="button">预览范围</button>'
      +     '<button class="primary-btn" id="re-docx" type="button">导出 DOCX</button>'
      +     '<button class="secondary-btn" id="re-html" type="button">导出 HTML（可打印成 PDF）</button>'
      +     '<button class="secondary-btn" id="re-md" type="button">导出 Markdown</button>'
      +   '</div>'
      +   '<div class="re-total" id="re-total"></div>'
      +   '<div id="re-preview"></div>'
      +   '<div id="re-result"></div>'
      + '</section>';

    el('#re-scope-type').onchange = syncScopeInputs;
    el('#re-preview-btn').onclick = function () {
      api('preview', { scope: scopePayload(), options: optionsPayload() })
        .then(renderPreview)
        .catch(function (e) { toast('预览失败：' + e.message, true); });
    };
    [['#re-docx', 'docx'], ['#re-html', 'html'], ['#re-md', 'md']].forEach(function (pair) {
      el(pair[0]).onclick = function () {
        var btn = el(pair[0]);
        btn.disabled = true;
        api('export', { scope: scopePayload(), options: optionsPayload(), format: pair[1] })
          .then(function (data) { renderResult(data); if (data.ok) toast('已生成 ' + data.file); })
          .catch(function (e) { renderResult({ ok: false, error: e.message }); })
          .then(function () { btn.disabled = false; });
      };
    });

    api('scopes').then(function (data) {
      STATE.scopes = data;
      renderScopeOptions();
    }).catch(function (e) {
      el('#re-total').textContent = '读取范围失败：' + e.message;
    });
  }

  if (!window.ERWPanels) return;
  window.ERWPanels.register({
    id: ID,
    group: 'research',
    before: 'graph',
    label: '报告导出',
    icon: '▤',
    eyebrow: 'DELIVERABLES',
    title: '报告导出',
    render: function (main) { render(main); },
  });
})();
