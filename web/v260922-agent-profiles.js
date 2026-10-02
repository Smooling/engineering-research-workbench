(() => {
  'use strict';
  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
  const esc=(v='')=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const route=()=> (location.hash||'#overview').slice(1).split('?')[0];
  async function api(url,opts={}){const init={...opts,headers:{'Content-Type':'application/json',...(opts.headers||{})}};if(init.body&&typeof init.body!=='string')init.body=JSON.stringify(init.body);const r=await fetch(url,init);let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.message||d.error||`HTTP ${r.status}`);return d}
  function toast(msg,bad=false){const root=$('#toast-stack');if(!root)return;const el=document.createElement('div');el.className='toast'+(bad?' error':'');el.textContent=msg;root.appendChild(el);setTimeout(()=>el.remove(),3200)}

  function installSidebarToggle(){
    const top=$('.topbar');if(!top||$('#sidebar-toggle'))return;
    const btn=document.createElement('button');btn.id='sidebar-toggle';btn.className='sidebar-toggle-btn';btn.type='button';btn.title='收起 / 展开侧边栏';btn.setAttribute('aria-label','收起 / 展开侧边栏');btn.textContent='☰';
    top.insertBefore(btn,top.firstChild);
    const saved=localStorage.getItem('sidebarCollapsed')==='1';document.body.classList.toggle('sidebar-collapsed',saved);
    const sync=()=>{const c=document.body.classList.contains('sidebar-collapsed');btn.textContent=c?'☰':'⇤';btn.title=c?'展开侧边栏':'收起侧边栏';btn.setAttribute('aria-expanded',String(!c))};
    btn.onclick=()=>{document.body.classList.toggle('sidebar-collapsed');localStorage.setItem('sidebarCollapsed',document.body.classList.contains('sidebar-collapsed')?'1':'0');sync()};sync();
  }

  let managerState=null;
  async function renderProfileManager(){
    const panel=$('#settings-panel');if(!panel||route()!=='settings')return;
    const cfg=await api('/api/config');const app=cfg.app||{},llm=app.llm||{};const profiles=JSON.parse(JSON.stringify(llm.profiles||[]));
    if(!profiles.length)return;
    managerState={cfg,app,llm,profiles,activeId:llm.active_profile_id||profiles[0].id,selectedId:llm.active_profile_id||profiles[0].id,openModes:{}}; /* v260929d · openModes：每个配置下展开编辑的请求模式 id 集合（默认全部收起省空间） */
    paintManagerShell(panel);paintProfileEditor();
  }
  function paintManagerShell(panel){
    const s=managerState;
    panel.innerHTML=`<div class="card-head"><div><div class="card-kicker">OPENAI COMPATIBLE PROFILES</div><h3>Agent API 配置</h3><p class="row-meta">多套配置保存在本地 config/secret.json；系统提示词统一保存在 app.json。只使用 OpenAI-compatible Chat Completions。</p></div></div>
    <div class="agent-profile-settings"><aside class="agent-profile-list"><div class="agent-profile-list-head"><h4>配置列表</h4><button class="primary-btn" id="profile-add">＋</button></div><div class="agent-profile-items" id="profile-items"></div></aside><section class="agent-profile-editor" id="profile-editor"></section></div>
    <div class="field" style="margin-top:14px"><label>统一系统提示词</label><textarea id="global-system-prompt" style="min-height:120px">${esc(s.llm.system_prompt||'')}</textarea></div>
    <div class="agent-settings-footer"><div class="left"><label class="badge"><input type="checkbox" id="agent-enabled" ${s.llm.enabled?'checked':''}> 启用 Agent</label><label class="badge"><input type="checkbox" id="llm-vision-global" ${s.llm.vision_enabled?'checked':''}> 多模态 / 截图识别</label><span class="row-meta">开启后阅读区 AI 面板可用「截取当前页 / 框选区域」代替选中文本；需模型支持图片输入（如 qwen-vl / gpt-4o 系列）。</span></div><button class="primary-btn" id="profile-save-all">保存全部配置</button></div>`;
    $('#profile-add').onclick=()=>{const id='profile-'+Date.now();s.profiles.push({id,name:'未命名配置',base_url:'https://api.openai.com/v1',has_api_key:false,timeout:120,max_output_tokens:0,temperature:null,show_reasoning:true,default_request_preset:'default',request_presets:[{id:'default',label:'默认',model:'',temperature:null,params:{}}]});s.selectedId=id;paintProfileList();paintProfileEditor()};
    $('#profile-save-all').onclick=saveAllProfiles;paintProfileList();
  }
  function paintProfileList(){
    const s=managerState,root=$('#profile-items');if(!root)return;root.innerHTML=s.profiles.map(p=>`<button class="agent-profile-item ${p.id===s.selectedId?'active':''}" data-profile-id="${esc(p.id)}"><span class="profile-state"><span class="profile-dot ${p.id===s.activeId?'on':''}"></span><strong>${esc(p.name||'未命名配置')}</strong></span><small>${esc(p.base_url||'')} · ${(p.request_presets||[]).length} 模式</small></button>`).join('');$$('[data-profile-id]',root).forEach(b=>b.onclick=()=>{captureEditor();s.selectedId=b.dataset.profileId;paintProfileList();paintProfileEditor()})
  }
  function selectedProfile(){return managerState?.profiles.find(p=>p.id===managerState.selectedId)}
  function paintProfileEditor(){
    const p=selectedProfile(),root=$('#profile-editor');if(!p||!root)return;const modes=p.request_presets||[];
    root.innerHTML=`<div class="agent-profile-editor-head"><div><div class="card-kicker">PROFILE</div><h3>${esc(p.name||'未命名配置')}</h3></div><div class="agent-profile-editor-actions"><button class="secondary-btn" id="profile-activate">${p.id===managerState.activeId?'当前已激活':'设为当前配置'}</button><button class="secondary-btn" id="profile-test">测试连接</button><button class="ghost-btn danger" id="profile-delete" ${managerState.profiles.length<=1?'disabled':''}>删除</button></div></div>
    <div class="agent-profile-grid">
      <div class="field span-2"><label>配置名称</label><input id="pf-name" value="${esc(p.name||'')}"></div>
      <div class="field span-2"><label>Base URL</label><input id="pf-base" value="${esc(p.base_url||'')}"></div>
      <div class="field span-2"><label>API Key</label><input id="pf-key" type="password" placeholder="${p.has_api_key?'已保存；留空则保持原 Key':'输入 API Key'}"></div>
      <div class="field"><label>超时 / 秒</label><input id="pf-timeout" type="number" min="5" max="600" value="${Number(p.timeout||120)}"></div>
      <div class="field"><label>最大输出 tokens</label><input id="pf-max" type="number" min="0" value="${Number(p.max_output_tokens||0)}"></div>
      <div class="field"><label>默认 Temperature</label><input id="pf-temp" type="number" min="0" max="2" step="0.1" value="${p.temperature==null?'':p.temperature}" placeholder="留空 = 不发送"></div>
      <div class="field"><label>思考过程</label><select id="pf-reason"><option value="1" ${p.show_reasoning!==false?'selected':''}>显示</option><option value="0" ${p.show_reasoning===false?'selected':''}>隐藏</option></select></div>
    </div><div class="agent-secret-note">Key 仅保存在本机 config/secret.json。仓库 .gitignore 已忽略整个 config/ 目录。</div>
    <div class="agent-mode-section"><div class="agent-mode-head"><div><h4>请求模式</h4><span class="row-meta">每个模式保存 id、label、模型名、可选 temperature 和 params。</span></div><button class="secondary-btn" id="mode-add">＋ 新增模式</button></div><div class="agent-mode-list" id="mode-list">${modes.map(modeRow).join('')}</div></div>`;
    $('#profile-activate').onclick=()=>{captureEditor();managerState.activeId=p.id;paintProfileList();paintProfileEditor()};
    $('#profile-delete').onclick=()=>{if(managerState.profiles.length<=1)return;managerState.profiles=managerState.profiles.filter(x=>x.id!==p.id);if(managerState.activeId===p.id)managerState.activeId=managerState.profiles[0].id;managerState.selectedId=managerState.profiles[0].id;paintProfileList();paintProfileEditor()};
    $('#mode-add').onclick=()=>{captureEditor();p.request_presets.push({id:'mode-'+(p.request_presets.length+1),label:'新模式',model:'',temperature:null,params:{}});const nm=p.request_presets[p.request_presets.length-1];(managerState.openModes[p.id]||(managerState.openModes[p.id]=new Set())).add(nm.id);paintProfileEditor()}; /* v260929d · 新增模式自动展开 */
    $('#profile-test').onclick=async()=>{try{captureEditor();managerState.activeId=p.id;await saveAllProfiles(false);const r=await api('/api/agent/test',{method:'POST',body:{}});toast(r.models?.length?`连接成功：${r.models.slice(0,3).join(' / ')}`:'连接成功')}catch(e){toast(e.message,true)}};
    wireModeDeletes();
  }
  function modeRow(m,i){const pid=selectedProfile()?.id,open=!!managerState.openModes?.[pid]?.has(m.id);return `<div class="agent-mode-row${open?' open':''}" data-mode-row="${i}"><input class="search-input" data-mode-id value="${esc(m.id||'')}" placeholder="id"><input class="search-input" data-mode-label value="${esc(m.label||'')}" placeholder="label"><input class="search-input" data-mode-model value="${esc(m.model||'')}" placeholder="模型名"><label class="mode-default"><input type="radio" name="mode-default" value="${esc(m.id||'')}" ${m.id===selectedProfile()?.default_request_preset?'checked':''}> 默认</label><button class="ghost-btn mode-toggle" type="button" data-mode-toggle="${i}" title="${open?'收起':'展开'}">${open?'▾':'▸'}</button><div class="agent-mode-body"><input class="search-input" data-mode-temp type="number" min="0" max="2" step="0.1" value="${m.temperature==null?'':m.temperature}" placeholder="温度"><button class="ghost-btn danger mode-delete" type="button" data-mode-delete="${i}">删除</button><textarea class="search-input mode-params" data-mode-params placeholder='{"reasoning_effort":"low"}'>${esc(JSON.stringify(m.params||{},null,2))}</textarea></div></div>`} /* v260929d · 模式行折叠：头部只留 id/label/模型/默认/▸，温度与 params 藏进 body（DOM 常驻，captureEditor 仍可读到） */
  function wireModeDeletes(){$$('[data-mode-toggle]').forEach(b=>b.onclick=()=>{const p=selectedProfile();const set=managerState.openModes[p.id]||(managerState.openModes[p.id]=new Set());const id=$(`[data-mode-row="${b.dataset.modeToggle}"] [data-mode-id]`)?.value.trim()||p.request_presets[Number(b.dataset.modeToggle)]?.id;if(id)set.has(id)?set.delete(id):set.add(id);paintProfileEditor()});$$('[data-mode-delete]').forEach(b=>b.onclick=()=>{captureEditor();const p=selectedProfile();p.request_presets.splice(Number(b.dataset.modeDelete),1);if(!p.request_presets.length)p.request_presets=[{id:'default',label:'默认',model:'',temperature:null,params:{}}];if(!p.request_presets.some(x=>x.id===p.default_request_preset))p.default_request_preset=p.request_presets[0].id;paintProfileEditor()})}
  function captureEditor(){
    const p=selectedProfile();if(!p||!$('#pf-name'))return;
    p.name=$('#pf-name').value.trim()||'未命名配置';p.base_url=$('#pf-base').value.trim();const key=$('#pf-key').value.trim();if(key)p.api_key=key;p.timeout=Math.max(5,Math.min(600,Number($('#pf-timeout').value)||120));p.max_output_tokens=Math.max(0,Number($('#pf-max').value)||0);p.temperature=$('#pf-temp').value.trim()===''?null:Number($('#pf-temp').value);p.show_reasoning=$('#pf-reason').value==='1';
    const modes=[];$$('[data-mode-row]').forEach(r=>{let params={};try{params=JSON.parse($('[data-mode-params]',r).value||'{}')}catch{throw new Error('请求模式 params 必须是合法 JSON 对象')}if(!params||Array.isArray(params)||typeof params!=='object')throw new Error('请求模式 params 必须是 JSON 对象');const id=$('[data-mode-id]',r).value.trim();if(!id)throw new Error('请求模式 id 不能为空');modes.push({id,label:$('[data-mode-label]',r).value.trim()||id,model:$('[data-mode-model]',r).value.trim(),temperature:$('[data-mode-temp]',r).value.trim()===''?null:Number($('[data-mode-temp]',r).value),params})});
    const ids=new Set();for(const m of modes){if(ids.has(m.id))throw new Error('请求模式 id 不能重复：'+m.id);ids.add(m.id)}p.request_presets=modes;const checked=$('input[name="mode-default"]:checked');p.default_request_preset=checked?.value||modes[0]?.id||'default';
  }
  async function saveAllProfiles(notify=true){
    try{captureEditor();const s=managerState;s.app.llm={...s.app.llm,enabled:$('#agent-enabled')?.checked===true,vision_enabled:$('#llm-vision-global')?.checked===true,system_prompt:$('#global-system-prompt')?.value||'',active_profile_id:s.activeId,profiles:s.profiles};const saved=await api('/api/config/app',{method:'POST',body:s.app});window.ERWConfigSync?.(saved); /* v260929d · 回写主应用 state.config，多模态开关等免刷新生效 */s.cfg.app=saved;s.app=saved;s.llm=saved.llm||{};s.profiles=JSON.parse(JSON.stringify(s.llm.profiles||[]));s.activeId=s.llm.active_profile_id||s.profiles[0]?.id;s.selectedId=s.activeId;paintManagerShell($('#settings-panel'));paintProfileEditor();if(notify)toast('Agent 配置已保存')}catch(e){toast(e.message,true);throw e}
  }

  async function enhanceAgentPage(){
    if(route()!=='agent')return;const preset=$('#agent-preset');if(!preset||$('#agent-profile-select'))return;const cfg=await api('/api/config');const llm=cfg.app?.llm||{},profiles=llm.profiles||[];if(!profiles.length)return;
    const wrap=document.createElement('div');wrap.className='agent-runtime-selects';wrap.innerHTML=`<label>API 配置 <select class="search-input" id="agent-profile-select">${profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===llm.active_profile_id?'selected':''}>${esc(p.name||'未命名配置')}</option>`).join('')}</select></label><span class="agent-profile-badge" id="agent-profile-badge">${esc(llm.active_profile_name||'')}</span>`;
    preset.closest('.agent-preset-label')?.parentElement?.insertBefore(wrap,preset.closest('.agent-preset-label'));
    $('#agent-profile-select').onchange=async()=>{const fresh=await api('/api/config');fresh.app.llm.active_profile_id=$('#agent-profile-select').value;const saved=await api('/api/config/app',{method:'POST',body:fresh.app});const active=saved.llm?.profiles?.find(p=>p.id===saved.llm.active_profile_id);$('#agent-profile-badge').textContent=active?.name||'';const modes=active?.request_presets||[];preset.innerHTML=modes.map((m,i)=>`<option value="${esc(m.id)}" ${m.id===active?.default_request_preset||(!active?.default_request_preset&&i===0)?'selected':''}>${esc(m.label||m.id)}</option>`).join('');preset.dispatchEvent(new Event('change',{bubbles:true}));toast('已切换 Agent API 配置')};
  }

  function onSettingsClick(e){const btn=e.target.closest('[data-set-tab="llm"]');if(!btn)return;setTimeout(()=>renderProfileManager().catch(err=>toast(err.message,true)),0)}
  const observer=new MutationObserver(()=>{installSidebarToggle();if(route()==='agent')enhanceAgentPage().catch(()=>{})});
  window.addEventListener('DOMContentLoaded',()=>{installSidebarToggle();document.addEventListener('click',onSettingsClick);observer.observe(document.body,{childList:true,subtree:true});if(route()==='agent')enhanceAgentPage().catch(()=>{})});
  window.addEventListener('hashchange',()=>setTimeout(()=>{installSidebarToggle();if(route()==='agent')enhanceAgentPage().catch(()=>{})},0));
})();
