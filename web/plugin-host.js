/* plugin-host.js · v261009 —— 插件前端宿主（§6.3 前端面板）
 *
 * 内核不知道任何具体功能：它把「已校验可用且启用」的插件清单（`GET /api/plugins`）
 * 下发给本宿主，宿主按清单把面板脚本挂进来；面板脚本自己在 eval 期调用
 * `window.ERWPanels.register(...)` 登记导航项、页头与渲染函数。
 *
 * 三条约定：
 * 1. **内核零插件可跑**：清单为空（或请求失败）时宿主什么都不做，页面照常工作；
 * 2. **单插件失败不影响内核与其它插件**（I4）：每个面板单独 try/catch，
 *    失败原因记进 `ERWPluginHost.failures` 并以 console.error 明示（I11 不得静默失败）；
 * 3. **顺序**：`ERWPluginHost.ready` 在全部面板加载尝试结束后 resolve；
 *    `app.js` 在构建侧栏之前 await 它，保证登记过的导航项能出现在侧栏里。
 */
(function () {
  'use strict';

  var host = {
    ready: null,
    plugins: [],
    loaded: [],
    failures: [],
  };

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var el = document.createElement('script');
      el.src = src;
      el.async = false; /* 同一批面板按清单顺序执行 */
      el.onload = function () { resolve(true); };
      el.onerror = function () {
        el.remove();
        reject(new Error('面板脚本加载失败：' + src));
      };
      document.head.appendChild(el);
    });
  }

  function loadStyle(href) {
    if (document.querySelector('link[data-plugin-style="' + href + '"]')) return;
    var el = document.createElement('link');
    el.rel = 'stylesheet';
    el.href = href;
    el.dataset.pluginStyle = href;
    document.head.appendChild(el);
  }

  async function boot() {
    var data;
    try {
      var res = await (window.erwFetch || fetch)('/api/plugins');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      data = await res.json();
    } catch (err) {
      host.failures.push({ id: '', error: '插件清单不可用：' + (err && err.message ? err.message : err) });
      console.warn('[plugins] 清单不可用，按「零插件」继续运行', err);
      return;
    }
    host.plugins = (data && data.plugins) || [];
    for (var i = 0; i < host.plugins.length; i++) {
      var plugin = host.plugins[i] || {};
      /* 面板脚本来源两种：nav[0]（有导航页的插件）与 panel_url（**没有导航页**的 UI——
         只贡献阅读区/设置页 tab 或槽位组件，如 litnote 的「笔记」tab）。都没有就跳过。 */
      var nav = (plugin.nav || [])[0];
      var scriptUrl = (nav && nav.url) || plugin.panel_url || '';
      var styleUrl = (nav && nav.style_url) || plugin.panel_style_url || '';
      if (!scriptUrl) continue;
      try {
        if (styleUrl) loadStyle(styleUrl); /* 插件自带样式，按 §2 作用域 */
        await loadScript(scriptUrl);
        host.loaded.push(plugin.id);
      } catch (err) {
        var reason = (err && err.message) ? err.message : String(err);
        host.failures.push({ id: plugin.id, error: reason });
        console.error('[plugins] ' + plugin.id + ' 面板加载失败：' + reason +
          '（该插件不会出现在侧栏；其余功能不受影响。用 python -m core.plugins check ' + plugin.id + ' 排查）');
      }
    }
  }

  host.ready = boot();
  window.ERWPluginHost = host;
})();
