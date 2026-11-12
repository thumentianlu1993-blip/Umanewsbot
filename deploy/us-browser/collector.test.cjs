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
