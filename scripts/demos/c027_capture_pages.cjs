// 只截图本地Django真实DOM；不连接任何外部站点，不生成模拟页面。
const {chromium} = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
(async () => {
  const runtime = path.resolve(process.argv[2]);
  const base = process.argv[3] || 'http://127.0.0.1:8767';
  assert.equal(new URL(base).hostname, '127.0.0.1');
  const evidence = JSON.parse(fs.readFileSync(path.join(runtime, 'verification.json')));
  const browser = await chromium.launch({headless: true});
  try {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, locale:'zh-CN'});
  const blocked = [], errors = [];
  await context.route('**/*', route => {
    if (new URL(route.request().url()).origin === base) return route.continue();
    blocked.push(route.request().url());return route.abort();
  });
  const page = await context.newPage();
  page.on('pageerror', err => errors.push(err.message));
  const shot = async name => {
    await page.screenshot({path:path.join(runtime,name+'.png'),fullPage:true});
    fs.writeFileSync(path.join(runtime,name+'.html'),await page.content());
  };
  await page.goto(base+'/',{waitUntil:'networkidle'});
  assert.equal(await page.locator('.hero-races .race-row').count(),4);
  assert.equal(await page.locator('.hero-races .race-row').first().locator('.race-row-winner').count(),0);
  assert.match(await page.locator('body').innerText(),/合成演示/);
  assert.equal(await page.locator('.hero-races').getByText('【合成演示】三级赛（第五场）',{exact:true}).count(),0);
  assert.equal(await page.locator('.hero-races').getByText('【合成演示】七天外重点赛',{exact:true}).count(),0);
  await shot('home-desktop');
  await page.goto(base+'/races/?tab=all&grade=g1&year='+evidence.date_beijing.slice(0,4),{waitUntil:'networkidle'});
  const badges = await page.locator('.cal-card .grade-badge').allTextContents();
  assert.equal(badges.length,4);assert(badges.every(x=>['G1','Jpn1','J-G1'].includes(x.trim())));
  await shot('g1-calendar-desktop');
  const filtered='/races/?tab=all&region=germany&grade=g1&year='+evidence.date_beijing.slice(0,4);
  await page.goto(base+filtered,{waitUntil:'networkidle'});
  assert.equal(await page.locator('.cal-card').count(),1);
  await shot('germany-g1-desktop');
  await page.locator('.cal-card').first().click();
  await page.waitForLoadState('networkidle');
  assert.match(page.url(),/c027-german-g1/);
  await shot('detail-with-return');
  await page.getByRole('link',{name:'返回赛事日历',exact:true}).click();
  await page.waitForLoadState('networkidle');
  const returned=new URL(page.url());
  assert.equal(returned.searchParams.get('grade'),'g1');
  assert.equal(returned.searchParams.get('region'),'germany');
  assert.equal(returned.searchParams.get('year'),evidence.date_beijing.slice(0,4));
  assert.equal(await page.locator('.cal-card').count(),1);
  const returnURL=page.url();await shot('return-preserves-filters');
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/',{waitUntil:'networkidle'});
  assert.equal(await page.locator('.hero-races .race-row').count(),4);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth));
  await shot('home-mobile');
  assert.equal(errors.length,0);
  const summary={source_main:evidence.source_main,candidate_sha:evidence.candidate_sha,synthetic:true,base,desktop:'1440x1000',mobile:'390x844',
    home_cards:4,date_only_has_no_clock:true,g1_badges:badges,return_url:returnURL,
    screenshots:['home-desktop','g1-calendar-desktop','germany-g1-desktop','detail-with-return','return-preserves-filters','home-mobile'],
    page_errors:errors,blocked_external_requests:blocked};
  fs.writeFileSync(path.join(runtime,'browser-verification.json'),JSON.stringify(summary,null,2)+'\n');
  console.log(JSON.stringify(summary));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
