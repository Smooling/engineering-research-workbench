/* __NAME__ 面板 · 插件模板
 *
 * 自登记（PLUGIN_SPEC §6.3）：导航项与设置 tab 都由**本文件**声明，内核不认识本插件——
 * 所以「加一个插件」不需要改内核的任何一行代码，也不会动到原来的内核 UI。
 *
 * 四条约定（详见 docs/PLUGIN_SPEC.md §6.1）：
 *   1. 只通过 `window.ERW*` 接缝接触内核，**不要改内核 DOM/CSS**（P14 红线）；
 *   2. 样式写在 `[data-plugin="__ID__"]` 作用域里（内核会给挂载容器打这个属性），别写裸选择器；
 *   3. 调自己的后端用 `window.erwFetch`，**别替换 `window.fetch`**；
 *   4. 可选接缝一律做空值保护——插件缺席或旧内核时，页面照常可用（I1）。
 *
 * 内核给的挂载点（都会带 `data-plugin="__ID__"`）：导航页 `#main`、设置页 `#settings-panel`、
 * 槽位容器；阅读区 tab 由阅读区插件自己的容器负责。
 */
(function () {
  'use strict';

  var ID = '__ID__';

  function el(sel, root) { return (root || document).querySelector(sel); }

  /* 内核提示条（可选接缝）：缺席时退化成 console，不要自己再造一套 toast */
  function toast(message, error) {
    if (typeof window.ERWToast === 'function') { window.ERWToast(message, error); return; }
    console.log('[' + ID + '] ' + message);
  }

  /* 调插件自己的后端：相对路径，内核会挂到 /api/plugins/__ID__/ 下 */
  function api(path, init) {
    var f = window.erwFetch || window.fetch;
    return f('/api/plugins/' + ID + '/' + path, init).then(function (r) { return r.json(); });
  }

  function render(main) {
    main.innerHTML = ''
      + '<section class="card card-pad tp-card">'
      +   '<div class="card-kicker">PLUGIN TEMPLATE</div>'
      +   '<h3>__NAME__</h3>'
      +   '<p class="row-meta">最小可用页面：读自己的配置、调自己的后端、把结果画出来。'
      +     '删掉这段、换成你的界面即可。</p>'
      +   '<div class="tp-row">'
      +     '<label for="tp-greeting">问候语（存在插件自己的配置里）</label>'
      +     '<input id="tp-greeting" type="text" placeholder="你好">'
      +   '</div>'
      +   '<div class="tp-actions">'
      +     '<button class="primary-btn" id="tp-save" type="button">保存配置</button>'
      +     '<button class="secondary-btn" id="tp-call" type="button">调用 /hello</button>'
      +   '</div>'
      +   '<pre class="tp-out" id="tp-out">还没调用过后端。</pre>'
      +   '<div class="tp-hint" id="tp-kinds"></div>'
      + '</section>';

    api('config').then(function (cfg) {
      if (el('#tp-greeting')) el('#tp-greeting').value = (cfg && cfg.greeting) || '';
    }).catch(function (e) {
      if (el('#tp-out')) el('#tp-out').textContent = '读配置失败：' + e.message;
    });

    /* 内核只读契约（可选接缝）：七类 kind / 标记 / 关系的中文名直接取，别在自己插件里再抄一份 */
    if (window.ERWContract && el('#tp-kinds')) {
      var labels = window.ERWContract.kindLabels ? window.ERWContract.kindLabels() : {};
      el('#tp-kinds').textContent = '内核契约里的类别：'
        + Object.keys(labels).map(function (k) { return labels[k]; }).join(' / ');
    }

    if (el('#tp-save')) el('#tp-save').onclick = function () {
      api('config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ greeting: el('#tp-greeting').value })
      }).then(function () { toast('配置已保存'); })
        .catch(function (e) { toast('保存失败：' + e.message, true); });
    };

    if (el('#tp-call')) el('#tp-call').onclick = function () {
      api('hello').then(function (data) {
        if (el('#tp-out')) el('#tp-out').textContent = JSON.stringify(data, null, 2);
      }).catch(function (e) {
        if (el('#tp-out')) el('#tp-out').textContent = '调用失败：' + e.message;
      });
    };
  }

  if (!window.ERWPanels) return;   /* 旧内核或极端装配：安静退出，不要炸整页 */

  /* ① 侧栏导航页（组与位置可以改；不写 group 默认进「系统」组） */
  window.ERWPanels.register({
    id: ID,
    group: 'system',
    before: 'settings',
    label: '__NAME__',
    icon: '__ICON__',
    eyebrow: 'PLUGIN',
    title: '__NAME__',
    render: function (main) { render(main); },
  });

  /* ② 设置页 tab（同一个脚本能登记多个点；不需要就删掉这一段） */
  window.ERWPanels.register({
    id: ID + '-settings',
    label: '__NAME__',
    settingsTab: {
      id: ID,
      label: '__NAME__',
      render: function (container) {
        container.innerHTML = '<div class="card-head"><div><div class="card-kicker">PLUGIN SETTINGS</div>'
          + '<h3>__NAME__ 设置</h3></div></div>'
          + '<p class="row-meta">这里读写的是插件自己的配置（<code>POST /api/plugins/__ID__/config</code>）。'
          + '内核的设置页不需要为它改一行。</p>';
      },
    },
  });
})();
