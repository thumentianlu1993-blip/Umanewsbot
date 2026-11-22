'use strict';
// 美国官方目录只读浏览器：无个人会话、无登录、无通用代理。
const MAX_BYTES=2*1024*1024,MAX_PDF=2*1024*1024;
const NSA_INDEX='https://nationalsteeplechase.com/racing/';
function isPdf(value){return typeof value==='string'&&/^https:\/\/nationalsteeplechase\.com\/wp-content\/uploads\/[0-9]{4}\/(?:0[1-9]|1[0-2])\/[A-Za-z0-9_.-]+\.pdf$/.test(value);}
const URLS=new Set([
 'https://nationalsteeplechase.com/racing/',
 'https://www.nyra.com/belmont/racing/stakes-schedule/',
 'https://www.dmtc.com/horsemen/nomforms',
 'https://www.dmtc.com/horsemen/nominations'
]);
function validateUrl(value){
 if(typeof value!=='string'||(!URLS.has(value)&&!isPdf(value)))throw Error('url_rejected');
 return new URL(value);
}
async function collect(url,chromium){
 const target=validateUrl(url),pdf=isPdf(url),navigation=pdf?NSA_INDEX:url,began=Date.now();
 const browser=await chromium.launch({headless:true,timeout:10000,chromiumSandbox:process.platform==='linux'});
 const deadline=setTimeout(()=>browser.close().catch(()=>{}),Math.max(1,30000-(Date.now()-began)));
 let requests=0,documents=0,denied='';
 try{
  const context=await browser.newContext({serviceWorkers:'block',acceptDownloads:false,locale:'en-US'});
  await context.route('**/*',async route=>{
   const req=route.request();let u;try{u=new URL(req.url());}catch{return route.abort();}
   if(denied||Date.now()-began>30000||u.origin!==target.origin||!['GET','HEAD'].includes(req.method())||!['document','script','xhr','fetch'].includes(req.resourceType()))return route.abort();
   if(req.resourceType()==='document'&&(u.href!==navigation||req.frame().parentFrame()||++documents>1)){denied='navigation_rejected';return route.abort();}
   if(++requests>96){denied='request_limit';return route.abort();}
   return route.continue();
  });
  const page=await context.newPage();page.setDefaultTimeout(20000);
  const response=await page.goto(navigation,{waitUntil:'domcontentloaded'});
  if(response?.status()!==200||denied)throw Error(denied||'upstream_'+response?.status());
  if(page.url()!==navigation)throw Error('navigation_rejected');
  const title=await page.title();
  if(/access denied|captcha|sign in|just a moment|verify.*human|challenge/i.test(title))throw Error('login_or_challenge_required');
  if(pdf){
   const data=await page.evaluate(async({url,max})=>{
    if(!Array.from(document.querySelectorAll('a[href]')).some(a=>a.href===url))throw Error('directory_link_missing');
    const response=await fetch(url,{credentials:'omit',redirect:'error'});
    if(response.status!==200)throw Error('upstream_'+response.status);
    if(response.url!==url||response.headers.get('content-type')?.split(';')[0].trim()!=='application/pdf')throw Error('pdf_response_rejected');
    if(Number(response.headers.get('content-length')||0)>max)throw Error('response_limit');
    const reader=response.body.getReader(),parts=[];let size=0;
    while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>max){await reader.cancel();throw Error('response_limit');}parts.push(value);}
    const bytes=new Uint8Array(size);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
    if(new TextDecoder().decode(bytes.slice(0,5))!=='%PDF-')throw Error('pdf_signature');
    let binary='';for(let i=0;i<bytes.length;i+=4096)binary+=String.fromCharCode(...bytes.subarray(i,i+4096));
    const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
    return {bytes_b64:btoa(binary),raw_sha256:sha};
   },{url,max:MAX_PDF});
   if(denied||page.url()!==navigation||Date.now()-began>30000)throw Error(denied||'response_limit');
   return {url,final_url:url,directory_url:navigation,...data,navigation_count:documents,document_requests:2,
    resource_requests:requests,observed_at:new Date().toISOString(),elapsed_ms:Date.now()-began};
  }
  const html=await page.evaluate(()=>{
   const clone=document.documentElement.cloneNode(true);
   clone.querySelectorAll('script,style,link,iframe,noscript,svg,img,input,form').forEach(el=>el.remove());
   return '<!DOCTYPE html>'+clone.outerHTML;
  });
  if(denied)throw Error(denied);
  if(page.url()!==navigation)throw Error('navigation_rejected');
  if(Buffer.byteLength(html)>MAX_BYTES||Date.now()-began>30000)throw Error('response_limit');
  return {url,final_url:page.url(),html,navigation_count:documents,resource_requests:requests,
   observed_at:new Date().toISOString(),elapsed_ms:Date.now()-began};
 }finally{clearTimeout(deadline);await browser.close();}
}
module.exports={collect,validateUrl,MAX_BYTES,MAX_PDF};
