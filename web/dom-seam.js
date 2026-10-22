/* dom-seam.js · v261009 —— 共享 DOM 变更订阅（A9：MutationObserver 收敛）
 *
 * 背景：7 个补丁各自 `new MutationObserver(...)` 观察整棵 `#main` / `body` / `documentElement`，
 * 一次 DOM 变更要跑 7 遍回调，且每个都要自己写过滤与合并（P14 点名的「各自为政的接缝」）。
 *
 * 现在只保留**一个** MutationObserver，订阅方通过 `ERWDom.onChildList(cb, opts)` 注册：
 *   - `root`：只关心该子树内的变更（选择器或元素；缺省 = document.body），
 *     语义与原先「observe(root)」一致；
 *   - `ignore`：命中的变更直接跳过（如浮球面板、PDF 阅读区的内部高频增删）；
 *   - 合并：同一帧内多次变更只回调一次（原来各补丁自己 debounce/rAF，现在由接缝统一做）；
 *   - 隔离：某个订阅方抛异常不影响其它订阅方与内核。
 *
 * 约定：本文件必须在所有补丁之前加载（补丁在求值期就会注册）。属性观察（attributeFilter）
 * 与 ResizeObserver / IntersectionObserver 不走这里——它们观察的语义不同。
 */
(function () {
  'use strict';

  var subscribers = [];
  var pending = [];
  var queued = false;

  function resolveRoot(spec) {
    if (!spec) return document.body;
    if (typeof spec === 'string') return document.querySelector(spec) || document.body;
    return spec;
  }

  function flush() {
    queued = false;
    var batch = pending;
    pending = [];
    for (var i = 0; i < batch.length; i++) {
      try {
        batch[i].cb();
      } catch (err) {
        console.warn('[ERWDom] 订阅方回调失败（已隔离，不影响其它订阅方）', err);
      }
    }
  }

  var observer = new MutationObserver(function (records) {
    for (var r = 0; r < records.length; r++) {
      var rec = records[r];
      if (rec.type !== 'childList') continue;
      for (var s = 0; s < subscribers.length; s++) {
        var sub = subscribers[s];
        var target = rec.target;
        if (target instanceof Element && sub.ignoreSelector && target.closest(sub.ignoreSelector)) continue;
        var root = resolveRoot(sub.rootSpec);
        if (!root) continue;
        if (root !== target && !(target instanceof Element && root.contains(target))) continue;
        if (pending.indexOf(sub) < 0) pending.push(sub);
      }
    }
    if (pending.length && !queued) {
      queued = true;
      requestAnimationFrame(flush);
    }
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.ERWDom = {
    /** 订阅文档级 childList 变更；返回取消订阅函数。 */
    onChildList: function (cb, opts) {
      var options = opts || {};
      if (typeof cb !== 'function') throw new Error('ERWDom.onChildList 需要回调函数');
      var sub = { cb: cb, rootSpec: options.root || null, ignoreSelector: options.ignore || null };
      subscribers.push(sub);
      return function off() {
        var i = subscribers.indexOf(sub);
        if (i >= 0) subscribers.splice(i, 1);
      };
    },
    /** 体检用：订阅方数量（Observer 实例永远只有 1 个）。 */
    subscriberCount: function () { return subscribers.length; },
    observerCount: function () { return 1; },
    /** 强制跑一帧（面板渲染完想立刻对齐时用）。 */
    flushNow: function () { if (queued) flush(); },
  };
})();
