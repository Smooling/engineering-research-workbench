/* FR-09: settings rebuild with a real backend, PDF.js and preview images. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const [base,docId,initialId,annId,historicalId,historicalAnnId]=process.argv.slice(2);
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];
  page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/weather**',route=>route.fulfill({json:{enabled:false}}));
  const open=async(id,annotationId)=>{
   await page.locator('[data-paper="'+id+'"]').click();
   await page.locator('#lit-pages canvas').first().waitFor();
   if(await page.locator('#lit-toggle-side').getAttribute('aria-expanded')!=='true')await page.locator('#lit-toggle-side').click();
   await page.locator('[data-tab="annotations"]').click();
   await page.locator('[data-open-ann="'+annotationId+'"]').waitFor();
   await page.waitForFunction(()=>[...document.querySelectorAll('.lit-ann-preview')].some(image=>image.complete&&image.naturalWidth>0));
   assert.match(await page.locator('#lit-side-body').innerText(),/必须保留的截图批注/);
  };
  await page.goto(base+'/#literature');await open(initialId,annId);
  const originalImage=await page.locator('.lit-ann-preview').first().getAttribute('src');
  await page.locator('#sidebar-nav [data-route="settings"]').click();
  await page.locator('[data-set-tab="literature"]').click();await page.locator('#lit-pdf-rebuild').click();
  const rebuilt=page.waitForResponse(response=>response.url()===base+'/api/literature/rebuild'&&response.request().method()==='POST');
  await page.locator('[data-dialog-result="confirm"]').click();assert.equal((await rebuilt).status(),200);
  const current=await (await fetch(base+'/api/literature/document/'+docId)).json();
  assert.equal(current.id,initialId,'registration retains the reader identity');
  await page.goto(base+'/#literature');await open(current.id,annId);
  assert.equal(await page.locator('.lit-ann-preview').first().getAttribute('src'),originalImage,'preview URL survives registration');
  await page.reload();await open(current.id,annId);
  await page.locator('[data-open-ann="'+annId+'"]').click();await page.locator('#ann-to-note').click();
  await page.locator('#lit-note').waitFor();
  await page.waitForFunction(()=>document.querySelector('#lit-note')?.value.includes('![批注'));
  assert.match(await page.locator('#lit-note').inputValue(),/原阅读笔记/);
  await page.locator('#lit-note-save').click();
  await page.waitForFunction(()=>!window.ERWLiterature.dirty());
  const note=await (await fetch(base+'/api/literature/'+current.id+'/note')).json();
  const image=note.content.match(/!\[[^\]]*\]\(([^)]+)\)/);assert(image,'copied preview is referenced by the saved note');
  const copied=await fetch(base+'/workspace-file/'+image[1]);assert.equal(copied.status,200);
  assert.deepEqual(Buffer.from(await copied.arrayBuffer()),Buffer.from(await (await fetch(base+originalImage)).arrayBuffer()));
  await open(historicalId,historicalAnnId);
  await page.locator('[data-open-ann="'+historicalAnnId+'"]').click();
  await page.locator('#ann-comment').fill('历史批注恢复后仍可保存');await page.locator('#ann-comment-save').click();
  await page.locator('[data-open-ann="'+historicalAnnId+'"]').waitFor();
  await page.reload();
  await page.locator('[data-paper="'+historicalId+'"]').click();await page.locator('#lit-pages canvas').first().waitFor();
  if(await page.locator('#lit-toggle-side').getAttribute('aria-expanded')!=='true')await page.locator('#lit-toggle-side').click();
  await page.locator('[data-tab="annotations"]').click();
  await page.locator('[data-open-ann="'+historicalAnnId+'"]').waitFor();
  assert.match(await page.locator('#lit-side-body').innerText(),/历史批注恢复后仍可保存/);
  await page.waitForFunction(()=>[...document.querySelectorAll('.lit-ann-preview')].some(image=>image.complete&&image.naturalWidth>0));
  assert.deepEqual(errors,[],'no uncaught browser errors');
  console.log('PASS: settings rebuild and refresh retain annotations, IDs and preview images; screenshots copy into saved notes; historical UUID annotations recover and remain editable.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
