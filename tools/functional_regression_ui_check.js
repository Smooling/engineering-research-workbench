/* Invoked by test_functional_regressions.py against its disposable real server. */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');

(async()=>{
  const base=process.argv[2];assert(base,'A disposable test server URL is required');
  const browser=await chromium.launch({headless:true,channel:process.env.UI_BROWSER||'msedge'});
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1000}});
    // Keep all application/data requests real; weather is unrelated to this check.
    await page.route('**/api/weather**',route=>route.fulfill({json:{enabled:false}}));
    const responsePromise=page.waitForResponse(r=>r.url()===base+'/api/dashboard');
    await page.goto(base+'/#overview');
    const response=await responsePromise;assert.equal(response.status(),200);
    const dashboard=await response.json();
    assert.equal(dashboard.counts.milestone,14,'global count deduplicates shared milestones');
    await page.locator('.project-pulse-item').nth(3).waitFor();
    for(const record of dashboard.project_stats){
      const card=page.locator('.project-pulse-item').filter({has:page.locator('.project-pulse-name strong').getByText(record.name,{exact:true})});
      assert.equal(await card.count(),1);
      assert.match(await card.locator('.project-pulse-metrics').innerText(),new RegExp(record.open_milestones+'\\s+待完成节点'));
      assert.equal(await card.getByText(/^\d+ 里程碑$/).count(),0);
    }
    console.log('PASS: actual HTTP dashboard renders pending milestones for partial, shared, completed and empty projects.');
    const citations=['@article{metadata,title={中文研究}}','@article{current,title={Current}}'];
    const oldBody='```bibtex\n@article{stale,title={Old}}\n```';
    for(const [i,bibtex] of [...citations,''].entries()){
      const created=await fetch(base+'/api/docs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'literature',title:i===2?'已清空引用':'导出文献 '+i,bibtex,body:i?oldBody:'# 阅读笔记'})});
      assert.equal(created.status,201);
    }
    await page.locator('[data-route="literature"]').click();
    await page.locator('#lit-list .lit-item').nth(2).waitFor();
    const downloadPromise=page.waitForEvent('download');
    await page.locator('#lit-export').click();
    const download=await downloadPromise,stream=await download.createReadStream(),chunks=[];
    for await(const chunk of stream)chunks.push(chunk);
    const content=Buffer.concat(chunks).toString('utf8');
    for(const bib of citations)assert(content.includes(bib));
    assert(!content.includes('stale'),'cleared/stale body citations must not leak into the download');
    assert.match(await page.locator('#lit-export-status').innerText(),/已选 3 篇 · 已导出 2 条 · 缺失 1 篇/);
    await page.locator('#lit-export-status summary').click();
    assert.match(await page.locator('#lit-export-status').innerText(),/已清空引用：未填写 BibTeX/);
    await page.locator('#lit-search').fill('已清空引用');
    await page.waitForFunction(()=>document.querySelectorAll('#lit-list .lit-item').length===1);
    let extraDownloads=0;page.on('download',()=>extraDownloads++);
    await page.locator('#lit-export').click();
    await page.waitForFunction(()=>document.querySelector('#lit-export-status').textContent.includes('已选 1 篇 · 已导出 0 条'));
    assert.match(await page.locator('#toast-stack').innerText(),/没有可导出的 BibTeX/);
    assert.equal(extraDownloads,0,'all-missing exports should show a result without downloading an empty file');
    console.log('PASS: actual literature export downloads current metadata and reports missing/cleared citations; no empty download.');
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
