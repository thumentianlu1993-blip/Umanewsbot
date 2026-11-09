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
  goto:async()=>{await handler({request:()=>({url:()=>url,method:()=>'GET',resourceType:()=>'document'}),continue:async()=>{},abort:async()=>{throw Error('request_blocked')}});return {status:()=>200};},
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
