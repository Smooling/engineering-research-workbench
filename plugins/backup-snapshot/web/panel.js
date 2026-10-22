/* 备份与快照 · 插件面板 v1.0.0
 * 自登记侧栏导航页；样式全部落在 [data-plugin="backup-snapshot"] 内。
 */
(function () {
  'use strict';

  var ID = 'backup-snapshot';

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

  function kb(bytes) { return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + ' MB' : (bytes / 1024).toFixed(0) + ' KB'; }

  function renderConfig(cfg) {
    el('#bk-interval').value = cfg.interval_hours;
    el('#bk-keep').value = cfg.keep;
    el('#bk-dest').value = cfg.dest_dir || '';
    el('#bk-proj').checked = !!cfg.include_projects_text;
    el('#bk-att').checked = !!cfg.include_attachments;
    el('#bk-idx').checked = !!cfg.include_index;
    el('#bk-auto').checked = cfg.auto_enabled !== false;
  }

  function configPayload() {
    return {
      interval_hours: Number(el('#bk-interval').value) || 24,
      keep: Number(el('#bk-keep').value) || 7,
      dest_dir: el('#bk-dest').value.trim(),
      include_projects_text: el('#bk-proj').checked,
      include_attachments: el('#bk-att').checked,
      include_index: el('#bk-idx').checked,
      auto_enabled: el('#bk-auto').checked,
    };
  }

  function renderList(data) {
    var items = data.items || [];
    var state = data.state || {};
    el('#bk-summary').innerHTML = ''
      + '<div class="bk-stat"><span>快照目录</span><b>' + esc(data.dir) + '</b>'
      + (data.is_default_dir ? '<i>（默认：插件自己的命名空间；建议改到外部目录）</i>' : '<i>（外置目录）</i>') + '</div>'
      + '<div class="bk-stat"><span>已有快照</span><b>' + data.count + ' 份 · ' + kb(data.total_bytes) + '</b></div>'
      + '<div class="bk-stat"><span>上次备份</span><b>' + esc(state.last_at || '（还没备份过）') + '</b>'
      + (state.last_name ? '<i>' + esc(state.last_name) + (state.last_bytes ? ' · ' + kb(state.last_bytes) : '') + '</i>' : '') + '</div>';
    el('#bk-list').innerHTML = items.length
      ? '<div class="bk-rows">' + items.map(function (it) {
          var url = '/api/plugins/' + ID + '/download?name=' + encodeURIComponent(it.name);
          return '<div class="bk-row"><code>' + esc(it.name) + '</code><span>' + kb(it.bytes) + '</span>'
            + '<span class="bk-muted">' + esc(it.at.replace('T', ' ')) + '</span>'
            + '<button class="secondary-btn" type="button" data-bk-inspect="' + esc(it.name) + '">查看内容</button>'
            + '<a class="secondary-btn" href="' + url + '" download>下载</a>'
            + '<button class="secondary-btn danger" type="button" data-bk-del="' + esc(it.name) + '">删除</button></div>';
        }).join('') + '</div>'
      : '<div class="bk-empty">还没有快照。点「立即备份」生成第一份。</div>';
    if (el('#bk-inspect')) el('#bk-inspect').innerHTML = '';
  }

  function wireList(root) {
    Array.prototype.slice.call(root.querySelectorAll('[data-bk-del]')).forEach(function (btn) {
      btn.onclick = function () {
        var name = btn.dataset.bkDel;
        if (!window.confirm('删除快照 ' + name + '？（只删这一个文件，知识库不受影响）')) return;
        btn.disabled = true;
        api('delete', { name: name }).then(function (data) {
          if (!data.ok) { toast('删除失败：' + data.error, true); btn.disabled = false; return; }
          toast('已删除 ' + name);
          renderList(data.snapshots);
          wireList(root);
        }).catch(function (e) { toast('删除失败：' + e.message, true); btn.disabled = false; });
      };
    });
    Array.prototype.slice.call(root.querySelectorAll('[data-bk-inspect]')).forEach(function (btn) {
      btn.onclick = function () {
        api('inspect', { name: btn.dataset.bkInspect }).then(function (data) {
          if (!data.ok) { toast('读取失败：' + data.error, true); return; }
          var bydir = Object.keys(data.by_dir || {}).map(function (k) {
            return '<li><code>' + esc(k) + '</code> ' + data.by_dir[k] + ' 个文件</li>';
          }).join('');
          el('#bk-inspect').innerHTML = '<div class="bk-inspect-box">'
            + '<b>快照内容 · ' + esc(btn.dataset.bkInspect) + '</b>'
            + '<div class="bk-muted">共 ' + data.entries + ' 个文件 · 生成于 '
            + esc((data.manifest || {}).created || '?') + ' · 原因 '
            + esc((data.manifest || {}).reason || '?') + ' · 内核 '
            + esc((data.manifest || {}).kernel_version || '?') + '</div>'
            + '<ul>' + bydir + '</ul>'
            + '<div class="bk-muted">恢复方式：下载 zip → 关闭工作台 → 解压覆盖对应目录。'
            + '本插件<b>不</b>做自动恢复（覆盖用户数据必须由你确认）。</div></div>';
        }).catch(function (e) { toast('读取失败：' + e.message, true); });
      };
    });
  }

  function render(main) {
    main.innerHTML = ''
      + '<section class="card card-pad bk-card">'
      +   '<div class="card-kicker">BACKUP / SNAPSHOT</div>'
      +   '<h3>备份与快照</h3>'
      +   '<p class="row-meta">把<b>知识库本体与配置</b>打成时间戳 zip：默认只收小体积的关键数据（几 MB），'
      +     '附件与派生索引默认不收。自动备份由内核调度，按间隔执行并按份数清理。</p>'
      +   '<div class="bk-summary" id="bk-summary"></div>'
      +   '<div class="bk-actions">'
      +     '<button class="primary-btn" id="bk-now" type="button">立即备份</button>'
      +     '<button class="secondary-btn" id="bk-refresh" type="button">刷新列表</button>'
      +     '<span class="bk-muted" id="bk-job"></span>'
      +   '</div>'
      +   '<div class="bk-opts">'
      +     '<label><span>自动间隔（小时）</span><input id="bk-interval" type="number" min="0.5" step="0.5" value="24"></label>'
      +     '<label><span>保留份数</span><input id="bk-keep" type="number" min="1" max="60" value="7"></label>'
      +     '<label class="bk-wide"><span>目标目录（留空 = 插件自己的命名空间）</span>'
      +       '<input id="bk-dest" type="text" placeholder="D:\\Backups\\erw"></label>'
      +   '</div>'
      +   '<div class="bk-checks">'
      +     '<label><input type="checkbox" id="bk-proj"> 收录项目文本（Notes/Manuscript/*.md 等）</label>'
      +     '<label><input type="checkbox" id="bk-att"> 收录附件与大文件（PDF/图片/办公文档，体积大）</label>'
      +     '<label><input type="checkbox" id="bk-idx"> 收录派生索引（可重建，一般不必）</label>'
      +     '<label><input type="checkbox" id="bk-auto" checked> 启用自动备份</label>'
      +     '<button class="secondary-btn" id="bk-save" type="button">保存设置</button>'
      +   '</div>'
      +   '<div id="bk-list"></div>'
      +   '<div id="bk-inspect"></div>'
      + '</section>';

    function load() {
      api('status').then(function (data) {
        if (!data.ok) { toast('读取状态失败', true); return; }
        renderList(data.snapshots);
        renderConfig(data.snapshots.config);
        wireList(main);
        var job = data.job || {};
        el('#bk-job').textContent = job.name
          ? ('后台任务 ' + job.name + '：已跑 ' + (job.runs || 0) + ' 次'
             + (job.failures ? '，失败 ' + job.failures + ' 次（' + (job.last_error || '') + '）' : '')
             + (job.running ? ' · 正在运行' : ''))
          : '';
      }).catch(function (e) { toast('读取状态失败：' + e.message, true); });
    }

    el('#bk-now').onclick = function () {
      var btn = el('#bk-now');
      btn.disabled = true;
      btn.textContent = '备份中…';
      api('snapshot', {}).then(function (data) {
        if (!data.ok) { toast('备份失败：' + data.error, true); return; }
        toast('已生成 ' + data.file + '（' + data.files + ' 文件 / ' + kb(data.bytes) + '）');
        var skipped = data.skipped_summary || {};
        var parts = Object.keys(skipped).map(function (k) { return k + ' ' + skipped[k] + ' 个'; });
        if (parts.length) toast('按设置未收录：' + parts.join('、'));
        load();
      }).catch(function (e) { toast('备份失败：' + e.message, true); })
        .then(function () { btn.disabled = false; btn.textContent = '立即备份'; });
    };
    el('#bk-refresh').onclick = load;
    el('#bk-save').onclick = function () {
      api('config', configPayload()).then(function () {
        toast('设置已保存（下轮自动备份按新间隔判断）');
        load();
      }).catch(function (e) { toast('保存失败：' + e.message, true); });
    };
    load();
  }

  if (!window.ERWPanels) return;
  window.ERWPanels.register({
    id: ID,
    group: 'system',
    before: 'settings',
    label: '备份快照',
    icon: '❐',
    eyebrow: 'SAFETY NET',
    title: '备份与快照',
    render: function (main) { render(main); },
  });
})();
