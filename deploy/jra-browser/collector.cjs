'use strict';
// 独立JRA浏览器传输；不持有数据库、个人登录状态或通用代理能力。
const ORIGIN = 'https://www.jra.go.jp';
const SEED = ORIGIN + '/keiba/thisweek/';
const MAX_BYTES = 2 * 1024 * 1024;
function validateUrl(value) {
  if (typeof value !== 'string' || value.length > 2048) throw new Error('url_rejected');
  const u = new URL(value);
  if (u.origin !== ORIGIN || u.username || u.password || u.hash || /%2f|%5c|%2e|\\/i.test(u.pathname)) throw new Error('url_rejected');
  if (u.pathname.startsWith('/JRADB/')) {
    const patterns = {
      '/JRADB/accessD.html': /^(?:pw01dde(?:01|10)\d{20}\/[0-9A-F]{2}|pw01dli00\/F3|pw01drl(?:00|10)\d{18}\/[0-9A-F]{2})$/,
      '/JRADB/accessS.html': /^pw01sde(?:01|10)\d{20}\/[0-9A-F]{2}$/,
      '/JRADB/accessT.html': /^(?:pw03tde00\d{16}\/[0-9A-F]{2}|pw03trl00\/29)$/,
    };
    const entries = [...u.searchParams];
    if (!patterns[u.pathname] || entries.length !== 1 || entries[0][0] !== 'CNAME' || !patterns[u.pathname].test(entries[0][1])) throw new Error('url_rejected');
  } else if (u.search || !(/^\/keiba\/(thisweek\/|race\/\d+\/[a-z_]+\.html)$/.test(u.pathname) || /^\/datafile\/seiseki\/(?:replay\/\d{4}\/(?:jyusyo|\d{3})|g1\/[a-z0-9_]+\/result\/[a-z0-9_]+\d{4})\.html$/.test(u.pathname))) {
    throw new Error('url_rejected');
  }
  return u;
}
async function collect(url, chromium) {
  const target = validateUrl(url);
  const began = Date.now();
  const browser = await chromium.launch({headless:true, timeout:10000, chromiumSandbox: process.platform === 'linux'});
  const deadline = setTimeout(() => browser.close().catch(() => {}), Math.max(1, 30000-(Date.now()-began)));
  let requests=0, documents=0, denied=null;
  try {
    const context = await browser.newContext({serviceWorkers:'block', acceptDownloads:false});
    await context.route('**/*', async route => {
      const req=route.request();
      let u; try {u=new URL(req.url());} catch {return route.abort();}
      if (denied || Date.now()-began>30000 || u.origin!==ORIGIN || !['document','script'].includes(req.resourceType())) return route.abort();
      if (req.resourceType()==='document') {
        const allowed = [target.origin+target.pathname, target.href, SEED];
        if (!allowed.includes(u.href) || ++documents>2) {denied='navigation_rejected';return route.abort();}
      }
      if (++requests>64) {denied='request_limit';return route.abort();}
      return route.continue();
    });
    const page=await context.newPage();
    page.setDefaultTimeout(20000);
    page.on('response', r=>{if([401,403,429].includes(r.status())) denied='upstream_'+r.status();});
    let response;
    if(target.pathname.startsWith('/JRADB/')) {
      response=await page.goto(SEED,{waitUntil:'domcontentloaded'});
      if(response?.status()!==200 || denied)throw Error(denied || 'upstream_'+response?.status());
      const [navigation]=await Promise.all([
        page.waitForNavigation({waitUntil:'domcontentloaded'}),
        page.evaluate(({path,cname})=>doAction(path,cname), {path:target.pathname,cname:target.searchParams.get('CNAME')})
      ]);
      response=navigation;
    } else response=await page.goto(target.href,{waitUntil:'domcontentloaded'});
    if(response?.status()!==200 || denied)throw Error(denied || 'upstream_'+response?.status());
    const title=await page.title();
    if(/パラメータエラー|Access Denied|captcha|認証が必要/i.test(title))throw Error('upstream_page_rejected');
    const html=await page.content();
    if(Buffer.byteLength(html)>MAX_BYTES || Date.now()-began>30000)throw Error('response_limit');
    return {url, final_url:page.url(), title, html, navigation_count:documents, resource_requests:requests,
      observed_at:new Date().toISOString(),elapsed_ms:Date.now()-began};
  } finally {clearTimeout(deadline); await browser.close();}
}
module.exports={collect,validateUrl,MAX_BYTES};
