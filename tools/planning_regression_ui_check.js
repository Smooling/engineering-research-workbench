/* Only invoked against the disposable service in test_planning_regressions.py. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');

(async()=>{
  const [base,id,draftId,sessionId]=process.argv.slice(2);assert(sessionId,'A disposable planning fixture is required');
  const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:2550,height:1233}});
    const other=await browser.newPage({viewport:{width:2550,height:1233}});
    for(const p of [page,other])await p.route('**/api/weather**',route=>route.fulfill({json:{enabled:false}}));
    const read=async()=>{const response=await fetch(base+'/api/docs/'+id);assert.equal(response.status,200);return response.json()};
    const open=async p=>{
      await p.goto(base+'/#milestones');await p.locator('[data-ms-view="gantt"]').click();
      await p.locator('.mg-row').nth(54).waitFor();
      await p.locator(`[data-milestone-id="${id}"] .mg-row-label`).click();
    };
    await open(page);await open(other);
    assert.equal(await page.locator('.mg-row').count(),55,'Gantt keeps documents beyond page one');
    assert.equal(await page.locator('.perf-doc-pager').count(),0,'complete Gantt does not expose document pagination');
    await page.locator('.mg-filter').selectOption('done');
    assert.equal(await page.locator('.mg-row').count(),27,'completed aliases share the completed filter');
    assert.equal(await page.locator('.mg-row.is-late').count(),0,'completed aliases are never overdue');
    await page.locator('.mg-filter').selectOption('');
    await other.locator('[name="due"]').fill('2026-11-29');
    await other.locator('.mg-detail-form button[type=submit]').click();
    await other.waitForFunction(()=>document.querySelector('.mg-form-message').textContent==='计划已保存');
    await page.locator('[name="progress"]').fill('64.5');
    assert.equal(await page.evaluate(()=>window.ERWSyncUI.refresh()),false,'sync refresh preserves a dirty old form');
    assert.equal(await page.locator('[name="progress"]').inputValue(),'64.5');
    const requestPromise=page.waitForRequest(r=>r.method()==='POST'&&new URL(r.url()).pathname==='/api/docs/'+id);
    await page.locator('.mg-detail-form button[type=submit]').click();
    const sent=(await requestPromise).postDataJSON();
    assert.deepEqual(Object.keys(sent).sort(),['expected_revision','progress'],'only changed fields are submitted');
    await page.getByText('保存冲突：其他客户端已更新此条目。您的输入已保留。',{exact:true}).waitFor();
    assert.equal(await page.locator('[name="progress"]').inputValue(),'64.5');
    assert.match(await page.locator('.mg-form-message').innerText(),/当前 2026-11-29/);
    assert.equal((await read()).progress,35,'rejected stale save has no effects');
    await page.getByRole('button',{name:'载入当前值并合并我的修改',exact:true}).click();
    assert.equal(await page.locator('[name="due"]').inputValue(),'2026-11-29');
    assert.equal(await page.locator('[name="progress"]').inputValue(),'64.5');
    await page.locator('.mg-detail-form button[type=submit]').click();
    await page.waitForFunction(()=>document.querySelector('.mg-form-message').textContent==='计划已保存');
    let saved=await read();assert.equal(saved.due,'2026-11-29');assert.equal(saved.progress,64.5);assert.equal(saved.body.trim(),'PLAN-BODY-42');
    assert.equal(await page.evaluate(()=>window.ERWMilestoneGantt.dirty()),false,'successful save resets the form baseline');
    await other.locator('[name="due"]').fill('2026-11-30');
    await other.locator('.mg-detail-form button[type=submit]').click();
    await other.getByText('保存冲突：其他客户端已更新此条目。您的输入已保留。',{exact:true}).waitFor();
    await other.getByRole('button',{name:'载入当前值并合并我的修改',exact:true}).click();
    assert.equal(await other.locator('[name="progress"]').inputValue(),'64.5');
    await other.locator('.mg-detail-form button[type=submit]').click();
    await other.waitForFunction(()=>document.querySelector('.mg-form-message').textContent==='计划已保存');
    saved=await read();assert.equal(saved.due,'2026-11-30');assert.equal(saved.progress,64.5);
    // Keep edits typed while a document save is in flight, using its new revision.
    await other.locator('.mg-detail-form .secondary-btn').click();await other.locator('#f-title').waitFor();
    await other.locator('#meta-toggle').click();await other.locator('#f-progress').fill('70');
    let release,committed,holdOnce=true;
    const hold=new Promise(resolve=>{release=resolve}),commit=new Promise(resolve=>{committed=resolve});
    await other.route('**/api/docs/'+id,async route=>{
      if(route.request().method()!=='POST'||!holdOnce)return route.continue();
      holdOnce=false;const response=await route.fetch();committed();await hold;await route.fulfill({response});
    });
    await other.locator('#doc-save').click();await commit;
    await other.locator('#f-progress').fill('71');release();
    await other.waitForFunction(()=>!document.querySelector('#doc-save').disabled);
    await other.locator('#doc-save').click();
    await other.waitForFunction(()=>!document.querySelector('#doc-save').disabled);
    saved=await read();assert.equal(saved.progress,71);assert.equal(saved.due,'2026-11-30');assert.equal(saved.body.trim(),'PLAN-BODY-42');
    await page.locator('[data-route="agent"]').click();await page.locator('#agent-input').waitFor();
    await page.locator(`[data-agent-session="${sessionId}"]`).click();
    await page.locator(`[data-draft-preview="${draftId}"]`).click();
    assert.match(await page.locator('.agent-draft-preview').innerText(),/完成进度 %：35 → 64.5/);
    const confirmResponse=page.waitForResponse(r=>new URL(r.url()).pathname===`/api/agent/drafts/${draftId}/confirm`);
    await page.locator(`[data-draft-confirm="${draftId}"]`).click();
    const rejected=await (await confirmResponse).json();assert.equal(rejected.status,'failed');assert.equal(rejected.result.conflict,true);
    assert.equal((await read()).revision,saved.revision,'stale Agent approval never overwrites manual changes');
    console.log('PASS: real 2550px two-window conflict/merge, partial payloads, preserved body/input and in-flight edits, shared completion aliases, full Gantt without pager, field-diff draft preview and stale approval.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
