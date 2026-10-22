/* Milestones and phase plans share the existing Markdown records. No model calls. */
(() => {
  'use strict';
  const DAY=86400000, PALETTE=['#6574da','#219d91','#bb8637','#9a69b7','#368bb7'];
  const STATUS={planned:{label:'计划',color:'#7c89a6'},active:{label:'进行中',color:'#6574da'},blocked:{label:'受阻',color:'#c97738'},done:{label:'完成',color:'#219d91'}};
  const node=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  function day(value){
    const s=String(value||'');if(!/^\d{4}-\d{2}-\d{2}$/.test(s))return null;
    const d=new Date(s+'T00:00:00Z');return Number.isFinite(+d)&&d.toISOString().slice(0,10)===s?Math.floor(+d/DAY):null;
  }
  const key=d=>new Date(d*DAY).toISOString().slice(0,10);
  const short=d=>key(d).slice(5).replace('-','/');
  const today=()=>{const d=new Date();return day([d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-'))};
  const status=raw=>['完成','已完成'].includes(raw)?'done':['受阻','阻塞'].includes(raw)?'blocked':raw==='进行中'?'active':'planned';
  const projects=doc=>Array.isArray(doc.projects)&&doc.projects.length?doc.projects:doc.project?[doc.project]:[];
  function normalize(doc){
    const start=day(doc.start_date),end=day(doc.due),invalid=!!(doc.start_date&&start===null||doc.due&&end===null||start!==null&&end!==null&&start>end);
    const state=doc.status_class||status(doc.status),progress=state==='done'?100:doc.progress===null||doc.progress===undefined||doc.progress===''?null:Number.isFinite(Number(doc.progress))?Math.max(0,Math.min(100,Number(doc.progress))):null;
    return {...doc,_start:start,_end:end,_invalid:invalid,_status:state,_progress:progress,_phase:start!==null&&end!==null&&start<end,_scheduled:end!==null&&!invalid,_late:!invalid&&end!==null&&end<today()&&state!=='done'};
  }
  async function api(url,options){const f=window.erwFetch||fetch;const r=await f(url,options);const data=await r.json();if(!r.ok)throw Object.assign(Error(data.message||data.error||'请求失败'),{current:data.current,status:r.status});return data;}
  let instance=null;
  class Gantt {
    constructor(root,options){this.root=root;this.options=options;this.docs=[];this.scale=localStorage.getItem('milestoneGanttScale')||'fit';this.project='';this.query='';this.filter='';this.closed=new Set();this.destroyed=false;this.loading=true;this.selected=null;this.saving=null;this.onResize=()=>this.size();window.addEventListener('resize',this.onResize);this.render();this.load()}
    async load(){
      try{const data=await api('/api/milestones/plan');if(this.destroyed)return;this.docs=(data.items||[]).map(normalize);this.unavailable=data.unavailable||0;this.loading=false;this.render()}
      catch(error){if(this.destroyed)return;this.loading=false;this.root.replaceChildren();const empty=node('div','mg-empty');empty.append(node('strong','','甘特图加载失败'),node('span','',error.message));const retry=node('button','secondary-btn','重新加载');retry.onclick=()=>{this.loading=true;this.render();this.load()};empty.append(retry);this.root.append(empty)}
    }
    dirty(){return !!this.form&&JSON.stringify(this.payload())!==this.baseline}
    async guard(){
      if(this.saving){try{await this.saving}catch{return false}}
      if(!this.dirty())return true;if(this.guardPending)return this.guardPending;
      this.guardPending=(async()=>{const answer=await window.ERWDialog.choose('里程碑计划有未保存的修改，是否保存后继续？',{title:'保存计划修改？',buttons:[{value:'cancel',label:'继续编辑'},{value:'discard',label:'不保存'},{value:'save',label:'保存并继续',primary:true}]});if(answer==='cancel')return false;if(answer==='save')return this.save();this.baseline=JSON.stringify(this.payload());return true})();
      try{return await this.guardPending}finally{this.guardPending=null}
    }
    destroy(){this.destroyed=true;this.picker?.destroy();this.observer?.disconnect();window.removeEventListener('resize',this.onResize);clearTimeout(this.resizeTimer);this.root.replaceChildren();this.form=null}
    size(){if(this.destroyed||!this.scroll)return;const zoom=parseFloat(getComputedStyle(document.documentElement).zoom)||1,top=this.chart.getBoundingClientRect().top+window.scrollY,extras=(this.footer?.offsetHeight||25)+(this.chart.querySelector('.mg-unscheduled')?.offsetHeight||0)+40;this.scroll.style.maxHeight=Math.max(260,(innerHeight-top)/zoom-extras)+'px'}
    visible(){return this.docs.filter(d=>(!this.project||projects(d).includes(this.project))&&(!this.query||[d.title,...projects(d)].join(' ').toLocaleLowerCase().includes(this.query))&&(!this.filter||(this.filter==='late'?d._late:this.filter==='undated'?!d._scheduled:d._status===this.filter)))}
    render(){
      this.picker?.destroy();this.observer?.disconnect();this.form=null;this.root.replaceChildren();
      const page=node('section','milestone-gantt');this.root.append(page);
      const toolbar=node('div','mg-toolbar'),intro=node('div','mg-intro');intro.append(node('strong','','研究计划'),node('span','','阶段条看周期，菱形看节点'));
      const controls=node('div','mg-controls'),scope=node('div',''),search=node('input','mg-search');search.type='search';search.placeholder='搜索里程碑…';search.setAttribute('aria-label','搜索里程碑');search.value=this.query;
      search.oninput=()=>{this.query=search.value.trim().toLocaleLowerCase();this.window=null;this.draw()};
      const filter=node('select','mg-filter');filter.setAttribute('aria-label','里程碑状态筛选');
      for(const [value,label] of [['','全部状态'],['active','进行中'],['planned','计划'],['blocked','受阻'],['done','已完成'],['late','已逾期'],['undated','待排期']]){const o=node('option','',label);o.value=value;filter.append(o)}filter.value=this.filter;filter.onchange=()=>{this.filter=filter.value;this.window=null;this.draw()};
      controls.append(scope,search,filter);toolbar.append(intro,controls);page.append(toolbar);
      const scopeNames=[...new Set(this.docs.flatMap(projects))];
      const onScope=name=>{this.project=name;this.window=null;this.draw()};
      this.picker = window.ERWProjectScope?.mount
        ? window.ERWProjectScope.mount(scope,{names:scopeNames,value:this.project,onChange:onScope})
        : (()=>{                                  /* 未加载 project-scope 时降级为原生下拉 */
            const sel=node('select','mg-filter project-scope');sel.setAttribute('aria-label','项目范围');
            const opt=(v,l)=>{const o=node('option','',l);o.value=v;sel.append(o)};
            opt('','全部项目');for(const n of scopeNames)opt(n,n);
            sel.value=this.project;sel.onchange=()=>onScope(sel.value);scope.append(sel);
            return {destroy(){sel.remove()}};
          })();
      this.summary=node('div','mg-summary');page.append(this.summary);
      const tools=node('div','mg-time-tools'),legend=node('div','mg-legend');
      for(const [value,label] of [['fit','全览'],['day','日'],['week','周'],['month','月']]){const b=node('button','',label);b.type='button';b.dataset.ganttScale=value;b.onclick=()=>{this.scale=value;this.window=null;localStorage.setItem('milestoneGanttScale',value);this.draw()};tools.append(b)}
      const goToday=node('button','mg-today-button','定位今天');goToday.type='button';goToday.onclick=()=>{if(!this.range||today()<this.range.start||today()>this.range.end){this.window={start:today()-30,end:today()+60};this.draw()}this.scrollToDay(today())};tools.append(goToday);
      legend.append(node('span','','━ 阶段计划'),node('span','','◆ 里程碑'),node('span','mg-today-legend','│ 今天'));tools.append(legend);page.append(tools);
      this.layout=node('div','mg-layout');this.chart=node('div','mg-chart');this.layout.append(this.chart);page.append(this.layout);
      this.footer=node('div','mg-footer');page.append(this.footer);this.draw();
      this.observer=new ResizeObserver(()=>{if(this.scale!=='fit'||this.loading)return;clearTimeout(this.resizeTimer);this.resizeTimer=setTimeout(()=>{if(!this.destroyed&&Math.abs(this.chart.clientWidth-(this.lastWidth||0))>3)this.draw()},90)});this.observer.observe(this.chart);
    }
    draw(){
      if(this.destroyed)return;const docs=this.visible(),scheduled=docs.filter(d=>d._scheduled),pending=docs.filter(d=>!d._scheduled);
      this.summary.replaceChildren();
      for(const [label,count] of [['节点',docs.length],['阶段计划',scheduled.filter(d=>d._phase).length],['已完成',docs.filter(d=>d._status==='done').length],['逾期',docs.filter(d=>d._late).length]]){const item=node('span','');item.append(node('b','',count),node('span','',label));this.summary.append(item)}
      this.root.querySelectorAll('[data-gantt-scale]').forEach(b=>{const active=b.dataset.ganttScale===this.scale;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
      this.chart.replaceChildren();this.footer.textContent='点击阶段条、菱形或名称查看与编辑 · 未设置开始日期的条目显示为节点 · 多项目条目按首个项目分组';
      if(this.unavailable)this.footer.textContent+=' · '+this.unavailable+' 个文档暂不可读，重新加载可重试';
      if(this.loading){this.chart.append(node('div','mg-empty','正在载入完整计划…'));return}
      if(!docs.length){const empty=node('div','mg-empty');empty.append(node('strong','',this.docs.length?'没有符合筛选条件的里程碑':'把下一步研究安排到时间上'),node('span','',this.docs.length?'换一个关键词或项目范围试试':'新建里程碑后，设置开始与截止日期即可生成阶段计划。'));if(!this.docs.length){const b=node('button','primary-btn','＋ 新建里程碑');b.onclick=()=>this.options.onNew?.();empty.append(b)}this.chart.append(empty);return}
      this.lastWidth=this.chart.clientWidth;
      const dates=scheduled.flatMap(d=>[d._start===null?d._end:d._start,d._end]);
      const start=this.window?.start??(dates.length?Math.min(...dates)-7:today()-14),end=this.window?.end??(dates.length?Math.max(...dates)+8:today()+46),days=Math.max(1,end-start+1);
      this.range={start,end};this.labelWidth=this.chart.clientWidth<640?190:272;
      this.ppd=Math.min(40000/days,this.scale==='fit'?Math.max(1,(this.chart.clientWidth-this.labelWidth-32)/days):({day:32,week:10,month:3}[this.scale]||10));
      const width=Math.max(this.chart.clientWidth-this.labelWidth-2,days*this.ppd);
      this.scroll=node('div','mg-scroll');this.scroll.tabIndex=0;this.scroll.setAttribute('aria-label','里程碑甘特图，可横向滚动查看时间');
      const table=node('div','mg-table');table.setAttribute('role','table');table.setAttribute('aria-label','研究里程碑计划');table.style.setProperty('--mg-label-width',this.labelWidth+'px');table.style.setProperty('--mg-time-width',width+'px');table.style.setProperty('--mg-day',this.ppd+'px');
      const head=node('div','mg-axis');head.setAttribute('role','row');const corner=node('div','mg-corner','里程碑 / 阶段');corner.setAttribute('role','columnheader');const ruler=node('div','mg-ruler');ruler.setAttribute('role','columnheader');ruler.setAttribute('aria-label',key(start)+' 至 '+key(end));this.ruler(ruler,start,end,width);head.append(corner,ruler);table.append(head);
      const groups=new Map();for(const d of docs){const name=this.project||projects(d)[0]||'未关联项目';if(!groups.has(name))groups.set(name,[]);groups.get(name).push(d)}
      let groupIndex=0;
      for(const [name,rows] of groups){
        const color=PALETTE[groupIndex++%PALETTE.length],group=node('div','mg-group');group.setAttribute('role','row');group.style.setProperty('--mg-project',color);
        const label=node('button','mg-group-label');label.type='button';label.title=name;label.setAttribute('aria-expanded',String(!this.closed.has(name)));label.append(node('span','',this.closed.has(name)?'▸':'▾'),node('strong','',name),node('small','',rows.length));label.onclick=()=>{this.closed.has(name)?this.closed.delete(name):this.closed.add(name);this.draw()};
        const track=node('div','mg-group-track');group.append(label,track);table.append(group);
        if(this.closed.has(name))continue;
        rows.sort((a,b)=>(a._end??Infinity)-(b._end??Infinity)||String(a.title).localeCompare(String(b.title),'zh-CN'));
        for(const d of rows)this.row(table,d,width);
      }
      this.scroll.append(table);this.chart.append(this.scroll);
      if(pending.length){const note=node('div','mg-unscheduled',pending.length+' 个待排期 / 日期待修正的条目已保留在表内，可点击名称补齐日期。');this.chart.append(note)}
      this.size();
      if(this.scale!=='fit'&&!this.window)requestAnimationFrame(()=>{if(!this.destroyed)this.scrollToDay(today()>=start&&today()<=end?today():start)});
    }
    ruler(root,start,end,width){
      const years=end-start>800,first=new Date(start*DAY);let next=years?Date.UTC(first.getUTCFullYear(),0,1)/DAY:Date.UTC(first.getUTCFullYear(),first.getUTCMonth(),1)/DAY;
      while(next<=end){const d=new Date(next*DAY),following=(years?Date.UTC(d.getUTCFullYear()+1,0,1):Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,1))/DAY,left=Math.max(0,(next-start)*this.ppd),right=Math.min(width,(following-start)*this.ppd);if(right>left){const month=node('span','mg-month',years?d.getUTCFullYear()+'年':d.getUTCFullYear()+'年'+(d.getUTCMonth()+1)+'月');month.style.left=left+'px';month.style.width=right-left+'px';root.append(month)}next=following}
      const step=this.ppd>=25?1:this.ppd>=6?7:Math.max(14,Math.ceil((end-start)/150)),offset=step===7?(7-(new Date(start*DAY).getUTCDay()+6)%7)%7:0;
      for(let d=start+offset;d<=end;d+=step){const tick=node('span','mg-tick',this.ppd>=25?new Date(d*DAY).getUTCDate():short(d));tick.style.left=(d-start)*this.ppd+'px';root.append(tick)}
      if(today()>=start&&today()<=end){const t=node('span','mg-today-marker','今天');t.style.left=(today()-start+.5)*this.ppd+'px';root.append(t)}
    }
    row(table,d,width){
      const row=node('div','mg-row'+(d._late?' is-late':'')+(d.id===this.selected?' is-selected':''));row.dataset.milestoneId=d.id;row.setAttribute('role','row');row.style.setProperty('--mg-status',STATUS[d._status].color);
      const label=node('button','mg-row-label');label.type='button';label.title=d.title;label.setAttribute('role','rowheader');label.append(node('i','mg-status-dot'),node('span','mg-row-title',d.title));const meta=node('small','',d._late?'已逾期':STATUS[d._status].label);label.append(meta);label.onclick=()=>this.open(d.id);row.append(label);
      const lane=node('div','mg-lane');lane.setAttribute('role','cell');
      if(today()>=this.range.start&&today()<=this.range.end){const t=node('i','mg-today-line');t.style.left=(today()-this.range.start+.5)*this.ppd+'px';lane.append(t)}
      if(d._scheduled){
        const x=((d._phase?d._start:d._end)-this.range.start+.5)*this.ppd,w=d._phase?(d._end-d._start)*this.ppd:0;
        if(x+w>=0&&x<=width){const bar=node('button',d._phase?'mg-bar':'mg-diamond');bar.type='button';bar.dataset.planId=d.id;bar.title=d.title+' · '+(d._phase?key(d._start)+' → ':'')+key(d._end)+' · '+STATUS[d._status].label+(d._progress===null?'':' · '+d._progress+'%');bar.setAttribute('aria-label',bar.title);bar.style.left=Math.max(0,x)+'px';
          if(d._phase){bar.style.width=Math.max(6,Math.min(width,x+w)-Math.max(0,x))+'px';const fill=node('span','mg-bar-progress');fill.style.width=(d._progress??0)+'%';bar.append(fill);if(w>62)bar.append(node('span','mg-bar-copy',d._progress===null?STATUS[d._status].label:d._progress+'%'));bar.append(node('i','mg-bar-end'))}else bar.append(node('i',''));
          bar.onclick=()=>this.open(d.id);lane.append(bar);
          if(!d._phase||w<115){const date=node('span','mg-lane-date',short(d._end));date.style.left=Math.min(width-48,Math.max(0,x+w+15))+'px';lane.append(date)}
        }
      }else{const b=node('button','mg-pending',d._invalid?'日期待修正':d._start!==null?'缺少截止日期':'待排期');b.type='button';b.onclick=()=>this.open(d.id);lane.append(b)}
      row.append(lane);table.append(row);
    }
    scrollToDay(d){if(this.scroll)this.scroll.scrollLeft=Math.max(0,(d-this.range.start)*this.ppd-(this.scroll.clientWidth-this.labelWidth)/2)}
    async open(id){
      if(!await this.guard()||this.destroyed)return;const doc=this.docs.find(d=>d.id===id);if(!doc)return;this.selected=id;this.form=null;this.layout.querySelector('.mg-detail')?.remove();this.layout.classList.add('has-detail');
      const aside=node('aside','mg-detail');aside.setAttribute('aria-label','里程碑计划详情');const head=node('div','mg-detail-head'),close=node('button','ghost-btn','×');close.type='button';close.setAttribute('aria-label','关闭里程碑详情');close.onclick=async()=>{if(!await this.guard()||this.destroyed)return;this.selected=null;this.form=null;aside.remove();this.layout.classList.remove('has-detail');this.draw()};head.append(node('strong','','计划详情'),close);aside.append(head,node('h3','',doc.title));
      const associations=node('p','mg-detail-project',projects(doc).join(' · ')||'未关联项目');aside.append(associations);
      const form=node('form','mg-detail-form');form.onsubmit=e=>{e.preventDefault();this.save()};
      const field=(label,name,type,value)=>{const l=node('label','');l.append(node('span','',label));const input=node('input','');input.type=type;input.name=name;input.value=value??'';l.append(input);form.append(l);return input};
      const start=field('开始日期（可留空）','start_date','date',day(doc.start_date)!==null?doc.start_date:''),due=field('截止日期','due','date',day(doc.due)!==null?doc.due:'');start.onchange=()=>{due.min=start.value};due.min=start.value;
      const progress=field('完成进度 %（留空表示未设置）','progress','number',doc.progress);progress.min=0;progress.max=100;progress.step=.1;
      const label=node('label','');label.append(node('span','','状态'));const select=node('select','');select.name='status';for(const s of [...new Set(['计划','进行中','受阻','完成',doc.status].filter(Boolean))]){const o=node('option','',s);o.value=s;select.append(o)}select.value=doc.status||'计划';label.append(select);form.append(label);
      form.append(node('p','mg-detail-hint','开始至截止为阶段计划；只填截止为里程碑节点。完成状态按 100% 显示，不会自动推算进度。'));
      this.error=node('div','mg-form-message');this.error.setAttribute('role','status');form.append(this.error);const save=node('button','primary-btn','保存计划');save.type='submit';form.append(save);const edit=node('button','secondary-btn','打开里程碑文档 ↗');edit.type='button';edit.onclick=async()=>{if(await this.guard()&&!this.destroyed)this.options.onOpen?.(id)};form.append(edit);
      aside.append(form);this.form=form;this.baseDoc=doc;this.baseline=JSON.stringify(this.payload());this.layout.append(aside);this.draw();
      if(doc._invalid)this.error.textContent='原日期无效，请修正后保存。';
      close.focus({preventScroll:true});
    }
    payload(){if(!this.form)return {};const data=new FormData(this.form);return {start_date:data.get('start_date')||'',due:data.get('due')||'',progress:data.get('progress')===''?null:Number(data.get('progress')),status:data.get('status')}}
    showConflict(current,local){
      const base=JSON.parse(this.baseline),labels={start_date:'开始日期',due:'截止日期',progress:'完成进度',status:'状态'};
      this.error.replaceChildren(node('strong','','保存冲突：其他客户端已更新此条目。您的输入已保留。'));
      const list=node('ul','');
      for(const [field,label] of Object.entries(labels))list.append(node('li','',label+'：本地 '+(local[field]??'未设置')+'；当前 '+(current[field]??'未设置')));
      this.error.append(list);
      const merge=node('button','secondary-btn','载入当前值并合并我的修改');merge.type='button';
      merge.onclick=()=>{
        const next={...current};for(const field of Object.keys(labels))if(local[field]!==base[field])next[field]=local[field];
        this.baseDoc=current;this.docs=this.docs.map(d=>d.id===current.id?normalize(current):d);this.options.onUpdate?.(current);this.baseline=JSON.stringify({start_date:current.start_date||'',due:current.due||'',progress:current.progress??null,status:current.status||'计划'});
        for(const field of Object.keys(labels))this.form.elements[field].value=next[field]??'';
        this.form.elements.due.min=this.form.elements.start_date.value;
        this.error.textContent='已载入当前值并合并本地修改，请核对后再次保存。';
      };
      this.error.append(merge);
    }
    async save(){
      if(this.saving)return this.saving;if(!this.form?.reportValidity())return false;
      const payload=this.payload();if(payload.start_date&&payload.due&&payload.start_date>payload.due){this.error.textContent='截止日期不能早于开始日期';return false}
      const base=JSON.parse(this.baseline),changes=Object.fromEntries(Object.entries(payload).filter(([field,value])=>value!==base[field]));
      if(!Object.keys(changes).length){this.error.textContent='没有需要保存的修改';return true}
      const id=this.selected,form=this.form,error=this.error;form.querySelectorAll('button,input,select').forEach(b=>b.disabled=true);error.textContent='正在保存…';
      this.saving=(async()=>{try{const updated=await api('/api/docs/'+encodeURIComponent(id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...changes,...(this.baseDoc.revision?{expected_revision:this.baseDoc.revision}:{})})});if(this.destroyed)return true;this.docs=this.docs.map(d=>d.id===id?normalize({...d,...updated}):d);this.baseDoc=updated;const saved={start_date:updated.start_date||'',due:updated.due||'',progress:updated.progress??null,status:updated.status||'计划'};for(const field of Object.keys(saved))form.elements[field].value=saved[field]??'';form.elements.due.min=saved.start_date;this.baseline=JSON.stringify(saved);error.textContent='计划已保存';this.options.onUpdate?.(updated);this.draw();return true}catch(e){if(!this.destroyed){if(e.status===409&&e.current)this.showConflict(e.current,payload);else error.textContent='保存失败：'+e.message}return false}finally{form.querySelectorAll('button,input,select').forEach(b=>b.disabled=false);this.saving=null}})();
      return this.saving;
    }
  }
  window.ERWMilestoneGantt={mount(root,options){this.destroy();instance=new Gantt(root,options||{});return instance},destroy(){instance?.destroy();instance=null},dirty:()=>instance?.dirty()||false,guard:()=>instance?.guard()??Promise.resolve(true)};
})();
