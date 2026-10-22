(() => {
  'use strict';
  const $=(s,r=document)=>r.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const prefs=['theme','pageDensity','uiScale','focusMinutes','breakMinutes','sidebarPinned','sidebarOpen','heatmapMonths','heatmapThresholds','heatmapColors'];
  const scopeLabels={documents:'Markdown 文档',attachments:'PDF、图片与附件',records:'项目、待办、文献、批注与科研热力图',settings:'通用设置与界面偏好',history:'Agent 对话记录'};
  const phases={idle:'待同步',syncing:'正在同步',synced:'已同步',pending:'有待同步变化',conflict:'有冲突待处理',error:'同步未完成'};
  const icon='<svg class="sync-symbol" viewBox="0 0 20 20" aria-hidden="true"><path d="M16.5 6.5A7 7 0 0 0 4.6 5.3L2.5 7.5m0-4v4h4M3.5 13.5a7 7 0 0 0 11.9 1.2l2.1-2.2m0 4v-4h-4"/></svg>';
  const chevron='<svg class="sync-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4.5 6.25 3.5 3.5 3.5-3.5"/></svg>';
  let state=null,wrap=null,polling=false,applied=null,prefSnapshot=null,pendingRefresh=false,guardSignature='',guardStamp=0;
  const client=crypto.randomUUID?.()||String(Math.random());
  const ui=()=>window.ERWSyncUI;
  async function api(path,body){
    const f=window.erwFetch||fetch;
    const response=await f('/api/sync/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const value=await response.json();if(!response.ok)throw new Error(value.message||'同步服务连接失败');return value;
  }
  const time=value=>value?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'尚未同步';
  function ensureControl(){
    if(wrap?.isConnected)return;
    wrap=document.createElement('div');wrap.className='sync-wrap';wrap.hidden=true;
    wrap.innerHTML=`<button class="sync-trigger" id="sync-now" type="button" aria-label="立即同步">${icon}<span id="sync-count" aria-hidden="true"></span></button><button class="sync-more" id="sync-more" type="button" title="同步状态与变化" aria-label="同步状态与变化" aria-controls="sync-menu" aria-expanded="false">${chevron}</button><section class="sync-menu" id="sync-menu" hidden aria-label="同步状态"><div id="sync-menu-content"></div></section>`;
    const slot=$('#desktop-sync-slot'),reload=$('.reload-wrap');
    if(document.documentElement.dataset.desktop==='true'&&slot)slot.append(wrap);else reload?.before(wrap);
    $('#sync-now').onclick=()=>run();
    $('#sync-more').onclick=()=>{const open=$('#sync-menu').hidden;$('#sync-menu').hidden=!open;$('#sync-more').setAttribute('aria-expanded',String(open));if(open)drawMenu()};
    document.addEventListener('click',event=>{if(!wrap.contains(event.target))closeMenu()});
    document.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenu()});
  }
  function closeMenu(){if(wrap){$('#sync-menu').hidden=true;$('#sync-more').setAttribute('aria-expanded','false')}}
  function drawMenu(){
    if(!state)return;
    $('#sync-menu-content').innerHTML=`<div class="sync-menu-heading"><strong>${esc(phases[state.phase]||'待同步')}</strong><span>${state.config.mode==='auto'?'自动同步':'主动同步'}</span></div><p class="sync-caption">↑ ${state.upload||0} 待上传　↓ ${state.download||0} 待下载　! ${state.conflicts||0} 冲突</p>${!state.remote_known?'<p class="sync-caption">服务器变化尚未检查</p>':''}<p class="sync-caption">上次成功：${esc(time(state.last_success))}</p>${state.error?`<p class="sync-error">${esc(state.error)}</p>`:''}<div class="sync-change-list">${changesHtml(state.changes?.slice(0,80)||[])}</div><div class="sync-menu-actions"><button class="secondary-btn" data-sync-check>检查服务器变化</button><button class="primary-btn" data-sync-run>立即同步</button><button class="secondary-btn" data-sync-settings>同步设置</button></div>`;
    wireActions($('#sync-menu-content'));
  }
  function changesHtml(rows){return rows.length?rows.map(c=>`<div class="sync-change"><span class="sync-badge" data-code="${esc(c.code)}">${esc(c.code)}</span><span class="sync-change-label" title="${esc(c.label)}">${esc(c.label)}${c.guarded?' · 等待编辑器保存':''}</span>${c.code==='!'?`<button class="secondary-btn" data-sync-conflict="${esc(c.key)}">处理</button>`:''}</div>`).join(''):'<p class="sync-caption">暂无待处理变化</p>'}
  function wireActions(root){
    root.querySelectorAll('[data-sync-run]').forEach(b=>b.onclick=()=>run());
    root.querySelectorAll('[data-sync-check]').forEach(b=>b.onclick=()=>run(true));
    root.querySelectorAll('[data-sync-settings]').forEach(b=>b.onclick=()=>{closeMenu();ui()?.openSettings()});
    root.querySelectorAll('[data-sync-conflict]').forEach(b=>b.onclick=()=>openConflict(b.dataset.syncConflict));
  }
  function draw(){
    ensureControl();wrap.hidden=state.config.mode==='off';wrap.dataset.phase=state.phase;
    $('#sync-now').disabled=state.phase==='syncing';
    $('#sync-count').textContent=state.conflicts?String(state.conflicts):state.upload||state.download?`↑${state.upload||0} ↓${state.download||0}`:'';
    $('#sync-count').dataset.kind=state.conflicts?'conflict':'pending';
    $('#sync-now').setAttribute('aria-label',`${phases[state.phase]||'待同步'}${state.conflicts?'，'+state.conflicts+' 项冲突':''}，点击立即同步`);
    $('#sync-now').title=`${phases[state.phase]||'待同步'} · 点击立即同步`;
    if(!$('#sync-menu').hidden)drawMenu();
    decorate();
    const status=$('#sync-settings-status');if(status){status.textContent=`${phases[state.phase]||'待同步'} · ↑ ${state.upload||0}　↓ ${state.download||0}　! ${state.conflicts||0} · 上次成功：${time(state.last_success)}`;status.dataset.phase=state.phase}
    const error=$('#sync-settings-error');if(error)error.textContent=state.error||'';
    const list=$('#sync-settings-changes');if(list){list.innerHTML=changesHtml(state.changes||[]);wireActions(list)}
  }
  function decorate(){
    const badges=new Map((state?.changes||[]).filter(c=>c.doc_id).map(c=>[c.doc_id,c]));
    document.querySelectorAll('.doc-item[data-doc-id]').forEach(el=>{
      const change=state?.config.mode!=='off'&&badges.get(el.dataset.docId),old=$('.sync-doc-badge',el);
      if(!change){old?.remove();return}if(old?.textContent===change.code)return;
      const badge=old||document.createElement('span');badge.className='sync-badge sync-doc-badge';badge.dataset.code=change.code;badge.textContent=change.code;badge.title=({A:'新增，等待上传',M:'修改，等待上传',D:'删除，等待上传','↓':'服务器有更新','!':'两端修改冲突'})[change.code];
      if(!old)($('.doc-mini-flags',el)||el).append(badge);
    });
  }
  async function guard(force=false){
    if(!state)return;
    const value={client,doc_id:window.ERWCurrentDoc||'',dirty:!!window.ERWDesktop?.hasUnsavedChanges?.()},signature=JSON.stringify(value),now=Date.now();
    if(force||signature!==guardSignature||now-guardStamp>18000){await api('guard',value);guardSignature=signature;guardStamp=now}
  }
  async function syncPreferences(){
    if(!state)return;
    const current=Object.fromEntries(prefs.map(k=>[k,localStorage.getItem(k)]).filter(([,v])=>v!==null));
    if(!prefSnapshot){
      const remote=state.preferences||{},existing=Object.fromEntries(Object.entries(remote).filter(([k])=>prefs.includes(k)));
      if(Object.keys(existing).length)ui()?.applyPreferences(existing);
      const missing=Object.fromEntries(Object.entries(current).filter(([k])=>!(k in remote)));
      if(Object.keys(missing).length)await api('preferences',missing);
      prefSnapshot={...current,...existing};return;
    }
    const modified=Object.fromEntries(Object.entries(current).filter(([k,v])=>prefSnapshot[k]!==v));
    if(Object.keys(modified).length){await api('preferences',modified);Object.assign(prefSnapshot,modified)}
    const incoming=Object.fromEntries(Object.entries(state.preferences||{}).filter(([k,v])=>prefs.includes(k)&&!(k in modified)&&prefSnapshot[k]!==v));
    if(Object.keys(incoming).length){ui()?.applyPreferences(incoming);Object.assign(prefSnapshot,incoming)}
  }
  async function poll(){
    if(polling)return;polling=true;
    try{
      const value=await api('status');if(!value.config)return;
      state=value;draw();await guard();await syncPreferences();
      if(applied!==null&&applied!==state.applied)pendingRefresh=true;applied=state.applied;
      if(pendingRefresh&&!window.ERWDesktop?.hasUnsavedChanges?.()&&!window.ERWDesktop?.documentDraft?.()){
        pendingRefresh=!(await ui()?.refresh());
      }
    }catch(error){if(state&&state.config.mode!=='off'){state.phase='error';state.error=error.message;draw()}}
    finally{polling=false}
  }
  async function run(check=false){
    closeMenu();try{await guard(true);state=await api(check?'check':'run',{});draw();setTimeout(poll,500)}catch(error){ui()?.toast(error.message,true)}
  }
  async function renderSettings(panel){
    panel.innerHTML='<p class="sync-caption">正在读取同步设置…</p>';
    try{
      const value=await api('status');if(!panel.isConnected)return;state=value;const c=state.config;
      panel.innerHTML=`<div class="card-head"><div><h3>同步</h3><p class="sync-caption">将已保存的材料与通用设置，在本机和服务器之间双向同步。</p></div></div><div class="sync-form"><label for="sync-url">服务器地址</label><div class="sync-address"><input id="sync-url" placeholder="http://192.168.1.10:8765 或 https://work.example.com" value="${esc(c.url)}" spellcheck="false"><button class="secondary-btn" id="sync-test">测试连接</button></div><p class="sync-caption" id="sync-test-result" role="status">填写服务器的工作台访问地址，也支持 frp 域名与端口。</p><label for="sync-mode">同步方式</label><select id="sync-mode"><option value="off" ${c.mode==='off'?'selected':''}>不同步</option><option value="manual" ${c.mode==='manual'?'selected':''}>主动同步 · 点击标题栏按钮时同步</option><option value="auto" ${c.mode==='auto'?'selected':''}>自动同步 · 保存后与后台定时同步</option></select><label for="sync-interval">自动检查间隔（秒）</label><input id="sync-interval" type="number" min="10" max="3600" value="${c.interval}"><fieldset class="sync-scopes"><legend>同步内容</legend>${Object.entries(scopeLabels).map(([key,label])=>`<label><input type="checkbox" data-sync-scope="${key}" ${c.scopes.includes(key)?'checked':''}>${label}</label>`).join('')}</fieldset><p class="sync-caption">服务器地址、同步方式、窗口设置、API 密钥和本机文件路径仅保存在本机。未保存的编辑和新建模板不会上传。附件需位于 Workspace 内；每个附件最大 512 MB。</p><div class="sync-menu-actions"><button class="primary-btn" id="sync-save">保存同步设置</button><button class="secondary-btn" data-sync-run ${c.mode==='off'?'disabled':''}>立即同步</button></div></div><section class="sync-settings-summary"><h3>同步状态与变化</h3><p id="sync-settings-status" role="status"></p><p class="sync-error" id="sync-settings-error"></p><div id="sync-settings-changes"></div><p class="sync-caption">A 新增　M 修改　D 删除　↓ 服务器更新　! 需要处理冲突。冲突解决前保留两端内容；同步删除的文件进入本机回收目录。</p></section>`;
      $('#sync-test').onclick=async()=>{const button=$('#sync-test'),result=$('#sync-test-result');button.disabled=true;result.textContent='正在连接…';try{const r=await api('test',{url:$('#sync-url').value});result.textContent=`连接成功 · ${r.count} 项已保存内容`;result.classList.remove('sync-error')}catch(error){result.textContent=error.message;result.classList.add('sync-error')}finally{button.disabled=false}};
      $('#sync-save').onclick=async()=>{
        const payload={url:$('#sync-url').value,mode:$('#sync-mode').value,interval:+$('#sync-interval').value,scopes:[...panel.querySelectorAll('[data-sync-scope]:checked')].map(el=>el.dataset.syncScope)};
        const controls=[...panel.querySelectorAll('.sync-form input,.sync-form select,#sync-save,#sync-test')];controls.forEach(el=>el.disabled=true);
        try{state=await api('config',payload);prefSnapshot=null;ui()?.toast('同步设置已保存');await renderSettings(panel);draw();await syncPreferences()}
        catch(error){ui()?.toast(error.message,true)}finally{controls.forEach(el=>el.disabled=false)}
      };
      wireActions(panel);draw();
    }catch(error){panel.textContent=error.message}
  }
  async function openConflict(key){
    closeMenu();try{
      const d=await api('conflict?key='+encodeURIComponent(key));
      ui().modal('处理同步冲突',`<div class="sync-conflict"><p class="sync-caption">${esc(d.label)}</p><p>两端都有变化，请比较后选择保留的版本。</p><div class="sync-versions"><label>本地版本<textarea readonly aria-label="本地版本">${esc(d.local.text)}</textarea></label><label>服务器版本<textarea readonly aria-label="服务器版本">${esc(d.remote.text)}</textarea></label></div><details><summary>查看上次共同版本</summary><pre>${esc(d.base.text)}</pre></details>${d.local.editable?`<details id="sync-merge-details"><summary>手动编辑合并内容</summary><textarea id="sync-merge-text" aria-label="合并内容">${esc(d.local.text)}</textarea><p class="sync-caption">保留顶部 id 字段，编辑完成后点击“保存合并”。</p></details>`:''}<p class="sync-error" id="sync-resolve-error" role="status"></p></div>`,`<button class="secondary-btn" id="sync-resolve-cancel">稍后处理</button>${d.can_keep_both?'<button class="secondary-btn" data-sync-choice="both">保留两份</button>':''}<button class="secondary-btn" data-sync-choice="remote">使用服务器版本</button><button class="primary-btn" data-sync-choice="local">使用本地版本</button>${d.local.editable?'<button class="primary-btn" data-sync-choice="merge">保存合并</button>':''}`);
      $('#modal').classList.add('sync-conflict-modal');
      $('#sync-resolve-cancel').onclick=()=>{ui().closeModal();$('#modal').classList.remove('sync-conflict-modal')};
      document.querySelectorAll('[data-sync-choice]').forEach(button=>button.onclick=async()=>{
        const choice=button.dataset.syncChoice;
        if(choice==='merge'&&!$('#sync-merge-details').open){$('#sync-merge-details').open=true;$('#sync-merge-text').focus();return}
        if(!await window.ERWDialog.confirm(choice==='both'?'保存本地副本，并将原条目更新为服务器版本？':choice==='merge'?'保存合并结果并同步到服务器？':`确认使用${choice==='local'?'本地':'服务器'}版本？被替换的文件版本会保留在同步记录中。`,{title:'确认冲突处理'}))return;
        document.querySelectorAll('[data-sync-choice]').forEach(b=>b.disabled=true);
        try{state=await api('resolve',{key,choice,local_hash:d.local_hash,remote_version:d.remote_version,text:$('#sync-merge-text')?.value});ui().closeModal();$('#modal').classList.remove('sync-conflict-modal');ui().toast('冲突已处理');pendingRefresh=true;draw();await poll()}catch(error){$('#sync-resolve-error').textContent=error.message}finally{document.querySelectorAll('[data-sync-choice]').forEach(b=>b.disabled=false)}
      });
    }catch(error){ui()?.toast(error.message,true)}
  }
  window.ERWSync={renderSettings,poll};
  window.addEventListener('workbench:ready',()=>{
    ensureControl();poll();setInterval(poll,3000);
    let timer;
    /* 文档级 DOM 变更走内核唯一观察者（ERWDom.onChildList），不再自建 MutationObserver */
    const onMainChange=()=>{clearTimeout(timer);timer=setTimeout(()=>{decorate();guard().catch(()=>{})},150)};
    if(window.ERWDom?.onChildList)window.ERWDom.onChildList(onMainChange,{root:$('#main')});
    else onMainChange();
    document.addEventListener('input',()=>{guard().catch(()=>{})},true);
    window.addEventListener('workbench:editor-state',()=>guard().catch(()=>{}));
    document.addEventListener('click',()=>setTimeout(()=>guard().catch(()=>{}),0),true);
    document.addEventListener('visibilitychange',()=>guard(true).catch(()=>{}));
    window.addEventListener('pagehide',()=>navigator.sendBeacon?.('/api/sync/guard',new Blob([JSON.stringify({client,doc_id:'',dirty:false})],{type:'application/json'})));
  },{once:true});
})();
