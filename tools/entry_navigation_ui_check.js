/* Only used against the disposable real service in test_entry_navigation.py. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
  const base=process.argv[2];assert(base,'A disposable test server is required');
  const request=async(url,data,method='POST')=>{const response=await fetch(base+url,{method,headers:{'Content-Type':'application/json'},...(data!==undefined?{body:JSON.stringify(data)}:{})});assert(response.ok,await response.clone().text());return response.json()};
  const target=await request('/api/docs',{kind:'idea',title:'用缓存减少重复计算',body:'可以尝试缓存中间结果，避免每次重新计算。',tags:['缓存','算法'],projects:['导航项目甲','导航项目乙']});
  const paragraphs=Array.from({length:100},(_,i)=>`第 ${i+1} 段。用于验证返回原条目后恢复正文阅读位置。`.repeat(4));
  const source=await request('/api/docs',{kind:'note',title:'导航源笔记',body:'# 导航源笔记\n\n'+paragraphs.slice(0,25).join('\n\n')+`\n\n[[${target.id}|关联灵感]]\n\n`+paragraphs.slice(25).join('\n\n')});
  const third=await request('/api/docs',{kind:'note',title:'导航另一篇笔记',body:'第三篇原始正文'});
  const paper=await request('/api/docs',{kind:'literature',title:'导航测试文献',body:`# 文献笔记\n\n[[${source.id}|返回源笔记]]\n\n`+paragraphs.join('\n\n')});
  const milestone=await request('/api/docs',{kind:'milestone',title:'专用类型节点',body:'验收条件'});
  const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];
    await page.addInitScript(()=>localStorage.setItem('editorMode','preview'));
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.route('**/api/weather**',route=>route.fulfill({json:{enabled:false}}));
    page.on('pageerror',error=>errors.push(error.message));
    const selected=async doc=>{await page.waitForFunction(id=>window.ERWCurrentDoc===id&&!document.querySelector('#main').hasAttribute('aria-busy'),doc.id);await page.waitForFunction(()=>!document.querySelector('#nav-back').disabled)};
    const open=async doc=>{assert.equal(await page.evaluate(doc=>window.ERWNav.open(doc.kind,doc.id),doc),true);await selected(doc)};
    const read=()=>request('/api/docs/'+target.id,undefined,'GET');
    const back=async doc=>{await page.locator('#nav-back').click();await selected(doc)};
    const forward=async doc=>{await page.locator('#nav-forward').click();await selected(doc)};
    const convert=async kind=>{await page.locator('#doc-entry-menu>summary').click();await page.locator(`[data-convert-kind="${kind}"]`).click()};
    await page.goto(base+'/#overview');await page.locator('.overview-dashboard').waitFor();
    assert(await page.locator('#nav-back').isDisabled());assert(await page.locator('#nav-forward').isDisabled());
    await open(source);
    const backBeforeRefresh=await page.locator('#nav-back').getAttribute('title');
    await page.evaluate(()=>window.ERWSyncUI.refresh());
    assert.equal(await page.locator('#nav-back').getAttribute('title'),backBeforeRefresh,'background refresh must not create navigation entries');
    const link=page.locator('#md-preview a').filter({hasText:'关联灵感'});await link.scrollIntoViewIfNeeded();await page.waitForTimeout(150);
    const origin=await page.evaluate(()=>window.ERWNavigation.capture());assert(Object.values(origin.scrolls).some(point=>point.top>100),'fixture must have a real reading position');
    await link.click({modifiers:['Control']});await selected(target);assert.equal(await page.locator('#f-title').inputValue(),target.title);
    await back(source);
    for(const [selector,point] of Object.entries(origin.scrolls))assert(Math.abs(await page.locator(selector).evaluate(el=>el.scrollTop)-point.top)<=2,selector+' reading position restored');
    await forward(target);await page.keyboard.press('Alt+ArrowLeft');await selected(source);
    await page.locator(`[data-doc-id="${third.id}"]`).click();await selected(third);assert(await page.locator('#nav-forward').isDisabled(),'new navigation truncates the forward branch');
    await page.locator('[data-edit-mode="edit"]').click();await page.locator('#md-input').fill('未保存的修改');
    await page.locator('#nav-back').click();await page.locator('[data-dialog-result="cancel"]').click();
    assert.equal(await page.locator('#f-title').inputValue(),third.title);assert.equal(await page.locator('#md-input').inputValue(),'未保存的修改');
    await page.locator('#nav-back').click();await page.locator('[data-dialog-result="discard"]').click();await selected(source);await forward(third);
    assert.equal((await page.locator('#md-input').inputValue()).trim(),third.body.trim(),'discarding does not create a saved copy');
    // Preserve list filters as well as the selected document.
    await page.locator('#doc-search').fill('导航');await page.waitForTimeout(350);
    await page.locator(`[data-doc-id="${source.id}"]`).click();await selected(source);await back(third);
    assert.equal(await page.locator('#doc-search').inputValue(),'导航');
    await open(target);await page.locator('[data-edit-mode="edit"]').click();
    const evolved=target.body+'\n\n## 实现步骤\n\n```python\ncache = {}\n```\n\n注意缓存失效。';await page.locator('#md-input').fill(evolved);
    await convert('note');await page.locator('[data-dialog-result="save"]').click();
    await page.waitForFunction(()=>location.hash==='#notes'&&document.querySelector('[data-convert-kind="note"]')?.disabled&&!document.querySelector('#main').hasAttribute('aria-busy'));
    let current=await read();assert.equal(current.kind,'note');assert.equal(current.id,target.id);assert.equal(current.created,target.created);assert.equal(current.title,target.title);
    assert.equal(current.body.trim(),evolved.trim());assert.deepEqual(current.tags,target.tags);assert.deepEqual(current.projects,target.projects);assert.equal(current.type_history.length,1);
    assert(current.path.startsWith('Knowledge/Notes/'));assert.equal(current.type_history[0].from,'idea');
    const graph=await request('/api/graph',undefined,'GET');assert.equal(graph.nodes.find(node=>node.id===target.id).kind,'note');
    assert(graph.edges.some(edge=>edge.source===source.id&&edge.target===target.id));
    await page.locator('#doc-entry-menu>summary').click();await page.locator('#doc-type-history').click();assert.match(await page.locator('#modal-body').innerText(),/灵感 → 笔记/);await page.locator('#type-history-close').click();
    await convert('summary');await page.waitForFunction(()=>location.hash==='#summaries'&&document.querySelector('#f-summary-type'));
    await page.waitForFunction(()=>!document.querySelector('#main').hasAttribute('aria-busy'));current=await read();assert.equal(current.kind,'summary');assert.equal(current.type_history.length,2);assert.equal(current.created,target.created);
    await convert('idea');await page.waitForFunction(()=>location.hash==='#ideas'&&document.querySelector('[data-convert-kind="idea"]')?.disabled&&!document.querySelector('#main').hasAttribute('aria-busy'));
    current=await read();assert.equal(current.type_history.length,3);assert.equal(current.body.trim(),evolved.trim());
    const screenshots=process.env.ERW_ENTRY_SCREENSHOTS;
    if(screenshots){fs.mkdirSync(screenshots,{recursive:true});await page.locator('#doc-entry-menu>summary').click();await page.screenshot({path:path.join(screenshots,'entry-type-menu.png')});await page.locator('#doc-entry-menu>summary').click()}
    await open(source);await page.locator('[data-edit-mode="preview"]').click();await link.scrollIntoViewIfNeeded();await link.click({modifiers:['Control']});await selected(target);
    assert.equal(await page.locator('#f-title').inputValue(),target.title,'original reference remains valid after roundtrip');
    await back(source);await forward(target);await back(source);
    // History entries resolve current kind and a missing destination leaves the source intact.
    current=await read();await request('/api/docs/'+target.id+'/convert-kind',{kind:'note',expected_revision:current.revision});await forward(target);
    assert.equal(await page.evaluate(()=>location.hash),'#notes');await back(source);
    await request('/api/docs/'+target.id,undefined,'DELETE');await page.locator('#nav-forward').click();await page.waitForFunction(()=>document.querySelector('#toast-stack').textContent.includes('无法前进'));
    assert.equal(await page.locator('#f-title').inputValue(),source.title);
    await open(milestone);assert.equal(await page.locator('#doc-entry-menu').count(),0,'special types do not offer conversion');
    await open(paper);assert.equal(await page.locator('#doc-entry-menu').count(),0);await page.locator('#lit-side [data-tab="notes"]').click();await page.locator('#lit-note').waitFor();
    await page.locator('#lit-note-mode').click();const litLink=page.locator('#lit-note-preview a');await litLink.click({modifiers:['Control']});await selected(source);await back(paper);
    assert(await page.locator('#lit-note-preview').isVisible(),'back restores the literature note and its preview mode');
    assert.deepEqual(errors,[],'no uncaught browser errors');
    console.log('PASS: conversion menu, stable references/graph/history, unsaved save/cancel/discard, back/forward/Alt arrows, reading position, filters, branching, converted/deleted targets, milestone and literature navigation.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
