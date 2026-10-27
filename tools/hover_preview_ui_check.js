/* Invoked only by test_hover_previews.py against its disposable real server. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');

(async()=>{
  const base=process.argv[2];assert(base,'A disposable test server URL is required');
  const create=async data=>{const response=await fetch(base+'/api/docs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert.equal(response.status,201);return response.json()};
  const longText='用于验证长正文在悬停卡片中最多显示五行，超出部分应被截断。'.repeat(30);
  const target=await create({kind:'note',title:'预览目标 <安全>',projects:['项目甲','项目乙'],tags:['算法','<b>纯文本标签</b>'],body:'# 目标\n\n这是正文开头，**强调内容**。[外链](https://example.invalid)\n\n## 实验结果\n\n这是对应章节的实验结论。\n\n## 其他章节\n\n不应显示在章节预览中。\n\n'+longText});
  const empty=await create({kind:'note',title:'空白条目',body:''});
  const source=await create({kind:'note',title:'悬停功能入口',body:`[[${target.id}|目标别名]]\n\n[[${target.id}#实验结果|章节别名]]\n\n[[${target.id}#不存在的章节|不存在的章节]]\n\n[[不存在的悬停目标]]\n\n[本地 Markdown](/workspace/${target.id}.md#实验结果)\n\n[外部链接](https://example.invalid)`});
  const paper=await create({kind:'literature',title:'文献悬停样例',projects:['项目甲'],tags:['文献标签'],body:'文献阅读笔记开头。'});
  const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/weather**',route=>route.fulfill({json:{enabled:false}}));
    await page.goto(base+'/#notes');
    await page.locator(`[data-doc-id="${empty.id}"]`).click();
    await page.waitForFunction(title=>document.querySelector('#f-title')?.value===title&&document.querySelector('#md-preview')?.dataset.referencePreviewBound==='true',empty.title);
    const tooltip=page.locator('#document-hover-preview');
    const hidden=()=>tooltip.waitFor({state:'detached'});
    const dismiss=async()=>{await page.mouse.move(2,2);await page.locator('#doc-search').focus();await page.keyboard.press('Escape');await hidden()};
    const text=()=>tooltip.innerText();
    const waitText=async value=>page.waitForFunction(value=>document.querySelector('#document-hover-preview')?.textContent.includes(value),value);
    const inBounds=async()=>{const rect=await tooltip.boundingBox(),viewport=page.viewportSize();assert(rect.x>=0&&rect.y>=0);assert(rect.x+rect.width<=viewport.width+1);assert(rect.y+rect.height<=viewport.height+1)};
    const noPaneTips=async()=>assert.deepEqual(await page.locator('[data-wheel-zoom-ready]').evaluateAll(elements=>elements.filter(el=>el.getAttribute('title')).map(el=>el.className||el.id)),[],'reading surfaces must not display native zoom tooltips');
    const nativeTitle=locator=>locator.evaluate(element=>{for(let node=element;node;node=node.parentElement)if(node.hasAttribute('title'))return node.getAttribute('title');return null});
    const compactExcerpt=async()=>{
      assert.equal(await tooltip.locator('.document-hover-excerpt>strong,.document-hover-hint').count(),0,'redundant body labels and action hints are removed');
      const metrics=await tooltip.locator('.document-hover-excerpt p').evaluate(element=>({height:element.clientHeight,lineHeight:parseFloat(getComputedStyle(element).lineHeight),fullHeight:element.scrollHeight,overflow:getComputedStyle(element).overflowY}));
      assert(metrics.height<=metrics.lineHeight*5+1,'body must occupy at most five lines');
      assert(metrics.fullHeight>metrics.height,'long body is visibly truncated');assert.equal(metrics.overflow,'hidden');
    };
    await dismiss();let requests=0;
    page.on('request',request=>{if(request.url().includes('/api/docs/resolve?'))requests++});
    const row=page.locator(`[data-doc-id="${target.id}"]`);
    await row.waitFor();await row.hover();await page.waitForTimeout(100);await page.mouse.move(2,2);await page.waitForTimeout(650);
    assert.equal(await tooltip.count(),0,'fast pointer passes must not open a tooltip');
    assert.equal(requests,0,'fast pointer passes must not fetch content');
    await row.hover();await waitText('这是正文开头');
    await noPaneTips();assert.equal(await nativeTitle(row),'');
    await compactExcerpt();
    const info=await text();for(const expected of [target.title,'所属项目','项目甲、项目乙','算法','<b>纯文本标签</b>','更新时间',target.updated.replace('T',' '),'强调内容'])assert(info.includes(expected),expected);
    assert.equal(await tooltip.locator('b,script,img,a').count(),0,'metadata and excerpts are safe text');
    assert(!info.includes('**'),'preview removes Markdown markup');await inBounds();
    const cachedRequests=requests;await tooltip.hover();await page.waitForTimeout(250);assert.equal(await tooltip.count(),1,'pointer can move into the tooltip');
    await dismiss();await row.hover();await waitText('这是正文开头');assert.equal(requests,cachedRequests,'repeat hovers reuse cached document');
    await dismiss();await row.focus();await waitText('这是正文开头');assert.equal(await row.getAttribute('aria-describedby'),'document-hover-preview');
    await page.keyboard.press('Escape');await hidden();assert.equal(await row.getAttribute('aria-describedby'),null);
    await page.locator(`[data-doc-id="${empty.id}"]`).hover();await waitText('暂无正文');assert((await text()).includes('未关联项目'));assert((await text()).includes('暂无标签'));
    await dismiss();await page.locator(`[data-doc-id="${source.id}"]`).click();
    const first=page.locator('#md-preview a').filter({hasText:'目标别名'}),section=page.locator('#md-preview a').filter({hasText:'章节别名'});
    await noPaneTips();
    // Removing a link title exposes the ancestor title; an empty title blocks it.
    await page.locator('#editor-pane').evaluate(element=>element.title='不应继承到悬停链接的整栏提示');
    await first.hover();await waitText('这是正文开头');assert((await text()).includes('链接预览'));
    assert.equal(await nativeTitle(first),'','hover masks inherited native tooltips');assert.equal(await tooltip.getAttribute('title'),'');
    await page.evaluate(()=>window.ERWDocReferences.bindPreview(document.querySelector('#md-preview')));
    await page.waitForFunction(()=>document.querySelector('#md-preview a')?.dataset.referenceState==='valid');
    assert.equal(await nativeTitle(first),'','reference revalidation must not reintroduce a native tooltip');
    await dismiss();assert.match(await first.getAttribute('title'),/悬停速览/,'latest link help is restored after hover');
    await page.locator('#editor-pane').evaluate(element=>element.removeAttribute('title'));
    await first.hover();await waitText('这是正文开头');
    assert.equal(await page.locator('.document-reference-preview').count(),0,'hover does not open the click preview');
    assert.equal(await page.locator('#f-title').inputValue(),source.title,'hover keeps the source document selected');
    await section.hover();await waitText('这是对应章节的实验结论');assert(!(await text()).includes('这是正文开头'));assert(!(await text()).includes('不应显示在章节预览中'));
    const screenshots=process.env.ERW_HOVER_SCREENSHOTS;
    if(screenshots){fs.mkdirSync(screenshots,{recursive:true});await page.evaluate(()=>document.documentElement.dataset.theme='light');await page.screenshot({path:path.join(screenshots,'link-hover-light.png')})}
    await page.locator('#md-preview a').filter({hasText:'不存在的章节'}).hover();await waitText('这是正文开头');assert.match(await tooltip.locator('.document-hover-excerpt').getAttribute('aria-label'),/未找到对应章节/);
    await page.locator('#md-preview a').filter({hasText:'本地 Markdown'}).hover();await waitText('这是对应章节的实验结论');
    await page.locator('#md-preview a').filter({hasText:'外部链接'}).hover();await hidden();await page.waitForTimeout(500);assert.equal(await tooltip.count(),0);
    await page.locator('#md-preview a').filter({hasText:'不存在的悬停目标'}).hover();await waitText('条目不可用');
    await first.hover();await waitText('这是正文开头');await first.click();await hidden();await page.locator('.reference-preview-body').getByText('这是对应章节的实验结论。').waitFor();
    await noPaneTips();
    const referenceBody=page.locator('.reference-preview-body'),fontBefore=await referenceBody.evaluate(element=>parseFloat(getComputedStyle(element).fontSize));
    await referenceBody.hover();await page.keyboard.down('Control');await page.mouse.wheel(0,-100);await page.keyboard.up('Control');
    await page.waitForFunction(before=>parseFloat(getComputedStyle(document.querySelector('.reference-preview-body')).fontSize)>before,fontBefore);
    await page.locator('[data-reference-close]').click();
    // A delayed response for a previous row must never replace the current hover.
    await dismiss();
    let release;const gate=new Promise(resolve=>release=resolve);let intercepted;
    const started=new Promise(resolve=>intercepted=resolve);
    const delayed=async route=>{intercepted();await gate;await route.continue()};
    await page.route('**/api/docs/resolve?target='+target.id,delayed);
    await page.evaluate(()=>window.ERWDocReferences.invalidate());
    await row.hover();await started;await page.locator(`[data-doc-id="${empty.id}"]`).hover();await waitText('暂无正文');release();await page.waitForTimeout(350);assert((await text()).includes(empty.title));
    await page.unroute('**/api/docs/resolve?target='+target.id,delayed);
    await dismiss();
    // Successful edits invalidate the existing preview cache.
    await row.click();await page.locator('[data-edit-mode="edit"]').click();await page.locator('#md-input').fill('更新后的正文开头。\n\n'+longText);
    const saved=page.waitForResponse(response=>response.url()===base+'/api/docs/'+target.id&&response.request().method()==='POST');await page.keyboard.press('Control+s');await saved;
    await page.mouse.move(2,2);await page.locator(`[data-doc-id="${target.id}"]`).hover();await waitText('更新后的正文开头');
    await page.evaluate(()=>document.documentElement.dataset.theme='dark');await inBounds();await compactExcerpt();
    if(screenshots)await page.screenshot({path:path.join(screenshots,'entry-hover-dark.png')});
    await dismiss();await page.setViewportSize({width:600,height:650});await page.evaluate(()=>document.documentElement.style.zoom='0.85');
    await page.locator(`[data-doc-id="${target.id}"]`).hover();await waitText('更新后的正文开头');await inBounds();await compactExcerpt();
    if(screenshots)await page.screenshot({path:path.join(screenshots,'entry-hover-compact.png')});
    await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>document.documentElement.style.zoom='');
    await page.locator('[data-route="literature"]').click();await hidden();
    const paperRow=page.locator(`[data-hover-doc-id="${paper.id}"]`);await paperRow.hover();await waitText('文献阅读笔记开头');assert((await text()).includes('文献标签'));
    await noPaneTips();assert.equal(await nativeTitle(paperRow),'');
    await page.locator('[data-route="overview"]').click();await hidden();
    const recent=page.locator(`[data-open-doc="${target.id}"]`).first();await recent.waitFor();await page.waitForTimeout(750);await recent.hover();
    await waitText('更新后的正文开头');
    await page.keyboard.press('Control+k');await hidden();await page.locator('#global-search-input').fill('预览目标');
    await page.locator(`.global-search-row[data-hover-doc-id="${target.id}"]`).hover();await waitText('更新后的正文开头');await page.locator('#modal-close').click();await hidden();
    // List filtering removes triggers and cleans up the floating element.
    await page.locator('[data-route="notes"]').click();await page.locator(`[data-doc-id="${target.id}"]`).hover();await waitText('更新后的正文开头');
    await page.evaluate(()=>{const input=document.querySelector('#doc-search');input.value='无匹配条目';input.dispatchEvent(new Event('input',{bubbles:true}))});await hidden();
    assert.deepEqual(errors,[],'hover interactions must not cause uncaught browser errors');
    console.log('PASS: real UI hover delay/cache, metadata, chapters, races, saved edits, keyboard, list/search previews, themes, viewport bounds, native tooltip suppression and retained Ctrl+wheel zoom.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
