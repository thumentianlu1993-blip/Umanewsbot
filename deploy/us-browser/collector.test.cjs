'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {validateUrl,collect}=require('./collector.cjs');
const URL='https://nationalsteeplechase.com/racing/';
test('仅允许精确官方目录，拒绝登录、查询、子域与重定向入口',()=>{
 for(const u of [URL,'https://www.nyra.com/belmont/racing/stakes-schedule/','https://www.dmtc.com/horsemen/nomforms','https://www.dmtc.com/horsemen/nominations'])assert.equal(validateUrl(u).href,u);
 for(const u of [URL+'?next=/login',URL+'#x',URL.replace('https:','http:'),URL.replace('national','www.national'),'https://u:p@nationalsteeplechase.com/racing/','https://nationalsteeplechase.com/wp-admin/','https://equibase.com/','https://www.dmtc.com/horsemen/../login'])assert.throws(()=>validateUrl(u));
});
async function fake({status=200,title='RACING',nav=[URL],resources=0,final=URL,late=0}={}){
 let handler,closed=false;const calls=[];
 async function request(url,type='document',method='GET',child=false){
  let outcome='';await handler({request:()=>({url:()=>url,method:()=>method,resourceType:()=>type,frame:()=>({parentFrame:()=>child?{}:null})}),continue:async()=>{outcome='continue'},abort:async()=>{outcome='abort'}});calls.push({url,outcome});
 }
 const page={setDefaultTimeout(){},url:()=>final,title:async()=>title,goto:async()=>{
  for(const u of nav)await request(u);
  for(let i=0;i<resources;i++)await request('https://nationalsteeplechase.com/asset.js','script');
  await request('https://equibase.com/asset.js','script');await request(URL,'fetch','POST');
  return {status:()=>status};
 },evaluate:async()=>{for(let i=0;i<late;i++)await request('https://nationalsteeplechase.com/late.js','script');return '<!DOCTYPE html><html><body>Colonial Cup</body></html>'}};
 const chromium={launch:async opts=>{assert.equal(opts.headless,true);return {newContext:async opts=>{assert.equal(opts.serviceWorkers,'block');assert.equal(opts.acceptDownloads,false);assert.equal(opts.storageState,undefined);return {route:async(_,fn)=>{handler=fn},newPage:async()=>page}},close:async()=>{closed=true}}}};
 try{const value=await collect(URL,chromium);return {value,calls}}finally{assert.equal(closed,true)}
}
test('正常目录只读收集；阻止跨域资源和写请求',async()=>{const {value,calls}=await fake();assert.equal(value.navigation_count,1);assert.equal(value.resource_requests,1);assert.equal(calls[1].outcome,'abort');assert.equal(calls[2].outcome,'abort')});
test('403、登录挑战和第二次导航均失败，不交付空名单',async()=>{
 for(const opts of [{status:403},{title:'Just a moment...'},{title:'Sign in'},{nav:[URL,URL]},{nav:[URL,URL+'other']},{final:URL+'other'},{resources:96},{resources:95,late:1}])await assert.rejects(fake(opts));
});
test('NSA PDF只允许公开uploads路径，不接受查询、凭据、其他主机',()=>{
 assert.equal(validateUrl('https://nationalsteeplechase.com/wp-content/uploads/2026/11/Colonial-Cup-Overnight.pdf').protocol,'https:');
 for(const u of ['https://nationalsteeplechase.com/wp-content/uploads/2026/11/a.pdf?download=1','https://nationalsteeplechase.com/wp-content/uploads/2026/13/a.pdf','https://www.nationalsteeplechase.com/wp-content/uploads/2026/11/a.pdf'])assert.throws(()=>validateUrl(u));
});
async function fakePdf({linked=true,status=200,body=Buffer.from('%PDF-1.7\nexample'),type='application/pdf',final=null,length=null}={}){
 const url='https://nationalsteeplechase.com/wp-content/uploads/2026/11/Colonial-Cup-Overnight.pdf';
 let handler,closed=false;const calls=[];const oldFetch=globalThis.fetch,oldDocument=globalThis.document;
 async function request(target,kind){let outcome='';await handler({request:()=>({url:()=>target,method:()=> 'GET',resourceType:()=>kind,frame:()=>({parentFrame:()=>null})}),continue:async()=>{outcome='continue'},abort:async()=>{outcome='abort'}});calls.push(outcome);assert.equal(outcome,'continue');}
 globalThis.document={querySelectorAll:()=>linked?[{href:url}]:[]};
 globalThis.fetch=async(target,opts)=>{
  assert.equal(target,url);assert.deepEqual(opts,{credentials:'omit',redirect:'error'});await request(target,'fetch');
  return {status,url:final||url,headers:{get:key=>key==='content-type'?type:key==='content-length'?String(length===null?body.length:length):null},
   body:new ReadableStream({start(controller){controller.enqueue(new Uint8Array(body));controller.close();}})};
 };
 const page={setDefaultTimeout(){},url:()=>URL,title:async()=> 'RACING',goto:async(target)=>{assert.equal(target,URL);await request(target,'document');return {status:()=>200};},evaluate:async(fn,args)=>fn(args)};
 const chromium={launch:async()=>({newContext:async()=>({route:async(_,fn)=>{handler=fn},newPage:async()=>page}),close:async()=>{closed=true}})};
 try{return {value:await collect(url,chromium),calls};}
 finally{globalThis.fetch=oldFetch;if(oldDocument===undefined)delete globalThis.document;else globalThis.document=oldDocument;assert.equal(closed,true);}
}
test('PDF只从目录显式链接读取，保留原始字节与摘要并计算两份文档',async()=>{
 const raw=Buffer.from('%PDF-1.7\n\xff\xfe','latin1'),{value,calls}=await fakePdf({body:raw});
 assert.deepEqual(Buffer.from(value.bytes_b64,'base64'),raw);
 assert.equal(value.raw_sha256,require('node:crypto').createHash('sha256').update(raw).digest('hex'));
 assert.equal(value.document_requests,2);assert.equal(value.navigation_count,1);assert.equal(value.resource_requests,2);assert.equal(calls.length,2);
});
test('缺目录链接、403、假PDF、重定向、超限均拒绝，不返回资料',async()=>{
 for(const opts of [{linked:false},{status:403},{type:'text/html'},{body:Buffer.from('<html>error</html>')},{final:URL},
   {length:2*1024*1024+1},{body:Buffer.alloc(2*1024*1024+1),length:0}])await assert.rejects(fakePdf(opts));
});
