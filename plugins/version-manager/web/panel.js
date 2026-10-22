/* 版本管理 · 插件前端 v1.0.0（v261009.44 从内核页面搬成插件）
 *
 * 页面：版本族列表（默认只看分叉中 + 搜索）+ 逐版对照（含来源）+ 按小节挑内容合并 + 归档/取回。
 * 数据与闸门都在内核：本面板只调用本插件后端 /api/plugins/version-manager/*（后端再走 core_api）。
 */
(function () {
  'use strict';

  var API = '/api/plugins/version-manager';
  var STATE = { families: [], current: '', detail: null, picks: {}, archiveAfter: true,
                filter: 'forked', keyword: '', autoInfo: null, clean: null };

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function api(path, options) {
    return (window.erwFetch || window.fetch)(path, options).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(data && data.message ? data.message : ('HTTP ' + r.status));
        return data;
      });
    });
  }
  function post(path, body) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                       body: JSON.stringify(body || {}) });
  }
  function toast(m, e) { if (typeof window.ERWToast === 'function') window.ERWToast(m, e); else console.log(m); }

  var KIND_LABEL = { note: '笔记', experiment: '实验', journal: '研究日志', idea: '灵感',
                     milestone: '里程碑', summary: '工作总结', literature: '文献' };
  var HISTORY_LABEL = { doc_create: '新建', doc_update: '更新', doc_merge: '合并',
                        doc_delete: '归档', doc_restore: '取回',
                        doc_external_edit: '外部改动' };

  function render(main) {
    main.innerHTML = ''
      + '<section class="vm-layout">'
      +   '<aside class="card vm-side">'
      +     '<div><div class="card-kicker">VERSIONS</div><h3>版本</h3>'
      +       '<p class="row-meta">同一笔记的不同版本会归成一条「版本族」——'
      +       '不论在工作台里改的，还是外部工具（MCP）塞进来的。</p></div>'
      +     '<div class="vm-stats" id="vm-stats"></div>'
      +     '<div class="vm-clean" id="vm-clean"></div>'
      +     '<div class="vm-filter">'
      +       '<span class="vm-seg" id="vm-seg">'
      +         '<button type="button" data-vm-filter="forked" class="active">只看分叉中</button>'
      +         '<button type="button" data-vm-filter="all">全部</button>'
      +       '</span>'
      +       '<input class="search-input" id="vm-search" placeholder="按标题过滤…">'
      +     '</div>'
      +     '<div class="vm-list" id="vm-list"><div class="empty compact">正在读取…</div></div>'
      +   '</aside>'
      +   '<section class="card vm-pane" id="vm-pane">'
      +     '<div class="empty">选择左侧的一条版本族</div></section>'
      + '</section>';

    var seg = main.querySelector('#vm-seg');
    Array.prototype.forEach.call(seg.querySelectorAll('[data-vm-filter]'), function (btn) {
      btn.onclick = function () {
        STATE.filter = btn.dataset.vmFilter;
        Array.prototype.forEach.call(seg.querySelectorAll('button'), function (b) {
          b.classList.toggle('active', b === btn);
        });
        paintList(main);
      };
    });
    var search = main.querySelector('#vm-search');
    search.oninput = function () { STATE.keyword = search.value.trim().toLowerCase(); paintList(main); };
    loadFamilies(main);
    loadCleanup(main);
  }

  function loadFamilies(main) {
    api(API + '/overview').then(function (data) {
      STATE.families = data.families || [];
      var counts = data.counts || {};
      var stats = main.querySelector('#vm-stats');
      if (stats) {
        stats.innerHTML = '<span class="vm-chip">' + (counts.families || 0) + ' 个族</span>'
          + '<span class="vm-chip ' + ((counts.forked || 0) ? 'on' : '') + '">'
          + (counts.forked || 0) + ' 个分叉中</span>'
          + '<span class="vm-chip">' + (counts.variants || 0) + ' 个版本</span>';
      }
      // 没有任何分叉时别给一个空列表：自动回落到「全部」，并在列表上方说明原因
      if (!counts.forked && STATE.filter === 'forked') {
        STATE.filter = 'all';
        var seg = main.querySelector('#vm-seg');
        if (seg) {
          Array.prototype.forEach.call(seg.querySelectorAll('button'), function (b) {
            b.classList.toggle('active', b.dataset.vmFilter === 'all');
          });
        }
        var note = document.createElement('div');
        note.className = 'vm-hint';
        note.style.margin = '0 0 6px';
        note.innerHTML = '当前<b>没有分叉中的版本族</b>，下面列出全部 ' + (counts.families || 0)
          + ' 个族——建一条同名不同版（如 <code>知识-方法-X（v2）</code>）后，它会自动归族并出现在这里。';
        var listBox = main.querySelector('#vm-list');
        if (listBox && listBox.parentElement) listBox.parentElement.insertBefore(note, listBox);
      }
      paintList(main);
      var first = visible().find(function (f) { return f.variant_count > 0; }) || visible()[0];
      if (first) loadDetail(first.base_id, main);
    }).catch(function (e) {
      main.querySelector('#vm-list').innerHTML = '<div class="vm-error">读取失败：' + esc(e.message) + '</div>';
    });
  }

  function visible() {
    var kw = STATE.keyword;
    return STATE.families.filter(function (f) {
      var hit = !kw || String(f.title || '').toLowerCase().indexOf(kw) >= 0
        || String(f.base_id || '').toLowerCase().indexOf(kw) >= 0;
      // 搜索时忽略「只看分叉中」：没分叉的笔记也要能选中（否则它的更新历史看不到）
      if (kw) return hit;
      if (STATE.filter === 'forked' && !f.variant_count) return false;
      return true;
    });
  }

  function paintList(main) {
    var list = main.querySelector('#vm-list');
    var rows = visible();
    var sameMap = {}, changedMap = {};
    if (STATE.clean) {
      (STATE.clean.same || []).forEach(function (x) { sameMap[x.base_id] = (x.ids || []).length; });
      (STATE.clean.changed || []).forEach(function (x) { changedMap[x.base_id] = (x.ids || []).length; });
    }
    if (!rows.length) {
      list.innerHTML = '<div class="empty compact">'
        + (STATE.filter === 'forked'
            ? '当前没有分叉中的版本族。<br>想看某条笔记的<b>更新历史</b>？切到「全部」，或直接搜标题。'
            : '没有匹配的族') + '</div>';
      return;
    }
    list.innerHTML = rows.map(function (f) {
      return '<button type="button" class="vm-item' + (f.base_id === STATE.current ? ' active' : '')
        + '" data-vm-base="' + esc(f.base_id) + '" title="' + esc(f.title) + '">'
        + '<span class="vm-item-main">' + esc(f.title || f.base_id) + '</span>'
        + '<span class="vm-item-meta">' + esc(KIND_LABEL[f.kind] || f.kind || '')
        + (f.variant_count ? ' · <b>' + f.variant_count + ' 个版本</b>' : '')
        + (changedMap[f.base_id] ? ' · <span class="vm-clean-badge changed">有改动</span>' : '')
        + (sameMap[f.base_id] ? ' · <span class="vm-clean-badge same">内容一致</span>' : '')
        + (f.updated ? ' · 改于 ' + esc(String(f.updated).replace('T', ' ').slice(5, 16)) : '')
        + '</span></button>';
    }).join('');
    Array.prototype.forEach.call(list.querySelectorAll('[data-vm-base]'), function (btn) {
      btn.onclick = function () { loadDetail(btn.dataset.vmBase, main); };
    });
  }

  /* 批量清理：一次扫描所有版本族，把「内容一致」与「有改动」分开 */
  function loadCleanup(main) {
    var box = main.querySelector('#vm-clean');
    if (!box) return;
    api(API + '/cleanup').then(function (data) {
      STATE.clean = data;
      paintClean(main, data);
      paintList(main);
    }).catch(function (e) {
      box.innerHTML = '<div class="vm-clean-hint">清理扫描失败：' + esc(e.message) + '</div>';
    });
  }

  function paintClean(main, data) {
    var box = main.querySelector('#vm-clean');
    if (!box) return;
    var total = (data.same_count || 0) + (data.changed_count || 0);
    if (!total) { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="vm-clean-card">'
      + '<div class="vm-clean-head"><b>批量清理</b><span class="vm-clean-total">' + total + ' 个快照</span></div>'
      + '<div class="vm-clean-meta">内容一致 ' + (data.same_count || 0)
      + ' · 有改动 ' + (data.changed_count || 0) + '</div>'
      + '<div class="vm-clean-actions">'
      + ((data.same_count || 0)
          ? '<button type="button" class="secondary-btn" data-vm-clean="same">归档内容一致的 ' + data.same_count + ' 个</button>'
          : '')
      + '<button type="button" class="secondary-btn" data-vm-clean="all">归档全部 ' + total + ' 个…</button>'
      + '</div>'
      + '<div class="vm-clean-hint">归档 = 移出主库到 System/Versions，可随时取回；基条内容不变。</div>'
      + '</div>';
    Array.prototype.forEach.call(box.querySelectorAll('[data-vm-clean]'), function (btn) {
      btn.onclick = function () {
        var mode = btn.dataset.vmClean;
        var count = mode === 'all' ? total : (data.same_count || 0);
        var ask = mode === 'all'
          ? '把全部 ' + count + ' 个快照归档？它们会移到 System/Versions/<基条>/archived/，可随时取回；基条内容不变。'
          : '归档 ' + count + ' 个「内容与基条一致」的快照？';
        var confirmFn = (window.ERWDialog && window.ERWDialog.confirm)
          ? window.ERWDialog.confirm(ask)
          : window.confirm(ask);
        Promise.resolve(confirmFn).then(function (ok) {
          if (!ok) return;
          btn.disabled = true;
          btn.textContent = '归档中…';
          post(API + '/cleanup-archive', { mode: mode }).then(function (out) {
            toast('已归档 ' + out.archived + ' 个快照（' + out.families + ' 个族）');
            loadFamilies(main);
            loadCleanup(main);
            if (STATE.current) loadDetail(STATE.current, main);
          }).catch(function (e) {
            toast('归档失败：' + e.message, true);
            btn.disabled = false;
          });
        });
      };
    });
  }

  function loadDetail(baseId, main) {
    STATE.current = baseId;
    STATE.picks = {};
    STATE.archiveAfter = true;
    STATE.autoInfo = null;
    var pane = main.querySelector('#vm-pane');
    pane.innerHTML = '<div class="empty">正在读取版本族…</div>';
    Array.prototype.forEach.call(main.querySelectorAll('.vm-item'), function (el) {
      el.classList.toggle('active', el.dataset.vmBase === baseId);
    });
    api(API + '/family?id=' + encodeURIComponent(baseId)).then(function (data) {
      STATE.detail = data;
      paintDetail(main);
    }).catch(function (e) {
      pane.innerHTML = '<div class="vm-error">读取失败：' + esc(e.message) + '</div>';
    });
  }

  /* 修改记录：这条笔记（含各版本）谁在什么时候改了什么（读内核活动日志） */
  function loadHistory(baseId, main) {
    var box = main.querySelector('#vm-history');
    if (!box) return;
    api(API + '/history?id=' + encodeURIComponent(baseId) + '&days=90').then(function (data) {
      var events = (data.events || []).slice().reverse();
      if (!events.length) {
        box.innerHTML = '<div class="empty compact">最近 90 天没有修改记录</div>';
        return;
      }
      box.innerHTML = events.slice(0, 40).map(function (e) {
        var detail = e.detail || {};
        var extra = '';
        if (e.type === 'doc_merge' && (detail.replaced_sections || []).length) {
          extra = ' · 替换小节 ' + esc(detail.replaced_sections.join('、'));
        }
        return '<div class="vm-hrow"><span class="vm-htime">'
          + esc(String(e.timestamp || '').replace('T', ' ').slice(0, 16)) + '</span>'
          + '<span class="vm-hkind">' + esc(HISTORY_LABEL[e.type] || e.type || '') + '</span>'
          + '<span class="vm-hsrc">'
          + (e.source ? esc(e.source)
                      : '<i class="vm-nosrc">未记录来源（该次写入来自旧版 MCP 进程或外部工具）</i>')
          + extra + '</span></div>';
      }).join('');
    }).catch(function (e) {
      box.innerHTML = '<div class="vm-error">修改记录读取失败：' + esc(e.message) + '</div>';
    });
  }

  /* ---------- 变更对照：小节解析 + 行级 diff（无第三方库） ---------- */

  function sectionsOf(body) {
    var out = [], cur = null;
    String(body || '').split('\n').forEach(function (line) {
      var m = /^##\s+(.+?)\s*$/.exec(line);
      if (m) {
        cur = { heading: m[1].trim(), lines: [] };
        out.push(cur);
      } else if (cur) {
        cur.lines.push(line);
      }
    });
    return out;
  }

  function sectionMap(body) {
    var map = {};
    sectionsOf(body).forEach(function (s) { map[s.heading] = s.lines.join('\n').replace(/\s+$/, ''); });
    return map;
  }

  /* 行级 LCS diff；文本很大时退化成"整体改动"标记，避免卡界面 */
  function diffLines(oldText, newText) {
    var A = String(oldText || '').split('\n'), B = String(newText || '').split('\n');
    if (A.length * B.length > 40000) {
      return { tooBig: true, added: B.length, removed: A.length,
               ops: [{ t: 'del', text: '（小节较大，仅统计：' + A.length + ' 行 → ' + B.length + ' 行）' }] };
    }
    var m = A.length, n = B.length, i, j;
    var dp = [];
    for (i = 0; i <= m; i++) { dp.push(new Array(n + 1).fill(0)); }
    for (i = m - 1; i >= 0; i--) {
      for (j = n - 1; j >= 0; j--) {
        dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    var ops = [], added = 0, removed = 0;
    i = 0; j = 0;
    while (i < m && j < n) {
      if (A[i] === B[j]) { ops.push({ t: 'same', text: A[i] }); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ t: 'del', text: A[i] }); removed++; i++; }
      else { ops.push({ t: 'add', text: B[j] }); added++; j++; }
    }
    while (i < m) { ops.push({ t: 'del', text: A[i++] }); removed++; }
    while (j < n) { ops.push({ t: 'add', text: B[j++] }); added++; }
    return { tooBig: false, added: added, removed: removed, ops: ops };
  }

  function oneSided(text, kind) {
    var lines = String(text || '').split('\n');
    return { tooBig: false, added: kind === 'add' ? lines.length : 0,
             removed: kind === 'del' ? lines.length : 0,
             ops: lines.map(function (l) { return { t: kind, text: l }; }) };
  }

  function sectionStatus(baseText, otherText) {
    // 单边小节也要能看到内容（否则用户只知道"有差异"却看不到差异是什么）
    if (baseText === undefined) {
      return { kind: 'onlyNew', label: '仅该版本有', added: 0, removed: 0, diff: oneSided(otherText, 'add') };
    }
    if (otherText === undefined) {
      return { kind: 'onlyBase', label: '基准独有', added: 0, removed: 0, diff: oneSided(baseText, 'del') };
    }
    if (String(baseText).trim() === String(otherText).trim()) {
      return { kind: 'same', label: '一致', added: 0, removed: 0, diff: null };
    }
    var d = diffLines(baseText, otherText);
    return { kind: 'changed', label: (d.tooBig ? '改动较大' : '+' + d.added + ' / −' + d.removed + ' 行'),
             added: d.added, removed: d.removed, diff: d };
  }

  function diffHtml(diff) {
    if (!diff) return '<div class="empty compact">没有可显示的差异</div>';
    var body = diff.ops.map(function (op) {
      var sign = op.t === 'add' ? '+' : (op.t === 'del' ? '−' : ' ');
      return '<div class="vm-dline ' + op.t + '"><i>' + sign + '</i>' + esc(op.text) + '</div>';
    }).join('');
    return '<div class="vm-diff">' + body + '</div>';
  }

  function originChip(doc) {
    var surface = doc.origin_surface || '';
    var cls = surface === 'mcp' ? 'mcp' : surface === 'plugin' ? 'plugin' : surface === 'agent' ? 'agent' : 'ui';
    return '<span class="vm-origin ' + cls + '" title="' + esc(doc.origin || '') + '">'
      + esc(doc.origin || '（未记录来源）') + '</span>';
  }

  function paintDetail(main) {
    var d = STATE.detail || {};
    var pane = main.querySelector('#vm-pane');
    var variants = d.variants || [];
    var base = d.base || {};

    var versionRows = variants.map(function (v) {
      return '<label class="vm-vrow' + (STATE.compare === v.id ? ' vm-compare' : '') + '">'
        + '<input type="checkbox" data-vm-archive="' + esc(v.id) + '">'
        + '<span class="vm-vtext"><b>' + esc(v.title) + '</b>'
        + '<span class="vm-vmeta">版本名 <code>' + esc(v.label || '（无）') + '</code>'
        + ' · <b>分支于 ' + esc(String(v.variant_at || v.created || '').replace('T', ' ').slice(0, 16)) + '</b>'
        + ' · 更新 ' + esc(String(v.updated || '').replace('T', ' ').slice(0, 16))
        + ' · 小节 ' + (v.sections || []).length + ' 个</span>'
        + originChip(v)
        + '<span class="vm-vact">'
        + '<button type="button" class="vm-cbtn' + (STATE.compare === v.id ? ' on' : '')
        + '" data-vm-compare="' + esc(v.id) + '" title="用这版做对照">对照</button>'
        + '<button type="button" class="vm-cbtn" data-vm-adopt="' + esc(v.id)
        + '" title="整篇采用这一版（写回基条，保留条目 id）">以这版为准</button>'
        + '</span></span></label>';
    }).join('');

    // 变更对照：以「当前为该小节选中的来源版本」为对照对象（没选就用第一个版本）
    var baseMap = sectionMap(base.body);
    var variantMaps = {};
    variants.forEach(function (v) { variantMaps[v.id] = sectionMap(v.body); });
    function latestId() {
      // 默认"最新版本"（按 variant_at → created → updated 取最大）
      if (!variants.length) return '';
      var sorted = variants.slice().sort(function (a, b) {
        return String(a.variant_at || a.created || a.updated || '')
          .localeCompare(String(b.variant_at || b.created || b.updated || ''));
      });
      return sorted[sorted.length - 1].id;
    }
    function comparedId(heading) {
      // 对照版本：用户选的（STATE.compare）→ 该小节已选的来源 → **最新版本**
      return STATE.compare || STATE.picks[heading] || latestId() || '';
    }
    function statusFor(heading) {
      var vid = comparedId(heading);
      var other = vid ? variantMaps[vid] : null;
      return { vid: vid, st: sectionStatus(baseMap[heading], other ? other[heading] : undefined) };
    }
    var headings = (d.sections || []).slice();
    variants.forEach(function (v) {
      Object.keys(variantMaps[v.id] || {}).forEach(function (h) {
        if (headings.indexOf(h) < 0) headings.push(h);
      });
    });

    var changedCount = 0;
    var changedRows = [], sameRows = [];
    headings.forEach(function (heading) {
      var info = statusFor(heading);
      var st = info.st;
      var options = ['<option value="">基准（当前内容）</option>']
        .concat(variants.map(function (v) {
          return '<option value="' + esc(v.id) + '">' + esc(v.label || v.id) + '</option>';
        })).join('');
      var same = st.kind === 'same';
      // 一致的小节：只留一行说明，**不摆任何控件**（展开才看内容）
      if (same) {
        sameRows.push('<div class="vm-srow vm-same-row" data-vm-srow="' + esc(heading) + '">'
          + '<span class="vm-sname">' + esc(heading) + '</span>'
          + '<span class="vm-keep">与基准一致</span></div>');
        return;
      }
      // 有改动的小节：差异**直接内联展开**，只挑需要决定的那几处
      var control = variants.length > 1
        ? '<select class="search-input vm-sel" data-vm-pick="' + esc(heading) + '">' + options + '</select>'
        : '<span class="vm-choice" data-vm-choice="' + esc(heading) + '">'
          + '<button type="button" class="vm-cbtn on" data-vm-accept="' + esc(heading) + '">采用新版</button>'
          + '<button type="button" class="vm-cbtn" data-vm-keep="' + esc(heading) + '">保留基准</button></span>';
      var row = '<div class="vm-srow vm-need" data-vm-srow="' + esc(heading) + '">'
        + '<div class="vm-shead"><span class="vm-sname">' + esc(heading)
        + ' <b class="vm-sbadge ' + st.kind + '">' + esc(st.label) + '</b>'
        + (STATE.autoInfo && STATE.autoInfo.picks && STATE.autoInfo.picks[heading]
            ? ' <b class="vm-agent-tag">Agent</b>' : '')
        + '</span>' + control + '</div>'
        + '<div class="vm-dwrap" data-vm-dwrap="' + esc(heading) + '">'
        + (st.diff ? diffHtml(st.diff) : '') + '</div></div>';
      changedCount++;
      changedRows.push(row);
    });

    // 有改动的小节默认就选「该版本」（你要的是"改动需同意"，不是"每节都要挑"）
    variants.forEach(function (v) {
      headings.forEach(function (heading) {
        if (STATE.picks[heading]) return;
        var st = sectionStatus(baseMap[heading], (variantMaps[v.id] || {})[heading]);
        if (st.kind !== 'same' && v.id === comparedId(heading)) STATE.picks[heading] = v.id;
      });
    });

    var sectionRows = changedRows.length
      ? changedRows.join('')
      : '<div class="empty compact">没有需要确认的改动——正文与基准一致</div>';
    var sameBlock = sameRows.length
      ? '<details class="vm-same"><summary>' + sameRows.length
        + ' 个小节与基准一致 · 已自动沿用（点开可核对）</summary>' + sameRows.join('') + '</details>'
      : '';

    var compareId = STATE.compare || latestId() || '';
    var compareOptions = variants.map(function (v) {
      return '<option value="' + esc(v.id) + '"' + (v.id === compareId ? ' selected' : '') + '>'
        + esc(v.label || v.id) + '</option>';
    }).join('');
    var comparePicker = variants.length > 1
      ? '<label class="vm-cmpick">对照版本 <select class="search-input" id="vm-compare-sel">'
        + compareOptions + '</select></label>'
      : '';
    var compareLabel = (variants.filter(function (v) { return v.id === compareId; })[0] || variants[0] || {});
    compareLabel = compareLabel.label || compareLabel.id || '';
    var latestPick = variants.filter(function (v) { return v.id === latestId(); })[0] || {};
    var latestLabel = latestPick.label || latestPick.id || '';
    var summary = variants.length
      ? '<div class="vm-hint" style="margin-bottom:8px">' + comparePicker + '与 <b>' + esc(compareLabel) + '</b> 相比：'
        + (changedCount
            ? '<b>' + changedCount + ' 个小节</b>有改动，<b>需要你确认</b>（默认采用该版本；'
              + '选「基准」即不采用）'
            : '正文完全一致，没有需要确认的改动')
        + '；其余小节自动沿用基准。<br>'
        + (variants.length > 1
            ? '<button type="button" class="primary-btn" id="vm-adopt-latest" style="margin-top:6px">'
              + '采用最新版本（' + esc(latestLabel) + '）并归档其余</button> '
            : '')
        + (changedCount
            ? '<button type="button" class="secondary-btn" id="vm-accept-all" style="margin-top:6px">'
              + '全部采用 ' + esc(compareLabel) + ' 的改动</button>'
            : '')
        + '</div>'
      : '';

    var autoInfo = STATE.autoInfo && STATE.autoInfo.base_id === d.base_id ? STATE.autoInfo : null;
    var autoBar = changedCount
      ? '<div class="vm-auto">'
        + '<button type="button" class="secondary-btn" id="vm-auto">✦ Agent 自动确认</button>'
        + '<label class="vm-check vm-auto-apply"><input type="checkbox" id="vm-auto-apply"> 直接应用</label>'
        + '<span class="vm-auto-state" id="vm-auto-state">'
        + (autoInfo ? '建议已生成，可调整后应用' : '模型逐节挑选来源；不可用时自动回退到最近更新优先')
        + '</span></div>'
      : '';
    var autoBanner = autoInfo
      ? '<div class="vm-auto-result ' + esc(autoInfo.mode || '') + '">'
        + '<div class="vm-auto-head">✦ Agent 建议 · '
        + (autoInfo.mode === 'agent'
            ? '模型 ' + esc(autoInfo.model || '（未命名）')
            : '规则回退')
        + ' · 采用 ' + (autoInfo.adopt_count || 0) + ' 处 / 保留基准 ' + (autoInfo.keep_count || 0) + ' 处</div>'
        + (autoInfo.note ? '<div class="vm-auto-note">' + esc(autoInfo.note) + '</div>' : '')
        + (Object.keys(autoInfo.reasons || {}).length
            ? '<details class="vm-auto-more"><summary>逐节理由（' + Object.keys(autoInfo.reasons).length + '）</summary>'
              + Object.keys(autoInfo.reasons).map(function (k) {
                  return '<div class="vm-auto-reason"><span>' + esc(k) + '</span><i>' + esc(autoInfo.reasons[k]) + '</i></div>';
                }).join('')
              + '</details>'
            : '')
        + '</div>'
      : '';

    var archived = (d.archived || []).map(function (row) {
      return '<div class="vm-arow"><span class="vm-vtext"><b>' + esc(row.title || row.id) + '</b>'
        + '<span class="vm-vmeta">归档于 ' + esc(String(row.archived_at || '').replace('T', ' ').slice(0, 16))
        + ' · ' + esc(row.origin || '') + '</span></span>'
        + '<button class="secondary-btn" data-vm-restore="' + esc(row.file) + '">取回</button></div>';
    }).join('');

    var forkHint = '<div class="vm-hint">这一族<b>当前没有分叉</b>：只有基条一条。'
      + '当你<b>再建一条同名不同版</b>（如 <code>' + esc((base.title || '') + '（v2）')
      + '</code>，界面或 MCP 都行），或族里已有版本后再改基条时，这里就会出现可对照、可合并的版本。</div>';

    pane.innerHTML = ''
      + '<div class="vm-head"><div><div class="card-kicker">' + esc(KIND_LABEL[base.kind] || base.kind || '')
      + '</div><h3>' + esc(base.title || d.base_id) + '</h3>'
      + '<div class="row-meta">基条 <code>' + esc(d.base_id) + '</code> · '
      + (d.forked ? '<b>' + variants.length + ' 个活版本</b>（合并前任何一版都不会被覆盖）' : '当前没有分叉')
      + '</div></div>'
      + '<button class="secondary-btn" id="vm-refresh">刷新</button></div>'

      + '<div class="vm-block"><h4>① 各版本' + (variants.length ? '（勾选后可归档）' : '') + '</h4>'
      + '<div class="vm-base-row"><span class="vm-vtext"><b>' + esc(base.title || '')
      + '</b><span class="vm-vmeta">基条 · 更新 '
      + esc(String(base.updated || '').replace('T', ' ').slice(0, 16)) + '</span></span>'
      + originChip(base) + '</div>'
      + (variants.length ? versionRows : forkHint) + '</div>'

      + (variants.length
          ? '<div class="vm-block"><h4>② 需要确认的改动（一致的小节自动沿用基准）</h4>' + summary + autoBar + autoBanner + sectionRows
            + sameBlock
            + '<label class="vm-check"><input type="checkbox" id="vm-archive-after" checked> 合并后把被替换的版本一并归档</label>'
            + '<div class="vm-actions"><button class="primary-btn" id="vm-merge">应用 '
            + (changedCount || 0) + ' 处改动</button>'
            + '<button class="secondary-btn" id="vm-archive">归档勾选的版本</button></div></div>'
          : '')

      + (archived ? '<div class="vm-block"><h4>③ 已归档（保留可追溯）</h4>' + archived + '</div>' : '')

      + '<div class="vm-block"><h4>④ 修改记录（最近 90 天）</h4>'
      + '<div class="vm-hint" style="margin-bottom:8px">谁在什么时候改了什么：'
      + '「外部 MCP 客户端 · kb_update_entry · 客户端名」这类来源会直接写在这里。</div>'
      + '<div id="vm-history"><div class="empty compact">正在读取…</div></div></div>';

    loadHistory(d.base_id, main);
    pane.querySelector('#vm-refresh').onclick = function () { loadDetail(d.base_id, main); };
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-pick]'), function (sel) {
      sel.onchange = function () {
        if (sel.value) STATE.picks[sel.dataset.vmPick] = sel.value;
        else delete STATE.picks[sel.dataset.vmPick];
        // 换了来源 → 该小节的差异徽章与 diff 立即跟着变
        var heading = sel.dataset.vmPick;
        var row = pane.querySelector('[data-vm-srow="' + heading.replace(/"/g, '\\"') + '"]');
        if (!row) return;
        var info = statusFor(heading), st = info.st;
        var badge = row.querySelector('.vm-sbadge');
        if (badge) { badge.textContent = st.label; badge.className = 'vm-sbadge ' + st.kind; }
        var wrap = row.querySelector('[data-vm-dwrap]');
        if (wrap) { wrap.innerHTML = st.diff ? diffHtml(st.diff) : ''; }
      };
    });
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-diff]'), function (btn) {
      btn.onclick = function () {
        var heading = btn.dataset.vmDiff;
        var wrap = pane.querySelector('[data-vm-dwrap="' + heading.replace(/"/g, '\\"') + '"]');
        if (wrap) wrap.hidden = !wrap.hidden;
        btn.textContent = wrap && !wrap.hidden ? '收起' : '看变更';
      };
    });
    var cmpSel = pane.querySelector('#vm-compare-sel');
    if (cmpSel) cmpSel.onchange = function () {
      STATE.compare = cmpSel.value;
      loadDetail(d.base_id, main);          // 换对照版本 → 重新计算徽章与差异
    };
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-compare]'), function (btn) {
      btn.onclick = function (event) {
        event.preventDefault();
        STATE.compare = btn.dataset.vmCompare;
        loadDetail(d.base_id, main);
      };
    });
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-adopt]'), function (btn) {
      btn.onclick = function (event) {
        event.preventDefault();
        var vid = btn.dataset.vmAdopt;
        var others = variants.filter(function (v) { return v.id !== vid; });
        var ask = others.length
          ? '以这版为准？基条内容会被这一版整篇替换，其余 ' + others.length + ' 个版本将归档（可追溯）'
          : '以这版为准？基条内容会被这一版整篇替换';
        if (window.confirm && !window.confirm(ask)) return;
        post(API + '/adopt', { base_id: d.base_id, variant_id: vid, archive_others: true })
          .then(function (out) {
            toast('已采用该版本（其余 ' + ((out.archived || []).length) + ' 个已归档）');
            loadDetail(d.base_id, main);
          }).catch(function (e) { toast('采用失败：' + e.message, true); });
      };
    });

    function markChoice(heading, accept) {
      var box = pane.querySelector('[data-vm-choice="' + heading.replace(/"/g, '\\"') + '"]');
      if (!box) return;
      var on = box.querySelector('[data-vm-accept]'), off = box.querySelector('[data-vm-keep]');
      if (on) on.classList.toggle('on', accept);
      if (off) off.classList.toggle('on', !accept);
    }
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-accept]'), function (btn) {
      btn.onclick = function () {
        var heading = btn.dataset.vmAccept;
        STATE.picks[heading] = comparedId(heading);
        markChoice(heading, true);
      };
    });
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-keep]'), function (btn) {
      btn.onclick = function () {
        var heading = btn.dataset.vmKeep;
        delete STATE.picks[heading];
        markChoice(heading, false);
      };
    });

    var adoptLatest = pane.querySelector('#vm-adopt-latest');
    if (adoptLatest) adoptLatest.onclick = function () {
      var vid = latestId();
      if (!vid) return;
      if (window.confirm && !window.confirm('采用最新版本？基条内容会被它整篇替换，其余版本归档（可追溯）')) return;
      post(API + '/adopt', { base_id: d.base_id, variant_id: vid, archive_others: true })
        .then(function (out) {
          toast('已采用最新版本（其余 ' + ((out.archived || {}).archived || []).length + ' 个已归档）');
          loadDetail(d.base_id, main);
        }).catch(function (e) { toast('采用失败：' + e.message, true); });
    };

    var acceptAll = pane.querySelector('#vm-accept-all');
    if (acceptAll) acceptAll.onclick = function () {
      var vid = comparedId('');
      headings.forEach(function (heading) {
        var st = sectionStatus(baseMap[heading], (variantMaps[vid] || {})[heading]);
        if (st.kind === 'same') return;
        STATE.picks[heading] = vid;
        var sel = pane.querySelector('[data-vm-pick="' + heading.replace(/"/g, '\\"') + '"]');
        if (sel) sel.value = vid;
        var badge = pane.querySelector('[data-vm-srow="' + heading.replace(/"/g, '\\"') + '"] .vm-sbadge');
        if (badge) { badge.textContent = st.label; badge.className = 'vm-sbadge ' + st.kind; }
      });
      toast('已全部采用该版本的改动，点「应用 ' + changedCount + ' 处改动」写回基条');
    };

    var after = pane.querySelector('#vm-archive-after');
    if (after) after.onchange = function () { STATE.archiveAfter = after.checked; };
    var mergeBtn = pane.querySelector('#vm-merge');
    if (mergeBtn) mergeBtn.onclick = function () {
      var picks = {};
      Object.keys(STATE.picks).forEach(function (k) {
        var vid = STATE.picks[k];
        var sel = pane.querySelector('[data-vm-pick="' + k.replace(/"/g, '\\"') + '"]');
        if (sel && !sel.value) return;            // 多版本下拉里选了「基准」→ 不采用这处改动
        if (vid) picks[k] = vid;
      });
      if (!Object.keys(picks).length) { toast('没有要应用的改动（都被设成「基准」了）', true); return; }
      post(API + '/merge', { base_id: d.base_id, picks: picks, archive_merged: STATE.archiveAfter })
        .then(function (out) {
          toast('已合并：替换小节 ' + ((out.replaced_sections || []).join('、') || '（无）'));
          loadDetail(d.base_id, main);
        }).catch(function (e) { toast('合并失败：' + e.message, true); });
    };
    var autoBtn = pane.querySelector('#vm-auto');
    if (autoBtn) autoBtn.onclick = function () {
      var applyNow = !!(pane.querySelector('#vm-auto-apply') && pane.querySelector('#vm-auto-apply').checked);
      var stateEl = pane.querySelector('#vm-auto-state');
      autoBtn.disabled = true;
      if (stateEl) stateEl.textContent = '分析中…' + (applyNow ? '（直接应用）' : '（只给建议）');
      post(API + '/auto-merge', { base_id: d.base_id, apply: applyNow, archive_merged: STATE.archiveAfter })
        .then(function (out) {
          if (out.applied) {
            var replaced = (out.merge && out.merge.replaced_sections) || [];
            toast('Agent 已自动合并：替换 ' + (replaced.join('、') || '（无）'));
            loadDetail(d.base_id, main);
            return;
          }
          STATE.picks = out.picks || {};
          STATE.autoInfo = out;
          paintDetail(main);
          toast('Agent 已选择 ' + (out.adopt_count || 0) + ' 处采用、' + (out.keep_count || 0) + ' 处保留基准；检查后点「应用」写回基条');
        })
        .catch(function (e) {
          autoBtn.disabled = false;
          if (stateEl) stateEl.textContent = '';
          toast('自动确认失败：' + e.message, true);
        });
    };
    var archBtn = pane.querySelector('#vm-archive');
    if (archBtn) archBtn.onclick = function () {
      var ids = Array.prototype.slice.call(pane.querySelectorAll('[data-vm-archive]:checked'))
        .map(function (box) { return box.dataset.vmArchive; });
      if (!ids.length) { toast('先勾选要归档的版本', true); return; }
      post(API + '/archive', { base_id: d.base_id, variant_ids: ids })
        .then(function (out) { toast('已归档 ' + ((out.archived || []).length) + ' 个版本'); loadDetail(d.base_id, main); })
        .catch(function (e) { toast('归档失败：' + e.message, true); });
    };
    Array.prototype.forEach.call(pane.querySelectorAll('[data-vm-restore]'), function (btn) {
      btn.onclick = function () {
        post(API + '/restore', { base_id: d.base_id, file: btn.dataset.vmRestore })
          .then(function () { toast('已取回成一个新版本'); loadDetail(d.base_id, main); })
          .catch(function (e) { toast('取回失败：' + e.message, true); });
      };
    });
  }

  if (!window.ERWPanels) return;
  window.ERWPanels.register({
    id: 'version-manager',
    /* v261021 · 按用户要求从「研究 · 知识」移到「系统」：版本是全局维护动作，
       与具体研究条目并列在知识组里并不合语义；排在「设置」之前。 */
    group: 'system',
    before: 'settings',
    label: '版本',
    icon: '⑂',
    eyebrow: 'VERSIONS',
    title: '版本',
    render: function (main) { render(main); },
  });
})();
