'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {validateUrl}=require('./collector.cjs');
test('仅允许已验证的法国赛事与目录入口',()=>{
 for(const url of ['https://www.geny.com/programme/2026-11-09',
   'https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports',
   'https://www.france-galop.com/fr/course/detail/2026/P/V3p6QkRwQllwT1AvdkUvZ1pnOHd4dz09',
   'https://www.france-galop.com/fr/courses/pattern-listed']) assert.equal(validateUrl(url).href,url);
 for(const url of ['https://www.geny.com/account','http://www.geny.com/programme/2026-11-09',
   'https://u:p@www.geny.com/programme/2026-11-09','https://www.geny.com/programme/2026-11-09?next=evil',
   'https://www.france-galop.com/fr/account','https://www.france-galop.com/fr/course/%2e%2e/account',
   'https://evil.example/course/1','https://www.geny.com:444/programme/2026-11-09']) assert.throws(()=>validateUrl(url));
});

async function timeoutBrowser(url, title, errorName='TimeoutError') {
 const {collect}=require('./collector.cjs');let handler;
 const page={
  setDefaultTimeout(){},url:()=>url,title:async()=>title,
  goto:async()=>{await handler({request:()=>({url:()=>url,method:()=>'GET',resourceType:()=>'document',frame:()=>({parentFrame:()=>null})}),continue:async()=>{},abort:async()=>{}});return {status:()=>200};},
  waitForFunction:async()=>{const error=Error('fixture wait timeout');error.name=errorName;throw error;},
  evaluate:async()=>'<html><head><title>'+title+'</title></head><body>Résultats non disponibles</body></html>'
 };
 const chromium={launch:async()=>({newContext:async()=>({route:async(pattern,fn)=>{handler=fn},newPage:async()=>page}),close:async()=>{}})};
 return collect(url,chromium);
}
test('已核Geny赛果页未出现最终结果时仍返回可判阶段的DOM',async()=>{
 const url='https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports';
 const value=await timeoutBrowser(url,"Arrivée et rapports de la course Prix de l’Avenir à Nantes le 2 novembre 2026 | Geny");
 assert.equal(value.navigation_count,1);assert.equal(value.final_url,url);
 assert.match(value.html,/Résultats non disponibles/);
});
test('卡表超时、登录页及其他错误不得当成未公布赛果',async()=>{
 const base='https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/';
 await assert.rejects(timeoutBrowser(base+'partants-pronostics','Partants et pronostics de la course Prix de l’Avenir à Nantes le 2 novembre 2026 | Geny'));
 await assert.rejects(timeoutBrowser(base+'arrivee-rapports','Sign in'));
 await assert.rejects(timeoutBrowser(base+'arrivee-rapports','Arrivée et rapports de la course Prix de l’Avenir à Nantes le 2 novembre 2026 | Geny','NetworkError'));
});

async function navigationBrowser(url, navigations, resourcesPerDocument=0) {
 const {collect}=require('./collector.cjs');let handler;
 const page={setDefaultTimeout(){},url:()=>url,title:async()=> 'Programme | Geny',
  goto:async()=>{
   for(const navigation of navigations) {await handler({
    request:()=>({url:()=>navigation.url||url,method:()=> 'GET',resourceType:()=> 'document',
     frame:()=>({parentFrame:()=>navigation.childFrame?{}:null})}),
    continue:async()=>{},abort:async()=>{}
   });
   for(let i=0;i<resourcesPerDocument;i++) await handler({
    request:()=>({url:()=>new URL('/assets/fixture.js',url).href,method:()=> 'GET',resourceType:()=> 'script'}),
    continue:async()=>{},abort:async()=>{}
   });}
   return {status:()=>200};
  },waitForFunction:async()=>{},evaluate:async()=>'<html><body>Programme</body></html>'};
 const chromium={launch:async()=>({newContext:async()=>({route:async(pattern,fn)=>{handler=fn},newPage:async()=>page}),close:async()=>{}})};
 return collect(url,chromium);
}
test('Geny白名单页面仅允许一次同URL主页面重载并报告两个文档请求',async()=>{
 for(const url of ['https://www.geny.com/programme/2026-11-11',
  'https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/partants-pronostics',
  'https://www.geny.com/course/1695527-2026-11-02-nantes-prix-de-l-avenir/arrivee-rapports']) {
 const result=await navigationBrowser(url,[{},{}]);
 assert.equal(result.navigation_count,2);assert.equal(result.resource_requests,2);
 assert.equal(result.final_url,url);
 }
});
test('目录第三次导航、换URL、子框架及其他页面第二次导航仍拒绝',async()=>{
 const url='https://www.geny.com/programme/2026-11-11';
 for(const navigations of [[{},{},{}],[{},{url:'https://www.geny.com/programme/2026-11-12'}],[{},{childFrame:true}]])
  await assert.rejects(navigationBrowser(url,navigations));
 for(const other of ['https://www.france-galop.com/fr/courses/pattern-listed'])
  await assert.rejects(navigationBrowser(other,[{},{}]));
});

test('同页重载保留每次96资源上限并有界汇总两次请求',async()=>{
 const url='https://www.geny.com/programme/2026-11-11';
 assert.equal((await navigationBrowser(url,[{},{}],60)).resource_requests,122);
 assert.equal((await navigationBrowser(url,[{},{}],95)).resource_requests,192);
 await assert.rejects(navigationBrowser(url,[{}],96));
 await assert.rejects(navigationBrowser(url,[{},{}],96));
});

test('重载后的晚到超限即使abort正常返回也不得交付部分DOM',async()=>{
 const {collect}=require('./collector.cjs');let handler;
 const url='https://www.geny.com/course/1697603-2026-11-11-toulouse-prix-fille-de-l-air/partants-pronostics';
 async function request(type){
  await handler({request:()=>({url:()=>type==='document'?url:'https://www.geny.com/assets/fixture.js',
   method:()=> 'GET',resourceType:()=>type,frame:()=>({parentFrame:()=>null})}),
   continue:async()=>{},abort:async()=>{}});
 }
 const page={setDefaultTimeout(){},url:()=>url,title:async()=> 'Course | Geny',
  goto:async()=>{await request('document');return {status:()=>200};},
  waitForFunction:async()=>{await request('document');for(let i=0;i<96;i++)await request('script');},
  evaluate:async()=>'<html><body><table><tr><td>partial</td></tr></table></body></html>'};
 const chromium={launch:async()=>({newContext:async()=>({route:async(pattern,fn)=>{handler=fn},newPage:async()=>page}),close:async()=>{}})};
 await assert.rejects(collect(url,chromium),/request_limit/);
});
