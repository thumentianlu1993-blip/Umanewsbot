const {test}=require('node:test');const assert=require('node:assert/strict');
const {validateUrl}=require('./collector.cjs');
test('only observed JRA public race document contracts accepted',()=>{
 for(const url of ['https://www.jra.go.jp/keiba/thisweek/','https://www.jra.go.jp/keiba/race/103/syutsuba.html','https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03tde000505031120261114/49'])assert.doesNotThrow(()=>validateUrl(url));
 for(const url of ['http://www.jra.go.jp/keiba/thisweek/','https://localhost/','https://evil.test/','https://www.jra.go.jp@evil.test/','https://user@www.jra.go.jp/keiba/thisweek/','https://www.jra.go.jp/login/','https://www.jra.go.jp/JRADB/accessT.html?CNAME=wrong','https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03tde000505031120261114/49&CNAME=other'])assert.throws(()=>validateUrl(url));
});
