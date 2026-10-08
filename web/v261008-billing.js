/* v261008 · 用量计费仪表盘（自包含模块）
 * 数据来源：GET /api/billing/summary | /api/billing/records | /api/billing/prices
 *           POST /api/billing/prices | DELETE /api/billing/records
 * 入口：#main 渲染，由 app.js 的 renderBillingPage() 调用 window.ERWBilling.render(main)。
 */
(() => {
  'use strict';

  const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (n) => Number(n||0).toLocaleString('zh-CN');
  const usd = (v) => { const x = Number(v)||0; return '$' + (x>=1 ? x.toFixed(2) : x>=0.01 ? x.toFixed(4) : x.toFixed(6)); };
  const pct = (v) => `${(Number(v||0)*100).toFixed(1)}%`;
  const toast = (m, err=false) => { const f = window.ERWToast; if (typeof f === 'function') return f(m, err); const t=document.createElement('div'); t.className='toast'+(err?' error':''); t.textContent=m; document.querySelector('#toast-stack')?.appendChild(t); setTimeout(()=>t.remove(),3200); };
  const fmtTime = (s) => { if(!s) return '—'; try { return new Date(s).toLocaleString('zh-CN',{hour12:false}); } catch { return s; } };

  async function api(url, opts={}) {
    const init = {...opts, headers:{'Content-Type':'application/json', ...(opts.headers||{})}};
    if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
    const res = await fetch(url, init);
    let data = null; try { data = await res.json(); } catch { data = {}; }
    if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
    return data;
  }

  const st = { tab:'overview', summary:null, prices:null, rec:{items:[], total:0, offset:0, sessionId:''} };

  function shellHtml() {
    return `<div class="billing-page">
      <div class="card card-pad">
        <div class="card-head"><div><div class="card-kicker">USAGE / COST</div><h3>用量与费用</h3>
        <p class="row-meta">统计 Agent 对话与 AI 阅读助手的 token 用量，按 Provider 单价表计费。数据落盘于 <code>Workspace/System/billing/ledger.jsonl</code>（只增不改）。</p></div>
        <button class="secondary-btn" id="billing-refresh" type="button">↻ 刷新</button></div>
        <div class="billing-tabs">
          <button data-btab="overview" class="active" type="button">概览</button>
          <button data-btab="records" type="button">调用明细</button>
          <button data-btab="prices" type="button">单价表</button>
        </div>
      </div>
      <div id="billing-body"><div class="card card-pad billing-muted">加载中…</div></div>
    </div>`;
  }

  function table(head, rows) {
    return `<div class="billing-scroll"><table class="billing-table"><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
  }
  const emptyRow = (cols) => `<tr><td colspan="${cols}" class="billing-muted">暂无数据</td></tr>`;

  const MODE_LABEL = { subscription:'订阅', free:'免费', token:'按量', mixed:'混合' };
  const modeBadge = (mode) => mode && mode !== 'token'
    ? `<span class="billing-badge billing-mode" title="订阅/免费档案：只统计用量，不做按量计费">${esc(MODE_LABEL[mode]||mode)}</span>`
    : '';

  function renderOverview() {
    const s = st.summary || {}; const t = s.total || {};
    const sub = t.subscription_calls||0, unp = t.unpriced_calls||0, miss = t.missing_usage_calls||0;
    const hit = Number(t.cache_hit_rate||0);
    const subEq = Number(t.subscription_equiv_usd||0);
    const cards = [
      ['总花费（按量）', usd(t.cost_usd),
        sub ? `另有 ${num(sub)} 次为订阅制（不计按量费用）` : (unp ? `${num(unp)} 次调用缺单价（记 0，见下方清单）` : `${s.unit||'USD'} · 累计`)],
      ['等价标价合计', usd(t.equiv_usd),
        subEq > 0 ? `按单价表折算；其中订阅内 ${num(sub)} 次 ≈ ${usd(subEq)}（参考，非实付）` : '按当前单价表折算（参考，非实付）'],
      ['调用次数', num(t.calls), miss ? `其中 ${num(miss)} 次网关未返回 usage` : '含所有模型与订阅调用'],
      ['总 tokens', num(t.total_tokens), `输入 ${num(t.prompt_tokens)} · 输出 ${num(t.completion_tokens)}`],
      ['缓存命中率', `${(hit*100).toFixed(1)}%`, `命中 ${num(t.cached_tokens)} · 计费输入 ${num(t.miss_input_tokens)}`],
    ];
    const cardHtml = `<div class="billing-cards">${cards.map(([k,v,sub2])=>`<div class="billing-card"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${esc(sub2)}</div></div>`).join('')}</div>`;

    const sessRows = (s.by_session||[]).map(x=>`<tr><td>${esc(x.title||x.session_id||'—')}</td><td class="num">${num(x.calls)}</td><td class="num">${num(x.total_tokens)}</td><td class="num">${pct(x.cache_hit_rate)}</td><td class="num">${usd(x.cost_usd)}</td></tr>`);
    const paidRows = (s.plans||[]).map(x=>`<tr><td>${esc(x.label||x.profile_id)}</td><td>${modeBadge(x.mode)}</td><td class="num">${num(x.calls)}</td><td class="num">${num(x.total_tokens)}</td><td class="billing-sub">金额不适用</td><td class="num">${x.equiv_usd>0?usd(x.equiv_usd):'<span class="billing-muted">缺标价</span>'}</td></tr>`);
    const modelRows = (s.by_model||[]).map(x=>`<tr>
      <td>${esc(x.model)}</td>
      <td>${x.billing_mode && x.billing_mode!=='token' ? modeBadge(x.billing_mode) : (x.unpriced_calls ? '<span class="billing-badge billing-warn">缺单价</span>' : '<span class="billing-badge">按量</span>')}</td>
      <td class="num">${num(x.calls)}</td><td class="num">${num(x.total_tokens)}</td>
      <td class="num">${num(x.cached_tokens)}</td><td class="num">${pct(x.cache_hit_rate)}</td>
      <td class="num">${usd(x.cost_usd)}</td>
      <td class="num">${x.equiv_usd>0?usd(x.equiv_usd):'<span class="billing-muted">—</span>'}</td></tr>`);
    const dateRows = (s.by_date||[]).slice().reverse().map(x=>`<tr><td>${esc(x.date||'—')}</td><td class="num">${num(x.calls)}</td><td class="num">${num(x.total_tokens)}</td><td class="num">${usd(x.cost_usd)}</td></tr>`);

    const unpricedBlock = (s.unpriced||[]).length ? `<div class="card card-pad">
      <div class="card-head"><div><div class="card-kicker">UNPRICED</div><h3>缺单价：这些调用记 0</h3>
      <p class="row-meta">下表是按量计费但没匹配到单价的「档案 + 模型」。点「加入单价表」会按 <code>档案id/模型名</code> 生成空条目，填好单价保存后，<b>新产生的调用</b>即开始计价（历史账本金额不变）。</p></div></div>
      ${table(['档案','模型','调用','tokens','建议键','操作'], (s.unpriced||[]).map(x=>`<tr>
        <td>${esc(x.profile_name||x.profile_id||'—')}</td><td>${esc(x.model)}</td>
        <td class="num">${num(x.calls)}</td><td class="num">${num(x.total_tokens)}</td>
        <td><code>${esc(x.suggested_key)}</code></td>
        <td><button class="secondary-btn billing-addprice" type="button" data-key="${esc(x.suggested_key)}">加入单价表</button></td></tr>`))}
    </div>` : '';

    return cardHtml
      + (paidRows.length ? `<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">SUBSCRIPTION / FREE</div><h3>订阅与免费档案</h3><p class="row-meta">这些档案按订阅套餐使用，实付金额不适用；「等价标价」是按同一份单价表（官方标价）折算的参考值，用来判断套餐是否划算。在「单价表 → plans」里声明 <code>mode=subscription|free</code> 即可。</p></div></div>${table(['档案','计费方式','调用','tokens','金额','等价标价'], paidRows)}</div>` : '')
      + `<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">BY SESSION</div><h3>按会话</h3></div></div>${table(['会话','调用','tokens','缓存命中率','花费'], sessRows.length?sessRows:[emptyRow(5)])}</div>`
      + `<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">BY MODEL</div><h3>按模型</h3><p class="row-meta">缓存命中部分按 <code>cache_hit</code> 单价计，未命中输入按 <code>input</code> 计——长上下文 Agent 里这是最大成本变量。「等价标价」对订阅/免费档案同样按官方标价折算（含币种换算）。</p></div></div>${table(['模型','计费方式','调用','tokens','缓存命中','命中率','花费','等价标价'], modelRows.length?modelRows:[emptyRow(8)])}</div>`
      + unpricedBlock
      + `<div class="card card-pad"><div class="card-head"><div><div class="card-kicker">BY DATE</div><h3>按日期</h3></div></div>${table(['日期','调用','tokens','花费'], dateRows.length?dateRows:[emptyRow(4)])}</div>`;
  }

  function recordRows() {
    return st.rec.items.map(x=>`<tr>
      <td class="billing-sub">${esc(fmtTime(x.ts))}</td>
      <td>${esc(x.session_title||x.session_id||'—')}</td>
      <td>${esc(x.model||'—')}</td>
      <td>${x.billing_mode && x.billing_mode!=='token' ? modeBadge(x.billing_mode) : (x.priced?'<span class="billing-badge">按量</span>':'<span class="billing-badge billing-warn">缺单价</span>')}${x.usage_missing?' <span class="billing-badge billing-warn" title="该网关本次未返回 usage，token 记 0">无 usage</span>':''}</td>
      <td class="num">${num(x.prompt_tokens)}</td>
      <td class="num">${num(x.completion_tokens)}</td>
      <td class="num">${num((x.cached_tokens||0)+(x.cache_write_tokens||0))}</td>
      <td class="num">${x.billing_mode && x.billing_mode!=='token' ? '<span class="billing-sub">订阅内</span>' : usd(x.cost_usd)}</td>
      <td class="billing-sub">${esc(x.source||'')}</td></tr>`);
  }

  function renderRecords() {
    const more = st.rec.items.length < st.rec.total;
    return `<div class="card card-pad">
      <div class="card-head"><div><div class="card-kicker">CALLS</div><h3>调用明细</h3><p class="row-meta">共 ${num(st.rec.total)} 条，已显示 ${num(st.rec.items.length)} 条（最新在前）。</p></div>
      <button class="secondary-btn" id="billing-clear" type="button" title="清空账本（不可撤销）">清空账本</button></div>
      <div class="billing-actions" style="margin-top:0;margin-bottom:10px">
        <input class="search-input" id="billing-sid" placeholder="按会话 ID 过滤（留空 = 全部）" value="${esc(st.rec.sessionId)}" style="max-width:320px">
        <button class="secondary-btn" id="billing-filter" type="button">过滤</button>
      </div>
      ${table(['时间','会话','模型','计费','输入','输出','缓存','花费','来源'], st.rec.items.length?recordRows():[emptyRow(9)])}
      ${more?'<div class="billing-actions"><button class="secondary-btn" id="billing-more" type="button">加载更多</button></div>':''}
    </div>`;
  }

  function renderPrices() {
    const p = st.prices || {};
    return `<div class="card card-pad billing-prices">
      <div class="card-head"><div><div class="card-kicker">PRICE TABLE</div><h3>单价表</h3>
      <p class="row-meta">单位：表头 <code>currency</code> / 1M tokens；单条可写 <code>"currency":"CNY"</code> 直接粘贴官方人民币标价，按 <code>fx</code> 参考汇率折算（1 USD = N 该币种，预置 <code>{"CNY":7.1}</code>，请按当日汇率改）。<b>models</b> 的键支持三种写法，优先级从高到低：<code>档案id/模型名</code>（同一模型在不同 Provider 不同价）→ <code>档案id</code>（该档案兜底价）→ <code>模型名</code>（可用 <code>*</code> 通配，如 <code>glm-*</code>）。字段：<code>input</code> / <code>output</code> / <code>cache_hit</code> / <code>cache_write</code>（+可选 <code>currency</code> / <code>note</code>）。</p>
      <p class="row-meta"><b>plans</b> 按档案声明计费方式：<code>{"档案id":{"mode":"subscription","label":"…"}}</code>，mode 取 <code>token</code>(默认，按量) / <code>subscription</code>(订阅套餐) / <code>free</code>(免费)。订阅/免费档案不再报「缺单价」，但仍会用同一份单价表算出<b>等价标价</b>——按官方定价换算，用来判断套餐是否划算。</p></div></div>
      <p class="billing-sub">${esc(p.note||'')}</p>
      <textarea id="billing-prices-text" spellcheck="false"></textarea>
      <div class="billing-actions">
        <button class="primary-btn" id="billing-price-save" type="button">保存单价表</button>
        <button class="secondary-btn" id="billing-price-default" type="button">载入预置模板</button>
        <span class="billing-sub">保存后新产生的调用即按新单价计价；历史账本金额不受影响（订阅/免费切换会立即影响总览口径）。</span>
      </div>
    </div>`;
  }

  function paintBody() {
    const body = document.querySelector('#billing-body'); if(!body) return;
    if (st.tab==='overview') { body.innerHTML = renderOverview(); wireOverview(); }
    else if (st.tab==='records') { body.innerHTML = renderRecords(); wireRecords(); }
    else { body.innerHTML = renderPrices(); wirePrices(); }
  }

  /* v261008b · 缺单价闭环：一键把「档案id/模型名」键加进单价表（空值待填），省得用户猜键名 */
  function addPriceKey(key) {
    const models = (st.prices && st.prices.models) || {};
    if (models[key]) { toast(`${key} 已在单价表中`); }
    else {
      models[key] = { input: 0, output: 0, cache_hit: 0 };
      st.prices = { ...(st.prices||{}), models };
      toast(`已加入 ${key}（单价填好后点保存）`);
    }
    st.tab = 'prices';
    document.querySelectorAll('[data-btab]').forEach(b=>b.classList.toggle('active', b.dataset.btab==='prices'));
    paintBody();
    const ta = document.querySelector('#billing-prices-text');
    if (ta) { ta.focus(); const i = ta.value.indexOf(key); if (i >= 0) ta.setSelectionRange(i, i + key.length); }
  }

  function wireOverview() {
    document.querySelectorAll('.billing-addprice').forEach(b => { b.onclick = () => addPriceKey(b.dataset.key); });
  }

  function wireTabs() {
    document.querySelectorAll('[data-btab]').forEach(b => b.onclick = () => {
      st.tab = b.dataset.btab;
      document.querySelectorAll('[data-btab]').forEach(x=>x.classList.toggle('active', x===b));
      paintBody();
    });
  }

  function wireRecords() {
    const more = document.querySelector('#billing-more');
    if (more) more.onclick = async () => { try { await loadRecords(st.rec.offset, false); } catch(e){ toast(e.message,true); } };
    const filter = document.querySelector('#billing-filter');
    if (filter) filter.onclick = async () => { st.rec.sessionId = document.querySelector('#billing-sid').value.trim(); try { await loadRecords(0, true); } catch(e){ toast(e.message,true); } };
    const clear = document.querySelector('#billing-clear');
    if (clear) clear.onclick = async () => {
      if (!confirm('确定清空全部用量账本？此操作不可撤销。')) return;
      try { const r = await api('/api/billing/records', {method:'DELETE'}); toast(`已清空 ${r.removed||0} 条记录`); await loadSummary(); st.rec = {items:[], total:0, offset:0, sessionId:''}; paintBody(); }
      catch(e){ toast(e.message,true); }
    };
  }

  function wirePrices() {
    const ta = document.querySelector('#billing-prices-text');
    if (ta && st.prices) ta.value = JSON.stringify(st.prices, null, 2);
    const save = document.querySelector('#billing-price-save');
    if (save) save.onclick = async () => {
      let obj; try { obj = JSON.parse(ta.value); } catch(e){ return toast('JSON 解析失败：'+e.message, true); }
      try { st.prices = await api('/api/billing/prices', {method:'POST', body:obj}); toast('单价表已保存'); paintBody(); }
      catch(e){ toast(e.message, true); }
    };
    const def = document.querySelector('#billing-price-default');
    if (def) def.onclick = async () => {
      if (!confirm('载入预置模板将覆盖当前编辑框内容（需再点「保存」才生效）。继续？')) return;
      try { const d = await api('/api/billing/prices?defaults=1'); ta.value = JSON.stringify(d, null, 2); toast('已载入预置模板，点击保存后生效'); }
      catch(e){ toast(e.message, true); }
    };
  }

  async function loadSummary() { st.summary = await api('/api/billing/summary'); }
  async function loadRecords(offset=0, replace=true) {
    const qs = new URLSearchParams({limit:'100', offset:String(offset)});
    if (st.rec.sessionId) qs.set('session_id', st.rec.sessionId);
    const r = await api('/api/billing/records?'+qs.toString());
    st.rec.total = r.total; st.rec.offset = offset + r.items.length;
    st.rec.items = replace ? r.items : st.rec.items.concat(r.items);
    if (st.tab==='records') paintBody();
  }

  async function render(main) {
    main.innerHTML = shellHtml();
    wireTabs();
    document.querySelector('#billing-refresh').onclick = () => boot(true);
    await boot(false);
  }

  async function boot(notify) {
    try {
      await Promise.all([loadSummary(), api('/api/billing/prices').then(p => st.prices = p), loadRecords(0, true)]);
      paintBody();
      if (notify) toast('用量数据已刷新');
    } catch(e) {
      const body = document.querySelector('#billing-body');
      if (body) body.innerHTML = `<div class="card card-pad danger">加载失败：${esc(e.message)}</div>`;
    }
  }

  window.ERWBilling = { render };
})();
