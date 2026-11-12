'use strict';
// 美国官方目录只读浏览器：无个人会话、无登录、无通用代理。
const MAX_BYTES=2*1024*1024;
const URLS=new Set([
 'https://nationalsteeplechase.com/racing/',
 'https://www.nyra.com/belmont/racing/stakes-schedule/',
 'https://www.dmtc.com/horsemen/nomforms',
 'https://www.dmtc.com/horsemen/nominations'
]);
function validateUrl(value){
 if(typeof value!=='string'||!URLS.has(value))throw Error('url_rejected');
 return new URL(value);
}
async function collect(url,chromium){
 const target=validateUrl(url),began=Date.now();
 const browser=await chromium.launch({headless:true,timeout:10000,chromiumSandbox:process.platform==='linux'});
 const deadline=setTimeout(()=>browser.close().catch(()=>{}),Math.max(1,30000-(Date.now()-began)));
 let requests=0,documents=0,denied='';
 try{
  const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:false,locale:'en-US'});
  await context.route('**/*',async route=>{
   const req=route.request();let u;try{u=new URL(req.url());}catch{return route.abort();}
   if(denied||Date.now()-began>30000||u.origin!==target.origin||!['GET','HEAD'].includes(req.method())||!['document','script','xhr','fetch'].includes(req.resourceType()))return route.abort();
   if(req.resourceType()==='document'&&(u.href!==target.href||req.frame().parentFrame()||++documents>1)){denied='navigation_rejected';return route.abort();}
   if(++requests>96){denied='request_limit';return route.abort();}
   return route.continue();
  });
  const page=await context.newPage();page.setDefaultTimeout(20000);
  const response=await page.goto(url,{waitUntil:'domcontentloaded'});
  if(response?.status()!==200||denied)throw Error(denied||'upstream_'+response?.status());
  if(page.url()!==url)throw Error('navigation_rejected');
  const title=await page.title();
  if(/access denied|captcha|sign in|just a moment|verify.*human|challenge/i.test(title))throw Error('login_or_challenge_required');
  const html=await page.evaluate(()=>{
   const clone=document.documentElement.cloneNode(true);
   clone.querySelectorAll('script,style,link,iframe,noscript,svg,img,input,form').forEach(el=>el.remove());
   return '<!DOCTYPE html>'+clone.outerHTML;
  });
  if(denied)throw Error(denied);
  if(page.url()!==url)throw Error('navigation_rejected');
  if(Buffer.byteLength(html)>MAX_BYTES||Date.now()-began>30000)throw Error('response_limit');
  return {url,final_url:page.url(),html,navigation_count:documents,resource_requests:requests,
   observed_at:new Date().toISOString(),elapsed_ms:Date.now()-began};
 }finally{clearTimeout(deadline);await browser.close();}
}
module.exports={collect,validateUrl,MAX_BYTES};
