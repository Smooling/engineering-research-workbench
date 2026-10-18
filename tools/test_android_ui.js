/* npm-provided Playwright; CHROMIUM_PATH may point at a local Chrome binary. */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {mkdtempSync, rmSync, mkdirSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const repository = path.resolve(__dirname, '..');
const data = mkdtempSync(path.join(tmpdir(), 'workbench-android-ui-'));
const output = process.env.ANDROID_QA_OUTPUT || path.join(data, 'screenshots');
mkdirSync(output, {recursive:true});
const url = 'http://127.0.0.1:8877';
const server = spawn(process.env.PYTHON || 'python', ['-u', '-c',
  "from server import build_server; s,_,_=build_server(port_override=8877,host_override='127.0.0.1',auto_open_browser=False); s.serve_forever()"],
  {cwd:repository, env:{...process.env,WORKBENCH_DATA_ROOT:data,WORKBENCH_ASSET_ROOT:repository},stdio:'ignore'});
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function samplePdf() {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 400] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    '<< /Length 47 >>\nstream\nBT /F1 16 Tf 30 330 Td (Android offline PDF) Tj ET\nendstream',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let text = '%PDF-1.4\n', offsets=[0];
  objects.forEach((object,i)=>{offsets.push(Buffer.byteLength(text));text+=`${i+1} 0 obj\n${object}\nendobj\n`});
  const xref=Buffer.byteLength(text);
  text+=`xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(x=>String(x).padStart(10,'0')+' 00000 n \n').join('')}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(text);
}

(async () => {
  let browser;
  try {
    for(let i=0;i<100;i++) {try{if((await fetch(url+'/api/health')).ok)break}catch{}await delay(100)}
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:393,height:852},deviceScaleFactor:1,
      userAgent:'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/145.0.0.0 Mobile Safari/537.36 ResearchWorkbenchAndroid/1'});
    // All browser resources must work offline from the bundled frontend.
    await context.route('**/*',route=>route.request().url().startsWith(url)?route.continue():route.abort());
    const page=await context.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(url);await page.locator('#android-nav').waitFor();
    for(const width of [360,393,768,1280]) {
      await page.setViewportSize({width,height:852});await delay(100);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Overview overflow at ${width}`);
    }
    await page.setViewportSize({width:393,height:852});
    await page.screenshot({path:path.join(output,'phone-overview.png'),fullPage:true});
    await page.locator('[data-android-route=more]').click();
    await page.waitForFunction(()=>document.documentElement.dataset.androidDrawer==='true');
    assert.ok(await page.locator('.sidebar').isVisible());
    await page.evaluate(()=>window.ERWAndroid.handleBack());
    assert.equal(await page.getAttribute('html','data-android-drawer'),'false');
    await page.locator('[data-android-route=notes]').click();
    await page.locator('#new-doc').click();await page.locator('#f-title').fill('Android 界面验证');
    await page.locator('#md-input').fill('# 手机记录\n\n离线保存和 Markdown 预览。');
    await page.evaluate(()=>window.ERWAndroid.handleBack());
    await page.locator('#workbench-dialog').waitFor();
    await page.locator('[data-dialog-result=cancel]').click();
    assert.ok(await page.locator('#md-input').isVisible());
    await page.locator('#doc-save').click();
    await page.waitForFunction(()=>!window.ERWDesktop.hasUnsavedChanges());
    await page.screenshot({path:path.join(output,'phone-editor.png'),fullPage:true});
    await page.locator('[data-edit-mode=preview]').click();
    await page.locator('#md-preview h1').waitFor();
    assert.equal(await page.locator('#md-preview h1').textContent(),'手机记录');
    await page.locator('#android-doc-back').click();await page.locator('#new-doc').waitFor();
    await page.evaluate(()=>window.ERWNav.navigate('settings'));
    await page.locator('[data-set-tab=service]').click();
    assert.ok(await page.locator('#android-backup').isVisible());
    await page.locator('#theme-btn').click();
    await page.screenshot({path:path.join(output,'phone-settings-dark.png'),fullPage:true});
    await page.evaluate(()=>window.ERWNav.navigate('literature'));
    await page.locator('#open-lit-workspace').click();
    await page.locator('#lit-file').setInputFiles({name:'android-offline.pdf',mimeType:'application/pdf',buffer:samplePdf()});
    await page.locator('#lit-page-label').filter({hasText:'1 / 1'}).waitFor({timeout:20000});
    await page.screenshot({path:path.join(output,'phone-pdf.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    // The same files must retain desktop navigation and omit Android chrome.
    const desktop=await browser.newPage({viewport:{width:1440,height:900}});
    await desktop.goto(url);await desktop.locator('.overview-dashboard').waitFor();
    assert.equal(await desktop.locator('#android-nav').count(),0);
    assert.notEqual(await desktop.getAttribute('html','data-platform'),'android');
    console.log('PASS: 360/393/768/1280 widths, drawer/back, dirty guard, note save/preview, storage settings, dark mode, offline PDF and desktop host isolation.');
  } finally {
    if(browser)await browser.close();server.kill();rmSync(data,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1});
