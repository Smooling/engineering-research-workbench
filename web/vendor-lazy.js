/* vendor-lazy.js · v261009 —— 重型前端库按需加载（A1）
 *
 * 背景：mathjax-tex-svg.js（2.11 MB）与 mermaid.min.js（2.57 MB）原先在 index.html 里
 * **无条件 defer**，首屏就要下载 4.7 MB；而它们只在「正文真的出现公式 / 图形」时才需要。
 * 现在改为：调用方在真正用到时 `await window.erwVendor.load('mathjax'|'mermaid')`，
 * 本地文件失败时按原先 onerror 的行为回退 CDN。
 *
 * 约定：
 * - 同一库只加载一次（共享 Promise）；失败后允许下次重试。
 * - MathJax 的 typeset 配置仍在 index.html 内联（必须在脚本加载前就位）。
 * - `hasMath(text)` 用来判断"这段文本值不值得拉 MathJax"，避免纯文本预览白拉 2 MB。
 */
(function () {
  'use strict';

  var SOURCES = {
    mathjax: {
      local: '/vendor/mathjax-tex-svg.js',
      cdn: 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-svg.min.js',
      ready: function () { return !!window.MathJax; }
    },
    mermaid: {
      local: '/vendor/mermaid.min.js',
      cdn: 'https://unpkg.com/mermaid@11.4.1/dist/mermaid.min.js',
      ready: function () { return !!window.mermaid; }
    }
  };

  var pending = {};

  function inject(src) {
    return new Promise(function (resolve, reject) {
      var el = document.createElement('script');
      el.src = src;
      el.async = true;
      el.onload = function () { resolve(true); };
      el.onerror = function () { el.remove(); reject(new Error('vendor load failed: ' + src)); };
      document.head.appendChild(el);
    });
  }

  function load(name) {
    var spec = SOURCES[name];
    if (!spec) return Promise.reject(new Error('unknown vendor: ' + name));
    if (spec.ready()) return Promise.resolve(true);
    if (pending[name]) return pending[name];
    pending[name] = inject(spec.local)
      .catch(function () { return inject(spec.cdn); })
      .then(function (ok) {
        if (!spec.ready()) throw new Error(name + ' 已下载但未就绪');
        return ok;
      })
      .catch(function (err) {
        pending[name] = null; /* 允许下次重试（例如中途断网后 Reload） */
        throw err;
      });
    return pending[name];
  }

  /* 只在文本真的含 TeX 标记时才认为需要 MathJax：$…$ / $$…$$ / \(…\) / \[…\] */
  function hasMath(text) {
    var s = String(text == null ? '' : text);
    return /\$\$[\s\S]+?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/.test(s);
  }

  window.erwVendor = { load: load, hasMath: hasMath, sources: SOURCES };
})();
