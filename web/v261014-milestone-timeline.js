(() => {
  'use strict';

  const DAY = 86400000;
  const RANGE_KEY = 'milestoneTimelineRangeMonths';
  const SCALE_KEY = 'milestoneTimelineScale';
  const FILTER_KEY = 'milestoneTimelineStatus';
  const VALID_RANGES = [3, 6, 12];
  const STATUS = [
    { key: 'done', label: '已完成', raw: ['完成', '已完成'], icon: '✓' },
    { key: 'active', label: '进行中', raw: ['进行中'], icon: '●' },
    { key: 'planned', label: '计划中', raw: ['计划', '计划中', '未开始'], icon: '○' },
    { key: 'blocked', label: '受阻', raw: ['受阻', '阻塞'], icon: '!' }
  ];

  let current = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function localMidnight(value) {
    if (value instanceof Date) return new Date(value.getFullYear(), value.getMonth(), value.getDate());
    const m = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }

  function addDays(date, amount) {
    const d = new Date(date);
    d.setDate(d.getDate() + amount);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function dayDiff(a, b) {
    return Math.round((localMidnight(a).getTime() - localMidnight(b).getTime()) / DAY);
  }

  function dateKey(date) {
    const d = localMidnight(date);
    if (!d) return '';
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function shortDate(date) {
    const d = localMidnight(date);
    if (!d) return '—';
    return String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function longDate(date) {
    const d = localMidnight(date);
    if (!d) return '—';
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function monthLabel(date) {
    const d = localMidnight(date);
    return d.getFullYear() + '年' + (d.getMonth() + 1) + '月';
  }

  function monthKey(date) {
    const d = localMidnight(date);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0');
  }

  function drawerDateParts(date) {
    const d = localMidnight(date);
    return {
      year: String(d.getFullYear()),
      monthDay: String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
    };
  }

  function statusKey(raw) {
    const value = String(raw || '').trim();
    for (const item of STATUS) {
      if (item.raw.includes(value)) return item.key;
    }
    return 'planned';
  }

  function statusConfig(key) {
    return STATUS.find(x => x.key === key) || STATUS[2];
  }

  function normalizeDocs(docs) {
    return (Array.isArray(docs) ? docs : []).map(doc => {
      const due = localMidnight(doc.due);
      return Object.assign({}, doc, {
        _due: due,
        _statusKey: doc.status_class || statusKey(doc.status)
      });
    }).filter(doc => doc._due).sort((a, b) => {
      const dt = a._due - b._due;
      if (dt) return dt;
      return String(a.id || '').localeCompare(String(b.id || ''));
    });
  }

  function collisionComponents(groups, cardWidth, canvasWidth, gap) {
    const rows = groups.map(group => {
      const left = clamp(group.x - cardWidth / 2, 8, Math.max(8, canvasWidth - cardWidth - 8));
      return { group, left, right: left + cardWidth };
    }).sort((a, b) => a.left - b.left || a.group.x - b.group.x);

    const components = [];
    let currentPart = [];
    let currentRight = -Infinity;

    rows.forEach(row => {
      if (!currentPart.length || row.left < currentRight + gap) {
        currentPart.push(row.group);
        currentRight = Math.max(currentRight, row.right);
      } else {
        components.push(currentPart);
        currentPart = [row.group];
        currentRight = row.right;
      }
    });
    if (currentPart.length) components.push(currentPart);
    return components;
  }

  function groupByDate(docs, start, pxPerDay) {
    const map = new Map();
    docs.forEach(doc => {
      const key = dateKey(doc._due);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(doc);
    });
    return [...map.entries()].map(([key, items]) => ({
      key,
      date: items[0]._due,
      docs: items,
      x: dayDiff(items[0]._due, start) * pxPerDay
    })).sort((a, b) => a.date - b.date || a.key.localeCompare(b.key));
  }

  function flatten(groups) {
    return groups.flatMap(group => group.docs);
  }

  class MilestoneTimeline {
    constructor(root, options) {
      this.root = root;
      this.options = options || {};
      this.docs = normalizeDocs(this.options.docs || []);
      const storedRange = Number(localStorage.getItem(RANGE_KEY));
      this.rangeMonths = VALID_RANGES.includes(storedRange) ? storedRange : 6;
      const storedScale = localStorage.getItem(SCALE_KEY);
      this.scale = storedScale === 'week' ? 'week' : 'month';
      const storedFilter = localStorage.getItem(FILTER_KEY) || '';
      this.statusFilter = STATUS.some(x => x.key === storedFilter) ? storedFilter : '';
      this.today = localMidnight(new Date());
      this.resizeObserver = null;
      this.resizeTimer = 0;
      this.lastViewportWidth = 0;
      this.drawerItems = [];
      this.render(this.today.getTime());
    }

    destroy() {
      if (this.resizeObserver) this.resizeObserver.disconnect();
      if (this.resizeTimer) clearTimeout(this.resizeTimer);
      this.resizeObserver = null;
      this.root.replaceChildren();
    }

    range() {
      const days = Math.max(30, Math.round(this.rangeMonths * 30.4375));
      const start = addDays(this.today, -Math.floor(days / 2));
      const end = addDays(start, days);
      return { start, end, days };
    }

    pxPerDay() {
      return this.scale === 'week' ? 22 : 8;
    }

    docsInRange() {
      const { start, end } = this.range();
      return this.docs.filter(doc => doc._due >= start && doc._due <= end);
    }

    captureCenterTime() {
      if (!this.scroll || !this.inner || !this.inner.offsetWidth) return this.today.getTime();
      const ratio = clamp((this.scroll.scrollLeft + this.scroll.clientWidth / 2) / this.inner.offsetWidth, 0, 1);
      const { start, end } = this.range();
      return start.getTime() + ratio * (end.getTime() - start.getTime());
    }

    render(centerMs) {
      if (this.resizeObserver) this.resizeObserver.disconnect();
      this.root.replaceChildren();

      const page = el('div', 'milestone-density-timeline');
      const toolbar = this.buildToolbar();
      page.appendChild(toolbar);

      const layout = el('div', 'mdt-layout');
      const main = el('div', 'mdt-main');
      const body = el('div', 'mdt-body');
      const labels = el('div', 'mdt-status-column');
      const rulerSpacer = el('div', 'mdt-ruler-spacer', '状态');
      labels.appendChild(rulerSpacer);

      STATUS.forEach(cfg => {
        const row = el('div', 'mdt-status-label mdt-status-' + cfg.key);
        const ico = el('span', 'mdt-status-icon', cfg.icon);
        const copy = el('div', 'mdt-status-copy');
        copy.appendChild(el('strong', '', cfg.label));
        const count = this.docsInRange().filter(doc => doc._statusKey === cfg.key).length;
        copy.appendChild(el('span', '', count + ' 个里程碑'));
        row.appendChild(ico);
        row.appendChild(copy);
        labels.appendChild(row);
      });

      const scroll = el('div', 'mdt-scroll');
      const inner = el('div', 'mdt-inner');
      scroll.appendChild(inner);
      body.appendChild(labels);
      body.appendChild(scroll);
      main.appendChild(body);

      const drawer = el('aside', 'mdt-drawer');
      drawer.hidden = true;
      layout.appendChild(main);
      layout.appendChild(drawer);
      page.appendChild(layout);
      this.root.appendChild(page);

      this.page = page;
      this.layout = layout;
      this.scroll = scroll;
      this.inner = inner;
      this.drawer = drawer;
      this.lastViewportWidth = scroll.clientWidth;

      requestAnimationFrame(() => {
        if (!this.root.isConnected) return;
        this.layoutTimeline(centerMs || this.today.getTime());
        this.observeResize();
      });
    }

    buildToolbar() {
      const toolbar = el('div', 'mdt-toolbar');
      const titleWrap = el('div', 'mdt-title');
      titleWrap.appendChild(el('div', 'card-kicker', 'MILESTONE TIMELINE'));
      titleWrap.appendChild(el('h3', '', '里程碑时间线'));
      const { start, end } = this.range();
      titleWrap.appendChild(el('p', 'mdt-range-caption', longDate(start) + ' — ' + longDate(end)));
      toolbar.appendChild(titleWrap);

      const rangeDocs = this.docsInRange();
      const stats = el('div', 'mdt-stats');
      STATUS.forEach(cfg => {
        const count = rangeDocs.filter(doc => doc._statusKey === cfg.key).length;
        const btn = el('button', 'mdt-stat mdt-stat-' + cfg.key, '');
        btn.type = 'button';
        btn.dataset.status = cfg.key;
        btn.classList.toggle('active', this.statusFilter === cfg.key);
        const num = el('strong', '', count);
        const label = el('span', '', cfg.label);
        btn.appendChild(num);
        btn.appendChild(label);
        btn.addEventListener('click', () => {
          const center = this.captureCenterTime();
          this.statusFilter = this.statusFilter === cfg.key ? '' : cfg.key;
          localStorage.setItem(FILTER_KEY, this.statusFilter);
          this.render(center);
        });
        stats.appendChild(btn);
      });
      toolbar.appendChild(stats);

      const controls = el('div', 'mdt-controls');
      const rangeSelect = el('select', 'mini-select mdt-range-select');
      rangeSelect.setAttribute('aria-label', '时间范围');
      VALID_RANGES.forEach(months => {
        const option = el('option', '', months + ' 个月');
        option.value = String(months);
        option.selected = months === this.rangeMonths;
        rangeSelect.appendChild(option);
      });
      rangeSelect.addEventListener('change', () => {
        this.rangeMonths = Number(rangeSelect.value) || 6;
        localStorage.setItem(RANGE_KEY, String(this.rangeMonths));
        this.statusFilter = '';
        localStorage.setItem(FILTER_KEY, '');
        this.render(this.today.getTime());
      });
      controls.appendChild(rangeSelect);

      const scale = el('div', 'mdt-scale');
      [['month', '月'], ['week', '周']].forEach(pair => {
        const btn = el('button', '', pair[1]);
        btn.type = 'button';
        btn.classList.toggle('active', this.scale === pair[0]);
        btn.addEventListener('click', () => {
          if (this.scale === pair[0]) return;
          const center = this.captureCenterTime();
          this.scale = pair[0];
          localStorage.setItem(SCALE_KEY, this.scale);
          this.render(center);
        });
        scale.appendChild(btn);
      });
      controls.appendChild(scale);

      const todayBtn = el('button', 'secondary-btn mdt-today-btn', '今天');
      todayBtn.type = 'button';
      todayBtn.addEventListener('click', () => this.centerOn(this.today.getTime(), true));
      controls.appendChild(todayBtn);

      toolbar.appendChild(controls);
      return toolbar;
    }

    observeResize() {
      if (!('ResizeObserver' in window) || !this.scroll) return;
      if (this.resizeObserver) this.resizeObserver.disconnect();
      this.resizeObserver = new ResizeObserver(entries => {
        const width = entries[0] && entries[0].contentRect ? entries[0].contentRect.width : this.scroll.clientWidth;
        if (Math.abs(width - this.lastViewportWidth) < 8) return;
        this.lastViewportWidth = width;
        const center = this.captureCenterTime();
        clearTimeout(this.resizeTimer);
        this.resizeTimer = setTimeout(() => {
          if (this.root.isConnected) this.layoutTimeline(center);
        }, 100);
      });
      this.resizeObserver.observe(this.scroll);
    }

    contentWidth() {
      const { days } = this.range();
      const natural = days * this.pxPerDay();
      return Math.max(this.scroll ? this.scroll.clientWidth : 0, natural, 760);
    }

    xFor(date, width) {
      const { start, end } = this.range();
      const total = Math.max(1, end.getTime() - start.getTime());
      return clamp((localMidnight(date).getTime() - start.getTime()) / total * width, 0, width);
    }

    centerOn(timeMs, smooth) {
      if (!this.scroll || !this.inner) return;
      const { start, end } = this.range();
      const ratio = clamp((timeMs - start.getTime()) / Math.max(1, end.getTime() - start.getTime()), 0, 1);
      const left = ratio * this.inner.offsetWidth - this.scroll.clientWidth / 2;
      this.scroll.scrollTo({ left: Math.max(0, left), behavior: smooth ? 'smooth' : 'auto' });
    }

    layoutTimeline(centerMs) {
      if (!this.inner || !this.scroll) return;
      const width = this.contentWidth();
      this.inner.style.width = width + 'px';
      this.inner.replaceChildren();

      this.buildRuler(width);
      this.buildGrid(width);
      this.buildLanes(width);
      this.centerOn(centerMs || this.today.getTime(), false);
    }

    buildRuler(width) {
      const ruler = el('div', 'mdt-ruler');
      const { start, end } = this.range();

      let cursor = new Date(start.getFullYear(), start.getMonth(), 1);
      if (cursor < start) cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
      while (cursor <= end) {
        const x = this.xFor(cursor, width);
        const month = el('div', 'mdt-month-label', monthLabel(cursor));
        month.style.left = x + 'px';
        ruler.appendChild(month);
        cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
      }

      const minorStep = this.scale === 'week' ? 7 : 10;
      for (let d = addDays(start, minorStep); d < end; d = addDays(d, minorStep)) {
        const x = this.xFor(d, width);
        const tick = el('div', 'mdt-date-label', this.scale === 'week' ? shortDate(d) : ((d.getMonth() + 1) + '月' + d.getDate() + '日'));
        tick.style.left = x + 'px';
        ruler.appendChild(tick);
      }

      this.inner.appendChild(ruler);
    }

    buildGrid(width) {
      const grid = el('div', 'mdt-grid-layer');
      const { start, end } = this.range();

      let month = new Date(start.getFullYear(), start.getMonth(), 1);
      if (month < start) month = new Date(month.getFullYear(), month.getMonth() + 1, 1);
      while (month <= end) {
        const line = el('i', 'mdt-grid-line major');
        line.style.left = this.xFor(month, width) + 'px';
        grid.appendChild(line);
        month = new Date(month.getFullYear(), month.getMonth() + 1, 1);
      }

      const step = this.scale === 'week' ? 1 : 10;
      for (let d = addDays(start, step); d < end; d = addDays(d, step)) {
        const line = el('i', 'mdt-grid-line minor');
        line.style.left = this.xFor(d, width) + 'px';
        grid.appendChild(line);
      }

      if (this.today >= start && this.today <= end) {
        const todayLine = el('i', 'mdt-today-line');
        todayLine.style.left = this.xFor(this.today, width) + 'px';
        const tag = el('span', '', '今天');
        todayLine.appendChild(tag);
        grid.appendChild(todayLine);
      }

      this.inner.appendChild(grid);
    }

    buildLanes(width) {
      const laneWrap = el('div', 'mdt-lanes');
      const rangeDocs = this.docsInRange();
      STATUS.forEach(cfg => {
        const lane = el('section', 'mdt-lane mdt-lane-' + cfg.key);
        lane.dataset.status = cfg.key;
        if (this.statusFilter && this.statusFilter !== cfg.key) lane.classList.add('filtered-out');

        const docs = rangeDocs.filter(doc => doc._statusKey === cfg.key && (!this.statusFilter || this.statusFilter === cfg.key));
        const groups = groupByDate(docs, this.range().start, this.pxPerDay());
        groups.forEach(group => group.x = this.xFor(group.date, width));
        this.renderMarkers(lane, groups, cfg);
        this.renderCards(lane, groups, cfg, width);
        laneWrap.appendChild(lane);
      });
      this.inner.appendChild(laneWrap);
    }

    renderMarkers(lane, groups, cfg) {
      groups.forEach(group => {
        const marker = el('button', 'mdt-marker', '');
        marker.type = 'button';
        marker.style.left = group.x + 'px';
        marker.title = longDate(group.date) + ' · ' + group.docs.length + ' 项' + cfg.label;
        marker.setAttribute('aria-label', marker.title);
        const pin = el('span', 'mdt-pin-glyph', '📌');
        marker.appendChild(pin);
        if (group.docs.length > 1) marker.appendChild(el('span', 'mdt-marker-count', group.docs.length));
        marker.addEventListener('click', e => {
          e.stopPropagation();
          if (group.docs.length === 1 && this.options.onOpen) this.options.onOpen(group.docs[0].id);
          else this.openDrawer(group.docs, cfg.key, group.date, group.date);
        });
        lane.appendChild(marker);
      });
    }

    renderCards(lane, groups, cfg, width) {
      if (!groups.length) return;
      const minGap = 14;
      const { start: rangeStart, end: rangeEnd } = this.range();
      const items = [];

      const segmentForMonth = date => {
        const d = localMidnight(date);
        const monthStart = new Date(d.getFullYear(), d.getMonth(), 1);
        const monthEnd = new Date(d.getFullYear(), d.getMonth() + 1, 1);
        const clippedStart = monthStart < rangeStart ? rangeStart : monthStart;
        const clippedEnd = monthEnd > rangeEnd ? rangeEnd : monthEnd;
        const x1 = this.xFor(clippedStart, width);
        const x2 = this.xFor(clippedEnd, width);
        return {key:monthKey(d),label:monthLabel(d),start:clippedStart,end:clippedEnd,x1,x2,width:Math.max(1,x2-x1)};
      };

      const titleMetrics = (group, compact=false) => {
        const title=String(group.docs[0]?.title||'未命名里程碑');
        const units=[...title].reduce((n,ch)=>n+(/[\x00-\xff]/.test(ch)?.58:1),0);
        const oneLine=compact?16:18;
        const lines=units<=oneLine?1:2;
        const target=compact
          ? clamp(Math.round(56+Math.min(units,23)*2.55),86,116)
          : clamp(Math.round(60+Math.min(units,25)*2.95),92,136);
        return {width:target,lines};
      };

      const placeSingles = (monthGroups, segment, compact=false) => {
        if(!monthGroups.every(group=>group.docs.length===1))return null;
        const inset=8;
        const placed=monthGroups.map(group=>{
          const metrics=titleMetrics(group,compact);
          if(segment.width<metrics.width+inset*2)return null;
          const maxLeft=segment.x2-metrics.width-inset;
          return {
            group,
            width:metrics.width,
            lines:metrics.lines,
            left:clamp(group.x-metrics.width/2,segment.x1+inset,maxLeft)
          };
        });
        if(placed.some(x=>!x))return null;
        placed.sort((a,b)=>a.left-b.left||a.group.x-b.group.x);
        for(let i=1;i<placed.length;i++){
          if(placed[i].left<placed[i-1].left+placed[i-1].width+minGap)return null;
        }
        return placed;
      };

      const byMonth=new Map();
      groups.forEach(group=>{
        const key=monthKey(group.date);
        if(!byMonth.has(key))byMonth.set(key,[]);
        byMonth.get(key).push(group);
      });

      [...byMonth.values()].forEach(monthGroups=>{
        const segment=segmentForMonth(monthGroups[0].date);
        const comfortable=placeSingles(monthGroups,segment,false);
        if(comfortable){
          comfortable.forEach(row=>items.push({kind:'single',groups:[row.group],width:row.width,left:row.left,lines:row.lines,segment}));
          return;
        }
        const compact=placeSingles(monthGroups,segment,true);
        if(compact){
          compact.forEach(row=>items.push({kind:'single compact',groups:[row.group],width:row.width,left:row.left,lines:row.lines,segment}));
          return;
        }
        const clusterWidth=clamp(segment.width-20,92,132);
        items.push({
          kind:'month-cluster',
          groups:monthGroups,
          width:clusterWidth,
          left:clamp((segment.x1+segment.x2-clusterWidth)/2,segment.x1+8,Math.max(segment.x1+8,segment.x2-clusterWidth-8)),
          lines:1,
          segment
        });
      });

      items.forEach(item=>{
        const docs=flatten(item.groups);
        const start=item.groups[0].date;
        const end=item.groups[item.groups.length-1].date;
        const weightedX=item.groups.reduce((sum,group)=>sum+group.x*group.docs.length,0)/Math.max(1,docs.length);
        const x=item.kind==='month-cluster'?(item.segment.x1+item.segment.x2)/2:weightedX;

        const connector=el('i','mdt-card-connector');
        connector.style.left=x+'px';
        lane.appendChild(connector);

        const card=el('button','mdt-card '+item.kind,'');
        card.type='button';
        card.style.left=item.left+'px';
        card.style.width=item.width+'px';

        if(item.kind==='month-cluster'){
          card.appendChild(el('div','mdt-month-cluster-year',String(start.getFullYear())));
          const monthTitle=el('div','mdt-month-cluster-title');
          monthTitle.appendChild(el('strong','',(start.getMonth()+1)+'月'));
          monthTitle.appendChild(el('span','',docs.length+'项'));
          card.appendChild(monthTitle);
        }else{
          card.appendChild(el('div','mdt-card-date',shortDate(docs[0]._due)));
          card.appendChild(el('div','mdt-card-title',docs[0].title||'未命名里程碑'));
        }

        card.title=item.kind==='month-cluster'
          ? monthLabel(start)+' · '+docs.length+'项'
          : (docs[0].title||'未命名里程碑')+' · '+longDate(docs[0]._due);
        card.addEventListener('click',e=>{
          e.stopPropagation();
          if(item.kind!=='month-cluster'&&docs.length===1&&this.options.onOpen)this.options.onOpen(docs[0].id);
          else this.openDrawer(docs,cfg.key,item.kind==='month-cluster'?item.segment.start:start,item.kind==='month-cluster'?addDays(item.segment.end,-1):end);
        });
        lane.appendChild(card);
      });
    }

    openDrawer(items, status, start, end) {
      this.drawerItems = [...items].sort((a, b) => a._due - b._due || String(a.id || '').localeCompare(String(b.id || '')));
      this.layout.classList.add('drawer-open');
      this.drawer.hidden = false;
      this.drawer.replaceChildren();

      const head = el('div', 'mdt-drawer-head');
      const titleWrap = el('div', '');
      titleWrap.appendChild(el('div', 'card-kicker', 'MILESTONE DETAILS'));
      titleWrap.appendChild(el('h3', '', statusConfig(status).label + '里程碑（' + this.drawerItems.length + '项）'));
      const rangeText = longDate(start) === longDate(end) ? longDate(start) : longDate(start) + ' — ' + longDate(end);
      titleWrap.appendChild(el('p', '', rangeText));
      const close = el('button', 'ghost-btn', '×');
      close.type = 'button';
      close.setAttribute('aria-label', '关闭详情');
      close.addEventListener('click', () => this.closeDrawer());
      head.appendChild(titleWrap);
      head.appendChild(close);
      this.drawer.appendChild(head);

      const list = el('div', 'mdt-drawer-list');
      this.drawerItems.forEach(doc => {
        const row = el('button', 'mdt-drawer-item', '');
        row.type = 'button';
        const dateParts = drawerDateParts(doc._due);
        const date = el('div', 'mdt-drawer-date');
        date.appendChild(el('span', 'mdt-drawer-year', dateParts.year));
        date.appendChild(el('strong', 'mdt-drawer-monthday', dateParts.monthDay));
        const copy = el('div', 'mdt-drawer-copy');
        copy.appendChild(el('strong', '', doc.title || '未命名里程碑'));
        copy.appendChild(el('span', '', doc.excerpt || ((doc.projects || []).join(', ') || doc.project || '未归属项目')));
        const badge = el('span', 'badge', doc.status || statusConfig(doc._statusKey).label);
        row.appendChild(date);
        row.appendChild(copy);
        row.appendChild(badge);
        row.addEventListener('click', () => {
          if (this.options.onOpen) this.options.onOpen(doc.id);
        });
        list.appendChild(row);
      });
      this.drawer.appendChild(list);

      const foot = el('div', 'mdt-drawer-foot');
      const closeBottom = el('button', 'secondary-btn', '关闭');
      closeBottom.type = 'button';
      closeBottom.addEventListener('click', () => this.closeDrawer());
      foot.appendChild(closeBottom);
      this.drawer.appendChild(foot);

      requestAnimationFrame(() => {
        this.lastViewportWidth = this.scroll.clientWidth;
        const center = this.captureCenterTime();
        this.layoutTimeline(center);
      });
    }

    closeDrawer() {
      if (!this.drawer) return;
      const center = this.captureCenterTime();
      this.layout.classList.remove('drawer-open');
      this.drawer.hidden = true;
      this.drawer.replaceChildren();
      requestAnimationFrame(() => {
        this.lastViewportWidth = this.scroll.clientWidth;
        this.layoutTimeline(center);
      });
    }
  }

  function mount(root, options) {
    if (!root) return null;
    if (current) current.destroy();
    current = new MilestoneTimeline(root, options || {});
    return current;
  }

  function destroy() {
    if (current) current.destroy();
    current = null;
  }

  window.ERWMilestoneTimeline = { mount, destroy };
})();
