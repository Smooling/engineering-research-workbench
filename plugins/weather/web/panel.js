/* 天气面板 · 插件 weather v1.0.0
 *
 * 从 web/app.js 搬出：顶栏天气卡片（`loadWeather`）与设置页「天气」tab 的编辑区
 * （地点 / 经纬度 / 时区 / 启用 + 按地点搜坐标 + 保存并刷新）。
 *
 * 两处有意的变化（PLUGIN_SPEC §11.2 显式声明）：
 * 1. 天气设置从「设置页的一个 tab」改为**点顶栏卡片弹出的模态**——插件拥有自己的 UI，
 *    内核不再知道「天气」这个概念；
 * 2. 接口从 `/api/weather`、`/api/weather/geocode`、`/api/config/app` 的 weather 段
 *    变为 `/api/plugins/weather/*`。
 *
 * 挂载方式：这是**槽位面板**（manifest 里 `nav[].slot = "topbar"`），
 * 通过 `ERWPanels.register({... slot:'topbar', renderSlot(el)})` 把自己画进内核给的顶栏槽位
 * —— 不是去改内核 DOM。
 */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var esc = function (v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  function api(url, opts) {
    var init = Object.assign({}, opts || {}, { headers: { 'Content-Type': 'application/json' } });
    if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
    return (window.erwFetch || fetch)(url, init).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error((d && (d.message || d.error)) || ('HTTP ' + r.status));
        return d;
      });
    });
  }
  function toast(message, error) {
    if (typeof window.ERWToast === 'function') { window.ERWToast(message, error); return; }
    var stack = $('#toast-stack');
    if (!stack) return;
    var el = document.createElement('div');
    el.className = 'toast' + (error ? ' error' : '');
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(function () { el.remove(); }, 3200);
  }

  var pill = null;

  async function refresh(force) {
    if (!pill) return;
    var text = $('.weather-text', pill);
    var button = $('.weather-pill', pill);
    try {
      var w = await api('/api/plugins/weather/current' + (force ? '?force=1' : ''));
      if (!w.enabled) { text.textContent = '天气关闭'; button.title = '天气已在插件设置里关闭'; return; }
      if (w.unavailable) {
        text.textContent = '天气不可用';
        button.title = (w.reason || '网络不可用') + ' · 点此配置';
        return;
      }
      var d = (w.daily || [])[0];
      text.textContent = w.location + ' · ' + w.current.condition + ' ' + w.current.temperature + '° · '
        + (d && d.low != null ? d.low : '—') + '~' + (d && d.high != null ? d.high : '—') + '°';
      button.title = 'Open-Meteo · 体感 ' + w.current.apparent + '° · 降水 ' + w.current.precipitation + ' mm'
        + (w.stale ? '（当前为缓存内容：' + (w.reason || '') + '）' : '') + ' · 点此配置';
    } catch (e) {
      text.textContent = '天气不可用';
      button.title = e.message;
    }
  }

  function openSettings() {
    if (!$('#modal-backdrop')) return;
    api('/api/plugins/weather/config').then(function (w) {
      var body = '<div class="card-head"><div><div class="card-kicker">OPEN-METEO</div><h3>天气设置</h3></div>'
        + '<span class="badge accent">无需 API Key</span></div>'
        + '<div class="form-grid">'
        + '<div class="field"><label>启用天气</label><select id="w-enabled">'
        + '<option value="1" ' + (w.enabled !== false ? 'selected' : '') + '>启用</option>'
        + '<option value="0" ' + (w.enabled === false ? 'selected' : '') + '>关闭</option></select></div>'
        + '<div class="field span-2"><label>地点名称</label><input id="w-location" value="' + esc(w.location || '') + '"></div>'
        + '<div class="field"><label>纬度</label><input id="w-lat" type="number" step="0.0001" value="' + (w.latitude != null ? w.latitude : '') + '"></div>'
        + '<div class="field"><label>经度</label><input id="w-lon" type="number" step="0.0001" value="' + (w.longitude != null ? w.longitude : '') + '"></div>'
        + '<div class="field span-2"><label>时区</label><input id="w-tz" value="' + esc(w.timezone || 'Asia/Shanghai') + '"></div>'
        + '</div><div style="margin-top:14px;display:flex;gap:7px">'
        + '<button class="secondary-btn" id="weather-geocode">根据地点搜索坐标</button>'
        + '<button class="primary-btn" id="weather-save">保存并刷新天气</button></div>';
      var backdrop = $('#modal-backdrop');
      $('#modal-title').textContent = '天气';
      $('#modal-body').innerHTML = body;
      $('#modal-footer').innerHTML = '<button class="secondary-btn" id="weather-close">关闭</button>';
      backdrop.classList.remove('hidden');
      $('#weather-close').onclick = function () { backdrop.classList.add('hidden'); };
      $('#weather-geocode').onclick = async function () {
        try {
          var r = await api('/api/plugins/weather/geocode?name=' + encodeURIComponent($('#w-location').value));
          if (!(r.results || []).length) { toast(r.reason || '没有找到地点', true); return; }
          var x = r.results[0];
          $('#w-lat').value = x.latitude;
          $('#w-lon').value = x.longitude;
          $('#w-tz').value = x.timezone || 'auto';
          toast('已匹配：' + x.name + ' ' + (x.admin1 || ''));
        } catch (e) { toast(e.message, true); }
      };
      $('#weather-save').onclick = async function () {
        try {
          await api('/api/plugins/weather/config?refresh=1', {
            method: 'POST',
            body: {
              enabled: $('#w-enabled').value === '1',
              location: $('#w-location').value,
              latitude: $('#w-lat').value,
              longitude: $('#w-lon').value,
              timezone: $('#w-tz').value,
            },
          });
          toast('天气设置已保存');
          backdrop.classList.add('hidden');
          refresh(true);
        } catch (e) { toast(e.message, true); }
      };
    }).catch(function (e) { toast('天气设置读取失败：' + e.message, true); });
  }

  function renderSlot(container) {
    container.innerHTML = '<button class="weather-pill" id="weather-pill" type="button" title="天气详情">'
      + '<span class="status-dot"></span><span class="weather-text" id="weather-text">天气加载中</span></button>';
    pill = container;
    $('#weather-pill', container).onclick = openSettings;
    refresh(false);
  }

  if (window.ERWPanels) {
    window.ERWPanels.register({
      id: 'weather', slot: 'topbar',
      label: '天气',
      renderSlot: function (container) { renderSlot(container); },
    });
  }
})();
