/* Shared answer-bound sources panel. It lives outside streaming message trees. */
(()=>{
  'use strict';
  const kinds={note:'笔记',idea:'灵感',summary:'总结',literature:'文献',journal:'实验记录',memory:'记忆',page:'页面 / 选区',file:'文件'};
  const channels={manual:'主动引用',rag:'知识检索',read:'知识读取',memory:'长期记忆',page:'页面 / 选区',history:'历史带入'};
  const statuses={prepared:'已准备，尚未确认发起',requested:'请求已发起',responded:'已收到响应',failed:'请求失败（已收到错误响应）',unknown:'发送 / 完成状态未知'};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let state=null,panel=null,focusReturn=null,generation=0,controller=null,refreshTimer=null;
  const captionText=text=>String(text||'正在生成的回答').replace(/```[\s\S]*?```/g,'').replace(/\[\[([^\]\n]+)\]\]/g,(_,target)=>target.split('|').at(-1)).replace(/[#*`_~]/g,'').replace(/\s+/g,' ').trim().slice(0,80);
  const revisions=new Map();
  const selections=new Map();
  function remember(){if(!state)return;selections.set(state.sid+':'+(state.mid||state.rid),{selected:state.selected,snapshot:state.snapshot,filter:state.filter});if(selections.size>100)selections.delete(selections.keys().next().value)}
  function entry(message,sessionId=''){
    if(message.role!=='assistant')return '';
    const summary=message.source_summary;
    const note=!summary||summary.recording_status!=='complete'?'来源记录不完整':summary.provided_source_count?Object.entries(summary.counts_by_kind||{}).map(([k,n])=>`${n} 条${kinds[k]||'资料'}`).join(' · '):'本轮未提供知识资料';
    const sid=sessionId||message.session_id||window.ERWAgentClient?.sessionId()||'';
    if(!message.id&&!message.run_id)return '';
    return `<button type="button" class="agent-sources-entry" data-source-session="${esc(sid)}" data-source-message="${esc(message.id||'')}" data-source-run="${esc(message.run_id||'')}" data-source-caption="${esc(captionText(message.content))}" aria-haspopup="dialog" aria-controls="agent-sources-panel" aria-expanded="false"><span class="agent-sources-icon" aria-hidden="true">▧</span><strong>本轮参考</strong><span>${esc(note)}</span><span aria-hidden="true">›</span></button>`;
  }
  async function api(path,signal){
    const response=await fetch('/api/agent/'+path,{signal});
    const data=await response.json();if(!response.ok)throw Error(data.message||data.error||'来源暂时无法读取');return data;
  }
  function base(){return state.mid?`sessions/${encodeURIComponent(state.sid)}/messages/${encodeURIComponent(state.mid)}/sources`:`runs/${encodeURIComponent(state.rid)}/sources`}
  function ensure(){
    if(panel)return;
    panel=document.createElement('aside');panel.id='agent-sources-panel';panel.className='agent-sources-panel';panel.hidden=true;
    panel.setAttribute('role','dialog');panel.setAttribute('aria-labelledby','agent-sources-title');
    panel.innerHTML=`<div class="agent-sources-resize" role="separator" tabindex="0" aria-label="调整参考面板宽度" aria-orientation="vertical"></div><header><div><h3 id="agent-sources-title">本轮参考</h3><small class="agent-sources-caption">来源记录 · 对应所选回答</small></div><button type="button" data-sources-close aria-label="关闭本轮参考">×</button></header><div class="agent-sources-content"></div>`;
    document.body.append(panel);
    panel.querySelector('[data-sources-close]').onclick=close;
    const handle=panel.querySelector('.agent-sources-resize');
    handle.onpointerdown=e=>{if(e.button!==0)return;e.preventDefault();handle.setPointerCapture(e.pointerId);handle.onpointermove=move=>width(innerWidth-move.clientX);handle.onpointerup=()=>{handle.onpointermove=null;localStorage.setItem('agentSourcesWidth',panel.style.width)}};
    handle.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();width(panel.getBoundingClientRect().width+(e.key==='ArrowLeft'?24:-24));localStorage.setItem('agentSourcesWidth',panel.style.width)}};
  }
  function width(value){const size=Math.max(340,Math.min(640,innerWidth-24,Number(value)||480));panel.style.width=size+'px';document.documentElement.style.setProperty('--agent-sources-width',size+'px');if(state){const layout=document.querySelector('.agent-layout'),left=layout?.getBoundingClientRect().left||180,sessions=document.querySelector('.agent-sessions')?.getBoundingClientRect().width||270,dock=!!layout&&!state.floating&&innerWidth-left-size-sessions-30>=520;document.body.dataset.agentSourcesMode=dock?'dock':'drawer';panel.setAttribute('aria-modal',String(!dock))}}
  function layout(){if(!panel||panel.hidden)return;width(parseFloat(panel.style.width)||480)}
  function expanded(){document.querySelectorAll('.agent-sources-entry').forEach(b=>b.setAttribute('aria-expanded',String(!!state&&b.dataset.sourceSession===state.sid&&b.dataset.sourceMessage===state.mid&&b.dataset.sourceRun===state.rid)))}
  function close(){if(!state)return;remember();generation++;controller?.abort();clearTimeout(refreshTimer);panel.hidden=true;state=null;delete document.body.dataset.agentSourcesMode;expanded();if(focusReturn?.isConnected)focusReturn.focus();else document.querySelector('#agent-input,#fab-input,#as-view-answer')?.focus()}
  async function open({sid,mid='',rid='',target='',floating=false,caption=''},origin){
    ensure();remember();generation++;controller?.abort();clearTimeout(refreshTimer);
    state={sid,mid,rid,target,floating,filter:'all',selected:'',snapshot:'',...(selections.get(sid+':'+(mid||rid))||{}),revision:-1,view:null,details:new Map()};focusReturn=origin||document.activeElement;
    panel.querySelector('.agent-sources-caption').textContent=caption?'对应回答 · '+caption:'来源记录 · 对应所选回答';
    panel.hidden=false;width(parseFloat(localStorage.getItem('agentSourcesWidth'))||480);layout();expanded();
    panel.querySelector('.agent-sources-content').innerHTML='<p class="agent-sources-empty" role="status">正在读取这条回答的来源…</p>';
    panel.querySelector('[data-sources-close]').focus();await load();
  }
  async function load(){
    if(!state)return;const token=generation,selected=state,key=base();controller?.abort();controller=new AbortController();
    try{
      const view=await api(key,controller.signal);if(token!==generation||selected!==state)return;
      const revision=view.source_summary?.revision||0;if(revision<state.revision)return;
      if(state.view&&revision===state.revision)return;
      state.revision=revision;state.view=view;
      if(!state.mid)for(const source of view.sources)state.details.set(source.source_id,source);
      if(state.target){const rows=view.sources.filter(s=>[s.title,s.entity_id].includes(state.target.split('#')[0]));if(rows.length===1){state.selected=rows[0].source_id;state.filter='all';if(!rows[0].provided)state.targetNotice='这处链接匹配到留存来源，但无法确认该片段已提供给模型。'}else{state.targetNotice=rows.length?'这处链接匹配多个同名来源，请手动选择。':'这处链接未匹配到本轮记录的来源。';state.unresolvedTarget=true}state.target=''}
      if(!state.unresolvedTarget)state.selected=state.selected||view.sources[0]?.source_id||'';render();
    }catch(error){if(error.name==='AbortError'||token!==generation)return;panel.querySelector('.agent-sources-content').innerHTML=`<div class="agent-sources-empty" role="alert">${esc(error.message)}<br><button type="button" data-sources-retry>重试</button></div>`;panel.querySelector('[data-sources-retry]').onclick=load}
  }
  function render(){
    if(!state?.view)return;const view=state.view,summary=view.source_summary,content=panel.querySelector('.agent-sources-content');
    const scroll=content.scrollTop;
    // Only the list/statistics change on events. The detail DOM stays mounted so
    // selection and scroll survive further model output and source updates.
    let top=content.querySelector('.agent-sources-list-section');
    if(!top){content.innerHTML='<section class="agent-sources-list-section"></section><section class="agent-sources-detail" aria-label="本轮发送片段"></section>';top=content.firstElementChild}
    const filters=[['all','全部'],...Array.from(new Set(view.sources.map(s=>s.kind))).map(k=>[k,kinds[k]||'其他'])];
    const rows=view.sources.filter(s=>state.filter==='all'||s.kind===state.filter);
    top.innerHTML=`<p class="agent-sources-stats">${summary.recording_status==='complete'?`${summary.provided_source_count} 条资料已提供 · ${summary.cited_source_count} 条在回答中引用`:'来源记录不完整 · 已知提供 '+summary.provided_source_count+' 条'}</p><p class="agent-sources-hint">已提供表示进入请求上下文；已引用表示回答存在明确链接，均不代表结论已核实。</p>${(view.warnings||[]).length?`<details class="agent-sources-warning"><summary>记录范围说明</summary>${view.warnings.map(w=>`<p>${esc(w)}</p>`).join('')}</details>`:''}<div class="agent-sources-filters" aria-label="筛选来源">${filters.map(([id,label])=>`<button type="button" data-sources-filter="${esc(id)}" aria-pressed="${state.filter===id}">${esc(label)} ${view.sources.filter(s=>id==='all'||s.kind===id).length}</button>`).join('')}</div><div class="agent-sources-list">${rows.map(s=>`<button type="button" class="agent-source-card ${state.selected===s.source_id?'selected':''}" data-source-select="${esc(s.source_id)}" aria-pressed="${state.selected===s.source_id}"><span class="agent-source-number">${s.number}</span><span><strong>${esc(s.title)}</strong><small>${esc(kinds[s.kind]||s.kind)}${s.tags?.length?' · '+s.tags.map(esc).join('、'):''}</small><small>${(s.channels?.length?s.channels:[s.channel]).map(c=>esc(channels[c]||c)).join(' · ')} · ${s.cited?'回答已引用':s.provided?'已提供':'已获得，未确认提供'}</small></span></button>`).join('')||'<p class="agent-sources-empty">'+(summary.recording_status==='complete'?'本轮未提供知识资料。':'没有可还原的来源片段。')+'</p>'}</div>${view.unresolved_citations?.length?`<p class="agent-sources-hint">${view.unresolved_citations.length} 处链接未能唯一匹配本轮已提供来源。</p>`:''}<details class="agent-source-requests"><summary>请求记录 · ${view.requests.length} 次</summary>${view.requests.map((r,i)=>`<p>${i+1}. ${r.step?`步骤 ${Number(r.step)} · 尝试 ${Number(r.attempt)||1} · `:""}${esc(statuses[r.status]||r.status)} · ${r.stream?'流式':'普通'} · ${r.protocol==='text'?'文本工具协议':'工具协议'}<br><small>${esc(r.created)}${r.error?' · '+esc(r.error):''}</small></p>`).join('')}</details>`;
    if(state.targetNotice){const notice=document.createElement('p');notice.className='agent-sources-warning';notice.setAttribute('role','status');notice.textContent=state.targetNotice;top.prepend(notice)}
    top.querySelectorAll('[data-sources-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.sourcesFilter;render()});
    top.querySelectorAll('[data-source-select]').forEach(b=>b.onclick=()=>{state.selected=b.dataset.sourceSelect;state.snapshot='';render()});
    content.scrollTop=scroll;showDetail();
  }
  async function showDetail(){
    if(!state)return;const current=state,token=generation,id=state.selected,detail=panel.querySelector('.agent-sources-detail');if(!id){detail.replaceChildren();return}
    const key=id+':'+state.snapshot;if(detail.dataset.key===key){
      const source=state.details.get(id),select=detail.querySelector('[data-source-snapshot]');
      if(source&&select&&select.options.length!==source.snapshots?.length){select.innerHTML=source.snapshots.map((s,i)=>`<option value="${esc(s.snapshot_id)}" ${s.snapshot_id===state.snapshot?'selected':''}>${i+1}. ${s.provided?'已提供':'未确认提供'} · ${esc(channels[s.channel]||s.channel)}${s.partial?' · 压缩节选':''} · ${esc(s.version?.slice(0,8)||'版本未知')}</option>`).join('')}
      return;
    }
    detail.dataset.key=key;
    let source=state.details.get(id);
    if(!source){
      detail.innerHTML='<p role="status">正在读取当时的片段…</p>';
      try{source=state.mid?await api(base()+'/'+encodeURIComponent(id)):state.view.sources.find(s=>s.source_id===id);if(token!==generation||state!==current||state.selected!==id)return;state.details.set(id,source)}
      catch(error){if(token!==generation||state!==current||state.selected!==id)return;detail.innerHTML=`<p role="alert">${esc(error.message)}</p><button type="button" data-source-detail-retry>重试读取片段</button>`;detail.querySelector('button').onclick=()=>{delete detail.dataset.key;showDetail()};return}
    }
    const snapshots=source.snapshots||[],snapshot=snapshots.find(s=>s.snapshot_id===state.snapshot)||snapshots.find(s=>s.provided)||snapshots[0];
    if(!snapshot){detail.innerHTML='<p>这条来源没有可还原的片段。</p>';return}
    state.snapshot=snapshot.snapshot_id;detail.dataset.key=id+':'+state.snapshot;
    const location=snapshot.location||{};
    detail.innerHTML=`<h4>${snapshot.provided?"本轮发送片段":"当时获得的片段（未确认提供）"}</h4>${source.projects?.length?`<p class="agent-sources-hint">项目：${source.projects.map(p=>esc(window.ERWResearchUI?.projectLabel(p)||p)).join('、')}</p>`:''}<label class="agent-source-fragment-label">片段 / 版本<select data-source-snapshot>${snapshots.map((s,i)=>`<option value="${esc(s.snapshot_id)}" ${s.snapshot_id===snapshot.snapshot_id?'selected':''}>${i+1}. ${s.provided?'已提供':'未确认提供'} · ${esc(channels[s.channel]||s.channel)}${s.partial?' · 压缩节选':''} · ${esc(s.version?.slice(0,8)||'版本未知')}</option>`).join('')}</select></label><p class="agent-sources-hint">${location.page?'第 '+Number(location.page)+' 页 · ':''}${location.offset!=null?'字符起点 '+Number(location.offset)+' · ':''}${snapshot.partial?'压缩后的实际节选':'留存片段'}${snapshot.updated?' · '+esc(snapshot.updated):''}</p><blockquote class="agent-source-excerpt" tabindex="0">${esc(snapshot.text)}</blockquote><p class="agent-sources-hint">${snapshot.provided?"片段来自当时请求的来源记录。":"片段留存在历史资料中，无法确认已提供给模型。"}原条目可能已更新或删除。</p><div class="agent-source-actions">${['doc','paper'].includes(source.entity_type)?'<button type="button" data-source-open>打开原条目 ↗</button>':''}<button type="button" data-source-copy>复制片段</button></div><p class="agent-source-action-status" role="status"></p>`;
    detail.querySelector('[data-source-snapshot]').onchange=e=>{state.snapshot=e.target.value;showDetail()};
    if(source.request_states?.length){const states=document.createElement('details');states.className='agent-source-requests';const labels={full:'内容块完整保留',partial:'压缩节选',extractive:'历史摘录',omitted:'本次未提供'};states.innerHTML='<summary>各次请求的提供范围</summary>'+source.request_states.map(r=>`<p>第 ${Number(r.number)} 次请求 · ${(r.representations||[]).map(v=>esc(labels[v]||v)).join('、')} · ${esc(statuses[r.status]||r.status)}${r.request_id===state.view.final_request_id?' · 生成本条回答':''}</p>`).join('');detail.append(states)}
    const status=detail.querySelector('[role=status]');
    detail.querySelector('[data-source-copy]').onclick=async()=>{try{await navigator.clipboard.writeText(snapshot.text);status.textContent='片段已复制'}catch{status.textContent='复制失败，可选中上方片段后复制'}};
    detail.querySelector('[data-source-open]')?.addEventListener('click',async()=>{try{
      if(source.entity_type==='doc'){
        const response=await fetch('/api/docs/'+encodeURIComponent(source.entity_id)),doc=await response.json();if(!response.ok)throw Error(doc.message||'原条目已删除或不可用，历史片段仍保留');
        if(await window.ERWNav.open(doc.kind,doc.id)===false){status.textContent='已取消跳转，历史片段仍保留';return}
      }else if(source.paper_id){await window.ERWNav.open('literature',source.paper_id)}
      if(state===current)status.textContent='已打开原条目的当前版本';
    }catch(error){if(state===current)status.textContent=error.message}});
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('.agent-sources-entry');if(!button)return;
    event.preventDefault();const options={sid:button.dataset.sourceSession,mid:button.dataset.sourceMessage,rid:button.dataset.sourceRun,caption:button.dataset.sourceCaption,floating:!!button.closest('#erw-fab-panel')};
    if(state&&state.sid===options.sid&&state.mid===options.mid&&state.rid===options.rid){close();return}open(options,button);
  });
  // Capture before the ordinary citation opener. Ctrl/Cmd-click retains direct navigation.
  document.addEventListener('click',event=>{
    if(event.ctrlKey||event.metaKey||event.altKey)return;const anchor=event.target.closest?.('[data-agent-reference]');if(!anchor||anchor.closest('#agent-sources-panel'))return;
    const article=anchor.closest('.agent-message.assistant,.fab-msg.assistant,.as-answer');const button=article?.querySelector('.agent-sources-entry');if(!button)return;
    event.preventDefault();event.stopImmediatePropagation();open({sid:button.dataset.sourceSession,mid:button.dataset.sourceMessage,rid:button.dataset.sourceRun,target:anchor.dataset.agentReference,caption:button.dataset.sourceCaption,floating:!!anchor.closest('#erw-fab-panel')},anchor);
  },true);
  document.addEventListener('keydown',event=>{if(!state)return;if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close()}else if(event.key==='Tab'&&document.body.dataset.agentSourcesMode==='drawer'){
    const focusable=[...panel.querySelectorAll('button,select,[tabindex="0"]')].filter(e=>!e.disabled&&!e.hidden);const first=focusable[0],last=focusable.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
  }},true);
  document.addEventListener('erw-agent-sources-updated',event=>{
    const data=event.detail||{},old=revisions.get(data.run_id)||-1;if(data.revision<=old)return;revisions.set(data.run_id,data.revision);
    if(state&&!state.mid&&state.rid===data.run_id){clearTimeout(refreshTimer);refreshTimer=setTimeout(load,180)}
  });
  window.ERWAgentClient?.subscribe(event=>{if(state&&event.type==='select'&&event.sessionId!==state.sid)close();if(state&&event.type==='session'&&event.sessionId===state.sid&&!state.mid){const messages=window.ERWAgentClient.snapshot(state.sid).session.messages;const m=messages.filter(m=>m.role==='assistant'&&m.run_id===state.rid).at(-1);if(m?.id){state.mid=m.id;state.revision=-1;load()}}});
  window.addEventListener('hashchange',close);window.addEventListener('resize',layout);
  window.ERWAgentSources={entry,open,close};
})();
