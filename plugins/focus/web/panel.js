/* 专注计时面板 · 插件 focus v1.1.0
 *
 * 接入 V3 原生桌面计时桥接，隐藏到托盘后继续计时；浏览器使用单调时钟兜底。
 *
 * 自登记（§6.3）：导航项、页头与渲染函数都由本文件声明，内核不再认识「专注」。
 * localStorage 键沿用 `focusMinutes` / `breakMinutes`，老用户的设置不会丢。
 */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* 内核的 toast 是 app.js 内部函数；这里优先用悬浮球提供的 window.ERWToast，否则自建一条 */
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

  function storedInt(key, fallback, min, max) {
    var raw = localStorage.getItem(key);
    var n = Number(raw);
    return raw != null && Number.isFinite(n) ? Math.max(min, Math.min(max, Math.round(n))) : fallback;
  }

  var state = {
    focus: {
      mode: '专注',
      focusMinutes: storedInt('focusMinutes', 25, 1, 240),
      breakMinutes: storedInt('breakMinutes', 5, 1, 120),
      seconds: 0, total: 0, timer: null, running: false, remaining: 0, endsAt: null, busy: false, native: false, completionId: null,
    },
  };
  state.focus.seconds = state.focus.focusMinutes * 60;
  state.focus.total = state.focus.focusMinutes * 60;
  state.focus.remaining = state.focus.total;

  async function renderFocus(){
    $('#main').innerHTML=`<section class="card focus-panel"><h3>专注计时</h3><p class="focus-caption">${hasNativeFocus()?'隐藏到托盘后仍会计时；结束时在屏幕右下角显示提醒，手动点击后关闭。':'专注与休息时长均可自定义，设置保存在当前浏览器。'}</p><div class="progress-ring" id="focus-ring"></div><div class="focus-time" id="focus-time">25:00</div><div class="focus-mode" id="focus-mode">专注 · 25 分钟</div>
      <div class="focus-duration-panel"><div class="focus-duration-grid"><label><span>专注时长</span><div><input id="focus-minutes" type="number" min="1" max="240" step="1" value="${state.focus.focusMinutes}"><em>分钟</em></div></label><label><span>休息时长</span><div><input id="break-minutes" type="number" min="1" max="120" step="1" value="${state.focus.breakMinutes}"><em>分钟</em></div></label><button class="secondary-btn" id="focus-apply">应用时长</button></div><div class="focus-presets"><span>快速预设</span>${[25,45,60,90].map(n=>`<button type="button" data-focus-preset="${n}">${n} min</button>`).join('')}</div></div>
      <div class="focus-actions"><button class="primary-btn" id="focus-start">开始</button><button class="secondary-btn" id="focus-reset">重置</button><button class="secondary-btn" id="focus-mode-btn">切换休息</button></div></section>`;
    paintFocus();
    $('#focus-start').onclick=()=>{ state.focus.running?pauseFocus():startFocus(); };
    $('#focus-reset').onclick=()=>resetFocus();
    $('#focus-mode-btn').onclick=()=>focusCommand(async()=>{const mode=state.focus.mode==='专注'?'休息':'专注';await resetFocusClock((mode==='专注'?state.focus.focusMinutes:state.focus.breakMinutes)*60,mode)});
    $('#focus-apply').onclick=()=>applyFocusDurations();
    $$('[data-focus-preset]').forEach(btn=>btn.onclick=()=>{ $('#focus-minutes').value=btn.dataset.focusPreset; applyFocusDurations(); });
    await refreshNativeFocus();paintFocus();
  }
  function clampFocusMinutes(value,min,max,fallback){ const n=Math.round(Number(value)); return Number.isFinite(n)?Math.max(min,Math.min(max,n)):fallback; }
  function applyFocusDurations(){return focusCommand(async()=>{
    const focus=clampFocusMinutes($('#focus-minutes')?.value,1,240,state.focus.focusMinutes);
    const rest=clampFocusMinutes($('#break-minutes')?.value,1,120,state.focus.breakMinutes);
    await resetFocusClock((state.focus.mode==='专注'?focus:rest)*60,state.focus.mode);
    state.focus.focusMinutes=focus; state.focus.breakMinutes=rest;
    localStorage.setItem('focusMinutes',String(focus)); localStorage.setItem('breakMinutes',String(rest));
    if($('#focus-minutes')) $('#focus-minutes').value=focus; if($('#break-minutes')) $('#break-minutes').value=rest;
    paintFocus(); toast(`已设置：专注 ${focus} 分钟 · 休息 ${rest} 分钟`);
  })}
  function paintFocus(){ const el=$('#focus-time'); if(!el)return; const s=state.focus.seconds; el.textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`; $('#focus-mode').textContent=`${state.focus.mode} · ${Math.round(state.focus.total/60)} 分钟`; $('#focus-start').textContent=state.focus.running?'暂停':'开始'; const deg=state.focus.total?Math.max(0,Math.min(360,(1-s/state.focus.total)*360)):0; $('#focus-ring').style.background=`conic-gradient(var(--accent) ${deg}deg,var(--surface-3) ${deg}deg)`; }
  function hasNativeFocus(){return typeof window.pywebview?.api?.desktop_focus_state==='function'}
  function clearFocusTick(){clearInterval(state.focus.timer);state.focus.timer=null}
  function acceptNativeFocus(value){
    if(!value?.initialized)return;
    const f=state.focus;clearFocusTick();f.native=true;f.mode=value.mode;f.total=value.total;f.seconds=value.seconds;f.remaining=value.remaining;f.running=value.running;
    f.endsAt=value.running?performance.now()+value.remaining*1000:null;
    if(f.running)f.timer=setInterval(tickFocus,1000);
    if(value.completed&&f.completionId!==value.completion_id){f.completionId=value.completion_id;toast(`${value.completion_mode||value.mode}计时完成`)}
    paintFocus();
  }
  async function refreshNativeFocus(){if(hasNativeFocus()){try{acceptNativeFocus(await window.pywebview.api.desktop_focus_state())}catch(error){console.warn('读取后台计时失败',error)}}}
  function tickFocus(){
    const f=state.focus;if(!f.running)return;
    f.remaining=Math.max(0,(f.endsAt-performance.now())/1000);f.seconds=Math.ceil(f.remaining);paintFocus();
    if(f.seconds===0){clearFocusTick();if(f.native){refreshNativeFocus()}else{f.running=false;f.endsAt=null;toast(`${f.mode}计时完成`);paintFocus()}}
  }
  async function focusCommand(action){
    if(state.focus.busy)return;
    state.focus.busy=true;setFocusBusy();
    try{await action()}catch(error){toast('计时操作失败：'+error.message,true)}finally{state.focus.busy=false;setFocusBusy();paintFocus()}
  }
  function setFocusBusy(){$$('.focus-actions button,#focus-apply,[data-focus-preset]').forEach(b=>b.disabled=state.focus.busy)}
  async function resetFocusClock(seconds,mode){
    if(hasNativeFocus()){acceptNativeFocus(await window.pywebview.api.desktop_focus_reset(seconds,mode))}
    else{clearFocusTick();Object.assign(state.focus,{running:false,native:false,mode,total:seconds,seconds,remaining:seconds,endsAt:null})}
  }
  function startFocus(){return focusCommand(async()=>{
    const f=state.focus;if(f.running)return;const seconds=f.remaining>0?f.remaining:f.total;
    if(hasNativeFocus()){acceptNativeFocus(await window.pywebview.api.desktop_focus_start(seconds,f.mode,f.total))}
    else{f.running=true;f.native=false;f.remaining=seconds;f.seconds=Math.ceil(seconds);f.endsAt=performance.now()+seconds*1000;clearFocusTick();f.timer=setInterval(tickFocus,1000)}
  })}
  function pauseFocus(){return focusCommand(async()=>{
    if(hasNativeFocus()){acceptNativeFocus(await window.pywebview.api.desktop_focus_pause())}
    else{const f=state.focus;if(f.running){f.remaining=Math.max(0,(f.endsAt-performance.now())/1000);f.seconds=Math.ceil(f.remaining)}clearFocusTick();f.running=false;f.endsAt=null}
  })}
  function resetFocus(){return focusCommand(()=>resetFocusClock(state.focus.total,state.focus.mode))}


    window.addEventListener('workbench:focus-state',event=>acceptNativeFocus(event.detail));
    window.addEventListener('pywebviewready',refreshNativeFocus);
    window.addEventListener('workbench:window-state',event=>{if(!event.detail.hidden)refreshNativeFocus()});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden){if(state.focus.native)refreshNativeFocus();else tickFocus()}});
  if (window.ERWPanels) {
    window.ERWPanels.register({
      id: 'focus', group: 'core', before: 'agent',
      label: '专注', icon: '◷', eyebrow: 'CORE WORK', title: '专注',
      render: function () { return renderFocus(); },
    });
  }
})();
