'use strict';
// 独立只读赛事浏览器；认证文件由部署包提供，禁止通用代理和登录写操作。
const MAX_BYTES=2*1024*1024;
function validateUrl(value){
 if(typeof value!=='string'||value.length>2048)throw Error('url_rejected');
 const u=new URL(value);
 if(u.protocol!=='https:'||u.username||u.password||u.port||u.search||u.hash||/%2f|%5c|%2e|\\/i.test(u.pathname))throw Error('url_rejected');
 const valid=u.hostname==='www.geny.com'
  ? /^\/(?:programme\/\d{4}-\d{2}-\d{2}|course\/\d+-\d{4}-\d{2}-\d{2}-[^/]+\/(?:partants-pronostics|arrivee-rapports))$/.test(u.pathname)
  : u.hostname==='www.france-galop.com'&&/^\/fr\/(?:course\/detail\/\d{4}\/[PO]\/[A-Za-z0-9=]+|courses\/pattern-listed)$/.test(u.pathname);
 if(!valid)throw Error('url_rejected');
 return u;
}
async function collect(url,chromium){
 const target=validateUrl(url),began=Date.now();
 const browser=await chromium.launch({headless:true,timeout:10000,chromiumSandbox:process.platform==='linux'});
 const deadline=setTimeout(()=>browser.close().catch(()=>{}),Math.max(1,30000-(Date.now()-began)));
 let requests=0,documents=0,denied='';
 try{
  const options={serviceWorkers:'block',acceptDownloads:false,timezoneId:'Europe/Paris',locale:'fr-FR',viewport:{width:1440,height:1000}};
  if(target.hostname==='www.france-galop.com'&&process.env.FRANCE_GALOP_STORAGE_STATE)options.storageState=process.env.FRANCE_GALOP_STORAGE_STATE;
  const context=await browser.newContext(options);
  await context.route('**/*',async route=>{
   const req=route.request();let u;try{u=new URL(req.url());}catch{return route.abort();}
   if(denied||Date.now()-began>30000||u.origin!==target.origin||!['GET','HEAD'].includes(req.method())||!['document','script','xhr','fetch'].includes(req.resourceType()))return route.abort();
   if(req.resourceType()==='document'&&(u.href!==target.href||++documents>1)){denied='navigation_rejected';return route.abort();}
   if(++requests>96){denied='request_limit';return route.abort();}
   return route.continue();
  });
  const page=await context.newPage();page.setDefaultTimeout(20000);
  const response=await page.goto(url,{waitUntil:'domcontentloaded'});
  if(response?.status()!==200||denied)throw Error(denied||'upstream_'+response?.status());
  if(page.url()!==url)throw Error('navigation_rejected');
  if(target.pathname.includes('/course/')){
   try{
    await page.waitForFunction(()=>document.querySelector('table tr td')||document.body.innerText.includes('ARRIVÉE DÉFINITIVE')||document.body.innerText.includes('AUCUNE LISTE DIFFUSABLE'),null,{timeout:15000});
   }catch(error){
    // 完整赛事标题但尚无最终结果的Geny页仍交给解析器判阶段；不把空表当结果。
    // 卡表、登录页和网络/脚本错误继续拒绝。日期/场地身份由解析器复核。
    if(!(error.name==='TimeoutError'&&target.hostname==='www.geny.com'
      &&target.pathname.endsWith('/arrivee-rapports')
      &&/^Arrivée et rapports (?:de la course|du Quinté\+) .+ \| Geny$/.test(await page.title())))throw error;
   }
  }
  const title=await page.title();
  if(/Access Denied|captcha|sign in|se connecter|connexion|authentification/i.test(title))throw Error('login_or_challenge_required');
  const html=await page.evaluate(()=>{
   const clone=document.documentElement.cloneNode(true);
   clone.querySelectorAll('script,style,link,iframe,noscript,svg,img,input,form').forEach(el=>el.remove());
   const meta=document.createElement('meta');meta.name='source-timezone';meta.content='Europe/Paris';clone.querySelector('head').append(meta);
   return '<!DOCTYPE html>'+clone.outerHTML;
  });
  if(Buffer.byteLength(html)>MAX_BYTES||Date.now()-began>30000)throw Error('response_limit');
  return {url,final_url:page.url(),html,navigation_count:documents,resource_requests:requests,
   observed_at:new Date().toISOString(),elapsed_ms:Date.now()-began};
 }finally{clearTimeout(deadline);await browser.close();}
}
module.exports={collect,validateUrl,MAX_BYTES};
