(() => {
  'use strict';

  const nativeFetch = window.fetch.bind(window);
  const perf = window.__workbenchPerf = {
    docs: null,
    docPage: 1,
    docKey: '',
    graphMeta: null,
    graphLimit: 300,
    searchController: null,
  };

  const jsonResponse = (data, source) => new Response(JSON.stringify(data), {
    status: source.status,
    statusText: source.statusText,
    headers: {'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store'},
  });

  const route = () => (location.hash || '#overview').slice(1).split('?')[0];
  const docKey = (u) => ['kind','q','status','project','mark'].map(k => `${k}=${u.searchParams.get(k) || ''}`).join('&');
  const isDocsCollection = (u, init) => (!init?.method || String(init.method).toUpperCase() === 'GET') && u.pathname === '/api/docs';

  window.fetch = async function workbenchPerformanceFetch(input, init = {}) {
    let requestUrl = typeof input === 'string' ? input : input?.url;
    if (!requestUrl) return nativeFetch(input, init);
    const u = new URL(requestUrl, location.origin);
    let nextInit = init;

    if (isDocsCollection(u, init)) {
      const key = docKey(u);
      if (key !== perf.docKey) {
        perf.docKey = key;
        perf.docPage = 1;
      }
      const kind = u.searchParams.get('kind') || '';
      const pageSize = kind === 'milestone' ? 200 : 50;
      u.searchParams.set('paged', '1');
      u.searchParams.set('page', String(perf.docPage));
      u.searchParams.set('page_size', String(pageSize));
    }

    if ((!init?.method || String(init.method).toUpperCase() === 'GET') && u.pathname === '/api/graph') {
      if (route() === 'research-overview') {
        u.pathname = '/api/graph/overview';
        u.searchParams.set('limit', '80');
      } else {
        u.searchParams.set('limit', String(perf.graphLimit));
      }
    }

    if ((!init?.method || String(init.method).toUpperCase() === 'GET') && u.pathname === '/api/search') {
      try { perf.searchController?.abort(); } catch (_) {}
      const controller = new AbortController();
      perf.searchController = controller;
      if (init.signal) {
        if (init.signal.aborted) controller.abort();
        else init.signal.addEventListener('abort', () => controller.abort(), {once: true});
      }
      nextInit = {...init, signal: controller.signal};
    }

    const target = u.origin === location.origin ? u.pathname + u.search : u.href;
    let res;
    try {
      res = await nativeFetch(target, nextInit);
    } catch (err) {
      if (err?.name === 'AbortError' && u.pathname === '/api/search') {
        return new Response('[]', {status: 200, headers: {'Content-Type': 'application/json; charset=utf-8'}});
      }
      throw err;
    }

    if (isDocsCollection(u, init) && res.ok) {
      try {
        const data = await res.clone().json();
        if (data && !Array.isArray(data) && Array.isArray(data.items)) {
          perf.docs = data;
          perf.docPage = Number(data.page || 1);
          window.dispatchEvent(new CustomEvent('workbench:docs-page', {detail: data}));
          return jsonResponse(data.items, res);
        }
      } catch (_) {}
    }

    if ((u.pathname === '/api/graph' || u.pathname === '/api/graph/overview') && res.ok) {
      try {
        const data = await res.clone().json();
        if (data?.meta) {
          perf.graphMeta = data.meta;
          window.dispatchEvent(new CustomEvent('workbench:graph-meta', {detail: data.meta}));
        }
      } catch (_) {}
    }
    return res;
  };

  function refreshCurrentDocs() {
    const search = document.querySelector('#doc-search');
    if (search) {
      search.dispatchEvent(new Event('input', {bubbles: true}));
      return;
    }
    const current = document.querySelector(`[data-route="${route()}"]`);
    current?.click();
  }

  function ensureDocPager() {
    const meta = perf.docs;
    if (!meta || meta.total <= meta.page_size) {
      document.querySelector('.perf-doc-pager')?.remove();
      return;
    }
    const list = document.querySelector('#doc-list');
    const milestoneView = document.querySelector('#ms-view');
    const anchor = list || milestoneView;
    if (!anchor) return;
    let pager = document.querySelector('.perf-doc-pager');
    if (!pager) {
      pager = document.createElement('div');
      pager.className = 'perf-doc-pager';
      anchor.insertAdjacentElement('afterend', pager);
    }
    const signature = `${meta.page}:${meta.pages}:${meta.total}:${meta.prev_page || ''}:${meta.next_page || ''}`;
    if (pager.dataset.signature === signature) return;
    pager.dataset.signature = signature;
    pager.innerHTML = `
      <button type="button" class="secondary-btn" data-perf-page="prev" ${meta.prev_page ? '' : 'disabled'}>上一页</button>
      <span><b>${meta.page}</b>/${meta.pages} 页 · 共 ${meta.total} 条</span>
      <button type="button" class="secondary-btn" data-perf-page="next" ${meta.next_page ? '' : 'disabled'}>下一页</button>`;
    pager.querySelector('[data-perf-page="prev"]')?.addEventListener('click', () => {
      if (!meta.prev_page) return;
      perf.docPage = meta.prev_page;
      refreshCurrentDocs();
    });
    pager.querySelector('[data-perf-page="next"]')?.addEventListener('click', () => {
      if (!meta.next_page) return;
      perf.docPage = meta.next_page;
      refreshCurrentDocs();
    });
  }

  function ensureGraphStatus() {
    if (route() !== 'graph') {
      document.querySelector('.perf-graph-status')?.remove();
      return;
    }
    const meta = perf.graphMeta;
    const head = document.querySelector('#graph-wrap')?.previousElementSibling;
    if (!meta || !head) return;
    let box = document.querySelector('.perf-graph-status');
    if (!box) {
      box = document.createElement('div');
      box.className = 'perf-graph-status';
      head.appendChild(box);
    }
    const signature = `${meta.shown_documents}:${meta.total_documents}:${meta.truncated}:${perf.graphLimit}`;
    if (box.dataset.signature === signature) return;
    box.dataset.signature = signature;
    box.innerHTML = `<span>当前加载 <b>${meta.shown_documents}</b> / ${meta.total_documents} 个知识节点</span>`;
    if (meta.truncated && perf.graphLimit < 500) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'secondary-btn';
      btn.textContent = '继续加载（最多 500）';
      btn.addEventListener('click', () => {
        perf.graphLimit = Math.min(500, perf.graphLimit + 100);
        document.querySelector('[data-route="graph"]')?.click();
      });
      box.appendChild(btn);
    } else if (meta.truncated) {
      const note = document.createElement('small');
      note.textContent = '已达到浏览器保护上限，请使用筛选或局部关系查看。';
      box.appendChild(note);
    }
  }

  const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function childHtml(node) {
    const isDir = node.type === 'dir';
    return `<div class="tree-node" data-perf-tree-node="1">
      <div class="tree-line">
        <span class="perf-tree-toggle" ${isDir ? `data-perf-expand="${esc(node.path)}"` : ''}>${isDir ? '▸' : '·'}</span>
        <span class="folder-name" title="${esc(node.path)}">${esc(node.name)}</span>
        ${isDir ? `<span class="folder-actions"><button data-open-path="${esc(node.path)}">↗</button></span>` : ''}
      </div>
    </div>`;
  }

  async function expandTreeNode(node, rel) {
    if (!node || node.dataset.perfLoading === '1') return;
    const existing = node.querySelector(':scope > .tree-children');
    if (existing) {
      const hidden = existing.hidden;
      existing.hidden = !hidden;
      const toggle = node.querySelector(':scope > .tree-line .perf-tree-toggle');
      if (toggle) toggle.textContent = hidden ? '▾' : '▸';
      return;
    }
    node.dataset.perfLoading = '1';
    const toggle = node.querySelector(':scope > .tree-line .perf-tree-toggle');
    if (toggle) toggle.textContent = '…';
    try {
      const res = await nativeFetch('/api/workspace/children?path=' + encodeURIComponent(rel));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const children = document.createElement('div');
      children.className = 'tree-children';
      children.innerHTML = (data.children || []).map(childHtml).join('') || '<div class="row-meta perf-tree-empty">空目录</div>';
      node.appendChild(children);
      if (toggle) toggle.textContent = '▾';
      wireLazyTree(children);
    } catch (err) {
      if (toggle) toggle.textContent = '!';
    } finally {
      delete node.dataset.perfLoading;
    }
  }

  function wireLazyTree(root = document) {
    root.querySelectorAll('.tree-node').forEach(node => {
      if (node.dataset.perfLazyWired === '1') return;
      const openBtn = node.querySelector(':scope > .tree-line [data-open-path]');
      if (!openBtn) return;
      node.dataset.perfLazyWired = '1';
      const rel = openBtn.dataset.openPath || '';
      const line = node.querySelector(':scope > .tree-line');
      let toggle = line?.querySelector('.perf-tree-toggle');
      if (!toggle && line) {
        toggle = document.createElement('span');
        toggle.className = 'perf-tree-toggle';
        toggle.textContent = '▸';
        line.insertBefore(toggle, line.firstChild);
      }
      const name = node.querySelector(':scope > .tree-line .folder-name');
      const expand = (e) => { e?.stopPropagation(); expandTreeNode(node, rel); };
      toggle?.addEventListener('click', expand);
      name?.addEventListener('click', expand);
    });
  }

  function decorateIndexStatus() {
    if (route() !== 'folders') return;
    const panel = document.querySelector('.workspace-layout > section.card.card-pad');
    if (!panel || panel.querySelector('.perf-index-status')) return;
    nativeFetch('/api/system/index').then(r => r.ok ? r.json() : null).then(data => {
      if (!data || !panel.isConnected) return;
      const box = document.createElement('div');
      box.className = 'perf-index-status';
      box.innerHTML = `<div class="section-title"><div><h3>性能索引</h3><p>SQLite 仅作为可重建缓存，Markdown 仍是真实数据源。</p></div></div>
        <div class="row-meta">${data.counts?.documents || 0} 文档 · ${data.counts?.edges || 0} 关系 · ${(data.db_size/1024/1024).toFixed(2)} MB · ${esc(data.fts_tokenizer || 'FTS5')}</div>
        <div style="margin-top:10px"><button class="secondary-btn" id="perf-rebuild-index" type="button">重建索引</button></div>`;
      panel.appendChild(box);
      box.querySelector('#perf-rebuild-index')?.addEventListener('click', async () => {
        const btn = box.querySelector('#perf-rebuild-index');
        btn.disabled = true; btn.textContent = '重建中…';
        try {
          const r = await nativeFetch('/api/system/index/rebuild', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          location.reload();
        } catch (_) {
          btn.disabled = false; btn.textContent = '重建索引';
        }
      });
    }).catch(() => {});
  }

  function decorate() {
    ensureDocPager();
    ensureGraphStatus();
    wireLazyTree();
    decorateIndexStatus();
  }

  window.addEventListener('workbench:docs-page', () => setTimeout(decorate, 0));
  window.addEventListener('workbench:graph-meta', () => setTimeout(decorate, 0));
  window.addEventListener('hashchange', () => {
    if (!['ideas','journals','notes','milestones','summaries','literature'].includes(route())) {
      perf.docs = null;
      perf.docKey = '';
      perf.docPage = 1;
    }
    setTimeout(decorate, 0);
  });

  const observer = new MutationObserver(() => requestAnimationFrame(decorate));
  window.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, {childList: true, subtree: true});
    decorate();
  });
})();
