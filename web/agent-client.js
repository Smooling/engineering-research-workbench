/* One in-page conversation store and durable stream transport for both views. */
(()=>{
  'use strict';
  const sessions=new Map(),listeners=new Set(),monitors=new Map(),resolutions=new Map(),drafts={},runStates=new Map();
  let selected=localStorage.getItem('agentActiveSession')||localStorage.getItem('fabAgentSession')||'',queued=new Map();
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  async function api(path,body,signal){
    const f=window.erwFetch||fetch;
    const response=await f('/api/agent/'+path,{...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),signal});
    const data=await response.json();if(!response.ok)throw Error(data.message||data.error||`HTTP ${response.status}`);return data;
  }
  let capabilities=null,capabilityLoad=null,settingsQueue=Promise.resolve(),savingSettings=0;
  const capabilityNames={rag_enabled:'RAG',memory_enabled:'记忆',skills_enabled:'Skill'};
  function capabilityControls(){
    return `<div class="agent-capability-controls" aria-label="默认能力开关"><span class="agent-capability-label" title="本次实际使用的能力还会受提问要求与助手权限限制">默认能力</span>${Object.entries(capabilityNames).map(([key,label])=>`<button type="button" data-agent-capability="${key}" aria-pressed="false" disabled><span aria-hidden="true">●</span> ${label}</button>`).join('')}<button type="button" data-agent-rag-config title="配置 Embedding 接口与向量索引" aria-label="配置 RAG">⚙</button></div>`;
  }
  function paintCapabilities(){
    document.querySelectorAll('[data-agent-capability]').forEach(button=>{
      const enabled=capabilities?.[button.dataset.agentCapability]!==false;
      button.setAttribute('aria-pressed',String(!!capabilities&&enabled));button.disabled=!capabilities||savingSettings>0;
      button.title=capabilities?`默认能力：${capabilityNames[button.dataset.agentCapability]} ${enabled?'已开启，点击关闭':'已关闭，点击开启'}；本次任务可按你的要求限制`:'正在加载能力设置';
    });
    document.querySelectorAll('[data-capability]').forEach(input=>{if(capabilities&&!input.disabled)input.checked=capabilities[input.dataset.capability]!==false});
  }
  function adoptCapabilities(options){capabilities={...options};paintCapabilities();notify('capabilities',selected);return {...capabilities}}
  async function getCapabilities(){
    if(capabilities)return {...capabilities};
    if(!capabilityLoad)capabilityLoad=api('system').then(data=>adoptCapabilities(data.settings||{})).finally(()=>{capabilityLoad=null});
    return capabilityLoad;
  }
  function saveSettings(patch){
    savingSettings++;paintCapabilities();
    const work=settingsQueue.catch(()=>{}).then(async()=>{await getCapabilities();return adoptCapabilities(await api('settings',patch))});
    settingsQueue=work;
    return work.finally(()=>{savingSettings--;paintCapabilities()});
  }
  function mountCapabilities(root=document){
    root.querySelectorAll('[data-agent-capability]').forEach(button=>button.onclick=async()=>{
      try{const options=await getCapabilities();await saveSettings({[button.dataset.agentCapability]:options[button.dataset.agentCapability]===false})}catch(error){window.ERWToast?.('能力设置未保存：'+error.message,true)}
    });
    root.querySelectorAll('[data-agent-rag-config]').forEach(button=>button.onclick=()=>window.ERWAgentSystem?.open('rag'));
    paintCapabilities();getCapabilities().catch(error=>{window.ERWToast?.('能力设置加载失败：'+error.message,true);root.querySelectorAll('[data-agent-capability]').forEach(button=>{button.disabled=false;button.title='加载失败，点击重试'})});
  }
  function entry(id){if(!sessions.has(id))sessions.set(id,{session:{id,title:'新对话',messages:[]},live:null,owner:'',runId:''});return sessions.get(id)}
  function notify(type,id,source='shared'){
    const dispatch=()=>{for(const listener of listeners){try{listener({type,sessionId:id,source})}catch(error){console.error('Agent view update',error)}}};
    if(type!=='live'){dispatch();return}
    const key=id+':'+source;if(queued.has(key))return;queued.set(key,true);requestAnimationFrame(()=>{queued.delete(key);dispatch()});
  }
  function select(id,source='shared'){
    id=String(id||'');if(selected===id)return;selected=id;
    if(id){localStorage.setItem('agentActiveSession',id);localStorage.setItem('fabAgentSession',id)}else{localStorage.removeItem('agentActiveSession');localStorage.removeItem('fabAgentSession')}
    notify('select',id,source);
  }
  function setSession(session,source='shared'){
    const e=entry(session.id);if(e.live)return e.session;
    if(JSON.stringify(e.session)===JSON.stringify(session))return e.session;
    e.session=session;
    for(const message of session.messages||[]){if(message.role==='assistant'&&message.run_id){if(message.run_status)runStates.set(message.run_id,message.run_status);else if(!(message.drafts||[]).length)runStates.set(message.run_id,'completed')}}
    notify('session',session.id,source);return session;
  }
  async function refresh(id,source='shared'){
    if(!id)return null;const e=entry(id);if(e.live)return e.session;
    const session=await api('sessions/'+encodeURIComponent(id));return setSession(session,source);
  }
  function liveMessage(parts=[]){return {role:'assistant',content:'',response_parts:[...parts],__thinking:true,__streaming:true,__t0:Date.now(),__tl:[]}}
  function start(id,user,source,parts=[]){
    const e=entry(id);if(e.live)throw Error('当前会话已有任务执行中');
    e.owner=source;e.live=liveMessage(parts);e.runId='';e.stopping=false;e.stopSent=false;
    if(user)e.session={...e.session,messages:[...e.session.messages,user]};
    notify('session',id,source);notify('live',id,source);return e;
  }
  function apply(e,event,data,source){
    const m=e.live,id=e.session.id;if(!m)return;
    const stamp=()=>Date.now()-m.__t0;
    const close=()=>{const last=m.__tl.at(-1);if(last&&last.t1==null)last.t1=stamp()};
    if(event==='run'){e.runId=data.run_id;m.run_id=data.run_id;runStates.set(e.runId,'running');if(e.stopping)cancelRun(e).catch(error=>window.ERWToast?.(error.message,true))}
    else if(event==='round'){
      if(m.content&&m.__round&&m.__responseRound!==m.__round)m.response_parts.push({round:m.__round,content:m.content});
      close();m.content='';m.__round=(data.i|0)+1;m.__tl.push({kind:'llm',round:m.__round,t0:stamp(),t1:null});m.__note=`第 ${m.__round} 轮 · 正在生成…`;
    }else if(event==='capabilities'){m.capabilities=data.capabilities;m.source_policy=data.source_policy}
    else if(event==='retrieval'){m.retrievals=(m.retrievals||[]).filter(r=>r.call_id!==data.call_id);m.retrievals.push(data);m.__note=`RAG 检索返回 ${data.count||0} 条${data.warning?' · 语义检索已回退':''}`}
    else if(event==='skill'){m.skills_used=(m.skills_used||[]).filter(s=>s.name!==data.name);m.skills_used.push(data)}
    else if(event==='delta'){m.__thinking=false;m.content+=data.text||''}
    else if(event==='response'){
      m.__thinking=false;m.__responseRound=data.round;
      if(data.intermediate){m.response_parts=m.response_parts.filter(p=>p.round!==data.round);if(data.content)m.response_parts.push({round:data.round,content:data.content});m.content=''}else m.content=data.content||'';
    }else if(event==='tool'){close();m.__tl.push({kind:'tool',name:data.name,ok:data.ok,t0:Math.max(0,stamp()-(data.ms||0)),t1:stamp()});m.__note=`工具 ${data.name||''} ${data.ok?'已完成':'失败'}`}
    else if(event==='done'){
      if(!data.assistant)throw Error('任务结果缺少回复');
      if(!Array.isArray(data.assistant.response_parts))data.assistant.response_parts=data.assistant.evidence?window.ERWFabTimeline?.parts?.(data.assistant)||m.response_parts:m.response_parts;
      e.session={...e.session,updated:new Date().toISOString(),messages:[...e.session.messages,data.assistant]};e.live=null;e.stopping=false;
      if(e.runId)runStates.set(e.runId,data.assistant.run_status||((data.assistant.drafts||[]).some(d=>(drafts[d.draft_id]?.status||'pending')==='pending')?'waiting_approval':'completed'));
      notify('session',id,source);document.dispatchEvent(new CustomEvent('erw-agent-run-updated',{detail:{sessionId:id,runId:e.runId}}));return;
    }else if(event==='error'){const error=Error(data.message||'任务执行失败');error.agentError=true;throw error}
    notify('live',id,source);
  }
  function fail(e,error,source){
    if(!e.live)return;
    const m=e.live,partial=m.content||m.response_parts.length;
    if(partial){delete m.__streaming;delete m.__thinking;delete m.__note}
    const note=error.name==='AbortError'?'已停止生成。已完成的操作以会话和草稿记录为准。':'请求失败：'+error.message;
    e.session={...e.session,messages:[...e.session.messages,...(partial?[m]:[]),{role:'assistant',content:note,error:error.name!=='AbortError',created:new Date().toISOString()}]};e.live=null;
    notify('session',e.session.id,source);
  }
  async function follow(runId,cursor,signal,emit){
    let failures=0;
    for(;;){
      signal?.throwIfAborted();
      try{
        const events=await api('runs/'+encodeURIComponent(runId)+'/events?after='+cursor,undefined,signal);
        for(const item of events){cursor=Math.max(cursor,item.seq);if(item.event==='done'){emit('done',item.data);return item.data}emit(item.event,item.data)}
        const run=await api('runs/'+encodeURIComponent(runId),undefined,signal);runStates.set(runId,run.status);
        if(['completed','waiting_approval','cancelled','paused','interrupted'].includes(run.status)&&run.result?.assistant){emit('done',run.result);return run.result}
        if(['completed','waiting_approval'].includes(run.status)){const error=Error('任务已结束，但未取得保存的回复，请查看任务记录');error.agentError=true;throw error}
        if(['failed','cancelled','paused','interrupted'].includes(run.status)){
          const error=Error(run.error||({cancelled:'任务已停止',paused:'任务已暂停，可继续执行',interrupted:'任务执行中断，可继续执行'}[run.status])||'任务执行失败');error.agentError=true;throw error;
        }
        failures=0;if(events.length>=200)continue;
      }catch(error){if(error.agentError||error.name==='AbortError')throw error;if(++failures>=8)throw Error('暂时无法连接任务服务；任务可能仍在后台执行，恢复连接后请查看会话。')}
      await sleep(failures?Math.min(2000,failures*300):400);
    }
  }
  async function send(payload,{source='shared',signal,onEvent=()=>{},user}={}){
    const id=payload.session_id,e=start(id,user||{role:'user',content:payload.message,quote_text:payload.context?.quote_text||'',edited_from:payload.context?.edited_from||'',images:payload.images||[],created:new Date().toISOString()},source);
    let cursor=0,done=null,received=false,reader;
    const emit=(event,data)=>{apply(e,event,data,source);onEvent(event,data);if(event==='done')done=data};
    try{
      const response=await fetch('/api/agent/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal});
      if(!response.ok||!response.body){let data={};try{data=await response.json()}catch{}throw Error(data.message||data.error||`HTTP ${response.status}`)}
      e.runId=response.headers.get('X-Agent-Run-ID')||'';
      if(e.stopping&&e.runId)await cancelRun(e);
      reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
      function frame(block){
        let event='',seq=0;const lines=[];
        for(const line of block.split(/\r?\n/)){if(line.startsWith('event:'))event=line.slice(6).trim();else if(line.startsWith('id:'))seq=Number(line.slice(3).trim())||0;else if(line.startsWith('data:'))lines.push(line.slice(5).trimStart())}
        if(!lines.length)return;let data;try{data=JSON.parse(lines.join('\n'))}catch{return}
        cursor=Math.max(cursor,seq);received=true;emit(event,data);
      }
      try{
        for(;;){const chunk=await reader.read();buffer+=decoder.decode(chunk.value||new Uint8Array(),{stream:!chunk.done});let match;
          while((match=/\r?\n\r?\n/.exec(buffer))){const block=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);frame(block);if(done)break}
          if(done)break;if(chunk.done){if(buffer.trim())frame(buffer);break}
        }
      }catch(error){if(error.agentError||error.name==='AbortError'||!e.runId)throw error}
      finally{reader.cancel().catch(()=>{})}
      if(!done){
        if(!e.runId)throw Error('连接中断且未取得任务编号，请检查任务列表；不要重复提交同一写入任务。');
        e.live.__note='连接中断，正在恢复任务结果…';notify('live',id,source);
        // Older streams without event IDs can first use the authoritative result.
        let run;try{run=await api('runs/'+encodeURIComponent(e.runId),undefined,signal)}catch(error){if(error.name==='AbortError')throw error}
        if(run&&['completed','waiting_approval','cancelled','paused','interrupted'].includes(run.status)&&run.result?.assistant)emit('done',run.result);
        else{
          if(!cursor&&received){e.live=liveMessage();emit('reset',{})}
          await follow(e.runId,cursor,signal,emit);
        }
      }
      return done;
    }catch(error){fail(e,error,source);throw error}
  }
  async function cancelRun(e){
    if(!e.live||!e.runId||e.stopSent)return;
    e.stopSent=true;
    try{await api('runs/'+encodeURIComponent(e.runId)+'/cancel',{})}
    catch(error){e.stopSent=false;e.stopping=false;notify('live',e.session.id);throw error}
  }
  async function stop(id=selected){
    const e=entry(id);if(!e.live)return;
    e.stopping=true;e.live.__note='正在停止，保留已生成内容…';notify('live',id);
    await cancelRun(e);
  }
  function linkify(html){
    const holder=document.createElement('div');holder.innerHTML=html;
    const walker=document.createTreeWalker(holder,NodeFilter.SHOW_TEXT),nodes=[];
    while(walker.nextNode())if(!walker.currentNode.parentElement.closest('a,pre,code,script,style'))nodes.push(walker.currentNode);
    for(const node of nodes){
      const text=node.nodeValue,pattern=/\[\[([^\]\n]+)\]\]/g;let match,offset=0,fragment=document.createDocumentFragment();
      while((match=pattern.exec(text))){
        fragment.append(document.createTextNode(text.slice(offset,match.index)));
        const [target,...alias]=match[1].split('|'),anchor=document.createElement('a');
        anchor.href='#';anchor.dataset.agentReference=target.trim();anchor.className='agent-citation';anchor.textContent=alias.join('|')||target;anchor.title='打开引用：'+target;
        fragment.append(anchor);offset=pattern.lastIndex;
      }
      if(offset){fragment.append(document.createTextNode(text.slice(offset)));node.replaceWith(fragment)}
    }
    holder.querySelectorAll('a[href^="/api/docs/"]').forEach(anchor=>{const id=anchor.getAttribute('href').slice('/api/docs/'.length);if(id&&!id.includes('/')){try{anchor.dataset.agentReference=decodeURIComponent(id)}catch{return}anchor.href='#';anchor.classList.add('agent-citation')}});
    return holder.innerHTML;
  }
  document.addEventListener('click',async event=>{
    const anchor=event.target.closest?.('[data-agent-reference]');if(!anchor)return;
    event.preventDefault();if(anchor.getAttribute('aria-busy')==='true')return;
    anchor.setAttribute('aria-busy','true');
    try{const response=await fetch('/api/docs/resolve?target='+encodeURIComponent(anchor.dataset.agentReference));const doc=await response.json();if(!response.ok)throw Error(doc.message||'未找到引用条目');await window.ERWNav.open(doc.kind,doc.id,{note:anchor.dataset.agentView==='note'})}
    catch(error){window.ERWToast?.('引用无法打开：'+error.message,true)}finally{anchor.removeAttribute('aria-busy')}
  });
  async function syncDrafts(){const rows=await api('drafts?status=');let changed=false;for(const draft of rows){if(JSON.stringify(drafts[draft.id])!==JSON.stringify(draft)){drafts[draft.id]=draft;changed=true}}if(changed)notify('drafts',selected);return rows}
  async function resolveDraft(id,confirm){
    if(resolutions.has(id))return resolutions.get(id);
    const promise=(async()=>{try{const result=await api('drafts/'+encodeURIComponent(id)+(confirm?'/confirm':'/reject'),{});drafts[id]={...drafts[id],...result};notify('drafts',selected);return result}catch(error){await syncDrafts().catch(()=>{});throw error}finally{resolutions.delete(id)}})();
    resolutions.set(id,promise);return promise;
  }
  async function resume(runId,source='shared'){
    if(monitors.has(runId))return monitors.get(runId);
    const promise=(async()=>{
      const run=await api('runs/'+encodeURIComponent(runId)),id=run.session_id;
      if(entry(id).live)throw Error('当前会话已有任务执行中');
      let cursor=0;
      for(;;){const events=await api('runs/'+encodeURIComponent(runId)+'/events?after='+cursor);if(events.length)cursor=events.at(-1).seq;if(events.length<200)break}
      const next=await api('runs/'+encodeURIComponent(runId)+'/resume',{});
      const previous=entry(id).session.messages.filter(m=>m.role==='assistant'&&m.run_id===runId).at(-1);
      const e=start(id,null,source,previous?.response_parts||[]);e.runId=runId;runStates.set(runId,next.status);notify('live',id,source);
      try{if(['completed','waiting_approval'].includes(next.status)&&next.result?.assistant){apply(e,'done',next.result,source);return next.result}return await follow(runId,cursor,undefined,(event,data)=>apply(e,event,data,source))}
      catch(error){fail(e,error,source);throw error}
    })().finally(()=>monitors.delete(runId));monitors.set(runId,promise);return promise;
  }
  function draftPreview(draft){
    if(!draft.changes?.length)return JSON.stringify(draft.args||{},null,2);
    const labels={start_date:'开始日期',due:'截止日期',progress:'完成进度 %',status:'状态',projects:'关联项目',body:'正文',tags:'标签',kind_marks:'分类标记'};
    const value=v=>v===null||v===undefined||v===''?'未设置':Array.isArray(v)?v.join('、')||'未关联':String(v);
    return (draft.args?.title?'条目：'+draft.args.title+'\n\n':'')+draft.changes.map(change=>(labels[change.field]||change.field)+'：'+value(change.before)+' → '+value(change.after)).join('\n');
  }
  window.ERWAgentClient={api,send,stop,linkify,select,setSession,refresh,syncDrafts,resolveDraft,resume,drafts,runStates,capabilityControls,mountCapabilities,getCapabilities,saveSettings,adoptCapabilities,draftPreview,sessionId:()=>selected,snapshot:id=>entry(id),busy:id=>!!sessions.get(id)?.live,subscribe:listener=>{listeners.add(listener);return()=>listeners.delete(listener)}};
})();
