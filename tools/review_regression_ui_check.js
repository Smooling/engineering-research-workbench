/* Real browser + backend regressions for FR-03. All data is disposable. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const [base,paperId,otherId,first,second]=process.argv.slice(2);
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1600,height:1000}});
  await context.route('**/api/weather**',route=>route.fulfill({json:{enabled:false}}));
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.setDefaultTimeout(12000);
  const read=async()=>await (await fetch(base+'/api/literature/'+paperId+'/annotations')).json();
  const open=async id=>{await page.locator('[data-paper="'+id+'"]').click();await page.locator('[data-paper="'+id+'"].active').waitFor();await page.waitForFunction(()=>document.querySelector('#lit-page-label')?.textContent.includes(' / 4'));await page.locator('#lit-pages canvas').first().waitFor()};
  const edit=async id=>{await page.locator('[data-tab="annotations"]').click();await page.locator('[data-open-ann="'+id+'"]').click();await page.locator('#ann-comment').waitFor()};
  const text=async expected=>assert.equal(await page.locator('#ann-comment').inputValue(),expected);
  const dirty=async expected=>assert.equal(await page.evaluate(()=>window.ERWLiterature.dirty()),expected);
  await page.goto(base+'/#literature');
  await open(paperId);
  if(!await page.locator('#li-title').isVisible())await page.locator('#lit-toggle-side').click();
  await edit(first);await page.locator('#ann-comment').fill('first unsaved draft');await dirty(true);
  assert.equal(await page.evaluate(()=>!window.dispatchEvent(new Event('beforeunload',{cancelable:true}))),true,'window close protection includes annotations');
  await page.locator('[data-tab="info"]').click();await page.locator('[data-tab="notes"]').click();await page.locator('#lit-note').waitFor();
  await edit(first);await text('first unsaved draft');
  await page.locator('[data-open-ann="'+second+'"]').click();await page.locator('#ann-comment').fill('second unsaved draft');
  await page.locator('#ann-editor-close').click();await edit(first);await text('first unsaved draft');
  await page.locator('[data-paper="'+otherId+'"]').click();await page.locator('[data-dialog-result="cancel"]').click();
  await text('first unsaved draft');await dirty(true);
  assert(await page.locator('[data-paper="'+paperId+'"].active').isVisible());
  await page.locator('[data-tab="info"]').click();
  await page.locator('[data-paper="'+otherId+'"]').click();await page.locator('[data-dialog-result="save"]').click();
  await page.locator('[data-paper="'+otherId+'"].active').waitFor();await dirty(false);
  let saved=await read();assert.equal(saved.find(a=>a.id===first).comment,'first unsaved draft');assert.equal(saved.find(a=>a.id===second).comment,'second unsaved draft');

  await open(paperId);await edit(first);await page.locator('#ann-comment').fill('retained after failed save');
  const annotationUrl=base+'/api/literature/'+paperId+'/annotations';
  await page.route(annotationUrl,route=>route.request().method()==='POST'?route.fulfill({status:500,json:{message:'injected save failure'}}):route.continue());
  await page.locator('#ann-comment-save').click();await page.locator('#toast-stack').filter({hasText:'injected save failure'}).waitFor();
  await text('retained after failed save');await dirty(true);
  await page.locator('[data-paper="'+otherId+'"]').click();await page.locator('[data-dialog-result="save"]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-dialog-result="save"]'));
  await text('retained after failed save');await dirty(true);
  await page.unroute(annotationUrl);
  await page.locator('#ann-comment').press('Control+s');await page.locator('[data-open-ann="'+first+'"]').waitFor();await dirty(false);
  saved=await read();assert.equal(saved.find(a=>a.id===first).comment,'retained after failed save');
  await edit(first);await page.locator('#ann-comment').fill('discard this draft');
  await page.locator('[data-tab="info"]').click();await page.locator('[data-paper="'+otherId+'"]').click();await page.locator('[data-dialog-result="discard"]').click();
  await page.locator('[data-paper="'+otherId+'"].active').waitFor();
  await open(paperId);await edit(first);await text('retained after failed save');await dirty(false);
  await page.reload();await page.locator('#lit-page-label').filter({hasText:' / 4'}).waitFor();
  if(!await page.locator('#li-title').isVisible())await page.locator('#lit-toggle-side').click();
  await edit(first);await text('retained after failed save');
  assert.deepEqual(errors,[],'no uncaught browser errors');
  console.log('PASS: annotation drafts survive tab/card changes and close; document switching saves all drafts, cancels or discards; failed saves preserve input; Ctrl+S, refresh and window-close protection work.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
