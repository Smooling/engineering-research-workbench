/* 指标表 · 插件面板 v1.1.0
 *
 * 数据来自条目正文：```metrics 块 **或**有数值列的 Markdown 表格（按行展开）。
 * 关键交互：模式（明细/按对象透视）、列收敛（只显示出现次数够多的指标列）、关键词过滤、来源可追溯。
 * 样式全部落在 [data-plugin="metrics-table"] 内。
 */
(function () {
  'use strict';

  var ID = 'metrics-table';
  if (window.__erwMetricsLoaded) return;
  window.__erwMetricsLoaded = true;

  function el(sel, root) { return (root || document).querySelector(sel); }
  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function toast(m, e) { if (typeof window.ERWToast === 'function') window.ERWToast(m, e); else console.log('[' + ID + '] ' + m); }
  function api(path) {
    return (window.erwFetch || window.fetch)('/api/plugins/' + ID + '/' + path).then(function (r) { return r.json(); });
  }
  function num(v, d) { return (v === null || v === undefined) ? '—' : Number(v).toFixed(d === undefined ? 4 : d); }

  var DATA = null;
  var STATE = { mode: 'records', minFilled: 1, keyword: '' };

  function params() {
    var p = el('#mt-project').value, k = el('#mt-kind').value;
    return '?project=' + encodeURIComponent(p) + '&kind=' + encodeURIComponent(k) + '&mode=' + STATE.mode;
  }

  /* 明细模式按「来源表格」分组：每张表列数少、可读；不再把所有表的列摊成一张宽表 */
  function groups() {
    if (!DATA) return [];
    var map = {};
    (DATA.rows || []).forEach(function (r) {
      var key = (r.entry_id || '') + '||' + (r.scope || '') + '||' + (r.source || '');
      if (!map[key]) {
        map[key] = { key: key, title: r.entry_title, short: r.short, scope: r.scope || '',
                     source: r.source, rows: [] };
      }
      map[key].rows.push(r);
    });
    return Object.keys(map).map(function (k) { return map[k]; });
  }

  function groupColumns(rows) {
    var order = [];
    rows.forEach(function (r) {
      Object.keys(r.metrics).forEach(function (k) { if (order.indexOf(k) < 0) order.push(k); });
    });
    return order.map(function (key) {
      var values = [], filled = 0, units = {};
      rows.forEach(function (r) {
        if (r.metrics[key] === undefined) return;
        filled += 1;
        var m = String(r.metrics[key]).replace(/,/g, '').match(/^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([^\d\s]*)$/);
        if (m) {
          values.push(Number(m[1]));
          if (m[2]) units[m[2]] = (units[m[2]] || 0) + 1;
        }
      });
      var unit = Object.keys(units).sort(function (a, b) { return units[b] - units[a]; })[0] || '';
      var mean = values.length ? values.reduce(function (a, b) { return a + b; }, 0) / values.length : null;
      return { key: key, filled: filled, missing: rows.length - filled, unit: unit,
               min: values.length ? Math.min.apply(null, values) : null,
               max: values.length ? Math.max.apply(null, values) : null, mean: mean };
    }).filter(function (c) { return c.filled >= STATE.minFilled; });
  }

  function matchesKeyword(text) {
    var kw = STATE.keyword.trim().toLowerCase();
    return !kw || String(text || '').toLowerCase().indexOf(kw) >= 0;
  }

  function renderSummary(groupsCount, shownRows) {
    var s = DATA.sources || {};
    el('#mt-summary').innerHTML = ''
      + '<span class="mt-chip">扫描 ' + DATA.scanned + ' 条条目</span>'
      + '<span class="mt-chip ok">命中 ' + DATA.with_metrics + ' 条记录</span>'
      + '<span class="mt-chip">来自正文表格 ' + (s.table || 0) + '</span>'
      + '<span class="mt-chip">来自 ```块 ' + (s.block || 0) + '</span>'
      + '<span class="mt-chip">来源表 ' + groupsCount + ' 张</span>'
      + '<span class="mt-chip">显示 ' + shownRows + ' 行</span>';
  }

  function renderGrouped() {
    var all = groups();
    var kw = STATE.keyword.trim().toLowerCase();
    var shown = 0;
    var html = [];
    all.forEach(function (g) {
      var rows = g.rows.filter(function (r) {
        if (!kw) return true;
        return matchesKeyword(r.object) || matchesKeyword(g.title) || matchesKeyword(g.scope)
          || Object.keys(r.metrics).join(' ').toLowerCase().indexOf(kw) >= 0;
      });
      if (!rows.length) return;
      var cols = groupColumns(rows);
      if (!cols.length) return;
      /* 附带信息（如「数据集」）当标识列放在对象旁边——2.1 的 27 组基线就是「模型 × 数据集」逐行，
         只显示对象会看着像重复行 */
      var extras = [];
      rows.forEach(function (r) {
        Object.keys(r.extra || {}).forEach(function (k) { if (extras.indexOf(k) < 0) extras.push(k); });
      });
      shown += rows.length;
      var head = '<tr><th class="mt-sticky">对象</th>'
        + extras.map(function (k) { return '<th>' + esc(k) + '</th>'; }).join('')
        + cols.map(function (c) { return '<th title="有 ' + c.filled + ' / 缺 ' + c.missing
            + (c.unit ? ' · 单位 ' + esc(c.unit) : '') + '">' + esc(c.key) + '</th>'; }).join('')
        + '</tr>';
      var stat = '<tr class="mt-stat"><td class="mt-sticky">统计</td>'
        + extras.map(function () { return '<td></td>'; }).join('')
        + cols.map(function (c) { return '<td>' + num(c.min, 3) + ' / ' + num(c.max, 3) + ' / ' + num(c.mean, 3) + '</td>'; }).join('')
        + '</tr>';
      var body = rows.map(function (r, i) {
        return '<tr data-mt-g="' + esc(g.key) + '" data-mt-i="' + i + '">'
          + '<td class="mt-sticky"><b>' + esc(r.object || '（整条）') + '</b></td>'
          + extras.map(function (k) {
              return '<td class="mt-extra">' + esc((r.extra || {})[k] || '') + '</td>'; }).join('')
          + cols.map(function (c) {
              var v = r.metrics[c.key];
              return v === undefined ? '<td class="mt-miss">—</td>' : '<td>' + esc(v) + '</td>';
            }).join('') + '</tr>';
      }).join('');
      html.push('<div class="mt-group"><div class="mt-group-head">'
        + '<b>' + esc(g.title) + '</b>'
        + '<span class="mt-src ' + (g.source === 'table' ? 'tbl' : 'blk') + '">'
        + (g.source === 'table' ? '正文表格' : '```块') + '</span>'
        + '<span class="mt-muted">' + esc(g.scope || '') + '</span>'
        + '<span class="mt-muted">' + rows.length + ' 行 × ' + cols.length + ' 项</span></div>'
        + '<div class="mt-scroll"><table class="mt-table"><thead>' + head + '</thead><tbody>'
        + stat + body + '</tbody></table></div></div>');
      g._rows = rows;
      g._cols = cols;
    });
    renderSummary(all.length, shown);
    el('#mt-table').innerHTML = html.join('') || '<div class="mt-empty">' + esc(DATA.hint || '没有数据') + '</div>';
    Array.prototype.slice.call(el('#mt-table').querySelectorAll('[data-mt-g]')).forEach(function (tr) {
      tr.onclick = function () {
        var g = all.filter(function (x) { return x.key === tr.dataset.mtG; })[0];
        if (g) showDetail(g._rows[parseInt(tr.dataset.mtI, 10)], g._cols);
      };
    });
  }

  function renderPivot() {
    var cols = (DATA.columns || []).filter(function (c) {
      if (c.filled < STATE.minFilled) return false;
      return matchesKeyword(c.key) || matchesKeyword(c.metric);
    });
    var rows = (DATA.rows || []).filter(function (r) {
      return matchesKeyword(r.object) || matchesKeyword((r.entries || []).join(' '));
    });
    renderSummary(1, rows.length);
    if (!rows.length || !cols.length) {
      el('#mt-table').innerHTML = '<div class="mt-empty">没有匹配的对象/指标（试试把「指标列最少出现」调小或清空关键词）</div>';
      return;
    }
    var head = '<tr><th class="mt-sticky">对象</th><th>来源实验</th>'
      + cols.map(function (c) { return '<th title="' + esc(c.metric + ' @ ' + c.source + ' · 有 '
          + c.filled + ' 个对象有值') + '">' + esc(c.metric) + '<i>@' + esc(c.source) + '</i></th>'; }).join('')
      + '</tr>';
    var stat = '<tr class="mt-stat"><td class="mt-sticky">统计</td><td></td>'
      + cols.map(function (c) { return '<td>' + num(c.min, 3) + ' / ' + num(c.max, 3) + ' / ' + num(c.mean, 3) + '</td>'; }).join('')
      + '</tr>';
    var body = rows.map(function (r, index) {
      return '<tr data-mt-p="' + index + '"><td class="mt-sticky"><b>' + esc(r.object) + '</b></td>'
        + '<td>' + esc((r.entries || []).join('、')) + '</td>'
        + cols.map(function (c) {
            var v = r.metrics[c.key];
            return v === undefined ? '<td class="mt-miss">—</td>' : '<td>' + esc(v) + '</td>';
          }).join('') + '</tr>';
    }).join('');
    el('#mt-table').innerHTML = '<div class="mt-scroll"><table class="mt-table"><thead>' + head
      + '</thead><tbody>' + stat + body + '</tbody></table></div>';
    Array.prototype.slice.call(el('#mt-table').querySelectorAll('[data-mt-p]')).forEach(function (tr) {
      tr.onclick = function () { showDetail(rows[parseInt(tr.dataset.mtP, 10)], cols); };
    });
  }

  function renderTable() {
    if (!DATA) return;
    if (STATE.mode === 'pivot') renderPivot();
    else renderGrouped();
  }

  function showDetail(row, cols) {
    var box = '<div class="mt-detail-box">';
    if (STATE.mode === 'pivot') {
      box += '<b>' + esc(row.object) + '</b><div class="mt-muted">来源实验：' + esc((row.entries || []).join('、')) + '</div>';
      box += '<ul class="mt-kv">' + (cols || []).filter(function (c) { return row.metrics[c.key] !== undefined; })
        .map(function (c) { return '<li><code>' + esc(c.metric) + '@' + esc(c.source) + '</code> ' + esc(row.metrics[c.key]) + '</li>'; })
        .join('') + '</ul>';
    } else {
      box += '<b>' + esc(row.entry_title) + '</b> <span class="mt-src ' + (row.source === 'table' ? 'tbl' : 'blk') + '">'
        + (row.source === 'table' ? '正文表格' : '```' + (DATA.config.block_name) + ' 块') + '</span>'
        + '<div class="mt-muted">对象：' + esc(row.object || '（整条）') + ' · 小节：' + esc(row.scope || '')
        + ' · id：<code>' + esc(row.entry_id || '') + '</code></div>';
      box += '<ul class="mt-kv">' + Object.keys(row.metrics).map(function (k) {
        return '<li><code>' + esc(k) + '</code> ' + esc(row.metrics[k]) + '</li>'; }).join('') + '</ul>';
      if (row.extra && Object.keys(row.extra).length) {
        box += '<div class="mt-muted">附带信息：' + esc(Object.keys(row.extra).map(function (k) {
          return k + '=' + row.extra[k]; }).join('，')) + '</div>';
      }
    }
    box += '<div class="mt-muted">这些数字是**从条目正文里读出来的**（表格按行展开），没有另存副本；'
      + '要改数字就改条目正文。写入走 <code>p_metrics-table__record_metrics</code>（草稿确认），但正文表格本来就能被读到。</div></div>';
    el('#mt-detail').innerHTML = box;
  }

  function load() {
    el('#mt-table').innerHTML = '<div class="mt-empty">正在读取…</div>';
    api('table' + params()).then(function (data) {
      DATA = data;
      el('#mt-min').value = String(STATE.minFilled);
      renderTable();
      el('#mt-csv').href = '/api/plugins/' + ID + '/export' + params() + '&format=csv';
      el('#mt-md').href = '/api/plugins/' + ID + '/export' + params() + '&format=md';
    }).catch(function (e) { el('#mt-table').innerHTML = '<div class="mt-empty">读取失败：' + esc(e.message) + '</div>'; });
  }

  function render(main) {
    main.innerHTML = ''
      + '<section class="card card-pad mt-card">'
      +   '<div class="card-kicker">METRICS</div>'
      +   '<h3>指标表</h3>'
      +   '<p class="row-meta">把条目正文里的指标汇成对照表：<b>```metrics 块</b> 与 <b>有数值列的 Markdown 表格</b>'
      +     '都会自动被识别（表格按行展开，自动挑出「模型/方法」这种对象列）。'
      +     '数字始终留在正文里——这里只是读出来对齐看。</p>'
      +   '<div class="mt-controls">'
      +     '<label><span>项目</span><select id="mt-project"><option value="">全部项目</option></select></label>'
      +     '<label><span>类别</span><select id="mt-kind">'
      +       '<option value="">默认（实验）</option><option value="experiment">实验</option><option value="note">笔记</option>'
      +       '<option value="milestone">里程碑</option><option value="summary">工作总结</option>'
      +       '<option value="idea">灵感</option><option value="journal">研究日志</option></select></label>'
      +     '<label><span>模式</span><select id="mt-mode">'
      +       '<option value="records">按来源表分组（推荐）</option>'
      +       '<option value="pivot">按对象透视（跨实验对照）</option></select></label>'
      +     '<label><span>指标列最少出现</span><input id="mt-min" type="number" min="1" max="50" value="1"></label>'
      +     '<label><span>关键词</span><input id="mt-kw" type="text" placeholder="过滤行/列"></label>'
      +     '<button class="secondary-btn" id="mt-refresh" type="button">刷新</button>'
      +     '<a class="secondary-btn" id="mt-csv" href="#" download>导出 CSV</a>'
      +     '<a class="secondary-btn" id="mt-md" href="#" download>导出 Markdown</a>'
      +   '</div>'
      +   '<div class="mt-summary" id="mt-summary"></div>'
      +   '<div id="mt-table"></div>'
      +   '<div id="mt-detail"></div>'
      +   '<div class="mt-hint">明细模式按<b>来源表</b>分组（每张表列数少、能直接读）；透视模式把同名对象（同一模型/方法）'
      +     '在不同实验里的数字并到一行，用于跨实验对照。列太多时调大「指标列最少出现」或填关键词收敛。'
      +     '写入仍走 Agent 工具 <code>p_metrics-table__record_metrics</code>（草稿确认），但<b>正文表格不需要写工具</b>——它本来就能被读到。</div>'
      + '</section>';

    el('#mt-refresh').onclick = load;
    el('#mt-project').onchange = load;
    el('#mt-kind').onchange = load;
    el('#mt-mode').onchange = function () {
      STATE.mode = el('#mt-mode').value;
      /* 透视模式列会很多（每个指标 × 每个实验一列），首次切过去时把阈值抬到 2 收敛一下；
         明细分组模式列本来就少，回到 1 免得藏掉只出现一次的指标 */
      STATE.minFilled = STATE.mode === 'pivot' ? 2 : 1;
      load();
    };
    el('#mt-min').onchange = function () { STATE.minFilled = Math.max(1, Number(el('#mt-min').value) || 1); renderTable(); };
    el('#mt-kw').oninput = function () { STATE.keyword = el('#mt-kw').value || ''; renderTable(); };

    (window.erwFetch || window.fetch)('/api/projects').then(function (r) { return r.json(); })
      .then(function (names) {
        (names || []).forEach(function (n) {
          var opt = document.createElement('option');
          opt.value = n; opt.textContent = n;
          el('#mt-project').appendChild(opt);
        });
      }).catch(function () { /* 拿不到项目列表就保持"全部项目" */ });
    load();
  }

  if (!window.ERWPanels) return;
  window.ERWPanels.register({
    id: ID,
    group: 'research',
    before: 'experiments',
    label: '指标表',
    icon: '▩',
    eyebrow: 'DATA',
    title: '指标表',
    render: function (main) { render(main); },
  });
})();
