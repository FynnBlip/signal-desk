// Requires the local service and an existing version comparison dataset.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  await page.route('**/api/**',route=>route.request().method()==='GET'?route.continue():route.abort());
  try {
    await page.goto('http://127.0.0.1:8090/?view=loop#compare');
    await page.waitForSelector('.insight-scene');
    await page.locator('#insightScene0').click();
    assert.equal(await page.locator('.insight-detail-head h3').evaluate(el=>getComputedStyle(el).color),'rgb(57, 117, 34)');
    const cells=await page.evaluate(()=>{
      const saved=versionRawRows[0].scores;
      try {
        versionRawRows[0].scores={v1:null,v3:0,v4:1};
        renderVersionRawTable();
        return [...document.querySelectorAll('#versionRawBody tr:first-child td')].slice(-4).map(el=>el.textContent);
      } finally { versionRawRows[0].scores=saved; renderVersionRawTable(); }
    });
    assert.deepEqual(cells,['—','—','0.000','1.000']);
    for(const card of await page.locator('.insight-scene').all()){
      assert.match(await card.locator('.plot-point.is-winner text').textContent(),/^V[1-4] · /);
      assert.match(await card.locator('.scene-result').textContent(),/综合推荐/);
    }
    await page.evaluate(()=>selectLoopPage('listen'));
    const player=page.locator('#goldenPair audio').first();
    await player.evaluate(el=>el.play());
    await page.evaluate(()=>showView('overview'));
    assert.equal(await player.evaluate(el=>el.paused),true);
    for(const view of ['channel','voice','evaluate']){
      await page.evaluate(view=>showView(view),view);
      assert.equal(await page.locator(`#view-${view} h1`).evaluate(el=>getComputedStyle(el).fontSize),'28px');
    }
    console.log('PASS: missing scores, chart semantics, scene colour, cross-view audio, tool titles.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
