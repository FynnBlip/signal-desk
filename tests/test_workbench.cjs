// Current served lab entry. GET only; writes blocked, no inference.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1380,height:900}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',r=>r.request().method()==='GET'?r.continue():r.abort());
 try{
  await page.goto(process.env.SIGNAL_DESK_TEST_URL||'http://127.0.0.1:8090/');
  await page.locator('#labCharts .lab-scene').first().waitFor();
  assert.equal(await page.locator('#labCharts .lab-scene').count(),6);
  assert.equal(await page.locator('script[src*="lab.js"]').count(),1);
  assert.equal(await page.locator('script[src*="workbench.js"]').count(),0);
  await page.getByRole('button',{name:'配置与运行',exact:true}).click();
  await page.locator('#labRunForm').waitFor();
  assert.equal(await page.getByRole('heading',{name:'配置与运行',exact:true}).count(),1);
  await page.getByRole('button',{name:'新建实验',exact:true}).click();
  assert.equal(await page.getByRole('dialog',{name:'开始一个新实验',exact:true}).count(),1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('dialog[open]').count(),0);
  assert.equal(await page.getByRole('button',{name:'新建实验',exact:true}).evaluate(e=>e===document.activeElement),true);
  for(const name of ['01 语料选择 固定测试文本','03 TTS 合成 生成多种音色','04 信道仿真 Opus × 六场景','05 降噪版本 V1 → V4','06 客观评测 AudioBox PQ','07 听审与迭代 人工确认 · 实验留痕']){
   await page.getByRole('button',{name,exact:true}).click();
   await page.locator('#labPanel .lab-intro').filter({hasNotText:'正在读取本地数据'}).waitFor();
   assert.equal(await page.locator('#labPanel [role="alert"]').count(),0);
  }
  for(const width of [1380,1024]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  }
  assert.deepEqual(errors,[]);console.log('PASS: actual lab entry, six scenes, current module navigation, named native dialog, Escape/focus, desktop overflow');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
