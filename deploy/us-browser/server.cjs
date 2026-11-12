'use strict';
const http=require('node:http');
const {chromium}=require('playwright');
const {collect}=require('./collector.cjs');
let busy=false;
function reply(res,status,value){res.writeHead(status,{'Content-Type':'application/json; charset=utf-8'});res.end(JSON.stringify(value));}
const server=http.createServer(async(req,res)=>{
 if(req.method==='GET' && req.url==='/healthz')return reply(res,200,{ok:true});
 if(req.method!=='POST' || req.url!=='/fetch')return reply(res,404,{error:'not_found'});
 if(busy)return reply(res,503,{error:'browser_busy'});
 busy=true;
 try {
  let data='';
  for await(const chunk of req){data+=chunk;if(Buffer.byteLength(data)>4096)throw Error('request_limit');}
  const input=JSON.parse(data);
  if(Object.keys(input).join(',')!=='url')throw Error('request_invalid');
  const result=await collect(input.url,chromium);
  reply(res,200,result);
 } catch(e){reply(res,502,{error:/^[a-z_]+(?:_[0-9]+)?$/.test(e.message)?e.message:'browser_collection_failed'});}
 finally{busy=false;}
});
server.requestTimeout=35000;server.headersTimeout=5000;
server.listen(8080,'0.0.0.0');
