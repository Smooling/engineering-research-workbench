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
    async function create(endpoint, body) {
      const response=await fetch(url+endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      assert.ok(response.ok,await response.text());
    }
    await create('/api/project-records',{name:'面向移动设备的科研数据分析与长期实验记录项目',description:'验证长标题、项目指标与手机排版',status:'进行中'});
    for(let i=0;i<7;i++)await create('/api/todos',{title:`第 ${i+1} 项实验：整理本周观测数据并检查异常结果`,due:'2026-10-20',priority:'高'});
    await create('/api/docs',{kind:'milestone',title:'完成第一阶段实验并整理研究结果',due:'2026-10-25',status:'计划',body:'阶段目标'});
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||undefined,args:['--no-sandbox']});
    const context=await browser.newContext({viewport:{width:393,height:852},deviceScaleFactor:1,
      userAgent:'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 Chrome/145.0.0.0 Mobile Safari/537.36 ResearchWorkbenchAndroid/1'});
    // All browser resources must work offline from the bundled frontend.
    await context.route('**/*',route=>route.request().url().startsWith(url)?route.continue():route.abort());
    const page=await context.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.goto(url);await page.locator('#android-nav').waitFor();
    for(const width of [360,393,768,1280]) {
      await page.setViewportSize({width,height:852});await delay(250);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Overview overflow at ${width}`);
    }
    await page.setViewportSize({width:393,height:852});
    await delay(250);
    assert.ok(await page.locator('.sidebar').evaluate(el=>el.getBoundingClientRect().right<=0),'Closed drawer must be outside the viewport');
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
    await page.locator('#meta-toggle').click();await page.locator('#f-tag-add').click();
    await page.locator('#f-tag-query').fill('手机适配');await page.locator('#f-tag-query-add').click();
    await page.setViewportSize({width:393,height:440});await page.evaluate(()=>window.ERWAndroid.setKeyboardVisible(true));await delay(100);
    const applyBox=await page.locator('#tag-pick-done').boundingBox();assert.ok(applyBox.y+applyBox.height<=440,'Sheet footer must remain above IME');
    await page.locator('#tag-pick-done').click();
    await page.setViewportSize({width:393,height:852});await page.evaluate(()=>window.ERWAndroid.setKeyboardVisible(false));
    await page.locator('#meta-toggle').click();
    // Native IME insets resize WebView; actions must stay in the remaining area.
    await page.locator('#md-input').focus();await page.setViewportSize({width:393,height:440});
    await page.evaluate(()=>window.ERWAndroid.setKeyboardVisible(true));await delay(150);
    assert.equal(await page.locator('#android-nav').isVisible(),false);
    const saveBox=await page.locator('#doc-save').boundingBox(), inputBox=await page.locator('#md-input').boundingBox();
    assert.ok(saveBox.y>=0&&saveBox.y+saveBox.height<=440,'Save must remain above IME');
    assert.ok(inputBox.height>=100&&inputBox.y+inputBox.height<=440,'Editor must fit resized viewport');
    await page.screenshot({path:path.join(output,'phone-editor-keyboard.png')});
    await page.locator('#doc-save').click();
    await page.waitForFunction(()=>!window.ERWDesktop.hasUnsavedChanges());
    await page.setViewportSize({width:393,height:852});await page.evaluate(()=>window.ERWAndroid.setKeyboardVisible(false));
    await page.setViewportSize({width:900,height:440});await delay(150);
    assert.ok(await page.locator('#doc-save').isVisible(),'Save must survive phone rotation');
    await page.setViewportSize({width:393,height:852});await delay(150);
    await page.screenshot({path:path.join(output,'phone-editor.png'),fullPage:true});
    await page.locator('[data-edit-mode=preview]').click();
    await page.locator('#md-preview h1').waitFor();
    assert.equal(await page.locator('#md-preview h1').textContent(),'手机记录');
    await page.locator('#android-doc-back').click();await page.locator('#new-doc').waitFor();
    for(const route of ['todos','projects','focus','agent','milestones','folders','billing','graph','settings']) {
      await page.evaluate(route=>window.ERWNav.navigate(route),route);await delay(350);
      assert.equal(await page.locator('#main .card.danger').count(),0,`${route} must load successfully`);
      for(const width of [360,430,768]){
        await page.setViewportSize({width,height:800});await delay(100);
        const overflow=await page.locator('#main').evaluate(el=>el.scrollWidth>el.clientWidth+2);
        if(overflow){
          console.log(await page.locator('#main').evaluate(el=>({main:{client:el.clientWidth,scroll:el.scrollWidth,box:el.getBoundingClientRect().toJSON()},scrolls:[...el.querySelectorAll('*')].filter(x=>x.scrollWidth>x.clientWidth+2).map(x=>({tag:x.tagName,cls:x.className,client:x.clientWidth,scroll:x.scrollWidth,overflow:getComputedStyle(x).overflowX})).slice(0,30)})));
          console.log(await page.locator('#main').evaluate(el=>[...el.querySelectorAll('*')].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.right>innerWidth+2}).map(x=>({tag:x.tagName,id:x.id,cls:x.className,width:x.getBoundingClientRect().width})).slice(0,25)));
          await page.screenshot({path:path.join(output,`overflow-${route}.png`)});
        }
        assert.equal(overflow,false,`${route} must fit ${width}px without clipped content`);
      }
      await page.setViewportSize({width:393,height:852});await delay(100);
      await page.screenshot({path:path.join(output,`phone-${route}.png`)});
      if(route==='agent'){
        assert.equal(await page.locator('#agent-profile-select').count(),1,'Async profile enhancement must not duplicate controls');
        await page.locator('#android-agent-sessions').click();assert.ok(await page.locator('.agent-sessions').isVisible());
        await page.evaluate(()=>window.ERWAndroid.handleBack());assert.ok(await page.locator('.agent-chat').isVisible());
        await page.locator('#agent-input').fill('第一行');await page.locator('#agent-input').press('Enter');
        assert.equal(await page.locator('#agent-input').inputValue(),'第一行\n','Android Enter must insert a newline');
        await page.setViewportSize({width:393,height:440});await page.evaluate(()=>window.ERWAndroid.setKeyboardVisible(true));await delay(100);
        const send=await page.locator('#agent-send').boundingBox();assert.ok(send.y+send.height<=440,'Send must remain above IME');
        await page.screenshot({path:path.join(output,'phone-agent-keyboard.png')});
        await page.setViewportSize({width:393,height:852});await page.evaluate(()=>window.ERWAndroid.setKeyboardVisible(false));
      }
    }
    await page.evaluate(()=>window.ERWNav.navigate('settings'));
    for(const tab of ['knowledge','literature','academic','weather','rss','llm','interface','sync']) {
      await page.locator(`[data-set-tab=${tab}]`).click();await delay(250);
      await page.setViewportSize({width:360,height:800});await delay(100);
      if(!await page.locator('#main').evaluate(el=>el.scrollWidth<=el.clientWidth+2)){
        console.log(await page.locator('#main').evaluate(el=>[...el.querySelectorAll('*')].filter(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.right>innerWidth+2}).map(x=>({tag:x.tagName,id:x.id,cls:x.className,width:x.getBoundingClientRect().width})).slice(0,25)));
        await page.screenshot({path:path.join(output,`overflow-settings-${tab}.png`)});
      }
      assert.ok(await page.locator('#main').evaluate(el=>el.scrollWidth<=el.clientWidth+2),`Settings ${tab} must fit the phone`);
      await page.screenshot({path:path.join(output,`phone-settings-${tab}.png`)});
    }
    await page.setViewportSize({width:393,height:852});
    await page.locator('[data-set-tab=service]').click();
    assert.ok(await page.locator('#android-backup').isVisible());
    await page.locator('#theme-btn').click();
    await page.screenshot({path:path.join(output,'phone-settings-dark.png'),fullPage:true});
    await page.evaluate(()=>window.ERWNav.navigate('literature'));
    await page.locator('#open-lit-workspace').click();
    await page.locator('#lit-file').setInputFiles({name:'android-offline.pdf',mimeType:'application/pdf',buffer:samplePdf()});
    await page.waitForFunction(()=>document.querySelector('#lit-pages canvas')?.width>1,{timeout:20000});
    assert.equal(await page.locator('.lit-library').isVisible(),false);
    const pdfWidth=await page.locator('.lit-page').evaluate(el=>el.getBoundingClientRect().width);
    assert.ok(pdfWidth<393,'PDF must initially fit the phone width');
    await page.screenshot({path:path.join(output,'phone-pdf.png'),fullPage:true});
    await page.setViewportSize({width:360,height:800});await page.locator('#lit-fit-width').click();
    await page.waitForFunction(()=>document.querySelector('#lit-pages canvas')?.width>1);
    assert.ok(await page.locator('.lit-page').evaluate(el=>el.getBoundingClientRect().width<360),'Fit width must work after rotation or resize');
    await page.setViewportSize({width:393,height:852});
    await page.locator('[data-android-pdf=side]').click();assert.ok(await page.locator('#lit-side-body').isVisible());
    await page.locator('[data-tab=notes]').click();await page.locator('#lit-note').fill('Android PDF 阅读笔记');await page.locator('#lit-note-save').click();
    await page.screenshot({path:path.join(output,'phone-pdf-notes.png')});
    await page.evaluate(()=>window.ERWAndroid.handleBack());assert.ok(await page.locator('.lit-library').isVisible());
    assert.deepEqual(errors,[]);
    // The same files must retain desktop navigation and omit Android chrome.
    const desktop=await browser.newPage({viewport:{width:1440,height:900}});
    await desktop.goto(url);await desktop.locator('.overview-dashboard').waitFor();
    assert.equal(await desktop.locator('#android-nav').count(),0);
    assert.notEqual(await desktop.getAttribute('html','data-platform'),'android');
    console.log('PASS: populated phone pages at 360/393/430/768/1280 widths; drawer/back; dirty guard; keyboard save/send; chat panes/newline; PDF fit/panes/notes; dark mode; desktop isolation.');
  } finally {
    if(browser)await browser.close();server.kill();rmSync(data,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1});
